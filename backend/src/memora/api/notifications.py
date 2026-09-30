from __future__ import annotations

import asyncio
import json
import secrets
import uuid

from fastapi import APIRouter, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy import select

from memora.core.deps import DB, CurrentUser, release_db
from memora.core.errors import Forbidden, NotFound, ValidationFailed
from memora.core.ratelimit import limiter
from memora.models import Agent, Notification, NotificationChannel, NotificationRule, User
from memora.services import notifications as NT
from memora.services import settings as S

router = APIRouter(prefix="/api/notifications", tags=["notifications"])

#: 인증 코드를 보내는 일에만 둔다. 계정 메일 인증과 같은 간격이고, 이것이 없으면 코드
#: 메일 자체가 남에게 보내는 한 통이 된다.
CODES_PER_10MIN = 3
_telegram_codes: dict[str, tuple[uuid.UUID, float]] = {}


def ch_out(c: NotificationChannel) -> dict:
    return {"id": str(c.id), "kind": c.kind, "label": c.label, "config": c.config_public, "enabled": c.enabled,
            "verified_at": c.verified_at.isoformat() if c.verified_at else None, "last_error": c.last_error, "created_at": c.created_at.isoformat()}


def rule_out(r: NotificationRule) -> dict:
    return {"id": str(r.id), "event": r.event, "agent_id": str(r.agent_id) if r.agent_id else None, "channel_ids": [str(x) for x in r.channel_ids or []],
            "enabled": r.enabled, "quiet_hours": r.quiet_hours, "min_urgency": r.min_urgency}


async def _owned_channel_ids(db, owner_id: uuid.UUID, raw: list[str]) -> list[uuid.UUID]:
    try:
        ids = list(dict.fromkeys(uuid.UUID(x) for x in raw))
    except (ValueError, TypeError) as e:
        raise ValidationFailed("channel_ids must contain UUIDs", code="invalid_channel_id") from e
    if not ids:
        return []
    owned = set((await db.execute(select(NotificationChannel.id).where(NotificationChannel.owner_id == owner_id,
                                                                      NotificationChannel.id.in_(ids)))).scalars().all())
    if owned != set(ids):
        # Fail closed without revealing whether a foreign UUID exists.
        raise NotFound("notification channel not found", code="channel_not_found")
    return ids


async def _owned_agent_id(db, owner_id: uuid.UUID, raw: str | None) -> uuid.UUID | None:
    if not raw:
        return None
    try:
        aid = uuid.UUID(raw)
    except ValueError as e:
        raise ValidationFailed("agent_id must be a UUID", code="invalid_agent_id") from e
    a = await db.get(Agent, aid)
    if a is None or a.owner_id != owner_id:
        raise NotFound("agent not found", code="agent_not_found")
    return aid


@router.get("/channels")
async def channels(user: CurrentUser, db: DB):
    await NT.ensure_default_rules(db, user)
    await db.commit()
    rows = (await db.execute(select(NotificationChannel).where(NotificationChannel.owner_id == user.id).order_by(NotificationChannel.created_at))).scalars().all()
    from memora.services.companies import switch as CO

    # 기업 기능이 꺼져 있으면 관심 기업 소식은 고를 것이 아니다 (plan/71).
    events = list(NT.EVENTS) if await CO.enabled(db) else [e for e in NT.EVENTS if e != "company_update"]
    return {"items": [ch_out(c) for c in rows], "events": events, "kinds": list(NT.KINDS),
            "telegram_bot": await S.get(db, "telegram.bot_username")}


class ChannelIn(BaseModel):
    kind: str
    config: dict = {}
    label: str = ""


@router.post("/channels", status_code=201)
async def create_channel(body: ChannelIn, user: CurrentUser, db: DB):
    c = await NT.create_channel(db, user, kind=body.kind, config=body.config, label=body.label)
    # 메일 채널은 만들자마자 그 주소로 코드가 간다. 한 걸음 덜 누르게 하려는 것이지,
    # 코드를 건너뛰는 것이 아니다. 메일이 안 나가도 채널은 만들어지고 [코드 다시 받기]가
    # 남는다: 여기서 실패를 던지면 방금 적은 주소를 다시 적게 된다.
    if c.kind == "email" and c.verified_at is None:
        limiter.check(f"notif:code:{user.id}", CODES_PER_10MIN, 600)
        try:
            await NT.send_code(db, c, user)
        except Exception:  # noqa: BLE001
            pass
    await db.commit()
    return ch_out(c)


