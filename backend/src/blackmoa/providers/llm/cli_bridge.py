#!/usr/bin/env python3
"""Stdio MCP server that bridges to black-moa's HTTP tool endpoint.

Phase I of docs/llm-backend-upgrade-plan/12_phase_i_claude_code_mcp_wrap.md.
Spawned as a subprocess by ``claude --mcp-config <json>`` with env vars
identifying the session + bearer token. The Claude Code CLI speaks MCP
JSON-RPC over our stdin/stdout; we forward each call to black-moa's
``/api/internal/mcp/{session_id}/rpc`` endpoint and proxy the response
back unchanged.

Design choices:

  - Keep this script **standalone and dependency-free**: only Python
    stdlib (``urllib``) so it works in any container where ``python3``
    is on PATH, no ``pip install`` required at bridge launch time.
  - **Synchronous, line-by-line** stdio reader. Claude Code sends one
    JSON-RPC envelope per line; we never need pipelining.
  - **HTTP errors get translated to MCP errors** so the CLI sees a
    coherent protocol response instead of a bridge crash.

Env vars (set by black-moa's MCP config when spawning claude):
  BLACKMOA_MCP_URL        — base URL (default http://127.0.0.1:8000)
  BLACKMOA_MCP_TOKEN      — bearer token (REQUIRED)
  BLACKMOA_MCP_SESSION_ID — session UUID (REQUIRED)
"""

from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.request

_DEFAULT_URL = os.environ.get("BLACKMOA_MCP_URL", "http://127.0.0.1:8000").rstrip("/")
_TOKEN = os.environ.get("BLACKMOA_MCP_TOKEN", "")
_SESSION_ID = os.environ.get("BLACKMOA_MCP_SESSION_ID", "")
_TIMEOUT = float(os.environ.get("BLACKMOA_MCP_TIMEOUT_S", "300"))


def _arm_parent_death_signal() -> None:
    """Best-effort: tell the kernel to send us SIGTERM if our parent dies.

    The spawning process is ``claude`` (Claude Code CLI). If it crashes
    or is killed while we're mid-RPC, the parent FD closes but Python's
    line-buffered ``for raw in sys.stdin`` loop sometimes wedges on
    epoll instead of cleanly observing EOF — leaving an orphaned bridge
    holding a port-3xxxx HTTP connection open until the kernel reaper
    notices. ``PR_SET_PDEATHSIG`` makes the kernel send SIGTERM to us
    the instant the parent exits, regardless of stdin state.

    Linux-only; on macOS / Windows this is a no-op and the existing
    EOF-driven cleanup remains the only path.
    """
    try:
        import ctypes
        import signal

        # Linux PR_SET_PDEATHSIG = 1
        libc = ctypes.CDLL("libc.so.6", use_errno=True)
        if libc.prctl(1, signal.SIGTERM, 0, 0, 0) != 0:
            err = ctypes.get_errno()
            sys.stderr.write(
                f"blackmoa_cli_bridge: prctl(PR_SET_PDEATHSIG) failed errno={err}\n"
            )
    except Exception:
        # Not Linux (or libc.so.6 missing) — fall back to EOF detection.
        pass


_arm_parent_death_signal()


def _write_response(response: dict) -> None:
    """Emit one MCP response line on stdout. Flush so the CLI sees
    it without buffering delay."""
    sys.stdout.write(json.dumps(response, ensure_ascii=False) + "\n")
    sys.stdout.flush()


def _err(req_id, code: int, message: str) -> dict:
    return {
        "jsonrpc": "2.0",
        "id": req_id,
        "error": {"code": code, "message": message},
    }


def _forward(envelope: dict) -> dict:
    """POST one JSON-RPC envelope to black-moa and return the response.

    Translates transport errors (HTTP 4xx/5xx, connection refused,
    timeout) into MCP-shaped JSON-RPC errors so the CLI never sees a
    bridge crash."""
    req_id = envelope.get("id")

    if not _TOKEN or not _SESSION_ID:
        return _err(
            req_id,
            -32603,
            "bridge misconfigured: missing BLACKMOA_MCP_TOKEN or BLACKMOA_MCP_SESSION_ID",
        )

    url = f"{_DEFAULT_URL}/api/internal/mcp/{_SESSION_ID}/rpc"
    payload = json.dumps(envelope, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=payload,
        method="POST",
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {_TOKEN}",
        },
    )

    try:
        with urllib.request.urlopen(req, timeout=_TIMEOUT) as resp:
            body = resp.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", errors="replace") if e.fp else ""
        # The black-moa endpoint returns its own JSON-RPC error envelope
        # on protocol failures (404 / 401 / 500). Try to surface it;
        # otherwise synthesize one.
        try:
            return json.loads(body)
        except json.JSONDecodeError:
            return _err(req_id, -32603, f"HTTP {e.code}: {body[:200]}")
    except urllib.error.URLError as e:
        return _err(req_id, -32603, f"transport error: {e.reason}")
    except Exception as e:  # noqa: BLE001
        return _err(req_id, -32603, f"bridge error: {e}")

    try:
        return json.loads(body)
    except json.JSONDecodeError:
        return _err(req_id, -32603, f"invalid JSON response: {body[:200]}")


def main() -> int:
    # Read line-delimited JSON-RPC from stdin until EOF.
    for raw in sys.stdin:
        line = raw.strip()
        if not line:
            continue
        try:
            envelope = json.loads(line)
        except json.JSONDecodeError:
            # Spec: server SHOULD NOT respond to malformed input;
            # log to stderr (CLI surfaces it under --debug=mcp).
            sys.stderr.write(f"blackmoa_cli_bridge: malformed JSON: {line[:120]}\n")
            sys.stderr.flush()
            continue

        # Notifications (no ``id``) per JSON-RPC spec don't expect a
        # response — but the CLI's MCP client awaits one for
        # ``notifications/initialized`` in practice. Forward
        # everything and let black-moa decide whether to respond.
        response = _forward(envelope)
        # Same-turn tool activation: when a tools/call changed the exposed tool set the
        # server stamps result._meta.blackmoaToolsChanged. Emit list_changed BEFORE the
        # response (XGEN lesson: after the response the CLI has already begun
        # assembling its next request and the new schema arrives one turn late).
        try:
            if (
                envelope.get("method") == "tools/call"
                and isinstance(response.get("result"), dict)
                and (response["result"].get("_meta") or {}).get("blackmoaToolsChanged")
            ):
                _write_response({"jsonrpc": "2.0", "method": "notifications/tools/list_changed"})
        except Exception:  # noqa: BLE001
            pass
        _write_response(response)
    return 0


if __name__ == "__main__":
    sys.exit(main())
