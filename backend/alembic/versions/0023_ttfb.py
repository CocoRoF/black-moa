"""Time to first byte, separately from total duration (plan/42).

A streamed response held a slot for as long as the client stayed; the record kept only that
number and called it the response time, so the chat lane reported a p95 of 29ms for turns
that ran fifteen seconds.
"""
from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "0023_ttfb"
down_revision = "0022_api_requests"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("api_requests", sa.Column("ttfb_ms", sa.Numeric(12, 2), nullable=False, server_default="0"))
    # The dashboard's percentiles read this column over a time window.
    op.create_index("ix_api_requests_at_ttfb", "api_requests", ["at", "ttfb_ms"])


def downgrade() -> None:
    op.drop_index("ix_api_requests_at_ttfb", table_name="api_requests")
    op.drop_column("api_requests", "ttfb_ms")
