"""Domain tests against the DB: knowledge (hash embeddings), network graph, credits idempotency, notifications rules, jobs."""
from __future__ import annotations

import uuid
from datetime import UTC, datetime

import pytest
from httpx import AsyncClient

from tests.conftest import auth, signup, square_name

pytestmark = pytest.mark.asyncio


async def _run_jobs(kinds: list[str] | None = None, max_jobs: int = 20) -> int:
    from memora.db.session import session_scope
    from memora.services import jobs as J
    from memora.worker.handlers import HANDLERS
    n = 0
    for _ in range(max_jobs):
        async with session_scope() as db:
            job = await J.claim(db, "test-worker", kinds)
            if job is None:
                break
            jid, kind, payload = job.id, job.kind, dict(job.payload or {})
            try:
                res = await HANDLERS[kind](db, payload)
                await J.finish(db, job, result=res if isinstance(res, dict) else {})
            except Exception as e:  # noqa: BLE001
                await db.rollback()
                from memora.models import Job
                job = await db.get(Job, jid)
                await J.fail(db, job, str(e))
        n += 1
    return n


async def test_knowledge_ingest_search_and_visibility(client: AsyncClient):
    user, tok = await signup(client)
    files = {"file": ("faq.md", "# 회사 소개\n\nMemora랩은 개인 비서 AI를 만드는 회사입니다.\n\n## 근무\n\n재택근무를 기본으로 합니다.".encode(), "text/markdown")}
    r = await client.post("/api/knowledge/documents", files=files, data={"kind": "file"}, headers=auth(tok))
    assert r.status_code == 202, r.text
    doc = r.json()
    assert doc["status"] == "processing" and "visibility" not in doc
    assert await _run_jobs(["knowledge.index"]) >= 1
    d = (await client.get(f"/api/knowledge/documents/{doc['id']}", headers=auth(tok))).json()
    assert d["status"] == "ready" and d["chunk_count"] >= 1, d
    hits = (await client.get("/api/knowledge/search", params={"q": "재택근무"}, headers=auth(tok))).json()["items"]
    assert hits and "재택" in hits[0]["text"]
    # 외부인에게 무엇을 쓸지는 비서의 [지식] 탭이 정한다 (plan/57). 새 비서는 아무것도 고르지 않았다.
    from memora.db.session import session_scope
    from memora.models import Agent
    from memora.services import knowledge as K
    from memora.services import outsider as OUT
    from memora.services.agents import DEFAULT_CAPABILITIES
    async with session_scope() as db:
        a = Agent(owner_id=uuid.UUID(user["id"]), name="비서", provider="fake", model_id="fake-1",
                  capabilities=dict(DEFAULT_CAPABILITIES), outsider=dict(OUT.DEFAULTS))
        db.add(a)
        await db.commit()
        aid = str(a.id)

    async def outsider_hits(who: str) -> list:
        async with session_scope() as db:
            agent = await db.get(Agent, uuid.UUID(aid))
            return await K.search(db, uuid.UUID(user["id"]), "재택근무", scope=await OUT.scope(db, agent, "knowledge", who))

    for who in ("known", "stranger"):
        assert await outsider_hits(who) == [], who
    # 고르고 [인맥에게만] 이면 인맥에게는 나오고 남에게는 안 나온다.
    r = await client.put(f"/api/agents/{aid}/outsider/picks", json={"kind": "knowledge", "ids": [doc["id"]]}, headers=auth(tok))
    assert r.status_code == 200 and r.json()["knowledge"]["docs_picked"] == 1, r.text
    assert (await client.patch(f"/api/agents/{aid}/outsider", json={"knowledge": "known"}, headers=auth(tok))).status_code == 200
    assert await outsider_hits("known")
    assert await outsider_hits("stranger") == []
    # [모두에게] 면 누구에게나 나온다. [쓰지 않음] 이면 누구에게도.
    await client.patch(f"/api/agents/{aid}/outsider", json={"knowledge": "public"}, headers=auth(tok))
    assert await outsider_hits("stranger")
    await client.patch(f"/api/agents/{aid}/outsider", json={"knowledge": "off", "profile": False}, headers=auth(tok))
    assert await outsider_hits("known") == []
    # 남의 문서나 모르는 값은 고를 수 없다.
    assert (await client.patch(f"/api/agents/{aid}/outsider", json={"knowledge": "everyone"}, headers=auth(tok))).status_code == 422
    f = await client.post("/api/knowledge/faqs", json={"question": "강연 문의는 어떻게 하나요?", "answer": "이메일로 주세요."}, headers=auth(tok))
    assert f.status_code == 201
    chunks = (await client.get(f"/api/knowledge/documents/{doc['id']}/chunks", headers=auth(tok))).json()
    assert chunks["total"] == d["chunk_count"]


async def test_network_graph_operations_and_visitor_filter(client: AsyncClient):
    user, tok = await signup(client)
    a = (await client.post("/api/network/nodes", json={"kind": "person", "name": "김철수", "attrs": {"company": "ACME", "emails": ["cs@acme.com"]}, "tags": ["client"]}, headers=auth(tok))).json()
    b = (await client.post("/api/network/nodes", json={"kind": "person", "name": "이영희"}, headers=auth(tok))).json()
    c = (await client.post("/api/network/nodes", json={"kind": "organization", "name": "ACME"}, headers=auth(tok))).json()
    await client.post("/api/network/edges", json={"src_id": a["id"], "dst_id": c["id"], "rel": "works_at"}, headers=auth(tok))
    await client.post("/api/network/edges", json={"src_id": a["id"], "dst_id": b["id"], "rel": "friend"}, headers=auth(tok))
    p = (await client.get("/api/network/path", params={"from_id": b["id"], "to_id": c["id"]}, headers=auth(tok))).json()
    assert p["found"] and p["hops"] == 2
    nb = (await client.get(f"/api/network/nodes/{a['id']}", headers=auth(tok))).json()
    assert len(nb["edges"]) == 2
    g = (await client.get("/api/network/graph", headers=auth(tok))).json()
    # Four, not three: the graph is an ego network and always carries the owner's own node,
    # created on first look (plan/31).
    # 떠 있던 두 사람은 나에게 바로 이어진다(plan/79) — 회사는 김철수를 거쳐 닿는다.
    assert len(g["nodes"]) == 4 and sorted(e["rel"] for e in g["edges"]) == ["friend", "network", "network", "works_at"]
    assert next(n for n in g["nodes"] if n["name"] == "ACME")["hops"] == 2
    me = [n for n in g["nodes"] if n["is_self"]]
    assert len(me) == 1 and me[0]["id"] == g["self_id"] and me[0]["person"] == "self"
    assert {n["person"] for n in g["nodes"] if not n["is_self"]} == {"offline"}, "hand-written cards are not people yet"
    st = (await client.get("/api/network/stats", headers=auth(tok))).json()
    assert st["nodes"] == 4 and st["kinds"]["person"] == 3
    from memora.db.session import session_scope
    from memora.services import network as N
    from memora.services.outsider import Scope
    # 외부인 대화에서는 비서가 고른 사람만 (plan/57) — 여기서는 김철수와 ACME 를 골랐다고 친다.
    picked = Scope(ids=frozenset({uuid.UUID(a["id"]), uuid.UUID(c["id"])}))
    async with session_scope() as db:
        rows = await N.search(db, uuid.UUID(user["id"]), "영희", viewer="stranger", scope=picked)
        assert rows == []
        nb_out = await N.neighbors(db, uuid.UUID(user["id"]), uuid.UUID(a["id"]), viewer="stranger", scope=picked)
        # 고르지 않은 이영희는 이웃으로도, 관계의 끝으로도 나오지 않는다.
        assert {n["name"] for n in nb_out["nodes"]} == {"김철수", "ACME"} and len(nb_out["edges"]) == 1
        rows2 = await N.search(db, uuid.UUID(user["id"]), "철수", viewer="stranger", scope=picked)
        # 이름과 회사는 카드가 되지만 내가 적어 둔 연락처는 범위와 무관하게 안 나간다.
        assert rows2 and "emails" not in rows2[0]["attrs"]
        node, score = await N.match_visitor(db, uuid.UUID(user["id"]), name="김철수", email=None, company="ACME")
        assert node is not None and node.name == "김철수" and score >= 0.85
    # A person the secretary merely heard about resolves to nobody: no account, never talked
    # to this owner. It retires itself instead of becoming a card the owner cannot act on
    # and a name in the graph that was never anybody (plan/31).
    from memora.db.session import session_scope as ss
    async with ss() as db:
        prop = await N.propose(db, uuid.UUID(user["id"]), agent_id=None, kind="add_node", payload={"kind": "person", "name": "박민수", "attrs": {"company": "Beta"}})
    props = (await client.get("/api/network/proposals", headers=auth(tok))).json()["items"]
    assert not any(x["id"] == str(prop.id) for x in props)
    assert (await client.get("/api/network/nodes", params={"q": "박민수"}, headers=auth(tok))).json()["items"] == []
    dup = (await client.post("/api/network/nodes", json={"kind": "person", "name": "김철수(중복)"}, headers=auth(tok))).json()
    m = (await client.post(f"/api/network/nodes/{dup['id']}/merge", json={"into_id": a["id"]}, headers=auth(tok))).json()
    assert "김철수(중복)" in m["aliases"]
    csv = "name,email,company,tags\n최지우,jw@x.com,X,vip|friend\n"
    r = await client.post("/api/network/import/csv", files={"file": ("c.csv", csv.encode(), "text/csv")}, headers=auth(tok))
    assert r.json()["imported"] == 1


