"""Input-side budget clamp (idea from XGEN context_budget): trim RAG block first, user text last."""
from __future__ import annotations

from dataclasses import dataclass

CHARS_PER_TOKEN = 3.2
CLAMP_NOTICE_KO = "입력이 길어 일부를 줄여서 처리했어요."


@dataclass
class Clamped:
    user_text: str
    reference_text: str
    clamped: bool


def estimate_tokens(text: str) -> int:
    return int(len(text) / CHARS_PER_TOKEN) + 1


def fit_input(user_text: str, reference_text: str, *, budget_tokens: int, reserved_tokens: int = 3000) -> Clamped:
    try:
        avail = max(2000, budget_tokens - reserved_tokens)
        total = estimate_tokens(user_text) + estimate_tokens(reference_text)
        if total <= avail:
            return Clamped(user_text, reference_text, False)
        over = total - avail
        ref_tokens = estimate_tokens(reference_text)
        cut = min(ref_tokens, over)
        if cut > 0 and reference_text:
            keep = max(0, len(reference_text) - int(cut * CHARS_PER_TOKEN))
            reference_text = reference_text[:keep].rstrip() + ("\n…[truncated]" if keep < len(reference_text) else "")
            over -= cut
        if over > 0 and user_text:
            keep_chars = max(200, len(user_text) - int(over * CHARS_PER_TOKEN))
            head = keep_chars * 2 // 3
            tail = keep_chars - head
            user_text = user_text[:head] + "\n…[중략]…\n" + (user_text[-tail:] if tail > 0 else "")
        return Clamped(user_text, reference_text, True)
    except Exception:
        return Clamped(user_text, reference_text, False)
