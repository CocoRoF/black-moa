from __future__ import annotations

import contextlib
import uuid
from datetime import datetime

from fastapi import APIRouter, Request
from pydantic import BaseModel, Field
from sqlalchemy import select

from blackmoa.core import pools
from blackmoa.core import visibility as VIS
from blackmoa.core.codes import public_link_url
from blackmoa.core.deps import DB, CurrentUser
from blackmoa.core.errors import Conflict, Forbidden, ValidationFailed
from blackmoa.memory import facade as MEM
from blackmoa.memory.facade import AgentMemory, delete_vault
from blackmoa.models import ShareLink
from blackmoa.pipeline import base_prompt as BP
from blackmoa.pipeline.personas import preset_list
from blackmoa.pipeline.runtime import runtimes
from blackmoa.pipeline.tools.base import all_tools
from blackmoa.services import agents as AG
from blackmoa.services import audit
from blackmoa.services import catalog as CAT
from blackmoa.services import outsider as OUT
from blackmoa.services import plans as P
from blackmoa.services import profile as PF
from blackmoa.services import settings as S

router = APIRouter(prefix="/api", tags=["agents"])


def agent_out(a, links: list | None = None, owner_name: str = "") -> dict:
    # ``greeting``/``role_line`` stay raw (the settings form edits them; empty means "auto"),
    # while ``*_display`` carry what a visitor actually sees right now.
    greeting_display, role_display = AG.display_texts(a, owner_name or "오너")
    return {"id": str(a.id), "name": a.name, "role_line": a.role_line, "avatar_url": a.avatar_url, "cover_url": a.cover_url, "character_url": AG.stage_figure(a), "status": a.status,
            "provider": a.provider, "model_id": a.model_id, "persona": a.persona, "custom_instructions": a.custom_instructions,
            "capabilities": a.capabilities, "disclosure_policy": a.disclosure_policy, "outsider": OUT.settings(a), "greeting": a.greeting,
            "suggested_questions": a.suggested_questions or [], "language": a.language, "theme": a.theme, "voice": a.voice,
            "visitor_settings": a.visitor_settings, "thinking_enabled": a.thinking_enabled, "stats": a.stats or {},
            "turn_cost_cap_credits": a.turn_cost_cap_credits, "daily_credit_cap": a.daily_credit_cap,
            "monthly_credit_cap": a.monthly_credit_cap,
            "created_at": a.created_at.isoformat() if a.created_at else None,
            "updated_at": a.updated_at.isoformat() if a.updated_at else None,
            "greeting_display": greeting_display, "role_line_display": role_display,
            "links": [link_out(l_) for l_ in (links or [])]}


def link_out(l_) -> dict:
    return {"id": str(l_.id), "agent_id": str(l_.agent_id), "code": l_.code, "url": public_link_url(l_.code), "label": l_.label,
            "status": l_.status, "expires_at": l_.expires_at.isoformat() if l_.expires_at else None,
            "max_conversations": l_.max_conversations, "conversation_count": l_.conversation_count, "turn_count": l_.turn_count,
            "last_visit_at": l_.last_visit_at.isoformat() if l_.last_visit_at else None, "created_at": l_.created_at.isoformat(),
            "settings": _link_settings_out(l_)}


def _link_settings_out(l_) -> dict:
    from blackmoa.services import relay as RELAY
    return {**RELAY.link_settings(l_), "layout": AG.link_layout(l_)}


