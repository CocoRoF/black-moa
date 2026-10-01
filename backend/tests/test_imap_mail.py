"""메일함 연결 — IMAP + 앱 비밀번호 (plan/74).

Gmail 을 Google API(gmail.readonly, 제한 범위)로 읽지 않고, 메일 서비스가 주는 IMAP 과 앱 비밀번호로 읽는다.
가짜 IMAP 서버로: 틀린 비밀번호는 저장하지 않는다, 가져오기(한글 제목·EUC-KR 본문·큰 메일은 머리글만·안 읽음),
본문은 열 때 읽는다, 비밀번호가 바뀌면 연결이 만료로, 끊으면 비밀번호와 메일이 지워진다, 내부 주소는 막는다.
"""
from __future__ import annotations

import imaplib
import uuid
from email.message import EmailMessage
from email.mime.text import MIMEText

import pytest
from httpx import AsyncClient
from sqlalchemy import select

from blackmoa.db.session import session_scope
from blackmoa.models import Connection, IntegrationEmail
from blackmoa.services import imap_mail as IM
from tests.conftest import auth, signup

APP_PW = "abcdefghijklmnop"


def _msg(uid: int, subject: str, body: str, *, charset: str = "utf-8", big: bool = False) -> bytes:
    if charset == "utf-8":
        m = EmailMessage()
        m.set_content(body + ("\n" + "x" * (IM.FULL_FETCH_MAX + 10) if big else ""))
    else:
        m = MIMEText(body, "plain", charset)
    m["Subject"] = subject
    m["From"] = "보스 <boss@acme.com>"
    m["To"] = "me@example.com"
    m["Message-ID"] = f"<m{uid}@acme.com>"
    m["Date"] = "Tue, 29 Sep 2026 10:00:00 +0900"
    return m.as_bytes()


class FakeServer:
    password = APP_PW
    validity = b"777"
    messages = {
        101: _msg(101, "견적 요청", "다음 주까지 견적 부탁드립니다."),
        102: _msg(102, "회의 안내", "목요일 오후 3시 회의입니다.", charset="euc-kr"),
        103: _msg(103, "큰 첨부", "첨부 확인 부탁", big=True),
    }
    unseen = [103]


class FakeIMAP:
    def __init__(self, host, ip, port, *, timeout):
        self.host = host

    def login(self, user, pw):
        if pw != FakeServer.password:
            raise imaplib.IMAP4.error("AUTHENTICATIONFAILED")
        return "OK", [b"ok"]

    def select(self, box, readonly=False):
        assert readonly is True  # 메일함을 바꾸지 않는다
        return "OK", [str(len(FakeServer.messages)).encode()]

    def response(self, code):
        return code, [FakeServer.validity]

    def uid(self, cmd, *args):
        if cmd == "SEARCH":
            crit = args[1]
            if "UNSEEN" in crit or "is:unread" in crit:
                return "OK", [" ".join(str(u) for u in FakeServer.unseen).encode()]
            return "OK", [" ".join(str(u) for u in sorted(FakeServer.messages)).encode()]
        if cmd == "FETCH":
            ids, what = args
            if what == "(RFC822.SIZE)":
                out = [f"{i} (UID {u} RFC822.SIZE {len(FakeServer.messages[int(u)])})".encode()
                       for i, u in enumerate(ids.decode().split(","), 1)]
                return "OK", out
            u = int(ids if isinstance(ids, int) else ids.decode())
            raw = FakeServer.messages.get(u)
            if raw is None:
                return "OK", [None]
            if "HEADER" in what:
                raw = raw.split(b"\n\n", 1)[0] + b"\n\n"
            meta = f'1 (UID {u} INTERNALDATE "29-Sep-2026 10:00:00 +0900" BODY[] {{{len(raw)}}}'.encode()
            return "OK", [(meta, raw), b")"]
        raise AssertionError(cmd)

    def logout(self):
        return "BYE", [b""]


@pytest.fixture
def fake_imap(monkeypatch):
    monkeypatch.setattr(IM, "_Pinned", FakeIMAP)
    monkeypatch.setattr(IM, "_check_host", lambda host: "203.0.113.10")
    FakeServer.password = APP_PW
    yield


async def _sync(conn_id: str) -> dict:
    from blackmoa.worker.handlers import integration_sync
    async with session_scope() as db:
        out = await integration_sync(db, {"connection_id": conn_id})
        await db.commit()
    return out


