"""관리자 [연결] (plan/59) — 공급자마다 켜기 · 로그인에 쓰기 · 사용자에게 줄 기능 · 앱 키 · 설정 확인.

화면은 공급자 등록표(services/oauth)를 그대로 그린다. 관리자가 필요한 값을 넣고 켜면 로그인 버튼과
데이터 연동이 그대로 작동한다 — 코드를 고치지 않는다. 공급자 콘솔에 등록할 주소(Redirect URI·사이트
도메인)도 여기서 알려 준다: 틀리기 가장 쉬운 곳이 거기다.
"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Request
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import aliased

from blackmoa.config import get_settings
from blackmoa.core.deps import DB, CurrentAdmin, client_ip
from blackmoa.core.errors import ValidationFailed
from blackmoa.core.redact import mask
from blackmoa.models import AuthIdentity, Connection, User
from blackmoa.services import audit
from blackmoa.services import oauth as OA
from blackmoa.services import settings as S

router = APIRouter(prefix="/api/admin/connections", tags=["admin"])


async def _stats(db, p: OA.OAuthProvider) -> dict[str, Any]:
    identities = int((await db.execute(select(func.count(AuthIdentity.id)).where(AuthIdentity.provider == p.id))).scalar_one())
    # 이 방법으로만 들어오는 사람 — 로그인을 끄면 [비밀번호 찾기]로 비밀번호를 만들어야 들어온다.
    other = aliased(AuthIdentity)
    only = int((await db.execute(
        select(func.count(func.distinct(AuthIdentity.user_id))).join(User, User.id == AuthIdentity.user_id)
        .where(AuthIdentity.provider == p.id, User.password_hash.is_(None),
               ~select(other.id).where(other.user_id == AuthIdentity.user_id, other.provider != p.id).exists())
    )).scalar_one())
    by_status = dict((await db.execute(select(Connection.status, func.count()).where(Connection.provider == p.id)
                                       .group_by(Connection.status))).all())
    return {"identities": identities, "login_only": only, "connections": sum(by_status.values()),
            "connections_by_status": {k: int(v) for k, v in by_status.items()}}


async def _out(db, p: OA.OAuthProvider) -> dict[str, Any]:
    cfg = await p.config(db)
    fields = []
    for f in p.fields:
        v = cfg.values.get(f.key)
        item: dict[str, Any] = {"key": f.key, "kind": f.kind, "required": f.required}
        if f.kind == "secret":
            item.update({"has_value": bool(v), "masked": mask(str(v)) if v else ""})
        elif f.kind == "bool":
            item["value"] = bool(v)
        else:
            item["value"] = str(v or "")
        fields.append(item)
    missing = p.missing(cfg)
    return {"id": p.id, "label": p.label, "console_url": p.console_url,
            "enabled": cfg.enabled, "login": cfg.login, "features": cfg.features,
            "capabilities": [{"id": c.id, "scopes": list(c.scopes)} for c in p.capabilities],
            "login_scopes": list(p.login_scopes), "fields": fields, "missing": missing,
            "ready": cfg.enabled and not missing, "login_ready": cfg.enabled and cfg.login and not missing,
            "redirect_uris": {"login": p.redirect_uri("login"), "connect": p.redirect_uri("connect")},
            "stats": await _stats(db, p)}


@router.get("")
async def list_connections(admin: CurrentAdmin, db: DB):
    base = get_settings().public_url.rstrip("/")
    return {"site_url": base, "providers": [await _out(db, p) for p in OA.PROVIDERS.values()]}


class ProviderIn(BaseModel):
    enabled: bool | None = None
    login: bool | None = None
    features: list[str] | None = Field(default=None, max_length=32)
    #: 칸 값. 비밀 칸은 비워 보내면 그대로 둔다 — 지우려면 ``clear`` 에 적는다.
    values: dict[str, Any] = Field(default_factory=dict)
    clear: list[str] = Field(default_factory=list, max_length=8)


@router.put("/{provider}")
async def save_connection(provider: str, body: ProviderIn, admin: CurrentAdmin, db: DB, request: Request):
    p = OA.get(provider)
    known = {f.key: f for f in p.fields}
    changed: list[str] = []
    for k, v in body.values.items():
        f = known.get(k)
        if f is None:
            raise ValidationFailed(f"unknown field {k}", code="unknown_field")
        if f.kind == "bool":
            if not isinstance(v, bool):
                raise ValidationFailed(f"{k} must be a boolean", code="bad_value")
            val: Any = v
        else:
            if not isinstance(v, str):
                raise ValidationFailed(f"{k} must be a string", code="bad_value")
            val = v.strip()
            if len(val) > 500:
                raise ValidationFailed(f"{k} is too long", code="bad_value")
            if f.kind == "secret" and not val:
                continue        # 비워 보낸 비밀은 "바꾸지 않음"
        await S.put(db, p.key(k), val, updated_by=admin.id)
        changed.append(k)
    enabled_now = (await p.config(db)).enabled
    for k in body.clear:
        f = known.get(k)
        if f is None:
            raise ValidationFailed(f"unknown field {k}", code="unknown_field")
        if f.required and enabled_now and body.enabled is not False:
            # 켜 둔 채로 필수 값을 지우면 로그인·연동이 한순간에 멈춘다. 끄고 지운다.
            raise ValidationFailed(f"{k} is required", code="field_required")
        await S.put(db, p.key(k), False if f.kind == "bool" else "", updated_by=admin.id)
        changed.append(k)
    if body.features is not None:
        caps = [c.id for c in p.capabilities]
        bad = [x for x in body.features if x not in caps]
        if bad:
            raise ValidationFailed(f"unknown feature {', '.join(bad)}", code="unknown_feature")
        before = set((await p.config(db)).features)
        feats = [c for c in caps if c in body.features]
        await S.put(db, p.key("features"), feats, updated_by=admin.id)
        changed.append("features")
        removed = before - set(feats)
        if removed:
            # 거둔 기능은 이미 켜 둔 사용자에게서도 끈다 — 화면에서 사라졌는데 뒤에서 돌면 안 된다.
            for c in (await db.execute(select(Connection).where(Connection.provider == p.id))).scalars().all():
                if set(c.capabilities or []) & removed:
                    c.capabilities = sorted(set(c.capabilities or []) - removed)
    if body.login is not None:
        await S.put(db, p.key("login"), bool(body.login), updated_by=admin.id)
        changed.append("login")
    if body.enabled is not None:
        if body.enabled:
            S.invalidate(f"oauth.{p.id}.")
            missing = p.missing(await p.config(db))
            if missing:
                raise ValidationFailed("fill in the required fields first", code="connection_missing_fields",
                                       detail={"fields": missing})
        await S.put(db, p.key("enabled"), bool(body.enabled), updated_by=admin.id)
        changed.append("enabled")
    S.invalidate(f"oauth.{p.id}.")
    audit.record(db, "connection_settings", actor_id=admin.id, actor_kind="admin", ip=client_ip(request),
                 meta={"provider": p.id, "keys": changed})
    await db.commit()
    return await _out(db, p)


@router.post("/{provider}/check")
async def check_connection(provider: str, admin: CurrentAdmin, db: DB):
    """저장된 앱 키로 공급자에게 물어본다. 켜기 전에도 확인할 수 있다."""
    p = OA.get(provider)
    S.invalidate(f"oauth.{p.id}.")
    return {**await p.check(db), "redirect_uris": {"login": p.redirect_uri("login"), "connect": p.redirect_uri("connect")}}
