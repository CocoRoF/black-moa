"""약관 동의 기록 (plan/73): 어느 판의 이용약관·개인정보 처리방침에, 언제 동의했나.

만 14세 이상 확인과 약관 동의를 한 번에 받는다. 비어 있으면(예전 계정, 로그인 화면에서 곧바로 만들어진 연결 계정)
앱에 들어올 때 한 번 받는다.

Revision ID: 0082_terms_consent
Revises: 0081_app_releases
"""
import sqlalchemy as sa
from alembic import op

revision = "0082_terms_consent"
down_revision = "0081_app_releases"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("users", sa.Column("terms_version", sa.String(32)))
    op.add_column("users", sa.Column("terms_agreed_at", sa.DateTime(timezone=True)))


def downgrade() -> None:
    op.drop_column("users", "terms_agreed_at")
    op.drop_column("users", "terms_version")
