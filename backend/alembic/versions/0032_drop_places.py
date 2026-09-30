"""The food map is withdrawn (plan/34, plan/35): its tables, the post link to it, the
board, and its settings go."""
from __future__ import annotations

from alembic import op

revision = "0032_drop_places"
down_revision = "0031_place_osm"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE community_posts DROP COLUMN IF EXISTS place_id")
    for t in ("place_reviews", "place_saves", "place_source_runs", "place_areas", "places"):
        op.execute(f"DROP TABLE IF EXISTS {t} CASCADE")
    op.execute("DELETE FROM community_boards WHERE slug = 'food'")
    op.execute("DELETE FROM system_settings WHERE key LIKE 'places.%'")
    op.execute("DELETE FROM jobs WHERE kind IN ('crawl.places', 'places.refresh')")


def downgrade() -> None:
    raise RuntimeError("the food map was withdrawn; there is nothing to restore it to")
