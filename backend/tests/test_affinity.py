"""호감도 — 쌓기는 어렵고 잃기는 쉽다 (plan/45 §4).

두 수를 나눈 이유가 이 파일에 다 있다. 자격은 쌓인 것이라 내려가지 않고, 호감도는
지금이라 방치하면 식는다. 실제 단계는 둘 중 낮은 쪽이다.
"""
from __future__ import annotations

from datetime import UTC, datetime, timedelta

from blackmoa.models import AgentRelationship
from blackmoa.services import relationship as R


def _rel(**kw) -> AgentRelationship:
    base = dict(stage="new", score=0.0, turns=0, active_days=0, streak_days=0, facts_remembered=0,
                posts_written=0, affinity=0.0, affinity_facts=0, milestones=[], mood={}, glanced=[])
    base.update(kw)
    return AgentRelationship(**base)


def test_the_stage_is_the_lower_of_what_was_earned_and_how_warm_it_is():
    # 동반까지 쌓았지만 온도가 식었다.
    cold = _rel(active_days=40, turns=200, facts_remembered=40, posts_written=20, affinity=30)
    assert R.earned_stage(cold) == "companion"
    assert R.warmth_stage(cold) == "familiar"
    assert R.computed_stage(cold) == "familiar"

    # 돌아오는 길은 짧다: 자격은 그대로라 온도만 오르면 제자리다.
    cold.affinity = 80
    assert R.computed_stage(cold) == "companion"


def test_talking_only_never_reaches_the_last_step():
    """마지막 한 칸은 자기 이야기를 남긴 적이 있어야 열린다 (결)."""
    talker = _rel(active_days=90, turns=500, facts_remembered=90, posts_written=0, affinity=100)
    assert R.earned_stage(talker) == "trusted"
    talker.posts_written = 10
    assert R.earned_stage(talker) == "companion"


def test_neglect_gets_steeper_every_day():
    assert R.decay_for(1) == 0 and R.decay_for(2) == 0          # 주말은 방치가 아니다
    three, four, five = R.decay_for(3), R.decay_for(4), R.decay_for(5)
    assert 0 < three < four < five                               # 날마다 가팔라진다
    assert R.decay_for(60) <= R.AFFINITY_DECAY_CAP               # 그래도 천장은 있다


def test_nobody_can_set_how_fast_it_grows():
    """속도 손잡이를 없앴으니 무엇을 넣어도 문지방은 하나다."""
    assert R.thresholds("fast") == R.thresholds("slow") == R.thresholds() == dict(R.THRESHOLDS)


def test_the_stage_can_come_back_down():
    from blackmoa.models import Agent

    rel = _rel(active_days=40, turns=200, facts_remembered=40, posts_written=20, affinity=100,
               started_at=datetime.now(UTC) - timedelta(days=40))
    agent = Agent(name="제니", persona={})

    # 처음 닿은 날은 소식이다.
    assert "stage_companion" in R.refresh_stage(rel, agent)
    assert rel.stage == "companion"

    # 오래 비면 내려간다. 멀어진 것은 알림이 아니라 상태다.
    rel.affinity = 10
    assert R.refresh_stage(rel, agent) == []
    assert rel.stage == "new"

    # 이정표는 지우지 않는다. 그건 역사이지 상태가 아니다.
    assert "stage_companion" in [m["key"] for m in rel.milestones]

    # 돌아와도 같은 소식을 두 번 전하지 않는다.
    rel.affinity = 100
    assert R.refresh_stage(rel, agent) == []
    assert rel.stage == "companion"


# ── 엔진 (plan/61) ─────────────────────────────────────────────────────────────
#
# 예전에는 하루 한 번의 정산에 오르는 것과 내리는 것이 함께 있어서, 15분 작업이 자정 직후 그날을 먼저
# 정산하면 낮의 대화가 한 번도 오르지 못했다. 운영에서 제니는 09-23·24·28 에 대화했는데 하나도 안 올랐다.

from datetime import date  # noqa: E402
from zoneinfo import ZoneInfo  # noqa: E402

TZ = ZoneInfo("Asia/Seoul")


def at(day: int, h: int = 12, m: int = 0) -> datetime:
    return datetime(2026, 9, day, h, m, tzinfo=TZ)


def fresh(affinity: float = 40.0) -> AgentRelationship:
    return _rel(started_at=at(1, 9), affinity=affinity, affinity_day=date(2026, 8, 31), affinity_state={},
                affinity_log=[], last_active_day=None)


def talk(rel: AgentRelationship, when: datetime) -> None:
    """record_turn 이 하는 순서 그대로: 지나간 것을 먼저 세고, 그다음 오늘의 대화."""
    R.advance(rel, when, TZ)
    rel.last_active_day = when.astimezone(TZ).date()
    R.credit_turn(rel, when, TZ)


def whys(rel: AgentRelationship) -> list[str]:
    return [e["why"] for e in rel.affinity_log]


def test_talking_after_the_midnight_settlement_still_counts():
    rel = fresh()
    talk(rel, at(1, 10))
    assert rel.affinity == 48
    R.advance(rel, at(2, 0, 5), TZ)          # 15분 작업이 자정 직후 하루를 정산했다
    assert rel.affinity == 48 and rel.affinity_day == date(2026, 9, 1)
    talk(rel, at(2, 9, 15))                  # 그날 낮의 대화 — 예전에는 여기서 아무것도 오르지 않았다
    assert rel.affinity == 56 and whys(rel) == ["talk", "talk"]


