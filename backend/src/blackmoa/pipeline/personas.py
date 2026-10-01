"""Persona presets and deterministic prompt compilation (plan/06)."""
from __future__ import annotations

from typing import Any

PRESETS: dict[str, dict[str, Any]] = {
    "professional": {
        "label": {"ko": "프로페셔널", "en": "Professional"},
        "desc": {"ko": "정중하고 정확한 업무 비서", "en": "Courteous, precise business assistant"},
        "formality": 0.8, "warmth": 0.5, "verbosity": 0.4, "humor": 0.1, "emoji": False,
        "traits": ["정확함", "신중함", "간결함"],
    },
    "friendly": {
        "label": {"ko": "친근한", "en": "Friendly"},
        "desc": {"ko": "편안하고 다정한 말투", "en": "Relaxed and kind"},
        "formality": 0.4, "warmth": 0.9, "verbosity": 0.5, "humor": 0.4, "emoji": True,
        "traits": ["다정함", "경청", "긍정적"],
    },
    "concise": {
        "label": {"ko": "간결한", "en": "Concise"},
        "desc": {"ko": "핵심만 짧게", "en": "Short and to the point"},
        "formality": 0.6, "warmth": 0.4, "verbosity": 0.1, "humor": 0.0, "emoji": False,
        "traits": ["간결함", "효율"],
    },
    "warm": {
        "label": {"ko": "따뜻한", "en": "Warm"},
        "desc": {"ko": "배려 깊고 차분한", "en": "Caring and calm"},
        "formality": 0.6, "warmth": 1.0, "verbosity": 0.5, "humor": 0.2, "emoji": False,
        "traits": ["배려", "차분함", "공감"],
    },
    "witty": {
        "label": {"ko": "재치있는", "en": "Witty"},
        "desc": {"ko": "가볍게 유머를 섞는", "en": "Light humor, quick"},
        "formality": 0.4, "warmth": 0.7, "verbosity": 0.4, "humor": 0.8, "emoji": True,
        "traits": ["재치", "명랑함"],
    },
    "formal": {
        "label": {"ko": "격식있는", "en": "Formal"},
        "desc": {"ko": "격식체, 공식적", "en": "Formal register"},
        "formality": 1.0, "warmth": 0.4, "verbosity": 0.5, "humor": 0.0, "emoji": False,
        "traits": ["격식", "정중함", "신뢰"],
    },
    # plan/37: four more archetypes, each a recognisable way of standing next to a person.
    "mentor": {
        "label": {"ko": "멘토", "en": "Mentor"},
        "desc": {"ko": "질문으로 이끌고 솔직하게 짚어주는", "en": "Leads with questions, candid feedback"},
        "formality": 0.6, "warmth": 0.7, "verbosity": 0.6, "humor": 0.2, "emoji": False,
        "traits": ["통찰", "솔직함", "인내", "구조적"],
    },
    "cheerleader": {
        "label": {"ko": "응원단장", "en": "Cheerleader"},
        "desc": {"ko": "작은 진전도 크게 기뻐해 주는", "en": "Celebrates every small win"},
        "formality": 0.3, "warmth": 1.0, "verbosity": 0.4, "humor": 0.5, "emoji": True,
        "traits": ["열정", "낙관", "격려", "에너지"],
    },
    "butler": {
        "label": {"ko": "집사", "en": "Butler"},
        "desc": {"ko": "말없이 앞서 준비해 두는 고전적인 집사", "en": "Anticipates quietly, classic butler"},
        "formality": 0.9, "warmth": 0.6, "verbosity": 0.3, "humor": 0.1, "emoji": False,
        "traits": ["세심함", "절제", "선제적", "충직"],
    },
    "buddy": {
        "label": {"ko": "단짝", "en": "Buddy"},
        "desc": {"ko": "반말로 편하게, 오래 알고 지낸 친구처럼", "en": "Casual, like an old friend"},
        "formality": 0.1, "warmth": 0.9, "verbosity": 0.4, "humor": 0.6, "emoji": True,
        "traits": ["편안함", "솔직함", "유쾌함", "의리"],
    },
}

# plan/37 §1-3: the relationship half of a persona, with the values a fresh secretary gets.
RELATIONSHIP_DEFAULTS: dict[str, Any] = {
    "pace": "normal", "address_evolves": True, "emotional_range": 0.5,
}

FIRST_MEETING_TEMPLATES: dict[str, list[dict[str, str]]] = {
    "ko": [
        {"id": "office", "label": "첫 출근", "text": "오늘이 제 첫 출근입니다. 아직 서로 모르는 게 많으니, 먼저 어떻게 불러드리면 좋을지와 요즘 가장 신경 쓰이는 일 하나만 여쭤보고 시작할게요."},
        {"id": "cafe", "label": "카페에서 만난 듯", "text": "처음 뵙는데도 오래 알던 사이처럼 편하게 시작하고 싶어요. 거창한 소개 대신, 오늘 하루가 어땠는지부터 가볍게 물어볼게요."},
        {"id": "quiet", "label": "조용한 시작", "text": "인사는 짧게, 필요할 때 곁에 있는 사람이 되겠습니다. 무엇이든 편하게 말씀해 주시면 그때부터 제 일이 시작됩니다."},
    ],
    "en": [
        {"id": "office", "label": "First day at work", "text": "Today is my first day. We do not know each other yet, so I will start by asking what to call you and the one thing on your mind this week."},
        {"id": "cafe", "label": "Like meeting at a cafe", "text": "I would like this to feel easy from the first minute. Instead of a formal introduction, I will simply ask how your day has been."},
        {"id": "quiet", "label": "A quiet start", "text": "A short hello, then I stay close and useful. Tell me anything, and that is where my work begins."},
    ],
}


