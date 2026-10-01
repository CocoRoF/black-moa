"""Cross-agent conversations, agent stats, Prometheus metrics, client telemetry."""
from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Request
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel
from sqlalchemy import func, select

from blackmoa.core.deps import DB, CurrentUser
from blackmoa.core.logging import get_logger
from blackmoa.core.ratelimit import limiter
from blackmoa.core.watchdog import loop_lag
from blackmoa.memory.synapse import index_cache
from blackmoa.models import Conversation, InboxItem, Job, Turn, UsageEvent
from blackmoa.pipeline.events import journals
from blackmoa.pipeline.runtime import runtimes
from blackmoa.services import agents as AG

router = APIRouter(tags=["misc"])
log = get_logger("blackmoa.telemetry")


@router.get("/api/conversations")
async def all_conversations(user: CurrentUser, db: DB, audience: str | None = None, limit: int = 50, q: str | None = None):
    from blackmoa.api.chat import conv_out
    stmt = select(Conversation).where(Conversation.owner_id == user.id, Conversation.simulated.is_(False)).order_by(
        Conversation.last_message_at.desc().nullslast()).limit(min(limit, 200))
    if audience:
        stmt = stmt.where(Conversation.audience == audience)
    if q:
        stmt = stmt.where((Conversation.title.ilike(f"%{q}%")) | (Conversation.summary.ilike(f"%{q}%")))
    rows = (await db.execute(stmt)).scalars().all()
    return {"items": [conv_out(c) for c in rows]}


@router.get("/api/agents/{agent_id}/stats")
async def agent_stats(agent_id: uuid.UUID, user: CurrentUser, db: DB, days: int = 7):
    a = await AG.get_owned(db, user.id, agent_id, include_archived=True)
    since = datetime.now(UTC) - timedelta(days=min(days, 90))
    t = (await db.execute(select(func.count(Turn.id), func.coalesce(func.sum(Turn.credits), 0), func.avg(Turn.ttft_ms),
                                 func.sum(func.cast(Turn.audience == "visitor", __import__("sqlalchemy").Integer)),
                                 func.sum(func.cast(Turn.status == "failed", __import__("sqlalchemy").Integer)))
                          .where(Turn.agent_id == a.id, Turn.started_at >= since))).one()
    convs = (await db.execute(select(Conversation.audience, func.count()).where(Conversation.agent_id == a.id, Conversation.created_at >= since,
                                                                                Conversation.simulated.is_(False)).group_by(Conversation.audience))).all()
    inbox = (await db.execute(select(InboxItem.kind, func.count()).where(InboxItem.agent_id == a.id, InboxItem.created_at >= since).group_by(InboxItem.kind))).all()
    day_col = func.date_trunc("day", Turn.started_at).label("day")
    daily = (await db.execute(select(day_col, func.count(), func.coalesce(func.sum(Turn.credits), 0))
                              .where(Turn.agent_id == a.id, Turn.started_at >= since).group_by(day_col).order_by(day_col))).all()
    total_convs = int((await db.execute(select(func.count(Conversation.id)).where(Conversation.agent_id == a.id, Conversation.simulated.is_(False)))).scalar_one())
    return {"days": days, "turns": t[0], "credits": float(t[1] or 0), "avg_ttft_ms": int(t[2] or 0), "visitor_turns": int(t[3] or 0), "failed": int(t[4] or 0),
            "conversations": {k: n for k, n in convs}, "conversations_total": total_convs, "inbox": {k: n for k, n in inbox},
            "daily": [{"day": d.date().isoformat(), "turns": n, "credits": float(c or 0)} for d, n, c in daily]}


def _metrics_allowed(request: Request) -> bool:
    """Scrapers on the docker/private network, or an admin bearer. nginx does not proxy /metrics, this is defence in depth."""
    import ipaddress

    from blackmoa.core.deps import bearer
    from blackmoa.core.security import decode_access_token
    host = request.client.host if request.client else ""
    try:
        ip = ipaddress.ip_address(host)
        if ip.is_private or ip.is_loopback or ip.is_link_local:
            return True
    except ValueError:
        pass
    tok = bearer(request)
    if tok:
        try:
            return decode_access_token(tok).get("role") == "admin"
        except Exception:
            return False
    return False


@router.get("/metrics", response_class=PlainTextResponse)
async def metrics(request: Request, db: DB):
    if not _metrics_allowed(request):
        from blackmoa.core.errors import Forbidden
        raise Forbidden("metrics are internal", code="metrics_forbidden")
    lines = [
        f"blackmoa_loop_lag_seconds {loop_lag():.3f}", f"blackmoa_runtime_sessions {runtimes.count()}",
        f"blackmoa_active_turns {journals.active_count()}", f"blackmoa_open_indexes {index_cache.open_count()}",
    ]
    since = datetime.now(UTC) - timedelta(hours=24)
    rows = (await db.execute(select(Turn.audience, Turn.status, func.count()).where(Turn.started_at >= since).group_by(Turn.audience, Turn.status))).all()
    for aud, st, n in rows:
        lines.append(f'blackmoa_turns_24h{{audience="{aud}",status="{st}"}} {n}')
    cred = (await db.execute(select(func.coalesce(func.sum(UsageEvent.credits), 0)).where(UsageEvent.created_at >= since))).scalar_one()
    lines.append(f"blackmoa_credits_charged_24h {float(cred or 0):.4f}")
    jobs = (await db.execute(select(Job.status, func.count()).group_by(Job.status))).all()
    for st, n in jobs:
        lines.append(f'blackmoa_jobs{{status="{st}"}} {n}')
    return "\n".join(lines) + "\n"


class ClientError(BaseModel):
    message: str
    stack: str | None = None
    url: str | None = None
    ua: str | None = None


@router.post("/api/telemetry/client-error", status_code=202)
async def client_error(body: ClientError, request: Request):
    ip = request.headers.get("cf-connecting-ip") or (request.client.host if request.client else "?")
    limiter.check(f"telemetry:{ip}", 20, 60)
    log.warning("client error", message=body.message[:300], url=(body.url or "")[:200], stack=(body.stack or "")[:800])
    return {"ok": True}
