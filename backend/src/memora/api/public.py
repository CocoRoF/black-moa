"""Visitor-facing API (plan/12). Auth: visitor JWT except link lookup + visitor creation."""
from __future__ import annotations

import contextlib
import hashlib
import uuid
from datetime import UTC, datetime
from pathlib import Path

from fastapi import APIRouter, File, Request, UploadFile
from fastapi.responses import FileResponse, Response
from pydantic import BaseModel, Field
from sqlalchemy import select

from memora.config import get_settings
from memora.core import pools
from memora.core.codes import LINK_PREFIX
from memora.core.deps import DB, CurrentVisitor, OptionalUser, client_ip
from memora.core.errors import Forbidden, NotFound, ValidationFailed
from memora.core.ratelimit import limiter
from memora.core.security import create_visitor_token, sha256, verify_state
from memora.models import Agent, KnowledgeDocument, ShareLink, Turn, User, Visitor
from memora.pipeline.events import journals
from memora.pipeline.runner import TurnRequest, cancel_turn, launch_turn, start_turn
from memora.services import agents as AG
from memora.services import conversations as CV
from memora.services import credits as CR
from memora.services import inbox as I
from memora.services import legal as LEGAL
from memora.services import profile as PF
from memora.services import settings as S
from memora.services import uploads as UP_SVC
from memora.services import voice as VOICE

router = APIRouter(prefix="/api/public", tags=["public"])


async def _resolve_link(db, code: str):
    link = await AG.get_link_by_code(db, code)
    if link is None:
        raise NotFound("link not found", code="link_not_found")
    agent = await db.get(Agent, link.agent_id)
    owner = await db.get(User, link.owner_id)
    if agent is None or owner is None or owner.status != "active":
        raise NotFound("link not found", code="link_not_found")
    return link, agent, owner


def _public_agent(agent: Agent, owner: User, status: str, resting: bool, owner_name: str = "", visitor_name: str | None = None, *,
                  voice: dict[str, bool]) -> dict:
    owner_name = owner_name or (owner.display_name or "")
    # 비서가 음성을 허락해도 서비스가 끈 것은 없다(plan/67). 받아쓰기(마이크)와 읽어 주기(음성으로 듣기)를 따로.
    allowed = bool((agent.capabilities or {}).get("voice", True))
    stt, tts = allowed and voice["stt"], allowed and voice["tts"]
    greeting, role_line = AG.display_texts(agent, owner_name)
    greeting = AG.personalize_greeting(greeting, visitor_name, language=agent.language or "ko")
    return {"name": agent.name, "role_line": role_line, "avatar_url": agent.avatar_url, "cover_url": agent.cover_url,
            # 무대(plan/71)에 설 그림: 올린 원본(동그라미로 자르기 전), 고른 얼굴이면 그 전신 그림. 없으면 프로필 사진.
            "character_url": AG.stage_figure(agent), "greeting": greeting,
            "suggested_questions": agent.suggested_questions or [], "theme": agent.theme or {}, "language": agent.language,
            "owner_display_name": owner_name, "voice_enabled": stt or tts, "stt_enabled": stt, "tts_enabled": tts,
            "leave_message_enabled": bool((agent.capabilities or {}).get("leave_message", True)),
            "collect_identity": (agent.visitor_settings or {}).get("collect_identity", "ask"),
            "require_turnstile": bool((agent.visitor_settings or {}).get("require_turnstile")), "status": status, "resting": resting,
            # 방문자 입력칸의 📎·붙여넣기·끌어다 놓기가 이것을 본다 (plan/55 §6-3).
            "files": _visitor_files(agent)}


