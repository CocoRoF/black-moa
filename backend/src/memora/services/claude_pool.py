"""The Claude Code account pool — many authenticated identities, one leased per session.

Why this exists: a single Claude Code login makes one subscription's rate limit the whole
service's rate limit, and one expiring session the whole service's outage. An operator can
register several accounts here; every one gets its own CLI config directory, its own
device login and its own health, and the balancer (``services/claude_balancer``) hands out
one per pipeline build.

Layout — each account is a self-contained CLI home, so two accounts can never read each
other's tokens and no account touches the legacy ``MEMORA_CLAUDE_HOME``:

    <data_dir>/claude-accounts/<account-id>/          → HOME
    <data_dir>/claude-accounts/<account-id>/.claude/  → CLAUDE_CONFIG_DIR
    …/.claude/.credentials.json                       → the CLI's live copy (0600)

The database row is the source of truth and the file is a working copy: the CLI refreshes
the access token in the file by itself, so ``harvest`` copies it back (hourly job, and
after every login), and ``materialize`` writes it out again on a fresh container.

Concurrency counters are per-process. Under several API workers each process balances its
own share; the durable counters (leases, failures, cooldowns) are in the database and are
therefore global, which is what actually decides whether an account is in rotation.

Empty pool ⇒ everything falls back to the single-account path in ``services/claude_code``,
so an existing install keeps working until an administrator adds accounts.
"""
from __future__ import annotations

import asyncio
import contextlib
import json
import os
import time
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from memora.config import get_settings
from memora.core.errors import Conflict, NotFound, ValidationFailed
from memora.core.logging import get_logger
from memora.core.security import decrypt, encrypt
from memora.models import ClaudeAccount
from memora.services import claude_balancer as B
from memora.services import settings as S

log = get_logger("memora.claude.pool")

AUTH_MODES = ("oauth", "console", "setup_token", "api_key")
# oauth and console are the same runtime path (both end in .credentials.json); they differ
# only in which login flow the browser is sent to.
FILE_MODES = ("oauth", "console")


# ── filesystem layout ──────────────────────────────────────────────

def home_for(account_id: uuid.UUID | str) -> Path:
    return get_settings().data_dir / "claude-accounts" / str(account_id)


def config_dir_for(account_id: uuid.UUID | str) -> Path:
    return home_for(account_id) / ".claude"


def creds_path_for(account_id: uuid.UUID | str) -> Path:
    return config_dir_for(account_id) / ".credentials.json"


def _write_creds(account_id: uuid.UUID | str, data: dict[str, Any]) -> None:
    p = creds_path_for(account_id)
    p.parent.mkdir(parents=True, exist_ok=True)
    os.chmod(p.parent, 0o700)
    tmp = p.with_suffix(".tmp")
    tmp.write_text(json.dumps(data))
    os.chmod(tmp, 0o600)
    tmp.replace(p)


def remove_home(account_id: uuid.UUID | str) -> None:
    """Delete one account's CLI home, credential and all.

    Refuses any path that is not inside the accounts root. A recursive delete should never
    be one malformed id away from the data directory itself.
    """
    import shutil

    root = (get_settings().data_dir / "claude-accounts").resolve()
    try:
        home = home_for(account_id).resolve()
    except OSError:
        return
    if home == root or root not in home.parents:
        log.warning("refusing to remove a claude home outside the account root", path=str(home))
        return
    with contextlib.suppress(Exception):
        shutil.rmtree(home)


def _read_creds(account_id: uuid.UUID | str) -> dict[str, Any] | None:
    try:
        p = creds_path_for(account_id)
        return json.loads(p.read_text()) if p.exists() else None
    except Exception:  # noqa: BLE001
        return None


def _stored_creds(acc: ClaudeAccount) -> dict[str, Any] | None:
    if not acc.credentials_json:
        return None
    try:
        return json.loads(decrypt(acc.credentials_json))
    except Exception:  # noqa: BLE001
        return None


# ── credential shape (shared with the single-account service) ──────

def _oauth(creds: dict[str, Any] | None) -> dict[str, Any]:
    o = (creds or {}).get("claudeAiOauth") if isinstance(creds, dict) else None
    return o if isinstance(o, dict) else {}


