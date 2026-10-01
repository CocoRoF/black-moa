"""스케줄의 일정 (plan/56). black-moa 가 캘린더이고 Google 은 붙이는 것이다."""
from __future__ import annotations

import uuid
from datetime import date, datetime

from sqlalchemy import Boolean, Date, DateTime, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from blackmoa.db.base import Base, IdMixin, TimestampMixin
from blackmoa.models._types import fk, owner_col


class ScheduleEvent(Base, IdMixin, TimestampMixin):
    __tablename__ = "schedule_events"
    __table_args__ = (Index("ix_schedule_events_owner_time", "owner_id", "start_at"),)
    owner_id: Mapped[uuid.UUID] = owner_col()
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    start_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    end_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    all_day: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    location: Mapped[str] = mapped_column(Text, default="", server_default="")
    note: Mapped[str] = mapped_column(Text, default="", server_default="")
    #: 빈 시간 계산에서 이 시간을 막는가. 종일 일정(생일·기념일)은 기본으로 막지 않는다.
    busy: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true")
    #: owner — 직접 · secretary — 주인이 비서에게 시켜서 · meeting — 미팅 요청 수락
    source: Mapped[str] = mapped_column(String(16), default="owner", server_default="owner")
    agent_id: Mapped[uuid.UUID | None] = fk("agents", nullable=True, ondelete="SET NULL")
    inbox_item_id: Mapped[uuid.UUID | None] = fk("inbox_items", nullable=True, ondelete="SET NULL")
    #: Google 에도 넣었으면 그 id. 동기화해 온 같은 일정과 겹쳐 보이지 않게 한다.
    google_event_id: Mapped[str | None] = mapped_column(String(256))


class SpecialDay(Base, IdMixin):
    """공식 출처(한국천문연구원 특일 정보)에서 받아 온 특별한 날 하나 (plan/60).

    내장 계산은 저장하지 않는다 — 코드와 라이브러리 판이 곧 자료다. 여기에는 받아 온 것만 있고,
    받아 온 해·종류는 내장 계산 대신 쓴다.
    """

    __tablename__ = "special_days"
    __table_args__ = (UniqueConstraint("country", "day", "kind", "name"), Index("ix_special_days_year", "country", "year"))
    country: Mapped[str] = mapped_column(String(2), nullable=False, default="KR")
    year: Mapped[int] = mapped_column(Integer, nullable=False)
    day: Mapped[date] = mapped_column(Date, nullable=False)
    #: holiday — 쉬는 날 · festival — 명절·잡절 · solar_term — 24절기 · anniversary — 기념일
    kind: Mapped[str] = mapped_column(String(16), nullable=False)
    name: Mapped[str] = mapped_column(String(80), nullable=False)
    off: Mapped[bool] = mapped_column(Boolean, default=False)
    source: Mapped[str] = mapped_column(String(16), default="kasi")
    fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
