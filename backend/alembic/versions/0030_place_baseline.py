"""Places become our own rows (plan/35): public identities in, provider content out.

Kakao's Local API results may not be stored in any form and existing copies must be
deleted; Google's content beyond the place ID may not be stored either. The rows that
came from Kakao go here, and the columns that held Google's rating and reviews go with
them. What replaces them are the public registry's facts.
"""
from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

from alembic import op

revision = "0030_place_baseline"
down_revision = "0029_place_google"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Provider rows out (policy), reviews and saves on them cascade.
    op.execute("DELETE FROM places WHERE provider = 'kakao'")
    op.drop_constraint("uq_places_provider_id", "places", type_="unique")
    op.drop_index("ix_places_google_fetched", table_name="places")
    for c in ("provider", "provider_place_id", "place_url", "google_rating", "google_ratings_total",
              "google_reviews", "google_url", "price_level", "google_fetched_at"):
        op.drop_column("places", c)
    op.execute("UPDATE places SET category_group = CASE WHEN category_group = 'CE7' THEN 'cafe' ELSE 'food' END")
    op.alter_column("places", "category_group", server_default="food")

    add = op.add_column
    add("places", sa.Column("sub_category", sa.String(80), nullable=False, server_default=""))
    add("places", sa.Column("mid_category", sa.String(80), nullable=False, server_default=""))
    add("places", sa.Column("floor", sa.String(16), nullable=False, server_default=""))
    add("places", sa.Column("building", sa.String(120), nullable=False, server_default=""))
    add("places", sa.Column("biz_key", sa.String(32)))
    add("places", sa.Column("lic_no", sa.String(64)))
    add("places", sa.Column("tour_content_id", sa.String(32)))
    add("places", sa.Column("google_looked_at", sa.DateTime(timezone=True)))
    add("places", sa.Column("kakao_place_id", sa.String(32)))
    add("places", sa.Column("kakao_place_url", sa.Text(), nullable=False, server_default=""))
    add("places", sa.Column("biz_status", sa.String(16), nullable=False, server_default="open"))
    add("places", sa.Column("opened_on", sa.Date()))
    add("places", sa.Column("closed_on", sa.Date()))
    add("places", sa.Column("area_m2", sa.Float()))
    add("places", sa.Column("hygiene_grade", sa.String(16), nullable=False, server_default=""))
    add("places", sa.Column("hygiene_since", sa.Date()))
    add("places", sa.Column("model_restaurant", sa.Boolean(), nullable=False, server_default="false"))
    add("places", sa.Column("model_since", sa.Date()))
    add("places", sa.Column("model_dish", sa.String(120), nullable=False, server_default=""))
    add("places", sa.Column("safe_restaurant", sa.Boolean(), nullable=False, server_default="false"))
    add("places", sa.Column("good_price", sa.Boolean(), nullable=False, server_default="false"))
    add("places", sa.Column("menus", JSONB, nullable=False, server_default="[]"))
    add("places", sa.Column("photos", JSONB, nullable=False, server_default="[]"))
    add("places", sa.Column("hours", sa.Text(), nullable=False, server_default=""))
    add("places", sa.Column("rest_days", sa.Text(), nullable=False, server_default=""))
    add("places", sa.Column("intro", sa.Text(), nullable=False, server_default=""))
    add("places", sa.Column("homepage", sa.Text(), nullable=False, server_default=""))
    add("places", sa.Column("parking", sa.Text(), nullable=False, server_default=""))
    add("places", sa.Column("reservation", sa.Text(), nullable=False, server_default=""))
    add("places", sa.Column("packing", sa.Text(), nullable=False, server_default=""))
    add("places", sa.Column("tags", JSONB, nullable=False, server_default="[]"))
    add("places", sa.Column("sources", JSONB, nullable=False, server_default="{}"))
    op.create_index("uq_places_biz_key", "places", ["biz_key"], unique=True, postgresql_where=sa.text("biz_key IS NOT NULL"))
    op.create_index("uq_places_lic_no", "places", ["lic_no"], unique=True, postgresql_where=sa.text("lic_no IS NOT NULL"))
    op.create_index("ix_places_tour", "places", ["tour_content_id"])
    op.create_index("ix_places_sub_category", "places", ["sub_category"])
    op.create_index("ix_places_status", "places", ["biz_status"])
    op.create_index("ix_places_name_lower", "places", [sa.text("lower(name)")])


def downgrade() -> None:
    raise RuntimeError("plan/35 is not reversible: the provider rows it deleted may not be recreated")