def oauth_valid(creds: dict[str, Any] | None) -> bool:
    o = _oauth(creds)
    if not o.get("accessToken") or not o.get("refreshToken"):
        return False
    # The refresh token is what keeps a login alive; an expired *access* token is normal
    # and the CLI rotates it on its own.
    sess = o.get("refreshTokenExpiresAt")
    return not (sess and float(sess) / 1000 < time.time())


def _expires_at(creds: dict[str, Any] | None) -> float:
    try:
        return float(_oauth(creds).get("expiresAt") or 0)
    except (TypeError, ValueError):
        return 0.0


def _dt(ms: Any) -> datetime | None:
    try:
        return datetime.fromtimestamp(float(ms) / 1000, tz=UTC) if ms else None
    except (TypeError, ValueError, OSError):
        return None


def usable(acc: ClaudeAccount) -> bool:
    """Does this account hold something the CLI could authenticate with at all?"""
    if acc.auth_mode == "setup_token":
        return bool(acc.setup_token)
    if acc.auth_mode == "api_key":
        return bool(acc.api_key)
    return oauth_valid(_stored_creds(acc)) or oauth_valid(_read_creds(acc.id))


# ── live (per-process) rotation state ──────────────────────────────

@dataclass
class _Live:
    in_flight: dict[str, int] = field(default_factory=dict)
    state: B.BalancerState = field(default_factory=B.BalancerState)
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    # Lease bookkeeping is kept here and persisted by ``report``, which is already the one
    # place that writes the row. Leasing used to write it too, which put two writers on one
    # row inside a single flow: whichever session went second waited for a lock the first
    # was still holding. That is what stopped the queue — every background completion hung
    # on it, holding a worker slot. One writer, and the deadlock has nowhere to live.
    pending_leases: dict[str, int] = field(default_factory=dict)
    last_used: dict[str, float] = field(default_factory=dict)

    def forget(self, account_id: str) -> None:
        self.in_flight.pop(account_id, None)
        self.pending_leases.pop(account_id, None)
        self.last_used.pop(account_id, None)
        self.state.forget(account_id)


_live = _Live()


def in_flight_of(account_id: uuid.UUID | str) -> int:
    return _live.in_flight.get(str(account_id), 0)


@dataclass
class Lease:
    """A held slot on one account. Always released — ``release`` is idempotent."""

    account_id: uuid.UUID
    label: str
    auth_mode: str
    home: Path
    config_dir: Path
    setup_token: str = ""
    api_key: str = ""
    strategy: str = B.DEFAULT_STRATEGY
    acquired_at: float = field(default_factory=time.time)
    released: bool = False

    def release(self) -> None:
        if self.released:
            return
        self.released = True
        key = str(self.account_id)
        n = _live.in_flight.get(key, 0) - 1
        if n > 0:
            _live.in_flight[key] = n
        else:
            _live.in_flight.pop(key, None)


# ── policy / settings ──────────────────────────────────────────────

async def strategy(db: AsyncSession) -> str:
    s = await S.get(db, "providers.claude_code.pool.strategy") or B.DEFAULT_STRATEGY
    return s if s in B.STRATEGIES else B.DEFAULT_STRATEGY


async def policy(db: AsyncSession) -> B.HealthPolicy:
    async def num(key: str, default: float) -> float:
        try:
            return float(await S.get(db, key) or default)
        except (TypeError, ValueError):
            return default

    return B.HealthPolicy(
        failure_threshold=int(await num("providers.claude_code.pool.failure_threshold", 3)),
        failure_cooldown_s=await num("providers.claude_code.pool.failure_cooldown_s", 120.0),
        rate_limit_cooldown_s=await num("providers.claude_code.pool.rate_limit_cooldown_s", 900.0),
        quota_cooldown_s=await num("providers.claude_code.pool.quota_cooldown_s", 3600.0),
    )


async def list_accounts(db: AsyncSession) -> list[ClaudeAccount]:
    return list((await db.execute(select(ClaudeAccount).order_by(ClaudeAccount.created_at))).scalars().all())