class AgentCreate(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    role_line: str = ""
    persona: dict | None = None
    provider: str | None = None
    model_id: str | None = None
    language: str = "auto"
    greeting: str = ""
    suggested_questions: list[str] = []
    avatar_url: str | None = None
    cover_url: str | None = None
    character_url: str | None = None


@router.get("/agents")
async def list_agents(user: CurrentUser, db: DB, include_archived: bool = False):
    agents = await AG.list_owned(db, user.id, include_archived=include_archived)
    links = (await db.execute(select(ShareLink).where(ShareLink.owner_id == user.id, ShareLink.status != "revoked"))).scalars().all()
    by_agent: dict = {}
    for l_ in links:
        by_agent.setdefault(l_.agent_id, []).append(l_)
    plan = await P.plan_for_user(db, user)
    own = await PF.display_name_for(db, user)
    return {"items": [agent_out(a, by_agent.get(a.id), own) for a in agents], "max_agents": plan.max_agents}


async def _require_verified_email(db, user) -> None:
    """Creating a secretary needs a reachable address; signing up does not.

    The secretary sends mail on the owner's behalf and answers strangers under their name,
    so an unreachable owner is a support problem and an abuse vector. Signup stays one step.
    """
    if user.email_verified_at is not None or user.role == "admin":
        return
    if not await S.get(db, "signup.verify_before_agent"):
        return
    raise Forbidden("email verification required", code="email_verification_required")


@router.post("/agents", status_code=201)
async def create_agent(body: AgentCreate, user: CurrentUser, db: DB, request: Request):
    await _require_verified_email(db, user)
    a = await AG.create(db, user, name=body.name, role_line=body.role_line, persona=body.persona, provider=body.provider,
                        model_id=body.model_id, language=body.language, greeting=body.greeting, suggested_questions=body.suggested_questions,
                        avatar_url=body.avatar_url, cover_url=body.cover_url, character=body.character_url)
    audit.record(db, "agent_create", actor_id=user.id, target_type="agent", target_id=a.id)
    await db.commit()
    return agent_out(a, None, await PF.display_name_for(db, user))


async def _prompt_sections(db, user, a, audience: str) -> tuple[list[tuple[str, str]], list[str]]:
    """The prompt as named sections, the way /prompt and /prompt-preview both show it: the
    composed layers, then the per-turn relationship block (plan/37) for the owner audience."""
    composed, names = await _composed_prompt(db, user, a, audience)
    sections = list(composed.ordered())
    if audience == "owner":
        from blackmoa.services import relationship as REL
        sections.append(("relationship", REL.prompt_block(await REL.get(db, user.id, a.id), a, user)))
    return sections, names


async def _composed_prompt(db, user, a, audience: str):
    """The composed prompt plus the tool names it advertises — one path for every reader."""
    from blackmoa.pipeline.context import TurnContext
    from blackmoa.pipeline.runtime import compose_prompt
    from blackmoa.pipeline.tools.base import core_overrides_for, tool_names_for
    from blackmoa.services import mail as MAIL
    from blackmoa.services import plans as P
    from blackmoa.services.companies import switch as CO

    profile = await PF.shown(db, user.id)
    features = {"feature:mail"} if await MAIL.readable(db, user.id) else set()
    if await CO.enabled(db):
        features.add("feature:companies")
    ctx = TurnContext(owner=user, agent=a, audience=audience, conversation_id=a.id, turn_id=None, profile=profile,
                      plan=await P.plan_for_user(db, user), memory=None, visitor=None, features=features,
                      locale=user.locale or "ko")
    names = tool_names_for(ctx)
    hidden = {n for n, is_core in core_overrides_for(ctx).items() if not is_core}
    composed = await compose_prompt(db, owner=user, agent=a, audience=audience, profile=profile,
                                    tool_names=names, hidden_tools=hidden)
    return composed, names


@router.get("/agents/{agent_id}/prompt")
async def agent_prompt(agent_id: uuid.UUID, user: CurrentUser, db: DB, audience: str = "owner"):
    """What this agent's system prompt actually is, so the owner can read the layer they do
    not write. Composed exactly as a turn composes it — the same function, not a copy."""
    if audience not in ("owner", "visitor"):
        raise ValidationFailed("audience must be owner or visitor")
    a = await AG.get_owned(db, user.id, agent_id, include_archived=True)
    sections, _ = await _prompt_sections(db, user, a, audience)
    base = {k: v for k, v in sections if k != "secretary"}
    return {"audience": audience,
            "base_sections": [{"name": k, "text": v} for k, v in base.items()],
            "base_prompt": "\n\n".join(base.values()),
            "secretary_prompt": dict(sections).get("secretary", ""),
            "custom_instructions": a.custom_instructions or "",
            "custom_default": BP.secretary_template(user.locale or "ko")}


@router.get("/agents/{agent_id}")
async def get_agent(agent_id: uuid.UUID, user: CurrentUser, db: DB):
    a = await AG.get_owned(db, user.id, agent_id, include_archived=True)
    links = (await db.execute(select(ShareLink).where(ShareLink.agent_id == a.id, ShareLink.status != "revoked"))).scalars().all()
    return agent_out(a, links, await PF.display_name_for(db, user))


@router.patch("/agents/{agent_id}")
async def patch_agent(agent_id: uuid.UUID, body: dict, user: CurrentUser, db: DB):
    a = await AG.get_owned(db, user.id, agent_id)
    from blackmoa.services import relationship as REL
    if any(k in body for k in REL.VERSIONED):
        # The version kept is the one being replaced, so the first save of a secretary
        # leaves its original personality behind it too.
        await REL.snapshot(db, a, label="")
    await AG.update(db, a, body, plan=await P.plan_for_user(db, user))
    if any(k in body for k in REL.VERSIONED):
        await REL.snapshot(db, a, label=str(body.get("_version_label") or "")[:80])
    await db.commit()
    return agent_out(a, None, await PF.display_name_for(db, user))


@router.post("/agents/{agent_id}/actions/{action}")
async def agent_action(agent_id: uuid.UUID, action: str, user: CurrentUser, db: DB):
    a = await AG.get_owned(db, user.id, agent_id, include_archived=True)
    mapping = {"pause": "paused", "resume": "active", "archive": "archived", "restore": "active"}
    if action not in mapping:
        from blackmoa.core.errors import NotFound
        raise NotFound("unknown action")
    await AG.set_status(a, mapping[action])
    audit.record(db, f"agent_{action}", actor_id=user.id, target_type="agent", target_id=a.id)
    await db.commit()
    await runtimes.drop_agent(a.id)
    return agent_out(a)


@router.delete("/agents/{agent_id}")
async def delete_agent(agent_id: uuid.UUID, user: CurrentUser, db: DB):
    a = await AG.get_owned(db, user.id, agent_id, include_archived=True)
    await runtimes.drop_agent(a.id)
    await delete_vault(a.id)
    audit.record(db, "agent_delete", actor_id=user.id, target_type="agent", target_id=a.id, meta={"name": a.name})
    # 그 비서가 받은 파일도 같이 간다 (plan/55). 행은 비서와 함께 지워지지만 바이트와
    # 썸네일은 저장소에 남아 저장 공간의 [기타] 를 영영 차지했다.
    from blackmoa.services import files as FILES
    uploads = await FILES.forget_agent(db, a.id)
    await db.delete(a)
    await db.flush()
    await FILES.purge_orphans(db, candidate_ids=uploads)
    await db.commit()
    return {"ok": True}


@router.get("/agents/{agent_id}/prompt-preview")
async def prompt_preview(agent_id: uuid.UUID, user: CurrentUser, db: DB, audience: str = "owner"):
    """The same prompt as /prompt, split into named sections with the tool list.

    It used to assemble its own approximation from a legacy module, so the dialog kept
    showing an older prompt — including a disclosure level the product no longer has.
    """
    if audience not in ("owner", "visitor"):
        raise ValidationFailed("audience must be owner or visitor")
    a = await AG.get_owned(db, user.id, agent_id, include_archived=True)
    sections, names = await _prompt_sections(db, user, a, audience)
    return {"audience": audience, "sections": [{"key": k, "text": t} for k, t in sections], "tools": names}


# ── [지식] 탭 = 외부인과의 대화에서 무엇을 쓰나 (plan/57) ─────────────────────────────

def _count_shared_notes(agent_id: uuid.UUID) -> int:
    """외부인에게 보일 수 있는 기억 — 주인·공유 방에서 범위가 [비공개] 가 아닌 것."""
    from blackmoa.memory.facade import note_level, note_store
    n = 0
    for ns in ("owner", "shared"):
        for note in note_store(agent_id, ns).iter_all():
            if note_level(ns, note.to_dict()) != "private":
                n += 1
    return n


async def _outsider_view(db, user, a) -> dict:
    """[지식] 탭 한 장. 수는 모두 대화가 실제로 쓰는 함수로 센다 — 화면과 대화가 다른 말을 하지 않게."""
    from datetime import datetime as _dt
    from datetime import timedelta as _td

    from sqlalchemy import func

    from blackmoa.models import AgentFile, BlogPost, Fact, KnowledgeDocument, KnowledgeFaq, NetworkNode
    from blackmoa.services import outsider as OUT
    from blackmoa.services import schedule as SCH

    st = OUT.settings(a)
    prof = await PF.shown(db, user.id)
    d = prof.data or {}
    # 1. 정보 — 프로필에서 누구에게 보이는지(칸마다의 공개 범위는 [내 정보 → 정보] 의 것).
    fields = []
    for key in PF.PROFILE_FIELDS:
        if key in ("cover", "cover_pos") or key in PF.LOCKED_FIELDS or key in PF.SCHEDULE_FIELDS:
            continue
        if key == "contact":
            for sub in ("email", "phone"):
                if (d.get("contact") or {}).get(sub):
                    fields.append({"key": f"contact.{sub}", "level": PF.field_visibility(prof, {}, f"contact.{sub}")})
            continue
        if d.get(key) not in (None, "", [], {}):
            fields.append({"key": key, "level": PF.field_visibility(prof, {}, key)})
    profile = {"fields": fields, "name": PF.display_name(prof, user, audience="visitor", policy=a.disclosure_policy or {})}

    kpick = await OUT.picked(db, a.id, "knowledge")
    # 2. 지식 — 준비된 문서와 FAQ, 그중 고른 것.
    docs_total = int((await db.execute(select(func.count(KnowledgeDocument.id)).where(
        KnowledgeDocument.owner_id == user.id, KnowledgeDocument.kind != "blog"))).scalar_one())
    posts = (await db.execute(select(BlogPost.visibility, func.count(BlogPost.id)).where(
        BlogPost.owner_id == user.id, BlogPost.status == "published", BlogPost.knowledge_document_id.isnot(None))
        .group_by(BlogPost.visibility))).all()
    pv = {VIS.normalize(v): int(n) for v, n in posts}
    faqs_total = int((await db.execute(select(func.count(KnowledgeFaq.id)).where(KnowledgeFaq.owner_id == user.id))).scalar_one())
    titles = [t for (t,) in (await db.execute(select(KnowledgeDocument.title).where(
        KnowledgeDocument.id.in_(list(kpick["document_id"]) or [uuid.uuid4()])).order_by(KnowledgeDocument.created_at.desc()).limit(6))).all()]
    # 피드 글은 [정보] 와 같은 층 — 정보 줄이 켜져 있으면 글마다의 범위대로 쓴다.
    profile["posts"] = {"public": pv.get("public", 0), "known": pv.get("known", 0)}
    knowledge = {"docs_total": docs_total, "faqs_total": faqs_total, "docs_picked": len(kpick["document_id"]),
                 "faqs_picked": len(kpick["faq_id"]), "titles": titles,
                 "file_docs": int((await db.execute(select(func.count(KnowledgeDocument.id)).where(
                     KnowledgeDocument.owner_id == user.id, KnowledgeDocument.kind == "file"))).scalar_one())}
    # 3. 파일 — [내 정보 → 파일]의 주인 파일 전부 중에서 이 비서에 이은 것 (plan/77).
    fq = [AgentFile.owner_id == user.id, AgentFile.scope == "owner", AgentFile.deleted_at.is_(None)]
    fpick = (await OUT.picked(db, a.id, "files"))["file_id"]
    files = {"total": int((await db.execute(select(func.count(AgentFile.id)).where(*fq))).scalar_one()),
             "picked": len(fpick),
             "names": [n for (n,) in (await db.execute(select(AgentFile.filename).where(
                 *fq, AgentFile.id.in_(list(fpick) or [uuid.uuid4()])).order_by(AgentFile.created_at.desc()).limit(6))).all()]}
    # 4. 인맥 — 나 자신은 세지 않는다.
    nq = [NetworkNode.owner_id == user.id, NetworkNode.is_self.is_(False)]
    npick = (await OUT.picked(db, a.id, "network"))["node_id"]
    network = {"total": int((await db.execute(select(func.count(NetworkNode.id)).where(*nq))).scalar_one()),
               "picked": len(npick),
               "names": [n for (n,) in (await db.execute(select(NetworkNode.name).where(
                   *nq, NetworkNode.id.in_(list(npick) or [uuid.uuid4()])).order_by(NetworkNode.importance.desc()).limit(6))).all()]}
    # 5. 스케줄 — 연락 가능 시간과, 모르는 사람(또는 인맥)에게 실제로 보일 빈 시간.
    win = SCH.window_of(prof)
    tz = SCH.zone(user)
    preview: list = []
    if st["schedule"] != "off" and win.get("weekly"):
        now = _dt.now(tz)
        preview = await SCH.free_slots(db, user, prof, start=now, end=now + _td(days=5), limit=30)
    schedule = {"weekly": win.get("weekly") or [], "note": win.get("note") or "", "timezone": str(tz), "preview": preview,
                "skip_holidays": SCH.skips_holidays(win)}
    # 6. 기억 — 공개로 둔 기억·사실(외부인에게 갈 수 있는 것).
    facts = (await db.execute(select(Fact.visibility, func.count(Fact.id)).where(
        Fact.owner_id == user.id, Fact.status == "active", (Fact.agent_id == a.id) | (Fact.agent_id.is_(None)))
        .group_by(Fact.visibility))).all()
    fv = {VIS.normalize(v) if v != "visitor_private" else v: n for v, n in facts}
    shared_notes = 0
    with contextlib.suppress(Exception):
        shared_notes = await pools.to_thread("memory", _count_shared_notes, a.id)
    memory = {"shared_notes": shared_notes, "public_facts": int(fv.get("public", 0)) + int(fv.get("known", 0))}

    links_active = int((await db.execute(select(func.count(ShareLink.id)).where(
        ShareLink.agent_id == a.id, ShareLink.status == "active"))).scalar_one() or 0)
    return {"agent_id": str(a.id), "settings": st, "links_active": links_active, "profile": profile,
            "knowledge": knowledge, "files": files, "network": network, "schedule": schedule, "memory": memory}


@router.get("/agents/{agent_id}/outsider")
async def get_outsider(agent_id: uuid.UUID, user: CurrentUser, db: DB):
    """비서의 [지식] 탭 — 외부인과의 대화에서 무엇을 쓰나 (plan/57)."""
    a = await AG.get_owned(db, user.id, agent_id, include_archived=True)
    return await _outsider_view(db, user, a)


@router.patch("/agents/{agent_id}/outsider")
async def patch_outsider(agent_id: uuid.UUID, body: dict, user: CurrentUser, db: DB):
    """줄 하나를 바꾼다. 바로 저장되고 다음 말부터 적용된다 (``updated_at`` 이 바뀌어 대화의 런타임이 다시 선다)."""
    from blackmoa.services import outsider as OUT
    a = await AG.get_owned(db, user.id, agent_id)
    a.outsider = {**(a.outsider or {}), **OUT.clean_patch(body)}
    audit.record(db, "agent.outsider", actor_id=user.id, target_type="agent", target_id=str(a.id), meta={"patch": body})
    await db.commit()
    await db.refresh(a)
    return await _outsider_view(db, user, a)


@router.get("/agents/{agent_id}/outsider/items")
async def outsider_items(agent_id: uuid.UUID, kind: str, user: CurrentUser, db: DB, q: str = "", limit: int = 300):
    """[고르기] 창의 목록 — 이 줄에서 고를 수 있는 것 전부와, 고른 것인지."""
    from blackmoa.models import AgentFile, KnowledgeDocument, KnowledgeFaq, NetworkNode
    from blackmoa.services import outsider as OUT
    a = await AG.get_owned(db, user.id, agent_id)
    if kind not in OUT.SCOPED:
        raise ValidationFailed("kind must be knowledge, files or network", code="bad_outsider_kind")
    picked = await OUT.picked(db, a.id, kind)
    lim = max(1, min(limit, 500))
    pat = ("%" + q.strip()[:80].replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%") if q.strip() else None
    items: list[dict] = []
    if kind == "knowledge":
        # 피드 글의 사본은 여기서 고르지 않는다 — 글마다의 범위와 정보 줄을 따른다.
        dq = select(KnowledgeDocument).where(KnowledgeDocument.owner_id == user.id, KnowledgeDocument.kind != "blog")
        if pat:
            dq = dq.where(KnowledgeDocument.title.ilike(pat, escape="\\"))
        for d_ in (await db.execute(dq.order_by(KnowledgeDocument.created_at.desc()).limit(lim))).scalars().all():
            items.append({"id": str(d_.id), "type": "doc", "title": d_.title, "sub": d_.filename or d_.source_url or "",
                          "doc_kind": d_.kind, "status": d_.status, "picked": d_.id in picked["document_id"]})
        fq = select(KnowledgeFaq).where(KnowledgeFaq.owner_id == user.id)
        if pat:
            fq = fq.where(KnowledgeFaq.question.ilike(pat, escape="\\"))
        for f in (await db.execute(fq.order_by(KnowledgeFaq.created_at.desc()).limit(lim))).scalars().all():
            items.append({"id": str(f.id), "type": "faq", "title": f.question[:200], "sub": f.answer[:120],
                          "picked": f.id in picked["faq_id"]})
    elif kind == "files":
        fq = select(AgentFile).where(AgentFile.owner_id == user.id, AgentFile.scope == "owner", AgentFile.deleted_at.is_(None))
        if pat:
            fq = fq.where(AgentFile.filename.ilike(pat, escape="\\"))
        for f in (await db.execute(fq.order_by(AgentFile.created_at.desc()).limit(lim))).scalars().all():
            items.append({"id": str(f.id), "type": "file", "title": f.filename, "sub": f.kind, "picked": f.id in picked["file_id"]})
    else:
        nq = select(NetworkNode).where(NetworkNode.owner_id == user.id, NetworkNode.is_self.is_(False))
        if pat:
            nq = nq.where(NetworkNode.name.ilike(pat, escape="\\"))
        for n in (await db.execute(nq.order_by(NetworkNode.importance.desc(), NetworkNode.name).limit(lim))).scalars().all():
            attrs = n.attrs or {}
            sub = " · ".join(x for x in (attrs.get("title"), attrs.get("company")) if x)
            items.append({"id": str(n.id), "type": "person", "title": n.name, "sub": sub, "node_kind": n.kind,
                          "picked": n.id in picked["node_id"]})
    return {"kind": kind, "scope": OUT.settings(a)[f"{kind}_scope"], "items": items}


class PicksIn(BaseModel):
    kind: str
    scope: str | None = None
    ids: list[str] = Field(default_factory=list, max_length=5000)
    faq_ids: list[str] = Field(default_factory=list, max_length=5000)


@router.put("/agents/{agent_id}/outsider/picks")
async def put_picks(agent_id: uuid.UUID, body: PicksIn, user: CurrentUser, db: DB):
    """[고르기] 창의 저장 — 고른 것을 통째로, 그리고 [고른 것만/전부]."""
    from blackmoa.services import outsider as OUT
    a = await AG.get_owned(db, user.id, agent_id)
    if body.scope is not None:
        a.outsider = {**(a.outsider or {}), **OUT.clean_patch({f"{body.kind}_scope": body.scope})}
    await OUT.set_picks(db, a, body.kind, ids=body.ids, faq_ids=body.faq_ids)
    audit.record(db, "agent.outsider_picks", actor_id=user.id, target_type="agent", target_id=str(a.id),
                 meta={"kind": body.kind, "scope": body.scope, "n": len(body.ids) + len(body.faq_ids)})
    await db.commit()
    await db.refresh(a)
    return await _outsider_view(db, user, a)


@router.get("/agents/{agent_id}/tools")
async def agent_tools(agent_id: uuid.UUID, user: CurrentUser, db: DB, audience: str = "owner"):
    from blackmoa.pipeline.context import TurnContext
    from blackmoa.pipeline.tools.base import tool_names_for
    a = await AG.get_owned(db, user.id, agent_id)
    from blackmoa.services.companies import switch as CO

    prof = await PF.shown(db, user.id)
    plan = await P.plan_for_user(db, user)
    features = {"feature:mail"} | ({"feature:companies"} if await CO.enabled(db) else set())
    ctx = TurnContext(owner=user, agent=a, audience=audience, conversation_id=uuid.uuid4(), turn_id=None, profile=prof, plan=plan,
                      memory=AgentMemory(a.id, audience), features=features)
    names = set(tool_names_for(ctx))
    reg = all_tools()
    return {"audience": audience, "tools": [{"name": n, "description": reg[n].tool_description, "core": reg[n].core,
                                             "requires_capability": reg[n].requires_capability, "requires_feature": reg[n].requires_feature}
                                            for n in sorted(names)]}


@router.get("/personas/presets")
async def personas(user: CurrentUser):
    return {"items": preset_list(user.locale or "ko")}


@router.get("/models")
async def models(user: CurrentUser, db: DB):
    # What this owner may pick — the pool as their plan narrows it (plan/33), so the picker
    # cannot offer something the save would then refuse.
    rows = await CAT.allowed_for_plan(db, await P.plan_for_user(db, user))
    return {"items": [{"provider": m.provider, "model_id": m.model_id, "display_name": m.display_name, "context_window": m.context_window,
                       "supports_thinking": m.supports_thinking, "supports_vision": m.supports_vision, "is_default": m.is_default,
                       "credit_per_1k_input": float(m.credit_per_1k_input), "credit_per_1k_output": float(m.credit_per_1k_output)} for m in rows]}


# ── share links ────────────────────────────────────────────────────

class LinkCreate(BaseModel):
    label: str = ""
    handle: str | None = None
    expires_at: datetime | None = None
    max_conversations: int | None = None
    # 방문자에게 보일 모양 (plan/71): chat(기본) · stage(배경 위에 비서가 서고 게임처럼 말하는 무대).
    layout: str = "chat"


@router.get("/agents/{agent_id}/links")
async def list_links(agent_id: uuid.UUID, user: CurrentUser, db: DB):
    a = await AG.get_owned(db, user.id, agent_id, include_archived=True)
    rows = (await db.execute(select(ShareLink).where(ShareLink.agent_id == a.id).order_by(ShareLink.created_at))).scalars().all()
    return {"items": [dict(link_out(l_), effective_status=AG.link_effective_status(l_, a)) for l_ in rows]}


@router.post("/agents/{agent_id}/links", status_code=201)
async def create_link(agent_id: uuid.UUID, body: LinkCreate, user: CurrentUser, db: DB):
    a = await AG.get_owned(db, user.id, agent_id)
    l_ = await AG.create_link(db, user, a, label=body.label, handle=body.handle, expires_at=body.expires_at, max_conversations=body.max_conversations)
    if body.layout in AG.LINK_LAYOUTS and body.layout != "chat":
        l_.settings = {**(l_.settings or {}), "layout": body.layout}
    audit.record(db, "link_create", actor_id=user.id, target_type="share_link", target_id=l_.id, meta={"code": l_.code})
    await db.commit()
    return link_out(l_)


class LinkPatch(BaseModel):
    label: str | None = None
    status: str | None = None
    expires_at: datetime | None = None
    max_conversations: int | None = None
    # plan/38: whether other members' secretaries may talk to this one, and how many of their
    # turns a day the owner will pay for.
    settings: dict | None = None


@router.patch("/links/{link_id}")
async def patch_link(link_id: uuid.UUID, body: LinkPatch, user: CurrentUser, db: DB):
    l_ = await AG.get_link_owned(db, user.id, link_id)
    if body.label is not None:
        l_.label = body.label[:80]
    if body.status in ("active", "paused", "revoked"):
        if l_.status == "revoked" and body.status != "revoked":
            # 거둔 링크를 되살리는 것도 "하나" 를 지킨다.
            other = (await db.execute(select(ShareLink.id).where(ShareLink.agent_id == l_.agent_id, ShareLink.id != l_.id,
                                                                 ShareLink.status != "revoked").limit(1))).first()
            if other:
                raise Conflict("this secretary already has a public link", code="link_exists")
        l_.status = body.status
    if body.expires_at is not None:
        l_.expires_at = body.expires_at
    if body.max_conversations is not None:
        l_.max_conversations = body.max_conversations or None
    if body.settings is not None:
        merged = dict(l_.settings or {})
        if "allow_agents" in body.settings:
            merged["allow_agents"] = bool(body.settings["allow_agents"])
        if "findable" in body.settings:
            merged["findable"] = bool(body.settings["findable"])
        if body.settings.get("layout") in AG.LINK_LAYOUTS:
            merged["layout"] = body.settings["layout"]
        if "agent_turns_per_day" in body.settings:
            try:
                merged["agent_turns_per_day"] = max(0, min(500, int(body.settings["agent_turns_per_day"] or 0)))
            except (TypeError, ValueError):
                pass
        l_.settings = merged
    await db.commit()
    return link_out(l_)


@router.delete("/links/{link_id}")
async def delete_link(link_id: uuid.UUID, user: CurrentUser, db: DB):
    l_ = await AG.get_link_owned(db, user.id, link_id)
    l_.status = "revoked"
    await db.commit()
    return {"ok": True}


def _qr_png(url: str) -> bytes:
    import io

    import qrcode
    img = qrcode.make(url)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


@router.get("/links/{link_id}/qr.png")
async def link_qr(link_id: uuid.UUID, user: CurrentUser, db: DB):

    from fastapi.responses import Response
    l_ = await AG.get_link_owned(db, user.id, link_id)
    png = await pools.to_thread("misc", _qr_png, public_link_url(l_.code))
    return Response(png, media_type="image/png")


# ── memory browser ─────────────────────────────────────────────────

def _check_namespace(namespace: str) -> str:
    from blackmoa.core.errors import NotFound
    from blackmoa.memory.facade import NAMESPACES
    if namespace not in NAMESPACES:
        raise NotFound("namespace not found", code="namespace_not_found")
    return namespace


@router.get("/agents/{agent_id}/memory")
async def memory_overview(agent_id: uuid.UUID, user: CurrentUser, db: DB):
    a = await AG.get_owned(db, user.id, agent_id, include_archived=True)
    mem = AgentMemory(a.id, "owner")
    return {"counts": await mem.counts()}


@router.get("/agents/{agent_id}/memory/{namespace}/notes")
async def memory_notes(agent_id: uuid.UUID, namespace: str, user: CurrentUser, db: DB, category: str | None = None, limit: int = 100, offset: int = 0):
    a = await AG.get_owned(db, user.id, agent_id, include_archived=True)
    mem = AgentMemory(a.id, "owner")
    ns = _check_namespace(namespace)
    notes = await mem.list_notes(ns, category=category, limit=min(limit, 200), offset=offset)
    # 범위는 기억마다 붙는다. 안 적힌 옛 기억은 그 방의 옛 뜻으로 읽는다 (plan/48 §2).
    return {"items": [{**n.to_dict(), "body": n.body[:400],
                       "visibility": MEM.note_level(ns, n.to_dict())} for n in notes]}


@router.get("/agents/{agent_id}/memory/{namespace}/note")
async def memory_note(agent_id: uuid.UUID, namespace: str, id: str, user: CurrentUser, db: DB):
    a = await AG.get_owned(db, user.id, agent_id, include_archived=True)
    ns = _check_namespace(namespace)
    n = await AgentMemory(a.id, "owner").read(ns, id)
    if n is None:
        from blackmoa.core.errors import NotFound
        raise NotFound("note not found")
    return {**n.to_dict(), "visibility": MEM.note_level(ns, n.to_dict())}


class NoteIn(BaseModel):
    title: str
    body: str
    category: str = "notes"
    tags: list[str] = []
    pinned: bool = False
    importance: str = "medium"
    namespace: str = "owner"
    #: 이 기억이 어디까지 나가는가. 안 주면 비공개다 (plan/48 §2).
    visibility: str | None = None
    id: str | None = None


@router.post("/agents/{agent_id}/memory/notes")
async def memory_write(agent_id: uuid.UUID, body: NoteIn, user: CurrentUser, db: DB):
    a = await AG.get_owned(db, user.id, agent_id, include_archived=True)
    mem = AgentMemory(a.id, "owner")
    ns = _check_namespace(body.namespace)
    if body.id:

        from blackmoa.core.errors import NotFound
        from blackmoa.memory.facade import namespace_root
        from blackmoa.memory.synapse import index_cache
        idx = await index_cache.get(namespace_root(a.id, ns))
        if await pools.to_thread("misc", idx.notes.read, body.id) is None:
            raise NotFound("note not found")  # also rejects ids that escape the namespace (path guard)
        # 고치는 경우 범위를 안 보내면 **있던 값을 지킨다.** 제목만 고치러 들어온
        # 요청이 그 기억을 조용히 비공개로 되돌리면 안 된다.
        had = await pools.to_thread("misc", idx.notes.read, body.id)
        level = VIS.normalize(body.visibility) if body.visibility else MEM.note_level(ns, had.to_dict())
        n = await pools.to_thread("misc", idx.notes.write, title=body.title, body=body.body, category=body.category, tags=body.tags,
                                    pinned=body.pinned, importance=body.importance, source="owner_console", note_id=body.id,
                                    meta={**(had.meta or {}), "visibility": level})
        await pools.to_thread("misc", idx.index_note, n)
    else:
        level = VIS.normalize(body.visibility)
        n = await mem.remember(title=body.title, body=body.body, category=body.category, tags=body.tags, pinned=body.pinned,
                               importance=body.importance, source="owner_console", namespace=ns, visibility=level)
    return {**n.to_dict(), "visibility": level}


@router.delete("/agents/{agent_id}/memory/{namespace}/note")
async def memory_delete(agent_id: uuid.UUID, namespace: str, id: str, user: CurrentUser, db: DB):
    a = await AG.get_owned(db, user.id, agent_id, include_archived=True)
    ok = await AgentMemory(a.id, "owner").forget(_check_namespace(namespace), id)
    return {"ok": ok}


@router.get("/agents/{agent_id}/memory/search")
async def memory_search(agent_id: uuid.UUID, q: str, user: CurrentUser, db: DB):
    a = await AG.get_owned(db, user.id, agent_id, include_archived=True)
    return {"items": await AgentMemory(a.id, "owner").search(q, top_k=12)}


def _fact_out(f) -> dict:
    return {"id": str(f.id), "subject": f.subject, "predicate": f.predicate, "object": f.object, "kind": f.kind,
            "confidence": f.confidence, "visibility": VIS.normalize(f.visibility),
            # 범위가 아니라 **그 손님에 대한 사실**이라는 표시다. 범위 칸을 주지 않는다:
            # 바꾸게 두면 손님 얘기가 주인에 대한 사실이 된다.
            "about_visitor": f.visibility == "visitor_private",
            "updated_at": f.updated_at.isoformat()}


@router.get("/agents/{agent_id}/facts")
async def list_facts(agent_id: uuid.UUID, user: CurrentUser, db: DB, status: str = "active", limit: int = 200):
    """**이 비서가** 알게 된 사실 (plan/49).

    사실은 비서가 대화에서 만들어 낸 것이라 그 비서의 것이다. 주인이 직접 넣은 것은
    [내 정보] 에 있고 모든 비서가 전부 본다. 둘은 다른 것이고, 다른 자리에 있어야 한다.
    """
    from blackmoa.models import Fact

    await AG.get_owned(db, user.id, agent_id, include_archived=True)
    rows = (await db.execute(select(Fact).where(
        Fact.owner_id == user.id, Fact.status == status,
        (Fact.agent_id == agent_id) | (Fact.agent_id.is_(None)))
        .order_by(Fact.updated_at.desc()).limit(min(limit, 500)))).scalars().all()
    return {"items": [_fact_out(f) for f in rows]}


class FactPatch(BaseModel):
    visibility: str | None = None
    status: str | None = None
    object: str | None = None


@router.patch("/facts/{fact_id}")
async def patch_fact(fact_id: uuid.UUID, body: FactPatch, user: CurrentUser, db: DB):
    from blackmoa.core.errors import NotFound
    from blackmoa.models import Fact
    f = await db.get(Fact, fact_id)
    if f is None or f.owner_id != user.id:
        raise NotFound("fact not found")
    # `visitor_private` 는 범위가 아니라 **그 방문자에 대한 사실**이라는 표시다.
    # 범위 칸으로 바꿀 수 없다: 바꾸는 순간 손님 얘기가 주인의 원장이 된다.
    if body.visibility in VIS.LEVELS and f.visibility != "visitor_private":
        f.visibility = VIS.normalize(body.visibility)
    if body.status in ("active", "rejected"):
        f.status = body.status
    if body.object:
        f.object = body.object[:2000]
    await db.commit()
    return {"ok": True}
