"""The provider registry — vendors as registered functions, one entry each.

A provider is not a class hierarchy; it is a small frozen bundle of three
callables, because the cache forces the split: a cache hit re-parses a stored
raw body without sending anything, so parsing must be callable apart from
sending, and the cache key is a hash of the built payload, so payload building
must be callable apart from both. State a vendor genuinely needs (an API key,
a base URL) binds by closure when its entry is constructed.

The module-level ``PROVIDERS`` dict is the default registry adapters register
into at import time; the client takes a registry as a constructor argument so
tests inject fakes without touching global state.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from steamlens.contracts import LlmResponse

type ProviderPayload = dict[str, object]
"""A built request body — plain JSON-serializable types only, because the
client hashes it (sorted-key JSON) into the cache key."""


class BuildPayload(Protocol):
    """Build the provider-specific request body for one completion call.

    Must be deterministic: the payload is hashed into the cache key, so any
    nondeterminism (timestamps, random ids) silently breaks caching. ``params``
    is the route's opaque provider-params block, passed through untranslated;
    ``max_output_tokens`` is the route's total generation ceiling (output plus
    thinking), which the implementation maps into the vendor's own syntax.
    """

    def __call__(
        self, *, model: str, prompt: str, max_output_tokens: int, params: dict[str, object]
    ) -> ProviderPayload:
        """The request body ``send`` will transmit for this call."""
        ...


class SendRequest(Protocol):
    """Transmit one built payload and return the raw response body, unparsed.

    Raises ``ProviderTransientError`` for retry-worthy failures (429, 5xx,
    timeouts); anything else propagates as permanent. Returns the body *raw*
    because that is what the cache stores — parsing is ``ParseResponse``'s job.
    """

    def __call__(self, *, model: str, payload: ProviderPayload) -> str:
        """The raw response body for ``payload``, exactly as the provider sent it."""
        ...


class ParseResponse(Protocol):
    """Normalize one raw response body into the contract record.

    Must be pure and deterministic — it re-runs over cached bodies on every
    cache hit, so consulting anything outside ``raw`` breaks hit/miss
    equivalence silently. This is where the vendor's finish-reason vocabulary
    maps into ``FinishReason`` and its usage fields into the required
    ``TokenUsage`` split (no thinking reported means an explicit 0).
    """

    def __call__(self, raw: str) -> LlmResponse:
        """The normalized response parsed out of ``raw``."""
        ...


@dataclass(frozen=True, slots=True)
class ProviderEntry:
    """One vendor's three doors, bundled under its registry name."""

    build_payload: BuildPayload
    send: SendRequest
    parse: ParseResponse


PROVIDERS: dict[str, ProviderEntry] = {}
"""The default registry. Adapters register at import time; the client snapshots
whichever registry it is constructed with."""


def register_provider(name: str, entry: ProviderEntry) -> None:
    """Register vendor ``name`` in the default registry; a name collision fails loud."""
    if name in PROVIDERS:
        raise ValueError(f"provider {name!r} is already registered")
    PROVIDERS[name] = entry
