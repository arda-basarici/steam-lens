"""The submit gate — who may start a fresh, money-spending analysis today.

The spend-breaker design (DESIGN, Deployment M3): the public allowance is a
*count* of fresh jobs per UTC day, checked at admission — a count cannot be
burst past the way a settling dollar total can. Two counts stack (the
2026-08-10 re-ruling): each visitor IP has its own daily allowance (the
fairness cap — one curious visitor cannot drain the day for everyone), and
the pooled cap over all visitors remains the un-burstable outer wall that
bounds the hostile ceiling at pool × per-job budget. Behind both, the
ledger's settled spend is a silent refusal condition (the runaway-day
guard), and one in-flight job per visitor IP reads straight from queue
memory. The route owns the check *order* (attach → exempt → the four guards
here): a request for an already-live game attaches before any guard runs,
so re-clicks and shared curiosity stay free.

The gate holds policy only — every fact it consults arrives as an injected
callable (queue membership, the admission count, the settled spend), so its
tests are data-in → refusal-out and the store/queue never appear. Exemption
is the unlock cookie: a secret token in the box environment, compared
constant-time; the operator's jobs skip the abuse guards but keep the per-job
budget, which is a correctness guard, not an abuse guard. The client IP is
the *last* entry of ``X-Forwarded-For`` — the one the box's own proxy
appended, which a visitor's forged header cannot displace — or the socket
peer when no proxy fronts the app (dev). Uvicorn's proxy trust stays
deliberately unwidened.

``SearchLimiter`` is the same discipline pointed at ``/search`` (the audit's
ungated-search finding): the route spends no money but does spend the box's
one Steam politeness budget, so a scripted flood would get the box's IP
rate-limited and break search for everyone. A per-IP fixed-window cap stops
the loop while staying invisible to a human searching on submit.
"""

from __future__ import annotations

import secrets
import threading
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime

UNLOCK_COOKIE = "steamlens_unlock"

DAY_USED_MESSAGE = (
    "today's fresh analyses are all used — published reports stay open; "
    "new analyses return at midnight UTC"
)
IP_DAY_USED_MESSAGE = (
    "your connection's fresh analyses for today are all used — published "
    "reports stay open; your allowance returns at midnight UTC"
)
IN_FLIGHT_MESSAGE = (
    "an analysis from your connection is already in flight — one at a time; "
    "the slot frees up when it finishes"
)
SEARCH_LIMIT_MESSAGE = (
    "too many searches from your connection — the allowance resets "
    "each minute"
)


def _utc_now() -> datetime:
    return datetime.now(UTC)


def utc_day_start(moment: datetime) -> datetime:
    """Midnight UTC of ``moment``'s day — the spend day's opening instant.

    The day boundary is this app's accounting day, owned here in the serve
    layer: the provider is pay-per-token with no daily window to align with
    (the llm_client's ``daily_reset_utc_hour`` is a provider-quota concept
    and stays parked).
    """
    return moment.astimezone(UTC).replace(hour=0, minute=0, second=0, microsecond=0)


def client_ip(forwarded_for: str | None, socket_peer: str) -> str:
    """The visitor's IP: the proxy's own X-Forwarded-For entry, else the peer.

    The *last* comma-separated entry is the one the box's Caddy appended —
    its actual peer — so a visitor sending a pre-forged header cannot spoof
    it: their fabrications sit to the left. Absent the header (dev, no
    proxy), the socket peer is the visitor.
    """
    if forwarded_for:
        last = forwarded_for.rsplit(",", 1)[-1].strip()
        if last:
            return last
    return socket_peer


