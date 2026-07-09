"""The classification records — the aspect atom and the per-review envelope.

Classifying one review yields exactly one ``ReviewClassification`` — the
envelope — holding zero or more ``AspectMention`` atoms. The envelope over a flat
list of mentions is a deliberate call: nearly half of reviews yield no aspect at
all, and under a flat shape an empty result is indistinguishable from an
unprocessed one. Recording *that* a review was classified (with its versions and
run) separately from *what* it produced is what keeps resume/caching honest
(empty reviews aren't re-paid every run) and makes "46% yield zero aspects" a
statable denominator rather than a guess.
"""

from __future__ import annotations

from dataclasses import dataclass

from steamlens.contracts.enums import AspectSlot, Origin, Sentiment
from steamlens.contracts.provenance import ClassifierVersions, Provenance


@dataclass(frozen=True, slots=True)
class AspectMention:
    """One aspect surfaced in a review — the atom the numbers are built from.

    ``aspect`` is the label (canonical when ``slot`` is pinned, free-form when it
    is a candidate); ``slot`` says which; ``sentiment`` is this aspect's polarity,
    distinct from the review's overall ``voted_up``. ``evidence`` is an optional
    supporting span from the review text — encouraged but never required, because
    a mandatory quote pushes the model to fabricate one, which would poison the
    very fabricated-quote metric the evaluation harness measures. A ``None``
    evidence is an honest "no clean span," not a defect.
    """

    aspect: str
    slot: AspectSlot
    sentiment: Sentiment
    evidence: str | None = None


@dataclass(frozen=True, slots=True)
class ReviewClassification:
    """The per-review envelope — proof a review was classified, and what it yielded.

    ``review_id`` ties the envelope to its ``Review``; ``origin`` records which
    track it belongs to (survey folds into numbers, investigation never does);
    ``versions`` is the content-cache key the labels were computed under; ``run``
    is the run that produced them. ``mentions`` holds the aspects found — an empty
    tuple is a first-class result meaning "processed, found nothing," the exact
    state a flat mention list can't express. The envelope existing at all is the
    record that this review was seen, which is what makes resume and honest
    denominators possible.
    """

    review_id: str
    origin: Origin
    versions: ClassifierVersions
    run: Provenance
    mentions: tuple[AspectMention, ...] = ()
