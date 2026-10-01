"""메일함 연결 — IMAP + 앱 비밀번호 (plan/74).

Google 의 Gmail 읽기 권한(gmail.readonly)은 "제한 범위"라서 외부 사용자에게 열려면 매년 유료 보안 평가(CASA)를
받아야 한다. 머리글만 보는 gmail.metadata 도 같다. 사용자가 자기 메일함을 비서에게 보여 주는 길은 그것만이 아니다 —
메일 서비스들이 주는 **IMAP 과 앱 비밀번호**(2단계 인증을 켠 계정이 만드는 전용 비밀번호)다. Google API 를 거치지
않으니 그 평가 대상이 아니고, 네이버·다음·카카오 메일도 같은 길로 붙는다.

- 받은편지함만, **읽기 전용**으로 연다(메일함을 바꾸지 않는다 — 읽음 표시도 하지 않는다).
- 최근 30일, 한 번에 새 메일 200통까지, 연결마다 최근 2,000통만 둔다. 본문은 보관하지 않고 열 때 읽는다(미리보기만 둔다).
- 앱 비밀번호는 암호화해서 둔다(`access_token_enc`). 화면에는 돌려주지 않는다.
- 서버 주소는 공인 주소만, 포트는 993(암호화된 IMAP)만. DNS 를 한 번 풀어 확인한 그 주소로만 접속한다 — 사용자가 적은
  주소로 우리 서버가 내부망을 두드리는 길이 되지 않게.
"""
from __future__ import annotations

import email
import imaplib
import re
import socket
import ssl
import time
from datetime import UTC, datetime, timedelta
from email import policy
from email.utils import parsedate_to_datetime
from typing import Any

from sqlalchemy import select, text
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from blackmoa.core import pools
from blackmoa.core.errors import ServiceUnavailable, ValidationFailed
from blackmoa.core.security import decrypt, encrypt
from blackmoa.models import Connection, IntegrationEmail, User

PROVIDER = "imap"
CAPABILITY = "mail_read"
PORT = 993
DAYS = 30
PER_RUN = 200
KEEP = 2000
FULL_FETCH_MAX = 256 * 1024     # 이보다 큰 메일(첨부가 큰 것)은 머리글만 — 미리보기 없이
TIMEOUT = 25
BODY_MAX = 8000

#: 고르는 메일 서비스. 앱 비밀번호를 만드는 곳은 화면이 안내한다.
PRESETS: dict[str, dict[str, Any]] = {
    "gmail": {"label": "Gmail", "host": "imap.gmail.com"},
    "naver": {"label": "네이버 메일", "host": "imap.naver.com"},
    "daum": {"label": "다음 메일", "host": "imap.daum.net"},
    "kakao": {"label": "카카오 메일", "host": "imap.kakao.com"},
    "custom": {"label": "메일", "host": ""},
}
_HOST = re.compile(r"^[a-z0-9]([a-z0-9-]*[a-z0-9])?(\.[a-z0-9]([a-z0-9-]*[a-z0-9])?)+$")


class _Pinned(imaplib.IMAP4_SSL):
    """확인해 둔 IP 로만 접속한다(인증서는 이름으로 검사한다)."""

    def __init__(self, host: str, ip: str, port: int, *, timeout: float):
        self._pinned_ip = ip
        super().__init__(host, port, ssl_context=ssl.create_default_context(), timeout=timeout)

    def _create_socket(self, timeout):  # type: ignore[override]
        sock = socket.create_connection((self._pinned_ip, self.port), timeout)
        return self.ssl_context.wrap_socket(sock, server_hostname=self.host)


def label_for(conn: Connection) -> str:
    return PRESETS.get((conn.settings or {}).get("preset") or "", PRESETS["custom"])["label"]


