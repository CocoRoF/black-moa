from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DateTime, Index, Integer, String, Text, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from blackmoa.db.base import Base, IdMixin, TimestampMixin
from blackmoa.models._types import ARRAY, CITEXT, JSONB, fk, owner_col


class Agent(Base, IdMixin, TimestampMixin):
    __tablename__ = "agents"
    owner_id: Mapped[uuid.UUID] = owner_col()
    name: Mapped[str] = mapped_column(String(80), nullable=False)
    role_line: Mapped[str] = mapped_column(String(160), default="", server_default="")
    avatar_url: Mapped[str | None] = mapped_column(Text)
    # The band behind the photo on the profile card. A profile is a picture on a background
    # everywhere else a person has seen one.
    cover_url: Mapped[str | None] = mapped_column(Text)
    # 올린 그림 그대로 — 자르지도 흰 바탕을 깔지도 않은 원본(plan/63). PC 앱의 아바타가 이것을 띄운다.
    # 비어 있으면(프리셋이거나 예전에 올린 사진) 앱은 프로필 사진을 쓴다.
    character_url: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(16), default="active", server_default="active")
    provider: Mapped[str] = mapped_column(String(32), nullable=False, default="claude_code")
    model_id: Mapped[str] = mapped_column(String(128), nullable=False, default="claude-sonnet-4-6")
    persona: Mapped[dict] = mapped_column(JSONB, default=dict, server_default="{}")
    custom_instructions: Mapped[str] = mapped_column(Text, default="", server_default="")
    capabilities: Mapped[dict] = mapped_column(JSONB, default=dict, server_default="{}")
    disclosure_policy: Mapped[dict] = mapped_column(JSONB, default=dict, server_default="{}")
    greeting: Mapped[str] = mapped_column(Text, default="", server_default="")
    suggested_questions: Mapped[list[str]] = mapped_column(ARRAY(Text), default=list, server_default="{}")
    language: Mapped[str] = mapped_column(String(8), default="auto", server_default="auto")
    theme: Mapped[dict] = mapped_column(JSONB, default=dict, server_default="{}")
    voice: Mapped[dict] = mapped_column(JSONB, default=dict, server_default="{}")
    visitor_settings: Mapped[dict] = mapped_column(JSONB, default=dict, server_default="{}")
    #: 외부인과의 대화에서 무엇을 쓰는가 (plan/57). 나와의 대화는 늘 전부라 여기 없다.
    #: 키와 기본값은 ``services/outsider`` 가 정본이다.
    outsider: Mapped[dict] = mapped_column(JSONB, default=dict, server_default="{}")
    thinking_enabled: Mapped[bool] = mapped_column(default=False, server_default="false")
    # What this secretary may spend, set by its owner (plan/34). 0 is no limit — the credit
    # balance is the limit that always applies, so these are the owner's own guard rails:
    # a cap per turn keeps one runaway answer from eating the month, and the day/month caps
    # keep one secretary from eating the account.
    turn_cost_cap_credits: Mapped[int] = mapped_column(Integer, default=50, server_default="50")
    daily_credit_cap: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    monthly_credit_cap: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    stats: Mapped[dict] = mapped_column(JSONB, default=dict, server_default="{}")
    archived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class AgentDisclosure(Base, IdMixin):
    """이 비서가 외부인에게 쓰라고 주인이 고른 것 하나 (plan/57).

    무엇을 가리키는지는 네 열 중 하나다. 열마다 외래 키라, 고른 문서·사람을 지우면
    이 행도 함께 사라진다 — 지워진 것을 가리키는 약속이 남지 않는다.
    """
    __tablename__ = "agent_disclosures"
    __table_args__ = (
        Index("uq_agent_disclosures_doc", "agent_id", "document_id", unique=True, postgresql_where="document_id IS NOT NULL"),
        Index("uq_agent_disclosures_faq", "agent_id", "faq_id", unique=True, postgresql_where="faq_id IS NOT NULL"),
        Index("uq_agent_disclosures_file", "agent_id", "file_id", unique=True, postgresql_where="file_id IS NOT NULL"),
        Index("uq_agent_disclosures_node", "agent_id", "node_id", unique=True, postgresql_where="node_id IS NOT NULL"),
    )
    agent_id: Mapped[uuid.UUID] = fk("agents")
    #: knowledge · files · network — [지식] 탭의 줄 이름
    kind: Mapped[str] = mapped_column(String(16), nullable=False)
    document_id: Mapped[uuid.UUID | None] = fk("knowledge_documents", nullable=True)
    faq_id: Mapped[uuid.UUID | None] = fk("knowledge_faqs", nullable=True)
    file_id: Mapped[uuid.UUID | None] = fk("agent_files", nullable=True)
    node_id: Mapped[uuid.UUID | None] = fk("network_nodes", nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class ShareLink(Base, IdMixin, TimestampMixin):
    __tablename__ = "share_links"
    # 비서 하나에 살아 있는 공개 링크 하나 (plan/80). 거둔 링크는 기록으로 남는다.
    __table_args__ = (Index("uq_share_links_one_live_per_agent", "agent_id", unique=True, postgresql_where="status <> 'revoked'"),)
    owner_id: Mapped[uuid.UUID] = owner_col()
    agent_id: Mapped[uuid.UUID] = fk("agents")
    code: Mapped[str] = mapped_column(CITEXT, unique=True, nullable=False)
    label: Mapped[str] = mapped_column(String(80), default="", server_default="")
    status: Mapped[str] = mapped_column(String(16), default="active", server_default="active")
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    max_conversations: Mapped[int | None] = mapped_column(Integer)
    conversation_count: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    turn_count: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    last_visit_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    settings: Mapped[dict] = mapped_column(JSONB, default=dict, server_default="{}")


class AgentMemo(Base, IdMixin, TimestampMixin):
    """What I wrote down about somebody else's secretary (plan/44 §8).

    The graph lets you press a published secretary the same way you press a person, and a
    person has a memo. A secretary is not a row in my graph, so the note about it lives
    here — mine, about theirs.
    """

    __tablename__ = "agent_memos"
    __table_args__ = (UniqueConstraint("owner_id", "agent_id", name="uq_agent_memo"),)

    owner_id: Mapped[uuid.UUID] = owner_col()
    agent_id: Mapped[uuid.UUID] = fk("agents")
    body: Mapped[str] = mapped_column(Text, default="", server_default="")
