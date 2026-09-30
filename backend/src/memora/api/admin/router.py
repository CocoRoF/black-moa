from __future__ import annotations

import asyncio
import contextlib
import json
import re
import time
import uuid
from datetime import UTC, date, datetime, timedelta

from fastapi import APIRouter, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy import func, select, text

from memora.core.deps import DB, CurrentAdmin, CurrentSuperAdmin, client_ip
from memora.core.errors import Forbidden, NotFound, ValidationFailed
from memora.models import (
    Agent,
    AuditLog,
    ClaudeAccount,
    CreditBalance,
    Invite,
    Job,
    ModelCatalog,
    Plan,
    Turn,
    UsageDaily,
    UsageEvent,
    User,
    WorkerHeartbeat,
)
from memora.providers.verify import CLI_ALIASES, discover_models, verify_key
from memora.services import accounts as A
from memora.services import audit
from memora.services import catalog as CAT
from memora.services import claude_code as CC
from memora.services import claude_pool as CP
from memora.services import credits as CR
from memora.services import jobs as J
from memora.services import legal as LEGAL
from memora.services import settings as S

router = APIRouter(prefix="/api/admin", tags=["admin"])
PROVIDER_KEYS = {"anthropic": "providers.anthropic.api_key", "openai": "providers.openai.api_key", "google": "providers.google.api_key",
                 "elevenlabs": "providers.elevenlabs.api_key", "voyage": "providers.voyage.api_key"}


@router.get("/bootstrap-status")
async def bootstrap_status(db: DB):
    n = await A.user_count(db)
    return {"bootstrap_needed": n == 0, "setup_completed": bool(await S.get(db, "setup_completed"))}


@router.get("/overview")
async def overview(admin: CurrentAdmin, db: DB):
    from zoneinfo import ZoneInfo

    from memora.config import get_settings
    tz = ZoneInfo(get_settings().timezone or "Asia/Seoul")
    today = datetime.now(tz).date()
    day_start = datetime.combine(today, datetime.min.time(), tzinfo=tz)
    users = int((await db.execute(select(func.count(User.id)))).scalar_one())
    agents = int((await db.execute(select(func.count(Agent.id)).where(Agent.status != "archived"))).scalar_one())
    t = (await db.execute(select(func.count(Turn.id), func.coalesce(func.sum(Turn.credits), 0),
                                 func.sum(func.cast(Turn.status == "failed", __import__("sqlalchemy").Integer)))
                          .where(Turn.started_at >= day_start))).one()
    hb = (await db.execute(select(WorkerHeartbeat).order_by(WorkerHeartbeat.last_seen_at.desc()))).scalars().first()
    recent = (await db.execute(select(User).order_by(User.created_at.desc()).limit(5))).scalars().all()
    jobs = (await db.execute(select(Job.status, func.count()).group_by(Job.status))).all()
    return {"users": users, "agents": agents, "turns_today": t[0], "credits_today": float(t[1] or 0), "failed_today": int(t[2] or 0),
            "worker": {"id": hb.worker_id, "last_seen_at": hb.last_seen_at.isoformat(), "stale": hb.last_seen_at < datetime.now(UTC) - timedelta(seconds=90)} if hb else None,
            "recent_users": [{"id": str(u.id), "email": u.email, "display_name": u.display_name, "role": u.role, "created_at": u.created_at.isoformat()} for u in recent],
            "jobs": {s: n for s, n in jobs}, "claude": await CC.status(db), "setup_completed": bool(await S.get(db, "setup_completed")),
            "default_admin_password_in_use": await A.default_admin_password_in_use(db),
            "providers_status": await S.get(db, "providers.status") or {}}


# ── settings ────────────────────────────────────────────────────────

@router.get("/legal/default/{kind}")
async def legal_default(kind: str, admin: CurrentAdmin):
    """기본 이용약관·개인정보 처리방침의 원문(자리표시 그대로) — 관리자가 고쳐 쓰기 시작할 때 (plan/73)."""
    if kind not in LEGAL.KINDS:
        raise NotFound("no such document", code="not_found")
    return {"kind": kind, "text": LEGAL.default_text(kind), "version": LEGAL.DEFAULT_VERSION}


@router.get("/settings")
async def get_settings_(admin: CurrentAdmin, db: DB, prefix: str = ""):
    return await S.public_view(db, prefix)


class SettingsIn(BaseModel):
    values: dict


SETTING_CHOICES = {"signup.mode": ("open", "invite", "closed"), "providers.claude_code.auth_mode": ("oauth", "api_key", "setup_token"),
                   "providers.claude_code.pool.strategy": ("least_busy", "round_robin", "weighted", "least_recently_used"),
                   "embedding.provider": ("openai", "gemini", "voyage", "hash"), "stt.provider": ("openai", "elevenlabs"),
                   "tts.provider": ("openai", "elevenlabs"), "log.level": ("DEBUG", "INFO", "WARNING", "ERROR"),
                   "memory.distill_provider": ("claude_code", "anthropic", "openai", "gemini", "fake")}
NON_NEGATIVE = {"credits.usd_per_credit", "credits.margin", "credits.signup_grant", "credits.low_watermark_ratio", "embedding.dim",
                "embedding.credit_per_1k", "stt.credit_per_minute", "tts.credit_per_1k_chars", "smtp.port", "memory.max_open_vaults",
                "memory.idle_evict_minutes", "public.default_rate_per_minute", "public.default_retention_days",
                "providers.claude_code.pool.failure_threshold", "providers.claude_code.pool.failure_cooldown_s",
                "providers.claude_code.pool.rate_limit_cooldown_s", "providers.claude_code.pool.quota_cooldown_s"}


def coerce_setting(key: str, value):
    """Type-check a PUT /settings value against the default's type (bool/int/float/str/dict). Numeric settings such as
    credits.usd_per_credit must never be stored as strings — float(...) at read time would otherwise 500 a turn."""
    default = S.default_for(key)
    if S.is_secret(key):
        if not isinstance(value, str):
            raise ValidationFailed(f"{key} must be a string")
        return value.strip()
    if isinstance(default, bool):
        if isinstance(value, bool):
            return value
        if isinstance(value, str) and value.lower() in ("true", "false", "1", "0"):
            return value.lower() in ("true", "1")
        raise ValidationFailed(f"{key} must be a boolean")
    if isinstance(default, int):
        try:
            v = int(value) if not isinstance(value, bool) else None
        except (TypeError, ValueError):
            v = None
        if v is None or (isinstance(value, float) and v != value):
            raise ValidationFailed(f"{key} must be an integer")
        if key in NON_NEGATIVE and v < 0:
            raise ValidationFailed(f"{key} must be >= 0")
        return v
    if isinstance(default, float):
        try:
            v = float(value) if not isinstance(value, bool) else None
        except (TypeError, ValueError):
            v = None
        if v is None or v != v or v in (float("inf"), float("-inf")):
            raise ValidationFailed(f"{key} must be a number")
        if key in NON_NEGATIVE and v < 0:
            raise ValidationFailed(f"{key} must be >= 0")
        return v
    if isinstance(default, dict):
        if not isinstance(value, dict):
            raise ValidationFailed(f"{key} must be an object")
        return value
    if isinstance(default, str):
        if not isinstance(value, str):
            raise ValidationFailed(f"{key} must be a string")
        if key == "legal.effective_date" and value.strip() and not re.fullmatch(r"\d{4}-\d{2}-\d{2}", value.strip()):
            # 동의받는 판이다 — 날짜가 아니면 판을 비교할 수 없다.
            raise ValidationFailed("legal.effective_date must be YYYY-MM-DD", code="invalid_date")
        if key in SETTING_CHOICES and value not in SETTING_CHOICES[key]:
            raise ValidationFailed(f"{key} must be one of {', '.join(SETTING_CHOICES[key])}")
        return value
    return value


EMBEDDING_KEYS = ("embedding.provider", "embedding.model", "embedding.dim")


@router.put("/settings")
async def put_settings(body: SettingsIn, admin: CurrentAdmin, db: DB, request: Request):
    cleaned: dict = {}
    for k, v in body.values.items():
        if k not in S.DEFAULTS:
            raise ValidationFailed(f"unknown setting {k}")
        if S.is_secret(k) and v in ("", None):
            continue  # never blank a secret by accident; use explicit clear endpoint
        cleaned[k] = coerce_setting(k, v)
    before = {k: await S.get(db, k, use_cache=False) for k in EMBEDDING_KEYS if k in cleaned}
    for k, v in cleaned.items():
        await S.put(db, k, v, updated_by=admin.id)
    reindex_queued = 0
    if any(before.get(k) != cleaned.get(k) for k in before):
        # plan/09: changing the embedding provider/model/dim invalidates every stored vector → full re-embed
        from memora.models import KnowledgeDocument
        # Owner by owner, so a full re-embed is spread across the queue's round-robin
        # instead of landing as one block in front of everybody's live work.
        for did, owner_id in (await db.execute(select(KnowledgeDocument.id, KnowledgeDocument.owner_id))).all():
            if await J.enqueue(db, "knowledge.index", {"document_id": str(did)}, priority=8,
                               dedupe_key=f"reindex:{did}", owner_id=owner_id):
                reindex_queued += 1
    audit.record(db, "settings_update", actor_id=admin.id, actor_kind="admin", ip=client_ip(request), meta={"keys": list(cleaned.keys())})
    await db.commit()
    out = await S.public_view(db)
    if reindex_queued:
        out["_reindex_queued"] = reindex_queued
    return out


@router.delete("/settings/{key}")
async def clear_setting(key: str, admin: CurrentAdmin, db: DB):
    if key not in S.DEFAULTS:
        raise ValidationFailed("unknown setting")
    await S.put(db, key, S.default_for(key), updated_by=admin.id)
    await db.commit()
    return {"ok": True}


# ── providers ───────────────────────────────────────────────────────

@router.get("/providers")
async def providers(admin: CurrentAdmin, db: DB):
    status = await S.get(db, "providers.status") or {}
    out = []
    for pid, key in PROVIDER_KEYS.items():
        v = await S.get(db, key)
        from memora.core.redact import mask
        out.append({"id": pid, "configured": bool(v), "masked": mask(v) if v else "", "status": status.get(pid)})
    return {"providers": out, "claude_code": await CC.status(db)}


class ProviderKeyIn(BaseModel):
    api_key: str


@router.put("/providers/{pid}")
async def put_provider(pid: str, body: ProviderKeyIn, admin: CurrentAdmin, db: DB):
    if pid not in PROVIDER_KEYS:
        raise NotFound("unknown provider")
    await S.put(db, PROVIDER_KEYS[pid], body.api_key.strip(), updated_by=admin.id)
    audit.record(db, "provider_key_set", actor_id=admin.id, actor_kind="admin", meta={"provider": pid})
    await db.commit()
    return await verify_provider(pid, admin, db)


@router.post("/providers/{pid}/verify")
async def verify_provider(pid: str, admin: CurrentAdmin, db: DB):
    if pid not in PROVIDER_KEYS:
        raise NotFound("unknown provider")
    key = await S.get(db, PROVIDER_KEYS[pid], use_cache=False)
    verdict, detail = await verify_key(pid, key, force=True)
    status = dict(await S.get(db, "providers.status", use_cache=False) or {})
    status[pid] = {"verdict": verdict, "detail": detail, "at": datetime.now(UTC).isoformat()}
    await S.put(db, "providers.status", status)
    await db.commit()
    return {"id": pid, "verdict": verdict, "detail": detail}


class ClaudeModeIn(BaseModel):
    auth_mode: str
    setup_token: str | None = None


