"""The Claude Code account pool (plan/30).

Two layers, tested separately on purpose. The balancer is pure — a snapshot in, a decision
out — so the interesting questions ("does a limited account actually leave the rotation?",
"does a busy one get skipped?") are answered without a database or a subprocess. The pool
service is then tested against the real tables and the real credential files, because that
is where isolation between accounts either holds or does not.
"""
from __future__ import annotations

import json
import os
import pathlib
import time
import uuid as _uuid
from datetime import UTC, datetime

import pytest
from httpx import AsyncClient
from sqlalchemy import text

from memora.db.session import session_scope
from memora.models import ClaudeAccount, User
from memora.services import claude_balancer as B
from memora.services import claude_pool as CP
from tests.conftest import auth, signup

# No module-level asyncio marker: half of this file is synchronous by design (the balancer
# needs no event loop), and pytest's auto mode already handles the async half.
NOW = 1_800_000_000.0


def snap(sid: str, **kw) -> B.AccountSnapshot:
    return B.AccountSnapshot(id=sid, label=sid, **kw)


def fake_credentials(*, session_days: float = 30.0, access_hours: float = 8.0) -> dict:
    ms = time.time() * 1000
    return {"claudeAiOauth": {"accessToken": f"sk-ant-oat-{_uuid.uuid4().hex}", "refreshToken": "rt-secret",
                              "expiresAt": ms + access_hours * 3600 * 1000,
                              "refreshTokenExpiresAt": ms + session_days * 86400 * 1000,
                              "subscriptionType": "max", "rateLimitTier": "tier_2", "scopes": ["user:inference"]}}


# ── balancer: who gets the next session ────────────────────────────

def test_round_robin_visits_every_eligible_account_before_repeating():
    accounts = [snap("a"), snap("b"), snap("c")]
    state = B.BalancerState()
    picks = [B.choose(accounts, strategy="round_robin", now=NOW, state=state).id for _ in range(6)]
    assert picks == ["a", "b", "c", "a", "b", "c"]


def test_weighted_interleaves_rather_than_bursting_on_the_heavy_account():
    """Smooth weighted round-robin: 3:1 must come out A A B A, not A A A B.

    Bursting is not a cosmetic difference — three consecutive sessions on one subscription
    is exactly the shape that trips its rate limit while the other account idles.
    """
    accounts = [snap("a", weight=3), snap("b", weight=1)]
    state = B.BalancerState()
    picks = [B.choose(accounts, strategy="weighted", now=NOW, state=state).id for _ in range(8)]
    assert picks == ["a", "a", "b", "a", "a", "a", "b", "a"]
    assert picks.count("a") == 6 and picks.count("b") == 2


def test_least_busy_measures_load_against_each_accounts_own_ceiling():
    # 3/12 is a quarter used; 2/4 is half used. Fewer in flight is not the same as less busy.
    busy_but_roomy = snap("roomy", in_flight=3, max_concurrency=12)
    idle_looking = snap("tight", in_flight=2, max_concurrency=4)
    assert B.choose([busy_but_roomy, idle_looking], strategy="least_busy", now=NOW).id == "roomy"


def test_an_account_at_its_concurrency_ceiling_is_skipped():
    full = snap("full", in_flight=4, max_concurrency=4)
    free = snap("free", in_flight=3, max_concurrency=4)
    assert B.ineligible_reason(full, now=NOW) == "at_capacity"
    assert B.choose([full, free], strategy="round_robin", now=NOW).id == "free"


def test_cooling_down_disabled_expired_and_credential_less_accounts_are_out_of_rotation():
    cases = {
        "cooling": (snap("cooling", cooldown_until=NOW + 60), "cooling_down"),
        "off": (snap("off", enabled=False), "disabled"),
        "dead": (snap("dead", status="expired"), "expired"),
        "empty": (snap("empty", usable=False), "no_credentials"),
    }
    for _name, (account, reason) in cases.items():
        assert B.ineligible_reason(account, now=NOW) == reason
    healthy = snap("ok")
    assert B.ineligible_reason(healthy, now=NOW) is None
    assert B.choose([c for c, _ in cases.values()] + [healthy], strategy="least_busy", now=NOW).id == "ok"


