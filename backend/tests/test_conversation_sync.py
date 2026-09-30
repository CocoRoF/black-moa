"""어디서 말하든 대화는 모든 화면에서 실시간으로 같다 (plan/69).

웹의 두 탭, PC 앱의 본창·아바타·빠른 대화가 같은 대화를 본다. 예전에는 답이 시작·끝·멈춤을 아무에게도 알리지
않아서, 말한 화면 말고는 새로 고치기 전까지 몰랐다. 이제 주인의 모든 화면에 `turn`(시작·끝)과
`conversation`(생김·바뀜·지워짐) 소식이 간다. 소식은 번호만 싣고, 말은 받는 쪽이 다시 읽는다.
"""
from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime

from httpx import AsyncClient
from sqlalchemy import select

from tests.conftest import auth, read_sse, signup


def _capture(monkeypatch) -> list[tuple[str, str, dict]]:
    from memora.core import bus

    sent: list[tuple[str, str, dict]] = []

    async def capture(db, *, owner_id, kind, data):
        sent.append((str(owner_id), kind, data))

    monkeypatch.setattr(bus, "publish", capture)
    return sent


async def _setup(client: AsyncClient):
    u, tok = await signup(client)
    a = (await client.post("/api/agents", json={"name": "제니"}, headers=auth(tok))).json()["id"]
    c = (await client.post(f"/api/agents/{a}/conversations", json={}, headers=auth(tok))).json()["id"]
    return u, tok, a, c


async def test_a_turn_is_announced_when_it_starts_and_when_it_ends(client: AsyncClient, monkeypatch):
    u, tok, a, c = await _setup(client)
    sent = _capture(monkeypatch)
    async with client.stream("POST", f"/api/agents/{a}/conversations/{c}/turns",
                             json={"text": "안녕", "client_turn_id": "web-1"}, headers=auth(tok)) as r:
        tid = r.headers["x-turn-id"]
        events = await read_sse(r)
    assert events[-1]["type"] == "turn.complete"
    turns = [d for o, k, d in sent if k == "turn" and o == u["id"]]
    start = next(d for d in turns if d["phase"] == "start")
    end = next(d for d in turns if d["phase"] == "end")
    assert start == {**start, "turn_id": tid, "conversation_id": c, "agent_id": a, "audience": "owner", "client_turn_id": "web-1"}
    assert end["turn_id"] == tid and end["status"] == "completed" and end["message_id"]
    # 번호만 싣는다 — 말은 받는 쪽이 다시 읽는다(소식의 크기 제한과 상관없게).
    assert "text" not in start and "content" not in end


async def test_a_new_question_elsewhere_stops_the_old_answer_and_says_why(client: AsyncClient, monkeypatch):
    from memora.db.session import session_scope
    from memora.models import Turn

    u, tok, a, c = await _setup(client)
    # 다른 화면에서 흐르던 답(작업은 이 프로세스에 없다)
    async with session_scope() as db:
        old = Turn(conversation_id=uuid.UUID(c), owner_id=uuid.UUID(u["id"]), agent_id=uuid.UUID(a), audience="owner",
                   status="running", user_text="먼저 한 말", started_at=datetime.now(UTC))
        db.add(old)
        await db.commit()
        old_id = str(old.id)
    sent = _capture(monkeypatch)
    async with client.stream("POST", f"/api/agents/{a}/conversations/{c}/turns", json={"text": "새 말"}, headers=auth(tok)) as r:
        await read_sse(r)
    start = next(d for o, k, d in sent if k == "turn" and d["phase"] == "start")
    assert start["superseded"] == old_id
    msgs = (await client.get(f"/api/agents/{a}/conversations/{c}/messages", headers=auth(tok))).json()["items"]
    assert [m["role"] for m in msgs][-2:] == ["user", "assistant"]


