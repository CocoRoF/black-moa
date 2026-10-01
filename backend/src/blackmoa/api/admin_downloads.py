"""관리자 [다운로드 센터] (plan/64) — 앱 릴리스를 어디서 읽어 오는지, 옮겨 둔 설치본의 상태."""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Request
from pydantic import BaseModel, Field

from blackmoa.core.deps import DB, CurrentAdmin, client_ip
from blackmoa.core.errors import ValidationFailed
from blackmoa.core.redact import mask
from blackmoa.services import audit
from blackmoa.services import downloads as D
from blackmoa.services import jobs as J
from blackmoa.services import settings as S

router = APIRouter(prefix="/api/admin/downloads", tags=["admin"])


async def _out(db) -> dict[str, Any]:
    cfg = await D.config(db)
    rels = []
    for r, assets in await D.releases(db):
        rels.append({**D.release_out(r, assets),
                     "files": [{"name": a.name, "platform": a.platform, "arch": a.arch, "size": a.size, "status": a.status,
                                "error": a.error, "tries": a.tries, "downloads": a.downloads,
                                "mirrored_at": a.mirrored_at.isoformat() if a.mirrored_at else None} for a in assets]})
    own = str(await S.get(db, "downloads.github.token", use_cache=False) or "")
    return {"enabled": cfg["enabled"], "repo": cfg["repo"], "tag_prefix": cfg["prefix"],
            "token": {"has_value": bool(own), "masked": mask(own) if own else ""},
            # 릴리스를 굽는 CI 가 알려 오는가(열쇠가 있나), 지금 그 짧은 토큰으로 옮기는 중인가.
            "ci": {"has_key": bool(await S.get(db, "downloads.ci_key", use_cache=False)), "session": cfg["session"]},
            "status": dict(await S.get(db, "downloads.status", use_cache=False) or {}), "releases": rels}


@router.get("")
async def get_downloads(admin: CurrentAdmin, db: DB):
    return await _out(db)


class DownloadsIn(BaseModel):
    enabled: bool | None = None
    repo: str | None = Field(default=None, max_length=140, pattern=r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")
    tag_prefix: str | None = Field(default=None, max_length=40)
    #: 비워 보내면 그대로 둔다 — 지우려면 ``clear_token``.
    token: str | None = Field(default=None, max_length=400)
    clear_token: bool = False


@router.put("")
async def put_downloads(body: DownloadsIn, admin: CurrentAdmin, db: DB, request: Request):
    changed = []
    if body.repo is not None:
        await S.put(db, "downloads.github.repo", body.repo.strip(), updated_by=admin.id)
        changed.append("repo")
    if body.tag_prefix is not None:
        await S.put(db, "downloads.github.tag_prefix", body.tag_prefix.strip(), updated_by=admin.id)
        changed.append("tag_prefix")
    if body.token and body.token.strip():
        await S.put(db, "downloads.github.token", body.token.strip(), updated_by=admin.id)
        changed.append("token")
    if body.clear_token:
        await S.put(db, "downloads.github.token", "", updated_by=admin.id)
        changed.append("token")
    if body.enabled is not None:
        await S.put(db, "downloads.enabled", bool(body.enabled), updated_by=admin.id)
        changed.append("enabled")
    S.invalidate("downloads.")
    if changed:
        # 바꾸자마자 한 번 읽어 온다 — 바꿨는데 그대로면 안 된 줄 안다.
        await J.enqueue(db, "downloads.sync", {"force": True}, priority=3, dedupe_key="downloads.sync")
    audit.record(db, "downloads_settings", actor_id=admin.id, actor_kind="admin", ip=client_ip(request), meta={"keys": changed})
    await db.commit()
    return await _out(db)


@router.post("/check")
async def check_downloads(admin: CurrentAdmin, db: DB):
    cfg = await D.config(db)
    if not cfg["repo"]:
        raise ValidationFailed("enter the repository first", code="downloads_repo_missing")
    return await D.check(cfg["repo"], cfg["token"])


@router.post("/sync", status_code=202)
async def sync_downloads(admin: CurrentAdmin, db: DB):
    await J.enqueue(db, "downloads.sync", {"force": True}, priority=3, dedupe_key="downloads.sync")
    await db.commit()
    return {"queued": True}
