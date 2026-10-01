"""Live key probes with a verdict cache keyed by (provider, sha1(key)) — ported from Geny credentials.py."""
from __future__ import annotations

import hashlib
import time

import httpx

_cache: dict[tuple[str, str], tuple[float, bool | None, str]] = {}
_TTL = 600.0


async def verify_key(provider: str, key: str, *, force: bool = False) -> tuple[bool | None, str]:
    if not key:
        return False, "missing"
    ck = (provider, hashlib.sha1(key.encode()).hexdigest())
    now = time.monotonic()
    if not force and ck in _cache and _cache[ck][0] > now:
        return _cache[ck][1], _cache[ck][2]
    verdict: bool | None
    detail: str
    try:
        async with httpx.AsyncClient(timeout=8.0) as c:
            if provider == "anthropic":
                r = await c.get("https://api.anthropic.com/v1/models", headers={"x-api-key": key, "anthropic-version": "2023-06-01"})
            elif provider == "openai":
                r = await c.get("https://api.openai.com/v1/models", headers={"Authorization": f"Bearer {key}"})
            elif provider == "google":
                r = await c.get("https://generativelanguage.googleapis.com/v1beta/models", params={"key": key})
            elif provider == "elevenlabs":
                r = await c.get("https://api.elevenlabs.io/v1/user", headers={"xi-api-key": key})
            elif provider == "voyage":
                r = await c.post("https://api.voyageai.com/v1/embeddings", headers={"Authorization": f"Bearer {key}"},
                                 json={"model": "voyage-3", "input": ["ping"]})
            else:
                return None, "unknown provider"
        if r.status_code in (401, 403):
            verdict, detail = False, f"rejected ({r.status_code})"
        elif 200 <= r.status_code < 300:
            verdict, detail = True, "verified"
        else:
            verdict, detail = None, f"inconclusive ({r.status_code})"
    except Exception as e:  # noqa: BLE001
        verdict, detail = None, f"network: {e.__class__.__name__}"
    if verdict is not None:
        _cache[ck] = (now + _TTL, verdict, detail)
    return verdict, detail


# Claude Code takes an alias for "whatever the newest model of that line is" as well as a
# pinned id. The aliases are worth offering: a subscription install usually wants to ride the
# latest model rather than re-adding a catalog row every release.
CLI_ALIASES = ("opus", "sonnet", "haiku", "fable")


def _anthropic_auth(key: str) -> dict[str, str]:
    """OAuth access tokens (`sk-ant-oat…`) authenticate as a bearer; API keys use x-api-key."""
    h = {"anthropic-version": "2023-06-01"}
    if key.startswith("sk-ant-oat"):
        h["Authorization"] = f"Bearer {key}"
    else:
        h["x-api-key"] = key
    return h


async def discover_models(provider: str, key: str) -> list[str]:
    try:
        async with httpx.AsyncClient(timeout=10.0) as c:
            if provider in ("anthropic", "claude_code"):
                r = await c.get("https://api.anthropic.com/v1/models?limit=100", headers=_anthropic_auth(key))
                r.raise_for_status()
                return sorted(m["id"] for m in r.json().get("data", []))
            if provider == "openai":
                r = await c.get("https://api.openai.com/v1/models", headers={"Authorization": f"Bearer {key}"})
                return sorted(m["id"] for m in r.json().get("data", []) if m["id"].startswith(("gpt", "o1", "o3", "o4")))
            if provider == "gemini":
                r = await c.get("https://generativelanguage.googleapis.com/v1beta/models", params={"key": key})
                return sorted(m["name"].split("/")[-1] for m in r.json().get("models", []) if "generateContent" in m.get("supportedGenerationMethods", []))
    except Exception:
        return []
    return []
