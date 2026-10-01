"""Who a network node actually is, and friendships between accounts (plan/31).

`services/network` owns the graph as a data structure — nodes, edges, search, paths. This
module owns the *identity* on top of it: whether a node is a black-moa account, a visitor who
talked to this owner's secretary, or a card the owner wrote; and the friend links that make
a connection something both people agreed to rather than one person's private note.

Two rules run through everything here:

* **Promotion never forks.** A card becomes a guest becomes a member by being bound and
  merged, never by a second node appearing beside the first. Years of notes must not split
  because the person finally signed up.
* **Identity is claimed by proof, not by typing.** A visitor's guest identity — which
  carries their conversations with this owner's secretary — fuses into an account only when
  that address is proven: verified, or logged into. Typing someone's email into a signup
  form is not proof.
"""
from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import String, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from blackmoa.core import visibility as VIS
from blackmoa.core.errors import Conflict, NotFound, ValidationFailed
from blackmoa.core.logging import get_logger
from blackmoa.models import Agent, NetworkEdge, NetworkNode, PersonFollow, User, Visitor
from blackmoa.services import network as N

log = get_logger("blackmoa.people")

# The relation a friendship gets on both sides. "knows" is the honest default: the link
# says these two agreed to be connected, not how.
FRIEND_REL = "knows"
LINK_STATUSES = ("pending", "accepted", "declined")


# ── what a node is ─────────────────────────────────────────────────

def person_class(n: NetworkNode) -> str:
    if n.is_self:
        return "self"
    if n.user_id:
        return "member"
    if n.visitor_id:
        return "guest"
    return "offline"


def _emails_of(n: NetworkNode) -> set[str]:
    v = (n.attrs or {}).get("emails")
    out = {str(x).strip().lower() for x in v} if isinstance(v, list) else set()
    one = (n.attrs or {}).get("email")
    if one:
        out.add(str(one).strip().lower())
    return {e for e in out if e}


def _with_email(n: NetworkNode, email: str | None) -> None:
    if not email:
        return
    attrs = dict(n.attrs or {})
    emails = [e for e in (attrs.get("emails") or []) if isinstance(e, str)]
    if email.lower() not in {e.lower() for e in emails}:
        emails.append(email)
    attrs["emails"] = emails[:8]
    n.attrs = attrs


def display_of(u: User) -> str:
    return (u.nickname or u.display_name or u.email.split("@")[0])[:200]


# ── the middle of the graph ────────────────────────────────────────

async def self_node(db: AsyncSession, owner: User) -> NetworkNode:
    """The owner's own node. Created on first use — an ego network needs a middle, and
    asking people to add themselves would be a strange first task."""
    n = (await db.execute(select(NetworkNode).where(NetworkNode.owner_id == owner.id,
                                                    NetworkNode.is_self.is_(True)))).scalars().first()
    if n is not None:
        if n.user_id != owner.id:
            n.user_id = owner.id
        return n
    n = NetworkNode(owner_id=owner.id, kind="person", name=display_of(owner), is_self=True, user_id=owner.id,
                    importance=5, source="self", attrs={"emails": [owner.email]})
    db.add(n)
    await db.flush()
    return n


# ── binding a node to a person ─────────────────────────────────────

async def _candidate_card(db: AsyncSession, owner_id: uuid.UUID, *, name: str | None, email: str | None) -> NetworkNode | None:
    """An unbound card that is plainly the same person: same email, else same exact name.

    Deliberately strict. A wrong merge silently mixes two people's notes together, and
    unlike a missed merge there is no obvious moment where the owner notices.
    """
    stmt = select(NetworkNode).where(NetworkNode.owner_id == owner_id, NetworkNode.is_self.is_(False),
                                     NetworkNode.user_id.is_(None), NetworkNode.kind == "person")
    rows = (await db.execute(stmt)).scalars().all()
    if email:
        e = email.strip().lower()
        for n in rows:
            if e in _emails_of(n):
                return n
    if name:
        nm = name.strip().lower()
        if len(nm) >= 2:
            for n in rows:
                if n.name.strip().lower() == nm and not _emails_of(n):
                    return n
    return None


async def node_for_user(db: AsyncSession, owner: User, other: User) -> NetworkNode:
    """This owner's node for another account, bound and up to date."""
    n = (await db.execute(select(NetworkNode).where(NetworkNode.owner_id == owner.id,
                                                    NetworkNode.user_id == other.id))).scalars().first()
    if n is None:
        n = await _candidate_card(db, owner.id, name=display_of(other), email=other.email)
        if n is None:
            n = NetworkNode(owner_id=owner.id, kind="person", name=display_of(other), source="member",
                            importance=3, attrs={})
            db.add(n)
        n.user_id = other.id
        n.source = "member"
    # The account is the source of truth for the name; a card's own name becomes an alias
    # so searching for what the owner used to call them still works.
    live = display_of(other)
    if n.name != live:
        n.aliases = list(dict.fromkeys([*(n.aliases or []), n.name]))[:20]
        n.name = live
    _with_email(n, other.email)
    await db.flush()
    return n


