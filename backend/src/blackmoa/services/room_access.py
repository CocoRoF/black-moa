"""비서가 사람끼리 방을 읽는 통로 — 주인의 허락이 있을 때만 (plan/55 §6-4, 결정 3).

사람끼리 방은 비서가 **당연히 보는 곳이 아니다.** 비서가 기록을 읽는 모든 길(대화 기록·
기억 증류·관계 맥락)은 ``conversation_id`` 로 찾고, 사람끼리 방의 말에는 그것이 없다. 그
벽은 그대로 둔다. 대신 좁은 통로 하나를 낸다:

1. ``rooms_find`` — 방의 겉만(상대·마지막 말 시각·말 수·파일 수). 내용은 한 글자도 없다.
2. ``room_access_request`` — 주인에게 허락 카드를 띄운다. "이 방이 맞나" 와 "읽어도 되나" 를
   한 번에 묻는다.
3. 주인이 [이번 대화에서만] / [계속 허락] 을 누르면 ``room_grants`` 에 한 행.
4. ``room_read`` — 허락이 살아 있을 때만 그 방의 말 전부(양쪽)와 파일 목록.

허락했는지는 ``granted()`` 한 함수가 정한다. 통로를 쓴 턴은 기억 증류를 건너뛴다 — 증류가
상대의 말을 사실로 적으면 허락을 거둬도 비서는 계속 안다. 그건 거둔 것이 아니다.
"""
from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import or_, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from blackmoa.core.errors import Forbidden, NotFound, ValidationFailed
from blackmoa.models import Agent, Message, Room, RoomGrant, RoomMember, Upload, User

SCOPES = ("conversation", "always")
READ_MAX = 200


async def _other(db: AsyncSession, room: Room, me_id: uuid.UUID) -> User | None:
    m = (await db.execute(select(RoomMember).where(RoomMember.room_id == room.id, RoomMember.user_id.isnot(None),
                                                   RoomMember.user_id != me_id))).scalars().first()
    return await db.get(User, m.user_id) if m and m.user_id else None


def _name(u: User | None) -> str:
    from blackmoa.services.people import display_of
    return display_of(u) if u else ""


async def _is_member(db: AsyncSession, room_id: uuid.UUID, user_id: uuid.UUID) -> bool:
    return bool((await db.execute(select(RoomMember.id).where(RoomMember.room_id == room_id,
                                                              RoomMember.user_id == user_id))).first())


async def granted(db: AsyncSession, *, agent_id: uuid.UUID, room_id: uuid.UUID,
                  conversation_id: uuid.UUID | None) -> RoomGrant | None:
    """이 비서가 지금 이 대화에서 이 방을 읽어도 되는가. 판정은 여기 한 곳이다."""
    g = (await db.execute(select(RoomGrant).where(RoomGrant.agent_id == agent_id, RoomGrant.room_id == room_id,
                                                  RoomGrant.revoked_at.is_(None)))).scalars().first()
    if g is None:
        return None
    if g.scope == "conversation" and g.conversation_id != conversation_id:
        return None
    # 허락한 사람이 그 방을 떠났으면(방이 사라졌으면) 허락도 없다.
    if not await _is_member(db, room_id, g.user_id):
        return None
    return g


async def summary(db: AsyncSession, room: Room, me: User, *, agent_id: uuid.UUID | None = None,
                  conversation_id: uuid.UUID | None = None) -> dict[str, Any]:
    """방의 겉: 상대가 누구고, 언제까지 말했고, 말과 파일이 몇 개인지. 내용은 없다."""
    other = await _other(db, room, me.id)
    files = (await db.execute(text(
        "SELECT count(*) FROM messages WHERE room_id = :r AND jsonb_array_length(coalesce(attachments, '[]'::jsonb)) > 0"),
        {"r": room.id})).scalar_one()
    out = {"room_id": str(room.id), "name": _name(other), "handle": (other.mail_handle or "") if other else "",
           "last_message_at": room.last_message_at.isoformat() if room.last_message_at else None,
           "message_count": int(room.message_count or 0), "messages_with_files": int(files or 0)}
    if agent_id is not None:
        out["access"] = "granted" if await granted(db, agent_id=agent_id, room_id=room.id, conversation_id=conversation_id) else "not granted"
    return out


