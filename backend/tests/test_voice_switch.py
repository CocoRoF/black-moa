"""음성 켜고 끄기 (plan/67).

관리자가 받아쓰기(STT)·읽어 주기(TTS)를 끄면 웹과 PC 앱은 단추와 설정을 감춘다. 그것은 이 서버가 알려 주는 값을
보고 하는 일이라, 알려 주는 값과 막는 일을 여기서 고정한다. 화면만 감추면 옛 앱이나 직접 부른 요청이 계속
공급자를 부르고 크레딧을 쓴다.
"""
from __future__ import annotations

import pytest_asyncio
from httpx import AsyncClient

from tests.conftest import auth, signup


async def _voice(stt: bool, tts: bool) -> None:
    from blackmoa.db.session import session_scope
    from blackmoa.services import settings as S
    async with session_scope() as db:
        await S.put(db, "stt.enabled", stt)
        await S.put(db, "tts.enabled", tts)
        await db.commit()
    S.invalidate("stt.")
    S.invalidate("tts.")


@pytest_asyncio.fixture
async def voice_restored(app):
    yield
    await _voice(True, True)


async def test_voice_is_on_by_default_and_the_status_says_so(client: AsyncClient):
    st = (await client.get("/api/auth/status")).json()
    assert st["voice"] == {"stt": True, "tts": True}


async def test_turning_voice_off_is_told_and_enforced(client: AsyncClient, voice_restored):
    _, tok = await signup(client)
    agent = (await client.post("/api/agents", json={"name": "서기"}, headers=auth(tok))).json()
    link = (await client.post(f"/api/agents/{agent['id']}/links", json={"label": "명함"}, headers=auth(tok))).json()

    await _voice(False, True)
    st = (await client.get("/api/auth/status")).json()
    assert st["voice"] == {"stt": False, "tts": True}
    # 주인의 대화: 받아쓰기는 공급자에 닿기 전에 막힌다.
    r = await client.post(f"/api/agents/{agent['id']}/stt", files={"file": ("a.webm", b"\x1a\x45\xdf\xa3", "audio/webm")}, headers=auth(tok))
    assert r.status_code == 403 and r.json()["error"]["code"] == "stt_disabled", r.text
    # 방문자 화면: 마이크는 감추고, 음성으로 듣기는 남는다.
    info = (await client.get(f"/api/public/links/{link['code']}")).json()["agent"]
    assert info["stt_enabled"] is False and info["tts_enabled"] is True and info["voice_enabled"] is True
    v = (await client.post(f"/api/public/links/{link['code']}/visitor", json={})).json()
    r = await client.post(f"/api/public/conversations/{v['conversation_id']}/stt",
                          files={"file": ("a.webm", b"\x1a\x45\xdf\xa3", "audio/webm")}, headers=auth(v["visitor_token"]))
    assert r.status_code == 403 and r.json()["error"]["code"] == "stt_disabled", r.text

    await _voice(False, False)
    assert (await client.get("/api/auth/status")).json()["voice"] == {"stt": False, "tts": False}
    r = await client.post(f"/api/agents/{agent['id']}/tts", json={"text": "안녕하세요"}, headers=auth(tok))
    assert r.status_code == 403 and r.json()["error"]["code"] == "tts_disabled", r.text
    r = await client.post(f"/api/public/conversations/{v['conversation_id']}/tts", json={"text": "안녕하세요"}, headers=auth(v["visitor_token"]))
    assert r.status_code == 403 and r.json()["error"]["code"] == "tts_disabled", r.text
    info = (await client.get(f"/api/public/links/{link['code']}")).json()["agent"]
    # 둘 다 끄면 방문자 화면에 "음성 대화" 도 보이지 않는다.
    assert info["voice_enabled"] is False and info["stt_enabled"] is False and info["tts_enabled"] is False


async def test_an_agent_that_refuses_voice_stays_silent_even_when_the_service_allows_it(client: AsyncClient):
    _, tok = await signup(client)
    agent = (await client.post("/api/agents", json={"name": "서기"}, headers=auth(tok))).json()
    await client.patch(f"/api/agents/{agent['id']}", json={"capabilities": {"voice": False}}, headers=auth(tok))
    link = (await client.post(f"/api/agents/{agent['id']}/links", json={"label": "명함"}, headers=auth(tok))).json()
    info = (await client.get(f"/api/public/links/{link['code']}")).json()["agent"]
    assert info["voice_enabled"] is False and info["stt_enabled"] is False and info["tts_enabled"] is False


async def test_the_admin_switch_takes_booleans_only(client: AsyncClient, voice_restored):
    from blackmoa.api.admin.router import coerce_setting
    from blackmoa.core.errors import ValidationFailed

    assert coerce_setting("stt.enabled", False) is False
    assert coerce_setting("tts.enabled", "true") is True
    try:
        coerce_setting("stt.enabled", "maybe")
    except ValidationFailed:
        pass
    else:
        raise AssertionError("a non-boolean was stored as the voice switch")
