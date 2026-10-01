from __future__ import annotations

import re
from typing import Any

SECRET_KEYS = re.compile(r"(api_?key|token|password|secret|authorization|refresh|credential|private_key)", re.I)
EMAIL_RE = re.compile(r"([A-Za-z0-9._%+-]+)@([A-Za-z0-9.-]+\.[A-Za-z]{2,})")
PHONE_RE = re.compile(r"(?<!\d)(?:\+?82[-\s]?|0)1[016789][-\s]?\d{3,4}[-\s]?\d{4}(?!\d)|(?<!\d)\+?\d{1,3}[-\s]?\d{2,4}[-\s]?\d{3,4}[-\s]?\d{4}(?!\d)")
CARD_RE = re.compile(r"(?<!\d)(?:\d{4}[-\s]?){3}\d{4}(?!\d)")
KEY_RE = re.compile(r"(sk-[A-Za-z0-9_-]{16,}|ghp_[A-Za-z0-9]{20,}|xox[abp]-[A-Za-z0-9-]{10,}|AIza[0-9A-Za-z_-]{30,})")


def mask(value: str, keep: int = 4) -> str:
    if not value:
        return ""
    if len(value) <= keep:
        return "*" * len(value)
    return "*" * (len(value) - keep) + value[-keep:]


def redact_obj(obj: Any) -> Any:
    if isinstance(obj, dict):
        return {k: ("***" if isinstance(k, str) and SECRET_KEYS.search(k) else redact_obj(v)) for k, v in obj.items()}
    if isinstance(obj, list):
        return [redact_obj(v) for v in obj]
    if isinstance(obj, str):
        return KEY_RE.sub("***", obj)
    return obj


def structlog_redact(_logger, _method, event_dict):  # structlog processor
    return redact_obj(event_dict)
