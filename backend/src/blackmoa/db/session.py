"""Sessions, from the one manager that owns them.

This module used to build an engine at import time and hand the same sessionmaker to
everything. It is now a thin front on ``core.database.manager`` — the names are unchanged
because two hundred call sites use them, but every connection they hand out is pooled,
lane-limited, health-checked and reconnecting. See ``core/database.py`` for why.
"""
from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import Request
from sqlalchemy.ext.asyncio import AsyncSession

from blackmoa.core.database import manager


def __getattr__(name: str):
    """``engine`` and ``SessionLocal`` resolve through the manager.

    Module attributes rather than constants so that a rebuilt engine is picked up by
    anything holding a reference — a module-level ``engine = ...`` would keep handing out
    the disposed one after a reconnect.
    """
    if name == "engine":
        return manager.engine
    if name == "SessionLocal":
        return manager.sessionmaker
    raise AttributeError(name)


def lane_for(request: Request) -> str:
    """Which class of work this request's session belongs to, so one class cannot take the
    whole pool. The lanes are the traffic dashboard's lanes; ``worker`` is its own."""
    from blackmoa.core.traffic import lane_of

    return lane_of(request.url.path)


async def get_session(request: Request) -> AsyncIterator[AsyncSession]:
    """The request's session.

    Parked on ``request.state`` so that a streaming endpoint can give the connection back
    the moment it is done with it — see ``core.deps.release_db``. FastAPI unwinds generator
    dependencies only after the response body has been sent, which for SSE is when the
    client goes away.
    """
    async with manager.session(lane_for(request), commit=False) as session:
        request.state.db = session
        yield session


@asynccontextmanager
async def session_scope(lane: str = "other") -> AsyncIterator[AsyncSession]:
    """A transaction that commits on success and rolls back on error."""
    async with manager.session(lane) as session:
        yield session