@dataclass(frozen=True, slots=True)
class SubmitGate:
    """The four admission guards over injected reads, plus the unlock check.

    ``refusal`` answers for a *fresh* job only — the caller has already taken
    the attach path for live games — and checks in this order: the visitor's
    in-flight slot, the visitor's own daily count, the day's pooled count,
    the day's settled spend. The personal guards run before the day-wide
    ones so the message explains *the visitor's* situation whenever both
    apply. ``admit`` journals an admission the moment a fresh job is
    actually minted; the recorded timestamp comes from the gate's own clock
    so tests steer the day. ``record_admission`` receives (ip, app_id, at);
    ``admitted_from_since`` receives (ip, since).
    """

    daily_job_limit: int
    per_ip_daily_job_limit: int
    daily_spend_backstop_usd: float
    has_live_from: Callable[[str], bool]
    admitted_since: Callable[[datetime], int]
    admitted_from_since: Callable[[str, datetime], int]
    spent_since: Callable[[datetime], float]
    record_admission: Callable[[str, int, datetime], None]
    admin_token: str | None = None
    # The refusal journal's write seam (kind, at) — the ops surface's "how
    # often does the breaker fire" read. None composes an unjournaled gate
    # (tests that only claim refusal policy); production always wires one.
    record_refusal: Callable[[str, datetime], None] | None = None
    now: Callable[[], datetime] = _utc_now

    def refusal(self, ip: str) -> str | None:
        """The refusal message for a fresh-job request from ``ip`` — None admits.

        A refusal journals which guard fired (``in_flight`` · ``ip_day_cap``
        · ``day_cap`` · ``backstop``) before returning its message — the two
        DAY_USED texts read identically to the visitor by design, so the
        journal's kind is the only place the backstop's firings stay
        distinguishable.
        """
        if self.has_live_from(ip):
            return self._refuse("in_flight", IN_FLIGHT_MESSAGE)
        day = utc_day_start(self.now())
        if self.admitted_from_since(ip, day) >= self.per_ip_daily_job_limit:
            return self._refuse("ip_day_cap", IP_DAY_USED_MESSAGE)
        if self.admitted_since(day) >= self.daily_job_limit:
            return self._refuse("day_cap", DAY_USED_MESSAGE)
        if self.spent_since(day) >= self.daily_spend_backstop_usd:
            return self._refuse("backstop", DAY_USED_MESSAGE)
        return None

    def _refuse(self, kind: str, message: str) -> str:
        if self.record_refusal is not None:
            self.record_refusal(kind, self.now())
        return message

    def admit(self, ip: str, app_id: int) -> None:
        """Journal one admitted fresh job against today's public allowance."""
        self.record_admission(ip, app_id, self.now())

    def is_exempt(self, cookie: str | None) -> bool:
        """Whether an unlock cookie exempts this request from the abuse guards.

        Constant-time compare against the configured token; no token
        configured means nobody is exempt — the route degrades safe. The
        ascii pre-check is load-bearing, not cosmetic: ``compare_digest``
        raises ``TypeError`` on a non-ascii str, so without it a garbage
        cookie would be a 500 instead of a failed unlock. (The configured
        token's own ascii-ness is the composition root's boot check.)
        """
        return (
            self.admin_token is not None
            and cookie is not None
            and cookie.isascii()
            and secrets.compare_digest(cookie, self.admin_token)
        )

    def unlock_ok(self, token: str) -> bool:
        """Whether ``token`` earns the unlock cookie (the ``/unlock`` route's check).

        Same ascii pre-check as ``is_exempt``, same reason — the token
        arrives off a public URL path.
        """
        return (
            self.admin_token is not None
            and token.isascii()
            and secrets.compare_digest(token, self.admin_token)
        )


class SearchLimiter:
    """A per-IP fixed-window cap on storefront searches — the politeness-budget guard.

    The window is the wall-clock minute: the whole state is one small dict of
    per-IP counts that clears as the minute rolls, so a flood from many
    distinct IPs cannot grow it without bound. Only *admitted* searches
    count — the cap bounds what reaches Steam, and a refused loop cannot
    deepen its own penalty. Refusals journal as kind ``"search"`` through the
    same seam as the submit gate's, so the ops page's refusal counts cover
    both guards without a new surface. The lock keeps counts exact under the
    route threadpool; the critical section is a dict touch, too brief to
    contend.
    """

    def __init__(
        self,
        per_minute: int,
        *,
        record_refusal: Callable[[str, datetime], None] | None = None,
        now: Callable[[], datetime] = _utc_now,
    ) -> None:
        self._per_minute = per_minute
        self._record_refusal = record_refusal
        self._now = now
        self._lock = threading.Lock()
        self._window: datetime | None = None
        self._counts: dict[str, int] = {}

    def refusal(self, ip: str) -> str | None:
        """The refusal message for a search from ``ip`` — None admits and counts it."""
        moment = self._now()
        window = moment.replace(second=0, microsecond=0)
        with self._lock:
            if window != self._window:
                self._window = window
                self._counts.clear()
            if self._counts.get(ip, 0) >= self._per_minute:
                if self._record_refusal is not None:
                    self._record_refusal("search", moment)
                return SEARCH_LIMIT_MESSAGE
            self._counts[ip] = self._counts.get(ip, 0) + 1
        return None
