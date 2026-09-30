from __future__ import annotations

from memora.db.session import session_scope
from memora.pipeline.tools.base import SecretaryTool, secretary_tool
from memora.services import profile as PF


@secretary_tool
class ProfileGet(SecretaryTool):
    tool_name = "profile_get"
    tool_description = "Get the owner's structured profile (name, title, company, bio, links, contact, availability window) with per-field visibility."
    schema = {"type": "object", "properties": {}}
    audiences = frozenset({"owner"})

    async def run(self, args):
        # 칸별 범위의 정본은 [내 정보] 하나다. 비서 기본값을 같이 내놓으면 둘이
        # 다를 때 어느 쪽이 사실인지 모델이 고르게 된다 (plan/48 §2).
        return {"data": self.ctx.profile.data or {}, "visibility": self.ctx.profile.visibility or {}}


@secretary_tool
class ProfileUpdate(SecretaryTool):
    tool_name = "profile_update"
    tool_description = "Update fields of the owner's profile (only when the owner asked). Optionally set per-field visibility (public/private)."
    schema = {"type": "object", "properties": {"data": {"type": "object", "description": "subset of profile fields to set"},
                                               "visibility": {"type": "object", "description": "field -> public|private"}}}
    audiences = frozenset({"owner"})
    read_only = False

    async def run(self, args):
        from memora.services.companies import switch as CO

        data = dict(args.get("data") or {})
        async with session_scope() as db:
            # 기업 기능이 꺼져 있으면 소속은 저장되지 않는다 (plan/71) — 저장했다고 말하지 않게 뺀다.
            skipped = [] if await CO.enabled(db) else sorted(k for k in data if k in CO.PROFILE_FIELDS)
            data = {k: v for k, v in data.items() if k not in skipped}
            await PF.update(db, self.ctx.owner_id, data=data, visibility=args.get("visibility"))
            self.ctx.profile = await PF.shown(db, self.ctx.owner_id)
        self.ctx.card("profile_updated", {"fields": sorted(data.keys()), "visibility": args.get("visibility") or {}})
        out = {"updated": True, "fields": sorted(data.keys())}
        if skipped:
            out["not_saved"] = skipped
            out["note"] = "Company fields are not available in this service; they were not saved. Tell the owner plainly."
        return out
