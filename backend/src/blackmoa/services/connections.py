"""데이터 연동의 연결 한 줄 — 공급자와 상관없이 같은 일 (plan/59).

``connections`` 한 줄이 "이 사람의 이 공급자 계정" 이다. 토큰은 암호화해 두고, 만료가 가까우면 공급자의
갱신 창구로 새로 받는다. 공급자가 거절하면(갱신 토큰 만료·철회) 연결을 "다시 연결 필요" 로 두고 주인에게
알린다. 끊을 때는 공급자 쪽 권한도 거둔다.

무엇을 가져오고 쓰는지(메일·일정·연락처·알림)는 각 데이터 서비스의 몫이고, 여기는 "열쇠" 만 맡는다.
"""
from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from blackmoa.core.errors import NotFound, ServiceUnavailable
from blackmoa.core.security import decrypt, encrypt
from blackmoa.models import Connection, User
from blackmoa.services import jobs as J
from blackmoa.services import oauth as OA


async def get(db: AsyncSession, owner_id: uuid.UUID, provider: str) -> Connection | None:
    return (await db.execute(select(Connection).where(Connection.owner_id == owner_id, Connection.provider == provider,
                                                     Connection.status.in_(("active", "error")))
                             .order_by(Connection.created_at))).scalars().first()


async def get_owned(db: AsyncSession, owner_id: uuid.UUID, conn_id: uuid.UUID) -> Connection:
    c = await db.get(Connection, conn_id)
    if c is None or c.owner_id != owner_id:
        raise NotFound("connection not found", code="connection_not_found")
    return c


async def upsert(db: AsyncSession, owner: User, provider: str, tokens: dict[str, Any], *, account_label: str,
                 capabilities: list[str], subject: str | None = None) -> Connection:
    """코드를 바꾼 뒤: 이 사람의 이 공급자 연결은 한 줄이다. 있으면 새 토큰으로, 없으면 새 줄.

    다른 계정으로 다시 이었으면(``subject`` 가 다르면) 앞 계정에서 가져온 것은 지우고 새로 시작한다 —
    남의 메일·일정이 섞이지 않게. 기능은 **공급자가 실제로 내준 권한**만 켠다. 동의 화면에서 사용자가
    항목을 뺐으면 그 기능은 켜지 않는다.
    """
    p = OA.get(provider)
    conn = (await db.execute(select(Connection).where(Connection.owner_id == owner.id, Connection.provider == provider)
                             .order_by(Connection.created_at))).scalars().first()
    if conn is None:
        conn = Connection(owner_id=owner.id, provider=provider, account_label=account_label, settings={})
        db.add(conn)
    else:
        before = (conn.settings or {}).get("subject")
        if subject and before and before != subject:
            await db.execute(text("DELETE FROM integration_emails WHERE connection_id = :c"), {"c": conn.id})
            await db.execute(text("DELETE FROM integration_events WHERE connection_id = :c"), {"c": conn.id})
            conn.sync_cursor = {}
            conn.scopes = []
            conn.capabilities = []
            conn.refresh_token_enc = None
        conn.account_label = account_label
    if subject:
        conn.settings = {**(conn.settings or {}), "subject": subject}
    _store(conn, tokens)
    conn.scopes = sorted(set(p.token_scopes(tokens)) | set(conn.scopes or []))
    granted = set(p.granted_caps(conn.scopes))
    conn.capabilities = sorted((set(capabilities) | set(conn.capabilities or [])) & granted)
    conn.status = "active"
    conn.error = None
    await db.flush()
    await J.enqueue(db, "integration.sync", {"connection_id": str(conn.id)}, priority=4, dedupe_key=f"sync:{conn.id}",
                    owner_id=conn.owner_id)
    return conn


def _store(conn: Connection, tokens: dict[str, Any]) -> None:
    conn.access_token_enc = encrypt(tokens["access_token"])
    if tokens.get("refresh_token"):
        conn.refresh_token_enc = encrypt(tokens["refresh_token"])
    conn.token_expires_at = datetime.now(UTC) + timedelta(seconds=int(tokens.get("expires_in") or 3600))


async def access_token(db: AsyncSession, conn: Connection) -> str:
    """쓸 수 있는 접근 토큰. 곧 끝나면 갱신한다.

    관리자가 [연결] 에서 그 공급자를 끄면 여기서 막힌다 — 메일·일정·알림 어느 길로도 공급자에 닿지 않는다.
    """
    p = OA.PROVIDERS.get(conn.provider)
    if p is None or not await p.ready(db):
        raise ServiceUnavailable(f"{conn.provider} is turned off", code=f"{conn.provider}_not_configured")
    if conn.token_expires_at and conn.token_expires_at > datetime.now(UTC) + timedelta(seconds=60):
        return decrypt(conn.access_token_enc)
    refresh = decrypt(conn.refresh_token_enc) if conn.refresh_token_enc else ""
    if not refresh:
        await _expired(db, conn, "no refresh token")
        raise ServiceUnavailable(f"{conn.provider} connection expired", code=f"{conn.provider}_expired")
    try:
        tok = await OA.get(conn.provider).refresh(db, refresh)
    except OA.OAuthError as e:
        if getattr(e, "status", 0) in (400, 401):
            await _expired(db, conn, getattr(e, "body", "") or str(e))
        raise ServiceUnavailable(f"{conn.provider} refresh failed", code=f"{conn.provider}_expired") from e
    _store(conn, tok)       # 카카오는 갱신 토큰 수명이 얼마 남지 않으면 새 갱신 토큰도 준다
    return tok["access_token"]


