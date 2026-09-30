"""One relationship: connecting (plan/43).

인맥 was a request somebody had to accept and 구독 was one-sided, so the same wish had two
shapes and a person had to know which one they wanted. Now there is one act. Doing it is
immediate; both people doing it is what 인맥 means, and that is derived rather than
negotiated.

Every accepted link becomes two connections, one each way. A request still waiting becomes
the one connection the asker already made: they chose, the other person has not yet, and
that is exactly what a one-way connection says. A refused request becomes nothing.

Revision ID: 0050_connections
Revises: 0049_post_mentions
"""
from __future__ import annotations

import uuid

import sqlalchemy as sa

from alembic import op

revision = "0050_connections"
down_revision = "0049_post_mentions"
branch_labels = None
depends_on = None


def upgrade() -> None:
    conn = op.get_bind()
    rows = conn.execute(sa.text(
        "SELECT requester_id, addressee_id, status, created_at, decided_at FROM network_links "
        "WHERE status IN ('accepted', 'pending')")).mappings().all()
    for row in rows:
        pairs = [(row["requester_id"], row["addressee_id"])]
        if row["status"] == "accepted":
            pairs.append((row["addressee_id"], row["requester_id"]))
        at = row["decided_at"] or row["created_at"]
        for follower, target in pairs:
            conn.execute(sa.text("""
                INSERT INTO person_follows (id, follower_id, target_id, created_at)
                VALUES (:id, :f, :t, :at)
                ON CONFLICT (follower_id, target_id) DO NOTHING
            """), {"id": str(uuid.uuid4()), "f": follower, "t": target, "at": at})
    # The graph's own lines are rebuilt from the connections as people use them; the ones
    # left from accepted links already point both ways, which is what mutual means.
    conn.execute(sa.text("UPDATE network_edges SET direction = 'both' WHERE rel = 'friend'"))
    op.drop_table("network_links")


def downgrade() -> None:
    """One way. A connection carries no record of who asked whom, because nobody asked."""
