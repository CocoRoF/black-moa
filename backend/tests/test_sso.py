"""연결로 로그인 · 관리자 [연결] · 카카오 데이터 (plan/59).

관리자가 [연결] 에서 공급자의 앱 키를 넣고 켜면, 로그인 버튼과 데이터 연동이 그대로 작동해야 한다.
여기서는 공급자와 주고받는 부분(코드 교환·사용자 정보·HTTP)만 흉내 내고, 우리 쪽 흐름은 실제로 탄다.
"""
from __future__ import annotations

import json
import time
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any
from urllib.parse import parse_qs, urlparse

import pytest_asyncio
from httpx import AsyncClient
from sqlalchemy import select

from blackmoa.db.session import session_scope
from blackmoa.models import AuthIdentity, Connection, User
from blackmoa.services import oauth as OA
from blackmoa.services import settings as S
from tests.conftest import auth, signup


async def _provider(pid: str, *, enabled: bool = True, login: bool = True, **extra: Any) -> None:
    async with session_scope() as db:
        await S.put(db, f"oauth.{pid}.enabled", enabled)
        await S.put(db, f"oauth.{pid}.login", login)
        await S.put(db, f"oauth.{pid}.client_id", "cid" if enabled else "")
        await S.put(db, f"oauth.{pid}.client_secret", "sec" if enabled else "")
        await S.put(db, f"oauth.{pid}.features", [c.id for c in OA.get(pid).capabilities])
        for k, v in extra.items():
            await S.put(db, f"oauth.{pid}.{k}", v)
        await db.commit()
    S.invalidate("oauth.")


async def _signup_mode(mode: str) -> None:
    async with session_scope() as db:
        await S.put(db, "signup.mode", mode)
        await db.commit()
    S.invalidate("signup.")


@pytest_asyncio.fixture(autouse=True)
async def _clean(app):
    yield
    for pid in ("google", "kakao"):
        await _provider(pid, enabled=False)
    async with session_scope() as db:
        await S.put(db, "oauth.kakao.oidc", False)
        await S.put(db, "oauth.kakao.email", False)
        await db.commit()
    await _signup_mode("open")


def _fake(monkeypatch, pid: str, ident: OA.Identity | None, *, tokens: dict | None = None) -> dict:
    """공급자의 코드 교환·신원을 흉내 낸다. 받은 nonce 를 돌려준다(검증에 쓰였는지 보려고)."""
    seen: dict[str, Any] = {}
    p = OA.PROVIDERS[pid]

    async def exchange(db, *, code, purpose):
        seen["purpose"] = purpose
        return tokens or {"access_token": "at", "expires_in": 3600, "scope": "openid email"}

    async def identity(db, toks, *, nonce):
        seen["nonce"] = nonce
        if ident is None:
            raise RuntimeError("boom")
        return ident

    monkeypatch.setattr(p, "exchange", exchange)
    monkeypatch.setattr(p, "identity", identity)
    return seen


async def _sso(client: AsyncClient, pid: str, *, start: str | None = None, **params: str):
    """로그인 버튼 → 공급자 → 콜백. 쿠키는 브라우저처럼 클라이언트가 들고 다닌다."""
    r = await client.get(start or f"/api/auth/{pid}/start", params=params, follow_redirects=False)
    assert r.status_code == 302, r.text
    q = parse_qs(urlparse(r.headers["location"]).query)
    state = q["state"][0]
    cb = await client.get(f"/api/auth/{pid}/callback", params={"code": "c", "state": state}, follow_redirects=False)
    return r, cb


def _loc(r) -> tuple[str, dict[str, str]]:
    u = urlparse(r.headers["location"])
    return u.path, {k: v[0] for k, v in parse_qs(u.query).items()}


# ── 로그인 버튼 ─────────────────────────────────────────────────────────


async def test_the_login_button_appears_only_when_the_provider_is_ready(client: AsyncClient):
    assert (await client.get("/api/auth/status")).json()["sso"] == []
    await _provider("google")
    assert [p["id"] for p in (await client.get("/api/auth/status")).json()["sso"]] == ["google"]
    # 로그인에 쓰기를 끄면 버튼이 사라진다(데이터 연동은 그대로).
    await _provider("google", login=False)
    assert (await client.get("/api/auth/status")).json()["sso"] == []
    # 필수 칸(Client Secret)이 비면 켜져 있어도 작동하지 않는다.
    await _provider("google")
    async with session_scope() as db:
        await S.put(db, "oauth.google.client_secret", "")
        await db.commit()
    S.invalidate("oauth.")
    assert (await client.get("/api/auth/status")).json()["sso"] == []
    r = await client.get("/api/auth/google/start", follow_redirects=False)
    assert _loc(r) == ("/login", {"error": "sso_unavailable"})