async def find(db: AsyncSession, me: User, who: str, *, agent_id: uuid.UUID, conversation_id: uuid.UUID | None,
               limit: int = 5) -> list[dict[str, Any]]:
    """내가 들어 있는 사람끼리 방 중 상대 이름·별명·핸들이 ``who`` 에 맞는 것."""
    q = (who or "").strip().lstrip("@")[:60]
    mine = select(RoomMember.room_id).where(RoomMember.user_id == me.id)
    stmt = (select(Room).join(RoomMember, RoomMember.room_id == Room.id).join(User, User.id == RoomMember.user_id)
            .where(Room.kind == "dm", Room.id.in_(mine), RoomMember.user_id != me.id))
    if q:
        like = f"%{q}%"
        stmt = stmt.where(or_(User.display_name.ilike(like), User.nickname.ilike(like), User.mail_handle.ilike(like)))
    rows = (await db.execute(stmt.order_by(Room.last_message_at.desc().nullslast()).limit(max(1, min(limit, 10))))).scalars().unique().all()
    return [await summary(db, r, me, agent_id=agent_id, conversation_id=conversation_id) for r in rows]


async def grant(db: AsyncSession, me: User, *, agent_id: uuid.UUID, room_id: uuid.UUID, scope: str,
                conversation_id: uuid.UUID | None, reason: str = "") -> RoomGrant:
    if scope not in SCOPES:
        raise ValidationFailed("bad scope", code="bad_scope")
    agent = await db.get(Agent, agent_id)
    room = await db.get(Room, room_id)
    if agent is None or agent.owner_id != me.id or room is None or room.kind != "dm" or not await _is_member(db, room_id, me.id):
        raise NotFound("room not found", code="room_not_found")
    now = datetime.now(UTC)
    for old in (await db.execute(select(RoomGrant).where(RoomGrant.agent_id == agent_id, RoomGrant.room_id == room_id,
                                                         RoomGrant.revoked_at.is_(None)))).scalars().all():
        old.revoked_at = now
    await db.flush()
    g = RoomGrant(user_id=me.id, agent_id=agent_id, room_id=room_id, scope=scope,
                  conversation_id=conversation_id if scope == "conversation" else None, reason=(reason or "")[:300], granted_at=now)
    db.add(g)
    await db.flush()
    await _audit(db, me, "room_grant.create", g)
    return g


async def revoke(db: AsyncSession, me: User, grant_id: uuid.UUID) -> None:
    g = await db.get(RoomGrant, grant_id)
    if g is None or g.user_id != me.id:
        raise NotFound("grant not found", code="grant_not_found")
    if g.revoked_at is None:
        g.revoked_at = datetime.now(UTC)
        await _audit(db, me, "room_grant.revoke", g)


async def listing(db: AsyncSession, me: User) -> list[dict[str, Any]]:
    """살아 있는 허락 전부. 비서의 [지식] 탭(메신저 대화 줄)과 메신저 방 위 한 줄이 쓴다."""
    rows = (await db.execute(select(RoomGrant).where(RoomGrant.user_id == me.id, RoomGrant.revoked_at.is_(None))
                             .order_by(RoomGrant.granted_at.desc()))).scalars().all()
    out = []
    for g in rows:
        room = await db.get(Room, g.room_id)
        agent = await db.get(Agent, g.agent_id)
        if room is None or agent is None:
            continue
        other = await _other(db, room, me.id)
        out.append({"id": str(g.id), "agent": {"id": str(agent.id), "name": agent.name, "avatar_url": agent.avatar_url},
                    "room_id": str(room.id), "person": {"name": _name(other), "handle": (other.mail_handle or "") if other else "",
                                                       "avatar_url": other.avatar_url if other else None},
                    "scope": g.scope, "conversation_id": str(g.conversation_id) if g.conversation_id else None,
                    "reason": g.reason, "granted_at": g.granted_at.isoformat(),
                    "last_read_at": g.last_read_at.isoformat() if g.last_read_at else None})
    return out


