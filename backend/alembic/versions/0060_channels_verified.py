"""이미 자기 주소로 가고 있던 메일 채널은 확인된 것으로 둔다.

인증되지 않은 채널로는 알림이 나가지 않게 바꾸면서, 이미 쓰고 있던 사람들의 알림이
조용히 멈추는 일이 없어야 한다. 받는 곳이 그 계정의 주소인 채널은 증명할 것이 없다:
그 주소는 처음부터 그 사람 것이다. 다른 주소를 가리키는 채널만 인증을 거친다.
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0060_channels_verified"
down_revision = "0059_rooms_by_pair"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(sa.text("""
        UPDATE notification_channels ch
           SET verified_at = COALESCE(ch.verified_at, now())
          FROM users u
         WHERE u.id = ch.owner_id
           AND ch.kind = 'email'
           AND ch.config_public->>'to' = u.email
    """))


def downgrade() -> None:
    pass
