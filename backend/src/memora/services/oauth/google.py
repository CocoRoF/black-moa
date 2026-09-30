"""Google (plan/59) — OpenID Connect 로그인과 캘린더·연락처 연동.

메일(gmail.readonly)은 청하지 않는다(plan/74) — Google 이 "제한 범위"로 두어 매년 유료 보안 평가(CASA)를 요구한다.
메일함은 IMAP + 앱 비밀번호로 잇는다(services/imap_mail)."""
from __future__ import annotations

from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from memora.providers.http import request
from memora.services.oauth import idtoken
from memora.services.oauth.base import Capability, Config, Field, Identity, OAuthProvider

CAL_READ = "https://www.googleapis.com/auth/calendar.readonly"
CAL_EVENTS = "https://www.googleapis.com/auth/calendar.events"
CONTACTS = "https://www.googleapis.com/auth/contacts.readonly"
#: Drive — 사용자가 파일 선택 창에서 고른 파일과 이 앱이 만든 파일만(민감하지 않은 범위, plan/75)
DRIVE_FILE = "https://www.googleapis.com/auth/drive.file"


class Google(OAuthProvider):
    id = "google"
    label = "Google"
    authorize_endpoint = "https://accounts.google.com/o/oauth2/v2/auth"
    token_endpoint = "https://oauth2.googleapis.com/token"
    login_scopes = ("openid", "email", "profile")
    capabilities = (
        Capability("calendar_read", (CAL_READ,)),
        # 넣기는 따로 받는다: "언제 비는가" 를 보는 것과 거기에 무엇을 넣는 것은 다른 신뢰다 (plan/41 §9.2).
        Capability("calendar_write", (CAL_EVENTS,)),
        Capability("contacts", (CONTACTS,)),
        Capability("drive", (DRIVE_FILE,)),
    )
    #: 파일 선택 창(Google Picker)은 브라우저용 API 키와 프로젝트 번호가 있어야 뜬다 — 없으면 Drive 가져오기만 안 된다.
    fields = (Field("client_id", required=True), Field("client_secret", kind="secret", required=True),
              Field("picker_api_key"), Field("app_id"))
    console_url = "https://console.cloud.google.com/apis/credentials"
    #: 동의 화면을 이 사람이 Memora 에서 쓰는 언어로 — 영어로 쓰는 사람에게는 영어 화면.
    locale_param = "hl"
    jwks_url = "https://www.googleapis.com/oauth2/v3/certs"
    issuers = ("https://accounts.google.com", "accounts.google.com")

    def extra_authorize_params(self, cfg: Config, *, purpose: str) -> dict[str, str]:
        if purpose == "connect":
            # 데이터 연동은 오래 가야 한다: 갱신 토큰을 받고, 이미 준 권한은 이어서 쌓는다.
            return {"access_type": "offline", "prompt": "consent", "include_granted_scopes": "true"}
        return {"prompt": "select_account"}

    async def identity(self, db: AsyncSession, tokens: dict[str, Any], *, nonce: str) -> Identity:
        cfg = await self.config(db)
        if tokens.get("id_token"):
            c = await idtoken.verify(tokens["id_token"], jwks_url=self.jwks_url, issuers=self.issuers,
                                     audience=cfg.client_id, nonce=nonce or None)
        else:
            r = await request("GET", "https://openidconnect.googleapis.com/v1/userinfo",
                              headers={"Authorization": f"Bearer {tokens['access_token']}"}, retries=1)
            c = r.json()
        return Identity(provider=self.id, subject=str(c["sub"]), email=(c.get("email") or "").lower() or None,
                        email_verified=bool(c.get("email_verified")), name=str(c.get("name") or ""),
                        avatar_url=c.get("picture"), raw={k: c.get(k) for k in ("sub", "email", "email_verified", "name", "picture")})

    async def revoke(self, db: AsyncSession, *, access_token: str, refresh_token: str, scopes: list[str] | None = None) -> None:
        tok = refresh_token or access_token
        if tok:
            await request("POST", "https://oauth2.googleapis.com/revoke", data={"token": tok}, retries=1)
