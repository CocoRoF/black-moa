"""Selection and health policy for the Claude Code account pool — pure functions only.

Everything here is a function of a snapshot: no DB, no filesystem, no clock of its own
(``now`` is always passed in). That is deliberate. The interesting part of a load balancer
is *why* it picked what it picked and when it takes a member out of rotation, and neither
is testable if it is tangled up with SQLAlchemy and a subprocess. ``services/claude_pool``
owns the state; this module owns the decisions.

The failure codes are the ones ``memora.providers.errors.classify`` already produces, so a
turn that fails is judged by exactly the same verdict the user-facing message came from.
"""
from __future__ import annotations

from dataclasses import dataclass, field

STRATEGIES = ("least_busy", "round_robin", "weighted", "least_recently_used")
DEFAULT_STRATEGY = "least_busy"

# A turn can fail for reasons that say nothing about the account that ran it. Counting a
# too-long conversation or a user pressing stop as an account failure is how a healthy
# pool talks itself into an outage.
NEUTRAL_CODES = frozenset({"context_limit", "cancelled", "credits_exhausted"})


@dataclass(frozen=True)
class AccountSnapshot:
    """What the balancer is allowed to know about one member of the pool."""

    id: str
    label: str = ""
    enabled: bool = True
    usable: bool = True          # holds a credential the CLI could actually use
    status: str = "ready"        # ready | expired | cooldown | error | unknown
    weight: int = 1
    max_concurrency: int = 4
    in_flight: int = 0
    cooldown_until: float = 0.0  # epoch seconds; 0 = not cooling down
    last_used: float = 0.0       # epoch seconds
    total_leases: int = 0
    consecutive_failures: int = 0

    @property
    def load(self) -> float:
        return self.in_flight / max(1, self.max_concurrency)


@dataclass
class BalancerState:
    """Mutable rotation state. One instance per process, owned by the pool service."""

    cursor: int = 0
    current_weights: dict[str, int] = field(default_factory=dict)

    def forget(self, account_id: str) -> None:
        self.current_weights.pop(account_id, None)


def ineligible_reason(a: AccountSnapshot, *, now: float) -> str | None:
    """Why this account cannot take a lease right now — ``None`` means it can.

    Returned as a string rather than a bool because the admin console shows it: "why is
    my second account never used" is the first question a pool raises.
    """
    if not a.enabled:
        return "disabled"
    if not a.usable:
        return "no_credentials"
    if a.status == "expired":
        return "expired"
    if a.cooldown_until and a.cooldown_until > now:
        return "cooling_down"
    if a.max_concurrency > 0 and a.in_flight >= a.max_concurrency:
        return "at_capacity"
    return None


def eligible(accounts: list[AccountSnapshot], *, now: float) -> list[AccountSnapshot]:
    return [a for a in accounts if ineligible_reason(a, now=now) is None]


def _round_robin(cands: list[AccountSnapshot], state: BalancerState) -> AccountSnapshot:
    order = sorted(cands, key=lambda a: a.id)
    idx = state.cursor % len(order)
    state.cursor = idx + 1
    return order[idx]


def _weighted(cands: list[AccountSnapshot], state: BalancerState) -> AccountSnapshot:
    """Smooth weighted round-robin (the nginx algorithm).

    Plain weighted random sends three requests to the same account often enough to matter
    on a pool of two; SWRR interleaves them (3:1 → A A B A rather than A A A B) and is
    deterministic, so the test can assert an exact sequence.
    """
    total = 0
    best: AccountSnapshot | None = None
    best_cw = 0
    for a in sorted(cands, key=lambda x: x.id):
        w = max(1, a.weight)
        total += w
        cw = state.current_weights.get(a.id, 0) + w
        state.current_weights[a.id] = cw
        if best is None or cw > best_cw:
            best, best_cw = a, cw
    assert best is not None
    state.current_weights[best.id] = best_cw - total
    return best


