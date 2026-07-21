"""The LLM-seam records — what crosses the one door to models, and the stores behind it.

Every model call goes through the single ``llm_client`` door, and these records
are its wire: a stage-keyed ``LlmRequest`` in, an ``LlmResponse`` out carrying
everything guards, ledger, and provenance consume. The accounting fields are
required here rather than reconstructed later because downstream can only record
what crosses the seam — a lesson the aspect-vocab probe paid for when unreported
thinking tokens put real cost at roughly eight times the sticker-price estimate.
The two protocols (``ResponseArchive``, ``SpendLedger``) follow the ``Sink``
precedent: defined at the contract layer, implemented in shells (in-memory
first, the durable SQLite pair with the store), bound at composition — the
client's logic never knows which implementation it holds.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

from steamlens.contracts.enums import FinishReason, LlmStage


@dataclass(frozen=True, slots=True)
class TokenUsage:
    """The token split of one model call — prompt, output, and thinking, never a lone total.

    Thinking tokens bill at the output rate and can dwarf the visible output,
    which is exactly how the probe's sticker-price estimate went ~8x wrong — a
    single total hides the component that dominates cost. All three fields are
    required: an adapter whose provider reports no thinking passes an explicit
    0, so the split can never be silently dropped.
    """

    prompt_tokens: int
    output_tokens: int
    thinking_tokens: int


@dataclass(frozen=True, slots=True)
class LlmRequest:
    """One stage-keyed completion request — the only thing a caller hands the door.

    ``stage`` keys the client's routing table; which provider, model, and params
    serve the call is config resolved inside the client, so retargeting a stage
    is a config edit, never a call-site sweep. ``prompt`` is the fully built
    text — prompt construction is core's job (classify's delimited data channel,
    for one), so by the time a request exists there is nothing left to template.
    """

    stage: LlmStage
    prompt: str


@dataclass(frozen=True, slots=True)
class LlmResponse:
    """What comes back through the door — the completion plus its full accounting.

    ``text`` is the completion the caller parses. The rest is the seam doing its
    recording duty: ``model_version`` is the provider-*reported* version that
    actually served the call (provenance pins what ran, not the alias the route
    dialed); ``finish_reason`` is the adapter-normalized outcome the truncation
    guard reads; ``usage`` is the required token split the ledger and the cost
    metrics consume.
    """

    text: str
    model_version: str
    finish_reason: FinishReason
    usage: TokenUsage


@dataclass(frozen=True, slots=True)
class SpendRecord:
    """One paid provider call, appended to the ledger at spend time.

    The record is the counter: daily-quota headroom and cost totals are derived
    by querying these rows, never trusted to an in-memory tally, so they survive
    restarts by construction. ``model`` is the name the route requested — quotas
    attach to it; ``model_version`` is what the provider reports actually served
    the call — provenance wants it; the two differ under preview aliases, which
    is why both ride along. ``cost`` is denominated in USD; ``created_at`` is
    timezone-aware.
    """

    created_at: datetime
    stage: LlmStage
    model: str
    model_version: str
    usage: TokenUsage
    cost: float


class ResponseArchive(Protocol):
    """The durable record of raw provider responses — content-addressed, never evicted.

    Keys are content hashes of the (request payload + model) pair, computed by
    the client; values are the *raw* provider response bodies. This is not a
    disposable cache: an LLM reply is unreproducible, and the archive is its
    only durable copy, so it is kept permanently (never pruned) as the system's
    provenance record. Re-pay-avoidance — a ``get`` hit lets a run resume
    without re-buying — is a free consequence of a permanent content-addressed
    store, not a second purpose. Keeping the raw body rather than the extracted
    text also keeps normalization re-runnable over bought labels without a
    second purchase. Concrete implementations live in shells and bind at
    composition, per the ``Sink`` precedent.
    """

    def get(self, key: str) -> str | None:
        """The archived raw response body under ``key``, or None on a miss."""
        ...

    def put(self, key: str, raw_response: str) -> None:
        """Store ``raw_response`` under ``key``, replacing any previous value."""
        ...


class SpendLedger(Protocol):
    """The append-only spend journal the client derives its quota and budget reads from.

    The ledger stores and aggregates; policy stays in the client — it computes
    the window that matters (a provider's daily reset, a run's start) and asks.
    Splitting the roles this way keeps the durable record dumb enough to be a
    table and the guards testable against an in-memory fake.
    """

    def append(self, entry: SpendRecord) -> None:
        """Journal one paid call. Append-only — a ledger entry is never revised."""
        ...

    def request_count_since(self, model: str, since: datetime) -> int:
        """Calls made to ``model`` (the requested name) at or after ``since`` — the quota read."""
        ...

    def cost_since(self, since: datetime) -> float:
        """Total USD spent across all models at or after ``since`` — the budget read."""
        ...
