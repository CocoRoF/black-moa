"""Network graph (plan/10): CRUD, search, neighbors/path, proposals. 외부인에게 누구를 쓸지는 비서의 [지식] 탭 (plan/57)."""
from __future__ import annotations

import uuid
from collections import deque
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import func, or_, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from memora.core import visibility as VISIBILITY
from memora.core.errors import NotFound, ValidationFailed
from memora.models import NetworkEdge, NetworkInteraction, NetworkNode, NetworkProposal, User
from memora.services.outsider import EVERYTHING, Scope

KINDS = ("person", "organization", "group", "project", "place", "event")
RELS = {"colleague": "undirected", "reports_to": "directed", "manages": "directed", "friend": "undirected",
        "family": "undirected", "spouse": "undirected", "parent": "directed", "child": "directed", "sibling": "undirected",
        "client": "directed", "vendor": "directed", "mentor": "directed", "mentee": "directed", "member_of": "directed",
        "works_at": "directed", "founder_of": "directed", "investor_in": "directed", "collaborates_on": "directed",
        "introduced_by": "directed", "knows": "undirected", "partner": "undirected"}


def node_dict(n: NetworkNode, *, viewer: str = "owner") -> dict[str, Any]:
    d = {"id": str(n.id), "kind": n.kind, "name": n.name, "aliases": n.aliases or [], "tags": n.tags or [],
         "importance": n.importance, "source": n.source,
         "last_contact_at": n.last_contact_at.isoformat() if n.last_contact_at else None,
         "attrs": dict(n.attrs or {}), "notes": n.notes or "",
         # Identity (plan/31): self | member | guest | offline. The screen draws a real face
         # for the first three and initials for a card, which is the difference between
         # "this person is here" and "I wrote their name down".
         "person": ("self" if n.is_self else "member" if n.user_id else "guest" if n.visitor_id else "offline"),
         "is_self": bool(n.is_self), "user_id": str(n.user_id) if n.user_id else None,
         "visitor_id": str(n.visitor_id) if n.visitor_id else None, "avatar_url": None}
    if VISIBILITY.normalize_viewer(viewer) != "owner":
        # 이름과 회사까지는 카드가 되지만, 연락처와 생일과 내가 적어 둔 메모는
        # 이 사람의 것이 아니라 **내가 그 사람에 대해 적은 것**이다. 범위와 무관하게
        # 밖으로 내보내지 않는다.
        attrs = dict(n.attrs or {})
        for k in ("emails", "phones", "birthday", "how_we_met", "notes", "address"):
            attrs.pop(k, None)
        d["attrs"] = attrs
        d["notes"] = ""
    return d


def edge_dict(e: NetworkEdge) -> dict[str, Any]:
    return {"id": str(e.id), "src_id": str(e.src_id), "dst_id": str(e.dst_id), "rel": e.rel, "direction": e.direction,
            "strength": e.strength, "since": e.since.isoformat() if e.since else None,
            "until": e.until.isoformat() if e.until else None, "attrs": e.attrs or {}, "source": e.source}


async def get_node(db: AsyncSession, owner_id: uuid.UUID, node_id: uuid.UUID) -> NetworkNode:
    n = await db.get(NetworkNode, node_id)
    if n is None or n.owner_id != owner_id:
        raise NotFound("node not found", code="node_not_found")
    return n


async def create_node(db: AsyncSession, owner: User, *, kind: str, name: str, aliases: list[str] | None = None,
                      attrs: dict | None = None, tags: list[str] | None = None, importance: int = 3, source: str = "manual", external_ref: str | None = None,
                      notes: str = "") -> NetworkNode:
    if kind not in KINDS:
        raise ValidationFailed("bad kind")
    # No ceiling on connections (plan/34): these are people the owner actually knows, and
    # a cap on them limited nothing that costs us anything.
    node = NetworkNode(owner_id=owner.id, kind=kind, name=name.strip()[:200], aliases=[a[:100] for a in (aliases or [])][:10],
                       attrs=attrs or {}, tags=[t[:40] for t in (tags or [])][:20],
                       importance=max(1, min(5, importance)),
                       source=source, external_ref=external_ref, notes=notes[:4000])
    db.add(node)
    await db.flush()
    return node


