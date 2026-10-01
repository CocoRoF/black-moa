"""Model catalog: seed from known prices, discover from providers, credit-per-1k math."""
from __future__ import annotations

from decimal import Decimal
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from blackmoa.models import ModelCatalog
from blackmoa.services import settings as S

# (provider, model_id, display, cli_alias, ctx, max_out, thinking, vision, usd_in/1M, usd_out/1M, usd_cache_read/1M)
#
# Prices and limits are the published ones as of 2026-09-08 (platform.claude.com/docs/about-claude/pricing,
# developers.openai.com/api/docs/pricing, ai.google.dev/gemini-api/docs/pricing). Newest first: the
# first claude_code row is what a fresh install runs.
#
# `cli_alias` is NOT a nickname for a pinned model — it is what gets sent to the CLI instead of
# model_id, so a pinned row must leave it empty or the install silently rides whatever that alias
# resolves to today. The alias rows below are the deliberate "always the latest" choice.
SEED = [
    ("claude_code", "claude-sonnet-5", "Claude Sonnet 5 (Claude Code)", None, 1_000_000, 128_000, True, True, 2, 10, 0.2),
    ("claude_code", "claude-opus-5", "Claude Opus 5 (Claude Code)", None, 1_000_000, 128_000, True, True, 5, 25, 0.5),
    ("claude_code", "claude-fable-5-1", "Claude Fable 5.1 (Claude Code)", None, 1_000_000, 128_000, True, True, 10, 50, 0.25),
    ("claude_code", "claude-haiku-4-5-20251001", "Claude Haiku 4.5 (Claude Code)", None, 200_000, 64_000, True, True, 1, 5, 0.1),
    # Alias rows: the CLI resolves these at launch, so they follow each new release without an edit.
    ("claude_code", "sonnet", "Sonnet 최신 (Claude Code)", "sonnet", 1_000_000, 128_000, True, True, 2, 10, 0.2),
    ("claude_code", "opus", "Opus 최신 (Claude Code)", "opus", 1_000_000, 128_000, True, True, 5, 25, 0.5),
    ("claude_code", "haiku", "Haiku 최신 (Claude Code)", "haiku", 200_000, 64_000, True, True, 1, 5, 0.1),
    ("claude_code", "fable", "Fable 최신 (Claude Code)", "fable", 1_000_000, 128_000, True, True, 10, 50, 0.25),
    ("anthropic", "claude-sonnet-5", "Claude Sonnet 5", None, 1_000_000, 128_000, True, True, 2, 10, 0.2),
    ("anthropic", "claude-opus-5", "Claude Opus 5", None, 1_000_000, 128_000, True, True, 5, 25, 0.5),
    ("anthropic", "claude-fable-5-1", "Claude Fable 5.1", None, 1_000_000, 128_000, True, True, 10, 50, 0.25),
    ("anthropic", "claude-haiku-4-5-20251001", "Claude Haiku 4.5", None, 200_000, 64_000, True, True, 1, 5, 0.1),
    ("openai", "gpt-5.6-terra", "GPT-5.6 terra", None, 400_000, 128_000, True, True, 2, 12, 0.2),
    ("openai", "gpt-5.6-luna", "GPT-5.6 luna", None, 400_000, 128_000, True, True, 0.2, 1.2, 0.02),
    ("openai", "gpt-6-astra", "GPT-6 astra", None, 400_000, 128_000, True, True, 10, 50, 1.0),
    ("gemini", "gemini-3.8-flash", "Gemini 3.8 Flash", None, 1_000_000, 65_536, True, True, 0.75, 3.75, 0.075),
    ("gemini", "gemini-3.1-pro-preview", "Gemini 3.1 Pro", None, 1_000_000, 65_536, True, True, 2, 12, 0.2),
]

DEFAULT_MODEL = ("claude_code", "claude-sonnet-5")

PROVIDER_TO_EXECUTOR = {"claude_code": "claude_code_cli", "anthropic": "anthropic", "openai": "openai", "gemini": "google"}


def usd_per_1m_to_credits_per_1k(usd_per_1m: float, usd_per_credit: float, margin: float) -> Decimal:
    if usd_per_credit <= 0:
        return Decimal("0")
    return Decimal(str(usd_per_1m / 1000.0 / usd_per_credit * margin)).quantize(Decimal("0.0001"))