def snapshot_of(acc: ClaudeAccount) -> B.AccountSnapshot:
    return B.AccountSnapshot(
        id=str(acc.id), label=acc.label, enabled=bool(acc.enabled), usable=usable(acc),
        status=acc.status or "unknown", weight=max(1, int(acc.weight or 1)),
        max_concurrency=max(1, int(acc.max_concurrency or 1)), in_flight=in_flight_of(acc.id),
        cooldown_until=acc.cooldown_until.timestamp() if acc.cooldown_until else 0.0,
        # Live values win: a lease taken a moment ago has not reached the row yet, and
        # rotation that cannot see it would hand the same account out again.
        last_used=max(acc.last_used_at.timestamp() if acc.last_used_at else 0.0,
                      _live.last_used.get(str(acc.id), 0.0)),
        total_leases=int(acc.total_leases or 0) + _live.pending_leases.get(str(acc.id), 0),
        consecutive_failures=int(acc.consecutive_failures or 0))


async def enabled(db: AsyncSession) -> bool:
    """True when the pool should be consulted at all — the switch *and* a member to lease."""
    if not bool(await S.get(db, "providers.claude_code.pool.enabled")):
        return False
    return any(a.enabled and usable(a) for a in await list_accounts(db))


# ── acquire / release ──────────────────────────────────────────────

async def acquire(db: AsyncSession, *, purpose: str = "session") -> Lease | None:
    """Lease the account the strategy picks, or ``None`` when the pool cannot serve.

    ``None`` is not an error: the caller falls back to the single-account credentials, which
    is what an install that never configured a pool has always used.
    """
    if not bool(await S.get(db, "providers.claude_code.pool.enabled")):
        return None
    accounts = await list_accounts(db)
    if not accounts:
        return None
    by_id = {str(a.id): a for a in accounts}
    strat = await strategy(db)
    # An account whose credential cannot be written out is broken *now*: skip it and ask
    # the strategy again rather than abandoning the pool. Falling back to the legacy single
    # credential because one member of three has an unwritable file is how a pool quietly
    # stops being a pool.
    skipped: set[str] = set()
    for _ in range(len(accounts)):
        now = time.time()
        async with _live.lock:
            # Snapshots are taken inside the lock so two coroutines cannot both read
            # in_flight=0 on the same account and both lease it past its ceiling.
            snaps = [snapshot_of(a) for a in accounts if str(a.id) not in skipped]
            pick = B.choose(snaps, strategy=strat, now=now, state=_live.state)
            if pick is None:
                # Full is not the same as unusable: a healthy account may take one more
                # session rather than let the conversation fail (plan/38).
                pick = B.over_capacity(snaps, now=now)
                if pick is not None:
                    log.info("claude pool over capacity; leasing anyway", purpose=purpose,
                             account=pick.label, in_flight=pick.in_flight, ceiling=pick.max_concurrency)
            if pick is None:
                if not skipped:
                    log.warning("claude pool has no eligible account", purpose=purpose,
                                reasons={a.label: B.ineligible_reason(snapshot_of(a), now=now) for a in accounts})
                break
            _live.in_flight[pick.id] = _live.in_flight.get(pick.id, 0) + 1
        acc = by_id[pick.id]
        lease = Lease(account_id=acc.id, label=acc.label, auth_mode=acc.auth_mode,
                      home=home_for(acc.id), config_dir=config_dir_for(acc.id),
                      setup_token=decrypt(acc.setup_token) if acc.setup_token else "",
                      api_key=decrypt(acc.api_key) if acc.api_key else "", strategy=strat)
        try:
            materialize(acc)
        except Exception as e:  # noqa: BLE001
            lease.release()
            skipped.add(pick.id)
            log.warning("could not materialize claude account credentials", account=acc.label, error=str(e)[:200])
            # Counted through the same health machine as any other unexplained failure, so
            # a disk that stays broken eventually rests the account instead of being picked
            # on every single build.
            await report(db, lease, ok=False, code="materialize_failed", error=str(e)[:200])
            continue
        # Recorded in memory; ``report`` folds it into the row. Nothing is written here,
        # so the caller's transaction leaves no lock on this account behind it.
        _live.pending_leases[pick.id] = _live.pending_leases.get(pick.id, 0) + 1
        _live.last_used[pick.id] = time.time()
        log.info("claude account leased", account=acc.label, strategy=strat, purpose=purpose,
                 in_flight=in_flight_of(acc.id))
        return lease
    if skipped:
        log.warning("claude pool could not hand out a usable account", purpose=purpose, skipped=len(skipped))
    return None


