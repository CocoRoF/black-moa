"""Admin console security: every /api/admin route is admin-only, and the seeded
default administrator behaves (idempotent, never overwrites, warns while default)."""
from __future__ import annotations

import uuid

import pytest
from httpx import AsyncClient

from tests.conftest import auth, signup

pytestmark = pytest.mark.asyncio

# Public on purpose: the signup page needs to know whether an install has any account
# at all. It exposes no user data.
PUBLIC_ADMIN_PATHS = {"/api/admin/bootstrap-status"}


def _admin_routes(app) -> list[tuple[str, str]]:
    """Every (method, path) the app actually serves under /api/admin.

    Recent FastAPI wraps ``include_router`` results in ``_IncludedRouter`` objects
    that expose the real routes only through ``original_router``, so walking
    ``app.routes`` naively finds nothing and the sweep would silently pass.
    """
    out: list[tuple[str, str]] = []

    def walk(routes) -> None:
        for r in routes:
            inner = getattr(r, "original_router", None)
            if inner is not None:
                walk(inner.routes)
                continue
            nested = getattr(r, "routes", None)
            if nested:
                walk(nested)
                continue
            path = getattr(r, "path", "") or ""
            if not path.startswith("/api/admin") or path in PUBLIC_ADMIN_PATHS:
                continue
            for m in sorted((getattr(r, "methods", None) or set()) - {"HEAD", "OPTIONS"}):
                out.append((m, path))

    walk(app.routes)
    return sorted(set(out))


def _fill(path: str) -> str:
    return path.replace("{uid}", str(uuid.uuid4())).replace("{id}", str(uuid.uuid4())) \
               .replace("{job_id}", str(uuid.uuid4())).replace("{code}", "zzzzzzzz") \
               .replace("{key}", "branding.service_name").replace("{model_id}", "fake-1") \
               .replace("{plan_id}", str(uuid.uuid4())).replace("{provider}", "openai") \
               .replace("{account_id}", str(uuid.uuid4()))


async def test_every_admin_route_rejects_non_admins(client: AsyncClient, app):
    # The very first account of an install is the admin, so make sure this one is not it.
    await signup(client, f"first-{uuid.uuid4().hex[:6]}@example.com")
    user, user_tok = await signup(client, f"plain-{uuid.uuid4().hex[:6]}@example.com")
    assert user["role"] == "user"
    routes = _admin_routes(app)
    assert len(routes) > 20, "admin router did not load"
    leaks: list[str] = []
    for method, path in routes:
        url = _fill(path)
        anon = await client.request(method, url, json={})
        if anon.status_code != 401:
            leaks.append(f"anon {method} {path} -> {anon.status_code}")
        as_user = await client.request(method, url, json={}, headers=auth(user_tok))
        if as_user.status_code != 403:
            leaks.append(f"user {method} {path} -> {as_user.status_code}")
    assert not leaks, "admin surface reachable without admin role:\n" + "\n".join(leaks)


async def test_admin_pages_need_a_live_admin_role_not_just_an_old_token(client: AsyncClient):
    """A demoted admin's still-valid access token must stop opening the console."""
    await signup(client, f"first-{uuid.uuid4().hex[:6]}@example.com")
    admin, admin_tok = await signup(client, f"a-{uuid.uuid4().hex[:6]}@example.com")
    second, second_tok = await signup(client, f"b-{uuid.uuid4().hex[:6]}@example.com")
    from memora.db.session import session_scope
    from memora.models import User
    async with session_scope() as db:
        u = await db.get(User, uuid.UUID(admin["id"]))
        u.role = "admin"
        v = await db.get(User, uuid.UUID(second["id"]))
        v.role = "admin"
    assert (await client.get("/api/admin/overview", headers=auth(second_tok))).status_code == 200
    async with session_scope() as db:
        v = await db.get(User, uuid.UUID(second["id"]))
        v.role = "user"
    # same token, role revoked in the database
    assert (await client.get("/api/admin/overview", headers=auth(second_tok))).status_code == 403
    async with session_scope() as db:
        v = await db.get(User, uuid.UUID(second["id"]))
        v.status = "suspended"
    assert (await client.get("/api/agents", headers=auth(second_tok))).status_code == 401
    # Leave the install with exactly the admin it started with: sibling tests assert
    # "last admin" behaviour against a global count.
    async with session_scope() as db:
        u = await db.get(User, uuid.UUID(admin["id"]))
        u.role = "user"


