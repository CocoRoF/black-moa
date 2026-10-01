from __future__ import annotations

import csv
import io
import uuid
from datetime import date, datetime

from fastapi import APIRouter, File, UploadFile
from pydantic import BaseModel, Field
from sqlalchemy import select

from blackmoa.core.deps import DB, CurrentUser
from blackmoa.core.errors import NotFound, ValidationFailed
from blackmoa.core.ratelimit import limiter
from blackmoa.models import NetworkInteraction, NetworkProposal
from blackmoa.services import network as N
from blackmoa.services import people as P
from blackmoa.services import uploads as U

router = APIRouter(prefix="/api/network", tags=["network"])

# ── 한 사람에게 몇 번까지 (plan/43) ──────────────────────────────────
#
# 연결을 몇 명과 맺든 그건 그 사람의 사정이다. 문제가 되는 것은 **한 사람에게 반복해서**
# 닿는 일이다. 연결할 때마다 상대의 인박스에 한 줄이 남으니, 끊었다 이으면 그 줄이 또
# 생긴다. 그래서 전체에 천장을 두는 대신 상대별로 센다: 같은 사람에게 짧은 사이에 여러
# 번 닿으면 그 사람에게는 더 보낼 수 없다. 다른 사람들과는 아무 상관이 없다.
#
# 카드·선·메모는 내 관계도 안의 일이라 아무에게도 닿지 않는다. 남는 위험은 스크립트가
# 밀어 넣는 것뿐이라 사람이 닿지 않는 높이에만 천장을 둔다.
CARD_PER_MIN = 60
CARD_PER_HOUR = 900
#: 주소록을 통째로 올리는 일은 하루에 몇 번 있는 일이 아니다.
IMPORT_PER_HOUR = 5


def _budget(user, what: str, limit: int, per: int) -> None:
    limiter.check(f"net:{what}:{user.id}", limit, per)


def _card_budget(user) -> None:
    _budget(user, "card", CARD_PER_MIN, 60)
    _budget(user, "card-hr", CARD_PER_HOUR, 3600)


@router.get("/graph")
async def graph(user: CurrentUser, db: DB, center: uuid.UUID | None = None, depth: int = 2, kinds: str | None = None, tags: str | None = None,
                q: str | None = None):
    # The middle of an ego network is not optional, so it is created on the first look
    # rather than asked for (plan/31).
    await P.self_node(db, user)
    await db.commit()
    return await N.graph_view(db, user.id, center=center, depth=min(depth, 3), kinds=kinds.split(",") if kinds else None,
                              tags=tags.split(",") if tags else None, q=q)


# ── people: the directory, friend links and guests (plan/31) ────────

class LinkIn(BaseModel):
    user_id: uuid.UUID
    note: str | None = Field(default=None, max_length=300)


@router.get("/people/search")
async def people_search(user: CurrentUser, db: DB, q: str = "", limit: int = 10):
    """Find an account you can already name. Never a browsable directory."""
    return {"items": await P.directory_search(db, user, q, limit=limit)}


@router.get("/people/mentionable")
async def people_mentionable(user: CurrentUser, db: DB, q: str = "", limit: int = 8):
    """Who `@` can offer: the people I am connected to, either way (plan/42 §11)."""
    return {"items": await P.mentionable(db, user, q, limit=limit)}


@router.get("/people/suggestions")
async def people_suggestions(user: CurrentUser, db: DB, limit: int = 24):
    """Who you could connect to, each with the reason. Never a listing of accounts."""
    return {"items": await P.suggestions(db, user, limit=min(50, max(1, limit)))}


@router.get("/people/{user_id}/link")
async def person_link(user_id: uuid.UUID, user: CurrentUser, db: DB):
    """What the space between me and this person is called right now: mutual · outgoing ·
    incoming · none (plan/69). Every button on the site that connects or disconnects reads
    this one small answer, so they cannot disagree."""
    if user_id == user.id:
        return {"status": "self"}
    return await P.link_between(db, user.id, user_id)


@router.post("/people/{user_id}/follow")
async def follow_person(user_id: uuid.UUID, user: CurrentUser, db: DB):
    """Connect to somebody. Nobody is asked and nothing waits (plan/43)."""
    out = await P.connect(db, user, user_id)
    await db.commit()
    return {"following": True, **out}