async def update_node(db: AsyncSession, node: NetworkNode, patch: dict[str, Any]) -> NetworkNode:
    for k in ("kind", "name", "aliases", "attrs", "tags", "importance", "notes", "last_contact_at"):
        if k in patch and patch[k] is not None:
            v = patch[k]
            if k == "kind" and v not in KINDS:
                continue
            if k == "attrs":
                v = {**(node.attrs or {}), **v}
            if k == "last_contact_at" and isinstance(v, str):
                v = datetime.fromisoformat(v)
                if v.tzinfo is None:
                    v = v.replace(tzinfo=UTC)
            if k == "importance":
                v = max(1, min(5, int(v)))
            if k in ("aliases", "tags") and not isinstance(v, list):
                continue
            setattr(node, k, v)
    node.updated_at = datetime.now(UTC)
    return node


async def create_edge(db: AsyncSession, owner_id: uuid.UUID, *, src_id: uuid.UUID, dst_id: uuid.UUID, rel: str,
                      strength: float = 0.5, attrs: dict | None = None,
                      source: str = "manual", since=None) -> NetworkEdge:
    if src_id == dst_id:
        raise ValidationFailed("self edge")
    await get_node(db, owner_id, src_id)
    await get_node(db, owner_id, dst_id)
    rel = rel.strip().lower()[:40]
    direction = RELS.get(rel, "directed")
    existing = (await db.execute(select(NetworkEdge).where(NetworkEdge.owner_id == owner_id, NetworkEdge.src_id == src_id,
                                                           NetworkEdge.dst_id == dst_id, NetworkEdge.rel == rel))).scalars().first()
    if existing:
        existing.strength = strength
        existing.attrs = {**(existing.attrs or {}), **(attrs or {})}
        return existing
    e = NetworkEdge(owner_id=owner_id, src_id=src_id, dst_id=dst_id, rel=rel, direction=direction,
                    strength=max(0.0, min(1.0, strength)), attrs=attrs or {},
                    source=source, since=since)
    db.add(e)
    await db.flush()
    return e


async def delete_edge(db: AsyncSession, owner_id: uuid.UUID, edge_id: uuid.UUID) -> None:
    e = await db.get(NetworkEdge, edge_id)
    if e is None or e.owner_id != owner_id:
        raise NotFound("edge not found")
    await db.delete(e)


async def load_graph(db: AsyncSession, owner_id: uuid.UUID) -> tuple[dict[uuid.UUID, NetworkNode], list[NetworkEdge]]:
    nodes = {n.id: n for n in (await db.execute(select(NetworkNode).where(NetworkNode.owner_id == owner_id))).scalars().all()}
    edges = list((await db.execute(select(NetworkEdge).where(NetworkEdge.owner_id == owner_id))).scalars().all())
    return nodes, edges


def _adj(edges: list[NetworkEdge]) -> dict[uuid.UUID, list[tuple[uuid.UUID, NetworkEdge]]]:
    adj: dict[uuid.UUID, list[tuple[uuid.UUID, NetworkEdge]]] = {}
    for e in edges:
        adj.setdefault(e.src_id, []).append((e.dst_id, e))
        adj.setdefault(e.dst_id, []).append((e.src_id, e))
    return adj