async def test_default_admin_seed_is_idempotent_and_warns_until_changed(client: AsyncClient, monkeypatch):
    from memora.config import get_settings
    from memora.db.session import session_scope
    from memora.services import accounts as A

    s = get_settings()
    email = f"seed-{uuid.uuid4().hex[:6]}@geny.com"
    monkeypatch.setattr(s, "default_admin_enabled", True, raising=False)
    monkeypatch.setattr(s, "default_admin_email", email, raising=False)
    monkeypatch.setattr(s, "default_admin_password", "admin123", raising=False)
    async with session_scope() as db:
        seeded = await A.ensure_default_admin(db)
        assert seeded is not None and seeded.role == "admin" and seeded.email == email
        seeded_id = seeded.id
        assert await A.ensure_default_admin(db) is None  # idempotent
        assert await A.default_admin_password_in_use(db) is True
    # it is a real login, not a shadow account
    r = await client.post("/api/auth/login", json={"email": email, "password": "admin123"})
    assert r.status_code == 200 and r.json()["user"]["role"] == "admin"
    tok = r.json()["access_token"]
    ov = await client.get("/api/admin/overview", headers=auth(tok))
    assert ov.status_code == 200 and ov.json()["default_admin_password_in_use"] is True
    # changing the password clears the warning and the seed never restores it
    pw = await client.post("/api/users/me/password", headers=auth(tok),
                           json={"current_password": "admin123", "new_password": "a-better-secret-9"})
    assert pw.status_code == 200
    # changing the password must not sign the caller out: the response carries a live session
    assert (await client.get("/api/admin/overview", headers=auth(pw.json()["access_token"]))).status_code == 200
    async with session_scope() as db:
        assert await A.ensure_default_admin(db) is None
        assert await A.default_admin_password_in_use(db) is False
    assert (await client.post("/api/auth/login", json={"email": email, "password": "admin123"})).status_code == 401
    # Same reason as above: do not leave a second administrator behind.
    async with session_scope() as db:
        from memora.models import User as U
        await db.delete(await db.get(U, seeded_id))


async def test_password_change_keeps_this_device_and_drops_the_others(client: AsyncClient):
    """A password change revokes sessions everywhere else, not the one performing it."""
    from httpx import AsyncClient as AC
    email = f"pw-{uuid.uuid4().hex[:6]}@example.com"
    await signup(client, email)
    # a second device, with its own refresh cookie
    async with AC(transport=client._transport, base_url="http://testserver") as other:
        r = await other.post("/api/auth/login", json={"email": email, "password": "correct-horse-9"})
        assert r.status_code == 200
        assert (await other.post("/api/auth/refresh")).status_code == 200

        me = await client.post("/api/auth/login", json={"email": email, "password": "correct-horse-9"})
        tok = me.json()["access_token"]
        changed = await client.post("/api/users/me/password", headers=auth(tok),
                                    json={"current_password": "correct-horse-9", "new_password": "another-good-pw-1"})
        assert changed.status_code == 200
        new_tok = changed.json()["access_token"]
        # this device keeps working, on both the returned access token and its rotated cookie
        assert (await client.get("/api/auth/me", headers=auth(new_tok))).status_code == 200
        assert (await client.post("/api/auth/refresh")).status_code == 200
        # the other device is out
        assert (await other.post("/api/auth/refresh")).status_code == 401
    assert (await client.post("/api/auth/login", json={"email": email, "password": "correct-horse-9"})).status_code == 401


# ── the maintainer ─────────────────────────────────────────────────

@pytest.fixture
async def admin_seat():
    """Put the roles back afterwards.

    These tests promote and demote accounts, and sibling files ask questions like "who is
    the earliest admin" and "is this the only one". Leaving the promotions behind makes
    this file's order decide whether those pass.
    """
    from sqlalchemy import select as _sel
    from sqlalchemy import text as _t

    from memora.db.session import session_scope
    from memora.models import User as _U

    async with session_scope() as db:
        before = {u.id: (u.role, u.is_super) for u in (await db.execute(_sel(_U))).scalars().all()}
    yield
    async with session_scope() as db:
        # Vacate the seat before filling it: the partial unique index refuses a moment in
        # which two rows are the maintainer, even inside one flush.
        await db.execute(_t("UPDATE users SET is_super = false WHERE is_super"))
        await db.flush()
        for u in (await db.execute(_sel(_U))).scalars().all():
            u.role, u.is_super = before.get(u.id, ("user", False))


