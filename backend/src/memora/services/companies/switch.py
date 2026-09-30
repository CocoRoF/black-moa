"""기업 기능을 이 서비스에서 쓰는가 (plan/71).

관리자가 [기업정보]에서 끈다. 끄면 기업 페이지·리뷰·공고의 기업 연결·회사 이메일 인증이 닫히고, 프로필의 소속과
인증된 회사는 어디에도 나가지 않는다 — 프로필 페이지, 프로필 카드, 공개 페이지, 광장의 글쓴이 줄, 비서의 지시문.
[내 정보]에서도 새로 넣을 수 없다. 저장된 것은 지우지 않는다: 다시 켜면 그대로 돌아온다.

화면만 감추면 옛 앱이나 직접 부른 요청이 계속 쓰고, 다른 사람의 프로필 응답에 소속이 실려 나간다 — 그래서 서버가
막고 걸러 낸다.
"""
from __future__ import annotations

from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from memora.core.deps import DB
from memora.core.errors import Forbidden
from memora.services import settings as S

#: 기업 기능이 프로필에 둔 칸: 적어 넣은 소속과, 회사 이메일로 인증한 회사.
PROFILE_FIELDS = frozenset({"company", "company_id", "company_verified_at", "company_domain"})


async def enabled(db: AsyncSession) -> bool:
    return bool(await S.get(db, "companies.enabled"))


async def require(db: AsyncSession) -> None:
    if not await enabled(db):
        raise Forbidden("companies disabled", code="companies_disabled")


def strip(data: dict[str, Any] | None) -> dict[str, Any]:
    """기업 칸을 뺀 사본. 원본(저장된 것)은 건드리지 않는다."""
    return {k: v for k, v in (data or {}).items() if k not in PROFILE_FIELDS}


async def gate(db: DB) -> None:
    """라우터 전체에 거는 문: 기업 페이지와 회사 인증의 모든 요청이 이것을 먼저 지난다."""
    await require(db)
