"""인맥 is public by default

`network_nodes.visibility` defaulted to 'private', which meant a secretary could not
mention any contact to a visitor until the owner went and flipped each one — and nobody
did, so the console shipped a permanent "지금은 모든 인맥이 비공개예요" notice. The default
is the wrong way round: a network exists to be introduced from, and the exception is the
person you want hidden.

Existing rows move too. The value they hold was never a decision — it is the default
nobody chose — and leaving them behind would mean the rule applies only to contacts added
after this deploy. Hiding one again is one click.

Revision ID: 0016_network_public_default
Revises: 0015_network_people
"""
from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "0016_network_public_default"
down_revision = "0015_network_people"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.alter_column("network_nodes", "visibility", server_default="public")
    op.alter_column("network_edges", "visibility", server_default="public")
    # The owner's own node stays private: it is the middle of their graph, not a contact
    # the secretary should introduce.
    op.execute(sa.text("UPDATE network_nodes SET visibility = 'public' WHERE visibility = 'private' AND is_self = false"))
    op.execute(sa.text("UPDATE network_edges SET visibility = 'public' WHERE visibility = 'private'"))


def downgrade() -> None:
    op.alter_column("network_edges", "visibility", server_default="private")
    op.alter_column("network_nodes", "visibility", server_default="private")
