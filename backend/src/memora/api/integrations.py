"""데이터 연동 (plan/11, plan/59): 공급자 계정을 이어 메일·일정·연락처·알림을 가져오고 쓴다.

공급자는 services/oauth 의 등록표에서 온다. 관리자가 [연결]에서 켜고 사용자에게 준 기능만 보인다.
"""
from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Cookie, Request, Response
from fastapi.responses import RedirectResponse
from pydantic import BaseModel, Field
from sqlalchemy import select

from memora.config import get_settings
from memora.core.deps import DB, CurrentUser
from memora.core.errors import MemoraError, Unauthorized, ValidationFailed
from memora.models import Connection, User
from memora.services import connections as CN
from memora.services import jobs as J
from memora.services import oauth as OA
from memora.services.oauth import state as OST

router = APIRouter(prefix="/api/integrations", tags=["integrations"])


@router.post("/google/push", include_in_schema=False, status_code=204)
async def google_push(request: Request, db: DB):
    """Google 캘린더 변경 알림(plan/76). 본문은 없고 머리글만 온다 — 우리 채널이 맞으면 곧 가져오기를 건다.
    누구나 두드릴 수 있는 주소라 채널 id·토큰이 우리가 연 것과 맞을 때만 움직이고, 아니면 조용히 204."""
    import hmac as _hmac

    from memora.core.logging import get_logger
    from memora.services import calendar_sources as CS
    from memora.services import google as G
    log = get_logger("memora.google.push")
    cid = request.headers.get("X-Goog-Channel-ID", "")
    state = request.headers.get("X-Goog-Resource-State", "")
    token = request.headers.get("X-Goog-Channel-Token", "")
    msg = request.headers.get("X-Goog-Message-Number", "")
    conn_id = G.channel_conn(cid)
    if conn_id is None or state not in ("exists", "not_exists"):
        log.info("google push ignored", why="state" if conn_id else "channel", state=state, msg=msg)
        return Response(status_code=204)
    conn = await db.get(Connection, conn_id)
    w = ((conn.settings or {}).get("gcal_watch") or {}) if conn is not None else {}
    if conn is None or w.get("id") != cid:
        # 새 채널을 열고 옛 채널을 닫기 전에 온 알림 — 그 연결이 살아 있으면 그래도 가져온다(토큰으로 우리 것임을 확인).
        if conn is None or not _hmac.compare_digest(token, G.channel_token(conn.id, cid)):
            log.info("google push ignored", why="unknown channel", state=state, msg=msg)
            return Response(status_code=204)
    elif not _hmac.compare_digest(token, G.channel_token(conn.id, cid)):
        log.info("google push ignored", why="token", state=state, msg=msg, has_token=bool(token))
        return Response(status_code=204)
    if conn.status == "active":
        await CS.nudge(db, conn)
        await db.commit()
    log.info("google push", conn=str(conn.id), state=state, msg=msg)
    return Response(status_code=204)


def conn_out(c: Connection) -> dict:
    p = OA.PROVIDERS.get(c.provider)
    return {"id": str(c.id), "provider": c.provider, "provider_label": p.label if p else c.provider,
            "account_label": c.account_label, "capabilities": c.capabilities or [],
            # 켜려면 공급자의 동의를 한 번 더 받아야 하는 기능 — 화면이 그 스위치를 누르면 동의 화면으로 보낸다.
            "granted": p.granted_caps(c.scopes) if p else [], "status": c.status,
            "last_sync_at": c.last_sync_at.isoformat() if c.last_sync_at else None, "error": c.error,
            "created_at": c.created_at.isoformat()}


@router.get("")
async def list_integrations(user: CurrentUser, db: DB):
    """이 사람이 쓸 수 있는 연결(관리자가 켠 것)과 이미 이은 것."""
    providers = []
    for p in OA.PROVIDERS.values():
        feats = await p.offered(db)
        if feats:
            providers.append({"id": p.id, "label": p.label, "capabilities": [{"id": c} for c in feats]})
    rows = (await db.execute(select(Connection).where(Connection.owner_id == user.id).order_by(Connection.created_at))).scalars().all()
    return {"providers": providers, "connections": [conn_out(c) for c in rows if c.provider in OA.PROVIDERS]}


class StartIn(BaseModel):
    capabilities: list[str] = Field(default_factory=list, max_length=16)
    #: 연결을 마치고 돌아갈 화면 — [메일]·[스케줄]·[알림] 에서 시작했으면 그리로.
    next: str | None = None


