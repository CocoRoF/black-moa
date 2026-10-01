"""Agents (secretaries) and share links."""
from __future__ import annotations

import re
import uuid
from datetime import UTC, datetime

from sqlalchemy import and_, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from blackmoa.core.codes import generate_code, validate_handle
from blackmoa.core.errors import Conflict, NotFound, ValidationFailed
from blackmoa.models import Agent, Plan, ShareLink, User
from blackmoa.services import catalog as CAT
from blackmoa.services import outsider as OUT
from blackmoa.services import plans as P
from blackmoa.services import settings as S

DEFAULT_PERSONA = {
    "preset": "professional", "formality": 0.7, "warmth": 0.6, "verbosity": 0.4, "humor": 0.2, "emoji": False,
    "self_reference": "저", "catchphrases": [], "address_owner_as": "", "traits": [], "extra": "",
}
#: 비서가 **외부인과의 대화에서 하는 일** (plan/57). 나와의 대화에서는 모든 기능이
#: 늘 켜져 있으므로 여기 없다. 외부인에게 무엇을 **쓰는지**(지식·인맥·스케줄…)는
#: 비서의 [지식] 탭, ``agents.outsider`` 가 정한다. 아는 것과 하는 것은 다른 문제다.
DEFAULT_CAPABILITIES = {"voice": True, "leave_message": True, "meeting_request": True}
CAPABILITY_KEYS = frozenset(DEFAULT_CAPABILITIES)
#: 비서가 외부인에게 **어떻게 말하는가**: 말해도 되는 주제, 피할 주제, 모를 때.
#: 무엇을 쓰는지는 [지식] 탭, 내 칸이 프로필에 어디까지 보이는지는 [내 정보 → 정보] 다.
DEFAULT_DISCLOSURE = {"topics_public": [], "topics_private": [], "unknown_policy": "offer_message"}
DISCLOSURE_KEYS = frozenset(DEFAULT_DISCLOSURE)
#: 공개 비서에 기본으로 서 있는 울타리 (plan/53).
#:
#: 공개 링크는 **받는 쪽이 내는 구조**다. 열어 둔 사람의 크레딧으로 모르는 사람이
#: 말한다. 그래서 상한이 없는 기본값은 "링크가 퍼지면 잔액이 사라진다" 와 같은 말이다.
#: 세 겹으로 막는다 — 하루 전체, 한 IP 가 새로 여는 대화, 한 방문자의 말 속도.
#: 셋 다 비서 설정에서 주인이 바꾼다. 0 은 제한 없음이고, 그건 주인이 고르는 것이다.
DEFAULT_VISITOR_SETTINGS = {"retention_days": 90,
                            # 한 방문자가 1분에 주고받는 말 (0 = 제한 없음)
                            "rate_per_minute": 10,
                            "require_turnstile": False, "collect_identity": "ask",
                            # 이 계정의 방문자 대화 전체에 걸리는 하루 상한 (0 = 제한 없음)
                            "turns_per_day": 200,
                            # 한 IP 가 한 시간에 새로 여는 방문자 대화 (0 = 제한 없음)
                            "sessions_per_hour": 30,
                            # 방문자에게서 파일 받기 (plan/55 §6-3, 결정 2 — 기본 켜짐).
                            # 받는 파일도 주인의 저장 공간을 쓰니 한 사람의 하루 개수와 한 개의 크기를 둔다.
                            "accept_files": True, "files_per_day": 20, "file_max_mb": 10}

#: 설정값의 울타리. 화면이 보내는 것이든 API 로 오는 것이든 여기서 잘린다.
VISITOR_BOUNDS = {"rate_per_minute": (0, 120), "turns_per_day": (0, 100_000),
                  "sessions_per_hour": (0, 10_000), "retention_days": (1, 3650),
                  # 파일은 "제한 없음" 을 두지 않는다 — 남의 저장 공간을 쓰는 일이다.
                  "files_per_day": (1, 200), "file_max_mb": (1, 25)}