@router.put("/providers/claude-code/mode")
async def claude_mode(body: ClaudeModeIn, admin: CurrentAdmin, db: DB):
    if body.auth_mode not in ("oauth", "console", "api_key", "setup_token"):
        raise ValidationFailed("bad mode")
    await S.put(db, "providers.claude_code.auth_mode", body.auth_mode, updated_by=admin.id)
    if body.setup_token:
        await S.put(db, "providers.claude_code.setup_token", body.setup_token.strip(), updated_by=admin.id)
    await db.commit()
    return await CC.status(db)


class CredsIn(BaseModel):
    credentials_json: str


@router.post("/providers/claude-code/import")
async def claude_import(body: CredsIn, admin: CurrentAdmin, db: DB):
    st = await CC.import_credentials(db, body.credentials_json, updated_by=admin.id)
    audit.record(db, "claude_credentials_import", actor_id=admin.id, actor_kind="admin")
    await db.commit()
    return st


@router.post("/providers/claude-code/restore")
async def claude_restore(admin: CurrentAdmin, db: DB):
    ok = await CC.restore_credentials(db)
    return {"restored": ok, "status": await CC.status(db)}


@router.post("/providers/claude-code/probe")
async def claude_probe(admin: CurrentAdmin, db: DB):
    r = await CC.probe(db)
    await db.commit()
    return r


class LoginStartIn(BaseModel):
    email: str | None = None   # pre-fills the address on the login page


@router.post("/providers/claude-code/login/start")
async def claude_login_start(admin: CurrentAdmin, db: DB, body: LoginStartIn | None = None):
    """Which account type the browser flow asks for is the saved auth mode's business
    (``console`` → Anthropic Console, otherwise the Claude subscription), so the two can
    never disagree the way a separate checkbox allowed."""
    mode = await S.get(db, "providers.claude_code.auth_mode") or "oauth"
    if mode not in ("oauth", "console"):
        raise ValidationFailed(f"auth mode {mode} does not use a browser login", code="login_not_applicable")
    job = await CC.start_login(console=(mode == "console"), email=(body.email if body else None))
    audit.record(db, "claude_login_start", actor_id=admin.id, actor_kind="admin", meta={"mode": mode})
    await db.commit()
    return {"started": True, **job.snapshot()}


@router.get("/providers/claude-code/login")
async def claude_login_state(admin: CurrentAdmin):
    """Snapshot for a client that reloaded mid-login: the console pane and the input box
    can be restored without waiting for the next SSE event."""
    job = CC.current_login()
    return job.snapshot() if job else {"running": False, "done": True, "lines": [], "url": None, "awaiting_input": False}


