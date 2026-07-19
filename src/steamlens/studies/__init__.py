"""The offline study drivers — thin entry shells over the assembled pipeline.

M1's corpus-labeling driver (and later the sampling study) lives here: each
study composes the existing seams — the local-corpus reader, ``core/classify``,
``LlmClient``, ``Store`` — into one narrated run. Nothing in this package owns
domain logic; a study is orchestration plus config, which is what lets the same
seams serve the web runtime unchanged. Design record: DESIGN.md's C1 labeling
driver entry (2026-07-19).
"""

from steamlens.studies.local_corpus import (
    EXCLUDED_APP_IDS,
    GameReadResult,
    corpus_review_files,
    has_content,
    read_reviews_file,
    review_from_raw,
)

__all__ = [
    "EXCLUDED_APP_IDS",
    "GameReadResult",
    "corpus_review_files",
    "has_content",
    "read_reviews_file",
    "review_from_raw",
]