@router.delete("/people/{user_id}/follow")
async def unfollow_person(user_id: uuid.UUID, user: CurrentUser, db: DB):
    out = await P.disconnect(db, user, user_id)
    await db.commit()
    return {"following": False, **out}


@router.get("/people/links")
async def people_links(user: CurrentUser, db: DB):
    return await P.links_for(db, user)


@router.delete("/people/links/{other_id}")
async def people_remove(other_id: uuid.UUID, user: CurrentUser, db: DB):
    """Undo my own half. What the other person chose is theirs (plan/43)."""
    out = await P.disconnect(db, user, other_id)
    await db.commit()
    return out


# Last of the /people routes on purpose: a path parameter declared above the literal ones
# would swallow /people/links and /people/search.
@router.get("/people/{user_id}/posts")
async def people_posts(user_id: uuid.UUID, user: CurrentUser, db: DB, page: int = 1, limit: int = 12):
    """One page of somebody's posts, filtered to what this reader may see (plan/42 §14).

    A page of tiles turns pages. Somebody's writing is a shelf you look through, and the
    grid is how it is looked through — endless scroll here would only make the rest of
    their profile unreachable.
    """
    from blackmoa.models import User as _User
    from blackmoa.services import blog as B

    target = await db.get(_User, user_id)
    if target is None or target.status != "active":
        raise NotFound("account not found", code="account_not_found")
    per = max(1, min(limit, 30))
    page = max(1, page)
    rows, total = await B.page_of_published(db, target.id, user, page=page, per=per)
    return {"items": [B.out(p) for p in rows], "page": page,
            "pages": max(1, -(-total // per)), "total": total}


@router.get("/people/{user_id}")
async def people_profile(user_id: uuid.UUID, user: CurrentUser, db: DB):
    from blackmoa.models import User as _User
    target = await db.get(_User, user_id)
    if target is None or target.status != "active":
        raise NotFound("account not found", code="account_not_found")
    return await P.profile_of(db, user, target)


@router.get("/guests")
async def guests(user: CurrentUser, db: DB, limit: int = 100):
    """Everyone who actually talked to this owner's secretaries, account or not."""
    return {"items": await P.guests(db, user, limit=min(300, max(1, limit)))}


@router.post("/guests/{visitor_id}", status_code=201)
async def add_guest(visitor_id: uuid.UUID, user: CurrentUser, db: DB):
    _card_budget(user)
    node = await P.add_guest(db, user, visitor_id)
    await db.commit()
    return N.node_dict(node)


@router.get("/stats")
async def stats(user: CurrentUser, db: DB):
    return await N.stats(db, user.id)


@router.get("/nodes")
async def nodes(user: CurrentUser, db: DB, q: str = "", kind: str | None = None, tag: str | None = None, limit: int = 50):
    return {"items": await N.search(db, user.id, q, kind=kind, tag=tag, limit=min(limit, 200))}


class NodeIn(BaseModel):
    kind: str = "person"
    name: str
    aliases: list[str] = []
    attrs: dict = {}
    tags: list[str] = []
    importance: int = 3
    notes: str = ""


@router.post("/nodes", status_code=201)
async def create_node(body: NodeIn, user: CurrentUser, db: DB):
    _card_budget(user)
    n = await N.create_node(db, user, kind=body.kind, name=body.name, aliases=body.aliases, attrs=body.attrs, tags=body.tags,
                            importance=body.importance, notes=body.notes)
    await db.commit()
    return N.node_dict(n)


# ── what the graph opens (plan/44 §8) ────────────────────────────────
#
# Pressing anything in the picture opens the same panel: a memo, and the two ways to reach
# whoever it is about. A person is a row in my graph; a published secretary is not a row at
# all, so the memo about one lives in its own place. The screen should not have to know
# which, so one door answers for both.

class MemoIn(BaseModel):
    body: str = Field(default="", max_length=4000)


@router.get("/subjects/agent/{agent_id}")
async def agent_subject(agent_id: uuid.UUID, user: CurrentUser, db: DB):
    """A published secretary as the graph's panel needs it: who it is, and my memo."""
    from blackmoa.models import Agent, AgentMemo, ShareLink
    from blackmoa.models import User as _User
    from blackmoa.services import agents as A

    row = (await db.execute(select(ShareLink, Agent).join(Agent, Agent.id == ShareLink.agent_id)
                            .where(ShareLink.agent_id == agent_id, A.open_link(), Agent.status == "active")
                            .order_by(ShareLink.created_at))).first()
    if row is None:
        raise NotFound("secretary not found", code="agent_not_found")
    link, agent = row
    holder = await db.get(_User, agent.owner_id)
    memo = (await db.execute(select(AgentMemo).where(AgentMemo.owner_id == user.id,
                                                     AgentMemo.agent_id == agent.id))).scalars().first()
    return {"kind": "agent", "id": str(agent.id), "name": agent.name, "avatar_url": agent.avatar_url,
            "link_code": link.code, "notes": memo.body if memo else "",
            "owner": {"id": str(holder.id), "name": P.display_of(holder)} if holder else None}


@router.put("/subjects/agent/{agent_id}/memo")
async def agent_memo(agent_id: uuid.UUID, body: MemoIn, user: CurrentUser, db: DB):
    _card_budget(user)
    from blackmoa.models import Agent, AgentMemo

    if await db.get(Agent, agent_id) is None:
        raise NotFound("secretary not found", code="agent_not_found")
    memo = (await db.execute(select(AgentMemo).where(AgentMemo.owner_id == user.id,
                                                     AgentMemo.agent_id == agent_id))).scalars().first()
    if memo is None:
        memo = AgentMemo(owner_id=user.id, agent_id=agent_id, body=body.body)
        db.add(memo)
    else:
        memo.body = body.body
    await db.commit()
    return {"notes": memo.body}


@router.get("/nodes/{node_id}")
async def get_node(node_id: uuid.UUID, user: CurrentUser, db: DB):
    n = await N.get_node(db, user.id, node_id)
    nb = await N.neighbors(db, user.id, node_id, depth=1)
    inter = (await db.execute(select(NetworkInteraction).where(NetworkInteraction.node_id == node_id).order_by(NetworkInteraction.at.desc()).limit(20))).scalars().all()
    return {**N.node_dict(n), "edges": nb["edges"], "neighbors": [x for x in nb["nodes"] if x["id"] != str(node_id)],
            "interactions": [{"id": str(i.id), "kind": i.kind, "at": i.at.isoformat(), "summary": i.summary} for i in inter]}


@router.patch("/nodes/{node_id}")
async def patch_node(node_id: uuid.UUID, body: dict, user: CurrentUser, db: DB):
    _card_budget(user)
    n = await N.get_node(db, user.id, node_id)
    await N.update_node(db, n, body)
    await db.commit()
    return N.node_dict(n)


@router.delete("/nodes/{node_id}")
async def delete_node(node_id: uuid.UUID, user: CurrentUser, db: DB):
    _card_budget(user)
    n = await N.get_node(db, user.id, node_id)
    await db.delete(n)
    await db.commit()
    return {"ok": True}


class MergeIn(BaseModel):
    into_id: uuid.UUID


@router.post("/nodes/{node_id}/merge")
async def merge(node_id: uuid.UUID, body: MergeIn, user: CurrentUser, db: DB):
    _card_budget(user)
    n = await N.merge(db, user.id, node_id, body.into_id)
    await db.commit()
    return N.node_dict(n)


class InteractionIn(BaseModel):
    kind: str = "meeting"
    at: datetime
    summary: str = ""


@router.post("/nodes/{node_id}/interactions", status_code=201)
async def add_interaction(node_id: uuid.UUID, body: InteractionIn, user: CurrentUser, db: DB):
    _card_budget(user)
    await N.add_interaction(db, user.id, node_id, kind=body.kind, at=body.at, summary=body.summary)
    await db.commit()
    return {"ok": True}


class EdgeIn(BaseModel):
    src_id: uuid.UUID
    dst_id: uuid.UUID
    rel: str
    strength: float = 0.5
    attrs: dict = {}
    since: date | None = None


@router.post("/edges", status_code=201)
async def create_edge(body: EdgeIn, user: CurrentUser, db: DB):
    _card_budget(user)
    e = await N.create_edge(db, user.id, src_id=body.src_id, dst_id=body.dst_id, rel=body.rel, strength=body.strength, attrs=body.attrs,
                            since=body.since)
    await db.commit()
    return N.edge_dict(e)


class EdgePatch(BaseModel):
    rel: str | None = Field(default=None, min_length=1, max_length=40)
    strength: float | None = Field(default=None, ge=0.0, le=1.0)
    attrs: dict | None = None
    since: date | None = None
    until: date | None = None


@router.patch("/edges/{edge_id}")
async def patch_edge(edge_id: uuid.UUID, body: EdgePatch, user: CurrentUser, db: DB):
    _card_budget(user)
    from blackmoa.core.errors import NotFound
    from blackmoa.models import NetworkEdge
    e = await db.get(NetworkEdge, edge_id)
    if e is None or e.owner_id != user.id:
        raise NotFound("edge not found")
    if body.rel is not None:
        e.rel = body.rel.strip().lower()
        e.direction = N.RELS.get(e.rel, "directed")
    if body.strength is not None:
        e.strength = body.strength
    if body.attrs is not None:
        e.attrs = {**(e.attrs or {}), **body.attrs}
    if body.since is not None:
        e.since = body.since
    if body.until is not None:
        e.until = body.until
    await db.commit()
    return N.edge_dict(e)


@router.delete("/edges/{edge_id}")
async def delete_edge(edge_id: uuid.UUID, user: CurrentUser, db: DB):
    _card_budget(user)
    await N.delete_edge(db, user.id, edge_id)
    await db.commit()
    return {"ok": True}


@router.get("/path")
async def path(user: CurrentUser, db: DB, from_id: uuid.UUID, to_id: uuid.UUID):
    return await N.shortest_path(db, user.id, from_id, to_id)


@router.get("/proposals")
async def proposals(user: CurrentUser, db: DB, status: str = "pending"):
    if status == "pending":
        # Resolved against real people, and the ones nobody can act on are retired here
        # rather than left to pile up (plan/31).
        items = await P.pending_proposals(db, user)
        await db.commit()
        return {"items": items}
    rows = (await db.execute(select(NetworkProposal).where(NetworkProposal.owner_id == user.id, NetworkProposal.status == status)
                             .order_by(NetworkProposal.created_at.desc()).limit(200))).scalars().all()
    return {"items": [{"id": str(p.id), "kind": p.kind, "payload": p.payload, "confidence": p.confidence, "status": p.status,
                       "agent_id": str(p.agent_id) if p.agent_id else None, "created_at": p.created_at.isoformat()} for p in rows]}


@router.post("/proposals/{pid}/{decision}")
async def decide(pid: uuid.UUID, decision: str, user: CurrentUser, db: DB):
    _card_budget(user)
    if decision not in ("accept", "reject"):
        raise ValidationFailed("bad decision", code="bad_decision")
    if decision == "accept":
        # An accepted person becomes an 인맥 신청 or a bound guest — never a loose card.
        r = await P.accept_proposal(db, user, pid)
        await db.commit()
        return {"ok": True, "did": r["action"]}
    p = await N.decide_proposal(db, user, pid, accept=False)
    await db.commit()
    return {"id": str(p.id), "status": p.status}


@router.post("/import/csv")
async def import_csv(user: CurrentUser, db: DB, file: UploadFile = File(...)):
    _budget(user, "import", IMPORT_PER_HOUR, 3600)
    text = (await U.read_capped(file, U.TEXT_MAX)).decode("utf-8-sig", errors="replace")
    reader = csv.DictReader(io.StringIO(text))
    n = 0
    for row in reader:
        name = (row.get("name") or row.get("이름") or "").strip()
        if not name:
            continue
        attrs = {}
        if row.get("email"):
            attrs["emails"] = [row["email"].strip()]
        if row.get("company"):
            attrs["company"] = row["company"].strip()
        if row.get("title"):
            attrs["title"] = row["title"].strip()
        tags = [t.strip() for t in (row.get("tags") or "").split("|") if t.strip()]
        await N.create_node(db, user, kind=(row.get("kind") or "person").strip(), name=name, attrs=attrs, tags=tags, source="import_csv",
                            notes=(row.get("relation") or "").strip())
        n += 1
        if n >= 2000:
            break
    await db.commit()
    return {"imported": n}
