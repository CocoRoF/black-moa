from __future__ import annotations

import io
import json
import zipfile
from datetime import UTC, datetime

from fastapi import APIRouter, Request, Response
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy import select

from blackmoa.core import pools
from blackmoa.core import visibility as VIS
from blackmoa.core.deps import DB, CurrentUser, client_ip
from blackmoa.core.errors import ValidationFailed
from blackmoa.models import (
    AuthSession,
    Conversation,
    Fact,
    KnowledgeDocument,
    Message,
    NetworkEdge,
    NetworkNode,
)
from blackmoa.services import accounts as A
from blackmoa.services import audit
from blackmoa.services import outbound_mail as OM
from blackmoa.services import profile as PF

router = APIRouter(prefix="/api/users", tags=["users"])


class MeUpdate(BaseModel):
    display_name: str | None = Field(default=None, max_length=120)
    nickname: str | None = Field(default=None, max_length=60)
    # Confirming the legal name is a deliberate act, not a side effect of editing it.
    confirm_name: bool | None = None
    locale: str | None = None
    timezone: str | None = None
    avatar_url: str | None = None
    onboarding_state: dict | None = None
    page_indexable: bool | None = None
    #: "all", "friends" or "none" — who may see the people I am connected to (plan/43 §5).
    network_public: str | None = None


@router.patch("/me")
async def update_me(body: MeUpdate, user: CurrentUser, db: DB):
    if body.display_name is not None:
        new_name = body.display_name.strip()
        if new_name and new_name != user.display_name:
            user.display_name = new_name
            user.name_confirmed_at = None   # a changed legal name has not been confirmed yet
    if body.nickname is not None:
        user.nickname = body.nickname.strip()[:60] or None
    if body.confirm_name:
        from datetime import UTC, datetime
        user.name_confirmed_at = datetime.now(UTC)
    if body.locale in ("ko", "en"):
        user.locale = body.locale
    if body.timezone:
        from zoneinfo import ZoneInfo
        try:
            ZoneInfo(body.timezone)
            user.timezone = body.timezone
        except Exception:
            pass
    if body.avatar_url is not None:
        user.avatar_url = body.avatar_url[:2000]
    if body.onboarding_state is not None:
        user.onboarding_state = {**(user.onboarding_state or {}), **body.onboarding_state}
    if body.page_indexable is not None:
        user.page_indexable = bool(body.page_indexable)
    # 옛 말(all/friends/none)도 받아 주되 저장은 정본으로 (plan/48 §2). 오래된
    # 화면이 남아 있을 수 있고, 모르는 값을 그대로 넣으면 그 칸이 뜻을 잃는다.
    if body.network_public in ("all", "friends", "none", *VIS.LEVELS):
        user.network_public = VIS.normalize({"all": "public", "friends": "known", "none": "private"}
                                            .get(body.network_public, body.network_public))
    await db.commit()
    from blackmoa.api.auth import _user_out
    return _user_out(user)


class MailHandleIn(BaseModel):
    handle: str = Field(max_length=64)


@router.get("/me/mail-handle")
async def mail_handle_status(user: CurrentUser, db: DB, handle: str | None = None):
    """The current address, plus whether a proposed one is free.

    Availability is answered as the person types, so the domain travels with it — an id on
    its own means nothing until you can see the address it makes.
    """
    domain = await OM.sending_domain(db)
    out: dict = {"handle": user.mail_handle or "", "domain": domain,
                 "address": f"{user.mail_handle}@{domain}" if (user.mail_handle and domain) else ""}
    if handle is not None:
        try:
            candidate = OM.clean_handle(handle)
        except ValidationFailed as e:
            out["check"] = {"ok": False, "code": e.code, "message": e.message}
            return out
        taken = await OM.handle_taken(db, candidate, exclude=user.id)
        out["check"] = {"ok": not taken, "handle": candidate,
                        "address": f"{candidate}@{domain}" if domain else "",
                        "code": "handle_taken" if taken else None,
                        "message": "이미 사용 중인 아이디예요" if taken else None}
    return out


