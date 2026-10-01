"""Google Drive 와 [파일] (plan/75) — drive.file 하나로: 고른 파일 가져오기, [파일]의 파일을 Drive 에 저장하기."""
from __future__ import annotations

import uuid

from fastapi import APIRouter
from pydantic import BaseModel, Field

from blackmoa.core.deps import DB, CurrentUser
from blackmoa.core.ratelimit import limiter
from blackmoa.services import gdrive as GD

router = APIRouter(prefix="/api/drive", tags=["drive"])


@router.get("/status")
async def drive_status(user: CurrentUser, db: DB):
    return await GD.status(db, user.id)


@router.get("/picker")
async def drive_picker(user: CurrentUser, db: DB):
    """파일 선택 창을 여는 데 필요한 것 — 이 사람의 접근 토큰과 앱의 브라우저 키."""
    out = await GD.picker(db, user)
    await db.commit()     # 토큰을 갱신했으면 남긴다
    return out


class ImportIn(BaseModel):
    #: 예전 화면이 보내던 값 — 받지만 쓰지 않는다. 파일은 [내 정보 → 파일]로 간다 (plan/77).
    agent_id: uuid.UUID | None = None
    file_ids: list[str] = Field(min_length=1, max_length=GD.MAX_FILES)


@router.post("/import")
async def drive_import(body: ImportIn, user: CurrentUser, db: DB):
    limiter.check(f"drive:{user.id}", 30, 600)
    out = await GD.import_files(db, user, file_ids=body.file_ids)
    await db.commit()
    return out


class SaveIn(BaseModel):
    file_id: uuid.UUID


@router.post("/save")
async def drive_save(body: SaveIn, user: CurrentUser, db: DB):
    limiter.check(f"drive:{user.id}", 30, 600)
    out = await GD.save_file(db, user, body.file_id)
    await db.commit()
    return out
