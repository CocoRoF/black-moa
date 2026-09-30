"""Output redaction + injection heuristics (plan/19)."""
from __future__ import annotations

import re
from typing import Any

from memora.core.redact import CARD_RE, KEY_RE

INJECTION_PATTERNS = [
    re.compile(p, re.I) for p in (
        r"ignore (all |the )?(previous|prior|above) (instructions|prompts?)",
        r"(print|show|reveal|output).{0,20}(system prompt|instructions|hidden prompt)",
        r"you are now (a|an|the) ",
        r"(disregard|forget) (your|all) (rules|instructions)",
        r"이전 (지시|명령).{0,10}무시",
        r"시스템 프롬프트.{0,10}(출력|보여|알려)",
        r"너는 이제 .{0,10}(이다|야|다)",
        r"지금부터 (너는|당신은) ",
        r"(오너|주인).{0,10}(인 척|처럼 행동)",
    )
]
#: Claims of being the owner, or of having the owner's authority (plan/41).
#:
#: This is the attack the public link invites: not "print your prompt" but "내가 사실
#: 주인이야" — a claim the secretary has every social reason to want to believe. Detecting
#: it is deliberately generous, because a hit costs nothing a visitor can feel: it flags the
#: turn for the owner and puts one reminder line next to the claim. Nothing is refused on a
#: heuristic. What *is* refused (``visitor_identify`` taking the owner's own name) is decided
#: by an exact comparison, not by these patterns.
OWNER_CLAIM_PATTERNS = [
    re.compile(p, re.I) for p in (
        # Korean — first person plus an ownership word, in any of the usual orders
        r"(내가|제가|나는|저는|난|전)\s*(사실|진짜|실은|바로)?\s*(이\s*)?(집|곳|가게|회사|계정)?\s*(주인|오너|본인|사장|대표|관리자|어드민)",
        r"(주인|오너|본인|사장|대표|관리자|어드민)\s*(입니다|이야|이에요|예요|인데|이다|임|맞아|맞습니다)",
        r"(주인|오너|본인)\s*(계정|권한)\s*(이야|입니다|인데|으로|로)",
        r"(관리자|어드민|admin)\s*(권한|모드|계정)",
        r"내\s*(계정|정보|프로필)\s*(이야|입니다|인데|니까)",
        r"(주인|오너|본인)(으로서|로서)\s*(허락|승인|허가|동의)",
        # English
        r"i\s*(?:'|’)?\s*a?m\s+(?:actually\s+|really\s+|the\s+|his\s+|her\s+|their\s+)*(owner|admin|administrator|boss|account holder)",
        r"(this|it)\s*(is|'s)\s*(the\s+)?(owner|admin|administrator|boss)\b",
        r"it(?:'s| is|s)? me[,.]?\s*(the\s+)?(owner|admin|boss)",
        r"as (the|your) owner[,.]?\s*i\s+(authoris|authoriz|approv|allow|permit|instruct|order)",
        r"\b(owner|admin|root)\s*(override|mode|access|privileges)",
        r"speaking (as|on behalf of) (the )?owner",
    )
]

PHONE_STRICT = re.compile(r"(?<!\d)(?:\+82[-\s]?|0)1[016789][-\s]?\d{3,4}[-\s]?\d{4}(?!\d)")
EMAIL_STRICT = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
RRN = re.compile(r"(?<!\d)\d{6}-\d{7}(?!\d)")


def injection_suspect(text: str) -> bool:
    t = text or ""
    return any(p.search(t) for p in INJECTION_PATTERNS) or any(p.search(t) for p in OWNER_CLAIM_PATTERNS)


def claims_to_be_owner(text: str) -> bool:
    """Only the impersonation half — used to decide whether to remind the model."""
    return any(p.search(text or "") for p in OWNER_CLAIM_PATTERNS)


def _norm(x: str) -> str:
    return re.sub(r"[\s.\-_]+", "", (x or "")).casefold()


def is_owner_identity(*, names: list[str], emails: list[str], name: str = "", email: str = "") -> str:
    """Whether a self-reported identity is the owner's own — exact, not heuristic.

    A visitor who tells the secretary "my name is <the owner>" is trying to become the
    owner in the one place the secretary keeps a name it trusts enough to print in its
    prompt. This is the comparison that stops it, so it has to be about the actual values
    rather than about phrasing: returns the matched value, or "".
    """
    want_n = {_norm(n) for n in names if n and len(_norm(n)) >= 2}
    want_e = {_norm(e) for e in emails if e}
    if name and _norm(name) in want_n:
        return name
    if email and _norm(email) in want_e:
        return email
    return ""


