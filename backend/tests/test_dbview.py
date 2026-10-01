"""The read-only database window, and everything it must refuse (plan/48).

This is an administrator with a SQL box against a database role that is a **superuser**, so
these tests are the feature. Each attack is run through the real endpoint against the real
database: a refusal that only happens in a unit test is not a refusal.
"""
from __future__ import annotations

import uuid as _uuid

import pytest
from httpx import AsyncClient
from sqlalchemy import text

from tests.conftest import auth, signup

pytestmark = pytest.mark.asyncio


@pytest.fixture
async def admin_client(client: AsyncClient):
    from blackmoa.db.session import session_scope
    from blackmoa.models import User
    from blackmoa.services.dbview import ensure_role

    user, tok = await signup(client, f"dbview-{_uuid.uuid4().hex[:6]}@example.com")
    async with session_scope() as db:
        (await db.get(User, _uuid.UUID(user["id"]))).role = "admin"
    async with session_scope() as db:
        await ensure_role(db)
    yield client, tok
    async with session_scope() as db:
        (await db.get(User, _uuid.UUID(user["id"]))).role = "user"


async def run(client: AsyncClient, tok: str, sql: str, **kw):
    return await client.post("/api/admin/diagnostics/db/query", json={"sql": sql, **kw}, headers=auth(tok))


# ── it has to actually work ─────────────────────────────────────────

async def test_a_select_returns_rows_and_columns(admin_client):
    client, tok = admin_client
    r = await run(client, tok, "SELECT id, email, role FROM users ORDER BY created_at LIMIT 3")
    assert r.status_code == 200, r.text
    d = r.json()
    assert d["columns"] == ["id", "email", "role"]
    assert d["rows"] and all(set(row) == {"id", "email", "role"} for row in d["rows"])


async def test_clicking_a_table_is_just_a_select(admin_client):
    """The default the browser sends."""
    client, tok = admin_client
    r = await run(client, tok, "SELECT * FROM users LIMIT 100", limit=100, table="users")
    assert r.status_code == 200, r.text
    assert r.json()["row_count"] >= 1


async def test_the_table_list_and_columns_describe_the_schema(admin_client):
    client, tok = admin_client
    tables = (await client.get("/api/admin/diagnostics/db/tables", headers=auth(tok))).json()["items"]
    assert any(t["name"] == "users" for t in tables)
    cols = (await client.get("/api/admin/diagnostics/db/columns?table=users", headers=auth(tok))).json()["items"]
    names = {c["name"] for c in cols}
    assert {"id", "email", "password_hash"} <= names
    assert next(c for c in cols if c["name"] == "password_hash")["masked"] is True


async def test_a_result_is_capped(admin_client):
    client, tok = admin_client
    r = await run(client, tok, "SELECT generate_series(1, 10000) AS n", limit=5)
    assert r.status_code == 200, r.text
    assert r.json()["row_count"] == 5 and r.json()["truncated"] is True


# ── what it must refuse ─────────────────────────────────────────────

@pytest.mark.parametrize("sql", [
    "DELETE FROM users",
    "UPDATE users SET role = 'admin'",
    "INSERT INTO users (email) VALUES ('x@y.z')",
    "DROP TABLE users",
    "TRUNCATE audit_logs",
    "ALTER TABLE users ADD COLUMN x int",
    "CREATE TABLE evil (x int)",
    "GRANT ALL ON users TO PUBLIC",
    # a write wearing a SELECT's clothes: allowed only at the top level, and we never run
    # the user's statement at the top level
    "WITH gone AS (DELETE FROM audit_logs RETURNING *) SELECT * FROM gone",
    "WITH up AS (UPDATE users SET role='admin' RETURNING id) SELECT * FROM up",
    # a second statement, including hidden behind a comment
    "SELECT 1; DROP TABLE users",
    "SELECT 1 -- \n; DROP TABLE users",
    "SELECT 1 /* hide */ ; TRUNCATE users",
    # table creation dressed as a query
    "SELECT * INTO evil FROM users",
    # the superuser powers that a read-only transaction would not stop
    "SELECT pg_read_file('/etc/passwd')",
    "SELECT pg_ls_dir('/')",
    "SELECT lo_import('/etc/passwd')",
    "SELECT pg_terminate_backend(1)",
    "SELECT pg_sleep(30)",
    "COPY users TO PROGRAM 'sh -c id'",
    "SELECT set_config('statement_timeout', '0', false)",
])
async def test_everything_that_is_not_a_read_is_refused(admin_client, sql: str):
    client, tok = admin_client
    r = await run(client, tok, sql)
    assert r.status_code >= 400, f"ACCEPTED: {sql} -> {r.text[:300]}"


