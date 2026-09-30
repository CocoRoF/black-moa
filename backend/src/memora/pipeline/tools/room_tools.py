"""사람끼리 방으로 가는 통로 (plan/55 §6-4). 주인과의 대화에만 있다.

비서는 사람끼리 방을 당연히 보지 않는다. 찾을 때는 겉만(상대·시각·개수), 읽을 때는 주인이
그 방을 확인하고 허락한 뒤에만. 판정은 ``room_access.granted`` 한 곳.
"""
from __future__ import annotations

import uuid
from datetime import datetime

from memora.db.session import session_scope
from memora.models import Room, User
from memora.pipeline.tools.base import SecretaryTool, secretary_tool
from memora.services import room_access as RA

_OWNER = frozenset({"owner"})


@secretary_tool
class RoomsFind(SecretaryTool):
    tool_name = "rooms_find"
    tool_description = ("Find the owner's messenger conversations with other people by the person's name or handle. "
                        "Returns only the outside of each room (who, last message time, counts) — never what was said. "
                        "To read one, ask the owner with room_access_request first.")
    schema = {"type": "object", "properties": {"who": {"type": "string", "description": "the other person's name, nickname or @handle"}},
              "required": ["who"]}
    audiences = _OWNER
    label_template = "메신저 대화를 찾는 중"

    async def run(self, args):
        async with session_scope() as db:
            me = await db.get(User, self.ctx.owner_id)
            rows = await RA.find(db, me, str(args.get("who") or ""), agent_id=self.ctx.agent.id,
                                 conversation_id=self.ctx.conversation_id)
        if not rows:
            return {"rooms": [], "note": "No messenger conversation with that person."}
        return {"rooms": rows, "next": "Show the owner which one you mean and ask with room_access_request; "
                                       "if access is already granted you may room_read it."}


@secretary_tool
class RoomAccessRequest(SecretaryTool):
    tool_name = "room_access_request"
    tool_description = ("Ask the owner, with a card in this chat, to confirm which messenger conversation you mean and to "
                        "let you read it. Pass every candidate room when the name matched more than one. Then stop and wait: "
                        "the owner's answer arrives as their next message.")
    schema = {"type": "object", "properties": {
        "room_ids": {"type": "array", "items": {"type": "string"}, "minItems": 1, "maxItems": 5},
        "reason": {"type": "string", "description": "one short sentence: why you want to read it"}},
        "required": ["room_ids", "reason"]}
    audiences = _OWNER
    read_only = False
    label_template = "대화를 읽어도 되는지 묻는 중"

    async def run(self, args):
        cands = []
        async with session_scope() as db:
            me = await db.get(User, self.ctx.owner_id)
            for rid in list(dict.fromkeys(args.get("room_ids") or []))[:5]:
                try:
                    room = await db.get(Room, uuid.UUID(str(rid)))
                except (TypeError, ValueError):
                    continue
                if room is None or room.kind != "dm" or not await RA._is_member(db, room.id, me.id):
                    continue
                cands.append(await RA.summary(db, room, me))
        if not cands:
            return {"error": "none of those are the owner's messenger conversations — use rooms_find"}
        self.ctx.card("room_access", {"agent_id": str(self.ctx.agent.id), "agent_name": self.ctx.agent.name,
                                      "conversation_id": str(self.ctx.conversation_id),
                                      "reason": str(args.get("reason") or "")[:300], "candidates": cands})
        return {"asked": True, "note": "The card is in front of the owner. Say one short line and wait for their answer; "
                                       "do not guess what the conversation says."}


@secretary_tool
class RoomRead(SecretaryTool):
    tool_name = "room_read"
    tool_description = ("Read a messenger conversation the owner has allowed you to read: both sides' messages, oldest first, "
                        "with the files attached (open them with file_read / file_view using the given file_id). "
                        "Fails unless the owner granted access.")
    schema = {"type": "object", "properties": {
        "room_id": {"type": "string"}, "query": {"type": "string", "description": "only messages containing this"},
        "before": {"type": "string", "description": "ISO time, to page back"},
        "limit": {"type": "integer", "minimum": 1, "maximum": 200}}, "required": ["room_id"]}
    audiences = _OWNER
    label_template = "허락받은 대화를 읽는 중"

    async def run(self, args):
        before = None
        if args.get("before"):
            try:
                before = datetime.fromisoformat(str(args["before"]))
            except ValueError:
                before = None
        async with session_scope() as db:
            me = await db.get(User, self.ctx.owner_id)
            out = await RA.read(db, me, agent_id=self.ctx.agent.id, conversation_id=self.ctx.conversation_id,
                                room_id=uuid.UUID(str(args["room_id"])), before=before,
                                limit=int(args.get("limit") or 60), query=str(args.get("query") or ""))
            await db.commit()
        self.ctx.read_rooms = True
        out["note"] = ("This is the owner's private conversation, shown with their permission. Use it to answer; "
                       "do not store what the other person said as memory unless the owner asks you to.")
        return out
