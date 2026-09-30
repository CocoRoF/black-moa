"""One-shot completion helper for background jobs (distillation, summaries) — no tools, no pipeline."""
from __future__ import annotations

import asyncio
import contextlib
import json
import re
from typing import Any

from geny_executor.llm_client.registry import ClientRegistry
from sqlalchemy.ext.asyncio import AsyncSession

from memora.core import llm_manager as LLM
from memora.core.logging import get_logger
from memora.core.pools import run_blocking
from memora.providers.llm.credentials import build_bundle
from memora.services.catalog import PROVIDER_TO_EXECUTOR

log = get_logger("memora.llm.simple")
_JSON_RE = re.compile(r"\{.*\}", re.S)

# One background completion at a time, per process.
#
# The worker runs four jobs at once. Background LLM calls go through an external CLI that
# can stop answering, and a call that never returns holds its slot: four of them and the
# queue stops — no indexing, no notifications, no credit sweeps, nothing. Serialised, a
# wedged call costs one slot and everything else keeps moving. Background work is not
# latency-sensitive; the queue is.
_ONE_AT_A_TIME = asyncio.Semaphore(1)
# A second lane for calls a person is waiting on right now (a message the owner asked the
# secretary to send, a studio preview), so they never queue behind a distillation. Still one
# at a time within the lane: the wedge argument above holds for it too.
_INTERACTIVE = asyncio.Semaphore(1)


async def complete(db: AsyncSession, *, provider: str, model: str, system: str, user_text: str, max_tokens: int = 2048,
                   timeout_s: float = 180.0, lane: str = "batch",
                   images: list[tuple[str, str]] | None = None) -> tuple[str, dict[str, Any]]:
    """Returns (text, usage_dict). ``lane="interactive"`` is for calls someone is waiting on.

    ``images`` is ``[(mime, base64), …]`` — sent ahead of the text as canonical image blocks,
    which every client translates (the CLI ingests them over stream-json)."""

    exec_provider = PROVIDER_TO_EXECUTOR.get(provider, provider)
    async with (_INTERACTIVE if lane == "interactive" else _ONE_AT_A_TIME):
        return await _complete_one(db, provider=provider, exec_provider=exec_provider, model=model, system=system,
                                   user_text=user_text, max_tokens=max_tokens, timeout_s=timeout_s, images=images)