async def report(db: AsyncSession, lease: Lease | None, *, ok: bool, code: str | None = None,
                 error: str | None = None, release: bool = True) -> B.HealthDecision | None:
    """Fold one turn's verdict into the account's health, and (by default) free the slot.

    ``release=False`` is the session case: a conversation holds its account across many
    turns, so each turn reports health while the slot stays held until the runtime closes.
    """
    if lease is None:
        return None
    d: B.HealthDecision | None = None
    acc = await db.get(ClaudeAccount, lease.account_id)
    if acc is not None:
        d = B.apply_outcome(snapshot_of(acc), ok=ok, code=code, now=time.time(), policy=await policy(db))
        key = str(acc.id)
        pending = _live.pending_leases.pop(key, 0)
        if pending:
            acc.total_leases = int(acc.total_leases or 0) + pending
        seen = _live.last_used.pop(key, 0.0)
        if seen:
            acc.last_used_at = datetime.fromtimestamp(seen, tz=UTC)
        acc.status = d.status
        acc.consecutive_failures = d.consecutive_failures
        acc.cooldown_until = datetime.fromtimestamp(d.cooldown_until, tz=UTC) if d.cooldown_until else None
        if ok:
            acc.last_ok_at = datetime.now(UTC)
            acc.last_error = None
        else:
            acc.total_failures = int(acc.total_failures or 0) + 1
            if code not in B.NEUTRAL_CODES:
                acc.last_error = f"{code or 'unknown'}: {(error or '')[:300]}"
        if d.changed and not ok:
            log.warning("claude account health changed", account=acc.label, status=d.status, note=d.note)
    if release:
        lease.release()
    return d


# ── credential movement (db ↔ disk) ────────────────────────────────

def materialize(acc: ClaudeAccount) -> bool:
    """Write the stored credential out for the CLI — never over a newer live file."""
    home_for(acc.id).mkdir(parents=True, exist_ok=True)
    config_dir_for(acc.id).mkdir(parents=True, exist_ok=True)
    if acc.auth_mode not in FILE_MODES:
        return False
    stored = _stored_creds(acc)
    if not oauth_valid(stored):
        return False
    live = _read_creds(acc.id)
    if oauth_valid(live) and _expires_at(live) >= _expires_at(stored):
        return False
    _write_creds(acc.id, stored or {})
    return True


async def harvest(db: AsyncSession, acc: ClaudeAccount) -> bool:
    """Copy the CLI's refreshed file back into the row, and mirror what it says.

    Guarded both ways: an empty or expired file never overwrites a good backup, and an
    older one never overwrites a newer one.
    """
    if acc.auth_mode not in FILE_MODES:
        return False
    live = _read_creds(acc.id)
    if not oauth_valid(live):
        return False
    stored = _stored_creds(acc)
    if stored is not None and _expires_at(stored) >= _expires_at(live):
        return False
    acc.credentials_json = encrypt(json.dumps(live))
    o = _oauth(live)
    acc.subscription = (o.get("subscriptionType") or None)
    acc.rate_limit_tier = (o.get("rateLimitTier") or None)
    acc.access_expires_at = _dt(o.get("expiresAt"))
    acc.session_expires_at = _dt(o.get("refreshTokenExpiresAt"))
    if acc.status in ("unknown", "expired"):
        acc.status = "ready"
    return True


async def sync_all(db: AsyncSession) -> dict[str, int]:
    """Hourly job: harvest every refreshed file, and expire the logins that really died."""
    harvested = materialized = expired = 0
    for acc in await list_accounts(db):
        with contextlib.suppress(Exception):
            if await harvest(db, acc):
                harvested += 1
            if materialize(acc):
                materialized += 1
        if acc.auth_mode in FILE_MODES and acc.enabled and not usable(acc) and acc.status != "expired":
            acc.status = "expired"
            expired += 1
    return {"harvested": harvested, "materialized": materialized, "expired": expired}