async def test_credit_charge_is_idempotent_and_precheck_blocks(client: AsyncClient):
    from memora.core.errors import PaymentRequired
    from memora.db.session import session_scope
    from memora.services import credits as CR
    user, tok = await signup(client)
    uid = uuid.UUID(user["id"])
    turn_id = uuid.uuid4()
    async with session_scope() as db:
        b0 = await CR.balance(db, uid)
        await CR.charge_turn(db, owner_id=uid, agent_id=uuid.uuid4(), turn_id=turn_id, provider="fake", model_id="m", input_tokens=1000,
                             output_tokens=1000, cache_read=0, cache_write=0, cost_usd=0.01, credits=3, audience="visitor")
    async with session_scope() as db:
        await CR.charge_turn(db, owner_id=uid, agent_id=uuid.uuid4(), turn_id=turn_id, provider="fake", model_id="m", input_tokens=1000,
                             output_tokens=1000, cache_read=0, cache_write=0, cost_usd=0.01, credits=3, audience="visitor")
        b1 = await CR.balance(db, uid)
        assert b0 - b1 == 3
        await CR.apply(db, uid, -float(b1), "adjust", note="drain")
    async with session_scope() as db:
        with pytest.raises(PaymentRequired):
            await CR.precheck(db, uid)
    r = await client.get("/api/credits/ledger", headers=auth(tok))
    kinds = [x["kind"] for x in r.json()["items"]]
    assert kinds.count("turn") == 1 and "grant" in kinds
    usage = (await client.get("/api/credits/usage", headers=auth(tok))).json()
    assert usage["daily"] and usage["daily"][-1]["visitor_turns"] == 1


async def test_notification_rules_and_channel_delivery_path(client: AsyncClient):
    user, tok = await signup(client)
    chans = (await client.get("/api/notifications/channels", headers=auth(tok))).json()
    assert any(c["kind"] == "email" for c in chans["items"])
    rules = (await client.get("/api/notifications/rules", headers=auth(tok))).json()["items"]
    assert any(r["event"] == "visitor_message" for r in rules)
    wh = await client.post("/api/notifications/channels", json={"kind": "webhook", "config": {"url": "http://127.0.0.1:9/x", "secret": "s"}, "label": "hook"}, headers=auth(tok))
    assert wh.status_code == 422
    from memora.db.session import session_scope
    from memora.services import notifications as NT
    async with session_scope() as db:
        n = await NT.evaluate(db, owner_id=uuid.UUID(user["id"]), event="visitor_message", payload={"text": "hi", "agent_name": "x"}, urgency=3)
        assert n == 1
        n0 = await NT.evaluate(db, owner_id=uuid.UUID(user["id"]), event="visitor_new_conversation", payload={}, urgency=1)
        assert n0 == 0
    log = (await client.get("/api/notifications/log", headers=auth(tok))).json()["items"]
    assert log and log[0]["status"] == "pending"
    await _run_jobs(["notify.send"])
    log2 = (await client.get("/api/notifications/log", headers=auth(tok))).json()["items"]
    assert log2[0]["status"] in ("pending", "failed") and log2[0]["error"]


async def test_jobs_claim_dedupe_and_retry():
    from memora.db.session import session_scope
    from memora.services import jobs as J
    async with session_scope() as db:
        j1 = await J.enqueue(db, "test.noop", {"a": 1}, dedupe_key="dd")
        j2 = await J.enqueue(db, "test.noop", {"a": 2}, dedupe_key="dd")
        assert j1 is not None and j2 is None
    async with session_scope() as db:
        job = await J.claim(db, "w1", ["test.noop"])
        assert job is not None and job.status == "running" and job.attempts == 1
        await J.fail(db, job, "boom")
        assert job.status == "queued" and job.run_at > job.created_at
    async with session_scope() as db:
        job = await J.claim(db, "w1", ["test.noop"])
        assert job is None


async def test_profile_visibility_rendering_and_private_literals(client: AsyncClient):
    user, tok = await signup(client)
    await client.put("/api/users/me/profile", json={"data": {"full_name": "홍길동", "title": "대표", "location": "서울 강남구", "contact": {"phone": "010-0000-1111", "email": "gd@x.com"}},
                                                  "visibility": {"location": "private"}}, headers=auth(tok))
    from memora.db.session import session_scope
    from memora.services import profile as PF
    from memora.services.agents import DEFAULT_DISCLOSURE
    async with session_scope() as db:
        p = await PF.get(db, uuid.UUID(user["id"]))
        owner_view = PF.render_profile(p, DEFAULT_DISCLOSURE, "owner")
        visitor_view = PF.render_profile(p, DEFAULT_DISCLOSURE, "visitor")
        assert "010-0000-1111" in owner_view and "서울 강남구" in owner_view
        assert "010-0000-1111" not in visitor_view and "서울 강남구" not in visitor_view
        assert "gd@x.com" not in visitor_view          # default policy keeps contact details private
        assert "on request" not in visitor_view.lower()  # two levels: hidden fields leave no trace
        lits = PF.private_literals(p, DEFAULT_DISCLOSURE)
        assert "010-0000-1111" in lits and "서울 강남구" in lits and "gd@x.com" in lits


async def test_admin_settings_secrets_masked_and_catalog(client: AsyncClient):
    from sqlalchemy import select

    from memora.db.session import session_scope
    from memora.models import User
    async with session_scope() as db:
        admin = (await db.execute(select(User).where(User.role == "admin"))).scalars().first()
    r = await client.post("/api/auth/login", json={"email": admin.email, "password": "correct-horse-9"})
    tok = r.json()["access_token"]
    r = await client.put("/api/admin/settings", json={"values": {"providers.openai.api_key": "sk-test-1234567890", "branding.service_name": "지니"}}, headers=auth(tok))
    assert r.status_code == 200
    view = r.json()
    assert view["providers.openai.api_key"]["has_value"] is True and "sk-test-1234567890" not in str(view)
    assert view["branding.service_name"] == "지니"
    models = (await client.get("/api/admin/models", headers=auth(tok))).json()["items"]
    assert any(m["provider"] == "claude_code" for m in models)
    ov = (await client.get("/api/admin/overview", headers=auth(tok))).json()
    assert "users" in ov and "claude" in ov
    inv = (await client.post("/api/admin/invites", json={"max_uses": 1}, headers=auth(tok))).json()
    assert inv["code"]
    aud = (await client.get("/api/admin/audit", headers=auth(tok))).json()["items"]
    assert any(a["action"] == "settings_update" for a in aud)


async def test_misc_endpoints(client: AsyncClient):
    user, tok = await signup(client)
    a = (await client.post("/api/agents", json={"name": "S"}, headers=auth(tok))).json()
    st = (await client.get(f"/api/agents/{a['id']}/stats", headers=auth(tok))).json()
    assert st["turns"] == 0 and "daily" in st
    convs = (await client.get("/api/conversations", headers=auth(tok))).json()
    assert convs["items"] == []
    m = await client.get("/metrics")
    assert m.status_code == 200 and "memora_runtime_sessions" in m.text
    r = await client.post("/api/telemetry/client-error", json={"message": "boom", "url": "/x"})
    assert r.status_code == 202
    assert await _run_jobs(["stats.refresh"]) >= 0


async def test_public_legal_and_avatar_upload(client: AsyncClient):
    r = await client.get("/api/public/legal")
    assert r.status_code == 200 and "terms" in r.json()
    user, tok = await signup(client)
    png = bytes.fromhex("89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c4890000000d49444154789c63f8cfc0f01f00050001ff89993d1d0000000049454e44ae426082")
    up = await client.post("/api/uploads", files={"file": ("a.png", png, "image/png")}, data={"kind": "avatar"}, headers=auth(tok))
    assert up.status_code == 201, up.text
    url = up.json()["url"]
    assert url.startswith("/api/public/uploads/")
    assert (await client.get(url)).status_code == 200
    att = await client.post("/api/uploads", files={"file": ("a.png", png, "image/png")}, data={"kind": "attachment"}, headers=auth(tok))
    assert (await client.get(f"/api/public/uploads/{att.json()['upload_id']}")).status_code == 404


async def test_visitor_simulator_runs_without_a_visitor_row(client, app):
    """The owner's simulator drives the visitor path with no visitor: it used to crash with
    AttributeError on the rate-limit key and surface as 'internal error' in the chat."""
    from tests.conftest import auth, read_sse, signup
    user, tok = await signup(client)
    a = (await client.post("/api/agents", json={"name": "시뮬"}, headers=auth(tok))).json()
    sim = await client.post(f"/api/agents/{a['id']}/simulate", headers=auth(tok))
    assert sim.status_code == 201, sim.text
    cid = sim.json()["id"]
    async with client.stream("POST", f"/api/agents/{a['id']}/conversations/{cid}/turns",
                             json={"text": "이 분은 어떤 일을 하시나요?"}, headers=auth(tok)) as r:
        assert r.status_code == 200, r.status_code
        events = await read_sse(r)
    assert not any((e.get("code") == "internal_error") for e in events), events[:3]
    assert events, "the simulated turn produced no events"


