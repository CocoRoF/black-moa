"""기억은 무엇을 남기고 무엇을 버리나 (plan/50).

여기 있는 것은 전부 운영에서 실제로 쌓인 것을 보고 만든 검사다.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from blackmoa.memory.distill import NOTE_MAX, SAME_STORY, _merged_body, _same_story
from blackmoa.memory.notes import content_words, overlap


@dataclass
class N:
    id: str
    title: str
    body: str
    meta: dict[str, Any] = field(default_factory=dict)


def test_particles_do_not_make_two_words_strangers():
    """조사를 안 떼면 "스완에게" 와 "스완의" 가 남남이 된다."""
    assert "스완" in content_words("스완에게 인사를 보냈다")
    assert "스완" in content_words("스완의 인사를 받았다")
    assert overlap("스완에게 인사를 보냈다", "스완의 인사를 받았다") > 0.2
    # 한 글자는 거의 다 조사나 수사다. 낱말로 세면 아무 두 글이나 겹친다.
    assert content_words("가 를 은") == set()
    # `의` 로 끝나는 낱말은 지킨다. 떼면 한 글자가 되는 것들이다.
    assert content_words("회의 임의 편의") == {"회의", "임의", "편의"}
    assert "프로젝트" in content_words("프로젝트의")
    assert overlap("", "무엇이든") == 0.0


def test_grammar_alone_never_counts_as_the_same_story():
    """글자 조각으로 재던 때 이 쌍이 0.30 이었다. 겹치는 것은 어미뿐이다.

    내용어로 재면 0.17 로 내려가고 문턱(0.30) 아래에 있다. 이 검사가 깨지면
    무관한 기억이 합쳐지기 시작한다는 뜻이다.
    """
    assert overlap("금요일에 배포하기로 했다.", "수요일에 점심을 먹기로 했다.") < SAME_STORY
    assert overlap("스완에게 인사를 보냈다", "제니의 모델을 바꿨다") == 0.0


def test_the_duplicate_that_actually_happened_is_caught():
    """운영에 52분 간격으로 두 개 쌓였던 그 쌍 (plan/50 §1-2).

    본문 겹침으로도 잡히고, 제목이 글자 그대로 같아서 제목만으로도 잡힌다.
    """
    a = "스완에게 인사 메시지를 보내기로 함. 현재 스완의 공개 연락처가 확인되지 않음. 배조스완을 통한 연결 가능성 검토 중."
    b = "장하렴이 스완에게 인사 메시지를 보내기를 원함. 스완의 공개 링크/연락처가 필요한 상태."
    assert overlap(a, b) >= SAME_STORY, overlap(a, b)
    # 제목까지 같았으므로 제목만으로도 잡힌다.
    here = [N(id="conversations/2026-09-13/x", title="스완과의 연락 시도", body=a)]
    assert _same_story("스완과의 연락 시도", b, here) is here[0]


def test_a_different_story_is_not_merged():
    """겹침을 낮게 잡으면 다른 이야기가 합쳐진다. 그건 기억을 잃는 것이다."""
    here = [N(id="a", title="금요일 배포", body="금요일에 배포하기로 했다.")]
    assert _same_story("말투 취향", "긴 설명보다 한 문장을 좋아한다.", here) is None
    assert _same_story("점심 약속", "수요일에 점심을 먹기로 했다.", here) is None


def test_the_reworded_duplicate_is_left_to_the_prompt():
    """같은 일을 **다른 말로** 적은 것은 본문 겹침만으로는 못 잡는다.

    0.20 쯤 나오는데, 무관한 짧은 문장도 0.17 까지 올라오므로 그 구간을 자동으로
    합치면 기억을 잃는다. 이 구간은 프롬프트가 맡는다 — 이 대화에 이미 적어 둔 것을
    모델에게 보여 주고 같은 말이면 쓰지 말라고 한다 (plan/50 §2).

    이 검사는 "못 잡는다" 를 못 박는다. 나중에 문턱을 낮추려는 사람이 이 줄을 보고
    무엇을 잃는지 알도록.
    """
    here = [N(id="a", title="새로운 프로젝트 시작 (@제니)",
              body="장하렴이 @제니에서 새로운 프로젝트를 시작하셨습니다. 아직 구체적인 내용이나 세부사항은 확인되지 않았습니다.")]
    body = "장하렴이 소셜 미디어에 '새로운 프로젝트를 시작했어'라는 글을 올렸고, 사용자를 멘션(@제니)했음."
    assert overlap(body, here[0].body) < SAME_STORY
    assert _same_story("장하렴이 새로운 프로젝트 시작 공지", body, here) is None
    # 프롬프트가 이 대화의 기존 노트를 실제로 보여 주는지.
    import inspect

    from blackmoa.memory import distill as D

    assert "{notes_here}" in D.SYSTEM
    assert "return null" in D.SYSTEM
    assert "recent_in_conversation" in inspect.getsource(D.distill_turn)


def test_nothing_to_compare_against_writes_a_new_note():
    assert _same_story("처음 적는 것", "본문", []) is None


def test_an_errand_turn_is_never_distilled():
    """막는 자리는 증류 안에 하나다 (plan/50 §2).

    부르는 쪽에서만 거르면 다른 경로로 증류를 부르는 코드가 생기는 순간 다시 샌다.
    """
    import inspect

    from blackmoa.memory import distill as D

    src = inspect.getsource(D.distill_turn)
    assert "if turn.simulated:" in src, "증류가 스스로 심부름을 거절하지 않는다"
    # 그리고 심부름을 만드는 곳이 턴에 표시를 붙인다.
    from blackmoa.services import blog as B

    for fn in (B.describe_photos, B.secretary_reply):
        assert "simulated=True" in inspect.getsource(fn), fn.__name__


def test_the_same_story_grows_instead_of_being_overwritten():
    """합칠 때 덮어쓰면 옛 줄에만 있던 것이 사라진다 (plan/50 §2).

    "연락처가 없어 못 보냈다" 위에 "보냈다" 를 덮으면 왜 늦었는지가 없어진다.
    이어 붙이면 둘 다 남는다.
    """
    old = "스완에게 보낼 초대를 썼다. 연락처가 없어 아직 못 보냈다."
    new = "연락처를 받아서 초대를 보냈다."
    merged = _merged_body(old, new)
    assert old in merged and new in merged
    # 이미 적힌 말은 두 번 적지 않는다.
    assert _merged_body(merged, new) == merged
    assert _merged_body("", new) == new


def test_a_note_that_keeps_growing_sheds_its_oldest_lines():
    """자라기만 하는 줄은 결국 못 읽는다. 버려야 한다면 오래된 쪽이다."""
    old = "\n\n".join(f"[{i}] 예전에 적은 줄. " + "가나다라마바사" * 60 for i in range(12))
    merged = _merged_body(old, "오늘 적은 줄.")
    assert len(merged) <= NOTE_MAX
    assert "오늘 적은 줄." in merged
    assert "[11]" in merged        # 가장 최근 것은 남고
    assert "[0]" not in merged     # 가장 오래된 것부터 나간다
