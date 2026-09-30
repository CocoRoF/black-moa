"""Claude Code account pool

One install had exactly one Claude Code login, so its rate limit was the whole service's
rate limit and its expiry was the whole service's outage. `claude_accounts` holds as many
authenticated identities as the operator wants; the pool leases one per session and takes
a member out of rotation when it is limited, expired or failing.

Existing single-account installs keep working untouched: the pool is empty until an
administrator adds accounts, and an empty pool falls back to the legacy credential file.

Revision ID: 0014_claude_accounts
Revises: 0013_seed_profile_names
"""
from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "0014_claude_accounts"
down_revision = "0013_seed_profile_names"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "claude_accounts",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("label", sa.String(64), nullable=False),
        sa.Column("email", sa.String(255)),
        sa.Column("auth_mode", sa.String(16), server_default="oauth", nullable=False),
        sa.Column("credentials_json", sa.Text()),
        sa.Column("setup_token", sa.Text()),
        sa.Column("api_key", sa.Text()),
        sa.Column("enabled", sa.Boolean(), server_default="true", nullable=False),
        sa.Column("weight", sa.Integer(), server_default="1", nullable=False),
        sa.Column("max_concurrency", sa.Integer(), server_default="4", nullable=False),
        sa.Column("status", sa.String(16), server_default="unknown", nullable=False),
        sa.Column("cooldown_until", sa.DateTime(timezone=True)),
        sa.Column("consecutive_failures", sa.Integer(), server_default="0", nullable=False),
        sa.Column("total_leases", sa.BigInteger(), server_default="0", nullable=False),
        sa.Column("total_failures", sa.BigInteger(), server_default="0", nullable=False),
        sa.Column("last_used_at", sa.DateTime(timezone=True)),
        sa.Column("last_ok_at", sa.DateTime(timezone=True)),
        sa.Column("last_probe_at", sa.DateTime(timezone=True)),
        sa.Column("last_error", sa.Text()),
        sa.Column("subscription", sa.String(32)),
        sa.Column("rate_limit_tier", sa.String(32)),
        sa.Column("access_expires_at", sa.DateTime(timezone=True)),
        sa.Column("session_expires_at", sa.DateTime(timezone=True)),
        sa.Column("notes", sa.Text()),
    )
    # The label is how an operator tells two subscriptions apart in the console and in the
    # audit log, so it has to actually be unique.
    op.create_unique_constraint("uq_claude_accounts_label", "claude_accounts", ["label"])
    op.create_index("ix_claude_accounts_status", "claude_accounts", ["status"])


def downgrade() -> None:
    op.drop_index("ix_claude_accounts_status", table_name="claude_accounts")
    op.drop_constraint("uq_claude_accounts_label", "claude_accounts", type_="unique")
    op.drop_table("claude_accounts")
