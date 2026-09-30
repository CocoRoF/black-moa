"""비서 하나에 공개 링크 하나 (plan/80).

거둔(revoked) 링크는 기록으로 남고, 살아 있는(active·paused) 링크는 비서마다 하나다.

Revision ID: 0084_one_link_per_secretary
Revises: 0083_files_belong_to_owner
"""
from alembic import op

revision = "0084_one_link_per_secretary"
down_revision = "0083_files_belong_to_owner"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 혹시 둘 이상 살아 있으면 가장 오래된 것만 남기고 멈춘다(지우지 않는다 — 되살릴 수 있게). 운영에는 없었다(2026-09-30).
    op.execute("""
        UPDATE share_links SET status = 'revoked'
         WHERE status <> 'revoked'
           AND id NOT IN (SELECT DISTINCT ON (agent_id) id FROM share_links WHERE status <> 'revoked'
                          ORDER BY agent_id, created_at)
    """)
    op.create_index("uq_share_links_one_live_per_agent", "share_links", ["agent_id"], unique=True,
                    postgresql_where="status <> 'revoked'")


def downgrade() -> None:
    op.drop_index("uq_share_links_one_live_per_agent", table_name="share_links")
