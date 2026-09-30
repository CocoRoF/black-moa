from __future__ import annotations

import base64
import hashlib
import io
import os
import unicodedata
import uuid
import warnings
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from memora.config import get_settings
from memora.core import pools
from memora.core.errors import ValidationFailed
from memora.models import Upload
from memora.services import objectstore

IMAGE_MAX = 10 * 1024 * 1024
DOC_MAX = 25 * 1024 * 1024
AUDIO_MAX = 25 * 1024 * 1024
TEXT_MAX = 5 * 1024 * 1024
IMAGE_MAX_PIXELS = 40_000_000
#: PNG 로 남겨 둘 수 있는 최대. 모델 한 장 상한(5MB)보다 넉넉히 아래.
PNG_KEEP_MAX = 3 * 1024 * 1024
#: 투명한 원본 그림(비서를 세우는 그림)의 긴 변. 무대·PC 앱에서 가장 크게 서도 거의 1:1.
FIGURE_EDGE = 1280
ALLOWED = {"image/png", "image/jpeg", "image/webp", "image/gif", "image/heic", "image/heif", "application/pdf", "text/plain", "text/markdown", "text/csv",
           "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
           "application/vnd.openxmlformats-officedocument.presentationml.presentation",
           "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", "audio/webm", "audio/mpeg", "audio/mp4", "audio/wav"}


#: Read a whole upload, but never more than ``limit``.
#:
#: ``await file.read()`` takes whatever arrives before anything checks how big it is, so a
#: request at nginx's ceiling was fully materialised in memory and only then rejected for
#: being over a limit a fraction of that size. Reading in chunks means the refusal happens
#: at the moment the limit is passed, and the rest of the body is never held at all.
CHUNK = 1024 * 1024


async def read_capped(file: Any, limit: int) -> bytes:
    parts: list[bytes] = []
    total = 0
    while True:
        chunk = await file.read(CHUNK)
        if not chunk:
            break
        total += len(chunk)
        if total > limit:
            raise ValidationFailed(f"file is larger than {limit // (1024 * 1024)}MB", code="file_too_large")
        parts.append(chunk)
    return b"".join(parts)


_MAGIC_TYPES = {"image/png", "image/jpeg", "image/webp", "image/gif", "image/heic", "image/heif", "application/pdf"}
#: 아이폰이 찍는 사진. ISO BMFF 상자라 4바이트 뒤에 ``ftyp`` 와 상표가 온다.
_HEIF_BRANDS = {b"heic", b"heix", b"hevc", b"hevx", b"heim", b"heis", b"mif1", b"msf1"}
_ZIP_TYPES = {"application/vnd.openxmlformats-officedocument.wordprocessingml.document",
              "application/vnd.openxmlformats-officedocument.presentationml.presentation",
              "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"}


#: 확장자 → 형식. 브라우저가 알려 주는 형식은 비어 있거나(.md, 일부 HEIC) 엉뚱할 때가 있다
#: (윈도우의 .csv 는 application/vnd.ms-excel). 받는 형식이 아니면 이름으로 한 번 더 본다 —
#: 내용 검사(_sniff)는 그대로 거치므로 이름만 바꿔 다른 것을 들이밀 수는 없다.
_EXT_MIME = {"md": "text/markdown", "markdown": "text/markdown", "txt": "text/plain", "csv": "text/csv",
             "pdf": "application/pdf", "png": "image/png", "jpg": "image/jpeg", "jpeg": "image/jpeg",
             "webp": "image/webp", "gif": "image/gif", "heic": "image/heic", "heif": "image/heif",
             "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
             "pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
             "xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
             "mp3": "audio/mpeg", "m4a": "audio/mp4", "wav": "audio/wav", "webm": "audio/webm"}


def declared_mime(filename: str, mime: str) -> str:
    m = (mime or "application/octet-stream").split(";")[0].strip().lower()
    if m in ALLOWED:
        return m
    ext = (filename or "").rsplit(".", 1)[-1].lower() if "." in (filename or "") else ""
    return _EXT_MIME.get(ext, m)


def _sniff(data: bytes, declared: str) -> str:
    """Content-sniffed MIME. Types with a magic number are decided by bytes alone; a declared magic type whose
    bytes do not match is rejected (never store an HTML/script payload under image/png)."""
    magic = None
    if data[:8] == b"\x89PNG\r\n\x1a\n":
        magic = "image/png"
    elif data[:3] == b"\xff\xd8\xff":
        magic = "image/jpeg"
    elif data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        magic = "image/webp"
    elif data[:6] in (b"GIF87a", b"GIF89a"):
        magic = "image/gif"
    elif data[:5] == b"%PDF-":
        magic = "application/pdf"
    elif data[4:8] == b"ftyp" and data[8:12] in _HEIF_BRANDS:
        magic = "image/heic"
    if magic:
        return magic
    if declared in _MAGIC_TYPES:
        raise ValidationFailed("file content does not match its type", code="mime_mismatch")
    if declared in _ZIP_TYPES and data[:2] != b"PK":
        raise ValidationFailed("file content does not match its type", code="mime_mismatch")
    if declared.startswith("text/") and b"\x00" in data[:4096]:
        raise ValidationFailed("binary content declared as text", code="mime_mismatch")
    return declared


