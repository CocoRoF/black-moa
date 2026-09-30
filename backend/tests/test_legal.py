"""이용약관·개인정보 처리방침과 동의 (plan/73).

- 기본 문서는 비워 둔 운영자 정보를 줄째로 빼고, 채운 것은 넣는다.
- 가입은 만 14세 이상 확인·약관 동의가 있어야 하고, 어느 판에 언제 동의했는지 남는다(감사 기록 포함).
- 판(시행일)이 바뀌면 앱이 다시 받는다 — 화면이 본 판과 다르면 동의를 받지 않는다.
- 보관 기간: 감사 기록 1년, 돈 내고 받은 크레딧은 이월 상한으로 사라지지 않는다.
"""
from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest_asyncio
from httpx import AsyncClient
from sqlalchemy import select, text

from memora.db.session import session_scope
from memora.models import AuditLog, User
from memora.services import legal as LEGAL
from memora.services import oauth as OA
from memora.services import settings as S
from tests.conftest import auth, signup
from tests.test_sso import _fake, _provider, _sso


async def _put(**vals) -> None:
    async with session_scope() as db:
        for k, v in vals.items():
            await S.put(db, k, v)
        await db.commit()
    S.invalidate("legal.")


@pytest_asyncio.fixture(autouse=True)
async def _clean(app):
    yield
    await _put(**{k: "" for k in ("legal.company_name", "legal.ceo_name", "legal.business_no", "legal.email",
                                  "legal.privacy_officer", "legal.effective_date", "legal.terms")})
    await _provider("google", enabled=False)


async def test_the_default_documents_fill_what_the_operator_gave_and_drop_the_rest(client: AsyncClient):
    d = (await client.get("/api/public/legal")).json()
    assert d["format"] == "markdown" and d["version"] == LEGAL.DEFAULT_VERSION
    assert "{{" not in d["terms"] and "{{" not in d["privacy"]
    # 아무것도 채우지 않았으면 대표자·사업자번호 줄이 없다(빈 "대표자: " 가 남지 않는다).
    assert "대표자:" not in d["terms"] and "사업자등록번호" not in d["privacy"]
    assert "제15조 (AI 비서의 설정과 운영에 대한 책임)" in d["terms"]
    assert "제22조 (자동화된 보호 조치)" in d["terms"] and "별도의 통지 없이" in d["terms"]
    assert "제7조 (개인정보의 국외 이전)" in d["privacy"] and "Anthropic" in d["privacy"]
    assert d["operator"] == {}

    await _put(**{"legal.company_name": "주식회사 메모라", "legal.ceo_name": "홍길동", "legal.business_no": "123-45-67890",
                  "legal.email": "help@example.com"})
    d = (await client.get("/api/public/legal")).json()
    assert "주식회사 메모라" in d["terms"] and "대표자: 홍길동" in d["terms"] and "사업자등록번호: 123-45-67890" in d["privacy"]
    # 개인정보 보호책임자를 따로 정하지 않았으면 대표자가 맡고, 문의처는 대표 이메일.
    assert "성명: 홍길동" in d["privacy"] and "문의: help@example.com" in d["privacy"]
    assert d["operator"]["company"] == "주식회사 메모라"

    # 관리자가 본문을 넣으면 그것을 쓴다(자리표시는 똑같이 채운다).
    await _put(**{"legal.terms": "# 우리 약관\n{{company}} 의 약관입니다."})
    d = (await client.get("/api/public/legal")).json()
    assert d["terms"].strip() == "# 우리 약관\n주식회사 메모라 의 약관입니다." and d["custom"]["terms"] is True


async def test_signing_up_needs_the_14_and_terms_agreement_and_records_it(client: AsyncClient):
    email = f"t{uuid.uuid4().hex[:8]}@example.com"
    body = {"email": email, "password": "correct-horse-9", "display_name": "가입자"}
    r = await client.post("/api/auth/signup", json=body)
    assert r.status_code == 422 and r.json()["error"]["code"] == "terms_required", r.text
    r = await client.post("/api/auth/signup", json={**body, "agree_terms": True})
    assert r.status_code == 200, r.text
    assert r.json()["user"]["terms_version"] == LEGAL.DEFAULT_VERSION
    async with session_scope() as db:
        u = (await db.execute(select(User).where(User.email == email))).scalars().one()
        assert u.terms_agreed_at is not None
        rows = (await db.execute(select(AuditLog).where(AuditLog.actor_id == u.id, AuditLog.action == "terms_agreed"))).scalars().all()
        assert rows and rows[0].meta["version"] == LEGAL.DEFAULT_VERSION


