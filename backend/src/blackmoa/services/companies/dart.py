"""The regulator's view: every filing company, and the details the exchange does not have.

Two collectors, because DART answers two different shapes of question:

  ``dart_codes``    one request returns a zip holding every company that files with DART —
                    about a hundred thousand, unlisted included — and the mapping from
                    ticker to corp code. That mapping is the join between the exchange's
                    world and this one.
  ``dart_company``  one request per company for the registration number, address, phone
                    and incorporation date. This is the expensive one.

The daily allowance is 20,000 calls and the directory alone is 2,800 listed companies, so
enrichment is budgeted and resumable: each run takes the companies whose details are
oldest or missing, and the next run continues from there. A collector that tries to do
everything in one pass spends the day's allowance and then fails for everyone else.
"""
from __future__ import annotations

import html
import io
import json
import re
import urllib.parse
import urllib.request
import zipfile
from datetime import date, datetime
from typing import Any

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from blackmoa.core.logging import get_logger
from blackmoa.core.pools import run_blocking

log = get_logger("blackmoa.companies.dart")

BASE = "https://opendart.fss.or.kr/api"
TIMEOUT_S = 60.0
#: A single company lookup answers in well under a second. One that has not answered in
#: twenty is not going to, and a hundred of those in a row is what turned a run into an
#: hour with nothing recorded.
COMPANY_TIMEOUT_S = 20.0
#: Calls per second. Measured at ~7.7/s with no throttling, but a directory-wide walk is
#: not urgent and being a good guest is cheaper than being blocked.
GAP_S = 0.08

#: Companies per chunk. One call each — there is no batch endpoint — so this is only how
#: often progress is written and the day's spend recorded, which is what makes a long run
#: watchable and a killed one honest about what it used.
BATCH = 100


class NeedsKey(RuntimeError):
    """No key configured. Not a failure of the collector — a thing an administrator has
    not done yet, and the admin screen says so rather than showing a stack."""


def _get_sync(url: str, timeout: float = TIMEOUT_S) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": "BlackMoaCompanyDirectory/1.0"})
    with urllib.request.urlopen(req, timeout=timeout) as r:  # noqa: S310 — a constant host
        return r.read()


def _url(path: str, **params: str) -> str:
    return f"{BASE}/{path}?" + urllib.parse.urlencode(params)


def _status_of(payload: bytes) -> tuple[str, str]:
    """DART reports failure in the body with HTTP 200, so the status is always read."""
    try:
        body = json.loads(payload)
        return str(body.get("status", "")), str(body.get("message", ""))
    except Exception:  # noqa: BLE001 — XML or a zip; those are checked by their own parsers
        m = re.search(rb"<status>(\d+)</status>.*?<message>(.*?)</message>", payload, re.S)
        return (m.group(1).decode(), m.group(2).decode("utf-8", "replace")) if m else ("", "")


def _raise_for_status(payload: bytes) -> None:
    """DART's own status codes. 010 and 011 are an unregistered and an unusable key — an
    administrator's job, not a failure; 020 is the daily allowance being gone."""
    status, message = _status_of(payload)
    if not status or status == "000":
        return
    if status in ("010", "011"):
        raise NeedsKey(f"DART {status}: {message}")
    raise RuntimeError(f"DART {status}: {message}")


def _date(text: str) -> date | None:
    t = (text or "").strip()
    try:
        return datetime.strptime(t, "%Y%m%d").date()
    except ValueError:
        return None


# ── the corp-code dictionary ─────────────────────────────────────────

SOURCE_CODES = "dart_codes"


def parse_codes(payload: bytes) -> list[dict[str, Any]]:
    """The zip holds one XML file listing every filing company."""
    with zipfile.ZipFile(io.BytesIO(payload)) as z:
        name = next(n for n in z.namelist() if n.lower().endswith(".xml"))
        xml = z.read(name).decode("utf-8", "replace")
    rows: list[dict[str, Any]] = []
    for block in re.findall(r"<list>(.*?)</list>", xml, re.S):
        def field(tag: str, b: str = block) -> str:
            m = re.search(rf"<{tag}>(.*?)</{tag}>", b, re.S)
            # The file is XML read with a regex, so "삼성E&amp;A" arrives as written. The
            # entity has to be undone here: it was reaching the screen as the company's name.
            return html.unescape(m.group(1) or "").strip() if m else ""

        name_, corp = field("corp_name"), field("corp_code")
        if not name_ or not corp:
            continue
        row: dict[str, Any] = {"name": name_, "corp_code": corp}
        stock = field("stock_code")
        if stock and stock.strip():
            row["stock_code"] = stock.strip().zfill(6)
        rows.append(row)
    return rows


