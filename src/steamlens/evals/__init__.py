"""The eval harness — gold-set loading and the frozen bake-off metrics.

The import law's top stratum: ``evals`` may import anything, nothing imports
``evals`` — certification consumes the system, never the reverse. Current
surface: the validated gold loader (``load_gold``) and the pure scoring core
(``tally_review`` → ``score`` → ``bootstrap_ci``), per DESIGN's C0 bake-off
protocol + scorer-design entries (2026-07-17/18). The bake-off runner and the
comparison-table generator live in ``probes/`` — one-shot orchestration stays
out of the library.
"""

from steamlens.evals.gold import GoldMention, GoldRecord, load_gold
from steamlens.evals.scoring import (
    BakeoffScores,
    ConfidenceInterval,
    ReviewTally,
    bootstrap_ci,
    score,
    tally_review,
)

__all__ = [
    # gold
    "GoldMention",
    "GoldRecord",
    "load_gold",
    # scoring
    "ReviewTally",
    "BakeoffScores",
    "ConfidenceInterval",
    "tally_review",
    "score",
    "bootstrap_ci",
]
