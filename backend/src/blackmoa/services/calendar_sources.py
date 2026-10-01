"""스케줄의 [연동] 탭 — 바깥 달력을 스케줄에 붙인다 (plan/58).

스케줄은 black-moa 의 원장이고 바깥 달력은 붙는 것이다 (plan/56). 가져온 일정은 스케줄에 함께 보이고
빈 시간을 셀 때 들어가며, 비서는 스케줄을 볼 뿐 바깥 달력에 직접 닿지 않는다 (plan/57).

달력은 공급자 등록표(``PROVIDERS``)로 붙는다. 지금은 Google 캘린더·카카오 톡캘린더다 (plan/59). 다른 달력은 같은 모양의
공급자를 하나 더 두면 되고, 화면은 이 목록을 그대로 그린다.

연결마다 정하는 것:
- 일정 가져오기 (읽기 권한) — 끄면 가져온 일정이 스케줄에서도, 빈 시간 계산에서도 빠진다.
- 자동으로 가져오기 — 끔 · 15분 · 1시간 · 6시간 · 하루. Google 은 여기에 더해 바뀌면 알려 온다(푸시, plan/76).
- 수락한 미팅을 그 달력에도 넣기 (쓰기 권한).
연결·해제 자체는 [관리·설정 → 연동] 의 일이다 — 한 연결이 메일·연락처도 함께 들고 있어서다.
"""
from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any, Protocol

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from blackmoa.core.errors import NotFound, ValidationFailed
from blackmoa.models import Connection, IntegrationEvent

#: 자동으로 가져오는 간격(분). 0 은 끔. 새 연결은 15분 — 카카오는 바뀌어도 알려 주지 않으니 이것이 늦는 만큼이다.
AUTO_EVERY = (0, 15, 60, 360, 1440)
DEFAULT_EVERY = 15
#: 화면을 열거나 비서가 일정을 볼 때 이보다 오래됐으면 먼저 가져온다. Google 은 변경 알림이 살아 있으면 알림을 믿는다.
FRESH = timedelta(minutes=5)
FRESH_PUSHED = timedelta(minutes=60)


class CalendarProvider(Protocol):
    id: str
    label: str
    label_en: str
    read_cap: str
    write_cap: str

    async def available(self, db: AsyncSession) -> bool: ...

    def granted(self, conn: Connection, cap: str) -> bool: ...

    async def sync(self, db: AsyncSession, conn: Connection) -> int: ...

    async def create_event(self, db: AsyncSession, conn: Connection, **kw: Any) -> dict[str, Any]: ...


class _OAuthCalendar:
    """[연결] 의 공급자 위에 선 달력. 연결할 수 있는지는 관리자가 그 공급자를 켜고 일정 기능을 사용자에게
    주었는가(plan/59), 권한은 공급자가 실제로 내준 것으로 가른다."""

    id = ""
    label = ""
    label_en = ""           # 비서에게 알리는 이름(프롬프트·도구 결과는 영어)
    read_cap = "calendar_read"
    write_cap = "calendar_write"

    async def available(self, db: AsyncSession) -> bool:
        from blackmoa.services import oauth as OA
        return self.read_cap in await OA.get(self.id).offered(db)

    def granted(self, conn: Connection, cap: str) -> bool:
        from blackmoa.services import oauth as OA
        return OA.get(self.id).granted(conn.scopes, cap)


class GoogleCalendar(_OAuthCalendar):
    id = "google"
    label = "Google Calendar"
    label_en = "Google Calendar"

    async def sync(self, db: AsyncSession, conn: Connection) -> int:
        from blackmoa.services import google as G
        return await G.sync_calendar(db, conn)

    async def create_event(self, db: AsyncSession, conn: Connection, **kw: Any) -> dict[str, Any]:
        from blackmoa.services import google as G
        return await G.create_event(db, conn, **kw)


