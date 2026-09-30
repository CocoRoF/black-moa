from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from memora.core import visibility as VIS
from memora.models import OwnerProfile

PROFILE_FIELDS = ["full_name", "preferred_name", "title", "company", "bio", "location", "languages", "links",
                  "contact", "availability_window", "contact_rules", "extra",
                  # The band behind the photo, and where it is anchored: one picture is shown
                  # in a card on a phone and across a monitor on a desktop, and only its owner
                  # knows which part of it matters.
                  "cover", "cover_pos",
                  # What they do, where, and in what industry — the community's own taxonomy
                  # (plan/36), so a secretary and a job board mean the same thing by them.
                  "job_codes", "region_codes", "industry_codes",
                  # Where they work, proven by a work mailbox (plan/40 §10): the company in
                  # the directory, and when it was proven. Written by the verification flow.
                  "company_id", "company_verified_at", "company_domain"]


def display_name(profile: OwnerProfile | None, user: Any, *, audience: str = "owner",
                 policy: dict | None = None) -> str:
    """What the owner is called.

    The name they chose in their profile wins over the account's display name (often just a
    signup label). In front of a visitor a profile name is used only when it is marked
    public — otherwise an on-request full name would be disclosed by the greeting itself,
    before profile_disclose ever runs.
    """
    data = (profile.data if profile is not None else None) or {}
    for key in ("preferred_name", "full_name"):
        v = (data.get(key) or "").strip() if isinstance(data.get(key), str) else ""
        if not v:
            continue
        if audience == "visitor" and profile is not None and field_visibility(profile, policy or {}, key) != "public":
            continue
        return v
    return (getattr(user, "display_name", "") or "").strip() or "오너"


async def display_name_for(db: AsyncSession, user: Any, *, audience: str = "owner",
                           policy: dict | None = None) -> str:
    return display_name(await get(db, user.id), user, audience=audience, policy=policy)


async def get(db: AsyncSession, owner_id: uuid.UUID) -> OwnerProfile:
    p = await db.get(OwnerProfile, owner_id)
    if p is None:
        p = OwnerProfile(owner_id=owner_id, data={}, visibility={}, updated_at=datetime.now(UTC))
        db.add(p)
        await db.flush()
    return p


async def seed_from_account(db: AsyncSession, user: Any) -> OwnerProfile:
    """Put what signup already asked for into the profile.

    The form collects a real name, a nickname and an email; without this they live only on
    the account row and the profile page opens blank — so the first thing a new account
    sees is a form asking again for what it just typed. Only empty fields are filled, so
    this is safe to run over an account that has since edited its profile.
    """
    p = await get(db, user.id)
    data = dict(p.data or {})
    seeds = {
        "full_name": (getattr(user, "display_name", "") or "").strip(),
        "preferred_name": (getattr(user, "nickname", "") or "").strip() or (getattr(user, "display_name", "") or "").strip(),
    }
    changed = False
    for key, value in seeds.items():
        if value and not (data.get(key) or "").strip():
            data[key] = value
            changed = True
    contact = dict(data.get("contact") or {})
    email = (getattr(user, "email", "") or "").strip()
    if email and not (contact.get("email") or "").strip():
        contact["email"] = email
        data["contact"] = contact
        changed = True
    if changed:
        p.data = data
        p.updated_at = datetime.now(UTC)
    return p


#: Written only by the verification flow (plan/40 §10): a profile edit cannot claim a
#: company it never proved.
LOCKED_FIELDS = frozenset({"company_id", "company_verified_at", "company_domain"})
#: 프로필에 저장되지만 프로필 칸이 아닌 것 (plan/57). 연락 가능 시간은 [내 정보 → 스케줄] 의
#: 것이라 프로필 페이지에도, 프로필 블록에도 나오지 않고, 공개 범위도 없다 — 외부인에게 쓸지는
#: 비서의 [지식] 탭 스케줄 줄이 정한다.
SCHEDULE_FIELDS = frozenset({"availability_window"})


class ProfileView:
    """읽기만 하는 프로필 — 기업 기능이 꺼졌을 때 기업 칸을 뺀 것 (plan/71).

    저장된 행을 고치지 않고 보여 줄 것만 고른다: 행의 ``data`` 를 바꾸면 세션이 그것을 저장해 버린다.
    """

    __slots__ = ("owner_id", "data", "visibility", "updated_at")

    def __init__(self, p: OwnerProfile) -> None:
        from memora.services.companies import switch as CO

        self.owner_id = p.owner_id
        self.data = CO.strip(p.data)
        self.visibility = {k: v for k, v in (p.visibility or {}).items() if k not in CO.PROFILE_FIELDS}
        self.updated_at = p.updated_at


