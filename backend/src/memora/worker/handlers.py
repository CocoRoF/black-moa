"""Job handlers. Each receives (db, payload) inside its own transaction."""
from __future__ import annotations

import contextlib
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import func, select, text

from memora.core.logging import get_logger
from memora.memory.distill import distill_turn, summarize_conversation
from memora.models import (
    Agent,
    Connection,
    Conversation,
    CreditBalance,
    CreditLedger,
    InboxItem,
    Notification,
    Plan,
    User,
)
from memora.services import claude_code as CC
from memora.services import claude_pool as CP
from memora.services import credits as CR
from memora.services import jobs as J
from memora.services import knowledge as K
from memora.services import notifications as NT
from memora.services import settings as S
from memora.services.mailer import send_mail

log = get_logger("memora.worker")
HANDLERS: dict[str, Any] = {}


def handler(kind: str):
    def deco(fn):
        HANDLERS[kind] = fn
        return fn
    return deco


@handler("knowledge.index")
async def knowledge_index(db, payload):
    return await K.index_document(db, uuid.UUID(payload["document_id"]))


@handler("files.ingest")
async def files_ingest(db, payload):
    """plan/55 §3-2: 대화로 들어온 파일을 한 번 읽어 둔다(글·썸네일·그림 설명)."""
    from memora.services import files as FILES
    fid = uuid.UUID(payload["file_id"])
    await FILES.note_attempt(fid)
    return await FILES.ingest(db, fid)


@handler("files.sweep")
async def files_sweep(db, payload):
    """못 읽고 남은 파일을 다시 줄 세우고, 지운 지 30일 지난 파일을 실제로 지운다.

    원장에 옮겨 적기만 하고 읽기 작업이 없는 행(이관), 작업자가 죽어 잃은 작업이 여기서
    다시 잡힌다. 방금 들어온 것은 제 작업이 곧 돌 테니 건드리지 않는다.
    """
    from memora.models import AgentFile
    from memora.services import files as FILES
    cutoff = datetime.now(UTC) - timedelta(minutes=10)
    rows = (await db.execute(select(AgentFile).where(AgentFile.status == "pending", AgentFile.deleted_at.is_(None),
                                                     AgentFile.created_at < cutoff).limit(200))).scalars().all()
    for f in rows:
        if (f.ingest_attempts or 0) >= FILES.INGEST_MAX_ATTEMPTS:
            # 다섯 번 읽어도 안 된 파일은 읽을 수 없는 파일이다. 영원히 다시 줄 세우지 않는다.
            # (기준이 "받은 지 며칠" 이면 옛 파일을 다시 읽히는 순간 시도도 없이 포기한다.)
            f.status, f.error = "unreadable", f.error or "gave_up"
            continue
        await J.enqueue(db, "files.ingest", {"file_id": str(f.id)}, dedupe_key=f"file:{f.id}", priority=6, owner_id=f.owner_id)
    purged = await FILES.purge(db)
    return {"queued": len(rows), "purged": purged}


@handler("memory.distill")
async def memory_distill(db, payload):
    r = await distill_turn(db, uuid.UUID(payload["turn_id"]))
    from memora.models import Turn
    t = await db.get(Turn, uuid.UUID(payload["turn_id"]))
    if t is not None:
        conv = await db.get(Conversation, t.conversation_id)
        if conv is not None and conv.message_count % 8 == 0:
            await summarize_conversation(db, conv.id)
    return r


@handler("integration.sync")
async def integration_sync(db, payload):
    from memora.core.errors import ServiceUnavailable
    from memora.services import connections as CN
    conn = await db.get(Connection, uuid.UUID(payload["connection_id"]))
    if conn is None or conn.status not in ("active", "error"):
        return {"skipped": True}
    try:
        return await CN.sync_all(db, conn)
    except ServiceUnavailable as e:
        # expired/revoked token: keep the status change (expired + error + owner notification) — do NOT raise,
        # a raise would roll the whole job transaction back and leave the connection looking healthy forever.
        return {"error": e.code, "status": conn.status}