async def search(db: AsyncSession, owner_id: uuid.UUID, q: str, *, viewer: str = "owner", scope: Scope | None = EVERYTHING,
                 kind: str | None = None, tag: str | None = None, limit: int = 10,
                 qvec: list[float] | None = None) -> list[dict[str, Any]]:
    """내 인맥에서 찾는다. 외부인 대화면 ``scope`` — 그 비서가 [지식] 탭에서 고른 사람만 (plan/57).
    ``viewer`` 는 카드에서 무엇을 뺄지(연락처·메모)만 정한다."""
    if scope is None:
        return []
    q = (q or "").strip()
    stmt = select(NetworkNode).where(NetworkNode.owner_id == owner_id)
    if kind:
        stmt = stmt.where(NetworkNode.kind == kind)
    if tag:
        stmt = stmt.where(NetworkNode.tags.any(tag))
    if not scope.all:
        stmt = stmt.where(NetworkNode.id.in_(list(scope.ids) or [uuid.uuid4()]))
    scored: dict[uuid.UUID, tuple[float, NetworkNode]] = {}
    if q:
        pat = "%" + q.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"  # literal match: % and _ are not wildcards
        rows = (await db.execute(stmt.where(or_(NetworkNode.name.ilike(pat, escape="\\"), func.array_to_string(NetworkNode.aliases, " ").ilike(pat, escape="\\"),
                                                NetworkNode.attrs["company"].astext.ilike(pat, escape="\\"),
                                                NetworkNode.attrs["title"].astext.ilike(pat, escape="\\"))).limit(limit * 2))).scalars().all()
        for n in rows:
            sc = 1.0 if n.name.lower() == q.lower() else 0.8 if q.lower() in n.name.lower() else 0.6
            scored[n.id] = (sc, n)
        try:
            trg = (await db.execute(text("""SELECT id, similarity(name, :q) AS s FROM network_nodes
                                            WHERE owner_id = :o AND similarity(name, :q) > 0.25 ORDER BY s DESC LIMIT :l"""),
                                    {"q": q, "o": owner_id, "l": limit})).all()
            for nid, s in trg:
                if nid not in scored:
                    n = await db.get(NetworkNode, nid)
                    if n and scope.has(n.id) and (not kind or n.kind == kind):
                        scored[nid] = (float(s) * 0.9, n)
        except Exception:
            pass
        if qvec is not None:
            vrows = (await db.execute(stmt.where(NetworkNode.embedding.isnot(None)).order_by(NetworkNode.embedding.cosine_distance(qvec)).limit(limit))).scalars().all()
            for i, n in enumerate(vrows):
                if n.id not in scored:
                    scored[n.id] = (0.5 - i * 0.03, n)
    else:
        rows = (await db.execute(stmt.order_by(NetworkNode.importance.desc(), NetworkNode.last_contact_at.desc().nullslast()).limit(limit))).scalars().all()
        for n in rows:
            scored[n.id] = (0.5, n)
    ordered = sorted(scored.values(), key=lambda t: t[0], reverse=True)[:limit]
    return [dict(node_dict(n, viewer=viewer), score=round(sc, 3)) for sc, n in ordered]


async def neighbors(db: AsyncSession, owner_id: uuid.UUID, node_id: uuid.UUID, *, depth: int = 1, viewer: str = "owner",
                    scope: Scope | None = EVERYTHING, max_nodes: int = 60) -> dict[str, Any]:
    """이 사람과 이어진 사람들. 외부인 대화면 고른 사람끼리의 관계만 — 고르지 않은 사람은
    이웃으로도, 관계의 한쪽 끝으로도 나오지 않는다 (plan/57)."""
    nodes, edges = await load_graph(db, owner_id)
    if node_id not in nodes or scope is None or not scope.has(node_id):
        raise NotFound("node not found", code="node_not_found")
    adj = _adj(edges)
    seen = {node_id: 0}
    dq = deque([node_id])
    out_edges: list[NetworkEdge] = []
    while dq:
        cur = dq.popleft()
        if seen[cur] >= depth:
            continue
        for nxt, e in adj.get(cur, []):
            if not scope.has(nxt):
                continue
            out_edges.append(e)
            if nxt not in seen and len(seen) < max_nodes:
                seen[nxt] = seen[cur] + 1
                dq.append(nxt)
    uniq = {e.id: e for e in out_edges}
    return {"center": str(node_id),
            "nodes": [dict(node_dict(nodes[n], viewer=viewer), depth=d) for n, d in seen.items()],
            "edges": [edge_dict(e) for e in uniq.values() if e.src_id in seen and e.dst_id in seen]}


