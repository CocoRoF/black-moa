"""One row per API request, for the traffic dashboard (plan/40)."""
from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "0022_api_requests"
down_revision = "0021_pool_session_ceiling"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "api_requests",
        sa.Column("id", sa.UUID(as_uuid=True), primary_key=True),
        sa.Column("at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("route", sa.String(200), nullable=False),
        sa.Column("method", sa.String(8), nullable=False),
        sa.Column("lane", sa.String(16), nullable=False),
        sa.Column("status", sa.Integer(), nullable=False),
        sa.Column("ms", sa.Numeric(12, 2), nullable=False),
        sa.Column("lag_ms", sa.Numeric(12, 2), nullable=False, server_default="0"),
        sa.Column("owner_id", sa.UUID(as_uuid=True)),
        sa.Column("agent_id", sa.UUID(as_uuid=True)),
        sa.Column("ip", sa.String(64), nullable=False, server_default=""),
        sa.Column("ua", sa.String(200), nullable=False, server_default=""),
        sa.Column("bytes_out", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("error", sa.Text()),
    )
    op.create_index("ix_api_requests_at", "api_requests", ["at"])
    op.create_index("ix_api_requests_route", "api_requests", ["route"])
    op.create_index("ix_api_requests_lane", "api_requests", ["lane"])
    op.create_index("ix_api_requests_status", "api_requests", ["status"])
    op.create_index("ix_api_requests_owner_id", "api_requests", ["owner_id"])
    # The dashboard's own shape: "the last hour, by lane, newest first".
    op.create_index("ix_api_requests_lane_at", "api_requests", ["lane", "at"])
    op.create_index("ix_api_requests_slow", "api_requests", ["at", "ms"])


def downgrade() -> None:
    op.drop_table("api_requests")
