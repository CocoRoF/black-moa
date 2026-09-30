"""FastAPI dependencies: db session, current user / admin / visitor, request context."""
from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Annotated

from fastapi import Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from memora.core.errors import Forbidden, Unauthorized
from memora.core.security import decode_access_token, decode_visitor_token
from memora.db.session import get_session
from memora.models import User

DB = Annotated[AsyncSession, Depends(get_session)]


async def release_db(request: Request) -> None:
    """Give this request's database connection back, now.

    For every ordinary endpoint FastAPI's timing is right: the session lives until the
    response is out. For a streaming one it is a leak with a hard ceiling. An SSE response
    ends when the client goes away — minutes for a chat turn, hours for a browser tab
    watching notifications — and the session is held for all of it. Measured against
    production: twelve open notification streams held twelve connections in
    ``idle in transaction``, out of a pool of thirty. At thirty open tabs every request in
    the service queues for a connection, and ``idle in transaction`` additionally stops
    VACUUM reclaiming anything.

    A streaming endpoint has finished with its session by the time it hands over the
    generator, so this is called at the top of the generator — before the first wait, and
    inside the thing that does the waiting, so it cannot be forgotten at a call site.
    ``close()`` is idempotent, so FastAPI closing it again later is a no-op.
    """
    db = getattr(request.state, "db", None)
    if db is None:
        return
    # The manager hands back the connection *and* this lane's right to take one. Closing
    # the session alone would leave the slot held for the whole stream.
    release = db.info.get("memora_release") if hasattr(db, "info") else None
    if release is not None:
        await release()
    else:
        await db.close()


def bearer(request: Request) -> str | None:
    auth = request.headers.get("authorization", "")
    if auth.lower().startswith("bearer "):
        return auth[7:].strip()
    return None


def client_ip(request: Request) -> str:
    return (
        request.headers.get("cf-connecting-ip")
        or (request.headers.get("x-forwarded-for", "").split(",")[0].strip())
        or (request.client.host if request.client else "0.0.0.0")
    )


async def current_user(request: Request, db: DB) -> User:
    token = bearer(request)
    if not token:
        raise Unauthorized("missing token", code="missing_token")
    payload = decode_access_token(token)
    user = await db.get(User, uuid.UUID(payload["sub"]))
    if user is None or user.status != "active":
        raise Unauthorized("user inactive", code="user_inactive")
    request.state.user = user
    # The traffic recorder reads this from the scope: a request with a name on it is the
    # difference between "something is hammering the API" and knowing who.
    request.scope["memora_owner_id"] = user.id
    return user


async def current_admin(user: Annotated[User, Depends(current_user)]) -> User:
    if user.role != "admin":
        raise Forbidden("admin only", code="admin_only")
    return user


async def current_super_admin(user: Annotated[User, Depends(current_admin)]) -> User:
    """The maintainer. Guards the small set of actions that change who is an admin."""
    if not user.is_super:
        raise Forbidden("only the super administrator can do that", code="super_admin_only")
    return user


async def optional_user(request: Request, db: DB) -> User | None:
    """The signed-in account, when there is one.

    Public pages are reachable without an account, but a visitor who *is* signed in should
    be recognised rather than treated as a stranger — so a bad or missing token is not an
    error here, it just means "anonymous".
    """
    token = bearer(request)
    if not token:
        return None
    try:
        payload = decode_access_token(token)
        user = await db.get(User, uuid.UUID(payload["sub"]))
    except Exception:  # noqa: BLE001 — an unreadable token is simply not a session
        return None
    return user if user is not None and user.status == "active" else None


CurrentUser = Annotated[User, Depends(current_user)]
OptionalUser = Annotated[User | None, Depends(optional_user)]
CurrentAdmin = Annotated[User, Depends(current_admin)]
CurrentSuperAdmin = Annotated[User, Depends(current_super_admin)]


@dataclass
class VisitorCtx:
    visitor_id: uuid.UUID
    agent_id: uuid.UUID
    code: str


def current_visitor(request: Request) -> VisitorCtx:
    token = bearer(request)
    if not token:
        raise Unauthorized("missing visitor token", code="missing_token")
    p = decode_visitor_token(token)
    return VisitorCtx(visitor_id=uuid.UUID(p["sub"]), agent_id=uuid.UUID(p["agent"]), code=p["code"])


CurrentVisitor = Annotated[VisitorCtx, Depends(current_visitor)]