async def test_agent_copy_follows_renames(client, app):
    """Greeting and role line are rendered from the current names while the owner has not
    written their own — renaming the agent or the owner must not leave stale copy behind."""
    from tests.conftest import auth, signup
    user, tok = await signup(client, name="처음이름")
    a = (await client.post("/api/agents", json={"name": "첫이름"}, headers=auth(tok))).json()
    assert a["greeting"] == "" and a["role_line"] == ""
    assert "첫이름" in a["greeting_display"] and "처음이름" in a["greeting_display"]

    renamed = (await client.patch(f"/api/agents/{a['id']}", json={"name": "제니"}, headers=auth(tok))).json()
    assert "제니" in renamed["greeting_display"]

    # the profile name wins over the account label, everywhere
    await client.put("/api/users/me/profile", json={"data": {"preferred_name": "하렴 사장님"}}, headers=auth(tok))
    after = (await client.get(f"/api/agents/{a['id']}", headers=auth(tok))).json()
    # …and an owner who wrote their own honorific must not be greeted as "사장님님"
    assert after["greeting_display"] == "안녕하세요, 하렴 사장님의 비서 제니입니다. 무엇을 도와드릴까요?", after["greeting_display"]
    assert after["role_line_display"] == "하렴 사장님의 업무 비서"

    # an owner-written greeting is never overwritten
    custom = (await client.patch(f"/api/agents/{a['id']}", json={"greeting": "반가워요!"}, headers=auth(tok))).json()
    assert custom["greeting_display"] == "반가워요!"


async def test_owner_honorific_is_added_once():
    from memora.services.agents import honorific
    assert honorific("장하렴") == "장하렴님"
    assert honorific("하렴 사장님") == "하렴 사장님"
    assert honorific("김 선생님") == "김 선생님"
    assert honorific("Hyeryeom") == "Hyeryeom님"


async def test_base_prompt_is_composed_from_configured_values_only(client, app):
    """The base layer states who the secretary works for, names only resources that exist,
    and keeps the owner's own instructions subordinate to it."""
    from tests.conftest import auth, signup
    user, tok = await signup(client, name="장하렴")
    await client.put("/api/users/me/profile", headers=auth(tok), json={
        "data": {"full_name": "장하렴", "preferred_name": "하렴 사장님", "title": "파트리더", "company": "플래티어"},
        "visibility": {"title": "public", "company": "public"}})
    a = (await client.post("/api/agents", json={"name": "제니"}, headers=auth(tok))).json()

    owner_view = (await client.get(f"/api/agents/{a['id']}/prompt?audience=owner", headers=auth(tok))).json()
    base = owner_view["base_prompt"]
    assert "You are **제니**, the personal secretary of **하렴 사장님**" in base
    assert "파트리더" in base and "플래티어" in base
    # nothing configured yet → the resources section is absent, not an empty list of promises
    assert "# 4. What the owner has given you" not in base
    assert "Audience: OWNER" in base

    visitor_view = (await client.get(f"/api/agents/{a['id']}/prompt?audience=visitor", headers=auth(tok))).json()
    vbase = visitor_view["base_prompt"]
    assert "Audience: VISITOR" in vbase
    assert "이분" in vbase and "means the owner" in vbase          # the deixis rule the model kept missing
    assert "What you may say about the owner" in vbase
    assert "not in this conversation at all" in vbase   # private is absence, not a locked door
    tools_section = vbase.split("# 3. Your tools")[1].split("# 5.")[0]
    assert "profile_update" not in tools_section      # owner-only tool never advertised
    assert "profile_disclose" not in tools_section    # the middle level is gone, and so is its tool

    # layer 2 is the owner's, and explicitly cannot loosen layer 1
    assert "Secretary instructions (written by the owner)" in owner_view["secretary_prompt"]
    assert "never loosen" in owner_view["secretary_prompt"]
    assert owner_view["custom_default"].startswith("내 비서가")   # Korean owner gets a Korean draft

    # a configured resource shows up, and only then — indexed documents only, since a
    # document still being processed is not searchable yet
    files = {"file": ("company.txt", "플래티어는 AI 회사입니다.".encode(), "text/plain")}
    r = await client.post("/api/knowledge/documents", files=files,
                          data={"kind": "file", "title": "회사 소개"}, headers=auth(tok))
    assert r.status_code in (200, 201, 202), r.text
    from sqlalchemy import select as _select

    from memora.db.session import session_scope
    from memora.models import KnowledgeDocument
    async with session_scope() as db:
        doc = (await db.execute(_select(KnowledgeDocument).where(KnowledgeDocument.title == "회사 소개"))).scalars().first()
        doc.status = "ready"
        doc_id = str(doc.id)
    # 나와의 대화에는 곧바로 들어간다.
    mine = (await client.get(f"/api/agents/{a['id']}/prompt?audience=owner", headers=auth(tok))).json()["base_prompt"]
    assert "**Knowledge base**: 1 document(s)" in mine and "회사 소개" in mine
    # 외부인에게는 비서가 [지식] 탭에서 고른 뒤에야 (plan/57).
    before = (await client.get(f"/api/agents/{a['id']}/prompt?audience=visitor", headers=auth(tok))).json()["base_prompt"]
    assert "Knowledge base" not in before
    await client.put(f"/api/agents/{a['id']}/outsider/picks", json={"kind": "knowledge", "ids": [doc_id]}, headers=auth(tok))
    after = (await client.get(f"/api/agents/{a['id']}/prompt?audience=visitor", headers=auth(tok))).json()["base_prompt"]
    assert "# 4. What the owner has given you" in after
    assert "**Knowledge base**: 1 document(s)" in after and "회사 소개" in after


async def test_creating_a_secretary_needs_a_verified_email(client, app):
    """Signing up is one step; owning a secretary is where the address has to be real."""
    from memora.db.session import session_scope
    from memora.models import User
    from memora.services import settings as S
    from tests.conftest import auth, signup
    async with session_scope() as db:
        await S.put(db, "signup.verify_before_agent", True)
    try:
        user, tok = await signup(client)
        r = await client.post("/api/agents", json={"name": "막힘"}, headers=auth(tok))
        assert r.status_code == 403 and r.json()["error"]["code"] == "email_verification_required"
        async with session_scope() as db:
            u = await db.get(User, uuid.UUID(user["id"]))
            u.email_verified_at = datetime.now(UTC)
        assert (await client.post("/api/agents", json={"name": "열림"}, headers=auth(tok))).status_code == 201
    finally:
        async with session_scope() as db:
            await S.put(db, "signup.verify_before_agent", False)


async def test_prompt_preview_is_the_prompt_not_a_second_copy(client, app):
    """The console's preview dialog and /prompt must be the same text.

    The dialog used to build its own approximation from a legacy module, so it kept
    advertising a three-level disclosure model ("on request") months after the product
    settled on public/private.
    """
    from tests.conftest import auth, signup
    _, tok = await signup(client, name="장하렴")
    a = (await client.post("/api/agents", json={"name": "제니"}, headers=auth(tok))).json()
    for audience in ("owner", "visitor"):
        prompt = (await client.get(f"/api/agents/{a['id']}/prompt?audience={audience}", headers=auth(tok))).json()
        preview = (await client.get(f"/api/agents/{a['id']}/prompt-preview?audience={audience}", headers=auth(tok))).json()
        sections = {s["key"]: s["text"] for s in preview["sections"]}
        assert [s["name"] for s in prompt["base_sections"]] == [k for k in sections if k != "secretary"]
        assert prompt["base_prompt"] == "\n\n".join(t for k, t in sections.items() if k != "secretary")
        assert prompt["secretary_prompt"] == sections["secretary"]
        whole = "\n".join(sections.values())
        assert "on request" not in whole.lower()   # two levels only: public / private
        assert "Working mode:" not in whole        # the legacy heading, gone with its module
    bad = await client.get(f"/api/agents/{a['id']}/prompt-preview?audience=nobody", headers=auth(tok))
    assert bad.status_code == 422


