from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import BigInteger, Boolean, DateTime, Integer, Numeric, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from memora.db.base import Base, IdMixin, TimestampMixin
from memora.models._types import JSONB, UUID


class SystemSetting(Base):
    __tablename__ = "system_settings"
    key: Mapped[str] = mapped_column(String(128), primary_key=True)
    value: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    is_secret: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    updated_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class ClaudeAccount(Base, IdMixin, TimestampMixin):
    """One authenticated Claude Code identity in the load-balanced pool (plan/30).

    The row is the source of truth; the CLI's own config directory
    (``<data_dir>/claude-accounts/<id>/.claude``) is a working copy the CLI refreshes and
    the pool harvests back. Secrets are Fernet-encrypted in place, the same way
    ``system_settings`` stores them, so a database dump is not a set of live sessions.
    """

    __tablename__ = "claude_accounts"
    label: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    email: Mapped[str | None] = mapped_column(String(255))
    auth_mode: Mapped[str] = mapped_column(String(16), default="oauth", server_default="oauth")
    credentials_json: Mapped[str | None] = mapped_column(Text)   # encrypted
    setup_token: Mapped[str | None] = mapped_column(Text)        # encrypted
    api_key: Mapped[str | None] = mapped_column(Text)            # encrypted
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true")
    # Rotation shape. `weight` only matters to the weighted strategy; `max_concurrency` is
    # enforced by every strategy, because it is what keeps one subscription from being
    # driven into its own rate limit while a sibling sits idle.
    weight: Mapped[int] = mapped_column(Integer, default=1, server_default="1")
    # Sessions, not requests: a conversation holds its account for its whole life, so this
    # is "how many conversations may sit on one login", not "how many calls at once". Four
    # was the latter's number and it took a single owner minutes to exhaust (plan/38).
    max_concurrency: Mapped[int] = mapped_column(Integer, default=16, server_default="16")
    # Health, written by the pool from the same verdict the user-facing error came from.
    status: Mapped[str] = mapped_column(String(16), default="unknown", server_default="unknown", index=True)
    cooldown_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    consecutive_failures: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    total_leases: Mapped[int] = mapped_column(BigInteger, default=0, server_default="0")
    total_failures: Mapped[int] = mapped_column(BigInteger, default=0, server_default="0")
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_ok_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_probe_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_error: Mapped[str | None] = mapped_column(Text)
    # Mirrored from the credential file so the console can show a login's real lifetime
    # without parsing a secret on every page load.
    subscription: Mapped[str | None] = mapped_column(String(32))
    rate_limit_tier: Mapped[str | None] = mapped_column(String(32))
    access_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    session_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    notes: Mapped[str | None] = mapped_column(Text)


class ModelCatalog(Base, IdMixin, TimestampMixin):
    __tablename__ = "model_catalog"
    __table_args__ = (UniqueConstraint("provider", "model_id"),)
    provider: Mapped[str] = mapped_column(String(32), nullable=False)
    model_id: Mapped[str] = mapped_column(String(128), nullable=False)
    display_name: Mapped[str] = mapped_column(String(128), nullable=False)
    cli_alias: Mapped[str | None] = mapped_column(String(64))
    context_window: Mapped[int] = mapped_column(Integer, default=200_000, server_default="200000")
    max_output: Mapped[int] = mapped_column(Integer, default=8192, server_default="8192")
    supports_thinking: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    supports_vision: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true")
    credit_per_1k_input: Mapped[float] = mapped_column(Numeric(12, 4), default=0, server_default="0")
    credit_per_1k_output: Mapped[float] = mapped_column(Numeric(12, 4), default=0, server_default="0")
    credit_per_1k_cache_read: Mapped[float] = mapped_column(Numeric(12, 4), default=0, server_default="0")
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true")
    is_default: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    sort_order: Mapped[int] = mapped_column(Integer, default=100, server_default="100")
    notes: Mapped[str | None] = mapped_column(Text)


class Plan(Base, IdMixin, TimestampMixin):
    __tablename__ = "plans"
    code: Mapped[str] = mapped_column(String(32), unique=True, nullable=False)
    name: Mapped[str] = mapped_column(String(64), nullable=False)
    # What the plan *grants* every cycle, not a ceiling on use: the balance is the ceiling,
    # and how fast a secretary may spend it is set on the secretary (plan/34).
    monthly_credits: Mapped[int] = mapped_column(Integer, default=300, server_default="300")
    max_agents: Mapped[int] = mapped_column(Integer, default=1, server_default="1")
    max_share_links: Mapped[int] = mapped_column(Integer, default=2, server_default="2")
    max_storage_mb: Mapped[int] = mapped_column(Integer, default=1024, server_default="1024")
    features: Mapped[dict] = mapped_column(JSONB, default=dict, server_default="{}")
    # Which of the pool this plan may use, as "provider:model_id" keys. Empty = the whole
    # pool, so a plan nobody has configured offers everything the admin turned on.
    models: Mapped[list] = mapped_column(JSONB, default=list, server_default="[]")
    is_default: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")


class Job(Base, IdMixin):
    __tablename__ = "jobs"
    kind: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    # Whose work this is. The queue is served round-robin across owners, so one person
    # importing five hundred documents cannot put themselves in front of everyone else.
    # NULL is the service's own work (schedules, admin), which shares one turn between them.
    owner_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), index=True)
    payload: Mapped[dict] = mapped_column(JSONB, default=dict, server_default="{}")
    status: Mapped[str] = mapped_column(String(16), default="queued", server_default="queued", index=True)
    priority: Mapped[int] = mapped_column(Integer, default=5, server_default="5")
    run_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    attempts: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    max_attempts: Mapped[int] = mapped_column(Integer, default=5, server_default="5")
    last_error: Mapped[str | None] = mapped_column(Text)
    locked_by: Mapped[str | None] = mapped_column(String(128))
    locked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    dedupe_key: Mapped[str | None] = mapped_column(String(160), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    result: Mapped[dict | None] = mapped_column(JSONB)


class WorkerHeartbeat(Base):
    __tablename__ = "worker_heartbeats"
    worker_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    info: Mapped[dict] = mapped_column(JSONB, default=dict, server_default="{}")
