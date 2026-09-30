"""먼저 말 걸기는 관리자의 것이다 (plan/54 §1).

비서마다 켜고 끄던 스위치(`persona.relationship.proactive`)와 그 시간대·하루 횟수를
걷는다. 엔진은 이미 읽지 않는다 — 남겨 두면 화면에는 없는데 데이터에는 있는 값이
되고, 언젠가 누가 그것을 다시 읽는다.

**모든 비서는 켜진 채로 간다.** 끄고 있던 비서도 이 이관 뒤에는 관리자의 설정을
따른다. 그것이 옮긴다는 말의 뜻이다.

Revision ID: 0070_triggers_are_the_admins
Revises: 0069_visitor_default_limits
"""
from alembic import op

revision = "0070_triggers_are_the_admins"
down_revision = "0069_visitor_default_limits"
branch_labels = None
depends_on = None

DEAD = ("proactive", "proactive_hours", "proactive_max_per_day")


def upgrade() -> None:
    for key in DEAD:
        op.execute(f"""
            UPDATE agents
               SET persona = jsonb_set(persona, '{{relationship}}',
                                       (persona->'relationship') - '{key}')
             WHERE persona ? 'relationship'
               AND jsonb_typeof(persona->'relationship') = 'object'
               AND (persona->'relationship') ? '{key}'
        """)
    # 성격 스냅샷(되돌리기용)은 그때의 기록이라 손대지 않는다.


def downgrade() -> None:
    # 개인에게 돌려주지 않는다. 되돌리려면 그 결정을 다시 해야 한다.
    pass
