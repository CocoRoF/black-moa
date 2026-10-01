"""Accounts: signup, login, refresh rotation, logout, password reset, SSO identities (plan/59)."""
from __future__ import annotations

import contextlib
import hmac
import secrets
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from blackmoa.config import get_settings
from blackmoa.core import pools
from blackmoa.core.errors import Conflict, Forbidden, NotFound, Unauthorized, ValidationFailed
from blackmoa.core.security import (
    create_access_token,
    hash_password,
    new_refresh_token,
    sha256,
    verify_password,
)
from blackmoa.models import AuthIdentity, AuthSession, EmailVerification, Invite, PasswordReset, User
from blackmoa.services import audit
from blackmoa.services import credits as C
from blackmoa.services import jobs as J
from blackmoa.services import plans as P
from blackmoa.services import profile as PF
from blackmoa.services import settings as S

LOCK_THRESHOLD = 5
LOCK_MINUTES = 15


async def user_count(db: AsyncSession) -> int:
    return int((await db.execute(select(func.count(User.id)))).scalar_one())


async def _consume_invite(db: AsyncSession, code: str | None) -> None:
    if not code:
        raise Forbidden("invite required", code="invite_required")
    inv = (await db.execute(select(Invite).where(Invite.code == code).with_for_update())).scalars().first()
    if inv is None or (inv.expires_at and inv.expires_at < datetime.now(UTC)) or inv.used >= inv.max_uses:
        raise Forbidden("invalid invite", code="invite_invalid")
    inv.used += 1


def _validate_password(pw: str) -> None:
    """At least 8 characters and two of {upper, lower, digit, symbol}.

    The signup form ticks these off as they are typed, so the server has to be the one
    enforcing them — a checklist the backend does not check is a lie with extra steps, and
    one the backend is stricter than refuses passwords it would have taken.
    """
    if len(pw) < 8:
        raise ValidationFailed("password too short", code="password_too_short")
    classes = sum([
        any(c.isupper() for c in pw),
        any(c.islower() for c in pw),
        any(c.isdigit() for c in pw),
        any(not c.isalnum() for c in pw),
    ])
    if classes < 2:
        raise ValidationFailed("password needs two character classes", code="password_too_simple")
    if pw.lower() in {"password", "12345678", "qwerty123", "11111111", "abcdefgh", "iloveyou"}:
        raise ValidationFailed("password too common", code="password_too_common")


def _validate_bootstrap(n: int, supplied: str | None) -> None:
    if n != 0:
        return
    s = get_settings()
    if not s.public_url.lower().startswith("https://"):
        return
    expected = s.bootstrap_token.strip()
    if not expected:
        raise Forbidden("admin bootstrap is not configured", code="bootstrap_not_configured")
    if not supplied or not hmac.compare_digest(expected, supplied.strip()):
        raise Forbidden("bootstrap token required", code="bootstrap_required")


def record_terms(user: User, version: str) -> None:
    """이 판의 이용약관·개인정보 처리방침에 지금 동의했다 (plan/73)."""
    user.terms_version = version
    user.terms_agreed_at = datetime.now(UTC)