async def _complete_one(db: AsyncSession, *, provider: str, exec_provider: str, model: str, system: str, user_text: str,
                        max_tokens: int, timeout_s: float,
                        images: list[tuple[str, str]] | None = None) -> tuple[str, dict[str, Any]]:
    from memora.services import claude_pool as CP

    # Background work (distillation, summaries) is short and frequent, so it takes a lease
    # for the length of one call rather than pinning an account the way a session does.
    lease = await CP.acquire(db, purpose="background") if provider == "claude_code" else None
    failure: str | None = None
    try:
        bundle = await build_bundle(db, provider, timeout_s=timeout_s, lease=lease)
        creds = bundle.by_provider.get(exec_provider)
        if creds is None:
            raise RuntimeError(f"provider {provider} not configured")
        from geny_executor.core.pipeline import _creds_to_client_kwargs
        kwargs = _creds_to_client_kwargs(exec_provider, creds)
        kwargs.pop("mcp_config", None)
        if exec_provider == "claude_code_cli":
            kwargs["prewarm_spawn"] = False
            # Background completions never need extended thinking, and ``--effort low`` alone
            # does not switch it off: measured on the proactive-message prompt, haiku spent
            # 3–7k thinking tokens (30–70 s) on a two-sentence answer; with thinking off the
            # same call is ~2 s and ~70 output tokens. Both switches, since either may be the
            # one this CLI version honours.
            kwargs["extra_args"] = list(kwargs.get("extra_args") or []) + ["--effort", "low", "--settings", '{"alwaysThinkingEnabled": false}']
            kwargs["env_extras"] = {**(kwargs.get("env_extras") or {}), "MAX_THINKING_TOKENS": "0"}
        # The whole exchange runs in a worker thread with its own event loop.
        #
        # Not caution: the CLI client blocks. Building it runs a version handshake against
        # the binary, and the call itself spawns and talks to a process — synchronously, in
        # places, inside async methods. On this loop a slow one froze the worker whole: no
        # other job ran, and no timeout fired either, because a blocked loop cannot time
        # anything out. Thirty jobs sat queued behind one distillation for twelve minutes.
        # Isolated in a thread, a block costs one job and every timeout works again.
        make = ClientRegistry.get(exec_provider)
        log.info("background completion starting", provider=exec_provider, model=model, timeout_s=timeout_s)

        content: Any = user_text
        if images:
            content = [*({"type": "image", "source": {"type": "base64", "media_type": m, "data": d}} for m, d in images),
                       {"type": "text", "text": user_text}]

        def _exchange() -> tuple[str, dict[str, Any]]:
            async def go() -> tuple[str, dict[str, Any]]:
                from geny_executor import ModelConfig
                client_local = make(**kwargs)
                try:
                    # No sampling parameters: anthropic SDK 1.4 removed ``temperature`` from
                    # messages.create, so a value here made every API-provider call fail
                    # before it left the process (and fall back to the slow CLI path).
                    cfg = ModelConfig(model=model, max_tokens=max_tokens)
                    cfg.temperature = None  # type: ignore[assignment]
                    resp = await asyncio.wait_for(
                        client_local.create_message(model_config=cfg,
                                                    messages=[{"role": "user", "content": content}], system=system),
                        timeout=timeout_s)
                    out = ""
                    for b in resp.content or []:
                        if isinstance(b, dict):
                            if b.get("type") == "text":
                                out += b.get("text", "")
                        else:
                            out += getattr(b, "text", "") or ""
                    u = getattr(resp, "usage", None)
                    return out, ({"input_tokens": int(getattr(u, "input_tokens", 0) or 0),
                                  "output_tokens": int(getattr(u, "output_tokens", 0) or 0)} if u else {})
                finally:
                    with contextlib.suppress(Exception):
                        aclose = getattr(client_local, "aclose", None)
                        if aclose:
                            await aclose()

            return asyncio.run(go())

        cid = LLM.manager.begin(provider=provider, model=model, kind="background",
                                account=getattr(lease, "label", "") if lease else "")
        try:
            # The thread cannot be cancelled, so the deadline is the client's own plus a
            # margin: whatever happens, this returns and the slot is given back.
            out = await run_blocking("llm", _exchange, label=f"complete:{model}", timeout_s=timeout_s + 30)
            log.info("background completion done", provider=exec_provider, chars=len(out[0]))
            LLM.manager.end(cid, ok=True, input_tokens=int((out[1] or {}).get("input_tokens", 0)),
                            output_tokens=int((out[1] or {}).get("output_tokens", 0)))
            return out
        except Exception as e:
            failure = f"{e.__class__.__name__}: {e}"
            log.warning("background completion failed", provider=exec_provider, model=model, err=failure[:200])
            from memora.providers.errors import classify as _classify
            LLM.manager.end(cid, ok=False, code=_classify(failure), error=failure)
            raise
    except Exception as e:
        # Anything that goes wrong before the call — a credential that will not build, a
        # client that will not construct — is still a failure of *this account*, and the
        # health machine has to hear about it or a broken login stays in rotation.
        if failure is None:
            failure = f"{e.__class__.__name__}: {e}"
        raise
    finally:
        if lease is not None:
            with contextlib.suppress(Exception):
                from memora.db.session import session_scope
                from memora.providers.errors import classify
                # Its own session, deliberately. When this call raised, the worker is about
                # to roll `db` back (worker/__main__.run_job), and a cooldown written into
                # that session would go with it — losing the one verdict the pool exists to
                # act on, on the exact path it exists for.
                async with session_scope() as s2:
                    await CP.report(s2, lease, ok=failure is None,
                                    code=None if failure is None else classify(failure), error=failure)
            lease.release()   # idempotent: report already released it on the normal path


def extract_json(text: str) -> dict[str, Any] | None:
    if not text:
        return None
    t = text.strip()
    if t.startswith("```"):
        t = re.sub(r"^```[a-zA-Z]*\n?", "", t).rstrip("`").strip()
    try:
        return json.loads(t)
    except Exception:
        m = _JSON_RE.search(t)
        if m:
            with contextlib.suppress(Exception):
                return json.loads(m.group(0))
    return None
