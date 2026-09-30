"""Places, reviews and saves for 내 주변 맛집 (plan/34)."""
from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

from alembic import op

revision = "0027_places"
down_revision = "0026_companies"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "places",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("provider", sa.String(16), nullable=False),
        sa.Column("provider_place_id", sa.String(64), nullable=False),
        sa.Column("name", sa.String(160), nullable=False),
        sa.Column("category_text", sa.String(160), nullable=False, server_default=""),
        sa.Column("category_group", sa.String(8), nullable=False, server_default=""),
        sa.Column("address", sa.Text(), nullable=False, server_default=""),
        sa.Column("road_address", sa.Text(), nullable=False, server_default=""),
        sa.Column("phone", sa.String(40), nullable=False, server_default=""),
        sa.Column("place_url", sa.Text(), nullable=False, server_default=""),
        sa.Column("lat", sa.Float(), nullable=False),
        sa.Column("lng", sa.Float(), nullable=False),
        sa.Column("review_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("rating_sum", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("save_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("post_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("provider", "provider_place_id", name="uq_places_provider_id"),
    )
    # "places near here" over our own rows — bounding-box queries on the two columns.
    op.create_index("ix_places_lat_lng", "places", ["lat", "lng"])

    op.create_table(
        "place_reviews",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("place_id", sa.Uuid(), sa.ForeignKey("places.id", ondelete="CASCADE"), nullable=False),
        sa.Column("user_id", sa.Uuid(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("rating", sa.Integer(), nullable=False),
        sa.Column("body", sa.Text(), nullable=False, server_default=""),
        sa.Column("images", JSONB, nullable=False, server_default="[]"),
        sa.Column("visited_on", sa.Date()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("place_id", "user_id", name="uq_place_reviews_place_user"),
        sa.CheckConstraint("rating BETWEEN 1 AND 5", name="ck_place_reviews_rating"),
    )
    op.create_index("ix_place_reviews_place", "place_reviews", ["place_id", "created_at"])
    op.create_index("ix_place_reviews_user", "place_reviews", ["user_id"])

    op.create_table(
        "place_saves",
        sa.Column("place_id", sa.Uuid(), sa.ForeignKey("places.id", ondelete="CASCADE"), nullable=False),
        sa.Column("user_id", sa.Uuid(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.PrimaryKeyConstraint("place_id", "user_id"),
    )
    op.create_index("ix_place_saves_user", "place_saves", ["user_id", "created_at"])

    op.add_column("community_posts", sa.Column("place_id", sa.Uuid(), nullable=True))
    op.create_foreign_key("fk_community_posts_place", "community_posts", "places",
                          ["place_id"], ["id"], ondelete="SET NULL")
    op.create_index("ix_community_posts_place", "community_posts", ["place_id"])


def downgrade() -> None:
    op.drop_index("ix_community_posts_place", table_name="community_posts")
    op.drop_constraint("fk_community_posts_place", "community_posts", type_="foreignkey")
    op.drop_column("community_posts", "place_id")
    op.drop_table("place_saves")
    op.drop_table("place_reviews")
    op.drop_table("places")
