from __future__ import annotations

import uuid

from blackmoa.db.session import session_scope
from blackmoa.pipeline.tools.base import SecretaryTool, secretary_tool
from blackmoa.services import network as N
from blackmoa.services import outsider as OUT


@secretary_tool
class NetworkSearch(SecretaryTool):
    tool_name = "network_search"
    tool_description = ("Search the owner's OWN address book — the people, organizations and projects they recorded — by name, "
                        "alias, company or tag. This is private to them and contains only what they entered. It is NOT how to "
                        "find somebody to ask about a subject: for that use secretary_find with `about`, which searches other "
                        "members of the service.")
    schema = {"type": "object", "properties": {"query": {"type": "string"}, "kind": {"type": "string", "enum": ["person", "organization", "group", "project", "place", "event"]},
                                               "tag": {"type": "string"}, "limit": {"type": "integer", "minimum": 1, "maximum": 20}}, "required": ["query"]}
    outsider = "network"
    label_template = "인맥을 찾는 중"

    async def run(self, args):
        d = OUT.disclosure_of(self.ctx)
        async with session_scope() as db:
            rows = await N.search(db, self.ctx.owner_id, args["query"], viewer=d.viewer, scope=d.network, kind=args.get("kind"),
                                  tag=args.get("tag"), limit=int(args.get("limit") or 8))
        if not self.ctx.is_owner:
            return {"results": rows, "note": "Only the contacts the owner chose to share in conversations like this one are listed."}
        if rows:
            return {"results": rows, "note": ""}
        # The address book is empty for this, and the owner was probably asking who could
        # answer something. Telling the model where to look next did not work: it answered
        # "nobody" instead. So the lookup happens here and the answer comes back with the
        # result (plan/41 §6) — the same trick secretary_ask uses for a name where a link
        # was expected.
        from blackmoa.models import Agent, User
        from blackmoa.services import relay as REL

        async with session_scope() as db:
            owner = await db.get(User, self.ctx.owner_id)
            agent = await db.get(Agent, self.ctx.agent.id)
            people = await REL.find_by_topic(db, owner=owner, agent=agent, query_text=args["query"],
                                             conversation_id=self.ctx.conversation_id, turn_id=self.ctx.turn_id)
        if not people:
            return {"results": [], "note": "Nothing in the owner's own address book, and nobody on the service has "
                                           "published anything about it either. Say so plainly."}
        self.ctx.card("relay_candidates", {"query": str(args["query"])[:80], "items": people})
        return {"results": [], "people_to_ask": people,
                "note": "Nothing in the owner's own address book — but these members wrote about it or say it is their "
                        "work, and their secretaries take inquiries. Show them with the reason each one is here (`why`) "
                        "and ask which to contact. Send only after the owner confirms, in a later turn."}


@secretary_tool
class NetworkPerson(SecretaryTool):
    tool_name = "network_person"
    tool_description = "Get details of one contact: attributes, relations and (owner only) recent interactions."
    schema = {"type": "object", "properties": {"node_id": {"type": "string"}}, "required": ["node_id"]}
    outsider = "network"

    async def run(self, args):
        d = OUT.disclosure_of(self.ctx)
        async with session_scope() as db:
            nid = uuid.UUID(args["node_id"])
            node = await N.get_node(db, self.ctx.owner_id, nid)
            if d.network is None or not d.network.has(node.id):
                return {"error": {"code": "not_found", "message": "contact not found"}}
            nb = await N.neighbors(db, self.ctx.owner_id, nid, depth=1, viewer=d.viewer, scope=d.network, max_nodes=25)
            out = {"node": N.node_dict(node, viewer=d.viewer), "relations": nb["edges"],
                   "neighbors": [n for n in nb["nodes"] if n["id"] != str(nid)]}
            if self.ctx.is_owner:
                from sqlalchemy import select

                from blackmoa.models import NetworkInteraction
                rows = (await db.execute(select(NetworkInteraction).where(NetworkInteraction.node_id == nid)
                                         .order_by(NetworkInteraction.at.desc()).limit(10))).scalars().all()
                out["interactions"] = [{"kind": r.kind, "at": r.at.isoformat(), "summary": r.summary} for r in rows]
            return out


@secretary_tool
class NetworkNeighbors(SecretaryTool):
    tool_name = "network_neighbors"
    tool_description = "Who is connected to a contact (up to 2 hops)."
    schema = {"type": "object", "properties": {"node_id": {"type": "string"}, "depth": {"type": "integer", "minimum": 1, "maximum": 2}}, "required": ["node_id"]}
    audiences = frozenset({"owner"})
    core = False

    async def run(self, args):
        async with session_scope() as db:
            return await N.neighbors(db, self.ctx.owner_id, uuid.UUID(args["node_id"]), depth=int(args.get("depth") or 1))


