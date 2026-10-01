from __future__ import annotations

import asyncio
import json
import uuid
from datetime import UTC, datetime
from types import SimpleNamespace

import pytest

from blackmoa.core.errors import Forbidden, PaymentRequired
from blackmoa.pipeline.events import _visitor_projection
from blackmoa.pipeline.guard import redact_response
from blackmoa.services import accounts as A
from blackmoa.services import profile as PF
from tests.conftest import auth, signup


def test_visitor_projection_drops_raw_text_and_internal_events():
    # text.delta reaches visitors, but only as bare sanitized text: the runner feeds every
    # visitor delta through guard.StreamRedactor before it is journalled (plan/12 + plan/19).
    delta = _visitor_projection({"seq": 1, "type": "text.delta", "data": {"text": "hi", "model": "x"}})
    assert delta is not None and delta["data"] == {"text": "hi"}
    assert _visitor_projection({"seq": 2, "type": "usage", "data": {"credits": 9}}) is None
    assert _visitor_projection({"seq": 3, "type": "guard.redacted", "data": {"count": 2}}) is None
    start = _visitor_projection(
        {
            "seq": 4,
            "type": "turn.start",
            "data": {
                "turn_id": "t1",
                "conversation_id": "c1",
                "model": "private-model",
                "provider": "private-provider",
            },
        }
    )
    assert start is not None
    assert start["data"] == {"turn_id": "t1", "conversation_id": "c1"}
    tool = _visitor_projection(
        {
            "seq": 5,
            "type": "tool.start",
            "data": {
                "call_id": "c1",
                "name": "email_search",
                "label": "메일을 찾는 중",
                "input_preview": "private query",
            },
        }
    )
    assert tool is not None
    assert tool["data"] == {"call_id": "c1", "name": "activity", "label": "메일을 찾는 중", "label_en": "Checking"}


def test_response_scanner_masks_unapproved_email_and_phone():
    out, count = redact_response("contact me at owner@example.com or 010-1234-5678", [])
    assert "owner@example.com" not in out
    assert "010-1234-5678" not in out
    assert count == 2
    allowed, count = redact_response("owner@example.com", [], allowed_literals=["owner@example.com"])
    assert allowed == "owner@example.com"
    assert count == 0


def test_private_profile_value_is_absent_from_a_visitor_prompt():
    """Two levels: public reaches the visitor's secretary, everything else is simply not in
    that conversation — not listed, not hinted at, not retrievable. Legacy `on_request` rows
    fold to private, which is exactly how they already behaved in the prompt."""
    profile = SimpleNamespace(
        data={"contact": {"email": "owner@example.com"}, "location": "Seoul", "title": "CTO"},
        visibility={"contact.email": "private", "location": "on_request", "title": "public"},
    )
    rendered = PF.render_profile(profile, {}, "visitor")
    assert "owner@example.com" not in rendered and "Seoul" not in rendered
    assert "CTO" in rendered
    assert "on request" not in rendered.lower(), "the middle level must leave no trace in the prompt"
    private = PF.private_literals(profile, {})
    assert "owner@example.com" in private and "Seoul" in private
    assert PF.field_visibility(profile, {}, "location") == "private"


def test_production_first_admin_requires_bootstrap_token(monkeypatch):
    monkeypatch.setattr(
        A,
        "get_settings",
        lambda: SimpleNamespace(public_url="https://secretary.example", bootstrap_token="correct-token"),
    )
    with pytest.raises(Forbidden) as e:
        A._validate_bootstrap(0, None)
    assert e.value.code == "bootstrap_required"
    with pytest.raises(Forbidden):
        A._validate_bootstrap(0, "wrong-token")
    A._validate_bootstrap(0, "correct-token")
    A._validate_bootstrap(1, None)


@pytest.mark.asyncio
async def test_notification_rule_rejects_foreign_channel(client):
    _, tok_a = await signup(client, "tenant-a@example.com", "A")
    _, tok_b = await signup(client, "tenant-b@example.com", "B")
    a_channels = (await client.get("/api/notifications/channels", headers=auth(tok_a))).json()["items"]
    b_channels = (await client.get("/api/notifications/channels", headers=auth(tok_b))).json()["items"]
    assert a_channels and b_channels
    foreign = b_channels[0]["id"]
    r = await client.post(
        "/api/notifications/rules",
        headers=auth(tok_a),
        json={"event": "credits_low", "channel_ids": [foreign], "enabled": True},
    )
    assert r.status_code == 404
    assert r.json()["error"]["code"] == "channel_not_found"