def _least_busy(cands: list[AccountSnapshot]) -> AccountSnapshot:
    # Load is a fraction of the account's own ceiling: an account allowed four concurrent
    # sessions with two running is busier than one allowed twelve with three.
    return min(cands, key=lambda a: (round(a.load, 6), a.total_leases, a.last_used, a.id))


def _least_recently_used(cands: list[AccountSnapshot]) -> AccountSnapshot:
    return min(cands, key=lambda a: (a.last_used, a.total_leases, a.id))


def over_capacity(accounts: list[AccountSnapshot], *, now: float) -> AccountSnapshot | None:
    """The least busy account whose *only* problem is that it is full.

    Capacity is a balancing hint — how work should be spread while there is a choice — not
    a reason to have no answer at all. An account that is signed in and healthy can take
    one more session; refusing the conversation instead is a worse outcome than a slightly
    uneven spread, and it is what an owner experiences as "my secretary stopped working".
    """
    full = [a for a in accounts if ineligible_reason(a, now=now) == "at_capacity"]
    return min(full, key=lambda a: (a.in_flight, a.id)) if full else None


def choose(accounts: list[AccountSnapshot], *, strategy: str = DEFAULT_STRATEGY, now: float,
           state: BalancerState | None = None) -> AccountSnapshot | None:
    """Pick one account, or ``None`` when every member is out of rotation."""
    cands = eligible(accounts, now=now)
    if not cands:
        return None
    st = state or BalancerState()
    if strategy == "round_robin":
        return _round_robin(cands, st)
    if strategy == "weighted":
        return _weighted(cands, st)
    if strategy == "least_recently_used":
        return _least_recently_used(cands)
    return _least_busy(cands)


@dataclass(frozen=True)
class HealthPolicy:
    failure_threshold: int = 3          # consecutive unexplained failures before a rest
    failure_cooldown_s: float = 120.0
    rate_limit_cooldown_s: float = 900.0
    quota_cooldown_s: float = 3600.0
    max_cooldown_s: float = 6 * 3600.0


@dataclass(frozen=True)
class HealthDecision:
    status: str
    consecutive_failures: int
    cooldown_until: float   # 0 clears any existing cooldown
    changed: bool
    note: str = ""


def apply_outcome(a: AccountSnapshot, *, ok: bool, code: str | None = None, now: float,
                  policy: HealthPolicy | None = None) -> HealthDecision:
    """The health state machine: one turn's verdict → this account's next state."""
    p = policy or HealthPolicy()
    if ok:
        changed = a.status != "ready" or a.consecutive_failures != 0 or bool(a.cooldown_until)
        return HealthDecision("ready", 0, 0.0, changed, "ok")
    if code in NEUTRAL_CODES:
        # Not the account's doing — leave its health exactly as it was.
        return HealthDecision(a.status, a.consecutive_failures, a.cooldown_until, False, f"neutral:{code}")
    fails = a.consecutive_failures + 1
    if code == "provider_auth":
        # A dead session is not something waiting fixes: it needs a human to log in again.
        return HealthDecision("expired", fails, 0.0, True, "auth")
    if code == "rate_limited":
        return HealthDecision("cooldown", fails, now + p.rate_limit_cooldown_s, True, "rate_limited")
    if code == "provider_quota":
        return HealthDecision("cooldown", fails, now + p.quota_cooldown_s, True, "quota")
    if code == "cli_not_found":
        return HealthDecision("error", fails, now + p.failure_cooldown_s, True, "cli_not_found")
    if fails >= p.failure_threshold:
        # Back off further each time it fails again straight after coming back.
        backoff = min(p.max_cooldown_s, p.failure_cooldown_s * (2 ** (fails - p.failure_threshold)))
        return HealthDecision("cooldown", fails, now + backoff, True, f"failures:{fails}")
    return HealthDecision(a.status if a.status != "ready" else "ready", fails, a.cooldown_until, True,
                          f"failures:{fails}")