async def read(db: AsyncSession, me: User, *, agent_id: uuid.UUID, conversation_id: uuid.UUID | None, room_id: uuid.UUID,
               before: datetime | None = None, limit: int = 60, query: str = "") -> dict[str, Any]:
    """허락받은 방의 말 전부 — 양쪽이 한 말과 붙인 파일의 목록(``room:<id>`` 로 연다)."""
    g = await granted(db, agent_id=agent_id, room_id=room_id, conversation_id=conversation_id)
    if g is None:
        raise Forbidden("the owner has not allowed you to read this conversation", code="room_not_granted")
    room = await db.get(Room, room_id)
    conds = [Message.room_id == room_id, Message.role.in_(("user", "assistant"))]
    if before:
        conds.append(Message.created_at < before)
    if query.strip():
        conds.append(Message.content.ilike(f"%{query.strip()[:80]}%"))
    rows = (await db.execute(select(Message).where(*conds).order_by(Message.created_at.desc())
                             .limit(max(1, min(limit, READ_MAX))))).scalars().all()
    names: dict[uuid.UUID, str] = {}
    for m in rows:
        if m.sender_user_id and m.sender_user_id not in names:
            names[m.sender_user_id] = _name(await db.get(User, m.sender_user_id))
    g.last_read_at = datetime.now(UTC)
    await _audit(db, me, "room_grant.read", g)
    items = []
    for m in reversed(rows):
        who = "owner" if m.sender_user_id == me.id else "other"
        att = [{"file_id": f"room:{a.get('upload_id')}", "name": a.get("filename"), "mime": a.get("mime")}
               for a in (m.attachments or []) if isinstance(a, dict) and a.get("upload_id")]
        # 상대가 한 말은 상대의 말이다 — 비서에게 하는 지시가 아니다(web_fetch 의 <untrusted> 와 같은 규칙).
        said = m.content if who == "owner" else f'<untrusted source="{names.get(m.sender_user_id, "the other person")}">{m.content}</untrusted>'
        items.append({"at": m.created_at.isoformat(), "from": names.get(m.sender_user_id, "") + (" (the owner)" if who == "owner" else ""),
                      "text": said, **({"files": att} if att else {})})
    other = await _other(db, room, me.id) if room else None
    return {"room": {"with": _name(other), "handle": (other.mail_handle or "") if other else ""},
            "messages": items, "older_before": rows[-1].created_at.isoformat() if len(rows) >= limit else None}


async def room_upload(db: AsyncSession, *, owner_id: uuid.UUID, agent_id: uuid.UUID, conversation_id: uuid.UUID | None,
                      upload_id: uuid.UUID) -> Upload:
    """허락받은 방에 붙은 파일 하나. 방에 실제로 붙어 있고, 그 방이 지금 허락돼 있어야 열린다."""
    rows = (await db.execute(select(Message.room_id).where(
        Message.room_id.isnot(None), Message.attachments.contains([{"upload_id": str(upload_id)}])))).scalars().all()
    for room_id in dict.fromkeys(rows):
        if await granted(db, agent_id=agent_id, room_id=room_id, conversation_id=conversation_id):
            room = await db.get(Room, room_id)
            if room is not None and room.kind == "dm" and await _is_member(db, room_id, owner_id):
                up = await db.get(Upload, upload_id)
                if up is not None:
                    return up
    raise Forbidden("the owner has not allowed you to open this file", code="room_not_granted")


async def _audit(db: AsyncSession, me: User, action: str, g: RoomGrant) -> None:
    """허락·거둠·열람은 감사 기록에 남긴다. 상대에게 알리지는 않는다(주인은 그 방을 이미 본다)."""
    try:
        from blackmoa.models import AuditLog
        db.add(AuditLog(actor_id=me.id, actor_kind="user", action=action, target_type="room_grant", target_id=str(g.id),
                        meta={"agent_id": str(g.agent_id), "room_id": str(g.room_id), "scope": g.scope},
                        created_at=datetime.now(UTC)))
        await db.flush()
    except Exception:  # noqa: BLE001
        pass