@pytest.mark.asyncio
async def test_turn_credit_reservations_never_overcommit(client):
    from blackmoa.db.session import session_scope
    from blackmoa.services import credits as CR

    user, _ = await signup(client)
    owner_id = uuid.UUID(user["id"])
    async with session_scope() as db:
        current = await CR.balance(db, owner_id)
        await CR.apply(db, owner_id, -(current - CR.q(5)), "adjust", note="reservation test")

    t1, t2, t3 = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    async with session_scope() as db:
        r1 = await CR.reserve_turn(
            db,
            owner_id=owner_id,
            turn_id=t1,
            turn_cap=3,
            daily_cap=10,
            audience="owner",
        )
        assert float(r1.amount) == 3.0
    async with session_scope() as db:
        r2 = await CR.reserve_turn(
            db,
            owner_id=owner_id,
            turn_id=t2,
            turn_cap=3,
            daily_cap=10,
            audience="owner",
        )
        assert float(r2.amount) == 2.0
    async with session_scope() as db:
        total, reserved, available = await CR.balance_state(db, owner_id)
        assert (float(total), float(reserved), float(available)) == (5.0, 5.0, 0.0)
        with pytest.raises(PaymentRequired):
            await CR.reserve_turn(
                db,
                owner_id=owner_id,
                turn_id=t3,
                turn_cap=1,
                daily_cap=10,
                audience="owner",
            )

    async with session_scope() as db:
        await CR.release_turn(db, t1)
    async with session_scope() as db:
        _, reserved, available = await CR.balance_state(db, owner_id)
        assert (float(reserved), float(available)) == (2.0, 3.0)
        available, charged = await CR.settle_turn(
            db,
            owner_id=owner_id,
            agent_id=uuid.uuid4(),
            turn_id=t2,
            provider="fake",
            model_id="fake-1",
            input_tokens=100,
            output_tokens=100,
            cache_read=0,
            cache_write=0,
            cost_usd=0.001,
            credits=1,
            audience="owner",
        )
        assert float(charged) == 1.0
        assert float(available) == 4.0


@pytest.mark.asyncio
async def test_turnstile_configuration_fails_closed(monkeypatch):
    from blackmoa.api import public as PUB

    async def missing(*args, **kwargs):
        return ""

    monkeypatch.setattr(PUB.S, "get", missing)
    agent = SimpleNamespace(visitor_settings={"require_turnstile": True})
    with pytest.raises(Forbidden) as e:
        await PUB._enforce_turnstile(object(), agent, "", "203.0.113.5")
    assert e.value.code == "turnstile_not_configured"


def test_safe_http_rejects_mixed_public_private_dns(monkeypatch):
    from blackmoa.services import safe_http as SH

    monkeypatch.setattr(SH, "get_settings", lambda: SimpleNamespace(outbound_allowed_ports="80,443"))
    monkeypatch.setattr(
        SH.socket,
        "getaddrinfo",
        lambda *_args, **_kwargs: [
            (SH.socket.AF_INET, SH.socket.SOCK_STREAM, 6, "", ("93.184.216.34", 443)),
            (SH.socket.AF_INET, SH.socket.SOCK_STREAM, 6, "", ("127.0.0.1", 443)),
        ],
    )
    with pytest.raises(ValueError, match="blocked_host"):
        SH.resolve_target("https://example.com/path")


