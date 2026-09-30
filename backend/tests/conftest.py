from __future__ import annotations

import asyncio
import os
import uuid

os.environ.setdefault("MEMORA_DATABASE_URL", "postgresql+asyncpg://memora:memora@127.0.0.1:55432/memora_test")
os.environ.setdefault("MEMORA_DATA_DIR", "/tmp/memora-test-data")
os.environ["MEMORA_FAKE_LLM"] = "1"
os.environ["MEMORA_RATELIMIT_DISABLED"] = "1"
os.environ["MEMORA_PUBLIC_URL"] = "http://testserver"
# The shipped admin seed would occupy the "first signup becomes admin" path; the
# seed itself is covered by tests/test_admin_security.py.
os.environ["MEMORA_DEFAULT_ADMIN_ENABLED"] = "0"
os.environ["MEMORA_CLAUDE_HOME"] = "/tmp/memora-test-data/claude"
os.environ.setdefault("OPENBLAS_NUM_THREADS", "1")

import pytest_asyncio  # noqa: E402
from httpx import ASGITransport, AsyncClient  # noqa: E402
from sqlalchemy import text  # noqa: E402


async def _reset_db():
    import asyncpg
    admin = await asyncpg.connect("postgresql://memora:memora@127.0.0.1:55432/memora")
    await admin.execute("SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname='memora_test' AND pid <> pg_backend_pid()")
    await admin.execute("DROP DATABASE IF EXISTS memora_test")
    await admin.execute("CREATE DATABASE memora_test")
    await admin.close()
    from alembic.config import Config

    from alembic import command
    cfg = Config("alembic.ini")
    await asyncio.to_thread(command.upgrade, cfg, "head")


@pytest_asyncio.fixture(scope="session")
async def app():
    await _reset_db()
    from memora.main import app as _app
    from memora.providers.llm.fake import register_fake
    register_fake()
    async with _app.router.lifespan_context(_app):
        from memora.db.session import session_scope
        from memora.models import ModelCatalog
        async with session_scope() as db:
            await db.execute(text("UPDATE model_catalog SET is_default=false"))
            db.add(ModelCatalog(provider="fake", model_id="fake-1", display_name="Fake", context_window=100000, max_output=4096,
                                credit_per_1k_input=1, credit_per_1k_output=2, credit_per_1k_cache_read=0.1, enabled=True, is_default=True, sort_order=0))
            from memora.services import settings as S
            await S.put(db, "embedding.provider", "hash")
            await S.put(db, "memory.distill_enabled", False)
            # Owning a secretary needs a verified address in production. Tests sign up
            # throwaway accounts with no mailbox, so the policy is off here and covered
            # on its own in test_domain.py::test_creating_a_secretary_needs_a_verified_email.
            await S.put(db, "signup.verify_before_agent", False)
            # Same shape: the production rule is on, tests sign up mailbox-less accounts,
            # and the rule itself is covered by test_community_writing_needs_a_verified_email.
            await S.put(db, "community.require_verified_email", False)
        yield _app


@pytest_asyncio.fixture
async def client(app):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as c:
        yield c


async def signup(client, email: str | None = None, name: str = "테스터") -> tuple[dict, str]:
    email = email or f"u{uuid.uuid4().hex[:8]}@example.com"
    r = await client.post("/api/auth/signup", json={"email": email, "password": "correct-horse-9", "display_name": name,
                                                    "agree_terms": True})
    assert r.status_code == 200, r.text
    j = r.json()
    return j["user"], j["access_token"]


async def square_name(client, token: str, name: str | None = None) -> str:
    """광장에 설 이름을 정한다 (plan/52).

    이름이 없으면 글을 쓸 수 없다. 광장을 건드리는 검사는 먼저 이것을 부른다 —
    진짜 사람도 그 순서로 한다.
    """
    # 이미 정해 두었으면 그대로 쓴다. 다시 정하면 주 1회 제한에 걸린다.
    got = (await client.get("/api/users/me/community-name", headers=auth(token))).json()
    if got["name"]:
        return got["name"]
    want = name or f"익명{uuid.uuid4().hex[:6]}"
    r = await client.put("/api/users/me/community-name", json={"name": want}, headers=auth(token))
    assert r.status_code == 200, r.text
    return r.json()["name"]


def auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


async def read_sse(resp) -> list[dict]:
    import json
    events = []
    buf = ""
    async for chunk in resp.aiter_text():
        buf += chunk
        while "\n\n" in buf:
            block, buf = buf.split("\n\n", 1)
            for line in block.split("\n"):
                if line.startswith("data: "):
                    events.append(json.loads(line[6:]))
    return events


async def provider_on(provider: str, on: bool = True) -> None:
    """관리자 [연결] 에서 공급자를 켜고 끈다 (plan/59). 꺼 둔 공급자의 데이터는 어디에도 보이지 않는다."""
    from memora.db.session import session_scope
    from memora.services import oauth as OA
    from memora.services import settings as S
    async with session_scope() as db:
        await S.put(db, f"oauth.{provider}.enabled", on)
        await S.put(db, f"oauth.{provider}.client_id", "cid" if on else "")
        await S.put(db, f"oauth.{provider}.client_secret", "sec" if on else "")
        await S.put(db, f"oauth.{provider}.features", [c.id for c in OA.get(provider).capabilities])
        await db.commit()
    S.invalidate("oauth.")


@pytest_asyncio.fixture
async def google_on(app):
    """이 검사 동안 관리자 [연결 → Google] 을 켜 둔다."""
    await provider_on("google")
    yield
    await provider_on("google", False)