class ChannelPatch(BaseModel):
    enabled: bool | None = None
    label: str | None = None


@router.patch("/channels/{ch_id}")
async def patch_channel(ch_id: uuid.UUID, body: ChannelPatch, user: CurrentUser, db: DB):
    c = await NT.get_channel(db, user.id, ch_id)
    if body.enabled is not None:
        c.enabled = body.enabled
    if body.label is not None:
        c.label = body.label[:80]
    await db.commit()
    return ch_out(c)


@router.delete("/channels/{ch_id}")
async def delete_channel(ch_id: uuid.UUID, user: CurrentUser, db: DB):
    c = await NT.get_channel(db, user.id, ch_id)
    await db.delete(c)
    await db.commit()
    return {"ok": True}


class CodeIn(BaseModel):
    code: str = ""


@router.post("/channels/{ch_id}/verify/send")
async def send_channel_code(ch_id: uuid.UUID, user: CurrentUser, db: DB):
    """이 주소가 당신 것인지 묻는 코드를 보낸다 (메일 채널)."""
    limiter.check(f"notif:code:{user.id}", CODES_PER_10MIN, 600)
    c = await NT.get_channel(db, user.id, ch_id)
    if c.kind != "email":
        raise ValidationFailed("메일 채널만 코드로 인증해요.", code="not_an_email_channel")
    try:
        await NT.send_code(db, c, user)
    except TimeoutError as e:
        raise ValidationFailed("인증 메일을 보내지 못했어요. 잠시 후 다시 시도해 주세요.", code="mail_send_failed") from e
    await db.commit()
    return ch_out(c)


@router.post("/channels/{ch_id}/verify")
async def verify_channel(ch_id: uuid.UUID, body: CodeIn, user: CurrentUser, db: DB):
    c = await NT.get_channel(db, user.id, ch_id)
    await NT.confirm_code(db, c, body.code)
    await db.commit()
    return ch_out(c)


@router.post("/channels/{ch_id}/test")
async def test_channel(ch_id: uuid.UUID, user: CurrentUser, db: DB):
    c = await NT.get_channel(db, user.id, ch_id)
    # 거절은 발송 실패가 아니다. 아래 try 는 "보내 봤더니 안 닿더라"를 담는 자리라서,
    # 여기서 걸러야 화면이 둘을 구별할 수 있다.
    if c.kind == "email" and c.verified_at is None:
        raise ValidationFailed("먼저 이 주소를 인증해 주세요.", code="channel_unverified")
    try:
        await NT.test_channel(db, c)
    except Exception as e:  # noqa: BLE001
        c.last_error = str(e)[:500]
        await db.commit()
        return {"ok": False, "error": str(e)[:300]}
    await db.commit()
    return {"ok": True}


@router.get("/rules")
async def rules(user: CurrentUser, db: DB):
    await NT.ensure_default_rules(db, user)
    await db.commit()
    rows = (await db.execute(select(NotificationRule).where(NotificationRule.owner_id == user.id))).scalars().all()
    return {"items": [rule_out(r) for r in rows]}


class RuleIn(BaseModel):
    event: str
    channel_ids: list[str] = []
    enabled: bool = True
    quiet_hours: dict = {}
    min_urgency: int = 0
    agent_id: str | None = None


@router.post("/rules", status_code=201)
async def create_rule(body: RuleIn, user: CurrentUser, db: DB):
    if body.event not in NT.EVENTS:
        raise ValidationFailed("bad event")
    channels = await _owned_channel_ids(db, user.id, body.channel_ids)
    agent_id = await _owned_agent_id(db, user.id, body.agent_id)
    r = NotificationRule(owner_id=user.id, event=body.event, channel_ids=channels, enabled=body.enabled,
                         quiet_hours=body.quiet_hours, min_urgency=max(0, min(3, body.min_urgency)), agent_id=agent_id)
    db.add(r)
    await db.commit()
    return rule_out(r)


@router.patch("/rules/{rule_id}")
async def patch_rule(rule_id: uuid.UUID, body: RuleIn, user: CurrentUser, db: DB):
    r = await db.get(NotificationRule, rule_id)
    if r is None or r.owner_id != user.id:
        raise NotFound("rule not found")
    if body.event not in NT.EVENTS:
        raise ValidationFailed("bad event")
    r.event = body.event
    r.channel_ids = await _owned_channel_ids(db, user.id, body.channel_ids)
    r.agent_id = await _owned_agent_id(db, user.id, body.agent_id)
    r.enabled, r.quiet_hours, r.min_urgency = body.enabled, body.quiet_hours, max(0, min(3, body.min_urgency))
    await db.commit()
    return rule_out(r)


