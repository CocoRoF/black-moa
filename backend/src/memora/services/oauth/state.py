"""연결 흐름의 state — 서명 + 이 브라우저와 묶기 (plan/59).

state 는 서버가 서명한 짧은 토큰(15분)이다. 거기에 더해, 흐름을 시작한 브라우저에만 있는 무작위
값을 HttpOnly 쿠키로 심고 state 에는 그 해시를 싣는다. 돌아왔을 때 둘이 맞지 않으면 받지 않는다 —
남이 자기 계정으로 시작한 흐름의 주소를 내 브라우저에 밀어 넣어 "남의 계정으로 로그인시키는"
공격(login CSRF)을 막는다. OIDC 의 nonce 도 여기서 만든다.
"""
from __future__ import annotations

import hashlib
import secrets
from typing import Any

from fastapi import Response

from memora.config import get_settings
from memora.core.errors import Unauthorized
from memora.core.security import sign_state, verify_state

COOKIE = "memora_oauth"
TTL_MIN = 15


def _h(v: str) -> str:
    return hashlib.sha256(v.encode()).hexdigest()


def begin(response: Response, *, provider: str, purpose: str, **extra: Any) -> tuple[str, str]:
    """새 흐름. (state, nonce) 를 돌려주고 쿠키를 심는다."""
    bind = secrets.token_urlsafe(24)
    nonce = secrets.token_urlsafe(16)
    state = sign_state({"kind": "oauth", "provider": provider, "purpose": purpose, "bind": _h(bind), "nonce": nonce,
                        **{k: v for k, v in extra.items() if v is not None}}, ttl_minutes=TTL_MIN)
    s = get_settings()
    response.set_cookie(COOKIE, bind, max_age=TTL_MIN * 60, httponly=True, secure=s.public_url.startswith("https"),
                        samesite="lax", path="/api")
    return state, nonce


def finish(state: str, cookie: str | None, *, provider: str) -> dict[str, Any]:
    """돌아온 state 를 확인한다. 서명·만료·공급자·브라우저가 모두 맞아야 한다."""
    try:
        st = verify_state(state)
    except Unauthorized as e:
        raise Unauthorized("invalid or expired state", code="bad_state") from e
    if st.get("kind") != "oauth" or st.get("provider") != provider:
        raise Unauthorized("state is for another flow", code="bad_state")
    if not cookie or _h(cookie) != st.get("bind"):
        raise Unauthorized("this sign-in was started in another browser", code="state_browser_mismatch")
    return st


def clear(response: Response) -> None:
    response.delete_cookie(COOKIE, path="/api")


def safe_next(v: Any, default: str = "/app") -> str:
    """돌아갈 곳은 우리 앱 안의 경로만. 밖으로 나가는 주소는 열린 리다이렉트다."""
    v = str(v or "").strip()
    if v.startswith("/") and not v.startswith("//") and "\\" not in v and "://" not in v and len(v) <= 300:
        return v
    return default


def join(path: str, **params: str) -> str:
    """경로에 질의 몇 개를 잇는다 — 이미 ``?`` 가 있으면 ``&`` 로."""
    from urllib.parse import urlencode
    if not params:
        return path
    return f"{path}{'&' if '?' in path else '?'}{urlencode(params)}"
