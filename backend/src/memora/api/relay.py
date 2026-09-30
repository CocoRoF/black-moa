"""Secretary-to-secretary conversations (plan/38): the owner's view, and the worker's hop entry point."""
from __future__ import annotations

import hmac
import uuid

from fastapi import APIRouter, Header
from pydantic import BaseModel

from memora.core.deps import DB, CurrentUser
from memora.core.errors import Forbidden
from memora.services import agents as AG
from memora.services import relay as REL

router = APIRouter(prefix="/api", tags=["relay"])
internal = APIRouter(prefix="/internal/relay", tags=["internal"])


class RelayIn(BaseModel):
    target: str
    message: str
    purpose: str = ""
    max_messages: int | None = None
    credit_cap: float | None = None


@router.post("/agents/{agent_id}/relays", status_code=201)
async def start_relay(agent_id: uuid.UUID, body: RelayIn, user: CurrentUser, db: DB):
    a = await AG.get_owned(db, user.id, agent_id)
    relay = await REL.start(db, owner=user, agent=a, target=body.target, message=body.message, purpose=body.purpose,
                            max_messages=body.max_messages, credit_cap=body.credit_cap)
    await db.commit()
    return await REL.relay_out(db, relay, user.id)


@router.get("/relays")
async def list_relays(user: CurrentUser, db: DB, agent_id: uuid.UUID | None = None, role: str | None = None, limit: int = 100):
    return {"items": await REL.list_for_owner(db, user.id, agent_id=agent_id, role=role if role in ("initiator", "target") else None,
                                              limit=max(1, min(200, limit)))}


@router.get("/relays/{relay_id}")
async def get_relay(relay_id: uuid.UUID, user: CurrentUser, db: DB):
    r = await REL.get_party(db, relay_id, user.id)
    return await REL.detail(db, r, user.id)


@router.post("/relays/{relay_id}/stop")
async def stop_relay(relay_id: uuid.UUID, user: CurrentUser, db: DB):
    r = await REL.get_party(db, relay_id, user.id)
    await REL.stop(db, r, owner_id=user.id)
    await db.commit()
    return await REL.detail(db, r, user.id)


class HopIn(BaseModel):
    relay_id: uuid.UUID


class PostReplyIn(BaseModel):
    post_id: uuid.UUID
    agent_id: uuid.UUID


@internal.post("/post-reply")
async def internal_post_reply(body: PostReplyIn, db: DB, x_memora_internal: str = Header(default="")):
    """A secretary that was named in a post reads it and answers (plan/43 §6). Turns run
    here, so the worker asks this process to do it."""
    if not hmac.compare_digest(x_memora_internal or "", REL.internal_token()):
        raise Forbidden("internal only", code="forbidden")
    from memora.services import blog as B

    out = await B.secretary_reply(db, body.post_id, body.agent_id)
    await db.commit()
    return out


class DescribeIn(BaseModel):
    post_id: uuid.UUID


@internal.post("/describe-photos")
async def internal_describe_photos(body: DescribeIn, db: DB, x_memora_internal: str = Header(default="")):
    """사진만 올린 글을 비서가 한 번 들여다본다 (plan/45 §2). 턴은 여기서 돈다."""
    if not hmac.compare_digest(x_memora_internal or "", REL.internal_token()):
        raise Forbidden("internal only", code="forbidden")
    from memora.services import blog as B

    out = await B.describe_photos(db, body.post_id)
    await db.commit()
    return out


@internal.post("/hop")
async def internal_hop(body: HopIn, db: DB, x_memora_internal: str = Header(default="")):
    """The worker asks the API process — where turns run — to answer the pending message."""
    if not hmac.compare_digest(x_memora_internal or "", REL.internal_token()):
        raise Forbidden("internal only", code="forbidden")
    out = await REL.run_hop(db, body.relay_id)
    await db.commit()
    return out