@handler("calendar.sync")
async def calendar_sync(db, payload):
    """달력 하나에서 일정을 가져온다 — [연동] 탭의 자동 가져오기와 가져오기를 막 켰을 때 (plan/58)."""
    from memora.core.errors import ServiceUnavailable
    from memora.services import calendar_sources as CS
    try:
        n = await CS.sync_connection(db, uuid.UUID(payload["connection_id"]))
    except ServiceUnavailable as e:
        # 만료·철회된 토큰: 연결의 상태 변경(오류 표시·주인 알림)은 남긴다 — 올려 보내면 되돌려진다.
        return {"error": e.code}
    return {"events": n} if n is not None else {"skipped": True}


@handler("calendar.autosync")
async def calendar_autosync(db, payload):
    """자동으로 가져올 때가 된 달력마다 가져오기를 건다. 달력마다 제 간격(1시간·6시간·하루)이 있다."""
    from memora.services import calendar_sources as CS
    ids = await CS.due(db)
    for cid in ids:
        await J.enqueue(db, "calendar.sync", {"connection_id": str(cid)}, priority=6, dedupe_key=f"calsync:{cid}")
    return {"queued": len(ids)}


@handler("integrations.autosync")
async def integrations_autosync(db, payload):
    """때가 된 메일함·Google 연락처마다 가져오기를 건다 (plan/76)."""
    from memora.services import connections as CN
    ids = await CN.due(db)
    for cid in ids:
        await J.enqueue(db, "integration.sync", {"connection_id": str(cid)}, priority=6, dedupe_key=f"sync:{cid}")
    return {"queued": len(ids)}


@handler("holidays.sync")
async def holidays_sync(db, payload):
    """한국천문연구원 특일 정보에서 올해와 내년을 받아 온다 (plan/60). 꺼져 있거나 키가 없으면 아무것도 하지 않는다."""
    from memora.services import special_days as SD
    return await SD.sync(db, force=bool(payload.get("force")))


@handler("downloads.sync")
async def downloads_sync(db, payload):
    """GitHub 의 앱 릴리스를 읽어 다운로드 센터를 맞춘다 (plan/64). 새 설치본마다 옮기는 작업을 건다."""
    from memora.services import downloads as D
    return await D.sync(db, force=bool(payload.get("force")))


@handler("downloads.mirror")
async def downloads_mirror(db, payload):
    """설치본 하나를 GitHub 에서 받아 제 저장소에 옮긴다. 100MB 가 넘으니 하나씩."""
    from memora.services import downloads as D
    return await D.mirror(db, uuid.UUID(payload["asset_id"]))


@handler("notify.evaluate")
async def notify_evaluate(db, payload):
    owner_id = uuid.UUID(payload["owner_id"])
    event = payload["event"]
    agent_id = uuid.UUID(payload["agent_id"]) if payload.get("agent_id") else None
    data = dict(payload.get("payload") or {})
    if payload.get("inbox_item_id"):
        item = await db.get(InboxItem, uuid.UUID(payload["inbox_item_id"]))
        if item:
            data = {**(item.payload or {}), "inbox_item_id": str(item.id)}
    if agent_id and "agent_name" not in data:
        a = await db.get(Agent, agent_id)
        if a:
            data["agent_name"] = a.name
    n = await NT.evaluate(db, owner_id=owner_id, event=event, payload=data, urgency=payload.get("urgency"), agent_id=agent_id)
    return {"notifications": n}