DEFAULT_THEME = {"accent": "#4f46e5", "avatar_shape": "circle", "bubble_style": "soft", "background": "gradient"}
DEFAULT_VOICE = {"tts_voice": "", "tts_speed": 1.0, "stt_language": ""}


def _merge(base: dict, override: dict | None) -> dict:
    out = dict(base)
    for k, v in (override or {}).items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _merge(out[k], v)
        else:
            out[k] = v
    return out


async def _turnstile_configured(db: AsyncSession) -> bool:
    site_key = str(await S.get(db, "public.turnstile_site_key") or "").strip()
    secret = str(await S.get(db, "public.turnstile_secret") or "").strip()
    return bool(site_key and secret)


async def _validate_visitor_settings(db: AsyncSession, settings: dict) -> None:
    if settings.get("require_turnstile") and not await _turnstile_configured(db):
        raise ValidationFailed("Turnstile site key and secret must be configured before enabling it",
                               code="turnstile_not_configured")
    for key, (low, high) in VISITOR_BOUNDS.items():
        if key not in settings:
            continue
        try:
            n = int(settings[key])
        except (TypeError, ValueError):
            raise ValidationFailed("숫자로 적어 주세요.", code="bad_visitor_setting", detail={"field": key}) from None
        # 쓴 값을 거절하는 대신 울타리 안으로 데려온다: 상한을 넘겨 적었다고 해서
        # 설정 전체가 저장되지 않으면, 고친 다른 칸까지 같이 사라진다.
        settings[key] = max(low, min(high, n))


async def count_for_owner(db: AsyncSession, owner_id: uuid.UUID) -> int:
    return int((await db.execute(select(func.count(Agent.id)).where(Agent.owner_id == owner_id,
                                                                    Agent.status != "archived"))).scalar_one())


async def create(db: AsyncSession, owner: User, *, name: str, role_line: str = "", persona: dict | None = None,
                 provider: str | None = None, model_id: str | None = None, language: str = "auto",
                 greeting: str = "", suggested_questions: list[str] | None = None,
                 avatar_url: str | None = None, cover_url: str | None = None, character: str | None = None) -> Agent:
    plan: Plan = await P.plan_for_user(db, owner)
    if await count_for_owner(db, owner.id) >= plan.max_agents:
        raise Conflict("agent limit reached", code="agent_limit", detail={"max": plan.max_agents})
    if provider and model_id:
        cat, _ = await CAT.resolve_for_plan(db, plan, provider, model_id)
    else:
        cat = await CAT.default_for_plan(db, plan)
    if cat is None:
        raise ValidationFailed("no model available — admin must enable a model", code="no_model_available")
    agent = Agent(owner_id=owner.id, name=name.strip()[:80] or "비서", role_line=role_line.strip()[:160],
                  # Chosen while the secretary was being made, so it has a face from its
                  # first message rather than after a trip through settings.
                  avatar_url=avatar_url or None, cover_url=cover_url or None, character_url=character_url(character),
                  provider=cat.provider, model_id=cat.model_id, persona=_merge(DEFAULT_PERSONA, persona),
                  capabilities=dict(DEFAULT_CAPABILITIES), disclosure_policy=dict(DEFAULT_DISCLOSURE),
                  outsider=dict(OUT.DEFAULTS),
                  greeting=greeting or "", suggested_questions=(suggested_questions or [])[:4], language=language,
                  theme=dict(DEFAULT_THEME), voice=dict(DEFAULT_VOICE), visitor_settings=dict(DEFAULT_VISITOR_SETTINGS), stats={})
    db.add(agent)
    await db.flush()
    return agent


async def get_owned(db: AsyncSession, owner_id: uuid.UUID, agent_id: uuid.UUID, *, include_archived: bool = False) -> Agent:
    agent = await db.get(Agent, agent_id)
    if agent is None or agent.owner_id != owner_id or (agent.status == "archived" and not include_archived):
        raise NotFound("agent not found", code="agent_not_found")
    return agent


async def list_owned(db: AsyncSession, owner_id: uuid.UUID, *, include_archived: bool = False) -> list[Agent]:
    stmt = select(Agent).where(Agent.owner_id == owner_id).order_by(Agent.created_at)
    if not include_archived:
        stmt = stmt.where(Agent.status != "archived")
    return list((await db.execute(stmt)).scalars().all())


