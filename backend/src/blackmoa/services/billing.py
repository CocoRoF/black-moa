"""Stripe adapter (active only when keys are configured)."""
from __future__ import annotations

import hashlib
import hmac
import json
import time
import uuid
from datetime import UTC, datetime

from sqlalchemy.ext.asyncio import AsyncSession

from blackmoa.config import get_settings
from blackmoa.core.errors import Forbidden, ServiceUnavailable, ValidationFailed
from blackmoa.models import Purchase, User
from blackmoa.providers.http import request
from blackmoa.services import credits as CR
from blackmoa.services import settings as S

PACKAGES = {"small": 1000, "medium": 5000, "large": 20000}


async def create_checkout(db: AsyncSession, user: User, package: str) -> str:
    key = await S.get(db, "stripe.secret_key")
    prices = await S.get(db, "stripe.price_ids") or {}
    if not key or package not in prices:
        raise ServiceUnavailable("billing not configured", code="billing_unavailable")
    base = get_settings().public_url.rstrip("/")
    p = Purchase(owner_id=user.id, provider="stripe", credits=PACKAGES.get(package, 0), status="pending", created_at=datetime.now(UTC))
    db.add(p)
    await db.flush()
    r = await request("POST", "https://api.stripe.com/v1/checkout/sessions", headers={"Authorization": f"Bearer {key}"},
                      data={"mode": "payment", "line_items[0][price]": prices[package], "line_items[0][quantity]": "1",
                            "success_url": f"{base}/app/credits?purchase=ok", "cancel_url": f"{base}/app/credits?purchase=cancel",
                            "client_reference_id": str(p.id), "metadata[purchase_id]": str(p.id), "customer_email": user.email}, retries=1)
    j = r.json()
    p.external_id = j.get("id")
    await db.commit()
    return j["url"]


async def handle_webhook(db: AsyncSession, body: bytes, sig_header: str) -> None:
    secret = await S.get(db, "stripe.webhook_secret")
    if not secret:
        raise Forbidden("webhook not configured")
    parts = dict(kv.split("=", 1) for kv in sig_header.split(",") if "=" in kv)
    ts, v1 = parts.get("t"), parts.get("v1")
    if not ts or not v1 or abs(time.time() - int(ts)) > 300:
        raise Forbidden("bad signature")
    expected = hmac.new(secret.encode(), f"{ts}.".encode() + body, hashlib.sha256).hexdigest()
    if not hmac.compare_digest(expected, v1):
        raise Forbidden("bad signature")
    ev = json.loads(body)
    if ev.get("type") != "checkout.session.completed":
        return
    sess = ev["data"]["object"]
    pid = (sess.get("metadata") or {}).get("purchase_id") or sess.get("client_reference_id")
    if not pid:
        raise ValidationFailed("no purchase id")
    p = await db.get(Purchase, uuid.UUID(pid))
    if p is None or p.status == "paid":
        return
    p.status = "paid"
    p.amount_cents = int(sess.get("amount_total") or 0)
    p.currency = (sess.get("currency") or "usd").upper()
    await CR.apply(db, p.owner_id, p.credits, "purchase", ref_type="purchase", ref_id=str(p.id), note="stripe")
