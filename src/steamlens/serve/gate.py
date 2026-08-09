"""The submit gate — who may start a fresh, money-spending analysis today.

The spend-breaker design (DESIGN, Deployment M3): the public allowance is a
*count* of fresh jobs per UTC day, checked at admission — a count cannot be
burst past the way a settling dollar total can — with the ledger's settled
spend as a second, silent refusal condition (the runaway-day guard), and one
in-flight job per visitor IP read straight from queue memory. The route owns
the check *order* (attach → exempt → the three guards here): a request for an
already-live game attaches before any guard runs, so re-clicks and shared
curiosity stay free.

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
"""

from __future__ import annotations

import secrets
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime

UNLOCK_COOKIE = "steamlens_unlock"

DAY_USED_MESSAGE = (
    "today's fresh analyses are all used — published reports stay open; "
    "new analyses return at midnight UTC"
)
IN_FLIGHT_MESSAGE = (
    "an analysis from your connection is already in flight — one at a time; "
    "the slot frees up when it finishes"
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
    """The three admission guards over injected reads, plus the unlock check.

    ``refusal`` answers for a *fresh* job only — the caller has already taken
    the attach path for live games — and checks in this order: the visitor's
    in-flight slot, the day's admission count, the day's settled spend.
    ``admit`` journals an admission the moment a fresh job is actually
    minted; the recorded timestamp comes from the gate's own clock so tests
    steer the day. ``record_admission`` receives (ip, app_id, at).
    """

    daily_job_limit: int
    daily_spend_backstop_usd: float
    has_live_from: Callable[[str], bool]
    admitted_since: Callable[[datetime], int]
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

        A refusal journals which guard fired (``in_flight`` · ``day_cap`` ·
        ``backstop``) before returning its message — the two DAY_USED texts
        read identically to the visitor by design, so the journal's kind is
        the only place the backstop's firings stay distinguishable.
        """
        if self.has_live_from(ip):
            return self._refuse("in_flight", IN_FLIGHT_MESSAGE)
        day = utc_day_start(self.now())
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
        configured means nobody is exempt — the route degrades safe.
        """
        return (
            self.admin_token is not None
            and cookie is not None
            and secrets.compare_digest(cookie, self.admin_token)
        )

    def unlock_ok(self, token: str) -> bool:
        """Whether ``token`` earns the unlock cookie (the ``/unlock`` route's check)."""
        return self.admin_token is not None and secrets.compare_digest(
            token, self.admin_token
        )
