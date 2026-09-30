"""연결 설정을 공급자별 자리로 (plan/59).

``google_oauth.client_id/secret`` → ``oauth.google.client_id/secret``. 값이 있었으면 Google 을 켜고
로그인에 쓰며 모든 기능을 준다 — 지금 동작 그대로. 비밀은 암호화된 값을 그대로 옮긴다.

Revision ID: 0077_oauth_settings
Revises: 0076_outsider
"""
from alembic import op

revision = "0077_oauth_settings"
down_revision = "0076_outsider"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        INSERT INTO system_settings (key, value, is_secret, updated_at)
        SELECT 'oauth.google.' || split_part(key, '.', 2), value, is_secret, now()
          FROM system_settings WHERE key IN ('google_oauth.client_id', 'google_oauth.client_secret')
        ON CONFLICT (key) DO NOTHING
    """)
    op.execute("""
        INSERT INTO system_settings (key, value, is_secret, updated_at)
        SELECT 'oauth.google.enabled', '{"v": true}'::jsonb, false, now()
         WHERE EXISTS (SELECT 1 FROM system_settings WHERE key = 'google_oauth.client_id' AND coalesce(value->>'v', '') <> '')
        ON CONFLICT (key) DO NOTHING
    """)
    op.execute("DELETE FROM system_settings WHERE key IN ('google_oauth.client_id', 'google_oauth.client_secret')")


def downgrade() -> None:
    op.execute("""
        INSERT INTO system_settings (key, value, is_secret, updated_at)
        SELECT 'google_oauth.' || split_part(key, '.', 3), value, is_secret, now()
          FROM system_settings WHERE key IN ('oauth.google.client_id', 'oauth.google.client_secret')
        ON CONFLICT (key) DO NOTHING
    """)