def test_a_cooldown_ends_by_itself():
    a = snap("a", cooldown_until=NOW + 60)
    assert B.choose([a], strategy="least_busy", now=NOW) is None
    assert B.choose([a], strategy="least_busy", now=NOW + 61) is not None


def test_no_eligible_account_returns_none_so_the_caller_can_fall_back():
    assert B.choose([snap("a", enabled=False)], strategy="least_busy", now=NOW) is None
    assert B.choose([], strategy="least_busy", now=NOW) is None


# ── balancer: health state machine ─────────────────────────────────

def test_a_rate_limited_account_rests_for_the_configured_window():
    d = B.apply_outcome(snap("a"), ok=False, code="rate_limited", now=NOW,
                        policy=B.HealthPolicy(rate_limit_cooldown_s=900))
    assert d.status == "cooldown" and d.cooldown_until == NOW + 900


def test_a_quota_failure_rests_longer_than_a_rate_limit():
    p = B.HealthPolicy(rate_limit_cooldown_s=900, quota_cooldown_s=3600)
    rate = B.apply_outcome(snap("a"), ok=False, code="rate_limited", now=NOW, policy=p)
    quota = B.apply_outcome(snap("a"), ok=False, code="provider_quota", now=NOW, policy=p)
    assert quota.cooldown_until > rate.cooldown_until


def test_a_dead_session_is_marked_expired_not_merely_cooled():
    """Waiting does not fix a logged-out account; it needs a human. A cooldown would put it
    straight back into rotation to fail again."""
    d = B.apply_outcome(snap("a"), ok=False, code="provider_auth", now=NOW)
    assert d.status == "expired" and d.cooldown_until == 0.0


def test_failures_that_are_not_the_accounts_fault_leave_its_health_alone():
    a = snap("a", consecutive_failures=1)
    for code in ("context_limit", "cancelled", "credits_exhausted"):
        d = B.apply_outcome(a, ok=False, code=code, now=NOW)
        assert (d.status, d.consecutive_failures, d.changed) == ("ready", 1, False), code


def test_repeated_unexplained_failures_open_the_circuit_with_growing_backoff():
    p = B.HealthPolicy(failure_threshold=3, failure_cooldown_s=120)
    a = snap("a")
    for _ in range(2):
        d = B.apply_outcome(a, ok=False, code="unknown", now=NOW, policy=p)
        a = snap("a", consecutive_failures=d.consecutive_failures, status=d.status)
        assert d.cooldown_until == 0.0, "a couple of failures is not an outage"
    third = B.apply_outcome(a, ok=False, code="unknown", now=NOW, policy=p)
    assert third.status == "cooldown" and third.cooldown_until == NOW + 120
    fourth = B.apply_outcome(snap("a", consecutive_failures=3), ok=False, code="unknown", now=NOW, policy=p)
    assert fourth.cooldown_until == NOW + 240


def test_one_success_clears_everything():
    sick = snap("a", status="cooldown", consecutive_failures=5, cooldown_until=NOW + 900)
    d = B.apply_outcome(sick, ok=True, now=NOW)
    assert (d.status, d.consecutive_failures, d.cooldown_until) == ("ready", 0, 0.0)


# ── the pool service, against the real database and real files ─────

async def _admin(client: AsyncClient) -> tuple[dict, str]:
    user, tok = await signup(client, f"pool-{_uuid.uuid4().hex[:6]}@example.com")
    async with session_scope() as db:
        u = await db.get(User, _uuid.UUID(user["id"]))
        u.role = "admin"
    return user, tok


async def _cleanup(ids: list[str]) -> None:
    """Put the pool back to empty. Bypasses `CP.delete` on purpose: the "never remove the
    last account" rule is a product rule for the console, not one about teardown, and every
    account this file adds — adopted or created — has to go."""
    async with session_scope() as db:
        for acc in await CP.list_accounts(db):
            CP._live.forget(str(acc.id))
            CP.remove_home(acc.id)
            await db.delete(acc)
        _ = ids


@pytest.fixture
async def admin_client(client: AsyncClient):
    """An admin plus a promise to leave the install exactly as it was found.

    Sibling tests count administrators, and every one of them builds pipelines against a
    pool that is supposed to be empty.
    """
    user, tok = await _admin(client)
    created: list[str] = []
    yield client, tok, created
    await _cleanup(created)
    async with session_scope() as db:
        u = await db.get(User, _uuid.UUID(user["id"]))
        u.role = "user"


