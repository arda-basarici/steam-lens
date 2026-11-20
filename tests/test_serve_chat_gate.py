"""Behavioral claims on the turn gate — who may have the chat answer right now.

The claims: a message is refused when it is empty or over its length, with
a line a page can show; an address has one turn in flight, and its place
comes back when the turn is over; an address's day and everyone's day are
counted at admission and refuse at their limits, the personal guard
answering first; the day's settled spend refuses under the day's own line
and its own journal kind; the process takes only so many turns at once,
and a turn refused for that counts against nobody; the operator skips the
abuse guards and the day's count and still takes a place; the counts start
again at midnight UTC; and every refusal is journalled by kind.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from steamlens.serve.chat_gate import (
    CHAT_BUSY_MESSAGE,
    DAY_USED_MESSAGE,
    EMPTY_MESSAGE,
    IN_FLIGHT_MESSAGE,
    IP_DAY_USED_MESSAGE,
    TurnGate,
    TurnPass,
    message_refusal,
)

_NOON = datetime(2026, 11, 20, 12, 0, tzinfo=UTC)


class _World:
    """The gate's injected facts, steered by a test: the clock, the spend, the journal."""

    def __init__(self) -> None:
        self.moment = _NOON
        self.spent = 0.0
        self.refusals: list[str] = []

    def gate(
        self, *, daily: int = 300, per_ip: int = 60, in_flight: int = 4
    ) -> TurnGate:
        return TurnGate(
            daily_turn_limit=daily,
            per_ip_daily_turn_limit=per_ip,
            turns_in_flight=in_flight,
            daily_spend_backstop_usd=2.0,
            spent_since=lambda _since: self.spent,
            record_refusal=lambda kind, _at: self.refusals.append(kind),
            now=lambda: self.moment,
        )


def _turn(gate: TurnGate, ip: str, *, exempt: bool = False) -> TurnPass | str:
    """One whole turn: admitted and finished at once, or the refusal's line."""
    admitted = gate.admit(ip, exempt=exempt)
    if isinstance(admitted, TurnPass):
        gate.finish(admitted)
    return admitted


def test_a_message_is_refused_when_empty_or_over_its_length() -> None:
    assert message_refusal("", 1_000) == EMPTY_MESSAGE
    assert message_refusal(" \n\t", 1_000) == EMPTY_MESSAGE
    assert message_refusal("x" * 1_000, 1_000) is None
    too_long = message_refusal("x" * 1_001, 1_000)
    assert too_long is not None and "1,000" in too_long and "1,001" in too_long


def test_an_address_has_one_turn_in_flight_and_gets_its_place_back() -> None:
    world = _World()
    gate = world.gate()
    running = gate.admit("1.1.1.1", exempt=False)
    assert isinstance(running, TurnPass)
    assert gate.admit("1.1.1.1", exempt=False) == IN_FLIGHT_MESSAGE
    assert isinstance(gate.admit("2.2.2.2", exempt=False), TurnPass)
    gate.finish(running)
    assert isinstance(gate.admit("1.1.1.1", exempt=False), TurnPass)
    assert world.refusals == ["chat_in_flight"]


def test_an_address_is_refused_at_its_own_days_count_and_others_are_not() -> None:
    world = _World()
    gate = world.gate(per_ip=2)
    assert isinstance(_turn(gate, "1.1.1.1"), TurnPass)
    assert isinstance(_turn(gate, "1.1.1.1"), TurnPass)
    assert _turn(gate, "1.1.1.1") == IP_DAY_USED_MESSAGE
    assert isinstance(_turn(gate, "2.2.2.2"), TurnPass)
    assert world.refusals == ["chat_ip_day_cap"]


def test_everyones_day_refuses_at_its_count_and_the_personal_guard_answers_first() -> None:
    """With both used up, the visitor reads about their own allowance."""
    world = _World()
    gate = world.gate(daily=3, per_ip=2)
    _turn(gate, "1.1.1.1")
    _turn(gate, "1.1.1.1")
    _turn(gate, "2.2.2.2")
    assert _turn(gate, "3.3.3.3") == DAY_USED_MESSAGE
    assert _turn(gate, "1.1.1.1") == IP_DAY_USED_MESSAGE
    assert world.refusals == ["chat_day_cap", "chat_ip_day_cap"]


def test_the_days_settled_spend_refuses_under_the_days_line_and_its_own_kind() -> None:
    """The wall is the one the report flow reads. The visitor is told the
    same thing as for the count; which wall it was is the journal's."""
    world = _World()
    gate = world.gate()
    assert isinstance(_turn(gate, "1.1.1.1"), TurnPass)
    world.spent = 2.0
    assert _turn(gate, "1.1.1.1") == DAY_USED_MESSAGE
    assert world.refusals == ["chat_backstop"]


def test_the_process_takes_only_so_many_turns_and_a_busy_refusal_counts_against_nobody() -> None:
    world = _World()
    gate = world.gate(per_ip=1, in_flight=2)
    first = gate.admit("1.1.1.1", exempt=False)
    second = gate.admit("2.2.2.2", exempt=False)
    assert isinstance(first, TurnPass) and isinstance(second, TurnPass)
    assert gate.admit("3.3.3.3", exempt=False) == CHAT_BUSY_MESSAGE
    gate.finish(first)
    # Refused as busy a moment ago, so its one turn for the day is still unspent.
    assert isinstance(gate.admit("3.3.3.3", exempt=False), TurnPass)
    assert world.refusals == ["chat_busy"]


def test_the_operator_skips_the_abuse_guards_and_the_days_count() -> None:
    world = _World()
    gate = world.gate(daily=1, per_ip=1)
    world.spent = 5.0
    held = gate.admit("1.1.1.1", exempt=True)
    assert isinstance(held, TurnPass)
    assert isinstance(gate.admit("1.1.1.1", exempt=True), TurnPass)
    world.spent = 0.0
    # Neither operator turn used the day's one public turn.
    assert isinstance(gate.admit("2.2.2.2", exempt=False), TurnPass)
    assert world.refusals == []


def test_the_operator_still_takes_one_of_the_processs_places() -> None:
    """The limit on turns in flight protects the thread pool, so no cookie skips it."""
    world = _World()
    gate = world.gate(in_flight=1)
    held = gate.admit("1.1.1.1", exempt=True)
    assert isinstance(held, TurnPass)
    assert gate.admit("1.1.1.1", exempt=True) == CHAT_BUSY_MESSAGE
    assert gate.admit("2.2.2.2", exempt=False) == CHAT_BUSY_MESSAGE
    gate.finish(held)
    assert isinstance(gate.admit("2.2.2.2", exempt=False), TurnPass)


def test_the_counts_start_again_at_midnight_utc() -> None:
    world = _World()
    gate = world.gate(daily=1, per_ip=1)
    assert isinstance(_turn(gate, "1.1.1.1"), TurnPass)
    assert _turn(gate, "1.1.1.1") == IP_DAY_USED_MESSAGE
    world.moment = _NOON + timedelta(hours=12, seconds=1)
    assert isinstance(_turn(gate, "1.1.1.1"), TurnPass)
    assert _turn(gate, "2.2.2.2") == DAY_USED_MESSAGE
