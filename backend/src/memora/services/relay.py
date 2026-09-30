"""Secretary-to-secretary conversations (plan/38).

One secretary, told to by its owner, speaks to another owner's secretary through that
secretary's public link. Both sides run the ordinary visitor pipeline — the other
secretary is a visitor, with everything that means for disclosure — and every message is
kept twice: in each side's own conversation, and in order in the relay ledger.

The exchange ends when either side says it is done (``relay_close``), when the message or
credit budget is spent, when the two are only trading pleasantries, when the link closes
under it, when it stalls, or when an owner stops it. It never runs unattended for long.
"""
from __future__ import annotations

import contextlib
import hashlib
import hmac
import re
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from memora.config import get_settings
from memora.core.errors import Conflict, MemoraError, NotFound, ValidationFailed
from memora.core.logging import get_logger
from memora.models import (
    Agent,
    AgentRelay,
    AgentRelayMessage,
    Conversation,
    RelayCandidate,
    ShareLink,
    Turn,
    User,
    Visitor,
)

log = get_logger("memora.relay")

SIDES = ("initiator", "target")
REASONS = ("done", "refused", "target_resting", "target_busy", "max_messages", "credit_cap", "link_closed", "resting",
           "stalled", "expired", "error", "owner_stop")
_ACK = re.compile(r"(감사(합니다|해요|드려요|드립니다)?|고맙(습니다|워요)?|고마워|알겠(습니다|어요)?|넵|네|좋아요|좋습니다|천만에요?|안녕히\s*(가세요|계세요)?|"
                  r"수고(하세요|하셨어요)?|살펴\s*가세요|thank(s| you)?|okay|\bok\b|bye|goodbye|got it|sounds good|you'?re welcome|noted|cheers|"
                  r"확인했(습니다|어요)|그럼요|다음에\s*또)", re.I)
_ACK_NOISE = re.compile(r"[\s\.,!~^:;\-–—'\"()\[\]…]+|합니다|입니다|해요|요$")
_LINK_RE = re.compile(r"/secretary/([a-z0-9][a-z0-9-]{1,30}[a-z0-9])", re.I)
_TZ_DAY = "Asia/Seoul"


# ── settings ───────────────────────────────────────────────────────────────────

async def _cfg(db: AsyncSession) -> dict[str, Any]:
    from memora.services import settings as S
    keys = ("relay.enabled", "relay.max_messages", "relay.hard_max_messages", "relay.default_credit_cap", "relay.hop_delay_s",
            "relay.threads_per_day", "relay.stall_minutes", "relay.expire_hours")
    return {k.split(".", 1)[1]: await S.get(db, k) for k in keys}


def link_settings(link: ShareLink) -> dict[str, Any]:
    """The relay half of a link's settings, normalised: may other secretaries talk to this
    one, and how many of their turns a day the owner is willing to pay for."""
    s = link.settings or {}
    try:
        cap = max(0, min(500, int(s.get("agent_turns_per_day", 20))))
    except (TypeError, ValueError):
        cap = 20
    return {"allow_agents": bool(s.get("allow_agents", True)), "agent_turns_per_day": cap,
            # May another owner's secretary find this link by the owner's name (plan/39)? Only
            # meaningful while allow_agents is on.
            "findable": bool(s.get("findable", True))}


def parse_target(target: str) -> str:
    t = (target or "").strip()
    m = _LINK_RE.search(t)
    if m:
        return m.group(1).lower()
    t = t.strip("/").split("?")[0].split("/")[-1].lower()
    if not re.fullmatch(r"[a-z0-9][a-z0-9-]{1,30}[a-z0-9]", t):
        raise ValidationFailed("give the other secretary's public link (URL or code)", code="relay_bad_target")
    return t


def internal_token() -> str:
    return hmac.new(get_settings().secret_key.encode(), b"memora-internal-relay", hashlib.sha256).hexdigest()


def other(side: str) -> str:
    return "target" if side == "initiator" else "initiator"


async def side_for_conversation(db: AsyncSession, relay_id: uuid.UUID, conversation_id: uuid.UUID) -> str | None:
    relay = await db.get(AgentRelay, relay_id)
    return side_of(relay, conversation_id) if relay else None


def side_of(relay: AgentRelay, conversation_id: uuid.UUID) -> str | None:
    if relay.initiator_conversation_id == conversation_id:
        return "initiator"
    if relay.target_conversation_id == conversation_id:
        return "target"
    return None


def is_ack(text: str) -> bool:
    """A message that only says thanks/ok/bye — the kind two polite machines can trade forever.

    Short, no question, and once the courtesy words are taken out there is nothing left."""
    t = (text or "").strip()
    if not t or len(t) > 60 or "?" in t or not _ACK.search(t):
        return False
    rest = _ACK_NOISE.sub("", _ACK.sub("", t))
    return len(rest) <= 4


def redact(text: str, literals: list[str]) -> str:
    out = text
    for lit in sorted({x for x in literals if x and len(x) >= 3}, key=len, reverse=True):
        out = out.replace(lit, "[비공개]")
    return out


async def _day_start_utc() -> datetime:
    from zoneinfo import ZoneInfo
    now = datetime.now(ZoneInfo(_TZ_DAY))
    return now.replace(hour=0, minute=0, second=0, microsecond=0).astimezone(UTC)


async def _enqueue_hop(db: AsyncSession, relay: AgentRelay, *, delay_s: float, owner_id: uuid.UUID | None = None) -> None:
    from memora.services import jobs as J
    # One key per hop, not per relay: the previous hop's job may still be marked running
    # when the turn it started has already finished, and the next hop must not be swallowed
    # by that. The sweep re-uses the same key, so a retry never doubles a queued hop.
    await J.enqueue(db, "relay.hop", {"relay_id": str(relay.id)}, delay_s=delay_s, priority=4,
                    dedupe_key=f"relay-hop:{relay.id}:{relay.message_count}", owner_id=owner_id)


async def _spent(db: AsyncSession, conversation_id: uuid.UUID | None) -> float:
    if conversation_id is None:
        return 0.0
    return float((await db.execute(select(func.coalesce(func.sum(Turn.credits), 0)).where(Turn.conversation_id == conversation_id))).scalar_one() or 0)


async def _link_agent_turns_today(db: AsyncSession, link_id: uuid.UUID) -> int:
    since = await _day_start_utc()
    return int((await db.execute(select(func.count(Turn.id)).join(Conversation, Conversation.id == Turn.conversation_id)
                                 .where(Conversation.share_link_id == link_id, Conversation.kind == "agent", Turn.started_at >= since))).scalar_one() or 0)


