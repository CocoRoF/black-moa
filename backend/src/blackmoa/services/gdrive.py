"""Google Drive 와 [파일] (plan/75).

권한은 **drive.file** 하나다 — 사용자가 Google 의 파일 선택 창(Picker)에서 고른 파일과, 이 앱이 만든 파일만 다룬다.
Drive 전체를 보는 권한(drive, drive.readonly, drive.metadata…)은 Google 이 "제한 범위"로 두어 매년 유료 보안
평가를 요구하고, drive.file 은 "민감하지 않은 범위"다. Google 이 권하는 방식이기도 하다.

- **가져오기**: Picker 에서 고른 파일을 비서의 [파일]로. Google 문서·시트·슬라이드는 Word·Excel·PowerPoint 로 바꿔
  받는다(그래야 비서가 읽는다). 한 번에 10개, 한 파일 25MB 까지. 저장 공간 한도를 따른다.
- **저장하기**: [파일]의 파일을 사용자의 Drive "black-moa" 폴더에 올린다(폴더는 이 앱이 만든다). 지우지 않는다.
- Picker 는 브라우저에서 돈다 — 사용자의 접근 토큰(이 사람 자신의 것)과 관리자가 넣은 브라우저용 API 키·프로젝트
  번호를 건넨다.
"""
from __future__ import annotations

import json
import uuid
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from blackmoa.core.errors import Conflict, NotFound, ValidationFailed
from blackmoa.models import Connection, User
from blackmoa.providers.http import ProviderHTTPError, request
from blackmoa.services import connections as CN
from blackmoa.services import settings as S

CAPABILITY = "drive"
API = "https://www.googleapis.com/drive/v3/files"
UPLOAD = "https://www.googleapis.com/upload/drive/v3/files"
FOLDER = "black-moa"
FOLDER_MIME = "application/vnd.google-apps.folder"
MAX_FILES = 10
MAX_BYTES = 25 * 1024 * 1024
#: Google 형식 → 비서가 읽는 형식
EXPORTS = {
    "application/vnd.google-apps.document": ("application/vnd.openxmlformats-officedocument.wordprocessingml.document", ".docx"),
    "application/vnd.google-apps.spreadsheet": ("application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", ".xlsx"),
    "application/vnd.google-apps.presentation": ("application/vnd.openxmlformats-officedocument.presentationml.presentation", ".pptx"),
    "application/vnd.google-apps.drawing": ("application/pdf", ".pdf"),
}


async def _connection(db: AsyncSession, owner_id: uuid.UUID) -> Connection:
    conn = await CN.get(db, owner_id, "google")
    if conn is None or conn.status != "active" or CAPABILITY not in (conn.capabilities or []):
        raise ValidationFailed("Google Drive is not connected", code="drive_not_connected")
    return conn


async def status(db: AsyncSession, owner_id: uuid.UUID) -> dict[str, Any]:
    """[파일] 화면이 Drive 단추를 어떻게 보일지: 쓸 수 있는가, 연결했는가."""
    from blackmoa.services import oauth as OA
    g = OA.PROVIDERS.get("google")
    offered = CAPABILITY in (await g.offered(db) if g else [])
    conn = await CN.get(db, owner_id, "google")
    connected = bool(conn and conn.status == "active" and CAPABILITY in (conn.capabilities or []))
    picker = bool(str(await S.get(db, "oauth.google.picker_api_key") or "").strip())
    return {"available": offered, "connected": connected, "picker": picker}


async def picker(db: AsyncSession, owner: User) -> dict[str, Any]:
    """Picker 를 여는 데 필요한 것 — 이 사람의 접근 토큰과 앱의 브라우저 키·프로젝트 번호."""
    conn = await _connection(db, owner.id)
    key = str(await S.get(db, "oauth.google.picker_api_key") or "").strip()
    if not key:
        raise ValidationFailed("the file picker is not set up", code="drive_picker_unconfigured")
    token = await CN.access_token(db, conn)
    return {"access_token": token, "api_key": key, "app_id": str(await S.get(db, "oauth.google.app_id") or "").strip()}


def _auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


