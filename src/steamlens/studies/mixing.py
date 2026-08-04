"""The mixing blend — contaminate a drawn sample with marked-window material.

The mixing experiment's one transform (step-9 design, ruled 2026-08-04):
**replacement at fixed n**. A mixed draw keeps the ruled sample size — the
certified plan draws the full sample, then a seeded random subset of
``round(share * n)`` members is swapped for marked-window reviews — because
contamination is the same-size sample a report would take with a fraction of
it being bomb material; adding instead of replacing would grow the sample and
entangle the contamination effect with a size effect.

Pure and deterministic, the study package's discipline: both inputs pass
through the canonical newest-first order before any seeded choice, so the
blend depends only on ``(sample, marked, share, seed)`` and never on the
caller's iteration order. The two seeded choices — which sample members leave,
which marked reviews enter — draw from one ``random.Random(seed)`` in a fixed
sequence. The replaced-count arithmetic rounds half away from zero
(``int(share * n + 0.5)``), documented because Python's built-in ``round``
would banker's-round exact halves and quietly zero out small-sample shares;
on the ruled grid at the ruled n every share lands on an integer anyway.
"""

from __future__ import annotations

import random
from collections.abc import Sequence

from steamlens.contracts import Review
from steamlens.studies.sample_corpus import newest_first


def contaminate(
    sample: Sequence[Review], marked: Sequence[Review], share: float, *, seed: int
) -> tuple[Review, ...]:
    """Swap a seeded random ``share`` of ``sample`` for members of ``marked``.

    Returns a same-size sample in canonical newest-first order with
    ``int(share * n + 0.5)`` members replaced by marked-window reviews drawn
    without replacement. ``share`` 0.0 returns the sample unchanged (in
    canonical order). Raises ``ValueError`` on an empty input, a duplicate id
    within either input, an id present in both (a marked pool overlapping the
    base sample means the blend would model a game contaminating itself —
    wiring, not contamination), a share outside ``[0.0, 1.0)``, a swap count
    that would replace the whole sample (nothing of the base game would
    remain to measure), or a marked pool too small to supply the swap.
    """
    if not sample:
        raise ValueError("cannot contaminate an empty sample")
    if not marked:
        raise ValueError("cannot contaminate from an empty marked pool")
    if not 0.0 <= share < 1.0:
        raise ValueError(f"share is {share} — a contamination share lives in [0.0, 1.0)")

    sample_ids = {review.review_id for review in sample}
    marked_ids = {review.review_id for review in marked}
    if len(sample_ids) != len(sample):
        raise ValueError("sample contains duplicate review ids — a draw never repeats a review")
    if len(marked_ids) != len(marked):
        raise ValueError("marked pool contains duplicate review ids")
    overlap = sample_ids & marked_ids
    if overlap:
        raise ValueError(
            f"{len(overlap)} review id(s) appear in both the sample and the marked pool "
            f"(first: {sorted(overlap)[:3]}) — a game cannot contaminate itself"
        )

    count = int(share * len(sample) + 0.5)
    if count >= len(sample):
        raise ValueError(
            f"share {share} of {len(sample)} would replace the whole sample — "
            "no base game left to measure"
        )
    if count > len(marked):
        raise ValueError(
            f"share {share} of {len(sample)} needs {count} marked reviews "
            f"but the pool holds {len(marked)}"
        )

    base = newest_first(sample)
    if count == 0:
        return tuple(base)

    rng = random.Random(seed)
    leaving = set(rng.sample(range(len(base)), count))
    entering = rng.sample(newest_first(marked), count)
    kept = [review for position, review in enumerate(base) if position not in leaving]
    return tuple(newest_first(kept + entering))