async def _record(db: AsyncSession, relay: AgentRelay, *, side: str, agent_id: uuid.UUID | None, kind: str, content: str,
                  turn_id: uuid.UUID | None = None) -> AgentRelayMessage:
    seq = int((await db.execute(select(func.coalesce(func.max(AgentRelayMessage.seq), 0)).where(AgentRelayMessage.relay_id == relay.id))).scalar_one()) + 1
    m = AgentRelayMessage(relay_id=relay.id, seq=seq, side=side, agent_id=agent_id, kind=kind, content=content[:2000], turn_id=turn_id,
                          created_at=datetime.now(UTC))
    db.add(m)
    if side in SIDES:
        relay.message_count = (relay.message_count or 0) + 1
        relay.last_message_at = m.created_at
    await db.flush()
    return m


def _delivered(relay: AgentRelay, side: str) -> int:
    return int((relay.delivered_seq_initiator if side == "initiator" else relay.delivered_seq_target) or 0)


def _mark_delivered(relay: AgentRelay, side: str, seq: int) -> None:
    if side == "initiator":
        relay.delivered_seq_initiator = max(int(relay.delivered_seq_initiator or 0), seq)
    else:
        relay.delivered_seq_target = max(int(relay.delivered_seq_target or 0), seq)


def _conv_id(relay: AgentRelay, side: str) -> uuid.UUID | None:
    return relay.initiator_conversation_id if side == "initiator" else relay.target_conversation_id


async def _sync_transcripts(db: AsyncSession, relay: AgentRelay) -> int:
    """Make each side's conversation contain every ledger message, in order.

    On the normal path a message reaches the other side when that side's turn starts (it is
    the turn's user message). When the exchange closes before that turn — link revoked,
    budget spent, an owner stopped it, it expired — the message would exist only in the
    ledger. This appends it, so what an owner reads in their secretary's history is the
    whole exchange, whichever way it ended."""
    from memora.services import conversations as CV
    msgs = (await db.execute(select(AgentRelayMessage).where(AgentRelayMessage.relay_id == relay.id, AgentRelayMessage.side.in_(SIDES))
                             .order_by(AgentRelayMessage.seq))).scalars().all()
    added = 0
    for side in SIDES:
        cid = _conv_id(relay, side)
        if cid is None:
            continue
        conv = await db.get(Conversation, cid)
        if conv is None:
            continue
        have = _delivered(relay, side)
        for m in msgs:
            if m.seq <= have:
                continue
            # Its own lines are written by its own turns; only the other side's need carrying over.
            if m.side != side:
                await CV.add_message(db, conv, role="user", content=m.content)
                conv.unread_owner = True
                added += 1
            _mark_delivered(relay, side, m.seq)
    return added


async def _last_message(db: AsyncSession, relay: AgentRelay, *, side: str | None = None) -> AgentRelayMessage | None:
    stmt = select(AgentRelayMessage).where(AgentRelayMessage.relay_id == relay.id, AgentRelayMessage.side.in_(SIDES))
    if side:
        stmt = stmt.where(AgentRelayMessage.side == side)
    return (await db.execute(stmt.order_by(AgentRelayMessage.seq.desc()).limit(1))).scalars().first()


# ── start ──────────────────────────────────────────────────────────────────────