def _visitor_files(agent: Agent) -> dict:
    from memora.services import files as FILES
    r = FILES.visitor_file_rules(agent)
    return {"accept": r["accept"], "per_day": r["per_day"], "max_mb": r["max_bytes"] // (1024 * 1024)}


@router.get("/branding")
async def branding(db: DB):
    return {"service_name": await S.get(db, "branding.service_name"), "tagline": await S.get(db, "branding.tagline"),
            "logo_url": await S.get(db, "branding.logo_url"), "turnstile_site_key": await S.get(db, "public.turnstile_site_key"),
            # The visitor door offers "sign up" only where signing up is actually open.
            "signup_mode": await S.get(db, "signup.mode")}


@router.get("/legal")
async def legal(db: DB):
    """이용약관·개인정보 처리방침(마크다운, 운영자 정보를 채운 것), 동의받는 판, 바닥글에 보일 운영자 정보 (plan/73)."""
    out = await LEGAL.documents(db)
    out["service_name"] = out["service"]
    return out


@router.get("/uploads/{upload_id}")
async def public_upload(upload_id: uuid.UUID, db: DB):
    """Public read for avatar uploads only (used by visitor pages / OG images)."""
    from memora.models import Upload
    up = await db.get(Upload, upload_id)
    if up is None or up.kind != "avatar":
        raise NotFound("not found")
    from memora.services import objectstore
    if up.storage_path.startswith(objectstore.S3_PREFIX):
        return Response(await objectstore.get(up.storage_path), media_type=up.mime,
                        headers={"Cache-Control": "public, max-age=86400"})
    return FileResponse(up.storage_path, media_type=up.mime, headers={"Cache-Control": "public, max-age=86400"})


@router.get("/people/{handle}")
async def public_person(handle: str, db: DB, account: OptionalUser = None):
    """A person's own page, readable by anyone (plan/41 §3).

    The page exists once they have an address and a secretary they published: both are
    choices they made, and nothing here publishes a field they kept private.
    """
    from memora.services import people as P

    target = await P.by_handle(db, handle)
    if target is None:
        raise NotFound("page not found", code="page_not_found")
    link = (await db.execute(select(ShareLink).where(ShareLink.owner_id == target.id, ShareLink.status == "active")
                             .order_by(ShareLink.created_at))).scalars().first()
    agent = await db.get(Agent, link.agent_id) if link is not None else None
    if link is None or agent is None or agent.status != "active":
        raise NotFound("page not open", code="page_not_open")
    status = AG.link_effective_status(link, agent)
    resting = (await CR.available_balance(db, target.id)) <= 0
    name = await PF.display_name_for(db, target, audience="visitor", policy=agent.disclosure_policy or {})
    who = await P.viewer_level(db, target.id, account.id if account else None)
    from memora.services import blog as B

    posts = await B.published(db, target.id, account, limit=24)
    return {"handle": target.mail_handle, "user_id": str(target.id), "display_name": name, "avatar_url": target.avatar_url,
            "indexable": bool(target.page_indexable),
            "fields": await P.public_fields(db, target, who),
            "secretary": {**_public_agent(agent, target, status, resting, name, voice=await VOICE.availability(db)), "code": link.code},
            "posts": [B.out(p) for p in posts],
            "account": {"signed_in": account is not None, "is_owner": bool(account and account.id == target.id)}}


@router.get("/posts/images/{upload_id}")
async def post_image(upload_id: uuid.UUID, db: DB, t: str = ""):
    """A photo on somebody's post (plan/42 §3).

    Signed rather than session-authenticated: an <img> tag cannot carry a bearer token, and
    a visitor reading a public page has no session at all. The signature names the post it
    was issued for and expires on its own, so a friends-only photo is never one guessed id
    away — the address only exists because somebody who could read the post was handed it.
    """
    from memora.core.security import verify_state
    from memora.models import BlogPost, Upload
    from memora.services import objectstore

    try:
        claim = verify_state(t)
    except Exception as e:  # noqa: BLE001
        raise NotFound("image not found", code="image_not_found") from e
    if claim.get("up") != str(upload_id):
        raise NotFound("image not found", code="image_not_found")
    post = await db.get(BlogPost, uuid.UUID(str(claim.get("post"))))
    if post is None or post.status != "published" or str(upload_id) not in (post.images or []):
        raise NotFound("image not found", code="image_not_found")
    up = await db.get(Upload, upload_id)
    if up is None:
        raise NotFound("image not found", code="image_not_found")
    return Response(await objectstore.get(up.storage_path), media_type=up.mime,
                    headers={"Cache-Control": "private, max-age=3600"})


@router.get("/people/{handle}/posts/{slug}")
async def public_post(handle: str, slug: str, db: DB, account: OptionalUser = None):
    """One post on somebody's own page. A post the reader may not see is not announced as
    existing (plan/41 §4)."""
    from memora.services import blog as B
    from memora.services import people as P

    target = await P.by_handle(db, handle)
    if target is None:
        raise NotFound("page not found", code="page_not_found")
    post = await B.by_slug(db, target.id, slug, account)
    post.view_count += 1
    await db.commit()
    return {"handle": target.mail_handle,
            "display_name": await PF.display_name_for(db, target, audience="visitor"),
            "avatar_url": target.avatar_url, "indexable": bool(target.page_indexable),
            "post": B.out(post, full=True)}


@router.get("/sitemap")
async def sitemap(db: DB, limit: int = 2000):
    """The public addresses a search engine may list (plan/41 §2).

    Only people whose page actually opens, and only those who left search listing on. A
    post appears under its author, so an unlisted person takes their posts with them.
    """
    from memora.models import BlogPost

    rows = (await db.execute(
        select(User, ShareLink.code).join(ShareLink, ShareLink.owner_id == User.id)
        .join(Agent, Agent.id == ShareLink.agent_id)
        .where(User.status == "active", User.page_indexable.is_(True), User.mail_handle.isnot(None),
               ShareLink.status == "active", Agent.status == "active")
        .order_by(User.created_at).limit(limit))).all()
    seen: dict[str, User] = {}
    for u, _code in rows:
        seen.setdefault(str(u.id), u)
    if not seen:
        return {"people": []}
    posts = (await db.execute(
        select(BlogPost).where(BlogPost.owner_id.in_([u.id for u in seen.values()]),
                               BlogPost.status == "published", BlogPost.visibility == "public")
        .order_by(BlogPost.published_at.desc()).limit(limit * 5))).scalars().all()
    by_owner: dict[uuid.UUID, list] = {}
    for post in posts:
        by_owner.setdefault(post.owner_id, []).append(post)
    return {"people": [
        {"handle": u.mail_handle,
         "updated_at": max([p.published_at for p in by_owner.get(u.id, []) if p.published_at] or [u.created_at]).isoformat(),
         "posts": [{"slug": p.slug, "updated_at": (p.updated_at or p.published_at).isoformat()}
                   for p in by_owner.get(u.id, [])]}
        for u in seen.values()]}


@router.get("/links/{code}")
async def get_link(code: str, db: DB, account: OptionalUser = None):
    link, agent, owner = await _resolve_link(db, code)
    status = AG.link_effective_status(link, agent)
    resting = (await CR.available_balance(db, owner.id)) <= 0
    return {"agent": _public_agent(agent, owner, status, resting,
                                   await PF.display_name_for(db, owner, audience="visitor", policy=agent.disclosure_policy or {}),
                                   voice=await VOICE.availability(db)),
            "link": {"code": link.code, "status": status, "layout": AG.link_layout(link)},
            # One browser, one identity. The page needs to know whether the person reading
            # it is signed in — and whether this is their own secretary — before it decides
            # to ask them who they are.
            "account": {"signed_in": account is not None, "name": _visitor_name(account) if account else "",
                        "is_owner": bool(account and account.id == owner.id),
                        "agent_id": str(agent.id) if account and account.id == owner.id else None}}


def _visitor_name(account: User) -> str:
    """What a secretary should call this person: the nickname they chose for exactly this,
    falling back to the account name."""
    return (account.nickname or account.display_name or "").strip()


class VisitorIn(BaseModel):
    existing_token: str | None = None
    display_name: str | None = Field(default=None, max_length=120)
    turnstile_token: str | None = None


async def _enforce_turnstile(db, agent: Agent, token: str, ip: str) -> None:
    if not (agent.visitor_settings or {}).get("require_turnstile"):
        return
    site_key = str(await S.get(db, "public.turnstile_site_key") or "").strip()
    secret = str(await S.get(db, "public.turnstile_secret") or "").strip()
    # Fail closed for both new and legacy configurations. A checkbox without a
    # complete server/client key pair must never silently disable bot defense.
    if not site_key or not secret:
        raise Forbidden("turnstile is required but not configured", code="turnstile_not_configured")
    if not token or not await _verify_turnstile(secret, token, ip):
        raise Forbidden("turnstile failed", code="turnstile_failed")


@router.post("/links/{code}/visitor")
async def create_visitor(code: str, body: VisitorIn, request: Request, db: DB, account: OptionalUser = None):
    link, agent, owner = await _resolve_link(db, code)
    status = AG.link_effective_status(link, agent)
    if status != "active":
        raise Forbidden("link not active", code=f"link_{status}")
    # The owner is not a visitor to their own secretary — a stranger row for them would put
    # their own account in their own inbox and network graph. The page runs the simulator
    # instead, which is the same conversation with the owner's own credits and no visitor.
    if account is not None and account.id == owner.id:
        conv = await CV.create(db, owner_id=owner.id, agent_id=agent.id, audience="visitor", simulated=True)
        await db.commit()
        return {"owner_preview": True, "agent_id": str(agent.id), "conversation_id": str(conv.id),
                "agent": _public_agent(agent, owner, status, (await CR.available_balance(db, owner.id)) <= 0,
                                       await PF.display_name_for(db, owner, audience="visitor", policy=agent.disclosure_policy or {}),
                                       voice=await VOICE.availability(db))}
    ip = client_ip(request)
    # 한 곳에서 새 대화를 몇 개나 여는가. 이 비서의 설정이 정하고, 안 정했으면 기본값이다
    # (plan/53). 방문자당 분당 제한만으로는 막지 못한다 — 새 대화를 열면 그 제한도
    # 새로 시작하므로, 문 자체를 세는 자리가 따로 있어야 한다.
    sessions = int((agent.visitor_settings or {}).get("sessions_per_hour",
                                                     AG.DEFAULT_VISITOR_SETTINGS["sessions_per_hour"]) or 0)
    if sessions > 0:
        limiter.check(f"visitor:{agent.id}:{ip}", sessions, 3600)
    await _enforce_turnstile(db, agent, body.turnstile_token or "", ip)
    visitor = None
    if body.existing_token:
        try:
            from memora.core.security import decode_visitor_token
            p = decode_visitor_token(body.existing_token)
            if p.get("code", "").lower() == link.code.lower() and p.get("agent") == str(agent.id):
                candidate = await db.get(Visitor, uuid.UUID(p["sub"]))
                if candidate and candidate.owner_id == owner.id and candidate.agent_id == agent.id:
                    # An account-bound session is a claim to be that person, and it lives
                    # only as long as that account's session on this device. A stored
                    # visitor token must not resurrect the name after a logout, so without
                    # the matching account the visit starts over as a stranger.
                    bound_elsewhere = candidate.user_id is not None and (account is None or account.id != candidate.user_id)
                    visitor = None if bound_elsewhere else candidate
        except Exception:
            visitor = None
    now = datetime.now(UTC)
    converted = False
    ip_hash = hashlib.sha256(f"{now:%Y%m%d}|{ip}".encode()).hexdigest()[:32]
    if visitor is None or visitor.blocked:
        if visitor is not None and visitor.blocked:
            raise Forbidden("blocked", code="visitor_blocked")
        # Serialize first-time visitor creation per share link. This closes the
        # max_conversations read/modify/write race at the boundary.
        link = (await db.execute(select(ShareLink).where(ShareLink.id == link.id).with_for_update())).scalars().first()
        if link is None:
            raise NotFound("link not found", code="link_not_found")
        status = AG.link_effective_status(link, agent)
        if status != "active":
            raise Forbidden("link not active", code=f"link_{status}")
        raw = uuid.uuid4().hex
        visitor = Visitor(owner_id=owner.id, agent_id=agent.id, share_link_id=link.id, token_hash=sha256(raw),
                          display_name=body.display_name or (_visitor_name(account) if account else None),
                          email=account.email if account else None,
                          user_id=account.id if account else None,
                          ip_hash=ip_hash, first_seen_at=now, last_seen_at=now, meta={"ua": request.headers.get("user-agent", "")[:200]})
        db.add(visitor)
        await db.flush()
        link.conversation_count = (link.conversation_count or 0) + 1
    else:
        visitor.last_seen_at = now
        if body.display_name and not visitor.display_name:
            visitor.display_name = body.display_name
        # Signing in mid-conversation keeps the same person — the owner's history of them
        # stays in one place — but the conversation restarts: what was said as an anonymous
        # stranger is not what you want carried into a session under your own name.
        if account is not None and visitor.user_id is None:
            visitor.user_id = account.id
            visitor.display_name = _visitor_name(account) or visitor.display_name
            visitor.email = visitor.email or account.email
            converted = True
            # The owner's graph learns it in the same breath: the guest node they may
            # already have becomes this account's node instead of a second person (plan/31).
            with contextlib.suppress(Exception):
                from memora.services import people as PEOPLE
                await PEOPLE.fuse_visitor(db, visitor)
    # 다시 온 사람과 이어서 이야기하는가 — [지식] 탭 기억 줄의 "다시 온 사람 기억하기" 하나가 정한다 (plan/57).
    # 예전에는 [능력 › 방문자 기억] 과 [방문자 설정 › 이어서 대화] 둘이 같은 일을 했다.
    from memora.services import outsider as OUT
    continue_conv = OUT.settings(agent)["visitors"] and not converted
    conv = None
    if continue_conv:
        from memora.models import Conversation
        conv = (await db.execute(select(Conversation).where(Conversation.visitor_id == visitor.id, Conversation.status == "active")
                                 .order_by(Conversation.created_at.desc()))).scalars().first()
    if conv is None:
        conv = await CV.create(db, owner_id=owner.id, agent_id=agent.id, audience="visitor", visitor_id=visitor.id, share_link_id=link.id)
    await db.commit()
    token = create_visitor_token(visitor.id, agent.id, link.code)
    return {"visitor_token": token, "conversation_id": str(conv.id),
            "visitor": {"display_name": visitor.display_name, "email": visitor.email, "signed_in": visitor.user_id is not None},
            "agent": _public_agent(agent, owner, status, (await CR.available_balance(db, owner.id)) <= 0,
                                   await PF.display_name_for(db, owner, audience="visitor", policy=agent.disclosure_policy or {}),
                                   visitor_name=visitor.display_name, voice=await VOICE.availability(db))}


async def _verify_turnstile(secret: str, token: str, ip: str) -> bool:
    try:
        from memora.providers.http import request as req
        r = await req("POST", "https://challenges.cloudflare.com/turnstile/v0/siteverify", data={"secret": secret, "response": token, "remoteip": ip}, retries=1)
        return bool(r.json().get("success"))
    except Exception:
        return False


async def _visitor_ctx(db, v: CurrentVisitor):
    visitor = await db.get(Visitor, v.visitor_id)
    if visitor is None or visitor.blocked:
        raise Forbidden("visitor blocked", code="visitor_blocked")
    link, agent, owner = await _resolve_link(db, v.code)
    if agent.id != v.agent_id or visitor.agent_id != agent.id or visitor.owner_id != owner.id:
        raise Forbidden("token mismatch", code="token_mismatch")
    return visitor, link, agent, owner


async def _not_blocked(db, v: CurrentVisitor) -> Visitor:
    visitor = await db.get(Visitor, v.visitor_id)
    if visitor is None or visitor.blocked:
        raise Forbidden("visitor blocked", code="visitor_blocked")
    return visitor


@router.get("/conversations/{cid}/messages")
async def messages(cid: uuid.UUID, v: CurrentVisitor, db: DB, before: uuid.UUID | None = None, limit: int = 50):
    await _not_blocked(db, v)
    conv = await CV.get_for_visitor(db, v.visitor_id, cid)
    rows = await CV.messages(db, conv.id, before=before, limit=min(limit, 100))
    from memora.services.uploads import with_urls
    return {"items": [{"id": str(m.id), "role": m.role, "content": m.content, "cards": m.cards or [],
                       "attachments": with_urls(m.attachments), "created_at": m.created_at.isoformat()} for m in rows]}


class PublicTurnIn(BaseModel):
    text: str = Field(default="", max_length=4000)
    client_turn_id: str | None = Field(default=None, max_length=64)
    upload_ids: list[uuid.UUID] = Field(default_factory=list, max_length=8)


@router.post("/conversations/{cid}/uploads", status_code=201)
async def visitor_upload(cid: uuid.UUID, v: CurrentVisitor, request: Request, db: DB, file: UploadFile = File(...)):
    """방문자가 건네는 파일 (plan/55 §6-3). 그 방문자의 칸에 들어가고, 그 방문자와의 대화에서만 쓰인다."""
    from memora.services import files as FILES
    from memora.services.uploads import signed_url
    visitor, link, agent, owner = await _visitor_ctx(db, v)
    await CV.get_for_visitor(db, visitor.id, cid)
    if AG.link_effective_status(link, agent) != "active":
        raise Forbidden("link not active", code="link_closed")
    limiter.check(f"pubup:{visitor.id}", 20, 600)
    limiter.check(f"pubup-ip:{client_ip(request)}", 60, 3600)
    data = await UP_SVC.read_capped(file, 25 * 1024 * 1024)
    up = await FILES.store_for_visitor(db, agent=agent, owner=owner, visitor=visitor, filename=file.filename or "file",
                                       mime=file.content_type or "", data=data)
    await db.commit()
    return {"upload_id": str(up.id), "url": signed_url(up.id), "mime": up.mime, "size": up.size_bytes, "filename": up.filename}


@router.post("/conversations/{cid}/turns")
async def post_turn(cid: uuid.UUID, body: PublicTurnIn, v: CurrentVisitor, request: Request, db: DB):
    visitor, link, agent, owner = await _visitor_ctx(db, v)
    conv = await CV.get_for_visitor(db, visitor.id, cid)
    status = AG.link_effective_status(link, agent)
    if status != "active":
        raise Forbidden("link not active", code=f"link_{status}")
    if (await CR.available_balance(db, owner.id)) <= 0:
        raise Forbidden("secretary resting", code="secretary_resting")
    # The member being visited pays for the answer, so an unbounded visitor is a way to
    # empty somebody else's balance. A conversation at human pace never reaches these;
    # both are counted because one source can open many visitor sessions.
    limiter.check(f"pubturn:{visitor.id}", 20, 600)
    limiter.check(f"pubturn-ip:{client_ip(request)}", 60, 3600)
    atts: list = []
    if body.upload_ids:
        from memora.services import files as FILES
        if not FILES.visitor_file_rules(agent)["accept"]:
            raise Forbidden("files are not accepted", code="visitor_files_unavailable")
        atts = await FILES.visitor_attachments(db, owner_id=owner.id, visitor_id=visitor.id, ids=body.upload_ids)
    if not body.text.strip() and not atts:
        raise ValidationFailed("write something first", code="empty_message")
    req = TurnRequest(owner=owner, agent=agent, conversation=conv, audience="visitor", text=body.text, visitor=visitor, share_link=link,
                      client_turn_id=body.client_turn_id, attachments=atts)
    turn = await start_turn(db, req)
    await db.commit()
    launch_turn(turn)
    from memora.api.chat import turn_stream
    return turn_stream(turn, 0, visitor=True, request=request)


@router.get("/turns/{turn_id}/events")
async def resume(turn_id: uuid.UUID, v: CurrentVisitor, db: DB, request: Request, after: int = 0):
    from memora.api.chat import turn_stream
    from memora.models import Conversation
    t = await db.get(Turn, turn_id)
    if t is None:
        raise NotFound("turn not found", code="turn_not_found")
    conv = await db.get(Conversation, t.conversation_id)
    if conv is None or conv.visitor_id != v.visitor_id:
        raise NotFound("turn not found", code="turn_not_found")
    return turn_stream(t, after, visitor=True, request=request)


@router.post("/turns/{turn_id}/cancel", status_code=202)
async def cancel(turn_id: uuid.UUID, v: CurrentVisitor, db: DB):
    from memora.models import Conversation
    t = await db.get(Turn, turn_id)
    conv = await db.get(Conversation, t.conversation_id) if t else None
    if conv is None or conv.visitor_id != v.visitor_id:
        raise NotFound("turn not found", code="turn_not_found")
    return {"cancelled": await cancel_turn(turn_id)}


@router.get("/conversations/{cid}/active-turn")
async def active(cid: uuid.UUID, v: CurrentVisitor, db: DB):
    await CV.get_for_visitor(db, v.visitor_id, cid)
    t = await CV.active_turn(db, cid)
    if t is None:
        return None
    j = journals.get(t.id)
    return {"turn_id": str(t.id), "seq": j.seq if j else 0}


class MessageIn(BaseModel):
    message: str = Field(min_length=1, max_length=4000)
    name: str | None = None
    contact: str | None = None


@router.post("/conversations/{cid}/messages", status_code=201)
async def leave_message(cid: uuid.UUID, body: MessageIn, v: CurrentVisitor, db: DB):
    """Form fallback (works even when the secretary is resting)."""
    visitor, link, agent, owner = await _visitor_ctx(db, v)
    conv = await CV.get_for_visitor(db, visitor.id, cid)
    limiter.check(f"pubmsg:{visitor.id}", 5, 600)
    if body.name and not visitor.display_name:
        visitor.display_name = body.name[:120]
    if body.contact and "@" in body.contact and not visitor.email:
        visitor.email = body.contact[:255]
    item = await I.create(db, owner_id=owner.id, agent_id=agent.id, kind="message",
                          payload={"visitor_id": str(visitor.id), "visitor_name": body.name or visitor.display_name or "방문자", "agent_name": agent.name,
                                   "text": body.message, "contact": body.contact}, conversation_id=conv.id, visitor_id=visitor.id, urgency=2)
    await CV.add_message(db, conv, role="card", content="", cards=[{"card_type": "leave_message", "payload": {"item_id": str(item.id), "message": body.message[:400], "status": "delivered"}}])
    await db.commit()
    return {"delivered": True, "item_id": str(item.id)}


class MeetingIn(BaseModel):
    purpose: str = Field(min_length=1, max_length=1000)
    slots: list[str] = Field(min_length=1, max_length=5)
    name: str | None = None
    contact: str | None = None


@router.post("/conversations/{cid}/meeting-requests", status_code=201)
async def meeting_request(cid: uuid.UUID, body: MeetingIn, v: CurrentVisitor, db: DB):
    visitor, link, agent, owner = await _visitor_ctx(db, v)
    conv = await CV.get_for_visitor(db, visitor.id, cid)
    limiter.check(f"pubmeet:{visitor.id}", 3, 600)
    item = await I.create(db, owner_id=owner.id, agent_id=agent.id, kind="meeting_request",
                          payload={"visitor_id": str(visitor.id), "visitor_name": body.name or visitor.display_name or "방문자", "agent_name": agent.name,
                                   "purpose": body.purpose, "slots": body.slots, "contact": body.contact, "text": body.purpose[:200]},
                          conversation_id=conv.id, visitor_id=visitor.id, urgency=3)
    await db.commit()
    return {"submitted": True, "item_id": str(item.id)}


class VisitorPatch(BaseModel):
    display_name: str | None = Field(default=None, max_length=120)
    email: str | None = Field(default=None, max_length=255)
    note: str | None = Field(default=None, max_length=500)


@router.post("/visitors/me/new-conversation")
async def visitor_new_conversation(v: CurrentVisitor, db: DB):
    """Start over. The previous conversation is left intact: the owner is entitled to read
    what was said to their secretary, so "reset" means a fresh thread, not a deletion."""
    visitor = await db.get(Visitor, v.visitor_id)
    if visitor is None:
        raise NotFound("visitor not found")
    if visitor.blocked:
        raise Forbidden("blocked", code="visitor_blocked")
    conv = await CV.create(db, owner_id=visitor.owner_id, agent_id=visitor.agent_id, audience="visitor",
                           visitor_id=visitor.id, share_link_id=visitor.share_link_id)
    await db.commit()
    return {"conversation_id": str(conv.id)}


@router.patch("/visitors/me")
async def patch_visitor(body: VisitorPatch, v: CurrentVisitor, db: DB):
    visitor = await db.get(Visitor, v.visitor_id)
    if visitor is None:
        raise NotFound("visitor not found")
    if body.display_name is not None:
        visitor.display_name = body.display_name.strip() or None
    if body.email is not None:
        visitor.email = body.email.strip() or None
    if body.note is not None:
        visitor.note = body.note.strip() or None
    await db.commit()
    return {"display_name": visitor.display_name, "email": visitor.email}


@router.post("/conversations/{cid}/stt")
async def stt(cid: uuid.UUID, v: CurrentVisitor, db: DB, file: UploadFile = File(...)):
    from memora.providers.stt import get_stt
    visitor, link, agent, owner = await _visitor_ctx(db, v)
    if not (agent.capabilities or {}).get("voice", True):
        raise Forbidden("voice disabled", code="voice_disabled")
    await VOICE.require(db, "stt")
    limiter.check(f"pubstt:{visitor.id}", 10, 60)
    data = await UP_SVC.read_capped(file, 10 * 1024 * 1024)
    prov = await get_stt(db)
    tr = await prov.transcribe(data, file.content_type or "audio/webm", (agent.voice or {}).get("stt_language") or None)
    minutes = max(0.1, (tr.duration_s or len(data) / 32000) / 60)
    await CR.charge_usage(db, owner_id=owner.id, kind="stt", credits=float(await S.get(db, "stt.credit_per_minute")) * minutes,
                          provider=prov.provider, units=minutes, agent_id=agent.id)
    await db.commit()
    return {"text": tr.text}


class TtsIn(BaseModel):
    text: str = Field(min_length=1, max_length=2000)


@router.post("/conversations/{cid}/tts")
async def tts(cid: uuid.UUID, body: TtsIn, v: CurrentVisitor, db: DB):
    from memora.providers.tts import cache_path, get_tts
    visitor, link, agent, owner = await _visitor_ctx(db, v)
    if not (agent.capabilities or {}).get("voice", True):
        raise Forbidden("voice disabled", code="voice_disabled")
    await VOICE.require(db, "tts")
    limiter.check(f"pubtts:{visitor.id}", 10, 60)
    prov = await get_tts(db)
    voice = (agent.voice or {}).get("tts_voice") or await S.get(db, "tts.default_voice")
    p = cache_path(body.text, voice, prov.model)
    if not await pools.to_thread("misc", p.exists):
        chunks = [c async for c in prov.synthesize(body.text, voice, float((agent.voice or {}).get("tts_speed") or 1.0))]
        await pools.to_thread("misc", p.write_bytes, b"".join(chunks))
        await CR.charge_usage(db, owner_id=owner.id, kind="tts", credits=float(await S.get(db, "tts.credit_per_1k_chars")) * len(body.text) / 1000,
                              provider=prov.provider, units=len(body.text), agent_id=agent.id)
        await db.commit()
    data = await pools.to_thread("misc", p.read_bytes)
    return Response(data, media_type="audio/mpeg", headers={"Cache-Control": "private, max-age=3600"})


@router.get("/files/{doc_id}")
async def public_file(doc_id: uuid.UUID, t: str, db: DB):
    st = verify_state(t)
    if st.get("kind") != "file_share" or st.get("doc") != str(doc_id):
        raise Forbidden("bad token")
    d = await db.get(KnowledgeDocument, doc_id)
    if d is None or not d.storage_path:
        raise NotFound("file not found")
    # 건넨 뒤 10분 사이에 주인이 [지식] 탭에서 거뒀으면 받지 못한다 — 링크가 거둔 것을 이기지 않는다.
    from memora.models import Agent
    from memora.services import outsider as OUT
    agent = await db.get(Agent, uuid.UUID(st["agent"])) if st.get("agent") else None
    if agent is None or agent.owner_id != d.owner_id or not OUT.possible(agent, "knowledge_files"):
        raise NotFound("file not found")
    if OUT.settings(agent)["knowledge_scope"] != "all" and d.id not in (await OUT.picked(db, agent.id, "knowledge"))["document_id"]:
        raise NotFound("file not found")
    from memora.services import objectstore
    if d.storage_path.startswith(objectstore.S3_PREFIX):
        return Response(await objectstore.get(d.storage_path), media_type=d.mime or "application/octet-stream",
                        headers={"Content-Disposition": f'inline; filename="{(d.filename or d.title)[:80]}"'})
    return FileResponse(d.storage_path, media_type=d.mime or "application/octet-stream", filename=d.filename or d.title)


# The two starting photographs the wizard offers. They are static files the frontend
# serves; this is the copy the card renderer draws from, kept byte-identical by a test
# (test_units.py::test_the_shipped_presets_match_the_ones_the_wizard_serves).
PRESET_DIR = Path(__file__).resolve().parent.parent / "assets" / "presets"

# A shared link is read as a card in a chat app long before anyone opens it, and the card
# is mostly the picture. These are the families Debian ships that can draw Hangul; the
# default PIL bitmap font cannot, which is why this used to render a row of tofu.
_FONTS = {
    True: ("/usr/share/fonts/truetype/nanum/NanumGothicBold.ttf", "/usr/share/fonts/truetype/nanum/NanumGothic.ttf",
           "/usr/share/fonts/truetype/noto/NotoSansCJK-Bold.ttc", "/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc"),
    False: ("/usr/share/fonts/truetype/nanum/NanumGothic.ttf",
            "/usr/share/fonts/truetype/noto/NotoSansCJK-Regular.ttc", "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc"),
}


def _og_font(size: int, *, bold: bool = False):
    from PIL import ImageFont
    for path in _FONTS[bold]:
        try:
            return ImageFont.truetype(path, size)
        except OSError:
            continue
    return ImageFont.load_default()


def _fit(draw, text: str, font, width: int) -> str:
    """Trim to the width it has, with an ellipsis — a name that runs off the card reads as
    a bug in the card."""
    if not text:
        return ""
    if draw.textlength(text, font=font) <= width:
        return text
    while text and draw.textlength(text + "…", font=font) > width:
        text = text[:-1]
    return text + "…"


def _render_og(name: str, owner_name: str, role_line: str, accent: str,
               avatar: bytes | None = None, cover: bytes | None = None) -> bytes:
    """The secretary's own card: its background, its face, its name.

    Everything here is what the profile shows, at the size a link preview is drawn — the
    picture is the reason a shared link gets opened at all.
    """
    import io

    from PIL import Image, ImageDraw, ImageFilter
    W, H = 1200, 630
    try:
        rgb = tuple(int(accent.lstrip("#")[i:i + 2], 16) for i in (0, 2, 4))
    except Exception:  # noqa: BLE001
        rgb = (79, 70, 229)

    img = Image.new("RGB", (W, H), (17, 24, 39))
    if cover:
        try:
            cov = Image.open(io.BytesIO(cover)).convert("RGB")
            scale = max(W / cov.width, H / cov.height)
            cov = cov.resize((max(1, round(cov.width * scale)), max(1, round(cov.height * scale))), Image.LANCZOS)
            img.paste(cov, (-(cov.width - W) // 2, -(cov.height - H) // 2))
            # Dark enough for white text over any photograph, still clearly the photograph.
            img = Image.blend(img, Image.new("RGB", (W, H), (10, 14, 26)), 0.55)
        except Exception:  # noqa: BLE001
            cover = None
    if not cover:
        # No cover: the secretary's accent, poured from the corner the face sits in.
        wash = Image.new("RGB", (W, H), (17, 24, 39))
        glow = Image.new("RGB", (W, H), tuple(int(c * 0.55) for c in rgb))
        mask = Image.linear_gradient("L").rotate(-25, expand=False).resize((W, H))
        img = Image.composite(wash, glow, mask).filter(ImageFilter.GaussianBlur(40))

    d = ImageDraw.Draw(img)
    d.rectangle([0, 0, W, 14], fill=rgb)

    text_x = 110
    if avatar:
        try:
            size = 240
            face = Image.open(io.BytesIO(avatar)).convert("RGB")
            s = max(size / face.width, size / face.height)
            face = face.resize((max(1, round(face.width * s)), max(1, round(face.height * s))), Image.LANCZOS)
            face = face.crop(((face.width - size) // 2, (face.height - size) // 2,
                              (face.width - size) // 2 + size, (face.height - size) // 2 + size))
            ring = Image.new("L", (size + 16, size + 16), 0)
            ImageDraw.Draw(ring).ellipse([0, 0, size + 15, size + 15], fill=255)
            plate = Image.new("RGB", (size + 16, size + 16), (255, 255, 255))
            img.paste(plate, (100, 195), ring)
            mask = Image.new("L", (size, size), 0)
            ImageDraw.Draw(mask).ellipse([0, 0, size - 1, size - 1], fill=255)
            img.paste(face, (108, 203), mask)
            text_x = 400
        except Exception:  # noqa: BLE001
            text_x = 110

    right = W - 90 - text_x
    whose = f"{owner_name}의 비서"
    d.text((text_x, 232), _fit(d, name, _og_font(68, bold=True), right), font=_og_font(68, bold=True), fill=(255, 255, 255))
    d.text((text_x, 322), _fit(d, whose, _og_font(36), right), font=_og_font(36), fill=(197, 203, 222))
    # An owner who left the role line at its default has it written above already; printing
    # it twice reads as a rendering fault.
    if role_line and role_line.strip() != whose:
        d.text((text_x, 378), _fit(d, role_line, _og_font(32), right), font=_og_font(32), fill=(150, 158, 184))
    d.text((text_x, 470), "memo-ora.com", font=_og_font(26), fill=(120, 128, 156))

    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


async def _picture(db, url: str | None) -> bytes | None:
    """The bytes of a profile picture, wherever it lives.

    An upload may be a file on this disk or an object in the store — reading the row's
    path directly worked only for the first, which is why a secretary whose photo lived in
    S3 was shared as a card with no face on it. A preset is a static file the frontend
    serves, and a secretary that picked one has a face too, so those are read from the
    bundled copy by name. Nothing else is fetched: `avatar_url` is owner-supplied text and
    a renderer that follows it anywhere is an SSRF.
    """
    if not url:
        return None
    if "/uploads/" in url:
        from memora.models import Upload
        try:
            up = await db.get(Upload, uuid.UUID(url.rsplit("/", 1)[-1].split("?")[0]))
        except ValueError:
            return None
        if up is None or up.kind != "avatar":
            return None
        from memora.services import uploads as UP
        try:
            return await UP.read_bytes(up)
        except Exception:  # noqa: BLE001
            return None
    if url.startswith("/presets/"):
        name = url.rsplit("/", 1)[-1].split("?")[0]
        path = PRESET_DIR / name

        def _read() -> bytes | None:
            try:
                return path.read_bytes() if path.is_file() and path.parent == PRESET_DIR else None
            except OSError:
                return None

        return await pools.to_thread("misc", _read, label="preset")
    return None


async def _og_response(code: str, db, *, versioned: bool) -> Response:
    link, agent, owner = await _resolve_link(db, code)
    png = await pools.to_thread("misc", _render_og, agent.name, owner.display_name, agent.role_line or "",
                                  (agent.theme or {}).get("accent", "#4f46e5"),
                                  await _picture(db, agent.avatar_url), await _picture(db, agent.cover_url))
    # A versioned name is content-addressed: the URL moves when the card does, so anything
    # holding it may hold it forever. The bare name is the one old previews already have,
    # and it has to be allowed to heal.
    cache = "public, max-age=31536000, immutable" if versioned else "public, max-age=300"
    return Response(png, media_type="image/png", headers={"Cache-Control": cache})


@router.get("/links/{code}/og.png")
async def og_image(code: str, db: DB):
    return await _og_response(code, db, versioned=False)


# The version lives in the path, not in a query: link scrapers — KakaoTalk's among them —
# are unreliable about query strings on og:image, and a preview that fetches nothing is
# worse than a stale one. `token` is never read; it only has to change.
@router.get("/links/{code}/og-{token}.png")
async def og_image_versioned(code: str, token: str, db: DB):
    return await _og_response(code, db, versioned=True)


def _render_icon(avatar: bytes | None, accent: str, size: int = 180) -> bytes:
    """This secretary's face for the browser tab.

    A tab icon is ~16 real pixels: the brand mark would make every shared link look the
    same, so an agent with an avatar wears its own. Cropped square and centred, because a
    tall portrait letterboxed into a favicon is a smudge.
    """
    import io

    from PIL import Image, ImageDraw
    canvas = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    mask = Image.new("L", (size, size), 0)
    ImageDraw.Draw(mask).rounded_rectangle([0, 0, size - 1, size - 1], radius=int(size * 0.22), fill=255)
    try:
        rgb = tuple(int(accent.lstrip("#")[i:i + 2], 16) for i in (0, 2, 4))
    except Exception:  # noqa: BLE001
        rgb = (23, 111, 214)
    canvas.paste(Image.new("RGBA", (size, size), (*rgb, 255)), (0, 0), mask)

    art: Image.Image | None = None
    if avatar:
        try:
            art = Image.open(io.BytesIO(avatar)).convert("RGBA")
        except Exception:  # noqa: BLE001
            art = None
    # No avatar: leave the accent plate, which still tells one link from another.
    if art is not None:
        w, h = art.size
        side = min(w, h)
        art = art.crop(((w - side) // 2, 0, (w - side) // 2 + side, side)).resize((size, size), Image.LANCZOS)
        canvas.paste(art, (0, 0), mask)
    buf = io.BytesIO()
    canvas.save(buf, format="PNG")
    return buf.getvalue()


@router.get("/links/{code}/icon.png")
async def link_icon(code: str, db: DB):
    link, agent, owner = await _resolve_link(db, code)
    png = await pools.to_thread("misc", _render_icon, await _picture(db, agent.avatar_url),
                                  (agent.theme or {}).get("accent", "#176fd6"))
    return Response(png, media_type="image/png", headers={"Cache-Control": "public, max-age=3600"})


@router.get("/links/{code}/manifest.webmanifest")
async def manifest(code: str, db: DB):
    link, agent, owner = await _resolve_link(db, code)
    accent = (agent.theme or {}).get("accent", "#4f46e5")
    base = get_settings().public_url.rstrip("/")
    return Response(content=__import__("json").dumps({
        "name": f"{agent.name}", "short_name": agent.name[:12],
        "start_url": f"/{LINK_PREFIX}/{link.code}", "scope": f"/{LINK_PREFIX}/{link.code}", "display": "standalone",
        "background_color": "#ffffff", "theme_color": accent,
        "icons": [{"src": f"{base}/api/public/links/{link.code}/icon.png", "sizes": "180x180", "type": "image/png"}, {"src": f"{base}/icons/icon-512.png", "sizes": "512x512", "type": "image/png"}],
    }), media_type="application/manifest+json")
