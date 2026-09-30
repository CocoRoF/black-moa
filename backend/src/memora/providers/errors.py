"""Provider error classification → stable codes + user messages (ported idea from XGEN classify_llm_error_message)."""
from __future__ import annotations

import re

_CREDIT = ("insufficient_quota", "exceeded your current quota", "billing_hard_limit_reached", "credit balance is too low",
           "credit_balance_too_low", "credit balance", "billing hard limit")
_AUTH = ("not authenticated", "unauthorized", "authentication_failed", "invalid api key", "invalid x-api-key",
         "incorrect api key", "401", "auth_failed", "please run /login", "not logged in")
_CTX = ("prompt is too long", "context_length_exceeded", "maximum context length", "too many tokens", "context window")
_RATE = ("429", "rate limit", "rate_limit", "overloaded", "too many requests")

MESSAGES = {
    "provider_auth": ("AI 프로바이더 인증에 실패했어요. 관리자에게 알려주세요.", "AI provider authentication failed. Please contact the admin."),
    "provider_quota": ("AI 프로바이더 사용량/결제 한도에 도달했어요. 관리자에게 알려주세요.", "AI provider quota or billing limit reached."),
    "rate_limited": ("잠시 후 다시 시도해 주세요.", "Please try again in a moment."),
    "context_limit": ("대화가 너무 길어졌어요. 새 대화를 시작해 주세요.", "The conversation is too long. Please start a new one."),
    "cli_not_found": ("Claude Code 실행 파일을 찾지 못했어요. 관리자에게 알려주세요.", "Claude Code binary not found."),
    "timeout": ("응답이 너무 오래 걸려 중단했어요. 다시 시도해 주세요.", "The response timed out. Please try again."),
    "cancelled": ("응답이 취소됐어요.", "The response was cancelled."),
    "unknown": ("답변 생성 중 문제가 생겼어요. 잠시 후 다시 시도해 주세요.", "Something went wrong while answering. Please try again."),
}


def classify(error_text: str, *, executor_code: str | None = None) -> str:
    t = (error_text or "").lower()
    if executor_code:
        if executor_code.endswith("auth_failed"):
            return "provider_auth"
        if executor_code.endswith("binary_not_found"):
            return "cli_not_found"
        if executor_code.endswith("timeout"):
            return "timeout"
    if any(m in t for m in _CTX):
        return "context_limit"
    if any(m in t for m in _CREDIT):
        return "provider_quota"
    if any(m in t for m in _AUTH) and not re.search(r"length \d{5,}", t):
        return "provider_auth"
    if any(m in t for m in _RATE):
        return "rate_limited"
    if "timeout" in t or "timed out" in t:
        return "timeout"
    return "unknown"


def user_message(code: str, locale: str = "ko") -> str:
    ko, en = MESSAGES.get(code, MESSAGES["unknown"])
    return ko if locale.startswith("ko") else en


def retryable(code: str) -> bool:
    return code in ("rate_limited", "timeout", "unknown")