async def start(db: AsyncSession, *, owner: User, agent: Agent, target: str, message: str, purpose: str = "",
                origin_conversation_id: uuid.UUID | None = None, origin_turn_id: uuid.UUID | None = None,
                max_messages: int | None = None, credit_cap: float | None = None,
                candidate_id: uuid.UUID | None = None) -> AgentRelay:
    """The initiator's owner asked their secretary to talk to another. Creates the ledger,
    both sides' conversations, records the opener, and queues the first hop — or refuses
    on the spot when the other link does not take secretaries."""
    from memora.core.security import sha256
    from memora.services import agents as AG
    from memora.services import conversations as CV
    from memora.services import credits as CR
    from memora.services import profile as PF

    cfg = await _cfg(db)
    if not cfg["enabled"]:
        raise Conflict("secretary conversations are switched off", code="relay_disabled")
    if agent.status != "active":
        raise Conflict("agent is not active", code="agent_not_active")
    text = (message or "").strip()
    if not text:
        raise ValidationFailed("message required", code="relay_empty")
    if (await CR.available_balance(db, owner.id)) <= 0:
        raise Conflict("not enough credits", code="insufficient_credits")
    since = await _day_start_utc()
    n_today = int((await db.execute(select(func.count(AgentRelay.id)).where(AgentRelay.initiator_owner_id == owner.id,
                                                                            AgentRelay.created_at >= since))).scalar_one())
    if n_today >= int(cfg["threads_per_day"]):
        raise Conflict("daily limit of secretary conversations reached", code="relay_daily_cap", detail={"max": int(cfg["threads_per_day"])})
    code = await _resolve_code(db, owner=owner, target=target, candidate_id=candidate_id,
                               origin_conversation_id=origin_conversation_id, origin_turn_id=origin_turn_id)
    link = await AG.get_link_by_code(db, code)
    if link is None:
        raise NotFound("public link not found", code="link_not_found")
    target_agent = await db.get(Agent, link.agent_id)
    target_owner = await db.get(User, link.owner_id)
    if target_agent is None or target_owner is None or target_owner.status != "active":
        raise NotFound("public link not found", code="link_not_found")
    if target_owner.id == owner.id:
        raise ValidationFailed("that is your own secretary — just talk to it", code="relay_self")
    status = AG.link_effective_status(link, target_agent)
    if status != "active":
        raise Conflict("that link is not active", code=f"link_{status}")
    # The same owner knocking on the same door: twice a day is a conversation, more is a nuisance.
    # Counted per secretary, not per link — a second link to the same secretary is the same door.
    n_target = int((await db.execute(select(func.count(AgentRelay.id)).where(AgentRelay.initiator_owner_id == owner.id,
                                                                             AgentRelay.target_agent_id == target_agent.id,
                                                                             AgentRelay.created_at >= since))).scalar_one())
    if n_target >= 2:
        raise Conflict("you already reached this secretary twice today", code="relay_target_cap", detail={"max": 2})

    hard = int(cfg["hard_max_messages"])
    mm = int(max_messages or cfg["max_messages"])
    mm = max(2, min(hard, mm))
    cap = float(credit_cap if credit_cap is not None else cfg["default_credit_cap"])
    cap = max(1.0, min(500.0, cap))

    prof_x = await PF.get(db, owner.id)
    pol_x = agent.disclosure_policy or {}
    # Same rule as everything a secretary says outside: nothing private leaves, even if the
    # owner's instruction happened to contain it.
    opener = redact(text, PF.private_literals(prof_x, pol_x))[:2000]
    relay = AgentRelay(initiator_agent_id=agent.id, initiator_owner_id=owner.id, target_agent_id=target_agent.id, target_owner_id=target_owner.id,
                       target_link_id=link.id, origin_conversation_id=origin_conversation_id, origin_turn_id=origin_turn_id,
                       purpose=(purpose or "")[:600], opener=opener, max_messages=mm, credit_cap=cap, status="open")
    db.add(relay)
    await db.flush()

    ls = link_settings(link)
    if not ls["allow_agents"]:
        await _record(db, relay, side="system", agent_id=None, kind="system", content="상대 비서가 다른 비서의 문의를 받지 않도록 설정되어 있어요.")
        await _close(db, relay, by="system", reason="refused")
        return relay
    if (await CR.available_balance(db, target_owner.id)) <= 0:
        await _record(db, relay, side="system", agent_id=None, kind="system", content="상대 비서가 지금 쉬고 있어요(크레딧 부족).")
        await _close(db, relay, by="system", reason="target_resting")
        return relay
    if ls["agent_turns_per_day"] and await _link_agent_turns_today(db, link.id) >= ls["agent_turns_per_day"]:
        await _record(db, relay, side="system", agent_id=None, kind="system", content="상대 비서가 오늘 받을 수 있는 비서 문의 한도를 다 썼어요.")
        await _close(db, relay, by="system", reason="target_busy")
        return relay

    now = datetime.now(UTC)
    name_x = PF.display_name(prof_x, owner, audience="visitor", policy=pol_x)
    prof_y = await PF.get(db, target_owner.id)
    name_y = PF.display_name(prof_y, target_owner, audience="visitor", policy=target_agent.disclosure_policy or {})
    email_x = None
    with contextlib.suppress(Exception):
        vis, val = PF.disclosure_value(prof_x, pol_x, "contact.email")
        email_x = str(val)[:255] if vis == "public" and val else None
    # In B's world, A is a visitor; in A's world, B is. Both rows say plainly what they are.
    tv = Visitor(owner_id=target_owner.id, agent_id=target_agent.id, share_link_id=link.id, user_id=owner.id, token_hash=sha256(uuid.uuid4().hex),
                 display_name=f"{agent.name} ({name_x}의 비서)"[:120], email=email_x,
                 note="다른 회원의 비서(자동 응답)가 그 회원을 대신해 문의합니다. 사람이 아닙니다.",
                 kind="agent", peer_agent_id=agent.id, first_seen_at=now, last_seen_at=now, meta={"relay_id": str(relay.id)})
    iv = Visitor(owner_id=owner.id, agent_id=agent.id, share_link_id=None, user_id=target_owner.id, token_hash=sha256(uuid.uuid4().hex),
                 display_name=f"{target_agent.name} ({name_y}의 비서)"[:120], email=None,
                 note="내가 문의를 보낸 상대 회원의 비서(자동 응답)입니다. 사람이 아닙니다.",
                 kind="agent", peer_agent_id=target_agent.id, first_seen_at=now, last_seen_at=now, meta={"relay_id": str(relay.id)})
    db.add_all([tv, iv])
    await db.flush()
    tc = await CV.create(db, owner_id=target_owner.id, agent_id=target_agent.id, audience="visitor", visitor_id=tv.id, share_link_id=link.id,
                         title=f"[비서] {agent.name} · {name_x}")
    ic = await CV.create(db, owner_id=owner.id, agent_id=agent.id, audience="visitor", visitor_id=iv.id, title=f"[비서] → {target_agent.name} · {name_y}")
    for c in (tc, ic):
        c.kind, c.relay_id = "agent", relay.id
    link.conversation_count = (link.conversation_count or 0) + 1
    relay.target_visitor_id, relay.initiator_visitor_id = tv.id, iv.id
    relay.target_conversation_id, relay.initiator_conversation_id = tc.id, ic.id
    # The opener is what A said: it sits in A's own conversation as A's line.
    await CV.add_message(db, ic, role="assistant", content=opener, cards=[{"card_type": "relay_note", "payload": {"kind": "sent", "relay_id": str(relay.id)}}])
    opened = await _record(db, relay, side="initiator", agent_id=agent.id, kind="open", content=opener, turn_id=origin_turn_id)
    _mark_delivered(relay, "initiator", opened.seq)
    relay.hop_pending, relay.pending_since = "target", now
    await _enqueue_hop(db, relay, delay_s=float(cfg["hop_delay_s"]), owner_id=target_owner.id)
    log.info("relay started", relay_id=str(relay.id), initiator=str(agent.id), target=str(target_agent.id), max_messages=mm)
    return relay


# ── finding the other secretary by the owner's name (plan/39) ──────────────────

async def _resolve_code(db: AsyncSession, *, owner: User, target: str, candidate_id: uuid.UUID | None,
                        origin_conversation_id: uuid.UUID | None, origin_turn_id: uuid.UUID | None) -> str:
    """The link code to send to. A candidate found by secretary_find may be used only from a
    later turn than the one that found it — i.e. after the owner has spoken again — and the
    same holds when its code is handed over as a plain link."""
    cand: RelayCandidate | None = None
    if candidate_id is not None:
        cand = await db.get(RelayCandidate, candidate_id)
        if cand is None or cand.owner_id != owner.id:
            raise NotFound("candidate not found", code="candidate_not_found")
    else:
        code = parse_target(target)
        if origin_conversation_id is not None:
            cand = (await db.execute(select(RelayCandidate).where(RelayCandidate.owner_id == owner.id,
                                                                  RelayCandidate.conversation_id == origin_conversation_id,
                                                                  RelayCandidate.link_code == code)
                                     .order_by(RelayCandidate.created_at.desc()).limit(1))).scalars().first()
        if cand is None:
            return code
    if not cand.reachable or not cand.link_code:
        raise Conflict("that secretary does not take inquiries", code="candidate_unreachable")
    if origin_turn_id is not None and cand.turn_id == origin_turn_id:
        raise Conflict("ask the owner to confirm this person first — send from a later turn", code="confirm_first",
                       detail={"candidate_id": str(cand.id)})
    if origin_turn_id is None and cand.created_at > datetime.now(UTC) - timedelta(seconds=5):
        raise Conflict("ask the owner to confirm this person first", code="confirm_first", detail={"candidate_id": str(cand.id)})
    return cand.link_code