@handler("notify.send")
async def notify_send(db, payload):
    from memora.db.session import session_scope
    from memora.models import NotificationChannel
    nid = uuid.UUID(payload["notification_id"])
    note = await db.get(Notification, nid)
    if note is None or note.status in ("sent", "failed", "skipped"):
        return {"skipped": True}
    note.attempts += 1
    try:
        await NT.deliver(db, note)
    except Exception as e:  # noqa: BLE001
        err = str(e)[:500]
        attempts = note.attempts
        channel_id = note.channel_id
        await db.rollback()
        # record the failure durably (the job transaction is rolled back by the runner on raise)
        async with session_scope() as db2:
            n2 = await db2.get(Notification, nid)
            if n2 is not None:
                n2.attempts = attempts
                n2.error = err
                n2.status = "failed" if attempts >= 3 else "pending"
            if channel_id:
                ch = await db2.get(NotificationChannel, channel_id)
                if ch:
                    ch.last_error = err[:300]
        raise
    return {"sent": True}


@handler("mail.send")
async def mail_send(db, payload):
    await send_mail(db, to=payload["to"], subject=payload["subject"], text=payload["text"], html=payload.get("html"))
    return {"sent": True}


@handler("admin.notify")
async def admin_notify(db, payload):
    admins = (await db.execute(select(User).where(User.role == "admin", User.status == "active"))).scalars().all()
    from memora.services import emails as E
    subject, text, html = E.admin_alert(subject=payload["subject"], text=payload["text"])
    for a in admins:
        try:
            await send_mail(db, to=a.email, subject=subject, text=text, html=html)
        except Exception as e:  # noqa: BLE001
            log.warning("admin mail failed", err=str(e)[:200])
    return {"admins": len(admins)}


@handler("account.bootstrap")
async def account_bootstrap(db, payload):
    user = await db.get(User, uuid.UUID(payload["user_id"]))
    if user:
        await NT.ensure_default_rules(db, user)
    return {"ok": True}


def rollover_plan(balance: float, monthly: int, protected: float = 0.0) -> tuple[float, float]:
    """plan/15: unused balance carried into the new cycle is capped at 2 × monthly grant; the excess expires,
    then the monthly grant is added. Returns (expire_amount, grant_amount). Negative balances (debt) carry over.

    ``protected``: 돈을 내고 받은 크레딧(결제·관리자 충전)은 5년 동안 이 상한으로 사라지지 않는다 (plan/73, 이용약관
    유료서비스 조항). 무료로 받은 것만 상한을 넘으면 사라진다."""
    cap = monthly * 2 + max(0.0, protected)
    expire = max(0.0, balance - cap) if monthly > 0 else 0.0
    return expire, float(monthly)


PAID_KINDS = ("purchase", "grant")
PAID_KEEP_DAYS = 365 * 5


async def paid_credits(db, owner_id, now: datetime) -> float:
    """최근 5년 동안 돈을 내고 받은 크레딧의 합 — 결제(purchase)와 관리자 충전(grant, 충전 요청을 받아 넣은 것)."""
    q = select(func.coalesce(func.sum(CreditLedger.delta), 0)).where(
        CreditLedger.owner_id == owner_id, CreditLedger.kind.in_(PAID_KINDS), CreditLedger.delta > 0,
        CreditLedger.created_at >= now - timedelta(days=PAID_KEEP_DAYS))
    return float((await db.execute(q)).scalar_one())


