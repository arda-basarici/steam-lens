"""Untrusted-wire narrowing — provider JSON read without trusting its shape.

Every adapter parses bodies the provider controls, so every field read is a
type claim that may not hold. These helpers make that narrowing explicit and
uniform across adapters: a value that is absent or of the wrong type reads as
the type's empty value rather than raising, because the fields they guard are
accounting and metadata — a missing token count must record as an explicit 0,
never kill a paid response. Structural failures that *do* invalidate a
response (a body that is not a JSON object at all) stay in the adapters,
which raise typed errors at that boundary.
"""

from __future__ import annotations

from typing import cast


def as_dict(value: object) -> dict[str, object]:
    """The value as a JSON object, or empty on any other shape.

    >>> as_dict({"a": 1})
    {'a': 1}
    >>> as_dict(None)
    {}
    """
    return cast(dict[str, object], value) if isinstance(value, dict) else {}


def as_list(value: object) -> list[object]:
    """The value as a JSON array, or empty on any other shape."""
    return cast(list[object], value) if isinstance(value, list) else []


def as_int(value: object) -> int:
    """The value as an integer, or 0 on any other shape.

    >>> as_int(42)
    42
    >>> as_int("42")
    0
    """
    return value if isinstance(value, int) else 0


def as_str(value: object) -> str:
    """The value as a string, or empty on any other shape (including JSON null)."""
    return value if isinstance(value, str) else ""