def _name_hit(q: str, *names: str | None) -> bool:
    ql = q.replace(" ", "").lower()
    return any(ql and ql in (n or "").replace(" ", "").lower() for n in names)


async def _reach(db: AsyncSession, target_user_id: uuid.UUID) -> list[dict[str, Any]]:
    """Every secretary of that member a stranger's secretary may reach: active, with an active
    link that takes secretaries and may be found by name."""
    out = []
    agents = (await db.execute(select(Agent).where(Agent.owner_id == target_user_id, Agent.status == "active"))).scalars().all()
    for a in agents:
        links = (await db.execute(select(ShareLink).where(ShareLink.agent_id == a.id, ShareLink.status == "active"))).scalars().all()
        for l_ in links:
            from memora.services import agents as AG
            ls = link_settings(l_)
            if AG.link_effective_status(l_, a) == "active" and ls["allow_agents"] and ls["findable"]:
                out.append({"agent_id": a.id, "agent_name": a.name, "code": l_.code})
                break
    return out


async def find_candidates(db: AsyncSession, *, owner: User, agent: Agent, query: str, conversation_id: uuid.UUID | None,
                          turn_id: uuid.UUID | None, limit: int = 6) -> list[dict[str, Any]]:
    """Who the owner might mean, from the strongest evidence down, each with whether their
    secretary can be reached. Every hit is recorded: sending to it needs a later turn."""
    from memora.models import NetworkNode
    from memora.services import people as P

    q = (query or "").strip()
    if len(q.replace(" ", "")) < 2:
        return []
    found: dict[uuid.UUID, str] = {}   # user_id -> strongest source
    # 1) members in my network (nodes bound to an account) whose name or alias matches
    nodes = (await db.execute(select(NetworkNode).where(NetworkNode.owner_id == owner.id, NetworkNode.user_id.isnot(None),
                                                        NetworkNode.is_self.is_(False)))).scalars().all()
    for n in nodes:
        if _name_hit(q, n.name, *(n.aliases or [])):
            found.setdefault(n.user_id, "network")
    # 2) 인맥: the people this owner and they each connected to (plan/43)
    friend_ids = list(await P._friend_ids(db, owner.id))
    if friend_ids:
        for u in (await db.execute(select(User).where(User.id.in_(friend_ids), User.status == "active"))).scalars().all():
            if _name_hit(q, u.display_name, u.nickname):
                found.setdefault(u.id, "friend")
    # 3) members who visited one of my secretaries
    visitors = (await db.execute(select(Visitor).where(Visitor.owner_id == owner.id, Visitor.user_id.isnot(None), Visitor.kind == "human"))).scalars().all()
    for v in visitors:
        if _name_hit(q, v.display_name):
            found.setdefault(v.user_id, "guest")
    # 4) the directory — by name, never as a listing
    for row in await P.directory_search(db, owner, q, limit=10, contains=True):
        uid = uuid.UUID(row["id"])
        if _name_hit(q, row.get("real_name"), row.get("display_name")):
            found.setdefault(uid, "directory")
    # 5) the name people actually know them by: a public profile name (preferred or full)
    from memora.models import OwnerProfile
    from memora.services import profile as PF
    esc = q.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    profs = (await db.execute(select(OwnerProfile).where(
        (OwnerProfile.data["preferred_name"].astext.ilike(f"%{esc}%", escape="\\")) |
        (OwnerProfile.data["full_name"].astext.ilike(f"%{esc}%", escape="\\"))).limit(20))).scalars().all()
    for prof in profs:
        if prof.owner_id == owner.id or prof.owner_id in found:
            continue
        d = prof.data or {}
        public = [d.get(k) for k in ("preferred_name", "full_name") if d.get(k) and PF.field_visibility(prof, {}, k) == "public"]
        if any(_name_hit(q, str(v)) for v in public):
            found.setdefault(prof.owner_id, "directory")
    # 6) the secretary's own name — "제니 비서한테" is how people talk. Only secretaries that
    #    can actually be reached this way, so this is not a way to enumerate agents.
    agents_named = (await db.execute(select(Agent).where(Agent.status == "active", Agent.owner_id != owner.id,
                                                          Agent.name.ilike(f"%{esc}%", escape="\\")).limit(20))).scalars().all()
    for ag in agents_named:
        if ag.owner_id not in found and any(r["agent_id"] == ag.id for r in await _reach(db, ag.owner_id)):
            found.setdefault(ag.owner_id, "secretary")
    return await _materialise(db, owner=owner, agent=agent, found=found, query=q,
                              conversation_id=conversation_id, turn_id=turn_id, limit=limit)


#: How sure we are that this is the person meant, best first. The topic sources sit last:
#: matching what somebody wrote is a reason to ask them, not a claim to know them.
SOURCE_ORDER = {"network": 0, "friend": 1, "guest": 2, "directory": 3, "secretary": 4, "wrote": 5, "profile": 6}


