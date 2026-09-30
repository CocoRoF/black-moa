"""Password hashing, JWT, refresh tokens, at-rest encryption, key derivation."""
from __future__ import annotations

import base64
import hashlib
import hmac
import secrets
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import jwt
from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError
from cryptography.fernet import Fernet, InvalidToken
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

from memora.config import get_settings
from memora.core.errors import Unauthorized

_ph = PasswordHasher(time_cost=3, memory_cost=65536, parallelism=2)
_DEV_SECRET = "dev-secret-change-me-dev-secret-change-me"


def hash_password(pw: str) -> str:
    return _ph.hash(pw)


def verify_password(pw: str, h: str | None) -> bool:
    if not h:
        return False
    try:
        return _ph.verify(h, pw)
    except VerifyMismatchError:
        return False
    except Exception:
        return False


def _hkdf(label: str, length: int = 32, *, secret_key: str | None = None) -> bytes:
    # Keep the original memora-v1 salt/info contract stable. Existing JWTs and
    # legacy Fernet ciphertext depend on these exact bytes.
    ikm = (secret_key if secret_key is not None else get_settings().secret_key).encode()
    return HKDF(algorithm=hashes.SHA256(), length=length, salt=b"memora-v1", info=label.encode()).derive(ikm)


def _jwt_key(audience: str) -> bytes:
    return _hkdf(f"jwt:{audience}")


def legacy_fernet_key(secret_key: str | None = None) -> str:
    """Return the pre-rotation Fernet key derived from ``MEMORA_SECRET_KEY``."""
    return base64.urlsafe_b64encode(_hkdf("fernet", secret_key=secret_key)).decode()


def _fernet_key_strings() -> list[str]:
    settings = get_settings()
    primary = settings.encryption_key.strip() or legacy_fernet_key()
    values = [primary]
    for value in settings.encryption_key_previous.split(","):
        value = value.strip()
        if value and value not in values:
            values.append(value)
    return values


def _fernets() -> list[Fernet]:
    try:
        return [Fernet(value.encode()) for value in _fernet_key_strings()]
    except (ValueError, TypeError) as e:
        raise RuntimeError(
            "MEMORA_ENCRYPTION_KEY / MEMORA_ENCRYPTION_KEY_PREVIOUS must be urlsafe-base64 32-byte Fernet keys. "
            "Generate one with `python -m memora.core.keytool generate`, or leave MEMORA_ENCRYPTION_KEY empty to "
            "keep deriving it from MEMORA_SECRET_KEY."
        ) from e


def validate_security_settings() -> None:
    """Fail closed on production bootstrap secrets and malformed Fernet keys."""
    settings = get_settings()
    if settings.public_url.lower().startswith("https://"):
        if settings.secret_key == _DEV_SECRET or len(settings.secret_key.encode()) < 32:
            raise RuntimeError(
                "MEMORA_SECRET_KEY must be a unique secret of at least 32 bytes when MEMORA_PUBLIC_URL is https. "
                "Generate one with `python -c \'import secrets; print(secrets.token_urlsafe(48))\'` and set it in "
                "deploy/.env. If this deployment already stores encrypted data, pin the current Fernet key FIRST "
                "with `python -m memora.core.keytool legacy` -> MEMORA_ENCRYPTION_KEY (see deploy/README.md)."
            )
    _fernets()


def encrypt(text: str) -> str:
    if text is None:
        return ""
    return _fernets()[0].encrypt(text.encode()).decode()


def decrypt(token: str | None) -> str:
    if not token:
        return ""
    raw = token.encode()
    for fernet in _fernets():
        try:
            return fernet.decrypt(raw).decode()
        except InvalidToken:
            continue
    raise ValueError("decrypt failed")


def sha256(s: str | bytes) -> str:
    if isinstance(s, str):
        s = s.encode()
    return hashlib.sha256(s).hexdigest()


def create_access_token(user_id: uuid.UUID, role: str, sid: uuid.UUID | None = None) -> str:
    s = get_settings()
    now = datetime.now(UTC)
    payload: dict[str, Any] = {
        "sub": str(user_id), "role": role, "aud": "user", "iat": int(now.timestamp()),
        "exp": int((now + timedelta(minutes=s.access_token_minutes)).timestamp()), "jti": secrets.token_hex(8),
    }
    if sid:
        payload["sid"] = str(sid)
    return jwt.encode(payload, _jwt_key("user"), algorithm="HS256")


def decode_access_token(token: str) -> dict[str, Any]:
    try:
        return jwt.decode(token, _jwt_key("user"), algorithms=["HS256"], audience="user")
    except jwt.ExpiredSignatureError as e:
        raise Unauthorized("token expired", code="token_expired") from e
    except jwt.PyJWTError as e:
        raise Unauthorized("invalid token", code="invalid_token") from e


def create_visitor_token(visitor_id: uuid.UUID, agent_id: uuid.UUID, link_code: str) -> str:
    s = get_settings()
    now = datetime.now(UTC)
    payload = {
        "sub": str(visitor_id), "agent": str(agent_id), "code": link_code, "aud": "visitor",
        "iat": int(now.timestamp()), "exp": int((now + timedelta(days=s.visitor_token_days)).timestamp()),
    }
    return jwt.encode(payload, _jwt_key("visitor"), algorithm="HS256")


def decode_visitor_token(token: str) -> dict[str, Any]:
    try:
        return jwt.decode(token, _jwt_key("visitor"), algorithms=["HS256"], audience="visitor")
    except jwt.PyJWTError as e:
        raise Unauthorized("invalid visitor token", code="invalid_visitor_token") from e


def sign_state(payload: dict[str, Any], ttl_minutes: int = 15) -> str:
    now = datetime.now(UTC)
    data = dict(payload, aud="state", exp=int((now + timedelta(minutes=ttl_minutes)).timestamp()))
    return jwt.encode(data, _jwt_key("state"), algorithm="HS256")


def verify_state(token: str) -> dict[str, Any]:
    try:
        return jwt.decode(token, _jwt_key("state"), algorithms=["HS256"], audience="state")
    except jwt.PyJWTError as e:
        raise Unauthorized("invalid state", code="invalid_state") from e


def new_refresh_token() -> tuple[str, str]:
    raw = secrets.token_urlsafe(48)
    return raw, sha256(raw)


def hmac_signature(secret: str, body: bytes) -> str:
    return "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()


def constant_eq(a: str, b: str) -> bool:
    return hmac.compare_digest(a.encode(), b.encode())