async def node_for_visitor(db: AsyncSession, owner: User, v: Visitor) -> NetworkNode:
    """This owner's node for a guest — someone who talked to their secretary."""
    if v.owner_id != owner.id:
        raise NotFound("visitor not found", code="visitor_not_found")
    n = (await db.execute(select(NetworkNode).where(NetworkNode.owner_id == owner.id,
                                                    NetworkNode.visitor_id == v.id))).scalars().first()
    if n is not None:
        return n
    if v.user_id:
        u = await db.get(User, v.user_id)
        if u is not None:
            n = await node_for_user(db, owner, u)
            n.visitor_id = v.id
            await db.flush()
            return n
    name = (v.display_name or "").strip() or "이름 없는 방문자"
    n = await _candidate_card(db, owner.id, name=v.display_name, email=v.email)
    if n is None:
        n = NetworkNode(owner_id=owner.id, kind="person", name=name[:200], source="guest",
                        importance=3, attrs={})
        db.add(n)
    n.visitor_id = v.id
    if n.source == "manual":
        n.source = "guest"
    _with_email(n, v.email)
    if v.note and v.note not in (n.notes or ""):
        n.notes = ((n.notes or "") + "\n" + v.note).strip()[:4000]
    if v.last_seen_at and (n.last_contact_at is None or v.last_seen_at > n.last_contact_at):
        n.last_contact_at = v.last_seen_at
    await db.flush()
    return n


# ── fusion: a guest turns out to be an account ─────────────────────

async def fuse_visitor(db: AsyncSession, v: Visitor) -> NetworkNode | None:
    """The visitor is now known to be `v.user_id`. Make the owner's graph agree.

    Promotes the guest node to a member node, and if the owner already had a separate node
    for that account, merges the two so the owner ends up with one person, not two.
    """
    if not v.user_id:
        return None
    owner = await db.get(User, v.owner_id)
    other = await db.get(User, v.user_id)
    if owner is None or other is None or owner.id == other.id:
        return None
    guest = (await db.execute(select(NetworkNode).where(NetworkNode.owner_id == owner.id,
                                                        NetworkNode.visitor_id == v.id))).scalars().first()
    member = (await db.execute(select(NetworkNode).where(NetworkNode.owner_id == owner.id,
                                                         NetworkNode.user_id == other.id))).scalars().first()
    if guest is None:
        return member
    if member is None:
        guest.user_id = other.id
        guest.source = "member"
        live = display_of(other)
        if guest.name != live:
            guest.aliases = list(dict.fromkeys([*(guest.aliases or []), guest.name]))[:20]
            guest.name = live
        _with_email(guest, other.email)
        await db.flush()
        log.info("guest promoted to member", owner=str(owner.id), node=str(guest.id))
        return guest
    if member.id == guest.id:
        return member
    # Two nodes, one person. Keep the member node (it carries the account binding) and fold
    # the guest's notes, edges and interactions into it.
    member.visitor_id = guest.visitor_id
    guest.visitor_id = None
    await db.flush()
    kept = await N.merge(db, owner.id, guest.id, member.id)
    log.info("guest merged into member node", owner=str(owner.id), node=str(kept.id))
    return kept


async def claim_visitors_for(db: AsyncSession, user: User) -> int:
    """Bind every unclaimed visitor holding this (now proven) address to this account.

    Called when an address is verified or logged into — never at signup. A guest identity
    carries real conversations with somebody's secretary; typing an address into a form is
    not evidence that it is yours.
    """
    if not user.email:
        return 0
    rows = (await db.execute(select(Visitor).where(Visitor.user_id.is_(None),
                                                   func.lower(Visitor.email) == user.email.lower()))).scalars().all()
    n = 0
    for v in rows:
        if v.owner_id == user.id:
            continue        # my own secretary: nothing to link myself to
        v.user_id = user.id
        if not v.display_name:
            v.display_name = display_of(user)
        await fuse_visitor(db, v)
        n += 1
    if n:
        log.info("claimed guest identities on proof of address", user=str(user.id), visitors=n)
    return n


# ── the directory: finding a real person ───────────────────────────

def _account_out(u: User, *, echo_email: str | None = None) -> dict[str, Any]:
    # The email comes back only when the caller already typed it: the directory tells you
    # about someone you can already name, it does not hand out addresses.
    return {"id": str(u.id), "display_name": display_of(u), "real_name": u.display_name,
            "avatar_url": u.avatar_url, "handle": u.mail_handle,
            "email": u.email if echo_email and u.email.lower() == echo_email else None}


