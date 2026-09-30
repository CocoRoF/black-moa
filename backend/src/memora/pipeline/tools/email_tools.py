"""Sending mail on the owner's behalf.

Owner audience only, and off by default. A visitor who could make someone else's
secretary send mail to an address of their choosing would have a spam cannon with a
stranger's name on it.
"""

from __future__ import annotations

from memora.db.session import session_scope
from memora.models import User
from memora.pipeline.tools.base import SecretaryTool, secretary_tool
from memora.services import outbound_mail as OM


@secretary_tool
class EmailSend(SecretaryTool):
    tool_name = "email_send"
    tool_description = (
        "Send an email on the owner's behalf through Memora. The message goes out from Memora's address "
        "carrying the owner's name, and replies go to the owner's own verified address. "
        "Confirm the recipient, the subject and the body with the owner before sending — this leaves the product "
        "and cannot be taken back. Plain text; separate paragraphs with a blank line."
    )
    schema = {
        "type": "object",
        "properties": {
            "to": {"type": "string", "description": "one recipient email address"},
            "subject": {"type": "string"},
            "body": {"type": "string", "description": "the message, in the owner's voice"},
        },
        "required": ["to", "subject", "body"],
    }
    audiences = frozenset({"owner"})
    read_only = False
    network = True
    label_template = "메일을 보내는 중"

    async def run(self, args):
        async with session_scope() as db:
            owner = await db.get(User, self.ctx.owner_id)
            out = await OM.send_as_owner(db, owner=owner, agent_name=self.ctx.agent.name,
                                         agent_id=self.ctx.agent.id, to=args.get("to", ""),
                                         subject=args.get("subject", ""), body=args.get("body", ""))
        self.ctx.card("email_sent", {"to": out["to"], "subject": " ".join((args.get("subject") or "").split())[:120],
                                     "reply_to": out["reply_to"], "remaining_today": out["remaining_today"]})
        return out
