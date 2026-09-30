"""AgentRuntime — a built pipeline + working state per (agent, audience, conversation). LRU + idle eviction."""
from __future__ import annotations

import asyncio
import secrets
import time
import uuid
from collections import OrderedDict
from dataclasses import dataclass, field
from typing import Any

from geny_executor import Pipeline, PipelineState
from geny_executor.stages.s03_system.artifact.default.builders import ComposablePromptBuilder
from geny_executor.tools.base import ToolContext
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from memora.config import get_settings
from memora.core.logging import get_logger
from memora.memory.facade import AgentMemory, vault_root
from memora.models import Agent, Conversation, Message, ModelCatalog, Plan, User, Visitor
from memora.pipeline import base_prompt as BP
from memora.pipeline.blocks import DynamicBlock, StaticBlock
from memora.pipeline.context import TurnContext
from memora.pipeline.manifest import build_manifest
from memora.pipeline.personas import compile_persona
from memora.pipeline.tools.base import ScopedToolProvider, core_overrides_for, tool_names_for
from memora.providers.llm.credentials import build_bundle
from memora.services import agents as AG
from memora.services import claude_pool as CP
from memora.services import outsider as OUT
from memora.services import profile as PF

log = get_logger("memora.runtime")
HISTORY_MESSAGES = 40


@dataclass
class AgentRuntime:
    key: str
    session_id: str
    agent_id: uuid.UUID
    audience: str
    conversation_id: uuid.UUID
    fingerprint: str
    pipeline: Pipeline
    state: PipelineState
    ctx: TurnContext
    provider: ScopedToolProvider
    blocks: dict[str, Any]
    bridge_token: str
    tool_names: list[str]
    context_window: int = 200_000
    # 그림을 볼 수 있는 모델인가. 못 보는 모델에 그림을 실으면 턴이 통째로 실패한다.
    vision: bool = True
    # What this session actually runs on. Kept because a session is the unit that holds
    # capacity, and "which model is that hour-old session pinned to" had no answer.
    llm_provider: str = ""
    model_id: str = ""
    # kept so the runner can recompose the owner/visitor sections with fresh state each turn
    owner_identity: Any = None
    resources: Any = None
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    last_used: float = field(default_factory=time.monotonic)
    turn_count: int = 0
    # The pooled Claude Code account this session is pinned to, held for the runtime's
    # whole life. Session affinity is not a nicety here: the CLI client is built with one
    # account's credentials, and its prompt cache belongs to that account.
    claude_lease: Any = None

    async def close(self) -> None:
        try:
            await self.pipeline.aclose()
        except Exception:  # noqa: BLE001
            pass
        if self.claude_lease is not None:
            self.claude_lease.release()
            self.claude_lease = None


def runtime_key(agent_id: uuid.UUID, audience: str, conversation_id: uuid.UUID) -> str:
    return f"{agent_id}:{audience}:{conversation_id}"


def _fingerprint(
    agent: Agent,
    cat: ModelCatalog,
    features: set[str],
    plan: Plan,
    turn_credit_cap: float | None = None,
) -> str:
    effective_cap = max(
        0.0001,
        float(turn_credit_cap if turn_credit_cap is not None else agent.turn_cost_cap_credits),
    )
    return "|".join([agent.updated_at.isoformat() if agent.updated_at else "", cat.provider, cat.model_id,
                     cat.updated_at.isoformat() if cat.updated_at else "", ",".join(sorted(features)),
                     str(agent.turn_cost_cap_credits), f"{effective_cap:.4f}"])