def _login_stream(job) -> StreamingResponse:
    """SSE for one login relay — replays what already happened, then follows.

    Shared by the single-account flow and every pooled account, so a client reconnecting
    mid-login gets the same treatment either way.
    """

    async def gen():
        if job is None:
            yield b"event: done\ndata: {\"kind\":\"done\",\"text\":\"no login\"}\n\n"
            return
        for ev in job.lines:
            yield f"event: {ev['kind']}\ndata: {json.dumps(ev, ensure_ascii=False)}\n\n".encode()
        if job.done:
            return
        q: asyncio.Queue = asyncio.Queue(maxsize=500)
        job.subscribers.add(q)
        try:
            while True:
                try:
                    ev = await asyncio.wait_for(q.get(), timeout=15)
                except TimeoutError:
                    yield b": ping\n\n"
                    continue
                if ev is None:
                    return
                yield f"event: {ev['kind']}\ndata: {json.dumps(ev, ensure_ascii=False)}\n\n".encode()
        finally:
            job.subscribers.discard(q)
    return StreamingResponse(gen(), media_type="text/event-stream", headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@router.get("/providers/claude-code/login/events")
async def claude_login_events(admin: CurrentAdmin):
    return _login_stream(CC.current_login())


class LoginInput(BaseModel):
    text: str


@router.post("/providers/claude-code/login/input")
async def claude_login_input(body: LoginInput, admin: CurrentAdmin, db: DB):
    job = CC.current_login()
    if job is None:
        raise NotFound("no login running")
    await job.send_input(body.text)
    return {"ok": True}


@router.post("/providers/claude-code/login/cancel")
async def claude_login_cancel(admin: CurrentAdmin):
    job = CC.current_login()
    if job:
        await job.cancel()
    return {"ok": True}


# ── claude code account pool (plan/30) ──────────────────────────────
#
# Several authenticated Claude identities, one leased per session. Every account gets its
# own CLI home, so the login relay below is the same flow as the single-account one,
# pointed somewhere else.

class PoolSettingsIn(BaseModel):
    enabled: bool | None = None
    strategy: str | None = None


class AccountIn(BaseModel):
    label: str = Field(min_length=1, max_length=64)
    email: str | None = None
    auth_mode: str = "oauth"
    weight: int = Field(default=1, ge=1, le=1000)
    max_concurrency: int = Field(default=16, ge=1, le=64)
    notes: str | None = None


class AccountPatch(BaseModel):
    label: str | None = Field(default=None, max_length=64)
    email: str | None = None
    auth_mode: str | None = None
    enabled: bool | None = None
    weight: int | None = Field(default=None, ge=1, le=1000)
    max_concurrency: int | None = Field(default=None, ge=1, le=64)
    setup_token: str | None = None
    api_key: str | None = None
    notes: str | None = None


@router.get("/providers/claude-code/accounts")
async def pool_accounts(admin: CurrentAdmin, db: DB):
    # One list, always at least one row: an install that already had a Claude Code login
    # sees it here as account #1 rather than in a second card beside this one.
    if await CP.adopt_legacy(db):
        await db.commit()
    return await CP.overview(db)


@router.put("/providers/claude-code/pool")
async def pool_settings(body: PoolSettingsIn, admin: CurrentAdmin, db: DB):
    if body.enabled is not None:
        await S.put(db, "providers.claude_code.pool.enabled", bool(body.enabled), updated_by=admin.id)
    if body.strategy is not None:
        if body.strategy not in SETTING_CHOICES["providers.claude_code.pool.strategy"]:
            raise ValidationFailed(f"unknown strategy {body.strategy}", code="bad_strategy")
        await S.put(db, "providers.claude_code.pool.strategy", body.strategy, updated_by=admin.id)
    audit.record(db, "claude_pool_settings", actor_id=admin.id, actor_kind="admin",
                 meta={"enabled": body.enabled, "strategy": body.strategy})
    await db.commit()
    return await CP.overview(db)


@router.post("/providers/claude-code/accounts")
async def pool_create(body: AccountIn, admin: CurrentAdmin, db: DB):
    acc = await CP.create(db, label=body.label, email=body.email, auth_mode=body.auth_mode,
                          weight=body.weight, max_concurrency=body.max_concurrency, notes=body.notes)
    audit.record(db, "claude_account_create", actor_id=admin.id, actor_kind="admin",
                 target_type="claude_account", target_id=acc.id, meta={"label": acc.label})
    await db.commit()
    await db.refresh(acc)
    return CP.account_out(acc)


@router.patch("/providers/claude-code/accounts/{account_id}")
async def pool_update(account_id: uuid.UUID, body: AccountPatch, admin: CurrentAdmin, db: DB):
    acc = await CP.update(db, account_id, **body.model_dump(exclude_unset=True))
    audit.record(db, "claude_account_update", actor_id=admin.id, actor_kind="admin",
                 target_type="claude_account", target_id=acc.id,
                 # never the secrets themselves, only that they were replaced
                 meta={k: (bool(v) if k in ("setup_token", "api_key") else v)
                       for k, v in body.model_dump(exclude_unset=True).items()})
    await db.commit()
    await db.refresh(acc)
    return CP.account_out(acc)


@router.delete("/providers/claude-code/accounts/{account_id}")
async def pool_delete(account_id: uuid.UUID, admin: CurrentAdmin, db: DB):
    acc = await CP.get(db, account_id)
    label = acc.label
    await CP.delete(db, account_id)
    audit.record(db, "claude_account_delete", actor_id=admin.id, actor_kind="admin",
                 target_type="claude_account", target_id=account_id, meta={"label": label})
    await db.commit()
    return {"ok": True}


@router.post("/providers/claude-code/accounts/{account_id}/import")
async def pool_import(account_id: uuid.UUID, body: CredsIn, admin: CurrentAdmin, db: DB):
    acc = await CP.import_credentials(db, account_id, body.credentials_json)
    audit.record(db, "claude_account_import", actor_id=admin.id, actor_kind="admin",
                 target_type="claude_account", target_id=account_id, meta={"label": acc.label})
    await db.commit()
    await db.refresh(acc)
    return CP.account_out(acc)


@router.post("/providers/claude-code/accounts/{account_id}/probe")
async def pool_probe(account_id: uuid.UUID, admin: CurrentAdmin, db: DB):
    r = await CP.probe(db, account_id)
    await db.commit()
    return r


@router.post("/providers/claude-code/accounts/{account_id}/cooldown/clear")
async def pool_clear_cooldown(account_id: uuid.UUID, admin: CurrentAdmin, db: DB):
    acc = await CP.clear_cooldown(db, account_id)
    audit.record(db, "claude_account_cooldown_clear", actor_id=admin.id, actor_kind="admin",
                 target_type="claude_account", target_id=account_id, meta={"label": acc.label})
    await db.commit()
    await db.refresh(acc)
    return CP.account_out(acc)


@router.post("/providers/claude-code/accounts/{account_id}/login/start")
async def pool_login_start(account_id: uuid.UUID, admin: CurrentAdmin, db: DB, body: LoginStartIn | None = None):
    """Device login for one pooled account, in that account's own CLI home."""
    acc = await CP.get(db, account_id)
    if acc.auth_mode not in CP.FILE_MODES:
        raise ValidationFailed(f"auth mode {acc.auth_mode} does not use a browser login", code="login_not_applicable")

    async def _harvest() -> None:
        # The CLI has just written the credential file; pull it into the row straight away
        # so a container restart cannot lose a login someone just performed by hand.
        from memora.db.session import session_scope
        async with session_scope() as s2:
            fresh = await s2.get(ClaudeAccount, account_id)
            if fresh is not None:
                await CP.harvest(s2, fresh)
                fresh.status = "ready"
                fresh.consecutive_failures = 0
                fresh.cooldown_until = None

    job = await CC.start_login(console=(acc.auth_mode == "console"), email=(body.email if body else acc.email),
                               key=str(account_id), home=CP.home_for(account_id),
                               config_dir=CP.config_dir_for(account_id), on_success=_harvest)
    audit.record(db, "claude_account_login_start", actor_id=admin.id, actor_kind="admin",
                 target_type="claude_account", target_id=account_id, meta={"label": acc.label})
    await db.commit()
    return {"started": True, **job.snapshot()}


@router.get("/providers/claude-code/accounts/{account_id}/login")
async def pool_login_state(account_id: uuid.UUID, admin: CurrentAdmin):
    job = CC.current_login(str(account_id))
    return job.snapshot() if job else {"running": False, "done": True, "lines": [], "url": None, "awaiting_input": False}


@router.get("/providers/claude-code/accounts/{account_id}/login/events")
async def pool_login_events(account_id: uuid.UUID, admin: CurrentAdmin):
    return _login_stream(CC.current_login(str(account_id)))


@router.post("/providers/claude-code/accounts/{account_id}/login/input")
async def pool_login_input(account_id: uuid.UUID, body: LoginInput, admin: CurrentAdmin):
    job = CC.current_login(str(account_id))
    if job is None:
        raise NotFound("no login running")
    await job.send_input(body.text)
    return {"ok": True}


@router.post("/providers/claude-code/accounts/{account_id}/login/cancel")
async def pool_login_cancel(account_id: uuid.UUID, admin: CurrentAdmin):
    job = CC.current_login(str(account_id))
    if job:
        await job.cancel()
    return {"ok": True}


# ── model catalog ───────────────────────────────────────────────────

def model_out(m: ModelCatalog) -> dict:
    return {"id": str(m.id), "provider": m.provider, "model_id": m.model_id, "display_name": m.display_name, "cli_alias": m.cli_alias,
            "context_window": m.context_window, "max_output": m.max_output, "supports_thinking": m.supports_thinking,
            "supports_vision": m.supports_vision, "credit_per_1k_input": float(m.credit_per_1k_input), "credit_per_1k_output": float(m.credit_per_1k_output),
            "credit_per_1k_cache_read": float(m.credit_per_1k_cache_read), "enabled": m.enabled, "is_default": m.is_default,
            "sort_order": m.sort_order, "notes": m.notes}


@router.get("/models")
async def models(admin: CurrentAdmin, db: DB):
    return {"items": [model_out(m) for m in await CAT.list_models(db)]}


@router.post("/models/seed")
async def seed_models(admin: CurrentAdmin, db: DB, overwrite_prices: bool = False):
    result = await CAT.seed(db, overwrite_prices=overwrite_prices)
    await db.commit()
    return result


@router.get("/models/discover")
async def discover(admin: CurrentAdmin, db: DB, provider: str):
    """List the models this install can actually reach.

    Claude Code used to need an Anthropic API key here, which a subscription-only install
    does not have — the one provider that is always logged in was the one that could not be
    listed. The CLI's own OAuth token authenticates against the models API, so it is tried
    first and the key is the fallback.
    """
    key = ""
    if provider == "claude_code":
        key = CC.oauth_access_token() or (await S.get(db, "providers.anthropic.api_key") or "")
    else:
        key_name = {"anthropic": "providers.anthropic.api_key", "openai": "providers.openai.api_key",
                    "gemini": "providers.google.api_key"}.get(provider)
        key = (await S.get(db, key_name) or "") if key_name else ""
    if not key:
        note = "Claude Code 로그인 또는 Anthropic 키가 필요해요" if provider == "claude_code" else "이 프로바이더의 API 키가 필요해요"
        return {"items": [], "aliases": [], "note": note}
    items = await discover_models(provider, key)
    if not items:
        return {"items": [], "aliases": [], "note": "프로바이더가 모델 목록을 돌려주지 않았어요"}
    # Aliases only mean something to the CLI, which resolves them at launch.
    return {"items": items, "aliases": list(CLI_ALIASES) if provider == "claude_code" else []}


class ModelIn(BaseModel):
    provider: str
    model_id: str
    display_name: str
    cli_alias: str | None = None
    context_window: int = 200000
    max_output: int = 8192
    supports_thinking: bool = False
    supports_vision: bool = True
    credit_per_1k_input: float = 0
    credit_per_1k_output: float = 0
    credit_per_1k_cache_read: float = 0
    enabled: bool = True
    is_default: bool = False
    sort_order: int = 100
    notes: str | None = None


@router.post("/models", status_code=201)
async def create_model(body: ModelIn, admin: CurrentAdmin, db: DB):
    if body.provider not in CAT.PROVIDER_TO_EXECUTOR:
        raise ValidationFailed("unsupported provider")
    m = ModelCatalog(**body.model_dump())
    if m.is_default:
        await db.execute(text("UPDATE model_catalog SET is_default = false"))
    db.add(m)
    await db.commit()
    return model_out(m)


@router.patch("/models/{mid}")
async def patch_model(mid: uuid.UUID, body: dict, admin: CurrentAdmin, db: DB):
    m = await db.get(ModelCatalog, mid)
    if m is None:
        raise NotFound("model not found")
    patch = {k: v for k, v in body.items() if k in ModelIn.model_fields}
    try:
        validated = ModelIn.model_validate({**{k: getattr(m, k) for k in ModelIn.model_fields}, **patch})
    except Exception as e:  # noqa: BLE001
        raise ValidationFailed("invalid model fields", detail=str(e)[:300]) from e
    if validated.provider not in CAT.PROVIDER_TO_EXECUTOR and validated.provider != m.provider:
        raise ValidationFailed("unsupported provider")
    if validated.is_default and not m.is_default:
        await db.execute(text("UPDATE model_catalog SET is_default = false"))
    for k in patch:
        setattr(m, k, getattr(validated, k))
    if not validated.enabled and m.is_default:
        m.is_default = False  # a disabled default would make every fallback fail
    await db.commit()
    return model_out(m)


@router.delete("/models/{mid}")
async def delete_model(mid: uuid.UUID, admin: CurrentAdmin, db: DB):
    m = await db.get(ModelCatalog, mid)
    if m is None:
        raise NotFound("model not found")
    await db.delete(m)
    await db.commit()
    return {"ok": True}


# ── traffic (plan/40) ───────────────────────────────────────────────
#
# What the server is serving, what it served, and what is still in flight. The live list is
# the one that finds a bad call while it is still happening; everything else is read from
# the request record, aggregated in the database.


@router.get("/traffic")
async def traffic_overview(admin: CurrentAdmin, db: DB, minutes: int = 60):
    from memora.core import pools
    from memora.core import traffic as TF
    from memora.core.database import manager as dbm
    from memora.core.watchdog import loop_lag
    from memora.pipeline.runtime import runtimes
    from memora.services import procstats as PS
    from memora.services import traffic as TR

    minutes = max(5, min(minutes, 1440))
    return {"summary": await TR.summary(db, minutes), "series": await TR.series(db, minutes),
            # Every process, not just the one that answered (plan/32 §6).
            "fleet": await PS.fleet(db),
            "process": {"loop_lag_s": round(loop_lag(), 3), "pools": pools.stats(), "sessions": runtimes.count(),
                        "db": dbm.stats(), **TF.counters()},
            "in_flight": TF.in_flight()}


@router.get("/traffic/endpoints")
async def traffic_endpoints(admin: CurrentAdmin, db: DB, minutes: int = 60, order: str = "total_ms", limit: int = 20):
    from memora.services import traffic as TR

    return {"items": await TR.endpoints(db, max(5, min(minutes, 1440)), min(limit, 100), order)}


@router.get("/traffic/anomalies")
async def traffic_anomalies(admin: CurrentAdmin, db: DB, minutes: int = 180, limit: int = 30):
    from memora.services import traffic as TR

    return {"items": await TR.anomalies(db, max(5, min(minutes, 1440)), min(limit, 200))}


@router.get("/traffic/callers")
async def traffic_callers(admin: CurrentAdmin, db: DB, minutes: int = 60, limit: int = 15):
    from memora.services import traffic as TR

    return {"items": await TR.callers(db, max(5, min(minutes, 1440)), min(limit, 100))}


@router.get("/traffic/queue")
async def traffic_queue(admin: CurrentAdmin, db: DB):
    """The worker's side of the same picture: nothing else matters if the queue is stuck."""
    from sqlalchemy import text as _text

    rows = (await db.execute(_text("""
        SELECT kind, status, count(*) AS n,
               coalesce(max(extract(epoch FROM now() - locked_at)), 0) AS oldest_running_s
        FROM jobs WHERE status IN ('queued', 'running')
        GROUP BY kind, status ORDER BY n DESC LIMIT 40
    """))).mappings().all()
    dead = (await db.execute(_text("SELECT count(*) FROM jobs WHERE status = 'dead' AND created_at > now() - interval '1 day'"))).scalar_one()
    return {"items": [{"kind": r["kind"], "status": r["status"], "n": int(r["n"]),
                       "oldest_running_s": round(float(r["oldest_running_s"]), 1)} for r in rows],
            "dead_last_day": int(dead)}


# ── 내 주변 맛집 (plan/34) ───────────────────────────────────────────


# ── companies (plan/33) ─────────────────────────────────────────────
#
# Collected in batches, never on a visitor's request: the sources have daily call caps and
# change at most daily, and a community query must not wait on someone else's server.


@router.get("/companies/sources")
async def company_sources(admin: CurrentAdmin, db: DB):
    from memora.services.companies.collect import status

    return await status(db)


@router.post("/companies/collect/{source}", status_code=202)
async def company_collect(source: str, admin: CurrentAdmin, db: DB):
    """Queue a collection. Queued rather than run here, so a slow source cannot hold an
    admin request open and the `crawl` class's ceiling still applies (plan/32 §4)."""
    from memora.services.companies.collect import SOURCES

    if source not in SOURCES:
        raise NotFound("unknown source")
    job = await J.enqueue(db, "crawl.companies", {"source": source},
                          dedupe_key=f"companies:{source}:{datetime.now(UTC):%Y%m%d%H%M}")
    await db.commit()
    return {"queued": True, "job_id": str(job.id) if job else None}


@router.get("/companies/runs")
async def company_runs(admin: CurrentAdmin, db: DB, limit: int = 40):
    """The collection log: what is queued, what is running, and what every run did.

    Queue and history in one answer because they are one question — "is it working" — and
    two requests would let the screen show a finished run beside a queue that has moved on.
    """
    from sqlalchemy import text as _text

    from memora.models import CompanySourceRun

    runs = (await db.execute(
        select(CompanySourceRun).order_by(CompanySourceRun.started_at.desc()).limit(min(limit, 200))
    )).scalars().all()
    queue = (await db.execute(_text("""
        SELECT id, kind, status, payload, attempts, run_at, locked_at, last_error,
               coalesce(extract(epoch FROM now() - locked_at), 0) AS running_s
        FROM jobs
        WHERE kind IN ('crawl.companies', 'companies.refresh')
          -- Live work, and anything that needs a person. Finished jobs are deliberately
          -- left out: they say nothing the run history does not, and a page of them pushed
          -- the history itself off the screen.
          AND (status IN ('queued', 'running')
               OR (status IN ('failed', 'dead') AND created_at > now() - interval '1 day'))
        ORDER BY (status = 'running') DESC, (status = 'queued') DESC, coalesce(locked_at, run_at) DESC
        LIMIT 20
    """))).mappings().all()
    return {
        "runs": [{"id": str(r.id), "source": r.source, "at": r.started_at.isoformat(),
                  "finished_at": r.finished_at.isoformat() if r.finished_at else None,
                  "running": r.finished_at is None, "ok": r.ok, "fetched": r.fetched,
                  "created": r.created, "updated": r.updated, "skipped": r.skipped,
                  "error": r.error,
                  "seconds": None if r.finished_at is None else
                  round((r.finished_at - r.started_at).total_seconds(), 1)} for r in runs],
        "queue": [{"id": str(q["id"]), "kind": q["kind"], "status": q["status"],
                   "source": (q["payload"] or {}).get("source"), "attempts": q["attempts"],
                   "run_at": q["run_at"].isoformat() if q["run_at"] else None,
                   "running_s": round(float(q["running_s"]), 1) if q["status"] == "running" else None,
                   "error": q["last_error"]} for q in queue],
    }


@router.get("/companies")
async def company_list(admin: CurrentAdmin, db: DB, q: str = "", market: str = "", region: str = "",
                       industry: str = "", page: int = 1, size: int = 50):
    from memora.services.companies.query import search

    return await search(db, q=q, market=market, region=region, industry=industry,
                        page=max(1, page), size=min(max(1, size), 200))


@router.get("/companies/domain-claims")
async def company_domain_claims(admin: CurrentAdmin, db: DB):
    """Domains members say belong to a company nobody had mapped (plan/40 §10)."""
    from memora.services.companies import domains as D

    return {"items": await D.pending_claims(db), "confirmed": await D.confirmed_count(db)}


@router.post("/companies/domain-claims/{domain_id}/{action}")
async def company_domain_decide(domain_id: uuid.UUID, action: str, admin: CurrentAdmin, db: DB):
    from memora.services.companies import domains as D

    if action not in ("approve", "reject"):
        raise ValidationFailed("approve or reject", code="bad_action")
    await D.decide(db, domain_id, approve=action == "approve")
    await db.commit()
    return {"ok": True}


@router.get("/companies/{company_id}/domains")
async def company_domains(company_id: uuid.UUID, admin: CurrentAdmin, db: DB):
    from memora.services.companies import domains as D

    return {"items": await D.for_company(db, company_id)}


class DomainIn(BaseModel):
    domain: str = Field(max_length=190)


@router.post("/companies/{company_id}/domains", status_code=201)
async def company_domain_add(company_id: uuid.UUID, body: DomainIn, admin: CurrentAdmin, db: DB):
    from memora.models import Company
    from memora.services.companies import domains as D

    if await db.get(Company, company_id) is None:
        raise NotFound("company not found")
    d = D.registrable(body.domain.strip().lower().lstrip("@"))
    if not d or D.is_free(d):
        raise ValidationFailed("not a company domain", code="bad_domain")
    row = await D.add(db, company_id=company_id, domain=d, source="admin", status="confirmed")
    await db.commit()
    return D.out(row)


@router.delete("/companies/{company_id}/domains/{domain_id}")
async def company_domain_remove(company_id: uuid.UUID, domain_id: uuid.UUID, admin: CurrentAdmin, db: DB):
    from memora.services.companies import domains as D

    await D.remove(db, domain_id)
    await db.commit()
    return {"ok": True}


@router.get("/companies/{company_id}")
async def company_detail(company_id: uuid.UUID, admin: CurrentAdmin, db: DB):
    from memora.models import Company
    from memora.services.companies.query import out

    c = await db.get(Company, company_id)
    if c is None:
        raise NotFound("company not found")
    return out(c, full=True)


class CompanyPatch(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=160)
    industry_codes: list[str] | None = Field(default=None, max_length=8)
    region_code: str | None = Field(default=None, max_length=8)
    homepage: str | None = Field(default=None, max_length=500)
    hidden: bool | None = None


@router.patch("/companies/{company_id}")
async def company_patch(company_id: uuid.UUID, body: CompanyPatch, admin: CurrentAdmin, db: DB):
    """A correction by hand, which no collector may then overwrite (plan/33 §3)."""
    from memora.models import Company
    from memora.services.companies.merge import normalise_name
    from memora.services.companies.query import out

    c = await db.get(Company, company_id)
    if c is None:
        raise NotFound("company not found")
    locked = set(c.locked_fields or [])
    for field, value in body.model_dump(exclude_unset=True).items():
        if value is None:
            continue
        setattr(c, field, value)
        if field == "name":
            c.name_norm = normalise_name(value)
        if field != "hidden":     # hiding is moderation, not a claim about the facts
            locked.add(field)
    c.locked_fields = sorted(locked)
    await db.commit()
    return out(c, full=True)


# ── plans ───────────────────────────────────────────────────────────

def plan_out(p: Plan) -> dict:
    return {"id": str(p.id), "code": p.code, "name": p.name, "monthly_credits": p.monthly_credits, "max_agents": p.max_agents,
            "max_share_links": p.max_share_links, "max_storage_mb": p.max_storage_mb,
            "features": p.features, "models": list(p.models or []), "is_default": p.is_default}


@router.get("/plans")
async def plans(admin: CurrentAdmin, db: DB):
    return {"items": [plan_out(p) for p in (await db.execute(select(Plan).order_by(Plan.monthly_credits))).scalars().all()]}


class PlanIn(BaseModel):
    code: str = Field(min_length=1, max_length=32, pattern=r"^[a-z0-9_-]+$")
    name: str = Field(min_length=1, max_length=64)
    monthly_credits: int = Field(default=300, ge=0)
    max_agents: int = Field(default=1, ge=1)
    max_share_links: int = Field(default=2, ge=0)
    max_storage_mb: int = Field(default=1024, ge=0)
    features: dict = Field(default_factory=dict)
    # "provider:model_id" keys from the pool; empty means the whole pool (plan/33).
    models: list[str] = Field(default_factory=list, max_length=64)
    is_default: bool = False


PLAN_FIELDS = tuple(PlanIn.model_fields)


@router.post("/plans", status_code=201)
async def create_plan(body: PlanIn, admin: CurrentAdmin, db: DB):
    if (await db.execute(select(Plan.id).where(Plan.code == body.code))).first():
        raise ValidationFailed("plan code already exists", code="plan_code_taken")
    p = Plan(**body.model_dump())
    if p.is_default:
        await db.execute(text("UPDATE plans SET is_default = false"))
    db.add(p)
    await db.commit()
    return plan_out(p)


@router.patch("/plans/{pid}")
async def patch_plan(pid: uuid.UUID, body: dict, admin: CurrentAdmin, db: DB):
    p = await db.get(Plan, pid)
    if p is None:
        raise NotFound("plan not found")
    patch = {k: v for k, v in body.items() if k in PLAN_FIELDS}
    try:
        validated = PlanIn.model_validate({**{k: getattr(p, k) for k in PLAN_FIELDS}, **patch})
    except Exception as e:  # noqa: BLE001
        raise ValidationFailed("invalid plan fields", detail=str(e)[:300]) from e
    if "code" in patch and validated.code != p.code and (await db.execute(select(Plan.id).where(Plan.code == validated.code))).first():
        raise ValidationFailed("plan code already exists", code="plan_code_taken")
    if validated.is_default and not p.is_default:
        await db.execute(text("UPDATE plans SET is_default = false"))
    for k in patch:
        setattr(p, k, getattr(validated, k))
    await db.commit()
    return plan_out(p)


# ── users ───────────────────────────────────────────────────────────

async def _user_row(db, u: User) -> dict:
    bal = await db.get(CreditBalance, u.id)
    n_agents = int((await db.execute(select(func.count(Agent.id)).where(Agent.owner_id == u.id, Agent.status != "archived"))).scalar_one())
    plan = await db.get(Plan, u.plan_id) if u.plan_id else None
    return {"id": str(u.id), "email": u.email, "display_name": u.display_name, "role": u.role, "is_super": bool(u.is_super),
            "status": u.status, "plan": plan.code if plan else None,
            "plan_id": str(u.plan_id) if u.plan_id else None, "balance": float(bal.balance) if bal else 0.0, "agents": n_agents,
            "last_login_at": u.last_login_at.isoformat() if u.last_login_at else None, "created_at": u.created_at.isoformat()}


@router.get("/users")
async def users(admin: CurrentAdmin, db: DB, q: str = "", page: int = 1, size: int = 50):
    stmt = select(User).order_by(User.created_at.desc())
    if q:
        stmt = stmt.where((User.email.ilike(f"%{q}%")) | (User.display_name.ilike(f"%{q}%")))
    total = int((await db.execute(select(func.count()).select_from(stmt.subquery()))).scalar_one())
    rows = (await db.execute(stmt.offset((page - 1) * size).limit(size))).scalars().all()
    return {"items": [await _user_row(db, u) for u in rows], "total": total}


@router.get("/users/{uid}")
async def get_user(uid: uuid.UUID, admin: CurrentAdmin, db: DB):
    u = await db.get(User, uid)
    if u is None:
        raise NotFound("user not found")
    agents = (await db.execute(select(Agent).where(Agent.owner_id == u.id))).scalars().all()
    return {**(await _user_row(db, u)), "agents_detail": [{"id": str(a.id), "name": a.name, "status": a.status, "provider": a.provider, "model_id": a.model_id} for a in agents]}


class CreditGrant(BaseModel):
    delta: float
    note: str


@router.post("/users/{uid}/credits")
async def grant(uid: uuid.UUID, body: CreditGrant, admin: CurrentAdmin, db: DB):
    u = await db.get(User, uid)
    if u is None:
        raise NotFound("user not found")
    if not body.note.strip():
        raise ValidationFailed("note required")
    bal = await CR.apply(db, u.id, body.delta, "grant" if body.delta > 0 else "adjust", note=body.note, created_by=admin.id)
    audit.record(db, "credit_grant", actor_id=admin.id, actor_kind="admin", target_type="user", target_id=u.id, meta={"delta": body.delta, "note": body.note})
    await db.commit()
    return {"balance": float(bal)}


class RoleIn(BaseModel):
    role: str


@router.post("/users/{uid}/role")
async def set_role(uid: uuid.UUID, body: RoleIn, admin: CurrentSuperAdmin, db: DB):
    u = await db.get(User, uid)
    if u is None:
        raise NotFound("user not found")
    await A.promote(db, admin, u, body.role)
    await db.commit()
    return {"role": u.role}


class UserPatch(BaseModel):
    status: str | None = None
    plan_id: uuid.UUID | None = None


@router.patch("/users/{uid}")
async def patch_user(uid: uuid.UUID, body: UserPatch, admin: CurrentAdmin, db: DB):
    u = await db.get(User, uid)
    if u is None:
        raise NotFound("user not found")
    if body.status in ("active", "suspended"):
        if u.id == admin.id and body.status == "suspended":
            raise ValidationFailed("cannot suspend yourself")
        if u.is_super and body.status == "suspended":
            raise ValidationFailed("the super administrator cannot be suspended", code="super_admin_locked")
        # Suspending an admin narrows the circle of people who run this install, which is
        # the maintainer's call.
        if body.status == "suspended" and u.role == "admin" and not admin.is_super:
            raise Forbidden("only the super administrator can suspend an admin", code="super_admin_only")
        if body.status == "suspended" and u.role == "admin" and u.status == "active":
            admins = int((await db.execute(select(func.count(User.id)).where(User.role == "admin", User.status == "active"))).scalar_one())
            if admins <= 1:
                raise ValidationFailed("last admin cannot be suspended", code="last_admin")
        u.status = body.status
        if body.status == "suspended":
            await A.logout(db, None, all_devices=True, user_id=u.id)
    if body.plan_id:
        if await db.get(Plan, body.plan_id) is None:
            raise NotFound("plan not found")
        u.plan_id = body.plan_id
    audit.record(db, "user_patch", actor_id=admin.id, actor_kind="admin", target_type="user", target_id=u.id, meta=body.model_dump(mode="json"))
    await db.commit()
    return await _user_row(db, u)


@router.delete("/users/{uid}")
async def delete_user(uid: uuid.UUID, admin: CurrentAdmin, db: DB):
    u = await db.get(User, uid)
    if u is None:
        raise NotFound("user not found")
    if u.id == admin.id:
        raise ValidationFailed("cannot delete yourself")
    if u.is_super:
        raise ValidationFailed("the super administrator cannot be deleted", code="super_admin_locked")
    if u.role == "admin" and not admin.is_super:
        raise Forbidden("only the super administrator can delete an admin", code="super_admin_only")
    await A.purge_user_storage(db, u.id)
    audit.record(db, "user_delete", actor_id=admin.id, actor_kind="admin", target_type="user", target_id=u.id, meta={"email": u.email})
    await db.delete(u)
    await db.commit()
    return {"ok": True}


# ── usage ───────────────────────────────────────────────────────────

@router.get("/usage")
async def usage(admin: CurrentAdmin, db: DB, days: int = 30):
    since = date.today() - timedelta(days=min(days, 365))
    daily = (await db.execute(select(UsageDaily.day, func.sum(UsageDaily.credits), func.sum(UsageDaily.turns), func.sum(UsageDaily.visitor_turns))
                              .where(UsageDaily.day >= since).group_by(UsageDaily.day).order_by(UsageDaily.day))).all()
    by_model = (await db.execute(select(UsageEvent.provider, UsageEvent.model_id, func.sum(UsageEvent.credits), func.sum(UsageEvent.cost_usd),
                                        func.sum(UsageEvent.input_tokens), func.sum(UsageEvent.output_tokens), func.count())
                                 .where(UsageEvent.created_at >= since).group_by(UsageEvent.provider, UsageEvent.model_id))).all()
    top = (await db.execute(select(UsageEvent.owner_id, func.sum(UsageEvent.credits)).where(UsageEvent.created_at >= since)
                            .group_by(UsageEvent.owner_id).order_by(func.sum(UsageEvent.credits).desc()).limit(10))).all()
    top_users = []
    for oid, c in top:
        u = await db.get(User, oid)
        top_users.append({"user_id": str(oid), "email": u.email if u else "?", "credits": float(c or 0)})
    errors = (await db.execute(select(Turn.error_code, func.count()).where(Turn.status == "failed", Turn.started_at >= datetime.now(UTC) - timedelta(days=7))
                               .group_by(Turn.error_code).order_by(func.count().desc()).limit(10))).all()
    return {"daily": [{"day": d.isoformat(), "credits": float(c or 0), "turns": int(t or 0), "visitor_turns": int(v or 0)} for d, c, t, v in daily],
            "by_model": [{"provider": p, "model_id": m, "credits": float(c or 0), "cost_usd": float(u or 0), "input_tokens": int(i or 0),
                          "output_tokens": int(o or 0), "count": n} for p, m, c, u, i, o, n in by_model],
            "top_users": top_users, "errors_7d": [{"code": e, "count": n} for e, n in errors]}


# ── invites ─────────────────────────────────────────────────────────

class InviteIn(BaseModel):
    max_uses: int = 1
    expires_days: int | None = 30
    note: str = ""


@router.get("/invites")
async def invites(admin: CurrentAdmin, db: DB):
    rows = (await db.execute(select(Invite).order_by(Invite.created_at.desc()).limit(200))).scalars().all()
    return {"items": [{"id": str(i.id), "code": i.code, "max_uses": i.max_uses, "used": i.used, "expires_at": i.expires_at.isoformat() if i.expires_at else None,
                       "note": i.note, "created_at": i.created_at.isoformat()} for i in rows]}


@router.post("/invites", status_code=201)
async def create_invite(body: InviteIn, admin: CurrentAdmin, db: DB):
    import secrets
    inv = Invite(code=secrets.token_urlsafe(8), created_by=admin.id, max_uses=max(1, body.max_uses),
                 expires_at=(datetime.now(UTC) + timedelta(days=body.expires_days)) if body.expires_days else None, note=body.note)
    db.add(inv)
    await db.commit()
    return {"code": inv.code}


@router.delete("/invites/{iid}")
async def delete_invite(iid: uuid.UUID, admin: CurrentAdmin, db: DB):
    inv = await db.get(Invite, iid)
    if inv:
        await db.delete(inv)
        await db.commit()
    return {"ok": True}


# ── jobs / audit / health ───────────────────────────────────────────

@router.get("/jobs")
async def jobs(admin: CurrentAdmin, db: DB, status: str | None = None, limit: int = 100):
    stmt = select(Job).order_by(Job.created_at.desc()).limit(min(limit, 500))
    if status:
        stmt = stmt.where(Job.status == status)
    rows = (await db.execute(stmt)).scalars().all()
    counts = (await db.execute(select(Job.status, func.count()).group_by(Job.status))).all()
    hbs = (await db.execute(select(WorkerHeartbeat))).scalars().all()
    return {"items": [{"id": str(j.id), "kind": j.kind, "status": j.status, "attempts": j.attempts, "run_at": j.run_at.isoformat(), "last_error": j.last_error,
                       "created_at": j.created_at.isoformat(), "finished_at": j.finished_at.isoformat() if j.finished_at else None, "payload": j.payload} for j in rows],
            "counts": {s: n for s, n in counts}, "workers": [{"id": h.worker_id, "last_seen_at": h.last_seen_at.isoformat(), "info": h.info} for h in hbs]}


@router.post("/jobs/{jid}/retry")
async def retry_job(jid: uuid.UUID, admin: CurrentAdmin, db: DB):
    j = await db.get(Job, jid)
    if j is None:
        raise NotFound("job not found")
    j.status, j.attempts, j.run_at, j.last_error = "queued", 0, datetime.now(UTC), None
    await db.commit()
    return {"ok": True}


@router.post("/jobs/{jid}/discard")
async def discard_job(jid: uuid.UUID, admin: CurrentAdmin, db: DB):
    j = await db.get(Job, jid)
    if j is None:
        raise NotFound("job not found")
    j.status = "dead"
    j.finished_at = datetime.now(UTC)
    await db.commit()
    return {"ok": True}


@router.get("/audit")
async def audit_logs(admin: CurrentAdmin, db: DB, action: str | None = None, actor_id: uuid.UUID | None = None, limit: int = 100):
    stmt = select(AuditLog).order_by(AuditLog.created_at.desc()).limit(min(limit, 500))
    if action:
        stmt = stmt.where(AuditLog.action == action)
    if actor_id:
        stmt = stmt.where(AuditLog.actor_id == actor_id)
    rows = (await db.execute(stmt)).scalars().all()
    return {"items": [{"id": str(a.id), "actor_id": str(a.actor_id) if a.actor_id else None, "actor_kind": a.actor_kind, "action": a.action,
                       "target_type": a.target_type, "target_id": a.target_id, "ip": a.ip, "meta": a.meta, "created_at": a.created_at.isoformat()} for a in rows]}


@router.get("/health")
async def admin_health(admin: CurrentAdmin, db: DB):
    from memora.api.health import health, ready
    r = await ready()
    failed = (await db.execute(select(Turn).where(Turn.status == "failed").order_by(Turn.started_at.desc()).limit(20))).scalars().all()
    return {"live": await health(), "ready": json.loads(r.body), "claude": await CC.status(db),
            "recent_failed_turns": [{"id": str(t.id), "agent_id": str(t.agent_id), "code": t.error_code, "message": t.error_message,
                                     "provider": t.provider, "model_id": t.model_id, "at": t.started_at.isoformat()} for t in failed]}


@router.post("/embedding/reindex", status_code=202)
async def reindex_all(admin: CurrentAdmin, db: DB):
    from memora.models import KnowledgeDocument
    rows = (await db.execute(select(KnowledgeDocument.id, KnowledgeDocument.owner_id))).all()
    for did, owner_id in rows:
        await J.enqueue(db, "knowledge.index", {"document_id": str(did)}, priority=8, owner_id=owner_id)
    await db.commit()
    return {"queued": len(rows)}


class SmtpTest(BaseModel):
    to: str


@router.post("/smtp/test")
async def smtp_test(body: SmtpTest, admin: CurrentAdmin, db: DB):
    from memora.services.mailer import send_mail
    try:
        from memora.services import emails as E
        subject, text, html = E.plain(title="메일 발송 테스트", text="메일 서버가 잘 연결됐어요. 회원에게 가는 인증 코드와 알림이 이 설정으로 나가요.", kicker="관리자")
        await send_mail(db, to=body.to, subject=subject, text=text, html=html)
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "error": str(e)[:300]}
    return {"ok": True}