async def test_the_database_is_untouched_by_a_refused_write(admin_client):
    """Not just refused — refused without effect."""
    client, tok = admin_client
    from blackmoa.db.session import session_scope

    async with session_scope() as db:
        before = (await db.execute(text("SELECT count(*) FROM audit_logs"))).scalar_one()
    for sql in ("DELETE FROM audit_logs",
                "WITH gone AS (DELETE FROM audit_logs RETURNING *) SELECT count(*) FROM gone"):
        await run(client, tok, sql)
    async with session_scope() as db:
        after = (await db.execute(text("SELECT count(*) FROM audit_logs"))).scalar_one()
        made = (await db.execute(text("SELECT to_regclass('public.evil')"))).scalar_one()
    assert after >= before, "a refused statement still deleted rows"
    assert made is None, "a refused statement still created a table"


async def test_secrets_are_masked_even_when_selected_directly(admin_client):
    """An administrator has no reason to read a password hash out of a grid, and a stolen
    administrator session has every reason to try."""
    client, tok = admin_client
    r = await run(client, tok, "SELECT email, password_hash FROM users LIMIT 5")
    assert r.status_code == 200, r.text
    d = r.json()
    assert "password_hash" in d["masked"]
    assert all(row["password_hash"] in ("••••••", None) for row in d["rows"]), d["rows"][:2]
    assert any("@" in (row["email"] or "") for row in d["rows"]), "masking swallowed everything"


async def test_the_connection_comes_back_as_itself(admin_client):
    """The role and the read-only flag are transaction-scoped; if the rollback were ever
    skipped, the next borrower of that connection would inherit a crippled session."""
    client, tok = admin_client
    from blackmoa.db.session import session_scope

    await run(client, tok, "SELECT 1")
    await run(client, tok, "DELETE FROM users")          # fails inside the transaction
    async with session_scope() as db:
        assert (await db.execute(text("SELECT current_user"))).scalar_one() == "blackmoa"
        assert (await db.execute(text("SHOW transaction_read_only"))).scalar_one() == "off"


# ── who may use it ──────────────────────────────────────────────────

async def test_it_is_closed_to_everyone_but_an_administrator(client: AsyncClient):
    _, user_tok = await signup(client, name="보통사람")
    for method, path in [("get", "/api/admin/diagnostics/db/tables"),
                         ("get", "/api/admin/diagnostics/db/columns?table=users"),
                         ("post", "/api/admin/diagnostics/db/query")]:
        anon = await getattr(client, method)(path)
        assert anon.status_code in (401, 403), f"anonymous reached {path}"
        as_user = await getattr(client, method)(path, headers=auth(user_tok), **({"json": {"sql": "SELECT 1"}} if method == "post" else {}))
        assert as_user.status_code == 403, f"a plain user reached {path}: {as_user.status_code}"


async def test_every_query_is_written_to_the_audit_log(admin_client):
    client, tok = admin_client
    from blackmoa.db.session import session_scope

    await run(client, tok, "SELECT 42 AS answer")
    await run(client, tok, "DROP TABLE users")
    async with session_scope() as db:
        rows = (await db.execute(text(
            "SELECT meta->>'sql' AS sql FROM audit_logs WHERE action = 'dbview_query' ORDER BY created_at DESC LIMIT 5"
        ))).scalars().all()
    assert any("SELECT 42" in (s or "") for s in rows)
    assert any("DROP TABLE" in (s or "") for s in rows), "a refused query left no trace"


async def test_people_do_not_read_what_google_gave_us(admin_client):
    """Limited Use (plan/73): 연동으로 가져온 메일·일정과 가져온 연락처가 들어가는 인맥은 관리자 조회로도 읽지 않는다."""
    client, tok = admin_client
    for table in ("integration_emails", "integration_events", "network_nodes"):
        r = await run(client, tok, f"SELECT * FROM {table} LIMIT 1")
        assert r.status_code >= 400, (table, r.status_code, r.text[:200])
    # 다른 표는 그대로 읽힌다.
    assert (await run(client, tok, "SELECT id FROM users LIMIT 1")).status_code == 200
