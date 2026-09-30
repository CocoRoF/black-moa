"""One row per process, holding what only that process can see (plan/32 §6).

Thread pools, database lanes, LLM capacity and in-flight requests all live in memory, so
an admin screen only ever saw the numbers belonging to whichever process answered the
request. The worker's side was therefore invisible: its pools and its share of the
connection pool appeared on no screen at all, which is a poor position from which to tune
an allocation. Each process writes its own snapshot here and the console adds them up.

Deliberately not the aggregate metrics (`api_requests`, `jobs`) — those are already in the
database and already complete. This is only for what is otherwise unobservable.
"""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, String
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from memora.db.base import Base


class ProcessStat(Base):
    __tablename__ = "process_stats"

    #: role:id — "api:memora-backend", "worker:worker-1". Keyed together so two processes
    #: of the same role never overwrite each other's row.
    key: Mapped[str] = mapped_column(String(160), primary_key=True)
    role: Mapped[str] = mapped_column(String(16), nullable=False)
    at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    snapshot: Mapped[dict] = mapped_column(JSONB, default=dict, server_default="{}")
