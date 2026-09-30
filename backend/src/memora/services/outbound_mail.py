"""Mail a secretary sends on its owner's behalf.

Separate from `mailer` because the interesting part is not SMTP, it is the policy: who is
allowed to make the product send a message to a stranger, how often, and whose name is on
it. Every rule here exists to keep a helpful feature from becoming an open relay.
"""

from __future__ import annotations

import re
import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from memora.core.errors import Conflict, Forbidden, ValidationFailed
from memora.models import AuditLog, User
from memora.services import audit as A
from memora.services.emails import agent_message
from memora.services.mailer import send_mail

ACTION = "agent.email_sent"
HANDLE_MIN, HANDLE_MAX = 3, 30
HANDLE = re.compile(r"^[a-z0-9](?:[a-z0-9._-]*[a-z0-9])?$")
# Addresses a mail system, a person, or we ourselves may already be using. Handing one out
# would mean a reply meant for support lands in someone's private inbox.
RESERVED = frozenset({
    "abuse", "admin", "administrator", "alert", "alerts", "billing", "contact", "help", "hello",
    "hostmaster", "info", "mail", "mailer-daemon", "mailerdaemon", "marketing", "memora", "news",
    "no-reply", "noreply", "notification", "notifications", "postmaster", "press", "privacy",
    "root", "sales", "security", "spam", "support", "system", "team", "webmaster", "www",
})
DAILY_CAP = 20
MAX_SUBJECT = 200
MAX_BODY = 20_000
# Deliberately strict: this address is handed to an SMTP server by a language model.
ADDRESS = re.compile(r"^[^@\s,;<>\"]+@[A-Za-z0-9]([A-Za-z0-9-]*[A-Za-z0-9])?(\.[A-Za-z0-9]([A-Za-z0-9-]*[A-Za-z0-9])?)+$")


async def sending_domain(db: AsyncSession) -> str:
    """The domain a secretary sends from, read off the configured mailbox so there is one
    place to change it."""
    from memora.services import settings as S
    cfg = await S.get_many(db, "smtp.")
    box = cfg.get("smtp.from_agent") or cfg.get("smtp.from") or ""
    addr = box.split("<")[-1].strip("<> ").strip()
    return addr.split("@")[-1].strip() if "@" in addr else ""


def clean_handle(raw: str) -> str:
    """Validate a claimed local part, or say precisely what is wrong with it."""
    value = (raw or "").strip().lower()
    if not (HANDLE_MIN <= len(value) <= HANDLE_MAX):
        raise ValidationFailed(f"{HANDLE_MIN}~{HANDLE_MAX}자로 지어주세요", code="handle_length")
    if not HANDLE.match(value):
        raise ValidationFailed("영문 소문자·숫자로 시작하고 끝나야 하고, 사이에 . - _ 만 쓸 수 있어요", code="handle_charset")
    if ".." in value or "--" in value or "__" in value:
        raise ValidationFailed("기호를 연달아 쓸 수 없어요", code="handle_charset")
    if value in RESERVED:
        raise ValidationFailed("이미 시스템이 쓰고 있는 주소예요", code="handle_reserved")
    return value


async def handle_taken(db: AsyncSession, handle: str, *, exclude: uuid.UUID | None = None) -> bool:
    stmt = select(func.count(User.id)).where(User.mail_handle == handle)
    if exclude is not None:
        stmt = stmt.where(User.id != exclude)
    return int((await db.execute(stmt)).scalar_one()) > 0


async def claim_handle(db: AsyncSession, *, user: User, raw: str) -> str:
    """Take a local part for this account.

    The uniqueness check races — two people can pass it in the same instant — so the column
    carries a unique constraint and this only turns the resulting integrity error into a
    sentence a person can act on.
    """
    from sqlalchemy.exc import IntegrityError

    handle = clean_handle(raw)
    if await handle_taken(db, handle, exclude=user.id):
        raise Conflict("이미 사용 중인 아이디예요", code="handle_taken")
    user.mail_handle = handle
    try:
        await db.flush()
    except IntegrityError as e:
        raise Conflict("이미 사용 중인 아이디예요", code="handle_taken") from e
    return handle


def clean_address(raw: str) -> str:
    value = (raw or "").strip().strip("<>").strip()
    if not ADDRESS.match(value) or len(value) > 254:
        raise ValidationFailed("that does not look like an email address", code="bad_recipient")
    return value


async def sent_today(db: AsyncSession, owner_id: uuid.UUID) -> int:
    """Counted from the audit log rather than a counter in memory: the cap has to survive a
    restart, and it has to mean the same thing when a second pod is answering."""
    since = datetime.now(UTC) - timedelta(days=1)
    return int((await db.execute(
        select(func.count(AuditLog.id)).where(AuditLog.action == ACTION, AuditLog.actor_id == owner_id,
                                              AuditLog.created_at >= since))).scalar_one())


async def send_as_owner(db: AsyncSession, *, owner: User, agent_name: str, to: str, subject: str, body: str,
                        agent_id: uuid.UUID | None = None) -> dict:
    """Send one message written by `agent_name` for `owner`.

    The owner must have a verified address. That is the whole trust model: the message
    carries their name and invites a reply to their mailbox, so we have to know the mailbox
    is theirs — otherwise the feature writes to strangers under a name nobody proved.
    """
    if owner.email_verified_at is None:
        raise Forbidden("verify your email address before the secretary can send mail", code="email_unverified")

    recipient = clean_address(to)
    subject = " ".join((subject or "").split())[:MAX_SUBJECT]
    body = (body or "").strip()[:MAX_BODY]
    if not subject or not body:
        raise ValidationFailed("a subject and a body are both required", code="empty_email")

    used = await sent_today(db, owner.id)
    if used >= DAILY_CAP:
        raise Forbidden(f"daily email limit reached ({DAILY_CAP})", code="email_quota_exhausted")

    sender_name = (owner.display_name or owner.nickname or "").strip()
    domain = await sending_domain(db)
    # Their own address when they claimed one, otherwise the shared secretary mailbox.
    from_address = f"{owner.mail_handle}@{domain}" if (owner.mail_handle and domain) else ""
    subj, text, html = agent_message(sender_name=sender_name, agent_name=agent_name,
                                     subject=subject, body=body, reply_to=owner.email)
    await send_mail(db, to=recipient, subject=subj, text=text, html=html,
                    identity="agent", from_address=from_address,
                    from_name=f"{sender_name} · {agent_name}" if sender_name else agent_name,
                    reply_to=owner.email)
    A.record(db, ACTION, actor_id=owner.id, target_type="email", target_id=recipient,
             meta={"subject": subject[:120], "agent": agent_name, "agent_id": str(agent_id) if agent_id else None})
    return {"sent": True, "to": recipient, "from": from_address, "reply_to": owner.email,
            "remaining_today": DAILY_CAP - used - 1}