async def _expired(db: AsyncSession, conn: Connection, why: str) -> None:
    conn.status = "expired"
    conn.error = why[:300]
    await J.enqueue(db, "notify.evaluate", {"event": "integration_error", "owner_id": str(conn.owner_id), "urgency": 2,
                                            "detail": conn.provider}, dedupe_key=f"integration_error:{conn.id}")


async def remove(db: AsyncSession, conn: Connection) -> None:
    """연결을 끊는다 — 공급자 쪽 권한을 거두고(실패해도 여기서는 끊는다), 가져온 것을 지운다."""
    if conn.provider == "google":
        # 달력 변경 알림 채널부터 닫는다 — 권한을 거두고 나면 닫을 토큰이 없다.
        from blackmoa.services import google as G
        await G.stop_watch(db, conn)
    p = OA.PROVIDERS.get(conn.provider)
    if p is not None:
        try:
            # 받은 권한 전부를 거둔다(지금 꺼 둔 기능의 권한도 받은 채로 남아 있다). 로그인에 쓰는 것은 공급자가 가린다.
            data_scopes = [s for c in p.capabilities if p.granted(conn.scopes, c.id) for s in c.scopes]
            access = decrypt(conn.access_token_enc) if conn.access_token_enc else ""
            refresh = decrypt(conn.refresh_token_enc) if conn.refresh_token_enc else ""
            if refresh and not (conn.token_expires_at and conn.token_expires_at > datetime.now(UTC) + timedelta(seconds=30)):
                # 권한을 거두는 요청에도 살아 있는 토큰이 필요하다(카카오).
                access = (await p.refresh(db, refresh)).get("access_token") or access
            await p.revoke(db, access_token=access, refresh_token=refresh, scopes=sorted(set(data_scopes)))
        except Exception:  # noqa: BLE001 — 공급자가 답하지 않아도 우리 쪽은 끊는다
            pass
    await db.execute(text("DELETE FROM integration_emails WHERE connection_id = :c"), {"c": conn.id})
    await db.execute(text("DELETE FROM integration_events WHERE connection_id = :c"), {"c": conn.id})
    await db.execute(text("DELETE FROM notification_channels WHERE kind = 'kakao' AND config_public->>'connection_id' = :c"),
                     {"c": str(conn.id)})
    conn.status = "removed"
    await announce(db, conn)
    await db.delete(conn)


# ── 가져오기의 공용 틀 (plan/76) ────────────────────────────────────────
#
# 가져오기는 여러 곳에서 시작된다: 연결 직후, [지금 동기화], 주기 작업, Google 의 변경 알림(푸시), 화면을 열었을 때,
# 비서가 일정을 볼 때. 어디서 시작하든 (1) 한 연결은 한 번에 하나만 돌고 (2) 끝나면 "마지막 동기화" 를 한 곳에
# 찍고 (3) 성공·실패를 열린 화면에 바로 알린다. 예전에는 달력 자동 가져오기가 연결의 "마지막 동기화" 를 찍지
# 않았고, 끝나도 화면이 몰라 새로 고칠 때까지 "–" 로 남았다.

#: 다시 해도 같은 답이 올 실패 — 권한·설정 문제. 다섯 번 되풀이하지 않고 적어 두고 알린다.
PERMANENT = (400, 403, 404)


async def lock(db: AsyncSession, conn_id: uuid.UUID) -> None:
    """이 연결의 가져오기를 하나씩 — 지우고 다시 넣는 가져오기가 겹치면 같은 일정이 두 번 들어간다. 트랜잭션이 끝나면 풀린다."""
    await db.execute(text("SELECT pg_advisory_xact_lock(hashtext(:k))"), {"k": f"conn-sync:{conn_id}"})


def synced(conn: Connection, part: str | None = None) -> None:
    """가져오기가 끝났다. ``part``(calendar·contacts·mail)의 지난 실패도 지운다."""
    conn.last_sync_at = datetime.now(UTC)
    conn.status = "active"
    cur = dict(conn.sync_cursor or {})
    if part:
        cur.pop(f"{part}_error", None)
    conn.sync_cursor = cur
    # 다른 부분의 실패가 남아 있으면 그것을 보인다.
    left = [v for k, v in cur.items() if k.endswith("_error") and v]
    conn.error = left[0] if left else None


