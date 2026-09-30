"""The company directory, collected from national and exchange sources (plan/33)."""
from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

from alembic import op

revision = "0026_companies"
down_revision = "0025_process_stats"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "companies",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("name", sa.String(160), nullable=False),
        sa.Column("name_norm", sa.String(160), nullable=False),
        sa.Column("stock_code", sa.String(12)),
        sa.Column("corp_code", sa.String(16)),
        sa.Column("biz_no", sa.String(12)),
        sa.Column("market", sa.String(16), nullable=False, server_default=""),
        sa.Column("industry_text", sa.String(160), nullable=False, server_default=""),
        sa.Column("industry_codes", JSONB, nullable=False, server_default="[]"),
        sa.Column("region_code", sa.String(8), nullable=False, server_default=""),
        sa.Column("region_text", sa.String(64), nullable=False, server_default=""),
        sa.Column("ceo", sa.String(120), nullable=False, server_default=""),
        sa.Column("homepage", sa.Text(), nullable=False, server_default=""),
        sa.Column("product", sa.Text(), nullable=False, server_default=""),
        sa.Column("listed_on", sa.Date()),
        sa.Column("fiscal_month", sa.String(8), nullable=False, server_default=""),
        sa.Column("address", sa.Text(), nullable=False, server_default=""),
        sa.Column("phone", sa.String(40), nullable=False, server_default=""),
        sa.Column("founded_on", sa.Date()),
        sa.Column("employees", sa.Integer()),
        sa.Column("status", sa.String(16), nullable=False, server_default="unknown"),
        sa.Column("sources", JSONB, nullable=False, server_default="{}"),
        sa.Column("locked_fields", JSONB, nullable=False, server_default="[]"),
        sa.Column("hidden", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_companies_name", "companies", ["name"])
    op.create_index("ix_companies_name_norm", "companies", ["name_norm"])
    op.create_index("ix_companies_region_code", "companies", ["region_code"])
    op.create_index("ix_companies_status", "companies", ["status"])
    # The join keys are unique only when known, which is what a partial index says and a
    # plain unique constraint does not: thousands of companies have no ticker.
    for col in ("stock_code", "corp_code", "biz_no"):
        op.create_index(f"uq_companies_{col}", "companies", [col], unique=True,
                        postgresql_where=sa.text(f"{col} IS NOT NULL"))
    # Industry filtering is by code, the same way the community filters job postings.
    op.create_index("ix_companies_industry_codes", "companies", ["industry_codes"], postgresql_using="gin")

    op.create_table(
        "company_source_runs",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("source", sa.String(32), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True)),
        sa.Column("ok", sa.Boolean()),
        sa.Column("fetched", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("updated", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("skipped", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("error", sa.Text()),
    )
    op.create_index("ix_company_source_runs_source", "company_source_runs", ["source", "started_at"])

    # A job posting may point at a real company; the free-text name stays, because a
    # posting for a company we have never heard of still has to be postable.
    op.add_column("community_jobs", sa.Column("company_id", sa.Uuid(), nullable=True))
    op.create_foreign_key("fk_community_jobs_company", "community_jobs", "companies",
                          ["company_id"], ["id"], ondelete="SET NULL")
    op.create_index("ix_community_jobs_company_id", "community_jobs", ["company_id"])


def downgrade() -> None:
    op.drop_index("ix_community_jobs_company_id", table_name="community_jobs")
    op.drop_constraint("fk_community_jobs_company", "community_jobs", type_="foreignkey")
    op.drop_column("community_jobs", "company_id")
    op.drop_table("company_source_runs")
    op.drop_table("companies")