async def _materialise(db: AsyncSession, *, owner: User, agent: Agent, found: dict[uuid.UUID, str], query: str,
                       conversation_id: uuid.UUID | None, turn_id: uuid.UUID | None, limit: int,
                       why: dict[uuid.UUID, str] | None = None, reachable_only: bool = False) -> list[dict[str, Any]]:
    """Turn a set of people into candidates the owner can confirm.

    Every hit is written down, because sending is only allowed in a later turn than the one
    that found it: the model must not search and send in the same breath (plan/39).
    """
    from memora.services import people as P

    q = query
    order = SOURCE_ORDER
    out: list[dict[str, Any]] = []
    now = datetime.now(UTC)
    for uid, source in sorted(found.items(), key=lambda kv: order[kv[1]])[:limit]:
        if uid == owner.id:
            continue
        target = await db.get(User, uid)
        if target is None or target.status != "active":
            continue
        if reachable_only and not await _reach(db, uid):
            continue
        prof = await P.profile_of(db, owner, target)
        fields = prof.get("fields") or {}
        reach = await _reach(db, uid)
        # The name they go by publicly (profile), falling back to the account label.
        shown = fields.get("preferred_name") or fields.get("full_name") or prof.get("display_name") or target.display_name
        base = {"user_id": str(uid), "name": shown, "title": fields.get("title"),
                "company": fields.get("company"), "source": source,
                "why": (why or {}).get(uid, "")}
        rows = reach or [None]
        for r in rows:
            # The same person found again in the same conversation is the same candidate: the
            # model tends to search once more in the very turn the owner confirms, and that
            # must not reset the "found in an earlier turn" clock.
            cand = None
            if conversation_id is not None:
                cand = (await db.execute(select(RelayCandidate).where(
                    RelayCandidate.owner_id == owner.id, RelayCandidate.conversation_id == conversation_id,
                    RelayCandidate.target_user_id == uid, RelayCandidate.link_code == (r["code"] if r else None),
                    RelayCandidate.created_at >= now - timedelta(hours=24)).order_by(RelayCandidate.created_at).limit(1))).scalars().first()
            if cand is None:
                cand = RelayCandidate(owner_id=owner.id, agent_id=agent.id, conversation_id=conversation_id, turn_id=turn_id, query=q[:200],
                                      target_user_id=uid, target_agent_id=r["agent_id"] if r else None, link_code=r["code"] if r else None,
                                      source=source, reachable=bool(r), created_at=now,
                                      meta={"agent_name": r["agent_name"] if r else None, "title": base["title"], "company": base["company"]})
                db.add(cand)
                await db.flush()
            out.append({**base, "candidate_id": str(cand.id), "reachable": bool(r), "secretary": r["agent_name"] if r else None})
    return out


# ── asking around ──────────────────────────────────────────────────────────────
#: Words that carry no topic: the way a question is asked, rather than what it is about.
_STOP = frozenset("""그 이 저 것 수 등 및 때 년 개 명 좀 관련 대해 사람 누구 누가 어떻게 어떤 어떤지 어디 언제 무엇 왜 뭐 뭔가
                     물어 물어봐 물어보지 물어볼 알려줘 궁금 궁금해 중인데 중이야 인데 입니다 합니다 해요 하는 한다 됩니다
                     about the a an of to for in on with at is are was were how who what which and or should would could my your""".split())
#: Particles glued to the end of a Korean noun. Longest first when stripping.
_PARTICLES = ("에서는", "으로는", "에게서", "한테서", "이라고", "에서", "에게", "한테", "으로", "까지", "부터", "보다",
              "처럼", "이나", "라도", "만큼", "밖에", "조차", "마저", "이란", "라고", "은", "는", "이", "가", "을",
              "를", "에", "와", "과", "도", "만", "의", "로", "께", "란")


def _stem(word: str) -> str:
    """Drop the particle a Korean noun is wearing, so "이직을" and "이직은" are one word."""
    if not re.fullmatch(r"[가-힣]+", word):
        return word
    for p in sorted(_PARTICLES, key=len, reverse=True):
        if word.endswith(p) and len(word) - len(p) >= 2:
            return word[: -len(p)]
    return word


def keywords(question: str, *, limit: int = 6) -> list[str]:
    """The words worth searching for in a question.

    Crude on purpose: the alternative is a morphological analyser for one search box. What
    it must get right is not dropping the noun the question is actually about.
    """
    out: list[str] = []
    for raw in re.split(r"[^0-9A-Za-z가-힣]+", question or ""):
        w = _stem(raw.strip())
        if len(w) < 2 or w.lower() in _STOP or raw.strip().lower() in _STOP:
            continue
        if w not in out:
            out.append(w)
    # Longest first: a longer word is a narrower one, and the list is capped.
    out.sort(key=lambda w: (-len(w), w))
    return out[:limit]


async def find_by_topic(db: AsyncSession, *, owner: User, agent: Agent, question: str = "", query_text: str = "",
                        conversation_id: uuid.UUID | None, turn_id: uuid.UUID | None,
                        limit: int = 5) -> list[dict[str, Any]]:
    """Who could answer this, from what they published (plan/41 §6).

    Not "who is popular" and not "who is nearby": who has written about it, or says this is
    their work. Only people whose secretary actually takes inquiries come back, because the
    point of the list is to ask.
    """
    from memora.models import BlogPost, OwnerProfile
    from memora.services import profile as PF

    words = keywords(question or query_text)
    if not words:
        return []
    found: dict[uuid.UUID, str] = {}
    why: dict[uuid.UUID, str] = {}

    def esc(w: str) -> str:
        return w.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")

    # 1) what they published on their own page: the strongest signal, and their own words
    post_hit = or_(*[BlogPost.title.ilike(f"%{esc(w)}%", escape="\\") for w in words],
                   *[BlogPost.body.ilike(f"%{esc(w)}%", escape="\\") for w in words])
    posts = (await db.execute(select(BlogPost).where(
        BlogPost.status == "published", BlogPost.visibility == "public", BlogPost.owner_id != owner.id,
        post_hit).order_by(BlogPost.published_at.desc()).limit(40))).scalars().all()
    for post in posts:
        if post.owner_id not in found:
            found[post.owner_id] = "wrote"
            why[post.owner_id] = post.title[:80]

    # 2) what they say they do, when it is public. 소속은 기업 기능이 켜져 있을 때만 (plan/71).
    from memora.services.companies import switch as CO

    keys = ("title", "company", "bio") if await CO.enabled(db) else ("title", "bio")
    prof_hit = or_(*[OwnerProfile.data[k].astext.ilike(f"%{esc(w)}%", escape="\\") for k in keys for w in words])
    profs = (await db.execute(select(OwnerProfile).where(OwnerProfile.owner_id != owner.id, prof_hit).limit(40))).scalars().all()
    for prof in profs:
        if prof.owner_id in found:
            continue
        d = prof.data or {}
        shown = [str(d.get(k)) for k in keys
                 if d.get(k) and PF.field_visibility(prof, {}, k) == "public"
                 and any(w.lower() in str(d.get(k)).lower() for w in words)]
        if shown:
            found[prof.owner_id] = "profile"
            why[prof.owner_id] = " · ".join(shown)[:80]

    return await _materialise(db, owner=owner, agent=agent, found=found, query=(question or query_text)[:200],
                              conversation_id=conversation_id, turn_id=turn_id, limit=limit,
                              why=why, reachable_only=True)


# ── one hop ────────────────────────────────────────────────────────────────────

