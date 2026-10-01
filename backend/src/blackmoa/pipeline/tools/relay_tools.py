"""Secretary-to-secretary conversations (plan/38): open one, close one."""
from __future__ import annotations

from blackmoa.db.session import session_scope
from blackmoa.pipeline.tools.base import SecretaryTool, secretary_tool
from blackmoa.services import relay as REL


@secretary_tool
class SecretaryFind(SecretaryTool):
    tool_name = "secretary_find"
    tool_description = ("Find somebody to contact, among the members of this service. Use it — not network_search, which is only "
                        "the owner's own address book — whenever the owner asks who could answer something, or who to ask about a "
                        "subject. Two ways: `name`, when the owner names a person or a secretary and gives no link "
                        "(their network, friends, members who visited, the directory, the secretary's own name); or `about`, when "
                        "the owner has a question and does not know who to ask — that one searches what members published on their "
                        "own pages and what they say they do, and returns only people whose secretary takes inquiries. Either way: "
                        "show the candidates and ask which one, then send in a LATER turn with the candidate_id. Do not search "
                        "again after they confirm.")
    schema = {"type": "object", "properties": {
        "name": {"type": "string", "description": "the person's name as the owner said it"},
        "about": {"type": "string", "description": "the owner's question or topic, when they do not know who to ask"}}}
    audiences = frozenset({"owner"})
    label_template = "상대 비서를 찾는 중"

    async def run(self, args):
        name = str(args.get("name") or "").strip()
        about = str(args.get("about") or "").strip()
        if not name and not about:
            raise ValueError("give a name or an about")
        async with session_scope() as db:
            from blackmoa.models import Agent, User
            owner = await db.get(User, self.ctx.owner_id)
            agent = await db.get(Agent, self.ctx.agent.id)
            if name:
                items = await REL.find_candidates(db, owner=owner, agent=agent, query=name,
                                                  conversation_id=self.ctx.conversation_id, turn_id=self.ctx.turn_id)
            else:
                items = await REL.find_by_topic(db, owner=owner, agent=agent, question=about,
                                                conversation_id=self.ctx.conversation_id, turn_id=self.ctx.turn_id)
        if items:
            self.ctx.card("relay_candidates", {"query": (name or about)[:80], "items": items})
        if about and not name:
            return {"candidates": items,
                    "note": ("Nobody has published anything about that, so there is no one to ask yet. Tell the owner plainly."
                             if not items else
                             "These people wrote about it or say it is their work. Show them with the reason each one is here "
                             "(the `why` field) and ask the owner which to ask. Send only after they confirm, in your next turn.")}
        known = [i for i in items if i["source"] != "directory"]
        note = ("No one by that name among people the owner knows or in the directory. Ask the owner for the person's public link."
                if not items else
                "Show these to the owner and ask which one (name, role, how you know them). Send only after they confirm, in your next turn."
                if known else
                "Nobody the owner knows matches; these are directory matches only — say so, and ask the owner whether it is one of them.")
        return {"candidates": items, "note": note}


