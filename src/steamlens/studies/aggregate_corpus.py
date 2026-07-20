"""Mint the census aggregates — read the survey pool, fold, return the numbers.

C2's thin shell: it reads the survey-origin, version-pinned label pool through
the store, attaches each mention's game via the skinny ``app_id`` map, counts
each game's denominator over all its survey envelopes (empties included), and
hands both to ``core.aggregate``'s pure fold. It owns no counting logic of its
own — the store answers in rows, the core folds, this composes the two — and it
persists nothing: the aggregate table is a snapshot the first publishing
consumer (F1) freezes, not a cache this fold maintains (DESIGN C2, decision 5).

The version pin is the caller's, passed explicitly: the census is labeled under
ontology ``v2``, but the packaged default stays ``v1`` (gold's identity pin), so
a consumer of the pool names ``v2`` by hand rather than inheriting a default
that would silently fold the wrong vocabulary.
"""

from __future__ import annotations

import hashlib
from collections import Counter
from collections.abc import Mapping

from steamlens.contracts import AspectAggregate, ClassifierVersions
from steamlens.core.aggregate import MentionRow, aggregate
from steamlens.store.store import Store


def census_manifest_id(versions: ClassifierVersions, sample_sizes: Mapping[int, int]) -> str:
    """A deterministic id for one fold — the same survey pool folds to the same id.

    Derived from the versions triple and the per-game sample sizes (which games,
    how many reviews each — the sample's identity), so re-folding the identical
    census reproduces the id exactly: provenance by construction, not a wall
    clock. The human-facing prefix states the ontology, game count, and envelope
    total; the digest disambiguates. A timestamped run manifest belongs to the
    snapshot step F1 adds, not to the in-memory fold's identity.
    """
    canonical = "|".join(
        [versions.model_version, versions.prompt_version, versions.ontology_version]
        + [f"{app_id}:{size}" for app_id, size in sorted(sample_sizes.items())]
    )
    digest = hashlib.sha256(canonical.encode()).hexdigest()[:12]
    total = sum(sample_sizes.values())
    return f"census/{versions.ontology_version}/{len(sample_sizes)}g-{total}e/{digest}"


def mint_census_aggregates(
    store: Store, *, versions: ClassifierVersions
) -> tuple[AspectAggregate, ...]:
    """Fold the survey pool under ``versions`` into per-game aspect aggregates.

    Reads the skinny ``app_id`` map once, counts each game's survey-envelope
    denominator (empties included), then streams the survey mentions through the
    pure fold with their game attached. Returns the aggregates in memory; storing
    them is a later, deliberate step.
    """
    app_id_of = store.reviews.app_id_by_review()
    sample_sizes: Counter[int] = Counter(
        app_id_of[review_id]
        for review_id in store.labels.iter_survey_envelope_review_ids(versions)
    )
    manifest_id = census_manifest_id(versions, sample_sizes)
    rows = (
        MentionRow(
            app_id=app_id_of[review_id],
            review_id=review_id,
            aspect=aspect,
            slot=slot,
            sentiment=sentiment,
        )
        for review_id, aspect, slot, sentiment in store.labels.iter_survey_mentions(versions)
    )
    return aggregate(rows, sample_sizes, versions=versions, manifest_id=manifest_id)