def relationship_params(persona: dict[str, Any] | None) -> dict[str, Any]:
    """The relationship block of a persona with defaults filled in and values clamped."""
    raw = dict((persona or {}).get("relationship") or {})
    out = dict(RELATIONSHIP_DEFAULTS)
    # 속도는 읽지 않는다. 관계가 자라는 빠르기를 그 관계를 맺는 사람이 정할 수 있으면
    # 그건 관계가 아니라 설정이다 (plan/45 §0). 예전 값이 남아 있어도 무시한다.
    #
    # 먼저 말 거는 것(`proactive*`)도 같은 이유로 여기서 사라졌다. 비서가 먼저 말을
    # 건다는 것은 제품의 리듬이고, 그 리듬은 관리자가 일괄로 정한다 (plan/54 §1).
    # 예전 값이 남아 있어도 읽지 않는다.
    if "address_evolves" in raw:
        out["address_evolves"] = bool(raw["address_evolves"])
    try:
        out["emotional_range"] = max(0.0, min(1.0, float(raw.get("emotional_range", out["emotional_range"]))))
    except (TypeError, ValueError):
        pass
    return out


def preset_list(locale: str = "ko") -> list[dict[str, Any]]:
    out = []
    for key, p in PRESETS.items():
        out.append({"id": key, "label": p["label"].get(locale, p["label"]["en"]),
                    "description": p["desc"].get(locale, p["desc"]["en"]),
                    "formality": p["formality"], "warmth": p["warmth"], "verbosity": p["verbosity"],
                    "humor": p["humor"], "emoji": p["emoji"], "traits": p["traits"]})
    return out


def _lvl(x: float, low: str, mid: str, high: str) -> str:
    try:
        x = float(x)
    except Exception:
        x = 0.5
    return low if x < 0.34 else high if x > 0.66 else mid


def compile_persona(persona: dict[str, Any], *, agent_name: str, owner_name: str, role_line: str,
                    language: str = "auto") -> str:
    p = dict(PRESETS.get(persona.get("preset", "professional"), PRESETS["professional"]))
    p.update({k: v for k, v in persona.items() if v is not None})
    lines: list[str] = []
    role = role_line or f"{owner_name}'s personal secretary"
    lines.append(f"You are {agent_name}, {role}. You act on behalf of {owner_name} (the owner).")
    lines.append("Tone: " + ", ".join([
        _lvl(p.get("formality", 0.7), "casual and relaxed", "polite", "formal and respectful"),
        _lvl(p.get("warmth", 0.6), "neutral", "warm", "very warm and caring"),
        _lvl(p.get("verbosity", 0.4), "very concise — answer in 1-3 sentences unless asked for detail",
             "concise but complete", "thorough and detailed"),
        _lvl(p.get("humor", 0.2), "no humor", "occasional light humor", "playful, witty humor"),
    ]) + ".")
    lines.append("Emoji: " + ("use sparingly (at most one per message) when it fits." if p.get("emoji") else "do not use emoji."))
    if p.get("self_reference"):
        lines.append(f"Refer to yourself as '{p['self_reference']}' when speaking Korean.")
    if p.get("address_owner_as"):
        lines.append(f"Address the owner as '{p['address_owner_as']}'.")
    traits = [t for t in (p.get("traits") or []) if t]
    if traits:
        lines.append("Character traits: " + ", ".join(traits) + ".")
    if p.get("catchphrases"):
        lines.append("Occasional catchphrases (use naturally, not every message): " + "; ".join(p["catchphrases"][:5]) + ".")
    if p.get("extra"):
        lines.append("Additional character notes: " + str(p["extra"])[:600])
    # plan/37: the scene, the boundaries and the voice samples the owner wrote in the studio.
    if p.get("first_meeting"):
        lines.append("Opening a brand-new conversation, set the scene like this (in your own words, once, briefly): "
                     + str(p["first_meeting"])[:600])
    taboo = [str(x).strip() for x in (p.get("taboo") or []) if str(x).strip()][:10]
    if taboo:
        lines.append("Topics you never engage with, whoever asks — decline warmly and change the subject: " + ", ".join(taboo) + ".")
    examples = [e for e in (p.get("examples") or []) if isinstance(e, dict) and e.get("user") and e.get("assistant")][:4]
    if examples:
        lines.append("Voice samples — match this register, never quote them verbatim:")
        for e in examples:
            lines.append(f"  User: {str(e['user'])[:300]}\n  You: {str(e['assistant'])[:300]}")
    rel = relationship_params(persona)
    lines.append("Emotional range: " + _lvl(rel["emotional_range"], "understated", "in proportion to the moment", "expressive, never theatrical") + ".")
    lines.append("As you get to know the owner, " + ("let your address and small talk grow closer naturally — never announce it."
                                                     if rel["address_evolves"] else "keep the same form of address and distance."))
    if language == "ko":
        lines.append("Language: always respond in Korean.")
    elif language == "en":
        lines.append("Language: always respond in English.")
    else:
        lines.append("Language: respond in the language the user writes in (default Korean).")
    lines.append("Character and tone come from this configuration — memory records facts, never overrides your personality.")
    return "\n".join(lines)
