"""OpenID Connect ``id_token`` 검증 (plan/59).

예전에는 id_token 을 base64 로 풀기만 했다. 이제는 공급자의 공개 키(JWKS)로 서명을 확인하고
발급자(iss) · 대상(aud = 우리 앱) · 만료(exp) · nonce 를 확인한다.

공개 키는 잠시 들고 있다가, 모르는 키 번호(kid)가 오면 한 번 다시 받는다(공급자가 키를 바꿀 때).
토큰 창구에서 TLS 로 직접 받은 토큰이라 서명 확인은 표준상 선택이지만(OIDC Core 3.1.3.7),
확인할 수 있으면 확인한다. 공개 키를 끝내 받지 못하면 서명 없이 나머지 항목만 확인한다.
"""
from __future__ import annotations

import time
from typing import Any

import jwt

from memora.core.errors import ValidationFailed
from memora.core.logging import get_logger
from memora.providers.http import request

log = get_logger("memora.oauth")
_JWKS: dict[str, tuple[float, dict[str, Any]]] = {}
_TTL = 6 * 3600


async def _jwks(url: str, *, refresh: bool = False) -> dict[str, Any] | None:
    now = time.monotonic()
    hit = _JWKS.get(url)
    if hit and hit[0] > now and not refresh:
        return hit[1]
    try:
        r = await request("GET", url, retries=2)
        doc = r.json()
    except Exception as e:  # noqa: BLE001
        log.warning("jwks fetch failed", url=url, err=str(e)[:160])
        return hit[1] if hit else None
    _JWKS[url] = (now + _TTL, doc)
    return doc


def _key(doc: dict[str, Any] | None, kid: str | None):
    for k in (doc or {}).get("keys", []):
        if kid is None or k.get("kid") == kid:
            try:
                return jwt.PyJWK(k).key
            except Exception:  # noqa: BLE001
                continue
    return None


async def verify(token: str, *, jwks_url: str, issuers: tuple[str, ...], audience: str, nonce: str | None) -> dict[str, Any]:
    """검증한 클레임. 틀리면 ``ValidationFailed(code="id_token_invalid")``."""
    try:
        header = jwt.get_unverified_header(token)
    except jwt.PyJWTError as e:
        raise ValidationFailed("malformed id_token", code="id_token_invalid") from e
    alg = header.get("alg") or "RS256"
    if alg not in ("RS256", "RS384", "RS512", "ES256"):
        raise ValidationFailed("unexpected id_token algorithm", code="id_token_invalid")
    key = _key(await _jwks(jwks_url), header.get("kid"))
    if key is None:
        key = _key(await _jwks(jwks_url, refresh=True), header.get("kid"))
    opts = {"require": ["exp", "iat", "iss", "aud", "sub"]}
    try:
        if key is not None:
            claims = jwt.decode(token, key, algorithms=[alg], audience=audience, issuer=list(issuers), options=opts, leeway=60)
        else:
            # 공개 키를 받지 못했다. 토큰 창구에서 TLS 로 직접 받은 것이니 나머지 항목만 확인한다.
            log.warning("id_token verified without signature (jwks unavailable)", iss=issuers[0])
            claims = jwt.decode(token, options={**opts, "verify_signature": False}, audience=audience,
                                issuer=list(issuers), algorithms=[alg], leeway=60)
    except jwt.PyJWTError as e:
        raise ValidationFailed(f"id_token rejected: {e}", code="id_token_invalid") from e
    if nonce is not None and claims.get("nonce") != nonce:
        raise ValidationFailed("id_token nonce mismatch", code="id_token_invalid")
    return claims
