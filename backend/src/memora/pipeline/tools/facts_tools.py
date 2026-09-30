from __future__ import annotations

from sqlalchemy import false, or_, select

from memora.core import visibility as VIS
from memora.db.session import session_scope
from memora.models import Fact
from memora.pipeline.tools.base import SecretaryTool, secretary_tool
from memora.services import outsider as OUT


def _vis_filter(ctx):
    """이 대화에서 읽을 수 있는 사실. 외부인 대화면 [지식] 탭의 기억 줄이 가른다 (plan/57):
    공개로 둔 사실은 ``memory``, 이 방문자에 대해 적은 사실은 ``visitors``."""
    if ctx.audience == "owner":
        return Fact.visibility != "visitor_private"
    d = OUT.disclosure_of(ctx)
    visitor_id = ctx.visitor.id if ctx.visitor else None
    conds = []
    if d.memory:
        conds.append(Fact.visibility.in_(VIS.readable_levels(d.viewer)))
    if d.visitors and visitor_id:
        conds.append((Fact.visibility == "visitor_private") & (Fact.visitor_id == visitor_id))
    return or_(*conds) if conds else false()


@secretary_tool
class FactsSearch(SecretaryTool):
    tool_name = "facts_search"
    tool_description = "Search the structured fact ledger (atomic facts: identity, preferences, relationships, commitments). Faster and more precise than memory_search for simple attribute questions."
    schema = {"type": "object", "properties": {"query": {"type": "string"}, "kind": {"type": "string", "enum": ["identity", "preference", "relationship", "commitment", "context", "knowledge"]},
                                               "limit": {"type": "integer", "minimum": 1, "maximum": 30}}, "required": ["query"]}
    outsider = "memory_any"

    async def run(self, args):
        q = f"%{args['query'][:80]}%"
        async with session_scope() as db:
            stmt = select(Fact).where(Fact.owner_id == self.ctx.owner_id, Fact.status == "active",
                                      _vis_filter(self.ctx),
                                      or_(Fact.subject.ilike(q), Fact.predicate.ilike(q), Fact.object.ilike(q)))
            if args.get("kind"):
                stmt = stmt.where(Fact.kind == args["kind"])
            rows = (await db.execute(stmt.order_by(Fact.confidence.desc(), Fact.updated_at.desc()).limit(int(args.get("limit") or 12)))).scalars().all()
            return {"facts": [{"id": str(f.id), "kind": f.kind, "statement": f"{f.subject} {f.predicate} {f.object}",
                               "subject": f.subject, "predicate": f.predicate, "object": f.object,
                               "confidence": f.confidence, "visibility": f.visibility} for f in rows]}


@secretary_tool
class FactsUpsert(SecretaryTool):
    tool_name = "facts_upsert"
    tool_description = ("Record an atomic fact about the owner as subject/predicate/object written as short natural phrases in the conversation's "
                        "language (e.g. subject='오너', predicate='이름', object='테스트'; or subject='owner', predicate='prefers coffee', object='iced americano'). "
                        "An existing fact with the same subject+predicate is superseded. Visibility defaults to private.")
    schema = {"type": "object", "properties": {"subject": {"type": "string"}, "predicate": {"type": "string"}, "object": {"type": "string"},
                                               "kind": {"type": "string", "enum": ["identity", "preference", "relationship", "commitment", "context", "knowledge"]},
                                               "visibility": {"type": "string", "enum": ["public", "private"]},
                                               "confidence": {"type": "number", "minimum": 0, "maximum": 1}},
              "required": ["subject", "predicate", "object"]}
    audiences = frozenset({"owner"})
    read_only = False

    async def run(self, args):
        async with session_scope() as db:
            prev = (await db.execute(select(Fact).where(Fact.owner_id == self.ctx.owner_id, Fact.status == "active",
                                                        Fact.subject.ilike(args["subject"].strip()),
                                                        Fact.predicate.ilike(args["predicate"].strip())))).scalars().all()
            f = Fact(owner_id=self.ctx.owner_id, agent_id=self.ctx.agent.id, subject=args["subject"].strip()[:200],
                     predicate=args["predicate"].strip()[:200], object=str(args["object"]).strip()[:2000],
                     kind=args.get("kind") or "context", confidence=float(args.get("confidence") or 0.9),
                     visibility=args.get("visibility") or "private", source_turn_id=self.ctx.turn_id)
            db.add(f)
            await db.flush()
            for p in prev:
                p.status = "superseded"
                p.superseded_by = f.id
            self.ctx.card("fact_saved", {"statement": f"{f.subject} {f.predicate} {f.object}", "subject": f.subject, "predicate": f.predicate,
                                         "object": f.object, "visibility": f.visibility, "id": str(f.id)})
            return {"saved": True, "id": str(f.id), "superseded": len(prev)}
