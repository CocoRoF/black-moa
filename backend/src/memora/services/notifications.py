"""Notification channels + rules + delivery (plan/16)."""
from __future__ import annotations

import asyncio
import hashlib
import json
import secrets
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from memora.config import get_settings
from memora.core import pools
from memora.core.errors import NotFound, ValidationFailed
from memora.core.security import decrypt, encrypt, hmac_signature, sign_state
from memora.models import Notification, NotificationChannel, NotificationRule, User
from memora.providers.http import request
from memora.services import jobs as J
from memora.services import settings as S
from memora.services.mailer import send_mail
from memora.services.safe_http import check_url, safe_request

BRAND_NAME = "Memora"

EVENTS = ("visitor_new_conversation", "visitor_message", "meeting_request", "contact_share", "question_unanswered",
          "credits_low", "integration_error", "agent_model_fallback", "digest_daily", "secretary_message",
          "relay_result", "relay_visit", "company_update", "network_link")
URGENCY = {"visitor_new_conversation": 1, "visitor_message": 3, "meeting_request": 3, "contact_share": 2,
           "question_unanswered": 1, "credits_low": 2, "integration_error": 2, "agent_model_fallback": 2, "digest_daily": 0,
           "secretary_message": 1, "relay_result": 1, "relay_visit": 1, "network_link": 2}
KINDS = ("email", "webhook", "telegram", "slack", "discord", "kakao")
DEFAULT_RULE_EVENTS = ("visitor_message", "meeting_request", "contact_share", "credits_low", "integration_error", "digest_daily",
                       "secretary_message", "relay_result", "relay_visit", "network_link")


def _public_config(kind: str, cfg: dict) -> dict:
    if kind == "email":
        return {"to": cfg.get("to", "")}
    if kind == "telegram":
        return {"chat_id": str(cfg.get("chat_id", ""))[-4:].rjust(4, "*")}
    if kind in ("slack", "discord", "webhook"):
        url = cfg.get("url") or cfg.get("webhook_url") or ""
        return {"url_hint": url[:30] + "…" if len(url) > 30 else url}
    if kind == "kakao":
        # 연동을 끊으면 이 채널도 함께 지운다 (services/connections.remove 가 이 값으로 찾는다).
        return {"connection_id": str(cfg.get("connection_id") or ""), "account": str(cfg.get("account") or "")}
    return {}


async def _kakao_connection(db: AsyncSession, owner_id: uuid.UUID, conn_id: Any):
    """카카오톡 나에게 보내기에 쓸 연결 — 이 사람의 것이고, 메시지 권한을 켜 둔 것이어야 한다 (plan/59)."""
    from memora.models import Connection
    try:
        c = await db.get(Connection, uuid.UUID(str(conn_id)))
    except (ValueError, TypeError):
        c = None
    if c is None or c.owner_id != owner_id or c.provider != "kakao":
        raise ValidationFailed("connect Kakao first", code="kakao_not_connected")
    if "talk_message" not in (c.capabilities or []):
        raise ValidationFailed("allow KakaoTalk messages first", code="kakao_message_off")
    if c.status != "active":
        raise ValidationFailed("reconnect Kakao", code="kakao_expired")
    return c