@router.post("/telegram/set-webhook")
async def telegram_set_webhook(admin: CurrentAdmin, db: DB):
    """Register {PUBLIC_URL}/api/notifications/telegram/webhook with Telegram using secret_token = sha256(bot_token)[:32]
    (the value the webhook handler verifies). Also fills telegram.bot_username from getMe when empty."""
    from memora.config import get_settings
    from memora.providers.http import ProviderHTTPError, request
    from memora.services import notifications as NT
    token = await S.get(db, "telegram.bot_token", use_cache=False)
    if not token:
        raise ValidationFailed("telegram.bot_token is not set", code="telegram_not_configured")
    url = f"{get_settings().public_url.rstrip('/')}/api/notifications/telegram/webhook"
    secret = NT.telegram_webhook_secret(token)
    try:
        r = await request("POST", f"https://api.telegram.org/bot{token}/setWebhook",
                          json={"url": url, "secret_token": secret, "allowed_updates": ["message"], "drop_pending_updates": False}, retries=2)
        res = r.json()
        me = (await request("GET", f"https://api.telegram.org/bot{token}/getMe", retries=1)).json()
    except ProviderHTTPError as e:
        return {"ok": False, "error": f"telegram: {e.body[:200]}", "url": url}
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "error": f"{e.__class__.__name__}: {str(e)[:200]}", "url": url}
    username = ((me.get("result") or {}).get("username") or "") if isinstance(me, dict) else ""
    if username and not await S.get(db, "telegram.bot_username", use_cache=False):
        await S.put(db, "telegram.bot_username", username, updated_by=admin.id)
    audit.record(db, "telegram_webhook_set", actor_id=admin.id, actor_kind="admin", meta={"url": url, "ok": bool(res.get("ok"))})
    await db.commit()
    return {"ok": bool(res.get("ok")), "description": res.get("description"), "url": url, "bot_username": username}


