"""The offline study drivers — thin entry shells over the assembled pipeline.

M1's corpus-labeling driver (and later the sampling study) lives here: each
study composes the existing seams — the corpus reader, ``core/classify``,
``LlmClient``, ``Store`` — into one narrated run. Nothing in this package owns
domain logic; a study is orchestration plus config, which is what lets the same
seams serve the web runtime unchanged. Design record: the census-dispatch
decisions in DESIGN's labeling-engine section (settled 2026-07-19).
"""

from steamlens.studies.aggregate_corpus import census_manifest_id, mint_census_aggregates
from steamlens.studies.measure import (
    AspectMeasurement,
    IntervalReading,
    measure_draw,
    mention_shares,
)
from steamlens.studies.sample_corpus import (
    corpus_histogram,
    execute_plan,
    uniform_reference_draw,
)

__all__ = [
    "census_manifest_id",
    "mint_census_aggregates",
    "corpus_histogram",
    "execute_plan",
    "uniform_reference_draw",
    "AspectMeasurement",
    "IntervalReading",
    "measure_draw",
    "mention_shares",
]
