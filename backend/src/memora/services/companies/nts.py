"""The tax office: whether a company is still trading.

The only authoritative answer to "is this business still open", and the one field no other
source has. It is asked in batches of a hundred registration numbers, which is what the
service accepts and also what keeps a directory-wide check to a couple of dozen calls.

A company the tax office reports as closed is not deleted. A job posting from last year
still refers to it, and "this company has closed" is more useful to a reader than a
company that has silently vanished from the directory.
"""
from __future__ import annotations

import json
import urllib.parse
import urllib.request
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from memora.core.logging import get_logger
from memora.core.pools import run_blocking
from memora.services.companies.dart import NeedsKey

log = get_logger("memora.companies.nts")

SOURCE = "nts"
URL = "https://api.odcloud.kr/api/nts-businessman/v1/status"
BATCH = 100
TIMEOUT_S = 30.0

#: The service answers in words. "계속사업자" is trading, "휴업자" is dormant, "폐업자" has
#: closed, and an unregistered number comes back with an empty state.
_STATE = {"계속사업자": "active", "휴업자": "suspended", "폐업자": "closed"}


def normalise_key(key: str) -> str:
    """The portal shows this key percent-encoded, so that is what gets pasted.

    data.go.kr displays the 일반 인증키 already encoded (`%2B` for `+`, `%3D` for `=`) and
    its own note tells you to try it both ways. Encoding it again turns `%2B` into `%252B`
    and the service answers 401 "등록되지 않은 인증키" — measured, not guessed. Base64 keys
    contain no literal `%`, so a `%` here can only mean it arrived encoded.
    """
    k = (key or "").strip()
    return urllib.parse.unquote(k) if "%" in k else k


def _post_sync(key: str, numbers: list[str]) -> bytes:
    body = json.dumps({"b_no": numbers}).encode()
    req = urllib.request.Request(
        f"{URL}?{urllib.parse.urlencode({'serviceKey': normalise_key(key)})}", data=body, method="POST",
        headers={"Content-Type": "application/json", "Accept": "application/json",
                 "User-Agent": "MemoraCompanyDirectory/1.0"})
    with urllib.request.urlopen(req, timeout=TIMEOUT_S) as r:  # noqa: S310 — a constant host
        return r.read()


def parse(payload: bytes) -> list[dict[str, Any]]:
    """Registration number → status. Pure, so the mapping is testable without a key."""
    body = json.loads(payload)
    if body.get("status_code") not in (None, "OK") and body.get("code") is not None:
        raise NeedsKey(f"국세청: {body.get('msg') or body.get('code')}")
    out: list[dict[str, Any]] = []
    for item in body.get("data") or []:
        b_no = str(item.get("b_no") or "").strip()
        if not b_no:
            continue
        state = _STATE.get(str(item.get("b_stt") or "").strip(), "unknown")
        out.append({"biz_no": b_no, "status": state})
    return out


async def check(key: str, numbers: list[str]) -> list[dict[str, Any]]:
    if not key:
        raise NeedsKey("공공데이터포털 키가 없어요")
    payload = await run_blocking("crawl", lambda: _post_sync(key, numbers),
                                 label=f"nts:status:{len(numbers)}", timeout_s=TIMEOUT_S + 10)
    return parse(payload)


async def due_for_check(db: AsyncSession, limit: int) -> list[str]:
    """Registration numbers whose status is unknown or oldest-checked first."""
    from memora.models import Company

    rows = (await db.execute(
        select(Company.biz_no).where(Company.biz_no.is_not(None))
        # `status != 'unknown'` is false for the ones we have never asked about, and false
        # sorts first — so the unknown ones lead. Written the other way round it asked about
        # companies whose status was already known and never reached the rest: 2,000 calls
        # returning 17 changes, then 2,000 returning none.
        .order_by(Company.status != "unknown", Company.updated_at.asc()).limit(limit)
    )).scalars().all()
    return [r for r in rows if r]
