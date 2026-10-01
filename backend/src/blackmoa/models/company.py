"""A company, as assembled from national and exchange sources (plan/33).

One row per company, and a record of which source last touched it. Several sources
describe the same company and none of them is complete: the exchange knows the ticker and
the market, the regulator knows the registration number and the address, the tax office
knows whether it is still trading. Keeping the provenance is what makes a disagreement
between them readable instead of mysterious.
"""
from __future__ import annotations

import uuid
from datetime import date, datetime

from sqlalchemy import Boolean, Date, DateTime, Float, Integer, String, Text, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from blackmoa.db.base import Base, IdMixin, TimestampMixin, utcnow
from blackmoa.models._types import fk


class Company(Base, IdMixin, TimestampMixin):
    __tablename__ = "companies"
    __table_args__ = (
        UniqueConstraint("stock_code", name="uq_companies_stock_code"),
        UniqueConstraint("corp_code", name="uq_companies_corp_code"),
        UniqueConstraint("biz_no", name="uq_companies_biz_no"),
    )

    name: Mapped[str] = mapped_column(String(160), nullable=False, index=True)
    #: Matching key: the same company is written "(주)카카오", "주식회사 카카오" and "카카오"
    #: by three different sources, and none of them is wrong.
    name_norm: Mapped[str] = mapped_column(String(160), nullable=False, index=True)

    #: The join keys, each owned by one source. Null until that source has seen the company.
    stock_code: Mapped[str | None] = mapped_column(String(12))    # KRX  ↔ DART
    corp_code: Mapped[str | None] = mapped_column(String(16))     # DART
    biz_no: Mapped[str | None] = mapped_column(String(12))        # 국세청

    market: Mapped[str] = mapped_column(String(16), default="", server_default="")
    industry_text: Mapped[str] = mapped_column(String(160), default="", server_default="")
    #: Mapped onto the taxonomy the community already filters by, so a company and a job
    #: posting can be found the same way. The raw text above is kept because the mapping is
    #: lossy and a human should be able to see what it was derived from.
    industry_codes: Mapped[list] = mapped_column(JSONB, default=list, server_default="[]")
    region_code: Mapped[str] = mapped_column(String(8), default="", server_default="", index=True)
    region_text: Mapped[str] = mapped_column(String(64), default="", server_default="")

    ceo: Mapped[str] = mapped_column(String(120), default="", server_default="")
    homepage: Mapped[str] = mapped_column(Text, default="", server_default="")
    product: Mapped[str] = mapped_column(Text, default="", server_default="")
    listed_on: Mapped[date | None] = mapped_column(Date)
    fiscal_month: Mapped[str] = mapped_column(String(8), default="", server_default="")

    address: Mapped[str] = mapped_column(Text, default="", server_default="")
    phone: Mapped[str] = mapped_column(String(40), default="", server_default="")
    founded_on: Mapped[date | None] = mapped_column(Date)
    employees: Mapped[int | None] = mapped_column(Integer)

    #: active | closed | suspended | unknown — only the tax office can say this.
    status: Mapped[str] = mapped_column(String(16), default="unknown", server_default="unknown", index=True)

    #: {"krx": "2026-09-11T…", "dart": …} — which source last wrote, and when.
    sources: Mapped[dict] = mapped_column(JSONB, default=dict, server_default="{}")
    #: Fields an administrator has corrected by hand. No collector may overwrite these.
    locked_fields: Mapped[list] = mapped_column(JSONB, default=list, server_default="[]")
    hidden: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")

    # ── derived from what people say and do (plan/40) ─────────────────────────────────
    # Kept on the row so the directory can sort by them and the dashboard can be read
    # without touching the reviews. `recompute` in services.companies.reviews is the one
    # writer; the worker's ranking pass refreshes the time-windowed ones.
    review_count: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    rating: Mapped[float] = mapped_column(Float, default=0.0, server_default="0")
    follow_count: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    view_count: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    views_7d: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    open_jobs: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    popularity: Mapped[float] = mapped_column(Float, default=0.0, server_default="0")
    #: axes averages, recommendation rates, salary and interview summaries, by year and by
    #: job family — everything the detail page's statistics panel shows.
    stats: Mapped[dict] = mapped_column(JSONB, default=dict, server_default="{}")
    #: Codes, not words: "pay", "balance", … — the screen translates them.
    tags: Mapped[list] = mapped_column(JSONB, default=list, server_default="[]")


