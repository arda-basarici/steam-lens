"""In-memory bindings of the persistence protocols — B3's own response archive and ledger.

These are the implementations the client's commits run on; the durable SQLite
pair lands with the store and binds in the same constructor slots. Deliberately
not thread-safe on their own: the client serializes every archive and ledger
touch under its one lock, so implementations stay dumb — a discipline the
SQLite pair inherits. Lifetime is the process; a run that must never re-pay
bought responses across restarts needs the durable pair (the first
corpus-labeling run does).
"""

from __future__ import annotations

from datetime import datetime

from steamlens.contracts import SpendRecord


class InMemoryResponseArchive:
    """Dict-backed ``ResponseArchive`` — satisfies the protocol structurally."""

    def __init__(self) -> None:
        self._entries: dict[str, str] = {}

    def get(self, key: str) -> str | None:
        """The archived raw response body under ``key``, or None on a miss."""
        return self._entries.get(key)

    def put(self, key: str, raw_response: str) -> None:
        """Store ``raw_response`` under ``key``, replacing any previous value."""
        self._entries[key] = raw_response


class InMemorySpendLedger:
    """List-backed ``SpendLedger`` — the journal as a plain append-only list.

    ``records`` is deliberately public: this binding exists for tests and
    offline runs, and inspecting the journal *is* its point; the protocol the
    client sees stays the narrow query surface.
    """

    def __init__(self) -> None:
        self.records: list[SpendRecord] = []

    def append(self, entry: SpendRecord) -> None:
        """Journal one paid call."""
        self.records.append(entry)

    def request_count_since(self, model: str, since: datetime) -> int:
        """Calls made to ``model`` (the requested name) at or after ``since``."""
        return sum(1 for r in self.records if r.model == model and r.created_at >= since)

    def cost_since(self, since: datetime) -> float:
        """Total USD spent across all models at or after ``since``."""
        return sum(r.cost for r in self.records if r.created_at >= since)