def _check_host(host: str) -> str:
    from blackmoa.services.safe_http import _public_ips

    h = (host or "").strip().lower().rstrip(".")
    if not _HOST.match(h) or len(h) > 253:
        raise ValidationFailed("invalid mail server", code="imap_host_invalid")
    try:
        ips = _public_ips(h, PORT)
    except ValueError as e:
        code = "imap_unreachable" if str(e) == "dns_failed" else "imap_host_blocked"
        raise ValidationFailed("this mail server cannot be used", code=code) from e
    return ips[0]


def _open(host: str, username: str, password: str) -> _Pinned:
    ip = _check_host(host)
    try:
        m = _Pinned(host, ip, PORT, timeout=TIMEOUT)
    except (OSError, ssl.SSLError, imaplib.IMAP4.error) as e:
        raise ServiceUnavailable("mail server did not answer", code="imap_unreachable") from e
    try:
        m.login(username, password)
    except imaplib.IMAP4.error as e:
        try:
            m.logout()
        except Exception:  # noqa: BLE001
            pass
        raise ValidationFailed("mail login failed", code="imap_auth_failed") from e
    typ, _ = m.select("INBOX", readonly=True)
    if typ != "OK":
        m.logout()
        raise ServiceUnavailable("inbox is not available", code="imap_unreachable")
    return m


def _uidvalidity(m: imaplib.IMAP4) -> str:
    """받은편지함의 UIDVALIDITY — 바뀌면 예전 번호는 다른 메일을 가리킨다(처음부터 다시 가져온다)."""
    _, data = m.response("UIDVALIDITY")
    return data[0].decode() if data and data[0] else "0"


def _decode(msg: email.message.Message, name: str) -> str:
    try:
        return str(msg.get(name, "") or "")
    except Exception:  # noqa: BLE001 — 깨진 머리글 하나로 메일 전체를 버리지 않는다
        return ""


def _body_text(msg: email.message.EmailMessage) -> str:
    try:
        part = msg.get_body(preferencelist=("plain", "html"))
        if part is None:
            return ""
        content = part.get_content()
        if part.get_content_type() == "text/html":
            from blackmoa.services.extract import html_to_text
            content = html_to_text(content)
        return str(content)
    except Exception:  # noqa: BLE001
        return ""


def _addrs(v: str) -> list[str]:
    return [x.strip() for x in v.split(",") if x.strip()][:20]


def _fetch_one(m: imaplib.IMAP4, uid: bytes, *, full: bool) -> tuple[bytes, bytes]:
    what = "(INTERNALDATE BODY.PEEK[])" if full else "(INTERNALDATE BODY.PEEK[HEADER])"
    typ, data = m.uid("FETCH", uid, what)
    if typ != "OK" or not data:
        return b"", b""
    for part in data:
        if isinstance(part, tuple) and len(part) >= 2:
            return part[0], part[1]
    return b"", b""


def _sizes(m: imaplib.IMAP4, uids: list[bytes]) -> dict[bytes, int]:
    out: dict[bytes, int] = {}
    if not uids:
        return out
    typ, data = m.uid("FETCH", b",".join(uids), "(RFC822.SIZE)")
    for line in data or []:
        raw = line if isinstance(line, bytes) else (line[0] if isinstance(line, tuple) else b"")
        mu = re.search(rb"UID (\d+)", raw)
        ms = re.search(rb"RFC822\.SIZE (\d+)", raw)
        if mu and ms:
            out[mu.group(1)] = int(ms.group(1))
    return out


def _since(days: int) -> str:
    return (datetime.now(UTC) - timedelta(days=days)).strftime("%d-%b-%Y")


def _search(m: imaplib.IMAP4, host: str, criteria: str) -> list[bytes]:
    typ, data = m.uid("SEARCH", None, criteria)
    if typ != "OK" or not data or not data[0]:
        return []
    return data[0].split()


