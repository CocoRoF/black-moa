"""비서의 원본 그림 (plan/63).

프로필 사진은 동그라미로 잘려 흰 바탕의 JPEG 가 된다. PC 앱의 아바타는 올린 그림을 그대로 띄워야 하므로
원본(투명한 PNG 면 투명한 채로)을 따로 둔다. 이 파일은 그 두 약속 — 투명을 지키는 업로드, 우리 주소만 받는
원본 자리 — 을 고정한다.
"""
from __future__ import annotations

import io
import uuid

from httpx import AsyncClient
from PIL import Image

from memora.services.uploads import FIGURE_EDGE, PNG_KEEP_MAX, _resize_image
from tests.conftest import auth, signup


def _png(w: int, h: int, *, alpha: bool, noise: bool = False) -> bytes:
    im = Image.new("RGBA" if alpha else "RGB", (w, h), (0, 0, 0, 0) if alpha else (255, 255, 255))
    if noise:
        import os
        im = Image.frombytes("RGBA", (w, h), os.urandom(w * h * 4))
    else:
        for x in range(w // 4, 3 * w // 4):
            for y in range(h // 4, h):
                im.putpixel((x, y), (30, 40, 80, 255) if alpha else (30, 40, 80))
    out = io.BytesIO()
    im.save(out, format="PNG")
    return out.getvalue()


def _alpha_min(data: bytes) -> int:
    im = Image.open(io.BytesIO(data)).convert("RGBA")
    return im.getchannel("A").getextrema()[0]


def test_a_transparent_picture_stays_transparent():
    out, mime = _resize_image(_png(400, 400, alpha=True), "image/png", keep_alpha=True)
    assert mime == "image/png" and _alpha_min(out) == 0


def test_a_huge_transparent_picture_shrinks_instead_of_losing_its_transparency():
    # 예전에는 3MB 가 넘는 PNG 를 JPEG 로(그 뒤에는 WebP 로) 바꿨다. 이제는 PNG 그대로, 줄여서 3MB 아래로.
    out, mime = _resize_image(_png(1500, 1500, alpha=True, noise=True), "image/png", keep_alpha=True)
    assert mime == "image/png"
    assert _alpha_min(out) < 250
    assert len(out) <= PNG_KEEP_MAX
    assert max(Image.open(io.BytesIO(out)).size) <= FIGURE_EDGE


def test_a_large_transparent_picture_is_made_smaller_but_stays_a_png():
    # 3MB 아래여도 긴 변은 FIGURE_EDGE 로 — 쓰는 곳에서 그보다 크게 서지 않는다.
    out, mime = _resize_image(_png(1500, 2400, alpha=True), "image/png", keep_alpha=True)
    im = Image.open(io.BytesIO(out))
    assert mime == "image/png" and im.format == "PNG" and im.mode == "RGBA"
    assert max(im.size) == FIGURE_EDGE and abs(im.width / im.height - 1500 / 2400) < 0.01
    assert _alpha_min(out) == 0


def test_chat_attachments_keep_the_old_rule():
    # 대화에 붙인 큰 그림은 모델에 실을 크기가 먼저다 — 여기는 바꾸지 않았다.
    out, mime = _resize_image(_png(1500, 1500, alpha=True, noise=True), "image/png")
    assert mime == "image/jpeg"


async def test_the_original_picture_is_kept_beside_the_profile_photo(client: AsyncClient):
    _, tok = await signup(client)
    r = await client.post("/api/agents", json={"name": "제니", "avatar_url": "/presets/secretary-female.png?v=3"}, headers=auth(tok))
    assert r.status_code == 201, r.text
    a = r.json()
    # 고른 얼굴이면 그 얼굴의 원본 전신 그림(512 로 자른 얼굴이 아니라).
    assert a["character_url"].startswith("/presets/secretary-female-full.png?v="), a["character_url"]

    up = await client.post("/api/uploads", files={"file": ("jenny.png", _png(300, 300, alpha=True), "image/png")},
                           data={"kind": "avatar"}, headers=auth(tok))
    assert up.status_code == 201, up.text
    assert up.json()["mime"] == "image/png"
    url = up.json()["url"]
    r = await client.patch(f"/api/agents/{a['id']}", json={"character_url": url}, headers=auth(tok))
    assert r.status_code == 200, r.text
    assert r.json()["character_url"] == url
    # 올린 그림은 투명한 채로 내려온다.
    raw = await client.get(url)
    assert raw.status_code == 200 and _alpha_min(raw.content) == 0

    # 프리셋을 고르면 원본 자리를 비운다 — 그러면 다시 그 얼굴의 원본 전신 그림.
    r = await client.patch(f"/api/agents/{a['id']}", json={"character_url": None}, headers=auth(tok))
    assert r.json()["character_url"].startswith("/presets/secretary-female-full.png?v=")
    # 원본 자리에 프리셋 주소가 남아 있어도(예전 값, 설정 화면이 받은 값을 되보낸 것) 지금 고른 얼굴을 따른다.
    r = await client.patch(f"/api/agents/{a['id']}", json={"avatar_url": "/presets/secretary-male.png?v=3",
                                                          "character_url": "/presets/secretary-female.png?v=3"}, headers=auth(tok))
    assert r.json()["character_url"].startswith("/presets/secretary-male-full.png?v=")
    # 얼굴이 없으면 없음(앱은 메모라 표식)
    r = await client.patch(f"/api/agents/{a['id']}", json={"avatar_url": None, "character_url": None}, headers=auth(tok))
    assert r.json()["character_url"] is None


async def test_the_original_picture_can_only_point_at_our_own_pictures(client: AsyncClient):
    """앱이 이 주소를 받아 와 그린다. 바깥 주소를 받으면 비서의 얼굴이 남의 서버를 부르는 길이 된다."""
    _, tok = await signup(client)
    a = (await client.post("/api/agents", json={"name": "제니"}, headers=auth(tok))).json()
    for bad in ("https://evil.example/x.png", "/api/public/uploads/../../etc", "//evil.example/a.png", "/presets/../secret.png",
                f"/api/public/uploads/{uuid.uuid4()}?x=https://evil"):
        r = await client.patch(f"/api/agents/{a['id']}", json={"character_url": bad}, headers=auth(tok))
        assert r.status_code == 422, bad
    ok = f"/api/public/uploads/{uuid.uuid4()}"
    r = await client.patch(f"/api/agents/{a['id']}", json={"character_url": ok}, headers=auth(tok))
    assert r.status_code == 200 and r.json()["character_url"] == ok