async def test_accounts_round_trip_through_the_admin_api(admin_client):
    client, tok, created = admin_client
    r = await client.post("/api/admin/providers/claude-code/accounts",
                          json={"label": "team-a", "email": "a@example.com", "weight": 3, "max_concurrency": 2},
                          headers=auth(tok))
    assert r.status_code == 200, r.text
    acc = r.json()
    created.append(acc["id"])
    assert acc["label"] == "team-a" and acc["weight"] == 3 and acc["status"] == "unknown"
    # A brand-new account holds no credential, so it must not be handed any traffic.
    assert acc["eligible"] is False and acc["ineligible_reason"] == "no_credentials"

    dup = await client.post("/api/admin/providers/claude-code/accounts", json={"label": "team-a"}, headers=auth(tok))
    assert dup.status_code == 409 and dup.json()["error"]["code"] == "label_taken"

    patched = await client.patch(f"/api/admin/providers/claude-code/accounts/{acc['id']}",
                                 json={"enabled": False, "weight": 7}, headers=auth(tok))
    assert patched.status_code == 200 and patched.json()["weight"] == 7
    assert patched.json()["ineligible_reason"] == "disabled"

    listing = (await client.get("/api/admin/providers/claude-code/accounts", headers=auth(tok))).json()
    # The install's own login is row one (adopted), and this test's account sits beside it.
    assert any(x["id"] == acc["id"] for x in listing["accounts"]) and listing["strategy"] in B.STRATEGIES
    assert listing["active"] is False, "an account without credentials must not make the pool active"

    assert (await client.delete(f"/api/admin/providers/claude-code/accounts/{acc['id']}",
                                headers=auth(tok))).status_code == 200
    created.clear()
    after = (await client.get("/api/admin/providers/claude-code/accounts", headers=auth(tok))).json()
    assert not any(x["id"] == acc["id"] for x in after["accounts"]), "the account this test made is gone"


async def test_imported_credentials_are_encrypted_at_rest_and_written_private_on_disk(admin_client):
    client, tok, created = admin_client
    acc = (await client.post("/api/admin/providers/claude-code/accounts", json={"label": "vault"},
                             headers=auth(tok))).json()
    created.append(acc["id"])
    creds = fake_credentials()
    token = creds["claudeAiOauth"]["accessToken"]
    r = await client.post(f"/api/admin/providers/claude-code/accounts/{acc['id']}/import",
                          json={"credentials_json": json.dumps(creds)}, headers=auth(tok))
    assert r.status_code == 200, r.text
    out = r.json()
    assert out["status"] == "ready" and out["subscription"] == "max" and out["eligible"] is True

    path = CP.creds_path_for(acc["id"])
    assert path.exists(), "the CLI reads a file, so the file has to exist"
    assert oct(os.stat(path).st_mode)[-3:] == "600", "a live session token must not be world readable"
    assert json.loads(path.read_text())["claudeAiOauth"]["accessToken"] == token

    async with session_scope() as db:
        raw = (await db.execute(text("SELECT credentials_json FROM claude_accounts WHERE id = :i"),
                                {"i": acc["id"]})).scalar_one()
    assert token not in raw, "a database dump must not be a set of live sessions"


async def test_a_bad_credential_blob_is_rejected_before_it_reaches_the_disk(admin_client):
    client, tok, created = admin_client
    acc = (await client.post("/api/admin/providers/claude-code/accounts", json={"label": "picky"},
                             headers=auth(tok))).json()
    created.append(acc["id"])
    for body, code in (("not json at all", "invalid_json"), ('{"claudeAiOauth": {}}', "invalid_credentials_shape")):
        r = await client.post(f"/api/admin/providers/claude-code/accounts/{acc['id']}/import",
                              json={"credentials_json": body}, headers=auth(tok))
        assert r.status_code == 422 and r.json()["error"]["code"] == code
    assert not CP.creds_path_for(acc["id"]).exists()


async def test_a_key_based_account_has_no_browser_login_to_start(admin_client):
    client, tok, created = admin_client
    acc = (await client.post("/api/admin/providers/claude-code/accounts",
                             json={"label": "token-only", "auth_mode": "setup_token"}, headers=auth(tok))).json()
    created.append(acc["id"])
    r = await client.post(f"/api/admin/providers/claude-code/accounts/{acc['id']}/login/start", json={},
                          headers=auth(tok))
    assert r.status_code == 422 and r.json()["error"]["code"] == "login_not_applicable"


