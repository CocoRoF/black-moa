"""Two refreshes at once must not sign a person out of everything (plan/47).

Refresh tokens rotate, and reuse detection revokes the whole family — correct against a
stolen token, and wrong against the ordinary case of a client sending two refreshes before
either reply comes back. Production recorded seventy of these; the only symptom a person
sees is being logged out for no reason.
"""
from __future__ import annotations

import asyncio

import pytest
from httpx import AsyncClient

from tests.conftest import signup

pytestmark = pytest.mark.asyncio


async def _cookie(client: AsyncClient) -> str:
    await signup(client, name="갱신")
    return client.cookies.get("memora_refresh") or ""


async def test_two_simultaneous_refreshes_both_succeed(client: AsyncClient):
    """The race itself: one cookie, two requests, nobody logged out."""
    tok = await _cookie(client)
    assert tok, "signup did not set a refresh cookie"

    a, b = await asyncio.gather(
        client.post("/api/auth/refresh", cookies={"memora_refresh": tok}),
        client.post("/api/auth/refresh", cookies={"memora_refresh": tok}),
        return_exceptions=True,
    )
    codes = sorted(r.status_code for r in (a, b))
    assert codes == [200, 200], f"a racing refresh was treated as theft: {codes}"

    # …and the session still works afterwards, which is the part that actually broke
    newest = b.json()["access_token"]
    me = await client.get("/api/auth/me", headers={"authorization": f"Bearer {newest}"})
    assert me.status_code == 200


async def test_a_token_replayed_later_is_still_treated_as_theft(client: AsyncClient):
    """The grace window must not cost the protection it is widening."""
    from memora.services import accounts as A

    tok = await _cookie(client)
    first = await client.post("/api/auth/refresh", cookies={"memora_refresh": tok})
    assert first.status_code == 200

    grace, A.REFRESH_GRACE_S = A.REFRESH_GRACE_S, 0.0   # the same replay, just not racing
    try:
        again = await client.post("/api/auth/refresh", cookies={"memora_refresh": tok})
    finally:
        A.REFRESH_GRACE_S = grace
    assert again.status_code == 401, "a replayed token was accepted"

    # and the family is gone: the successor must not keep working either
    successor = first.cookies.get("memora_refresh")
    assert (await client.post("/api/auth/refresh", cookies={"memora_refresh": successor})).status_code == 401


async def test_a_chain_of_racing_refreshes_stays_usable(client: AsyncClient):
    """A page that fires several on load — the shape this actually takes in a browser."""
    tok = await _cookie(client)
    results = await asyncio.gather(*[
        client.post("/api/auth/refresh", cookies={"memora_refresh": tok}) for _ in range(4)
    ])
    assert all(r.status_code == 200 for r in results), [r.status_code for r in results]
    last = results[-1].json()["access_token"]
    assert (await client.get("/api/auth/me", headers={"authorization": f"Bearer {last}"})).status_code == 200