async def grant_monthly_for_user(db, u: User, plan: Plan, now: datetime) -> bool:
    anchor = u.plan_cycle_anchor or u.created_at
    if (now - anchor).days < 30:
        return False
    bal = float(await CR.balance(db, u.id))
    expire, grant = rollover_plan(bal, plan.monthly_credits, await paid_credits(db, u.id, now))
    if expire > 0:
        # Rollover expiry is a policy debit on an already-closed cycle; refusing it
        # because one turn holds credits would abort the grant for every remaining
        # user in this job.
        await CR.apply(db, u.id, -expire, "expire", note="rollover cap", allow_reserved=True)
    if grant > 0:
        await CR.apply(db, u.id, grant, "monthly_grant", note=f"{plan.code} monthly")
    u.plan_cycle_anchor = anchor + timedelta(days=30 * ((now - anchor).days // 30))
    row = await db.get(CreditBalance, u.id)
    if row:
        row.low_notified_at = None
    return True


@handler("credits.monthly_grant")
async def monthly_grant(db, payload):
    now = datetime.now(UTC)
    users = (await db.execute(select(User).where(User.status == "active"))).scalars().all()
    n = 0
    for u in users:
        plan = await db.get(Plan, u.plan_id) if u.plan_id else None
        if plan is None:
            continue
        if await grant_monthly_for_user(db, u, plan, now):
            n += 1
    return {"granted": n}


@handler("credits.low_watch")
async def low_watch(db, payload):
    ratio = float(await S.get(db, "credits.low_watermark_ratio"))
    rows = (await db.execute(select(CreditBalance))).scalars().all()
    n = 0
    for b in rows:
        u = await db.get(User, b.owner_id)
        if u is None:
            continue
        plan = await db.get(Plan, u.plan_id) if u.plan_id else None
        wm = (plan.monthly_credits if plan else 300) * ratio
        if float(b.balance) <= wm and b.low_notified_at is None:
            await NT.evaluate(db, owner_id=u.id, event="credits_low", payload={"text": f"남은 크레딧 {float(b.balance):.1f}"})
            b.low_notified_at = datetime.now(UTC)
            n += 1
        elif float(b.balance) > wm * 2:
            b.low_notified_at = None
    return {"notified": n}


async def build_digest(db, u: User, *, since: datetime | None = None) -> dict | None:
    """What the morning mail says for one person, or None when nothing happened."""
    from zoneinfo import ZoneInfo

    from memora.services.notifications import KIND_LABEL

    since = since or datetime.now(UTC) - timedelta(hours=24)
    rows = (await db.execute(text("""SELECT kind, count(*) FROM inbox_items WHERE owner_id=:o AND created_at >= :s GROUP BY kind"""), {"o": u.id, "s": since})).all()
    convs = (await db.execute(text("""SELECT count(*) FROM conversations WHERE owner_id=:o AND audience='visitor' AND created_at >= :s"""), {"o": u.id, "s": since})).scalar()
    used = (await db.execute(text("""SELECT coalesce(sum(credits),0) FROM usage_events WHERE owner_id=:o AND created_at >= :s"""), {"o": u.id, "s": since})).scalar()
    props = (await db.execute(text("""SELECT count(*) FROM network_proposals WHERE owner_id=:o AND status='pending'"""), {"o": u.id})).scalar()
    if not rows and not convs and not props:
        return None
    from memora.services import inbox as I

    hidden = await I.hidden_kinds(db)
    counts = {k: int(c) for k, c in rows if k not in hidden}
    if not counts and not convs and not props:
        return None
    items: list[dict] = []
    if convs:
        items.append({"label": "새 방문자 대화", "value": f"{int(convs)}건"})
    for kind in KIND_LABEL:
        if counts.get(kind):
            items.append({"label": KIND_LABEL[kind], "value": f"{counts[kind]}건"})
    for kind, c in counts.items():
        if kind not in KIND_LABEL:
            items.append({"label": kind, "value": f"{c}건"})
    if float(used or 0) > 0:
        items.append({"label": "쓴 크레딧", "value": f"{float(used or 0):,.1f}"})
    if props:
        items.append({"label": "승인을 기다리는 인맥 제안", "value": f"{int(props)}건"})
    try:
        local = datetime.now(ZoneInfo(u.timezone or "Asia/Seoul"))
    except Exception:  # noqa: BLE001
        local = datetime.now(ZoneInfo("Asia/Seoul"))
    date = f"{local.month}월 {local.day}일 ({'월화수목금토일'[local.weekday()]})"
    return {"text": "\n".join(f"{i['label']} {i['value']}" for i in items), "items": items,
            "name": u.nickname or u.display_name or "", "date": date, "agent_name": "Memora"}


@handler("digest.daily")
async def digest_daily(db, payload):
    from zoneinfo import ZoneInfo
    users = (await db.execute(select(User).where(User.status == "active"))).scalars().all()
    n = 0
    for u in users:
        try:
            local = datetime.now(ZoneInfo(u.timezone or "Asia/Seoul"))
        except Exception:
            local = datetime.now(ZoneInfo("Asia/Seoul"))
        if local.hour != 9:
            continue
        # once per local day (the schedule fires twice inside the 09:xx hour)
        day_start = local.replace(hour=0, minute=0, second=0, microsecond=0).astimezone(UTC)
        already = (await db.execute(text("""SELECT 1 FROM notifications WHERE owner_id=:o AND event='digest_daily' AND created_at >= :d LIMIT 1"""),
                                    {"o": u.id, "d": day_start})).first()
        if already:
            continue
        # One person's summary failing must not take everybody after them with it: this
        # runs once a day, and the rest of the list would silently get no mail at all.
        try:
            digest = await build_digest(db, u)
            if digest is None:
                continue
            await NT.evaluate(db, owner_id=u.id, event="digest_daily", payload=digest)
        except Exception as e:  # noqa: BLE001
            log.warning("digest failed for one owner", owner=str(u.id), err=str(e)[:200])
            continue
        n += 1
    return {"digests": n}


@handler("relationship.tick")
async def relationship_tick(db, payload):
    """plan/37: every few minutes, queue the messages secretaries should send first."""
    from memora.services import relationship as REL

    return await REL.tick(db)


@handler("relationship.proactive")
async def relationship_proactive(db, payload):
    from memora.services import relationship as REL

    return await REL.run_proactive(db, agent_id=uuid.UUID(payload["agent_id"]), user_id=uuid.UUID(payload["user_id"]),
                                   kind=payload.get("kind"), force=bool(payload.get("force")),
                                   rule=str(payload.get("rule") or ""), tone=str(payload.get("tone") or ""))


@handler("relay.hop")
async def relay_hop(db, payload):
    """plan/38: ask the API process — where turns run — to answer the pending relay message."""
    import httpx

    from memora.config import get_settings
    from memora.services import relay as RELAY

    url = get_settings().internal_api_url.rstrip("/") + "/internal/relay/hop"
    async with httpx.AsyncClient(timeout=30) as c:
        r = await c.post(url, json={"relay_id": str(payload["relay_id"])}, headers={"X-Memora-Internal": RELAY.internal_token()})
    if r.status_code >= 500:
        raise RuntimeError(f"relay hop {r.status_code}: {r.text[:200]}")
    try:
        return r.json()
    except Exception:  # noqa: BLE001
        return {"status": r.status_code}


@handler("photos.catchup")
async def photos_catchup(db, payload):
    """아직 안 본 사진을 뒤늦게 채운다 (plan/45 §2).

    규칙이 "글이 없는 글만" 이던 동안 올라온 글들은 사진을 못 본 채로 남아 있다.
    새 글만 고치면 그 글들은 영영 빈 종이다.

    한 번에 조금씩만 집는다. 한 장 볼 때마다 턴이 하나 돌고 크레딧이 나가므로,
    한꺼번에 훑으면 밀린 글 수만큼 청구서가 한 번에 생긴다.
    """
    from sqlalchemy import func

    from memora.models.blog import BlogPost
    from memora.services import jobs as J

    limit = int((payload or {}).get("limit") or 3)
    rows = (await db.execute(
        select(BlogPost)
        .where(BlogPost.status == "published",
               func.jsonb_array_length(func.coalesce(BlogPost.images, text("'[]'::jsonb"))) > 0,
               ~BlogPost.meta.has_key("seen"))
        .order_by(BlogPost.created_at.desc())
        .limit(limit))).scalars().all()
    for post in rows:
        await J.enqueue(db, "post.describe_photos", {"post_id": str(post.id)},
                        dedupe_key=f"seen:{post.id}", priority=7, owner_id=post.owner_id)
    await db.commit()
    return {"queued": len(rows)}


@handler("post.describe_photos")
async def post_describe_photos(db, payload):
    """plan/45 §2: 사진이 붙은 글은 비서가 한 번 들여다본다. 턴은 API 쪽에서 돈다."""
    import httpx

    from memora.config import get_settings
    from memora.services import relay as RELAY

    url = get_settings().internal_api_url.rstrip("/") + "/internal/relay/describe-photos"
    async with httpx.AsyncClient(timeout=180) as c:
        r = await c.post(url, json={"post_id": str(payload["post_id"])},
                         headers={"X-Memora-Internal": RELAY.internal_token()})
    if r.status_code >= 500:
        raise RuntimeError(f"describe {r.status_code}: {r.text[:200]}")
    try:
        return r.json()
    except Exception:  # noqa: BLE001
        return {"status": r.status_code}


@handler("post.secretary_reply")
async def post_secretary_reply(db, payload):
    """plan/43 §6: ask the API process to let a named secretary answer under the post."""
    import httpx

    from memora.config import get_settings
    from memora.services import relay as RELAY

    url = get_settings().internal_api_url.rstrip("/") + "/internal/relay/post-reply"
    async with httpx.AsyncClient(timeout=180) as c:
        r = await c.post(url, json={"post_id": str(payload["post_id"]), "agent_id": str(payload["agent_id"])},
                         headers={"X-Memora-Internal": RELAY.internal_token()})
    if r.status_code >= 500:
        raise RuntimeError(f"post reply {r.status_code}: {r.text[:200]}")
    try:
        return r.json()
    except Exception:  # noqa: BLE001
        return {"status": r.status_code}


@handler("relay.sweep")
async def relay_sweep(db, payload):
    from memora.services import relay as RELAY

    return await RELAY.sweep(db)


@handler("retention.sweep")
async def retention_sweep(db, payload):
    """Full visitor-relationship retention boundary (plan/19)."""
    from memora.services.procstats import sweep as _proc_sweep
    from memora.services.retention import retention_sweep as _sweep
    from memora.services.traffic import sweep as _traffic_sweep

    out = await _sweep(db, payload)
    # The traffic record is a working set, not an archive (plan/40).
    with contextlib.suppress(Exception):
        out = {**(out if isinstance(out, dict) else {"result": out}), "api_requests_pruned": await _traffic_sweep(db)}
    # …and a process that is never coming back — a renamed container, a scaled-down
    # replica — should not sit on the diagnostics screen for ever (plan/32 §6).
    with contextlib.suppress(Exception):
        out = {**out, "process_rows_pruned": await _proc_sweep(db)}
    return out


@handler("retention.purge_memory")
async def retention_purge_memory(db, payload):
    from memora.services.retention import retention_purge_memory as _purge

    return await _purge(db, payload)


@handler("credits.reservation_reaper")
async def reservation_reaper(db, payload):
    """Heal credit holds orphaned by a hard-killed API process, then trim audit rows."""
    minutes = int(payload.get("minutes") or CR.RESERVATION_TTL_MINUTES)
    released = await CR.expire_stale_reservations(db, minutes=minutes)
    swept = await CR.sweep_reservations(db, days=30)
    if released:
        log.warning("released stale credit reservations", count=released)
    return {"released": released, "swept": swept}


@handler("claude_creds.backup")
async def claude_backup(db, payload):
    # The CLI refreshes each account's access token in its own file; this walks the pool
    # back into the database (and writes a missing file out again after a volume swap).
    return {"backed_up": await CC.backup_credentials(db), "pool": await CP.sync_all(db)}


@handler("ops.watch")
async def ops_watch(db, payload):
    """Tell the administrator about things that will actually break.

    Two bugs made this the noisiest thing in the system. It watched `expires_at`, which is
    the access token the CLI rotates roughly every 8 hours — a value that is *supposed* to
    pass — and `dedupe_key` only blocks jobs that are queued or running, so a finished alert
    never stopped the next tick five minutes later. 170 identical emails.
    """
    import hashlib
    import shutil
    import time

    from memora.config import get_settings
    st = await CC.status(db)
    alerts = []
    pool = await CP.overview(db)
    if pool["active"]:
        # With a pool serving, the legacy credential file is not what answers turns —
        # what matters is how many members are still in rotation.
        counts = pool["counts"]
        if counts["eligible"] == 0:
            alerts.append("Claude Code 계정 풀에 사용 가능한 계정이 없습니다. 대화가 동작하지 않습니다.")
        else:
            # "at_capacity" is a busy account, not a broken one — alerting on it would page
            # the operator for the pool doing exactly its job.
            down = [a["label"] for a in pool["accounts"]
                    if a["enabled"] and a["ineligible_reason"] not in (None, "at_capacity")]
            if down:
                alerts.append(f"Claude Code 계정 {len(down)}개가 로테이션에서 빠졌습니다: {', '.join(down[:5])}")
        for a in pool["accounts"]:
            if a["enabled"] and a["session_expires_at"]:
                dt = datetime.fromisoformat(a["session_expires_at"])
                if dt < datetime.now(UTC) + timedelta(days=3):
                    alerts.append(f"Claude Code 계정 '{a['label']}' 로그인이 {dt:%Y-%m-%d %H:%M} 에 만료됩니다.")
    elif st.get("credentials_present") and st.get("auth_mode") == "oauth":
        if st.get("expired"):
            alerts.append("Claude Code 로그인이 만료됐습니다. 관리자 콘솔 → 프로바이더에서 다시 로그인해 주세요.")
        else:
            sess = st.get("session_expires_at")
            if sess:
                dt = datetime.fromisoformat(sess)
                # The login's own lifetime — about a month — is worth three days' notice.
                if dt < datetime.now(UTC) + timedelta(days=3):
                    alerts.append(f"Claude Code 로그인이 {dt:%Y-%m-%d %H:%M} 에 만료됩니다. 미리 다시 로그인해 주세요.")
    elif not st.get("credentials_present") and not st.get("has_anthropic_key"):
        alerts.append("Claude Code 자격증명이 없습니다. 대화가 동작하지 않습니다.")

    u = shutil.disk_usage(get_settings().data_dir)
    if u.used / u.total > 0.85:
        alerts.append(f"디스크 사용률 {u.used / u.total:.0%}")

    if not alerts:
        await S.put(db, "ops.last_alert", {})      # recovered: the next problem is news again
        return {"alerts": []}

    digest = hashlib.sha256("\n".join(alerts).encode()).hexdigest()[:16]
    last = await S.get(db, "ops.last_alert") or {}
    unchanged = last.get("digest") == digest
    recent = time.time() - float(last.get("at") or 0) < 86400
    if unchanged and recent:
        return {"alerts": alerts, "suppressed": True}
    await J.enqueue(db, "admin.notify", {"subject": "[Memora] 운영 경고", "text": "\n".join(alerts)},
                    dedupe_key=f"ops:{digest}")
    await S.put(db, "ops.last_alert", {"digest": digest, "at": time.time()})
    return {"alerts": alerts}


@handler("stats.refresh")
async def stats_refresh(db, payload):
    from datetime import timedelta

    from sqlalchemy import func, select

    from memora.models import Conversation, InboxItem, Turn
    since = datetime.now(UTC) - timedelta(days=7)
    agents = (await db.execute(select(Agent).where(Agent.status != "archived"))).scalars().all()
    for a in agents:
        t = (await db.execute(select(func.count(Turn.id), func.coalesce(func.sum(Turn.credits), 0), func.avg(Turn.ttft_ms))
                              .where(Turn.agent_id == a.id, Turn.started_at >= since))).one()
        vc = int((await db.execute(select(func.count(Conversation.id)).where(Conversation.agent_id == a.id, Conversation.audience == "visitor",
                                                                            Conversation.created_at >= since, Conversation.simulated.is_(False)))).scalar_one())
        total = int((await db.execute(select(func.count(Conversation.id)).where(Conversation.agent_id == a.id, Conversation.simulated.is_(False)))).scalar_one())
        unans = int((await db.execute(select(func.count(InboxItem.id)).where(InboxItem.agent_id == a.id, InboxItem.kind == "question_unanswered",
                                                                              InboxItem.status == "new"))).scalar_one())
        a.stats = {"conversations_total": total, "visitor_conversations_7d": vc, "turns_7d": int(t[0] or 0), "credits_7d": float(t[1] or 0),
                   "avg_ttft_ms": int(t[2] or 0), "unanswered_questions": unans, "refreshed_at": datetime.now(UTC).isoformat()}
    return {"agents": len(agents)}


@handler("community.rank")
async def community_rank(db, payload):
    """Recompute what the feed calls hot.

    Ranking has to be a background write: sorting the whole table per request is fine with
    a hundred posts and a table scan with a hundred thousand.
    """
    from memora.services import community as C
    n = await C.recompute_hot(db)
    return {"reranked": n}


@handler("crawl.companies")
async def crawl_companies(db, payload):
    """Collect company information from one national or exchange source (plan/33).

    In the `crawl` class, which plan/32 §4 reserved for exactly this: it waits on someone
    else's server, so it gets its own worker-slot ceiling and its own thread pool and
    cannot slow a chat turn or a document import down by being slow itself.
    """
    from memora.services.companies.collect import run

    return await run(db, payload.get("source") or "krx", payload)


@handler("companies.rank")
async def companies_rank(db, payload):
    """What "popular" means in the directory, recomputed for every company (plan/40)."""
    from memora.services.companies import switch as CO
    from memora.services.companies.domains import sync_from_homepages
    from memora.services.companies.reviews import rank_all

    # 기업 기능이 꺼져 있으면 아무도 보지 않는 순위다 (plan/71).
    if not await CO.enabled(db):
        return {"skipped": "companies are off"}
    out = await rank_all(db)
    out["domains"] = await sync_from_homepages(db)
    return out


@handler("companies.refresh")
async def companies_refresh(db, payload):
    """The daily pass over every source that can run (plan/33).

    "Batch" has to mean a schedule, not "when an administrator remembers". Each source is
    queued as its own job rather than run here, so one slow or rate-limited source cannot
    stop the others and each gets its own entry in the run history.
    """
    from memora.services import settings as S
    from memora.services.companies.collect import SOURCES

    if not await S.get(db, "companies.auto_collect"):
        return {"skipped": "auto_collect is off"}
    # 기업 기능이 꺼져 있으면 모으지도 않는다. 관리자의 [지금 수집] 은 그대로 된다 (plan/71).
    if not await S.get(db, "companies.enabled"):
        return {"skipped": "companies are off"}

    from memora.services.companies.collect import ran_recently

    queued, skipped = [], []
    for name, spec in SOURCES.items():
        setting = spec["needs_key"]
        if setting and not await S.get(db, setting):
            continue                      # no key: nothing to try, and nothing to report
        # Once a day means once a day: a pass that already succeeded in the last twenty
        # hours is not run again because the worker happened to restart.
        if not payload.get("force") and await ran_recently(db, name, hours=20):
            skipped.append(name)
            continue
        await J.enqueue(db, "crawl.companies", {"source": name},
                        dedupe_key=f"companies:{name}:{datetime.now(UTC):%Y%m%d}")
        queued.append(name)
    return {"queued": queued, "skipped": skipped}