async def test_probing_an_account_with_no_credentials_says_so_instead_of_spawning_a_cli(admin_client):
    client, tok, created = admin_client
    acc = (await client.post("/api/admin/providers/claude-code/accounts", json={"label": "empty"},
                             headers=auth(tok))).json()
    created.append(acc["id"])
    r = await client.post(f"/api/admin/providers/claude-code/accounts/{acc['id']}/probe", headers=auth(tok))
    assert r.status_code == 200 and r.json()["ok"] is False
    assert "credentials_missing" in r.json()["error"]


async def test_an_empty_pool_leases_nothing_so_single_account_installs_are_untouched():
    async with session_scope() as db:
        assert await CP.acquire(db) is None
        assert await CP.enabled(db) is False


async def test_a_leased_session_runs_in_its_own_cli_home(admin_client):
    """The isolation the whole feature rests on: HOME *and* CLAUDE_CONFIG_DIR point at the
    leased account's directory, so one subscription can never read another's tokens."""
    from memora.providers.llm.credentials import build_bundle

    client, tok, created = admin_client
    acc = (await client.post("/api/admin/providers/claude-code/accounts", json={"label": "isolated"},
                             headers=auth(tok))).json()
    created.append(acc["id"])
    await client.post(f"/api/admin/providers/claude-code/accounts/{acc['id']}/import",
                      json={"credentials_json": json.dumps(fake_credentials())}, headers=auth(tok))
    async with session_scope() as db:
        lease = await CP.acquire(db)
        assert lease is not None and str(lease.account_id) == acc["id"]
        try:
            bundle = await build_bundle(db, "claude_code", session_id="s", bridge_token="t", cwd="/tmp", lease=lease)
            env = bundle.by_provider["claude_code_cli"].extras["env_extras"]
            assert env["HOME"] == str(CP.home_for(acc["id"]))
            assert env["CLAUDE_CONFIG_DIR"] == str(CP.config_dir_for(acc["id"]))
            assert bundle.by_provider["claude_code_cli"].api_key == "", "subscription auth never carries an API key"
            assert CP.in_flight_of(acc["id"]) == 1
        finally:
            lease.release()
    assert CP.in_flight_of(acc["id"]) == 0, "a released lease frees the slot"


async def test_a_rate_limited_account_hands_the_next_session_to_its_sibling(admin_client):
    client, tok, created = admin_client
    ids = []
    for label in ("first", "second"):
        a = (await client.post("/api/admin/providers/claude-code/accounts",
                               json={"label": label, "max_concurrency": 8}, headers=auth(tok))).json()
        created.append(a["id"])
        ids.append(a["id"])
        await client.post(f"/api/admin/providers/claude-code/accounts/{a['id']}/import",
                          json={"credentials_json": json.dumps(fake_credentials())}, headers=auth(tok))

    async with session_scope() as db:
        await client.put("/api/admin/providers/claude-code/pool", json={"strategy": "round_robin"}, headers=auth(tok))
        first = await CP.acquire(db)
        assert first is not None
        # The provider said 429: this account has to leave the rotation, and the session
        # that hit it must not simply retry into the same wall.
        decision = await CP.report(db, first, ok=False, code="rate_limited", error="429 rate limit")
        assert decision is not None and decision.status == "cooldown"

        second = await CP.acquire(db)
        assert second is not None and second.account_id != first.account_id
        await CP.report(db, second, ok=False, code="rate_limited", error="429 rate limit")

        # Both resting → the pool says so honestly rather than handing out a doomed lease.
        assert await CP.acquire(db) is None

    # An operator who knows the limit has reset can put one back immediately.
    r = await client.post(f"/api/admin/providers/claude-code/accounts/{ids[0]}/cooldown/clear", headers=auth(tok))
    assert r.status_code == 200 and r.json()["eligible"] is True
    async with session_scope() as db:
        again = await CP.acquire(db)
        assert again is not None and str(again.account_id) == ids[0]
        again.release()


