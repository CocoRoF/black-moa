"""Saying an answer was wrong, and what was actually the case (plan/41 §8).

Until now the product could enforce what must not be said and had nothing to say about
whether what it said was true. The owner is the only one who knows, so the loop starts
with them pointing at a turn. The correction does not sit in a report: it becomes an
answer the secretary gives next time.
"""
from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from memora.core.errors import NotFound, ValidationFailed
from memora.models import Message, Turn, TurnFeedback, User
from memora.services import knowledge as K

VERDICTS = ("wrong", "good")
MAX_NOTE = 2000


async def _turn_texts(db: AsyncSession, turn: Turn) -> tuple[str, str]:
    """What was asked and what was answered, as they were said."""
    rows = (await db.execute(select(Message).where(Message.turn_id == turn.id).order_by(Message.created_at))).scalars().all()
    asked = next((m.content for m in rows if m.role == "user" and m.content), "")
    said = next((m.content for m in reversed(rows) if m.role == "assistant" and m.content), "")
    return asked[:2000], said[:4000]


async def mark(db: AsyncSession, user: User, turn_id: uuid.UUID, *, verdict: str, note: str = "") -> dict[str, Any]:
    """Record the owner's verdict on one of their secretary's answers.

    A wrong answer with a correction teaches: the question and the correction are stored as
    an answer the secretary can find, which is the same path a taught answer takes from the
    inbox. Marking wrong without saying what was right still counts — it is a signal even
    when the owner has no time to fix it.
    """
    if verdict not in VERDICTS:
        raise ValidationFailed("verdict must be wrong or good", code="bad_verdict")
    turn = await db.get(Turn, turn_id)
    if turn is None or turn.owner_id != user.id:
        raise NotFound("turn not found", code="turn_not_found")
    note = (note or "").strip()[:MAX_NOTE]
    asked, said = await _turn_texts(db, turn)

    row = (await db.execute(select(TurnFeedback).where(TurnFeedback.turn_id == turn.id))).scalars().first()
    if row is None:
        row = TurnFeedback(turn_id=turn.id, owner_id=user.id, agent_id=turn.agent_id, verdict=verdict)
        db.add(row)
    row.verdict, row.note, row.question, row.answer = verdict, note, asked, said

    if verdict == "wrong" and note and asked:
        # The correction is the owner's own words, and it is theirs to hand out: it answers
        # the question a visitor already asked.
        # Correcting the same turn twice edits that answer rather than leaving two of them
        # for the secretary to choose between.
        faq = await K.upsert_faq(db, user.id, question=asked, answer=note, faq_id=row.faq_id, source="corrected")
        row.faq_id = faq.id
        # 그 대화를 한 비서는 외부인에게도 고친 답을 쓴다 — [지식] 탭 고른 목록에 저절로 (plan/57).
        if turn.agent_id:
            from memora.services import outsider as OUT
            await OUT.pick(db, turn.agent_id, "knowledge", faq_id=faq.id)
    await db.flush()
    return {"verdict": row.verdict, "note": row.note, "faq_id": str(row.faq_id) if row.faq_id else None,
            "question": row.question}


async def for_turns(db: AsyncSession, owner_id: uuid.UUID, turn_ids: list[uuid.UUID]) -> dict[str, dict[str, Any]]:
    """What the owner already said about these turns, for the screen that shows them."""
    if not turn_ids:
        return {}
    rows = (await db.execute(select(TurnFeedback).where(TurnFeedback.owner_id == owner_id,
                                                        TurnFeedback.turn_id.in_(turn_ids)))).scalars().all()
    return {str(r.turn_id): {"verdict": r.verdict, "note": r.note} for r in rows}
