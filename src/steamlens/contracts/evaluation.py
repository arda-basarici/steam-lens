"""The eval-run records — a certification result that can name its every input.

An evaluation mints numbers that get cited for weeks (a report, a post, a
trend line), so the record's job is the regenerability set: everything needed
to reproduce the number to the digit rides with it — the scored pool's
versions triple, the pinned measuring stick (reference kind + id + content
hash), the bootstrap dial (seed, resamples), and the scorer's identity. The metric values themselves
are name-keyed rows rather than fixed fields because the metric family grows
with the harness (fabricated-quote rate, per-category judge agreement) and a
grown family must never mean reshaping the record of runs already minted.
"""

from __future__ import annotations

from dataclasses import dataclass

from steamlens.contracts.enums import ReferenceKind
from steamlens.contracts.provenance import ClassifierVersions, Provenance


@dataclass(frozen=True, slots=True)
class EvalMetric:
    """One named number from an eval run, with its interval when one was measured.

    ``metric`` is the harness's stable name for the quantity (``"f1"``,
    ``"zero_share_pred"``, later ``"judge_agreement/<category>"`` — the name
    carries any per-category grain). ``ci_low``/``ci_high`` bound the 95%
    bootstrap interval and are ``None`` together for point-only diagnostics —
    a missing interval means "not bootstrapped", never "interval of zero
    width".
    """

    metric: str
    value: float
    ci_low: float | None = None
    ci_high: float | None = None


@dataclass(frozen=True, slots=True)
class EvalRun:
    """One eval run: what was scored, against which reference, how — and the numbers.

    ``run`` is the universal run stamp (who computed this); ``versions`` names
    the label pool slice under judgment — the certified thing is the pool's
    labels, not a model in the abstract. ``ontology_content_hash`` pins the
    codebook bytes behind the triple's version label; ``reference_kind`` +
    ``reference_id`` + ``reference_sha256`` pin the measuring stick the same
    way (each kind's pin mechanics are the ``ReferenceKind`` docstring's),
    because references drift — gold's wording batches, a re-judged sample —
    and a number scored against yesterday's stick must say so.
    ``n_scored_reviews`` may be smaller than ``n_reference_reviews`` when the
    reference reaches outside the pool's scope (the CS2 case: gold predates
    the usable-pool ruling) — the narrowing is stored, not buried in prose.
    ``scorer`` names the scoring procedure's identity so a future change in
    pairing semantics can never silently mix with old rows.
    """

    run: Provenance
    versions: ClassifierVersions
    ontology_content_hash: str
    reference_kind: ReferenceKind
    reference_id: str
    reference_sha256: str
    n_reference_reviews: int
    n_scored_reviews: int
    seed: int
    n_resamples: int
    scorer: str
    metrics: tuple[EvalMetric, ...]
