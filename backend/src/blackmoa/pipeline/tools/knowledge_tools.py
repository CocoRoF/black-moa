from __future__ import annotations

import uuid

from sqlalchemy import select

from blackmoa.db.session import session_scope
from blackmoa.models import KnowledgeDocument
from blackmoa.pipeline.tools.base import SecretaryTool, secretary_tool
from blackmoa.services import knowledge as K
from blackmoa.services import outsider as OUT


@secretary_tool
class KnowledgeSearch(SecretaryTool):
    tool_name = "knowledge_search"
    tool_description = "Search the owner's uploaded documents, notes and FAQ (resume, portfolio, company info, policies). Returns matching passages with document titles; cite the title when you use one."
    schema = {"type": "object", "properties": {"query": {"type": "string"}, "k": {"type": "integer", "minimum": 1, "maximum": 8}}, "required": ["query"]}
    outsider = "knowledge_any"
    label_template = "자료를 찾는 중"

    async def run(self, args):
        async with session_scope() as db:
            # 도구로 들어와도 같은 벽을 지난다. 블록만 막고 도구를 열어 두면
            # 비서에게 "찾아보라" 고 시키는 것만으로 벽을 넘을 수 있다.
            hits = await K.search(db, self.ctx.owner_id, args["query"], k=int(args.get("k") or 5),
                                  scope=OUT.disclosure_of(self.ctx).knowledge)
        return {"results": hits}


@secretary_tool
class KnowledgeRead(SecretaryTool):
    tool_name = "knowledge_read"
    tool_description = "Read a section of a knowledge document by id (optionally a page or heading)."
    schema = {"type": "object", "properties": {"document_id": {"type": "string"}, "page": {"type": "integer"}, "heading": {"type": "string"}},
              "required": ["document_id"]}
    outsider = "knowledge_any"

    async def run(self, args):
        async with session_scope() as db:
            return await K.read_document(db, self.ctx.owner_id, uuid.UUID(args["document_id"]),
                                         scope=OUT.disclosure_of(self.ctx).knowledge,
                                         page=args.get("page"), heading=args.get("heading"))


@secretary_tool
class KnowledgeList(SecretaryTool):
    tool_name = "knowledge_list"
    tool_description = "List the owner's knowledge documents (title, kind, status)."
    schema = {"type": "object", "properties": {}}
    audiences = frozenset({"owner"})
    core = False

    async def run(self, args):
        async with session_scope() as db:
            rows = (await db.execute(select(KnowledgeDocument).where(KnowledgeDocument.owner_id == self.ctx.owner_id)
                                     .order_by(KnowledgeDocument.created_at.desc()).limit(100))).scalars().all()
        return {"documents": [{"id": str(d.id), "title": d.title, "kind": d.kind, "status": d.status,
                               "chunks": d.chunk_count} for d in rows]}