async def shortest_path(db: AsyncSession, owner_id: uuid.UUID, a: uuid.UUID, b: uuid.UUID, *, max_hops: int = 4) -> dict[str, Any]:
    nodes, edges = await load_graph(db, owner_id)
    if a not in nodes or b not in nodes:
        raise NotFound("node not found", code="node_not_found")
    adj = _adj(edges)
    prev: dict[uuid.UUID, tuple[uuid.UUID, NetworkEdge] | None] = {a: None}
    dq = deque([(a, 0)])
    found = False
    while dq:
        cur, d = dq.popleft()
        if cur == b:
            found = True
            break
        if d >= max_hops:
            continue
        for nxt, e in adj.get(cur, []):
            if nxt not in prev:
                prev[nxt] = (cur, e)
                dq.append((nxt, d + 1))
    if not found:
        return {"found": False, "path": []}
    path = []
    cur = b
    while prev[cur] is not None:
        p, e = prev[cur]
        path.append({"from": node_dict(nodes[p]), "rel": e.rel, "to": node_dict(nodes[cur])})
        cur = p
    path.reverse()
    return {"found": True, "hops": len(path), "path": path}


async def recent(db: AsyncSession, owner_id: uuid.UUID, n: int = 10) -> list[dict[str, Any]]:
    rows = (await db.execute(select(NetworkNode).where(NetworkNode.owner_id == owner_id, NetworkNode.last_contact_at.isnot(None))
                             .order_by(NetworkNode.last_contact_at.desc()).limit(n))).scalars().all()
    return [node_dict(r) for r in rows]


async def stats(db: AsyncSession, owner_id: uuid.UUID) -> dict[str, Any]:
    nodes, edges = await load_graph(db, owner_id)
    kinds: dict[str, int] = {}
    tags: dict[str, int] = {}
    for n in nodes.values():
        kinds[n.kind] = kinds.get(n.kind, 0) + 1
        for t in n.tags or []:
            tags[t] = tags.get(t, 0) + 1
    top_tags = sorted(tags.items(), key=lambda kv: kv[1], reverse=True)[:8]
    return {"nodes": len(nodes), "edges": len(edges), "kinds": kinds, "top_tags": top_tags}


async def _decorate_people(db: AsyncSession, out: list[dict[str, Any]]) -> None:
    """Fill in live avatars and names for the nodes that are accounts.

    Read through to `users` rather than copied into the node: a contact who changes their
    photo should change in my graph too, and a stale copy is how a network of real people
    turns back into an address book.
    """
    ids = {uuid.UUID(d["user_id"]) for d in out if d.get("user_id")}
    if not ids:
        return
    from memora.models import User as _U
    users = {u.id: u for u in (await db.execute(select(_U).where(_U.id.in_(ids)))).scalars().all()}
    for d in out:
        u = users.get(uuid.UUID(d["user_id"])) if d.get("user_id") else None
        if u is not None:
            d["avatar_url"] = u.avatar_url
            d["name"] = (u.nickname or u.display_name or d["name"])[:200]


def _hops_from(root: uuid.UUID | None, ids: set[uuid.UUID], edges: list[NetworkEdge]) -> dict[uuid.UUID, int]:
    """Distance from me, in hops. What makes the picture an ego network rather than a cloud."""
    if root is None or root not in ids:
        return {}
    adj: dict[uuid.UUID, set[uuid.UUID]] = {}
    for e in edges:
        if e.src_id in ids and e.dst_id in ids:
            adj.setdefault(e.src_id, set()).add(e.dst_id)
            adj.setdefault(e.dst_id, set()).add(e.src_id)
    out = {root: 0}
    q: deque[uuid.UUID] = deque([root])
    while q:
        cur = q.popleft()
        for nb in adj.get(cur, ()):  # noqa: SIM118
            if nb not in out:
                out[nb] = out[cur] + 1
                q.append(nb)
    return out


