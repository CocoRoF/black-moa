"""Keep a pinned engine talking to a newer Anthropic SDK.

anthropic 1.4 removed the sampling parameters — ``temperature``, ``top_p``, ``top_k`` —
from ``Messages.create`` and ``Messages.stream``. The engine still sends the temperature
every model config carries, and those methods take no ``**kwargs``, so every direct-API
call died before it left the process:

    AsyncMessages.stream() got an unexpected keyword argument 'temperature'

The engine already drops these for the model families whose *API* rejected them, but this
is not an API refusal — it is a signature that no longer has the parameter, so no request
is ever made and nothing can heal it at the 400 level.

Only those three keys are dropped, and only when the installed SDK genuinely cannot take
them: an unknown keyword that is not one of these still raises, because that would be our
bug rather than a version skew. Logged once per key so an operator can see why a
temperature they chose is not being sent.
"""
from __future__ import annotations

import inspect
from functools import wraps
from typing import Any

import structlog

log = structlog.get_logger(__name__)

SAMPLING_KEYS = ("temperature", "top_p", "top_k")
_installed = False
_warned: set[str] = set()


def _wrap(fn: Any, unsupported: tuple[str, ...], where: str) -> Any:
    @wraps(fn)
    def call(*args: Any, **kwargs: Any) -> Any:
        for key in unsupported:
            if key in kwargs:
                kwargs.pop(key)
                if key not in _warned:
                    _warned.add(key)
                    log.info("anthropic sdk does not accept this parameter; dropping it", param=key, method=where)
        return fn(*args, **kwargs)
    return call


def install() -> None:
    """Idempotent; safe to call when the SDK is absent or already compatible."""
    global _installed
    if _installed:
        return
    _installed = True
    try:
        from anthropic.resources.messages import AsyncMessages, Messages
    except Exception:  # noqa: BLE001 — no SDK installed: nothing to keep compatible
        return
    for cls in (AsyncMessages, Messages):
        for name in ("create", "stream"):
            fn = getattr(cls, name, None)
            if fn is None:
                continue
            params = inspect.signature(fn).parameters
            if any(p.kind is p.VAR_KEYWORD for p in params.values()):
                continue                      # takes anything: nothing to drop
            missing = tuple(k for k in SAMPLING_KEYS if k not in params)
            if missing:
                setattr(cls, name, _wrap(fn, missing, f"{cls.__name__}.{name}"))