async def test_documents_index_without_an_embedding_key(client, app):
    """A key-less install must still be able to use its documents: indexing drops the vector
    leg instead of failing the document, and keyword search still finds it."""
    from sqlalchemy import select as _select

    from memora.db.session import session_scope
    from memora.models import KnowledgeChunk
    from memora.services import settings as S
    from tests.conftest import auth, signup

    user, tok = await signup(client)
    async with session_scope() as db:
        await S.put(db, "embedding.provider", "openai")      # configured, but no key exists
        await S.put(db, "providers.openai.api_key", "")
    try:
        files = {"file": ("policy.md", "# 환불 정책\n\n환불은 결제일로부터 14일 이내에 가능합니다.".encode(), "text/markdown")}
        r = await client.post("/api/knowledge/documents", files=files,
                              data={"kind": "file", "visibility": "public", "title": "환불 정책"}, headers=auth(tok))
        assert r.status_code == 202, r.text
        doc_id = r.json()["id"]
        assert await _run_jobs(["knowledge.index"]) >= 1

        listing = (await client.get("/api/knowledge/documents", headers=auth(tok))).json()
        assert listing["semantic_search"] is False          # the UI can say why
        doc = next(d for d in listing["items"] if d["id"] == doc_id)
        assert doc["status"] == "ready", doc
        assert doc["chunk_count"] >= 1

        async with session_scope() as db:
            chunks = (await db.execute(_select(KnowledgeChunk).where(KnowledgeChunk.document_id == uuid.UUID(doc_id)))).scalars().all()
            assert chunks and all(c.embedding is None for c in chunks)   # indexed, just not embedded

        hits = (await client.get("/api/knowledge/search", params={"q": "환불", "audience": "owner"}, headers=auth(tok))).json()["items"]
        assert any("환불" in h["text"] for h in hits), hits
    finally:
        async with session_scope() as db:
            await S.put(db, "embedding.provider", "hash")


async def test_faq_keyword_fallback_matches_a_differently_worded_question(client, app):
    """Without embeddings the FAQ leg fell back to matching the whole sentence as one LIKE
    pattern, which never fires: a visitor never phrases the question the way it was stored."""
    import uuid as _uuid

    from memora.db.session import session_scope
    from memora.services import knowledge as K
    from memora.services import settings as S
    from tests.conftest import auth, signup

    user, tok = await signup(client)
    await client.post("/api/knowledge/faqs", headers=auth(tok),
                      json={"question": "지원하는 결제사가 어디인가요?", "answer": "토스페이먼츠와 나이스페이를 지원합니다."})
    async with session_scope() as db:
        await S.put(db, "embedding.provider", "openai")   # configured, no key → no vectors
        await S.put(db, "providers.openai.api_key", "")
    try:
        async with session_scope() as db:
            hits = await K.search_faqs(db, _uuid.UUID(user["id"]), "어떤 결제사를 지원하나요?", qvec=None)
            assert hits and "토스페이먼츠" in hits[0]["text"], hits
            assert hits[0]["score"] < K.FAQ_THRESHOLD    # keyword evidence, not a semantic match
            none = await K.search_faqs(db, _uuid.UUID(user["id"]), "주차는 어디에 하나요?", qvec=None)
            assert not none, none
    finally:
        async with session_scope() as db:
            await S.put(db, "embedding.provider", "hash")


async def test_faq_tokens_strip_korean_particles():
    from memora.services.knowledge import faq_tokens
    assert "결제사" in faq_tokens("어떤 결제사를 지원하나요?")
    assert "결제사" in faq_tokens("지원하는 결제사가 어디인가요?")
    assert faq_tokens("어떤 무엇 뭐") == []          # question words alone carry nothing


async def test_inbox_list_is_advertised_to_the_owner(client, app):
    """A hidden tool must be found with ToolSearch first; the owner asking "did anyone leave
    a message?" every day should not depend on that extra step."""
    import uuid as _uuid

    from memora.db.session import session_scope
    from memora.models import Agent, User
    from memora.pipeline.context import TurnContext
    from memora.pipeline.tools.base import core_overrides_for
    from memora.services import plans as P
    from memora.services import profile as PF
    from tests.conftest import auth, signup

    user, tok = await signup(client)
    a = (await client.post("/api/agents", json={"name": "인박스"}, headers=auth(tok))).json()
    async with session_scope() as db:
        owner = await db.get(User, _uuid.UUID(user["id"]))
        agent = await db.get(Agent, _uuid.UUID(a["id"]))
        ctx = TurnContext(owner=owner, agent=agent, audience="owner", conversation_id=agent.id, turn_id=None,
                          profile=await PF.get(db, owner.id), plan=await P.plan_for_user(db, owner),
                          memory=None, visitor=None, features=set(), locale="ko")
        core = core_overrides_for(ctx)
    assert core.get("inbox_list") is True, "inbox_list must be advertised, not hidden behind ToolSearch"


async def test_community_counters_survive_concurrent_writers(client, app):
    """Likes and views are decided by the database, not by a prior read.

    Two pods tapping like at the same moment must not both count, and a reader refreshing a
    post must not inflate its view count — both are single statements whose row count is the
    source of truth.
    """
    import asyncio

    from memora.db.session import session_scope
    from memora.models import CommunityPost
    from memora.services import community as C
    from tests.conftest import auth, signup

    user, tok = await signup(client)
    async with session_scope() as db:
        await C.seed_boards(db)
    await square_name(client, tok)
    r = await client.post("/api/community/posts", headers=auth(tok),
                          json={"board": "free", "title": "동시성", "body": "본문"})
    assert r.status_code == 201, r.text
    pid = r.json()["id"]

    # the same submit twice is one post
    again = await client.post("/api/community/posts", headers=auth(tok),
                              json={"board": "free", "title": "중복", "body": "본문", "client_token": "t1"})
    dup = await client.post("/api/community/posts", headers=auth(tok),
                            json={"board": "free", "title": "중복", "body": "본문", "client_token": "t1"})
    assert again.json()["id"] == dup.json()["id"]

    # a like toggles once however many times it races
    await asyncio.gather(*[client.post(f"/api/community/posts/{pid}/like", headers=auth(tok)) for _ in range(1)])
    async with session_scope() as db:
        p = await db.get(CommunityPost, uuid.UUID(pid))
        assert p.like_count == 1
    await client.post(f"/api/community/posts/{pid}/like", headers=auth(tok))
    async with session_scope() as db:
        p = await db.get(CommunityPost, uuid.UUID(pid))
        assert p.like_count == 0

    # reading the post repeatedly is one view for the day
    for _ in range(3):
        assert (await client.get(f"/api/community/posts/{pid}", headers=auth(tok))).status_code == 200
    async with session_scope() as db:
        p = await db.get(CommunityPost, uuid.UUID(pid))
        assert p.view_count == 1

    # a comment moves the post's counter, and deleting it moves it back
    c = await client.post(f"/api/community/posts/{pid}/comments", headers=auth(tok), json={"body": "댓글"})
    assert c.status_code == 201
    async with session_scope() as db:
        assert (await db.get(CommunityPost, uuid.UUID(pid))).comment_count == 1
    assert (await client.delete(f"/api/community/comments/{c.json()['id']}", headers=auth(tok))).status_code == 200
    async with session_scope() as db:
        assert (await db.get(CommunityPost, uuid.UUID(pid))).comment_count == 0

    # someone else cannot edit your post
    _, other = await signup(client)
    assert (await client.patch(f"/api/community/posts/{pid}", headers=auth(other), json={"title": "탈취"})).status_code == 403


async def test_community_search_and_notifications(client, app):
    """Two things that were only claimed until now: Korean search actually matches, and a
    comment reaches the author's inbox without a secretary attached."""
    from sqlalchemy import select

    from memora.db.session import session_scope
    from memora.models import InboxItem
    from memora.services import community as C
    from tests.conftest import auth, signup

    author, atok = await signup(client)
    async with session_scope() as db:
        await C.seed_boards(db)
    await square_name(client, atok)
    r = await client.post("/api/community/posts", headers=auth(atok),
                          json={"board": "worklife", "title": "사수 없이 일하는 법", "body": "기록이 사수가 된다"})
    assert r.status_code == 201, r.text
    pid = r.json()["id"]

    # Korean substring search finds it — the tokenizer alone would not
    found = await client.get("/api/community/posts", headers=auth(atok), params={"q": "사수"})
    assert any(p["id"] == pid for p in found.json()["items"])

    # a comment from someone else lands in the author's inbox, with no agent
    _, other = await signup(client, name="박실명")
    other_pen = await square_name(client, other)
    c = await client.post(f"/api/community/posts/{pid}/comments", headers=auth(other), json={"body": "공감합니다"})
    assert c.status_code == 201
    async with session_scope() as db:
        rows = (await db.execute(select(InboxItem).where(InboxItem.owner_id == uuid.UUID(author["id"])))).scalars().all()
        note = [i for i in rows if i.kind == "community_comment"]
        assert note and note[0].agent_id is None
        # 알림도 광장 이름으로 온다 (plan/51 §2). 글과 댓글에서 실명을 걷어내고도
        # 알림이 실명을 들고 나가면, 내 글에 달린 댓글 하나로 그 사람의 계정 이름을
        # 알게 된다 — 숨긴 줄 알고 쓴 사람에게는 이것이 가장 큰 구멍이다.
        assert note[0].payload["actor_name"] == other_pen
        assert "박실명" not in note[0].payload["actor_name"]
    inbox = await client.get("/api/inbox", headers=auth(atok), params={"source": "community"})
    assert any(i["kind"] == "community_comment" for i in inbox.json()["items"])
    assert (await client.get("/api/inbox", headers=auth(atok), params={"source": "agent"})).json()["items"] == []

    # commenting on your own post does not notify you
    before = len((await client.get("/api/inbox", headers=auth(atok), params={"source": "community"})).json()["items"])
    await client.post(f"/api/community/posts/{pid}/comments", headers=auth(atok), json={"body": "자답"})
    after = len((await client.get("/api/inbox", headers=auth(atok), params={"source": "community"})).json()["items"])
    assert after == before

    # (writing rules are covered on their own below)


