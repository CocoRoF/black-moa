"""One super administrator: the account that may hand out admin

Every admin could already do everything, including making another admin and deleting one.
That is fine for a single maintainer and wrong for a growing team: the person who runs the
install should be the only one who can widen or narrow that circle.

`is_super` rather than a third role, deliberately. Every `role == "admin"` check in the
codebase — and there are many — keeps meaning exactly what it meant; super is one extra
capability on top, not a new kind of account that those checks would silently mis-handle.

The earliest admin is marked here, because that is the person who set the install up.

Revision ID: 0017_super_admin
Revises: 0016_network_public_default
"""
from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "0017_super_admin"
down_revision = "0016_network_public_default"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("users", sa.Column("is_super", sa.Boolean(), server_default="false", nullable=False))
    # Exactly one, enforced by the database rather than by everyone remembering to check.
    op.create_index("uq_users_is_super", "users", ["is_super"], unique=True, postgresql_where=sa.text("is_super"))
    op.execute(sa.text("""
        UPDATE users SET is_super = true
        WHERE id = (SELECT id FROM users WHERE role = 'admin' ORDER BY created_at LIMIT 1)
    """))


def downgrade() -> None:
    op.drop_index("uq_users_is_super", table_name="users")
    op.drop_column("users", "is_super")