async def directory_search(db: AsyncSession, me: User, q: str, limit: int = 10, *, contains: bool = False) -> list[dict[str, Any]]:
    """Find accounts by exact email, exact mail handle, or a name prefix.

    No browsable listing: `q` is required and short queries are refused, so this answers
    "is <person I can name> on black-moa" and not "who is on black-moa". ``contains`` matches the
    name anywhere — a secretary told "스완" has to find 배조스완 (plan/39).
    """
    term = (q or "").strip()
    if len(term) < 2:
        return []
    low = term.lower()
    stmt = select(User).where(User.id != me.id, User.status == "active")
    if "@" in term:
        stmt = stmt.where(func.lower(User.email.cast(String)) == low)
    else:
        esc = term.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        pat = ("%" + esc + "%") if contains else (esc + "%")
        stmt = stmt.where(or_(func.lower(User.mail_handle.cast(String)) == low,
                              User.display_name.ilike(pat, escape="\\"),
                              User.nickname.ilike(pat, escape="\\")))
    rows = (await db.execute(stmt.order_by(User.display_name).limit(min(20, max(1, limit))))).scalars().all()
    if not rows:
        return []
    states = await link_states(db, me, [u.id for u in rows])
    return [dict(_account_out(u, echo_email=low if "@" in term else None), link=states.get(u.id)) for u in rows]


# ── friend links ───────────────────────────────────────────────────

async def conn_between(db: AsyncSession, a: uuid.UUID, b: uuid.UUID) -> tuple[bool, bool]:
    """(a connected to b, b connected to a)."""
    rows = set((await db.execute(select(PersonFollow.follower_id, PersonFollow.target_id).where(
        or_((PersonFollow.follower_id == a) & (PersonFollow.target_id == b),
            (PersonFollow.follower_id == b) & (PersonFollow.target_id == a))))).all())
    return (a, b) in rows, (b, a) in rows


def _state(out: bool, back: bool) -> dict[str, Any] | None:
    """What to call the space between two people (plan/43).

    One word for each of the three things that can be true, and nothing for the fourth.
    There is no pending: connecting is done the moment it is done.
    """
    if out and back:
        return {"status": "mutual", "direction": "both"}
    if out:
        return {"status": "outgoing", "direction": "outgoing"}
    if back:
        return {"status": "incoming", "direction": "incoming"}
    return None


async def link_states(db: AsyncSession, me: User, others: list[uuid.UUID]) -> dict[uuid.UUID, dict[str, Any] | None]:
    if not others:
        return {}
    rows = set((await db.execute(select(PersonFollow.follower_id, PersonFollow.target_id).where(
        or_(PersonFollow.follower_id == me.id, PersonFollow.target_id == me.id)))).all())
    out = {b for a, b in rows if a == me.id}
    back = {a for a, b in rows if b == me.id}
    return {o: _state(o in out, o in back) for o in others}


async def link_between(db: AsyncSession, me: uuid.UUID, other: uuid.UUID) -> dict[str, Any]:
    """What the space between me and them is called, from my side. Always a status — "none" too."""
    out, back = await conn_between(db, me, other)
    return _state(out, back) or {"status": "none"}


async def announce_link(db: AsyncSession, a: uuid.UUID, b: uuid.UUID) -> None:
    """Tell both people, on every screen they have open, what the space between them is now
    (plan/69). A connection is shown in a dozen places — a profile, a card, the inbox, the
    graph — and a change made in one tab or by the other person must reach all of them
    instead of waiting for a reload."""
    from blackmoa.core import bus

    out, back = await conn_between(db, a, b)
    await bus.publish(db, owner_id=a, kind="link", data={"user_id": str(b), **(_state(out, back) or {"status": "none"})})
    await bus.publish(db, owner_id=b, kind="link", data={"user_id": str(a), **(_state(back, out) or {"status": "none"})})


async def connect(db: AsyncSession, me: User, other_id: uuid.UUID) -> dict[str, Any]:
    """Connect to somebody. Nobody is asked and nothing waits (plan/43)."""
    from blackmoa.services import blog as B

    added = await B.follow(db, me, other_id)
    if added:
        await announce_link(db, me.id, other_id)
    return {"added": added, **await link_between(db, me.id, other_id)}


async def disconnect(db: AsyncSession, me: User, other_id: uuid.UUID) -> dict[str, Any]:
    """Stop. Only my own half: what the other person chose is theirs to keep or drop."""
    from blackmoa.services import blog as B

    await B.unfollow(db, me, other_id)
    await announce_link(db, me.id, other_id)
    return await link_between(db, me.id, other_id)


async def materialize_connection(db: AsyncSession, me: User, other: User) -> None:
    """Draw what is true between two people, in both of their graphs (plan/43 §2).

    A connection is one-way until it is answered, so the picture has to say which way it
    points. `direction` carries that: outgoing from my side, incoming on theirs, and both
    once each has chosen the other. When neither has, the line goes.
    """
    out, back = await conn_between(db, me.id, other.id)
    for owner, guest, mine, theirs in ((me, other, out, back), (other, me, back, out)):
        if not (mine or theirs):
            await _drop_edges(db, owner.id, guest.id)
            continue
        me_node = await self_node(db, owner)
        their_node = await node_for_user(db, owner, guest)
        direction = "both" if (mine and theirs) else ("outgoing" if mine else "incoming")
        edge = await N.create_edge(db, owner.id, src_id=me_node.id, dst_id=their_node.id, rel=FRIEND_REL,
                                   strength=0.7 if direction == "both" else 0.4, source="link")
        edge.direction = direction
    await db.flush()


