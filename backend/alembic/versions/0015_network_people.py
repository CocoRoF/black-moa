"""Network identity: nodes that are real people, and friend links between accounts

`network_nodes` was an address book — a card I wrote, pointing at nobody. A node can now
*be* someone: a black-moa account (`user_id`), a visitor who talked to my secretary
(`visitor_id`), or exactly one node per owner that is me (`is_self`). `network_links`
carries friend requests between accounts, which is what makes a connection mutual instead
of one person's private note.

Nothing existing changes shape: every column is nullable or defaulted, and an install with
no links behaves exactly as it did.

Revision ID: 0015_network_people
Revises: 0014_claude_accounts
"""
from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "0015_network_people"
down_revision = "0014_claude_accounts"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("network_nodes", sa.Column("user_id", postgresql.UUID(as_uuid=True)))
    op.add_column("network_nodes", sa.Column("visitor_id", postgresql.UUID(as_uuid=True)))
    op.add_column("network_nodes", sa.Column("is_self", sa.Boolean(), server_default="false", nullable=False))
    op.create_foreign_key("fk_network_nodes_user", "network_nodes", "users", ["user_id"], ["id"], ondelete="SET NULL")
    op.create_foreign_key("fk_network_nodes_visitor", "network_nodes", "visitors", ["visitor_id"], ["id"], ondelete="SET NULL")
    # One node per person per owner, and exactly one "me". Partial, because the vast
    # majority of nodes are plain cards with neither binding.
    op.create_index("uq_network_nodes_user", "network_nodes", ["owner_id", "user_id"], unique=True,
                    postgresql_where=sa.text("user_id IS NOT NULL"))
    op.create_index("uq_network_nodes_visitor", "network_nodes", ["owner_id", "visitor_id"], unique=True,
                    postgresql_where=sa.text("visitor_id IS NOT NULL"))
    op.create_index("uq_network_nodes_self", "network_nodes", ["owner_id"], unique=True,
                    postgresql_where=sa.text("is_self"))

    op.create_table(
        "network_links",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("requester_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("addressee_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("status", sa.String(16), server_default="pending", nullable=False),
        sa.Column("note", sa.String(300)),
        sa.Column("decided_at", sa.DateTime(timezone=True)),
        sa.CheckConstraint("requester_id <> addressee_id", name="ck_network_links_not_self"),
    )
    # The pair is the identity of the request in one direction; the service refuses a
    # second request when one already exists the other way.
    op.create_index("uq_network_links_pair", "network_links", ["requester_id", "addressee_id"], unique=True)
    op.create_index("ix_network_links_addressee", "network_links", ["addressee_id", "status"])
    op.create_index("ix_network_links_requester", "network_links", ["requester_id", "status"])


def downgrade() -> None:
    op.drop_index("ix_network_links_requester", table_name="network_links")
    op.drop_index("ix_network_links_addressee", table_name="network_links")
    op.drop_index("uq_network_links_pair", table_name="network_links")
    op.drop_table("network_links")
    op.drop_index("uq_network_nodes_self", table_name="network_nodes")
    op.drop_index("uq_network_nodes_visitor", table_name="network_nodes")
    op.drop_index("uq_network_nodes_user", table_name="network_nodes")
    op.drop_constraint("fk_network_nodes_visitor", "network_nodes", type_="foreignkey")
    op.drop_constraint("fk_network_nodes_user", "network_nodes", type_="foreignkey")
    op.drop_column("network_nodes", "is_self")
    op.drop_column("network_nodes", "visitor_id")
    op.drop_column("network_nodes", "user_id")