@router.post("/setup/complete")
async def setup_complete(admin: CurrentAdmin, db: DB):
    await S.put(db, "setup_completed", True, updated_by=admin.id)
    await db.commit()
    return {"ok": True}


# ── 비서 트리거 이벤트 (plan/54) ──────────────────────────────────────
class TriggerPatch(BaseModel):
    enabled: bool | None = None
    provider: str | None = None
    model: str | None = None
    max_per_day: int | None = None
    lapse_after_days: int | None = None
    min_gap_minutes: int | None = None
    rules: list[dict] | None = None


async def _trigger_view(db) -> dict:
    """관리 화면 한 장이 읽는 전부: 설정·실제로 도는 모델·칸별 인원·최근 발송."""
    from memora.models import AgentRelationship
    from memora.services import triggers as TR

    cfg = await TR.config(db)
    provider, model, fell_back = await TR.model_for(db)
    # 칸별로 지금 몇 쌍이 서 있나. 칸은 저장된 값이 아니라 마지막 대화에서 나온다.
    now = datetime.now(UTC)
    rows = (await db.execute(select(AgentRelationship.last_turn_at, AgentRelationship.started_at,
                                    AgentRelationship.proactive_state))).all()
    counts = dict.fromkeys(TR.LADDER, 0)
    for last, started, st in rows:
        rel = type("R", (), {"last_turn_at": last, "started_at": started, "proactive_state": st or {}})()
        counts[TR.ladder_state(rel, now=now, tz=UTC, lapse_after=cfg["lapse_after_days"])["state"]] += 1
    # 발송 기록은 **메시지**에서 읽는다. 무엇을 태웠는지(usage)만 보면 "누가 언제
    # 무엇을 두 번 받았나" 를 알 수 없고, 관리자가 이 화면에 오는 이유가 보통 그것이다.
    sent = (await db.execute(text(
        "SELECT m.created_at, a.name AS agent, u.display_name AS owner, "
        "       m.cards->0->'payload'->>'kind' AS kind, m.cards->0->'payload'->>'rule' AS rule, "
        "       c.owner_id::text || ':' || c.agent_id::text AS pair "
        "  FROM messages m "
        "  JOIN conversations c ON c.id = m.conversation_id "
        "  JOIN agents a ON a.id = c.agent_id "
        "  JOIN users u ON u.id = c.owner_id "
        " WHERE m.cards->0->>'card_type' = 'proactive' "
        " ORDER BY m.created_at DESC LIMIT 30"))).all()
    worth = (await db.execute(text(
        "SELECT coalesce(sum(units), 0) FROM usage_events "
        " WHERE kind = 'trigger' AND created_at >= date_trunc('day', now())"))).scalar() or 0
    return {**cfg, "labels": TR.LADDER_LABELS, "kinds": list(TR.KINDS), "hard_max_per_day": TR.HARD_MAX_PER_DAY,
            "running": {"provider": provider, "model": model, "fell_back": fell_back},
            "states": counts,
            "today_worth": float(worth),
            "recent": [{"at": r[0].isoformat(), "agent": r[1] or "", "owner": r[2] or "",
                        "kind": r[3] or "", "rule": r[4] or "", "pair": r[5]} for r in sent],
            "defaults": TR.DEFAULT_RULES}


