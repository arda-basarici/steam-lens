"""Behavioral claims on the fetch's pure half — how a want is read, and what the answer call gets.

How a want is read: an aspect by its label, a term by its phrases, a store
fact by the search words of its vocabulary entry, and a release year or a
want with no target not at all.

What the answer call gets: the candidates in the pick's order under their
titles, a line per want with the reading in words and no count; the three
ways a want can be without excerpts kept apart (nothing to read, cut by the
cap, read and empty counting as nothing to read); one identifier per
excerpt, unique across the turn; and the named game's side of a comparison
once, only when some candidate is read on that comparison and the library
holds the game.
"""

from __future__ import annotations

import dataclasses
from datetime import UTC, date, datetime

import pytest

from steamlens.contracts import (
    AspectTarget,
    CandidatesDecision,
    Excerpt,
    Feeling,
    Firmness,
    LibraryGame,
    MustStanding,
    NamedGame,
    NamedGameRole,
    NameMatch,
    PickCandidate,
    PlayerRequest,
    ReadState,
    ReleaseYearsTarget,
    RequestIntent,
    Sentiment,
    SentimentCounts,
    SheetCell,
    Stance,
    StoreFactTarget,
    StorefrontLabel,
    StorefrontMetadata,
    StorefrontTagCapture,
    TermTarget,
    Want,
    WantFinding,
    WantStatus,
)
from steamlens.core.material import (
    AspectRead,
    NamedSideRead,
    WordsRead,
    candidates_material,
    named_sides_to_read,
    review_read,
)
from steamlens.core.pick import ReadPlan, read_plan
from steamlens.core.sheet import read_sheet, sentiment_group
from steamlens.core.store_facts import store_fact

_READ = datetime(2026, 11, 14, tzinfo=UTC)
_ONLINE_COOP = 38
_PUZZLE = TermTarget(phrases=("puzzle", "puzzles"))
_FRANTIC = TermTarget(phrases=("frantic",))


def _music(positive: int, negative: int) -> SheetCell:
    counts = SentimentCounts(positive, negative, 0, 0)
    return SheetCell("music", positive + negative, 600, counts,
                     sentiment_group(counts, positive + negative))


def _game(app_id: int, *cells: SheetCell, online_coop: bool = False) -> LibraryGame:
    categories = (2, _ONLINE_COOP) if online_coop else (2,)
    return LibraryGame(
        app_id=app_id, name=f"Title {app_id}", run_id=f"serve-{app_id}", reported_at=_READ,
        sample_size=600, complete_count=False, labeler="m", cells=cells,
        storefront=StorefrontMetadata(
            app_id=app_id, genres=(StorefrontLabel(25, "Adventure"),),
            categories=tuple(StorefrontLabel(category, "") for category in categories),
            windows=True, mac=False, linux=False, release_date_text="Sep 17, 2020",
            release_date=date(2020, 9, 17), coming_soon=False,
            short_description=f"The store's words for {app_id}.", captured_at=_READ,
        ),
        tags=StorefrontTagCapture(app_id=app_id, tags=(), captured_at=_READ),
    )


def _excerpt(app_id: int, review_id: str, sentiment: Sentiment | None = None) -> Excerpt:
    return Excerpt(app_id, review_id, f"what {review_id} says", sentiment)


# "Online co-op (must), a puzzle game (want), nice music (nice-to-have)".
# 7004 lists online co-op and "puzzle" clusters in it; 7002 does not list it.
_LIBRARY = (_game(7002), _game(7004, _music(60, 5), online_coop=True))
_REQUEST = PlayerRequest(
    intent=RequestIntent.RECOMMEND,
    wants=(
        Want("online co-op", Firmness.MUST, Stance.WANTS, StoreFactTarget("online-co-op")),
        Want("a puzzle game", Firmness.WANT, Stance.WANTS, _PUZZLE),
        Want("nice music", Firmness.NICE_TO_HAVE, Stance.WANTS, AspectTarget("music")),
    ),
)
_SHEET = read_sheet(_REQUEST, _LIBRARY, {_PUZZLE: {7002: 90, 7004: 120}})
_DECISION = CandidatesDecision((PickCandidate(7004), PickCandidate(7002, (1,))))


def test_a_target_is_read_by_label_by_words_or_not_at_all() -> None:
    assert review_read(AspectTarget("music")) == AspectRead("music")
    assert review_read(_PUZZLE) == WordsRead(("puzzle", "puzzles"))
    assert review_read(StoreFactTarget("online-co-op")) == WordsRead(
        store_fact("online-co-op").search_words
    )
    assert review_read(ReleaseYearsTarget(first=2019, last=None)) is None
    assert review_read(None) is None