async def test_community_writing_needs_a_verified_email(client, app):
    """Reading is open to any account; writing is not. An unreachable author is a
    moderation problem, so a post and a comment both ask for a verified address."""
    from datetime import UTC, datetime

    from memora.db.session import session_scope
    from memora.models import User
    from memora.services import community as C
    from memora.services import settings as S
    from tests.conftest import auth, signup

    async with session_scope() as db:
        await C.seed_boards(db)
        await S.put(db, "community.require_verified_email", True)
    try:
        writer, wtok = await signup(client)          # verified: seeds the thread to comment on
        async with session_scope() as db:
            (await db.get(User, uuid.UUID(writer["id"]))).email_verified_at = datetime.now(UTC)
        await square_name(client, wtok)
        seed = await client.post("/api/community/posts", headers=auth(wtok),
                                 json={"board": "free", "title": "안내", "body": "본문"})
        assert seed.status_code == 201
        pid = seed.json()["id"]

        _, unverified = await signup(client)
        await square_name(client, unverified)
        post = await client.post("/api/community/posts", headers=auth(unverified),
                                 json={"board": "free", "title": "미인증", "body": "본문"})
        assert post.status_code == 403 and post.json()["error"]["code"] == "community_needs_verified_email"
        comment = await client.post(f"/api/community/posts/{pid}/comments", headers=auth(unverified), json={"body": "댓글"})
        assert comment.status_code == 403

        # reading stays open
        assert (await client.get("/api/community/posts", headers=auth(unverified))).status_code == 200
        assert (await client.get(f"/api/community/posts/{pid}", headers=auth(unverified))).status_code == 200
    finally:
        async with session_scope() as db:
            await S.put(db, "community.require_verified_email", False)


async def test_job_filters_follow_the_taxonomy_tree(client, app):
    """A posting filed under a district answers a search for its province, and the facet
    count says so before the click.

    The expansion runs in both directions and is easy to get half right: filtering by 서울
    has to reach a posting tagged 강남구, and the count shown next to 서울 has to include it.
    """
    from tests.conftest import auth, signup

    _user, tok = await signup(client)
    made = []
    for body in (
        {"title": "백엔드 엔지니어", "company": "가", "region_codes": ["11680"], "job_codes": ["dev.backend"],
         "industry_codes": ["it.saas"], "employment_type": "fulltime", "salary_min": 6000, "salary_max": 9000},
        {"title": "데이터 분석가", "company": "나", "region_codes": ["26350"], "job_codes": ["data.analyst"],
         "industry_codes": ["fin.bank"], "employment_type": "contract", "salary_min": 4000, "salary_max": 5000},
    ):
        r = await client.post("/api/community/jobs", headers=auth(tok), json=body)
        assert r.status_code == 201, r.text
        made.append(r.json()["id"])

    async def titles(**q):
        r = await client.get("/api/community/jobs", headers=auth(tok), params=q)
        assert r.status_code == 200, r.text
        return sorted(x["title"] for x in r.json()["items"])

    assert await titles(region="11") == ["백엔드 엔지니어"]          # province reaches its district
    assert await titles(region="11680") == ["백엔드 엔지니어"]       # and the district itself
    assert await titles(region="11,26") == ["데이터 분석가", "백엔드 엔지니어"]  # widens within a dimension
    assert await titles(job="dev") == ["백엔드 엔지니어"]            # family reaches its title
    assert await titles(industry="fin") == ["데이터 분석가"]
    assert await titles(region="11", job="data") == []              # dimensions narrow
    assert await titles(min_salary=6000) == ["백엔드 엔지니어"]
    assert await titles(max_experience=0) == ["데이터 분석가", "백엔드 엔지니어"]

    facets = (await client.get("/api/community/jobs/facets", headers=auth(tok))).json()
    assert facets["region"]["11"] == 1 and facets["region"]["11680"] == 1, facets["region"]
    assert facets["job"]["dev"] == 1 and facets["job"]["dev.backend"] == 1
    assert facets["type"] == {"fulltime": 1, "contract": 1}

    # The display line follows the codes, so a listing cannot show one place and be filed
    # under another.
    one = (await client.get("/api/community/jobs", headers=auth(tok), params={"region": "11680"})).json()["items"][0]
    assert one["location"] == "서울 강남구"


async def test_job_posting_drops_codes_the_taxonomy_does_not_define(client, app):
    """A code nobody can pick would file the posting where no filter can reach it."""
    from tests.conftest import auth, signup

    _user, tok = await signup(client)
    r = await client.post("/api/community/jobs", headers=auth(tok),
                          json={"title": "테스트", "company": "다",
                                "region_codes": ["11680", "99999", "11680"], "job_codes": ["nope"]})
    assert r.status_code == 201, r.text
    got = (await client.get("/api/community/jobs", headers=auth(tok), params={"region": "11680"})).json()["items"][0]
    assert got["region_codes"] == ["11680"]      # unknown dropped, duplicate collapsed
    assert got["job_codes"] == []


async def test_job_taxonomy_is_served_whole(client, app):
    from tests.conftest import auth, signup

    _user, tok = await signup(client)
    tax = (await client.get("/api/community/jobs/taxonomy", headers=auth(tok))).json()
    assert len(tax["regions"]) >= 18
    seoul = next(r for r in tax["regions"] if r["value"] == "11")
    assert any(c["label"] == "강남구" for c in seoul["children"])
    assert any(f["value"] == "dev" for f in tax["jobs"])
    assert "fulltime" in tax["employment_types"]


async def test_two_people_never_stand_under_one_square_name(client, app):
    """지어 주는 이름은 80가지뿐이라 부딪힌다 (plan/52).

    운영 열한 명에서 이미 부딪혔다: 한 사람이 고른 이름과 다른 사람의 지어 준
    이름이 같았다. 익명 게시판에서 같은 이름 둘은 서로를 사칭하는 것과 같으므로,
    광장에서 입을 열 때 이름을 **받아 적고** 부딪히면 비켜 간다.
    """
    from memora.db.session import session_scope
    from memora.models import User
    from memora.services import community as C
    from tests.conftest import auth, signup

    author, atok = await signup(client)
    async with session_scope() as db:
        await C.seed_boards(db)
    await square_name(client, atok)
    r = await client.post("/api/community/posts", headers=auth(atok),
                          json={"board": "worklife", "title": "이름은 하나", "body": "광장에서는 그 이름이 나다"})
    pid = r.json()["id"]

    # 댓글을 다는 사람의 지어 줄 이름을 누군가 이미 쓰고 있다
    commenter, ctok = await signup(client)
    async with session_scope() as db:
        u = await db.get(User, uuid.UUID(author["id"]))
        u.community_name = C.pen_name_for(uuid.UUID(commenter["id"]))
        await db.commit()

    c = await client.post(f"/api/community/posts/{pid}/comments", headers=auth(ctok), json={"body": "동감이에요"})
    assert c.status_code == 201
    async with session_scope() as db:
        me = await db.get(User, uuid.UUID(commenter["id"]))
        other = await db.get(User, uuid.UUID(author["id"]))
        assert me.community_name                                   # 받아 적혔고
        assert me.community_name != other.community_name           # 남의 이름이 아니고
        assert me.community_name_at is None                        # 내가 고른 것이 아니니 시계는 그대로다
    # 그러니 이 사람은 아직 제 이름을 한 번 고를 수 있다
    assert (await client.put("/api/users/me/community-name", json={"name": "내가고른이름"},
                             headers=auth(ctok))).status_code == 200


async def test_the_secretary_cannot_see_the_square_through_the_inbox(client, app):
    """비서는 광장을 보지 않는다 (plan/51 §2).

    지식 문서로 가는 다리는 지웠는데 인박스는 열려 있었다. 내 익명 글에 달린 댓글
    알림은 제목 하나만 읽어도 "내 주인이 광장에 그 글을 썼다" 가 되고, 그 앎이
    언젠가 방문자 앞에서 두 이름을 잇는다.
    """
    from memora.core.errors import NotFound
    from memora.db.session import session_scope
    from memora.services import community as C
    from memora.services import inbox as I
    from tests.conftest import auth, signup

    author, atok = await signup(client)
    async with session_scope() as db:
        await C.seed_boards(db)
    await square_name(client, atok)
    r = await client.post("/api/community/posts", headers=auth(atok),
                          json={"board": "worklife", "title": "광장에 쓴 글", "body": "여기서는 익명이다"})
    pid = r.json()["id"]
    _, other = await signup(client)
    assert (await client.post(f"/api/community/posts/{pid}/comments", headers=auth(other),
                              json={"body": "저도요"})).status_code == 201

    async with session_scope() as db:
        mine = await I.list_items(db, uuid.UUID(author["id"]))
        square = [i for i in mine if i.kind == "community_comment"]
        assert square, "주인의 인박스에는 있어야 한다"
        # 비서가 부르면 없는 것으로 보인다
        theirs = await I.list_items(db, uuid.UUID(author["id"]), secretary=True)
        assert all(i.kind not in I.COMMUNITY_KINDS for i in theirs)
        # 목록에서 가렸어도 id 를 알면 읽히던 길까지 닫는다
        with pytest.raises(NotFound):
            await I.get_owned(db, uuid.UUID(author["id"]), square[0].id, secretary=True)
        # 주인 자신이 보는 길은 그대로다
        assert await I.get_owned(db, uuid.UUID(author["id"]), square[0].id)


