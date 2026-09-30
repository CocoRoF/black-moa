"""올린 파일을 다시 여는 길 (plan/55 §7 P0).

예전에는 저장소를 S3 로 옮긴 뒤 ``GET /api/uploads/{id}`` 가 모두 500 이었고, 대화에
붙인 그림은 로그인 토큰을 못 싣는 ``<img>`` 라 401 이었다. 둘 다 여기서 막는다.
"""
from __future__ import annotations

import io

from httpx import AsyncClient

from memora.services.uploads import _resize_image, _sniff, with_urls
from tests.conftest import auth, signup


def _jpeg(w: int = 40, h: int = 20, orientation: int | None = None) -> bytes:
    from PIL import Image
    im = Image.new("RGB", (w, h), (200, 30, 30))
    out = io.BytesIO()
    if orientation:
        exif = Image.Exif()
        exif[0x0112] = orientation
        im.save(out, format="JPEG", exif=exif.tobytes())
    else:
        im.save(out, format="JPEG")
    return out.getvalue()


def test_heic_is_recognised_and_becomes_jpeg():
    from PIL import Image
    from pillow_heif import from_pillow
    buf = io.BytesIO()
    from_pillow(Image.new("RGB", (32, 16), (10, 120, 200))).save(buf, quality=60)
    data = buf.getvalue()
    assert _sniff(data, "application/octet-stream") == "image/heic"
    out, mime = _resize_image(data, "image/heic")
    assert mime == "image/jpeg"
    assert Image.open(io.BytesIO(out)).size == (32, 16)


def test_a_phone_photo_is_stood_up_before_its_exif_is_dropped():
    """EXIF 6 = 시계 방향으로 돌려 보라. 버리기 전에 실제로 돌려야 옆으로 눕지 않는다."""
    from PIL import Image
    out, _ = _resize_image(_jpeg(40, 20, orientation=6), "image/jpeg")
    assert Image.open(io.BytesIO(out)).size == (20, 40)


def test_urls_are_made_here_never_taken_from_the_request():
    atts = with_urls([{"upload_id": "u1", "filename": "a.png", "mime": "image/png", "url": "javascript:alert(1)", "text": "x"},
                      {"filename": "ghost", "url": "https://evil.example/x.png"}])
    assert atts[0]["url"].startswith("/api/uploads/u1/raw?t=")
    assert "text" not in atts[0]
    assert "url" not in atts[1]


async def test_owner_can_open_and_img_can_open_by_signature(client: AsyncClient):
    _, tok = await signup(client)
    r = await client.post("/api/uploads", headers=auth(tok), files={"file": ("사진.jpg", _jpeg(), "image/jpeg")},
                          data={"kind": "attachment"})
    assert r.status_code == 201, r.text
    body = r.json()
    uid, url = body["upload_id"], body["url"]
    assert url.startswith(f"/api/uploads/{uid}/raw?t=")

    own = await client.get(f"/api/uploads/{uid}", headers=auth(tok))
    assert own.status_code == 200 and own.headers["content-type"] == "image/jpeg"
    assert own.headers["x-content-type-options"] == "nosniff"

    signed = await client.get(url)                       # 토큰 없이, <img> 처럼
    assert signed.status_code == 200 and signed.content == own.content

    assert (await client.get(f"/api/uploads/{uid}/raw?t=nope")).status_code == 404
    _, other = await signup(client)
    assert (await client.get(f"/api/uploads/{uid}", headers=auth(other))).status_code == 404


async def test_a_signature_opens_only_its_own_file(client: AsyncClient):
    _, tok = await signup(client)
    a = (await client.post("/api/uploads", headers=auth(tok), files={"file": ("a.jpg", _jpeg(), "image/jpeg")})).json()
    b = (await client.post("/api/uploads", headers=auth(tok), files={"file": ("b.jpg", _jpeg(), "image/jpeg")})).json()
    t = a["url"].split("t=", 1)[1]
    assert (await client.get(f"/api/uploads/{b['upload_id']}/raw?t={t}")).status_code == 404


async def test_a_text_file_downloads_instead_of_rendering(client: AsyncClient):
    _, tok = await signup(client)
    up = (await client.post("/api/uploads", headers=auth(tok),
                            files={"file": ("x.txt", b"<script>alert(1)</script>", "text/plain")})).json()
    r = await client.get(up["url"])
    assert r.status_code == 200
    assert r.headers["content-disposition"].startswith("attachment;")
    assert "sandbox" in r.headers["content-security-policy"]


def test_a_screenshot_stays_a_png():
    """글자가 든 화면 캡처를 JPEG 로 바꾸면 글자가 번진다."""
    from PIL import Image
    im = Image.new("RGB", (300, 100), (255, 255, 255))
    buf = io.BytesIO()
    im.save(buf, format="PNG")
    out, mime = _resize_image(buf.getvalue(), "image/png")
    assert mime == "image/png" and out[:8] == b"\x89PNG\r\n\x1a\n"
