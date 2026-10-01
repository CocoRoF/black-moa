"""Locks the Claude Code argv contract (plan/07 §claude_code, plan/25 D-07/D-28)."""
from __future__ import annotations

import json

import pytest
from geny_executor.core.pipeline import _creds_to_client_kwargs
from geny_executor.llm_client.translators._cli import claude_code_argv
from geny_executor.llm_client.types import APIRequest

from blackmoa.db.session import session_scope
from blackmoa.providers.llm.credentials import CLI_NATIVE_TOOLS, build_bundle
from blackmoa.providers.llm.simple import extract_json
from blackmoa.services import settings as S

pytestmark = pytest.mark.asyncio


async def _argv(mode: str) -> tuple[list[str], dict]:
    async with session_scope() as db:
        await S.put(db, "providers.claude_code.auth_mode", mode)
        if mode == "api_key":
            await S.put(db, "providers.anthropic.api_key", "sk-ant-test")
        if mode == "setup_token":
            await S.put(db, "providers.claude_code.setup_token", "sk-ant-oat01-test")
        b = await build_bundle(db, "claude_code", session_id="s1", bridge_token="t1", cwd="/tmp", max_budget_usd=0.05)
    kw = _creds_to_client_kwargs("claude_code_cli", b.by_provider["claude_code_cli"])
    req = APIRequest(model="haiku", messages=[{"role": "user", "content": "hi"}], system="sys", stream=True, mcp_config=kw.get("mcp_config"))
    argv = claude_code_argv(req, bare_mode=kw["bare_mode"], auth_mode=kw.get("auth_mode", "oauth"), has_api_key=bool(kw.get("api_key")),
                            permission_mode=kw["default_permission_mode"], max_budget_usd=kw.get("max_budget_usd"), settings_path=kw.get("settings_path"),
                            mcp_config=kw.get("mcp_config"), allow_tools=kw["allow_tools"], disallow_tools=kw["disallow_tools"], extra_args=kw["extra_args"])
    return argv, kw


async def test_oauth_mode_blocks_natives_and_wires_bridge(app):
    argv, kw = await _argv("oauth")
    joined = " ".join(argv)
    assert "--bare" not in argv, "bare mode must never be used with subscription auth"
    assert kw.get("api_key") == "" and "ANTHROPIC_API_KEY" not in (kw.get("env_extras") or {})
    assert "--tools" in argv and argv[argv.index("--tools") + 1] == ""
    dis = argv[argv.index("--disallowedTools") + 1].split()
    assert set(CLI_NATIVE_TOOLS) <= set(dis) and "Bash" in dis and "WebFetch" in dis
    assert argv[argv.index("--allowedTools") + 1] == "mcp__blackmoa"
    assert "--strict-mcp-config" in argv and "--mcp-config" in argv
    mcp = json.loads(argv[argv.index("--mcp-config") + 1])
    srv = mcp["mcpServers"]["blackmoa"]
    assert srv["type"] == "stdio" and srv["env"]["BLACKMOA_MCP_SESSION_ID"] == "s1" and srv["env"]["BLACKMOA_MCP_TOKEN"] == "t1"
    assert srv["args"][0].endswith("cli_bridge.py")
    settings = json.loads(argv[argv.index("--settings") + 1])
    assert settings["permissions"]["allow"] == ["mcp__blackmoa"]
    assert "--max-budget-usd" in argv and "--system-prompt" in joined
    assert argv[-2:] == ["--", "hi"] or "--input-format" in argv  # streaming: prompt via stdin


async def test_api_key_mode_uses_bare_and_key(app):
    argv, kw = await _argv("api_key")
    assert "--bare" in argv and kw.get("api_key") == "sk-ant-test"


async def test_setup_token_mode_passes_env_only(app):
    argv, kw = await _argv("setup_token")
    assert "--bare" not in argv
    assert kw["env_extras"]["CLAUDE_CODE_OAUTH_TOKEN"] == "sk-ant-oat01-test" and kw.get("api_key") == ""
    async with session_scope() as db:
        await S.put(db, "providers.claude_code.auth_mode", "oauth")


async def test_extract_json_tolerates_fences_and_prose():
    assert extract_json('```json\n{"a": 1}\n```') == {"a": 1}
    assert extract_json('Sure! Here it is: {"facts": [], "note": null, "people": []} hope it helps') == {"facts": [], "note": None, "people": []}
    assert extract_json("no json here") is None