@router.get("/triggers")
async def triggers_get(admin: CurrentAdmin, db: DB):
    return await _trigger_view(db)


@router.put("/triggers")
async def triggers_put(body: TriggerPatch, admin: CurrentAdmin, db: DB):
    from memora.services import triggers as TR

    patch = {k: v for k, v in body.model_dump().items() if v is not None}
    await TR.save(db, patch, admin_id=admin.id)
    audit.record(db, "triggers_update", actor_id=admin.id, actor_kind="admin", meta={"keys": sorted(patch)})
    await db.commit()
    return await _trigger_view(db)


@router.post("/triggers/simulate")
async def triggers_simulate(body: TriggerPatch, admin: CurrentAdmin, db: DB, days: int = 30, talk_days: str = "0"):
    """저장하기 전에 본다: 이 규칙이면 30일 동안 언제 무엇이 가는가 (plan/54 §5)."""
    from memora.services import triggers as TR

    cfg = await TR.config(db)
    patch = {k: v for k, v in body.model_dump().items() if v is not None}
    if "rules" in patch:
        cfg = {**cfg, "rules": TR.normalise_rules(patch["rules"])}
    cfg = {**cfg, **{k: v for k, v in patch.items() if k in ("enabled", "max_per_day", "lapse_after_days", "min_gap_minutes")}}
    try:
        talked = tuple(int(x) for x in talk_days.split(",") if x.strip() != "")
    except ValueError:
        talked = (0,)
    return {"days": max(1, min(120, days)), "talk_days": list(talked),
            "events": TR.simulate(cfg, days=max(1, min(120, days)), talk_days=talked)}


@router.get("/triggers/log")
async def triggers_log(admin: CurrentAdmin, db: DB, since: str | None = None, until: str | None = None,
                       agent: str = "", rule: str = "", replied: str = "", offset: int = 0, limit: int = 50):
    """발송 기록 — 누구에게, 어느 비서가, 어떤 규칙으로, **무슨 말을** 보냈나 (plan/54 §5).

    관리자가 이 화면에 오는 이유는 보통 둘이다: "이 사람이 왜 두 번 받았나" 와 "이 기능이
    얼마를 쓰고, 사람들이 답을 하나". 그래서 한 줄에 받은 사람·비서·규칙이 있고, 위에는
    그 기간의 합계가, 줄을 누르면 실제로 간 말과 돌아온 답이 있다.

    값은 사용 기록(usage_events)에서, 말은 메시지에서 온다. 둘을 잇는 열쇠는 따로 없어서
    같은 짝·같은 비서의 **보내기 직전** 사용 기록을 붙인다(값을 적은 뒤에 보내므로).
    """
    from datetime import date as _date

    from memora.services import triggers as TR

    def _day(v: str | None, fallback: _date) -> _date:
        try:
            return _date.fromisoformat(v) if v else fallback
        except ValueError:
            return fallback

    today = datetime.now(UTC).date()
    d0 = _day(since, today - timedelta(days=6))
    d1 = _day(until, today)
    if d1 < d0:
        d0, d1 = d1, d0
    rows = (await db.execute(text(
        "SELECT m.id, m.created_at, m.content, m.conversation_id, "
        "       m.cards->0->'payload'->>'kind' AS kind, m.cards->0->'payload'->>'rule' AS rule, "
        "       a.id AS agent_id, a.name AS agent, a.avatar_url, u.id AS owner_id, "
        "       coalesce(nullif(u.display_name, ''), u.email) AS owner, "
        "       ue.units, ue.model_id, ue.input_tokens, ue.output_tokens, "
        "       rp.created_at AS replied_at, left(rp.content, 600) AS reply "
        "  FROM messages m "
        "  JOIN conversations c ON c.id = m.conversation_id "
        "  JOIN agents a ON a.id = c.agent_id "
        "  JOIN users u ON u.id = c.owner_id "
        "  LEFT JOIN LATERAL (SELECT e.units, e.model_id, e.input_tokens, e.output_tokens FROM usage_events e "
        "                      WHERE e.kind = 'trigger' AND e.owner_id = c.owner_id AND e.agent_id = c.agent_id "
        "                        AND e.created_at BETWEEN m.created_at - interval '3 minutes' "
        "                                             AND m.created_at + interval '5 seconds' "
        "                      ORDER BY e.created_at DESC LIMIT 1) ue ON true "
        "  LEFT JOIN LATERAL (SELECT r.created_at, r.content FROM messages r "
        "                      WHERE r.conversation_id = m.conversation_id AND r.role = 'user' "
        "                        AND r.created_at > m.created_at "
        "                      ORDER BY r.created_at LIMIT 1) rp ON true "
        " WHERE m.cards->0->>'card_type' = 'proactive' "
        "   AND m.created_at >= CAST(:d0 AS date) AND m.created_at < CAST(:d1 AS date) + interval '1 day' "
        " ORDER BY m.created_at DESC LIMIT 5000"), {"d0": d0, "d1": d1})).all()   # asyncpg 는 날짜를 글자로 받지 않는다

    cfg = await TR.config(db)
    labels = {r["key"]: r["label"] for r in [*cfg["rules"], *TR.DEFAULT_RULES]}
    usd_per_credit = float(await S.get(db, "credits.usd_per_credit") or 0)
    items = []
    last_by_pair: dict[str, datetime] = {}
    # 오래된 것부터 훑어야 "같은 짝의 직전 발송" 을 알 수 있다.
    for r in reversed(rows):
        pair = f"{r.owner_id}:{r.agent_id}"
        prev = last_by_pair.get(pair)
        last_by_pair[pair] = r.created_at
        # 답은 다음 발송 전에, 하루 안에 온 것만 이 말에 대한 답으로 본다.
        # 이름이 `replied` 이면 요청의 거르기 값을 덮어써서, [답이 온 것] 을 골라도 전부가
        # 나왔다. 반복문 안의 이름은 요청과 다르게 둔다.
        answered = r.replied_at is not None and r.replied_at - r.created_at <= timedelta(hours=24)
        items.append({
            "id": str(r.id), "at": r.created_at.isoformat(), "text": r.content or "",
            "conversation_id": str(r.conversation_id),
            "agent": {"id": str(r.agent_id), "name": r.agent, "avatar_url": r.avatar_url},
            "owner": {"id": str(r.owner_id), "name": r.owner},
            "kind": r.kind or "", "rule": r.rule or "", "label": labels.get(r.rule or "", ""),
            "model": r.model_id or "", "tokens": int(r.input_tokens or 0) + int(r.output_tokens or 0),
            "worth": float(r.units or 0),
            "repeat": prev is not None and r.created_at - prev < timedelta(hours=2),
            "replied_at": r.replied_at.isoformat() if answered else None,
            "reply": (r.reply or "") if answered else "",
        })
    items.reverse()
    # 고를 거리는 기간 안에 실제로 있는 것들에서 뽑는다 — 없는 비서를 고르게 하지 않는다.
    facets = {
        "agents": sorted({(i["agent"]["id"], i["agent"]["name"]) for i in items}, key=lambda x: x[1]),
        "rules": sorted({(i["rule"], i["label"] or i["rule"]) for i in items if i["rule"]}, key=lambda x: x[1]),
    }
    if agent:
        items = [i for i in items if i["agent"]["id"] == agent]
    if rule:
        items = [i for i in items if i["rule"] == rule]
    if replied == "yes":
        items = [i for i in items if i["replied_at"]]
    elif replied == "no":
        items = [i for i in items if not i["replied_at"]]
    worth = sum(i["worth"] for i in items)
    summary = {
        "count": len(items),
        "people": len({i["owner"]["id"] for i in items}),
        "worth": round(worth, 2), "usd": round(worth * usd_per_credit, 4),
        "replied": sum(1 for i in items if i["replied_at"]),
        "repeats": sum(1 for i in items if i["repeat"]),
    }
    limit = max(1, min(200, limit))
    return {"since": d0.isoformat(), "until": d1.isoformat(), "summary": summary,
            "facets": {"agents": [{"id": a, "name": n} for a, n in facets["agents"]],
                       "rules": [{"key": k, "label": lab} for k, lab in facets["rules"]]},
            "items": items[offset:offset + limit], "total": len(items)}


class TriggerTest(BaseModel):
    agent_id: uuid.UUID
    rule: dict


@router.post("/triggers/test")
async def triggers_test(body: TriggerTest, admin: CurrentAdmin):
    """관리자가 **자기 비서로** 한 규칙의 말을 받아 본다 (plan/54 §5).

    이것은 시험이다. 메시지도, 사다리의 표도, 기억도, 사용량도 남지 않는다. 말을 짓는
    길이 사이에 무언가를 적는 자리(글을 들춰 본 기록 같은)가 있어서, 저장하지 않는
    세션 하나를 열고 끝나면 통째로 되돌린다 — 조심해서 안 적는 것보다 적어도 버려지는
    쪽이 새는 곳이 없다.

    아직 저장하지 않은 규칙도 시험할 수 있다: 편집기가 보낸 규칙을 그대로 쓴다.
    """
    from memora.core.database import manager
    from memora.models import Agent, AgentRelationship, User
    from memora.services import relationship as REL
    from memora.services import triggers as TR

    rule = TR.normalise_rule(body.rule)
    async with manager.session("admin", commit=False) as tdb:
        try:
            agent = await tdb.get(Agent, body.agent_id)
            if agent is None or agent.owner_id != admin.id:
                raise NotFound("agent not found", code="agent_not_found")
            owner = await tdb.get(User, admin.id)
            now = datetime.now(UTC)
            rel = await REL.get(tdb, admin.id, agent.id)
            if rel is None:
                # 아직 대화한 적 없는 비서도 시험은 된다. 세션에 넣지 않는 임시 짝이다.
                rel = AgentRelationship(user_id=admin.id, agent_id=agent.id, stage="new", score=0.0, turns=0,
                                        active_days=0, streak_days=0, facts_remembered=0, milestones=[], mood={},
                                        proactive_count=0, proactive_state={}, started_at=now, last_turn_at=now)
            # **규칙이 정한 상황으로 받아 본다.** 관리자와 비서의 실제 사이로 돌리면,
            # 6~8일 침묵용 말을 사흘 침묵에서 받아 보고 "7일째" 인사를 17일째에 받아
            # 본다 — 규칙을 시험한 게 아니라 오늘의 내 사정을 시험한 것이 된다. 이 세션은
            # 되돌려지므로 짝의 시각을 옮겨 놓아도 남지 않는다.
            occasion = ""
            situation = ""
            if rule["when"].get("occasion") == "anniversary":
                days = rule["when"].get("days") or []
                if days:
                    rel.started_at = now - timedelta(days=days[0] - 1)
                    occasion = f"함께한 지 {days[0]}일째 되는 날"
                else:
                    occasion = "사이가 한 단계 가까워진 날"
                situation = occasion
            else:
                span = rule["when"].get("after_days") or rule["when"].get("silent_days")
                quiet = int(span[0]) if span else 0
                if rule["when"].get("state") == "active":
                    quiet = 0
                rel.last_turn_at = now - (timedelta(days=quiet) if quiet else timedelta(hours=2))
                rel.started_at = min(rel.started_at or now, rel.last_turn_at - timedelta(days=1))
                situation = f"마지막 대화가 {quiet}일 전인 상황" if quiet else "오늘 이미 대화한 상황"
            # 되돌리고 나면 행의 속성은 읽을 수 없다. 필요한 값은 그 전에 꺼내 둔다.
            who = {"id": str(agent.id), "name": agent.name, "avatar_url": agent.avatar_url}
            text, usage, ran = await REL.compose_proactive(tdb, rel, agent, owner, rule["kind"],
                                                           tone=rule["tone"], occasion=occasion)
        finally:
            await tdb.rollback()
    return {"text": text, "empty": not text, "agent": who,
            "rule": rule["key"], "label": rule["label"], "kind": rule["kind"], "occasion": occasion,
            "situation": situation,
            "model": ran.get("model", ""), "provider": ran.get("provider", ""), "fell_back": bool(ran.get("fell_back")),
            "tokens": {"input": int((usage or {}).get("input_tokens") or 0), "output": int((usage or {}).get("output_tokens") or 0)}}


