"""외부 연결의 공급자 틀 (plan/59).

공급자 하나가 클래스 하나다: 인가 주소 · 코드 교환 · 토큰 갱신 · 신원(로그인) · 철회 · 설정 확인.
로그인(SSO)과 데이터 연동이 같은 클래스를 쓰고, 관리자 [연결] 화면과 사용자 화면은 이 목록을 그대로 그린다.

관리자가 넣는 값은 시스템 설정 ``oauth.<id>.<field>`` 에 있다(비밀은 암호화). 켜져 있고 필수 값이
다 있으면 그대로 작동한다 — 코드를 고치지 않는다.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, ClassVar
from urllib.parse import urlencode

from sqlalchemy.ext.asyncio import AsyncSession

from memora.config import get_settings
from memora.core.errors import ServiceUnavailable, ValidationFailed
from memora.providers.http import ProviderHTTPError, request
from memora.services import settings as S


@dataclass
class Identity:
    """공급자가 말해 준 "이 사람". ``subject`` 는 그 공급자 안에서 바뀌지 않는 번호다."""

    provider: str
    subject: str
    email: str | None = None
    #: 공급자가 **검증했다고 말한** 이메일인가. 참일 때만 기존 계정과 이어 붙인다.
    email_verified: bool = False
    name: str = ""
    avatar_url: str | None = None
    raw: dict[str, Any] = field(default_factory=dict)

    @property
    def label(self) -> str:
        return self.email or self.name or self.subject


@dataclass(frozen=True)
class Field:
    """관리자 [연결] 화면의 칸 하나."""

    key: str
    kind: str = "text"          # text | secret | bool
    required: bool = False


@dataclass(frozen=True)
class Capability:
    """사용자에게 줄 수 있는 기능 하나와, 그것에 필요한 공급자 권한."""

    id: str
    scopes: tuple[str, ...]


@dataclass
class Config:
    enabled: bool
    login: bool
    features: list[str]
    values: dict[str, Any]

    @property
    def client_id(self) -> str:
        return str(self.values.get("client_id") or "").strip()

    @property
    def client_secret(self) -> str:
        return str(self.values.get("client_secret") or "").strip()


class OAuthError(ValidationFailed):
    """공급자가 거절했거나 알아들을 수 없는 답을 준 것."""


class OAuthProvider:
    id: ClassVar[str] = ""
    label: ClassVar[str] = ""
    authorize_endpoint: ClassVar[str] = ""
    token_endpoint: ClassVar[str] = ""
    #: 로그인에 쓸 때 청하는 권한
    login_scopes: ClassVar[tuple[str, ...]] = ()
    #: 데이터 기능들 — 순서대로 화면에 나온다
    capabilities: ClassVar[tuple[Capability, ...]] = ()
    #: 관리자가 넣는 칸(켜기·로그인·기능 말고)
    fields: ClassVar[tuple[Field, ...]] = (Field("client_id", required=True), Field("client_secret", kind="secret", required=True))
    #: 공급자 콘솔
    console_url: ClassVar[str] = ""
    #: 권한 문자열의 구분자 (Google·카카오 모두 공백)
    scope_sep: ClassVar[str] = " "

    # ── 설정 ────────────────────────────────────────────────────────────

    def key(self, name: str) -> str:
        return f"oauth.{self.id}.{name}"

    async def config(self, db: AsyncSession) -> Config:
        values = {f.key: await S.get(db, self.key(f.key)) for f in self.fields}
        feats = await S.get(db, self.key("features")) or []
        known = {c.id for c in self.capabilities}
        return Config(enabled=bool(await S.get(db, self.key("enabled"))), login=bool(await S.get(db, self.key("login"))),
                      features=[f for f in feats if f in known], values=values)

    def missing(self, cfg: Config) -> list[str]:
        """켜기 전에 채워야 하는 칸."""
        return [f.key for f in self.fields if f.required and not str(cfg.values.get(f.key) or "").strip()]

    async def ready(self, db: AsyncSession) -> bool:
        """켜져 있고 필수 값이 다 있는가 — 로그인 버튼·연동 카드가 보이는 조건."""
        cfg = await self.config(db)
        return cfg.enabled and not self.missing(cfg)

    async def login_ready(self, db: AsyncSession) -> bool:
        cfg = await self.config(db)
        return cfg.enabled and cfg.login and not self.missing(cfg)

    async def offered(self, db: AsyncSession) -> list[str]:
        """사용자에게 줄 기능 — 켜져 있을 때만."""
        cfg = await self.config(db)
        if not cfg.enabled or self.missing(cfg):
            return []
        # 이제 없는 기능(예: 빼 버린 gmail_read)이 설정에 남아 있어도 내주지 않는다.
        known = {c.id for c in self.capabilities}
        return [f for f in cfg.features if f in known]

    async def _cfg_or_raise(self, db: AsyncSession) -> Config:
        cfg = await self.config(db)
        if not cfg.enabled or self.missing(cfg):
            raise ServiceUnavailable(f"{self.id} is not configured", code=f"{self.id}_not_configured")
        return cfg

    # ── 주소 ────────────────────────────────────────────────────────────

    def redirect_uri(self, purpose: str) -> str:
        """``login`` 이면 로그인·계정 연결, ``connect`` 면 데이터 연동. 공급자 콘솔에 둘 다 등록한다."""
        base = get_settings().public_url.rstrip("/")
        if purpose == "connect":
            return f"{base}/api/integrations/{self.id}/callback"
        return f"{base}/api/auth/{self.id}/callback"

    def scopes_for(self, caps: list[str], *, login: bool) -> list[str]:
        out: list[str] = list(self.login_scopes) if login else list(self.base_scopes())
        for c in self.capabilities:
            if c.id in caps:
                for s in c.scopes:
                    if s not in out:
                        out.append(s)
        return out

    def base_scopes(self) -> tuple[str, ...]:
        """데이터 연동에도 늘 청하는 것 — 연결한 계정이 누구인지 알기 위해."""
        return self.login_scopes

    def granted(self, scopes: list[str] | None, cap: str) -> bool:
        have = set(scopes or [])
        c = next((c for c in self.capabilities if c.id == cap), None)
        return c is not None and all(s in have for s in c.scopes)

    def granted_caps(self, scopes: list[str] | None) -> list[str]:
        return [c.id for c in self.capabilities if self.granted(scopes, c.id)]

    def extra_authorize_params(self, cfg: Config, *, purpose: str) -> dict[str, str]:
        return {}

    #: 동의 화면의 언어를 정하는 인자 이름(Google 은 ``hl``). 없으면 공급자가 알아서 고른다.
    locale_param: str | None = None

    async def authorize_url(self, db: AsyncSession, *, purpose: str, scopes: list[str], state: str, nonce: str,
                            locale: str | None = None) -> str:
        cfg = await self._cfg_or_raise(db)
        params = {"client_id": cfg.client_id, "redirect_uri": self.redirect_uri(purpose), "response_type": "code",
                  "state": state, "scope": self.scope_sep.join(scopes)}
        if nonce:
            params["nonce"] = nonce
        params.update(self.extra_authorize_params(cfg, purpose=purpose))
        if locale and self.locale_param:
            params[self.locale_param] = locale
        return f"{self.authorize_endpoint}?{urlencode(params)}"

    # ── 토큰 ────────────────────────────────────────────────────────────

    def token_body(self, cfg: Config, extra: dict[str, str]) -> dict[str, str]:
        body = {"client_id": cfg.client_id, **extra}
        if cfg.client_secret:
            body["client_secret"] = cfg.client_secret
        return body

    async def _token(self, db: AsyncSession, extra: dict[str, str]) -> dict[str, Any]:
        cfg = await self._cfg_or_raise(db)
        try:
            r = await request("POST", self.token_endpoint, data=self.token_body(cfg, extra), retries=1,
                              headers={"Content-Type": "application/x-www-form-urlencoded;charset=utf-8"})
        except ProviderHTTPError as e:
            err = OAuthError(f"{self.id} token endpoint refused: {e.body[:200]}", code=f"{self.id}_token_failed")
            #: 400/401 이면 공급자가 이 토큰·코드를 거절한 것 — 연결을 "다시 연결 필요" 로 둔다.
            err.status = e.status
            err.body = e.body[:300]
            raise err from e
        return r.json()

    async def exchange(self, db: AsyncSession, *, code: str, purpose: str) -> dict[str, Any]:
        return await self._token(db, {"grant_type": "authorization_code", "code": code,
                                      "redirect_uri": self.redirect_uri(purpose)})

    async def refresh(self, db: AsyncSession, refresh_token: str) -> dict[str, Any]:
        return await self._token(db, {"grant_type": "refresh_token", "refresh_token": refresh_token})

    def token_scopes(self, tokens: dict[str, Any]) -> list[str]:
        return [s for s in str(tokens.get("scope") or "").replace(",", " ").split() if s]

    # ── 신원·철회·확인 (공급자마다) ──────────────────────────────────────

    async def identity(self, db: AsyncSession, tokens: dict[str, Any], *, nonce: str) -> Identity:
        raise NotImplementedError

    async def revoke(self, db: AsyncSession, *, access_token: str, refresh_token: str, scopes: list[str] | None = None) -> None:
        """연동을 끊을 때 공급자 쪽 권한도 거둔다. ``scopes`` 는 이 연동이 받은 데이터 권한."""
        return None

    async def check(self, db: AsyncSession) -> dict[str, Any]:
        """관리자의 [설정 확인]. 가짜 코드로 토큰 창구를 두드려, 앱 키가 맞는지를 공급자의 답으로 가른다.

        키가 맞으면 공급자는 "그런 코드 없음"(invalid_grant)으로, 틀리면 "그런 앱/비밀 없음"(invalid_client)으로 답한다.
        사용자 없이 키만 확인하는 방법이 이것뿐이다.
        """
        cfg = await self.config(db)
        missing = self.missing(cfg)
        if missing:
            return {"ok": False, "code": "missing", "fields": missing}
        try:
            await request("POST", self.token_endpoint, retries=1, data=self.token_body(cfg, {
                "grant_type": "authorization_code", "code": "memora-config-check", "redirect_uri": self.redirect_uri("login")}),
                headers={"Content-Type": "application/x-www-form-urlencoded;charset=utf-8"})
        except ProviderHTTPError as e:
            return self.classify_check(e.status, _json(e.body))
        except Exception as e:  # noqa: BLE001 — 닿지 않으면 그렇다고 말한다
            return {"ok": False, "code": "unreachable", "detail": str(e)[:200]}
        return {"ok": False, "code": "unexpected", "detail": "the provider accepted a fake code"}

    def classify_check(self, status: int, body: dict[str, Any]) -> dict[str, Any]:
        err = str(body.get("error") or "")
        if err == "invalid_grant":
            return {"ok": True, "code": "ok"}
        if err in ("invalid_client", "unauthorized_client"):
            return {"ok": False, "code": "invalid_client", "detail": str(body.get("error_description") or "")[:200]}
        if "redirect" in str(body.get("error_description") or "").lower() or err == "redirect_uri_mismatch":
            return {"ok": False, "code": "redirect_uri", "detail": str(body.get("error_description") or "")[:200]}
        return {"ok": False, "code": err or f"http_{status}", "detail": str(body.get("error_description") or "")[:200]}


def _json(text: str) -> dict[str, Any]:
    import json
    try:
        v = json.loads(text)
        return v if isinstance(v, dict) else {}
    except ValueError:
        return {}