@secretary_tool
class SecretaryAsk(SecretaryTool):
    tool_name = "secretary_ask"
    tool_description = ("Send an opening message to another member's secretary on the owner's behalf: by its public link "
                        "(URL or code), or by a candidate_id from secretary_find that the owner has confirmed. The exchange then "
                        "runs on its own; the result arrives here as a card. Polite, specific, nothing private about the owner. "
                        "If the result says sent:false, tell the owner it was NOT sent and why — never say it went out.")
    schema = {"type": "object", "properties": {
        "link": {"type": "string", "description": "public link URL or code (when the owner gave one)"},
        "candidate_id": {"type": "string", "description": "a candidate from secretary_find, after the owner confirmed it"},
        "message": {"type": "string", "description": "the opening message, in the other side's language"},
        "purpose": {"type": "string", "description": "one line: what the owner wants out of this"},
        "max_messages": {"type": "integer", "minimum": 2, "maximum": 20, "description": "cap on messages for both sides together (default 8)"},
    }, "required": ["message"]}
    audiences = frozenset({"owner"})
    read_only = False
    label_template = "다른 비서에게 문의를 보내는 중"

    async def run(self, args):
        import uuid as _uuid
        cid = None
        if args.get("candidate_id"):
            try:
                cid = _uuid.UUID(str(args["candidate_id"]))
            except ValueError as e:
                raise ValueError("candidate_id is not valid") from e
        if not cid and not (args.get("link") or "").strip():
            raise ValueError("give a link or a candidate_id")
        from blackmoa.core.errors import BlackMoaError
        # A name where a link was expected: do the lookup the model skipped, and hand back
        # candidates to confirm instead of an error to explain.
        raw = str(args.get("link") or "").strip()
        if not cid and raw:
            try:
                REL.parse_target(raw)
            except BlackMoaError:
                async with session_scope() as db:
                    from blackmoa.models import Agent, User
                    owner = await db.get(User, self.ctx.owner_id)
                    agent = await db.get(Agent, self.ctx.agent.id)
                    items = await REL.find_candidates(db, owner=owner, agent=agent, query=raw, conversation_id=self.ctx.conversation_id, turn_id=self.ctx.turn_id)
                if items:
                    self.ctx.card("relay_candidates", {"query": raw[:80], "items": items})
                    return {"sent": False, "error": "confirm_first", "candidates": items,
                            "note": "NOT sent. That was a name, not a link. Show these candidates and ask the owner which one; send in your next turn with the candidate_id."}
                return {"sent": False, "error": "not_found", "note": "NOT sent. Nobody by that name can be reached; ask the owner for the person's public link."}
        try:
            async with session_scope() as db:
                from blackmoa.models import Agent, User
                owner = await db.get(User, self.ctx.owner_id)
                agent = await db.get(Agent, self.ctx.agent.id)
                relay = await REL.start(db, owner=owner, agent=agent, target=str(args.get("link") or ""), message=str(args.get("message") or ""),
                                        purpose=str(args.get("purpose") or "")[:600], origin_conversation_id=self.ctx.conversation_id,
                                        origin_turn_id=self.ctx.turn_id, max_messages=args.get("max_messages"), candidate_id=cid)
                out = await REL.relay_out(db, relay, owner.id)
        except BlackMoaError as e:
            # The card tells the owner the truth whatever the model says next.
            self.ctx.card("relay_started", {"status": "failed", "close_reason": e.code, "target_agent_name": "", "target_owner_name": ""})
            hint = {"confirm_first": "Ask the owner to confirm the person first; send in your next turn with the candidate_id.",
                    "relay_target_cap": "The owner already reached this secretary twice today.",
                    "candidate_unreachable": "That member's secretary does not take inquiries.",
                    "link_not_found": "No such public link.", "relay_self": "That is the owner's own secretary."}.get(e.code, e.message)
            return {"sent": False, "error": e.code, "note": f"NOT sent — {hint} Tell the owner plainly."}
        self.ctx.card("relay_started", {"relay_id": out["id"], "target_agent_name": out["peer_agent_name"], "target_owner_name": out["peer_owner_name"],
                                        "purpose": out["purpose"], "status": out["status"], "close_reason": out["close_reason"]})
        if out["status"] == "closed":
            return {"sent": False, "relay_id": out["id"], "reason": out["close_reason"],
                    "note": "The other secretary could not be reached (see reason). Tell the owner plainly; do not retry by yourself."}
        return {"sent": True, "relay_id": out["id"], "target_agent": out["peer_agent_name"], "target_owner": out["peer_owner_name"],
                "note": "Sent. The exchange continues by itself and the result arrives here as a card; the owner need not wait."}


@secretary_tool
class RelayClose(SecretaryTool):
    tool_name = "relay_close"
    tool_description = ("End this exchange with the other secretary after your current message: the purpose is served, they have what "
                        "they asked for, or they signed off. Give a one-line summary for your owner.")
    schema = {"type": "object", "properties": {"summary": {"type": "string", "description": "one line for your owner: what was asked and what came of it"}},
              "required": ["summary"]}
    audiences = frozenset({"owner", "visitor"})
    relay_only = True
    read_only = False
    label_template = "대화를 마무리하는 중"

    async def run(self, args):
        async with session_scope() as db:
            return await REL.request_close(db, self.ctx.relay_id, self.ctx.conversation_id, str(args.get("summary") or ""))