async def test_stop_reaches_the_answer_whoever_started_it(client: AsyncClient, monkeypatch):
    from memora.db.session import session_scope
    from memora.models import Turn

    u, tok, a, c = await _setup(client)
    r = await client.post(f"/api/agents/{a}/conversations/{c}/cancel", headers=auth(tok))
    assert r.status_code == 202 and r.json() == {"cancelled": False, "turn_id": None}

    # 주인을 잃은 답(재시작 등으로 도는 작업이 없다)도 [그만] 이 멈춘다.
    async with session_scope() as db:
        t = Turn(conversation_id=uuid.UUID(c), owner_id=uuid.UUID(u["id"]), agent_id=uuid.UUID(a), audience="owner",
                 status="running", user_text="길게 설명해 줘", started_at=datetime.now(UTC))
        db.add(t)
        await db.commit()
        tid = str(t.id)
    sent = _capture(monkeypatch)
    r = await client.post(f"/api/agents/{a}/conversations/{c}/cancel", headers=auth(tok))
    assert r.json() == {"cancelled": True, "turn_id": tid}
    async with session_scope() as db:
        row = (await db.execute(select(Turn).where(Turn.id == uuid.UUID(tid)))).scalars().first()
        assert row.status == "cancelled"
    end = next(d for o, k, d in sent if k == "turn" and d["phase"] == "end")
    assert end["turn_id"] == tid and end["status"] == "cancelled"
    # 다른 사람은 멈출 수 없다.
    _, other = await signup(client)
    r = await client.post(f"/api/agents/{a}/conversations/{c}/cancel", headers=auth(other))
    assert r.status_code == 404


async def test_a_stopped_answer_says_so_on_every_screen(client: AsyncClient):
    from memora.db.session import session_scope
    from memora.models import Turn
    from memora.services.conversations import add_message, get_owned

    u, tok, a, c = await _setup(client)
    async with session_scope() as db:
        t = Turn(conversation_id=uuid.UUID(c), owner_id=uuid.UUID(u["id"]), agent_id=uuid.UUID(a), audience="owner",
                 status="cancelled", error_code="cancelled", user_text="물음", started_at=datetime.now(UTC))
        db.add(t)
        await db.flush()
        conv = await get_owned(db, uuid.UUID(u["id"]), uuid.UUID(c), uuid.UUID(a))
        await add_message(db, conv, role="user", content="물음", turn_id=t.id)
        await add_message(db, conv, role="assistant", content="답하다 멈", turn_id=t.id)
        await db.commit()
    msgs = (await client.get(f"/api/agents/{a}/conversations/{c}/messages", headers=auth(tok))).json()["items"]
    assert msgs[-1]["turn_status"] == "cancelled"


async def test_conversation_changes_are_announced(client: AsyncClient, monkeypatch):
    u, tok = await signup(client)
    a = (await client.post("/api/agents", json={"name": "제니"}, headers=auth(tok))).json()["id"]
    sent = _capture(monkeypatch)
    c = (await client.post(f"/api/agents/{a}/conversations", json={}, headers=auth(tok))).json()["id"]
    await client.patch(f"/api/agents/{a}/conversations/{c}", json={"title": "여행 계획"}, headers=auth(tok))
    await client.delete(f"/api/agents/{a}/conversations/{c}", headers=auth(tok))
    changes = [d["change"] for o, k, d in sent if k == "conversation" and d["conversation_id"] == c]
    assert changes == ["created", "updated", "deleted"]


def test_a_long_korean_event_stays_whole_json_under_the_byte_limit():
    from memora.core.bus import MAX_BYTES, encode

    long = "가나다라마바사아자차" * 1200  # 12000자, 36000바이트
    body = encode(uuid.uuid4(), "room", {"room_id": "r1", "message": {"id": "m1", "body": long}})
    assert len(body.encode()) <= MAX_BYTES
    msg = json.loads(body)
    assert msg["data"]["room_id"] == "r1" and msg["data"]["truncated"] is True


async def test_a_failed_notify_does_not_undo_what_it_announced(app):
    """NOTIFY 가 실패해도(너무 큰 몸통) 알리려던 일은 저장된다 — 세이브포인트 안에서 실패한다."""
    from sqlalchemy import text

    from memora.core import bus
    from memora.db.session import session_scope

    async with session_scope() as db:
        await db.execute(text("CREATE TEMP TABLE IF NOT EXISTS _bus_probe (v int)"))
        await db.execute(text("INSERT INTO _bus_probe VALUES (1)"))
        # encode 를 건너뛰고 한도를 넘는 몸통을 그대로 보내 본다.
        orig = bus.encode
        bus.encode = lambda *a, **k: "x" * 9000  # type: ignore[assignment]
        try:
            await bus.publish(db, owner_id=uuid.uuid4(), kind="t", data={})
        finally:
            bus.encode = orig  # type: ignore[assignment]
        n = (await db.execute(text("SELECT count(*) FROM _bus_probe"))).scalar()
        assert n == 1