async def _drop_edges(db: AsyncSession, owner_id: uuid.UUID, other_user_id: uuid.UUID) -> None:
    """The line goes; the node stays. Ending a relationship is not never having met, and
    the notes on that person are the owner's."""
    owner_self = (await db.execute(select(NetworkNode).where(NetworkNode.owner_id == owner_id,
                                                             NetworkNode.is_self.is_(True)))).scalars().first()
    their = (await db.execute(select(NetworkNode).where(NetworkNode.owner_id == owner_id,
                                                        NetworkNode.user_id == other_user_id))).scalars().first()
    if owner_self is None or their is None:
        return
    edges = (await db.execute(select(NetworkEdge).where(
        NetworkEdge.owner_id == owner_id, NetworkEdge.rel == FRIEND_REL,
        or_((NetworkEdge.src_id == owner_self.id) & (NetworkEdge.dst_id == their.id),
            (NetworkEdge.src_id == their.id) & (NetworkEdge.dst_id == owner_self.id))))).scalars().all()
    for e in edges:
        await db.delete(e)


async def links_for(db: AsyncSession, me: User) -> dict[str, list[dict[str, Any]]]:
    """The three things the 인맥 page shows: 인맥, 내가 연결한, 나를 연결한 (plan/43 §3)."""
    rows = (await db.execute(select(PersonFollow).where(
        or_(PersonFollow.follower_id == me.id, PersonFollow.target_id == me.id))
        .order_by(PersonFollow.created_at.desc()))).scalars().all()
    out_at: dict[uuid.UUID, Any] = {}
    back_at: dict[uuid.UUID, Any] = {}
    for r in rows:
        (out_at if r.follower_id == me.id else back_at)[
            r.target_id if r.follower_id == me.id else r.follower_id] = r.created_at
    ids = set(out_at) | set(back_at)
    users = {u.id: u for u in (await db.execute(
        select(User).where(User.id.in_(ids or {me.id}), User.status == "active"))).scalars().all()}
    result: dict[str, list[dict[str, Any]]] = {"friends": [], "incoming": [], "outgoing": []}
    for uid in ids:
        u = users.get(uid)
        if u is None:
            continue
        at = out_at.get(uid) or back_at.get(uid)
        item = dict(_account_out(u), at=at.isoformat() if at else None, link=_state(uid in out_at, uid in back_at))
        if uid in out_at and uid in back_at:
            result["friends"].append(item)
        elif uid in out_at:
            result["outgoing"].append(item)
        else:
            result["incoming"].append(item)
    return result


# ── guests: the people who actually showed up ──────────────────────

async def guests(db: AsyncSession, owner: User, *, limit: int = 100) -> list[dict[str, Any]]:
    """Visitors who talked to this owner's secretaries, with what is known about each.

    The list is the answer to "who came to see me": it is the one place where a person with
    no account and no card is still visible, because their conversations are the evidence.
    """
    rows = (await db.execute(select(Visitor).where(Visitor.owner_id == owner.id, Visitor.turn_count > 0)
                             .order_by(Visitor.last_seen_at.desc()).limit(limit))).scalars().all()
    if not rows:
        return []
    agent_ids = {v.agent_id for v in rows}
    agents = {a.id: a for a in (await db.execute(select(Agent).where(Agent.id.in_(agent_ids)))).scalars().all()}
    nodes = {n.visitor_id: n for n in (await db.execute(select(NetworkNode).where(
        NetworkNode.owner_id == owner.id, NetworkNode.visitor_id.in_({v.id for v in rows})))).scalars().all()}
    user_ids = {v.user_id for v in rows if v.user_id}
    users = {u.id: u for u in (await db.execute(select(User).where(User.id.in_(user_ids)))).scalars().all()} if user_ids else {}
    # An address that belongs to an account this visitor never logged into: a member in
    # waiting, and the reason to offer a friend request rather than a card.
    emails = {v.email.lower() for v in rows if v.email and not v.user_id}
    by_email = {u.email.lower(): u for u in (await db.execute(select(User).where(
        func.lower(User.email.cast(String)).in_(emails)))).scalars().all()} if emails else {}
    states = await link_states(db, owner, [u.id for u in list(users.values()) + list(by_email.values())])
    out = []
    for v in rows:
        u = users.get(v.user_id) if v.user_id else (by_email.get(v.email.lower()) if v.email else None)
        node = nodes.get(v.id)
        out.append({
            "visitor_id": str(v.id), "name": v.display_name, "email": v.email, "note": v.note,
            "agent": (agents.get(v.agent_id).name if agents.get(v.agent_id) else None),
            "turns": int(v.turn_count or 0), "blocked": bool(v.blocked),
            "first_seen_at": v.first_seen_at.isoformat() if v.first_seen_at else None,
            "last_seen_at": v.last_seen_at.isoformat() if v.last_seen_at else None,
            "signed_in": v.user_id is not None,
            "account": _account_out(u) if u is not None else None,
            "link": states.get(u.id) if u is not None else None,
            "node_id": str(node.id) if node is not None else None,
        })
    return out


