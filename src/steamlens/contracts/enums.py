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


class ReferenceKind(StrEnum):
    """What kind of measuring stick an eval run was scored against.

    The eval-run journal pins every reference by content, but the pin's
    mechanics depend on the kind: a ``GOLD_FILE`` reference is a file on disk
    — the run's ``reference_id`` is its path and ``reference_sha256`` hashes
    its bytes; a ``POOL_LABELS`` reference is another annotator's stored label
    set — ``reference_id`` names its versions triple plus the sampled slice,
    and the hash is a digest of the canonically-serialized labels. Alongside
    the scorer identity, the kind also marks a row's epistemic weight: a
    gold-file run certifies against human truth, a pool-labels run measures
    two instruments agreeing — which can share blind spots.

    >>> ReferenceKind.GOLD_FILE == "gold-file"
    True
    """

    GOLD_FILE = "gold-file"
    POOL_LABELS = "pool-labels"


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


class IdentityVerdict(StrEnum):
    """What the identity guard concluded about a resolved game — recorded, never thrown.

    Steam resolves an ``app_id`` to whatever the store currently says it is, so
    the guard compares the returned name against the caller's expectation and
    records its conclusion in the ``GameRef`` instead of raising: a ``MISMATCH``
    is an honest answer about what Steam returned, not an error condition.
    ``NO_DATA`` means the store had nothing for the id at all (delisted or
    invalid) — distinct from a mismatch, because there was no name to compare.

    >>> IdentityVerdict.NO_DATA == "no-data"
    True
    """

    OK = "ok"
    MISMATCH = "mismatch"
    NO_DATA = "no-data"


class RollupUnit(StrEnum):
    """The bucket size of a histogram's rollup series — age-dependent, never assumed.

    Steam rolls a game's review histogram into months or weeks depending on the
    game's age (the smoke-test probes caught both on real games), so the unit is
    read from the response and carried on every ``HistogramSnapshot`` rather
    than hardcoded. The wire values match Steam's own ``rollup_type`` strings.
    """

    MONTH = "month"
    WEEK = "week"


class PathOutcome(StrEnum):
    """Which path a window fetch actually took — the per-window provenance verdict.

    The date-window request params are undocumented, so a window fetch can
    resolve three ways and the result says which: ``WINDOWED`` is the primary
    path (the window params held); ``FALLBACK_WALKED`` means the plain
    cursor walk was used instead, timestamp-gated to the window;
    ``SKIPPED_INFEASIBLE`` means the fallback's feasibility estimate found the
    walk too deep for the rate budget and the window was skipped — disclosed,
    never a silent hole in the data.

    >>> PathOutcome.FALLBACK_WALKED == "fallback-walked"
    True
    """

    WINDOWED = "windowed"
    FALLBACK_WALKED = "fallback-walked"
    SKIPPED_INFEASIBLE = "skipped-infeasible"


class SamplingPolicyKind(StrEnum):
    """Which runtime-expressible draw a sampling policy asks for.

    Steam's API offers no random access to reviews, so every policy the
    runtime can actually execute is one of two shapes: a windowed draw
    (date windows with per-window quotas — ``TIME_PROPORTIONAL`` spreads the
    budget by each window's review volume, ``EQUAL_PER_WINDOW`` gives every
    window the same share) or ``CURSOR_PREFIX`` (the documented cursor walk
    from the newest review — the fallback path as it actually behaves, a
    most-recent prefix). The sampling study (M2) races these against a
    uniform-random reference; that reference is deliberately NOT a member
    here, because it is not runtime-expressible — it lives in the study
    shell, never in a plan.

    >>> SamplingPolicyKind.TIME_PROPORTIONAL == "time-proportional"
    True
    """

    TIME_PROPORTIONAL = "time-proportional"
    EQUAL_PER_WINDOW = "equal-per-window"
    CURSOR_PREFIX = "cursor-prefix"


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