async def fetch_codes(key: str) -> list[dict[str, Any]]:
    if not key:
        raise NeedsKey("DART 키가 없어요")
    payload = await run_blocking("crawl", lambda: _get_sync(_url("corpCode.xml", crtfc_key=key)),
                                 label="dart:corpCode", timeout_s=TIMEOUT_S + 10)
    if not payload.startswith(b"PK"):          # a zip, or an error document pretending to be one
        _raise_for_status(payload)
        raise RuntimeError("DART returned something that is not a zip")
    rows = parse_codes(payload)
    log.info("fetched the DART corp-code dictionary", rows=len(rows),
             listed=sum(1 for r in rows if r.get("stock_code")))
    return rows


# ── per-company details ──────────────────────────────────────────────

SOURCE_COMPANY = "dart"


def parse_company(payload: bytes) -> dict[str, Any]:
    body = json.loads(payload)
    if str(body.get("status")) != "000":
        return {}
    out: dict[str, Any] = {}
    if body.get("corp_name"):
        out["name"] = body["corp_name"].strip()
    for src, dst in (("bizr_no", "biz_no"), ("adres", "address"), ("phn_no", "phone")):
        if body.get(src):
            out[dst] = str(body[src]).strip()
    if out.get("biz_no"):
        # Ten digits or nothing. DART hands back placeholders ("11940") for some unlisted
        # filers; truncating those to whatever was there made several companies share one
        # "number", and the unique index then failed the whole run.
        digits = re.sub(r"\D", "", out["biz_no"])
        out["biz_no"] = digits if len(digits) == 10 else None
    founded = _date(str(body.get("est_dt") or ""))
    if founded:
        out["founded_on"] = founded
    return out


async def fetch_company(key: str, corp_code: str) -> dict[str, Any]:
    payload = await run_blocking("crawl", lambda: _get_sync(_url("company.json", crtfc_key=key, corp_code=corp_code), timeout=COMPANY_TIMEOUT_S),
                                 label=f"dart:company:{corp_code}", timeout_s=COMPANY_TIMEOUT_S + 5)
    status, message = _status_of(payload)
    if status in ("010", "011"):
        raise NeedsKey(f"DART {status}: {message}")
    if status == "020":
        raise RuntimeError(f"DART {status}: {message}")     # the day's allowance is gone
    return parse_company(payload)


async def due_for_details(db: AsyncSession, limit: int) -> list[tuple[str, str]]:
    """(corp_code, id) for the companies worth spending the next calls on.

    The dictionary holds about 119,000 companies and enrichment costs one call each, so at
    a realistic budget the whole set takes weeks. Order therefore decides whether the
    feature is useful tomorrow or in two months:

      1. companies a job posting actually points at — someone is reading these today
      2. listed companies — the ones a reader is most likely to look up
      3. everything else, oldest first, so the queue drains evenly

    Resumable by construction: each run takes the next slice and the following run
    continues from there.
    """
    from blackmoa.models import CommunityJob, Company

    linked = select(CommunityJob.company_id).where(CommunityJob.company_id.is_not(None))
    rows = (await db.execute(
        select(Company.id, Company.corp_code)
        .where(Company.corp_code.is_not(None))
        .where(or_(Company.biz_no.is_(None), Company.address == ""))
        .order_by(
            Company.id.notin_(linked),          # False sorts first: linked companies lead
            # `market` is set by the exchange and means *currently* listed. A stock code is
            # not the same test: the regulator's dictionary keeps one for every company that
            # ever listed, so ranking by it spent the first hundred calls on long-dissolved
            # shells — 95 of which the tax office then reported closed.
            Company.market == "",
            Company.stock_code.is_(None),
            Company.updated_at.asc(),
        )
        .limit(limit)
    )).all()
    return [(r.corp_code, str(r.id)) for r in rows]