@router.put("/me/mail-handle")
async def set_mail_handle(body: MailHandleIn, user: CurrentUser, db: DB):
    handle = await OM.claim_handle(db, user=user, raw=body.handle)
    await db.commit()
    domain = await OM.sending_domain(db)
    return {"handle": handle, "domain": domain, "address": f"{handle}@{domain}" if domain else ""}


class PasswordIn(BaseModel):
    current_password: str = ""
    new_password: str = Field(min_length=8)


@router.post("/me/password")
async def change_password(body: PasswordIn, user: CurrentUser, db: DB, request: Request, response: Response):
    """Change the password, keep this device signed in.

    Every session is revoked (that is the point of changing a password), then a new
    one is issued for the caller: the response carries a fresh access token and sets
    a fresh refresh cookie, so the person changing their password is not the one who
    gets logged out.
    """
    await A.change_password(db, user, body.current_password, body.new_password)
    ip, ua = client_ip(request), request.headers.get("user-agent", "")
    access, raw, _ = await A.issue_session(db, user, ip=ip, ua=ua)
    audit.record(db, "password_changed", actor_id=user.id, target_type="user", target_id=user.id, ip=ip, ua=ua)
    await db.commit()
    from blackmoa.api.auth import _set_refresh, _user_out
    _set_refresh(response, raw)
    return {"ok": True, "access_token": access, "user": _user_out(user)}


@router.get("/me/sessions")
async def sessions(user: CurrentUser, db: DB):
    rows = (await db.execute(select(AuthSession).where(AuthSession.user_id == user.id, AuthSession.revoked_at.is_(None))
                             .order_by(AuthSession.created_at.desc()).limit(50))).scalars().all()
    return {"items": [{"id": str(s.id), "ua": s.ua, "ip": s.ip, "created_at": s.created_at.isoformat(), "expires_at": s.expires_at.isoformat()} for s in rows]}


@router.get("/me/profile")
async def get_profile(user: CurrentUser, db: DB):
    await PF.get(db, user.id)
    await db.commit()
    # 기업 기능이 꺼져 있으면 소속과 인증한 회사는 내 정보에도 없다 (plan/71). 저장된 것은 남는다.
    p = await PF.shown(db, user.id)
    return {"data": p.data, "visibility": p.visibility, "updated_at": p.updated_at.isoformat()}


class ProfileIn(BaseModel):
    data: dict | None = None
    visibility: dict | None = None


@router.put("/me/profile")
async def put_profile(body: ProfileIn, user: CurrentUser, db: DB):
    await PF.update(db, user.id, data=body.data, visibility=body.visibility)
    await db.commit()
    p = await PF.shown(db, user.id)
    return {"data": p.data, "visibility": p.visibility, "updated_at": p.updated_at.isoformat()}


def _zip_export(entries: list[tuple[str, str]]) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for name, payload in entries:
            z.writestr(name, payload)
    return buf.getvalue()


