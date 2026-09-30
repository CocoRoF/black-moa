"""Per-user sending address

A secretary's mail went out from one shared mailbox, so every recipient saw the same
sender whoever it was written for. Each account can now claim a local part and send from
<handle>@<domain>.

Revision ID: 0012_mail_handle
Revises: 0011_job_taxonomy
"""
from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "0012_mail_handle"
down_revision = "0011_job_taxonomy"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("users", sa.Column("mail_handle", postgresql.CITEXT(), nullable=True))
    # Unique, not merely indexed: this is an address. Case-insensitive because a mailbox is.
    op.create_unique_constraint("uq_users_mail_handle", "users", ["mail_handle"])


def downgrade() -> None:
    op.drop_constraint("uq_users_mail_handle", "users", type_="unique")
    op.drop_column("users", "mail_handle")
