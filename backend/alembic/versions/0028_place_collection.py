"""Batch collection of places: areas, runs, and where each place came from (plan/34 §8)."""
from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

from alembic import op

revision = "0028_place_collection"
down_revision = "0027_places"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("places", sa.Column("last_seen_at", sa.DateTime(timezone=True)))
    op.add_column("places", sa.Column("area_id", sa.Uuid()))
    op.add_column("places", sa.Column("hidden", sa.Boolean(), nullable=False, server_default="false"))
    op.create_index("ix_places_area", "places", ["area_id"])
    op.create_index("ix_places_category_group", "places", ["category_group"])

    op.create_table(
        "place_areas",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("name", sa.String(80), nullable=False),
        sa.Column("lat", sa.Float(), nullable=False),
        sa.Column("lng", sa.Float(), nullable=False),
        sa.Column("radius_m", sa.Integer(), nullable=False, server_default="2000"),
        sa.Column("categories", JSONB, nullable=False, server_default='["food", "cafe"]'),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default="true"),
        sa.Column("cursor", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("cells", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("place_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("last_run_at", sa.DateTime(timezone=True)),
        sa.Column("last_completed_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_table(
        "place_source_runs",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("source", sa.String(32), nullable=False),
        sa.Column("area_id", sa.Uuid()),
        sa.Column("area_name", sa.String(80), nullable=False, server_default=""),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True)),
        sa.Column("ok", sa.Boolean()),
        sa.Column("calls", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("fetched", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("updated", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("error", sa.Text()),
    )
    op.create_index("ix_place_source_runs_source", "place_source_runs", ["source"])
    op.create_index("ix_place_source_runs_started", "place_source_runs", ["started_at"])


def downgrade() -> None:
    op.drop_table("place_source_runs")
    op.drop_table("place_areas")
    op.drop_index("ix_places_category_group", table_name="places")
    op.drop_index("ix_places_area", table_name="places")
    op.drop_column("places", "hidden")
    op.drop_column("places", "area_id")
    op.drop_column("places", "last_seen_at")
