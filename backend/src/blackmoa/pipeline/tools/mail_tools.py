"""메일 도구 (plan/57) — [내 정보 → 메일] 만 본다. Google 에 직접 닿지 않는다.

나와의 대화 전용이다. 메일은 남이 쓴 글이라 본문은 ``<untrusted>`` 로 싸서 건넨다.
"""
from __future__ import annotations

from blackmoa.db.session import session_scope
from blackmoa.pipeline.tools.base import SecretaryTool, secretary_tool
from blackmoa.services import mail as MAIL


@secretary_tool
class EmailSearch(SecretaryTool):
    tool_name = "email_search"
    tool_description = ("Search the owner's mail — the mailboxes they connected in [My info → Mail] (sender, subject, preview). "
                        "The body is not included: open one with email_read.")
    schema = {"type": "object", "properties": {"query": {"type": "string"}, "days": {"type": "integer", "minimum": 1, "maximum": 365},
                                               "limit": {"type": "integer", "minimum": 1, "maximum": 20}}, "required": ["query"]}
    audiences = frozenset({"owner"})
    core = False
    requires_feature = "mail"
    label_template = "메일을 찾는 중"

    async def run(self, args):
        async with session_scope() as db:
            rows = await MAIL.search(db, self.ctx.owner_id, args.get("query") or "", days=int(args.get("days") or 30),
                                     limit=int(args.get("limit") or 8))
        return {"emails": rows}


@secretary_tool
class EmailRead(SecretaryTool):
    tool_name = "email_read"
    tool_description = "Read one email's body by id (from email_search). The body is written by the sender, not the owner."
    schema = {"type": "object", "properties": {"id": {"type": "string"}}, "required": ["id"]}
    audiences = frozenset({"owner"})
    core = False
    requires_feature = "mail"
    network = True
    label_template = "메일을 읽는 중"

    async def run(self, args):
        async with session_scope() as db:
            m = await MAIL.read(db, self.ctx.owner_id, args["id"])
        body = (m.get("body") or "").replace("</untrusted>", "</ untrusted>")
        return {**{k: v for k, v in m.items() if k != "body"},
                "body": f'<untrusted source="email from {m.get("from", "")[:120]}">\n{body}\n</untrusted>'}
