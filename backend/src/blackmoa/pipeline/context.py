"""TurnContext — everything tools and prompt blocks need about the current turn."""
from __future__ import annotations

import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from blackmoa.memory.facade import AgentMemory
from blackmoa.models import Agent, OwnerProfile, Plan, User, Visitor


@dataclass
class TurnContext:
    owner: User
    agent: Agent
    audience: str                    # owner | visitor
    conversation_id: uuid.UUID
    turn_id: uuid.UUID | None
    profile: OwnerProfile
    plan: Plan
    memory: AgentMemory
    visitor: Visitor | None = None
    #: 이 턴에 이 비서가 지금 듣는 사람에게 쓸 수 있는 것 (plan/57, services.outsider.Disclosure).
    #: 턴마다 러너가 채운다. 비어 있으면 주인 대화는 전부, 외부인 대화는 아무것도.
    disclosure: Any = None
    matched_node: dict[str, Any] | None = None
    private_literals: list[str] = field(default_factory=list)
    allowed_disclosures: set[str] = field(default_factory=set)
    stream_redactor: Any = None   # guard.StreamRedactor on visitor turns
    features: set[str] = field(default_factory=set)      # feature:mail etc.
    cards: list[dict[str, Any]] = field(default_factory=list)
    notices: list[dict[str, Any]] = field(default_factory=list)
    used_memory: list[tuple[str, str]] = field(default_factory=list)
    emit: Callable[[str, dict[str, Any]], None] | None = None
    now: datetime | None = None
    locale: str = "ko"
    visitor_known_contact: str = ""   # filled per turn when the visitor matches a contact in the graph
    relay_id: uuid.UUID | None = None   # set when this conversation is one side of a secretary relay (plan/38)
    vision: bool = True                 # can this turn's model see pictures (plan/55 §5-2)
    read_rooms: bool = False            # this turn read a person-to-person room — skip distillation (plan/55 §6-4)

    @property
    def owner_id(self) -> uuid.UUID:
        return self.owner.id

    @property
    def is_owner(self) -> bool:
        return self.audience == "owner"

    def card(self, card_type: str, payload: dict[str, Any]) -> dict[str, Any]:
        c = {"card_type": card_type, "payload": payload}
        self.cards.append(c)
        if self.emit:
            self.emit("card", c)
        return c

    @property
    def tz(self) -> str:
        return self.owner.timezone or "Asia/Seoul"
