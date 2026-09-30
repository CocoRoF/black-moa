"""Build a geny-executor CredentialBundle from admin settings (plan/17). Rebuilt per session build."""
from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

from geny_executor import CredentialBundle, ProviderCredentials
from sqlalchemy.ext.asyncio import AsyncSession

from memora.config import get_settings
from memora.services import settings as S

# Every native Claude Code tool is blocked; host tools arrive only through the MCP bridge (plan/25 D-07).
CLI_NATIVE_TOOLS = ("Bash", "Read", "Write", "Edit", "MultiEdit", "NotebookEdit", "Glob", "Grep", "LS", "WebSearch",
                    "WebFetch", "TodoWrite", "Task", "Agent", "AgentSearch", "Skill", "EnterPlanMode", "ExitPlanMode",
                    "Monitor", "TaskOutput", "TaskStop", "AskUserQuestion", "PushNotification", "ScheduleWakeup",
                    "RemoteTrigger", "CronCreate", "CronDelete", "CronList", "SendMessage", "ListAgents",
                    "NotebookRead", "KillShell", "BashOutput", "SendUserFile", "EnterWorktree", "ExitWorktree")
BRIDGE_SERVER = "memora"


def resolve_claude_binary() -> str:
    """Absolute path to the claude CLI. The executor treats an explicit binary_path literally
    (a bare 'claude' that is not a file → CLI_NOT_FOUND), so resolve through PATH here."""
    import shutil
    b = get_settings().claude_binary or "claude"
    return shutil.which(b) or b


def bridge_script_path() -> str:
    return str(Path(__file__).resolve().parents[1] / "llm" / "cli_bridge.py")


def mcp_bridge_config(session_id: str, token: str) -> dict[str, Any]:
    s = get_settings()
    return {"mcpServers": {BRIDGE_SERVER: {
        "type": "stdio", "command": sys.executable, "args": [bridge_script_path()],
        "env": {"MEMORA_MCP_URL": s.internal_api_url, "MEMORA_MCP_TOKEN": token, "MEMORA_MCP_SESSION_ID": session_id,
                "MEMORA_MCP_TIMEOUT_S": "300"},
    }}}


async def build_bundle(db: AsyncSession, provider: str, *, session_id: str = "", bridge_token: str = "",
                       cwd: str | None = None, max_budget_usd: float | None = None, timeout_s: float = 600.0,
                       lease: Any = None) -> CredentialBundle:
    """``provider`` is the Memora id (claude_code|anthropic|openai|gemini).

    ``lease`` is a ``services.claude_pool.Lease``: when the account pool is serving, the
    CLI is pointed at that account's own HOME/CLAUDE_CONFIG_DIR instead of the single
    shared credential file, and its auth mode wins over the global setting. Without a
    lease the behaviour is exactly what it was before the pool existed.
    """
    by: dict[str, ProviderCredentials] = {}
    anthropic_key = await S.get(db, "providers.anthropic.api_key") or ""
    openai_key = await S.get(db, "providers.openai.api_key") or ""
    google_key = await S.get(db, "providers.google.api_key") or ""
    if anthropic_key:
        by["anthropic"] = ProviderCredentials(api_key=anthropic_key)
    if openai_key:
        by["openai"] = ProviderCredentials(api_key=openai_key)
    if google_key:
        by["google"] = ProviderCredentials(api_key=google_key)
    if provider == "claude_code":
        s = get_settings()
        mode = await S.get(db, "providers.claude_code.auth_mode") or "oauth"
        extras: dict[str, Any] = {
            "workspace_root": cwd or str(s.data_dir / "cli-cwd"),
            "default_permission_mode": "default",
            "disallow_tools": list(CLI_NATIVE_TOOLS),
            "allow_tools": [f"mcp__{BRIDGE_SERVER}"],
            "settings_path": json.dumps({"permissions": {"allow": [f"mcp__{BRIDGE_SERVER}"]}}),
            "extra_args": ["--tools", ""],
            "timeout_s": float(timeout_s),
            "bare_mode": False,
        }
        if session_id and bridge_token:
            extras["mcp_config"] = mcp_bridge_config(session_id, bridge_token)
        if max_budget_usd:
            extras["max_budget_usd"] = float(max_budget_usd)
        env_extras = {"HOME": str(s.claude_home.parent) if s.claude_home.name == ".claude" else str(s.claude_home),
                      "DISABLE_AUTOUPDATER": "1", "CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC": "1"}
        api_key = ""
        # "console" is a login-flow distinction (Anthropic Console vs Claude subscription);
        # both land in the same ~/.claude/.credentials.json, so the runtime path is oauth.
        auth_mode = "oauth"
        if lease is not None:
            mode = lease.auth_mode
            # Both, deliberately: the CLI derives its config dir from HOME unless told
            # otherwise, and a stale HOME is how one account ends up reading another's file.
            env_extras["HOME"] = str(lease.home)
            env_extras["CLAUDE_CONFIG_DIR"] = str(lease.config_dir)
        if mode == "api_key":
            api_key = (lease.api_key if lease is not None else "") or anthropic_key
            auth_mode = "api_key"
            extras["bare_mode"] = True
        elif mode == "setup_token":
            tok = (lease.setup_token if lease is not None else "") or await S.get(db, "providers.claude_code.setup_token") or ""
            env_extras["CLAUDE_CODE_OAUTH_TOKEN"] = tok
            auth_mode = "setup_token"
        extras["env_extras"] = env_extras
        by["claude_code_cli"] = ProviderCredentials(api_key=api_key, binary_path=resolve_claude_binary(), extras=extras, auth_mode=auth_mode)
    if provider not in ("claude_code", "anthropic", "openai", "gemini"):
        # test/dev providers registered at runtime (e.g. MEMORA_FAKE_LLM)
        by[provider] = ProviderCredentials(api_key="test")
    return CredentialBundle(by_provider=by)