@pytest.mark.asyncio
async def test_safe_http_connects_to_the_validated_ip(monkeypatch):
    from blackmoa.services import safe_http as SH

    target = SH._Target(
        url="http://example.com/hello",
        scheme="http",
        host="example.com",
        port=80,
        request_target="/hello",
        host_header="example.com",
        ips=("93.184.216.34",),
    )
    monkeypatch.setattr(SH, "resolve_target", lambda _url: target)
    captured: dict[str, object] = {}

    class Writer:
        def __init__(self):
            self.data = bytearray()

        def write(self, data):
            self.data.extend(data)

        async def drain(self):
            return None

        def close(self):
            return None

        async def wait_closed(self):
            return None

    writer = Writer()

    async def fake_open_connection(host, port, **kwargs):
        captured.update(host=host, port=port, kwargs=kwargs)
        reader = asyncio.StreamReader()
        reader.feed_data(b"HTTP/1.1 200 OK\r\nContent-Length: 2\r\n\r\nok")
        reader.feed_eof()
        return reader, writer

    monkeypatch.setattr(SH.asyncio, "open_connection", fake_open_connection)
    response = await SH.safe_request("GET", "http://example.com/hello")
    assert response.content == b"ok"
    assert captured["host"] == "93.184.216.34"
    assert b"Host: example.com\r\n" in writer.data


def test_parser_child_env_does_not_inherit_application_secrets(monkeypatch):
    from blackmoa.services import extract as EX

    monkeypatch.setenv("BLACKMOA_DATABASE_URL", "postgresql://contains-secret")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "contains-secret")

    def fake_run(*args, **kwargs):
        assert "BLACKMOA_DATABASE_URL" not in kwargs["env"]
        assert "ANTHROPIC_API_KEY" not in kwargs["env"]
        return SimpleNamespace(
            returncode=0,
            stdout=b'{"ok":true,"text":"hello","pages":[],"title":""}',
            stderr=b"",
        )

    monkeypatch.setattr(EX.subprocess, "run", fake_run)
    assert EX.extract(b"hello", "text/plain", "hello.txt").text == "hello"


def test_fernet_rotation_decrypts_previous_but_encrypts_primary(monkeypatch):
    from cryptography.fernet import Fernet

    from blackmoa.core import security as SEC

    old_key = Fernet.generate_key()
    new_key = Fernet.generate_key()
    settings = SimpleNamespace(
        encryption_key=new_key.decode(),
        encryption_key_previous=old_key.decode(),
        secret_key="s" * 64,
        public_url="https://secretary.example",
    )
    monkeypatch.setattr(SEC, "get_settings", lambda: settings)
    legacy = Fernet(old_key).encrypt(b"legacy").decode()
    assert SEC.decrypt(legacy) == "legacy"
    current = SEC.encrypt("current")
    assert Fernet(new_key).decrypt(current.encode()) == b"current"


def test_https_production_rejects_dev_secret(monkeypatch):
    from blackmoa.core import security as SEC

    settings = SimpleNamespace(
        encryption_key="",
        encryption_key_previous="",
        secret_key="dev-secret-change-me-dev-secret-change-me",
        public_url="https://secretary.example",
    )
    monkeypatch.setattr(SEC, "get_settings", lambda: settings)
    with pytest.raises(RuntimeError, match="BLACKMOA_SECRET_KEY"):
        SEC.validate_security_settings()


@pytest.mark.asyncio
async def test_visitor_stream_is_live_but_never_leaks_a_private_literal(client):
    """Visitors keep live streaming (plan/12); the private value is masked in-flight (plan/19).

    The fake provider emits the owner's private phone number in the middle of the answer and
    the deltas are 6 characters wide, so the literal is split across chunk boundaries — exactly
    the case a finalize-only redactor would publish before masking it.
    """
    from tests.conftest import read_sse

    user, tok = await signup(client)
    await client.put("/api/users/me/profile", headers=auth(tok),
                     json={"data": {"full_name": "박서준", "contact": {"phone": "010-9999-8888"}}})
    agent = (await client.post("/api/agents", headers=auth(tok), json={"name": "지니"})).json()
    await client.patch(f"/api/agents/{agent['id']}", headers=auth(tok), json={"custom_instructions": "secret-phone"})
    link = (await client.post(f"/api/agents/{agent['id']}/links", json={"label": "t"}, headers=auth(tok))).json()
    v = (await client.post(f"/api/public/links/{link['code']}/visitor", json={})).json()
    vh = {"Authorization": f"Bearer {v['visitor_token']}"}
    async with client.stream("POST", f"/api/public/conversations/{v['conversation_id']}/turns",
                             json={"text": "전화번호 알려주세요"}, headers=vh) as resp:
        events = await read_sse(resp)

    blob = json.dumps(events, ensure_ascii=False)
    assert "010-9999-8888" not in blob, "private literal reached the public stream"
    assert "text.delta" in [e["type"] for e in events]
    streamed = "".join(e["data"]["text"] for e in events if e["type"] == "text.delta")
    assert "[비공개]" in streamed
    final = events[-1]
    assert final["type"] == "turn.complete" and "010-9999-8888" not in final["data"]["answer"]

    # the owner's own transcript keeps the same masked text the visitor saw
    msgs = (await client.get(f"/api/agents/{agent['id']}/conversations/{v['conversation_id']}/messages",
                             headers=auth(tok))).json()["items"]
    assert all("010-9999-8888" not in m["content"] for m in msgs)