# ── admin operations ───────────────────────────────────────────────

def _clean_label(label: str) -> str:
    out = (label or "").strip()[:64]
    if not out:
        raise ValidationFailed("label is required", code="label_required")
    return out


async def create(db: AsyncSession, *, label: str, email: str | None = None, auth_mode: str = "oauth",
                 weight: int = 1, max_concurrency: int = 16, notes: str | None = None) -> ClaudeAccount:
    if auth_mode not in AUTH_MODES:
        raise ValidationFailed(f"unknown auth mode {auth_mode}", code="bad_auth_mode")
    label = _clean_label(label)
    if (await db.execute(select(ClaudeAccount).where(ClaudeAccount.label == label))).scalar_one_or_none():
        raise Conflict("an account with that label already exists", code="label_taken")
    acc = ClaudeAccount(label=label, email=(email or "").strip()[:255] or None, auth_mode=auth_mode,
                        weight=max(1, min(1000, int(weight))), max_concurrency=max(1, min(64, int(max_concurrency))),
                        status="unknown", notes=(notes or None))
    db.add(acc)
    await db.flush()
    home_for(acc.id).mkdir(parents=True, exist_ok=True)
    config_dir_for(acc.id).mkdir(parents=True, exist_ok=True)
    return acc


async def get(db: AsyncSession, account_id: uuid.UUID) -> ClaudeAccount:
    acc = await db.get(ClaudeAccount, account_id)
    if acc is None:
        raise NotFound("claude account not found", code="claude_account_not_found")
    return acc


async def update(db: AsyncSession, account_id: uuid.UUID, **fields: Any) -> ClaudeAccount:
    acc = await get(db, account_id)
    if (label := fields.get("label")) is not None:
        label = _clean_label(label)
        dup = (await db.execute(select(ClaudeAccount).where(ClaudeAccount.label == label,
                                                            ClaudeAccount.id != acc.id))).scalar_one_or_none()
        if dup is not None:
            raise Conflict("an account with that label already exists", code="label_taken")
        acc.label = label
    if (email := fields.get("email")) is not None:
        acc.email = email.strip()[:255] or None
    if (mode := fields.get("auth_mode")) is not None:
        if mode not in AUTH_MODES:
            raise ValidationFailed(f"unknown auth mode {mode}", code="bad_auth_mode")
        acc.auth_mode = mode
    if (w := fields.get("weight")) is not None:
        acc.weight = max(1, min(1000, int(w)))
    if (c := fields.get("max_concurrency")) is not None:
        acc.max_concurrency = max(1, min(64, int(c)))
    if (e := fields.get("enabled")) is not None:
        acc.enabled = bool(e)
    if (n := fields.get("notes")) is not None:
        acc.notes = n[:2000] or None
    if (tok := fields.get("setup_token")):
        acc.setup_token = encrypt(tok.strip())
    if (key := fields.get("api_key")):
        acc.api_key = encrypt(key.strip())
    return acc


async def delete(db: AsyncSession, account_id: uuid.UUID) -> None:
    acc = await get(db, account_id)
    if in_flight_of(acc.id):
        raise Conflict("account is serving sessions; disable it first", code="account_busy")
    # The pool *is* the Claude Code provider, so it always has at least one row. Removing
    # the last one would leave the console with nothing to authenticate against — sign this
    # one in again instead.
    n = int((await db.execute(select(func.count(ClaudeAccount.id)))).scalar_one())
    if n <= 1:
        raise Conflict("this is the only account; sign it in again instead of removing it", code="last_account")
    _live.forget(str(acc.id))
    from memora.services.claude_code import forget_login
    forget_login(str(acc.id))
    # The whole CLI home goes with the row, not only the credential: the CLI's own
    # `.claude.json` records which account signed in (email, org) and `backups/` keeps
    # copies of it. Leaving that behind after an operator removed the account is exactly
    # the kind of leftover nobody audits.
    remove_home(acc.id)
    await db.delete(acc)


