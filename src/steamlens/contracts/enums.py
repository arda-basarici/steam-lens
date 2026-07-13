"""The closed vocabularies shared across the contract set.

Every enum here is a ``StrEnum``: its members *are* strings, so they serialize
to a stable label with no lookup table, compare equal to that label, and read
plainly in logs and stored rows. The values are the wire format — renaming a
member is a data migration, not a cosmetic edit, which is exactly the discipline
a closed vocabulary should force.
"""

from __future__ import annotations

from enum import StrEnum


class Origin(StrEnum):
    """Which track a classification belongs to — the two-track wall, in one field.

    Every displayed number is folded from ``SURVEY`` labels drawn against the
    fixed survey sample; ``INVESTIGATION`` labels come from the event
    investigator's targeted window fetches and never enter an aggregate. The
    aggregation step folds ``SURVEY`` only, so this field is the load-bearing
    guard that keeps a story's evidence out of the numbers.

    >>> Origin.SURVEY == "survey"
    True
    """

    SURVEY = "survey"
    INVESTIGATION = "investigation"


class AspectSlot(StrEnum):
    """Whether a mentioned aspect is part of the pinned core or a free candidate.

    The ontology is hybrid: a ratified fixed core (``PINNED``) plus open
    extraction of anything the model surfaces beyond it (``CANDIDATE``). Only
    pinned aspects carry a stable definition and feed the gold-set instructions;
    candidates are the raw tail, kept for the next ontology revision.
    """

    PINNED = "pinned"
    CANDIDATE = "candidate"


class Sentiment(StrEnum):
    """The polarity of a single aspect mention — distinct from the review's overall vote.

    A review's ``voted_up`` and its per-aspect sentiment dissociate constantly
    ("refunded it, but the soundtrack is gorgeous"), so this is recorded per
    mention. ``NEUTRAL`` is a real, retained outcome: a factual aspect mention
    with no polarity ("it has cloud saves") is signal, and rejecting it would be
    silent data loss. ``MIXED`` is a single mention carrying both charges at
    once ("gorgeous art, but it stutters").
    """

    POSITIVE = "positive"
    NEGATIVE = "negative"
    MIXED = "mixed"
    NEUTRAL = "neutral"


class LlmStage(StrEnum):
    """Which pipeline job a model call serves — the routing key at the LLM door.

    Every model call carries its stage, and the client's routing table maps it
    to a provider, model, and params — so retargeting a stage (say, moving
    classification to a paid tier at the milestone-exit decision) is a config
    edit, never a code change. ``CLASSIFY`` labels survey reviews, ``JUDGE`` is
    the eval harness's calibrated judge, ``PHRASE`` writes report prose over the
    minted numbers, ``INVESTIGATE`` drives the event investigator. The set grows
    as stages land; a new member plus a route is the whole cost.

    >>> LlmStage.CLASSIFY == "classify"
    True
    """

    CLASSIFY = "classify"
    JUDGE = "judge"
    PHRASE = "phrase"
    INVESTIGATE = "investigate"


class FinishReason(StrEnum):
    """How a generation ended, normalized across providers — the truncation guard's read.

    Adapters map each provider's own vocabulary (Gemini's ``MAX_TOKENS``,
    another vendor's ``length``) into this closed set, so the client's guards
    are written once, provider-independent. ``STOP`` is a clean finish;
    ``LENGTH`` means the output was cut by the token ceiling — a truncated
    classification is never retried, because a temperature-0 call re-truncates
    identically; ``REFUSAL`` is the provider declining to complete (safety
    blocks and the like); ``OTHER`` is the honest bucket for anything an adapter
    cannot map — surfaced, never silently coerced to a known reason.

    >>> FinishReason.LENGTH == "length"
    True
    """

    STOP = "stop"
    LENGTH = "length"
    REFUSAL = "refusal"
    OTHER = "other"


class StageKind(StrEnum):
    """The kind of a stage-progress event carried over the narration sink.

    A running pipeline narrates itself as a sequence of stage events: a stage
    ``STARTED``, made ``PROGRESS``, reached ``DONE``, or hit a non-fatal ``WARN``
    (a degraded-but-continuing condition — a skipped window, a quota nudge). See
    the narration sink in ``telemetry`` for how these reach a console or an SSE
    stream.
    """

    STARTED = "started"
    PROGRESS = "progress"
    DONE = "done"
    WARN = "warn"
