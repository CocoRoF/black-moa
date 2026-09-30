"""visitors.user_id — a visitor who signed in is a known account, not an anonymous session

Revision ID: 0007_visitor_account
Revises: 0006_credit_reservation_owner_fk
"""
from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "0007_visitor_account"
down_revision = "0006_credit_reservation_owner_fk"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("visitors", sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=True))
    op.create_foreign_key("visitors_user_id_fkey", "visitors", "users", ["user_id"], ["id"], ondelete="SET NULL")
    op.create_index("ix_visitors_user_id", "visitors", ["user_id"])


def downgrade() -> None:
    op.drop_index("ix_visitors_user_id", table_name="visitors")
    op.drop_constraint("visitors_user_id_fkey", "visitors", type_="foreignkey")
    op.drop_column("visitors", "user_id")
