"""One row per API request (plan/40)."""
from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DateTime, Integer, Numeric, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from memora.db.base import Base, IdMixin
from memora.models._types import UUID


class ApiRequest(Base, IdMixin):
    """What one request did, kept so an operator can answer "what is the server doing".

    Written after the response is sent, in batches, off the request's own path — measuring
    traffic must never be a reason traffic is slower.
    """

    __tablename__ = "api_requests"
    at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    # The route template ("/api/agents/{agent_id}/turns"), not the concrete path: an id in
    # the key means a million keys and no aggregate worth reading.
    route: Mapped[str] = mapped_column(String(200), nullable=False, index=True)
    method: Mapped[str] = mapped_column(String(8), nullable=False)
    # chat | docs | admin | community | public | other — the classes that must not block
    # each other, so saturation can be read per class.
    lane: Mapped[str] = mapped_column(String(16), nullable=False, index=True)
    status: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    # Two clocks, two questions. ``ms`` is how long the request held a slot — for a stream
    # that is until the client left. ``ttfb_ms`` is how long it took to start answering,
    # which is what "how fast is the API" means; percentiles are read off this one, or a
    # single notification stream left open all afternoon would set them.
    ms: Mapped[float] = mapped_column(Numeric(12, 2), nullable=False)
    ttfb_ms: Mapped[float] = mapped_column(Numeric(12, 2), default=0, server_default="0")
    # Time the loop was stalled while this request ran: the signal that says "this call is
    # why everything else was slow".
    lag_ms: Mapped[float] = mapped_column(Numeric(12, 2), default=0, server_default="0")
    owner_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), index=True)
    agent_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    ip: Mapped[str] = mapped_column(String(64), default="", server_default="")
    ua: Mapped[str] = mapped_column(String(200), default="", server_default="")
    bytes_out: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    error: Mapped[str | None] = mapped_column(Text)