@router.delete("/rules/{rule_id}")
async def delete_rule(rule_id: uuid.UUID, user: CurrentUser, db: DB):
    r = await db.get(NotificationRule, rule_id)
    if r is None or r.owner_id != user.id:
        raise NotFound("rule not found")
    await db.delete(r)
    await db.commit()
    return {"ok": True}


@router.get("/log")
async def log(user: CurrentUser, db: DB, limit: int = 50):
    rows = (await db.execute(select(Notification).where(Notification.owner_id == user.id).order_by(Notification.created_at.desc()).limit(min(limit, 200)))).scalars().all()
    return {"items": [{"id": str(n.id), "event": n.event, "status": n.status, "error": n.error, "channel_id": str(n.channel_id) if n.channel_id else None,
                       "created_at": n.created_at.isoformat(), "sent_at": n.sent_at.isoformat() if n.sent_at else None} for n in rows]}


@router.post("/telegram/link")
async def telegram_link(user: CurrentUser, db: DB):
    import time
    code = secrets.token_hex(3)
    _telegram_codes[code] = (user.id, time.time() + 900)
    bot = await S.get(db, "telegram.bot_username")
    return {"code": code, "bot_username": bot, "instructions": f"텔레그램에서 @{bot} 에게 /start {code} 를 보내세요." if bot else "관리자가 텔레그램 봇을 설정하지 않았어요."}


@router.post("/telegram/webhook")
async def telegram_webhook(request: Request, db: DB):
    import time

    from memora.core.security import constant_eq
    secret = request.headers.get("x-telegram-bot-api-secret-token", "")
    bot_token = await S.get(db, "telegram.bot_token")
    if not bot_token or not secret or not constant_eq(secret, NT.telegram_webhook_secret(bot_token)):
        raise Forbidden("bad secret")
    upd = await request.json()
    msg = (upd.get("message") or {})
    text = (msg.get("text") or "").strip()
    chat_id = (msg.get("chat") or {}).get("id")
    if text.startswith("/start") and chat_id:
        code = text.split(" ", 1)[1].strip() if " " in text else ""
        entry = _telegram_codes.pop(code, None)
        if entry and entry[1] > time.time():
            user = await db.get(User, entry[0])
            if user:
                await NT.create_channel(db, user, kind="telegram", config={"chat_id": chat_id}, label="텔레그램")
                await db.commit()
                await NT.send_via(db, "telegram", {"chat_id": chat_id}, subject="", text="Memora 알림이 연결됐어요 ✅", html="", payload={})
    return {"ok": True}


@router.get("/unsubscribe")
async def unsubscribe(token: str, db: DB):
    from memora.core.security import verify_state
    st = verify_state(token)
    if st.get("kind") != "unsubscribe" or not st.get("ch"):
        raise Forbidden("bad token")
    ch = await db.get(NotificationChannel, uuid.UUID(st["ch"]))
    if ch:
        ch.enabled = False
        await db.commit()
    return {"ok": True, "disabled": bool(ch)}


@router.get("/stream")
async def notifications_stream(user: CurrentUser, request: Request):
    """Live notifications for this account.

    SSE rather than a websocket: the traffic is one-way and it survives proxies that would
    need extra configuration for an upgrade. Anything missed here is still in /api/inbox —
    this only decides whether the badge moves now or on the next poll.
    """
    from memora.core import bus

    async def gen():
        # A tab left open is a wait with no end; the connection goes back first.
        await release_db(request)
        async with bus.subscribe(user.id) as q:
            yield "retry: 3000\n\n"
            while True:
                if await request.is_disconnected():
                    return
                try:
                    msg = await asyncio.wait_for(q.get(), timeout=25)
                except TimeoutError:
                    yield ": keepalive\n\n"      # proxies drop a stream that goes quiet
                    continue
                yield f"event: {msg.get('kind', 'event')}\ndata: {json.dumps(msg.get('data') or {}, ensure_ascii=False)}\n\n"

    return StreamingResponse(gen(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache, no-transform", "X-Accel-Buffering": "no",
                                      "Connection": "keep-alive"})