async def create_channel(db: AsyncSession, owner: User, *, kind: str, config: dict[str, Any],
                         label: str = "") -> NotificationChannel:
    if kind not in KINDS:
        raise ValidationFailed("bad channel kind")
    if kind in ("webhook", "slack", "discord"):
        url = config.get("url") or config.get("webhook_url")
        if not url:
            raise ValidationFailed("url required")
        try:
            url = await pools.to_thread("misc", check_url, str(url))
        except ValueError as e:
            raise ValidationFailed("invalid url", code=str(e)) from e
        config["url"] = url
    if kind == "telegram" and not str(config.get("chat_id") or "").strip():
        raise ValidationFailed("chat_id required (link the bot with /start <code>)", code="telegram_chat_id_required")
    if kind == "kakao":
        # 카카오톡 "나와의 채팅" 으로만 간다 — 받는 사람이 늘 연결한 본인이라 따로 증명할 것이 없다.
        c = await _kakao_connection(db, owner.id, config.get("connection_id"))
        config = {"connection_id": str(c.id), "account": c.account_label or ""}
    if kind == "email":
        # 받는 주소는 어디든 될 수 있다. 다만 **그 주소가 자기 것임을 증명한 뒤에야**
        # 알림이 간다. 증명 없이 보낼 수 있으면 채널 하나로 우리 메일 서버가 남에게
        # 보내는 통로가 된다. 천장을 낮추는 대신 문을 잠그는 쪽이 맞다.
        config["to"] = (config.get("to") or owner.email or "").strip()
        if "@" not in config["to"]:
            raise ValidationFailed("메일 주소 형식이 아니에요.", code="invalid_email")
    ch = NotificationChannel(owner_id=owner.id, kind=kind, label=label[:80] or kind,
                             config_enc=encrypt(json.dumps(config)), config_public=_public_config(kind, config), enabled=True)
    # 계정의 주소로 가는 메일 채널은 증명할 것이 없다. 그 주소는 처음부터 그 사람 것이다.
    # 다른 주소를 가리킬 때만 코드를 거친다.
    if kind == "email" and config.get("to") and config["to"] == (owner.email or "").strip():
        ch.verified_at = datetime.now(UTC)
    if kind == "kakao":
        ch.verified_at = datetime.now(UTC)
    db.add(ch)
    await db.flush()
    return ch


async def get_channel(db: AsyncSession, owner_id: uuid.UUID, ch_id: uuid.UUID) -> NotificationChannel:
    ch = await db.get(NotificationChannel, ch_id)
    if ch is None or ch.owner_id != owner_id:
        raise NotFound("channel not found")
    return ch


def channel_config(ch: NotificationChannel) -> dict[str, Any]:
    try:
        return json.loads(decrypt(ch.config_enc) or "{}")
    except Exception:
        return {}


async def ensure_default_rules(db: AsyncSession, owner: User) -> None:
    existing = (await db.execute(select(NotificationRule).where(NotificationRule.owner_id == owner.id))).scalars().first()
    if existing:
        return
    email_ch = (await db.execute(select(NotificationChannel).where(NotificationChannel.owner_id == owner.id,
                                                                   NotificationChannel.kind == "email"))).scalars().first()
    if email_ch is None:
        email_ch = await create_channel(db, owner, kind="email", config={"to": owner.email}, label="이메일")
    for ev in DEFAULT_RULE_EVENTS:
        db.add(NotificationRule(owner_id=owner.id, event=ev, channel_ids=[email_ch.id], enabled=True,
                                quiet_hours={}, min_urgency=0))


async def evaluate(db: AsyncSession, *, owner_id: uuid.UUID, event: str, payload: dict[str, Any],
                   urgency: int | None = None, agent_id: uuid.UUID | None = None) -> int:
    urgency = URGENCY.get(event, 1) if urgency is None else urgency
    rules = (await db.execute(select(NotificationRule).where(NotificationRule.owner_id == owner_id,
                                                             NotificationRule.event == event,
                                                             NotificationRule.enabled.is_(True)))).scalars().all()
    chosen: set[uuid.UUID] = set()
    for r in rules:
        if r.agent_id and agent_id and r.agent_id != agent_id:
            continue
        if urgency < (r.min_urgency or 0):
            continue
        if _in_quiet_hours(r.quiet_hours or {}) and event != "digest_daily" and urgency < 3:
            continue
        chosen.update(r.channel_ids or [])
    if not chosen:
        return 0
    # 확인되지 않은 곳으로는 아무것도 나가지 않는다. `verified_at` 은 이 주소가 그 사람
    # 것이라는 유일한 증거이고, 그것을 여기서 보지 않으면 칸이 있으나 마나다.
    channels = (await db.execute(select(NotificationChannel).where(NotificationChannel.owner_id == owner_id,
                                                                    NotificationChannel.id.in_(chosen),
                                                                    NotificationChannel.enabled.is_(True),
                                                                    NotificationChannel.verified_at.isnot(None)))).scalars().all()
    n = 0
    for ch in channels:
        note = Notification(owner_id=owner_id, event=event, payload=payload, channel_id=ch.id,
                            status="pending", created_at=datetime.now(UTC))
        db.add(note)
        await db.flush()
        await J.enqueue(db, "notify.send", {"notification_id": str(note.id)}, priority=2)
        n += 1
    return n