# ── community ───────────────────────────────────────────────────────
@router.get("/community/overview")
async def community_overview(admin: CurrentAdmin, db: DB):
    from sqlalchemy import func as F

    from memora.models import CommunityComment, CommunityJob, CommunityPost, CommunityReport
    from memora.services import community as COMM
    since = datetime.now(UTC) - timedelta(days=7)
    posts = (await db.execute(select(F.count()).select_from(CommunityPost).where(CommunityPost.status == "published"))).scalar() or 0
    week = (await db.execute(select(F.count()).select_from(CommunityPost)
                             .where(CommunityPost.status == "published", CommunityPost.created_at >= since))).scalar() or 0
    comments = (await db.execute(select(F.count()).select_from(CommunityComment).where(CommunityComment.status == "published"))).scalar() or 0
    open_reports = (await db.execute(select(F.count()).select_from(CommunityReport).where(CommunityReport.status == "open"))).scalar() or 0
    jobs = (await db.execute(select(F.count()).select_from(CommunityJob).where(CommunityJob.status == "open"))).scalar() or 0
    return {"posts": posts, "posts_7d": week, "comments": comments, "open_reports": open_reports, "jobs": jobs,
            "boards": [{"id": str(b.id), "slug": b.slug, "name": b.name, "description": b.description,
                        "kind": b.kind, "icon": b.icon, "sort_order": b.sort_order, "enabled": b.enabled,
                        "post_count": b.post_count} for b in await COMM.boards_all(db)]}


class BoardIn(BaseModel):
    slug: str = Field(max_length=48)
    name: str = Field(max_length=60)
    description: str = Field(default="", max_length=400)
    kind: str = "discussion"
    icon: str = Field(default="", max_length=24)
    sort_order: int = 100


@router.post("/community/boards", status_code=201)
async def create_board(body: BoardIn, admin: CurrentAdmin, db: DB):
    from memora.services import community as COMM
    b = await COMM.admin_create_board(db, **body.model_dump())
    await db.commit()
    return {"id": str(b.id)}


@router.patch("/community/boards/{board_id}")
async def patch_board(board_id: uuid.UUID, body: dict, admin: CurrentAdmin, db: DB):
    from memora.services import community as COMM
    await COMM.admin_update_board(db, board_id, body)
    await db.commit()
    return {"ok": True}


@router.get("/community/reports")
async def community_reports(admin: CurrentAdmin, db: DB, status: str = "open"):
    from memora.services import community as COMM
    return {"items": await COMM.admin_reports(db, status=status)}


@router.post("/community/reports/{report_id}/resolve")
async def resolve_report(report_id: uuid.UUID, admin: CurrentAdmin, db: DB, action: str = "dismiss"):
    from memora.services import community as COMM
    await COMM.admin_resolve_report(db, report_id, action=action, admin_id=admin.id)
    await db.commit()
    return {"ok": True}


@router.get("/community/posts")
async def community_posts(admin: CurrentAdmin, db: DB, status: str = "published", limit: int = 50):
    from memora.services import community as COMM
    return {"items": await COMM.admin_posts(db, status=status, limit=limit)}


@router.post("/community/posts/{post_id}/status")
async def set_post_status(post_id: uuid.UUID, admin: CurrentAdmin, db: DB, status: str = "hidden"):
    from memora.services import community as COMM
    await COMM.admin_set_post_status(db, post_id, status)
    await db.commit()
    return {"ok": True}


# ── LLM management (plan/46) ─────────────────────────────────────────
#
# Everything that answers "where is the LLM load coming from, and what is it costing":
# the providers and their accounts, the live sessions each one is pinned to, the calls in
# flight, and the machine's share of it.


@router.get("/llm")
async def llm_overview(admin: CurrentAdmin, db: DB):
    from memora.core.llm_manager import manager as LLM
    from memora.services import claude_pool as CP

    pool: dict = {}
    try:
        pool = await CP.overview(db)
    except Exception:  # noqa: BLE001 — a broken pool must not take the dashboard with it
        pool = {"error": "unavailable"}
    return {**LLM.stats(), "pool": pool,
            "providers_configured": await _provider_state(db),
            "sessions": await _session_list(db)}


@router.get("/llm/sessions")
async def llm_sessions(admin: CurrentAdmin, db: DB):
    return {"items": await _session_list(db)}


@router.delete("/llm/sessions/{key}")
async def llm_close_session(key: str, admin: CurrentAdmin, db: DB):
    """Close one session, giving back its CLI process and its pooled account.

    The reason this exists: a session holds an account for as long as it lives, so one that
    is wedged is capacity nobody else can have, and the alternative was restarting the
    process and taking every other conversation with it.
    """
    from memora.pipeline.runtime import runtimes

    closed = await runtimes.close_key(key)
    if not closed:
        raise NotFound("session not found", code="session_not_found")
    audit.record(db, "llm_session_close", actor_id=admin.id, actor_kind="admin", meta={"key": key})
    await db.commit()
    return {"ok": True}


async def _provider_state(db) -> list[dict]:
    """Which providers this install can actually call, how they were checked, and how many
    models each one contributes to the catalogue."""
    from memora.services import catalog as CAT

    status = await S.get(db, "providers.status") or {}
    by_provider: dict[str, int] = {}
    for m in await CAT.list_models(db):
        if m.enabled:
            by_provider[m.provider] = by_provider.get(m.provider, 0) + 1
    out = []
    for pid, key in PROVIDER_KEYS.items():
        st = status.get(pid) or {}
        out.append({"id": pid, "configured": bool(await S.get(db, key)), "models": by_provider.get(pid, 0),
                    "verdict": st.get("verdict"), "checked_at": st.get("at")})
    # The CLI provider has no API key: it is configured when the pool can hand out an
    # account, which is a different question and worth showing as one.
    out.append({"id": "claude_code", "configured": bool(await CP.enabled(db)),
                "models": by_provider.get("claude_code", 0), "verdict": None, "checked_at": None})
    return out


async def _session_list(db) -> list[dict]:
    from memora.core.llm_manager import sessions as _sessions

    return await _sessions(db)


# ── worker & jobs (plan/46) ──────────────────────────────────────────


@router.get("/jobs/overview")
async def jobs_overview(admin: CurrentAdmin, db: DB, hours: int = 24):
    """The worker's own dashboard: what it is doing, what it has done, and what is waiting.

    The jobs table already holds all of this — it was only ever shown as a flat list of
    rows, so "is the queue keeping up", "which kind fails" and "is one owner taking the
    queue" all had to be eyeballed.
    """
    from sqlalchemy import text as _t

    hours = max(1, min(hours, 168))
    p = {"h": hours}

    kinds = (await db.execute(_t("""
        SELECT kind,
               count(*) FILTER (WHERE status = 'queued')  AS queued,
               count(*) FILTER (WHERE status = 'running') AS running,
               count(*) FILTER (WHERE status = 'done'   AND finished_at > now() - make_interval(hours => :h)) AS done,
               count(*) FILTER (WHERE status = 'failed' AND finished_at > now() - make_interval(hours => :h)) AS failed,
               count(*) FILTER (WHERE status = 'dead'   AND finished_at > now() - make_interval(hours => :h)) AS dead,
               coalesce(avg(EXTRACT(epoch FROM finished_at - locked_at)) FILTER (
                   WHERE status = 'done' AND finished_at > now() - make_interval(hours => :h)), 0) AS avg_s,
               coalesce(percentile_disc(0.95) WITHIN GROUP (ORDER BY EXTRACT(epoch FROM finished_at - locked_at)) FILTER (
                   WHERE status = 'done' AND finished_at > now() - make_interval(hours => :h)), 0) AS p95_s,
               coalesce(max(EXTRACT(epoch FROM now() - locked_at)) FILTER (WHERE status = 'running'), 0) AS oldest_running_s,
               coalesce(min(EXTRACT(epoch FROM now() - run_at)) FILTER (WHERE status = 'queued' AND run_at <= now()), 0) AS newest_wait_s,
               coalesce(max(EXTRACT(epoch FROM now() - run_at)) FILTER (WHERE status = 'queued' AND run_at <= now()), 0) AS oldest_wait_s
        FROM jobs GROUP BY kind ORDER BY queued DESC, done DESC
    """), p)).mappings().all()

    series = (await db.execute(_t("""
        SELECT to_timestamp(floor(EXTRACT(epoch FROM finished_at) / 900) * 900) AS bucket,
               count(*) FILTER (WHERE status = 'done')   AS done,
               count(*) FILTER (WHERE status IN ('failed', 'dead')) AS failed,
               coalesce(avg(EXTRACT(epoch FROM finished_at - locked_at)), 0) AS avg_s
        FROM jobs WHERE finished_at > now() - make_interval(hours => :h) GROUP BY 1 ORDER BY 1
    """), p)).mappings().all()

    # The fairness view: who is waiting, and how long the person behind them has waited.
    owners = (await db.execute(_t("""
        SELECT j.owner_id, coalesce(u.display_name, u.email, '(서비스)') AS name,
               count(*) AS queued,
               coalesce(max(EXTRACT(epoch FROM now() - j.run_at)), 0) AS oldest_wait_s
        FROM jobs j LEFT JOIN users u ON u.id = j.owner_id
        WHERE j.status = 'queued' AND j.run_at <= now()
        GROUP BY j.owner_id, u.display_name, u.email ORDER BY queued DESC LIMIT 12
    """))).mappings().all()

    running = (await db.execute(_t("""
        SELECT id, kind, locked_by, attempts, owner_id,
               EXTRACT(epoch FROM now() - locked_at) AS elapsed_s
        FROM jobs WHERE status = 'running' ORDER BY locked_at ASC LIMIT 30
    """))).mappings().all()

    # Only workers that have been alive today. A heartbeat row is per container id, and
    # nothing removes them, so every restart since the install left one behind: the list
    # was mostly headstones and the live worker had to be picked out of them.
    workers = (await db.execute(
        select(WorkerHeartbeat)
        .where(WorkerHeartbeat.last_seen_at > datetime.now(UTC) - timedelta(days=1))
        .order_by(WorkerHeartbeat.last_seen_at.desc()))).scalars().all()
    now = datetime.now(UTC)
    return {
        "kinds": [{"kind": r["kind"], "queued": int(r["queued"]), "running": int(r["running"]), "done": int(r["done"]),
                   "failed": int(r["failed"]), "dead": int(r["dead"]), "avg_s": round(float(r["avg_s"]), 2),
                   "p95_s": round(float(r["p95_s"]), 2), "oldest_running_s": round(float(r["oldest_running_s"]), 1),
                   "oldest_wait_s": round(float(r["oldest_wait_s"]), 1)} for r in kinds],
        "series": [{"at": r["bucket"].isoformat(), "done": int(r["done"]), "failed": int(r["failed"]),
                    "avg_s": round(float(r["avg_s"]), 2)} for r in series],
        "owners": [{"owner_id": str(r["owner_id"]) if r["owner_id"] else None, "name": r["name"],
                    "queued": int(r["queued"]), "oldest_wait_s": round(float(r["oldest_wait_s"]), 1)} for r in owners],
        "running": [{"id": str(r["id"]), "kind": r["kind"], "worker": r["locked_by"], "attempts": int(r["attempts"]),
                     "owner_id": str(r["owner_id"]) if r["owner_id"] else None,
                     "elapsed_s": round(float(r["elapsed_s"]), 1)} for r in running],
        "workers": [{"id": w.worker_id, "last_seen_at": w.last_seen_at.isoformat(), "info": w.info or {},
                     "stale": (now - w.last_seen_at).total_seconds() > 90} for w in workers],
        "limits": _worker_limits(),
        "window_hours": hours,
    }