async def signup(db: AsyncSession, *, email: str, password: str | None, display_name: str,
                 nickname: str | None = None, invite_code: str | None = None, bootstrap_token: str | None = None,
                 identity: Any = None, ip: str = "", ua: str = "") -> User:
    """``identity`` (services.oauth.Identity) 가 있으면 그 공급자 계정을 로그인 방법으로 붙인다 (plan/59).
    이메일은 공급자가 검증했다고 말했고 그 이메일로 가입할 때만 인증된 것으로 둔다."""
    email = email.strip().lower()
    if password is not None:
        _validate_password(password)
    await db.execute(text("SELECT pg_advisory_xact_lock(4242)"))
    n = await user_count(db)
    _validate_bootstrap(n, bootstrap_token)
    mode = await S.get(db, "signup.mode")
    if n > 0:
        if mode == "closed":
            raise Forbidden("signup closed", code="signup_closed")
        if mode == "invite":
            await _consume_invite(db, invite_code)
    exists = (await db.execute(select(User.id).where(User.email == email))).first()
    if exists:
        raise Conflict("email already registered", code="email_taken")
    proven = identity is not None and identity.email_verified and (identity.email or "").lower() == email
    plan = await P.default_plan(db)
    user = User(email=email, password_hash=hash_password(password) if password else None,
                display_name=display_name.strip()[:120] or email.split("@")[0],
                nickname=(nickname or "").strip()[:60] or None, role="admin" if n == 0 else "user",
                plan_id=plan.id if plan else None, plan_cycle_anchor=datetime.now(UTC),
                email_verified_at=datetime.now(UTC) if proven else None)
    db.add(user)
    await db.flush()
    if identity is not None:
        db.add(AuthIdentity(user_id=user.id, provider=identity.provider, subject=identity.subject,
                            email=identity.email, raw_profile=identity.raw))
    grant = int(await S.get(db, "credits.signup_grant"))
    if plan and plan.monthly_credits:
        grant = max(grant, plan.monthly_credits)
    if grant > 0:
        await C.apply(db, user.id, grant, "grant", note="signup grant")
    if not proven and await S.get(db, "signup.require_email_verification"):
        await start_email_verification(db, user)
    # The profile is what the secretary introduces its owner from, and the form just
    # asked for the name — carry it across instead of making them type it twice.
    await PF.seed_from_account(db, user)
    await claim_super(db, user)
    await J.enqueue(db, "account.bootstrap", {"user_id": str(user.id)})
    audit.record(db, "signup", actor_id=user.id, target_type="user", target_id=user.id, ip=ip, ua=ua,
                 meta={"role": user.role, "super": user.is_super, "sso": identity.provider if identity is not None else None})
    return user


async def claim_super(db: AsyncSession, user: User) -> bool:
    """Make this admin the maintainer when the install has none yet.

    Called at both places an admin can first appear — the first signup and the seeded
    account — so a fresh install has somebody who can appoint admins without anyone
    running SQL.
    """
    if user.role != "admin" or user.is_super:
        return False
    taken = (await db.execute(select(User.id).where(User.is_super.is_(True)))).first()
    if taken:
        return False
    user.is_super = True
    return True


async def ensure_default_admin(db: AsyncSession) -> User | None:
    """Create the seeded administrator (``admin@geny.com`` by default) when it is missing.

    Idempotent and non-destructive: an account that already exists is never touched,
    so changing the seeded password (or the role) sticks across restarts. Disable the
    seed entirely with ``BLACKMOA_DEFAULT_ADMIN_ENABLED=false``.
    """
    s = get_settings()
    if not s.default_admin_enabled:
        return None
    email = (s.default_admin_email or "").strip().lower()
    password = s.default_admin_password or ""
    if not email or len(password) < 8:
        return None
    await db.execute(text("SELECT pg_advisory_xact_lock(4243)"))
    if (await db.execute(select(User.id).where(User.email == email))).first():
        return None
    plan = await P.default_plan(db)
    user = User(email=email, password_hash=hash_password(password), display_name=(s.default_admin_name or "Admin")[:120],
                role="admin", plan_id=plan.id if plan else None, plan_cycle_anchor=datetime.now(UTC),
                email_verified_at=datetime.now(UTC))
    db.add(user)
    await db.flush()
    grant = int(await S.get(db, "credits.signup_grant"))
    if plan and plan.monthly_credits:
        grant = max(grant, plan.monthly_credits)
    if grant > 0:
        await C.apply(db, user.id, grant, "grant", note="default admin grant")
    # The profile is what the secretary introduces its owner from, and the form just
    # asked for the name — carry it across instead of making them type it twice.
    await PF.seed_from_account(db, user)
    await claim_super(db, user)
    await J.enqueue(db, "account.bootstrap", {"user_id": str(user.id)})
    audit.record(db, "default_admin_seeded", actor_id=user.id, target_type="user", target_id=user.id,
                 meta={"email": email, "super": user.is_super})
    return user


async def default_admin_password_in_use(db: AsyncSession) -> bool:
    """True while the seeded admin still holds the shipped password (console warns on it)."""
    s = get_settings()
    if not s.default_admin_enabled or not s.default_admin_password:
        return False
    email = (s.default_admin_email or "").strip().lower()
    user = (await db.execute(select(User).where(User.email == email))).scalars().first()
    if user is None or not user.password_hash or user.status != "active":
        return False
    return verify_password(s.default_admin_password, user.password_hash)