async def run_hop(db: AsyncSession, relay_id: uuid.UUID) -> dict[str, Any]:
    """Start the turn that answers the last message. Runs in the API process (turns live
    there); commits and launches the turn itself."""
    from memora.pipeline.runner import TurnRequest, launch_turn, start_turn
    from memora.services import agents as AG
    from memora.services import credits as CR

    relay = (await db.execute(select(AgentRelay).where(AgentRelay.id == relay_id).with_for_update())).scalars().first()
    if relay is None or relay.status != "open" or not relay.hop_pending:
        return {"skipped": "not_pending"}
    if relay.in_flight_turn_id:
        t = await db.get(Turn, relay.in_flight_turn_id)
        if t is not None and t.status in ("pending", "running"):
            return {"skipped": "in_flight"}
    side = relay.hop_pending
    incoming = await _last_message(db, relay)
    if incoming is None or incoming.side != other(side):
        return {"skipped": "nothing_to_answer"}
    if side == "target":
        agent, owner_id, conv_id, vis_id = relay.target_agent_id, relay.target_owner_id, relay.target_conversation_id, relay.target_visitor_id
    else:
        agent, owner_id, conv_id, vis_id = relay.initiator_agent_id, relay.initiator_owner_id, relay.initiator_conversation_id, relay.initiator_visitor_id
    receiver = await db.get(Agent, agent)
    receiver_owner = await db.get(User, owner_id)
    conv = await db.get(Conversation, conv_id) if conv_id else None
    visitor = await db.get(Visitor, vis_id) if vis_id else None
    if receiver is None or receiver_owner is None or conv is None or visitor is None:
        await _close(db, relay, by="system", reason="error")
        return {"closed": "error"}
    if receiver.status != "active" or receiver_owner.status != "active":
        await _close(db, relay, by="system", reason="link_closed" if side == "target" else "resting")
        return {"closed": "inactive"}
    if (await CR.available_balance(db, receiver_owner.id)) <= 0:
        await _close(db, relay, by="system", reason="target_resting" if side == "target" else "resting")
        return {"closed": "resting"}
    if relay.message_count >= relay.max_messages:
        await _close(db, relay, by="system", reason="max_messages")
        return {"closed": "max_messages"}
    if await _spent(db, conv.id) >= float(relay.credit_cap):
        await _close(db, relay, by="system", reason="credit_cap")
        return {"closed": "credit_cap"}
    link = None
    if side == "target":
        link = await db.get(ShareLink, relay.target_link_id) if relay.target_link_id else None
        if link is None or AG.link_effective_status(link, receiver) != "active" or not link_settings(link)["allow_agents"]:
            await _close(db, relay, by="system", reason="link_closed")
            return {"closed": "link_closed"}
        cap = link_settings(link)["agent_turns_per_day"]
        if cap and await _link_agent_turns_today(db, link.id) >= cap:
            await _close(db, relay, by="system", reason="target_busy")
            return {"closed": "target_busy"}
    req = TurnRequest(owner=receiver_owner, agent=receiver, conversation=conv, audience="visitor", text=incoming.content[:2000],
                      visitor=visitor, share_link=link, client_turn_id=f"relay:{relay.id}:{incoming.seq}")
    try:
        turn = await start_turn(db, req)
    except MemoraError as e:
        relay.attempts = (relay.attempts or 0) + 1
        if e.code in ("insufficient_credits", "credit_cap", "daily_cap", "monthly_cap", "visitor_turn_cap"):
            await _close(db, relay, by="system", reason="credit_cap" if e.code != "insufficient_credits" else ("target_resting" if side == "target" else "resting"))
            return {"closed": e.code}
        if relay.attempts >= 3:
            await _close(db, relay, by="system", reason="error")
            return {"closed": "error", "err": e.code}
        await _enqueue_hop(db, relay, delay_s=30, owner_id=receiver_owner.id)
        return {"retry": e.code}
    relay.in_flight_turn_id, relay.pending_since = turn.id, datetime.now(UTC)
    relay.attempts = (relay.attempts or 0) + 1
    _mark_delivered(relay, side, incoming.seq)   # start_turn wrote it as this side's user message
    await db.commit()
    launch_turn(turn)
    return {"turn_id": str(turn.id), "side": side}


async def after_turn(db: AsyncSession, conv: Conversation, turn: Turn, answer: str, status: str) -> None:
    """Called when a relay-side turn finalizes: keep the answer, decide whether the exchange
    goes on, and either queue the other side or close."""

    relay = (await db.execute(select(AgentRelay).where(AgentRelay.id == conv.relay_id).with_for_update())).scalars().first()
    if relay is None:
        return
    side = side_of(relay, conv.id)
    if side is None:
        return
    text = (answer or "").strip()
    if relay.status != "open":
        # Closed while this turn was running (an owner stopped it, the sweep expired it). What
        # the turn still produced is in this side's conversation; keep the ledger and the other
        # side's transcript equal to it.
        if text and turn.status in ("completed", "cancelled"):
            m = await _record(db, relay, side=side, agent_id=turn.agent_id, kind="reply" if status == "completed" else "partial", content=text, turn_id=turn.id)
            _mark_delivered(relay, side, m.seq)
            await _sync_transcripts(db, relay)
        return
    if relay.in_flight_turn_id and relay.in_flight_turn_id != turn.id:
        return
    cfg = await _cfg(db)
    relay.in_flight_turn_id = None
    if status != "completed":
        if (relay.attempts or 0) >= 3:
            await _close(db, relay, by="system", reason="error")
        else:
            relay.pending_since = datetime.now(UTC)
            await _enqueue_hop(db, relay, delay_s=30)
        return
    relay.attempts = 0
    close_req = relay.close_requested_by == side
    prev = await _last_message(db, relay, side=other(side))
    kind = "close" if close_req else "reply"
    if text:
        mine = await _record(db, relay, side=side, agent_id=turn.agent_id, kind=kind, content=text, turn_id=turn.id)
        _mark_delivered(relay, side, mine.seq)   # the turn's own answer is already in its conversation
    reason: str | None = None
    by = side
    if close_req or not text:
        reason = "done"
    elif relay.message_count >= relay.max_messages:
        reason, by = "max_messages", "system"
    elif is_ack(text) and (relay.message_count >= 4 or (prev is not None and is_ack(prev.content))):
        # Two secretaries thanking each other is not a conversation.
        reason, by = "done", "system"
    if reason is None:
        relay.hop_pending, relay.pending_since = other(side), datetime.now(UTC)
        await _enqueue_hop(db, relay, delay_s=float(cfg["hop_delay_s"]),
                           owner_id=relay.target_owner_id if other(side) == "target" else relay.initiator_owner_id)
        return
    # The last word still reaches the other side's transcript — as a message, not a turn
    # (_close syncs whatever is missing on either side).
    await _close(db, relay, by=by, reason=reason)


