"""Structured region, job and industry codes on job postings

A free-text location cannot be filtered on: "서울 송파", "송파구", and "Seoul" are the same
place to a reader and three different strings to a query. Postings now carry codes from a
fixed taxonomy alongside the display text.

Revision ID: 0011_job_taxonomy
Revises: 0010_community_search_inbox
"""
from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "0011_job_taxonomy"
down_revision = "0010_community_search_inbox"
branch_labels = None
depends_on = None


def upgrade() -> None:
    for col in ("region_codes", "job_codes", "industry_codes"):
        op.add_column("community_jobs",
                      sa.Column(col, postgresql.JSONB(astext_type=sa.Text()),
                                server_default=sa.text("'[]'::jsonb"), nullable=False))
        # Containment is the only operator these are queried with, and a GIN index is what
        # makes `@>` a lookup instead of a scan.
        op.create_index(f"ix_community_jobs_{col}", "community_jobs", [col],
                        postgresql_using="gin")
    op.add_column("community_jobs", sa.Column("remote", sa.Boolean(), server_default=sa.text("false"), nullable=False))


def downgrade() -> None:
    op.drop_column("community_jobs", "remote")
    for col in ("region_codes", "job_codes", "industry_codes"):
        op.drop_index(f"ix_community_jobs_{col}", table_name="community_jobs")
        op.drop_column("community_jobs", col)