async def seed(db: AsyncSession, *, overwrite_prices: bool = False) -> dict[str, object]:
    """Add the current models, and repair rows an older seed left in a lying state."""
    usd_per_credit = float(await S.get(db, "credits.usd_per_credit"))
    margin = float(await S.get(db, "credits.margin"))
    existing = {(m.provider, m.model_id): m for m in (await db.execute(select(ModelCatalog))).scalars().all()}
    added = 0
    has_default = any(m.is_default for m in existing.values())
    for i, (prov, mid, disp, alias, ctx, mo, think, vis, pin, pout, pcache) in enumerate(SEED):
        cin = usd_per_1m_to_credits_per_1k(pin, usd_per_credit, margin)
        cout = usd_per_1m_to_credits_per_1k(pout, usd_per_credit, margin)
        cc = usd_per_1m_to_credits_per_1k(pcache, usd_per_credit, margin)
        row = existing.get((prov, mid))
        if row is None:
            row = ModelCatalog(provider=prov, model_id=mid, display_name=disp, cli_alias=alias, context_window=ctx,
                               max_output=mo, supports_thinking=think, supports_vision=vis, credit_per_1k_input=cin,
                               credit_per_1k_output=cout, credit_per_1k_cache_read=cc, enabled=True,
                               is_default=(not has_default and (prov, mid) == DEFAULT_MODEL),
                               sort_order=i)
            if row.is_default:
                has_default = True
            db.add(row)
            existing[(prov, mid)] = row
            added += 1
        elif overwrite_prices:
            row.credit_per_1k_input, row.credit_per_1k_output, row.credit_per_1k_cache_read = cin, cout, cc

    # A pinned row must not carry an alias. cli_alias is what the CLI is actually launched
    # with, so `claude-sonnet-4-6` + alias `sonnet` ran whatever `sonnet` resolved to that
    # day — the catalog said one model and the service used another.
    repaired = 0
    for (_prov, mid), row in existing.items():
        if row.cli_alias and row.cli_alias != mid:
            row.cli_alias = None
            repaired += 1

    # Seeding is the "bring me up to date" action, so a default left on a model this release
    # no longer ships moves forward. A default the admin picked from the current set stays.
    seeded = {(p, m) for p, m, *_ in SEED}
    moved = ""
    current = next((m for m in existing.values() if m.is_default), None)
    if current is not None and (current.provider, current.model_id) not in seeded:
        target = existing.get(DEFAULT_MODEL)
        if target is not None:
            current.is_default = False
            target.is_default = True
            moved = target.model_id
    return {"added": added, "alias_repaired": repaired, "default_moved": moved}


def model_key(m: ModelCatalog) -> str:
    """How a plan names a model. provider *and* id, because the same id is sold by more
    than one of them (claude_code and anthropic both serve claude-sonnet-5)."""
    return f"{m.provider}:{m.model_id}"


async def list_models(db: AsyncSession, *, enabled_only: bool = False) -> list[ModelCatalog]:
    stmt = select(ModelCatalog).order_by(ModelCatalog.sort_order, ModelCatalog.provider, ModelCatalog.model_id)
    if enabled_only:
        stmt = stmt.where(ModelCatalog.enabled.is_(True))
    return list((await db.execute(stmt)).scalars().all())


async def get_model(db: AsyncSession, provider: str, model_id: str) -> ModelCatalog | None:
    return (await db.execute(select(ModelCatalog).where(ModelCatalog.provider == provider,
                                                        ModelCatalog.model_id == model_id))).scalars().first()


async def default_model(db: AsyncSession) -> ModelCatalog | None:
    m = (await db.execute(select(ModelCatalog).where(ModelCatalog.is_default.is_(True), ModelCatalog.enabled.is_(True)))).scalars().first()
    if m:
        return m
    rows = await list_models(db, enabled_only=True)
    return rows[0] if rows else None


async def resolve_model(db: AsyncSession, provider: str, model_id: str) -> tuple[ModelCatalog | None, bool]:
    """Return (catalog row, fell_back). Disabled/unknown → default model."""
    m = await get_model(db, provider, model_id)
    if m and m.enabled:
        return m, False
    d = await default_model(db)
    return d, True


# ── the pool, and what each plan may take from it (plan/33) ─────────
#
# Two dials, deliberately: the admin turns models *on* in the catalog — that is the pool,
# everything this install is willing to run — and then a plan may narrow that further. A
# plan with no picks offers the whole pool, so adding a model reaches every plan at once
# and nobody has to remember to widen four plans after turning one on.


async def pool(db: AsyncSession) -> list[ModelCatalog]:
    return await list_models(db, enabled_only=True)


async def allowed_for_plan(db: AsyncSession, plan: Any | None) -> list[ModelCatalog]:
    rows = await pool(db)
    picked = set(getattr(plan, "models", None) or [])
    if not picked:
        return rows
    keep = [m for m in rows if model_key(m) in picked]
    # A plan whose every pick has since left the pool falls back to the pool rather than to
    # nothing: an admin turning a model off must not leave a paying plan unable to answer.
    return keep or rows


async def default_for_plan(db: AsyncSession, plan: Any | None) -> ModelCatalog | None:
    rows = await allowed_for_plan(db, plan)
    return next((m for m in rows if m.is_default), rows[0] if rows else None)


async def resolve_for_plan(db: AsyncSession, plan: Any | None, provider: str, model_id: str) -> tuple[ModelCatalog | None, bool]:
    """Return (catalog row, fell_back), honouring what the plan may use."""
    rows = await allowed_for_plan(db, plan)
    m = next((r for r in rows if r.provider == provider and r.model_id == model_id), None)
    if m is not None:
        return m, False
    return await default_for_plan(db, plan), True
