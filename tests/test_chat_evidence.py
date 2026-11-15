"""Behavioral claims on the chat's review reads — which excerpts reach a prompt.

Each test seeds one game in a real store file: a published report, its
sample, and labels under the report's versions. The claims: an aspect is
read by its labels, in proportion and the same every time; words are read
through the keyword index, best match first; a review containing "spoiler"
is in neither read; and an aspect too few reviews mention is not read at
all.

The report is seeded with a direct insert, as the sheet shell's tests do,
since these reads use only its identity, its versions and its aggregate rows.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path

from steamlens.chat.evidence import aspect_excerpts, term_excerpts
from steamlens.chat.sheet import load_library
from steamlens.contracts import (
    AspectMention,
    AspectSlot,
    ClassifierVersions,
    LibraryGame,
    Origin,
    Provenance,
    Review,
    ReviewClassification,
    Sentiment,
)
from steamlens.store import Store, utc_isoformat

_NOW = datetime(2026, 11, 15, 12, 0, tzinfo=UTC)
_HADES = 1145360
_RUN = "serve-hades"
_VERSIONS = ClassifierVersions(model_version="labeler-b", prompt_version="p", ontology_version="v2")

# A labelled review: its id, its text, and its story mention as a sentiment
# and an evidence span, or ``None`` for a review with no story mention.
type Labelled = tuple[str, str, tuple[Sentiment, str | None] | None]


def _seed(path: Path, labelled: Sequence[Labelled]) -> None:
    """One published report for Hades whose sample holds ``labelled``."""
    with Store(path):
        pass
    mentions = sum(1 for _, _, story in labelled if story is not None)
    conn = sqlite3.connect(path)
    with conn:
        conn.execute(
            "INSERT INTO runs (run_id, code_version, created_at, config_hash)"
            " VALUES (?, 'abc1234', ?, 'cfg')",
            (_RUN, utc_isoformat(_NOW)),
        )
        conn.execute(
            "INSERT INTO reports (run_id, app_id, game_name, created_at, model_version,"
            " prompt_version, ontology_version, sample_size, take_all, windowed_windows,"
            " fallback_windows, skipped_windows, narrative_outcome, narrative_json,"
            " histogram_json, episodes_json, language_mix_json, marked_windows_json,"
            " fetch_windows_json) VALUES (?, ?, 'Hades', ?, 'labeler-b', 'p', 'v2', ?, 1, 1, 0,"
            " 0, 'withheld', '{}', '{}', '[]', '[]', '[]', '[]')",
            (_RUN, _HADES, utc_isoformat(_NOW), len(labelled)),
        )
        conn.execute(
            "INSERT INTO aggregate_snapshots (run_id, aspect, slot, reviews_with_aspect,"
            " positive, negative, mixed, neutral, sample_size)"
            " VALUES (?, 'story', 'pinned', ?, ?, 0, 0, 0, ?)",
            (_RUN, mentions, mentions, len(labelled)),
        )
    conn.close()
    stamp = Provenance(run_id=_RUN, code_version="abc1234", created_at=_NOW, config_hash="cfg")
    with Store(path) as store:
        store.reviews.put_many(
            Review(review_id, _HADES, _NOW, "english", text, True)
            for review_id, text, _ in labelled
        )
        store.sample_members.add_members(_RUN, [review_id for review_id, _, _ in labelled])
        for review_id, _, story in labelled:
            store.labels.put(
                ReviewClassification(
                    review_id=review_id, origin=Origin.SURVEY, versions=_VERSIONS, run=stamp,
                    mentions=() if story is None else (
                        AspectMention("story", AspectSlot.PINNED, story[0], story[1]),
                    ),
                )
            )


def _hades(store: Store) -> LibraryGame:
    (game,) = load_library(store)
    return game


def test_an_aspect_is_read_by_its_labels_as_the_sentence_around_each_span(
    tmp_path: Path,
) -> None:
    """Five labelled reviews, under the limit, so all are read. Each excerpt
    is the sentence holding the stored span and carries the label's
    sentiment; the review with no story mention is not among them."""
    path = tmp_path / "steamlens.sqlite3"
    _seed(path, [
        ("r1", "Runs well. The story is superb, start to finish! 10/10",
         (Sentiment.POSITIVE, "story is superb")),
        ("r2", "the story drags in act two", (Sentiment.NEGATIVE, "story drags")),
        ("r3", "great story", (Sentiment.POSITIVE, "great story")),
        ("r4", "loved the story\nhated the grind", (Sentiment.POSITIVE, "loved the story")),
        ("r5", "story was fine I guess", (Sentiment.MIXED, "story was fine")),
        ("r6", "tight combat and nothing else to say", None),
    ])
    with Store(path) as store:
        excerpts = aspect_excerpts(store, _hades(store), "story")
    assert [(e.review_id, e.text, e.sentiment) for e in excerpts] == [
        ("r1", "The story is superb, start to finish!", Sentiment.POSITIVE),
        ("r3", "great story", Sentiment.POSITIVE),
        ("r4", "loved the story", Sentiment.POSITIVE),
        ("r2", "the story drags in act two", Sentiment.NEGATIVE),
        ("r5", "story was fine I guess", Sentiment.MIXED),
    ]
    assert {e.app_id for e in excerpts} == {_HADES}


def test_a_larger_pool_is_drawn_in_proportion_and_the_same_on_every_read(
    tmp_path: Path,
) -> None:
    path = tmp_path / "steamlens.sqlite3"
    praising: list[Labelled] = [
        (f"p{n:02}", f"the story is lovely, take {n}", (Sentiment.POSITIVE, "story is lovely"))
        for n in range(20)
    ]
    critical: list[Labelled] = [
        (f"n{n:02}", f"the story is a mess, take {n}", (Sentiment.NEGATIVE, "story is a mess"))
        for n in range(10)
    ]
    _seed(path, praising + critical)
    with Store(path) as store:
        game = _hades(store)
        first = aspect_excerpts(store, game, "story")
        again = aspect_excerpts(store, game, "story")
    assert first == again
    assert [e.sentiment for e in first] == [Sentiment.POSITIVE] * 4 + [Sentiment.NEGATIVE] * 2


def test_a_review_containing_spoiler_is_in_neither_read(tmp_path: Path) -> None:
    """It is left out before anything is drawn or ranked, so it cannot take
    a place and cannot reach a prompt. A label with no evidence span has
    nothing to cut around and is not read either."""
    path = tmp_path / "steamlens.sqlite3"
    _seed(path, [
        ("r1", "SPOILER: the story ends with the father", (Sentiment.POSITIVE, "the story ends")),
        ("r2", "the story is superb", (Sentiment.POSITIVE, "story is superb")),
        ("r3", "story story story", (Sentiment.POSITIVE, None)),
        ("r4", "a fine story", (Sentiment.POSITIVE, "fine story")),
        ("r5", "the story, no spoilers, is good", (Sentiment.POSITIVE, "story")),
        ("r6", "what a story", (Sentiment.POSITIVE, "what a story")),
    ])
    with Store(path) as store:
        game = _hades(store)
        by_label = aspect_excerpts(store, game, "story")
        by_words = term_excerpts(store, game, ["story"])
    assert sorted(e.review_id for e in by_label) == ["r2", "r4", "r6"]
    assert sorted(e.review_id for e in by_words) == ["r2", "r3", "r4", "r6"]


def test_an_aspect_few_reviews_mention_is_not_read_by_label(tmp_path: Path) -> None:
    """Four reviews mention the story, one under the floor: at that count a
    label is too often about something else. An aspect no review mentions
    reads the same way. The words can still be searched."""
    path = tmp_path / "steamlens.sqlite3"
    _seed(path, [
        (f"r{n}", "the story is superb", (Sentiment.POSITIVE, "story is superb"))
        for n in range(4)
    ])
    with Store(path) as store:
        game = _hades(store)
        assert aspect_excerpts(store, game, "story") == ()
        assert aspect_excerpts(store, game, "music") == ()
        assert len(term_excerpts(store, game, ["story"])) == 4


def test_words_are_read_through_the_index_best_match_first_and_up_to_the_limit(
    tmp_path: Path,
) -> None:
    """An excerpt found by search is the sentence around the matched words
    and says nothing of sentiment. A game with no match reads as nothing."""
    path = tmp_path / "steamlens.sqlite3"
    _seed(path, [
        ("r1", "Fun for an hour. Then the Co-Op lobby broke! Refunded.", None),
        ("r2", "coop coop coop", None),
        ("r3", "single player only and proud of it", None),
        ("r4", "great co-op with my brother", None),
    ])
    with Store(path) as store:
        game = _hades(store)
        excerpts = term_excerpts(store, game, ["co-op", "coop"])
        assert term_excerpts(store, game, ["co-op", "coop"], limit=2) == excerpts[:2]
        assert term_excerpts(store, game, ["metroidvania"]) == ()
    assert {e.review_id: e.text for e in excerpts} == {
        "r1": "Then the Co-Op lobby broke!",
        "r2": "coop coop coop",
        "r4": "great co-op with my brother",
    }
    assert all(e.sentiment is None and e.app_id == _HADES for e in excerpts)