@router.get("/me/export")
async def export_me(user: CurrentUser, db: DB):
    dumps = lambda o: json.dumps(o, ensure_ascii=False, indent=2, default=str)  # noqa: E731
    entries: list[tuple[str, str]] = []
    p = await PF.get(db, user.id)
    entries.append(("profile.json", dumps({"data": p.data, "visibility": p.visibility})))
    facts = (await db.execute(select(Fact).where(Fact.owner_id == user.id))).scalars().all()
    entries.append(("facts.json", dumps([{"subject": f.subject, "predicate": f.predicate, "object": f.object, "kind": f.kind,
                                          "visibility": f.visibility, "status": f.status} for f in facts])))
    nodes = (await db.execute(select(NetworkNode).where(NetworkNode.owner_id == user.id))).scalars().all()
    edges = (await db.execute(select(NetworkEdge).where(NetworkEdge.owner_id == user.id))).scalars().all()
    entries.append(("network.json", dumps({"nodes": [{"id": str(n.id), "kind": n.kind, "name": n.name, "attrs": n.attrs, "tags": n.tags} for n in nodes],
                                           "edges": [{"src": str(e.src_id), "dst": str(e.dst_id), "rel": e.rel} for e in edges]})))
    docs = (await db.execute(select(KnowledgeDocument).where(KnowledgeDocument.owner_id == user.id))).scalars().all()
    entries.append(("knowledge.json", dumps([{"title": d.title, "kind": d.kind, "preview": d.text_preview} for d in docs])))
    convs = (await db.execute(select(Conversation).where(Conversation.owner_id == user.id))).scalars().all()
    for c in convs:
        msgs = (await db.execute(select(Message).where(Message.conversation_id == c.id).order_by(Message.created_at))).scalars().all()
        entries.append((f"conversations/{c.audience}-{c.id}.json", dumps([{"role": m.role, "content": m.content, "at": m.created_at.isoformat()} for m in msgs])))
    data = await pools.to_thread("misc", _zip_export, entries)  # compression off the event loop
    return StreamingResponse(iter([data]), media_type="application/zip",
                             headers={"Content-Disposition": f"attachment; filename=blackmoa-export-{datetime.now(UTC):%Y%m%d}.zip"})


@router.delete("/me")
async def delete_me(user: CurrentUser, db: DB):
    if user.role == "admin":
        from sqlalchemy import func

        from blackmoa.core.errors import Conflict
        from blackmoa.models import User
        admins = int((await db.execute(select(func.count(User.id)).where(User.role == "admin", User.status == "active"))).scalar_one())
        if admins <= 1:
            raise Conflict("last admin cannot delete their account", code="last_admin")
    # 계정을 지우면 그 사람을 가리키는 줄이 여러 표에서 함께 지워진다. 그 순간 다른 요청(상대의 화면, 일꾼)이 같은
    # 줄을 잡고 있으면 데이터베이스가 교착으로 한쪽을 끊는다 — 드물지만 "탈퇴가 안 된다" 가 된다. 잠깐 뒤 다시 한다.
    import asyncio

    from sqlalchemy.exc import DBAPIError

    from blackmoa.models import User as _User

    uid, email = user.id, user.email
    await A.purge_user_storage(db, uid)
    for attempt in range(3):
        try:
            me = await db.get(_User, uid)
            if me is None:
                return {"ok": True}
            audit.record(db, "account_deleted", actor_id=uid, target_type="user", target_id=uid, meta={"email": email})
            await db.delete(me)
            await db.commit()
            return {"ok": True}
        except DBAPIError as e:
            await db.rollback()
            if "deadlock" not in str(e).lower() or attempt == 2:
                raise
            await asyncio.sleep(0.3 * (attempt + 1))
    return {"ok": True}


class CommunityNameIn(BaseModel):
    name: str


@router.get("/me/community-name")
async def my_community_name(user: CurrentUser, db: DB):
    """광장에서 쓰는 이름 (plan/52).

    **내 정보의 다른 칸과 성격이 다르다.** 공개 범위가 없다: 아무에게도 내 계정과
    함께 나가지 않는다. 여기 있는 이유는 하나뿐이고, 정하는 자리가 여기가 맞아서다.
    """
    from blackmoa.services import community as C

    return {"name": (user.community_name or ""), "wait_days": C.name_wait_days(user),
            "change_days": C.NAME_CHANGE_DAYS}


@router.put("/me/community-name")
async def set_my_community_name(body: CommunityNameIn, user: CurrentUser, db: DB):
    from blackmoa.services import community as C

    await C.set_community_name(db, user, body.name)
    await db.commit()
    return {"name": user.community_name or "", "wait_days": C.name_wait_days(user),
            "change_days": C.NAME_CHANGE_DAYS}
