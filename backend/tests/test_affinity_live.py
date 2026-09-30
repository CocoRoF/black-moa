"""호감도 엔진을 실제 DB 로 (plan/61): 대화 기록 · 15분 작업 · 먼저 건넨 말, 그리고 재계산.

엔진의 셈은 tests/test_affinity.py 가 시간만 흉내 내어 본다. 여기서는 그 엔진이 실제로 배선되어 있는지 —
대화가 끝나면 오르고, 작업이 끝난 날을 정산하고, 먼저 건넨 말이 답을 기다리는지 — 와, 재계산이 같은
엔진으로 과거 기록을 다시 세는지를 본다.
"""
from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

from httpx import AsyncClient

from memora.db.session import session_scope
from memora.models import Agent, AgentRelationship, Fact, Message, Turn, User
from memora.services import conversations as CV
from memora.services import relationship as R
from tests.conftest import auth, signup

KST = ZoneInfo("Asia/Seoul")


def T(month: int, day: int, h: int = 12, m: int = 0) -> datetime:
    return datetime(2026, month, day, h, m, tzinfo=KST)


async def _pair(client: AsyncClient) -> tuple[uuid.UUID, uuid.UUID]:
    user, tok = await signup(client)
    a = (await client.post("/api/agents", json={"name": "제니"}, headers=auth(tok))).json()
    return uuid.UUID(user["id"]), uuid.UUID(a["id"])


async def test_talk_after_the_nightly_job_counts(client: AsyncClient):
    uid, aid = await _pair(client)
    async with session_scope() as db:
        owner, agent = await db.get(User, uid), await db.get(Agent, aid)
        rel, _ = await R.record_turn(db, owner=owner, agent=agent, at=T(10, 1, 10))
        assert rel.affinity == 8                                # 처음 만난 사이는 0 에서
        await R.settle(db, owner=owner, agent=agent, rel=rel, now=T(10, 2, 0, 5))   # 자정 직후 작업
        await R.record_turn(db, owner=owner, agent=agent, at=T(10, 2, 9, 15))
        assert rel.affinity == 16, "자정에 정산했어도 낮의 대화가 오른다"
        await db.commit()


async def test_a_word_sent_first_waits_for_an_answer(client: AsyncClient):
    uid, aid = await _pair(client)
    async with session_scope() as db:
        owner, agent = await db.get(User, uid), await db.get(Agent, aid)
        rel, _ = await R.record_turn(db, owner=owner, agent=agent)
        await R.deliver_proactive(db, rel, agent, owner, "checkin", "잘 지내요?", rule="daily")
        assert rel.affinity_state["awaiting"]["steps"] == 0
        now = datetime.now(UTC)
        assert await R.settle(db, owner=owner, agent=agent, rel=rel, now=now + timedelta(hours=23)) == 0
        await R.settle(db, owner=owner, agent=agent, rel=rel, now=now + timedelta(hours=25))
        assert rel.affinity_log[-1]["why"] == "ignored" and rel.affinity_log[-1]["d"] < 0
        # 답하면 줄기가 끝난다.
        await R.record_turn(db, owner=owner, agent=agent, at=now + timedelta(hours=26))
        assert "awaiting" not in rel.affinity_state
        await db.commit()


async def _history(uid: uuid.UUID, aid: uuid.UUID, *, turns: list[datetime], proactive: list[datetime],
                   facts: list[datetime], started: datetime) -> None:
    async with session_scope() as db:
        conv = await CV.create(db, owner_id=uid, agent_id=aid, audience="owner")
        for t in turns:
            db.add(Turn(conversation_id=conv.id, owner_id=uid, agent_id=aid, audience="owner", status="completed",
                        started_at=t, ended_at=t + timedelta(seconds=5)))
        for p in proactive:
            db.add(Message(conversation_id=conv.id, role="assistant", content="먼저 건넨 말", created_at=p,
                           cards=[{"card_type": "proactive", "payload": {"kind": "checkin"}}]))
        for i, f in enumerate(facts):
            db.add(Fact(owner_id=uid, agent_id=aid, subject="주인", predicate=f"좋아함{i}", object="커피", status="active",
                        visibility="private", created_at=f))
        db.add(AgentRelationship(user_id=uid, agent_id=aid, started_at=started, affinity=3.0, turns=len(turns)))
        await db.commit()


async def test_recompute_replays_the_real_history_with_the_same_engine(client: AsyncClient):
    uid, aid = await _pair(client)
    # 09-22 에 처음 만났다(호감도가 생긴 뒤라 0 에서): 그날 12번(활발한 날), 09-23 한 번 + 기억 둘,
    # 09-23 19:00 비서가 먼저 건넸는데 하루 넘게 답이 없다가 09-25 10:00 에 답했다.
    turns = [T(9, 22, 10, i) for i in range(12)] + [T(9, 23, 11), T(9, 25, 10)]
    await _history(uid, aid, turns=turns, proactive=[T(9, 23, 19)], facts=[T(9, 23, 12), T(9, 23, 12, 1)],
                   started=T(9, 22, 10))
    async with session_scope() as db:
        rel = await R.get(db, uid, aid)
        r = await R.recompute(db, rel, now=T(9, 27, 12))
        assert r["seed"] == 0 and r["before"] == 3.0
        assert [e["why"] for e in r["log"]] == ["talk", "lively", "talk", "memory", "memory", "ignored", "talk"]
        # 8+4 · +8 · +2+2 · −15 · +8, 09-26 은 말 없는 첫날이라 그대로
        assert r["after"] == 17
        await R.apply_recompute(db, rel, r)
        await db.commit()
    async with session_scope() as db:
        rel = await R.get(db, uid, aid)
        assert rel.affinity == 17 and rel.affinity_log[-1]["why"] == "recomputed" and "awaiting" not in rel.affinity_state
        assert rel.affinity_facts == 2 and str(rel.affinity_day) == "2026-09-26"


async def test_recompute_starts_old_pairs_from_what_they_had_earned(client: AsyncClient):
    uid, aid = await _pair(client)
    # 호감도가 생기기 전(09-21 전)에 사흘 열두 번 — [익숙] 까지 쌓았다 → 49 에서 시작.
    turns = [T(9, d, 10, i) for d in (15, 16, 17) for i in range(4)]
    await _history(uid, aid, turns=turns, proactive=[], facts=[], started=T(9, 15, 10))
    async with session_scope() as db:
        rel = await R.get(db, uid, aid)
        r = await R.recompute(db, rel, now=T(9, 22, 12))
        # 09-21 은 17일 뒤 말 없는 나흘째 — 호감도가 생기기 전의 침묵도 이어서 센다.
        assert r["seed_stage"] == "familiar" and r["seed"] == 49 and r["after"] == round(49 - R.decay_for(4), 2)
