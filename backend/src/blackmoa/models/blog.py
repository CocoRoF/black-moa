"""A person's own writing, and who reads it (plan/41 §4, §5)."""
from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DateTime, Index, Integer, String, Text, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from blackmoa.db.base import Base, IdMixin, TimestampMixin, utcnow
from blackmoa.models._types import fk, owner_col


class BlogPost(Base, IdMixin, TimestampMixin):
    """One post on the author's own page.

    Published, it is two things at once: a page at `/@handle/{slug}` and a document the
    author's secretary can answer from. Writing once has to be enough.
    """

    __tablename__ = "blog_posts"
    __table_args__ = (UniqueConstraint("owner_id", "slug", name="uq_blog_owner_slug"),)

    owner_id: Mapped[uuid.UUID] = owner_col()
    slug: Mapped[str] = mapped_column(String(190), nullable=False)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    body: Mapped[str] = mapped_column(Text, default="", server_default="")
    #: public | friends | private
    visibility: Mapped[str] = mapped_column(String(16), default="public", server_default="public")
    #: draft | published
    status: Mapped[str] = mapped_column(String(16), default="draft", server_default="draft")
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    knowledge_document_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    view_count: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    #: note — typed into the box at the top of 소식, no title of its own.
    #: article — written in the blog editor, with a title (plan/42 §4).
    kind: Mapped[str] = mapped_column(String(16), default="article", server_default="article")
    like_count: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    comment_count: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    #: Upload ids, in the order the author arranged them (plan/42 §3).
    images: Mapped[list] = mapped_column(JSONB, default=list, server_default="[]")
    #: Handles written into the body that belonged to a real account when it was saved.
    mentions: Mapped[list] = mapped_column(JSONB, default=list, server_default="[]")
    #: 글 자체가 아닌, 글에 대해 우리가 알아낸 것. `seen` 은 비서가 사진에서 본 것을 적어
    #: 둔 한 줄이다 (plan/45 §2). 사진만 올린 글도 그 날의 기록이라, 눈이 없다고 없는
    #: 일이 되면 소식의 절반이 비서에게는 빈 종이다.
    meta: Mapped[dict] = mapped_column(JSONB, default=dict, server_default="{}")


class PostReaction(Base, IdMixin):
    """One person liking one post. The house keeps its own table (plan/41 §1)."""

    __tablename__ = "post_reactions"
    __table_args__ = (UniqueConstraint("post_id", "user_id", name="uq_post_reaction"),)

    post_id: Mapped[uuid.UUID] = fk("blog_posts")
    user_id: Mapped[uuid.UUID] = fk("users")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), default=utcnow)


class PostComment(Base, IdMixin, TimestampMixin):
    """A reply under a post, or under one of its replies (plan/42 §5).

    Two layers and no more. Answering a reply joins the thread it is already in instead of
    starting a third column: a conversation stays a conversation and never becomes a board.
    """

    __tablename__ = "post_comments"
    __table_args__ = (Index("ix_post_comments_post_created", "post_id", "created_at"),)

    post_id: Mapped[uuid.UUID] = fk("blog_posts")
    #: Who may delete it. A secretary is not an account, so its owner stays here.
    author_id: Mapped[uuid.UUID] = fk("users")
    #: Set when a secretary wrote it: the byline is then the secretary, not its owner.
    agent_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    #: The comment this answers. Always a root comment: a reply never parents another.
    parent_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    body: Mapped[str] = mapped_column(Text, nullable=False)


class PersonFollow(Base, IdMixin):
    """One person connecting to another (plan/43).

    This is the whole relationship model. It needs no approval and claims nothing about
    the other person. Both rows existing is what 인맥 means — derived, never negotiated.
    """

    __tablename__ = "person_follows"
    __table_args__ = (UniqueConstraint("follower_id", "target_id", name="uq_person_follow"),)

    follower_id: Mapped[uuid.UUID] = owner_col()
    target_id: Mapped[uuid.UUID] = fk("users")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), default=utcnow)
