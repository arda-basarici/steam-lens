"""The frozen-corpus reader — raw steam-reviews JSONL into usable ``Review`` records.

M1's review supply is the frozen ``steam-reviews`` corpus on disk, not the live
API — this module is the offline stand-in for the live door, doing the same job
the ``steam_client`` shell will do for fetched pages: source-specific parsing at
the boundary, so the ``Review`` contract never sees a Steam wire format. The
**usable filter** lives here too, because the census ruling defined the survey
pool at the reader's level: English reviews whose text survives the
Unicode-honest emptiness test, across the 49 usable games. What this filter
deliberately does NOT do is judge content — low-effort English reviews ("gud
game 10/10") pass through and get bought, because "no aspects" is the
classifier's own verdict and the zero-mention share is a measured quantity
(DESIGN's census-slice ruling), never a pre-filter's guess.

Counts are first-class output: each file read returns its drop arithmetic
(total / non-English / empty / usable) so the driver can narrate what was
excluded and assert the ruled census supply (135,260) before any money moves.
Failure discipline is trust-no-raw-data: a malformed line or a mistyped field
in a *usable* record fails loud naming the file, line, or review — the corpus
is frozen and was fully readable at the supply count, so damage means the
files changed, not that a row should be quietly skipped.
"""

from __future__ import annotations

import json
import unicodedata
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Final, cast

from steamlens.contracts import Review

EXCLUDED_APP_IDS: Final = frozenset({730})
"""App ids outside the usable-games set — excluded from every corpus walk.

CS2 (730) is the one member: its corpus slice holds only ~19 English reviews —
far too thin to stand as a game — and every downstream ruling (the ontology
ratification's 49-game evidence base, the census supply count) already counts
the corpus without it. The exclusion is by id, here, so "usable games" means
the same set in every consumer.
"""

_ENGLISH: Final = "english"


def has_content(text: str) -> bool:
    """Whether ``text`` survives the Unicode-honest emptiness test.

    Strips every Unicode category-C character (controls, format chars such as
    zero-width spaces) plus whitespace before judging — the gold draw's lesson:
    a review can render as blank while holding a screenful of invisible
    characters, and counting those as content would inflate the labelable pool.

    >>> has_content("gud game 10/10")
    True
    >>> has_content(" \\u200b\\u0001\\n ")
    False
    """
    stripped = "".join(
        ch for ch in text if not unicodedata.category(ch).startswith("C")
    ).strip()
    return bool(stripped)


@dataclass(frozen=True, slots=True)
class GameReadResult:
    """One corpus file's usable reviews plus its drop arithmetic.

    ``reviews`` is the usable slice in file order; the counts reconcile as
    ``total == non_english + empty + usable`` — ``empty`` counts English
    reviews that failed the content test, mirroring the supply count's
    accounting so the driver's narration adds up against the ruled census.
    """

    app_id: int
    reviews: tuple[Review, ...]
    total: int
    non_english: int
    empty: int

    @property
    def usable(self) -> int:
        """How many reviews survived both filters — ``len(reviews)``, named."""
        return len(self.reviews)


def review_from_raw(raw: Mapping[str, object], app_id: int) -> Review:
    """One raw Steam review record as its contract, validated at the boundary.

    ``app_id`` comes from the caller (the corpus keys files by app, not rows).
    Steam's epoch seconds become the timezone-aware ``created_at`` here — the
    contract never sees the raw number. Raises ``ValueError`` naming the field
    (and the review id once known) on a missing or mistyped field: the record
    was drawn from a frozen corpus, so a bad field is damage to investigate,
    never a row to skip.
    """
    review_id = raw.get("recommendationid")
    if not isinstance(review_id, str) or not review_id:
        raise ValueError(f"recommendationid is {review_id!r}, expected a non-empty string")
    language = raw.get("language")
    if not isinstance(language, str):
        raise ValueError(f"review {review_id}: language is {language!r}, expected a string")
    text = raw.get("review")
    if not isinstance(text, str):
        raise ValueError(f"review {review_id}: review text is {text!r}, expected a string")
    timestamp = raw.get("timestamp_created")
    if isinstance(timestamp, bool) or not isinstance(timestamp, int):
        raise ValueError(
            f"review {review_id}: timestamp_created is {timestamp!r}, expected an integer"
        )
    voted_up = raw.get("voted_up")
    if not isinstance(voted_up, bool):
        raise ValueError(f"review {review_id}: voted_up is {voted_up!r}, expected a boolean")
    return Review(
        review_id=review_id,
        app_id=app_id,
        created_at=datetime.fromtimestamp(timestamp, tz=UTC),
        language=language,
        text=text,
        voted_up=voted_up,
    )


def read_reviews_file(path: Path) -> GameReadResult:
    """Read one ``<app_id>_reviews.jsonl`` corpus file into its usable slice.

    Filter order matches the supply count that priced the census: language
    first (only ``english`` proceeds), then the Unicode-honest content test —
    so ``empty`` means "English but blank", and the counts reconcile against
    the ruled supply. A missing or null ``review`` field counts as blank
    rather than failing: the ruling's arithmetic already discarded such rows
    as unusable, and only usable records cross the validated boundary. Blank
    *lines* are a file-format artifact and are skipped uncounted. Raises
    ``ValueError`` on an undecodable line (naming file and line number) or a
    filename whose leading segment is not an app id.
    """
    app_id = _app_id_from_name(path)
    reviews: list[Review] = []
    total = non_english = empty = 0
    with path.open(encoding="utf-8") as lines:
        for line_number, line in enumerate(lines, start=1):
            if not line.strip():
                continue
            try:
                record = json.loads(line)
            except json.JSONDecodeError as exc:
                raise ValueError(
                    f"{path.name} line {line_number}: undecodable JSON: {exc}"
                ) from exc
            if not isinstance(record, dict):
                raise ValueError(
                    f"{path.name} line {line_number}: record is "
                    f"{type(record).__name__}, expected an object"
                )
            raw = cast(dict[str, object], record)
            total += 1
            if raw.get("language") != _ENGLISH:
                non_english += 1
                continue
            text = raw.get("review")
            if not isinstance(text, str) or not has_content(text):
                empty += 1
                continue
            reviews.append(review_from_raw(raw, app_id))
    return GameReadResult(
        app_id=app_id,
        reviews=tuple(reviews),
        total=total,
        non_english=non_english,
        empty=empty,
    )


def corpus_review_files(reviews_dir: Path) -> tuple[Path, ...]:
    """The usable-game review files under ``reviews_dir``, sorted by filename.

    Globs ``*_reviews.jsonl`` and drops the excluded app ids, so a walk over
    this list IS a walk over the usable games. Raises ``ValueError`` when the
    directory is missing or matches nothing — an empty corpus walk would let a
    driver "succeed" at ingesting nothing.
    """
    if not reviews_dir.is_dir():
        raise ValueError(f"corpus reviews directory does not exist: {reviews_dir}")
    files = tuple(
        path
        for path in sorted(reviews_dir.glob("*_reviews.jsonl"))
        if _app_id_from_name(path) not in EXCLUDED_APP_IDS
    )
    if not files:
        raise ValueError(f"no *_reviews.jsonl files under {reviews_dir}")
    return files


def _app_id_from_name(path: Path) -> int:
    """The app id a corpus filename carries, or ``ValueError`` if it carries none."""
    leading = path.name.split("_", 1)[0]
    if not leading.isdigit():
        raise ValueError(f"{path.name}: expected an '<app_id>_reviews.jsonl' corpus filename")
    return int(leading)