@secretary_tool
class NetworkPath(SecretaryTool):
    tool_name = "network_path"
    tool_description = "How two contacts are connected (shortest path, up to 4 hops)."
    schema = {"type": "object", "properties": {"from_id": {"type": "string"}, "to_id": {"type": "string"}}, "required": ["from_id", "to_id"]}
    audiences = frozenset({"owner"})
    core = False

    async def run(self, args):
        async with session_scope() as db:
            return await N.shortest_path(db, self.ctx.owner_id, uuid.UUID(args["from_id"]), uuid.UUID(args["to_id"]))


@secretary_tool
class NetworkRecent(SecretaryTool):
    tool_name = "network_recent"
    tool_description = "Contacts the owner interacted with most recently."
    schema = {"type": "object", "properties": {"n": {"type": "integer", "minimum": 1, "maximum": 30}}}
    audiences = frozenset({"owner"})
    core = False

    async def run(self, args):
        async with session_scope() as db:
            return {"recent": await N.recent(db, self.ctx.owner_id, int(args.get("n") or 10))}


@secretary_tool
class NetworkPropose(SecretaryTool):
    tool_name = "network_propose"
    tool_description = ("Propose a change to the owner's network graph. A person can only be proposed when the system can act on them: "
                        "they have a black-moa account (the owner is offered a connection request) or they have talked to this owner's "
                        "secretary (the owner is offered to add that guest). Somebody merely mentioned in passing cannot be added — "
                        "remember that with the memory tools instead. Proposals wait for the owner's approval; never claim the contact was added.")
    schema = {"type": "object", "properties": {
        "kind": {"type": "string", "enum": ["add_node", "add_edge", "update_attr"]},
        "payload": {"type": "object", "description": "add_node: {kind,name,aliases?,attrs?{company,title,emails,phones},tags?,relation_to_owner?}; add_edge: {src_id,dst_id,rel,strength?}; update_attr: {node_id,attrs}"},
        "confidence": {"type": "number", "minimum": 0, "maximum": 1}, "reason": {"type": "string"}}, "required": ["kind", "payload"]}
    # 제안은 주인에게 올리는 것이지 밖으로 내보내는 것이 아니다 — 외부인 대화에서도 늘 있다.
    read_only = False

    async def run(self, args):
        from blackmoa.models import User
        from blackmoa.services import people as P

        async with session_scope() as db:
            payload = dict(args["payload"] or {})
            if args.get("reason"):
                payload["reason"] = args["reason"][:500]
            if self.ctx.visitor is not None:
                payload["from_visitor_id"] = str(self.ctx.visitor.id)
            # Refuse at the source. A proposal that resolves to nobody produces a card the
            # owner cannot act on and a name in the graph that was never anybody — which is
            # how the queue filled up with rows people learned to ignore (plan/31).
            owner = await db.get(User, self.ctx.owner_id)
            resolved = await P.resolve_proposal(db, owner, args["kind"], payload) if owner else {"action": "none"}
            if args["kind"] == "add_node" and resolved["action"] == "none":
                return {"proposed": False, "reason": resolved.get("why") or "not_reachable",
                        "message": ("This person has no black-moa account and has not talked to the owner's secretary, "
                                    "so there is nothing to add to the network. Record it as a memory instead.")}
            p = await N.propose(db, self.ctx.owner_id, agent_id=self.ctx.agent.id, kind=args["kind"], payload=payload,
                                confidence=float(args.get("confidence") or 0.6), source_turn_id=self.ctx.turn_id)
        if self.ctx.is_owner:
            self.ctx.card("network_proposal", {"proposal_id": str(p.id), "kind": p.kind, "payload": payload})
        return {"proposed": True, "proposal_id": str(p.id), "status": "pending_owner_approval"}


@secretary_tool
class ContactsLookup(SecretaryTool):
    tool_name = "contacts_lookup"
    tool_description = "Look up a contact's email/phone from the owner's network (Google contacts are imported into the network)."
    schema = {"type": "object", "properties": {"query": {"type": "string"}}, "required": ["query"]}
    audiences = frozenset({"owner"})
    core = False

    async def run(self, args):
        async with session_scope() as db:
            rows = await N.search(db, self.ctx.owner_id, args["query"], limit=5)
        return {"contacts": [{"id": r["id"], "name": r["name"], "emails": (r.get("attrs") or {}).get("emails", []),
                              "phones": (r.get("attrs") or {}).get("phones", []), "company": (r.get("attrs") or {}).get("company")} for r in rows]}