def test_candidates_come_in_the_picks_order_with_titles_and_a_line_per_want() -> None:
    """The plan reads 7004 on the puzzle words and the music, and 7002 on
    its failed must first. The music read came back empty, which is the
    same to a reply as having nothing to read."""
    plan = read_plan(_DECISION, _REQUEST, _SHEET)
    assert plan.pairs == ((7004, 1), (7004, 2), (7002, 0), (7002, 1), (7002, 2))
    material = candidates_material(
        _REQUEST, _SHEET, _DECISION, plan,
        {
            (7004, 1): (_excerpt(7004, "a1"), _excerpt(7004, "a2")),
            (7004, 2): (),
            (7002, 0): (_excerpt(7002, "b1"),),
            (7002, 1): (_excerpt(7002, "b2"),),
            (7002, 2): (_excerpt(7002, "b3", Sentiment.POSITIVE),),
        },
    )

    first, second = material.games
    assert (first.app_id, first.title, first.description, first.standing) == (
        7004, "Title 7004", "The store's words for 7004.", MustStanding.MEETS,
    )
    assert (second.app_id, second.standing) == (7002, MustStanding.CONFLICTS)

    assert [(want.status, want.finding, want.read) for want in first.wants] == [
        (WantStatus.MATCHES, WantFinding.LISTED, ReadState.NOTHING_TO_READ),
        (WantStatus.MATCHES, WantFinding.TERM_CLUSTERS, ReadState.READ),
        (WantStatus.MATCHES, WantFinding.ASPECT_GROUP, ReadState.NOTHING_TO_READ),
    ]
    assert [want.read for want in second.wants] == [ReadState.READ] * 3
    assert second.wants[0].status is WantStatus.FAILS

    cited = [
        (cited.identifier, cited.excerpt.review_id)
        for game in material.games for want in game.wants for cited in want.excerpts
    ]
    assert cited == [("e1", "a1"), ("e2", "a2"), ("e3", "b1"), ("e4", "b2"), ("e5", "b3")]


def test_no_count_reaches_the_answer_call() -> None:
    """The sheet holds 120 matching reviews for 7004. A want's line in the
    material carries the reading in words, so there is no number on it to
    state or to set beside another game's."""
    assert _SHEET.rows[0].readings[1].hits == 120
    material = candidates_material(
        _REQUEST, _SHEET, _DECISION, read_plan(_DECISION, _REQUEST, _SHEET), {}
    )
    for game in material.games:
        for want in game.wants:
            values = [
                getattr(want, field.name)
                for field in dataclasses.fields(want) if field.name != "excerpts"
            ]
            assert not any(isinstance(value, int) for value in values)


def test_a_pair_the_cap_cut_is_told_apart_from_one_with_nothing_to_read() -> None:
    """A game can have reviews on a want that the read budget did not reach.
    A reply may not treat that as the reviews saying nothing."""
    plan = ReadPlan(pairs=((7004, 1),), cut=((7004, 2), (7002, 1)))
    material = candidates_material(
        _REQUEST, _SHEET, _DECISION, plan, {(7004, 1): (_excerpt(7004, "a1"),)}
    )
    first, second = material.games
    assert [want.read for want in first.wants] == [
        ReadState.NOTHING_TO_READ, ReadState.READ, ReadState.CUT_BY_CAP,
    ]
    assert [want.read for want in second.wants] == [
        ReadState.NOTHING_TO_READ, ReadState.CUT_BY_CAP, ReadState.NOTHING_TO_READ,
    ]


def _relative_request(named: NamedGame) -> PlayerRequest:
    return PlayerRequest(
        intent=RequestIntent.RECOMMEND, named_games=(named,),
        wants=(
            Want("nice music", Firmness.WANT, Stance.WANTS, AspectTarget("music")),
            Want("less frantic", Firmness.WANT, Stance.AVOIDS, _FRANTIC, compared_to="that game"),
        ),
    )


def test_the_named_games_side_is_read_once_when_a_candidate_is_read_on_the_comparison() -> None:
    named = NamedGame("that game", 7002, NameMatch.EXACT, NamedGameRole.LIKE_THIS, Feeling.LIKED)
    request = _relative_request(named)
    sheet = read_sheet(request, _LIBRARY, {_FRANTIC: {7002: 4}})
    decision = CandidatesDecision((PickCandidate(7004),))
    plan = read_plan(decision, request, sheet)
    assert named_sides_to_read(request, plan) == ((1, 7002),)

    material = candidates_material(
        request, sheet, decision, plan,
        {(7004, 0): (_excerpt(7004, "a1"),), (7004, 1): (_excerpt(7004, "a2"),)},
        (NamedSideRead(1, _LIBRARY[0], (_excerpt(7002, "n1"), _excerpt(7002, "n2"))),),
    )
    (side,) = material.named_sides
    assert (side.want, side.app_id, side.title) == (1, 7002, "Title 7002")
    assert [cited.identifier for cited in side.excerpts] == ["e3", "e4"]
    relative = material.games[0].wants[1]
    assert relative.status is WantStatus.CANNOT_TELL
    assert relative.on_game is not None and relative.on_named_game is not None


def test_no_named_side_is_read_for_a_game_the_library_lacks_or_a_comparison_left_unread() -> None:
    unmeasured = NamedGame(
        "that game", None, NameMatch.NOT_IN_LIBRARY, NamedGameRole.LIKE_THIS, Feeling.LIKED
    )
    request = _relative_request(unmeasured)
    sheet = read_sheet(request, _LIBRARY, {_FRANTIC: {}})
    plan = read_plan(CandidatesDecision((PickCandidate(7004),)), request, sheet)
    assert (7004, 1) in plan.pairs
    assert named_sides_to_read(request, plan) == ()

    named = NamedGame("that game", 7002, NameMatch.EXACT, NamedGameRole.LIKE_THIS, Feeling.LIKED)
    unread = ReadPlan(pairs=((7004, 0),), cut=((7004, 1),))
    assert named_sides_to_read(_relative_request(named), unread) == ()


def test_material_is_put_together_against_the_sheet_the_decision_was_made_from() -> None:
    stray = CandidatesDecision((PickCandidate(9999),))
    with pytest.raises(ValueError, match="not a row of the sheet"):
        candidates_material(_REQUEST, _SHEET, stray, ReadPlan(pairs=()), {})