async def authenticate(db: AsyncSession, *, email: str, password: str, ip: str = "", ua: str = "") -> User:
    email = email.strip().lower()
    user = (await db.execute(select(User).where(User.email == email))).scalars().first()
    if user is None or user.status != "active":
        raise Unauthorized("invalid credentials", code="invalid_credentials")
    if user.locked_until and user.locked_until > datetime.now(UTC):
        raise Unauthorized("account locked", code="account_locked", detail={"until": user.locked_until.isoformat()})
    if not verify_password(password, user.password_hash):
        user.failed_logins = (user.failed_logins or 0) + 1
        if user.failed_logins >= LOCK_THRESHOLD:
            user.locked_until = datetime.now(UTC) + timedelta(minutes=LOCK_MINUTES)
            user.failed_logins = 0
        audit.record(db, "login_failed", actor_id=user.id, ip=ip, ua=ua)
        raise Unauthorized("invalid credentials", code="invalid_credentials")
    user.failed_logins = 0
    user.locked_until = None
    user.last_login_at = datetime.now(UTC)
    # Signing in is the other proof that the address is this person's; a visitor who left
    # their email with someone's secretary and later logs in becomes that person there.
    if user.email_verified_at:
        with contextlib.suppress(Exception):
            from blackmoa.services import people as PEOPLE
            await PEOPLE.claim_visitors_for(db, user)
    audit.record(db, "login", actor_id=user.id, ip=ip, ua=ua)
    return user


async def issue_session(db: AsyncSession, user: User, *, ip: str = "", ua: str = "",
                        family_id: uuid.UUID | None = None) -> tuple[str, str, AuthSession]:
    raw, h = new_refresh_token()
    s = get_settings()
    sess = AuthSession(user_id=user.id, family_id=family_id or uuid.uuid4(), refresh_hash=h, ua=ua[:500], ip=ip,
                       expires_at=datetime.now(UTC) + timedelta(days=s.refresh_token_days), created_at=datetime.now(UTC))
    db.add(sess)
    await db.flush()
    return create_access_token(user.id, user.role, sess.id), raw, sess


#: How long a just-rotated refresh token still counts as the racing twin of the one that
#: replaced it, rather than as a stolen token. Seconds, because that is the width of the
#: race — a network round trip — and anything longer starts to weaken the detection.
REFRESH_GRACE_S = 20.0


async def _live_head(db: AsyncSession, sess: AuthSession) -> AuthSession | None:
    """Follow ``replaced_by`` to the session this family is currently using.

    Bounded: a cycle or a long chain must not turn a sign-in into a walk of the table.
    """
    seen = 0
    cur = sess
    while cur.replaced_by is not None and seen < 10:
        nxt = await db.get(AuthSession, cur.replaced_by)
        if nxt is None:
            return None
        if nxt.revoked_at is None:
            return nxt
        cur, seen = nxt, seen + 1
    return None


async def refresh(db: AsyncSession, raw_refresh: str, *, ip: str = "", ua: str = "") -> tuple[str, str, User]:
    h = sha256(raw_refresh)
    sess = (await db.execute(select(AuthSession).where(AuthSession.refresh_hash == h))).scalars().first()
    if sess is None:
        raise Unauthorized("invalid refresh", code="invalid_refresh")
    now = datetime.now(UTC)
    if sess.revoked_at is not None:
        # A token that was rotated a moment ago is a racing client, not a stolen one.
        #
        # Two refreshes leaving the browser before either Set-Cookie comes back is ordinary:
        # a reload while one is in flight, a second tab, a component mounting twice. Both
        # carry the same cookie, the first rotates it, and the second then looked exactly
        # like theft — so the whole family was revoked and the person was signed out of
        # every device. It happened seventy times on this install before anyone noticed,
        # because the only symptom is being logged out for no reason.
        #
        # Inside the grace window the request continues from the family's live head instead.
        # Outside it, or when the family has no live head, this is still treated as theft:
        # a token replayed later, or after the family was revoked, is exactly the case the
        # detection exists for.
        head = await _live_head(db, sess) if (now - sess.revoked_at).total_seconds() <= REFRESH_GRACE_S else None
        if head is None:
            await db.execute(text("UPDATE auth_sessions SET revoked_at = now() WHERE family_id = :f AND revoked_at IS NULL"), {"f": sess.family_id})
            audit.record(db, "refresh_reuse_detected", actor_id=sess.user_id, ip=ip, ua=ua)
            raise Unauthorized("refresh reused", code="refresh_reused")
        sess = head
    if sess.expires_at < now:
        raise Unauthorized("refresh expired", code="refresh_expired")
    user = await db.get(User, sess.user_id)
    if user is None or user.status != "active":
        raise Unauthorized("user inactive", code="user_inactive")
    sess.revoked_at = now
    access, raw, new_sess = await issue_session(db, user, ip=ip, ua=ua, family_id=sess.family_id)
    sess.replaced_by = new_sess.id
    return access, raw, user


