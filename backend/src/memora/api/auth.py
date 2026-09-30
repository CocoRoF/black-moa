from __future__ import annotations

import secrets
import uuid
from typing import Annotated

from fastapi import APIRouter, Cookie, Request, Response
from fastapi.responses import RedirectResponse
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy import select

from memora.config import get_settings
from memora.core import visibility as VIS
from memora.core.deps import DB, CurrentUser, client_ip
from memora.core.errors import (
    Conflict,
    Forbidden,
    MemoraError,
    ServiceUnavailable,
    Unauthorized,
    ValidationFailed,
)
from memora.core.ratelimit import limiter
from memora.core.security import sign_state, verify_state
from memora.models import AuthIdentity, User
from memora.services import accounts as A
from memora.services import audit
from memora.services import legal as LEGAL
from memora.services import oauth as OA
from memora.services import settings as S
from memora.services import voice as VOICE
from memora.services.companies import switch as CO
from memora.services.oauth import state as OST

router = APIRouter(prefix="/api/auth", tags=["auth"])
COOKIE = "memora_refresh"
# The name before the 2026-09-09 rename. Read as a fallback so the rename does not sign
# everyone out; a session that presents it is reissued under the new name and the old one
# is cleared on the way out.
LEGACY_COOKIE = "mfsg_refresh"


def _set_refresh(resp: Response, raw: str) -> None:
    s = get_settings()
    resp.set_cookie(COOKIE, raw, max_age=s.refresh_token_days * 86400, httponly=True, secure=s.public_url.startswith("https"),
                    samesite="lax", path="/api/auth")


def _clear_refresh(resp: Response) -> None:
    resp.delete_cookie(COOKIE, path="/api/auth")
    resp.delete_cookie(LEGACY_COOKIE, path="/api/auth")


def _user_out(u) -> dict:
    return {"id": str(u.id), "email": u.email, "display_name": u.display_name, "nickname": u.nickname or "",
            "name_confirmed": bool(u.name_confirmed_at), "role": u.role, "locale": u.locale,
            "timezone": u.timezone, "avatar_url": u.avatar_url, "is_super": bool(u.is_super), "plan_id": str(u.plan_id) if u.plan_id else None,
            "onboarding_state": u.onboarding_state or {}, "email_verified": bool(u.email_verified_at),
            "page_indexable": bool(getattr(u, "page_indexable", True)),
            "network_public": VIS.normalize(getattr(u, "network_public", "public")),
            # 동의한 약관의 판 (plan/73). 지금 판(/status 의 legal_version)과 다르면 앱이 한 번 동의를 받는다.
            "terms_version": getattr(u, "terms_version", None),
            "created_at": u.created_at.isoformat() if u.created_at else None}


class SignupIn(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8, max_length=200)
    display_name: str = Field(min_length=1, max_length=120)
    nickname: str | None = Field(default=None, max_length=60)
    invite_code: str | None = None
    bootstrap_token: str | None = Field(default=None, max_length=512)
    #: 만 14세 이상이며 이용약관에 동의하고 개인정보 처리방침을 확인했다 (plan/73). 없으면 가입하지 않는다.
    agree_terms: bool = False


class LoginIn(BaseModel):
    email: EmailStr
    password: str


@router.get("/status")
async def status(db: DB):
    n = await A.user_count(db)
    # ``bootstrap_needed`` only says "no accounts yet". The token is a separate,
    # https-production-only requirement, so the signup form can keep a local /
    # http install zero-config instead of demanding a value the server ignores.
    bootstrap_token_required = n == 0 and get_settings().public_url.lower().startswith("https://")
    return {"bootstrap_needed": n == 0, "bootstrap_token_required": bootstrap_token_required,
            "signup_mode": await S.get(db, "signup.mode"),
            # 로그인에 쓰기가 켜진 연결 (plan/59) — 로그인·가입 화면의 버튼.
            "sso": [{"id": p.id, "label": p.label} for p in OA.PROVIDERS.values() if await p.login_ready(db)],
            "service_name": await S.get(db, "branding.service_name"), "tagline": await S.get(db, "branding.tagline"),
            # The console needs to know before the click, not from the 403 after it.
            "verify_before_agent": bool(await S.get(db, "signup.verify_before_agent")),
            "mail_configured": bool(await S.get(db, "smtp.host")) and bool(await S.get(db, "smtp.from")),
            # 음성을 쓰는가 (plan/67) — 웹과 PC 앱이 마이크·소리 단추와 그 설정을 보일지 여기서 정한다.
            "voice": await VOICE.availability(db),
            # 기업 기능을 쓰는가 (plan/71) — 기업정보 탭·기업 페이지·소속·회사 인증을 보일지.
            "companies": await CO.enabled(db),
            # 지금 동의받는 약관의 판 (plan/73). 사용자의 terms_version 과 다르면 앱이 한 번 받는다.
            "legal_version": await LEGAL.version(db)}