_CHARACTER = re.compile(r"^/(api/public/uploads/[0-9a-fA-F-]{36}|presets/[A-Za-z0-9_-]{1,64}\.png(\?v=\d{1,4})?)$")


def character_url(v: object) -> str | None:
    """원본 그림의 자리. 우리가 내어 주는 두 곳(올린 그림, 프리셋)만 받는다 — 앱이 그 주소를 받아 와 그리므로
    바깥 주소를 받으면 비서의 얼굴이 남의 서버를 부르는 길이 된다."""
    s = str(v or "").strip()
    if not s:
        return None
    if not _CHARACTER.match(s):
        raise ValidationFailed("invalid character image", code="invalid_character")
    return s


# 고른 얼굴(프리셋)마다 세울 전신 그림: `frontend/public/presets/<이름>-full.png` 는 images/*_portrait 의 원본(투명
# PNG)을 **PNG 그대로, 투명한 채로** 줄인 것이다 — `tools/preset_figures.py` 가 만든다(긴 변 1280, 한 장 3MB 아래).
# 얼굴 쪽 `<이름>.png` 는 동그라미용으로 512 에 잘라 흰 바탕을 깐 것이라, 그것을 세우면 흰 바탕을 다시 걷어 내느라
# 머리 둘레가 희게 남고 흰 셔츠에 구멍이 났다. 이름을 더하면 그 도구의 목록과 파일도 같이(테스트가 확인한다).
PRESET_FIGURES = frozenset({
    "secretary-male", "secretary-male-pinstripe", "secretary-male-double", "secretary-male-grey", "secretary-male-burgundy",
    "secretary-female", "secretary-female-bob", "secretary-female-dark", "secretary-female-ponytail", "secretary-female-pixie",
    "secretary-female-dot-cardigan", "secretary-female-dot-auburn", "secretary-female-dot-shirt", "secretary-female-dot-green",
    "secretary-female-dot-navy",
})
PRESET_FIGURE_REV = "3"
_PRESET_FACE = re.compile(r"^/presets/([A-Za-z0-9_-]{1,64})\.png(\?v=\d{1,4})?$")


def stage_figure(agent: Agent) -> str | None:
    """비서를 세울 그림(무대, PC 앱의 아바타): 올린 원본이 있으면 그것, 고른 얼굴이면 그 얼굴의 원본 전신 그림,
    아니면 없음(쓰는 쪽이 프로필 사진을 쓴다).

    저장된 값이 프리셋 주소면 믿지 않고 지금 고른 얼굴에서 다시 정한다 — 예전에는 512 얼굴 자체가 원본 자리에
    들어가기도 했고, 얼굴을 바꾼 뒤에도 옛 얼굴의 그림이 남을 수 있다."""
    c = agent.character_url
    if c and not c.startswith("/presets/"):
        return c
    m = _PRESET_FACE.match(agent.avatar_url or "")
    if m and m.group(1) in PRESET_FIGURES:
        return f"/presets/{m.group(1)}-full.png?v={PRESET_FIGURE_REV}"
    return None


UPDATABLE = {"name", "role_line", "avatar_url", "cover_url", "character_url", "persona", "custom_instructions", "capabilities", "disclosure_policy",
             "greeting", "suggested_questions", "language", "theme", "voice", "visitor_settings", "thinking_enabled",
             # The owner's own guard rails on this secretary (plan/34)
             "turn_cost_cap_credits", "daily_credit_cap", "monthly_credit_cap"}


