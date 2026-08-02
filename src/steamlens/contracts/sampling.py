"""The sampling-plan contracts — what the plan compiler promises its executors.

A ``FetchPlan`` is the one currency between the pure plan compiler
(``core/sampling``) and the two shells that execute plans: the live Steam door
at deployment and the corpus simulator in the sampling study (M2). The study
certifies whatever the compiler emits, so production must run the *same* plans
the study measured — one plan type, two executors, is what keeps the certified
policy and the shipped policy the same code (VISION names
policy-implemented-twice a fatal).

The within-window selection rule lives here, on the contract, for the same
reason: a window whose quota is smaller than its population must be subsampled
*identically* by both executors, or the study certifies a draw production never
performs. The rule is stated on ``PlannedWindow`` — newest-first, up to quota —
so a divergence would have to contradict the contract's own docstring rather
than drift in silently.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from steamlens.contracts.enums import SamplingPolicyKind


@dataclass(frozen=True, slots=True)
class SamplingPolicy:
    """One runtime sampling policy, fully specified: the draw shape and its budget.

    ``kind`` picks the draw (see ``SamplingPolicyKind``); ``target_size`` is how
    many reviews the policy wants in total. That pair is the entire policy
    surface by design — anything more (window placement, quota arithmetic) is
    the compiler's derivation from the histogram, not caller-tunable input, so
    two calls with the same policy and histogram cannot plan different draws.
    """

    kind: SamplingPolicyKind
    target_size: int


@dataclass(frozen=True, slots=True)
class PlannedWindow:
    """One date window of a fetch plan, with its quota and the rule for filling it.

    ``start``/``end`` bound the window (start-inclusive, end-exclusive,
    timezone-aware); ``quota`` is how many reviews to take from it. When the
    window holds more than ``quota``, the executor takes them **newest-first,
    in the API's return order, up to quota** — the one selection rule both the
    live door and the corpus simulator implement. This is the quota-prefix
    design (ruled 2026-08-02): its within-window recency bias is accepted
    *because the study measures it*; a take-all plan — every quota equal to
    its window's claimed volume — expresses the micro-window alternative with
    no new fields, so the fancier design stays reachable without a contract
    change.
    """

    start: datetime
    end: datetime
    quota: int


@dataclass(frozen=True, slots=True)
class FetchPlan:
    """A compiled sampling plan — the executable intent for one game's draw.

    ``windows`` is chronological and holds only quota-bearing windows; it is
    empty exactly when ``policy.kind`` is ``CURSOR_PREFIX``, whose draw ("walk
    from the newest review, take ``target_size``") needs no windows. The plan
    carries its provenance: ``policy`` is the spec it was compiled from, and
    ``histogram_fetched_at`` pins the snapshot whose claimed volumes shaped the
    quotas — histogram claims are Steam's, not ground truth, so a window may
    under-deliver at execution time; what the executor does then (disclosed
    shortfall, fallback) is the executor's contract, and the plan records what
    was *asked*.
    """

    app_id: int
    policy: SamplingPolicy
    windows: tuple[PlannedWindow, ...]
    histogram_fetched_at: datetime

    @property
    def planned_total(self) -> int:
        """How many reviews the plan asks for across all windows.

        For a cursor-prefix plan this is the policy's ``target_size`` (there
        are no windows to sum); for windowed plans it is the quota sum — which
        is *less* than ``target_size`` when the histogram's whole claimed
        supply is smaller than the ask, because a plan never requests reviews
        its own evidence says do not exist.
        """
        if self.policy.kind is SamplingPolicyKind.CURSOR_PREFIX:
            return self.policy.target_size
        return sum(window.quota for window in self.windows)
