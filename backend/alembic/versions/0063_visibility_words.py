"""인맥 공개 범위를 정본 어휘로 (plan/48 §2).

`all` / `friends` / `none` 은 `public` / `known` / `private` 과 같은 뜻이다. 같은 셋을
칸마다 다른 말로 부르면, 주인이 "인맥에게만" 이라고 정한 것이 어떤 원천에서는
지켜지고 어떤 원천에서는 조용히 비공개가 된다.

**값만 옮긴다.** 누구의 공개 범위도 넓어지거나 좁아지지 않는다.

Revision ID: 0063_visibility_words
Revises: 0062_post_meta
"""
from alembic import op

revision = "0063_visibility_words"
down_revision = "0062_post_meta"
branch_labels = None
depends_on = None

FORWARD = {"all": "public", "friends": "known", "none": "private"}


def upgrade() -> None:
    for old, new in FORWARD.items():
        op.execute(f"UPDATE users SET network_public = '{new}' WHERE network_public = '{old}'")
    # 새로 만들어지는 계정도 같은 말을 쓴다.
    op.execute("ALTER TABLE users ALTER COLUMN network_public SET DEFAULT 'public'")


def downgrade() -> None:
    for old, new in FORWARD.items():
        op.execute(f"UPDATE users SET network_public = '{old}' WHERE network_public = '{new}'")
    op.execute("ALTER TABLE users ALTER COLUMN network_public SET DEFAULT 'all'")
