from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from blackmoa.db.base import Base, IdMixin, TimestampMixin
from blackmoa.models._types import CITEXT, JSONB, UUID, fk


class User(Base, IdMixin, TimestampMixin):
    __tablename__ = "users"
    email: Mapped[str] = mapped_column(CITEXT, unique=True, nullable=False)
    email_verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    password_hash: Mapped[str | None] = mapped_column(Text)
    # The real name the account is billed and administered under.
    display_name: Mapped[str] = mapped_column(String(120), nullable=False)
    # What a secretary calls this person. Optional: falls back to display_name.
    nickname: Mapped[str | None] = mapped_column(String(60))
    name_confirmed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    #: 동의한 이용약관·개인정보 처리방침의 판(시행일, plan/73)과 그때. 만 14세 이상 확인을 같이 받는다.
    #: 비어 있거나 지금 판과 다르면 앱에 들어올 때 한 번 받는다.
    terms_version: Mapped[str | None] = mapped_column(String(32))
    terms_agreed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    #: 광장에서 쓰는 이름 (plan/52). **어디에도 내 계정과 함께 나가지 않는다.**
    #:
    #: 계정에 두는 이유는 하나다: 글마다 이름을 적게 두면 같은 사람이 여러 이름으로
    #: 흩어져 대화가 이어지지 않고, 남의 실명을 적어 넣는 길도 열린다(운영에서 실제로
    #: 한 건 있었다). 하나를 두고 자주 못 바꾸게 한다.
    #:
    #: CITEXT 로 유일하다. 두 사람이 같은 이름을 쓰면 익명 게시판에서 서로를 사칭하게 된다.
    community_name: Mapped[str | None] = mapped_column(CITEXT, unique=True)
    #: 마지막으로 바꾼 때. 처음 정하는 것은 바꾼 것이 아니다.
    community_name_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # The local part this person's secretary sends from: <mail_handle>@<sending domain>.
    # Unique because it is an address — two people cannot share a mailbox, and replies to
    # it are routed by it. CITEXT so "Haryeom" and "haryeom" cannot both be taken.
    mail_handle: Mapped[str | None] = mapped_column(CITEXT, unique=True)
    avatar_url: Mapped[str | None] = mapped_column(Text)
    locale: Mapped[str] = mapped_column(String(8), default="ko", server_default="ko")
    timezone: Mapped[str] = mapped_column(String(64), default="Asia/Seoul", server_default="Asia/Seoul")
    role: Mapped[str] = mapped_column(String(16), default="user", server_default="user")
    # The one maintainer. Same powers as any admin, plus the only one who may grant or
    # revoke admin, or remove one. A flag rather than a third role so that every existing
    # `role == "admin"` check keeps meaning what it meant.
    is_super: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    status: Mapped[str] = mapped_column(String(16), default="active", server_default="active")
    # Anyone with the address can always read the page. This is only about whether a
    # search engine may list it, which is a separate thing to agree to.
    page_indexable: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true")
    #: Who may see the people I am connected to: "all", "friends" or "none" (plan/43 §5).
    #: 내 인맥을 누가 볼 수 있나. 정본 어휘(public/known/private)를 쓴다 (plan/48 §2).
    network_public: Mapped[str] = mapped_column(String(16), default="public", server_default="public")
    #: Whether my own secretaries may use my 인맥 at all.
    #: 더는 읽지 않는다 (plan/48 §2). 비서는 내 인맥을 본다. 남에게 갈지는 노드마다의
    #: 공개 범위가 정한다. 칸은 남겨 둔다: 쓰지 않는 칸을 지우는 것은 되돌릴 수 없다.
    network_to_secretary: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true")
    plan_id: Mapped[uuid.UUID | None] = fk("plans", nullable=True, ondelete="SET NULL")
    plan_cycle_anchor: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    onboarding_state: Mapped[dict] = mapped_column(JSONB, default=dict, server_default="{}")
    failed_logins: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    locked_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class AuthIdentity(Base, IdMixin, TimestampMixin):
    __tablename__ = "auth_identities"
    __table_args__ = (UniqueConstraint("provider", "subject"),)
    user_id: Mapped[uuid.UUID] = fk("users")
    provider: Mapped[str] = mapped_column(String(32), nullable=False)
    subject: Mapped[str] = mapped_column(String(255), nullable=False)
    email: Mapped[str | None] = mapped_column(String(255))
    raw_profile: Mapped[dict] = mapped_column(JSONB, default=dict, server_default="{}")


class AuthSession(Base, IdMixin):
    __tablename__ = "auth_sessions"
    user_id: Mapped[uuid.UUID] = fk("users")
    family_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False, index=True)
    refresh_hash: Mapped[str] = mapped_column(String(128), unique=True, nullable=False)
    ua: Mapped[str | None] = mapped_column(Text)
    ip: Mapped[str | None] = mapped_column(String(64))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    replaced_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class PasswordReset(Base, IdMixin):
    __tablename__ = "password_resets"
    user_id: Mapped[uuid.UUID] = fk("users")
    token_hash: Mapped[str] = mapped_column(String(128), unique=True, nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class EmailVerification(Base, IdMixin):
    __tablename__ = "email_verifications"
    user_id: Mapped[uuid.UUID] = fk("users")
    code_hash: Mapped[str] = mapped_column(String(128), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class Invite(Base, IdMixin, TimestampMixin):
    __tablename__ = "invites"
    code: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    created_by: Mapped[uuid.UUID | None] = fk("users", nullable=True, ondelete="SET NULL")
    max_uses: Mapped[int] = mapped_column(Integer, default=1, server_default="1")
    used: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    note: Mapped[str | None] = mapped_column(Text)


class AuditLog(Base, IdMixin):
    __tablename__ = "audit_logs"
    actor_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), index=True)
    actor_kind: Mapped[str] = mapped_column(String(16), nullable=False, default="user")
    action: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    target_type: Mapped[str | None] = mapped_column(String(32))
    target_id: Mapped[str | None] = mapped_column(String(64))
    ip: Mapped[str | None] = mapped_column(String(64))
    ua: Mapped[str | None] = mapped_column(Text)
    meta: Mapped[dict] = mapped_column(JSONB, default=dict, server_default="{}")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    active: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true")