async def graph_view(db: AsyncSession, owner_id: uuid.UUID, *, center: uuid.UUID | None = None, depth: int = 2,
                     kinds: list[str] | None = None, tags: list[str] | None = None, q: str | None = None,
                     max_nodes: int = 500) -> dict[str, Any]:
    if center:
        return await neighbors(db, owner_id, center, depth=depth, max_nodes=max_nodes)
    nodes, edges = await load_graph(db, owner_id)
    self_id = next((n.id for n in nodes.values() if n.is_self), None)
    sel = [n for n in nodes.values() if (not kinds or n.kind in kinds) and (not tags or any(t in (n.tags or []) for t in tags))
           and (not q or q.lower() in n.name.lower())]
    sel = sorted(sel, key=lambda n: (n.importance, n.last_contact_at or datetime.min.replace(tzinfo=UTC)), reverse=True)[:max_nodes]
    # Me first, always. A filter that hides the middle of an ego network leaves a picture
    # that cannot be read, so the self node survives every filter.
    if self_id is not None and all(n.id != self_id for n in sel):
        sel.insert(0, nodes[self_id])
    ids = {n.id for n in sel}
    communities = _label_propagation(ids, edges)
    hops = _hops_from(self_id, ids, edges)
    out = [dict(node_dict(n), community=communities.get(n.id, 0), hops=hops.get(n.id)) for n in sel]
    await _decorate_people(db, out)
    drawn = [edge_dict(e) for e in edges if e.src_id in ids and e.dst_id in ids][:3000]
    agents, agent_edges = await _secretaries(db, out)
    hubs, hub_edges = _sources(out, self_id, drawn)
    return {"nodes": out + hubs + agents, "self_id": str(self_id) if self_id else None,
            "edges": drawn + hub_edges + agent_edges, "truncated": len(nodes) > len(sel)}


#: 바깥에서 가져온 사람의 출처 — 이 사람들은 나에게 바로 붙지 않고 "연결한 곳" 을 거쳐 붙는다(plan/79).
#: 이름은 화면이 ``net.source_<키>`` 로 옮긴다.
SOURCE_HUBS: dict[str, dict[str, str]] = {
    "google_contacts": {"provider": "google", "name": "Google 연락처"},
    "kakao_friends": {"provider": "kakao", "name": "카카오톡 친구"},
}