def _heif_opener() -> None:
    """HEIC 는 Pillow 가 혼자 못 연다. 한 번 등록하면 ``Image.open`` 이 알아본다."""
    global _HEIF_READY
    if not _HEIF_READY:
        from pillow_heif import register_heif_opener
        register_heif_opener()
        _HEIF_READY = True


_HEIF_READY = False


def _has_alpha(im) -> bool:
    if im.mode in ("RGBA", "LA", "PA") or (im.mode == "P" and "transparency" in im.info):
        a = (im.convert("RGBA") if im.mode != "RGBA" else im).getchannel("A")
        return a.getextrema()[0] < 250
    return False


def _resize_image(data: bytes, mime: str, max_edge: int = 1568, keep_alpha: bool = False) -> tuple[bytes, str]:
    from PIL import Image, ImageOps, UnidentifiedImageError

    if mime in ("image/heic", "image/heif"):
        _heif_opener()

    try:
        with warnings.catch_warnings():
            # Preserve PIL's built-in bomb threshold and make its warning fatal,
            # then apply the stricter Memora 40M-pixel ceiling ourselves. No
            # process-global PIL setting is mutated, so concurrent uploads do
            # not race each other's validation state.
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            probe = Image.open(io.BytesIO(data))
            width, height = probe.size
            if width <= 0 or height <= 0 or width * height > IMAGE_MAX_PIXELS:
                raise ValidationFailed("image dimensions are too large", code="image_too_many_pixels")
            probe.verify()

        # GIF animation is intentionally preserved after structural verification;
        # other formats are decoded and re-encoded to strip active/auxiliary data.
        if mime == "image/gif":
            return data, mime

        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            im = Image.open(io.BytesIO(data))
            im.load()
            # 휴대폰 사진은 픽셀을 눕혀 두고 EXIF 로 "세워서 보라"고 적는다. 아래에서 EXIF 를
            # 버리니 그 전에 실제로 세운다 — 안 그러면 올린 사진이 옆으로 누워 있다.
            im = ImageOps.exif_transpose(im)
            if keep_alpha and _has_alpha(im):
                # 프로필·비서의 원본 그림(plan/63): 투명한 곳은 투명한 채로, **PNG 그대로** 둔다. JPEG 로 바꾸면 투명한
                # 곳이 채워져 비서가 네모 판 위에 서고, WebP 는 가장자리가 번진다. 대신 크기를 줄인다 — 긴 변
                # FIGURE_EDGE(무대에 가장 크게 서도 거의 1:1), 그래도 3MB 가 넘으면 더 줄인다. LANCZOS 는 RGBA 를 알파를
                # 곱한 채로 줄여 머리카락 가장자리에 테가 생기지 않는다(프리셋은 tools/preset_figures.py 가 같은 규칙).
                im = im.convert("RGBA")
                edge = FIGURE_EDGE
                while True:
                    k = min(1.0, edge / max(im.size))
                    out_im = im if k >= 1 else im.resize((max(1, round(im.width * k)), max(1, round(im.height * k))), Image.LANCZOS)
                    png = io.BytesIO()
                    out_im.save(png, format="PNG", optimize=True, compress_level=9)
                    if png.tell() <= PNG_KEEP_MAX or edge <= 480:
                        return png.getvalue(), "image/png"
                    edge = int(edge * 0.85)
            w, h = im.size
            if max(w, h) > max_edge:
                scale = max_edge / max(w, h)
                im = im.resize((max(1, int(w * scale)), max(1, int(h * scale))))
            if mime == "image/png":
                # 화면 캡처는 글자가 많은 그림이다. JPEG 로 바꾸면 글자 가장자리가 번진다 —
                # 다시 그려 부속 데이터만 버리고 PNG 로 둔다. 너무 크면(사진을 PNG 로 올린
                # 경우) 모델에 실을 수 있는 크기를 넘으니 그때만 JPEG 로.
                png = io.BytesIO()
                (im if im.mode in ("RGB", "RGBA", "L", "LA") else im.convert("RGBA")).save(png, format="PNG", optimize=True)
                if png.tell() <= PNG_KEEP_MAX:
                    return png.getvalue(), "image/png"
            im = im.convert("RGB") if im.mode not in ("RGB", "L") else im
            out = io.BytesIO()
            im.save(out, format="JPEG", quality=85)
            return out.getvalue(), "image/jpeg"
    except ValidationFailed:
        raise
    except (Image.DecompressionBombError, Image.DecompressionBombWarning, UnidentifiedImageError, OSError, ValueError) as e:
        raise ValidationFailed("invalid or unsafe image", code="invalid_image") from e


def _read_sync(storage_path: str) -> bytes:
    """Synchronous read for the attachment loader, which already runs off the loop."""
    if storage_path.startswith(objectstore.S3_PREFIX):
        return objectstore._get_sync(objectstore._split(storage_path)[1])
    with open(storage_path, "rb") as fh:
        return fh.read()