def view(p: OwnerProfile, companies: bool) -> Any:
    """보여 줄 프로필: 기업 기능이 켜져 있으면 그 행, 꺼져 있으면 기업 칸을 뺀 사본."""
    return p if companies else ProfileView(p)


async def shown(db: AsyncSession, owner_id: uuid.UUID) -> Any:
    """읽어서 보여 줄(비서의 지시문·프로필 응답에 실을) 프로필. 고치려면 :func:`get` 을 쓴다."""
    from memora.services.companies import switch as CO

    return view(await get(db, owner_id), await CO.enabled(db))


async def update(db: AsyncSession, owner_id: uuid.UUID, data: dict[str, Any] | None = None,
                 visibility: dict[str, str] | None = None, *, trusted: bool = False) -> OwnerProfile:
    from memora.services.companies import switch as CO

    p = await get(db, owner_id)
    # 기업 기능이 꺼져 있으면 소속은 새로 쓰이지 않는다 (plan/71). 합치는 것이라 들어온 칸을 버리면 저장된 값은 남는다.
    companies = await CO.enabled(db)
    if data is not None:
        merged = dict(p.data or {})
        for k, v in data.items():
            if not companies and k in CO.PROFILE_FIELDS:
                continue
            if k in PROFILE_FIELDS and (trusted or k not in LOCKED_FIELDS):
                merged[k] = v
        p.data = merged
    if visibility is not None:
        vis = dict(p.visibility or {})
        for k, v in visibility.items():
            if k in SCHEDULE_FIELDS or (not companies and k in CO.PROFILE_FIELDS):
                continue
            if v in ("public", "known", "private", "on_request"):   # accept the legacy value, store the new one
                vis[k] = normalize_visibility(v)
        p.visibility = vis
    p.updated_at = datetime.now(UTC)
    return p


#: 범위와 읽는 사람의 정본은 `core.visibility` 하나다 (plan/48 §2). 프로필만 쓰던
#: 말을 그 모듈로 올렸고, 여기 있는 이름들은 부르던 자리를 깨지 않기 위한 별명이다.
VISIBILITIES = VIS.LEVELS
VIEWERS = VIS.VIEWERS
normalize_visibility = VIS.normalize
visible_to = VIS.visible_to


# What a field is before anybody has said otherwise. The profile form shows these as the
# state of each switch, so the server has to agree with it: a field the owner was shown as
# 공개, and never touched, must actually be public. Anything not listed stays private.
DEFAULT_FIELD_VIS = {
    "full_name": "public", "preferred_name": "public", "title": "public", "company": "public",
    "bio": "public", "languages": "public", "links": "public",
    "contact_rules": "public", "cover": "public", "cover_pos": "public",
    "job_codes": "public", "region_codes": "public", "industry_codes": "public",
    "company_id": "public", "company_verified_at": "public",
}


def field_visibility(profile: OwnerProfile, agent_policy: dict, field: str) -> str:
    """이 칸이 어디까지 나가는가. **정본은 [내 정보] 하나다** (plan/48 §2).

    예전에는 비서의 `disclosure_policy.profile_fields` 가 두 번째로 답했다. 주인이
    [내 정보] 에서 정하지 않은 칸은 비서 설정이 정했고, 화면 둘이 같은 칸에 서로 다른
    값을 보여 줄 수 있었다. 기본값 표도 둘이라 `location` 이 한쪽은 공개, 다른 쪽은
    비공개여서 **비서를 만든 사람과 안 만든 사람의 기본값이 달랐다.**

    `agent_policy` 는 부르던 자리를 깨지 않으려고 남겨 둔 인자이고, 읽지 않는다.
    """
    return normalize_visibility((profile.visibility or {}).get(field)
                                or DEFAULT_FIELD_VIS.get(field) or "private")


_DAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]


