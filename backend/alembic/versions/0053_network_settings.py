"""Two switches about my own people, in one place (plan/43 §5).

Who may see who I am connected to, and whether my own secretaries may use that at all.
The second one was a per-secretary capability, which meant the same decision had to be
made again for every secretary and was nowhere near the page it is about.

Both default to open: this platform is for people who want to be found.

Revision ID: 0053_network_settings
Revises: 0052_both_sides
"""
from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "0053_network_settings"
down_revision = "0052_both_sides"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("users", sa.Column("network_public", sa.String(16), nullable=False, server_default="all"))
    op.add_column("users", sa.Column("network_to_secretary", sa.Boolean(), nullable=False, server_default="true"))
    # Anybody who turned the capability off on every secretary meant it for themselves.
    op.get_bind().execute(sa.text("""
        UPDATE users u SET network_to_secretary = false
        WHERE EXISTS (SELECT 1 FROM agents a WHERE a.owner_id = u.id)
          AND NOT EXISTS (SELECT 1 FROM agents a WHERE a.owner_id = u.id
                          AND coalesce((a.capabilities->>'network')::boolean, true))
    """))


def downgrade() -> None:
    op.drop_column("users", "network_to_secretary")
    op.drop_column("users", "network_public")