async def test_start_sends_the_browser_to_the_provider_bound_to_it(client: AsyncClient):
    await _provider("google")
    r = await client.get("/api/auth/google/start", params={"next": "/app/inbox"}, follow_redirects=False)
    u = urlparse(r.headers["location"])
    q = {k: v[0] for k, v in parse_qs(u.query).items()}
    assert u.netloc == "accounts.google.com" and q["client_id"] == "cid" and q["response_type"] == "code"
    assert q["redirect_uri"] == "http://testserver/api/auth/google/callback"
    assert set(q["scope"].split()) == {"openid", "email", "profile"} and q["nonce"] and q["state"]
    # 이 브라우저에만 있는 값(HttpOnly)을 심는다 — 남의 흐름 주소를 밀어 넣는 공격을 막는다.
    cookie = r.headers["set-cookie"]
    assert "blackmoa_oauth=" in cookie and "HttpOnly" in cookie and "Path=/api" in cookie

    # 카카오: 동의항목은 쉼표로, OIDC 를 켠 앱이면 openid 와 nonce, 이메일을 켠 앱이면 account_email.
    await _provider("kakao", oidc=True, email=True)
    r = await client.get("/api/auth/kakao/start", follow_redirects=False)
    q = {k: v[0] for k, v in parse_qs(urlparse(r.headers["location"]).query).items()}
    assert q["scope"] == "openid,profile_nickname,account_email" and q["nonce"]
    await _provider("kakao", oidc=False, email=False)
    r = await client.get("/api/auth/kakao/start", follow_redirects=False)
    q = {k: v[0] for k, v in parse_qs(urlparse(r.headers["location"]).query).items()}
    assert q["scope"] == "profile_nickname" and "nonce" not in q


async def test_a_callback_from_another_browser_is_refused(client: AsyncClient, app, monkeypatch):
    await _provider("google")
    _fake(monkeypatch, "google", OA.Identity(provider="google", subject="s", email="x@example.com", email_verified=True))
    r = await client.get("/api/auth/google/start", follow_redirects=False)
    state = parse_qs(urlparse(r.headers["location"]).query)["state"][0]
    # 다른 브라우저 — 쿠키가 없다.
    from httpx import ASGITransport
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as other:
        cb = await other.get("/api/auth/google/callback", params={"code": "c", "state": state}, follow_redirects=False)
    assert _loc(cb) == ("/login", {"error": "state_browser_mismatch"})
    # 위조한 state.
    cb = await client.get("/api/auth/google/callback", params={"code": "c", "state": "forged"}, follow_redirects=False)
    assert _loc(cb)[0] == "/login" and "error" in _loc(cb)[1]
    # 다른 공급자의 state 는 받지 않는다.
    await _provider("kakao")
    cb = await client.get("/api/auth/kakao/callback", params={"code": "c", "state": state}, follow_redirects=False)
    assert _loc(cb) == ("/login", {"error": "bad_state"})


# ── 로그인 · 가입 ───────────────────────────────────────────────────────


async def test_a_new_verified_account_signs_up_and_comes_back_signed_in(client: AsyncClient, monkeypatch):
    await _provider("google")
    email = f"g{uuid.uuid4().hex[:6]}@gmail.com"
    sub = uuid.uuid4().hex
    seen = _fake(monkeypatch, "google", OA.Identity(provider="google", subject=sub, email=email, email_verified=True, name="구글 사람"))
    start, cb = await _sso(client, "google", next="/app/inbox")
    assert cb.status_code == 302 and _loc(cb) == ("/app/inbox", {"login": "google"})
    assert "blackmoa_refresh=" in cb.headers.get("set-cookie", "")
    # nonce 는 시작할 때 만든 것이 신원 확인까지 간다.
    assert seen["nonce"] == parse_qs(urlparse(start.headers["location"]).query)["nonce"][0]
    async with session_scope() as db:
        u = (await db.execute(select(User).where(User.email == email))).scalars().one()
        assert u.password_hash is None and u.email_verified_at is not None and u.display_name == "구글 사람"
        ids = (await db.execute(select(AuthIdentity).where(AuthIdentity.user_id == u.id))).scalars().all()
        assert [(i.provider, i.subject) for i in ids] == [("google", sub)]
        uid = u.id
    # 다음 번에는 같은 계정으로 들어온다(새 계정을 만들지 않는다).
    _, cb = await _sso(client, "google")
    assert _loc(cb) == ("/app", {"login": "google"})
    async with session_scope() as db:
        assert len((await db.execute(select(User).where(User.email == email))).scalars().all()) == 1
        assert (await db.get(User, uid)).last_login_at is not None
    # 받은 세션으로 들어갈 수 있다.
    r = await client.post("/api/auth/refresh")
    assert r.status_code == 200 and r.json()["user"]["email"] == email


async def test_a_verified_email_joins_the_existing_account(client: AsyncClient, monkeypatch):
    await _provider("kakao", email=True)
    user, tok = await signup(client)
    async with session_scope() as db:
        (await db.get(User, uuid.UUID(user["id"]))).email_verified_at = datetime.now(UTC)
        await db.commit()
    _fake(monkeypatch, "kakao", OA.Identity(provider="kakao", subject="k-join", email=user["email"], email_verified=True, name="카톡"))
    _, cb = await _sso(client, "kakao")
    assert _loc(cb) == ("/app", {"login": "kakao"})
    async with session_scope() as db:
        u = await db.get(User, uuid.UUID(user["id"]))
        # 이미 주소를 증명한 계정이면 비밀번호도 그대로다 — 들어오는 방법이 하나 는 것이다.
        assert u.password_hash is not None
        assert (await db.execute(select(AuthIdentity.provider).where(AuthIdentity.user_id == u.id))).scalars().all() == ["kakao"]


