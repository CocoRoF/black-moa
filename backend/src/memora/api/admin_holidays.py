"""관리자 [연결 → 공휴일] (plan/60) — 한국천문연구원 특일 정보를 잇는다.

공휴일·대체공휴일·명절·절기는 이것 없이도 내장 계산으로 늘 나온다. 이으면 임시공휴일과 기념일 전부가
정부 발표대로 맞춰진다. 화면은 해마다 종류별로 어디서 온 자료인지, 내장 계산과 공식 출처가 쉬는 날을
다르게 본 날이 있는지 보여 준다 — 라이브러리 판이 늦었는지를 여기서 안다.
"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Request
from pydantic import BaseModel, Field

from memora.core.deps import DB, CurrentAdmin, client_ip
from memora.core.errors import ValidationFailed
from memora.core.redact import mask
from memora.services import audit
from memora.services import jobs as J
from memora.services import settings as S
from memora.services import special_days as SD

router = APIRouter(prefix="/api/admin/holidays", tags=["admin"])


async def _out(db) -> dict[str, Any]:
    key = str(await S.get(db, "holidays.kasi.key", use_cache=False) or "")
    return {"enabled": bool(await S.get(db, "holidays.kasi.enabled", use_cache=False)),
            "key": {"has_value": bool(key), "masked": mask(key) if key else ""},
            "dataset_url": SD.DATASET_URL, **await SD.status(db)}


@router.get("")
async def get_holidays(admin: CurrentAdmin, db: DB):
    return await _out(db)


class HolidaysIn(BaseModel):
    enabled: bool | None = None
    #: 비워 보내면 그대로 둔다 — 지우려면 ``clear_key``.
    key: str | None = Field(default=None, max_length=400)
    clear_key: bool = False


@router.put("")
async def put_holidays(body: HolidaysIn, admin: CurrentAdmin, db: DB, request: Request):
    changed = []
    if body.key and body.key.strip():
        await S.put(db, "holidays.kasi.key", body.key.strip(), updated_by=admin.id)
        changed.append("key")
    if body.clear_key:
        await S.put(db, "holidays.kasi.key", "", updated_by=admin.id)
        await S.put(db, "holidays.kasi.enabled", False, updated_by=admin.id)
        changed += ["key", "enabled"]
    if body.enabled is not None:
        if body.enabled and not str(await S.get(db, "holidays.kasi.key", use_cache=False) or ""):
            raise ValidationFailed("enter the service key first", code="holidays_key_missing")
        await S.put(db, "holidays.kasi.enabled", bool(body.enabled), updated_by=admin.id)
        changed.append("enabled")
        if body.enabled:
            # 켜자마자 한 번 받아 온다 — 켰는데 그대로면 안 된 줄 안다.
            await J.enqueue(db, "holidays.sync", {"force": True}, priority=3, dedupe_key="holidays.sync")
    S.invalidate("holidays.")
    audit.record(db, "holidays_settings", actor_id=admin.id, actor_kind="admin", ip=client_ip(request), meta={"keys": changed})
    await db.commit()
    return await _out(db)


@router.post("/check")
async def check_holidays(admin: CurrentAdmin, db: DB):
    """저장된 서비스 키로 이번 달 공휴일을 물어본다. 켜기 전에도 할 수 있다."""
    return await SD.check(str(await S.get(db, "holidays.kasi.key", use_cache=False) or ""))


@router.post("/sync", status_code=202)
async def sync_holidays(admin: CurrentAdmin, db: DB):
    if not str(await S.get(db, "holidays.kasi.key", use_cache=False) or ""):
        raise ValidationFailed("enter the service key first", code="holidays_key_missing")
    await J.enqueue(db, "holidays.sync", {"force": True}, priority=3, dedupe_key="holidays.sync")
    await db.commit()
    return {"queued": True}
