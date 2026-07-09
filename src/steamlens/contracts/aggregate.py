"""The minted aspect number — the survey-only rollup a report actually displays.

An ``AspectAggregate`` is what the two-track wall exists to protect: a count
folded from survey-origin labels over one sample, under one set of versions. It
carries raw counts only — the evidence floor that greys out thinly-supported
aspects is a presentation rule applied at compose time, not baked into the
number, so the stored aggregate stays a faithful tally and the display policy can
change without recomputing.
"""

from __future__ import annotations

from dataclasses import dataclass

from steamlens.contracts.enums import AspectSlot
from steamlens.contracts.provenance import ClassifierVersions


@dataclass(frozen=True, slots=True)
class SentimentCounts:
    """The per-sentiment breakdown behind one aspect's total.

    Four counts — how many mentions of an aspect fell in each polarity. Kept as a
    named record rather than four loose fields on the aggregate so the breakdown
    reads as one quantity and stays hashable (all-``int``, deeply immutable). The
    total mentions is the sum; ``reviews_with_aspect`` on the aggregate is the
    distinct-review count, which differs when a review mentions an aspect twice.
    """

    positive: int
    negative: int
    mixed: int
    neutral: int


@dataclass(frozen=True, slots=True)
class AspectAggregate:
    """One aspect's rolled-up number over one survey sample.

    ``aspect`` and ``slot`` identify what was counted; ``reviews_with_aspect`` is
    the distinct reviews that mentioned it; ``counts`` is the per-sentiment
    breakdown; ``sample_size`` is the denominator — the reviews in the sample this
    was folded over. ``versions`` pins the label versions that were folded (only
    matching-version, survey-origin labels enter), and ``manifest_id`` ties the
    number back to the exact sample it came from. That manifest linkage stays
    loose until the sample source lands in a later milestone; the field is defined
    now so the shape is stable.
    """

    aspect: str
    slot: AspectSlot
    reviews_with_aspect: int
    counts: SentimentCounts
    sample_size: int
    versions: ClassifierVersions
    manifest_id: str
