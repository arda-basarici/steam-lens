"""Behavioral claims on the submit gate — refusal policy as data-in → answer-out.

Every fact the gate consults arrives as an injected callable, so these tests
hold no queue and no store: a scripted world (who is in flight, how much the
day admitted and settled) and the policy's answer. The HTTP side — the check
order against attach, the 429 wire shape, the unlock cookie's round trip —
lives in test_serve_app; the admission journal's SQLite binding in test_store.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta, timezone

from steamlens.serve.gate import (
    DAY_USED_MESSAGE,
    IN_FLIGHT_MESSAGE,
    SubmitGate,
    client_ip,
    utc_day_start,
)

_NOON = datetime(2026, 8, 8, 12, 30, tzinfo=UTC)
_MIDNIGHT = datetime(2026, 8, 8, tzinfo=UTC)


class _World:
    """A scripted world for one gate: injected facts plus the admission record."""

    def __init__(
        self,
        *,
        live_ips: frozenset[str] = frozenset(),
        admitted_today: int = 0,
        settled_today: float = 0.0,
    ) -> None:
        self.live_ips = live_ips
        self.admitted_today = admitted_today
        self.settled_today = settled_today
        self.admissions: list[tuple[str, int, datetime]] = []
        self.since_seen: list[datetime] = []

    def gate(
        self,
        *,
        limit: int = 5,
        backstop: float = 1.0,
        admin_token: str | None = None,
    ) -> SubmitGate:
        def admitted_since(since: datetime) -> int:
            self.since_seen.append(since)
            return self.admitted_today

        def spent_since(since: datetime) -> float:
            self.since_seen.append(since)
            return self.settled_today

        return SubmitGate(
            daily_job_limit=limit,
            daily_spend_backstop_usd=backstop,
            has_live_from=lambda ip: ip in self.live_ips,
            admitted_since=admitted_since,
            spent_since=spent_since,
            record_admission=lambda ip, app_id, at: self.admissions.append(
                (ip, app_id, at)
            ),
            admin_token=admin_token,
            now=lambda: _NOON,
        )


def test_admits_under_all_limits_and_journals_with_the_gates_clock() -> None:
    """A quiet day admits, and the admission lands with the gate's own
    timestamp — the clock a test steers is the clock the journal gets."""
    world = _World()
    gate = world.gate()
    assert gate.refusal("203.0.113.7") is None
    gate.admit("203.0.113.7", 440)
    assert world.admissions == [("203.0.113.7", 440, _NOON)]


def test_a_visitor_with_a_job_in_flight_is_refused_before_any_day_math() -> None:
    """The in-flight refusal wins the order: a visitor mid-job gets the
    one-at-a-time message even on a day that is also exhausted — the message
    must explain *their* situation, not the day's."""
    world = _World(live_ips=frozenset({"203.0.113.7"}), admitted_today=99)
    gate = world.gate(limit=5)
    assert gate.refusal("203.0.113.7") == IN_FLIGHT_MESSAGE
    assert world.since_seen == [], "the day reads must not have run"
    assert gate.refusal("198.51.100.2") == DAY_USED_MESSAGE


def test_the_day_allowance_refuses_at_the_limit_exactly() -> None:
    world = _World(admitted_today=4)
    assert world.gate(limit=5).refusal("203.0.113.7") is None
    world.admitted_today = 5
    assert world.gate(limit=5).refusal("203.0.113.7") == DAY_USED_MESSAGE


def test_the_settled_spend_backstop_refuses_at_the_threshold() -> None:
    """The runaway-day guard: settled dollars at the backstop close the day
    even with admission slots left — and share the visitor-facing day text."""
    world = _World(admitted_today=1, settled_today=1.0)
    assert world.gate(limit=5, backstop=1.0).refusal("203.0.113.7") == DAY_USED_MESSAGE
    world.settled_today = 0.99
    assert world.gate(limit=5, backstop=1.0).refusal("203.0.113.7") is None


def test_the_day_reads_are_windowed_from_utc_midnight() -> None:
    """Both store reads receive midnight UTC of the gate's *now* — the spend
    day is this app's accounting day, nobody else's."""
    world = _World()
    world.gate().refusal("203.0.113.7")
    assert world.since_seen == [_MIDNIGHT, _MIDNIGHT]


def test_utc_day_start_windows_by_instant_not_wall_clock() -> None:
    """An offset timestamp's day is its UTC day: 01:30+03:00 is 22:30 UTC the
    *previous* day, so its day opens at the previous UTC midnight."""
    plus3 = timezone(timedelta(hours=3))
    early_local = datetime(2026, 8, 8, 1, 30, tzinfo=plus3)
    assert utc_day_start(early_local) == datetime(2026, 8, 7, tzinfo=UTC)
    assert utc_day_start(_NOON) == _MIDNIGHT


def test_exemption_requires_a_configured_token_and_an_exact_cookie() -> None:
    """No token configured → nobody is exempt and no unlock succeeds (the
    route degrades safe); with one, only the exact value passes either door."""
    unconfigured = _World().gate(admin_token=None)
    assert not unconfigured.is_exempt("anything")
    assert not unconfigured.unlock_ok("anything")

    configured = _World().gate(admin_token="sesame")
    assert configured.is_exempt("sesame")
    assert not configured.is_exempt("Sesame")
    assert not configured.is_exempt(None)
    assert configured.unlock_ok("sesame")
    assert not configured.unlock_ok("sesam")


def test_client_ip_takes_the_proxys_own_entry_never_the_forged_ones() -> None:
    """The last X-Forwarded-For entry is the proxy's truthful append — a
    visitor pre-loading the header cannot displace it; no header means no
    proxy, and the socket peer is the visitor."""
    assert client_ip(None, "172.18.0.2") == "172.18.0.2"
    assert client_ip("", "172.18.0.2") == "172.18.0.2"
    assert client_ip("203.0.113.7", "172.18.0.2") == "203.0.113.7"
    assert client_ip("9.9.9.9, 203.0.113.7", "172.18.0.2") == "203.0.113.7"
    assert client_ip("9.9.9.9,8.8.8.8,  203.0.113.7 ", "172.18.0.2") == "203.0.113.7"