def _worker_limits() -> dict:
    """The ceilings the worker enforces, shown next to what is actually running so a queue
    that is not moving can be read against the rule that is holding it."""
    from memora.worker.__main__ import CLASS_LIMITS, CONCURRENCY, KIND_CLASS, KIND_LIMITS

    return {"concurrency": CONCURRENCY, "kinds": dict(KIND_LIMITS), "classes": dict(CLASS_LIMITS),
            "kind_class": dict(KIND_CLASS)}


# ── diagnostics: server / database / storage (plan/46) ───────────────


@router.get("/diagnostics/server")
async def diag_server(admin: CurrentAdmin, db: DB):
    """The process and the machine it is on.

    Read from /proc rather than a dependency: this runs in a Linux container, the files are
    already there, and a diagnostics page should not be the reason a package is installed.
    """
    import os
    import shutil
    import sys

    from memora.config import get_settings as _settings
    from memora.core import pools
    from memora.core.watchdog import loop_lag
    from memora.memory.synapse import index_cache
    from memora.pipeline.events import journals
    from memora.pipeline.runtime import runtimes

    s = _settings()
    proc: dict = {"pid": os.getpid(), "python": sys.version.split()[0]}
    with contextlib.suppress(Exception):
        with open("/proc/self/status") as fh:
            for line in fh:
                if line.startswith("VmRSS:"):
                    proc["rss_mb"] = round(int(line.split()[1]) / 1024, 1)
                elif line.startswith("Threads:"):
                    proc["threads"] = int(line.split()[1])
    with contextlib.suppress(Exception):
        proc["open_files"] = len(os.listdir("/proc/self/fd"))
    with contextlib.suppress(Exception):
        with open("/proc/self/stat") as fh:
            parts = fh.read().split()
        ticks = os.sysconf("SC_CLK_TCK")
        proc["cpu_seconds"] = round((int(parts[13]) + int(parts[14])) / ticks, 1)
        with open("/proc/uptime") as fh:
            up = float(fh.read().split()[0])
        proc["uptime_s"] = round(up - int(parts[21]) / ticks, 1)
    host: dict = {}
    with contextlib.suppress(Exception):
        with open("/proc/loadavg") as fh:
            one, five, fifteen = fh.read().split()[:3]
        host["load"] = [float(one), float(five), float(fifteen)]
        host["cpus"] = os.cpu_count()
    with contextlib.suppress(Exception):
        with open("/proc/meminfo") as fh:
            mem = {k.rstrip(":"): int(v) for k, v, *_ in (line.split() for line in fh)}
        host["mem_total_mb"] = round(mem["MemTotal"] / 1024)
        host["mem_available_mb"] = round(mem["MemAvailable"] / 1024)
    disk: dict = {}
    with contextlib.suppress(Exception):
        u = shutil.disk_usage(s.data_dir)
        disk = {"total_gb": round(u.total / 1e9, 1), "free_gb": round(u.free / 1e9, 1),
                "used_pct": round(100 * (u.total - u.free) / u.total, 1)}
    return {
        "process": proc, "host": host, "disk": disk,
        "loop_lag_s": round(loop_lag(), 3),
        "pools": pools.stats(),
        "sessions": runtimes.count(), "active_turns": journals.active_count(),
        "open_indexes": index_cache.open_count(),
        "settings": {"timezone": s.timezone, "public_url": s.public_url, "debug": s.debug,
                     "idle_minutes": s.runtime_idle_minutes, "max_sessions": s.runtime_max_sessions},
    }


@router.get("/diagnostics/database")
async def diag_database(admin: CurrentAdmin, db: DB):
    """The pool this process owns, and the server on the other end of it."""
    from sqlalchemy import text as _t

    from memora.core.database import manager as dbm

    out: dict = {"pool": dbm.stats()}
    with contextlib.suppress(Exception):
        out["version"] = (await db.execute(_t("SHOW server_version"))).scalar_one()
        out["size_mb"] = round(float((await db.execute(_t("SELECT pg_database_size(current_database())"))).scalar_one()) / 1e6, 1)
        out["max_connections"] = int((await db.execute(_t("SHOW max_connections"))).scalar_one())
    with contextlib.suppress(Exception):
        rows = (await db.execute(_t("""
            SELECT coalesce(application_name, '?') AS app, state, count(*) AS n,
                   coalesce(max(EXTRACT(epoch FROM now() - state_change)), 0) AS oldest_s
            FROM pg_stat_activity WHERE datname = current_database()
            GROUP BY 1, 2 ORDER BY n DESC LIMIT 20
        """))).mappings().all()
        out["connections"] = [{"app": r["app"], "state": r["state"], "n": int(r["n"]),
                               "oldest_s": round(float(r["oldest_s"]), 1)} for r in rows]
    with contextlib.suppress(Exception):
        # Anything holding a transaction open is the thing that blocks everyone else, so it
        # is named rather than counted.
        rows = (await db.execute(_t("""
            SELECT pid, coalesce(application_name, '?') AS app, state, wait_event_type AS wait,
                   round(EXTRACT(epoch FROM now() - xact_start)::numeric, 1) AS xact_s,
                   left(regexp_replace(query, '\\s+', ' ', 'g'), 120) AS query
            FROM pg_stat_activity
            WHERE datname = current_database() AND xact_start IS NOT NULL
              AND now() - xact_start > interval '5 seconds'
            ORDER BY xact_start ASC LIMIT 10
        """))).mappings().all()
        out["long_transactions"] = [dict(r) for r in rows]
    with contextlib.suppress(Exception):
        rows = (await db.execute(_t("""
            SELECT relname AS table, n_live_tup AS rows,
                   pg_total_relation_size(relid) AS bytes,
                   coalesce(n_dead_tup, 0) AS dead_rows,
                   to_char(greatest(last_autovacuum, last_vacuum), 'YYYY-MM-DD HH24:MI') AS last_vacuum
            FROM pg_stat_user_tables ORDER BY pg_total_relation_size(relid) DESC LIMIT 12
        """))).mappings().all()
        out["tables"] = [{"table": r["table"], "rows": int(r["rows"]), "size_mb": round(int(r["bytes"]) / 1e6, 2),
                          "dead_rows": int(r["dead_rows"]), "last_vacuum": r["last_vacuum"]} for r in rows]
    with contextlib.suppress(Exception):
        r = (await db.execute(_t("""
            SELECT sum(heap_blks_hit) AS hit, sum(heap_blks_read) AS read FROM pg_statio_user_tables
        """))).mappings().one()
        total = float(r["hit"] or 0) + float(r["read"] or 0)
        out["cache_hit_ratio"] = round(float(r["hit"] or 0) / total, 4) if total else None
    return out


@router.get("/diagnostics/storage")
async def diag_storage(admin: CurrentAdmin, db: DB):
    """Where uploads actually live, and whether it is answering."""
    from sqlalchemy import text as _t

    from memora.config import get_settings as _settings
    from memora.services import objectstore as OS

    s = _settings()
    out: dict = {"mode": "s3" if OS.s3_enabled() else "local",
                 "endpoint": s.s3_endpoint, "bucket": s.s3_bucket}
    t0 = time.monotonic()
    try:
        out["health"] = await OS.health()
        out["latency_ms"] = round((time.monotonic() - t0) * 1000, 1)
    except Exception as e:  # noqa: BLE001
        out["health"] = {"ok": False, "error": f"{e.__class__.__name__}: {e}"[:200]}
    if OS.s3_enabled():
        with contextlib.suppress(Exception):
            out["usage"] = await OS.usage()
    else:
        with contextlib.suppress(Exception):
            import shutil
            u = shutil.disk_usage(s.upload_root)
            out["usage"] = {"objects": None, "bytes": None, "free_gb": round(u.free / 1e9, 1)}
    # What the application believes it has stored, which is the number that should match.
    with contextlib.suppress(Exception):
        r = (await db.execute(_t("""
            SELECT count(*) AS n, coalesce(sum(size_bytes), 0) AS bytes,
                   count(*) FILTER (WHERE storage_path LIKE 's3://%') AS in_s3
            FROM uploads
        """))).mappings().one()
        out["uploads"] = {"count": int(r["n"]), "bytes": int(r["bytes"]), "in_object_store": int(r["in_s3"])}
    with contextlib.suppress(Exception):
        r = (await db.execute(_t("""
            SELECT count(*) AS n, coalesce(sum(size_bytes), 0) AS bytes,
                   count(*) FILTER (WHERE status = 'failed') AS failed
            FROM knowledge_documents
        """))).mappings().one()
        out["documents"] = {"count": int(r["n"]), "bytes": int(r["bytes"]), "failed": int(r["failed"])}
    return out


# ── DB view: a read-only window, admin only (plan/48) ────────────────
#
# See services/dbview for why this is built the way it is. The short version: the
# application's database role is a superuser, so the safety cannot come from inspecting the
# SQL. It comes from running the query as a role that holds only SELECT, inside a read-only
# transaction, wrapped so that a non-SELECT is a syntax error.


class DbQueryIn(BaseModel):
    sql: str = Field(min_length=1, max_length=20_000)
    limit: int = Field(default=100, ge=1, le=500)
    table: str = Field(default="", max_length=120)


@router.get("/diagnostics/db/tables")
async def dbview_tables(admin: CurrentAdmin, db: DB):
    from memora.services import dbview as DV

    return {"items": await DV.list_tables(db), "role": DV.ROLE, "max_rows": DV.MAX_ROWS}


@router.get("/diagnostics/db/columns")
async def dbview_columns(admin: CurrentAdmin, db: DB, table: str):
    from memora.services import dbview as DV

    return {"items": await DV.columns_of(db, table)}


@router.post("/diagnostics/db/query")
async def dbview_query(body: DbQueryIn, admin: CurrentAdmin, db: DB, request: Request):
    """Run one read-only query.

    The query runs on its own session: ``SET TRANSACTION READ ONLY`` is only accepted
    before a transaction's first statement, and the request's own session has already
    started one by authenticating the administrator.
    """
    from memora.core.database import manager as dbm
    from memora.services import dbview as DV

    # Recorded before it runs, and recorded whatever happens to it: the audit trail for a
    # SQL console is only worth anything if a refused query is in it too.
    audit.record(db, "dbview_query", actor_id=admin.id, actor_kind="admin", ip=client_ip(request),
                 meta={"sql": body.sql[:2000], "limit": body.limit})
    await db.commit()
    async with dbm.session("admin", commit=False) as fresh:
        return await DV.run_query(fresh, body.sql, limit=body.limit, table_hint=body.table)
