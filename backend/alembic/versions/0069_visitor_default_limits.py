"""공개 비서에 울타리를 세워 둔다 (plan/53).

공개 링크는 받는 쪽이 내는 구조다. 열어 둔 사람의 크레딧으로 모르는 사람이 말한다.
그런데 기본값이 "상한 없음" 이었다 — `turns_per_day = 0`. 제동은 방문자당 분당
8턴뿐이었고, 새 대화를 열면 그 제동도 새로 시작한다. 링크 하나가 퍼지면 한 달치가
몇십 분이다.

이미 만들어진 비서에게도 같은 울타리를 세운다. **기본값이던 값만 바꾼다**: 주인이
직접 적어 넣은 값은 그 사람의 결정이므로 건드리지 않는다. 다만 `turns_per_day = 0`
은 "안 정함" 과 "제한 없음" 을 구별할 수 없다 — 화면에 이 칸이 생기기 전부터 0이었고
아무도 0을 고른 적이 없으므로, 여기서는 안 정한 것으로 본다. 다시 0으로 두고 싶으면
비서 설정에서 그렇게 하면 된다.

Revision ID: 0069_visitor_default_limits
Revises: 0068_square_name_for_speakers
"""
from alembic import op

revision = "0069_visitor_default_limits"
down_revision = "0068_square_name_for_speakers"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 하루 전체 상한: 없거나 0이면 200.
    op.execute("""
        UPDATE agents
           SET visitor_settings = coalesce(visitor_settings, '{}'::jsonb)
                                  || jsonb_build_object('turns_per_day', 200)
         WHERE coalesce((visitor_settings->>'turns_per_day')::int, 0) = 0
    """)
    # 한 방문자의 말 속도: 안 정했거나 옛 기본값(8)이면 10.
    op.execute("""
        UPDATE agents
           SET visitor_settings = coalesce(visitor_settings, '{}'::jsonb)
                                  || jsonb_build_object('rate_per_minute', 10)
         WHERE coalesce((visitor_settings->>'rate_per_minute')::int, 8) = 8
    """)
    # 한 IP 가 한 시간에 여는 새 대화: 전에는 코드에 박혀 있던 30을 설정으로 옮긴다.
    op.execute("""
        UPDATE agents
           SET visitor_settings = coalesce(visitor_settings, '{}'::jsonb)
                                  || jsonb_build_object('sessions_per_hour', 30)
         WHERE visitor_settings IS NULL OR NOT (visitor_settings ? 'sessions_per_hour')
    """)


def downgrade() -> None:
    # 울타리를 도로 걷지 않는다. 내리고 싶으면 비서 설정에서 내린다.
    pass
