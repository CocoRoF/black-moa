"""A read-only window onto the database, for the console (plan/48).

An administrator with a SQL box is the most dangerous thing in this codebase, and the
danger is not hypothetical here: the application's database role is a **superuser**, so a
query is one `COPY … FROM PROGRAM` away from a shell on the database host and one
`pg_read_file` away from reading anything on it. A keyword filter is not an answer to that.
Regular expressions over SQL are a guessing game — comments, string literals, quoted
identifiers, dollar quoting, data-modifying CTEs — and the guess only has to be wrong once.

So the guarantees are taken from PostgreSQL itself, and the filter is only the first of
four layers:

  1. **Shape.** One statement, no semicolons, must begin as a SELECT, with a small
     blocklist for functions that read or break things without writing.
  2. **Structure.** The query is wrapped as ``SELECT * FROM ( … ) LIMIT n``. Anything that
     is not a SELECT is then a *syntax error* rather than a thing we hoped to have caught,
     and PostgreSQL refuses a data-modifying CTE anywhere but the top level — so the
     `WITH x AS (DELETE … RETURNING *) SELECT * FROM x` trick stops being expressible.
  3. **Privilege.** ``SET LOCAL ROLE`` drops to a role that holds nothing but SELECT, for
     the length of the transaction. Verified against the live database: `pg_read_file`
     comes back "permission denied for function".
  4. **Transaction.** ``SET TRANSACTION READ ONLY``, so every write path — including any
     this file failed to imagine — is refused by the server: "cannot execute DELETE in a
     read-only transaction".

On top of that: a statement timeout so a query cannot hold a connection, a row and cell
cap so a result cannot exhaust memory, and masking of the columns that hold password
hashes and credentials, so that even a stolen administrator session cannot read them out.
Every query is written to the audit log with its text.
"""
from __future__ import annotations

import re
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from blackmoa.core.errors import ValidationFailed
from blackmoa.core.logging import get_logger

log = get_logger("blackmoa.dbview")

#: The role queries run as. Holds SELECT on the public schema and nothing else.
ROLE = "blackmoa_dbview"
#: 관리자 조회로도 읽지 않는 표 — 이용자가 연결한 Google 계정에서 온 메일·일정, 가져온 연락처가 들어가는 인맥.
PRIVATE_TABLES = ("integration_emails", "integration_events", "network_nodes")

MAX_ROWS = 500
MAX_CELL = 2000          # characters; longer values are truncated with an ellipsis
TIMEOUT_MS = 5000

#: Things that do not write and so would survive a read-only transaction, but read the
#: server's files, break its connections, or simply never return. The privilege layer
#: already refuses most of them; this is so the refusal is a clear message rather than a
#: database error, and so a future grant cannot quietly re-open one.
_FORBIDDEN = re.compile(
    r"\b(pg_read_file|pg_read_binary_file|pg_ls_\w+|pg_stat_file|lo_import|lo_export|dblink\w*"
    r"|pg_terminate_backend|pg_cancel_backend|pg_sleep\w*|pg_reload_conf|pg_rotate_logfile"
    r"|set_config|pg_create_\w+|pg_drop_\w+|pg_promote|pg_switch_wal|copy)\b",
    re.I,
)

#: A statement has to begin as a query. Anything else is refused before it reaches the
#: database at all. EXPLAIN is deliberately absent: it cannot live inside the wrapper that
#: gives layer two its guarantee, and a confusing syntax error is a worse answer than a
#: clear refusal.
_STARTS = ("select", "with", "table", "values")

#: Columns whose contents an administrator has no reason to read out of a grid. Matched by
#: name, so a new table with a `password_hash` is covered the day it is created.
_SECRET_COL = re.compile(r"(password|secret|api_key|token|credential|private_key|encryption|_hash)$", re.I)
_SECRET_EXACT = {("system_settings", "value")}
MASK = "••••••"


