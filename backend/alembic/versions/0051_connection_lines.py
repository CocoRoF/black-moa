"""Draw every connection as the line it actually is (plan/43 §2).

0050 aimed its redraw at `rel = 'friend'` and the member relation is `knows`, so nothing
moved: mutual and one-way still looked the same, and a connection made where no friendship
followed had no line at all — it used to be a request, and requests were never drawn.

This redraws from what is true now: both ways, my way, or theirs.

Revision ID: 0051_connection_lines
Revises: 0050_connections
"""
from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "0051_connection_lines"
down_revision = "0050_connections"
branch_labels = None
depends_on = None


def upgrade() -> None:
    conn = op.get_bind()
    # A person I connected to needs a card in my own graph before a line can reach it.
    conn.execute(sa.text("""
        INSERT INTO network_nodes (id, owner_id, kind, name, user_id, visibility, created_at, updated_at)
        SELECT gen_random_uuid(), f.follower_id, 'person', coalesce(u.display_name, '회원'), f.target_id,
               'public', now(), now()
        FROM person_follows f JOIN users u ON u.id = f.target_id
        WHERE NOT EXISTS (SELECT 1 FROM network_nodes n
                          WHERE n.owner_id = f.follower_id AND n.user_id = f.target_id)
    """))
    conn.execute(sa.text("""
        INSERT INTO network_edges (id, owner_id, src_id, dst_id, rel, direction, strength, attrs,
                                   visibility, source, created_at, updated_at)
        SELECT gen_random_uuid(), f.follower_id, me.id, them.id, 'knows', 'outgoing', 0.4,
               '{}'::jsonb, 'public', 'link', now(), now()
        FROM person_follows f
        JOIN network_nodes me ON me.owner_id = f.follower_id AND me.is_self
        JOIN network_nodes them ON them.owner_id = f.follower_id AND them.user_id = f.target_id
        WHERE NOT EXISTS (
            SELECT 1 FROM network_edges e WHERE e.owner_id = f.follower_id AND e.rel = 'knows'
              AND ((e.src_id = me.id AND e.dst_id = them.id) OR (e.src_id = them.id AND e.dst_id = me.id)))
    """))
    # And every member line says which way it points.
    conn.execute(sa.text("""
        UPDATE network_edges e SET direction = CASE
            WHEN EXISTS (SELECT 1 FROM person_follows f
                         WHERE f.follower_id = e.owner_id AND f.target_id = n.user_id)
             AND EXISTS (SELECT 1 FROM person_follows f
                         WHERE f.follower_id = n.user_id AND f.target_id = e.owner_id)
            THEN 'both'
            WHEN EXISTS (SELECT 1 FROM person_follows f
                         WHERE f.follower_id = e.owner_id AND f.target_id = n.user_id)
            THEN 'outgoing' ELSE 'incoming' END
        FROM network_nodes n
        WHERE n.id = e.dst_id AND n.user_id IS NOT NULL AND e.rel = 'knows'
    """))


def downgrade() -> None:
    op.get_bind().execute(sa.text("UPDATE network_edges SET direction = 'undirected' WHERE rel = 'knows'"))