async def _start_slow(client: AsyncClient, tok: str, a: str, c: str):
    """천천히 흐르는 답을 뒤에서 시작하고, 글이 흐르기 시작할 때까지 기다린다. (turn_id, 끝날 때의 사건들)"""
    import asyncio

    from memora.pipeline.events import journals

    async def run():
        async with client.stream("POST", f"/api/agents/{a}/conversations/{c}/turns", json={"text": "[[slow]] 길게 말해 줘"}, headers=auth(tok)) as r:
            return await read_sse(r)

    task = asyncio.create_task(run())
    tid = None
    for _ in range(200):
        await asyncio.sleep(0.05)
        act = (await client.get(f"/api/agents/{a}/conversations/{c}/active-turn", headers=auth(tok))).json()
        if act and (j := journals.get(uuid.UUID(act["turn_id"]))) is not None and j.answer:
            tid = act["turn_id"]
            break
    assert tid, "천천히 흐르는 답이 시작되지 않았다"
    return tid, task


async def test_stop_really_stops_the_model_and_the_next_question_is_answered(client: AsyncClient):
    """[그만] 은 읽기만 멈추는 게 아니다: 모델의 일도 멈추고, 대화 상태를 놓아 다음 물음이 답을 받는다.
    예전에는 모델이 끝까지 돌았고, 그동안 다음 물음이 'already executing a run' 으로 실패했다(운영에서 실제로)."""
    import asyncio

    from memora.providers.llm.fake import FakeSecretaryClient

    u, tok, a, c = await _setup(client)
    tid, task = await _start_slow(client, tok, a, c)
    r = await client.post(f"/api/agents/{a}/conversations/{c}/cancel", headers=auth(tok))
    assert r.json() == {"cancelled": True, "turn_id": tid}
    events = await asyncio.wait_for(task, 10)
    assert events[-1]["type"] == "turn.cancelled" and events[-1]["data"]["reason"] == "cancelled"
    at_stop = FakeSecretaryClient.slow_chunks
    await asyncio.sleep(0.5)
    assert FakeSecretaryClient.slow_chunks - at_stop <= 1, "멈춘 뒤에도 모델이 계속 흘렸다"
    async with client.stream("POST", f"/api/agents/{a}/conversations/{c}/turns", json={"text": "다음 물음"}, headers=auth(tok)) as r2:
        after = await read_sse(r2)
    assert after[-1]["type"] == "turn.complete", after[-1]


async def test_a_new_question_replaces_a_running_answer_and_is_answered(client: AsyncClient):
    """다른 화면(앱의 아바타 ↔ 웹)에서 답을 받는 중에 새로 물으면, 앞 답은 까닭과 함께 멈추고 새 물음은 답을 받는다."""
    import asyncio

    u, tok, a, c = await _setup(client)
    old, task = await _start_slow(client, tok, a, c)
    async with client.stream("POST", f"/api/agents/{a}/conversations/{c}/turns", json={"text": "새 물음"}, headers=auth(tok)) as r:
        new_events = await read_sse(r)
    assert new_events[-1]["type"] == "turn.complete", new_events[-1]
    old_events = await asyncio.wait_for(task, 10)
    assert old_events[-1]["type"] == "turn.cancelled" and old_events[-1]["data"]["reason"] == "superseded"
    msgs = (await client.get(f"/api/agents/{a}/conversations/{c}/messages", headers=auth(tok))).json()["items"]
    by_turn = {m.get("turn_id"): m.get("turn_status") for m in msgs}
    assert by_turn.get(old) == "superseded"
    # 새 물음이 대화 기록에 남아 있다 — 앞 턴의 정리가 새 턴의 말을 지우지 않았다.
    assert [m["content"] for m in msgs if m["role"] == "user"][-1] == "새 물음"
    assert msgs[-1]["role"] == "assistant" and "새 물음" in msgs[-1]["content"]
