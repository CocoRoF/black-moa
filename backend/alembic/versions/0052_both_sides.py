"""Both people see the same connection (plan/43 §2).

0051 drew each connection in the graph of whoever made it. The other person's graph was
left without it, so [나를 연결한] showed a name in a list and nothing in the picture. A
relationship one side cannot see is not drawn at all.

Revision ID: 0052_both_sides
Revises: 0051_connection_lines
"""
from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "0052_both_sides"
down_revision = "0051_connection_lines"
branch_labels = None
depends_on = None

#: Both halves of every connection, written from each owner's point of view. Idempotent:
#: it only adds what is missing and then restates every direction from what is true.
_NODES = """
    INSERT INTO network_nodes (id, owner_id, kind, name, user_id, visibility, created_at, updated_at)
    SELECT gen_random_uuid(), {owner}, 'person', coalesce(u.display_name, '회원'), {other},
           'public', now(), now()
    FROM person_follows f JOIN users u ON u.id = {other}
    WHERE NOT EXISTS (SELECT 1 FROM network_nodes n WHERE n.owner_id = {owner} AND n.user_id = {other})
"""
_EDGES = """
    INSERT INTO network_edges (id, owner_id, src_id, dst_id, rel, direction, strength, attrs,
                               visibility, source, created_at, updated_at)
    SELECT gen_random_uuid(), {owner}, me.id, them.id, 'knows', 'incoming', 0.4,
           '{{}}'::jsonb, 'public', 'link', now(), now()
    FROM person_follows f
    JOIN network_nodes me ON me.owner_id = {owner} AND me.is_self
    JOIN network_nodes them ON them.owner_id = {owner} AND them.user_id = {other}
    WHERE NOT EXISTS (
        SELECT 1 FROM network_edges e WHERE e.owner_id = {owner} AND e.rel = 'knows'
          AND ((e.src_id = me.id AND e.dst_id = them.id) OR (e.src_id = them.id AND e.dst_id = me.id)))
"""
_DIRECTIONS = """
    UPDATE network_edges e SET direction = CASE
        WHEN EXISTS (SELECT 1 FROM person_follows f WHERE f.follower_id = e.owner_id AND f.target_id = n.user_id)
         AND EXISTS (SELECT 1 FROM person_follows f WHERE f.follower_id = n.user_id AND f.target_id = e.owner_id)
        THEN 'both'
        WHEN EXISTS (SELECT 1 FROM person_follows f WHERE f.follower_id = e.owner_id AND f.target_id = n.user_id)
        THEN 'outgoing' ELSE 'incoming' END
    FROM network_nodes n
    WHERE n.id = e.dst_id AND n.user_id IS NOT NULL AND e.rel = 'knows'
"""


def upgrade() -> None:
    conn = op.get_bind()
    # The person who was connected to, seen from their own side.
    fmt = {"owner": "f.target_id", "other": "f.follower_id"}
    conn.execute(sa.text(_NODES.format(**fmt)))
    conn.execute(sa.text(_EDGES.format(**fmt)))
    conn.execute(sa.text(_DIRECTIONS))


def downgrade() -> None:
    """One way: the lines are correct now and there is nothing to put back."""