async def test_someone_who_signed_up_with_my_address_first_loses_the_account(client: AsyncClient, monkeypatch):
    """남이 내 주소로 먼저 가입해 두고(인증 없이) 비밀번호를 쥐고 있으면, 주소를 증명한 내가 계정을 갖는다."""
    await _provider("google")
    squatter, _ = await signup(client, email=f"victim{uuid.uuid4().hex[:6]}@gmail.com")
    r = await client.post("/api/auth/login", json={"email": squatter["email"], "password": "correct-horse-9"})
    assert r.status_code == 200
    _fake(monkeypatch, "google", OA.Identity(provider="google", subject="g-victim", email=squatter["email"], email_verified=True))
    _, cb = await _sso(client, "google")
    assert _loc(cb)[1].get("login") == "google"
    async with session_scope() as db:
        u = await db.get(User, uuid.UUID(squatter["id"]))
        assert u.password_hash is None and u.email_verified_at is not None
    r = await client.post("/api/auth/login", json={"email": squatter["email"], "password": "correct-horse-9"})
    assert r.status_code == 401, "먼저 가입해 둔 사람의 비밀번호는 더 이상 통하지 않는다"


async def test_an_unverified_or_missing_email_finishes_signup_on_our_page(client: AsyncClient, monkeypatch):
    await _provider("kakao")
    sub = f"k-{uuid.uuid4().hex[:8]}"
    # 카카오가 인증했다고 말하지 않은 이메일은 남의 계정에 붙이지 않는다 — 마무리 화면에서 이메일을 받는다.
    victim, _ = await signup(client)
    _fake(monkeypatch, "kakao", OA.Identity(provider="kakao", subject=sub, email=victim["email"], email_verified=False,
                                            name="닉네임", raw={"id": sub}))
    _, cb = await _sso(client, "kakao", next="/app/agents")
    path, q = _loc(cb)
    assert path == "/signup/complete" and q["t"]
    async with session_scope() as db:
        assert (await db.execute(select(AuthIdentity).where(AuthIdentity.subject == sub))).first() is None
    pend = (await client.get("/api/auth/sso/pending", params={"t": q["t"]})).json()
    assert pend["provider"] == "kakao" and pend["name"] == "닉네임" and pend["email_hint"] == victim["email"]
    assert pend["invite_needed"] is False
    # 이미 있는 주소로는 마칠 수 없다.
    r = await client.post("/api/auth/sso/complete", json={"token": q["t"], "email": victim["email"], "display_name": "닉네임", "agree_terms": True})
    assert r.status_code == 409 and r.json()["error"]["code"] == "email_taken"
    email = f"k{uuid.uuid4().hex[:6]}@example.com"
    r = await client.post("/api/auth/sso/complete", json={"token": q["t"], "email": email, "display_name": "닉네임", "agree_terms": True})
    assert r.status_code == 200, r.text
    j = r.json()
    assert j["access_token"] and j["next"] == "/app/agents" and "blackmoa_refresh=" in r.headers.get("set-cookie", "")
    async with session_scope() as db:
        u = (await db.execute(select(User).where(User.email == email))).scalars().one()
        # 우리가 받은 이메일은 아직 증명되지 않았다.
        assert u.email_verified_at is None and u.password_hash is None
    # 같은 토큰으로 두 번 가입하지 않는다.
    r = await client.post("/api/auth/sso/complete", json={"token": q["t"], "email": "again@example.com", "display_name": "x", "agree_terms": True})
    assert r.status_code == 409 and r.json()["error"]["code"] == "identity_taken"
    # 그다음부터는 카카오로 바로 들어온다.
    _, cb = await _sso(client, "kakao")
    assert _loc(cb) == ("/app", {"login": "kakao"})


async def test_signup_rules_hold_for_sso_too(client: AsyncClient, monkeypatch):
    await _provider("google")
    await signup(client)            # 첫 가입(관리자)이 아닌 경우를 보려고
    await _signup_mode("invite")
    email = f"inv{uuid.uuid4().hex[:6]}@gmail.com"
    _fake(monkeypatch, "google", OA.Identity(provider="google", subject=f"g-{email}", email=email, email_verified=True))
    _, cb = await _sso(client, "google")
    assert _loc(cb) == ("/login", {"error": "invite_required"})
    # 초대 코드를 넣고 시작하면 된다.
    code = f"INV{uuid.uuid4().hex[:6]}"
    async with session_scope() as db:
        from blackmoa.models import Invite
        db.add(Invite(code=code, max_uses=1, used=0))
        await db.commit()
    _, cb = await _sso(client, "google", invite=code)
    assert _loc(cb)[1].get("login") == "google"
    # 가입을 닫으면 새 사람은 들어오지 못한다 — 이메일이 없는 계정도 마무리 화면까지 보내지 않는다.
    await _signup_mode("closed")
    _fake(monkeypatch, "google", OA.Identity(provider="google", subject="g-closed", email=None))
    _, cb = await _sso(client, "google")
    assert _loc(cb) == ("/login", {"error": "signup_closed"})
    # 이미 이어진 사람은 가입을 닫아도 들어온다.
    _fake(monkeypatch, "google", OA.Identity(provider="google", subject=f"g-{email}", email=email, email_verified=True))
    _, cb = await _sso(client, "google")
    assert _loc(cb)[1].get("login") == "google"


async def test_a_failed_or_cancelled_sign_in_says_so(client: AsyncClient, monkeypatch):
    await _provider("google")
    _fake(monkeypatch, "google", None)
    _, cb = await _sso(client, "google")
    assert _loc(cb) == ("/login", {"error": "sso_failed"})
    r = await client.get("/api/auth/google/start", follow_redirects=False)
    state = parse_qs(urlparse(r.headers["location"]).query)["state"][0]
    cb = await client.get("/api/auth/google/callback", params={"error": "access_denied", "state": state}, follow_redirects=False)
    assert _loc(cb) == ("/login", {"error": "sso_denied"})
    # 흐름 사이에 관리자가 로그인을 껐다.
    r = await client.get("/api/auth/google/start", follow_redirects=False)
    state = parse_qs(urlparse(r.headers["location"]).query)["state"][0]
    await _provider("google", login=False)
    cb = await client.get("/api/auth/google/callback", params={"code": "c", "state": state}, follow_redirects=False)
    assert _loc(cb) == ("/login", {"error": "sso_unavailable"})


