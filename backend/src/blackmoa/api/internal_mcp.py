"""Loopback MCP JSON-RPC endpoint for the Claude Code CLI bridge (plan/07 §claude_code)."""
from __future__ import annotations

import json
import time
from typing import Any

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from geny_executor.tools.base import ToolContext

from blackmoa.core.logging import get_logger
from blackmoa.core.security import constant_eq
from blackmoa.pipeline.events import journals
from blackmoa.pipeline.runner import record_tool_span, tool_label, tool_label_en
from blackmoa.pipeline.runtime import runtimes

router = APIRouter(prefix="/api/internal/mcp", tags=["internal"])
log = get_logger("blackmoa.mcp")
PROTOCOL = "2024-11-05"


def _err(id_, code: int, msg: str) -> dict:
    return {"jsonrpc": "2.0", "id": id_, "error": {"code": code, "message": msg}}


def _describe(name: str, tool: Any) -> dict:
    return {"name": name, "description": (tool.description or "")[:1000], "inputSchema": tool.input_schema or {"type": "object", "properties": {}}}


def _to_mcp_content(content: Any) -> list:
    if isinstance(content, list) and content and all(isinstance(b, dict) and b.get("type") in ("text", "image") for b in content):
        # 도구는 모델 쪽 모양(``source``)으로 그림을 돌려준다. MCP 의 그림은 ``data``·``mimeType``
        # 이다 — 그대로 넘기면 CLI 는 그림을 버린다(file_view, plan/55).
        out = []
        for b in content:
            src = b.get("source") if b.get("type") == "image" else None
            if isinstance(src, dict) and src.get("type") == "base64":
                out.append({"type": "image", "data": src.get("data", ""), "mimeType": src.get("media_type", "image/png")})
            else:
                out.append(b)
        return out
    if isinstance(content, str):
        return [{"type": "text", "text": content}]
    try:
        return [{"type": "text", "text": json.dumps(content, ensure_ascii=False, default=str)}]
    except Exception:
        return [{"type": "text", "text": str(content)}]


@router.post("/{session_id}/rpc")
async def rpc(session_id: str, request: Request):
    auth = request.headers.get("authorization", "")
    token = auth[7:].strip() if auth.lower().startswith("bearer ") else ""
    rt = await runtimes.by_token(session_id, token) if token else None
    if rt is None or not constant_eq(rt.bridge_token, token):
        log.warning("bridge unauthorized", session=session_id, has_token=bool(token))
        return JSONResponse(status_code=401, content=_err(None, -32001, "unauthorized"))
    try:
        env = await request.json()
    except Exception:
        return JSONResponse(status_code=400, content=_err(None, -32700, "parse error"))
    method = env.get("method")
    id_ = env.get("id")
    params = env.get("params") or {}
    log.info("bridge rpc", session=session_id[:8], method=method, tool=(params.get("name") if method == "tools/call" else None))
    if method == "initialize":
        return {"jsonrpc": "2.0", "id": id_, "result": {"protocolVersion": PROTOCOL, "capabilities": {"tools": {"listChanged": True},
                "resources": {"listChanged": False, "subscribe": False}, "prompts": {"listChanged": False}, "logging": {}},
                "serverInfo": {"name": "blackmoa", "version": "1.0"}}}
    if method in ("notifications/initialized", "logging/setLevel", "ping"):
        return {"jsonrpc": "2.0", "id": id_, "result": {}}
    if method == "resources/list":
        return {"jsonrpc": "2.0", "id": id_, "result": {"resources": []}}
    if method == "resources/templates/list":
        return {"jsonrpc": "2.0", "id": id_, "result": {"resourceTemplates": []}}
    if method == "prompts/list":
        return {"jsonrpc": "2.0", "id": id_, "result": {"prompts": []}}
    if method == "completion/complete":
        return {"jsonrpc": "2.0", "id": id_, "result": {"completion": {"values": [], "total": 0, "hasMore": False}}}
    registry = getattr(rt.pipeline, "_tool_registry", None)
    if method == "tools/list":
        tools = []
        if registry is not None:
            for t in registry.list_exposed():
                tools.append(_describe(t.name, t))
        else:
            for name in rt.tool_names:
                t = rt.provider.get(name)
                if t is not None:
                    tools.append(_describe(name, t))
        log.info("bridge tools/list", session=session_id[:8], count=len(tools))
        return {"jsonrpc": "2.0", "id": id_, "result": {"tools": tools}}
    if method == "tools/call":
        name = str(params.get("name") or "")
        args = params.get("arguments") or {}
        if not name:
            return _err(id_, -32602, "missing tool name")
        tool = registry.get(name) if registry is not None else rt.provider.get(name)
        if tool is None:
            return {"jsonrpc": "2.0", "id": id_, "result": {"content": [{"type": "text", "text": f"Tool '{name}' not found"}], "isError": True}}
        j = journals.get(rt.ctx.turn_id) if rt.ctx.turn_id else None
        call_id = str(id_) if id_ is not None else None
        if j is not None:
            j.emit("tool.start", {"call_id": call_id, "name": name, "label": tool_label(name), "label_en": tool_label_en(name), "input_preview": json.dumps(args, ensure_ascii=False)[:200]})
        ver_before = getattr(registry, "version", None)
        t0 = time.monotonic()
        try:
            tctx = ToolContext(session_id=session_id, working_dir=str(rt.pipeline.config.metadata.get("cwd", "")) if hasattr(rt.pipeline, "config") else "",
                               tool_registry=registry, extras={"blackmoa": rt.ctx})
            result = await tool.execute(args if isinstance(args, dict) else {}, tctx)
            content = result.display_text if result.display_text is not None else result.content
            is_error = bool(result.is_error)
        except Exception as e:  # noqa: BLE001
            log.warning("bridge tool failed", tool=name, err=str(e)[:200])
            content, is_error = f"Tool '{name}' failed: {e.__class__.__name__}", True
        dur = int((time.monotonic() - t0) * 1000)
        preview = content if isinstance(content, str) else json.dumps(content, ensure_ascii=False, default=str)
        if j is not None:
            j.emit("tool.end", {"call_id": call_id, "name": name, "is_error": is_error, "duration_ms": dur, "output_preview": preview[:200]})
        if rt.ctx.turn_id:
            try:
                await record_tool_span(rt.ctx.turn_id, rt.ctx.owner_id, name, args if isinstance(args, dict) else {}, preview, is_error, dur)
            except Exception:
                pass
        out: dict[str, Any] = {"content": _to_mcp_content(content), "isError": is_error}
        if registry is not None and getattr(registry, "version", None) != ver_before:
            out["_meta"] = {"blackmoaToolsChanged": True}
        return {"jsonrpc": "2.0", "id": id_, "result": out}
    return _err(id_, -32601, f"method not found: {method}")
