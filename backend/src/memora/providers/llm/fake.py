"""Deterministic fake LLM for tests/dev (MEMORA_FAKE_LLM=1). Streams text; calls a tool when asked."""
from __future__ import annotations

import asyncio
import json
import re
from collections.abc import AsyncIterator
from typing import Any

from geny_executor.llm_client.base import BaseClient, ClientCapabilities
from geny_executor.llm_client.registry import ClientRegistry
from geny_executor.llm_client.types import APIRequest, APIResponse, ContentBlock, TokenUsage

_TOOL_RE = re.compile(r"\[\[tool:([a-z_]+)(?:\s+(\{.*?\}))?\]\]", re.S)


class FakeSecretaryClient(BaseClient):
    provider = "fake"
    capabilities = ClientCapabilities(supports_tools=True, supports_streaming=True, supports_thinking=False, streaming_granularity="token")
    calls = 0
    #: "[[slow]]" 이 든 물음은 천천히 길게 흐른다 — 멈춤·밀려남을 시험하려고. 흘린 조각을 센다(멈춘 뒤에도 흐르는지).
    slow_chunks = 0

    def _last_user_text(self, messages: list[dict[str, Any]]) -> str:
        for m in reversed(messages):
            if m.get("role") == "user":
                c = m.get("content")
                if isinstance(c, str):
                    return c
                if isinstance(c, list):
                    return " ".join(b.get("text", "") for b in c if isinstance(b, dict) and b.get("type") == "text")
        return ""

    def _has_tool_result(self, messages: list[dict[str, Any]]) -> bool:
        last = messages[-1] if messages else {}
        c = last.get("content")
        return isinstance(c, list) and any(isinstance(b, dict) and b.get("type") == "tool_result" for b in c)

    def _plan(self, request: APIRequest) -> tuple[str | None, dict, str]:
        text = self._last_user_text(request.messages)
        tool_names = {t.get("name") for t in (request.tools or [])}
        if self._has_tool_result(request.messages):
            last = request.messages[-1]["content"]
            res = next((b for b in last if isinstance(b, dict) and b.get("type") == "tool_result"), {})
            content = res.get("content")
            if isinstance(content, list):
                content = " ".join(b.get("text", "") for b in content if isinstance(b, dict))
            return None, {}, f"도구 결과를 확인했어요: {str(content)[:200]}"
        m = _TOOL_RE.search(text)
        if m and m.group(1) in tool_names:
            args = json.loads(m.group(2)) if m.group(2) else {}
            return m.group(1), args, ""
        sys_text = request.system if isinstance(request.system, str) else ""
        mode = "visitor" if "VISITOR" in sys_text else "owner"
        reply = f"[{mode}] 네, 말씀하신 내용 잘 들었어요: {text[:80]}"
        if "secret-phone" in sys_text and "전화" in text:
            reply += " 전화번호는 010-9999-8888 입니다."
        return None, {}, reply

    async def _send(self, request: APIRequest, *, purpose: str = "") -> APIResponse:
        FakeSecretaryClient.calls += 1
        tool, args, reply = self._plan(request)
        if tool:
            return APIResponse(content=[ContentBlock(type="tool_use", tool_use_id=f"fake-{self.calls}", tool_name=tool, tool_input=args)],
                               stop_reason="tool_use", usage=TokenUsage(input_tokens=120, output_tokens=20, cost_usd=0.0005), model=request.model)
        return APIResponse(content=[ContentBlock(type="text", text=reply)], stop_reason="end_turn",
                           usage=TokenUsage(input_tokens=200, output_tokens=len(reply) // 2 + 5, cost_usd=0.001), model=request.model)

    async def create_message_stream(self, *, model_config, messages, system="", tools=None, tool_choice=None, purpose="") -> AsyncIterator[dict[str, Any]]:
        request = self._build_request(model_config=model_config, messages=messages, system=system, tools=tools, tool_choice=tool_choice, stream=True)
        FakeSecretaryClient.calls += 1
        tool, args, reply = self._plan(request)
        if tool:
            yield {"type": "tool_use", "id": f"fake-{self.calls}", "name": tool, "input": args}
            yield {"type": "message_complete", "response": APIResponse(
                content=[ContentBlock(type="tool_use", tool_use_id=f"fake-{self.calls}", tool_name=tool, tool_input=args)],
                stop_reason="tool_use", usage=TokenUsage(input_tokens=120, output_tokens=20, cost_usd=0.0005), model=request.model)}
            return
        if "[[slow]]" in self._last_user_text(request.messages):
            for i in range(200):
                FakeSecretaryClient.slow_chunks += 1
                yield {"type": "text_delta", "text": f"{i}, "}
                await asyncio.sleep(0.05)
            reply = "천천히 끝났어요"
        for i in range(0, len(reply), 6):
            yield {"type": "text_delta", "text": reply[i:i + 6]}
            await asyncio.sleep(0)
        yield {"type": "message_complete", "response": APIResponse(content=[ContentBlock(type="text", text=reply)], stop_reason="end_turn",
                                                                    usage=TokenUsage(input_tokens=200, output_tokens=len(reply) // 2 + 5, cost_usd=0.001), model=request.model)}


def register_fake() -> None:
    if "fake" not in ClientRegistry.available():
        ClientRegistry.register("fake", lambda: FakeSecretaryClient)
