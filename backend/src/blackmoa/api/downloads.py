"""다운로드 센터 (plan/64): 앱 설치본의 목록과 내려받기."""
from __future__ import annotations

import hmac
import re
import uuid
from urllib.parse import quote

from fastapi import APIRouter, Request
from fastapi.responses import Response, StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy import update

from blackmoa.core.deps import DB, CurrentUser
from blackmoa.core.errors import Forbidden, NotFound
from blackmoa.models import AppRelease, AppReleaseAsset
from blackmoa.services import downloads as D
from blackmoa.services import jobs as J
from blackmoa.services import settings as S

router = APIRouter(prefix="/api/downloads", tags=["downloads"])


@router.get("")
async def list_downloads(user: CurrentUser, db: DB):
    return await D.listing(db)


_RANGE = re.compile(r"^bytes=(\d*)-(\d*)$")


@router.get("/assets/{asset_id}")
async def get_asset(asset_id: uuid.UUID, t: str, request: Request, db: DB):
    """서명된 주소로만 받는다(브라우저의 링크는 로그인 토큰을 싣지 못한다). 이어받기를 받는다."""
    if not D.allowed(asset_id, t):
        raise Forbidden("link expired", code="link_expired")
    a = await db.get(AppReleaseAsset, asset_id)
    rel = await db.get(AppRelease, a.release_id) if a else None
    if a is None or rel is None or rel.gone or a.status != "ready" or not a.storage_path:
        raise NotFound("not found", code="not_found")
    size = int(a.size or 0)
    start, end, status = 0, size - 1, 200
    m = _RANGE.match(request.headers.get("range", "").strip())
    if m and size:
        s, e = m.group(1), m.group(2)
        if s:
            start, end = int(s), (int(e) if e else size - 1)
        elif e:
            start, end = max(0, size - int(e)), size - 1
        end = min(end, size - 1)
        if start > end or start >= size:
            return Response(status_code=416, headers={"Content-Range": f"bytes */{size}"})
        status = 206
    if start == 0:
        # 처음부터 받는 것만 센다(이어받기는 같은 한 번이다).
        await db.execute(update(AppReleaseAsset).where(AppReleaseAsset.id == a.id).values(downloads=AppReleaseAsset.downloads + 1))
        await db.commit()
    headers = {
        "Content-Disposition": f"attachment; filename*=UTF-8''{quote(a.name)}",
        "Content-Length": str(end - start + 1),
        "Accept-Ranges": "bytes",
        "Cache-Control": "private, no-store",
        "X-Content-Type-Options": "nosniff",
    }
    if a.sha256:
        headers["X-Checksum-Sha256"] = a.sha256
    if status == 206:
        headers["Content-Range"] = f"bytes {start}-{end}/{size}"
    return StreamingResponse(D.stream(a.storage_path, start, end), status_code=status,
                             media_type="application/octet-stream", headers=headers)


# ── 릴리스를 굽는 CI 가 부르는 곳 ─────────────────────────────────────────────


async def _ci_allowed(request: Request, db) -> None:
    key = str(await S.get(db, "downloads.ci_key", use_cache=False) or "")
    got = request.headers.get("authorization", "").removeprefix("Bearer ").strip()
    if not key or not got or not hmac.compare_digest(key, got):
        raise Forbidden("not allowed", code="forbidden")


class CiIn(BaseModel):
    #: 그 잡의 GITHUB_TOKEN — 이 저장소 읽기만 되고 잡이 끝나면 무효가 된다.
    github_token: str = Field(min_length=20, max_length=400)
    tag: str = Field(default="", max_length=64)


@router.post("/ci", status_code=202)
async def ci_release(body: CiIn, request: Request, db: DB):
    """릴리스가 나갔다. 건넨 토큰으로 곧바로 읽어 와 옮긴다."""
    await _ci_allowed(request, db)
    await D.accept_session(db, body.github_token)
    await J.enqueue(db, "downloads.sync", {"force": True}, priority=2, dedupe_key="downloads.sync")
    await db.commit()
    return {"queued": True}


@router.get("/ci")
async def ci_status(request: Request, db: DB, tag: str = ""):
    await _ci_allowed(request, db)
    return await D.ci_state(db, tag[:64])
