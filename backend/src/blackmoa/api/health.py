from __future__ import annotations

import shutil
from datetime import UTC, datetime, timedelta

from fastapi import APIRouter
from sqlalchemy import select, text

from blackmoa.config import get_settings
from blackmoa.core.watchdog import loop_lag
from blackmoa.db.session import session_scope
from blackmoa.memory.synapse import index_cache
from blackmoa.models import WorkerHeartbeat
from blackmoa.pipeline.events import journals
from blackmoa.pipeline.runtime import runtimes

router = APIRouter(tags=["health"])


@router.get("/health")
async def health():
    lag = loop_lag()
    return {"status": "degraded" if lag > 0.5 else "ok", "loop_lag_s": round(lag, 3), "runtimes": runtimes.count(),
            "active_turns": journals.active_count(), "open_indexes": index_cache.open_count()}


@router.get("/health/ready")
async def ready():
    s = get_settings()
    out = {"status": "ok", "db": "ok", "data": "ok", "worker": "ok", "claude_credentials": "unknown"}
    try:
        async with session_scope() as db:
            await db.execute(text("SELECT 1"))
            hb = (await db.execute(select(WorkerHeartbeat).order_by(WorkerHeartbeat.last_seen_at.desc()))).scalars().first()
            if hb is None or hb.last_seen_at < datetime.now(UTC) - timedelta(seconds=90):
                out["worker"] = "stale"
    except Exception as e:  # noqa: BLE001
        out["db"] = f"error: {e.__class__.__name__}"
    try:
        p = s.data_dir / ".write-test"
        p.write_text("ok")
        p.unlink()
        usage = shutil.disk_usage(s.data_dir)
        out["disk_free_gb"] = round(usage.free / 1e9, 1)
    except Exception as e:  # noqa: BLE001
        out["data"] = f"error: {e.__class__.__name__}"
    try:
        out["claude_credentials"] = "present" if (s.claude_home / ".credentials.json").exists() else "missing"
    except OSError:
        out["claude_credentials"] = "unreadable"
    if out["db"] != "ok" or out["data"] != "ok":
        out["status"] = "error"
    from fastapi.responses import JSONResponse
    return JSONResponse(status_code=503 if out["status"] == "error" else 200, content=out)