def failed(conn: Connection, part: str, code: str) -> None:
    """그 부분만 실패했다 — 연결은 살아 있다(다른 부분은 계속 가져온다)."""
    cur = dict(conn.sync_cursor or {})
    cur[f"{part}_error"] = code
    conn.sync_cursor = cur
    conn.error = code


def error_code(part: str, e: Exception) -> str:
    from blackmoa.providers.http import ProviderHTTPError
    if isinstance(e, ProviderHTTPError) and e.status in (401, 403):
        return f"{part}_forbidden"
    return f"{part}_failed"


async def announce(db: AsyncSession, conn: Connection, part: str = "all") -> None:
    """열린 화면(연동·스케줄·메일·인맥)이 새로 읽게 한다 — 소식만, 내용은 화면이 다시 묻는다."""
    from blackmoa.core import bus
    await bus.publish(db, owner_id=conn.owner_id, kind="connection", data={
        "id": str(conn.id), "provider": conn.provider, "part": part, "status": conn.status, "error": conn.error,
        "last_sync_at": conn.last_sync_at.isoformat() if conn.last_sync_at else None})


async def sync_all(db: AsyncSession, conn: Connection) -> dict[str, int]:
    """이 연결이 받은 기능대로 가져온다."""
    await lock(db, conn.id)
    await db.refresh(conn)
    try:
        return await _sync_all(db, conn)
    finally:
        await announce(db, conn)


async def _sync_all(db: AsyncSession, conn: Connection) -> dict[str, int]:
    if conn.provider == "imap":
        # 메일함 연결(plan/74) — OAuth 공급자가 아니다. 앱 비밀번호가 틀리면 imap_mail 이 연결을 만료로 적는다.
        from blackmoa.services import imap_mail as IM
        try:
            out = {"emails": await IM.sync(db, conn)}
        except ServiceUnavailable as e:
            conn.error = e.message
            raise
        synced(conn, "mail")
        return out
    p = OA.PROVIDERS.get(conn.provider)
    if p is None or not await p.ready(db):
        # 관리자가 꺼 둔 동안은 가져오지 않는다. 연결의 오류로 적지도 않는다 — 사용자의 잘못이 아니다.
        return {}
    owner = await db.get(User, conn.owner_id)
    out: dict[str, int] = {}
    caps = set(conn.capabilities or [])
    try:
        if conn.provider == "google":
            from blackmoa.services import google as G
            out = await G.sync_all(db, conn, owner)
        elif conn.provider == "kakao" and "calendar_read" in caps:
            from blackmoa.services import kakao as K
            out["events"] = await calendar_part(conn, K.sync_calendar(db, conn))
        if not any(k.endswith("_error") and v for k, v in (conn.sync_cursor or {}).items()):
            synced(conn)
        else:
            conn.last_sync_at = datetime.now(UTC)
    except ServiceUnavailable as e:
        conn.error = e.message
        raise
    return out


async def calendar_part(conn: Connection, coro: Any) -> int:
    """일정 가져오기 한 부분. 권한·설정 실패는 적어 두고 다른 부분은 계속한다 — 되풀이해도 같은 답이다."""
    from blackmoa.providers.http import ProviderHTTPError
    try:
        n = await coro
    except ProviderHTTPError as e:
        if e.status not in PERMANENT:
            raise
        failed(conn, "calendar", error_code("calendar", e))
        return 0
    cur = dict(conn.sync_cursor or {})
    cur.pop("calendar_error", None)
    conn.sync_cursor = cur
    return n


#: 메일함은 알려 주지 않는다(IMAP IDLE 은 연결을 계속 붙들어야 한다) — 이만큼마다 새 메일을 본다.
MAIL_EVERY = timedelta(minutes=10)
#: 메일 화면을 열었을 때 이보다 오래됐으면 먼저 가져온다.
MAIL_FRESH = timedelta(minutes=3)


async def due(db: AsyncSession, now: datetime | None = None) -> list[uuid.UUID]:
    """때가 된 연결 — 메일함(10분)과 Google 연락처(하루). 달력은 calendar_sources.due 가 따로 본다(plan/76)."""
    from blackmoa.services import google as G
    now = now or datetime.now(UTC)
    rows = (await db.execute(select(Connection).where(Connection.status == "active",
                                                      Connection.provider.in_(("imap", "google"))))).scalars().all()
    out = []
    for c in rows:
        caps = set(c.capabilities or [])
        if c.provider == "imap" and "mail_read" in caps and (c.last_sync_at is None or now - c.last_sync_at >= MAIL_EVERY):
            out.append(c.id)
        elif c.provider == "google" and "contacts" in caps and G.contacts_due(c, now):
            out.append(c.id)
    return out