def _require_terms(agreed: bool) -> None:
    """가입은 만 14세 이상 확인과 약관 동의가 있어야 한다 (plan/73). 14세 미만은 법정대리인 동의를 받아야 하는데
    그 절차를 두지 않으므로 받지 않는다(개인정보 보호법 제22조의2)."""
    if not agreed:
        raise ValidationFailed("you must be 14 or older and agree to the terms", code="terms_required")


async def _record_terms(db, user: User, *, ip: str) -> None:
    """어느 판에 언제 동의했는지 남긴다. 감사 기록에도 — 다툼이 생겼을 때 증빙이다."""
    v = await LEGAL.version(db)
    A.record_terms(user, v)
    audit.record(db, "terms_agreed", actor_id=user.id, ip=ip, meta={"version": v})


@router.post("/signup")
async def signup(body: SignupIn, request: Request, response: Response, db: DB):
    ip = client_ip(request)
    limiter.check(f"signup:{ip}", 5, 3600)
    _require_terms(body.agree_terms)
    user = await A.signup(db, email=body.email, password=body.password, display_name=body.display_name,
                          nickname=body.nickname, invite_code=body.invite_code,
                          bootstrap_token=body.bootstrap_token, ip=ip, ua=request.headers.get("user-agent", ""))
    await _record_terms(db, user, ip=ip)
    access, raw, _ = await A.issue_session(db, user, ip=ip, ua=request.headers.get("user-agent", ""))
    await db.commit()
    _set_refresh(response, raw)
    return {"access_token": access, "user": _user_out(user)}


@router.post("/login")
async def login(body: LoginIn, request: Request, response: Response, db: DB):
    ip = client_ip(request)
    limiter.check(f"login:{ip}", 10, 60)
    try:
        user = await A.authenticate(db, email=body.email, password=body.password, ip=ip, ua=request.headers.get("user-agent", ""))
    except Unauthorized:
        await db.commit()
        raise
    access, raw, _ = await A.issue_session(db, user, ip=ip, ua=request.headers.get("user-agent", ""))
    await db.commit()
    _set_refresh(response, raw)
    return {"access_token": access, "user": _user_out(user)}


@router.post("/refresh")
async def refresh(request: Request, response: Response, db: DB,
                 memora_refresh: Annotated[str | None, Cookie()] = None,
                 mfsg_refresh: Annotated[str | None, Cookie()] = None):
    token = memora_refresh or mfsg_refresh
    if not token:
        raise Unauthorized("no refresh cookie", code="no_refresh")
    try:
        access, raw, user = await A.refresh(db, token, ip=client_ip(request), ua=request.headers.get("user-agent", ""))
    except Unauthorized:
        await db.commit()
        _clear_refresh(response)
        raise
    await db.commit()
    _set_refresh(response, raw)
    return {"access_token": access, "user": _user_out(user)}


@router.post("/logout")
async def logout(response: Response, db: DB,
                memora_refresh: Annotated[str | None, Cookie()] = None,
                mfsg_refresh: Annotated[str | None, Cookie()] = None):
    await A.logout(db, memora_refresh or mfsg_refresh)
    await db.commit()
    _clear_refresh(response)
    return {"ok": True}


@router.post("/logout-all")
async def logout_all(user: CurrentUser, response: Response, db: DB):
    await A.logout(db, None, all_devices=True, user_id=user.id)
    await db.commit()
    _clear_refresh(response)
    return {"ok": True}


@router.get("/me")
async def me(user: CurrentUser):
    return _user_out(user)


class ForgotIn(BaseModel):
    email: EmailStr


class ResetIn(BaseModel):
    token: str
    password: str = Field(min_length=8)


