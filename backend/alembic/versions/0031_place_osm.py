"""OpenStreetMap identity on places (plan/35): the keyless source, attributed."""
from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "0031_place_osm"
down_revision = "0030_place_baseline"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("places", sa.Column("osm_id", sa.String(32)))
    op.create_index("uq_places_osm_id", "places", ["osm_id"], unique=True, postgresql_where=sa.text("osm_id IS NOT NULL"))


def downgrade() -> None:
    op.drop_index("uq_places_osm_id", table_name="places")
    op.drop_column("places", "osm_id")
