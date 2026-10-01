"""Startup verification that the configured Fernet keys still open existing data.

``BLACKMOA_ENCRYPTION_KEY`` may be empty, in which case the key is derived from
``BLACKMOA_SECRET_KEY`` (legacy contract). Rotating the signing key then silently
orphans every encrypted column: nothing fails at boot, and the deployment only
breaks later with opaque 500s the first time a provider key / OAuth token /
webhook config is read. plan/19 requires that to be caught at startup with an
actionable message, so this samples real at-rest ciphertext and fails closed.
"""
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from blackmoa.core.security import decrypt

_FIX_HINT = (
    "BLACKMOA_ENCRYPTION_KEY no longer decrypts this database's at-rest secrets. "
    "This normally means BLACKMOA_SECRET_KEY was rotated while BLACKMOA_ENCRYPTION_KEY was empty "
    "(the Fernet key is derived from the signing key when it is unset). To recover: "
    "(1) put the PREVIOUS BLACKMOA_SECRET_KEY back in deploy/.env, "
    "(2) run `sudo docker compose -p blackmoa run --rm --no-deps backend "
    "python -m blackmoa.core.keytool legacy` and copy the printed key, "
    "(3) set BLACKMOA_ENCRYPTION_KEY=<that key> permanently (or put it in "
    "BLACKMOA_ENCRYPTION_KEY_PREVIOUS and generate a new primary with "
    "`python -m blackmoa.core.keytool generate`), "
    "(4) restore the new BLACKMOA_SECRET_KEY and redeploy. See deploy/README.md."
)


async def _samples(db: AsyncSession) -> list[str]:
    """A few real ciphertexts from the tables that hold at-rest secrets."""
    from blackmoa.models import Connection, NotificationChannel, SystemSetting

    out: list[str] = []
    rows = (await db.execute(select(SystemSetting.value).where(SystemSetting.is_secret.is_(True)).limit(20))).scalars().all()
    for value in rows:
        raw = value.get("v") if isinstance(value, dict) else value
        if isinstance(raw, str) and raw:
            out.append(raw)
    for column in (NotificationChannel.config_enc, Connection.access_token_enc, Connection.refresh_token_enc):
        for raw in (await db.execute(select(column).where(column.is_not(None)).limit(5))).scalars().all():
            if isinstance(raw, str) and raw:
                out.append(raw)
    return out


async def verify_encryption_keys(db: AsyncSession) -> int:
    """Raise with an operator-actionable message when no sampled secret decrypts.

    Returns the number of samples checked. A fresh install has none and passes.
    A single corrupt column cannot brick a boot either: the failure requires
    that *every* sample fails, which is what a key mismatch actually looks like.
    """
    samples = await _samples(db)
    if not samples:
        return 0
    for raw in samples:
        try:
            decrypt(raw)
        except ValueError:
            continue
        return len(samples)
    raise RuntimeError(f"{_FIX_HINT} (checked {len(samples)} stored secrets, none could be decrypted)")
