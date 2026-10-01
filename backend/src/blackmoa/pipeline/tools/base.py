"""Tool base + registry + audience-scoped provider (plan/07 §도구 표면)."""
from __future__ import annotations

import json
from typing import Any, ClassVar

from geny_executor.tools.base import Tool, ToolCapabilities, ToolContext, ToolResult

from blackmoa.core.logging import get_logger
from blackmoa.pipeline.context import TurnContext

log = get_logger("blackmoa.tools")
_REGISTRY: dict[str, type[SecretaryTool]] = {}


class SecretaryTool(Tool):
    tool_name: ClassVar[str] = ""
    tool_description: ClassVar[str] = ""
    schema: ClassVar[dict[str, Any]] = {"type": "object", "properties": {}}
    audiences: ClassVar[frozenset[str]] = frozenset({"owner", "visitor"})
    core: ClassVar[bool] = True
    #: 외부인 대화에서 하는 일(plan/57): agents.capabilities 의 키. 나와의 대화에서는 보지 않는다.
    requires_capability: ClassVar[str | None] = None
    #: 외부인 대화에서 무엇을 쓰는 도구인가(plan/57): services/outsider 의 줄 이름.
    #: 그 줄이 꺼져 있으면 외부인 대화에 이 도구가 없다. 나와의 대화에서는 늘 있다.
    outsider: ClassVar[str | None] = None
    requires_feature: ClassVar[str | None] = None       # e.g. "mail"
    relay_only: ClassVar[bool] = False                  # exists only inside a secretary-to-secretary relay (plan/38)
    read_only: ClassVar[bool] = True
    network: ClassVar[bool] = False
    label_template: ClassVar[str] = ""                  # human line for tool.start

    def __init__(self, ctx: TurnContext):
        self.ctx = ctx

    @property
    def name(self) -> str:
        return self.tool_name

    @property
    def description(self) -> str:
        return self.tool_description

    @property
    def input_schema(self) -> dict[str, Any]:
        return self.schema

    def capabilities(self, input: dict[str, Any]) -> ToolCapabilities:
        return ToolCapabilities(read_only=self.read_only, network_egress=self.network, max_result_chars=40_000, timeout_s=60)

    async def run(self, args: dict[str, Any]) -> Any:  # override
        raise NotImplementedError

    async def execute(self, input: dict[str, Any], context: ToolContext) -> ToolResult:
        try:
            out = await self.run(dict(input or {}))
        except PermissionError as e:
            return ToolResult(content={"error": {"code": "forbidden", "message": str(e) or "not allowed"}}, is_error=True)
        except Exception as e:  # noqa: BLE001
            log.warning("tool failed", tool=self.tool_name, err=str(e)[:300])
            msg = getattr(e, "message", None) or str(e) or e.__class__.__name__
            code = getattr(e, "code", "tool_error")
            return ToolResult(content={"error": {"code": code, "message": msg[:500]}}, is_error=True)
        if isinstance(out, ToolResult):
            return out
        if isinstance(out, str):
            return ToolResult(content=out)
        return ToolResult(content=json.dumps(out, ensure_ascii=False, default=str))


def secretary_tool(cls: type[SecretaryTool]) -> type[SecretaryTool]:
    assert cls.tool_name, "tool_name required"
    _REGISTRY[cls.tool_name] = cls
    return cls


def all_tools() -> dict[str, type[SecretaryTool]]:
    return dict(_REGISTRY)


def _allowed(cls: type[SecretaryTool], ctx: TurnContext) -> bool:
    if ctx.audience not in cls.audiences:
        return False
    if cls.relay_only and not getattr(ctx, "relay_id", None):
        return False
    if cls.requires_feature and f"feature:{cls.requires_feature}" not in ctx.features:
        return False
    # 나와의 대화에서는 모든 기능이 켜져 있다 (plan/57). 스위치는 외부인 쪽에만 있다.
    if ctx.audience == "owner":
        return True
    from blackmoa.services import outsider as OUT
    if cls.outsider and not OUT.possible(ctx.agent, cls.outsider):
        return False
    if cls.requires_capability and not (ctx.agent.capabilities or {}).get(cls.requires_capability, True):
        return False
    return True


def tool_names_for(ctx: TurnContext) -> list[str]:
    return sorted(n for n, c in _REGISTRY.items() if _allowed(c, ctx))


def core_overrides_for(ctx: TurnContext) -> dict[str, bool]:
    return {n: c.core for n, c in _REGISTRY.items() if _allowed(c, ctx)}


class ScopedToolProvider:
    """AdhocToolProvider: only tools allowed for this audience/capabilities exist at all."""

    def __init__(self, ctx: TurnContext):
        self.ctx = ctx
        self._names = tool_names_for(ctx)
        self._cache: dict[str, SecretaryTool] = {}

    def list_names(self) -> list[str]:
        return list(self._names)

    def get(self, name: str):
        if name not in self._names:
            return None
        if name not in self._cache:
            self._cache[name] = _REGISTRY[name](self.ctx)
        return self._cache[name]

    def rebind(self, ctx: TurnContext) -> None:
        """Point existing tool instances at a fresh TurnContext (same audience)."""
        self.ctx = ctx
        for t in self._cache.values():
            t.ctx = ctx