class KakaoCalendar(_OAuthCalendar):
    id = "kakao"
    label = "카카오 톡캘린더"
    label_en = "Kakao Talk Calendar"

    async def sync(self, db: AsyncSession, conn: Connection) -> int:
        from blackmoa.services import kakao as K
        return await K.sync_calendar(db, conn)

    async def create_event(self, db: AsyncSession, conn: Connection, **kw: Any) -> dict[str, Any]:
        from blackmoa.services import kakao as K
        return await K.create_event(db, conn, **kw)


PROVIDERS: dict[str, CalendarProvider] = {"google": GoogleCalendar(), "kakao": KakaoCalendar()}


def _every(conn: Connection) -> int:
    v = (conn.settings or {}).get("calendar_auto_every", DEFAULT_EVERY)
    return int(v) if v in AUTO_EVERY else DEFAULT_EVERY


def _last(conn: Connection) -> str | None:
    return (conn.sync_cursor or {}).get("calendar_last_sync")


def reading(conn: Connection) -> bool:
    p = PROVIDERS.get(conn.provider)
    return p is not None and conn.status in ("active", "error") and p.read_cap in (conn.capabilities or [])


async def reading_ids(db: AsyncSession, owner_id: uuid.UUID) -> list[uuid.UUID]:
    """일정을 가져오기로 한 연결들 — 스케줄은 이 연결의 일정만 합친다."""
    on = [pid for pid, p in PROVIDERS.items() if await p.available(db)]
    if not on:
        return []
    rows = (await db.execute(select(Connection).where(Connection.owner_id == owner_id,
                                                      Connection.provider.in_(on)))).scalars().all()
    return [c.id for c in rows if reading(c)]


async def _conn(db: AsyncSession, owner_id: uuid.UUID, provider: str) -> Connection | None:
    return (await db.execute(select(Connection).where(Connection.owner_id == owner_id, Connection.provider == provider,
                                                     Connection.status.in_(("active", "error")))
                             .order_by(Connection.created_at))).scalars().first()


def _provider(provider: str) -> CalendarProvider:
    p = PROVIDERS.get(provider)
    if p is None:
        raise NotFound("no such calendar", code="calendar_provider_unknown")
    return p


async def sources(db: AsyncSession, owner_id: uuid.UUID) -> list[dict[str, Any]]:
    """[연동] 탭 한 장 — 붙일 수 있는 달력마다 지금 상태와 설정."""
    out = []
    for p in PROVIDERS.values():
        conn = await _conn(db, owner_id, p.id)
        item: dict[str, Any] = {"provider": p.id, "label": p.label, "label_en": p.label_en, "available": await p.available(db), "connected": conn is not None}
        if conn is not None:
            n = int((await db.execute(select(func.count(IntegrationEvent.id)).where(IntegrationEvent.connection_id == conn.id))).scalar_one())
            caps = conn.capabilities or []
            item.update({
                "account": conn.account_label or "", "status": conn.status, "error": conn.error or None,
                "read": p.read_cap in caps, "write": p.write_cap in caps,
                "read_granted": p.granted(conn, p.read_cap), "write_granted": p.granted(conn, p.write_cap),
                "auto_every": _every(conn), "last_sync": _last(conn), "events": n,
                "sync_error": (conn.sync_cursor or {}).get("calendar_error") or None,
            })
        out.append(item)
    return out


