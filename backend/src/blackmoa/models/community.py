"""Community: boards, posts, comments, reactions.

Author identity is deliberately absent from these rows — it is read from `users`/`profiles`
at display time, so editing a profile updates every past post's job line and no second copy
of a person's identity exists to drift.
"""
from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, Float, Integer, String, Text, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from blackmoa.db.base import Base, IdMixin, TimestampMixin, utcnow
from blackmoa.models._types import JSONB, UUID, Index, fk


class CommunityBoard(Base, IdMixin, TimestampMixin):
    __tablename__ = "community_boards"
    slug: Mapped[str] = mapped_column(String(48), unique=True, nullable=False)
    name: Mapped[str] = mapped_column(String(60), nullable=False)
    description: Mapped[str] = mapped_column(Text, default="", server_default="")
    kind: Mapped[str] = mapped_column(String(16), default="discussion", server_default="discussion")
    icon: Mapped[str] = mapped_column(String(24), default="", server_default="")
    sort_order: Mapped[int] = mapped_column(Integer, default=100, server_default="100")
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true")
    post_count: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    # all | verified (a confirmed email) | job (a profile that says what you do) | admin
    write_policy: Mapped[str] = mapped_column(String(24), default="all", server_default="all")


class CommunityPost(Base, IdMixin, TimestampMixin):
    __tablename__ = "community_posts"
    __table_args__ = (
        # One accidental double-submit is one post.
        UniqueConstraint("author_id", "client_token", name="uq_community_posts_author_token"),
        Index("ix_community_posts_board_created", "board_id", "created_at"),
        Index("ix_community_posts_hot", "hot_score", "created_at"),
    )
    board_id: Mapped[uuid.UUID] = fk("community_boards", ondelete="RESTRICT")
    author_id: Mapped[uuid.UUID] = fk("users")
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    body: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(String(16), default="published", server_default="published", index=True)
    is_pinned: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    comment_count: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    like_count: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    view_count: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    # Written by the worker, read by the feed: ranking must not be a per-request sort.
    hot_score: Mapped[float] = mapped_column(Float, default=0.0, server_default="0")
    client_token: Mapped[str | None] = mapped_column(String(64))
    version: Mapped[int] = mapped_column(Integer, default=1, server_default="1")
    edited_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    meta: Mapped[dict] = mapped_column(JSONB, default=dict, server_default="{}")


class CommunityComment(Base, IdMixin, TimestampMixin):
    __tablename__ = "community_comments"
    __table_args__ = (Index("ix_community_comments_post_created", "post_id", "created_at"),)
    post_id: Mapped[uuid.UUID] = fk("community_posts")
    author_id: Mapped[uuid.UUID] = fk("users")
    parent_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True, index=True)
    body: Mapped[str] = mapped_column(Text, nullable=False)
    # Soft delete keeps a thread readable: a removed comment still anchors its replies.
    status: Mapped[str] = mapped_column(String(16), default="published", server_default="published")
    like_count: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    depth: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    version: Mapped[int] = mapped_column(Integer, default=1, server_default="1")


class CommunityReaction(Base, IdMixin):
    __tablename__ = "community_reactions"
    __table_args__ = (UniqueConstraint("target_type", "target_id", "user_id", "kind",
                                       name="uq_community_reaction"),)
    target_type: Mapped[str] = mapped_column(String(16), nullable=False)
    target_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False, index=True)
    user_id: Mapped[uuid.UUID] = fk("users")
    kind: Mapped[str] = mapped_column(String(16), default="like", server_default="like")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), default=utcnow)


class CommunityPostView(Base, IdMixin):
    """One row per (post, reader, day): the view counter increments only when this inserts,
    so a hot post is not a single row every reader queues behind."""
    __tablename__ = "community_post_views"
    __table_args__ = (UniqueConstraint("post_id", "viewer_key", "day", name="uq_community_post_view"),)
    post_id: Mapped[uuid.UUID] = fk("community_posts")
    viewer_key: Mapped[str] = mapped_column(String(64), nullable=False)
    day: Mapped[str] = mapped_column(String(10), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), default=utcnow)


class CommunityReport(Base, IdMixin, TimestampMixin):
    __tablename__ = "community_reports"
    target_type: Mapped[str] = mapped_column(String(16), nullable=False)
    target_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False, index=True)
    reporter_id: Mapped[uuid.UUID] = fk("users")
    reason: Mapped[str] = mapped_column(String(40), nullable=False)
    detail: Mapped[str] = mapped_column(Text, default="", server_default="")
    status: Mapped[str] = mapped_column(String(16), default="open", server_default="open", index=True)


class CommunityJob(Base, IdMixin, TimestampMixin):
    __tablename__ = "community_jobs"
    title: Mapped[str] = mapped_column(String(160), nullable=False)
    company: Mapped[str] = mapped_column(String(120), nullable=False)
    location: Mapped[str] = mapped_column(String(120), default="", server_default="")
    employment_type: Mapped[str] = mapped_column(String(24), default="fulltime", server_default="fulltime")
    experience_min: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    salary_min: Mapped[int | None] = mapped_column(Integer)
    salary_max: Mapped[int | None] = mapped_column(Integer)
    tags: Mapped[dict] = mapped_column(JSONB, default=list, server_default="[]")
    # Codes from blackmoa.data, not free text: "서울 송파" and "송파구" are one place to a reader
    # and two strings to a query. The display string stays in `location`.
    region_codes: Mapped[list] = mapped_column(JSONB, default=list, server_default="[]")
    job_codes: Mapped[list] = mapped_column(JSONB, default=list, server_default="[]")
    industry_codes: Mapped[list] = mapped_column(JSONB, default=list, server_default="[]")
    remote: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    description: Mapped[str] = mapped_column(Text, default="", server_default="")
    apply_url: Mapped[str] = mapped_column(Text, default="", server_default="")
    #: The real company, when we have it. `company` above stays as written: a posting for
    #: a company that is not in the directory still has to be postable (plan/33 §2).
    company_id: Mapped[uuid.UUID | None] = fk("companies", nullable=True, ondelete="SET NULL")
    # lazy="raise": the employer card is rendered per posting, so a missing eager load
    # should be a loud error at development time rather than a query per row in production.
    company_obj: Mapped[Company | None] = relationship("Company", lazy="raise")  # noqa: F821
    posted_by: Mapped[uuid.UUID | None] = fk("users", nullable=True, ondelete="SET NULL")
    status: Mapped[str] = mapped_column(String(16), default="open", server_default="open", index=True)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