async def add_guest(db: AsyncSession, owner: User, visitor_id: uuid.UUID) -> NetworkNode:
    v = await db.get(Visitor, visitor_id)
    if v is None or v.owner_id != owner.id:
        raise NotFound("visitor not found", code="visitor_not_found")
    node = await node_for_visitor(db, owner, v)
    me = await self_node(db, owner)
    await N.create_edge(db, owner.id, src_id=me.id, dst_id=node.id, rel=FRIEND_REL, strength=0.4, source="guest")
    v.matched_node_id = node.id
    return node


# ── profiles: what one member may see of another ───────────────────

# The fields a profile page shows when their owner marked them public. Everything else on
# a profile — contact rules, availability, the free-form extras — is between the owner and
# their own secretary.
PUBLIC_PROFILE_FIELDS = ("full_name", "preferred_name", "title", "company", "bio", "location", "languages", "links",
                         "cover", "cover_pos", "job_codes", "region_codes", "industry_codes",
                         # Only the fact that the company was proven, never the mailbox (plan/40 §10).
                         "company_verified_at",
                         # [정보] 의 공개 범위는 곧 "프로필에서 누구에게 보이나" 다 (plan/57). 범위를 고를 수
                         # 있는 칸이 프로필에 없으면, 고른 범위가 무엇을 뜻하는지 아무도 모른다.
                         "contact_rules", "extra")


def visible_profile(prof: Any, who: str) -> dict[str, Any]:
    """이 사람(``who``)에게 프로필이 보여 주는 칸 — 공개 페이지와 회원 프로필이 같은 이 함수를 쓴다.
    연락처는 이메일·전화가 칸마다 따로 범위를 가진다."""
    from blackmoa.services import profile as PF

    data = prof.data or {}
    out: dict[str, Any] = {}
    for key in PUBLIC_PROFILE_FIELDS:
        val = data.get(key)
        if val in (None, "", [], {}):
            continue
        if PF.visible_to(PF.field_visibility(prof, {}, key), who):
            out[key] = val
    contact = {sub: str(v) for sub, v in ((data.get("contact") or {}) if isinstance(data.get("contact"), dict) else {}).items()
               if sub in ("email", "phone") and v and PF.visible_to(PF.field_visibility(prof, {}, f"contact.{sub}"), who)}
    if contact:
        out["contact"] = contact
    return out
# An album is a handful of pictures, not a gallery: past two dozen it stops being
# something a visitor looks at and starts being something they scroll past.


async def by_handle(db: AsyncSession, handle: str) -> User | None:
    """The account a public address points at (plan/41 §2). `mail_handle` is CITEXT, so the
    comparison is already case-insensitive."""
    h = (handle or "").strip().lstrip("@")
    if not h:
        return None
    return (await db.execute(select(User).where(User.mail_handle == h, User.status == "active"))).scalars().first()


async def viewer_level(db: AsyncSession, owner_id: uuid.UUID, viewer_id: uuid.UUID | None) -> str:
    """How close the reader stands to this owner (plan/41 §8).

    A connection they both agreed to, or a colleague at a company they have each proven,
    counts as known. Everybody else is a stranger, including a signed-in member: having an
    account is not a relationship.
    """
    if viewer_id is None:
        return "stranger"
    if viewer_id == owner_id:
        return "owner"
    from blackmoa.services import blog as B

    if await B.are_friends(db, owner_id, viewer_id):
        return "known"
    from blackmoa.services.companies import switch as CO
    from blackmoa.services.companies import verification as VF

    # 같은 회사 동료는 기업 기능의 것이다 — 끄면 인증한 회사도 없는 것이다 (plan/71).
    if not await CO.enabled(db):
        return "stranger"

    mine = await VF.verified_company_id(db, owner_id)
    theirs = await VF.verified_company_id(db, viewer_id)
    return "known" if mine is not None and mine == theirs else "stranger"


async def public_fields(db: AsyncSession, target: User, viewer: str = "stranger") -> dict[str, Any]:
    """What this person publishes to anyone, signed in or not.

    The same per-field switches the secretary obeys (plan/41 §3): a field nobody marked
    public does not become public because the page is.
    """
    from blackmoa.services import profile as PF

    return visible_profile(await PF.shown(db, target.id), viewer)