def _pull(host: str, username: str, password: str, known: set[str], cursor: dict[str, Any]) -> dict[str, Any]:
    """메일함에서 새 메일의 머리글·미리보기와 안 읽은 메일 목록을 읽어 온다(스레드에서 돈다)."""
    m = _open(host, username, password)
    try:
        validity = _uidvalidity(m)
        reset = bool(cursor.get("uidvalidity")) and cursor.get("uidvalidity") != validity
        if host == "imap.gmail.com":
            # Gmail 은 받은편지함에 광고·소셜 탭도 들어 있다 — 받은편지함 화면과 같게 거른다.
            uids = _search(m, host, f'X-GM-RAW "newer_than:{DAYS}d -category:promotions -category:social"')
            unseen = _search(m, host, f'X-GM-RAW "newer_than:{DAYS}d is:unread"')
        else:
            uids = _search(m, host, f"SINCE {_since(DAYS)}")
            unseen = _search(m, host, f"UNSEEN SINCE {_since(DAYS)}")
        seen_known = set() if reset else known
        new = [u for u in reversed(uids) if f"{validity}:{u.decode()}" not in seen_known][:PER_RUN]
        sizes = _sizes(m, new)
        rows = []
        for u in new:
            full = sizes.get(u, FULL_FETCH_MAX + 1) <= FULL_FETCH_MAX
            meta, raw = _fetch_one(m, u, full=full)
            if not raw:
                continue
            msg = email.message_from_bytes(raw, policy=policy.default)
            received = None
            t = imaplib.Internaldate2tuple(meta) if meta else None
            if t:
                received = datetime.fromtimestamp(time.mktime(t), tz=UTC)
            if received is None:
                try:
                    received = parsedate_to_datetime(_decode(msg, "Date"))
                except Exception:  # noqa: BLE001
                    received = datetime.now(UTC)
            snippet = " ".join(_body_text(msg).split())[:300] if full else ""  # type: ignore[arg-type]
            rows.append({"ext_id": f"{validity}:{u.decode()}", "thread_id": (_decode(msg, "Message-ID") or "")[:128] or None,
                         "from": _decode(msg, "From")[:320], "to": _addrs(_decode(msg, "To")),
                         "subject": _decode(msg, "Subject")[:1000], "snippet": snippet, "received": received})
        return {"validity": validity, "reset": reset, "rows": rows,
                "unseen": [f"{validity}:{u.decode()}" for u in unseen]}
    finally:
        try:
            m.logout()
        except Exception:  # noqa: BLE001
            pass


def _read_body(host: str, username: str, password: str, ext_id: str) -> dict[str, Any]:
    validity, _, uid = ext_id.partition(":")
    m = _open(host, username, password)
    try:
        if _uidvalidity(m) != validity:
            raise ValidationFailed("this mail is no longer in the mailbox", code="mail_not_found")
        _, raw = _fetch_one(m, uid.encode(), full=True)
        if not raw:
            raise ValidationFailed("this mail is no longer in the mailbox", code="mail_not_found")
        msg = email.message_from_bytes(raw, policy=policy.default)
        return {"id": ext_id, "from": _decode(msg, "From"), "to": _decode(msg, "To"), "subject": _decode(msg, "Subject"),
                "date": _decode(msg, "Date"), "body": _body_text(msg)[:BODY_MAX]}  # type: ignore[arg-type]
    finally:
        try:
            m.logout()
        except Exception:  # noqa: BLE001
            pass


def _creds(conn: Connection) -> tuple[str, str, str]:
    s = conn.settings or {}
    return str(s.get("host") or ""), str(s.get("username") or conn.account_label or ""), decrypt(conn.access_token_enc)


