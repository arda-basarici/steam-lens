"""The fetch against a real store — the reads a recommendation turn's reply is written from.

Two games are seeded in a store file, each with a published report, its
sample and labels. The claims: every planned pair is read the way its target
calls for (an aspect by label, a term and a store fact's search words
through the keyword index); the named game's side of a comparison is read
once, from that game's reviews; what was read is journalled; and a pair the
cap leaves unread is journalled and marked as cut, not as empty.

The reports are seeded with a direct insert, as the evidence reads' tests
do, since the fetch uses only a report's identity, versions and aggregate
rows.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path

import pytest
from fakes import CollectingSink

from steamlens.chat.fetch import FETCH_STAGE, fetch_candidates
from steamlens.chat.sheet import load_library, sheet_for
from steamlens.contracts import (
    AspectMention,
    AspectSlot,
    AspectTarget,
    CandidatesDecision,
    CandidatesMaterial,
    ClassifierVersions,
    Feeling,
    Firmness,
    MetricEvent,
    NamedGame,
    NamedGameRole,
    NameMatch,
    Origin,
    PickCandidate,
    PlayerRequest,
    Provenance,
    ReadState,
    RequestIntent,
    Review,
    ReviewClassification,
    Sentiment,
    Stance,
    StoreFactTarget,
    TermTarget,
    Want,
)
from steamlens.store import Store, utc_isoformat

_NOW = datetime(2026, 11, 15, 12, 0, tzinfo=UTC)
_VERSIONS = ClassifierVersions(model_version="labeler-b", prompt_version="p", ontology_version="v2")
_CANDIDATE, _NAMED = 7001, 7002

# A review: its id, its text, and the evidence span of its positive story
# mention, or ``None`` when it has none.
type Seeded = tuple[str, str, str | None]

_CANDIDATE_REVIEWS: tuple[Seeded, ...] = (
    ("c1", "The story is superb. No grind at all, which I loved.", "story is superb"),
    ("c2", "great story, played it in co-op with my brother", "great story"),
    ("c3", "loved the story", "loved the story"),
    ("c4", "the story kept me up all night", "story kept me up"),
    ("c5", "a story worth the price", "story worth the price"),
    ("c6", "the late game is a grind", None),
)
_NAMED_REVIEWS: tuple[Seeded, ...] = (
    ("n1", "so much grind before anything happens", None),
    ("n2", "tight controls", None),
)


def _seed_game(path: Path, app_id: int, name: str, reviews: Sequence[Seeded]) -> None:
    """One published report for ``app_id`` whose sample holds ``reviews``."""
    run_id = f"serve-{app_id}"
    mentions = sum(1 for _, _, span in reviews if span is not None)
    conn = sqlite3.connect(path)
    with conn:
        conn.execute(
            "INSERT INTO runs (run_id, code_version, created_at, config_hash)"
            " VALUES (?, 'abc1234', ?, 'cfg')",
            (run_id, utc_isoformat(_NOW)),
        )
        conn.execute(
            "INSERT INTO reports (run_id, app_id, game_name, created_at, model_version,"
            " prompt_version, ontology_version, sample_size, take_all, windowed_windows,"
            " fallback_windows, skipped_windows, narrative_outcome, narrative_json,"
            " histogram_json, episodes_json, language_mix_json, marked_windows_json,"
            " fetch_windows_json) VALUES (?, ?, ?, ?, 'labeler-b', 'p', 'v2', ?, 1, 1, 0,"
            " 0, 'withheld', '{}', '{}', '[]', '[]', '[]', '[]')",
            (run_id, app_id, name, utc_isoformat(_NOW), len(reviews)),
        )
        if mentions:
            conn.execute(
                "INSERT INTO aggregate_snapshots (run_id, aspect, slot, reviews_with_aspect,"
                " positive, negative, mixed, neutral, sample_size)"
                " VALUES (?, 'story', 'pinned', ?, ?, 0, 0, 0, ?)",
                (run_id, mentions, mentions, len(reviews)),
            )
    conn.close()
    stamp = Provenance(run_id=run_id, code_version="abc1234", created_at=_NOW, config_hash="cfg")
    with Store(path) as store:
        store.reviews.put_many(
            Review(review_id, app_id, _NOW, "english", text, True) for review_id, text, _ in reviews
        )
        store.sample_members.add_members(run_id, [review_id for review_id, _, _ in reviews])
        for review_id, _, span in reviews:
            store.labels.put(
                ReviewClassification(
                    review_id=review_id, origin=Origin.SURVEY, versions=_VERSIONS, run=stamp,
                    mentions=() if span is None else (
                        AspectMention("story", AspectSlot.PINNED, Sentiment.POSITIVE, span),
                    ),
                )
            )


@pytest.fixture
def store_path(tmp_path: Path) -> Path:
    path = tmp_path / "steamlens.sqlite3"
    with Store(path):
        pass
    _seed_game(path, _CANDIDATE, "The Candidate", _CANDIDATE_REVIEWS)
    _seed_game(path, _NAMED, "The Named Game", _NAMED_REVIEWS)
    return path


# A good story (an aspect), less grind than the named game (a term, relative),
# and online co-op (a store fact; no store facts are seeded, so it cannot be
# told and its search words are read).
_REQUEST = PlayerRequest(
    intent=RequestIntent.RECOMMEND,
    named_games=(
        NamedGame("that game", _NAMED, NameMatch.EXACT, NamedGameRole.LIKE_THIS, Feeling.LIKED),
    ),
    wants=(
        Want("a good story", Firmness.WANT, Stance.WANTS, AspectTarget("story")),
        Want(
            "less grind", Firmness.WANT, Stance.AVOIDS, TermTarget(("grind", "grindy")),
            compared_to="that game",
        ),
        Want("online co-op", Firmness.MUST, Stance.WANTS, StoreFactTarget("online-co-op")),
    ),
)
_DECISION = CandidatesDecision((PickCandidate(_CANDIDATE),))


def _fetch(path: Path) -> tuple[CandidatesMaterial, dict[str, float]]:
    sink = CollectingSink()
    with Store(path) as store:
        sheet = sheet_for(store, _REQUEST)
        material = fetch_candidates(
            store, _REQUEST, sheet, _DECISION, load_library(store), sink
        )
    metrics = {
        event.name: event.value
        for event in sink.events
        if isinstance(event, MetricEvent) and event.stage == FETCH_STAGE
    }
    return material, metrics


def test_each_planned_pair_is_read_the_way_its_target_calls_for(store_path: Path) -> None:
    """The story by its labels, the grind by its words, and online co-op by
    the search words its store fact carries, which find the one review that
    says "co-op"."""
    material, metrics = _fetch(store_path)
    (game,) = material.games
    assert game.title == "The Candidate"
    story, grind, coop = game.wants

    assert story.read is ReadState.READ
    assert {cited.excerpt.review_id for cited in story.excerpts} == {"c1", "c2", "c3", "c4", "c5"}
    assert {cited.excerpt.sentiment for cited in story.excerpts} == {Sentiment.POSITIVE}

    assert grind.read is ReadState.READ
    assert {cited.excerpt.review_id for cited in grind.excerpts} == {"c1", "c6"}

    assert coop.read is ReadState.READ
    assert [cited.excerpt.review_id for cited in coop.excerpts] == ["c2"]

    identifiers = [
        cited.identifier
        for want in game.wants for cited in want.excerpts
    ] + [cited.identifier for side in material.named_sides for cited in side.excerpts]
    assert identifiers == [f"e{number}" for number in range(1, len(identifiers) + 1)]
    assert metrics == {"fetch_pairs_read": 3.0, "fetch_excerpts": float(len(identifiers))}


def test_the_named_games_side_of_a_comparison_is_read_from_its_own_reviews(
    store_path: Path,
) -> None:
    material, _ = _fetch(store_path)
    (side,) = material.named_sides
    assert (side.want, side.app_id, side.title) == (1, _NAMED, "The Named Game")
    assert [cited.excerpt.review_id for cited in side.excerpts] == ["n1"]
    assert {cited.excerpt.app_id for cited in side.excerpts} == {_NAMED}


def test_a_pair_the_cap_leaves_unread_is_journalled_and_marked_as_cut(
    store_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """With room for one pair, the must is read and the other two wants are
    cut. They have reviews, so they are not marked as having none, and the
    comparison that was not read brings no named side."""
    monkeypatch.setattr("steamlens.core.pick.MAX_READ_PAIRS", 1)
    material, metrics = _fetch(store_path)
    (game,) = material.games
    assert [want.read for want in game.wants] == [
        ReadState.CUT_BY_CAP, ReadState.CUT_BY_CAP, ReadState.READ,
    ]
    assert material.named_sides == ()
    assert metrics["fetch_pairs_cut"] == 2.0
    assert metrics["fetch_pairs_read"] == 1.0