async def logout(db: AsyncSession, raw_refresh: str | None, *, all_devices: bool = False,
                 user_id: uuid.UUID | None = None) -> None:
    if all_devices and user_id:
        await db.execute(text("UPDATE auth_sessions SET revoked_at = now() WHERE user_id = :u AND revoked_at IS NULL"),
                         {"u": user_id})
        return
    if raw_refresh:
        await db.execute(text("UPDATE auth_sessions SET revoked_at = now() WHERE refresh_hash = :h AND revoked_at IS NULL"),
                         {"h": sha256(raw_refresh)})


async def change_password(db: AsyncSession, user: User, current: str, new: str) -> None:
    """Set a new password and revoke every existing session.

    The caller is expected to mint a fresh session for the device that made the
    change (see ``POST /api/users/me/password``) - a password change must log out
    stolen sessions elsewhere, not the person performing it.
    """
    if user.password_hash and not verify_password(current, user.password_hash):
        raise Unauthorized("wrong password", code="invalid_credentials")
    _validate_password(new)
    user.password_hash = hash_password(new)
    await logout(db, None, all_devices=True, user_id=user.id)


async def start_password_reset(db: AsyncSession, email: str) -> tuple[User, str] | None:
    user = (await db.execute(select(User).where(User.email == email.strip().lower()))).scalars().first()
    if user is None:
        return None
    raw = secrets.token_urlsafe(32)
    db.add(PasswordReset(user_id=user.id, token_hash=sha256(raw), expires_at=datetime.now(UTC) + timedelta(minutes=30)))
    return user, raw


async def finish_password_reset(db: AsyncSession, raw: str, new: str) -> User:
    pr = (await db.execute(select(PasswordReset).where(PasswordReset.token_hash == sha256(raw)))).scalars().first()
    if pr is None or pr.used_at or pr.expires_at < datetime.now(UTC):
        raise Unauthorized("invalid reset token", code="invalid_reset")
    _validate_password(new)
    user = await db.get(User, pr.user_id)
    user.password_hash = hash_password(new)
    pr.used_at = datetime.now(UTC)
    await logout(db, None, all_devices=True, user_id=user.id)
    return user


async def start_email_verification(db: AsyncSession, user: User, *, inline: bool = False) -> str:
    """Issue a verification code and mail it.

    `inline` sends on this request instead of through the queue. Someone standing in front
    of "send me a code" needs to learn *now* that the mail server rejected us — a queued
    send fails in the worker, and the screen still says the code is on its way.
    """
    code = f"{secrets.randbelow(1_000_000):06d}"
    await db.execute(text("UPDATE email_verifications SET used_at = now() WHERE user_id = :u AND used_at IS NULL"), {"u": user.id})
    db.add(EmailVerification(user_id=user.id, code_hash=sha256(f"{user.id}:{code}"),
                             expires_at=datetime.now(UTC) + timedelta(minutes=30)))
    from blackmoa.services.emails import verification
    subject, body, html = verification(code=code, name=user.nickname or user.display_name or "")
    if inline:
        from blackmoa.services.mailer import send_mail
        await send_mail(db, to=user.email, subject=subject, text=body, html=html)
    else:
        await J.enqueue(db, "mail.send", {"to": user.email, "subject": subject, "text": body, "html": html}, priority=1)
    return code


