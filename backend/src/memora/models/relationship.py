"""The relationship between a person and a secretary, and the secretary's personality history (plan/37).

One relationship row per (user, agent). Today the user is always the owner; from plan/36 stage
B a person who adopts a secretary from the store gets their own row against the same agent,
which is why the column is ``user_id`` and not ``owner_id``.
"""
from __future__ import annotations

import uuid
from datetime import date, datetime

from sqlalchemy import Date, DateTime, Float, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from memora.db.base import Base, IdMixin, TimestampMixin
from memora.models._types import JSONB, fk


class AgentRelationship(Base, IdMixin, TimestampMixin):
    __tablename__ = "agent_relationships"
    __table_args__ = (UniqueConstraint("user_id", "agent_id", name="uq_agent_relationships_user_agent"),)
    user_id: Mapped[uuid.UUID] = fk("users")
    agent_id: Mapped[uuid.UUID] = fk("agents")
    stage: Mapped[str] = mapped_column(String(16), default="new", server_default="new")
    score: Mapped[float] = mapped_column(Float, default=0.0, server_default="0")
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_turn_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    turns: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    active_days: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    last_active_day: Mapped[date | None] = mapped_column(Date)
    streak_days: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    facts_remembered: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    stage_changed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    milestones: Mapped[list] = mapped_column(JSONB, default=list, server_default="[]")
    mood: Mapped[dict] = mapped_column(JSONB, default=dict, server_default="{}")
    # Messages the secretary sent first, counted per local day.
    proactive_day: Mapped[date | None] = mapped_column(Date)
    proactive_count: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    last_proactive_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_proactive_kind: Mapped[str] = mapped_column(String(24), default="", server_default="")
    # e.g. {"followup_for": "<last_turn_at iso>"} — the pause already followed up on.
    proactive_state: Mapped[dict] = mapped_column(JSONB, default=dict, server_default="{}")
    # ── 호감도: 지금 우리 사이의 온도 (plan/45 §4) ───────────────────────────
    # 위의 셈들은 쌓인 것이라 내려가지 않는다. 이것은 지금이라 방치하면 식는다.
    affinity: Mapped[float] = mapped_column(Float, default=0.0, server_default="0")
    #: 정산을 마친 **끝난** 날(주인의 현지 날짜). 조용한 날의 감소는 그날이 지나간 뒤에 붙는다 (plan/61).
    affinity_day: Mapped[date | None] = mapped_column(Date)
    #: 가산을 마친 기억의 수. 늘어난 만큼만 쳐 준다.
    affinity_facts: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    #: 오늘의 셈과 기다리는 것 (plan/61): {"day", "turns", "talked", "lively", "facts"(오늘 받은 기억 가산),
    #: "talk_days"(최근 대화한 날들), "awaiting": {"since", "steps"}(답을 기다리는 먼저 건넨 말)}.
    affinity_state: Mapped[dict] = mapped_column(JSONB, default=dict, server_default="{}")
    #: 증감 하나하나와 그 까닭(최근 120개). 화면에는 나오지 않는다 — 식는 것은 알림이 아니다.
    affinity_log: Mapped[list] = mapped_column(JSONB, default=list, server_default="[]")
    #: 이 사람이 발행한 글 수(캐시). 마지막 단계는 이야기만으로는 닿지 않는다.
    posts_written: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    #: 비서가 이미 들춰 본 글. 같은 것만 되풀이해 보지 않게 (plan/45 §3).
    glanced: Mapped[list] = mapped_column(JSONB, default=list, server_default="[]")


class AgentPersonaVersion(Base, IdMixin):
    """A snapshot of who the secretary is, taken whenever that changes."""
    __tablename__ = "agent_persona_versions"
    agent_id: Mapped[uuid.UUID] = fk("agents")
    owner_id: Mapped[uuid.UUID] = fk("users")
    label: Mapped[str] = mapped_column(String(80), default="", server_default="")
    snapshot: Mapped[dict] = mapped_column(JSONB, default=dict, server_default="{}")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