async def test_the_public_secretary_comes_with_its_fence_up(client, app):
    """공개 비서의 상한 셋은 기본으로 서 있고, 주인이 바꾼다 (plan/53).

    공개 링크는 받는 쪽이 내는 구조다. 상한이 없는 기본값은 링크가 퍼지면 잔액이
    사라진다는 말과 같다. 셋이 각각 다른 문을 지킨다: 하루 전체, 한 곳에서 새로 여는
    대화, 한 사람의 말 속도.
    """
    from tests.conftest import auth, signup

    _, tok = await signup(client)
    a = (await client.post("/api/agents", json={"name": "문지기"}, headers=auth(tok))).json()
    vs = a["visitor_settings"]
    assert (vs["turns_per_day"], vs["sessions_per_hour"], vs["rate_per_minute"]) == (200, 30, 10)

    # 주인이 바꾼다. 설정 화면이 읽는 자리에도 그대로 실려 나온다.
    patched = (await client.patch(f"/api/agents/{a['id']}", headers=auth(tok),
                                  json={"visitor_settings": {"turns_per_day": 50, "sessions_per_hour": 5,
                                                             "rate_per_minute": 3}})).json()
    assert patched["visitor_settings"]["sessions_per_hour"] == 5
    again = (await client.get(f"/api/agents/{a['id']}", headers=auth(tok))).json()
    assert again["visitor_settings"]["turns_per_day"] == 50 and again["visitor_settings"]["sessions_per_hour"] == 5

    # 울타리 밖의 값은 거절이 아니라 울타리 안으로. 한 칸 때문에 나머지 고친 것까지
    # 사라지면 설정 화면을 못 쓴다.
    huge = (await client.patch(f"/api/agents/{a['id']}", headers=auth(tok),
                               json={"visitor_settings": {"turns_per_day": 10 ** 9, "rate_per_minute": -4}})).json()
    assert huge["visitor_settings"]["turns_per_day"] == 100_000
    assert huge["visitor_settings"]["rate_per_minute"] == 0      # 0 = 제한 없음, 주인이 고를 수 있다


async def test_one_place_cannot_open_conversations_without_end(client, app):
    """새 대화를 여는 문에도 세는 자리가 있다 (plan/53).

    방문자당 분당 제한만으로는 막지 못한다: 새 대화를 열면 그 제한도 새로 시작한다.
    그래서 한 곳(IP)이 한 시간에 여는 대화 수를 따로 센다. 이 숫자는 비서 설정에
    있고, 0이면 주인이 제한을 고르지 않은 것이다.
    """
    import os

    from tests.conftest import auth, signup

    _, tok = await signup(client)
    agent = (await client.post("/api/agents", json={"name": "문"}, headers=auth(tok))).json()
    await client.patch(f"/api/agents/{agent['id']}", headers=auth(tok),
                       json={"visitor_settings": {"sessions_per_hour": 2}})
    link = (await client.post(f"/api/agents/{agent['id']}/links", json={"label": "명함"}, headers=auth(tok))).json()

    # 0 은 제한 없음이다. 주인이 그렇게 고를 수 있어야 한다 (요금제가 계정당 비서
    # 하나라, 두 번째 비서는 다른 사람의 것이다).
    _, tok2 = await signup(client)
    other = (await client.post("/api/agents", json={"name": "열린문"}, headers=auth(tok2))).json()
    assert "id" in other, other
    await client.patch(f"/api/agents/{other['id']}", headers=auth(tok2),
                       json={"visitor_settings": {"sessions_per_hour": 0}})
    link2 = (await client.post(f"/api/agents/{other['id']}/links", json={"label": "명함"}, headers=auth(tok2))).json()

    os.environ.pop("MEMORA_RATELIMIT_DISABLED", None)   # 이 검사만 진짜로 센다
    try:
        codes = [(await client.post(f"/api/public/links/{link['code']}/visitor", json={})).status_code
                 for _ in range(3)]
        assert codes[:2] == [200, 200] and codes[2] == 429
        opened = [(await client.post(f"/api/public/links/{link2['code']}/visitor", json={})).status_code
                  for _ in range(4)]
        assert opened == [200, 200, 200, 200]
    finally:
        os.environ["MEMORA_RATELIMIT_DISABLED"] = "1"


async def test_the_trigger_ladder_walks_the_way_it_was_written(client, app):
    """plan/54 §3 의 사다리가 그대로 도는가.

    말이 없는 사람에게 30일 동안 무엇이 가는지를 엔진에 직접 물어본다. 시뮬레이터가
    규칙을 다시 적으면 거짓말을 하므로, 시뮬레이터도 `decide` 를 그대로 돈다.
    """
    from memora.services import triggers as TR

    cfg = {"enabled": True, "max_per_day": 3, "lapse_after_days": 3,
           "rules": [dict(r) for r in TR.DEFAULT_RULES]}
    ev = TR.simulate(cfg, days=30, talk_days=(0,))
    by_day: dict[int, list[str]] = {}
    for e in ev:
        by_day.setdefault(e["day"], []).append(e["rule"])

    # 오늘 말을 걸었으면 점심·저녁으로 두 번 더
    assert by_day[0] == ["lunch", "dinner"]
    # 하루 말이 없으면 하루 한 번
    assert by_day[1] == ["daily"] and by_day[2] == ["daily"]
    # 사흘째부터는 매일 거는 것을 멈춘다
    assert all("daily" not in v for d, v in by_day.items() if d >= 3)
    # 침묵 6~8일 사이에 [버림받은 느낌] 한 번
    ab = [e for e in ev if e["rule"] == "abandoned"]
    assert len(ab) == 1 and 6 <= ab[0]["day"] <= 8
    # 그로부터 5~7일 뒤에 [애원하는 느낌] 한 번, 그리고 끝
    pl = [e for e in ev if e["rule"] == "pleading"]
    assert len(pl) == 1 and 5 <= pl[0]["day"] - ab[0]["day"] <= 7
    assert max(e["day"] for e in ev) == pl[0]["day"]
    # 밤에는 걸지 않는다
    assert all(9 <= e["hour"] < 21 for e in ev)


async def test_a_pair_that_never_talked_is_never_spoken_to_first(client, app):
    """한 번도 말한 적 없는 사람에게는 걸지 않는다 (plan/54 §3). 아직 관계가 아니다."""
    from datetime import UTC, datetime, timedelta
    from types import SimpleNamespace

    from memora.services import triggers as TR

    cfg = {"enabled": True, "max_per_day": 3, "lapse_after_days": 3, "rules": [dict(r) for r in TR.DEFAULT_RULES]}
    rel = SimpleNamespace(user_id=uuid.uuid4(), agent_id=uuid.uuid4(), proactive_state={},
                          started_at=None, last_turn_at=None)
    agent, owner = SimpleNamespace(status="active"), SimpleNamespace(status="active")
    now = datetime(2026, 9, 22, 10, 0, tzinfo=UTC)
    assert TR.ladder_state(rel, now=now, tz=UTC)["state"] == "cold"
    assert TR.decide(rel, agent, owner, cfg, now=now, tz=UTC) is None
    # 꺼 두면 아무에게도 가지 않는다
    talked = SimpleNamespace(user_id=uuid.uuid4(), agent_id=uuid.uuid4(), proactive_state={},
                             started_at=now - timedelta(days=30), last_turn_at=now - timedelta(days=1))
    assert TR.decide(talked, agent, owner, cfg, now=now, tz=UTC) is not None
    assert TR.decide(talked, agent, owner, {**cfg, "enabled": False}, now=now, tz=UTC) is None
    # 방금 대화한 사람에게는 무엇도 보내지 않는다
    assert TR.decide(talked, agent, owner, cfg, now=now, tz=UTC, recent_turn=True) is None


async def test_the_admin_owns_the_trigger_rules(client, app):
    """규칙과 모델은 관리자의 것이다 (plan/54 §1·§2)."""
    from memora.db.session import session_scope
    from memora.models import User
    from memora.services import triggers as TR
    from tests.conftest import auth, signup

    user, tok = await signup(client)
    async with session_scope() as db:
        (await db.get(User, uuid.UUID(user["id"]))).role = "admin"
    got = (await client.get("/api/admin/triggers", headers=auth(tok))).json()
    assert got["enabled"] is True and len(got["rules"]) == len(TR.DEFAULT_RULES)
    assert got["running"]["model"], "실제로 도는 모델이 보여야 한다"

    rules = [dict(r) for r in got["rules"]]
    rules[1]["window"] = [8, 20]
    saved = (await client.put("/api/admin/triggers", headers=auth(tok),
                              json={"max_per_day": 2, "rules": rules})).json()
    assert saved["max_per_day"] == 2 and saved["rules"][1]["window"] == [8, 20]

    # 뜻이 없는 규칙은 저장되지 않는다 — 저장됐다고 믿게 두는 것이 더 나쁘다
    bad = (await client.put("/api/admin/triggers", headers=auth(tok),
                            json={"rules": [{**rules[0], "when": {"state": "없는칸"}}]}))
    assert bad.status_code == 422

    sim = (await client.post("/api/admin/triggers/simulate", headers=auth(tok), json={}, params={"days": 20})).json()
    assert sim["events"] and all("rule" in e for e in sim["events"])


