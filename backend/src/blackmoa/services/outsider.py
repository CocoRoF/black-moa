"""외부인과의 대화에서 비서가 무엇을 쓰나 — 정본 (plan/57).

    [내 정보]  ──전부──▶  [비서]  ──[지식] 탭에서 정한 만큼──▶  [외부인]

나와의 대화에서는 비서가 내 것을 전부 쓴다. 여기 있는 것은 **외부인 쪽** 하나뿐이다:
공개 링크로 온 사람, 그리고 다른 사람의 비서(릴레이). 공개 범위를 원천마다 따로 두던
것을 걷고, 비서마다 [지식] 탭 한 곳에서 정한다. 예외는 [정보] 하나 — 그 칸들은 프로필
페이지에 그대로 보이므로 공개 범위를 [내 정보 → 정보] 가 정하고, 여기서는 "프로필에
보이는 것을 외부인 대화에서 쓸지" 만 정한다.

줄마다:
- 수준 (지식·파일·인맥·스케줄): ``off`` 쓰지 않음 · ``known`` 인맥에게만 · ``public`` 모두에게.
- 범위 (지식·파일·인맥): ``picked`` 고른 것만 · ``all`` 전부(새로 넣는 것도).
- 스위치: 정보(``profile``) · 원본 파일 건네기(``knowledge_files``) · 공개로 둔 기억(``memory``) ·
  다시 온 사람 기억(``visitors``) · 웹 검색(``web``).

도구·지시문·기억·[지식] 탭 표시가 모두 이 모듈을 지난다. 화면이 끄면 대화도 꺼진다.
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from blackmoa.core import visibility as VIS
from blackmoa.core.errors import ValidationFailed

LEVELS: tuple[str, ...] = ("off", "known", "public")
#: 수준을 고르는 줄
LEVELED: tuple[str, ...] = ("knowledge", "files", "network", "schedule")
#: 그중 무엇을 쓸지 고르는 줄
SCOPED: tuple[str, ...] = ("knowledge", "files", "network")
SCOPES: tuple[str, ...] = ("picked", "all")
SWITCHES: tuple[str, ...] = ("profile", "knowledge_files", "memory", "visitors", "web")

#: 새 비서의 값. 고르는 줄은 [모두에게 · 고른 것만(0개)] 로 시작한다 — 무엇을 올리든
#: 주인이 고르기 전에는 밖으로 나가지 않는다. 웹 검색은 주인의 크레딧을 쓰니 꺼 둔다.
DEFAULTS: dict[str, Any] = {
    "profile": True,
    "knowledge": "public", "knowledge_scope": "picked", "knowledge_files": False,
    "files": "public", "files_scope": "picked",
    "network": "public", "network_scope": "picked",
    "schedule": "public",
    "memory": True, "visitors": True, "web": False,
}

#: [지식] 탭의 줄 이름 → agent_disclosures 의 열
_COLUMNS: dict[str, tuple[str, ...]] = {"knowledge": ("document_id", "faq_id"), "files": ("file_id",), "network": ("node_id",)}


def settings(agent: Any) -> dict[str, Any]:
    """이 비서의 설정 — 기본값을 채우고 모르는 값은 가장 좁은 쪽으로 접는다."""
    raw = dict(getattr(agent, "outsider", None) or {})
    out = dict(DEFAULTS)
    for k in LEVELED:
        if k in raw:
            out[k] = raw[k] if raw[k] in LEVELS else "off"
    for k in SCOPED:
        sk = f"{k}_scope"
        if sk in raw:
            out[sk] = raw[sk] if raw[sk] in SCOPES else "picked"
    for k in SWITCHES:
        if k in raw:
            out[k] = bool(raw[k])
    return out


def clean_patch(patch: dict[str, Any]) -> dict[str, Any]:
    """화면이 보낸 값을 검사한다. 모르는 키나 값은 조용히 넘기지 않고 거절한다."""
    out: dict[str, Any] = {}
    for k, v in (patch or {}).items():
        if k in LEVELED:
            if v not in LEVELS:
                raise ValidationFailed(f"{k} must be one of {', '.join(LEVELS)}", code="bad_outsider_level")
            out[k] = v
        elif k.endswith("_scope") and k[:-6] in SCOPED:
            if v not in SCOPES:
                raise ValidationFailed(f"{k} must be picked or all", code="bad_outsider_scope")
            out[k] = v
        elif k in SWITCHES:
            out[k] = bool(v)
        else:
            raise ValidationFailed(f"unknown setting {k}", code="bad_outsider_key")
    return out


def _level_reaches(level: str, viewer: str) -> bool:
    if level == "off":
        return False
    return VIS.visible_to(level, viewer)


def possible(agent: Any, key: str) -> bool:
    """이 줄이 **누구에게든** 쓰일 수 있는가 — 외부인 대화에 도구를 둘지 가를 때.

    듣는 사람이 인맥인지는 턴마다 다르므로, 도구는 수준이 켜져 있으면 두고 실제 범위는
    실행할 때 :class:`Disclosure` 가 가른다.
    """
    s = settings(agent)
    if key in LEVELED:
        return s[key] != "off"
    if key == "knowledge_files":
        return s["knowledge"] != "off" and s["knowledge_files"]
    if key == "knowledge_any":
        # 지식 줄, 또는 정보 줄 — 피드 글은 프로필에 실리는 것이라 정보 줄을 따르지만 지식 검색으로 찾는다.
        return s["knowledge"] != "off" or s["profile"]
    if key == "memory_any":
        return s["memory"] or s["visitors"]
    return bool(s.get(key))


@dataclass(frozen=True)
class Scope:
    """외부인에게 쓸 수 있는 항목들. ``all`` 이면 전부, 아니면 ``ids`` 에 든 것만."""

    all: bool = False
    ids: frozenset[uuid.UUID] = field(default_factory=frozenset)
    #: 지식 줄의 FAQ — 문서와 같은 줄이지만 표가 다르다.
    faq_ids: frozenset[uuid.UUID] = field(default_factory=frozenset)

    def has(self, item_id: Any) -> bool:
        if self.all:
            return True
        try:
            return uuid.UUID(str(item_id)) in self.ids
        except (TypeError, ValueError):
            return False

    def has_faq(self, faq_id: Any) -> bool:
        if self.all:
            return True
        try:
            return uuid.UUID(str(faq_id)) in self.faq_ids
        except (TypeError, ValueError):
            return False


EVERYTHING = Scope(all=True)


@dataclass(frozen=True)
class Disclosure:
    """이 턴에 이 비서가 지금 듣는 사람에게 쓸 수 있는 것. ``None`` 인 범위는 아무것도 없다는 뜻."""

    viewer: str = "owner"
    profile: bool = True
    knowledge: Scope | None = EVERYTHING
    knowledge_files: bool = True
    files: Scope | None = EVERYTHING
    network: Scope | None = EVERYTHING
    schedule: bool = True
    memory: bool = True
    visitors: bool = True
    web: bool = True

    @property
    def is_owner(self) -> bool:
        return self.viewer == "owner"


#: 나와의 대화 — 전부.
OWNER = Disclosure()
#: 아무것도 쓰지 않는 외부인 대화. 비서를 모를 때 기본값으로 쓴다 (좁은 쪽).
NOTHING = Disclosure(viewer="stranger", profile=False, knowledge=None, knowledge_files=False, files=None,
                     network=None, schedule=False, memory=False, visitors=False, web=False)


async def picked(db: AsyncSession, agent_id: uuid.UUID, kind: str) -> dict[str, set[uuid.UUID]]:
    """고른 것들 — 열 이름별로."""
    from blackmoa.models import AgentDisclosure

    cols = _COLUMNS[kind]
    out: dict[str, set[uuid.UUID]] = {c: set() for c in cols}
    rows = (await db.execute(select(*(getattr(AgentDisclosure, c) for c in cols))
                             .where(AgentDisclosure.agent_id == agent_id, AgentDisclosure.kind == kind))).all()
    for row in rows:
        for c, v in zip(cols, row, strict=True):
            if v is not None:
                out[c].add(v)
    return out


async def _self_node(db: AsyncSession, owner_id: uuid.UUID) -> uuid.UUID | None:
    from blackmoa.models import NetworkNode

    return (await db.execute(select(NetworkNode.id).where(NetworkNode.owner_id == owner_id,
                                                          NetworkNode.is_self.is_(True)))).scalars().first()


async def _knowledge_scope(db: AsyncSession, agent: Any, s: dict[str, Any], viewer: str) -> Scope | None:
    """지식 줄의 범위 — 늘 **이름을 댄** 문서·FAQ 목록이다 (``all`` 이 아니다).

    - 지식 줄이 닿으면: 고른 것(또는 [전부] 면 피드 글이 아닌 문서 전부와 FAQ 전부).
    - 정보 줄이 켜져 있으면: 피드 글의 사본 중 **그 글이 이 사람에게 보이는 것**. 피드 글은 프로필
      페이지에 실리는 것이라 [정보] 와 같은 층이다 — 글마다 정한 범위를 따르고, 여기서 고르지 않는다.
    """
    from blackmoa.models import BlogPost, KnowledgeDocument, KnowledgeFaq

    docs: set[uuid.UUID] = set()
    faqs: set[uuid.UUID] = set()
    reached = False
    if _level_reaches(s["knowledge"], viewer):
        reached = True
        if s["knowledge_scope"] == "all":
            docs |= set((await db.execute(select(KnowledgeDocument.id).where(
                KnowledgeDocument.owner_id == agent.owner_id, KnowledgeDocument.kind != "blog"))).scalars().all())
            faqs |= set((await db.execute(select(KnowledgeFaq.id).where(KnowledgeFaq.owner_id == agent.owner_id))).scalars().all())
        else:
            got = await picked(db, agent.id, "knowledge")
            docs |= got["document_id"]
            faqs |= got["faq_id"]
    if s["profile"]:
        reached = True
        docs |= set((await db.execute(select(BlogPost.knowledge_document_id).where(
            BlogPost.owner_id == agent.owner_id, BlogPost.status == "published", BlogPost.knowledge_document_id.isnot(None),
            BlogPost.visibility.in_([*VIS.readable_levels(viewer), *(["friends"] if viewer == "known" else [])])))).scalars().all())
    if not reached:
        return None
    return Scope(ids=frozenset(docs), faq_ids=frozenset(faqs))


async def scope(db: AsyncSession, agent: Any, key: str, viewer: str) -> Scope | None:
    """``key`` 줄에서 ``viewer`` 에게 쓸 수 있는 항목. 닿지 않으면 ``None``."""
    v = VIS.normalize_viewer(viewer)
    if v == "owner":
        return EVERYTHING
    s = settings(agent)
    if key == "knowledge":
        return await _knowledge_scope(db, agent, s, v)
    if not _level_reaches(s[key], v):
        return None
    if s[f"{key}_scope"] == "all":
        return EVERYTHING
    got = await picked(db, agent.id, key)
    ids = set(got[_COLUMNS[key][0]])
    if key == "network":
        # 주인 자신은 고르지 않아도 인맥의 한가운데다 — 인맥을 쓰는 순간 "누구를 아는가" 의 주어다.
        me = await _self_node(db, agent.owner_id)
        if me is not None:
            ids.add(me)
    return Scope(ids=frozenset(ids))


async def for_turn(db: AsyncSession, agent: Any, viewer: str) -> Disclosure:
    """이 턴의 :class:`Disclosure`. 주인이면 전부."""
    v = VIS.normalize_viewer(viewer)
    if v == "owner":
        return OWNER
    s = settings(agent)
    knowledge = await scope(db, agent, "knowledge", v)
    return Disclosure(
        viewer=v, profile=s["profile"], knowledge=knowledge,
        knowledge_files=_level_reaches(s["knowledge"], v) and s["knowledge_files"],
        files=await scope(db, agent, "files", v), network=await scope(db, agent, "network", v),
        schedule=_level_reaches(s["schedule"], v), memory=s["memory"], visitors=s["visitors"], web=s["web"])


def disclosure_of(ctx: Any) -> Disclosure:
    """대화 문맥에 붙은 것. 주인 대화면 전부, 붙지 않은 외부인 대화면 아무것도."""
    d = getattr(ctx, "disclosure", None)
    if isinstance(d, Disclosure):
        return d
    return OWNER if getattr(ctx, "audience", "") == "owner" else NOTHING


# ── 고르기 ──────────────────────────────────────────────────────────────────

async def _owned_ids(db: AsyncSession, agent: Any, column: str, ids: list[uuid.UUID]) -> list[uuid.UUID]:
    """고르려는 것이 정말 이 주인의 것인지. 남의 것을 가리키는 약속은 만들지 않는다."""
    from blackmoa.models import AgentFile, KnowledgeDocument, KnowledgeFaq, NetworkNode

    if not ids:
        return []
    if column == "document_id":
        # 피드 글의 사본은 고르지 않는다 — 그 글의 범위와 정보 줄이 정한다.
        q = select(KnowledgeDocument.id).where(KnowledgeDocument.owner_id == agent.owner_id, KnowledgeDocument.kind != "blog",
                                               KnowledgeDocument.id.in_(ids))
    elif column == "faq_id":
        q = select(KnowledgeFaq.id).where(KnowledgeFaq.owner_id == agent.owner_id, KnowledgeFaq.id.in_(ids))
    elif column == "file_id":
        # 파일은 계정의 것 — 이 비서가 받은 것만이 아니라 [내 정보 → 파일]의 주인 파일 무엇이든 이을 수 있다 (plan/77).
        q = select(AgentFile.id).where(AgentFile.owner_id == agent.owner_id, AgentFile.scope == "owner",
                                       AgentFile.deleted_at.is_(None), AgentFile.id.in_(ids))
    else:
        q = select(NetworkNode.id).where(NetworkNode.owner_id == agent.owner_id, NetworkNode.is_self.is_(False),
                                         NetworkNode.id.in_(ids))
    return list((await db.execute(q)).scalars().all())


def _uuids(values: list[Any] | None) -> list[uuid.UUID]:
    out = []
    for v in values or []:
        try:
            out.append(uuid.UUID(str(v)))
        except (TypeError, ValueError):
            raise ValidationFailed("bad id", code="bad_id") from None
    return out


async def set_picks(db: AsyncSession, agent: Any, kind: str, *, ids: list[Any] | None = None,
                    faq_ids: list[Any] | None = None) -> dict[str, int]:
    """``kind`` 줄에서 고른 것을 통째로 바꾼다 (지식은 문서와 FAQ 를 함께)."""
    from blackmoa.models import AgentDisclosure

    if kind not in SCOPED:
        raise ValidationFailed("unknown kind", code="bad_outsider_kind")
    wanted: dict[str, list[uuid.UUID]] = {}
    cols = _COLUMNS[kind]
    wanted[cols[0]] = await _owned_ids(db, agent, cols[0], _uuids(ids))
    if kind == "knowledge":
        wanted["faq_id"] = await _owned_ids(db, agent, "faq_id", _uuids(faq_ids))
    await db.execute(delete(AgentDisclosure).where(AgentDisclosure.agent_id == agent.id, AgentDisclosure.kind == kind))
    for col, vals in wanted.items():
        for v in dict.fromkeys(vals):
            db.add(AgentDisclosure(agent_id=agent.id, kind=kind, **{col: v}))
    await db.flush()
    return {col: len(set(vals)) for col, vals in wanted.items()}


async def pick(db: AsyncSession, agent_id: uuid.UUID, kind: str, **target: uuid.UUID) -> None:
    """하나를 더한다 — 이미 있으면 그대로. 인박스에서 가르친 답처럼 **외부인이 물은 것에 주인이
    답한 것**은 그 비서가 외부인에게 쓰는 목록에 저절로 들어간다."""
    from blackmoa.models import AgentDisclosure

    (col, value), = target.items()
    if col not in _COLUMNS.get(kind, ()):
        raise ValueError(f"{col} is not a {kind} target")
    exists = (await db.execute(select(AgentDisclosure.id).where(
        AgentDisclosure.agent_id == agent_id, getattr(AgentDisclosure, col) == value))).first()
    if exists is None:
        db.add(AgentDisclosure(agent_id=agent_id, kind=kind, **{col: value}))
        await db.flush()


async def counts(db: AsyncSession, agent_id: uuid.UUID) -> dict[str, int]:
    """줄마다 고른 개수 (지식은 문서+FAQ)."""
    from blackmoa.models import AgentDisclosure

    rows = (await db.execute(select(AgentDisclosure.kind, func.count()).where(AgentDisclosure.agent_id == agent_id)
                             .group_by(AgentDisclosure.kind))).all()
    return {k: int(n) for k, n in rows}