# ── 계정 설정의 로그인 방법 ─────────────────────────────────────────────


async def test_login_methods_can_be_added_and_removed_but_never_the_last(client: AsyncClient, monkeypatch):
    await _provider("google")
    await _provider("kakao")
    user, tok = await signup(client)
    ids = (await client.get("/api/auth/identities", headers=auth(tok))).json()
    assert ids["has_password"] is True and ids["items"] == []
    assert {(p["id"], p["linked"]) for p in ids["providers"]} == {("google", False), ("kakao", False)}
    sub = f"g-link-{uuid.uuid4().hex[:6]}"
    _fake(monkeypatch, "google", OA.Identity(provider="google", subject=sub, email="other@gmail.com", email_verified=True))
    r = await client.post("/api/auth/identities/google/start", json={"next": "/app/settings?tab=account"}, headers=auth(tok))
    state = parse_qs(urlparse(r.json()["url"]).query)["state"][0]
    cb = await client.get("/api/auth/google/callback", params={"code": "c", "state": state}, follow_redirects=False)
    assert _loc(cb) == ("/app/settings", {"tab": "account", "linked": "google"})
    ids = (await client.get("/api/auth/identities", headers=auth(tok))).json()
    assert [(i["provider"], i["email"]) for i in ids["items"]] == [("google", "other@gmail.com")]
    # 그 Google 계정으로 이 계정에 들어온다(주소가 달라도).
    _, cb = await _sso(client, "google")
    assert _loc(cb)[1].get("login") == "google"

    # 이미 다른 사람에게 이어진 계정은 잇지 못한다.
    other, otok = await signup(client)
    r = await client.post("/api/auth/identities/google/start", json={}, headers=auth(otok))
    state = parse_qs(urlparse(r.json()["url"]).query)["state"][0]
    cb = await client.get("/api/auth/google/callback", params={"code": "c", "state": state}, follow_redirects=False)
    assert _loc(cb)[1].get("error") == "identity_taken"

    # 떼기. 비밀번호가 있으니 뗄 수 있다.
    iid = ids["items"][0]["id"]
    assert (await client.delete(f"/api/auth/identities/{iid}", headers=auth(tok))).status_code == 200
    # 비밀번호 없이 카카오 하나로만 들어오는 사람은 그 하나를 뗄 수 없다.
    ksub = f"k-only-{uuid.uuid4().hex[:6]}"
    _fake(monkeypatch, "kakao", OA.Identity(provider="kakao", subject=ksub, email=f"{ksub}@kakao.com", email_verified=True))
    _, cb = await _sso(client, "kakao")
    r = await client.post("/api/auth/refresh")
    ktok = r.json()["access_token"]
    ids = (await client.get("/api/auth/identities", headers=auth(ktok))).json()
    assert ids["has_password"] is False and len(ids["items"]) == 1
    r = await client.delete(f"/api/auth/identities/{ids['items'][0]['id']}", headers=auth(ktok))
    assert r.status_code == 409 and r.json()["error"]["code"] == "last_login_method"
    # 비밀번호를 만들면 뗄 수 있다.
    r = await client.post("/api/users/me/password", json={"current_password": "", "new_password": "correct-horse-7"}, headers=auth(ktok))
    assert r.status_code == 200, r.text
    ktok = r.json().get("access_token") or ktok
    assert (await client.delete(f"/api/auth/identities/{ids['items'][0]['id']}", headers=auth(ktok))).status_code == 200


# ── id_token ────────────────────────────────────────────────────────────


async def test_the_id_token_is_verified_against_the_providers_keys(monkeypatch):
    import jwt
    from cryptography.hazmat.primitives.asymmetric import rsa

    from blackmoa.core.errors import ValidationFailed
    from blackmoa.services.oauth import idtoken

    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    jwk = json.loads(jwt.algorithms.RSAAlgorithm.to_jwk(key.public_key()))
    jwk["kid"] = "k1"

    class R:
        def json(self):
            return {"keys": [jwk]}

    async def fake_request(method, url, **kw):
        return R()

    monkeypatch.setattr(idtoken, "request", fake_request)
    idtoken._JWKS.clear()
    now = int(time.time())
    good = {"iss": "https://accounts.google.com", "aud": "cid", "sub": "123", "iat": now, "exp": now + 600, "nonce": "n1"}

    def tok(claims, signer=key, kid="k1"):
        return jwt.encode(claims, signer, algorithm="RS256", headers={"kid": kid})

    args = {"jwks_url": "https://jwks", "issuers": ("https://accounts.google.com", "accounts.google.com"), "audience": "cid"}
    assert (await idtoken.verify(tok(good), nonce="n1", **args))["sub"] == "123"
    bad_cases = [
        ({**good, "aud": "someone-else"}, "n1", key),
        ({**good, "iss": "https://evil.example"}, "n1", key),
        ({**good, "exp": now - 3600}, "n1", key),
        (good, "n2", key),                                       # nonce 가 다르다
        (good, "n1", rsa.generate_private_key(public_exponent=65537, key_size=2048)),   # 다른 키로 서명했다
    ]
    for claims, nonce, signer in bad_cases:
        try:
            await idtoken.verify(tok(claims, signer), nonce=nonce, **args)
        except ValidationFailed as e:
            assert e.code == "id_token_invalid"
        else:
            raise AssertionError(f"accepted {claims} / {nonce}")