async def test_health_is_persisted_so_every_worker_sees_the_same_verdict(admin_client):
    client, tok, created = admin_client
    acc = (await client.post("/api/admin/providers/claude-code/accounts", json={"label": "durable"},
                             headers=auth(tok))).json()
    created.append(acc["id"])
    await client.post(f"/api/admin/providers/claude-code/accounts/{acc['id']}/import",
                      json={"credentials_json": json.dumps(fake_credentials())}, headers=auth(tok))
    async with session_scope() as db:
        lease = await CP.acquire(db)
        await CP.report(db, lease, ok=False, code="provider_auth", error="not logged in")
    view = (await client.get("/api/admin/providers/claude-code/accounts", headers=auth(tok))).json()
    row = view["accounts"][0]
    assert row["status"] == "expired" and row["ineligible_reason"] == "expired"
    assert row["total_failures"] == 1 and "provider_auth" in row["last_error"]
    assert view["counts"]["eligible"] == 0


async def test_neutral_turn_failures_do_not_take_a_healthy_account_out_of_rotation(admin_client):
    client, tok, created = admin_client
    acc = (await client.post("/api/admin/providers/claude-code/accounts", json={"label": "innocent"},
                             headers=auth(tok))).json()
    created.append(acc["id"])
    await client.post(f"/api/admin/providers/claude-code/accounts/{acc['id']}/import",
                      json={"credentials_json": json.dumps(fake_credentials())}, headers=auth(tok))
    async with session_scope() as db:
        for _ in range(5):
            lease = await CP.acquire(db)
            assert lease is not None, "a conversation being too long is not the account's fault"
            await CP.report(db, lease, ok=False, code="context_limit", error="prompt is too long")
    row = (await client.get("/api/admin/providers/claude-code/accounts", headers=auth(tok))).json()["accounts"][0]
    assert row["eligible"] is True and row["consecutive_failures"] == 0


async def test_the_hourly_sync_harvests_a_token_the_cli_refreshed_by_itself(admin_client):
    """The CLI rotates the access token in its own file. If that never came back to the
    database, a container restart would hand the pool a stale credential."""
    client, tok, created = admin_client
    acc = (await client.post("/api/admin/providers/claude-code/accounts", json={"label": "refresher"},
                             headers=auth(tok))).json()
    created.append(acc["id"])
    await client.post(f"/api/admin/providers/claude-code/accounts/{acc['id']}/import",
                      json={"credentials_json": json.dumps(fake_credentials(access_hours=1))}, headers=auth(tok))
    refreshed = fake_credentials(access_hours=9)
    CP.creds_path_for(acc["id"]).write_text(json.dumps(refreshed))

    async with session_scope() as db:
        report = await CP.sync_all(db)
        assert report["harvested"] == 1
        stored = json.loads(__import__("memora.core.security", fromlist=["decrypt"]).decrypt(
            (await db.get(ClaudeAccount, _uuid.UUID(acc["id"]))).credentials_json))
    assert stored["claudeAiOauth"]["accessToken"] == refreshed["claudeAiOauth"]["accessToken"]

    # And the guard in the other direction: an older file never overwrites a newer backup.
    CP.creds_path_for(acc["id"]).write_text(json.dumps(fake_credentials(access_hours=0.5)))
    async with session_scope() as db:
        assert (await CP.sync_all(db))["harvested"] == 0


async def test_deleting_an_account_takes_its_credential_file_with_it(admin_client):
    client, tok, created = admin_client
    # A second account, because removing the only one is refused: the pool is the provider.
    keep = (await client.post("/api/admin/providers/claude-code/accounts", json={"label": "keeper"},
                              headers=auth(tok))).json()
    created.append(keep["id"])
    acc = (await client.post("/api/admin/providers/claude-code/accounts", json={"label": "temporary"},
                             headers=auth(tok))).json()
    await client.post(f"/api/admin/providers/claude-code/accounts/{acc['id']}/import",
                      json={"credentials_json": json.dumps(fake_credentials())}, headers=auth(tok))
    assert CP.creds_path_for(acc["id"]).exists()
    assert (await client.delete(f"/api/admin/providers/claude-code/accounts/{acc['id']}",
                                headers=auth(tok))).status_code == 200
    assert not CP.creds_path_for(acc["id"]).exists(), "a removed account must not leave a live token on disk"
    # …and not the rest of the CLI home either: `.claude.json` names the account that
    # signed in, and `backups/` keeps copies of it.
    assert not CP.home_for(acc["id"]).exists(), "a removed account must not leave its CLI home behind"
    assert acc["id"] not in created


