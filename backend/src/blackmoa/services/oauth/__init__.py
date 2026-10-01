"""외부 연결 공급자 등록표 (plan/59). 새 공급자는 클래스 하나를 만들어 여기에 더한다."""
from __future__ import annotations

from blackmoa.core.errors import NotFound
from blackmoa.services.oauth.base import Capability, Config, Field, Identity, OAuthError, OAuthProvider
from blackmoa.services.oauth.google import Google
from blackmoa.services.oauth.kakao import Kakao

PROVIDERS: dict[str, OAuthProvider] = {p.id: p for p in (Google(), Kakao())}


def get(provider: str) -> OAuthProvider:
    p = PROVIDERS.get(provider)
    if p is None:
        raise NotFound("no such connection", code="provider_unknown")
    return p


__all__ = ["PROVIDERS", "get", "Capability", "Config", "Field", "Identity", "OAuthError", "OAuthProvider"]