# ── 관리자 [연결] ───────────────────────────────────────────────────────


async def _admin(client: AsyncClient) -> str:
    user, _ = await signup(client)
    async with session_scope() as db:
        (await db.get(User, uuid.UUID(user["id"]))).role = "admin"
        await db.commit()
    r = await client.post("/api/auth/login", json={"email": user["email"], "password": "correct-horse-9"})
    return r.json()["access_token"]


async def test_the_admin_fills_in_the_keys_and_it_works(client: AsyncClient):
    tok = await _admin(client)
    _, utok = await signup(client)
    assert (await client.get("/api/admin/connections", headers=auth(utok))).status_code == 403
    j = (await client.get("/api/admin/connections", headers=auth(tok))).json()
    g = next(p for p in j["providers"] if p["id"] == "google")
    k = next(p for p in j["providers"] if p["id"] == "kakao")
    assert g["enabled"] is False and g["ready"] is False and set(g["missing"]) == {"client_id", "client_secret"}
    # 콘솔에 넣을 주소를 그대로 알려 준다.
    assert g["redirect_uris"] == {"login": "http://testserver/api/auth/google/callback",
                                  "connect": "http://testserver/api/integrations/google/callback"}
    assert k["missing"] == ["client_id"], "카카오의 Client Secret 은 콘솔에서 켰을 때만 필요하다"
    assert [f["key"] for f in k["fields"]] == ["client_id", "client_secret", "oidc", "email"]
    # 키 없이 켜지 않는다.
    r = await client.put("/api/admin/connections/google", json={"enabled": True}, headers=auth(tok))
    assert r.status_code == 422 and r.json()["error"]["code"] == "connection_missing_fields"
    # 키를 넣고 켠다 — 비밀은 가려서 돌려준다.
    r = await client.put("/api/admin/connections/google", json={"enabled": True, "values": {
        "client_id": " 123.apps.googleusercontent.com ", "client_secret": "GOCSPX-secret-value"}}, headers=auth(tok))
    assert r.status_code == 200, r.text
    g = r.json()
    sec = next(f for f in g["fields"] if f["key"] == "client_secret")
    assert g["ready"] and g["login_ready"] and sec["has_value"] and "GOCSPX-secret-value" not in json.dumps(g)
    assert next(f for f in g["fields"] if f["key"] == "client_id")["value"] == "123.apps.googleusercontent.com"
    assert [p["id"] for p in (await client.get("/api/auth/status")).json()["sso"]] == ["google"]
    # 비밀을 비워 보내면 그대로 둔다.
    r = await client.put("/api/admin/connections/google", json={"values": {"client_secret": ""}}, headers=auth(tok))
    assert next(f for f in r.json()["fields"] if f["key"] == "client_secret")["has_value"] is True
    # 필수 칸은 지우지 못한다. 모르는 칸·기능은 받지 않는다.
    r = await client.put("/api/admin/connections/google", json={"clear": ["client_secret"]}, headers=auth(tok))
    assert r.status_code == 422 and r.json()["error"]["code"] == "field_required"
    r = await client.put("/api/admin/connections/google", json={"values": {"nope": "x"}}, headers=auth(tok))
    assert r.json()["error"]["code"] == "unknown_field"
    r = await client.put("/api/admin/connections/google", json={"features": ["gmail_read", "teleport"]}, headers=auth(tok))
    assert r.json()["error"]["code"] == "unknown_feature"
    # 사용자에게 보이는 연동 목록이 관리자가 준 기능을 따른다.
    await client.put("/api/admin/connections/google", json={"features": ["calendar_read", "calendar_write"]}, headers=auth(tok))
    prov = (await client.get("/api/integrations", headers=auth(utok))).json()["providers"]
    assert [(p["id"], [c["id"] for c in p["capabilities"]]) for p in prov] == [("google", ["calendar_read", "calendar_write"])]
    # 끄면서라면(또는 꺼 둔 뒤에는) 키를 지울 수 있다 — 앱을 바꾸거나 거둘 때.
    r = await client.put("/api/admin/connections/google", json={"enabled": False, "clear": ["client_id", "client_secret"]}, headers=auth(tok))
    assert r.status_code == 200 and r.json()["enabled"] is False and set(r.json()["missing"]) == {"client_id", "client_secret"}


async def test_taking_a_feature_away_turns_it_off_for_everyone(client: AsyncClient):
    tok = await _admin(client)
    await _provider("google")
    user, _ = await signup(client)
    async with session_scope() as db:
        c = Connection(owner_id=uuid.UUID(user["id"]), provider="google", account_label="a@b.c",
                       capabilities=["calendar_read", "contacts"], scopes=[], access_token_enc="", status="active")
        db.add(c)
        await db.commit()
        cid = c.id
    await client.put("/api/admin/connections/google", json={"features": ["calendar_read"]}, headers=auth(tok))
    async with session_scope() as db:
        assert (await db.get(Connection, cid)).capabilities == ["calendar_read"]
    j = (await client.get("/api/admin/connections", headers=auth(tok))).json()
    assert next(p for p in j["providers"] if p["id"] == "google")["stats"]["connections"] >= 1


