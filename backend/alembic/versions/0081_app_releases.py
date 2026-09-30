"""다운로드 센터 (plan/64): GitHub 릴리스의 설치본을 옮겨 둔 거울.

Revision ID: 0081_app_releases
Revises: 0080_agent_character
"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql as pg

revision = "0081_app_releases"
down_revision = "0080_agent_character"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "app_releases",
        sa.Column("id", pg.UUID(as_uuid=True), primary_key=True),
        sa.Column("tag", sa.String(64), nullable=False, unique=True),
        sa.Column("version", sa.String(32), nullable=False),
        sa.Column("name", sa.String(160), nullable=False, server_default=""),
        sa.Column("notes", sa.Text, nullable=False, server_default=""),
        sa.Column("published_at", sa.DateTime(timezone=True)),
        sa.Column("prerelease", sa.Boolean, nullable=False, server_default="false"),
        sa.Column("github_id", sa.BigInteger, nullable=False),
        sa.Column("gone", sa.Boolean, nullable=False, server_default="false"),
        sa.Column("synced_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_table(
        "app_release_assets",
        sa.Column("id", pg.UUID(as_uuid=True), primary_key=True),
        sa.Column("release_id", pg.UUID(as_uuid=True), sa.ForeignKey("app_releases.id", ondelete="CASCADE"), nullable=False),
        sa.Column("github_id", sa.BigInteger, nullable=False, unique=True),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("platform", sa.String(16), nullable=False),
        sa.Column("arch", sa.String(16), nullable=False, server_default="x64"),
        sa.Column("kind", sa.String(16), nullable=False),
        sa.Column("size", sa.BigInteger, nullable=False, server_default="0"),
        sa.Column("sha256", sa.String(64)),
        sa.Column("storage_path", sa.Text),
        sa.Column("status", sa.String(16), nullable=False, server_default="pending"),
        sa.Column("error", sa.Text, nullable=False, server_default=""),
        sa.Column("tries", sa.Integer, nullable=False, server_default="0"),
        sa.Column("downloads", sa.Integer, nullable=False, server_default="0"),
        sa.Column("mirrored_at", sa.DateTime(timezone=True)),
    )
    op.create_index("ix_app_release_assets_release_id", "app_release_assets", ["release_id"])


def downgrade() -> None:
    op.drop_index("ix_app_release_assets_release_id", table_name="app_release_assets")
    op.drop_table("app_release_assets")
    op.drop_table("app_releases")
