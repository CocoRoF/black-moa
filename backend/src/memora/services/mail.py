"""[내 정보 → 메일] (plan/57).

바깥 메일함에서 가져온 메일이 모이는 곳이고, 비서는 **여기만** 본다 — Google 에 직접
닿지 않는다. 캘린더가 스케줄을, 연락처가 인맥을 거치는 것과 같다.

메일함은 공급자 등록표(``PROVIDERS``)로 붙는다. 지금은 IMAP(앱 비밀번호) 하나다(plan/74) — Gmail 도
IMAP 으로 붙는다. Google API 의 Gmail 읽기 권한은 "제한 범위"라 매년 유료 보안 평가가 붙어 쓰지 않는다.
가져온 메일은 ``integration_emails`` 에 연결 하나당 하나씩 쌓인다.

메일은 **나와의 대화에서만** 쓴다. 남이 보낸 글이므로 비서에게 건널 때는 늘
``<untrusted>`` 로 싸서 건넨다.
"""
from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any, Protocol

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from memora.core.errors import NotFound, ValidationFailed
from memora.models import AuditLog, Connection, IntegrationEmail


class MailProvider(Protocol):
    id: str

    async def ready(self, db: AsyncSession) -> bool: ...

    def label(self, conn: Connection) -> str: ...

    def can_read(self, conn: Connection) -> bool: ...

    async def read(self, db: AsyncSession, conn: Connection, ext_id: str) -> dict[str, Any]: ...


class ImapMail:
    """IMAP + 앱 비밀번호 — 최근 30일의 머리글·미리보기를 가져오고, 본문은 열 때 읽는다(services/imap_mail)."""

    id = "imap"

    async def ready(self, db: AsyncSession) -> bool:
        return True

    def label(self, conn: Connection) -> str:
        from memora.services import imap_mail as IM
        return IM.label_for(conn)

    def can_read(self, conn: Connection) -> bool:
        return conn.status == "active" and "mail_read" in (conn.capabilities or [])

    async def read(self, db: AsyncSession, conn: Connection, ext_id: str) -> dict[str, Any]:
        from memora.services import imap_mail as IM
        return await IM.read(conn, ext_id)


PROVIDERS: dict[str, MailProvider] = {"imap": ImapMail()}


def _last_sync(conn: Connection) -> str | None:
    return (conn.sync_cursor or {}).get("gmail_last_sync") or (conn.last_sync_at.isoformat() if conn.last_sync_at else None)


async def _connections(db: AsyncSession, owner_id: uuid.UUID) -> list[Connection]:
    on = [pid for pid, p in PROVIDERS.items() if await p.ready(db)]
    if not on:
        return []
    return list((await db.execute(select(Connection).where(Connection.owner_id == owner_id,
                                                           Connection.provider.in_(on))
                                  .order_by(Connection.created_at))).scalars().all())


async def _readable_ids(db: AsyncSession, owner_id: uuid.UUID) -> list[uuid.UUID]:
    return [c.id for c in await _connections(db, owner_id) if PROVIDERS[c.provider].can_read(c)]


async def accounts(db: AsyncSession, owner_id: uuid.UUID) -> list[dict[str, Any]]:
    """연결한 메일함들. 연결은 있는데 메일 읽기 권한이 없으면 ``can_read`` 가 거짓이다."""
    out = []
    for c in await _connections(db, owner_id):
        p = PROVIDERS[c.provider]
        n = int((await db.execute(select(func.count(IntegrationEmail.id)).where(IntegrationEmail.connection_id == c.id))).scalar_one())
        out.append({"id": str(c.id), "provider": p.id, "provider_label": p.label(c), "account": c.account_label or "",
                    "preset": (c.settings or {}).get("preset") or "",
                    "status": c.status, "can_read": p.can_read(c), "last_sync": _last_sync(c), "count": n,
                    "error": c.error or None})
    return out


async def readable(db: AsyncSession, owner_id: uuid.UUID) -> bool:
    """비서가 메일을 쓸 수 있는가 — 읽을 수 있는 메일함이 하나라도 있으면."""
    return bool(await _readable_ids(db, owner_id))


def _out(e: IntegrationEmail) -> dict[str, Any]:
    return {"id": str(e.id), "from": e.from_addr, "to": list(e.to_addrs or []), "subject": e.subject,
            "snippet": (e.snippet or "")[:300], "summary": e.summary or "", "unread": bool(e.unread),
            "important": bool(e.importance), "received_at": e.received_at.isoformat() if e.received_at else None}