def _in_quiet_hours(q: dict[str, Any]) -> bool:
    try:
        if not q or not q.get("start") or not q.get("end"):
            return False
        from zoneinfo import ZoneInfo

        now = datetime.now(ZoneInfo(q.get("tz") or "Asia/Seoul"))
        s = int(q["start"].split(":")[0])
        e = int(q["end"].split(":")[0])
        h = now.hour
        return (s <= h < e) if s < e else (h >= s or h < e)
    except Exception:
        return False


def telegram_webhook_secret(bot_token: str) -> str:
    return hashlib.sha256(bot_token.encode()).hexdigest()[:32]


def unsubscribe_token(channel_id: uuid.UUID) -> str:
    return sign_state({"ch": str(channel_id), "kind": "unsubscribe"}, ttl_minutes=60 * 24 * 365)


#: What each kind of inbox item is called when it is counted, in words a person uses.
KIND_LABEL = {
    "message": "방문자가 남긴 메시지", "meeting_request": "미팅 요청", "contact_share": "연락처 요청",
    "question_unanswered": "비서가 답하지 못한 질문", "community_comment": "내 글에 달린 댓글",
    "community_reply": "내 댓글에 달린 답글", "relay_result": "비서끼리 나눈 대화", "relay_visit": "다른 비서의 문의",
    "company_review": "관심 기업의 새 리뷰", "company_job": "관심 기업의 채용 공고",
    # 내 집 쪽 (plan/41·43). 라벨이 없으면 아침 메일에 `post_comment` 가 그대로 찍힌다.
    "post_comment": "내 글에 달린 댓글", "post_reply": "내 댓글에 달린 답글",
    "post_mention": "나를 언급한 글", "person_follow": "나를 구독한 사람",
    "storage_notice": "저장 공간 알림",
}


def link_for(event: str, payload: dict[str, Any]) -> tuple[str, str]:
    """알림이 여는 화면(서비스 안의 경로)과 그 버튼 이름."""
    if event == "secretary_message" and payload.get("agent_id") and payload.get("conversation_id"):
        return f"/app/chat?a={payload['agent_id']}&c={payload['conversation_id']}", "대화 이어가기"
    if event in ("relay_result", "relay_visit") and payload.get("relay_id"):
        return f"/app/conversations?relay={payload['relay_id']}", "대화 보기"
    if event == "company_update" and payload.get("company_id"):
        return (f"/app/community/companies/{payload['company_id']}" + ("?tab=hiring" if payload.get("job_id") else "?tab=reviews"),
                "채용 공고 보기" if payload.get("job_id") else "리뷰 보기")
    if event == "credits_low":
        return "/app/credits", "크레딧 확인하기"
    if event == "integration_error":
        return "/app/account#connections", "연결 확인하기"
    if event == "agent_model_fallback":
        return "/app/agents", "비서 설정 열기"
    if event == "network_link":
        return "/app/network?tab=people", "인맥 열기"
    if event in ("test", "channel_verify"):
        return "/app/notifications", "알림 설정 열기"
    if payload.get("inbox_item_id"):
        return f"/app/inbox?item={payload['inbox_item_id']}", "인박스 열기"
    return "/app/inbox", "인박스 열기"