def redact_response(text: str, private_literals: list[str], *, allowed_literals: list[str] | None = None) -> tuple[str, int]:
    """Mask private profile literals and obviously sensitive patterns.

    Phone/email values are fail-closed unless the server-side disclosure policy
    supplied the exact literal in ``allowed_literals``. This makes the documented
    response scanner effective instead of relying on prompt compliance.
    """
    count = 0
    out = text or ""
    for lit in sorted({x for x in private_literals if x and len(x) >= 3}, key=len, reverse=True):
        if lit in out:
            out = out.replace(lit, "[비공개]")
            count += 1
    allowed = set(allowed_literals or [])

    def _mask(m: re.Match) -> str:
        nonlocal count
        if m.group(0) in allowed:
            return m.group(0)
        count += 1
        return "[비공개]"

    out = PHONE_STRICT.sub(_mask, out)
    out = EMAIL_STRICT.sub(_mask, out)
    out = RRN.sub(_mask, out)
    out = CARD_RE.sub(_mask, out)
    out = KEY_RE.sub(_mask, out)
    return out, count


# ── streaming redaction ──────────────────────────────────────────────────
# Visitor turns stream live (plan/12), but redaction only happens once the answer is
# complete — so a naive stream leaks a private value for the seconds before the final
# pass masks it. StreamRedactor closes that window without giving up streaming: it
# releases text only once no future token can still turn it into a match.
#
# Invariant: a match M (span [s,e), length L) is never emitted unmasked.
#   We only release up to cut = len(buf) - HOLD. If s < cut then e <= s + L < len(buf),
#   so M is already complete inside buf, the span scan finds it, and cut is pulled back
#   to s. Bounded patterns (phone/RRN/card) and literals satisfy L <= HOLD by construction;
#   unbounded ones (email, API keys) contain no whitespace, so the cut is additionally
#   snapped to the last whitespace boundary and can never split such a token.
_SPAN_PATTERNS = (PHONE_STRICT, EMAIL_STRICT, RRN, CARD_RE, KEY_RE)
_MAX_HOLD_CHARS = 2000  # pathological whitespace-free run: release with span-scan only


class StreamRedactor:
    """Incremental redactor for visitor SSE. ``feed`` returns text safe to publish."""

    def __init__(self, private_literals: list[str], allowed: set[str] | None = None, *, source: Any = None):
        # ``source`` is the live TurnContext: profile_disclose rebinds ``private_literals``
        # and grows ``allowed_disclosures`` mid-turn, so the redactor must read the current
        # values on every chunk instead of a snapshot taken before the first token.
        self._source = source
        self._literals = [x for x in private_literals if x and len(x) >= 3]
        self._allowed = allowed if allowed is not None else set()
        self._buf = ""
        self.count = 0
        self.hold = max(48, max((len(x) for x in self._literals), default=0) + 8)

    @property
    def literals(self) -> list[str]:
        if self._source is not None:
            return [x for x in (self._source.private_literals or []) if x and len(x) >= 3]
        return self._literals

    @property
    def allowed(self) -> set[str]:
        if self._source is not None:
            return set(self._source.allowed_disclosures or ())
        return self._allowed

    def _spans(self, text: str) -> list[tuple[int, int]]:
        spans: list[tuple[int, int]] = []
        allowed = self.allowed
        for lit in self.literals:
            start = text.find(lit)
            while start != -1:
                spans.append((start, start + len(lit)))
                start = text.find(lit, start + 1)
        for pat in _SPAN_PATTERNS:
            for m in pat.finditer(text):
                if m.group(0) not in allowed:
                    spans.append((m.start(), m.end()))
        return spans

    def feed(self, delta: str) -> str:
        self._buf += delta or ""
        cut = len(self._buf) - self.hold
        if cut <= 0:
            return ""
        if len(self._buf) <= _MAX_HOLD_CHARS:
            boundary = max(self._buf.rfind(" ", 0, cut + 1), self._buf.rfind("\n", 0, cut + 1))
            cut = boundary + 1 if boundary >= 0 else 0
        for s, e in self._spans(self._buf):
            if s < cut < e:
                cut = min(cut, s)
        if cut <= 0:
            return ""
        head, self._buf = self._buf[:cut], self._buf[cut:]
        return self._redact(head)

    def flush(self) -> str:
        head, self._buf = self._buf, ""
        return self._redact(head)

    def _redact(self, text: str) -> str:
        if not text:
            return ""
        out, n = redact_response(text, self.literals, allowed_literals=list(self.allowed))
        self.count += n
        return out
