"""Corpus access — the frozen local snapshot behind the same records as the live door.

M1's review supply is the frozen ``steam-reviews`` corpus on disk; this
package is its reader shell, sitting at rank 2 beside ``steam_client`` as the
offline stand-in for the live door (relocated from ``studies/local_corpus``
2026-07-28 — it was always a reader, not a study driver). The record parser
is the door's own ``review_from_raw``, imported never forked, so a corpus
review and a fetched review cross the same validated boundary into the
``Review`` contract.
"""

from steamlens.corpus.local import (
    EXCLUDED_APP_IDS,
    GameReadResult,
    corpus_review_files,
    has_content,
    read_reviews_file,
)

__all__ = [
    "EXCLUDED_APP_IDS",
    "GameReadResult",
    "corpus_review_files",
    "has_content",
    "read_reviews_file",
]
