"""The exchange's own list of listed companies (plan/33 §0).

The one source that needs no registration: a single request returns every company listed
in Korea — 2,802 of them when this was written — with industry, region, CEO, homepage and
market. That is what lets the feature work before anyone has signed up for an API key.

Two things about it are peculiar and both are load-bearing:

  * It is served as ``application/vnd.ms-excel`` and is not Excel. It is an HTML table,
    encoded EUC-KR. Handing it to a spreadsheet reader fails; parsing it as the HTML it
    actually is works.
  * It answers a browser, so it is asked like one.
"""
from __future__ import annotations

import html
import re
from datetime import date, datetime
from typing import Any

from memora.core.logging import get_logger

log = get_logger("memora.companies.krx")

SOURCE = "krx"
URL = "https://kind.krx.co.kr/corpgeneral/corpList.do?method=download&searchType=13"
TIMEOUT_S = 60.0

#: Sanity floor. The exchange occasionally answers with a login page or an empty table, and
#: a "successful" run that wipes the directory down to nine companies is worse than a
#: failed one. Well below the real count (~2,800), well above anything broken.
MIN_ROWS = 500

_MARKETS = {"유가": "유가", "코스닥": "코스닥", "코넥스": "코넥스", "유가증권": "유가"}


def _cells(row_html: str) -> list[str]:
    return [html.unescape(re.sub(r"<[^>]+>", "", c)).strip()
            for c in re.findall(r"<t[dh][^>]*>(.*?)</t[dh]>", row_html, re.S)]


def _date(text: str) -> date | None:
    t = (text or "").strip().replace("/", "-")
    for fmt in ("%Y-%m-%d", "%Y.%m.%d", "%Y%m%d"):
        try:
            return datetime.strptime(t, fmt).date()
        except ValueError:
            continue
    return None


def parse(payload: bytes) -> list[dict[str, Any]]:
    """Rows from the exchange's table. Pure, so the parser is testable without the network."""
    text = payload.decode("euc-kr", "replace")
    rows = re.findall(r"<tr[^>]*>(.*?)</tr>", text, re.S)
    if not rows:
        return []
    header = _cells(rows[0])
    idx = {name: i for i, name in enumerate(header)}
    need = ("회사명", "종목코드")
    if not all(k in idx for k in need):
        raise ValueError(f"unexpected columns from the exchange: {header[:12]}")

    def at(cells: list[str], key: str) -> str:
        i = idx.get(key)
        return cells[i].strip() if i is not None and i < len(cells) else ""

    out: list[dict[str, Any]] = []
    for r in rows[1:]:
        c = _cells(r)
        if len(c) < len(header):
            continue
        name = at(c, "회사명")
        code = at(c, "종목코드")
        if not name or not code:
            continue
        out.append({
            "name": name,
            # Six characters, and the leading zeros matter: "005930" is Samsung and 5930 is
            # nothing. The source gives it as text; keep it that way.
            "stock_code": code.zfill(6),
            "market": _MARKETS.get(at(c, "시장구분"), at(c, "시장구분")),
            "industry_text": at(c, "업종"),
            "product": at(c, "주요제품"),
            "listed_on": _date(at(c, "상장일")),
            "fiscal_month": at(c, "결산월"),
            "ceo": at(c, "대표자명"),
            "homepage": at(c, "홈페이지"),
            "region_text": at(c, "지역"),
        })
    return out


def _get_sync(url: str, timeout: float) -> bytes:
    """Blocking fetch, run in the ``crawl`` pool by the caller."""
    import urllib.request

    req = urllib.request.Request(url, headers={
        # The exchange answers a browser; without this it serves a page instead of the table.
        "User-Agent": "Mozilla/5.0 (compatible; MemoraCompanyDirectory/1.0)",
        "Accept": "*/*",
    })
    with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310 — a constant URL
        return resp.read()


async def fetch() -> list[dict[str, Any]]:
    """Every listed company, once. Off the event loop: this is someone else's server."""
    from memora.core.pools import run_blocking

    payload = await run_blocking("crawl", lambda: _get_sync(URL, TIMEOUT_S), label="krx:corpList",
                                 timeout_s=TIMEOUT_S + 10)
    rows = parse(payload)
    if len(rows) < MIN_ROWS:
        raise ValueError(f"the exchange returned only {len(rows)} companies (expected at least {MIN_ROWS})")
    log.info("fetched the listed-company list", rows=len(rows), bytes=len(payload))
    return rows
