from __future__ import annotations

from memora.pipeline.tools.base import SecretaryTool, secretary_tool


@secretary_tool
class MemorySearch(SecretaryTool):
    tool_name = "memory_search"
    tool_description = "Search the secretary's long-term memory notes (observations, past conversations, decisions, people notes). Use before answering questions about the owner's preferences, history or past agreements."
    schema = {"type": "object", "properties": {"query": {"type": "string", "description": "Natural-language query (Korean or English)"},
                                               "category": {"type": "string", "enum": ["conversations", "observations", "decisions", "people", "inbox", "notes", "summaries"]},
                                               "top_k": {"type": "integer", "minimum": 1, "maximum": 15}},
              "required": ["query"]}
    outsider = "memory_any"
    label_template = "기억을 찾는 중"

    async def run(self, args):
        cats = (args.get("category"),) if args.get("category") else None
        hits = await self.ctx.memory.search(args["query"], top_k=int(args.get("top_k") or 6), categories=cats)
        for h in hits:
            self.ctx.used_memory.append((h["namespace"], h["id"]))
        return {"results": [{"namespace": h["namespace"], "id": h["id"], "title": h["title"], "category": h["category"],
                             "score": round(h["score"], 3), "excerpt": h["body"][:400]} for h in hits]}


@secretary_tool
class MemoryRead(SecretaryTool):
    tool_name = "memory_read"
    tool_description = "Read one memory note in full by namespace and id (from memory_search results)."
    schema = {"type": "object", "properties": {"namespace": {"type": "string"}, "id": {"type": "string"}}, "required": ["namespace", "id"]}
    outsider = "memory_any"

    async def run(self, args):
        n = await self.ctx.memory.read(args["namespace"], args["id"])
        if n is None:
            return {"error": {"code": "not_found", "message": "note not found"}}
        self.ctx.used_memory.append((args["namespace"], args["id"]))
        return {"id": n.id, "title": n.title, "category": n.category, "tags": n.tags, "pinned": n.pinned, "body": n.body}


@secretary_tool
class MemoryRemember(SecretaryTool):
    tool_name = "memory_remember"
    tool_description = "Store something worth remembering about the owner (preference, decision, context, person). Write a short title and a self-contained body. Use category 'people' for notes about a person."
    schema = {"type": "object", "properties": {"title": {"type": "string"}, "body": {"type": "string"},
                                               "category": {"type": "string", "enum": ["observations", "decisions", "people", "notes"]},
                                               "tags": {"type": "array", "items": {"type": "string"}}, "pinned": {"type": "boolean"},
                                               "importance": {"type": "string", "enum": ["critical", "high", "medium", "low"]},
                                               "shared_with_visitors": {"type": "boolean", "description": "true only if the owner explicitly wants visitors to know this"}},
              "required": ["title", "body"]}
    audiences = frozenset({"owner"})
    read_only = False
    label_template = "기억을 저장하는 중"

    async def run(self, args):
        ns = "shared" if args.get("shared_with_visitors") else None
        n = await self.ctx.memory.remember(title=args["title"], body=args["body"], category=args.get("category") or "observations",
                                           tags=args.get("tags") or [], pinned=bool(args.get("pinned")),
                                           importance=args.get("importance") or "medium", source="owner_chat", namespace=ns)
        return {"saved": True, "id": n.id, "namespace": ns or "owner"}


@secretary_tool
class MemoryForget(SecretaryTool):
    tool_name = "memory_forget"
    tool_description = "Delete a memory note. First call with confirm=false to see what would be deleted, then confirm=true."
    schema = {"type": "object", "properties": {"namespace": {"type": "string"}, "id": {"type": "string"}, "confirm": {"type": "boolean"}},
              "required": ["namespace", "id"]}
    audiences = frozenset({"owner"})
    core = False
    read_only = False

    async def run(self, args):
        n = await self.ctx.memory.read(args["namespace"], args["id"])
        if n is None:
            return {"error": {"code": "not_found", "message": "note not found"}}
        if not args.get("confirm"):
            return {"would_delete": {"id": n.id, "title": n.title, "excerpt": n.body[:300]}, "hint": "call again with confirm=true"}
        ok = await self.ctx.memory.forget(args["namespace"], args["id"])
        return {"deleted": ok}