def _sources(out: list[dict[str, Any]], self_id: uuid.UUID | None, drawn: list[dict[str, Any]]) -> tuple[list[dict], list[dict]]:
    """그림의 뼈대를 출처대로 세운다 (plan/79).

    - 연동으로 가져온 사람(Google 연락처 …)은 [나] — [연결한 곳] — [그 사람], 한 칸 떨어져 붙는다. 수백 명이 나를
      둘러싸 Memora 에서 이어진 사람을 가리지 않게, 그리고 어디서 왔는지가 선으로 보이게.
    - Memora 인맥(계정으로 이어진 사람·직접 적은 사람·대화에서 알게 된 사람·방문자)은 나에게 바로 붙는다. 이미 다른
      선으로 닿는 사람은 그대로 두고, 아무 선도 없어 떠 있던 사람만 나에게 잇는다.
    이 선들은 원장(network_edges)에 적지 않는다 — 출처는 그 사람의 성질이지 사이가 아니다.
    """
    if self_id is None:
        return [], []
    me = str(self_id)
    hubs: dict[str, dict[str, Any]] = {}
    lines: list[dict[str, Any]] = []
    touched = {x for e in drawn for x in (e["src_id"], e["dst_id"])}
    for d in out:
        if d.get("is_self"):
            continue
        src = d.get("source") or ""
        if src in SOURCE_HUBS and not d.get("user_id"):
            hub = hubs.get(src)
            if hub is None:
                meta = SOURCE_HUBS[src]
                hub = hubs[src] = {"id": f"source:{src}", "kind": "source", "name": meta["name"], "aliases": [], "tags": [],
                                   "importance": 4, "source": src, "last_contact_at": None,
                                   "attrs": {"provider": meta["provider"], "count": 0}, "notes": "", "person": "source",
                                   "is_self": False, "user_id": None, "visitor_id": None, "avatar_url": None,
                                   "community": 900 + list(SOURCE_HUBS).index(src), "hops": 1}
                lines.append({"id": f"source-edge:{src}", "src_id": me, "dst_id": hub["id"], "rel": "source",
                              "direction": "undirected", "strength": 0.9, "since": None, "until": None, "attrs": {}, "source": src})
            hub["attrs"]["count"] += 1
            lines.append({"id": f"from:{src}:{d['id']}", "src_id": hub["id"], "dst_id": d["id"], "rel": "imported",
                          "direction": "undirected", "strength": 0.3, "since": None, "until": None, "attrs": {}, "source": src})
            d["community"] = 900 + list(SOURCE_HUBS).index(src)     # 같은 곳에서 온 사람은 같은 색
        elif d.get("hops") is None and (d.get("kind") == "person" or d["id"] not in touched):
            # 떠 있던 Memora 인맥 — 나에게 바로. 사람이 아닌 카드(회사 …)는 선이 하나도 없을 때만: 이미 누군가와
            # 이어진 회사는 그 사람을 거쳐 닿는다.
            lines.append({"id": f"mine:{d['id']}", "src_id": me, "dst_id": d["id"], "rel": "network",
                          "direction": "undirected", "strength": 0.5, "since": None, "until": None, "attrs": {}, "source": d.get("source") or ""})
    # 더한 선까지 넣어 나로부터의 거리를 다시 잰다 — 사람을 거쳐 닿는 회사도 제 거리를 얻는다.
    adj: dict[str, set[str]] = {}
    for e in drawn + lines:
        adj.setdefault(e["src_id"], set()).add(e["dst_id"])
        adj.setdefault(e["dst_id"], set()).add(e["src_id"])
    dist = {me: 0}
    q: deque[str] = deque([me])
    while q:
        cur = q.popleft()
        for nb in adj.get(cur, ()):
            if nb not in dist:
                dist[nb] = dist[cur] + 1
                q.append(nb)
    for d in [*out, *hubs.values()]:
        if d["id"] in dist:
            d["hops"] = dist[d["id"]]
    return list(hubs.values()), lines


async def _secretaries(db: AsyncSession, people: list[dict[str, Any]]) -> tuple[list[dict], list[dict]]:
    """The secretaries hanging off the people in this picture (plan/43 §6).

    A member with a secretary anybody can talk to is reachable in a way a name on a card is
    not, and the graph should say so: the secretary hangs off its owner, and pressing it
    opens that conversation. Only published ones — a secretary nobody can reach is not a
    door.
    """
    from memora.models import Agent, ShareLink
    from memora.services import agents as A

    owners = {uuid.UUID(d["user_id"]): d for d in people if d.get("user_id")}
    if not owners:
        return [], []
    rows = (await db.execute(
        select(ShareLink, Agent).join(Agent, Agent.id == ShareLink.agent_id)
        .where(ShareLink.owner_id.in_(owners), A.open_link(), Agent.status == "active")
        .order_by(ShareLink.created_at))).all()
    nodes: list[dict[str, Any]] = []
    lines: list[dict[str, Any]] = []
    seen: set[uuid.UUID] = set()
    for link, agent in rows:
        if agent.id in seen:
            continue
        seen.add(agent.id)
        owner = owners.get(link.owner_id)
        if owner is None:
            continue
        nid = f"agent:{agent.id}"
        nodes.append({"id": nid, "kind": "agent", "name": agent.name, "aliases": [], "tags": [],
                      "importance": 2, "source": "link",
                      "last_contact_at": None, "attrs": {}, "notes": "",
                      "person": "agent", "is_self": False, "user_id": None, "visitor_id": None,
                      "avatar_url": agent.avatar_url, "community": owner.get("community", 0),
                      "hops": (owner.get("hops") or 0) + 1,
                      # What the screen needs to open the door.
                      "link_code": link.code, "owner_node_id": owner["id"]})
        lines.append({"id": f"agent-edge:{agent.id}", "src_id": owner["id"], "dst_id": nid,
                      "rel": "secretary", "direction": "undirected", "strength": 0.5,
                      "since": None, "until": None, "attrs": {}, "source": "link"})
    return nodes, lines