async def test_check_reads_the_providers_answer(client: AsyncClient, monkeypatch):
    """[설정 확인] 은 가짜 코드로 토큰 창구에 묻는다. "그런 코드 없음" 이면 앱 키는 맞은 것이다."""
    from blackmoa.providers.http import ProviderHTTPError
    from blackmoa.services.oauth import base

    tok = await _admin(client)
    answers: list[tuple[int, dict]] = []
    sent: list[dict] = []

    async def fake_request(method, url, **kw):
        sent.append({"url": url, **kw})
        status, body = answers.pop(0)
        raise ProviderHTTPError(status, json.dumps(body))

    monkeypatch.setattr(base, "request", fake_request)
    r = (await client.post("/api/admin/connections/google/check", headers=auth(tok))).json()
    assert r["ok"] is False and r["code"] == "missing" and not sent
    await client.put("/api/admin/connections/google", json={"values": {"client_id": "cid", "client_secret": "sec"}}, headers=auth(tok))
    cases = [
        ("google", (400, {"error": "invalid_grant", "error_description": "Malformed auth code."}), True, "ok"),
        ("google", (401, {"error": "invalid_client", "error_description": "The OAuth client was not found."}), False, "invalid_client"),
        ("google", (400, {"error": "redirect_uri_mismatch"}), False, "redirect_uri"),
    ]
    await client.put("/api/admin/connections/kakao", json={"values": {"client_id": "rest-key", "client_secret": "ks"}}, headers=auth(tok))
    cases += [
        ("kakao", (400, {"error": "invalid_grant", "error_code": "KOE320"}), True, "ok"),
        ("kakao", (401, {"error": "invalid_client", "error_code": "KOE010"}), False, "invalid_secret"),
        ("kakao", (401, {"error": "invalid_client", "error_code": "KOE101"}), False, "invalid_client"),
        ("kakao", (400, {"error": "invalid_request", "error_code": "KOE004"}), False, "login_disabled"),
    ]
    for pid, answer, ok, code in cases:
        answers.append(answer)
        r = (await client.post(f"/api/admin/connections/{pid}/check", headers=auth(tok))).json()
        assert (r["ok"], r["code"]) == (ok, code), (pid, answer, r)
    # 확인은 켜기 전에도 할 수 있고, 저장한 키를 보낸다.
    assert sent[-1]["url"] == "https://kauth.kakao.com/oauth/token" and sent[-1]["data"]["client_id"] == "rest-key"
    assert sent[-1]["data"]["client_secret"] == "ks"


# ── 카카오 데이터 ──────────────────────────────────────────────────────


class _Resp:
    def __init__(self, body: dict):
        self._b = body

    def json(self):
        return self._b


async def _kakao_conn(owner_id: str, caps: list[str]) -> uuid.UUID:
    async with session_scope() as db:
        c = Connection(owner_id=uuid.UUID(owner_id), provider="kakao", account_label="카톡이름", capabilities=caps,
                       scopes=["profile_nickname", "talk_calendar", "talk_message"], access_token_enc="", status="active",
                       token_expires_at=datetime.now(UTC) + timedelta(hours=1))
        db.add(c)
        await db.commit()
        return c.id


async def test_kakao_talk_calendar_is_read_in_31_day_windows(client: AsyncClient, monkeypatch):
    from blackmoa.services import kakao as K

    await _provider("kakao")
    user, tok = await signup(client)
    cid = await _kakao_conn(user["id"], ["calendar_read"])
    calls: list[dict] = []
    soon = (datetime.now(UTC) + timedelta(days=2)).replace(hour=5, minute=0, second=0, microsecond=0)

    async def fake_token(db, conn):
        return "kakao-at"

    async def fake_request(method, url, **kw):
        calls.append({"method": method, "url": url, **kw})
        if len(calls) == 1:
            return _Resp({"events": [{"id": "e1", "title": "톡 회의", "time": {"start_at": soon.strftime("%Y-%m-%dT%H:%M:%SZ"),
                                                                            "end_at": (soon + timedelta(hours=1)).strftime("%Y-%m-%dT%H:%M:%SZ"),
                                                                            "all_day": False}}],
                          "has_next_events": True, "after_url": "https://kapi.kakao.com/v2/api/calendar/events?cursor=2"})
        if len(calls) == 2:
            return _Resp({"events": [{"id": "e2", "title": "종일", "time": {"start_at": soon.strftime("%Y-%m-%dT00:00:00Z"),
                                                                          "end_at": (soon + timedelta(days=1)).strftime("%Y-%m-%dT00:00:00Z"),
                                                                          "all_day": True}},
                                     {"id": "e1", "title": "중복", "time": {"start_at": soon.isoformat()}}],
                          "has_next_events": False})
        return _Resp({"events": [], "has_next_events": False})

    monkeypatch.setattr("blackmoa.services.connections.access_token", fake_token)
    monkeypatch.setattr(K, "request", fake_request)
    async with session_scope() as db:
        n = await K.sync_calendar(db, await db.get(Connection, cid))
        await db.commit()
    assert n == 2
    # 첫 창은 질의를, 다음 쪽은 받은 after_url 을 그대로 쓴다. 지난 7일~앞으로 60일은 31일 창 세 개다.
    assert calls[0]["params"]["from"] and calls[0]["headers"]["Authorization"] == "Bearer kakao-at"
    assert calls[1]["url"].endswith("cursor=2") and calls[1]["params"] is None
    assert len(calls) == 4
    ev = (await client.get("/api/schedule", params={"from": (soon - timedelta(days=1)).date().isoformat(),
                                                    "to": (soon + timedelta(days=2)).date().isoformat()}, headers=auth(tok))).json()["events"]
    assert {e["title"]: e["source"] for e in ev} == {"톡 회의": "kakao", "종일": "kakao"}
    allday = next(e for e in ev if e["title"] == "종일")
    # 종일 일정은 주인의 날짜 그대로다(UTC 자정이 한국 오전 9시가 되지 않게).
    assert allday["all_day"] and allday["start_date"] == soon.date().isoformat() and allday["end_date"] == soon.date().isoformat()