def test_one_talk_credit_a_day_and_one_more_for_a_lively_day():
    rel = fresh()
    for i in range(9):
        talk(rel, at(1, 10, i))
    assert rel.affinity == 48, "하루 한 번 — 몇 번 말했는지와 상관없이"
    talk(rel, at(1, 11))                     # 열 번째
    assert rel.affinity == 52 and whys(rel) == ["talk", "lively"]
    for i in range(20):
        talk(rel, at(1, 13, i))
    assert rel.affinity == 52, "활발한 날도 하루 한 번"
    talk(rel, at(2, 9))
    assert rel.affinity == 60, "다음 날은 다시"


def test_new_memories_count_up_to_a_daily_cap():
    rel = fresh()
    R.credit_facts(rel, at(1, 10), TZ, 5)
    assert rel.affinity == 46 and rel.affinity_facts == 5, "다섯 개여도 하루 최대 +6"
    R.credit_facts(rel, at(1, 20), TZ, 7)
    assert rel.affinity == 46 and rel.affinity_facts == 7, "넘친 것은 이월하지 않는다"
    R.credit_facts(rel, at(2, 10), TZ, 8)
    assert rel.affinity == 48
    R.credit_facts(rel, at(2, 11), TZ, 3)     # 기억을 지웠다 — 기준만 낮춘다
    R.credit_facts(rel, at(2, 12), TZ, 4)
    assert rel.affinity == 50 and rel.affinity_facts == 4


def test_a_quiet_day_cools_only_after_it_has_passed():
    rel = fresh(60)
    talk(rel, at(1, 10))                     # 68
    R.advance(rel, at(4, 0, 5), TZ)          # 2일·3일은 이틀의 여유
    assert rel.affinity == 68
    R.advance(rel, at(4, 23, 59), TZ)        # 말 없는 사흘째가 아직 끝나지 않았다 — 오늘 말하면 된다
    assert rel.affinity == 68
    R.advance(rel, at(5, 0, 5), TZ)          # 사흘째가 지나갔다
    assert rel.affinity == 62 and rel.affinity_log[-1]["why"] == "quiet_3"
    assert rel.affinity_log[-1]["at"].startswith("2026-09-04T15:00")      # 그날이 끝난 순간(한국 자정)
    R.advance(rel, at(6, 0, 5), TZ)
    assert rel.affinity == round(62 - R.decay_for(4), 2)
    # 글을 남긴 날은 식지 않는다(침묵의 길이는 이어진다).
    before = rel.affinity
    R.advance(rel, at(7, 0, 5), TZ, posted={date(2026, 9, 6)})
    assert rel.affinity == before
    R.advance(rel, at(8, 0, 5), TZ)
    assert rel.affinity == round(before - R.decay_for(6), 2)


def test_an_unanswered_word_cools_hard_and_quietly():
    rel = fresh(60)
    talk(rel, at(1, 10))                     # 68
    R.note_proactive(rel, at(1, 19))         # 비서가 먼저 건넸다
    R.note_proactive(rel, at(1, 21))         # 한 번 더 — 새 줄기를 만들지 않는다
    R.advance(rel, at(2, 18, 59), TZ)
    assert rel.affinity == 68
    R.advance(rel, at(2, 19), TZ)            # 하루 동안 답이 없다
    assert rel.affinity == 53 and rel.affinity_log[-1]["why"] == "ignored"
    R.advance(rel, at(3, 19), TZ)            # 이틀
    assert rel.affinity == 28 and rel.affinity_log[-1]["why"] == "ignored_2d"
    R.advance(rel, at(3, 23), TZ)
    assert rel.affinity == 28, "한 줄기에 기한마다 한 번씩만"
    talk(rel, at(4, 8))                      # 답했다 — 줄기가 끝나고, 그날의 대화가 붙는다
    assert rel.affinity == 36 and "awaiting" not in rel.affinity_state
    # 사용자에게 보이는 것에는 증감 기록이 없다.
    agent = __import__("blackmoa.models", fromlist=["Agent"]).Agent(name="제니", persona={}, owner_id=None)
    out = R.rel_out(rel, agent)
    assert "affinity_log" not in out and "awaiting" not in str(out)


def test_answering_within_a_day_costs_nothing_and_a_late_answer_still_pays():
    rel = fresh(60)
    talk(rel, at(1, 10))
    R.note_proactive(rel, at(1, 19))
    talk(rel, at(2, 18))                     # 23시간 뒤 답했다
    assert "ignored" not in whys(rel)
    R.note_proactive(rel, at(2, 20))
    # 워커가 멈춰 있어 기한을 아무도 세지 않았고, 30시간 뒤에 답했다 — 그래도 하루가 지난 것은 지난 것이다.
    talk(rel, at(4, 2))
    assert whys(rel)[-2:] == ["ignored", "talk"] and "awaiting" not in rel.affinity_state


def test_days_missed_by_the_worker_are_settled_one_by_one():
    rel = fresh(80)
    rel.affinity_state = {"talk_days": ["2026-09-01", "2026-09-03"]}
    rel.last_active_day = date(2026, 9, 3)
    R.advance(rel, at(10, 0, 5), TZ)        # 1~9일을 한 번에 — 하루씩 센다
    expected = 80 - sum(R.decay_for(n) for n in (3, 4, 5, 6))   # 6·7·8·9일
    assert rel.affinity == round(expected, 2) and rel.affinity_day == date(2026, 9, 9)
    assert whys(rel) == ["quiet_3", "quiet_4", "quiet_5", "quiet_6"]
