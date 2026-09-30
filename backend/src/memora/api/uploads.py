from __future__ import annotations

import uuid

from fastapi import APIRouter, File, Form, UploadFile
from fastapi.responses import Response

from memora.core.deps import DB, CurrentUser
from memora.core.errors import NotFound
from memora.core.security import verify_state
from memora.models import Upload
from memora.services import files as FILES
from memora.services import uploads as U

router = APIRouter(prefix="/api/uploads", tags=["uploads"])


@router.post("", status_code=201)
async def upload(user: CurrentUser, db: DB, file: UploadFile = File(...), kind: str = Form("attachment"),
                 lane: str = Form("docs")):
    data = await U.read_capped(file, max(U.IMAGE_MAX, U.DOC_MAX))
    if kind != "avatar":
        # 저장 공간은 계정에 하나다 (plan/55 §3-3). 가득 차면 받지 않는다 — 프로필 사진만은
        # 예외: 작고, 그것까지 막으면 가득 찬 사람은 제 얼굴도 못 바꾼다.
        await FILES.ensure_room(db, user, len(data))
    # room — 사람끼리 방에 건네는 파일(plan/55). 저장 공간의 [메신저] 칸으로 센다.
    up = await U.store(db, user.id, kind=kind if kind in ("attachment", "avatar", "room") else "attachment", filename=file.filename or "file",
                       mime=file.content_type or "", data=data,
                       # One endpoint serves several features, so the client declares which
                       # one it is. Anything unrecognised resizes in `docs`, as before.
                       lane=lane if lane in ("docs", "community") else "docs")
    if up.kind != "avatar":
        await FILES.maybe_warn(db, user)
    await db.commit()
    url = f"/api/public/uploads/{up.id}" if up.kind == "avatar" else U.signed_url(up.id)
    return {"upload_id": str(up.id), "url": url, "mime": up.mime, "size": up.size_bytes, "filename": up.filename}


async def _serve(up: Upload) -> Response:
    """저장소가 디스크든 S3 든 바이트를 읽어 그대로 내보낸다.

    예전에는 ``FileResponse(storage_path)`` 였다. 저장소를 S3 로 옮긴 뒤 ``storage_path`` 는
    ``s3://…`` 가 되었고, 그것을 파일 경로로 열려다 모든 요청이 500 이 되었다.

    그림과 PDF 만 화면 안에서 연다. 나머지는 내려받게 한다 — 사람이 올린 글 파일을
    이 도메인의 문서로 열어 주면 그 안의 무엇이든 우리 이름으로 실행된다.
    """
    data = await U.read_bytes(up)
    inline = up.mime.startswith("image/") or up.mime == "application/pdf"
    from urllib.parse import quote
    disp = f"{'inline' if inline else 'attachment'}; filename*=UTF-8''{quote(up.filename or 'file')}"
    headers = {"Content-Disposition": disp, "X-Content-Type-Options": "nosniff", "Cache-Control": "private, max-age=3600"}
    if up.mime != "application/pdf":
        # 올린 파일이 이 도메인에서 스크립트를 부르거나 무엇을 싣지 못하게 한다. PDF 는
        # 빼야 한다 — 브라우저의 PDF 보기가 sandbox 안에서는 뜨지 않는다.
        headers["Content-Security-Policy"] = "default-src 'none'; img-src 'self' data:; style-src 'unsafe-inline'; sandbox"
    return Response(data, media_type=up.mime, headers=headers)


@router.get("/{upload_id}/raw")
async def get_upload_signed(upload_id: uuid.UUID, db: DB, t: str = ""):
    """서명한 주소로 여는 파일 (``U.signed_url``). ``<img>``·새 탭·내려받기가 모두 이 길이다."""
    try:
        claim = verify_state(t)
    except Exception as e:  # noqa: BLE001
        raise NotFound("upload not found") from e
    if claim.get("up") != str(upload_id):
        raise NotFound("upload not found")
    up = await db.get(Upload, upload_id)
    if up is None or await FILES.upload_is_gone(db, upload_id):
        raise NotFound("upload not found")
    return await _serve(up)


@router.get("/{upload_id}")
async def get_upload(upload_id: uuid.UUID, user: CurrentUser, db: DB):
    up = await db.get(Upload, upload_id)
    if up is None or up.owner_id != user.id or await FILES.upload_is_gone(db, upload_id):
        raise NotFound("upload not found")
    return await _serve(up)