async def test_never_saved_rules_are_not_broken_rules(client, app):
    """빈 설정은 "아직 안 정했다" 이지 "깨졌다" 가 아니다.

    관리 화면이 빨간 줄로 "규칙을 읽지 못했다" 고 말하면, 관리자는 고칠 것이 없는데
    고치려고 들어온다.
    """
    from memora.services import triggers as TR

    assert TR.normalise_rules({}) == TR.DEFAULT_RULES
    assert TR.normalise_rules({"items": []}) == TR.DEFAULT_RULES
    assert TR.normalise_rules(None) == TR.DEFAULT_RULES


async def test_a_sent_trigger_leaves_its_mark_on_the_ladder(client, app):
    """보낸 뒤에 표를 찍지 않으면 [버림받은 느낌]이 날마다 다시 나간다.

    한 번만 보내기로 한 말이 매일 오는 것은 이 기능에서 가장 나쁜 고장이다.
    """
    from datetime import UTC, datetime, timedelta
    from types import SimpleNamespace

    from memora.services import triggers as TR

    cfg = {"enabled": True, "max_per_day": 3, "lapse_after_days": 3, "rules": [dict(r) for r in TR.DEFAULT_RULES]}
    agent, owner = SimpleNamespace(status="active"), SimpleNamespace(status="active")
    # 창(10~20시)의 끝자락이면 그날 고른 시각이 몇 시든 이미 지나 있다.
    now = datetime(2026, 9, 22, 19, 0, tzinfo=UTC)
    rel = SimpleNamespace(user_id=uuid.UUID(int=7), agent_id=uuid.UUID(int=8), proactive_state={},
                          started_at=now - timedelta(days=60), last_turn_at=now - timedelta(days=9))
    first = TR.decide(rel, agent, owner, cfg, now=now, tz=UTC)
    assert first and first["rule"] == "abandoned"
    TR.remember_fired(rel, first, now=now, tz=UTC, state=TR.ladder_state(rel, now=now, tz=UTC))
    # 같은 날에도, 다음 날에도 다시 나가지 않는다
    assert TR.decide(rel, agent, owner, cfg, now=now + timedelta(minutes=30), tz=UTC) is None
    later = now + timedelta(days=1)
    assert (TR.decide(rel, agent, owner, cfg, now=later, tz=UTC) or {}).get("rule") != "abandoned"
    # 그리고 칸이 [마지막]으로 옮겨 가 있다
    assert TR.ladder_state(rel, now=later, tz=UTC)["state"] == "pleading"


async def test_a_real_send_walks_the_ladder_and_costs_the_owner_nothing(client, app, monkeypatch):
    """보내는 길 전체를 한 번 돈다 (plan/54).

    규칙이 고르고, 트리거 모델이 쓰고, 사다리에 표가 남고, **사용자의 원장에서는
    한 푼도 나가지 않는다**. 단위 검사가 각각을 확인해도 배선이 끊어지면 아무 일도
    일어나지 않으므로, 한 번은 끝에서 끝까지 돈다.
    """
    from datetime import UTC, datetime, timedelta

    from sqlalchemy import select

    from memora.db.session import session_scope
    from memora.models import AgentRelationship, UsageEvent
    from memora.services import credits as CR
    from memora.services import relationship as REL
    from tests.conftest import auth, signup

    user, tok = await signup(client)
    a = (await client.post("/api/agents", json={"name": "먼저"}, headers=auth(tok))).json()["id"]

    async def fake_complete(db, **kw):
        assert "trigger" not in kw.get("system", ""), "온도는 프롬프트에 들어가되 종류 이름은 아니다"
        return "오늘 하루 어땠어요?", {"input_tokens": 100, "output_tokens": 20}
    monkeypatch.setattr(REL, "complete", fake_complete, raising=False)
    import memora.providers.llm.simple as SIMPLE
    monkeypatch.setattr(SIMPLE, "complete", fake_complete)

    uid, aid = uuid.UUID(user["id"]), uuid.UUID(a)
    now = datetime.now(UTC)
    async with session_scope() as db:
        # 창을 하루 전체로 열어 둔다. 검사가 시계에 매달리면 밤에만 빨개진다.
        from memora.services import settings as S
        from memora.services import triggers as TR
        rules = [dict(r) for r in TR.DEFAULT_RULES]
        for r in rules:
            r["window"] = [0, 24]
        await S.put(db, "triggers.rules", {"items": rules})
        await db.commit()
    async with session_scope() as db:
        rel = await REL.get_or_create(db, uid, aid)
        rel.started_at = now - timedelta(days=40)
        rel.last_turn_at = now - timedelta(days=2)      # [조용] — 하루 한 번 거는 칸
        rel.turns, rel.active_days = 20, 10
        await db.commit()

    async with session_scope() as db:
        before = float(await CR.balance(db, uid))
        out = await REL.run_proactive(db, agent_id=aid, user_id=uid)
        await db.commit()
    assert out.get("sent") and out.get("rule") == "daily", out

    async with session_scope() as db:
        after = float(await CR.balance(db, uid))
        rel = (await db.execute(select(AgentRelationship).where(AgentRelationship.user_id == uid))).scalars().first()
        ev = (await db.execute(select(UsageEvent).where(UsageEvent.owner_id == uid, UsageEvent.kind == "trigger"))).scalars().all()
    assert after == before, "먼저 건넨 말에 사용자의 크레딧이 나가면 안 된다"
    assert len(ev) == 1 and float(ev[0].credits) == 0 and ev[0].input_tokens == 100
    # 사다리에 표가 남아 오늘 다시 나가지 않는다
    assert (rel.proactive_state or {}).get("rules_today", {}).get("daily") == 1
    async with session_scope() as db:
        again = await REL.run_proactive(db, agent_id=aid, user_id=uid)
    assert again.get("skipped") == "nothing_to_say"

    # 아직 로그인한 사람의 화면에서도 이 설정은 관리자의 것이다
    seen = (await client.get(f"/api/agents/{a}/relationship", headers=auth(tok))).json()
    assert seen["proactive"]["managed"] is True


async def test_two_messages_never_land_within_the_floor(client, app):
    """규칙의 셈이 무엇을 잊어도 두 번 잇따라 보내지 않는다 (plan/54 §7).

    운영에서 실제로 15분 간격으로 거의 같은 말이 두 번 나갔다. 원인은 앞선 발송이
    "보냈다" 는 표를 남기지 못한 것이었고, 그 표에 기대는 셈은 그래서 0을 읽었다.
    셈과 **독립된** 바닥선을 둔다: 보낼 때마다 반드시 적히는 시각 하나.
    """
    from datetime import UTC, datetime, timedelta
    from types import SimpleNamespace

    from memora.services import triggers as TR

    cfg = {"enabled": True, "max_per_day": 3, "lapse_after_days": 3, "min_gap_minutes": 120,
           "rules": [dict(r) for r in TR.DEFAULT_RULES]}
    agent, owner = SimpleNamespace(status="active"), SimpleNamespace(status="active")
    now = datetime(2026, 9, 22, 12, 0, tzinfo=UTC)
    # 방금 보냈고, 셈은 비어 있다(표를 남기지 못한 그 상황 그대로)
    rel = SimpleNamespace(user_id=uuid.UUID(int=11), agent_id=uuid.UUID(int=12), proactive_state={},
                          started_at=now - timedelta(days=30), last_turn_at=now - timedelta(days=1),
                          last_proactive_at=now - timedelta(minutes=15))
    assert TR.decide(rel, agent, owner, cfg, now=now, tz=UTC) is None
    # 바닥선을 지나면 다시 걸 수 있다
    rel.last_proactive_at = now - timedelta(minutes=121)
    assert TR.decide(rel, agent, owner, cfg, now=now, tz=UTC) is not None
    # 0 이면 바닥선이 없다 — 관리자가 그렇게 고를 수 있다
    rel.last_proactive_at = now - timedelta(minutes=1)
    assert TR.decide(rel, agent, owner, {**cfg, "min_gap_minutes": 0}, now=now, tz=UTC) is not None