def _label_propagation(ids: set[uuid.UUID], edges: list[NetworkEdge], iters: int = 8) -> dict[uuid.UUID, int]:
    label = {nid: i for i, nid in enumerate(sorted(ids, key=str))}
    adj: dict[uuid.UUID, list[uuid.UUID]] = {}
    for e in edges:
        if e.src_id in ids and e.dst_id in ids:
            adj.setdefault(e.src_id, []).append(e.dst_id)
            adj.setdefault(e.dst_id, []).append(e.src_id)
    for _ in range(iters):
        changed = False
        for nid in ids:
            nb = adj.get(nid)
            if not nb:
                continue
            counts: dict[int, int] = {}
            for m in nb:
                counts[label[m]] = counts.get(label[m], 0) + 1
            best = max(counts.items(), key=lambda kv: (kv[1], -kv[0]))[0]
            if best != label[nid]:
                label[nid] = best
                changed = True
        if not changed:
            break
    remap = {}
    return {nid: remap.setdefault(lab, len(remap)) for nid, lab in label.items()}


async def merge(db: AsyncSession, owner_id: uuid.UUID, node_id: uuid.UUID, into_id: uuid.UUID) -> NetworkNode:
    a = await get_node(db, owner_id, node_id)
    b = await get_node(db, owner_id, into_id)
    b.aliases = list(dict.fromkeys((b.aliases or []) + [a.name] + (a.aliases or [])))[:20]
    b.attrs = {**(a.attrs or {}), **(b.attrs or {})}
    b.tags = list(dict.fromkeys((b.tags or []) + (a.tags or [])))
    b.notes = (b.notes or "") + ("\n" + a.notes if a.notes else "")
    edges = (await db.execute(select(NetworkEdge).where(NetworkEdge.owner_id == owner_id,
                                                        or_(NetworkEdge.src_id == a.id, NetworkEdge.dst_id == a.id)))).scalars().all()
    for e in edges:
        src = b.id if e.src_id == a.id else e.src_id
        dst = b.id if e.dst_id == a.id else e.dst_id
        if src == dst:
            await db.delete(e)
            continue
        dup = (await db.execute(select(NetworkEdge).where(NetworkEdge.owner_id == owner_id, NetworkEdge.src_id == src,
                                                          NetworkEdge.dst_id == dst, NetworkEdge.rel == e.rel))).scalars().first()
        if dup and dup.id != e.id:
            await db.delete(e)
        else:
            e.src_id, e.dst_id = src, dst
    await db.execute(text("UPDATE network_interactions SET node_id = :b WHERE node_id = :a"), {"a": a.id, "b": b.id})
    # 합쳐지는 사람을 외부인에게 쓰라고 고른 비서는, 합친 뒤의 사람을 고른 것이다 (plan/57).
    # 그대로 두면 행이 지워지는 쪽과 함께 사라져, 합치기만 했는데 공개가 거둬진다.
    await db.execute(text("""INSERT INTO agent_disclosures (id, agent_id, kind, node_id)
                             SELECT gen_random_uuid(), d.agent_id, 'network', :b FROM agent_disclosures d
                              WHERE d.node_id = :a
                                AND NOT EXISTS (SELECT 1 FROM agent_disclosures x WHERE x.agent_id = d.agent_id AND x.node_id = :b)"""),
                     {"a": a.id, "b": b.id})
    await db.delete(a)
    return b


async def add_interaction(db: AsyncSession, owner_id: uuid.UUID, node_id: uuid.UUID, *, kind: str, at: datetime,
                          summary: str = "", ref: dict | None = None) -> None:
    n = await get_node(db, owner_id, node_id)
    db.add(NetworkInteraction(owner_id=owner_id, node_id=node_id, kind=kind, at=at, summary=summary[:1000], ref=ref or {}))
    if n.last_contact_at is None or at > n.last_contact_at:
        n.last_contact_at = at