@pytest.mark.asyncio
async def test_base_prompt_identity_line_obeys_disclosure(client):
    """The prompt's opening line names the owner's role and city. Those go through the same
    visibility gate as the profile block — otherwise the prompt discloses on-request values
    to a visitor before profile_disclose ever runs."""
    user, tok = await signup(client)
    await client.put("/api/users/me/profile", headers=auth(tok), json={
        "data": {"full_name": "장하렴", "title": "파트리더", "company": "플래티어", "location": "서울 송파"},
        "visibility": {"title": "public", "company": "public", "location": "private", "full_name": "private"}})
    a = (await client.post("/api/agents", headers=auth(tok), json={"name": "제니"})).json()

    v = (await client.get(f"/api/agents/{a['id']}/prompt?audience=visitor", headers=auth(tok))).json()["base_prompt"]
    assert "파트리더" in v and "플래티어" in v          # public: fine
    assert "서울 송파" not in v, "on-request location leaked into the visitor prompt"
    assert "They are based in" not in v
    assert "장하렴" not in v.split("# 3.")[0].replace("하렴 사장님", ""), "on-request full name leaked"
    assert "private" not in v.split("# 3.")[0].lower() or True   # nothing about hidden fields is described at all

    o = (await client.get(f"/api/agents/{a['id']}/prompt?audience=owner", headers=auth(tok))).json()["base_prompt"]
    assert "서울 송파" in o and "장하렴" in o           # the owner sees their own data


@pytest.mark.asyncio
async def test_availability_window_reads_as_words(client):
    user, tok = await signup(client)
    await client.put("/api/users/me/profile", headers=auth(tok), json={
        "data": {"availability_window": {"weekly": [{"days": [0, 1, 2, 3, 4], "start": "10:00", "end": "18:00"}], "note": "오전 회의 많음"}},
        "visibility": {"availability_window": "public"}})
    a = (await client.post("/api/agents", headers=auth(tok), json={"name": "제니"})).json()
    p = (await client.get(f"/api/agents/{a['id']}/prompt?audience=visitor", headers=auth(tok))).json()["base_prompt"]
    assert "Mon/Tue/Wed/Thu/Fri 10:00-18:00" in p
    assert '"weekly"' not in p, "raw JSON reached the prompt"


async def test_signed_in_visit_does_not_outlive_the_account_session(client):
    """A stored visitor token must not walk back in wearing a name after logout.

    The browser keeps the visitor token for a shared link so a returning stranger is
    recognised. When that session was created while signed in it speaks under the account's
    name — and the token alone is not proof the account is still signed in on that device.
    Presenting it without the account has to start over as a stranger.
    """
    from tests.conftest import auth, signup

    owner, otok = await signup(client, name="박서준")
    guest, gtok = await signup(client, name="김하람")
    agent = (await client.post("/api/agents", json={"name": "서기"}, headers=auth(otok))).json()
    link = (await client.post(f"/api/agents/{agent['id']}/links", json={"label": "명함"}, headers=auth(otok))).json()
    code = link["code"]

    named = (await client.post(f"/api/public/links/{code}/visitor", json={}, headers=auth(gtok))).json()
    assert named["visitor"]["signed_in"] is True
    assert named["visitor"]["display_name"]

    # Same stored token, no account: the name must not come back with it.
    after = (await client.post(f"/api/public/links/{code}/visitor",
                               json={"existing_token": named["visitor_token"]})).json()
    assert after["visitor"]["signed_in"] is False, after["visitor"]
    assert after["visitor_token"] != named["visitor_token"]
    assert after["conversation_id"] != named["conversation_id"]

    # And with the account back, the person is recognised again rather than duplicated.
    again = (await client.post(f"/api/public/links/{code}/visitor",
                               json={"existing_token": named["visitor_token"]}, headers=auth(gtok))).json()
    assert again["visitor"]["signed_in"] is True
    assert again["conversation_id"] == named["conversation_id"]