async def test_kakao_events_snap_to_five_minutes(monkeypatch):
    from blackmoa.services import kakao as K

    sent: dict = {}

    async def fake_token(db, conn):
        return "at"

    async def fake_request(method, url, **kw):
        sent.update({"url": url, **kw})
        return _Resp({"event_id": "kev"})

    monkeypatch.setattr("blackmoa.services.connections.access_token", fake_token)
    monkeypatch.setattr(K, "request", fake_request)
    s = datetime(2026, 10, 1, 5, 3, tzinfo=UTC)
    r = await K.create_event(None, None, summary="김민수님과의 미팅", start=s, end=s + timedelta(minutes=45), location="강남역")
    ev = json.loads(sent["data"]["event"])
    assert r == {"id": "kev", "html_link": ""} and sent["url"].endswith("/v2/api/calendar/create/event")
    assert ev["time"]["start_at"] == "2026-10-01T05:00:00Z" and ev["time"]["end_at"] == "2026-10-01T05:50:00Z"
    assert ev["title"] == "김민수님과의 미팅" and ev["location"] == {"name": "강남역"} and sent["data"]["calendar_id"] == "primary"


async def test_kakao_talk_as_a_notification_channel(client: AsyncClient, monkeypatch):
    from blackmoa.services import kakao as K

    await _provider("kakao")
    user, tok = await signup(client)
    # 연결 없이는, 또는 메시지 권한을 켜지 않았으면 만들지 않는다.
    r = await client.post("/api/notifications/channels", json={"kind": "kakao", "config": {"connection_id": str(uuid.uuid4())}},
                          headers=auth(tok))
    assert r.status_code == 422 and r.json()["error"]["code"] == "kakao_not_connected"
    cid = await _kakao_conn(user["id"], ["calendar_read"])
    r = await client.post("/api/notifications/channels", json={"kind": "kakao", "config": {"connection_id": str(cid)}}, headers=auth(tok))
    assert r.json()["error"]["code"] == "kakao_message_off"
    async with session_scope() as db:
        (await db.get(Connection, cid)).capabilities = ["talk_message"]
        await db.commit()
    r = await client.post("/api/notifications/channels", json={"kind": "kakao", "config": {"connection_id": str(cid)}, "label": "카카오톡"},
                          headers=auth(tok))
    assert r.status_code == 201, r.text
    ch = r.json()
    # 받는 사람은 늘 연결한 본인이라 따로 인증하지 않는다.
    assert ch["verified_at"]
    assert ch["config"] == {"connection_id": str(cid), "account": "카톡이름"}
    # 남의 연결로는 만들 수 없다.
    _, otok = await signup(client)
    r = await client.post("/api/notifications/channels", json={"kind": "kakao", "config": {"connection_id": str(cid)}}, headers=auth(otok))
    assert r.json()["error"]["code"] == "kakao_not_connected"

    sent: list[dict] = []

    async def fake_token(db, conn):
        return "at"

    async def fake_request(method, url, **kw):
        sent.append({"url": url, **kw})
        return _Resp({"result_code": 0})

    monkeypatch.setattr("blackmoa.services.connections.access_token", fake_token)
    monkeypatch.setattr(K, "request", fake_request)
    r = await client.post(f"/api/notifications/channels/{ch['id']}/test", headers=auth(tok))
    assert r.status_code == 200, r.text
    tpl = json.loads(sent[0]["data"]["template_object"])
    assert sent[0]["url"].endswith("/v2/api/talk/memo/default/send")
    assert tpl["object_type"] == "text" and tpl["link"]["web_url"] == "http://testserver/app/notifications" and len(tpl["text"]) <= 200

    # 알림 하나가 그대로 카톡으로 — 여는 곳은 그 알림의 화면이다.
    from blackmoa.services import notifications as NT
    sent.clear()
    async with session_scope() as db:
        await NT.send_via(db, "kakao", {"connection_id": str(cid)}, subject="[비서] 김민수님의 미팅 요청", text="", html="",
                          payload={"event": "meeting_request", "inbox_item_id": "abc", "text": "다음 주 화요일 어때요? " * 20},
                          owner_id=uuid.UUID(user["id"]))
    tpl = json.loads(sent[0]["data"]["template_object"])
    assert tpl["link"]["web_url"] == "http://testserver/app/inbox?item=abc" and tpl["text"].startswith("[비서] 김민수님의 미팅 요청")
    assert len(tpl["text"]) <= 200 and tpl["button_title"] == "인박스 열기"

    # 연동을 끊으면 채널도 함께 사라진다.
    async with session_scope() as db:
        from blackmoa.services import connections as CN
        await CN.remove(db, await db.get(Connection, cid))
        await db.commit()
    chans = (await client.get("/api/notifications/channels", headers=auth(tok))).json()["items"]
    assert all(c["kind"] != "kakao" for c in chans)


