"""Value conversion at the store's write boundary — one timestamp format, enforced.

SQLite has no datetime type, so timestamps are stored as ISO-8601 text — and
the `since` queries compare that text. String order only equals chronological
order if every stored timestamp shares one offset and one precision, so writes
normalize to UTC at microsecond precision here, in exactly one place. A naive
datetime is rejected loud: guessing its zone would silently corrupt the
ordering guarantee every windowed query leans on.
"""

from __future__ import annotations

from datetime import UTC, datetime


def utc_isoformat(moment: datetime) -> str:
    """``moment`` as UTC ISO-8601 text, uniform to the microsecond.

    Rejects naive datetimes with ``ValueError`` — a naive value reaching the
    store is a caller bug (the contracts carry timezone-aware datetimes
    throughout), and interpreting it in any zone would break the
    string-order-is-time-order property the schema documents.

    >>> utc_isoformat(datetime(2026, 7, 14, 12, 30, tzinfo=UTC))
    '2026-07-14T12:30:00.000000+00:00'
    """
    if moment.tzinfo is None:
        raise ValueError(f"naive datetime crossing the store boundary: {moment!r}")
    return moment.astimezone(UTC).isoformat(timespec="microseconds")