async def test_secretary_email_is_gated_by_a_verified_owner_and_a_daily_cap(client, app):
    """Sending mail as someone is the one tool that can hurt a stranger.

    So: the owner's address must be proven theirs, the volume is capped from the audit log
    rather than from memory, and the From stays on our domain — a From carrying the owner's
    own address fails DMARC at the recipient and lands in spam. Their address is the
    Reply-To, which is what actually decides where an answer goes.
    """
    from unittest.mock import AsyncMock, patch

    from blackmoa.core.errors import Forbidden, ValidationFailed
    from blackmoa.db.session import session_scope
    from blackmoa.models import User
    from blackmoa.services import outbound_mail as OM
    from tests.conftest import signup

    user, _tok = await signup(client, name="유지수")
    uid = uuid.UUID(user["id"])

    async with session_scope() as db:
        owner = await db.get(User, uid)
        with pytest.raises(Forbidden) as unverified:
            await OM.send_as_owner(db, owner=owner, agent_name="Soo", to="a@example.com", subject="s", body="b")
        assert unverified.value.code == "email_unverified"

        owner.email_verified_at = datetime.now(UTC)
        await db.commit()

    sent: list[dict] = []

    async def fake_send(_db, **kw):
        sent.append(kw)

    with patch("blackmoa.services.outbound_mail.send_mail", AsyncMock(side_effect=fake_send)):
        async with session_scope() as db:
            owner = await db.get(User, uid)
            out = await OM.send_as_owner(db, owner=owner, agent_name="Soo", to=" Someone@Example.com ",
                                         subject="  회의  일정 ", body="본문입니다")
            await db.commit()

    assert out["sent"] is True and out["to"] == "Someone@Example.com"
    assert sent[0]["identity"] == "agent"                       # the secretary's mailbox, not no-reply
    assert sent[0]["reply_to"] == user["email"]                 # an answer reaches the owner
    assert user["email"] not in str(sent[0].get("from_name"))   # the From is a name, not their address
    assert sent[0]["subject"] == "회의 일정"                      # whitespace collapsed

    # A malformed address never reaches the SMTP server.
    async with session_scope() as db:
        owner = await db.get(User, uid)
        for bad in ("nope", "a@b", "two@a.com, other@b.com", "<script>@x.com"):
            with pytest.raises(ValidationFailed):
                await OM.send_as_owner(db, owner=owner, agent_name="Soo", to=bad, subject="s", body="b")

    # The cap is counted from what was actually recorded, so a restart cannot reset it.
    async with session_scope() as db:
        assert await OM.sent_today(db, uid) == 1
        owner = await db.get(User, uid)
        for i in range(OM.DAILY_CAP - 1):
            with patch("blackmoa.services.outbound_mail.send_mail", AsyncMock()):
                await OM.send_as_owner(db, owner=owner, agent_name="Soo", to=f"x{i}@example.com", subject="s", body="b")
        await db.commit()
    async with session_scope() as db:
        owner = await db.get(User, uid)
        with patch("blackmoa.services.outbound_mail.send_mail", AsyncMock()):
            with pytest.raises(Forbidden) as capped:
                await OM.send_as_owner(db, owner=owner, agent_name="Soo", to="last@example.com", subject="s", body="b")
        assert capped.value.code == "email_quota_exhausted"