def _strip_comments(sql: str) -> str:
    """Remove comments before anything looks at the text.

    `SELECT 1 -- ; DROP TABLE users` and its block-comment cousins are how a naive
    single-statement check gets talked around.
    """
    sql = re.sub(r"/\*.*?\*/", " ", sql, flags=re.S)
    sql = re.sub(r"--[^\n]*", " ", sql)
    return sql.strip()


def _split_statements(sql: str) -> list[str]:
    """Split on semicolons that are not inside a string or a quoted identifier."""
    out: list[str] = []
    buf: list[str] = []
    quote: str | None = None
    i = 0
    while i < len(sql):
        ch = sql[i]
        if quote:
            buf.append(ch)
            if ch == quote:
                # '' and "" are escaped quotes, not the end of one
                if i + 1 < len(sql) and sql[i + 1] == quote:
                    buf.append(sql[i + 1])
                    i += 2
                    continue
                quote = None
        elif ch in "'\"":
            quote = ch
            buf.append(ch)
        elif ch == ";":
            out.append("".join(buf))
            buf = []
        else:
            buf.append(ch)
        i += 1
    out.append("".join(buf))
    return [s.strip() for s in out if s.strip()]


def sanitize(sql: str) -> str:
    """Layer one. Returns the single statement to run, or raises with a plain reason."""
    raw = (sql or "").strip()
    if not raw:
        raise ValidationFailed("쿼리를 입력해 주세요.", code="empty_query")
    if len(raw) > 20_000:
        raise ValidationFailed("쿼리가 너무 길어요.", code="query_too_long")
    body = _strip_comments(raw)
    parts = _split_statements(body)
    if len(parts) != 1:
        raise ValidationFailed("한 번에 하나의 문장만 실행할 수 있어요.", code="multiple_statements")
    stmt = parts[0]
    first = re.match(r"[a-z_]+", stmt, re.I)
    if not first or first.group(0).lower() not in _STARTS:
        raise ValidationFailed("SELECT 문만 실행할 수 있어요.", code="not_a_select")
    hit = _FORBIDDEN.search(stmt)
    if hit:
        raise ValidationFailed(f"허용되지 않는 함수예요: {hit.group(0)}", code="forbidden_function")
    if re.search(r"\binto\b", stmt, re.I) and not re.search(r"\binto\s+strict\b", stmt, re.I):
        # SELECT … INTO creates a table; it is a write wearing a SELECT's clothes.
        raise ValidationFailed("SELECT ... INTO 는 사용할 수 없어요.", code="select_into")
    return stmt


async def ensure_role(db: AsyncSession) -> None:
    """Create the read-only role and keep its grants current.

    Idempotent, and re-run at startup so that tables added by a migration are covered — a
    table the role cannot read would otherwise look to an operator like a missing table.
    """
    await db.execute(text(f"""
        DO $$ BEGIN
            IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = '{ROLE}') THEN
                CREATE ROLE {ROLE} NOLOGIN;
            END IF;
        END $$;
    """))
    await db.execute(text(f"GRANT USAGE ON SCHEMA public TO {ROLE}"))
    await db.execute(text(f"GRANT SELECT ON ALL TABLES IN SCHEMA public TO {ROLE}"))
    await db.execute(text(f"ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT SELECT ON TABLES TO {ROLE}"))
    # 사람이 읽지 않는 표 (plan/73, 개인정보 처리방침 제8조 — Google API 서비스 사용자 데이터 정책의 Limited Use):
    # 연동으로 가져온 메일·일정, 그리고 가져온 연락처가 들어가는 인맥. 관리자 조회로도 열리지 않게 권한째 뺀다.
    for t in PRIVATE_TABLES:
        await db.execute(text(f"REVOKE SELECT ON TABLE {t} FROM {ROLE}"))
    # So that SET ROLE works even if this application ever stops being a superuser.
    await db.execute(text(f"GRANT {ROLE} TO CURRENT_USER"))


def _mask(table_hint: str, column: str) -> bool:
    if (table_hint, column.lower()) in _SECRET_EXACT:
        return True
    return bool(_SECRET_COL.search(column))