@router.post("/password/forgot")
async def forgot(body: ForgotIn, request: Request, db: DB):
    limiter.check(f"forgot:{client_ip(request)}", 5, 3600)
    res = await A.start_password_reset(db, body.email)
    if res:
        user, raw = res
        from memora.services import jobs as J
        from memora.services.emails import password_reset
        link = f"{get_settings().public_url.rstrip('/')}/reset-password?token={raw}"
        subject, text, html = password_reset(link=link)
        await J.enqueue(db, "mail.send", {"to": user.email, "subject": subject, "text": text, "html": html}, priority=1)
    await db.commit()
    return {"ok": True}


@router.post("/password/reset")
async def reset(body: ResetIn, db: DB):
    await A.finish_password_reset(db, body.token, body.password)
    await db.commit()
    return {"ok": True}


# ── 연결로 로그인 (SSO, plan/59) ──────────────────────────────────────────
# 주소는 공급자마다 같은 모양이다: /api/auth/{provider}/start · /api/auth/{provider}/callback.
# 콜백 주소는 로그인·가입과 "계정 설정에서 로그인 방법 더하기" 가 함께 쓴다 — 공급자 콘솔에 하나만 등록한다.

def _base() -> str:
    return get_settings().public_url.rstrip("/")


def _to(path: str, **params: str) -> RedirectResponse:
    return RedirectResponse(f"{_base()}{OST.join(path, **params)}", status_code=302)


@router.get("/{provider}/start")
async def sso_start(provider: str, request: Request, db: DB, next: str = "/app", invite: str | None = None,
                    agree: bool = False):
    """공급자의 로그인 화면으로 보낸다. 초대제면 입력한 초대 코드를 흐름에 싣는다. 가입 화면에서 약관에 동의하고
    눌렀으면(``agree``) 그것도 싣는다 — 새 계정이 만들어지면 동의를 남긴다(plan/73)."""
    p = OA.PROVIDERS.get(provider)
    if p is None or not await p.login_ready(db):
        return _to("/login", error="sso_unavailable")
    limiter.check(f"sso:{client_ip(request)}", 30, 600)
    resp = RedirectResponse("/", status_code=302)
    state, nonce = OST.begin(resp, provider=provider, purpose="login", next=OST.safe_next(next),
                             invite=(invite or "").strip()[:64] or None, agree=True if agree else None)
    resp.headers["location"] = await p.authorize_url(db, purpose="login", scopes=p.scopes_for([], login=True),
                                                     state=state, nonce=nonce)
    return resp


@router.get("/{provider}/callback")
async def sso_callback(provider: str, request: Request, db: DB, code: str | None = None, state: str | None = None,
                       error: str | None = None, memora_oauth: Annotated[str | None, Cookie()] = None):
    p = OA.PROVIDERS.get(provider)
    if p is None or not await p.login_ready(db):
        # 흐름을 시작한 사이에 관리자가 이 로그인을 껐다.
        resp = _to("/login", error="sso_unavailable")
        OST.clear(resp)
        return resp
    try:
        st = OST.finish(state or "", memora_oauth, provider=provider)
    except Unauthorized as e:
        resp = _to("/login", error=e.code if error is None else "sso_denied")
        OST.clear(resp)
        return resp
    if st.get("purpose") not in ("login", "link"):
        # 데이터 연동의 state 로 로그인하지 않는다.
        resp = _to("/login", error="bad_state")
        OST.clear(resp)
        return resp
    linking = st.get("purpose") == "link"
    back = OST.safe_next(st.get("next"), "/app/settings" if linking else "/app")
    fail_to = back if linking else "/login"
    if error or not code:
        # 사용자가 동의 화면에서 취소했다.
        resp = _to(fail_to, error="sso_denied")
        OST.clear(resp)
        return resp
    ip, ua = client_ip(request), request.headers.get("user-agent", "")
    try:
        tokens = await p.exchange(db, code=code, purpose="login")
        ident = await p.identity(db, tokens, nonce=st.get("nonce") or "")
        if linking:
            user = await db.get(User, uuid.UUID(str(st.get("uid"))))
            if user is None or user.status != "active":
                raise Unauthorized("user inactive", code="user_inactive")
            await A.link_identity(db, user, ident, ip=ip, ua=ua)
            await db.commit()
            resp = _to(back, linked=provider)
            OST.clear(resp)
            return resp
        user, outcome = await A.sso_login(db, ident, invite_code=st.get("invite"), ip=ip, ua=ua)
        if user is not None and outcome == "signup" and st.get("agree"):
            await _record_terms(db, user, ip=ip)
        if user is None:
            # 이메일을 주지 않은(또는 검증되지 않은) 계정 — 가입 마무리에서 이메일을 받는다.
            # 가입을 받지 않는 곳이면 마무리 화면까지 보내 놓고 거절하지 않는다.
            if await S.get(db, "signup.mode") == "closed" and await A.user_count(db) > 0:
                raise Forbidden("signup closed", code="signup_closed")
            pending = sign_state({"kind": "sso_pending", "provider": ident.provider, "subject": ident.subject,
                                  "name": ident.name[:120], "email_hint": ident.email or "", "raw": ident.raw,
                                  "invite": st.get("invite"), "next": back}, ttl_minutes=30)
            await db.rollback()
            resp = _to("/signup/complete", t=pending)
            OST.clear(resp)
            return resp
        access, raw, _ = await A.issue_session(db, user, ip=ip, ua=ua)
    except MemoraError as e:
        await db.rollback()
        resp = _to(fail_to, error=e.code)
        OST.clear(resp)
        return resp
    except Exception:  # noqa: BLE001
        await db.rollback()
        resp = _to(fail_to, error="sso_failed")
        OST.clear(resp)
        return resp
    audit.record(db, f"login_{provider}", actor_id=user.id, ip=ip, meta={"outcome": outcome})
    await db.commit()
    resp = _to(back, login=provider)
    _set_refresh(resp, raw)
    OST.clear(resp)
    return resp


