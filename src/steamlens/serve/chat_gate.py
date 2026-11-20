"""The turn gate — who may have the chat answer a message right now.

A chat turn costs a fraction of a cent, and a script can ask for thousands,
so the chat is capped the way a fresh analysis is (DESIGN: the spend
breaker): counts taken at admission, since a count cannot be burst past the
way a settling dollar total can, and the day's settled spend as the wall
behind them. The dollar wall is the one the report flow reads, so the two
drain it together. A turn settles in the ledger within seconds, where a
report job settles over minutes, so the chat can pass it only by the turns
in flight at that moment.

The order is the breaker's: the visitor's own guards answer before the
day-wide ones, so a refusal explains the visitor's own situation whenever
both apply. One turn in flight per address, the address's day, everyone's
day, the day's spend. The last check is of another kind: at most a few
turns run at once in the whole process. They share the web server's thread
pool with every page and the health check, and that limit is what keeps a
burst of turns from making the pinger wait. The operator's unlock cookie
skips the abuse guards and not that one.

Counting happens once, when every check has passed, so a refused message
counts against nobody. The counts live in memory and a restart resets
them. That departs from the submit gate, whose admissions persist; the
spend wall reads the ledger and survives a restart, and the stored counts
come with the chat's own storage. Refusals are journalled by kind through
the same seam as the submit gate's.

``message_refusal`` is the check that needs no gate: a message is not
empty and within its length. It is this module's own code and not a rule
on the request model, whose refusal would be the framework's own shape and
no line a page can show.
"""

from __future__ import annotations

import threading
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Final

from steamlens.serve.gate import utc_day_start

EMPTY_MESSAGE: Final = "Write a message first."
IN_FLIGHT_MESSAGE: Final = (
    "One message at a time from your connection: wait for the reply to the last one."
)
IP_DAY_USED_MESSAGE: Final = (
    "Your connection has used today's chat allowance. It returns at midnight UTC."
)
DAY_USED_MESSAGE: Final = "Today's chat allowance is used. It returns at midnight UTC."
CHAT_BUSY_MESSAGE: Final = "The chat is busy right now. Try again in a moment."


def message_refusal(text: str, max_chars: int) -> str | None:
    """Why ``text`` cannot be taken as a message, or ``None`` when it can.

    >>> message_refusal("  ", 1000)
    'Write a message first.'
    >>> message_refusal("a calm game", 1000) is None
    True
    >>> message_refusal("x" * 1001, 1000)
    'A message can be up to 1,000 characters. Yours is 1,001.'
    """
    if not text.strip():
        return EMPTY_MESSAGE
    if len(text) > max_chars:
        return f"A message can be up to {max_chars:,} characters. Yours is {len(text):,}."
    return None


@dataclass(frozen=True, slots=True)
class TurnPass:
    """One admitted turn, handed back to the gate when the turn is over."""

    ip: str
    exempt: bool


def _utc_now() -> datetime:
    return datetime.now(UTC)


class TurnGate:
    """The chat's admission guards over one injected read, with their counts.

    ``admit`` answers a refusal line or a ``TurnPass``; the caller gives the
    pass to ``finish`` when the turn has ended, however it ended.
    ``spent_since`` is the ledger's settled spend since a moment, the same
    read the submit gate's backstop uses. ``record_refusal`` receives
    (kind, at); ``None`` composes an unjournaled gate for tests that only
    claim policy. ``now`` is injected so a test steers the day.

    An exempt turn skips the address's guards, the day's count and the
    spend wall, and is not counted in the day: the operator's turns spend
    and are no public admissions. It still takes one of the process's
    places.
    """

    def __init__(
        self,
        *,
        daily_turn_limit: int,
        per_ip_daily_turn_limit: int,
        turns_in_flight: int,
        daily_spend_backstop_usd: float,
        spent_since: Callable[[datetime], float],
        record_refusal: Callable[[str, datetime], None] | None = None,
        now: Callable[[], datetime] = _utc_now,
    ) -> None:
        self._daily_turn_limit = daily_turn_limit
        self._per_ip_daily_turn_limit = per_ip_daily_turn_limit
        self._turns_in_flight = turns_in_flight
        self._daily_spend_backstop_usd = daily_spend_backstop_usd
        self._spent_since = spent_since
        self._record_refusal = record_refusal
        self._now = now
        self._lock = threading.Lock()
        self._day: datetime | None = None
        self._admitted_today = 0
        self._admitted_today_by_ip: dict[str, int] = {}
        self._in_flight = 0
        self._in_flight_ips: set[str] = set()

    def admit(self, ip: str, *, exempt: bool) -> TurnPass | str:
        """Admit one turn from ``ip`` and count it, or answer the refusal's line.

        The lock makes check-and-count one step, so two requests cannot
        both pass a count that had room for one. The spend read is taken
        inside it, one indexed sum that only a request past every count
        reaches. A refusal is journalled after the lock is let go, so a
        flood of refused requests does not queue the admitted ones behind
        its writes.
        """
        moment = self._now()
        day = utc_day_start(moment)
        with self._lock:
            if day != self._day:
                self._day = day
                self._admitted_today = 0
                self._admitted_today_by_ip.clear()
            refusal = None if exempt else self._abuse_refusal(ip, day)
            if refusal is None and self._in_flight >= self._turns_in_flight:
                refusal = ("chat_busy", CHAT_BUSY_MESSAGE)
            if refusal is None:
                self._in_flight += 1
                if not exempt:
                    self._in_flight_ips.add(ip)
                    self._admitted_today += 1
                    self._admitted_today_by_ip[ip] = self._admitted_today_by_ip.get(ip, 0) + 1
        if refusal is None:
            return TurnPass(ip, exempt)
        kind, line = refusal
        if self._record_refusal is not None:
            self._record_refusal(kind, moment)
        return line

    def finish(self, admitted: TurnPass) -> None:
        """Give back the places an admitted turn held; its count for the day stays."""
        with self._lock:
            self._in_flight -= 1
            if not admitted.exempt:
                self._in_flight_ips.discard(admitted.ip)

    def _abuse_refusal(self, ip: str, day: datetime) -> tuple[str, str] | None:
        """The first abuse guard that refuses ``ip``, as (kind, line)."""
        if ip in self._in_flight_ips:
            return "chat_in_flight", IN_FLIGHT_MESSAGE
        if self._admitted_today_by_ip.get(ip, 0) >= self._per_ip_daily_turn_limit:
            return "chat_ip_day_cap", IP_DAY_USED_MESSAGE
        if self._admitted_today >= self._daily_turn_limit:
            return "chat_day_cap", DAY_USED_MESSAGE
        if self._spent_since(day) >= self._daily_spend_backstop_usd:
            # The same line as the day's count: which wall it was is the
            # journal's to tell, as with the submit gate.
            return "chat_backstop", DAY_USED_MESSAGE
        return None