async def test_a_mailbox_connects_with_an_app_password_and_the_secretary_reads_it(client: AsyncClient, fake_imap):
    _, tok = await signup(client)
    body = {"preset": "gmail", "email": "me@example.com", "password": "wrong-password"}
    r = await client.post("/api/mail/accounts", json=body, headers=auth(tok))
    assert r.status_code == 422 and r.json()["error"]["code"] == "imap_auth_failed"
    assert (await client.get("/api/mail", headers=auth(tok))).json()["accounts"] == []   # 틀린 비밀번호는 저장하지 않는다

    # 앱 비밀번호는 네 자씩 띄어 보여 준다 — 띄어 쓴 그대로 붙여 넣어도 된다.
    r = await client.post("/api/mail/accounts", json={**body, "password": "abcd efgh ijkl mnop"}, headers=auth(tok))
    assert r.status_code == 201, r.text
    acct = r.json()["accounts"][0]
    assert acct["provider"] == "imap" and acct["provider_label"] == "Gmail" and acct["account"] == "me@example.com"
    assert acct["can_read"] is True and APP_PW not in r.text
    async with session_scope() as db:
        conn = await db.get(Connection, uuid.UUID(acct["id"]))
        assert conn.access_token_enc and APP_PW not in conn.access_token_enc   # 암호화해서 둔다

    out = await _sync(acct["id"])
    assert out == {"emails": 3}
    got = (await client.get("/api/mail", headers=auth(tok))).json()
    by = {m["subject"]: m for m in got["items"]}
    assert set(by) == {"견적 요청", "회의 안내", "큰 첨부"}
    assert by["견적 요청"]["snippet"].startswith("다음 주까지 견적") and by["견적 요청"]["unread"] is False
    assert by["회의 안내"]["snippet"].startswith("목요일 오후 3시")          # EUC-KR 도 읽는다
    assert by["큰 첨부"]["snippet"] == "" and by["큰 첨부"]["unread"] is True  # 큰 메일은 머리글만
    assert by["견적 요청"]["from"] == "보스 <boss@acme.com>"

    one = (await client.get(f"/api/mail/{by['견적 요청']['id']}", headers=auth(tok))).json()
    assert one["body"].startswith("다음 주까지 견적") and one["provider"] == "imap"

    # 다시 가져와도 같은 메일을 두 번 넣지 않는다.
    assert (await _sync(acct["id"])) == {"emails": 0}

    # 메일 서비스에서 앱 비밀번호를 지웠다 — 연결이 만료되고, 비서는 메일을 읽지 않는다.
    FakeServer.password = "changed"
    res = await _sync(acct["id"])
    assert res.get("error") == "imap_auth_failed"
    async with session_scope() as db:
        assert (await db.get(Connection, uuid.UUID(acct["id"]))).status == "expired"
    assert (await client.get("/api/mail", headers=auth(tok))).json()["accounts"][0]["can_read"] is False

    # 다시 넣으면 살아난다(같은 주소면 한 줄).
    FakeServer.password = APP_PW
    r = await client.post("/api/mail/accounts", json={**body, "password": APP_PW}, headers=auth(tok))
    assert [a["id"] for a in r.json()["accounts"]] == [acct["id"]] and r.json()["accounts"][0]["can_read"] is True

    # 끊으면 저장한 비밀번호와 가져온 메일이 지워진다.
    r = await client.delete(f"/api/mail/accounts/{acct['id']}", headers=auth(tok))
    assert r.status_code == 200 and r.json()["accounts"] == []
    async with session_scope() as db:
        assert (await db.get(Connection, uuid.UUID(acct["id"]))) is None
        left = (await db.execute(select(IntegrationEmail).where(IntegrationEmail.connection_id == uuid.UUID(acct["id"])))).first()
        assert left is None


def test_a_mail_server_on_our_own_network_is_refused(monkeypatch):
    from blackmoa.core.errors import ValidationFailed

    for bad in ("not a host", "http://imap.x.com", "a" * 300 + ".com"):
        with pytest.raises(ValidationFailed) as e:
            IM._check_host(bad)
        assert e.value.code == "imap_host_invalid"

    def private(host, port):
        raise ValueError("blocked_host")
    monkeypatch.setattr("blackmoa.services.safe_http._public_ips", private)
    with pytest.raises(ValidationFailed) as e:
        IM._check_host("mail.internal.example.com")
    assert e.value.code == "imap_host_blocked"


async def test_google_no_longer_asks_for_gmail(client: AsyncClient):
    from blackmoa.services import oauth as OA
    g = OA.get("google")
    assert "gmail_read" not in {c.id for c in g.capabilities}
    assert not any("gmail" in s for c in g.capabilities for s in c.scopes)