async def verify_email_code(db: AsyncSession, user: User, code: str) -> bool:
    row = (await db.execute(select(EmailVerification).where(EmailVerification.user_id == user.id,
                                                            EmailVerification.used_at.is_(None))
                            .order_by(EmailVerification.expires_at.desc()))).scalars().first()
    if row is None or row.expires_at < datetime.now(UTC):
        return False
    if not hmac.compare_digest(row.code_hash, sha256(f"{user.id}:{code.strip()}")):
        return False
    row.used_at = datetime.now(UTC)
    user.email_verified_at = datetime.now(UTC)
    # The address is proven now, so any guest identity left at that address is theirs to
    # claim (plan/31). Not at signup: typing an address into a form is not proof, and a
    # guest identity carries real conversations with somebody's secretary.
    with contextlib.suppress(Exception):
        from blackmoa.services import people as PEOPLE
        await PEOPLE.claim_visitors_for(db, user)
    return True


async def purge_user_storage(db: AsyncSession, user_id: uuid.UUID) -> None:
    import shutil

    from blackmoa.memory.facade import delete_vault
    from blackmoa.models import Agent
    from blackmoa.pipeline.runtime import runtimes

    for (aid,) in (await db.execute(select(Agent.id).where(Agent.owner_id == user_id))).all():
        await runtimes.drop_agent(aid)
        await delete_vault(aid)
    await db.execute(text("DELETE FROM turn_events WHERE turn_id IN (SELECT id FROM turns WHERE owner_id = :u)"),
                     {"u": user_id})
    await db.execute(text("DELETE FROM credit_balances WHERE owner_id = :u"), {"u": user_id})
    await pools.to_thread("misc", shutil.rmtree, get_settings().upload_root / str(user_id), True)
    # 저장소가 S3 면 파일은 디스크가 아니라 버킷에 있다. 모든 키가 ``<user_id>/`` 로 시작한다
    # (업로드·지식·비서 파일의 썸네일과 글). 여기서 지우지 않으면 지운 계정의 자료가 남는다.
    from blackmoa.services import objectstore
    try:
        await objectstore.delete_prefix(f"{user_id}/")
    except Exception as e:  # noqa: BLE001
        from blackmoa.core.logging import get_logger
        get_logger("blackmoa.accounts").warning("account objects not removed", user_id=str(user_id), err=str(e)[:200])


async def sso_login(db: AsyncSession, ident: Any, *, invite_code: str | None = None, ip: str = "", ua: str = "") -> tuple[User | None, str]:
    """공급자 계정으로 들어온 사람을 계정에 잇는다 (plan/59). ``(user, outcome)``.

    - 이미 이어진 공급자 계정 → 그 계정으로 로그인 (``login``)
    - 공급자가 **검증했다고 말한** 이메일이 이미 있는 계정 → 이어 붙이고 로그인 (``linked``)
    - 검증된 이메일이 새것 → 가입 (``signup``) — 일반 가입과 같은 규칙(닫힘·초대제·첫 관리자)을 따른다
    - 이메일이 없거나 검증되지 않음 → ``(None, "needs_email")``: 가입 마무리 화면에서 이메일을 받는다.
      검증되지 않은 이메일로 남의 계정에 붙이면, 그 이메일을 적어 넣은 사람이 계정을 가져간다.
    """
    row = (await db.execute(select(AuthIdentity).where(AuthIdentity.provider == ident.provider,
                                                      AuthIdentity.subject == ident.subject))).scalars().first()
    if row is not None:
        user = await db.get(User, row.user_id)
        if user is None or user.status != "active":
            raise Unauthorized("user inactive", code="user_inactive")
        row.email = ident.email or row.email
        row.raw_profile = ident.raw or row.raw_profile
        user.last_login_at = datetime.now(UTC)
        await _claim_visitors(db, user)
        return user, "login"
    email = (ident.email or "").lower()
    if email and ident.email_verified:
        user = (await db.execute(select(User).where(User.email == email))).scalars().first()
        if user is not None:
            if user.status != "active":
                raise Unauthorized("user inactive", code="user_inactive")
            db.add(AuthIdentity(user_id=user.id, provider=ident.provider, subject=ident.subject, email=email, raw_profile=ident.raw))
            took_over = False
            if not user.email_verified_at:
                # 이메일을 인증하지 않은 계정은 그 주소의 주인이 만들었다는 보장이 없다. 남이 내 주소로 먼저
                # 가입해 두고 비밀번호를 쥐고 기다리는 경우, 여기서 잇기만 하면 그 사람도 계속 들어온다.
                # 주소를 증명한 쪽이 계정을 갖는다 — 비밀번호와 열린 세션을 거둔다.
                took_over = bool(user.password_hash)
                user.password_hash = None
                await logout(db, None, all_devices=True, user_id=user.id)
                user.email_verified_at = datetime.now(UTC)
            user.last_login_at = datetime.now(UTC)
            audit.record(db, "identity_linked", actor_id=user.id, target_type="user", target_id=user.id, ip=ip, ua=ua,
                         meta={"provider": ident.provider, "by": "verified_email", "password_cleared": took_over})
            await _claim_visitors(db, user)
            return user, "linked"
        user = await signup(db, email=email, password=None, display_name=ident.name or email.split("@")[0],
                            invite_code=invite_code, identity=ident, ip=ip, ua=ua)
        return user, "signup"
    return None, "needs_email"