async def test_a_failed_turn_records_the_real_reason(client, app, monkeypatch):
    """실패를 적는 자리가 실패하면 원인이 사라진다.

    턴을 돌린 세션의 카탈로그 행을 마무리에서 다시 읽으면, 그 턴이 실패해 세션이
    되돌려진 경우 속성이 만료돼 DetachedInstanceError 가 난다. 하필 그 자리가
    "무엇 때문에 실패했나" 를 적는 자리라, 진짜 원인(금고 폴더 권한)이 통째로
    덮였다. 마무리는 **자기 세션에서 다시 읽는다.**
    """
    from memora.db.session import session_scope
    from memora.models import Turn
    from memora.pipeline import runner as R
    from tests.conftest import auth, read_sse, signup

    _, tok = await signup(client)
    a = (await client.post("/api/agents", json={"name": "권한"}, headers=auth(tok))).json()["id"]
    c = (await client.post(f"/api/agents/{a}/conversations", json={}, headers=auth(tok))).json()["id"]

    async def boom(*args, **kw):
        raise PermissionError("[Errno 13] Permission denied: '/data/vaults/x/cli-cwd'")
    monkeypatch.setattr(R.runtimes, "get_or_create", boom)

    async with client.stream("POST", f"/api/agents/{a}/conversations/{c}/turns",
                             json={"text": "안녕"}, headers=auth(tok)) as r:
        events = await read_sse(r)
    assert any(e["type"] == "turn.error" for e in events)

    async with session_scope() as db:
        from sqlalchemy import select
        t = (await db.execute(select(Turn).where(Turn.conversation_id == uuid.UUID(c)))).scalars().first()
    assert t is not None and t.status == "failed"
    # 원인이 남아 있다. 여기 "DetachedInstanceError" 가 적히면 그건 우리가 우리 실패를
    # 덮은 것이다.
    assert "Permission denied" in (t.error_message or ""), t.error_message
    assert t.provider and t.model_id, "어떤 모델로 돌다 실패했는지도 남아야 한다"


async def test_the_anniversary_rule_says_which_day_it_is(client, app):
    """"기념일" 이라고만 적어 두면 무엇이 기념일인지 아무도 모른다.

    규칙이 날을 들고 있고(처음 대화한 날부터 센 날수, 사이가 가까워진 날), 울릴 때는
    그 까닭을 함께 내놓는다 — 말을 짓는 모델이 오늘이 무슨 날인지 알아야 한다.
    """
    from memora.services import triggers as TR

    rule = next(r for r in TR.DEFAULT_RULES if r["key"] == "anniversary")
    assert rule["when"]["days"] == [7, 30, 100, 365] and rule["when"]["stage_up"] is True
    assert TR.anniversary_reason(rule, {"days_together": 30}) == "함께한 지 30일째 되는 날"
    assert TR.anniversary_reason(rule, {"days_together": 31}) == ""
    assert TR.anniversary_reason(rule, {"days_together": 31, "stage_up": True}) == "사이가 한 단계 가까워진 날"

    # 관리자가 날을 바꾸면 그 날에 울린다
    mine = TR.normalise_rule({**rule, "when": {**rule["when"], "days": ["50", 7, 7]}})
    assert mine["when"]["days"] == [7, 50]
    # 날도 없고 가까워진 날도 끄면 영영 안 울리는 규칙이다 — 저장하지 않는다
    import pytest as _pt

    from memora.core.errors import ValidationFailed
    with _pt.raises(ValidationFailed):
        TR.normalise_rule({**rule, "when": {**rule["when"], "days": [], "stage_up": False}})

    # 시뮬레이션에도 7일째가 보인다
    cfg = {"enabled": True, "max_per_day": 3, "lapse_after_days": 3, "min_gap_minutes": 0,
           "rules": [dict(r) for r in TR.DEFAULT_RULES]}
    ev = TR.simulate(cfg, days=10, talk_days=tuple(range(10)))
    assert any(e["rule"] == "anniversary" and e["day"] == 6 for e in ev)


async def test_an_admin_can_try_a_trigger_on_their_own_secretary_without_a_trace(client, app, monkeypatch):
    """관리자는 자기 비서로 규칙의 말을 받아 본다. 그리고 **아무것도 남지 않는다.**

    메시지·사다리의 표·사용량 어느 것도 적히면 안 된다 — 시험이 운영을 건드리면,
    다음 날 그 비서가 "어제 이미 보냈다" 며 입을 닫는다.
    """
    from sqlalchemy import func, select

    from memora.db.session import session_scope
    from memora.models import AgentRelationship, Message, UsageEvent, User
    from memora.services import triggers as TR
    from tests.conftest import auth, signup

    user, tok = await signup(client)
    uid = uuid.UUID(user["id"])
    async with session_scope() as db:
        (await db.get(User, uid)).role = "admin"
    a = (await client.post("/api/agents", json={"name": "시험"}, headers=auth(tok))).json()["id"]

    import memora.providers.llm.simple as SIMPLE

    async def fake_complete(db, **kw):
        assert "30일째" in kw.get("user_text", ""), "오늘이 무슨 날인지 모델이 알아야 한다"
        return "벌써 한 달이네요.", {"input_tokens": 50, "output_tokens": 8}
    monkeypatch.setattr(SIMPLE, "complete", fake_complete)

    async def counts():
        async with session_scope() as db:
            return ((await db.execute(select(func.count()).select_from(Message))).scalar_one(),
                    (await db.execute(select(func.count()).select_from(UsageEvent).where(UsageEvent.owner_id == uid))).scalar_one(),
                    (await db.execute(select(func.count()).select_from(AgentRelationship).where(AgentRelationship.user_id == uid))).scalar_one())
    before = await counts()

    rule = {**next(r for r in TR.DEFAULT_RULES if r["key"] == "anniversary"),
            "when": {"state": "any", "occasion": "anniversary", "days": [30], "stage_up": False}}
    r = await client.post("/api/admin/triggers/test", headers=auth(tok), json={"agent_id": a, "rule": rule})
    assert r.status_code == 200, r.text
    out = r.json()
    assert out["text"] == "벌써 한 달이네요." and out["occasion"] == "함께한 지 30일째 되는 날"
    assert await counts() == before, "시험이 흔적을 남겼다"

    # 남의 비서로는 시험할 수 없다
    _, other = await signup(client)
    b = (await client.post("/api/agents", json={"name": "남의 것"}, headers=auth(other))).json()["id"]
    assert (await client.post("/api/admin/triggers/test", headers=auth(tok),
                              json={"agent_id": b, "rule": rule})).status_code == 404


async def test_the_trigger_log_shows_what_was_said_and_what_it_cost(client, app, monkeypatch):
    """발송 기록은 누구에게 무슨 말이 갔고, 얼마가 들었고, 답이 왔는지다.

    값은 사용 기록에, 말은 메시지에 있다. 둘이 한 줄로 이어져야 합계가 맞고, 줄을
    눌렀을 때 실제로 간 말을 볼 수 있다.
    """
    from datetime import UTC, datetime, timedelta

    from memora.db.session import session_scope
    from memora.models import User
    from memora.services import relationship as REL
    from memora.services import settings as S
    from memora.services import triggers as TR
    from tests.conftest import auth, signup

    user, tok = await signup(client)
    uid = uuid.UUID(user["id"])
    async with session_scope() as db:
        (await db.get(User, uid)).role = "admin"
        rules = [dict(r) for r in TR.DEFAULT_RULES]
        for r in rules:
            r["window"] = [0, 24]
        await S.put(db, "triggers.rules", {"items": rules})
    a = (await client.post("/api/agents", json={"name": "기록"}, headers=auth(tok))).json()["id"]

    import memora.providers.llm.simple as SIMPLE

    async def fake_complete(db, **kw):
        return "요즘 어떻게 지내세요?", {"input_tokens": 100, "output_tokens": 20}
    monkeypatch.setattr(SIMPLE, "complete", fake_complete)
    now = datetime.now(UTC)
    async with session_scope() as db:
        rel = await REL.get_or_create(db, uid, uuid.UUID(a))
        rel.started_at, rel.last_turn_at = now - timedelta(days=30), now - timedelta(days=1)
    async with session_scope() as db:
        out = await REL.run_proactive(db, agent_id=uuid.UUID(a), user_id=uid)
    assert out.get("sent"), out

    log = (await client.get("/api/admin/triggers/log", headers=auth(tok))).json()
    mine = [i for i in log["items"] if i["agent"]["id"] == a]
    assert mine and mine[0]["text"] == "요즘 어떻게 지내세요?" and mine[0]["rule"] == "daily"
    assert mine[0]["tokens"] == 120, "값이 말과 이어지지 않았다"
    assert log["summary"]["count"] >= 1 and log["facets"]["agents"]
    # 필터: 이 비서만, 그리고 답이 없는 것만
    only = (await client.get("/api/admin/triggers/log", headers=auth(tok),
                             params={"agent": a, "replied": "no"})).json()
    assert only["summary"]["count"] == 1 and only["summary"]["replied"] == 0
    # 답이 오면 [답이 온 것] 에만 선다 — 거르기가 실제로 걸러야 한다
    from memora.models import Message
    from memora.services import conversations as CV
    async with session_scope() as db:
        conv = await db.get(__import__("memora.models", fromlist=["Conversation"]).Conversation, uuid.UUID(mine[0]["conversation_id"]))
        await CV.add_message(db, conv, role="user", content="잘 지내요!")
    yes = (await client.get("/api/admin/triggers/log", headers=auth(tok), params={"agent": a, "replied": "yes"})).json()
    no = (await client.get("/api/admin/triggers/log", headers=auth(tok), params={"agent": a, "replied": "no"})).json()
    assert yes["summary"]["count"] == 1 and yes["items"][0]["reply"] == "잘 지내요!"
    assert no["summary"]["count"] == 0
    _ = Message