def _cell(v: Any) -> Any:
    if v is None or isinstance(v, bool | int | float):
        return v
    s = str(v)
    return s[:MAX_CELL] + "…" if len(s) > MAX_CELL else s


async def run_query(db: AsyncSession, sql: str, *, limit: int = 100, table_hint: str = "") -> dict[str, Any]:
    """Layers two, three and four. The session must be freshly opened and is never committed."""
    stmt = sanitize(sql)
    limit = max(1, min(int(limit or 100), MAX_ROWS))

    # Read-only first: PostgreSQL only accepts SET TRANSACTION before the transaction's
    # first query, so nothing may be executed above this line.
    await db.execute(text("SET TRANSACTION READ ONLY"))
    await db.execute(text(f"SET LOCAL statement_timeout = {TIMEOUT_MS}"))
    await db.execute(text(f"SET LOCAL ROLE {ROLE}"))
    try:
        # Wrapping is the structural guarantee: a non-SELECT here is a syntax error, and a
        # data-modifying CTE is rejected outright for not being at the top level.
        res = await db.execute(text(f"SELECT * FROM (\n{stmt}\n) AS _blackmoa_view LIMIT {limit}"))
        cols = list(res.keys())
        masked = {c for c in cols if _mask(table_hint, c)}
        rows = [
            {c: (MASK if (c in masked and r[i] is not None) else _cell(r[i])) for i, c in enumerate(cols)}
            for r in res.fetchall()
        ]
    except Exception as e:  # noqa: BLE001
        # The database's own refusal is the most useful thing we can show — "cannot execute
        # DELETE in a read-only transaction" says exactly what happened. It is returned as a
        # 400 with that one line: a rejected query is the administrator's mistake, not a
        # server fault, and a stack trace is neither an answer nor safe to render.
        raise ValidationFailed(_reason(e), code="query_failed") from e
    finally:
        # Always: the role and the read-only flag are transaction-scoped, so rolling back is
        # what hands the connection back to the pool as itself again.
        await db.rollback()
    return {"columns": cols, "rows": rows, "row_count": len(rows), "truncated": len(rows) >= limit,
            "masked": sorted(masked), "limit": limit, "sql": stmt}


def _reason(e: Exception) -> str:
    """The one line of a database error that means something, without the plumbing."""
    msg = getattr(getattr(e, "orig", None), "args", None)
    text_ = str(msg[0]) if msg else str(e)
    text_ = re.sub(r"^<class '[^']+'>:\s*", "", text_.strip())
    return (text_.splitlines()[0] if text_ else "쿼리를 실행할 수 없어요.")[:300]


async def list_tables(db: AsyncSession) -> list[dict[str, Any]]:
    """Every table, with an estimate of its size — the left-hand pane of the browser."""
    rows = (await db.execute(text("""
        SELECT c.relname AS name,
               greatest(c.reltuples, 0)::bigint AS rows_estimate,
               pg_total_relation_size(c.oid) AS bytes,
               obj_description(c.oid) AS comment
        FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
        WHERE n.nspname = 'public' AND c.relkind IN ('r', 'p', 'v', 'm')
        ORDER BY c.relname
    """))).mappings().all()
    return [{"name": r["name"], "rows": int(r["rows_estimate"]), "size_mb": round(int(r["bytes"]) / 1e6, 2),
             "comment": r["comment"]} for r in rows]


async def columns_of(db: AsyncSession, table: str) -> list[dict[str, Any]]:
    """The shape of one table. ``table`` is passed as a parameter, never interpolated."""
    rows = (await db.execute(text("""
        SELECT column_name AS name, data_type AS type, is_nullable = 'YES' AS nullable
        FROM information_schema.columns
        WHERE table_schema = 'public' AND table_name = :t
        ORDER BY ordinal_position
    """), {"t": table})).mappings().all()
    return [{"name": r["name"], "type": r["type"], "nullable": bool(r["nullable"]),
             "masked": _mask(table, r["name"])} for r in rows]