@router.get("/sso/pending")
async def sso_pending(t: str, db: DB):
    """가입 마무리 화면이 채워 둘 것 — 어느 공급자의 누구인지, 초대 코드를 더 받아야 하는지."""
    st = verify_state(t)
    if st.get("kind") != "sso_pending":
        raise Unauthorized("invalid token", code="invalid_state")
    p = OA.PROVIDERS.get(st.get("provider") or "")
    mode = await S.get(db, "signup.mode")
    return {"provider": st.get("provider"), "provider_label": p.label if p else st.get("provider"),
            "name": st.get("name") or "", "email_hint": st.get("email_hint") or "",
            "signup_mode": mode, "invite_needed": mode == "invite" and not st.get("invite")}


class SsoCompleteIn(BaseModel):
    token: str = Field(max_length=4096)
    email: EmailStr
    display_name: str = Field(min_length=1, max_length=120)
    invite_code: str | None = Field(default=None, max_length=64)
    agree_terms: bool = False


@router.post("/sso/complete")
async def sso_complete(body: SsoCompleteIn, request: Request, response: Response, db: DB):
    """이메일을 주지 않은 공급자 계정으로 가입을 마친다. 일반 가입과 같은 규칙을 따른다 — 이메일은 인증 전이다."""
    ip, ua = client_ip(request), request.headers.get("user-agent", "")
    limiter.check(f"signup:{ip}", 5, 3600)
    st = verify_state(body.token)
    if st.get("kind") != "sso_pending" or st.get("provider") not in OA.PROVIDERS:
        raise Unauthorized("invalid token", code="invalid_state")
    ident = OA.Identity(provider=st["provider"], subject=str(st["subject"]), email=None, email_verified=False,
                        name=str(st.get("name") or ""), raw=dict(st.get("raw") or {}))
    taken = (await db.execute(select(AuthIdentity).where(AuthIdentity.provider == ident.provider,
                                                        AuthIdentity.subject == ident.subject))).first()
    if taken:
        raise Conflict("this account already has a Memora account", code="identity_taken")
    _require_terms(body.agree_terms)
    user = await A.signup(db, email=body.email, password=None, display_name=body.display_name,
                          invite_code=body.invite_code or st.get("invite"), identity=ident, ip=ip, ua=ua)
    await _record_terms(db, user, ip=ip)
    access, raw, _ = await A.issue_session(db, user, ip=ip, ua=ua)
    audit.record(db, f"login_{ident.provider}", actor_id=user.id, ip=ip, meta={"outcome": "signup_completed"})
    await db.commit()
    _set_refresh(response, raw)
    return {"access_token": access, "user": _user_out(user), "next": OST.safe_next(st.get("next"))}


