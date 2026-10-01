"""한 해치 달력 (plan/60): 한국의 공휴일·명절·절기·기념일과 날마다의 음력.

누구의 것도 아닌 공공의 달력이라 로그인 없이 준다. 한 해는 한번 정해지면 거의 바뀌지 않으므로 브라우저는
받아 두고 다시 쓰며(ETag 로 확인만 — 바뀌지 않았으면 304), 스케줄 화면은 사용자 일정만 불러온다.
"""
from __future__ import annotations

from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Request, Response
from fastapi.responses import JSONResponse

from blackmoa.core.deps import DB
from blackmoa.core.errors import NotFound
from blackmoa.services import special_days as SD

router = APIRouter(prefix="/api/calendar", tags=["calendar"])


def _cache(year: int) -> str:
    this = (datetime.now(UTC) + timedelta(hours=9)).year
    if year < this:
        # 지난해는 더 바뀔 일이 없다.
        return "public, max-age=604800, stale-while-revalidate=2592000"
    # 올해·내년은 임시공휴일이 새로 정해질 수 있다 — 한 시간마다 확인(바뀌지 않았으면 304).
    return "public, max-age=3600, stale-while-revalidate=86400"


def _matches(header: str | None, etag: str) -> bool:
    if not header:
        return False
    tags = [t.strip().removeprefix("W/") for t in header.split(",")]
    return "*" in tags or etag in tags


@router.get("/{country}/{year}")
async def year(country: str, year: int, request: Request, db: DB):
    if country != SD.COUNTRY or not (SD.YEAR_MIN <= year <= SD.YEAR_MAX):
        raise NotFound("no calendar for that year", code="calendar_year_unavailable")
    y = await SD.year_of(db, year)
    etag = f'"{y.version}"'
    headers = {"ETag": etag, "Cache-Control": _cache(year), "Vary": "Accept-Encoding"}
    if _matches(request.headers.get("if-none-match"), etag):
        return Response(status_code=304, headers=headers)
    return JSONResponse(await SD.payload(db, year), headers=headers)