async def _download(token: str, file_id: str) -> tuple[str, str, bytes]:
    """(이름, 형식, 바이트). Google 형식은 읽을 수 있는 형식으로 바꿔 받는다."""
    meta = (await request("GET", f"{API}/{file_id}", headers=_auth(token),
                          params={"fields": "id,name,mimeType,size", "supportsAllDrives": "true"}, retries=2)).json()
    name, mime = str(meta.get("name") or "file"), str(meta.get("mimeType") or "application/octet-stream")
    if mime == FOLDER_MIME:
        raise ValidationFailed("folders cannot be imported", code="drive_folder")
    if mime in EXPORTS:
        out_mime, ext = EXPORTS[mime]
        r = await request("GET", f"{API}/{file_id}/export", headers=_auth(token), params={"mimeType": out_mime}, retries=2)
        return (name if name.lower().endswith(ext) else name + ext), out_mime, r.content
    if mime.startswith("application/vnd.google-apps."):
        raise ValidationFailed("this Google file type cannot be imported", code="drive_unsupported")
    if int(meta.get("size") or 0) > MAX_BYTES:
        raise ValidationFailed("file too large", code="file_too_large")
    r = await request("GET", f"{API}/{file_id}", headers=_auth(token), params={"alt": "media", "supportsAllDrives": "true"}, retries=2)
    if len(r.content) > MAX_BYTES:
        raise ValidationFailed("file too large", code="file_too_large")
    return name, mime, r.content


async def import_files(db: AsyncSession, owner: User, *, file_ids: list[str]) -> dict[str, Any]:
    """Picker 에서 고른 파일을 [내 정보 → 파일]로 (plan/77). 파일은 계정의 것이다 — 어느 비서에게 넣지 않는다.
    비서는 나와의 대화에서 내 파일을 모두 보고, 외부인에게 쓸 것은 비서마다 [지식] 탭에서 잇는다.
    파일마다 되거나 안 된 까닭을 돌려준다."""
    from blackmoa.services import files as FILES
    from blackmoa.services import uploads as U

    ids = [i for i in dict.fromkeys(str(x).strip() for x in file_ids) if i][:MAX_FILES]
    if not ids:
        raise ValidationFailed("choose files", code="drive_nothing_chosen")
    conn = await _connection(db, owner.id)
    token = await CN.access_token(db, conn)
    done: list[dict[str, Any]] = []
    failed: list[dict[str, Any]] = []
    for fid in ids:
        try:
            name, mime, data = await _download(token, fid)
            await FILES.ensure_room(db, owner, len(data))
            up = await U.store(db, owner.id, kind="attachment", filename=name, mime=mime, data=data, lane="docs")
            f = await FILES.record(db, agent_id=None, upload=up, source="drive")
            done.append({"id": str(f.id), "name": f.filename})
        except (ValidationFailed, Conflict) as e:   # 형식·크기·저장 공간 — 이 파일만 건너뛴다
            failed.append({"drive_id": fid, "code": e.code})
        except ProviderHTTPError as e:
            failed.append({"drive_id": fid, "code": "drive_not_found" if e.status in (403, 404) else "drive_failed"})
    await FILES.maybe_warn(db, owner)
    return {"imported": done, "failed": failed}


async def _folder(token: str) -> str:
    """사용자의 Drive 에서 이 앱이 만든 "black-moa" 폴더. 없으면 만든다(drive.file 은 이 앱이 만든 것만 보인다)."""
    q = f"name = '{FOLDER}' and mimeType = '{FOLDER_MIME}' and trashed = false"
    got = (await request("GET", API, headers=_auth(token), params={"q": q, "fields": "files(id)", "pageSize": "1"}, retries=2)).json()
    if got.get("files"):
        return str(got["files"][0]["id"])
    made = (await request("POST", API, headers=_auth(token), params={"fields": "id"},
                          json={"name": FOLDER, "mimeType": FOLDER_MIME}, retries=2)).json()
    return str(made["id"])


async def save_file(db: AsyncSession, owner: User, file_id: uuid.UUID) -> dict[str, Any]:
    """[파일]의 파일 하나를 사용자의 Drive "black-moa" 폴더에 올린다. 올린 파일의 주소를 돌려준다."""
    from blackmoa.models import Upload
    from blackmoa.services import files as FILES
    from blackmoa.services import uploads as U

    f = await FILES.get_owned(db, owner.id, file_id)
    up = await db.get(Upload, f.upload_id)
    if up is None:
        raise NotFound("file not found", code="file_not_found")
    data = await U.read_bytes(up)
    conn = await _connection(db, owner.id)
    token = await CN.access_token(db, conn)
    folder = await _folder(token)
    meta = json.dumps({"name": f.filename, "parents": [folder]}).encode()
    boundary = f"blackmoa{uuid.uuid4().hex}"
    body = (f"--{boundary}\r\nContent-Type: application/json; charset=UTF-8\r\n\r\n".encode() + meta +
            f"\r\n--{boundary}\r\nContent-Type: {f.mime or 'application/octet-stream'}\r\n\r\n".encode() + data +
            f"\r\n--{boundary}--\r\n".encode())
    r = await request("POST", UPLOAD, headers={**_auth(token), "Content-Type": f"multipart/related; boundary={boundary}"},
                      params={"uploadType": "multipart", "fields": "id,name,webViewLink"}, content=body, retries=2)
    out = r.json()
    return {"id": out.get("id", ""), "name": out.get("name", f.filename), "link": out.get("webViewLink", "")}
