"""Turning rows from several sources into one company each.

Two problems, and they are the whole of this module:

**Which row is which company.** The sources share no single identifier. The exchange knows
a ticker, the regulator a corp code, the tax office a registration number, and each has
only its own. So matching walks the keys it does have, strongest first, and falls back to
a normalised name — because "(주)카카오", "주식회사 카카오" and "카카오" are one company and
three strings.

**Who wins when they disagree.** Not last-write: each source is authoritative about
different things and merely well-informed about the rest. The exchange owns the ticker and
the market, the regulator owns the registration number and the address, the tax office owns
whether the company is still trading. And a value a person has corrected outranks all of
them — a collector that overwrites a human correction every night is worse than no
collector, because the correction stops being worth making.
"""
from __future__ import annotations

import re
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from blackmoa.core.logging import get_logger
from blackmoa.models import Company
from blackmoa.services.companies.taxonomy import industry_codes_for, region_code_for

log = get_logger("blackmoa.companies")

#: Which source is believed for which field. A source may only write a field it owns, or
#: one nobody owns (then first writer wins and later ones fill blanks).
OWNERS: dict[str, str] = {
    "stock_code": "krx", "market": "krx", "product": "krx", "listed_on": "krx",
    "corp_code": "dart", "biz_no": "dart", "address": "dart", "phone": "dart",
    "founded_on": "dart",
    "status": "nts",
    "employees": "nps",
}

_STRIP = re.compile(r"\(주\)|\(유\)|주식회사|유한회사|㈜|,|\.|\s+")


def normalise_name(name: str) -> str:
    return _STRIP.sub("", (name or "")).lower()


async def _find(db: AsyncSession, row: dict[str, Any]) -> Company | None:
    """The strongest identifier this row carries, then the name."""
    for key in ("corp_code", "biz_no", "stock_code"):
        if row.get(key):
            hit = (await db.execute(select(Company).where(getattr(Company, key) == row[key]))).scalar_one_or_none()
            if hit is not None:
                return hit
    norm = normalise_name(row.get("name") or "")
    if not norm:
        return None      # identifier-only row and no identifier matched: not ours to guess
    # A name match is only trusted when neither side claims a different hard identifier:
    # two unrelated companies can share a name, and the codes are what say they are not
    # the same one.
    cands = (await db.execute(select(Company).where(Company.name_norm == norm).limit(5))).scalars().all()
    for c in cands:
        clash = any(row.get(k) and getattr(c, k) and row[k] != getattr(c, k)
                    for k in ("corp_code", "biz_no", "stock_code"))
        if not clash:
            return c
    return None


def _may_write(company: Company | None, field: str, source: str) -> bool:
    if company is not None and field in (company.locked_fields or []):
        return False                                  # a person decided this one
    owner = OWNERS.get(field)
    if owner is None or owner == source:
        return True
    # Not the owner: allowed only to fill a blank the owner has not filled.
    current = getattr(company, field, None) if company is not None else None
    return current in (None, "", [], 0)


UNIQUE_KEYS = ("corp_code", "biz_no", "stock_code")


async def _held_elsewhere(db: AsyncSession, field: str, value: Any, company: Company) -> bool:
    col = getattr(Company, field)
    q = select(Company.id).where(col == value)
    if company.id is not None:
        q = q.where(Company.id != company.id)
    if (await db.execute(q.limit(1))).first() is not None:
        return True
    # Rows applied earlier in this same chunk are not flushed yet; the database cannot
    # see them, so look at the session too.
    return any(isinstance(o, Company) and o is not company and getattr(o, field, None) == value
               for o in list(db.new) + list(db.dirty))


async def apply_rows(db: AsyncSession, source: str, rows: list[dict[str, Any]]) -> dict[str, int]:
    """Merge a collector's rows. Returns what happened, for the run record."""
    created = updated = skipped = 0
    now = datetime.now(UTC).isoformat()
    for row in rows:
        name = (row.get("name") or "").strip()
        #: A source that only answers about identifiers it was given does not send a name —
        #: the tax office replies with a registration number and a status, nothing else. It
        #: may still update a company it can identify; it may never create one, because a
        #: row with no name is not a company we could show anybody.
        keyed = any(row.get(k) for k in ("corp_code", "biz_no", "stock_code"))
        if not name and not keyed:
            skipped += 1
            continue
        # Derived fields, so every source lands in the same taxonomy.
        if row.get("industry_text") and not row.get("industry_codes"):
            row["industry_codes"] = industry_codes_for(row["industry_text"])
        if row.get("region_text"):
            code, label = region_code_for(row["region_text"])
            row["region_code"], row["region_text"] = code, label

        company = await _find(db, row)
        if company is None and not name:
            skipped += 1          # nothing to update, and nothing we could create
            continue
        fresh = company is None
        # The region moves as a pair or not at all. The exchange lists forty-three
        # companies twice and the two rows differ only here — one spelling resolves to a
        # province and the other does not — so a row that cannot say where the company is
        # does not get to change where the company is. Field-by-field, the code was kept
        # and the label replaced, leaving the two disagreeing.
        if company is not None and not row.get("region_code") and company.region_code:
            row.pop("region_code", None)
            row.pop("region_text", None)
        if company is None:
            company = Company(name=name, name_norm=normalise_name(name), sources={})
            db.add(company)

        changed = False
        for field, value in row.items():
            if field in ("name",) or value in (None, "", []):
                continue
            if not hasattr(Company, field) or not _may_write(company, field, source):
                continue
            if getattr(company, field) != value:
                # The three identifiers are unique across the directory. A source that
                # assigns one already held by another company is wrong about one of them,
                # and the database saying so mid-run took the whole run down. Keep what we
                # have, note it, and let the rest of the row through.
                if field in UNIQUE_KEYS and await _held_elsewhere(db, field, value, company):
                    log.info("unique key already held by another company; kept", field=field, value=value,
                             company=company.name, source=source)
                    continue
                setattr(company, field, value)
                changed = True
        # The display name follows the source that owns identity, or fills a blank.
        if name and _may_write(company, "name", source) and (fresh or source == "dart") and company.name != name:
            company.name, company.name_norm = name, normalise_name(name)
            changed = True

        company.sources = {**(company.sources or {}), source: now}
        if fresh:
            created += 1
        elif changed:
            updated += 1
        else:
            skipped += 1
    return {"created": created, "updated": updated, "skipped": skipped}
