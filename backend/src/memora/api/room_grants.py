"""비서에게 사람끼리 방을 보여 주는 허락 (plan/55 §6-4).

허락은 비서 대화의 카드에서 누르고, 거두는 것은 그 비서의 [지식] 탭(메신저 대화 줄)과
메신저 방 정보에서 한다. 거두면 그 순간부터 통로가 닫힌다.
"""
from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Literal

from fastapi import APIRouter, Response
from pydantic import BaseModel, Field
from sqlalchemy.orm.attributes import flag_modified

from memora.core.deps import DB, CurrentUser
from memora.core.errors import NotFound, ValidationFailed
from memora.models import Message
from memora.services import agents as AG
from memora.services import room_access as RA

router = APIRouter(prefix="/api", tags=["room-grants"])


class DecideIn(BaseModel):
    message_id: uuid.UUID
    room_id: uuid.UUID | None = None
    choice: Literal["conversation", "always", "deny"]
    reason: str = Field(default="", max_length=300)


@router.post("/agents/{agent_id}/room-access")
async def decide(agent_id: uuid.UUID, body: DecideIn, user: CurrentUser, db: DB):
    """허락 카드의 답. 카드에 답을 적어 두어 다시 열어도 그때 무엇을 골랐는지 보인다."""
    await AG.get_owned(db, user.id, agent_id)
    m = await db.get(Message, body.message_id)
    if m is None or m.owner_id != user.id:
        raise NotFound("message not found", code="message_not_found")
    card = next((c for c in (m.cards or []) if isinstance(c, dict) and c.get("card_type") == "room_access"), None)
    if card is None or (card.get("payload") or {}).get("agent_id") != str(agent_id):
        raise NotFound("card not found", code="card_not_found")
    pay = card.setdefault("payload", {})
    cands = {c.get("room_id") for c in pay.get("candidates") or []}
    grant_id = None
    if body.choice != "deny":
        if body.room_id is None or str(body.room_id) not in cands:
            raise ValidationFailed("pick one of the rooms on the card", code="bad_room")
        conv = pay.get("conversation_id")
        g = await RA.grant(db, user, agent_id=agent_id, room_id=body.room_id, scope=body.choice,
                           conversation_id=uuid.UUID(conv) if conv else m.conversation_id, reason=pay.get("reason") or "")
        grant_id = str(g.id)
    pay["decided"] = {"choice": body.choice, "room_id": str(body.room_id) if body.room_id else None,
                      "grant_id": grant_id, "at": datetime.now(UTC).isoformat()}
    flag_modified(m, "cards")
    await db.commit()
    return {"decided": pay["decided"]}


@router.get("/room-grants")
async def list_grants(user: CurrentUser, db: DB, room_id: uuid.UUID | None = None, agent_id: uuid.UUID | None = None):
    """살아 있는 허락. 비서의 [지식] 탭은 ``agent_id`` 로, 메신저 방은 ``room_id`` 로 본다."""
    items = await RA.listing(db, user)
    if room_id:
        items = [g for g in items if g["room_id"] == str(room_id)]
    if agent_id:
        items = [g for g in items if g["agent"]["id"] == str(agent_id)]
    return {"items": items}


@router.delete("/room-grants/{grant_id}", status_code=204)
async def revoke(grant_id: uuid.UUID, user: CurrentUser, db: DB):
    await RA.revoke(db, user, grant_id)
    await db.commit()
    return Response(status_code=204)

