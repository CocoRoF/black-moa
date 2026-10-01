from __future__ import annotations

from typing import Any


class BlackMoaError(Exception):
    """Single error hierarchy. ``code`` is a stable snake_case string for clients."""

    status = 400
    code = "bad_request"

    def __init__(self, message: str = "", *, code: str | None = None, status: int | None = None, detail: Any = None):
        super().__init__(message or self.code)
        self.message = message or self.code
        if code:
            self.code = code
        if status:
            self.status = status
        self.detail = detail

    def to_dict(self) -> dict[str, Any]:
        out: dict[str, Any] = {"code": self.code, "message": self.message}
        if self.detail is not None:
            out["detail"] = self.detail
        return {"error": out}


class NotFound(BlackMoaError):
    status = 404
    code = "not_found"


class Unauthorized(BlackMoaError):
    status = 401
    code = "unauthorized"


class Forbidden(BlackMoaError):
    status = 403
    code = "forbidden"


class Conflict(BlackMoaError):
    status = 409
    code = "conflict"


class ValidationFailed(BlackMoaError):
    status = 422
    code = "validation_error"


class RateLimited(BlackMoaError):
    status = 429
    code = "rate_limited"


class PaymentRequired(BlackMoaError):
    status = 402
    code = "credits_exhausted"


class ServiceUnavailable(BlackMoaError):
    status = 503
    code = "service_unavailable"
