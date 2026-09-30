"""공개 대화의 모양 (plan/71): 링크마다 chat(기본) 또는 stage.

stage 는 배경 위에 비서의 그림이 서고 게임처럼 대화창으로 말하는 모양이다. 링크를 만들 때·고칠 때 정하고, 공개
페이지는 링크 정보에서 모양과 세울 그림(character_url)을 받는다.
"""
from __future__ import annotations

from httpx import AsyncClient

from tests.conftest import auth, signup


async def test_a_link_is_chat_unless_told_otherwise_and_can_be_a_stage(client: AsyncClient):
    _, tok = await signup(client)
    agent = (await client.post("/api/agents", json={"name": "제니", "avatar_url": "/presets/secretary-female.png?v=3"}, headers=auth(tok))).json()
    plain = (await client.post(f"/api/agents/{agent['id']}/links", json={"label": "명함"}, headers=auth(tok))).json()
    assert plain["settings"]["layout"] == "chat"
    pub = (await client.get(f"/api/public/links/{plain['code']}")).json()
    assert pub["link"]["layout"] == "chat"
    assert "character_url" in pub["agent"]

    _, tok2 = await signup(client)   # 비서 하나에 링크 하나 (plan/80) — 무대는 다른 비서의 링크로
    other = (await client.post("/api/agents", json={"name": "하나"}, headers=auth(tok2))).json()
    stage = (await client.post(f"/api/agents/{other['id']}/links", json={"label": "무대", "layout": "stage"}, headers=auth(tok2))).json()
    assert stage["settings"]["layout"] == "stage"
    assert (await client.get(f"/api/public/links/{stage['code']}")).json()["link"]["layout"] == "stage"

    # 고치기: 모양만 바꾸고 나머지 설정은 그대로. 모르는 모양은 무시한다.
    r = await client.patch(f"/api/links/{plain['id']}", json={"settings": {"layout": "stage"}}, headers=auth(tok))
    assert r.json()["settings"]["layout"] == "stage" and r.json()["settings"]["allow_agents"] is True
    r = await client.patch(f"/api/links/{plain['id']}", json={"settings": {"layout": "theater"}}, headers=auth(tok))
    assert r.json()["settings"]["layout"] == "stage"
    r = await client.patch(f"/api/links/{plain['id']}", json={"settings": {"layout": "chat"}}, headers=auth(tok))
    assert r.json()["settings"]["layout"] == "chat"


async def test_a_chosen_face_stands_on_the_stage_as_its_full_figure(client: AsyncClient):
    """고른 얼굴(512 상반신에 흰 바탕)을 세우면 바탕을 걷느라 머리 둘레가 희게 남고 얼굴만 부푼다. 공개 정보와 주인 쪽
    (PC 앱) 모두 그 얼굴의 **원본** 전신 그림(투명 PNG, 바이트 그대로)을 준다."""
    _, tok = await signup(client)
    agent = (await client.post("/api/agents", json={"name": "제니", "avatar_url": "/presets/secretary-female-dot-green.png?v=3"}, headers=auth(tok))).json()
    link = (await client.post(f"/api/agents/{agent['id']}/links", json={"label": "무대", "layout": "stage"}, headers=auth(tok))).json()
    pub = (await client.get(f"/api/public/links/{link['code']}")).json()
    assert pub["agent"]["character_url"].startswith("/presets/secretary-female-dot-green-full.png?v=")
    assert agent["character_url"] == pub["agent"]["character_url"]

    # 모르는 프리셋 이름이면 없음(무대가 프로필 사진을 쓴다)
    await client.patch(f"/api/agents/{agent['id']}", json={"avatar_url": "/presets/unknown-face.png"}, headers=auth(tok))
    assert (await client.get(f"/api/public/links/{link['code']}")).json()["agent"]["character_url"] is None


def test_every_preset_figure_is_a_small_transparent_png_made_from_its_original():
    """세우는 그림은 원본(투명 PNG)을 PNG 그대로 줄인 것이다 — 형식을 바꾸지 않고, 투명한 채로, 한 장 3MB 아래."""
    import importlib.util
    from pathlib import Path

    import pytest
    from PIL import Image

    from memora.services.agents import PRESET_FIGURES

    root = Path(__file__).resolve().parents[2]
    presets = root / "frontend" / "public" / "presets"
    tool = root / "tools" / "preset_figures.py"
    if not presets.is_dir() or not tool.is_file():
        pytest.skip("frontend tree not present")
    spec = importlib.util.spec_from_file_location("preset_figures", tool)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)  # type: ignore[union-attr]
    assert set(mod.SOURCES.values()) == set(PRESET_FIGURES), "도구의 목록과 백엔드의 목록이 갈라졌다"
    for rel, name in mod.SOURCES.items():
        f = presets / f"{name}-full.png"
        assert (presets / f"{name}.png").is_file(), name
        im = Image.open(f)
        assert im.format == "PNG" and im.mode == "RGBA", (name, im.format, im.mode)
        assert im.getchannel("A").getextrema()[0] == 0, f"{name} 가 투명하지 않다"
        assert max(im.size) <= mod.LONG_EDGE and f.stat().st_size <= mod.MAX_BYTES, (name, im.size, f.stat().st_size)
        # 원본의 사람 모양 그대로(비율) — 다른 그림으로 바뀌거나 늘어나지 않았다.
        src = Image.open(root / "images" / rel)
        bb = src.convert("RGBA").getchannel("A").getbbox()
        assert abs((bb[2] - bb[0]) / (bb[3] - bb[1]) - im.width / im.height) < 0.03, name


async def test_one_secretary_has_one_public_link(client):
    """비서 하나에 공개 링크 하나 (plan/80) — 둘째는 만들지 않고, 거둔 링크를 되살려 둘이 되게 하지도 않는다."""
    from tests.conftest import auth, signup
    _, tok = await signup(client)
    a = (await client.post("/api/agents", json={"name": "하나"}, headers=auth(tok))).json()
    first = (await client.post(f"/api/agents/{a['id']}/links", json={}, headers=auth(tok))).json()
    r = await client.post(f"/api/agents/{a['id']}/links", json={}, headers=auth(tok))
    assert r.status_code == 409 and r.json()["error"]["code"] == "link_exists"
    # 거두면 새로 만들 수 있다 — 그리고 옛 것을 되살리면 둘이 되니 막는다.
    assert (await client.patch(f"/api/links/{first['id']}", json={"status": "revoked"}, headers=auth(tok))).status_code == 200
    second = await client.post(f"/api/agents/{a['id']}/links", json={}, headers=auth(tok))
    assert second.status_code == 201
    r = await client.patch(f"/api/links/{first['id']}", json={"status": "active"}, headers=auth(tok))
    assert r.status_code == 409 and r.json()["error"]["code"] == "link_exists"