async def profile_of(db: AsyncSession, viewer: User, target: User) -> dict[str, Any]:
    """A member's profile, filtered by what they chose to publish.

    Read through `services/profile`'s per-field visibility rather than inventing a second
    policy: a field is on a profile page for the same reason a secretary may say it out
    loud, and one owner should not have to answer that question twice.
    """
    from blackmoa.services import profile as PF

    prof = await PF.shown(db, target.id)
    me = viewer.id == target.id
    who = await viewer_level(db, target.id, viewer.id)
    fields = visible_profile(prof, who)
    link = None if me else _state(*await conn_between(db, viewer.id, target.id))
    out = {
        "id": str(target.id), "display_name": display_of(target), "avatar_url": target.avatar_url,
        "handle": target.mail_handle, "is_me": me, "link": link,
        "joined_at": target.created_at.isoformat() if getattr(target, "created_at", None) else None,
        "fields": fields,
        # 인맥: the people who chose each other. A one-way connection is not a count of
        # how well known somebody is.
        "connections": len(await _friend_ids(db, target.id)),
    }
    from blackmoa.services import blog as B

    # Their own counts, and separately whether *I* read them: one key cannot mean both.
    out["follow"] = {**await B.follow_counts(db, target.id),
                     "i_follow": (not me) and await B.follows(db, viewer.id, target.id)}
    # The grid that replaced the album (plan/42 §9): everything they wrote that this
    # reader may see, photos and words in one place rather than two. The first page comes
    # with the profile so the grid draws at once; the rest is turned page by page.
    rows, total = await B.page_of_published(db, target.id, viewer, page=1, per=12)
    out["posts"] = [B.out(p) for p in rows]
    out["posts_total"] = total
    # Who they are connected to, if they left that open. Open by default: this is a place
    # for people who want to be found (plan/43 §5).
    level = VIS.normalize(getattr(target, "network_public", "public"))
    out["connections_open"] = bool(
        me or level == "public" or (level == "known" and await B.are_friends(db, target.id, viewer.id)))
    if out["connections_open"]:
        friends = await _friend_ids(db, target.id)
        rows = (await db.execute(select(User).where(User.id.in_(friends or {target.id}),
                                                    User.status == "active").limit(24))).scalars().all()
        # Their people, not their paperwork: a list of who somebody knows is not a place to
        # hand out everybody's legal name.
        out["connections_list"] = [{k: v for k, v in _account_out(u).items() if k != "real_name"}
                                   for u in rows if u.id in friends]
    else:
        out["connections_list"] = []
    # The secretaries anybody can talk to (plan/44 §8): a card about a person offers the
    # door they left open, so [비서와 대화] is one press from their face.
    from blackmoa.models import Agent, ShareLink
    from blackmoa.services import agents as A
    seen_bots: set[uuid.UUID] = set()
    out["secretaries"] = []
    for link_row, bot in (await db.execute(
            select(ShareLink, Agent).join(Agent, Agent.id == ShareLink.agent_id)
            .where(ShareLink.owner_id == target.id, A.open_link(), Agent.status == "active")
            .order_by(ShareLink.created_at))).all():
        if bot.id in seen_bots:
            continue
        seen_bots.add(bot.id)
        out["secretaries"].append({"id": str(bot.id), "name": bot.name, "avatar_url": bot.avatar_url,
                                   "role_line": bot.role_line or "", "link_code": link_row.code})
    if me:
        out["email"] = target.email
        out["real_name"] = target.display_name
    elif link and link["status"] == "mutual":
        # 인맥 are allowed to know how to reach each other. A one-way connection is not
        # that agreement: they have not chosen me back (plan/43).
        out["email"] = target.email
    return out


async def _friend_ids(db: AsyncSession, user_id: uuid.UUID) -> set[uuid.UUID]:
    """인맥: the people this person and I each chose (plan/43)."""
    rows = set((await db.execute(select(PersonFollow.follower_id, PersonFollow.target_id).where(
        or_(PersonFollow.follower_id == user_id, PersonFollow.target_id == user_id)))).all())
    out = {b for a, b in rows if a == user_id}
    back = {a for a, b in rows if b == user_id}
    return out & back


async def mentionable(db: AsyncSession, me: User, q: str = "", limit: int = 8) -> list[dict[str, Any]]:
    """People I can name in a caption (plan/42 §11).

    Bounded by my own graph — anybody I connected to or who connected to me — so typing `@`
    offers the people I actually know rather than opening the account table to a prefix
    search. An address is not required: a mention points at a person, and most people have
    not claimed one (plan/42 §11).
    """
    rows = set((await db.execute(select(PersonFollow.follower_id, PersonFollow.target_id).where(
        or_(PersonFollow.follower_id == me.id, PersonFollow.target_id == me.id)))).all())
    ids = {b for a, b in rows if a == me.id} | {a for a, b in rows if b == me.id}
    term = (q or "").strip().lower()
    stmt = select(User).where(User.id.in_(ids or {me.id}), User.status == "active", User.id != me.id)
    if term:
        esc = term.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        stmt = stmt.where(or_(func.lower(User.mail_handle.cast(String)).like(esc + "%", escape="\\"),
                              User.display_name.ilike("%" + esc + "%", escape="\\"),
                              User.nickname.ilike("%" + esc + "%", escape="\\")))
    users = (await db.execute(stmt.order_by(User.display_name).limit(min(20, max(1, limit))))).scalars().all() if ids else []
    out = [{"kind": "person", "id": str(u.id), "handle": u.mail_handle or "",
            "display_name": display_of(u), "avatar_url": u.avatar_url}
           for u in users]

    # Secretaries anybody can talk to, mine included: naming one in a caption is asking it
    # to read the post and answer (plan/43 §6).
    from blackmoa.models import Agent, ShareLink
    from blackmoa.services import agents as A

    rows = (await db.execute(
        select(ShareLink, Agent, User).join(Agent, Agent.id == ShareLink.agent_id)
        .join(User, User.id == Agent.owner_id)
        .where(ShareLink.owner_id.in_(ids | {me.id}), A.open_link(), Agent.status == "active")
        .order_by(ShareLink.created_at))).all()
    seen: set[uuid.UUID] = set()
    for link, agent, holder in rows:
        if agent.id in seen:
            continue
        seen.add(agent.id)
        if term and term not in (agent.name or "").lower():
            continue
        # Whose it is travels with it: two people can each have a 제니, and a picker that
        # offers "제니" twice has told the reader nothing.
        out.append({"kind": "agent", "id": str(agent.id), "handle": "", "display_name": agent.name,
                    "avatar_url": agent.avatar_url, "link_code": link.code,
                    "owner_name": display_of(holder), "mine": agent.owner_id == me.id})
    return out[:max(1, limit) * 3]