def _history_to_messages(msgs: list[Message]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for m in msgs:
        if m.role not in ("user", "assistant"):
            continue
        text = m.content or ""
        if m.role == "assistant" and m.cards:
            text += "\n" + "\n".join(f"[card:{c.get('card_type')}]" for c in m.cards)
        if not text.strip():
            continue
        if out and out[-1]["role"] == m.role:
            out[-1]["content"] += "\n\n" + text
        else:
            out.append({"role": m.role, "content": text})
    while out and out[0]["role"] != "user":
        out.pop(0)
    if out and out[-1]["role"] == "user":
        out.pop()
    return out



async def owner_identity(owner: User, profile, owner_name: str, *, audience: str = "owner",
                         policy: dict | None = None, share: bool = True) -> BP.OwnerIdentity:
    """The one-line identity the prompt opens with.

    It goes through the same visibility gate as the profile block: a visitor prompt that
    states "They are based in X" while the profile block says X is on-request has already
    disclosed it. ``share`` false (the 정보 row of the secretary's [지식] tab is off, plan/57)
    leaves the name and nothing else.
    """
    d = profile.data or {}

    def field(key: str) -> str:
        val = str(d.get(key) or "")[:80]
        if not val or audience != "visitor":
            return val
        if not share:
            return ""
        return val if PF.field_visibility(profile, policy or {}, key) == "public" else ""

    return BP.OwnerIdentity(name=AG.honorific(owner_name), full_name=field("full_name"),
                            title=field("title"), company=field("company"), location=field("location"),
                            timezone=owner.timezone or "Asia/Seoul", locale=owner.locale or "ko",
                            profile_shared=audience != "visitor" or share)


async def refresh_outsider(db: AsyncSession, res: BP.Resources, owner: User, agent: Agent, audience: str, profile,
                           disclosure: OUT.Disclosure | None = None) -> None:
    """지시문의 "주인이 준 것" 가운데 **턴마다 바뀌는 것**을 다시 채운다 (plan/56, plan/57).

    스케줄은 대화 도중에도 바뀌고(주인이 고치거나 비서가 일정을 넣는다), 외부인 대화에서 무엇을
    쓸지는 듣는 사람이 누구냐(모르는 사람/인맥)와 주인이 [지식] 탭에서 고른 것에 달렸다. 런타임을
    세울 때 한 번만 적으면 한 시간 전의 설정으로 답한다.

    외부인 대화에는 그 비서의 [지식] 탭이 허락한 것만 싣는다: 연락 가능 시간은 스케줄 줄, 연락 규칙은
    정보 줄(그 칸이 프로필에서 이 사람에게 보일 때), 지식 제목·인맥 수·건넬 파일 수는 고른 것만.
    """
    from datetime import UTC as _UTC
    from datetime import datetime as _dt
    from datetime import timedelta as _td

    from memora.models import KnowledgeDocument, NetworkNode
    from memora.services import schedule as SCH

    d = profile.data or {}
    dis = disclosure or (OUT.OWNER if audience == "owner" else OUT.NOTHING)
    langs = d.get("languages")
    langs_shown = dis.is_owner or (dis.profile and PF.visible_to(PF.field_visibility(profile, {}, "languages"), dis.viewer))
    res.languages = [str(x)[:24] for x in langs[:6]] if isinstance(langs, list) and langs_shown else []
    win = d.get("availability_window")
    res.availability_window = PF.render_window(win) if win and (dis.is_owner or dis.schedule) else None
    rules = d.get("contact_rules")
    rules_shown = dis.is_owner or (dis.profile and PF.visible_to(PF.field_visibility(profile, {}, "contact_rules"), dis.viewer))
    res.contact_rules = rules[:300] if isinstance(rules, str) and rules_shown else ""
    if audience == "owner":
        now = _dt.now(_UTC)
        res.schedule_week = len(await SCH.events_between(db, owner, now, now + _td(days=7), limit=200))
        return
    # 외부인 대화: 고른 것만 센다.
    k = dis.knowledge
    if k is None:
        res.knowledge_docs, res.knowledge_titles, res.files_shareable = 0, [], 0
    else:
        q = select(KnowledgeDocument.title, KnowledgeDocument.kind).where(KnowledgeDocument.owner_id == owner.id,
                                                                          KnowledgeDocument.status == "ready")
        if not k.all:
            q = q.where(KnowledgeDocument.id.in_(list(k.ids) or [uuid.uuid4()]))
        docs = (await db.execute(q.order_by(KnowledgeDocument.created_at.desc()).limit(40))).all()
        res.knowledge_docs = len(docs)
        res.knowledge_titles = [t for t, _kind in docs[:8] if t]
        res.files_shareable = sum(1 for _t, kind in docs if kind == "file") if dis.knowledge_files else 0
    n = dis.network
    if n is None:
        res.network_nodes = 0
    else:
        q = select(func.count(NetworkNode.id)).where(NetworkNode.owner_id == owner.id, NetworkNode.is_self.is_(False))
        if not n.all:
            q = q.where(NetworkNode.id.in_(list(n.ids) or [uuid.uuid4()]))
        res.network_nodes = int((await db.execute(q)).scalar_one() or 0)


async def collect_resources(db: AsyncSession, owner: User, agent: Agent, audience: str, profile) -> BP.Resources:
    """Only what is actually configured — an unset resource is left out of the prompt entirely,
    so the model never chases a knowledge base or a calendar that does not exist.

    나와의 대화에는 내 것이 전부 들어간다. 외부인 대화의 것은 :func:`refresh_outsider` 가
    그 비서의 [지식] 탭대로 채운다 (여기서는 모르는 사람을 기준으로 먼저, 턴마다 다시).
    """
    from memora.models import KnowledgeDocument, NetworkNode, NotificationChannel, ShareLink
    from memora.services import mail as MAIL

    res = BP.Resources()
    if audience == "owner":
        docs = (await db.execute(select(KnowledgeDocument.title).where(
            KnowledgeDocument.owner_id == owner.id, KnowledgeDocument.status == "ready")
            .order_by(KnowledgeDocument.created_at.desc()).limit(40))).scalars().all()
        res.knowledge_docs = len(docs)
        res.knowledge_titles = [t for t in docs[:8] if t]
        # 비서는 내 인맥을 본다 (plan/48 §2). 외부인에게 누구를 쓸지는 [지식] 탭이 정한다 (plan/57).
        res.network_nodes = int((await db.execute(
            select(func.count(NetworkNode.id)).where(NetworkNode.owner_id == owner.id))).scalar_one() or 0)
        # 메일은 [내 정보 → 메일] 을 거친다 (plan/57) — Google 에 직접 닿지 않는다.
        res.mail_accounts = [f"{a['provider_label']} ({a['account']})" if a["account"] else a["provider_label"]
                             for a in await MAIL.accounts(db, owner.id) if a["can_read"]]
        # 캘린더는 비서의 능력이 아니라 스케줄의 일부다 — [연동] 에서 가져오기를 켠 달력이 붙는다 (plan/56·58).
        from memora.services import calendar_sources as CS
        res.external_calendars = [s["label_en"] for s in await CS.sources(db, owner.id)
                                  if s.get("connected") and s.get("read") and s.get("status") == "active"]
    disclosure = OUT.OWNER if audience == "owner" else await OUT.for_turn(db, agent, "stranger")
    await refresh_outsider(db, res, owner, agent, audience, profile, disclosure)
    if audience == "visitor":
        chans = (await db.execute(select(NotificationChannel).where(NotificationChannel.owner_id == owner.id,
                                                                    NotificationChannel.enabled.is_(True)))).scalars().all()
        res.notification_channels = sorted({c.kind for c in chans})
    res.share_links = int((await db.execute(select(func.count(ShareLink.id)).where(
        ShareLink.agent_id == agent.id, ShareLink.status == "active"))).scalar_one() or 0)
    return res



@dataclass
class ComposedPrompt:
    """The two prompt layers in the order they are sent.

    The runtime and the owner-facing preview both go through here: a preview assembled
    from its own copy of the text drifts silently, which is exactly how the console came
    to show a disclosure level the product no longer has.
    """

    base: dict[str, str]
    secretary: str
    owner: BP.OwnerIdentity
    resources: BP.Resources

    # Order is load-bearing: everything stable comes first and forms the cached prefix, and
    # the executor routes blocks after the first volatile one into session context — so a
    # volatile block placed above the secretary layer would push it out of the system prompt.
    STABLE = ("base_mission", "base_owner", "base_tools", "base_resources", "base_rules", "base_relay", "base_answering")

    def ordered(self) -> list[tuple[str, str]]:
        out = [(n, self.base[n]) for n in self.STABLE if n in self.base]
        out.append(("secretary", self.secretary))
        if "base_visitor" in self.base:  # volatile: who the visitor is can change mid-conversation
            out.append(("base_visitor", self.base["base_visitor"]))
        return out


async def compose_prompt(db: AsyncSession, *, owner: User, agent: Agent, audience: str, profile,
                         tool_names: list[str], hidden_tools: set[str], relay_side: str | None = None) -> ComposedPrompt:
    owner_name = PF.display_name(profile, owner, audience=audience, policy=agent.disclosure_policy or {})
    persona_text = compile_persona(agent.persona or {}, agent_name=agent.name, owner_name=owner_name,
                                   role_line=agent.role_line or "", language=agent.language or "auto")
    share = audience == "owner" or OUT.settings(agent)["profile"]
    owner_ident = await owner_identity(owner, profile, owner_name, audience=audience, policy=agent.disclosure_policy or {},
                                       share=share)
    resources = await collect_resources(db, owner, agent, audience, profile)
    role_line = AG.display_texts(agent, owner_name)[1]
    # Layer 1: composed by the service from configured values only, always English.
    base = BP.compose(agent_name=agent.name, role_line=role_line, audience=audience, owner=owner_ident,
                      profile_text=PF.render_profile(profile, agent.disclosure_policy or {}, audience, share=share),
                      tool_names=tool_names, resources=resources, language=agent.language or "auto", visitor=None,
                      hidden_tools=hidden_tools, relay_side=relay_side)
    # Layer 2: persona + the owner's own words, in the owner's language.
    return ComposedPrompt(base=base, secretary=BP.secretary_layer(persona_text, agent.custom_instructions or ""),
                          owner=owner_ident, resources=resources)


class RuntimeRegistry:
    def __init__(self) -> None:
        self._items: OrderedDict[str, AgentRuntime] = OrderedDict()
        self._by_token: dict[str, AgentRuntime] = {}
        self._build_locks: dict[str, asyncio.Lock] = {}
        self._lock = asyncio.Lock()

    async def by_token(self, session_id: str, token: str) -> AgentRuntime | None:
        rt = self._by_token.get(token)
        if rt is None or rt.session_id != session_id:
            return None
        rt.last_used = time.monotonic()
        return rt

    async def get_or_create(self, db: AsyncSession, *, owner: User, agent: Agent, audience: str, conversation: Conversation,
                            cat: ModelCatalog, plan: Plan, visitor: Visitor | None = None,
                            turn_credit_cap: float | None = None) -> AgentRuntime:
        key = runtime_key(agent.id, audience, conversation.id)
        features = await self._features(db, owner, agent)
        effective_cap = max(0.0001, float(turn_credit_cap if turn_credit_cap is not None else agent.turn_cost_cap_credits))
        fp = _fingerprint(agent, cat, features, plan, effective_cap)
        lock = self._build_locks.setdefault(key, asyncio.Lock())
        async with lock:
            rt = self._items.get(key)
            if rt is not None and rt.fingerprint == fp:
                rt.last_used = time.monotonic()
                self._items.move_to_end(key)
                return rt
            if rt is not None:
                await self._drop(key)
            rt = await self._build(db, owner=owner, agent=agent, audience=audience, conversation=conversation, cat=cat, plan=plan,
                                   visitor=visitor, features=features, fingerprint=fp, key=key, turn_credit_cap=effective_cap)
            async with self._lock:
                self._items[key] = rt
                self._by_token[rt.bridge_token] = rt
                while len(self._items) > get_settings().runtime_max_sessions:
                    old_key, _ = next(iter(self._items.items()))
                    await self._drop(old_key)
            return rt

    async def _features(self, db: AsyncSession, owner: User, agent: Agent) -> set[str]:
        """바깥에 붙은 것. 메일은 비서의 스위치가 아니라 [내 정보 → 메일] 에 메일함이 있느냐다 (plan/57).
        기업 정보는 관리자가 기업 기능을 켜 두었느냐다 (plan/71) — 지문에 들어가 바뀌면 런타임을 다시 세운다."""
        from memora.services import mail as MAIL
        from memora.services.companies import switch as CO

        feats: set[str] = set()
        if await MAIL.readable(db, owner.id):
            feats.add("feature:mail")
        if await CO.enabled(db):
            feats.add("feature:companies")
        return feats

    async def _build(self, db: AsyncSession, *, owner: User, agent: Agent, audience: str, conversation: Conversation,
                     cat: ModelCatalog, plan: Plan, visitor: Visitor | None, features: set[str], fingerprint: str, key: str,
                     turn_credit_cap: float) -> AgentRuntime:
        session_id = str(uuid.uuid5(uuid.NAMESPACE_URL, key))
        bridge_token = secrets.token_hex(32)
        profile = await PF.shown(db, owner.id)
        memory = AgentMemory(agent.id, audience, visitor.id if visitor else None)
        ctx = TurnContext(owner=owner, agent=agent, audience=audience, conversation_id=conversation.id, turn_id=None,
                          profile=profile, plan=plan, memory=memory, visitor=visitor, features=set(features),
                          private_literals=PF.private_literals(profile, agent.disclosure_policy or {}), locale=owner.locale or "ko",
                          relay_id=getattr(conversation, "relay_id", None),
                          vision=bool(getattr(cat, "supports_vision", True)))
        provider = ScopedToolProvider(ctx)
        tool_names = tool_names_for(ctx)
        usd_per_credit = 0.001
        try:
            from memora.services import settings as S
            usd_per_credit = float(await S.get(db, "credits.usd_per_credit") or 0.001)
        except Exception:
            pass
        # The provider budget tracks the DB hold for this turn, so a runaway turn cannot
        # spend far past what was reserved. The floor exists because the billing boundary
        # is the hold, not this number: settle_turn charges min(actual, hold), so on a
        # nearly-empty account (0.1-credit minimum hold ⇒ $0.0001) a floor-less budget would
        # truncate a legitimate final answer mid-sentence instead of letting it finish and
        # then refusing the *next* turn with a clean 402.
        cap_usd = max(0.02, turn_credit_cap * max(0.000001, usd_per_credit))
        core_map = core_overrides_for(ctx)
        manifest = build_manifest(agent, cat, audience=audience, tool_names=tool_names, core_overrides=core_map,
                                  turn_cost_cap_usd=cap_usd)
        cwd = vault_root(agent.id) / "cli-cwd"
        cwd.mkdir(parents=True, exist_ok=True)
        # One account is leased per session build. A pool that has nothing to give returns
        # None and the build falls back to the single shared credential, which is what an
        # install without a pool has always used.
        lease = await CP.acquire(db, purpose="session") if agent.provider == "claude_code" else None
        try:
            creds = await build_bundle(db, agent.provider, session_id=session_id, bridge_token=bridge_token, cwd=str(cwd),
                                       max_budget_usd=cap_usd, timeout_s=600.0, lease=lease)
            pipeline = await Pipeline.from_manifest_async(manifest, credentials=creds, adhoc_providers=[provider],
                                                          satisfied_config=set(features) | {"feature:memora"}, strict=False)
        except Exception:
            if lease is not None:
                lease.release()   # a build that never became a runtime must not hold a slot forever
            raise
        _configure_chains(pipeline, audience)
        hidden_tools = {n for n, is_core in core_map.items() if not is_core}
        relay_side = None
        if getattr(conversation, "relay_id", None):
            from memora.services import relay as RELAY
            relay_side = await RELAY.side_for_conversation(db, conversation.relay_id, conversation.id)
        composed = await compose_prompt(db, owner=owner, agent=agent, audience=audience, profile=profile,
                                        tool_names=tool_names, hidden_tools=hidden_tools, relay_side=relay_side)
        owner_ident, resources = composed.owner, composed.resources
        blocks: dict[str, Any] = {}
        for name, text in composed.ordered():
            if name in ("base_owner", "base_resources"):  # the runner refreshes both each turn (profile, schedule)
                blocks[name] = DynamicBlock(name)
                blocks[name].__class__ = _StableDynamicBlock
                blocks[name].text = text
            elif name == "base_visitor":
                blocks[name] = DynamicBlock(name)
                blocks[name].text = text
            else:
                blocks[name] = StaticBlock(name, text)
        # 파일 목록은 새 파일이 올 때만 바뀐다. 턴마다 바뀌는 live 보다 앞에 둬야 캐시가 산다.
        blocks.update({"facts": DynamicBlock("facts"), "relationship": DynamicBlock("relationship"), "relay": DynamicBlock("relay"),
                       "files": DynamicBlock("files"), "live": DynamicBlock("live"), "memory": DynamicBlock("memory")})
        builder = ComposablePromptBuilder(list(blocks.values()))
        tool_ctx = ToolContext(session_id=session_id, working_dir=str(cwd), storage_path=str(vault_root(agent.id)),
                               allowed_paths=[str(cwd)], extras={"memora": ctx})
        pipeline.attach_runtime(system_builder=builder, tool_context=tool_ctx)
        state = PipelineState(session_id=session_id)
        hist = (await db.execute(select(Message).where(Message.conversation_id == conversation.id)
                                 .order_by(Message.created_at.desc()).limit(HISTORY_MESSAGES))).scalars().all()
        state.messages = _history_to_messages(list(reversed(hist)))
        rt = AgentRuntime(key=key, session_id=session_id, agent_id=agent.id, audience=audience, conversation_id=conversation.id,
                          fingerprint=fingerprint, pipeline=pipeline, state=state, ctx=ctx, provider=provider, blocks=blocks,
                          bridge_token=bridge_token, tool_names=tool_names, context_window=int(cat.context_window or 200_000),
                          llm_provider=cat.provider, model_id=cat.model_id,
                          vision=bool(getattr(cat, "supports_vision", True)))
        rt.owner_identity, rt.resources = owner_ident, resources
        rt.claude_lease = lease
        log.info("runtime built", key=key, provider=agent.provider, model=cat.model_id, tools=len(tool_names), history=len(state.messages),
                 turn_credit_cap=turn_credit_cap, max_budget_usd=cap_usd, claude_account=lease.label if lease else None)
        return rt

    async def drop(self, key: str) -> None:
        """Public form of ``_drop`` — the runner uses it to abandon a session whose leased
        account just went out of rotation, so the next turn rebuilds on a healthy one."""
        async with self._lock:
            await self._drop(key)

    async def _drop(self, key: str) -> None:
        rt = self._items.pop(key, None)
        lock = self._build_locks.get(key)
        if lock is not None and not lock.locked():
            self._build_locks.pop(key, None)  # per-key build locks must not grow with every conversation ever seen
        if rt is None:
            return
        self._by_token.pop(rt.bridge_token, None)
        await rt.close()

    async def drop_conversation(self, agent_id: uuid.UUID, conversation_id: uuid.UUID) -> None:
        for aud in ("owner", "visitor"):
            await self._drop(runtime_key(agent_id, aud, conversation_id))

    async def drop_agent(self, agent_id: uuid.UUID) -> None:
        for key in [k for k in self._items if k.startswith(f"{agent_id}:")]:
            await self._drop(key)

    async def evict_idle(self, idle_seconds: float) -> int:
        now = time.monotonic()
        n = 0
        for key in [k for k, rt in self._items.items() if now - rt.last_used > idle_seconds and not rt.lock.locked()]:
            await self._drop(key)
            n += 1
        return n

    def count(self) -> int:
        return len(self._items)

    def snapshot(self) -> list[dict[str, Any]]:
        """What every live session is and what it is holding.

        A session pins a CLI process, a pooled account and that account's prompt cache for
        its whole life, so "how many" was never the useful number — which agent, on which
        account, idle for how long is. Newest first, because a session that has just been
        built is the one someone is usually asking about.
        """
        now = time.monotonic()
        out: list[dict[str, Any]] = []
        for key, rt in self._items.items():
            lease = rt.claude_lease
            out.append({
                "key": key, "session_id": rt.session_id, "agent_id": str(rt.agent_id),
                "conversation_id": str(rt.conversation_id), "audience": rt.audience,
                "turns": rt.turn_count, "idle_s": round(now - rt.last_used, 1),
                "busy": rt.lock.locked(), "tools": len(rt.tool_names),
                "context_window": rt.context_window,
                "account": getattr(lease, "label", "") if lease is not None else "",
                "account_held_s": round(time.time() - lease.acquired_at, 1) if lease is not None else None,
                "provider": rt.llm_provider, "model": rt.model_id,
            })
        out.sort(key=lambda r: r["idle_s"])
        return out

    async def close_key(self, key: str) -> bool:
        """Close one session and give back everything it holds.

        A session pins a CLI process and a pooled account for its whole life, so a wedged
        one is capacity nobody else can have. Without this the only way to reclaim it was
        restarting the process, which takes every other conversation with it.
        """
        if key not in self._items:
            return False
        await self._drop(key)
        return True

    async def close_all(self) -> None:
        for key in list(self._items):
            await self._drop(key)


def _configure_chains(pipeline: Pipeline, audience: str) -> None:
    """Guards must be populated at runtime (the default chain is empty and manifest
    ``chain_order`` can only reorder — plan/25 D-30); reviewers are trimmed to what we need."""
    import contextlib
    s4 = pipeline.get_stage(4)
    if s4 is not None:
        with contextlib.suppress(Exception):
            existing = {getattr(i, "name", "") for i in s4.get_strategy_chains()["guards"].items}
            for g in ("token_budget", "cost_budget", "iteration"):
                if g not in existing:
                    s4.add_to_chain("guards", g)
    s11 = pipeline.get_stage(11)
    if s11 is not None:
        keep = {"size", "sensitive"} if audience == "visitor" else {"size"}
        with contextlib.suppress(Exception):
            for item in list(s11.get_strategy_chains()["reviewers"].items):
                if getattr(item, "name", "") not in keep:
                    s11.remove_from_chain("reviewers", getattr(item, "name", ""))


class _StableDynamicBlock(DynamicBlock):
    @property
    def volatile(self) -> bool:
        return False


runtimes = RuntimeRegistry()
