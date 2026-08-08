"""Game-shape metrics for the long-tail stage-1 splits — the transfer-risk axes.

The corpus is ~50 popular games; the deployed app will be pointed at anything.
Stage 1 of the long-tail evidence (DESIGN, the study-design section) splits the
sweep's convergence results by game shape to measure whether the ruled size
rule holds across shapes or must condition on them. Three axes, computed at the
replication unit's grain — one value per (game, anchor) pool, because a
truncated pool has its own shape:

- **Population** — the anchor's pool size. Already carried on every
  measurement row (``pool_size``); no function here mints it.
- **Temporal spikiness** — ``peak_window_share``: the pool share of the
  busiest histogram bucket. Graduated to ``core.allowance`` (2026-08-08) when
  the regime it decides became a production display input; the split views
  import it from there.
- **Aspect concentration** — ``headline_aspect_count``: how many of the
  pool's aspects sit in the headline band (census share at or above the
  ruled floor, ``core.allowance.HEADLINE_SHARE_FLOOR``). The checkpoint
  located the windowed penalty almost entirely in that band, so "how much of
  this game's report is headline material" is the transfer-relevant
  concentration question, not a distribution-wide entropy.

The metrics deliberately take the study's existing artifacts as input — the
histogram ``corpus_histogram`` builds per anchored pool, and a reference-share
mapping in ``anchored_reference_shares``'s shape — so the split views compute
shapes from the run of record plus one corpus pass, never a re-sweep.
"""

from __future__ import annotations

from collections.abc import Mapping

from steamlens.core.allowance import HEADLINE_SHARE_FLOOR


def headline_aspect_count(
    reference_shares: Mapping[str, float], *, floor: float = HEADLINE_SHARE_FLOOR
) -> int:
    """How many aspects sit in the headline band — the concentration axis.

    Counts the shares at or above ``floor`` (inclusive, matching the band's
    "at or above 15%" ruling). The default floor is the checkpoint's; the
    parameter exists for sensitivity views, not for redefining the band.
    Raises on an empty mapping — a pool with no reference shares is a wiring
    bug upstream, never a zero-concentration game.
    """
    if not reference_shares:
        raise ValueError("no reference shares — a measured pool always has a truth to count")
    return sum(1 for share in reference_shares.values() if share >= floor)
