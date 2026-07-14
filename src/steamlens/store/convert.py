"""Value conversion at the store's boundaries — one timestamp format, validated reads.

SQLite has no datetime type, so timestamps are stored as ISO-8601 text — and
the `since` queries compare that text. String order only equals chronological
order if every stored timestamp shares one offset and one precision, so writes
normalize to UTC at microsecond precision here, in exactly one place. A naive
datetime is rejected loud: guessing its zone would silently corrupt the
ordering guarantee every windowed query leans on.

Reads go the other way and trust nothing: a stored file is raw external data
(hand-edited, half-migrated, written by other code), so values re-enter the
contracts through the parsers below, which raise ``StoreDataError`` naming the
offending value instead of letting a corrupt row cross into the pipeline.
"""

from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum

from steamlens.store.errors import StoreDataError


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


def parse_utc_isoformat(text: str, *, context: str) -> datetime:
    """The timezone-aware datetime stored as ``text``; ``StoreDataError`` if it isn't one.

    ``context`` names the row for the error message — the read boundary's whole
    job is failing with enough to find the corruption.
    """
    try:
        moment = datetime.fromisoformat(text)
    except ValueError as exc:
        raise StoreDataError(f"{context}: unparseable timestamp {text!r}") from exc
    if moment.tzinfo is None:
        raise StoreDataError(f"{context}: naive timestamp {text!r} — the store only writes UTC")
    return moment


def parse_enum[E: StrEnum](enum_cls: type[E], value: str, *, context: str) -> E:
    """``value`` as a member of ``enum_cls``; ``StoreDataError`` if the vocabulary rejects it.

    The schema deliberately carries no CHECK constraints on enum columns (an
    enum addition must not be a migration), so this parser is where a stored
    label proves it still belongs to the closed vocabulary.
    """
    try:
        return enum_cls(value)
    except ValueError as exc:
        raise StoreDataError(
            f"{context}: {value!r} is not a valid {enum_cls.__name__}"
        ) from exc