async def suggestions(db: AsyncSession, me: User, limit: int = 24) -> list[dict[str, Any]]:
    """People to connect to, from evidence rather than from a user dump (plan/43 §3).

    Two signals, both about somebody who already did something:
      1. they connected to me and I have not answered — one tap makes it 인맥, and they
         already said they wanted it;
      2. they talked to my secretary and they have an account — the strongest thing this
         product knows about a stranger, and it is not a guess.

    Nothing here browses the account table, and nobody appears because of who their friends
    are: every name comes with something that person did.
    """
    rows = set((await db.execute(select(PersonFollow.follower_id, PersonFollow.target_id).where(
        or_(PersonFollow.follower_id == me.id, PersonFollow.target_id == me.id)))).all())
    out = {b for a, b in rows if a == me.id}
    back = {a for a, b in rows if b == me.id}
    # Anybody I already connected to is not a suggestion, whether or not they answered.
    skip = out | {me.id}

    scored: dict[uuid.UUID, dict[str, Any]] = {}
    # 1) they connected to me first
    for uid in back - skip:
        u = await db.get(User, uid)
        if u is None or u.status != "active":
            continue
        scored[uid] = {**_account_out(u), "reason": "connected_me", "reason_detail": None,
                       "mutual": 0, "rank": 200, "link": _state(False, True)}
    # 2) guests of mine who turned out to have accounts
    visitors = (await db.execute(select(Visitor).where(Visitor.owner_id == me.id, Visitor.turn_count > 0)
                                 .order_by(Visitor.last_seen_at.desc()).limit(200))).scalars().all()
    emails = {v.email.lower() for v in visitors if v.email}
    by_email = {u.email.lower(): u for u in (await db.execute(select(User).where(
        func.lower(User.email.cast(String)).in_(emails), User.status == "active"))).scalars().all()} if emails else {}
    for v in visitors:
        u = (await db.get(User, v.user_id)) if v.user_id else (by_email.get(v.email.lower()) if v.email else None)
        if u is None or u.id in skip or u.id in scored or u.status != "active":
            continue
        scored[u.id] = {**_account_out(u), "reason": "guest", "reason_detail": v.display_name or None,
                        "mutual": 0, "rank": 100 + int(v.turn_count or 0), "link": _state(False, u.id in back)}
    ordered = sorted(scored.values(), key=lambda r: r["rank"], reverse=True)
    for r in ordered:
        r.pop("rank", None)
    return ordered[:limit]


# ── the photo album ────────────────────────────────────────────────

# ── proposals, resolved against real people ────────────────────────

def _payload_identity(pl: dict[str, Any]) -> tuple[str | None, str | None]:
    """The name and the address a proposal is talking about."""
    name = (pl.get("name") or "").strip() or None
    attrs = pl.get("attrs") if isinstance(pl.get("attrs"), dict) else {}
    email = None
    for v in ((attrs or {}).get("emails") or []):
        if isinstance(v, str) and "@" in v:
            email = v.strip().lower()
            break
    if not email and isinstance((attrs or {}).get("email"), str) and "@" in attrs["email"]:
        email = attrs["email"].strip().lower()
    return name, email


