"""The prompt stays inside its budget (plan/39 §2).

Every section has a ceiling, the whole base prompt has one, no bullet appears twice, and
the per-tool guide is gone from the system prompt (tool descriptions are the single source).
"""
from __future__ import annotations

import pytest
from httpx import AsyncClient

from tests.conftest import auth, signup

pytestmark = pytest.mark.asyncio

CEILINGS = {"base_mission": 700, "base_owner": 2200, "base_tools": 900, "base_resources": 1200, "base_rules": 1700,
            "base_relay": 1400, "base_answering": 500, "secretary": 1800, "relationship": 900, "base_visitor": 900}
TOTAL = {"owner": 5200, "visitor": 5600}


async def _sections(client, tok, aid, audience):
    r = await client.get(f"/api/agents/{aid}/prompt-preview", params={"audience": audience}, headers=auth(tok))
    assert r.status_code == 200, r.text
    return {s["key"]: s["text"] for s in r.json()["sections"]}


async def test_every_section_and_the_whole_stay_under_their_ceilings(client: AsyncClient):
    _, tok = await signup(client, name="예산")
    a = (await client.post("/api/agents", json={"name": "버짓"}, headers=auth(tok))).json()
    # a fully switched-on secretary: every capability, a long custom prompt, all persona extras
    await client.patch(f"/api/agents/{a['id']}", json={
        "capabilities": {k: True for k in ("knowledge", "network", "google_email", "google_calendar", "web_search", "voice", "leave_message", "meeting_request", "email_send", "file_share", "visitor_memory")},
        "custom_instructions": "내 비서가 지켰으면 하는 것들: " + "정중하지만 딱딱하지 않게. " * 20,
        "persona": {"preset": "buddy", "first_meeting": "오늘이 첫 출근입니다.", "taboo": ["정치", "종교"], "examples": [{"user": "안녕", "assistant": "반가워요"}],
                    "catchphrases": ["좋아요", "그럼요"], "traits": ["다정함", "재치"], "extra": "짧게 답하는 편"}}, headers=auth(tok))
    for audience in ("owner", "visitor"):
        secs = await _sections(client, tok, a["id"], audience)
        for key, text in secs.items():
            assert len(text) <= CEILINGS.get(key, 1500), f"{audience}/{key} is {len(text)} chars"
        total = sum(len(t) for k, t in secs.items() if k != "secretary")
        assert total <= TOTAL[audience], f"{audience} base prompt is {total} chars"
        # no bullet said twice
        bullets = [ln.strip() for t in secs.values() for ln in t.splitlines() if ln.strip().startswith("- ")]
        dup = {b for b in bullets if bullets.count(b) > 1}
        assert not dup, dup
        # tools: names appear in the tool schemas, not re-explained in the prompt
        tools = secs["base_tools"]
        assert "knowledge_search —" not in tools and "memory_search /" not in tools
        assert "exact name" in tools


async def test_relay_rules_are_stable_and_the_per_turn_note_is_small():
    from blackmoa.pipeline import base_prompt as BP
    for side in ("initiator", "target"):
        sec = BP.relay_section(side)
        assert len(sec) <= CEILINGS["base_relay"] and "relay_close" in sec
    # the boundaries moved into the owner rules once; the volatile relationship block no longer carries them
    assert "sexual" in BP.OWNER_RULES and "pretending to be human" in BP.OWNER_RULES
    from blackmoa.services import relationship as REL
    assert not hasattr(REL, "SAFETY_LINES")
