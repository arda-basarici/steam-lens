"""Typed failures of the Steam door — what went wrong, said precisely.

The taxonomy mirrors the LLM door's split between transient and permanent
trouble, because the fix differs: ``SteamUnavailableError`` is the world
failing (network trouble or retryable statuses that outlived the bounded retry
loop — patience already ran out), while ``SteamResponseError`` is Steam
answering in a way retrying cannot improve — an unexpected status, or a 200
whose body isn't the JSON it claims to be. The latter is never retried: a
malformed answer at temperature zero of the web is the same malformed answer
again, and the fix is investigation, not repetition.
"""

from __future__ import annotations


class SteamClientError(Exception):
    """The family root — every failure the Steam door raises is catchable as this."""


class SteamUnavailableError(SteamClientError):
    """Transient trouble — network failures or retryable statuses (429/5xx) —
    survived the bounded retry loop. Raised only at exhaustion; a transient that
    a retry absorbed never surfaces."""


class SteamResponseError(SteamClientError):
    """Steam answered for keeps in a way we can't use: a non-retryable HTTP
    status, or a 200 whose body fails to parse as a JSON object. Never retried —
    this is the API misbehaving or our request being wrong, and either way the
    fix is an edit or an investigation, not patience. The message carries the
    URL and a body snippet."""