async def update(db: AsyncSession, owner_id: uuid.UUID, provider: str, *, read: bool | None = None,
                 write: bool | None = None, auto_every: int | None = None) -> dict[str, Any]:
    """설정을 바꾼다. 켜려는 권한을 아직 받지 않았으면 바꾸지 않고 ``needs_consent`` 를 돌려준다 —
    화면은 그 권한을 청하는 동의 화면으로 보낸다."""
    p = _provider(provider)
    conn = await _conn(db, owner_id, p.id)
    if conn is None:
        raise ValidationFailed("the calendar is not connected", code="calendar_not_connected")
    want = [c for c, on in ((p.read_cap, read), (p.write_cap, write)) if on and not p.granted(conn, c)]
    if want:
        return {"needs_consent": want}
    caps = set(conn.capabilities or [])
    for cap, on in ((p.read_cap, read), (p.write_cap, write)):
        if on is True:
            caps.add(cap)
        elif on is False:
            caps.discard(cap)
    conn.capabilities = sorted(caps)
    if read is False and conn.provider == "google":
        from blackmoa.services import google as G
        await G.stop_watch(db, conn)
    if auto_every is not None:
        if auto_every not in AUTO_EVERY:
            raise ValidationFailed("unknown interval", code="bad_auto_every")
        conn.settings = {**(conn.settings or {}), "calendar_auto_every": auto_every}
    await db.flush()
    # 가져오기를 막 켰으면 바로 한 번 가져온다 — 켰는데 비어 있으면 안 된 줄 안다.
    if read is True and not _last(conn):
        from blackmoa.services import jobs as J
        await J.enqueue(db, "calendar.sync", {"connection_id": str(conn.id)}, priority=2, dedupe_key=f"calsync:{conn.id}",
                        owner_id=owner_id)
    return {"needs_consent": []}


async def sync_now(db: AsyncSession, owner_id: uuid.UUID, provider: str) -> int:
    p = _provider(provider)
    conn = await _conn(db, owner_id, p.id)
    if conn is None or conn.status != "active" or not reading(conn):
        raise ValidationFailed("importing from this calendar is off", code="calendar_not_reading")
    # 실패해도 올려 보내지 않는다 — 올려 보내면 적어 둔 실패까지 되돌려진다. 화면은 목록의 sync_error 로 안다.
    return await sync_connection(db, conn.id) or 0


def _stale(conn: Connection, now: datetime) -> bool:
    last = _last(conn)
    try:
        last_at = datetime.fromisoformat(last) if last else None
    except ValueError:
        last_at = None
    if last_at is None:
        return True
    from blackmoa.services import google as G
    limit = FRESH_PUSHED if conn.provider == "google" and G.watching(conn, now) else FRESH
    return now - last_at >= limit


