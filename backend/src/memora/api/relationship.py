"""The relationship between an owner and a secretary (plan/37): state, journal, proactive messages."""
from __future__ import annotations

import uuid

from fastapi import APIRouter
from pydantic import BaseModel

from memora.core.deps import DB, CurrentUser
from memora.core.errors import ValidationFailed
from memora.services import agents as AG
from memora.services import jobs as J
from memora.services import relationship as REL
from memora.services import triggers as TR

router = APIRouter(prefix="/api", tags=["relationship"])


def _loc(user) -> str:
    return "en" if (user.locale or "ko").startswith("en") else "ko"


@router.get("/relationships")
async def list_relationships(user: CurrentUser, db: DB):
    return {"items": await REL.brief_for_user(db, user.id, _loc(user))}


@router.get("/agents/{agent_id}/relationship")
async def get_relationship(agent_id: uuid.UUID, user: CurrentUser, db: DB):
    a = await AG.get_owned(db, user.id, agent_id, include_archived=True)
    rel = await REL.get(db, user.id, a.id)
    if rel is not None:
        # The calendar moves the stage too (anniversaries), not only turns — and the
        # distiller adds memories between turns, so the count is refreshed on read.
        rel.facts_remembered = await REL.count_facts(db, user.id, a.id)
        REL.refresh_stage(rel, a)
        await db.commit()
    return REL.rel_out(rel, a, _loc(user), triggers=await TR.config(db))


@router.get("/agents/{agent_id}/relationship/journal")
async def get_journal(agent_id: uuid.UUID, user: CurrentUser, db: DB, limit: int = 60):
    a = await AG.get_owned(db, user.id, agent_id, include_archived=True)
    return {"items": await REL.journal(db, owner=user, agent=a, limit=max(1, min(200, limit)))}


class MoodIn(BaseModel):
    state: str = ""
    reason: str = ""
    hours: int = 24


class RelPatch(BaseModel):
    mood: MoodIn | None = None


@router.patch("/agents/{agent_id}/relationship")
async def patch_relationship(agent_id: uuid.UUID, body: RelPatch, user: CurrentUser, db: DB):
    a = await AG.get_owned(db, user.id, agent_id)
    rel = await REL.get_or_create(db, user.id, a.id)
    if body.mood is not None:
        if body.mood.state and body.mood.state not in REL.MOODS:
            raise ValidationFailed("unknown mood")
        REL.set_mood(rel, body.mood.state, body.mood.reason, body.mood.hours)
    await db.commit()
    return REL.rel_out(rel, a, _loc(user), triggers=await TR.config(db))


class ProactiveIn(BaseModel):
    kind: str | None = None


@router.post("/agents/{agent_id}/relationship/proactive", status_code=202)
async def send_proactive(agent_id: uuid.UUID, body: ProactiveIn, user: CurrentUser, db: DB):
    """"Say something now": the owner asks the secretary to send a message first, regardless of
    the daily cap — but never inside the quiet window after their own last message."""
    from datetime import timedelta

    from memora.core.errors import Conflict

    a = await AG.get_owned(db, user.id, agent_id)
    if a.status != "active":
        raise ValidationFailed("agent is not active", code="agent_not_active")
    if body.kind is not None and body.kind not in REL.PROACTIVE_KINDS:
        raise ValidationFailed("unknown kind")
    recent = await REL.recent_owner_turn(db, user.id, a.id)
    if recent is not None:
        until = recent + timedelta(minutes=REL.QUIET_MINUTES)
        raise Conflict("the owner talked to this secretary a moment ago", code="too_soon",
                       detail={"quiet_until": until.isoformat(), "quiet_minutes": REL.QUIET_MINUTES})
    rel = await REL.get_or_create(db, user.id, a.id)
    job = await J.enqueue(db, "relationship.proactive", {"agent_id": str(a.id), "user_id": str(user.id), "kind": body.kind, "force": True},
                          priority=3, owner_id=user.id)
    await db.commit()
    return {"queued": True, "job_id": str(job.id) if job is not None else None,
            "last_proactive_at": rel.last_proactive_at.isoformat() if rel.last_proactive_at else None}


@router.get("/agents/{agent_id}/relationship/proactive/{job_id}")
async def proactive_status(agent_id: uuid.UUID, job_id: uuid.UUID, user: CurrentUser, db: DB):
    """Where the requested message is: waiting for a worker, being written, delivered, or not sent (and why)."""
    from datetime import UTC, datetime

    from memora.core.errors import NotFound
    from memora.models import Job

    await AG.get_owned(db, user.id, agent_id)
    job = await db.get(Job, job_id)
    if job is None or job.kind != "relationship.proactive" or job.owner_id != user.id:
        raise NotFound("job not found")
    now = datetime.now(UTC)
    res = job.result if isinstance(job.result, dict) else {}
    phase = "queued" if job.status == "queued" else "writing" if job.status == "running" else \
        "sent" if job.status == "done" and res.get("sent") else "skipped" if job.status == "done" else "failed"
    return {"status": job.status, "phase": phase, "kind": res.get("sent"), "skipped": res.get("skipped"),
            "conversation_id": res.get("conversation_id"), "message_id": res.get("message_id"),
            "elapsed_s": int((now - job.created_at).total_seconds()),
            "writing_s": int((now - job.locked_at).total_seconds()) if job.status == "running" and job.locked_at else None,
            "error": (job.last_error or "")[:200] if job.status in ("failed", "dead") else None}