async def _claim_visitors(db: AsyncSession, user: User) -> None:
    """이메일이 증명된 사람이 들어오면, 그 주소로 누군가의 비서에게 남긴 방문 기록이 이 사람의 것이 된다 (비밀번호 로그인과 같다)."""
    if user.email_verified_at:
        with contextlib.suppress(Exception):
            from blackmoa.services import people as PEOPLE
            await PEOPLE.claim_visitors_for(db, user)


async def link_identity(db: AsyncSession, user: User, ident: Any, *, ip: str = "", ua: str = "") -> None:
    """로그인한 사람이 계정 설정에서 공급자 계정을 로그인 방법으로 더한다."""
    row = (await db.execute(select(AuthIdentity).where(AuthIdentity.provider == ident.provider,
                                                      AuthIdentity.subject == ident.subject))).scalars().first()
    if row is not None:
        if row.user_id != user.id:
            raise Conflict("this account already signs in to another black-moa account", code="identity_taken")
        return
    mine = (await db.execute(select(AuthIdentity).where(AuthIdentity.user_id == user.id,
                                                       AuthIdentity.provider == ident.provider))).scalars().first()
    if mine is not None:
        raise Conflict("another account of this provider is already linked", code="identity_provider_linked")
    db.add(AuthIdentity(user_id=user.id, provider=ident.provider, subject=ident.subject, email=ident.email, raw_profile=ident.raw))
    audit.record(db, "identity_linked", actor_id=user.id, target_type="user", target_id=user.id, ip=ip, ua=ua,
                 meta={"provider": ident.provider, "by": "settings"})


async def unlink_identity(db: AsyncSession, user: User, identity_id: uuid.UUID) -> None:
    """로그인 방법 하나를 뗀다. 마지막 남은 방법은 뗄 수 없다 — 들어올 길이 없어진다."""
    row = await db.get(AuthIdentity, identity_id)
    if row is None or row.user_id != user.id:
        raise NotFound("identity not found", code="identity_not_found")
    others = int((await db.execute(select(func.count(AuthIdentity.id)).where(AuthIdentity.user_id == user.id,
                                                                          AuthIdentity.id != row.id))).scalar_one())
    if not user.password_hash and others == 0:
        raise Conflict("this is the only way to sign in", code="last_login_method")
    await db.delete(row)
    audit.record(db, "identity_unlinked", actor_id=user.id, target_type="user", target_id=user.id,
                 meta={"provider": row.provider})


async def promote(db: AsyncSession, actor: User, target: User, role: str) -> None:
    if role not in ("admin", "user"):
        raise ValidationFailed("bad role")
    if not actor.is_super:
        raise Forbidden("only the super administrator can change roles", code="super_admin_only")
    if target.is_super:
        # Not even by themselves: an install with nobody who can appoint an admin is an
        # install that needs a database console to recover.
        raise Conflict("the super administrator's role cannot be changed", code="super_admin_locked")
    if role == "user" and target.role == "admin":
        admins = int((await db.execute(select(func.count(User.id)).where(User.role == "admin",
                                                                       User.status == "active"))).scalar_one())
        if admins <= 1:
            raise Conflict("last admin cannot be demoted", code="last_admin")
    target.role = role
    audit.record(db, "role_change", actor_id=actor.id, actor_kind="admin", target_type="user", target_id=target.id,
                 meta={"role": role})