class TermsIn(BaseModel):
    #: 동의하는 판 — 화면이 본 판과 지금 판이 다르면(그 사이에 바뀌었다) 다시 보여 준다.
    version: str = Field(max_length=32)
    agree: bool = False


@router.post("/terms")
async def agree_terms(body: TermsIn, request: Request, user: CurrentUser, db: DB):
    """앱에 들어올 때 받는 동의 (plan/73): 예전 계정, 로그인 화면에서 곧바로 만들어진 연결 계정, 약관의 판이 바뀐 뒤."""
    _require_terms(body.agree)
    if body.version != await LEGAL.version(db):
        raise Conflict("the terms changed; read them again", code="terms_changed")
    await _record_terms(db, user, ip=client_ip(request))
    await db.commit()
    return {"user": _user_out(user)}


# ── 로그인 방법 (계정 설정) ────────────────────────────────────────────────

@router.get("/identities")
async def identities(user: CurrentUser, db: DB):
    """이 계정에 들어오는 방법들: 비밀번호와 이어 둔 공급자 계정. 더할 수 있는 공급자도."""
    rows = (await db.execute(select(AuthIdentity).where(AuthIdentity.user_id == user.id)
                             .order_by(AuthIdentity.created_at))).scalars().all()
    linked = {r.provider for r in rows}
    providers = [{"id": p.id, "label": p.label, "linked": p.id in linked}
                 for p in OA.PROVIDERS.values() if p.id in linked or await p.login_ready(db)]
    return {"has_password": bool(user.password_hash), "providers": providers,
            "items": [{"id": str(r.id), "provider": r.provider, "label": OA.PROVIDERS[r.provider].label if r.provider in OA.PROVIDERS else r.provider,
                       "email": r.email, "name": (r.raw_profile or {}).get("name") or (r.raw_profile or {}).get("nickname") or "",
                       "created_at": r.created_at.isoformat() if r.created_at else None} for r in rows]}


class LinkStartIn(BaseModel):
    next: str = "/app/settings"


@router.post("/identities/{provider}/start")
async def identity_link_start(provider: str, body: LinkStartIn, user: CurrentUser, db: DB, response: Response):
    """로그인 방법으로 공급자 계정을 더한다 — 동의 화면 주소를 주고, 돌아오면 이 계정에 잇는다."""
    p = OA.get(provider)
    if not await p.login_ready(db):
        raise ValidationFailed("this sign-in is not available", code="sso_unavailable")
    state, nonce = OST.begin(response, provider=provider, purpose="link", uid=str(user.id), next=OST.safe_next(body.next, "/app/settings"))
    return {"url": await p.authorize_url(db, purpose="login", scopes=p.scopes_for([], login=True), state=state, nonce=nonce)}


@router.delete("/identities/{identity_id}")
async def identity_unlink(identity_id: uuid.UUID, user: CurrentUser, db: DB):
    await A.unlink_identity(db, user, identity_id)
    await db.commit()
    return {"ok": True}


class VerifyIn(BaseModel):
    code: str = Field(min_length=4, max_length=12)


@router.post("/email/verify")
async def verify_email(body: VerifyIn, db: DB, user: CurrentUser):
    if user.email_verified_at:
        return {"ok": True, "already": True}
    if not await A.verify_email_code(db, user, body.code):
        await db.commit()
        raise ValidationFailed("invalid or expired code", code="invalid_verification_code")
    await db.commit()
    return {"ok": True}


@router.post("/email/send-code")
async def send_verification(db: DB, user: CurrentUser, request: Request):
    limiter.check(f"verify:{user.id}", 3, 600)
    if user.email_verified_at:
        return {"ok": True, "already": True}
    # Both silent failures live here: no mail server at all, and a mail server that
    # rejects us. Sending inline turns each of them into an answer on this request.
    try:
        await A.start_email_verification(db, user, inline=True)
    except ServiceUnavailable:
        raise
    except Exception as e:  # noqa: BLE001 — SMTP failures are the user's answer, not a 500
        await db.rollback()
        raise ServiceUnavailable(f"could not send the verification mail: {str(e)[:200]}", code="mail_send_failed") from e
    await db.commit()
    return {"ok": True, "nonce": secrets.token_hex(2)}