async def test_a_new_version_is_agreed_to_once_in_the_app(client: AsyncClient):
    user, tok = await signup(client)
    st = (await client.get("/api/auth/status")).json()
    assert st["legal_version"] == user["terms_version"] == LEGAL.DEFAULT_VERSION

    # 관리자가 시행일을 바꾸면(형식이 맞아야 한다) 모두에게 다시 받는다.
    await _put(**{"legal.effective_date": "2027-01-01"})
    assert (await client.get("/api/auth/status")).json()["legal_version"] == "2027-01-01"
    assert (await client.get("/api/auth/me", headers=auth(tok))).json()["terms_version"] == LEGAL.DEFAULT_VERSION

    # 체크하지 않았거나 화면이 본 판이 옛 판이면 받지 않는다.
    r = await client.post("/api/auth/terms", json={"version": "2027-01-01", "agree": False}, headers=auth(tok))
    assert r.status_code == 422
    r = await client.post("/api/auth/terms", json={"version": LEGAL.DEFAULT_VERSION, "agree": True}, headers=auth(tok))
    assert r.status_code == 409 and r.json()["error"]["code"] == "terms_changed"
    r = await client.post("/api/auth/terms", json={"version": "2027-01-01", "agree": True}, headers=auth(tok))
    assert r.status_code == 200 and r.json()["user"]["terms_version"] == "2027-01-01"
    d = (await client.get("/api/public/legal")).json()
    assert "2027년 1월 1일부터" in d["privacy"] and "2027년 1월 1일부터 시행" in d["terms"]


async def test_the_effective_date_must_be_a_date(client: AsyncClient):
    user, tok = await signup(client)
    async with session_scope() as db:
        (await db.get(User, uuid.UUID(user["id"]))).role = "admin"
        await db.commit()
    try:
        r = await client.put("/api/admin/settings", json={"values": {"legal.effective_date": "내일"}}, headers=auth(tok))
        assert r.status_code == 422
        r = await client.put("/api/admin/settings", json={"values": {"legal.effective_date": "2026-10-01"}}, headers=auth(tok))
        assert r.status_code == 200, r.text
        # 관리자는 기본 문서의 원문(자리표시 그대로)을 받아 고쳐 쓸 수 있다.
        r = await client.get("/api/admin/legal/default/terms", headers=auth(tok))
        assert r.status_code == 200 and "{{company}}" in r.json()["text"]
    finally:
        S.invalidate("legal.")
        async with session_scope() as db:
            (await db.get(User, uuid.UUID(user["id"]))).role = "user"
            await db.commit()


async def test_an_account_made_from_the_signup_page_by_google_keeps_the_agreement(client: AsyncClient, monkeypatch):
    await _provider("google")
    sub = uuid.uuid4().hex
    email = f"g{sub[:8]}@example.com"
    _fake(monkeypatch, "google", OA.Identity(provider="google", subject=sub, email=email, email_verified=True, name="구글", raw={}))
    _, cb = await _sso(client, "google", agree="true")
    assert cb.status_code == 302
    async with session_scope() as db:
        u = (await db.execute(select(User).where(User.email == email))).scalars().one()
        assert u.terms_version == LEGAL.DEFAULT_VERSION and u.terms_agreed_at is not None

    # 로그인 화면에서(동의 없이) 곧바로 만들어진 계정은 비어 있다 — 앱에 들어올 때 받는다.
    sub2 = uuid.uuid4().hex
    email2 = f"g{sub2[:8]}@example.com"
    _fake(monkeypatch, "google", OA.Identity(provider="google", subject=sub2, email=email2, email_verified=True, name="구글2", raw={}))
    await _sso(client, "google")
    async with session_scope() as db:
        u2 = (await db.execute(select(User).where(User.email == email2))).scalars().one()
        assert u2.terms_version is None


async def test_audit_logs_are_kept_a_year(client: AsyncClient):
    from memora.services import retention

    user, _ = await signup(client)
    uid = uuid.UUID(user["id"])
    async with session_scope() as db:
        old = datetime.now(UTC) - timedelta(days=400)
        await db.execute(text("INSERT INTO audit_logs (id, actor_id, actor_kind, action, created_at) VALUES (:i, :a, 'user', 'old_thing', :t)"),
                         {"i": uuid.uuid4(), "a": uid, "t": old})
        await db.commit()
    async with session_scope() as db:
        out = await retention.retention_sweep(db, {})
        await db.commit()
    assert out["audit_logs_deleted"] >= 1
    async with session_scope() as db:
        left = (await db.execute(select(AuditLog.action).where(AuditLog.actor_id == uid))).scalars().all()
    assert "old_thing" not in left and "signup" in left


def test_paid_credits_do_not_expire_under_the_rollover_cap():
    from memora.worker.handlers import rollover_plan

    # 무료만: 2×월지급 넘는 만큼 사라진다(예전과 같다).
    assert rollover_plan(700, 300) == (100.0, 300.0)
    # 5년 안에 돈 내고 받은 500 이 있으면 상한이 그만큼 늘어 아무것도 사라지지 않는다.
    assert rollover_plan(700, 300, 500) == (0.0, 300.0)
    assert rollover_plan(1400, 300, 500) == (300.0, 300.0)
