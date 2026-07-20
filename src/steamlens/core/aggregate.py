"""The number mint — fold survey labels into per-game aspect aggregates.

This is C2's pure core: a single deterministic function that turns a stream of
already-selected mention rows into ``AspectAggregate`` records, one per
``(game, aspect, slot)``. It mints raw tallies and nothing else — no evidence
floor, no candidate merging, no version or origin filtering. Those are all
someone else's job by deliberate design: the floor is a compose-time display
rule (the contract keeps the stored number a faithful tally), candidate
consolidation is a downstream, human-gated step, and the survey/version filter
is a store-query concern. The fold *trusts its inputs*: callers pass only
survey-origin, version-matched rows and the versions to stamp, so the core stays
a small pure function testable as data-in / data-out.

Two inputs, not one, and the second is not redundant. ``mention_rows`` carries
the aspects found; ``game_sample_sizes`` carries each game's denominator —
including the ~46% of reviews that mentioned no aspect at all. Those empty
reviews leave no mention row, so the denominator genuinely cannot be recovered
from the mention stream; it must be counted separately and handed in. A game
present only in ``game_sample_sizes`` (every review empty) mints no aggregate,
which is correct — it has no aspect number — and the caller still holds its
denominator for zero-share questions.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Iterable, Mapping
from dataclasses import dataclass

from steamlens.contracts import (
    AspectAggregate,
    AspectSlot,
    ClassifierVersions,
    Sentiment,
    SentimentCounts,
)

_GroupKey = tuple[int, str, AspectSlot]


@dataclass(frozen=True, slots=True)
class MentionRow:
    """One survey mention, flattened to exactly what the fold counts.

    The lean unit the shell streams into ``aggregate``: a mention's game
    (``app_id``), its originating ``review_id`` (needed for the distinct-review
    count, nothing else), and the ``aspect``/``slot``/``sentiment`` that place and
    score it. It carries no evidence span — aggregation never reads one — so the
    store can project this cheaply without hydrating a full envelope, which is what
    keeps the census fold sub-second instead of paying a fat-table join per row.
    """

    app_id: int
    review_id: str
    aspect: str
    slot: AspectSlot
    sentiment: Sentiment


def aggregate(
    mention_rows: Iterable[MentionRow],
    game_sample_sizes: Mapping[int, int],
    *,
    versions: ClassifierVersions,
    manifest_id: str,
) -> tuple[AspectAggregate, ...]:
    """Fold mention rows into per-game aspect aggregates, deterministically ordered.

    Groups ``mention_rows`` by ``(app_id, aspect, slot)`` and mints one
    ``AspectAggregate`` per group, stamping ``versions`` and ``manifest_id`` onto
    every record. ``sample_size`` is read from ``game_sample_sizes`` (the game's
    full survey count, empties included); ``reviews_with_aspect`` is the distinct
    reviews in the group; ``counts`` is the per-sentiment tally. The sentiment
    total and the distinct-review count are accumulated independently, so the
    contract's "differs when a review mentions an aspect twice" case stays honest
    rather than assuming upstream collapse made them equal.

    Fails loud on two input inconsistencies rather than minting a wrong number: a
    mention whose ``app_id`` is absent from ``game_sample_sizes`` (the mention
    stream and the denominator map disagree on the game set), and a group whose
    distinct-review count exceeds its game's ``sample_size`` (a numerator larger
    than its denominator — mentions leaking in from outside the counted sample).

    Output is sorted by ``(app_id, slot, aspect)`` so the same inputs always
    produce the identical tuple, regardless of the row stream's order.
    """
    sentiments: dict[_GroupKey, Counter[Sentiment]] = {}
    review_ids: dict[_GroupKey, set[str]] = {}
    for row in mention_rows:
        if row.app_id not in game_sample_sizes:
            raise ValueError(
                f"mention for app_id {row.app_id} has no sample size — the mention "
                "stream and the sample-size map disagree on the surveyed game set"
            )
        key: _GroupKey = (row.app_id, row.aspect, row.slot)
        if key not in sentiments:
            sentiments[key] = Counter()
            review_ids[key] = set()
        sentiments[key][row.sentiment] += 1
        review_ids[key].add(row.review_id)

    aggregates: list[AspectAggregate] = []
    for (app_id, aspect, slot), tally in sentiments.items():
        reviews_with_aspect = len(review_ids[(app_id, aspect, slot)])
        sample_size = game_sample_sizes[app_id]
        if reviews_with_aspect > sample_size:
            raise ValueError(
                f"aspect {aspect!r} ({slot}) in app_id {app_id} has "
                f"{reviews_with_aspect} reviews but the game's sample size is "
                f"{sample_size} — mentions from outside the counted sample"
            )
        aggregates.append(
            AspectAggregate(
                app_id=app_id,
                aspect=aspect,
                slot=slot,
                reviews_with_aspect=reviews_with_aspect,
                counts=SentimentCounts(
                    positive=tally[Sentiment.POSITIVE],
                    negative=tally[Sentiment.NEGATIVE],
                    mixed=tally[Sentiment.MIXED],
                    neutral=tally[Sentiment.NEUTRAL],
                ),
                sample_size=sample_size,
                versions=versions,
                manifest_id=manifest_id,
            )
        )

    aggregates.sort(key=lambda a: (a.app_id, a.slot.value, a.aspect))
    return tuple(aggregates)