async def test_a_home_outside_the_account_root_is_never_removed(tmp_path):
    """`remove_home` deletes a tree. It must be impossible to talk it into deleting one
    that is not an account's — a malformed id is not a reason to lose /data."""
    outsider = tmp_path / "not-an-account"
    outsider.mkdir()
    CP.remove_home("../../..")
    CP.remove_home("")
    assert outsider.exists()
    assert pathlib.Path(CP.get_settings().data_dir).exists(), "the data directory itself survives"


async def test_the_pool_can_be_switched_off_without_deleting_anything(admin_client):
    client, tok, created = admin_client
    acc = (await client.post("/api/admin/providers/claude-code/accounts", json={"label": "parked"},
                             headers=auth(tok))).json()
    created.append(acc["id"])
    await client.post(f"/api/admin/providers/claude-code/accounts/{acc['id']}/import",
                      json={"credentials_json": json.dumps(fake_credentials())}, headers=auth(tok))
    try:
        off = (await client.put("/api/admin/providers/claude-code/pool", json={"enabled": False},
                                headers=auth(tok))).json()
        assert off["enabled"] is False and off["active"] is False
        async with session_scope() as db:
            assert await CP.acquire(db) is None, "switched off means the single-account path again"
        bad = await client.put("/api/admin/providers/claude-code/pool", json={"strategy": "vibes"}, headers=auth(tok))
        assert bad.status_code == 422 and bad.json()["error"]["code"] == "bad_strategy"
    finally:
        await client.put("/api/admin/providers/claude-code/pool",
                         json={"enabled": True, "strategy": "least_busy"}, headers=auth(tok))


async def test_a_background_failure_still_takes_the_account_out_of_rotation(admin_client, monkeypatch):
    """Distillation and summaries run inside the worker, and the worker rolls its session
    back when a handler raises (``worker/__main__.run_job``). A cooldown written into that
    session goes with it — so a rate-limited account would keep taking background work
    forever, on the exact path the pool exists to protect.
    """
    from geny_executor.llm_client.registry import ClientRegistry

    from memora.providers.llm import simple

    client, tok, created = admin_client
    acc = (await client.post("/api/admin/providers/claude-code/accounts", json={"label": "background"},
                             headers=auth(tok))).json()
    created.append(acc["id"])
    await client.post(f"/api/admin/providers/claude-code/accounts/{acc['id']}/import",
                      json={"credentials_json": json.dumps(fake_credentials())}, headers=auth(tok))

    class _Limited:
        def __init__(self, **kw):
            pass

        async def create_message(self, **kw):
            raise RuntimeError("429 rate limit exceeded")

        async def aclose(self):
            return None

    monkeypatch.setattr(ClientRegistry, "get", lambda *a, **k: _Limited)

    async with session_scope() as db:
        with pytest.raises(RuntimeError):
            await simple.complete(db, provider="claude_code", model="haiku", system="s", user_text="u")
        await db.rollback()   # exactly what the worker does with a failed handler

    async with session_scope() as db:
        fresh = await db.get(ClaudeAccount, _uuid.UUID(acc["id"]))
        assert fresh.status == "cooldown", "the 429 verdict has to survive the caller's rollback"
        assert fresh.cooldown_until is not None
    assert CP.in_flight_of(acc["id"]) == 0, "the lease is released even when the call blew up"