async def import_credentials(db: AsyncSession, account_id: uuid.UUID, raw_json: str) -> ClaudeAccount:
    acc = await get(db, account_id)
    try:
        data = json.loads(raw_json)
    except json.JSONDecodeError as e:
        raise ValidationFailed("invalid JSON", code="invalid_json") from e
    o = _oauth(data)
    if not o.get("accessToken") or not o.get("refreshToken"):
        raise ValidationFailed("missing claudeAiOauth.accessToken/refreshToken", code="invalid_credentials_shape")
    acc.credentials_json = encrypt(json.dumps(data))
    acc.subscription = o.get("subscriptionType") or None
    acc.rate_limit_tier = o.get("rateLimitTier") or None
    acc.access_expires_at = _dt(o.get("expiresAt"))
    acc.session_expires_at = _dt(o.get("refreshTokenExpiresAt"))
    if acc.auth_mode not in FILE_MODES:
        acc.auth_mode = "oauth"
    acc.status = "ready"
    acc.consecutive_failures = 0
    acc.cooldown_until = None
    acc.last_error = None
    materialize(acc)
    return acc


async def clear_cooldown(db: AsyncSession, account_id: uuid.UUID) -> ClaudeAccount:
    acc = await get(db, account_id)
    acc.cooldown_until = None
    acc.consecutive_failures = 0
    if acc.status in ("cooldown", "error"):
        acc.status = "ready" if usable(acc) else "unknown"
    return acc


async def probe(db: AsyncSession, account_id: uuid.UUID) -> dict[str, Any]:
    """Run one tiny turn on this account alone — the only honest proof it can serve."""
    from memora.providers.llm.credentials import build_bundle
    from memora.services.claude_code import run_probe

    acc = await get(db, account_id)
    materialize(acc)
    lease = Lease(account_id=acc.id, label=acc.label, auth_mode=acc.auth_mode, home=home_for(acc.id),
                  config_dir=config_dir_for(acc.id),
                  setup_token=decrypt(acc.setup_token) if acc.setup_token else "",
                  api_key=decrypt(acc.api_key) if acc.api_key else "")
    if not usable(acc):
        result = {"ok": False, "error": "credentials_missing: log in or import credentials for this account",
                  "at": datetime.now(UTC).isoformat(), "ms": 0}
    else:
        bundle = await build_bundle(db, "claude_code", timeout_s=120, lease=lease)
        result = await run_probe(bundle)
    acc.last_probe_at = datetime.now(UTC)
    if result.get("ok"):
        acc.status, acc.consecutive_failures, acc.cooldown_until, acc.last_error = "ready", 0, None, None
        acc.last_ok_at = datetime.now(UTC)
    else:
        acc.last_error = str(result.get("error"))[:300]
        if acc.status == "unknown":
            acc.status = "error"
    return result


# ── admin view ─────────────────────────────────────────────────────

def account_out(acc: ClaudeAccount, *, now: float | None = None) -> dict[str, Any]:
    snap = snapshot_of(acc)
    n = now if now is not None else time.time()
    return {
        "id": str(acc.id), "label": acc.label, "email": acc.email, "auth_mode": acc.auth_mode,
        "enabled": bool(acc.enabled), "weight": int(acc.weight or 1),
        "max_concurrency": int(acc.max_concurrency or 1), "status": acc.status,
        "in_flight": snap.in_flight, "usable": snap.usable,
        "eligible": B.ineligible_reason(snap, now=n) is None,
        "ineligible_reason": B.ineligible_reason(snap, now=n),
        "cooldown_until": acc.cooldown_until.isoformat() if acc.cooldown_until else None,
        "consecutive_failures": int(acc.consecutive_failures or 0),
        "total_leases": int(acc.total_leases or 0), "total_failures": int(acc.total_failures or 0),
        "last_used_at": acc.last_used_at.isoformat() if acc.last_used_at else None,
        "last_ok_at": acc.last_ok_at.isoformat() if acc.last_ok_at else None,
        "last_probe_at": acc.last_probe_at.isoformat() if acc.last_probe_at else None,
        "last_error": acc.last_error, "subscription": acc.subscription, "rate_limit_tier": acc.rate_limit_tier,
        "session_expires_at": acc.session_expires_at.isoformat() if acc.session_expires_at else None,
        "access_expires_at": acc.access_expires_at.isoformat() if acc.access_expires_at else None,
        "has_setup_token": bool(acc.setup_token), "has_api_key": bool(acc.api_key),
        "credentials_present": bool(acc.credentials_json) or creds_path_for(acc.id).exists(),
        "notes": acc.notes,
    }