async def test_disconnecting_kakao_revokes_only_the_data_consent(client: AsyncClient, monkeypatch):
    from blackmoa.core.security import encrypt
    from blackmoa.services import connections as CN
    from blackmoa.services.oauth import kakao as KO

    await _provider("kakao")
    user, _ = await signup(client)
    cid = await _kakao_conn(user["id"], ["calendar_read", "talk_message"])
    async with session_scope() as db:
        (await db.get(Connection, cid)).access_token_enc = encrypt("live-at")
        await db.commit()
    sent: list[dict] = []

    async def fake_request(method, url, **kw):
        sent.append({"url": url, **kw})
        return _Resp({"id": 1})

    monkeypatch.setattr(KO, "request", fake_request)
    async with session_scope() as db:
        await CN.remove(db, await db.get(Connection, cid))
        await db.commit()
    assert sent[0]["url"] == "https://kapi.kakao.com/v2/user/revoke/scopes"
    assert sorted(json.loads(sent[0]["data"]["scopes"])) == ["talk_calendar", "talk_message"]
    assert sent[0]["headers"]["Authorization"] == "Bearer live-at"
    async with session_scope() as db:
        assert await db.get(Connection, cid) is None


async def test_turning_a_provider_off_stops_every_data_path(client: AsyncClient):
    from blackmoa.core.errors import ServiceUnavailable
    from blackmoa.services import connections as CN

    await _provider("kakao")
    user, _ = await signup(client)
    cid = await _kakao_conn(user["id"], ["calendar_read", "talk_message"])
    await _provider("kakao", enabled=False)
    async with session_scope() as db:
        c = await db.get(Connection, cid)
        try:
            await CN.access_token(db, c)
        except ServiceUnavailable as e:
            assert e.code == "kakao_not_configured"
        else:
            raise AssertionError("a turned-off provider handed out a token")
        # 가져오기는 조용히 건너뛴다 — 사용자 연결의 오류로 적지 않는다.
        assert await CN.sync_all(db, c) == {} and c.status == "active" and not c.error


async def test_one_connection_per_provider_and_a_new_account_starts_clean(client: AsyncClient, monkeypatch):
    """같은 계정으로 다시 이으면 권한이 쌓이고, 다른 계정으로 이으면 앞 계정에서 가져온 것은 지운다."""
    from blackmoa.models import IntegrationEvent

    await _provider("google")
    user, tok = await signup(client)
    who = {"sub": "acct-a", "email": "a@gmail.com", "scope": "openid email https://www.googleapis.com/auth/calendar.readonly"}
    g = OA.PROVIDERS["google"]

    async def exchange(db, *, code, purpose):
        return {"access_token": "at", "refresh_token": "rt", "expires_in": 3600, "scope": who["scope"]}

    async def identity(db, toks, *, nonce):
        return OA.Identity(provider="google", subject=who["sub"], email=who["email"], email_verified=True)

    monkeypatch.setattr(g, "exchange", exchange)
    monkeypatch.setattr(g, "identity", identity)

    async def connect(caps: list[str]):
        r = await client.post("/api/integrations/google/start", json={"capabilities": caps}, headers=auth(tok))
        state = parse_qs(urlparse(r.json()["url"]).query)["state"][0]
        return await client.get("/api/integrations/google/callback", params={"code": "c", "state": state}, follow_redirects=False)

    cb = await connect(["calendar_read"])
    assert _loc(cb)[1].get("connected") == "google"
    async with session_scope() as db:
        c = (await db.execute(select(Connection).where(Connection.owner_id == uuid.UUID(user["id"])))).scalars().one()
        db.add(IntegrationEvent(owner_id=c.owner_id, connection_id=c.id, ext_id="a1", title="A의 일정",
                                start_at=datetime.now(UTC), end_at=datetime.now(UTC) + timedelta(hours=1)))
        await db.commit()
        cid = c.id
    # 같은 계정: 연락처 권한을 더 받았다 — 한 줄에 쌓인다.
    who["scope"] = "openid email https://www.googleapis.com/auth/contacts.readonly"
    await connect(["contacts"])
    async with session_scope() as db:
        rows = (await db.execute(select(Connection).where(Connection.owner_id == uuid.UUID(user["id"])))).scalars().all()
        assert [r.id for r in rows] == [cid] and rows[0].capabilities == ["calendar_read", "contacts"]
        assert (await db.execute(select(IntegrationEvent).where(IntegrationEvent.connection_id == cid))).first() is not None
    # 다른 계정: 앞 계정의 일정은 지우고, 앞 계정에서 받은 권한도 넘겨받지 않는다.
    who.update({"sub": "acct-b", "email": "b@gmail.com", "scope": "openid email https://www.googleapis.com/auth/calendar.readonly"})
    cb = await connect(["calendar_read"])
    # 동의 화면에서 연락처를 뺐다고 알린다 — 이 계정에서는 연락처 권한을 받지 않았다.
    assert _loc(cb)[1].get("partial") == "contacts"
    async with session_scope() as db:
        rows = (await db.execute(select(Connection).where(Connection.owner_id == uuid.UUID(user["id"])))).scalars().all()
        assert [r.id for r in rows] == [cid] and rows[0].account_label == "b@gmail.com" and rows[0].capabilities == ["calendar_read"]
        assert (await db.execute(select(IntegrationEvent).where(IntegrationEvent.connection_id == cid))).first() is None
