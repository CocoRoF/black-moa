from __future__ import annotations

from typing import Any


class MemoraError(Exception):
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


class NotFound(MemoraError):
    status = 404
    code = "not_found"


class Unauthorized(MemoraError):
    status = 401
    code = "unauthorized"


class Forbidden(MemoraError):
    status = 403
    code = "forbidden"


class Conflict(MemoraError):
    status = 409
    code = "conflict"


class ValidationFailed(MemoraError):
    status = 422
    code = "validation_error"


class RateLimited(MemoraError):
    status = 429
    code = "rate_limited"


class PaymentRequired(MemoraError):
    status = 402
    code = "credits_exhausted"


class ServiceUnavailable(MemoraError):
    status = 503
    code = "service_unavailable"
