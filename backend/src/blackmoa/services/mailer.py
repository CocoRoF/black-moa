from __future__ import annotations

from email.header import Header
from email.message import EmailMessage
from email.utils import formataddr, parseaddr

import aiosmtplib
from sqlalchemy.ext.asyncio import AsyncSession

from blackmoa.core.errors import ServiceUnavailable
from blackmoa.services import settings as S


def _domain(value: str) -> str:
    return _addr(value).rsplit("@", 1)[-1].lower()


def _addr(value: str) -> str:
    """The bare address out of a possibly-decorated "Name <a@b>" setting."""
    return parseaddr(value)[1] or value


async def smtp_config(db: AsyncSession) -> dict:
    cfg = await S.get_many(db, "smtp.")
    if not cfg.get("smtp.host") or not cfg.get("smtp.from"):
        raise ServiceUnavailable("smtp not configured", code="smtp_not_configured")
    return cfg


async def send_mail(db: AsyncSession, *, to: str, subject: str, text: str, html: str | None = None,
                    identity: str = "system", from_name: str = "", from_address: str = "",
                    reply_to: str = "") -> None:
    """Send one message.

    `identity` picks which mailbox it comes from: "system" is the no-reply address that
    carries codes and alerts, "agent" is the address a secretary writes from. The From
    domain always stays ours — SPF and DKIM are published for it, and a From carrying the
    owner's own address would fail DMARC at the recipient and land in spam. Their address
    goes in Reply-To, which is what actually decides where an answer is sent.
    """
    cfg = await smtp_config(db)
    sender = (cfg.get("smtp.from_agent") or cfg["smtp.from"]) if identity == "agent" else cfg["smtp.from"]
    # A caller may supply the exact mailbox — a per-user address on our sending domain.
    # Only that domain is honoured: SPF and DKIM are published for it and nowhere else.
    if from_address and identity == "agent" and _domain(from_address) == _domain(sender):
        sender = from_address
    msg = EmailMessage()
    msg["From"] = formataddr((str(Header(from_name, "utf-8")), _addr(sender))) if from_name else sender
    msg["To"] = to
    if reply_to:
        msg["Reply-To"] = reply_to
    msg["Subject"] = subject
    msg.set_content(text)
    if html:
        msg.add_alternative(html, subtype="html")
    port = int(cfg.get("smtp.port") or 587)
    use_tls = bool(cfg.get("smtp.use_tls", True))
    await aiosmtplib.send(msg, hostname=cfg["smtp.host"], port=port, username=cfg.get("smtp.user") or None,
                          password=cfg.get("smtp.password") or None, start_tls=(use_tls and port != 465),
                          use_tls=(port == 465), timeout=20)