async def test_one_unwritable_account_is_skipped_instead_of_collapsing_the_pool(admin_client, monkeypatch):
    """A credential that cannot be written to disk is that account's problem, not the
    pool's. Returning None here would drop the whole install back to the legacy single
    credential because one member of two has an unwritable directory.
    """
    client, tok, created = admin_client
    ids = []
    for label in ("unwritable", "healthy"):
        a = (await client.post("/api/admin/providers/claude-code/accounts", json={"label": label},
                               headers=auth(tok))).json()
        created.append(a["id"])
        ids.append(a["id"])
        await client.post(f"/api/admin/providers/claude-code/accounts/{a['id']}/import",
                          json={"credentials_json": json.dumps(fake_credentials())}, headers=auth(tok))
    broken, healthy = ids
    await client.put("/api/admin/providers/claude-code/pool", json={"strategy": "least_recently_used"},
                     headers=auth(tok))

    real = CP.materialize

    def _fails_for_the_broken_one(a):
        if str(a.id) == broken:
            raise OSError("read-only file system")
        return real(a)

    async with session_scope() as db:
        # Make the broken account the one the strategy must reach for first, so the test
        # is about the skip and not about which id happened to sort lower.
        (await db.get(ClaudeAccount, _uuid.UUID(healthy))).last_used_at = datetime.now(UTC)
        (await db.get(ClaudeAccount, _uuid.UUID(broken))).last_used_at = None

    monkeypatch.setattr(CP, "materialize", _fails_for_the_broken_one)
    async with session_scope() as db:
        lease = await CP.acquire(db)
        assert lease is not None, "the pool still has a healthy member to serve from"
        assert str(lease.account_id) == healthy
        lease.release()

    assert CP.in_flight_of(broken) == 0, "the slot taken for the failed attempt is handed back"
    async with session_scope() as db:
        assert (await db.get(ClaudeAccount, _uuid.UUID(broken))).consecutive_failures == 1


# ── one provider, one list ─────────────────────────────────────────

async def test_the_existing_login_becomes_account_one(admin_client):
    """An install that already had a Claude Code login must not end up with two places to
    look. Opening the page adopts it as the first row."""
    from memora.services import settings as S

    client, tok, created = admin_client
    async with session_scope() as db:
        await S.put(db, "providers.claude_code.auth_mode", "oauth")
        await S.put(db, "providers.claude_code.credentials_json", json.dumps(fake_credentials()))

    pool = (await client.get("/api/admin/providers/claude-code/accounts", headers=auth(tok))).json()
    assert pool["counts"]["total"] == 1
    row = pool["accounts"][0]
    created.append(row["id"])
    assert row["label"] == CP.DEFAULT_LABEL and row["usable"] is True and row["eligible"] is True

    # Idempotent: a second look does not mint a second row.
    again = (await client.get("/api/admin/providers/claude-code/accounts", headers=auth(tok))).json()
    assert again["counts"]["total"] == 1


async def test_the_last_account_cannot_be_removed(admin_client):
    """The pool is the provider; a list with nothing in it has nothing to authenticate."""
    client, tok, created = admin_client
    a = (await client.post("/api/admin/providers/claude-code/accounts", json={"label": "only-one"},
                           headers=auth(tok))).json()
    created.append(a["id"])
    async with session_scope() as db:
        others = [x for x in await CP.list_accounts(db) if str(x.id) != a["id"]]
        for o in others:
            await db.delete(o)
    r = await client.delete(f"/api/admin/providers/claude-code/accounts/{a['id']}", headers=auth(tok))
    assert r.status_code == 409 and r.json()["error"]["code"] == "last_account"

    b = (await client.post("/api/admin/providers/claude-code/accounts", json={"label": "second"},
                           headers=auth(tok))).json()
    created.append(b["id"])
    assert (await client.delete(f"/api/admin/providers/claude-code/accounts/{b['id']}", headers=auth(tok))).status_code == 200


def test_a_full_account_is_still_asked_before_a_conversation_fails():
    """Capacity is a balancing hint, not a wall (plan/38).

    A session holds its account for the whole conversation, so a handful of open chats
    used to exhaust the ceiling and every further conversation was refused outright — with
    the account signed in, healthy and perfectly able to answer.
    """
    from memora.services import claude_balancer as B

    full = B.AccountSnapshot(id="a", label="a", max_concurrency=2, in_flight=2)
    fuller = B.AccountSnapshot(id="b", label="b", max_concurrency=2, in_flight=5)
    broken = B.AccountSnapshot(id="c", label="c", usable=False)
    now = 1000.0

    assert B.choose([full, fuller, broken], now=now) is None          # nothing under its ceiling
    assert B.ineligible_reason(full, now=now) == "at_capacity"
    # …but a full account is asked anyway, least loaded first
    assert B.over_capacity([full, fuller, broken], now=now).id == "a"
    # a pool with nothing usable stays empty: that is a real refusal, not a busy one
    assert B.over_capacity([broken], now=now) is None
    # and while anything is under its ceiling, the normal path is untouched
    free = B.AccountSnapshot(id="d", label="d", max_concurrency=4, in_flight=1)
    assert B.choose([full, free], now=now).id == "d"