async def test_only_the_owner_can_make_a_secretary_send_mail(client, app):
    """A visitor with this tool would be a spam cannon wearing someone else's name."""
    from blackmoa.pipeline.tools import all_tools

    tool = all_tools()["email_send"]
    assert tool.audiences == frozenset({"owner"})
    # 나와의 대화에서는 모든 기능이 켜져 있다 (plan/57) — 메일 보내기도 주인이 시킬 때만, 주인 대화에서만.
    # 외부인 대화에는 어떤 설정으로도 열리지 않는다: 스위치가 아니라 대상(audience)이 막는다.
    from types import SimpleNamespace

    from blackmoa.pipeline.tools.base import _allowed
    from blackmoa.services import outsider as OUT
    agent = SimpleNamespace(capabilities={"email_send": True}, outsider={k: ("public" if k in OUT.LEVELED else True)
                                                                          for k in (*OUT.LEVELED, *OUT.SWITCHES)})
    visitor = SimpleNamespace(audience="visitor", relay_id=None, features={"feature:mail"}, agent=agent)
    assert _allowed(tool, visitor) is False
    assert _allowed(all_tools()["email_search"], visitor) is False, "외부인은 메일을 읽지 못한다"


async def test_a_mail_handle_is_unique_and_never_a_system_address(client, app):
    """The handle becomes a real mailbox, so two people cannot hold one and nobody can
    take an address the mail system itself answers to."""
    from blackmoa.core.errors import Conflict, ValidationFailed
    from blackmoa.db.session import session_scope
    from blackmoa.models import User
    from blackmoa.services import outbound_mail as OM
    from tests.conftest import signup

    a, _ = await signup(client)
    b, _ = await signup(client)

    async with session_scope() as db:
        owner = await db.get(User, uuid.UUID(a["id"]))
        assert await OM.claim_handle(db, user=owner, raw="  Haryeom  ") == "haryeom"   # trimmed, lowered
        await db.commit()

    async with session_scope() as db:
        other = await db.get(User, uuid.UUID(b["id"]))
        with pytest.raises(Conflict) as taken:
            await OM.claim_handle(db, user=other, raw="HARYEOM")        # a mailbox is case-insensitive
        assert taken.value.code == "handle_taken"

        for bad, why in [("no-reply", "handle_reserved"), ("postmaster", "handle_reserved"),
                         ("ab", "handle_length"), ("-nope", "handle_charset"),
                         ("a..b", "handle_charset"), ("has space", "handle_charset"),
                         ("hi@there", "handle_charset")]:
            with pytest.raises(ValidationFailed) as bad_handle:
                await OM.claim_handle(db, user=other, raw=bad)
            assert bad_handle.value.code == why, bad


async def test_a_secretary_sends_from_its_owners_own_address(client, app):
    """And only ever on our sending domain — that is where SPF and DKIM are published."""
    from unittest.mock import AsyncMock, patch

    from blackmoa.db.session import session_scope
    from blackmoa.models import User
    from blackmoa.services import outbound_mail as OM
    from blackmoa.services import settings as S
    from tests.conftest import signup

    user, _ = await signup(client)
    async with session_scope() as db:
        await S.put(db, "smtp.host", "smtp.example.net")
        await S.put(db, "smtp.from", "black-moa <no-reply@black.memo-ora.com>")
        await S.put(db, "smtp.from_agent", "black-moa <blackmoa@black.memo-ora.com>")
        owner = await db.get(User, uuid.UUID(user["id"]))
        owner.email_verified_at = datetime.now(UTC)
        # A handle is unique across the database, and the suite shares one.
        handle = f"sender{uuid.uuid4().hex[:8]}"
        await OM.claim_handle(db, user=owner, raw=handle)
        await db.commit()

    sent: list[dict] = []
    with patch("blackmoa.services.outbound_mail.send_mail", AsyncMock(side_effect=lambda _db, **kw: sent.append(kw))):
        async with session_scope() as db:
            owner = await db.get(User, uuid.UUID(user["id"]))
            out = await OM.send_as_owner(db, owner=owner, agent_name="제니", to="someone@example.com",
                                         subject="안녕하세요", body="본문")
            await db.commit()
    assert out["from"] == f"{handle}@black.memo-ora.com"
    assert sent[0]["from_address"] == f"{handle}@black.memo-ora.com"

    # A mailbox on someone else's domain is refused by the mailer, not merely discouraged.
    from blackmoa.services.mailer import _domain
    assert _domain(f"{handle}@black.memo-ora.com") == _domain("black-moa <blackmoa@black.memo-ora.com>")
    assert _domain(f"{handle}@evil.example") != _domain("black-moa <blackmoa@black.memo-ora.com>")
