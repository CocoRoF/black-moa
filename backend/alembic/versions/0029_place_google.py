"""Google Places enrichment on places: rating, count, a handful of reviews (plan/34 §9)."""
from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

from alembic import op

revision = "0029_place_google"
down_revision = "0028_place_collection"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("places", sa.Column("google_place_id", sa.String(160)))
    op.add_column("places", sa.Column("google_rating", sa.Float()))
    op.add_column("places", sa.Column("google_ratings_total", sa.Integer()))
    op.add_column("places", sa.Column("google_reviews", JSONB, nullable=False, server_default="[]"))
    op.add_column("places", sa.Column("google_url", sa.Text(), nullable=False, server_default=""))
    op.add_column("places", sa.Column("price_level", sa.Integer()))
    op.add_column("places", sa.Column("google_fetched_at", sa.DateTime(timezone=True)))
    op.create_index("ix_places_google_fetched", "places", ["google_fetched_at"])


def downgrade() -> None:
    op.drop_index("ix_places_google_fetched", table_name="places")
    for c in ("google_fetched_at", "price_level", "google_url", "google_reviews", "google_ratings_total", "google_rating", "google_place_id"):
        op.drop_column("places", c)