def render(event: str, payload: dict[str, Any], locale: str = "ko",
           *, channel_id: uuid.UUID | None = None) -> tuple[str, str, str]:
    """(subject, text, html) for one notification. Chat channels read the text; the mail
    channel gets the Memora envelope (services/emails)."""
    from memora.services import emails as E

    base = get_settings().public_url.rstrip("/")
    agent = payload.get("agent_name", "비서")
    visitor = payload.get("visitor_name") or "방문자"
    path, link_label = link_for(event, payload)
    link = f"{base}{path}"
    body = payload.get("text") or payload.get("summary") or ""
    settings_url = f"{base}/app/notifications"
    unsub = f"{base}/api/notifications/unsubscribe?token={unsubscribe_token(channel_id)}" if channel_id is not None else ""
    company = payload.get("company_name") or "관심 기업"
    other = payload.get("target_agent_name") or "상대 비서"
    caller = payload.get("initiator_agent_name") or "다른 비서"
    mood = {"morning": "아침 인사", "anniversary": "함께한 날", "followup": "아까 이야기 이어서"}.get(str(payload.get("kind")), "안부를 물어요")
    actor = payload.get("actor_name") or "누군가"
    mutual = bool(payload.get("mutual"))
    # title: what happened · intro: one sentence of context · quote: who said the body, if a person did
    spec: dict[str, tuple[str, str, str]] = {
        "visitor_message": (f"{visitor}님이 메시지를 남겼어요", f"비서 {agent}와 이야기하던 {visitor}님이 남긴 말이에요.", visitor),
        "meeting_request": (f"{visitor}님의 미팅 요청", f"비서 {agent}에게 {visitor}님이 미팅을 요청했어요.", visitor),
        "contact_share": (f"{visitor}님이 연락처를 남겼어요", f"비서 {agent}에게 {visitor}님이 연락처를 남겼어요.", visitor),
        "question_unanswered": ("답하지 못한 질문이 있어요", f"비서 {agent}가 답을 몰라서 넘긴 질문이에요. 답을 알려주면 다음부터는 직접 답해요.", visitor),
        "visitor_new_conversation": ("새 방문자 대화", f"비서 {agent}에게 새 방문자가 찾아왔어요.", ""),
        "credits_low": ("크레딧이 얼마 남지 않았어요", "크레딧이 다 떨어지면 비서가 대화를 멈춰요.", ""),
        "integration_error": ("연결에 문제가 생겼어요", "연결해 둔 서비스가 응답하지 않아요.", ""),
        "agent_model_fallback": ("비서 모델이 기본 모델로 바뀌었어요", "고른 모델을 쓸 수 없어서 기본 모델로 대화를 이어가고 있어요.", ""),
        "relay_result": (f"{other}와의 대화가 끝났어요", f"비서 {agent}가 {other}와 나눈 대화의 결과예요.", agent),
        "relay_visit": (f"{caller}가 문의하고 갔어요", f"비서 {agent}에게 {caller}가 찾아와 물어본 내용이에요.", caller),
        "secretary_message": (mood, f"비서 {agent}가 보낸 말이에요.", agent),
        "company_update": (("새 채용 공고가 올라왔어요" if payload.get("job_id") else "새 리뷰가 올라왔어요"),
                           f"팔로우한 {company}에 새 소식이 있어요.", ""),
        # Connecting is one act, and the only thing worth saying differently is whether it
        # just made the two of you 인맥 (plan/43).
        "network_link": ((f"{actor}님과 인맥이 됐어요" if mutual else f"{actor}님이 나를 연결했어요"),
                         ("서로 연결해서 이제 인맥이에요." if mutual
                          else "내가 공개한 글이 그 사람 소식에 보여요. 연결하면 인맥이 돼요."), ""),
    }
    title, intro, quote_from = spec.get(event, (event, "", ""))
    system_events = ("credits_low", "integration_error", "agent_model_fallback", "network_link")
    if event == "company_update":
        prefix, kicker = f"[{company}]", "관심 기업"
    elif event in system_events:
        prefix, kicker = f"[{BRAND_NAME}]", BRAND_NAME
    else:
        prefix, kicker = f"[{agent}]", f"비서 {agent}"
    subject = f"{prefix} {title}"

    if event == "digest_daily":
        items = [(str(i.get("label") or ""), str(i.get("value") or "")) for i in (payload.get("items") or [])]
        if not items:
            items = [(ln.split(" ")[0], ln) for ln in body.splitlines() if ln.strip()]
        return E.digest(name=str(payload.get("name") or ""), date_label=str(payload.get("date") or ""), items=items,
                        link=link, settings_url=settings_url, unsubscribe_url=unsub)
    return E.notification(subject=subject, title=title, intro=intro, body=body, quote_from=quote_from,
                          link=link, link_label=link_label, kicker=kicker, settings_url=settings_url, unsubscribe_url=unsub)