def render_window(win: Any) -> str:
    """The weekly availability in words. The stored shape is built for the UI; handing the
    model raw JSON makes it quote braces back at visitors."""
    if isinstance(win, str):
        return win[:200]
    if not isinstance(win, dict):
        return ""
    parts = []
    for row in (win.get("weekly") or [])[:7]:
        days = [_DAYS[i] for i in (row.get("days") or []) if isinstance(i, int) and 0 <= i < 7]
        if days and row.get("start") and row.get("end"):
            parts.append(f"{'/'.join(days)} {row['start']}-{row['end']}")
    note = str(win.get("note") or "")[:120]
    joined = ", ".join(parts)
    if joined and win.get("skip_holidays") is not False:
        joined += ", not on public holidays"
    return (joined + (f" ({note})" if note else "")) if joined else note


def _render_value(val: Any, key: str = "") -> str:
    if isinstance(val, dict | list):
        import json
        return json.dumps(val, ensure_ascii=False)[:600]
    return str(val)[:600]


def render_profile(profile: OwnerProfile, agent_policy: dict, audience: str, *, viewer: str = "",
                   share: bool = True) -> str:
    """Render the profile block for the model.

    A visitor session sees what the owner's profile page shows *this* reader and nothing
    else — a private field is not listed, not hinted at, and has no path into that
    conversation. The owner's own session sees everything. The level is decided per field
    in [내 정보 → 정보]; whether this secretary uses the profile with outsiders at all is
    ``share`` — the 정보 row of its [지식] tab (plan/57). Off, the block is empty: the name
    the secretary introduces its owner by comes from elsewhere and stays.
    """
    d = profile.data or {}
    who = viewer if viewer in VIEWERS else ("owner" if audience != "visitor" else "stranger")
    if who != "owner" and not share:
        return ""
    lines: list[str] = []
    for key in PROFILE_FIELDS:
        if key in SCHEDULE_FIELDS:
            continue
        val = d.get(key)
        if val in (None, "", [], {}):
            continue
        if key == "contact" and isinstance(val, dict):
            for sub, sv in val.items():
                if not sv:
                    continue
                field = f"contact.{sub}"
                if not visible_to(field_visibility(profile, agent_policy, field), who):
                    continue
                lines.append(f"- {field}: {_render_value(sv)}")
            continue
        if key in LOCKED_FIELDS:
            continue
        if not visible_to(field_visibility(profile, agent_policy, key), who):
            continue
        # The company, when proven with a work mailbox, says so (plan/40 §10).
        note = " (회사 이메일로 인증됨)" if key == "company" and d.get("company_verified_at") else ""
        lines.append(f"- {key}: {_render_value(val, key)}{note}")
    return "\n".join(lines)


def disclosure_value(profile: OwnerProfile, agent_policy: dict, field: str) -> tuple[str, Any | None]:
    """Return (visibility, value) for a supported profile field without rendering it into a prompt."""
    if field.startswith("contact."):
        sub = field.split(".", 1)[1]
        value = ((profile.data or {}).get("contact") or {}).get(sub)
    elif field in PROFILE_FIELDS and field != "contact":
        value = (profile.data or {}).get(field)
    else:
        return "private", None
    return field_visibility(profile, agent_policy, field), value


def private_literals(profile: OwnerProfile, agent_policy: dict, *, viewer: str = "stranger", share: bool = True,
                     keep: tuple[str, ...] = ()) -> list[str]:
    """Values that must not appear accidentally in a visitor response.

    Anything this reader may not see is included: nothing outside what they are allowed
    may surface in the answer, whatever path it took to get there (memory, a document, a
    stray echo). A connection is allowed more than a stranger, so the list is shorter for
    them — and the redactor is what makes that difference real rather than a prompt rule.

    ``share`` false (the secretary does not use the profile with outsiders, plan/57) masks
    every one of these values, except those in ``keep`` — the name the secretary introduces
    its owner by, which it must still be able to say.
    """
    d = profile.data or {}
    who = viewer if viewer in VIEWERS else "stranger"
    kept = {str(k) for k in keep if k}
    out: list[str] = []

    def hidden(field: str) -> bool:
        return not share or not visible_to(field_visibility(profile, agent_policy, field), who)

    contact = d.get("contact") or {}
    for sub, sv in contact.items():
        if sv and hidden(f"contact.{sub}") and str(sv) not in kept:
            out.append(str(sv))
    for key in ("location", "full_name", "company", "title", "bio", "links"):
        v = d.get(key)
        if v and isinstance(v, str) and len(v) >= 3 and hidden(key) and v not in kept:
            out.append(v)
    return out
