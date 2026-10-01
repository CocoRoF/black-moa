"""이용약관·개인정보 처리방침 (plan/73).

기본 문서는 `assets/legal/{terms,privacy}.md` 에 있다(한국어, 대한민국 법 기준). 관리자가 본문을 넣으면 그것을 쓰고,
비워 두면 기본 문서를 쓴다. 어느 쪽이든 운영자 정보(상호·대표자·연락처·개인정보 보호책임자…)는 관리자 설정에서
채워 넣는다.

자리표시:
- ``{{key}}``  — 값으로 바꾼다. 비어 있으면 정해 둔 대신 말(``_FALLBACK``)로.
- ``{{?key}}`` — 그 줄은 값이 있을 때만 있다. 비어 있으면 줄째로 빠진다(비어 있는 "대표자: " 가 남지 않게).

판(version) 은 시행일이다. 동의는 판에 붙는다 — 시행일을 바꾸면 모두에게 다시 한 번 받는다.
"""
from __future__ import annotations

import re
from functools import lru_cache
from pathlib import Path

from sqlalchemy.ext.asyncio import AsyncSession

from blackmoa.services import settings as S

LEGAL_DIR = Path(__file__).resolve().parent.parent / "assets" / "legal"
#: 기본 문서의 시행일. 기본 문서를 고치면 이것도 올린다(관리자가 시행일을 정해 두었으면 그것이 먼저).
DEFAULT_VERSION = "2026-09-29"
KINDS = ("terms", "privacy")

#: 자리표시 → 설정 키
_KEYS = {
    "company": "legal.company_name",
    "ceo": "legal.ceo_name",
    "business_no": "legal.business_no",
    "mail_order_no": "legal.mail_order_no",
    "address": "legal.address",
    "phone": "legal.phone",
    "email": "legal.email",
    "hosting": "legal.hosting",
    "privacy_officer": "legal.privacy_officer",
    "privacy_officer_title": "legal.privacy_officer_title",
    "privacy_email": "legal.privacy_email",
    "privacy_phone": "legal.privacy_phone",
}
_PLACEHOLDER = re.compile(r"\{\{(\?)?([a-z_]+)\}\}")


@lru_cache(maxsize=4)
def _default_text(kind: str) -> str:
    return (LEGAL_DIR / f"{kind}.md").read_text(encoding="utf-8")


def _date_ko(v: str) -> str:
    m = re.fullmatch(r"(\d{4})-(\d{2})-(\d{2})", v.strip())
    return f"{int(m.group(1))}년 {int(m.group(2))}월 {int(m.group(3))}일" if m else v


async def version(db: AsyncSession) -> str:
    """지금 동의받는 판(시행일, YYYY-MM-DD)."""
    v = str(await S.get(db, "legal.effective_date") or "").strip()
    return v or DEFAULT_VERSION


async def operator(db: AsyncSession) -> dict[str, str]:
    """운영자 정보(비어 있는 것은 빠진다). 바닥글과 문서가 같이 쓴다."""
    out: dict[str, str] = {}
    for k, key in _KEYS.items():
        v = str(await S.get(db, key) or "").strip()
        if v:
            out[k] = v
    return out


def render(template: str, values: dict[str, str]) -> str:
    """자리표시를 채운다. ``{{?key}}`` 가 비면 그 줄을 뺀다."""
    lines = []
    for line in template.splitlines():
        drop = False

        def sub(m: re.Match[str]) -> str:
            nonlocal drop
            optional, key = m.group(1), m.group(2)
            v = values.get(key, "")
            if not v and optional:
                drop = True
            return v

        new = _PLACEHOLDER.sub(sub, line)
        if not drop:
            lines.append(new)
    return "\n".join(lines).strip() + "\n"


async def values(db: AsyncSession) -> dict[str, str]:
    op = await operator(db)
    service = str(await S.get(db, "branding.service_name") or "black-moa").strip() or "black-moa"
    v = await version(db)
    vals = dict(op)
    vals["service"] = service
    # 상호가 없으면 서비스 이름으로 부른다(개인이 운영하는 경우도 있다).
    vals.setdefault("company", service)
    # 개인정보 보호책임자를 따로 정하지 않았으면 대표자가 맡는다(개인정보 보호법 시행령 제32조).
    if "privacy_officer" not in vals and "ceo" in vals:
        vals["privacy_officer"] = vals["ceo"]
        vals.setdefault("privacy_officer_title", "대표")
    vals.setdefault("privacy_email", vals.get("email", ""))
    vals.setdefault("privacy_phone", vals.get("phone", ""))
    # 문의 창구: 이메일 > 전화. 둘 다 없으면 이 문장은 "서비스 안의 문의 방법"을 가리킨다.
    vals["contact"] = vals.get("privacy_email") or vals.get("email") or vals.get("phone") or "서비스 안에서 알리는 연락처"
    vals["effective_date"] = _date_ko(v)
    vals["version"] = v
    return vals


async def documents(db: AsyncSession) -> dict:
    """공개 화면이 받는 것: 두 문서(마크다운), 판, 운영자 정보."""
    vals = await values(db)
    docs = {}
    custom = {}
    for kind in KINDS:
        own = str(await S.get(db, f"legal.{kind}") or "").strip()
        custom[kind] = bool(own)
        docs[kind] = render(own or _default_text(kind), vals)
    op = await operator(db)
    return {"terms": docs["terms"], "privacy": docs["privacy"], "format": "markdown", "version": vals["version"],
            "effective_date": vals["effective_date"], "custom": custom, "operator": op,
            "service": vals["service"]}


def default_text(kind: str) -> str:
    """관리자 화면이 "기본 문서로 시작" 할 때 채워 넣는 원문(자리표시 그대로)."""
    if kind not in KINDS:
        raise KeyError(kind)
    return _default_text(kind)