async def update(db: AsyncSession, agent: Agent, patch: dict, *, plan: Plan | None = None) -> Agent:
    for k, v in patch.items():
        if k not in UPDATABLE and k not in ("provider", "model_id"):
            continue
        if k in ("persona", "capabilities", "disclosure_policy", "theme", "voice", "visitor_settings"):
            v = dict(v or {})
            # 이제 아무것도 정하지 않는 옛 키는 받지 않는다 — 저장되면 화면이 그것을 설정처럼 다시 보여 준다.
            if k == "capabilities":
                v = {c: bool(x) for c, x in v.items() if c in CAPABILITY_KEYS}
            elif k == "disclosure_policy":
                v = {c: x for c, x in v.items() if c in DISCLOSURE_KEYS}
            elif k == "visitor_settings":
                v = {c: x for c, x in v.items() if c in DEFAULT_VISITOR_SETTINGS}
            merged = _merge(getattr(agent, k) or {}, v)
            if k == "visitor_settings":
                await _validate_visitor_settings(db, merged)
            setattr(agent, k, merged)
        elif k == "suggested_questions":
            agent.suggested_questions = [str(x)[:120] for x in (v or [])][:4]
        elif k == "custom_instructions":
            agent.custom_instructions = str(v or "")[:4000]
        elif k == "name":
            agent.name = str(v).strip()[:80] or agent.name
        elif k == "character_url":
            agent.character_url = character_url(v)
        elif k in ("turn_cost_cap_credits", "daily_credit_cap", "monthly_credit_cap"):
            # 0 means no limit everywhere except per turn, where a turn has to be allowed
            # to hold something or it can never start.
            n = max(0, int(v or 0))
            setattr(agent, k, max(1, n) if k == "turn_cost_cap_credits" else n)
        else:
            setattr(agent, k, v)
    if "provider" in patch or "model_id" in patch:
        cat, fell = await CAT.resolve_for_plan(db, plan, patch.get("provider", agent.provider), patch.get("model_id", agent.model_id))
        if cat is None:
            raise ValidationFailed("model unavailable", code="model_unavailable")
        if fell:
            # Either it is off in the catalog, or this plan may not use it. One message:
            # the difference is the admin's business, not the owner's.
            raise ValidationFailed("model not available on this plan", code="model_not_enabled")
        agent.provider, agent.model_id = cat.provider, cat.model_id
    return agent


async def set_status(agent: Agent, status: str) -> Agent:
    if status not in ("active", "paused", "archived"):
        raise ValidationFailed("bad status")
    agent.status = status
    agent.archived_at = datetime.now(UTC) if status == "archived" else None
    return agent


async def create_link(db: AsyncSession, owner: User, agent: Agent, *, label: str = "", handle: str | None = None,
                      expires_at: datetime | None = None, max_conversations: int | None = None) -> ShareLink:
    code = None
    if handle:
        try:
            code = validate_handle(handle)
        except ValueError as e:
            raise ValidationFailed(str(e), code=str(e)) from e
    # 비서 하나에 공개 링크 하나 (plan/80) — 둘째 링크는 만들지 않는다. 주소를 바꾸려면 그 링크를 고친다.
    if (await db.execute(select(ShareLink.id).where(ShareLink.agent_id == agent.id, ShareLink.status != "revoked")
                         .limit(1))).first():
        raise Conflict("this secretary already has a public link", code="link_exists")
    plan = await P.plan_for_user(db, owner)
    n = int((await db.execute(select(func.count(ShareLink.id)).where(ShareLink.owner_id == owner.id,
                                                                     ShareLink.status != "revoked"))).scalar_one())
    if n >= plan.max_share_links:
        raise Conflict("share link limit reached", code="link_limit", detail={"max": plan.max_share_links})
    if code:
        if (await db.execute(select(ShareLink.id).where(ShareLink.code == code))).first():
            raise Conflict("handle taken", code="handle_taken")
    else:
        code = generate_code()
        while (await db.execute(select(ShareLink.id).where(ShareLink.code == code))).first():
            code = generate_code()
    link = ShareLink(owner_id=owner.id, agent_id=agent.id, code=code, label=label[:80], expires_at=expires_at,
                     max_conversations=max_conversations, settings={})
    db.add(link)
    await db.flush()
    return link


async def get_link_by_code(db: AsyncSession, code: str) -> ShareLink | None:
    link = (await db.execute(select(ShareLink).where(ShareLink.code == code.lower()))).scalars().first()
    if link is None:
        return None
    agent = await db.get(Agent, link.agent_id)
    if agent is not None and (agent.visitor_settings or {}).get("require_turnstile") and not await _turnstile_configured(db):
        # Existing deployments that enabled Turnstile before configuring both
        # credentials must fail closed instead of silently accepting visitors.
        return None
    return link