async def nudge(db: AsyncSession, conn: Connection, *, delay_s: float = 2) -> None:
    """곧 한 번 가져오게 한다. 가져오기가 이미 도는 중에 온 변경도 놓치지 않도록, 10초 칸마다 따로 건다 —
    같은 칸의 것이 이미 돌고 있으면 다음 칸에 하나를 더 건다. 같은 연결의 가져오기는 잠금으로 하나씩 돈다."""
    from blackmoa.services import jobs as J
    bucket = int(datetime.now(UTC).timestamp() // 10)
    job = await J.enqueue(db, "calendar.sync", {"connection_id": str(conn.id)}, priority=2, delay_s=delay_s,
                          dedupe_key=f"calpush:{conn.id}:{bucket}", owner_id=conn.owner_id)
    if job is None:
        await J.enqueue(db, "calendar.sync", {"connection_id": str(conn.id)}, priority=2, delay_s=delay_s + 10,
                        dedupe_key=f"calpush:{conn.id}:{bucket + 1}", owner_id=conn.owner_id)


async def refresh_if_stale(db: AsyncSession, owner_id: uuid.UUID) -> int:
    """스케줄 화면을 열었다 — 오래된 달력이 있으면 가져오기를 건다(끝나면 화면이 소식을 받아 다시 읽는다)."""
    now = datetime.now(UTC)
    ids = await reading_ids(db, owner_id)
    n = 0
    for cid in ids:
        conn = await db.get(Connection, cid)
        if conn is not None and conn.status == "active" and _stale(conn, now):
            await nudge(db, conn, delay_s=0)
            n += 1
    return n


async def ensure_fresh(owner_id: uuid.UUID, *, timeout: float = 6.0) -> None:
    """비서가 일정을 보기 직전 — 오래된 달력은 그 자리에서 가져온다. 늦거나 실패하면 가진 것으로 답한다."""
    import asyncio

    from blackmoa.core.logging import get_logger
    from blackmoa.db.session import session_scope
    now = datetime.now(UTC)
    async with session_scope() as db:
        ids = [c for c in await reading_ids(db, owner_id)
               if (conn := await db.get(Connection, c)) is not None and conn.status == "active" and _stale(conn, now)]
    for cid in ids:
        try:
            async with asyncio.timeout(timeout):
                async with session_scope() as db:
                    await sync_connection(db, cid)
                    await db.commit()
        except Exception as e:  # noqa: BLE001 — 가진 일정으로 답한다
            get_logger("blackmoa.calendar").info("calendar refresh before answering skipped", err=str(e)[:200])


async def due(db: AsyncSession, now: datetime | None = None) -> list[uuid.UUID]:
    """자동으로 가져올 때가 된 연결들."""
    now = now or datetime.now(UTC)
    rows = (await db.execute(select(Connection).where(Connection.provider.in_(list(PROVIDERS)),
                                                      Connection.status == "active"))).scalars().all()
    # 관리자가 꺼 둔 공급자는 건너뛴다 (plan/59).
    on = {pid for pid, p in PROVIDERS.items() if await p.available(db)}
    out = []
    for c in rows:
        if c.provider not in on:
            continue
        every = _every(c)
        if not reading(c) or every == 0:
            continue
        last = _last(c)
        try:
            last_at = datetime.fromisoformat(last) if last else None
        except ValueError:
            last_at = None
        if last_at is None or now - last_at >= timedelta(minutes=every):
            out.append(c.id)
    return out


async def push_event(db: AsyncSession, owner_id: uuid.UUID, **kw: Any) -> dict[str, Any]:
    """수락한 미팅을 바깥 달력에도 넣는다 — "넣기" 를 켠 첫 달력에.

    결과 ``status``: ``added`` · ``failed``(약속은 그대로) · ``off``(달력은 있지만 넣기를 꺼 둠) ·
    ``no_connection``(이은 달력이 없음).
    """
    rows = (await db.execute(select(Connection).where(Connection.owner_id == owner_id, Connection.status == "active",
                                                      Connection.provider.in_(list(PROVIDERS)))
                             .order_by(Connection.created_at))).scalars().all()
    offered: dict[str, list[str]] = {}
    for c in rows:
        p = PROVIDERS[c.provider]
        if c.provider not in offered:
            from blackmoa.services import oauth as OA
            offered[c.provider] = await OA.get(c.provider).offered(db)
        if p.write_cap not in (c.capabilities or []) or p.write_cap not in offered[c.provider]:
            continue
        try:
            ev = await p.create_event(db, c, **kw)
        except Exception as e:  # noqa: BLE001 — 약속은 그대로다
            return {"provider": p.id, "label": p.label, "status": "failed", "error": str(e)[:200]}
        return {"provider": p.id, "label": p.label, "status": "added", "event_id": ev.get("id") or "",
                "html_link": ev.get("html_link") or ""}
    return {"provider": None, "label": "", "status": "off" if rows else "no_connection"}


async def sync_connection(db: AsyncSession, conn_id: uuid.UUID) -> int | None:
    """달력 하나를 가져온다 — 푸시·주기·화면·비서 어디서 불러도 여기로 온다(plan/76)."""
    from blackmoa.services import connections as CN
    await CN.lock(db, conn_id)
    conn = await db.get(Connection, conn_id)
    if conn is None:
        return None
    await db.refresh(conn)
    if not reading(conn) or conn.status != "active":
        return None
    n = await CN.calendar_part(conn, PROVIDERS[conn.provider].sync(db, conn))
    if not (conn.sync_cursor or {}).get("calendar_error"):
        CN.synced(conn, "calendar")
    if conn.provider == "google":
        from blackmoa.services import google as G
        await G.ensure_watch(db, conn)
    await CN.announce(db, conn, "calendar")
    return n