async def request_close(db: AsyncSession, relay_id: uuid.UUID, conversation_id: uuid.UUID, summary: str = "") -> dict[str, Any]:
    """The relay_close tool: this side is done after the message it is writing now."""
    relay = await db.get(AgentRelay, relay_id)
    if relay is None or relay.status != "open":
        return {"ok": False, "note": "This conversation is already closed."}
    side = side_of(relay, conversation_id)
    if side is None:
        return {"ok": False, "note": "Not a party to this conversation."}
    relay.close_requested_by = side
    if summary:
        relay.summary = summary.strip()[:600]
    return {"ok": True, "note": "Closing after this message. Keep your reply to one short closing line, or reply with nothing."}


async def stop(db: AsyncSession, relay: AgentRelay, *, owner_id: uuid.UUID) -> None:
    from memora.pipeline.runner import cancel_turn
    if relay.status != "open":
        return
    if relay.in_flight_turn_id:
        with contextlib.suppress(Exception):
            await cancel_turn(relay.in_flight_turn_id)
    who = "initiator" if owner_id == relay.initiator_owner_id else "target"
    await _record(db, relay, side="system", agent_id=None, kind="system", content=f"오너({'문의한 쪽' if who == 'initiator' else '받은 쪽'})가 대화를 중단했어요.")
    await _close(db, relay, by="owner", reason="owner_stop")


# ── close + report ─────────────────────────────────────────────────────────────

async def _close(db: AsyncSession, relay: AgentRelay, *, by: str, reason: str, summary: str | None = None) -> None:
    from memora.services import conversations as CV
    from memora.services import inbox as I
    from memora.services import profile as PF

    if relay.status != "open":
        return
    now = datetime.now(UTC)
    relay.status, relay.closed_at, relay.closed_by, relay.close_reason = "closed", now, by, reason
    relay.hop_pending, relay.in_flight_turn_id = None, None
    if summary:
        relay.summary = summary[:600]
    if not relay.summary:
        last = await _last_message(db, relay)
        relay.summary = (last.content[:300] if last else "") or relay.opener[:300]
    with contextlib.suppress(Exception):
        await _sync_transcripts(db, relay)
    a = await db.get(Agent, relay.initiator_agent_id)
    b = await db.get(Agent, relay.target_agent_id)
    ox = await db.get(User, relay.initiator_owner_id)
    oy = await db.get(User, relay.target_owner_id)
    name_a = a.name if a else "비서"
    name_b = b.name if b else "비서"
    name_x = name_y = ""
    with contextlib.suppress(Exception):
        name_x = PF.display_name(await PF.get(db, relay.initiator_owner_id), ox, audience="visitor", policy=(a.disclosure_policy if a else {}) or {})
        name_y = PF.display_name(await PF.get(db, relay.target_owner_id), oy, audience="visitor", policy=(b.disclosure_policy if b else {}) or {})
    reason_ko = {"done": "대화를 마쳤어요", "refused": "상대가 비서 문의를 받지 않아요", "target_resting": "상대 비서가 쉬고 있어요(크레딧)",
                 "target_busy": "상대 비서의 오늘 비서 문의 한도가 찼어요", "max_messages": "정해진 메시지 수를 다 썼어요", "credit_cap": "크레딧 상한에 닿았어요",
                 "link_closed": "상대 링크가 닫혔어요", "resting": "내 비서가 쉬고 있어요(크레딧)", "stalled": "응답이 멈춰 종료했어요",
                 "expired": "오래 열려 있어 종료했어요", "error": "오류로 종료했어요", "owner_stop": "오너가 중단했어요"}.get(reason, reason)
    payload = {"relay_id": str(relay.id), "reason": reason, "reason_text": reason_ko, "closed_by": by, "message_count": relay.message_count,
               "purpose": relay.purpose, "text": relay.summary, "initiator_agent_name": name_a, "target_agent_name": name_b,
               "initiator_owner_name": name_x, "target_owner_name": name_y,
               # Who the other side is, so the exchange can become a connection between the
               # people rather than ending with their secretaries (plan/41 §6, M5).
               "initiator_user_id": str(relay.initiator_owner_id), "target_user_id": str(relay.target_owner_id)}
    # The owner who asked hears how it went; the owner who was visited hears that it happened.
    with contextlib.suppress(Exception):
        await I.create(db, owner_id=relay.initiator_owner_id, agent_id=relay.initiator_agent_id, kind="relay_result", payload=payload,
                       conversation_id=relay.initiator_conversation_id, visitor_id=relay.initiator_visitor_id, urgency=1)
    if relay.target_conversation_id is not None:
        with contextlib.suppress(Exception):
            await I.create(db, owner_id=relay.target_owner_id, agent_id=relay.target_agent_id, kind="relay_visit", payload=payload,
                           conversation_id=relay.target_conversation_id, visitor_id=relay.target_visitor_id, urgency=1)
    if relay.origin_conversation_id is not None:
        oc = await db.get(Conversation, relay.origin_conversation_id)
        if oc is not None and oc.status != "deleted":
            # One line; the card underneath carries the summary and the link, so the body does not repeat it.
            body = f"{name_b}({name_y})와의 대화가 끝났어요. {reason_ko}."
            with contextlib.suppress(Exception):
                await CV.add_message(db, oc, role="assistant", content=body, cards=[{"card_type": "relay_result", "payload": payload}])
                oc.unread_owner = True
    log.info("relay closed", relay_id=str(relay.id), by=by, reason=reason, messages=relay.message_count)


# ── prompt ─────────────────────────────────────────────────────────────────────

async def prompt_block(db: AsyncSession, relay_id: uuid.UUID, conversation_id: uuid.UUID, agent: Agent, owner: User) -> str:
    """The per-turn note of a relay conversation: who, what for, how much is left. The rules
    are in the base prompt (relay_section), where they stay cached."""
    from memora.services import profile as PF
    relay = await db.get(AgentRelay, relay_id)
    if relay is None:
        return ""
    side = side_of(relay, conversation_id)
    if side is None:
        return ""
    peer_agent = await db.get(Agent, relay.target_agent_id if side == "initiator" else relay.initiator_agent_id)
    peer_owner = await db.get(User, relay.target_owner_id if side == "initiator" else relay.initiator_owner_id)
    peer_owner_name = ""
    with contextlib.suppress(Exception):
        peer_owner_name = PF.display_name(await PF.get(db, peer_owner.id), peer_owner, audience="visitor", policy=(peer_agent.disclosure_policy if peer_agent else {}) or {})
    n, mx = relay.message_count, relay.max_messages
    remaining = max(0, mx - n)
    lines = ["# This exchange", f"With {peer_agent.name if peer_agent else 'another secretary'}, secretary of {peer_owner_name or 'another member'}."]
    if side == "initiator":
        lines.append(f"Purpose: {relay.purpose or relay.opener[:200]}")
    lines.append(f"Messages {n} of {mx}; {remaining} left for both sides together.")
    if remaining <= 1:
        lines.append("This is the last message allowed: make it a closing one and call relay_close.")
    elif remaining <= 2:
        lines.append("Two messages remain: wrap up now.")
    return "\n".join(lines)