async def search(db: AsyncSession, owner_id: uuid.UUID, query: str = "", *, days: int | None = None,
                 limit: int = 30, before: datetime | None = None) -> list[dict[str, Any]]:
    """읽을 수 있는 메일함의 메일. 권한을 거둔 메일함의 메일은 나오지 않는다."""
    conns = await _readable_ids(db, owner_id)
    if not conns:
        return []
    stmt = select(IntegrationEmail).where(IntegrationEmail.owner_id == owner_id, IntegrationEmail.connection_id.in_(conns))
    if days:
        stmt = stmt.where(IntegrationEmail.received_at >= datetime.now(UTC) - timedelta(days=max(1, min(days, 365))))
    if before is not None:
        stmt = stmt.where(IntegrationEmail.received_at < before)
    q = (query or "").strip()[:100]
    if q:
        pat = "%" + q.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"
        stmt = stmt.where(IntegrationEmail.subject.ilike(pat, escape="\\") | IntegrationEmail.from_addr.ilike(pat, escape="\\")
                          | IntegrationEmail.snippet.ilike(pat, escape="\\") | IntegrationEmail.summary.ilike(pat, escape="\\"))
    rows = (await db.execute(stmt.order_by(IntegrationEmail.received_at.desc().nullslast()).limit(max(1, min(limit, 100))))).scalars().all()
    return [_out(e) for e in rows]


async def read(db: AsyncSession, owner_id: uuid.UUID, mail_id: Any) -> dict[str, Any]:
    """메일 한 통 — 본문은 메일함에서 그때 읽는다(보관하지 않는다)."""
    try:
        mid = uuid.UUID(str(mail_id))
    except (TypeError, ValueError):
        raise NotFound("mail not found", code="mail_not_found") from None
    e = await db.get(IntegrationEmail, mid)
    if e is None or e.owner_id != owner_id:
        raise NotFound("mail not found", code="mail_not_found")
    conn = await db.get(Connection, e.connection_id)
    p = PROVIDERS.get(conn.provider) if conn is not None else None
    if conn is None or p is None or not p.can_read(conn):
        raise NotFound("mail not found", code="mail_not_found")
    full = await p.read(db, conn, e.ext_id)
    if e.unread:
        e.unread = False     # 열어 본 것은 여기서도 읽은 것으로 — 다음 가져오기가 메일함 쪽 상태로 다시 맞춘다
    return {**_out(e), "body": full.get("body") or "", "date": full.get("date") or "",
            "account": conn.account_label or "", "provider": p.id}


async def recent_unread(db: AsyncSession, owner_id: uuid.UUID, *, days: int = 2, limit: int = 5) -> list[dict[str, Any]]:
    conns = await _readable_ids(db, owner_id)
    if not conns:
        return []
    rows = (await db.execute(select(IntegrationEmail).where(
        IntegrationEmail.owner_id == owner_id, IntegrationEmail.connection_id.in_(conns), IntegrationEmail.unread.is_(True),
        IntegrationEmail.received_at >= datetime.now(UTC) - timedelta(days=days))
        .order_by(IntegrationEmail.received_at.desc()).limit(limit))).scalars().all()
    return [_out(e) for e in rows]


async def refresh_if_stale(db: AsyncSession, owner_id: uuid.UUID) -> int:
    """메일 화면을 열었다 — 오래된 메일함이 있으면 가져오기를 건다. 끝나면 화면이 소식을 받아 다시 읽는다."""
    from memora.models import Connection
    from memora.services import connections as CN
    from memora.services import jobs as J
    now = datetime.now(UTC)
    n = 0
    for cid in await _readable_ids(db, owner_id):
        c = await db.get(Connection, cid)
        if c is not None and c.status == "active" and (c.last_sync_at is None or now - c.last_sync_at >= CN.MAIL_FRESH):
            await J.enqueue(db, "integration.sync", {"connection_id": str(cid)}, priority=2, dedupe_key=f"sync:{cid}",
                            owner_id=owner_id)
            n += 1
    return n


async def request_sync(db: AsyncSession, owner_id: uuid.UUID) -> int:
    """읽을 수 있는 메일함마다 가져오기를 건다. 몇 개를 걸었는지."""
    from memora.services import jobs as J

    conns = await _readable_ids(db, owner_id)
    if not conns:
        raise ValidationFailed("no mailbox is connected", code="mail_not_connected")
    for cid in conns:
        await J.enqueue(db, "integration.sync", {"connection_id": str(cid)}, priority=2, dedupe_key=f"sync:{cid}",
                        owner_id=owner_id)
    return len(conns)


async def sent(db: AsyncSession, owner_id: uuid.UUID, *, limit: int = 50) -> list[dict[str, Any]]:
    """비서가 내 이름으로 보낸 메일 — 받는 사람·제목·보낸 비서·때. 본문은 남기지 않는다."""
    from memora.services.outbound_mail import ACTION

    rows = (await db.execute(select(AuditLog).where(AuditLog.action == ACTION, AuditLog.actor_id == owner_id)
                             .order_by(AuditLog.created_at.desc()).limit(max(1, min(limit, 200))))).scalars().all()
    return [{"id": str(r.id), "to": r.target_id or "", "subject": (r.meta or {}).get("subject", ""),
             "agent": (r.meta or {}).get("agent", ""), "agent_id": (r.meta or {}).get("agent_id"),
             "at": r.created_at.isoformat() if r.created_at else None} for r in rows]