async def store(db: AsyncSession, owner_id: uuid.UUID, *, kind: str, filename: str, mime: str, data: bytes,
                lane: str = "docs") -> Upload:
    """``lane`` is which thread pool the image work runs in — the caller's class of work,
    not the file's type. Community pictures used to resize in the ``docs`` pool and push
    back document indexing; the fix is for the caller to say who it is."""
    mime = _sniff(data, declared_mime(filename, mime))
    if mime not in ALLOWED:
        raise ValidationFailed("unsupported file type", code="unsupported_type")
    if mime.startswith("image/"):
        if len(data) > IMAGE_MAX:
            raise ValidationFailed("image too large", code="file_too_large")
        # 프로필·비서 그림은 투명을 지킨다(plan/63). 대화 첨부는 모델에 실을 크기가 먼저라 예전 그대로.
        data, mime = await pools.to_thread(lane, _resize_image, data, mime, 1568, kind == "avatar")  # PIL work off the event loop
    elif len(data) > DOC_MAX:
        raise ValidationFailed("file too large", code="file_too_large")
    # 맥에서 온 한글 이름은 자모가 풀린 꼴(NFD)이다. 그대로 두면 "회의록" 으로 찾아도 안 나온다.
    safe_name = unicodedata.normalize("NFC", os.path.basename(filename or "file").replace("\x00", ""))[:255] or "file"
    stem, dot, ext_ = safe_name.rpartition(".")
    if dot and mime == "image/jpeg" and ext_.lower() in ("heic", "heif", "png", "webp"):
        safe_name = f"{stem}.jpg"          # 받은 것과 담은 형식이 다르면 이름도 담은 것을 따른다
    up = Upload(owner_id=owner_id, kind=kind, filename=safe_name, mime=mime, size_bytes=len(data), storage_path="",
                sha256=hashlib.sha256(data).hexdigest(), created_at=datetime.now(UTC))
    db.add(up)
    await db.flush()
    ext = {"image/jpeg": ".jpg", "image/png": ".png", "image/webp": ".webp", "image/gif": ".gif", "application/pdf": ".pdf"}.get(mime, "")
    key = f"{owner_id}/{kind}/{up.id}{ext}"
    up.storage_path = await objectstore.put(key, data, mime,
                                            local_path=get_settings().upload_root / key)
    return up


#: 서명한 주소가 사는 시간. 대화 화면을 하루 종일 열어 두어도 그림이 깨지지 않을 만큼.
URL_TTL_MIN = 720


def signed_url(upload_id: uuid.UUID | str) -> str:
    """``<img>`` 가 열 수 있는 주소.

    그림 태그는 로그인 토큰을 실어 보내지 못한다. 그래서 주소 자체에 "이 파일을 봐도
    된다"는 서명을 붙인다. 서명은 이 파일 하나만 가리키고 스스로 만료된다 — 이 주소를
    받았다는 것은 그 파일을 볼 수 있는 사람이 건네받았다는 뜻이다.
    """
    from memora.core.security import sign_state

    return f"/api/uploads/{upload_id}/raw?t={sign_state({'up': str(upload_id)}, ttl_minutes=URL_TTL_MIN)}"


def with_urls(atts: list | None) -> list:
    """메시지에 담긴 첨부 목록(메타데이터만)에 지금 쓸 수 있는 주소를 붙인다.

    주소는 저장하지 않는다. 저장하면 서명이 만료된 뒤 영영 깨진 그림이 된다 — 읽을
    때마다 새로 서명한다."""
    out = []
    for a in atts or []:
        if not isinstance(a, dict):
            continue
        # 주소는 언제나 여기서 만든다. 요청에 실려 온 url 은 믿지 않는다.
        a = {k: v for k, v in a.items() if k not in ("data", "text", "url")}
        if a.get("upload_id"):
            a["url"] = signed_url(a["upload_id"])
        out.append(a)
    return out


async def read_bytes(u: Upload) -> bytes:
    """Wherever it was stored — a filesystem path from before S3, or an s3:// URI."""
    return await objectstore.get(u.storage_path)


def _load_attachment(u: Upload) -> dict:
    data = _read_sync(u.storage_path)
    item = {"upload_id": str(u.id), "filename": u.filename, "mime": u.mime, "size": u.size_bytes}
    if u.mime.startswith("image/"):
        item["data"] = base64.b64encode(data).decode()
    else:
        try:
            from memora.services.extract import extract
            item["text"] = extract(data, u.mime, u.filename).text[:20000]
        except Exception:
            item["text"] = ""
    return item


async def attachments_from_ids(db: AsyncSession, owner_id: uuid.UUID, ids: list[uuid.UUID]) -> list[dict]:
    if not ids:
        return []
    rows = (await db.execute(select(Upload).where(Upload.owner_id == owner_id, Upload.id.in_(ids)))).scalars().all()
    order = {str(i): n for n, i in enumerate(dict.fromkeys(ids))}
    rows = sorted(rows, key=lambda u: order.get(str(u.id), 0))          # 보낸 순서 그대로
    out = []
    for u in rows:
        try:
            out.append(await pools.to_thread("docs", _load_attachment, u))  # file read + text extraction off the loop
        except OSError:
            continue
    return out