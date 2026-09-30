from __future__ import annotations

import pytest
from httpx import AsyncClient

from tests.conftest import auth, signup

pytestmark = pytest.mark.asyncio


async def test_bootstrap_first_user_is_admin(client: AsyncClient):
    st = (await client.get("/api/auth/status")).json()
    assert st["bootstrap_needed"] is True
    admin, tok = await signup(client, "admin@example.com", "관리자")
    assert admin["role"] == "admin"
    user, tok2 = await signup(client, "user1@example.com", "한지민")
    assert user["role"] == "user"
    # admin-only endpoint
    assert (await client.get("/api/admin/overview", headers=auth(tok2))).status_code == 403
    assert (await client.get("/api/admin/overview", headers=auth(tok))).status_code == 200
    # unauthenticated gate
    assert (await client.get("/api/agents")).status_code == 401