class CompanyReview(Base, IdMixin, TimestampMixin):
    """What one person says about one employer (plan/40).

    One row per (company, author): a second opinion from the same person edits the first
    rather than standing beside it. Identity is never rendered — a review shows a job
    family, an employment status and a year, which is what makes it safe to write.
    """

    __tablename__ = "company_reviews"
    __table_args__ = (UniqueConstraint("company_id", "author_id", name="uq_company_review_author"),)

    company_id: Mapped[uuid.UUID] = fk("companies")
    author_id: Mapped[uuid.UUID] = fk("users")
    #: published | hidden | deleted
    status: Mapped[str] = mapped_column(String(16), default="published", server_default="published")
    #: current | former
    employment: Mapped[str] = mapped_column(String(16), default="current", server_default="current")
    job_code: Mapped[str] = mapped_column(String(32), default="", server_default="")
    #: The year the review speaks about, which is what the year filter sorts by.
    work_year: Mapped[int] = mapped_column(Integer, nullable=False)
    title: Mapped[str] = mapped_column(String(120), default="", server_default="")
    pros: Mapped[str] = mapped_column(Text, default="", server_default="")
    cons: Mapped[str] = mapped_column(Text, default="", server_default="")
    advice: Mapped[str] = mapped_column(Text, default="", server_default="")
    rating: Mapped[float] = mapped_column(Float, nullable=False)
    #: Area scores, derived from `answers` (means of the questions in each area); a review
    #: written before the questions existed carries the stars it was given.
    rating_pay: Mapped[float] = mapped_column(Float, nullable=False)
    rating_balance: Mapped[float] = mapped_column(Float, nullable=False)
    rating_culture: Mapped[float] = mapped_column(Float, nullable=False)
    rating_promotion: Mapped[float] = mapped_column(Float, nullable=False)
    rating_management: Mapped[float] = mapped_column(Float, nullable=False)
    #: {"hours": "h45_52", "overtime": "weekly", "again": "probably", "fit": ["growth"], …}
    #: — the concrete answers (services.companies.questions), the part a reader can use.
    answers: Mapped[dict] = mapped_column(JSONB, default=dict, server_default="{}")
    recommend: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true")
    ceo_approval: Mapped[bool | None] = mapped_column(Boolean)
    #: up | flat | down
    growth: Mapped[str] = mapped_column(String(8), default="flat", server_default="flat")
    #: 연봉, in 만원 a year. Optional — the salary tab is what these add up to.
    salary: Mapped[int | None] = mapped_column(Integer)
    experience_years: Mapped[int | None] = mapped_column(Integer)
    #: {"difficulty": 1..5, "result": "pass|fail|pending", "questions": "…", "process": "…"}
    interview: Mapped[dict] = mapped_column(JSONB, default=dict, server_default="{}")
    #: Codes from the benefits catalogue.
    benefits: Mapped[list] = mapped_column(JSONB, default=list, server_default="[]")
    #: What the text talks about ("salary", "balance", …), derived when saved.
    topics: Mapped[list] = mapped_column(JSONB, default=list, server_default="[]")
    helpful_count: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    version: Mapped[int] = mapped_column(Integer, default=1, server_default="1")
    #: Written by someone who proved a work mailbox at this company (plan/40 §10).
    verified: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")


class CompanyDomain(Base, IdMixin):
    """An email domain a company is known by (plan/40 §10).

    From the exchange's homepage, from an administrator, or proposed by members who
    verified a mailbox there. Several companies may share one domain (a group's
    subsidiaries do); a domain row says "this company is one of them".
    """

    __tablename__ = "company_domains"
    __table_args__ = (UniqueConstraint("domain", "company_id", name="uq_company_domain"),)

    domain: Mapped[str] = mapped_column(String(190), nullable=False, index=True)
    company_id: Mapped[uuid.UUID] = fk("companies")
    #: homepage | admin | claim
    source: Mapped[str] = mapped_column(String(16), default="homepage", server_default="homepage")
    #: confirmed | pending — a claim is pending until an administrator agrees or enough
    #: verified members make the same claim.
    status: Mapped[str] = mapped_column(String(16), default="confirmed", server_default="confirmed")
    claims: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), default=utcnow)


class CompanyVerification(Base, IdMixin, TimestampMixin):
    """One person proving one work mailbox, and the company they said it belongs to."""

    __tablename__ = "company_verifications"

    user_id: Mapped[uuid.UUID] = fk("users")
    company_id: Mapped[uuid.UUID | None] = fk("companies", nullable=True, ondelete="SET NULL")
    domain: Mapped[str] = mapped_column(String(190), nullable=False)
    email_masked: Mapped[str] = mapped_column(String(190), default="", server_default="")
    email_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    code_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    code_expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    code_verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    attempts: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    #: pending | verified | replaced | removed | expired
    status: Mapped[str] = mapped_column(String(16), default="pending", server_default="pending")
    verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class CompanyFollow(Base, IdMixin):
    __tablename__ = "company_follows"
    __table_args__ = (UniqueConstraint("company_id", "user_id", name="uq_company_follow"),)

    company_id: Mapped[uuid.UUID] = fk("companies")
    user_id: Mapped[uuid.UUID] = fk("users")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), default=utcnow)


class CompanyView(Base, IdMixin):
    """A reader, once a day. The unique row is what makes the count mean people."""

    __tablename__ = "company_views"
    __table_args__ = (UniqueConstraint("company_id", "viewer_key", "day", name="uq_company_view"),)

    company_id: Mapped[uuid.UUID] = fk("companies")
    viewer_key: Mapped[str] = mapped_column(String(64), nullable=False)
    day: Mapped[str] = mapped_column(String(10), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), default=utcnow)


class CompanySourceRun(Base, IdMixin):
    """One collection run, so the admin screen can say what happened and when."""

    __tablename__ = "company_source_runs"

    source: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    ok: Mapped[bool | None] = mapped_column(Boolean)
    fetched: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    created: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    updated: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    skipped: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    error: Mapped[str | None] = mapped_column(Text)
