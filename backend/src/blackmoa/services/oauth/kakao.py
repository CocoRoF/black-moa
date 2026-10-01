"""카카오 (plan/59) — 카카오 로그인과 톡캘린더·나에게 보내기 연동.

- 인가 ``kauth.kakao.com/oauth/authorize`` · 토큰 ``kauth.kakao.com/oauth/token`` · 사용자 ``kapi.kakao.com/v2/user/me``.
- 앱 키는 **REST API 키**(client_id). Client Secret 은 카카오 콘솔에서 켰을 때만 보낸다.
- OpenID Connect 를 켠 앱이면 ``openid`` 로 id_token 을 받아 검증한다. 이메일은 [카카오계정(이메일)]
  동의항목을 설정한 앱에서만 오고, 카카오가 유효·인증됐다고 말한 것만 믿는다.
- 동의항목 ID 는 쉼표로 잇는다(카카오 규칙). 토큰 응답의 ``scope`` 는 공백으로 온다.
"""
from __future__ import annotations

from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from blackmoa.providers.http import request
from blackmoa.services.oauth import idtoken
from blackmoa.services.oauth.base import Capability, Config, Field, Identity, OAuthProvider

API = "https://kapi.kakao.com"


class Kakao(OAuthProvider):
    id = "kakao"
    label = "카카오"
    authorize_endpoint = "https://kauth.kakao.com/oauth/authorize"
    token_endpoint = "https://kauth.kakao.com/oauth/token"
    # 닉네임 하나만 청한다. 콘솔에 설정하지 않은 동의항목을 청하면 카카오가 로그인 화면을 열지 않는다(KOE205).
    login_scopes = ("profile_nickname",)
    capabilities = (
        # 톡캘린더는 동의항목 하나(talk_calendar)가 조회와 관리를 함께 연다.
        Capability("calendar_read", ("talk_calendar",)),
        Capability("calendar_write", ("talk_calendar",)),
        Capability("talk_message", ("talk_message",)),
    )
    fields = (Field("client_id", required=True), Field("client_secret", kind="secret"),
              Field("oidc", kind="bool"), Field("email", kind="bool"))
    console_url = "https://developers.kakao.com/console/app"
    scope_sep = ","
    jwks_url = "https://kauth.kakao.com/.well-known/jwks.json"
    issuers = ("https://kauth.kakao.com",)

    def login_scopes_for(self, cfg: Config) -> list[str]:
        out = []
        if cfg.values.get("oidc"):
            out.append("openid")
        out += list(self.login_scopes)
        if cfg.values.get("email"):
            out.append("account_email")
        return out

    async def authorize_url(self, db: AsyncSession, *, purpose: str, scopes: list[str], state: str, nonce: str,
                            locale: str | None = None) -> str:
        cfg = await self._cfg_or_raise(db)
        if purpose == "login":
            scopes = list(dict.fromkeys([*self.login_scopes_for(cfg), *[s for s in scopes if s not in self.login_scopes]]))
        # nonce 는 OpenID Connect 에서만 뜻이 있다.
        return await super().authorize_url(db, purpose=purpose, scopes=scopes, state=state,
                                           nonce=nonce if cfg.values.get("oidc") and "openid" in scopes else "", locale=locale)

    def base_scopes(self) -> tuple[str, ...]:
        # 데이터 연동에서도 누구의 카카오인지는 알아야 한다 — 이름 하나면 된다.
        return ("profile_nickname",)

    async def identity(self, db: AsyncSession, tokens: dict[str, Any], *, nonce: str) -> Identity:
        cfg = await self.config(db)
        sub = None
        claims: dict[str, Any] = {}
        if tokens.get("id_token"):
            claims = await idtoken.verify(tokens["id_token"], jwks_url=self.jwks_url, issuers=self.issuers,
                                          audience=cfg.client_id, nonce=nonce or None)
            sub = str(claims["sub"])
        # 이메일의 유효·인증 여부는 사용자 정보에만 있다. OIDC 여도 한 번 묻는다.
        r = await request("GET", f"{API}/v2/user/me", headers={"Authorization": f"Bearer {tokens['access_token']}"}, retries=1)
        me = r.json()
        kid = str(me.get("id") or "")
        if sub and kid and sub != kid:
            from blackmoa.core.errors import ValidationFailed
            raise ValidationFailed("id_token subject does not match the account", code="id_token_invalid")
        acct = me.get("kakao_account") or {}
        prof = acct.get("profile") or {}
        email = (acct.get("email") or "").lower() or None
        verified = bool(email) and bool(acct.get("is_email_valid")) and bool(acct.get("is_email_verified"))
        return Identity(provider=self.id, subject=sub or kid, email=email, email_verified=verified,
                        name=str(prof.get("nickname") or claims.get("nickname") or ""),
                        avatar_url=None if prof.get("is_default_image") else (prof.get("profile_image_url") or claims.get("picture")),
                        raw={"id": kid, "nickname": prof.get("nickname"), "email": email, "email_verified": verified})

    async def revoke(self, db: AsyncSession, *, access_token: str, refresh_token: str, scopes: list[str] | None = None) -> None:
        """데이터 연동을 끊을 때는 그 동의항목만 거둔다 — 카카오 로그인은 그대로 둔다."""
        if not access_token or not scopes:
            return
        import json
        await request("POST", f"{API}/v2/user/revoke/scopes", headers={"Authorization": f"Bearer {access_token}"},
                      data={"scopes": json.dumps(scopes)}, retries=1)

    def classify_check(self, status: int, body: dict[str, Any]) -> dict[str, Any]:
        code = str(body.get("error_code") or "")
        if code == "KOE004":
            return {"ok": False, "code": "login_disabled", "detail": str(body.get("error_description") or "")}
        if code == "KOE010":
            return {"ok": False, "code": "invalid_secret", "detail": str(body.get("error_description") or "")}
        if code in ("KOE101", "KOE102"):
            return {"ok": False, "code": "invalid_client", "detail": str(body.get("error_description") or "")}
        if code == "KOE303" or "redirect" in str(body.get("error_description") or "").lower():
            return {"ok": False, "code": "redirect_uri", "detail": str(body.get("error_description") or "")}
        return super().classify_check(status, body)