async def propose(db: AsyncSession, owner_id: uuid.UUID, *, agent_id: uuid.UUID | None, kind: str, payload: dict,
                  confidence: float = 0.5, source_turn_id: uuid.UUID | None = None) -> NetworkProposal:
    if kind not in ("add_node", "add_edge", "update_attr", "merge"):
        raise ValidationFailed("bad proposal kind")
    p = NetworkProposal(owner_id=owner_id, agent_id=agent_id, kind=kind, payload=payload, confidence=confidence,
                        source_turn_id=source_turn_id)
    db.add(p)
    await db.flush()
    return p


async def decide_proposal(db: AsyncSession, owner: User, proposal_id: uuid.UUID, accept: bool) -> NetworkProposal:
    p = await db.get(NetworkProposal, proposal_id)
    if p is None or p.owner_id != owner.id:
        raise NotFound("proposal not found")
    if p.status != "pending":
        return p
    p.status = "accepted" if accept else "rejected"
    p.decided_at = datetime.now(UTC)
    if accept:
        pl = p.payload or {}
        # `add_node` is not decided here any more: a person proposal is resolved against
        # real people and accepted through `services/people.accept_proposal`, which either
        # sends a connection request or binds a guest. Minting a card from free text is the
        # thing that filled this queue with rows nobody could act on (plan/31).
        if p.kind == "add_edge":
            await create_edge(db, owner.id, src_id=uuid.UUID(pl["src_id"]), dst_id=uuid.UUID(pl["dst_id"]), rel=pl.get("rel", "knows"),
                              strength=float(pl.get("strength", 0.5)), attrs=pl.get("attrs"), source="chat_derived")
        elif p.kind == "update_attr":
            node = await get_node(db, owner.id, uuid.UUID(pl["node_id"]))
            await update_node(db, node, {"attrs": pl.get("attrs", {}), "tags": pl.get("tags", node.tags)})
        elif p.kind == "merge":
            await merge(db, owner.id, uuid.UUID(pl["node_id"]), uuid.UUID(pl["into_id"]))
    return p


async def match_visitor(db: AsyncSession, owner_id: uuid.UUID, *, name: str | None, email: str | None,
                        company: str | None = None) -> tuple[NetworkNode | None, float]:
    """Best-effort match of a self-identified visitor to a node."""
    cands: dict[uuid.UUID, tuple[float, NetworkNode]] = {}
    if email:
        rows = (await db.execute(text("""SELECT id FROM network_nodes WHERE owner_id=:o AND attrs->'emails' ? :e"""),
                                 {"o": owner_id, "e": email.lower()})).all()
        for (nid,) in rows:
            n = await db.get(NetworkNode, nid)
            if n:
                cands[nid] = (0.95, n)
    if name:
        for r in await search(db, owner_id, name, limit=5):
            nid = uuid.UUID(r["id"])
            sc = r["score"]
            if company and company.lower() in str((r.get("attrs") or {}).get("company", "")).lower():
                sc = min(1.0, sc + 0.15)
            if nid not in cands or cands[nid][0] < sc:
                n = await db.get(NetworkNode, nid)
                cands[nid] = (sc, n)
    if not cands:
        return None, 0.0
    sc, n = max(cands.values(), key=lambda t: t[0])
    return n, sc


def render_summary(stats_: dict[str, Any], recent_: list[dict[str, Any]]) -> str:
    if not stats_.get("nodes"):
        return ""
    lines = [f"Network: {stats_['nodes']} contacts, {stats_['edges']} relations. Kinds: " +
             ", ".join(f"{k} {v}" for k, v in stats_.get("kinds", {}).items())]
    if stats_.get("top_tags"):
        lines.append("Top tags: " + ", ".join(f"{t}({c})" for t, c in stats_["top_tags"]))
    if recent_:
        lines.append("Recent contacts: " + "; ".join(f"{r['name']} ({(r.get('attrs') or {}).get('company', r['kind'])})" for r in recent_[:5]))
    return "\n".join(lines)