def _esc(s: str) -> str:
    return (s or "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


async def deliver(db: AsyncSession, note: Notification) -> None:
    ch = await db.get(NotificationChannel, note.channel_id) if note.channel_id else None
    if ch is None or ch.owner_id != note.owner_id or not ch.enabled or ch.verified_at is None:
        note.status = "skipped"
        note.error = "notification channel unavailable"
        return
    cfg = channel_config(ch)
    subject, text, html = render(note.event, note.payload, channel_id=ch.id if ch.kind == "email" else None)
    await send_via(db, ch.kind, cfg, subject=subject, text=text, html=html,
                   payload={"event": note.event, **note.payload}, owner_id=ch.owner_id)
    note.status = "sent"
    note.sent_at = datetime.now(UTC)
    ch.last_error = None


async def _safe_delivery_url(cfg: dict[str, Any]) -> str:
    url = str(cfg.get("url") or cfg.get("webhook_url") or "")
    if not url:
        raise ValidationFailed("url required")
    try:
        return await pools.to_thread("misc", check_url, url)
    except ValueError as e:
        raise ValidationFailed("webhook destination is no longer allowed", code=str(e)) from e


async def _post_user_url(url: str, *, body: bytes, headers: dict[str, str]) -> None:
    try:
        response = await safe_request(
            "POST",
            url,
            headers=headers,
            body=body,
            max_bytes=512 * 1024,
            timeout=12.0,
            max_redirects=0,
        )
    except (ValueError, ConnectionError, TimeoutError) as e:
        raise ValidationFailed("webhook delivery failed", code="webhook_delivery_failed") from e
    if response.status_code >= 400:
        raise ValidationFailed(f"webhook returned HTTP {response.status_code}", code="webhook_http_error")


async def send_via(db: AsyncSession, kind: str, cfg: dict[str, Any], *, subject: str, text: str,
                   html: str, payload: dict, owner_id: uuid.UUID | None = None) -> None:
    if kind == "kakao":
        from memora.services import kakao as K
        if owner_id is None:
            raise ValidationFailed("connect Kakao first", code="kakao_not_connected")
        conn = await _kakao_connection(db, owner_id, cfg.get("connection_id"))
        path, label = link_for(str(payload.get("event") or ""), payload)
        body = str(payload.get("text") or payload.get("summary") or "").strip()
        msg = subject if not body else f"{subject}\n\n{body}"
        await K.send_memo(db, conn, text_=msg if len(msg) <= 200 else msg[:199] + "…", link_path=path, button=label)
    elif kind == "email":
        await send_mail(db, to=cfg["to"], subject=subject, text=text, html=html)
    elif kind == "telegram":
        token = await S.get(db, "telegram.bot_token")
        if not token:
            raise ValidationFailed("telegram bot not configured", code="telegram_not_configured")
        await request("POST", f"https://api.telegram.org/bot{token}/sendMessage",
                      json={"chat_id": cfg["chat_id"], "text": text[:4000], "disable_web_page_preview": True}, retries=2)
    elif kind == "slack":
        body = json.dumps({"text": text[:3000]}, ensure_ascii=False).encode()
        await _post_user_url(await _safe_delivery_url(cfg), body=body, headers={"Content-Type": "application/json"})
    elif kind == "discord":
        body = json.dumps({"content": text[:1900]}, ensure_ascii=False).encode()
        await _post_user_url(await _safe_delivery_url(cfg), body=body, headers={"Content-Type": "application/json"})
    elif kind == "webhook":
        body = json.dumps(payload, ensure_ascii=False, default=str).encode()
        headers = {"Content-Type": "application/json"}
        if cfg.get("secret"):
            headers["X-Memora-Signature"] = hmac_signature(cfg["secret"], body)
        await _post_user_url(await _safe_delivery_url(cfg), body=body, headers=headers)


#: 코드가 살아 있는 시간, 그리고 몇 번까지 틀려도 되는지.
CODE_MINUTES = 30
CODE_TRIES = 5


async def send_code(db: AsyncSession, ch: NotificationChannel, owner: User) -> None:
    """이 주소가 당신 것이 맞는지 묻는다 (메일 채널).

    계정 인증과 같은 방식이다. 주소는 자유롭게 적되, 거기로 간 코드를 가져와야 그 주소로
    알림이 나간다. 코드는 채널 설정 안에 해시로만 남는다.
    """
    from memora.core.security import sha256
    from memora.services import emails as E

    cfg = channel_config(ch)
    to = (cfg.get("to") or "").strip()
    if "@" not in to:
        raise ValidationFailed("메일 주소 형식이 아니에요.", code="invalid_email")
    code = f"{secrets.randbelow(1_000_000):06d}"
    cfg["code_hash"] = sha256(code)
    cfg["code_until"] = (datetime.now(UTC) + timedelta(minutes=CODE_MINUTES)).isoformat()
    cfg["code_tries"] = 0
    ch.config_enc = encrypt(json.dumps(cfg))
    subject, text, html = E.verification(code=code, name=owner.display_name or "", minutes=CODE_MINUTES)
    await asyncio.wait_for(send_via(db, "email", {"to": to}, subject=subject, text=text, html=html,
                                    payload={"event": "channel_verify"}), timeout=20)


async def confirm_code(db: AsyncSession, ch: NotificationChannel, code: str) -> None:
    from memora.core.security import sha256

    cfg = channel_config(ch)
    until = cfg.get("code_until")
    if not cfg.get("code_hash") or not until:
        raise ValidationFailed("먼저 코드를 받아주세요.", code="no_pending_verification")
    if datetime.fromisoformat(until) < datetime.now(UTC):
        raise ValidationFailed("코드가 만료됐어요. 다시 받아주세요.", code="code_expired")
    if int(cfg.get("code_tries") or 0) >= CODE_TRIES:
        raise ValidationFailed("코드를 너무 여러 번 틀렸어요. 새 코드를 받아주세요.", code="too_many_attempts")
    if sha256((code or "").strip()) != cfg["code_hash"]:
        cfg["code_tries"] = int(cfg.get("code_tries") or 0) + 1
        ch.config_enc = encrypt(json.dumps(cfg))
        raise ValidationFailed("코드가 맞지 않아요. 메일을 다시 확인해 주세요.", code="bad_code")
    for k in ("code_hash", "code_until", "code_tries"):
        cfg.pop(k, None)
    ch.config_enc = encrypt(json.dumps(cfg))
    ch.verified_at = datetime.now(UTC)
    ch.last_error = None


async def test_channel(db: AsyncSession, ch: NotificationChannel) -> None:
    if ch.kind == "email" and ch.verified_at is None:
        raise ValidationFailed("먼저 이 주소를 인증해 주세요.", code="channel_unverified")
    cfg = channel_config(ch)
    try:
        from memora.services import emails as E
        subject, text, html = E.plain(title="알림 채널 테스트", text="알림 채널이 잘 연결됐어요. 앞으로 알림이 이 채널로 와요.", kicker="알림")
        await asyncio.wait_for(send_via(db, ch.kind, cfg, subject=subject, text=text, html=html,
                                        payload={"event": "test", "text": "알림 채널이 잘 연결됐어요."}, owner_id=ch.owner_id),
                               timeout=12)
    except TimeoutError as e:
        raise RuntimeError("timeout (12s): endpoint did not respond") from e
    ch.verified_at = datetime.now(UTC)
    ch.last_error = None