async def start_url(db, user: User, provider: str, caps: list[str], next_url: str | None, response: Response) -> str:
    """동의 화면 주소. 이미 받은 기능은 그대로 두고 새 기능을 더 청한다(공급자의 "추가 동의")."""
    p = OA.get(provider)
    offered = await p.offered(db)
    if not offered:
        raise ValidationFailed("this connection is not available", code="provider_unavailable")
    want = [c for c in caps if c in offered]
    if not want:
        raise ValidationFailed("choose at least one feature", code="no_capability")
    conn = await CN.get(db, user.id, provider)
    have = [c for c in ((conn.capabilities or []) if conn else []) if c in offered]
    caps_all = list(dict.fromkeys([*have, *want]))
    state, nonce = OST.begin(response, provider=provider, purpose="connect", uid=str(user.id), caps=caps_all,
                             next=OST.safe_next(next_url, "/app/integrations"))
    return await p.authorize_url(db, purpose="connect", scopes=p.scopes_for(caps_all, login=False), state=state, nonce=nonce,
                                 locale=user.locale or None)


@router.post("/{provider}/start")
async def connect_start(provider: str, body: StartIn, user: CurrentUser, db: DB, response: Response):
    return {"url": await start_url(db, user, provider, body.capabilities, body.next, response)}


@router.get("/{provider}/callback")
async def connect_callback(provider: str, request: Request, db: DB, code: str | None = None, state: str | None = None,
                           error: str | None = None, memora_oauth: Annotated[str | None, Cookie()] = None):
    base = get_settings().public_url.rstrip("/")
    p = OA.PROVIDERS.get(provider)

    def to(path: str, **params: str) -> RedirectResponse:
        r = RedirectResponse(f"{base}{OST.join(path, **params)}", status_code=302)
        OST.clear(r)
        return r

    if p is None:
        return to("/app/integrations", error="provider_unknown")
    try:
        st = OST.finish(state or "", memora_oauth, provider=provider)
    except Unauthorized as e:
        return to("/app/integrations", error=e.code)
    back = OST.safe_next(st.get("next"), "/app/integrations")
    if st.get("purpose") != "connect":
        return to(back, error="bad_state")
    if error or not code:
        return to(back, error="denied")
    user = await db.get(User, uuid.UUID(str(st.get("uid"))))
    if user is None or user.status != "active":
        return RedirectResponse(f"{base}/login", status_code=302)
    try:
        tokens = await p.exchange(db, code=code, purpose="connect")
        ident = await p.identity(db, tokens, nonce=st.get("nonce") or "")
        caps = [c for c in (st.get("caps") or []) if c in await p.offered(db)]
        conn = await CN.upsert(db, user, provider, tokens, account_label=ident.label[:255], capabilities=caps, subject=ident.subject)
        missing = [c for c in caps if c not in (conn.capabilities or [])]
        await db.commit()
    except MemoraError as e:
        await db.rollback()
        return to(back, error=e.code)
    except Exception:  # noqa: BLE001
        await db.rollback()
        return to(back, error=f"{provider}_failed")
    # 동의 화면에서 뺀 항목이 있으면 그렇다고 알린다 — 켜진 줄 알았는데 안 되는 것이 가장 나쁘다.
    return to(back, connected=provider, **({"partial": ",".join(missing)} if missing else {}))


@router.post("/{conn_id}/sync", status_code=202)
async def sync_now(conn_id: uuid.UUID, user: CurrentUser, db: DB):
    c = await CN.get_owned(db, user.id, conn_id)
    await J.enqueue(db, "integration.sync", {"connection_id": str(c.id)}, priority=2, dedupe_key=f"sync:{c.id}",
                    owner_id=user.id)
    await db.commit()
    return {"queued": True}


class CapsIn(BaseModel):
    capabilities: list[str] = Field(max_length=16)
    next: str | None = None


@router.patch("/{conn_id}")
async def patch_conn(conn_id: uuid.UUID, body: CapsIn, user: CurrentUser, db: DB, response: Response):
    """기능을 켜고 끈다. 아직 공급자가 내주지 않은 권한을 켜면 바꾸지 않고 동의 화면 주소를 준다."""
    c = await CN.get_owned(db, user.id, conn_id)
    p = OA.get(c.provider)
    offered = await p.offered(db)
    want = [x for x in body.capabilities if x in offered]
    need = [x for x in want if not p.granted(c.scopes, x)]
    if need:
        return {**conn_out(c), "consent_url": await start_url(db, user, c.provider, need, body.next, response)}
    c.capabilities = sorted(set(want))
    if c.provider == "google" and "calendar_read" not in c.capabilities:
        from memora.services import google as G
        await G.stop_watch(db, c)
    await CN.announce(db, c, "settings")
    await db.commit()
    return {**conn_out(c), "consent_url": None}


@router.delete("/{conn_id}")
async def disconnect(conn_id: uuid.UUID, user: CurrentUser, db: DB):
    c = await CN.get_owned(db, user.id, conn_id)
    await CN.remove(db, c)
    await db.commit()
    return {"ok": True}