async def _make_admin(user_id: str, *, is_super: bool = False) -> None:
    """Promote in the database. The seat is single-occupancy (partial unique index), so
    claiming it vacates whoever an earlier test left in it."""
    import uuid as _u

    from sqlalchemy import text as _t

    from memora.db.session import session_scope
    from memora.models import User as _U
    async with session_scope() as db:
        if is_super:
            await db.execute(_t("UPDATE users SET is_super = false WHERE is_super"))
            await db.flush()
        u = await db.get(_U, _u.UUID(user_id))
        u.role, u.is_super = "admin", is_super


async def test_only_the_super_administrator_hands_out_admin(client: AsyncClient, admin_seat):
    """Every admin could already appoint another and delete one. That is the maintainer's
    call, not every admin's."""
    boss, boss_tok = await signup(client)
    await _make_admin(boss["id"], is_super=True)
    deputy, deputy_tok = await signup(client)
    await _make_admin(deputy["id"])
    someone, _ = await signup(client)

    denied = await client.post(f"/api/admin/users/{someone['id']}/role", json={"role": "admin"}, headers=auth(deputy_tok))
    assert denied.status_code == 403 and denied.json()["error"]["code"] == "super_admin_only"

    ok = await client.post(f"/api/admin/users/{someone['id']}/role", json={"role": "admin"}, headers=auth(boss_tok))
    assert ok.status_code == 200 and ok.json()["role"] == "admin"


async def test_the_super_administrator_cannot_be_demoted_suspended_or_deleted(client: AsyncClient, admin_seat):
    """An install with nobody who can appoint an admin needs a database console to recover."""
    boss, boss_tok = await signup(client)
    await _make_admin(boss["id"], is_super=True)
    other, other_tok = await signup(client)
    await _make_admin(other["id"])

    assert (await client.post(f"/api/admin/users/{boss['id']}/role", json={"role": "user"}, headers=auth(boss_tok))).status_code == 409
    for tok in (boss_tok, other_tok):
        assert (await client.patch(f"/api/admin/users/{boss['id']}", json={"status": "suspended"}, headers=auth(tok))).status_code in (400, 422)
        assert (await client.delete(f"/api/admin/users/{boss['id']}", headers=auth(tok))).status_code in (400, 422)
    assert (await client.get("/api/auth/me", headers=auth(boss_tok))).json()["is_super"] is True


async def test_an_ordinary_admin_cannot_remove_another_admin(client: AsyncClient, admin_seat):
    boss, _ = await signup(client)
    await _make_admin(boss["id"], is_super=True)
    a_user, a_tok = await signup(client)
    await _make_admin(a_user["id"])
    b_user, _ = await signup(client)
    await _make_admin(b_user["id"])
    r = await client.delete(f"/api/admin/users/{b_user['id']}", headers=auth(a_tok))
    assert r.status_code == 403 and r.json()["error"]["code"] == "super_admin_only"
    # …but an ordinary account is still theirs to remove.
    plain, _ = await signup(client)
    assert (await client.delete(f"/api/admin/users/{plain['id']}", headers=auth(a_tok))).status_code == 200


async def test_the_seat_is_single_occupancy(client: AsyncClient, admin_seat):
    """Nobody should have to run SQL to have somebody who can appoint an admin — and a
    second admin never takes a seat that is already occupied."""
    import uuid as _u

    from sqlalchemy import select as _sel
    from sqlalchemy import text as _t

    from memora.db.session import session_scope
    from memora.models import User as _U
    from memora.services import accounts as A

    async with session_scope() as db:
        await db.execute(_t("UPDATE users SET is_super = false WHERE is_super"))
    first, _ = await signup(client)
    second, _ = await signup(client)
    async with session_scope() as db:
        a = await db.get(_U, _u.UUID(first["id"]))
        a.role = "admin"
        assert await A.claim_super(db, a) is True, "an install with no maintainer appoints one"
    async with session_scope() as db:
        b = await db.get(_U, _u.UUID(second["id"]))
        b.role = "admin"
        assert await A.claim_super(db, b) is False, "the seat was taken"
        assert len((await db.execute(_sel(_U).where(_U.is_super.is_(True)))).scalars().all()) == 1
