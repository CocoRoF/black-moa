"""Share-link code generation + handle validation."""
from __future__ import annotations

import re
import secrets

# Shared links live under their own prefix. They used to sit at the root, where every code
# competed with the app's own pages for one namespace: a new top-level route could shadow
# a link somebody had already printed, and the only defence was the word list below.
LINK_PREFIX = "secretary"

ALPHABET = "abcdefghjkmnpqrstuvwxyz23456789"
# Kept although codes are namespaced now: the old links still resolve through a redirect at
# the root, so a code that collides with a page there would break that path — and these are
# words nobody should be handed as an identity anyway.
RESERVED = frozenset(
    "app admin api login signup logout health static _next c s about terms privacy favicon.ico manifest.webmanifest "
    "robots.txt sitemap.xml assets public docs metrics ws internal auth users agents settings help support blog "
    "pricing legal www mail secretary".split()
)
HANDLE_RE = re.compile(r"^[a-z0-9](?:[a-z0-9-]{1,30}[a-z0-9])$")


def public_link_url(code: str) -> str:
    from blackmoa.config import get_settings

    return f"{get_settings().public_url.rstrip('/')}/{LINK_PREFIX}/{code}"


def generate_code(length: int = 8) -> str:
    return "".join(secrets.choice(ALPHABET) for _ in range(length))


def validate_handle(handle: str) -> str:
    h = (handle or "").strip().lower()
    if not HANDLE_RE.match(h):
        raise ValueError("invalid_handle")
    if h in RESERVED:
        raise ValueError("reserved_handle")
    return h