async def resolve_proposal(db: AsyncSession, owner: User, kind: str, payload: dict[str, Any]) -> dict[str, Any]:
    """What can actually be done about a proposed person.

    The secretary proposes people it heard about. Most of those it heard *about* — a third
    party mentioned in passing — and turning each into a card was how the queue filled with
    rows nobody could act on and the graph filled with names that were never anybody.

    A proposal is only actionable when it lands on someone this system can reach:

      connect   → they have a black-moa account; accepting sends an 인맥 신청
      add_guest → they talked to this owner's secretary; accepting binds that guest
      none      → nobody the system can act on. Not a card. Nothing.
    """
    if kind != "add_node" or (payload.get("kind") or "person") != "person":
        return {"action": "none"}
    name, email = _payload_identity(payload)
    if not name and not email:
        return {"action": "none"}

    # 1) an account — the strongest resolution, and the only one that ends in a connection.
    user: User | None = None
    if email:
        user = (await db.execute(select(User).where(func.lower(User.email.cast(String)) == email,
                                                    User.status == "active"))).scalars().first()
    if user is not None and user.id != owner.id:
        link = _state(*await conn_between(db, owner.id, user.id))
        if link and link["status"] in ("mutual", "outgoing"):
            return {"action": "none", "why": "already_connected"}
        return {"action": "connect", "person": {**_account_out(user), "link": link}}

    # 2) somebody who actually came to see me. Their conversations are the evidence.
    stmt = select(Visitor).where(Visitor.owner_id == owner.id, Visitor.turn_count > 0)
    if email:
        stmt = stmt.where(func.lower(Visitor.email) == email)
    elif name:
        stmt = stmt.where(func.lower(Visitor.display_name) == name.lower())
    v = (await db.execute(stmt.order_by(Visitor.last_seen_at.desc()))).scalars().first()
    if v is not None:
        # The visitor may turn out to be an account even when the proposal carried no
        # address — matched by name, or bound by a later login. If they are, asking is the
        # only honest action: a card for someone who is here is a copy they never agreed to.
        vu = await db.get(User, v.user_id) if v.user_id else None
        if vu is None and v.email:
            vu = (await db.execute(select(User).where(func.lower(User.email.cast(String)) == v.email.lower(),
                                                      User.status == "active"))).scalars().first()
        if vu is not None and vu.id != owner.id:
            link = _state(*await conn_between(db, owner.id, vu.id))
            if link and link["status"] in ("mutual", "outgoing"):
                return {"action": "none", "why": "already_connected"}
            return {"action": "connect", "person": {**_account_out(vu), "link": link}}
        node = (await db.execute(select(NetworkNode).where(NetworkNode.owner_id == owner.id,
                                                            NetworkNode.visitor_id == v.id))).scalars().first()
        if node is not None:
            return {"action": "none", "why": "already_in_network"}
        return {"action": "add_guest", "visitor_id": str(v.id),
                "person": {"id": str(v.id), "display_name": v.display_name or "이름 없는 방문자",
                           "avatar_url": None, "handle": None, "turns": int(v.turn_count or 0)}}
    return {"action": "none"}


async def pending_proposals(db: AsyncSession, owner: User, limit: int = 200) -> list[dict[str, Any]]:
    """The proposals worth showing, with the one action each of them has.

    Anything that resolves to nobody is retired here rather than left to accumulate: a queue
    of things that cannot be done is not a queue, and the owner reading it learns to ignore
    the whole tab.
    """
    from blackmoa.models import NetworkProposal

    rows = (await db.execute(select(NetworkProposal).where(NetworkProposal.owner_id == owner.id,
                                                            NetworkProposal.status == "pending")
                             .order_by(NetworkProposal.created_at.desc()).limit(limit))).scalars().all()
    out: list[dict[str, Any]] = []
    retired = 0
    for p in rows:
        r = await resolve_proposal(db, owner, p.kind, p.payload or {})
        if r["action"] == "none" and p.kind == "add_node":
            p.status = "obsolete"
            p.decided_at = datetime.now(UTC)
            retired += 1
            continue
        out.append({"id": str(p.id), "kind": p.kind, "payload": p.payload, "confidence": p.confidence,
                    "status": p.status, "agent_id": str(p.agent_id) if p.agent_id else None,
                    "created_at": p.created_at.isoformat(), "resolved": r})
    if retired:
        log.info("retired proposals nobody could act on", owner=str(owner.id), count=retired)
    return out


async def accept_proposal(db: AsyncSession, owner: User, proposal_id: uuid.UUID) -> dict[str, Any]:
    """Accepting a person proposal does the real thing, not a card."""
    from blackmoa.models import NetworkProposal

    p = await db.get(NetworkProposal, proposal_id)
    if p is None or p.owner_id != owner.id:
        raise NotFound("proposal not found", code="proposal_not_found")
    if p.status != "pending":
        raise Conflict("this proposal was already answered", code="proposal_decided")
    r = await resolve_proposal(db, owner, p.kind, p.payload or {})
    if r["action"] == "connect":
        await connect(db, owner, uuid.UUID(r["person"]["id"]))
    elif r["action"] == "add_guest":
        await add_guest(db, owner, uuid.UUID(r["visitor_id"]))
    else:
        # Retire it in its own session: this path raises, the request rolls back, and the
        # row would come back pending for the owner to press again on the next load.
        from blackmoa.db.session import session_scope
        from blackmoa.models import NetworkProposal as _NP
        async with session_scope() as s2:
            stale = await s2.get(_NP, proposal_id)
            if stale is not None and stale.status == "pending":
                stale.status, stale.decided_at = "obsolete", datetime.now(UTC)
        raise ValidationFailed("there is nobody here to add", code="proposal_unresolvable")
    p.status, p.decided_at = "accepted", datetime.now(UTC)
    return r