async def overview(db: AsyncSession) -> dict[str, Any]:
    accounts = await list_accounts(db)
    now = time.time()
    items = [account_out(a, now=now) for a in accounts]
    return {
        "enabled": bool(await S.get(db, "providers.claude_code.pool.enabled")),
        "active": await enabled(db),
        "strategy": await strategy(db),
        "strategies": list(B.STRATEGIES),
        "policy": {"failure_threshold": (p := await policy(db)).failure_threshold,
                   "failure_cooldown_s": p.failure_cooldown_s,
                   "rate_limit_cooldown_s": p.rate_limit_cooldown_s,
                   "quota_cooldown_s": p.quota_cooldown_s},
        "accounts": items,
        "counts": {"total": len(items), "eligible": sum(1 for i in items if i["eligible"]),
                   "enabled": sum(1 for i in items if i["enabled"]),
                   "in_flight": sum(i["in_flight"] for i in items)},
    }


# ── one path, not two ──────────────────────────────────────────────

DEFAULT_LABEL = "기본 계정"


async def adopt_legacy(db: AsyncSession) -> ClaudeAccount | None:
    """Turn the single shared Claude Code login into account #1.

    The console used to show two things that were really one: a provider card holding one
    login, and a pool of accounts beside it. An operator had to understand which of the two
    was answering turns before they could do anything. There is one list now, and the login
    this install already had is the first row in it.

    Idempotent, and never destructive: the legacy credential is copied, not moved. Once an
    account exists the pool serves every turn, so nothing reads the old file for a turn
    again — but it is still there if an operator needs it.
    """
    if (await db.execute(select(ClaudeAccount.id).limit(1))).first():
        return None
    mode = await S.get(db, "providers.claude_code.auth_mode") or "oauth"
    acc = ClaudeAccount(label=DEFAULT_LABEL, auth_mode=mode if mode in AUTH_MODES else "oauth",
                        weight=1, max_concurrency=4, status="unknown",
                        notes="이 설치가 이미 쓰고 있던 로그인이에요.")
    db.add(acc)
    await db.flush()
    home_for(acc.id).mkdir(parents=True, exist_ok=True)
    config_dir_for(acc.id).mkdir(parents=True, exist_ok=True)
    if acc.auth_mode == "setup_token":
        tok = await S.get(db, "providers.claude_code.setup_token") or ""
        if tok:
            acc.setup_token = encrypt(tok)
    elif acc.auth_mode == "api_key":
        key = await S.get(db, "providers.anthropic.api_key") or ""
        if key:
            acc.api_key = encrypt(key)
    else:
        from memora.services.claude_code import read_credentials
        creds = None
        with contextlib.suppress(Exception):
            creds = read_credentials()
        if not oauth_valid(creds):
            stored = await S.get(db, "providers.claude_code.credentials_json")
            with contextlib.suppress(Exception):
                creds = json.loads(stored) if isinstance(stored, str) and stored else (stored or None)
        if oauth_valid(creds):
            acc.credentials_json = encrypt(json.dumps(creds))
            o = _oauth(creds)
            acc.subscription = o.get("subscriptionType") or None
            acc.rate_limit_tier = o.get("rateLimitTier") or None
            acc.access_expires_at = _dt(o.get("expiresAt"))
            acc.session_expires_at = _dt(o.get("refreshTokenExpiresAt"))
            acc.status = "ready"
            materialize(acc)
    log.info("adopted the existing Claude Code login as the first account",
             account=str(acc.id), mode=acc.auth_mode, authenticated=acc.status == "ready")
    return acc
