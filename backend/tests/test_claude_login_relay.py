"""The Claude Code device-login relay: the console pane and, above all, the box for the
pasted code. Regression cover for the two defects that made the flow unusable in prod:
the prompt never reaching the client, and it arriving split mid-word."""
from __future__ import annotations

import asyncio

import pytest

from memora.services.claude_code import LoginJob, _looks_like_prompt

pytestmark = pytest.mark.asyncio  # every async test here; the one sync check below is harmless

CLI_OUTPUT = [
    b"Opening browser to sign in\xe2\x80\xa6\n",
    b"If the browser didn't open, visit: https://claude.com/cai/oauth/authorize?code=true&client_id=x&state=y\n",
    b"Paste code here if prompte",   # the CLI's prompt, split across reads and newline-less
    b"d > ",
]


async def _feed(job: LoginJob, chunks: list[bytes]) -> None:
    reader = asyncio.StreamReader()
    task = asyncio.create_task(job._drain(reader))
    for c in chunks:
        reader.feed_data(c)
        await asyncio.sleep(0.05)
    await asyncio.sleep(0.5)          # let the idle flush fire
    reader.feed_eof()
    await asyncio.wait_for(task, timeout=2)


async def test_prompt_reaches_the_client_whole_and_opens_the_input_box():
    job = LoginJob(["/bin/true"])
    await _feed(job, CLI_OUTPUT)
    kinds = [e["kind"] for e in job.lines]
    assert "url" in kinds, "the OAuth URL must be surfaced as its own event"
    prompts = [e["text"] for e in job.lines if e["kind"] == "prompt"]
    assert prompts == ["Paste code here if prompted >"], prompts
    assert job.awaiting_input is True
    assert job.url and job.url.startswith("https://claude.com/cai/oauth/authorize")


async def test_login_failure_is_reported_as_an_error_not_a_log():
    job = LoginJob(["/bin/true"])
    await _feed(job, [b"Login failed: Request failed with status code 400\n"])
    assert [e["kind"] for e in job.lines if e["kind"] == "error"], job.lines


async def test_sending_input_without_a_process_is_a_clean_conflict():
    from memora.core.errors import Conflict
    job = LoginJob(["/bin/true"])
    with pytest.raises(Conflict):
        await job.send_input("code")


@pytest.mark.filterwarnings("ignore")
def test_prompt_detection():
    assert _looks_like_prompt("Paste code here if prompted >")
    assert _looks_like_prompt("Continue?")
    assert not _looks_like_prompt("Opening browser to sign in…")
    assert not _looks_like_prompt("   ")


async def test_browser_login_is_refused_for_key_based_auth_modes(client, app):
    """A key mode carries no session, so starting a browser login there is a user error,
    not a spawned CLI. (The console/subscription choice lives in the auth mode itself.)"""
    import uuid as _uuid

    from memora.db.session import session_scope
    from memora.models import User
    from memora.services import settings as S
    from tests.conftest import auth, signup

    admin, tok = await signup(client, f"cc-{_uuid.uuid4().hex[:6]}@example.com")
    async with session_scope() as db:
        u = await db.get(User, _uuid.UUID(admin["id"]))
        u.role = "admin"
    try:
        async with session_scope() as db:
            await S.put(db, "providers.claude_code.auth_mode", "api_key")
        r = await client.post("/api/admin/providers/claude-code/login/start", json={}, headers=auth(tok))
        assert r.status_code == 422, r.text
        assert r.json()["error"]["code"] == "login_not_applicable"
    finally:
        async with session_scope() as db:
            await S.put(db, "providers.claude_code.auth_mode", "oauth")
            u = await db.get(User, _uuid.UUID(admin["id"]))
            u.role = "user"   # sibling tests count admins


def test_an_existing_login_is_not_mistaken_for_a_new_one(tmp_path):
    """A relay finishes on the credential, so it must be a *new* credential (plan/38).

    Ending on "a valid credential exists" was a regression with teeth: an account that was
    already signed in reported "로그인 완료" the instant the CLI launched, before anyone had
    pasted a code — and the operator had no way to tell a real login from a no-op.
    """
    import json
    import time as _time

    from memora.services.claude_code import LoginJob

    cfg = tmp_path / "cfg"
    cfg.mkdir()
    live = {"claudeAiOauth": {"accessToken": "a", "refreshToken": "old",
                              "expiresAt": (_time.time() + 3600) * 1000, "refreshTokenExpiresAt": 1}}
    (cfg / ".credentials.json").write_text(json.dumps(live))

    job = LoginJob(["claude", "auth", "login"], home=tmp_path / "home", config_dir=cfg)
    assert job._new_credential_written() is False, "the credential that was already there is not a login"

    # the CLI writes a fresh one: same shape, different tokens
    fresh = {"claudeAiOauth": {"accessToken": "b", "refreshToken": "new",
                               "expiresAt": (_time.time() + 7200) * 1000, "refreshTokenExpiresAt": 2}}
    (cfg / ".credentials.json").write_text(json.dumps(fresh))
    assert job._new_credential_written() is True

    # and an empty directory: nothing there, nothing claimed
    empty = LoginJob(["claude"], home=tmp_path / "h2", config_dir=tmp_path / "c2")
    assert empty._new_credential_written() is False


async def test_a_wedged_probe_answers_instead_of_hanging(monkeypatch):
    """The verify button is a person waiting (plan/38).

    The cap used to cover only the model call, so a CLI that hung while *starting* left an
    admin watching a spinner. One cap now covers construction, call and teardown.
    """
    import asyncio

    from memora.services import claude_code as CC

    class _Wedged:
        def __init__(self, **_kw):
            pass

        async def create_message(self, **_kw):
            await asyncio.sleep(30)

        async def aclose(self):
            await asyncio.sleep(30)

    monkeypatch.setattr(CC, "PROBE_TIMEOUT_S", 0.2)

    class _Bundle:
        by_provider = {"claude_code_cli": object()}

    import geny_executor
    monkeypatch.setattr(geny_executor, "ClaudeCodeCLIClient", _Wedged, raising=False)
    monkeypatch.setattr("geny_executor.core.pipeline._creds_to_client_kwargs", lambda *_a, **_k: {}, raising=False)

    t0 = asyncio.get_running_loop().time()
    out = await CC.run_probe(_Bundle())
    assert out["ok"] is False and "timed out" in out["error"]
    assert asyncio.get_running_loop().time() - t0 < 2, "the cap did not fire, or teardown was awaited in front of it"