async def get_link_owned(db: AsyncSession, owner_id: uuid.UUID, link_id: uuid.UUID) -> ShareLink:
    link = await db.get(ShareLink, link_id)
    if link is None or link.owner_id != owner_id:
        raise NotFound("link not found", code="link_not_found")
    return link


def open_link():
    """A link somebody could actually walk through right now.

    The same three conditions `link_effective_status` calls "active", written once as a
    query so the places that show a secretary as reachable — the picker, the graph, a
    caption naming one — cannot drift from the page that opens.
    """
    now = datetime.now(UTC)
    return and_(ShareLink.status == "active",
                or_(ShareLink.expires_at.is_(None), ShareLink.expires_at > now),
                or_(ShareLink.max_conversations.is_(None),
                    ShareLink.conversation_count < ShareLink.max_conversations))


# 공개 대화의 모양 (plan/71). chat: 지금의 채팅 화면. stage: 배경 위에 비서의 그림이 서고, 게임처럼 대화창으로 말한다.
LINK_LAYOUTS = ("chat", "stage")


def link_layout(link: ShareLink) -> str:
    v = (link.settings or {}).get("layout")
    return v if v in LINK_LAYOUTS else "chat"


def link_effective_status(link: ShareLink, agent: Agent) -> str:
    if link.status == "revoked":
        return "revoked"
    if link.expires_at and link.expires_at < datetime.now(UTC):
        return "expired"
    if link.max_conversations and link.conversation_count >= link.max_conversations:
        return "expired"
    if link.status == "paused" or agent.status != "active":
        return "paused"
    return "active"


# Honorifics owners actually type into "preferred name" (하렴 사장님, 김 선생님, 박 대표님 …).
_HONORIFIC_TAIL = ("님", "씨", "군", "양")


def honorific(owner_name: str) -> str:
    """The owner's name with 님 attached — unless they already wrote an honorific.

    "하렴 사장님" + 님 read as "하렴 사장님님" on the public page.
    """
    name = (owner_name or "").strip()
    return name if name.endswith(_HONORIFIC_TAIL) else f"{name}님"


def auto_greeting(agent_name: str, owner_name: str) -> str:
    return f"안녕하세요, {honorific(owner_name)}의 비서 {agent_name}입니다. 무엇을 도와드릴까요?"


def personalize_greeting(greeting: str, visitor_name: str | None, *, language: str = "ko") -> str:
    """Address a visitor we know by name.

    `{visitor_name}` in an owner-written greeting is substituted; otherwise a known name is
    prefixed, because a greeting that ignores someone who just told you their name reads
    worse than no greeting at all. honorific() keeps "지수님님" from happening, and only
    Korean gets the honorific — "Alex님 Hello" is not a greeting in English.
    """
    text = (greeting or "").strip()
    name = (visitor_name or "").strip()
    korean = not language or language.startswith(("ko", "auto"))
    if "{visitor_name}" in text:
        shown = (honorific(name) if korean else name) if name else ""
        return " ".join(text.replace("{visitor_name}", shown).split())
    if not name:
        return text
    return f"{honorific(name)} {text}" if korean else f"{name}, {text}"


def auto_role_line(owner_name: str) -> str:
    # Same wording the onboarding used to prefill, so nothing reads differently after the
    # frozen copies are cleared.
    return f"{owner_name}의 업무 비서"


def display_texts(agent, owner_name: str) -> tuple[str, str]:
    """Greeting and role line as shown anywhere.

    Both are stored empty until the owner writes their own, and the default is rendered from
    the *current* names. Persisting the generated text (as this used to) froze it: renaming
    the agent or the owner left visitors reading "OO님의 비서 13" forever.
    """
    return ((agent.greeting or "").strip() or auto_greeting(agent.name, owner_name),
            (agent.role_line or "").strip() or auto_role_line(owner_name))
