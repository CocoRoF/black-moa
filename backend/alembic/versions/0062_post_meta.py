"""글에 대해 우리가 알아낸 것 (plan/45 §2).

`meta.seen` 은 비서가 사진에서 본 것을 적어 둔 한 줄이다. 사진만 올린 글도 그 날의
기록인데, 비서에게는 적힌 말이 없으면 빈 종이였다.
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0062_post_meta"
down_revision = "0061_affinity"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("blog_posts", sa.Column("meta", postgresql.JSONB(), nullable=False, server_default="{}"))


def downgrade() -> None:
    op.drop_column("blog_posts", "meta")
