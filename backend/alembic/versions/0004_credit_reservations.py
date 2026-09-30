"""atomic credit reservations

Revision ID: 0004_credit_reservations
Revises: 0003_turn_invariants
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "0004_credit_reservations"
down_revision = "0003_turn_invariants"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("credit_balances", sa.Column("reserved", sa.Numeric(14, 4), nullable=False, server_default="0"))
    op.add_column("usage_daily", sa.Column("reserved_credits", sa.Numeric(14, 4), nullable=False, server_default="0"))
    op.add_column("usage_daily", sa.Column("reserved_turns", sa.Integer(), nullable=False, server_default="0"))
    op.add_column("usage_daily", sa.Column("reserved_visitor_turns", sa.Integer(), nullable=False, server_default="0"))
    op.create_table(
        "credit_reservations",
        sa.Column("turn_id", sa.UUID(), nullable=False),
        sa.Column("owner_id", sa.UUID(), nullable=False),
        sa.Column("amount", sa.Numeric(14, 4), nullable=False),
        sa.Column("actual_credits", sa.Numeric(14, 4), nullable=False, server_default="0"),
        sa.Column("charged_credits", sa.Numeric(14, 4), nullable=False, server_default="0"),
        sa.Column("day", sa.Date(), nullable=False),
        sa.Column("audience", sa.String(length=16), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False, server_default="held"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("settled_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("turn_id"),
    )
    op.create_index("ix_credit_reservations_owner_id", "credit_reservations", ["owner_id"])
    op.create_index("ix_credit_reservations_status", "credit_reservations", ["status"])


def downgrade() -> None:
    op.drop_index("ix_credit_reservations_status", table_name="credit_reservations")
    op.drop_index("ix_credit_reservations_owner_id", table_name="credit_reservations")
    op.drop_table("credit_reservations")
    op.drop_column("usage_daily", "reserved_visitor_turns")
    op.drop_column("usage_daily", "reserved_turns")
    op.drop_column("usage_daily", "reserved_credits")
    op.drop_column("credit_balances", "reserved")