async def connect(db: AsyncSession, owner: User, *, preset: str, email_addr: str, password: str, host: str | None = None) -> Connection:
    """메일함을 잇는다 — 먼저 실제로 들어가 본다(틀린 비밀번호를 저장하지 않는다). 같은 주소면 비밀번호만 바꾼다."""
    if preset not in PRESETS:
        raise ValidationFailed("unknown mail service", code="imap_preset_unknown")
    username = (email_addr or "").strip()
    if not username or len(username) > 254:
        raise ValidationFailed("enter your mail address", code="imap_username_required")
    password = (password or "").replace(" ", "")     # 앱 비밀번호는 네 자씩 띄어 보여 준다
    if not password or len(password) > 200:
        raise ValidationFailed("enter the app password", code="imap_password_required")
    server = PRESETS[preset]["host"] or (host or "").strip().lower()
    m = await pools.to_thread("misc", _open, server, username, password, label="imap-login")
    await pools.to_thread("misc", m.logout, label="imap-logout")
    conn = (await db.execute(select(Connection).where(Connection.owner_id == owner.id, Connection.provider == PROVIDER,
                                                      Connection.account_label == username))).scalars().first()
    if conn is None:
        conn = Connection(owner_id=owner.id, provider=PROVIDER, account_label=username, scopes=[], sync_cursor={})
        db.add(conn)
    conn.settings = {"preset": preset, "host": server, "username": username}
    conn.access_token_enc = encrypt(password)
    conn.capabilities = [CAPABILITY]
    conn.status = "active"
    conn.error = None
    await db.flush()
    from blackmoa.services import jobs as J
    await J.enqueue(db, "integration.sync", {"connection_id": str(conn.id)}, priority=2, dedupe_key=f"sync:{conn.id}",
                    owner_id=owner.id)
    return conn


async def sync(db: AsyncSession, conn: Connection) -> int:
    """새 메일을 가져오고 안 읽음 표시를 메일함에 맞춘다. 가져온 수."""
    from blackmoa.services import connections as CN

    host, username, password = _creds(conn)
    known = {row[0] for row in (await db.execute(select(IntegrationEmail.ext_id)
                                                 .where(IntegrationEmail.connection_id == conn.id))).all()}
    cursor = dict(conn.sync_cursor or {})
    try:
        got = await pools.to_thread("misc", _pull, host, username, password, known, cursor, label="imap-sync")
    except ValidationFailed as e:
        if e.code == "imap_auth_failed":
            # 앱 비밀번호를 지웠거나 바꿨다 — 다시 넣을 때까지 가져오지 않는다(사용자에게 알린다).
            await CN._expired(db, conn, "mail login failed")
            raise ServiceUnavailable("mail login failed", code="imap_auth_failed") from e
        raise ServiceUnavailable(e.message, code=e.code) from e
    if got["reset"]:
        await db.execute(text("DELETE FROM integration_emails WHERE connection_id = :c"), {"c": conn.id})
    unseen = set(got["unseen"])
    for r in got["rows"]:
        await db.execute(insert(IntegrationEmail).values(
            owner_id=conn.owner_id, connection_id=conn.id, ext_id=r["ext_id"], thread_id=r["thread_id"],
            from_addr=r["from"], to_addrs=r["to"], subject=r["subject"], snippet=r["snippet"], received_at=r["received"],
            labels=["INBOX"], unread=r["ext_id"] in unseen, importance=0,
        ).on_conflict_do_nothing())
    await db.execute(text("""UPDATE integration_emails SET unread = (ext_id = ANY(:u))
                             WHERE connection_id = :c AND received_at >= now() - interval '30 days'"""),
                     {"u": got["unseen"], "c": conn.id})
    await db.execute(text("""DELETE FROM integration_emails WHERE connection_id = :c AND id NOT IN (
        SELECT id FROM integration_emails WHERE connection_id = :c ORDER BY received_at DESC NULLS LAST LIMIT :k)"""),
                     {"c": conn.id, "k": KEEP})
    cursor["uidvalidity"] = got["validity"]
    conn.sync_cursor = cursor
    return len(got["rows"])


async def read(conn: Connection, ext_id: str) -> dict[str, Any]:
    host, username, password = _creds(conn)
    return await pools.to_thread("misc", _read_body, host, username, password, ext_id, label="imap-read")

