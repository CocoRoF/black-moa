"""음성을 이 서비스에서 쓰는가 (plan/67) — 받아쓰기(STT)와 읽어 주기(TTS), 둘을 따로.

관리자가 [음성]에서 끈다. 끄면 웹과 PC 앱이 관련 단추와 설정을 감추고, 서버는 그 요청을 받지 않는다. 화면만
감추면 옛 앱이나 직접 부른 요청이 계속 공급자를 부르고 크레딧을 쓴다.
"""
from __future__ import annotations

from typing import Literal

from sqlalchemy.ext.asyncio import AsyncSession

from memora.core.errors import Forbidden
from memora.services import settings as S

Kind = Literal["stt", "tts"]


async def availability(db: AsyncSession) -> dict[str, bool]:
    return {"stt": bool(await S.get(db, "stt.enabled")), "tts": bool(await S.get(db, "tts.enabled"))}


async def require(db: AsyncSession, kind: Kind) -> None:
    if not await S.get(db, f"{kind}.enabled"):
        raise Forbidden(f"{kind} disabled", code=f"{kind}_disabled")