# ── maintenance ────────────────────────────────────────────────────────────────

async def sweep(db: AsyncSession) -> dict[str, Any]:
    cfg = await _cfg(db)
    now = datetime.now(UTC)
    stalled = retried = expired = 0
    rows = (await db.execute(select(AgentRelay).where(AgentRelay.status == "open"))).scalars().all()
    for r in rows:
        if r.created_at and now - r.created_at > timedelta(hours=float(cfg["expire_hours"])):
            await _close(db, r, by="system", reason="expired")
            expired += 1
            continue
        if r.hop_pending and r.pending_since and now - r.pending_since > timedelta(minutes=float(cfg["stall_minutes"])):
            if r.in_flight_turn_id:
                t = await db.get(Turn, r.in_flight_turn_id)
                if t is not None and t.status in ("pending", "running"):
                    continue  # a long turn, not a stall
                r.in_flight_turn_id = None
            if (r.attempts or 0) >= 3:
                await _close(db, r, by="system", reason="stalled")
                stalled += 1
            else:
                r.pending_since = now
                await _enqueue_hop(db, r, delay_s=1)
                retried += 1
    return {"open": len(rows), "retried": retried, "stalled": stalled, "expired": expired}


# ── read models ────────────────────────────────────────────────────────────────

async def _names(db: AsyncSession, relay: AgentRelay) -> dict[str, str]:
    from memora.services import profile as PF
    a = await db.get(Agent, relay.initiator_agent_id)
    b = await db.get(Agent, relay.target_agent_id)
    ox = await db.get(User, relay.initiator_owner_id)
    oy = await db.get(User, relay.target_owner_id)
    out = {"initiator_agent": a.name if a else "", "target_agent": b.name if b else "", "initiator_owner": "", "target_owner": ""}
    with contextlib.suppress(Exception):
        out["initiator_owner"] = PF.display_name(await PF.get(db, relay.initiator_owner_id), ox, audience="visitor", policy=(a.disclosure_policy if a else {}) or {})
        out["target_owner"] = PF.display_name(await PF.get(db, relay.target_owner_id), oy, audience="visitor", policy=(b.disclosure_policy if b else {}) or {})
    return out


async def relay_out(db: AsyncSession, relay: AgentRelay, viewer_owner_id: uuid.UUID) -> dict[str, Any]:
    names = await _names(db, relay)
    role = "initiator" if relay.initiator_owner_id == viewer_owner_id else "target"
    my_conv = relay.initiator_conversation_id if role == "initiator" else relay.target_conversation_id
    my_agent = relay.initiator_agent_id if role == "initiator" else relay.target_agent_id
    return {"id": str(relay.id), "status": relay.status, "role": role,
            "my_agent_id": str(my_agent), "my_agent_name": names["initiator_agent" if role == "initiator" else "target_agent"],
            "my_conversation_id": str(my_conv) if my_conv else None,
            "peer_agent_name": names["target_agent" if role == "initiator" else "initiator_agent"],
            "peer_owner_name": names["target_owner" if role == "initiator" else "initiator_owner"],
            "purpose": relay.purpose, "opener": relay.opener, "message_count": relay.message_count, "max_messages": relay.max_messages,
            "credit_cap": float(relay.credit_cap), "my_credits": await _spent(db, my_conv), "hop_pending": relay.hop_pending,
            "summary": relay.summary, "closed_at": relay.closed_at.isoformat() if relay.closed_at else None, "closed_by": relay.closed_by,
            "close_reason": relay.close_reason, "created_at": relay.created_at.isoformat() if relay.created_at else None,
            "last_message_at": relay.last_message_at.isoformat() if relay.last_message_at else None}


async def list_for_owner(db: AsyncSession, owner_id: uuid.UUID, *, agent_id: uuid.UUID | None = None, role: str | None = None,
                         limit: int = 100) -> list[dict[str, Any]]:
    stmt = select(AgentRelay)
    if role == "initiator":
        stmt = stmt.where(AgentRelay.initiator_owner_id == owner_id)
    elif role == "target":
        stmt = stmt.where(AgentRelay.target_owner_id == owner_id)
    else:
        stmt = stmt.where((AgentRelay.initiator_owner_id == owner_id) | (AgentRelay.target_owner_id == owner_id))
    if agent_id:
        stmt = stmt.where((AgentRelay.initiator_agent_id == agent_id) | (AgentRelay.target_agent_id == agent_id))
    rows = (await db.execute(stmt.order_by(AgentRelay.created_at.desc()).limit(limit))).scalars().all()
    return [await relay_out(db, r, owner_id) for r in rows]


async def get_party(db: AsyncSession, relay_id: uuid.UUID, owner_id: uuid.UUID) -> AgentRelay:
    r = await db.get(AgentRelay, relay_id)
    if r is None or owner_id not in (r.initiator_owner_id, r.target_owner_id):
        raise NotFound("conversation not found", code="relay_not_found")
    return r


async def detail(db: AsyncSession, relay: AgentRelay, viewer_owner_id: uuid.UUID) -> dict[str, Any]:
    out = await relay_out(db, relay, viewer_owner_id)
    names = await _names(db, relay)
    msgs = (await db.execute(select(AgentRelayMessage).where(AgentRelayMessage.relay_id == relay.id).order_by(AgentRelayMessage.seq))).scalars().all()
    out["messages"] = [{"seq": m.seq, "side": m.side, "kind": m.kind, "content": m.content, "created_at": m.created_at.isoformat(),
                        "agent_name": names["initiator_agent"] if m.side == "initiator" else names["target_agent"] if m.side == "target" else "",
                        "mine": (m.side == out["role"])} for m in msgs]
    out["names"] = names
    return out
