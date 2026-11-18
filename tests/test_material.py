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

A turn about one game: each thing asked is read by its target, a store fact
whether or not the store lists it; a subject past the number a turn reads is
marked as cut; "would it suit me" brings the game's row on the standing
wants; and a question about the game in general, with no wants stated,
brings what its reviewers praise strongly and what they criticise.

A reply that offers nothing: the games left off the sheet on the player's
say reach it by title; and it gets how the library divides on each want as
presence with no count, the game named as "like this" not among the games
read, and wants met by different games told apart from a want no game
meets.
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
    LeftOut,
    LibraryGame,
    MustStanding,
    NamedGame,
    NamedGameRole,
    NameMatch,
    NothingFitsDecision,
    PickCandidate,
    PlayerRequest,
    ReadState,
    ReleaseYearsTarget,
    RequestIntent,
    Sentiment,
    SentimentCounts,
    SentimentGroup,
    SheetCell,
    Stance,
    StoreFactTarget,
    StorefrontLabel,
    StorefrontMetadata,
    StorefrontTagCapture,
    Subject,
    TermTarget,
    Want,
    WantFinding,
    WantStatus,
)
from steamlens.core.material import (
    MAX_SUBJECTS,
    AspectRead,
    NamedSideRead,
    StandingWantsRead,
    WordsRead,
    asks_for_an_overview,
    asks_whether_it_suits,
    candidates_material,
    left_out_games,
    named_sides_to_read,
    nothing_fits_material,
    one_game_material,
    review_read,
    subject_reading,
    subjects_to_read,
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
        left_out=LeftOut(),
    )

    first, second = material.games
    assert (first.app_id, first.title, first.description, first.standing) == (
        7004, "Title 7004", "The store's words for 7004.", MustStanding.MEETS,
    )
    assert (second.app_id, second.standing) == (7002, MustStanding.CONFLICTS)
    assert first.release_year == 2020

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
        _REQUEST, _SHEET, _DECISION, read_plan(_DECISION, _REQUEST, _SHEET), {},
        left_out=LeftOut(),
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
        _REQUEST, _SHEET, _DECISION, plan, {(7004, 1): (_excerpt(7004, "a1"),)},
        left_out=LeftOut(),
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
        left_out=LeftOut(),
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
        candidates_material(
            _REQUEST, _SHEET, stray, ReadPlan(pairs=()), {}, left_out=LeftOut()
        )


# --- what was left out, and a reply that offers nothing -------------------------


def test_the_games_left_off_the_sheet_reach_the_reply_by_title() -> None:
    """7002 was already played and 7004 was offered before the player asked
    for other games. Both are off the sheet, and a reply has to be able to
    say so."""
    played = NamedGame("that one", 7002, NameMatch.EXACT, NamedGameRole.NOT_THIS, Feeling.UNKNOWN)
    request = dataclasses.replace(_REQUEST, named_games=(played,), other_games=True)
    sheet = read_sheet(request, _LIBRARY, {_PUZZLE: {}}, offered=(7004,))
    assert sheet.rows == ()

    left_out = left_out_games(sheet, {7002: "Title 7002", 7004: "Title 7004"})
    assert left_out == LeftOut(already_played=("Title 7002",), earlier_offers=("Title 7004",))

    with pytest.raises(ValueError, match="do not hold it"):
        left_out_games(sheet, {7004: "Title 7004"})


def test_a_reply_that_offers_nothing_reads_how_the_library_divides_with_no_count() -> None:
    """Online co-op: one game lists it and one does not. The puzzle words
    cluster in both. Music: one game is praised for it, and the other has
    too few mentions to say."""
    material = nothing_fits_material(NothingFitsDecision((0,)), _SHEET, LeftOut())
    coop, puzzle, music = material.wants
    assert (coop.matched, coop.failed, coop.undecided) == (True, True, False)
    assert coop.findings == (WantFinding.LISTED, WantFinding.NOT_LISTED)
    assert (puzzle.matched, puzzle.failed, puzzle.undecided) == (True, False, False)
    assert (music.matched, music.failed, music.undecided) == (True, False, True)
    assert material.unmet == (0,)
    for line in material.wants:
        values = [getattr(line, field.name) for field in dataclasses.fields(line)]
        assert not any(type(value) is int for value in values)


def test_wants_met_by_different_games_are_told_apart_from_a_want_no_game_meets() -> None:
    """7004 has online co-op and 7002 does not; give 7002 the praised music
    and 7004 none. Each want is met by some game and no game meets both."""
    library = (_game(7002, _music(60, 5)), _game(7004, online_coop=True))
    request = dataclasses.replace(_REQUEST, wants=(_REQUEST.wants[0], _REQUEST.wants[2]))
    sheet = read_sheet(request, library, {})
    apart = nothing_fits_material(NothingFitsDecision((0, 1)), sheet, LeftOut())
    assert apart.met_only_apart

    one_want = nothing_fits_material(NothingFitsDecision((0,)), sheet, LeftOut())
    assert not one_want.met_only_apart

    with pytest.raises(ValueError, match="read against 2 wants"):
        nothing_fits_material(NothingFitsDecision((5,)), sheet, LeftOut())


def test_the_game_named_as_like_this_is_not_among_the_games_the_library_is_read_over() -> None:
    """Only 7004 lists online co-op, and the player named it as the kind of
    game they want. It is never offered, so "some game matches" would be
    true for a game the reply cannot give."""
    liked = NamedGame("that one", 7004, NameMatch.EXACT, NamedGameRole.LIKE_THIS, Feeling.LIKED)
    request = dataclasses.replace(_REQUEST, named_games=(liked,))
    sheet = read_sheet(request, _LIBRARY, {_PUZZLE: {7002: 90, 7004: 120}})
    assert any(row.like_this for row in sheet.rows)

    material = nothing_fits_material(NothingFitsDecision((0,)), sheet, LeftOut())
    assert not material.wants[0].matched
    assert material.wants[0].failed


# --- a turn about one game ----------------------------------------------------


def _cell(aspect: str, mentions: int, positive: int, negative: int) -> SheetCell:
    counts = SentimentCounts(positive, negative, mentions - positive - negative, 0)
    return SheetCell(aspect, mentions, 600, counts, sentiment_group(counts, mentions))


def _about(*subjects: Subject, wants: tuple[Want, ...] = ()) -> PlayerRequest:
    return PlayerRequest(intent=RequestIntent.ABOUT_GAME, wants=wants, subjects=subjects)


_ASKED = _LIBRARY[1]


def test_each_thing_asked_about_a_game_is_read_by_its_target() -> None:
    """The store lists online co-op for this game and the subject is read
    all the same: the player asked about it, and reviews say more than the
    listing. A release year has no reviews behind it, and the year itself
    is on the material."""
    request = _about(
        Subject("how is the music", AspectTarget("music")),
        Subject("does it have co-op", StoreFactTarget("online-co-op")),
        Subject("is it a puzzle game", _PUZZLE),
        Subject("is it recent", ReleaseYearsTarget(first=2019, last=None)),
    )
    assert subjects_to_read(request) == (0, 1, 2)
    readings = [subject_reading(subject, _ASKED, {_PUZZLE: {7004: 120}})
                for subject in request.subjects]
    material = one_game_material(
        request, _ASKED, readings,
        {0: (_excerpt(7004, "m1"),), 1: (_excerpt(7004, "c1"),),
         2: (_excerpt(7004, "p1"), _excerpt(7004, "p2"))},
    )

    assert (material.title, material.release_year) == ("Title 7004", 2020)
    assert [(s.words, s.finding, s.group, s.read) for s in material.subjects] == [
        ("how is the music", WantFinding.ASPECT_GROUP, SentimentGroup.STRONGLY_POSITIVE,
         ReadState.READ),
        ("does it have co-op", WantFinding.LISTED, None, ReadState.READ),
        ("is it a puzzle game", WantFinding.TERM_CLUSTERS, None, ReadState.READ),
        ("is it recent", WantFinding.RELEASED_IN_RANGE, None, ReadState.NOTHING_TO_READ),
    ]
    assert [cited.identifier for s in material.subjects for cited in s.excerpts] == [
        "e1", "e2", "e3", "e4",
    ]
    assert material.standing_wants is None and material.overview == ()


def test_a_subject_past_the_number_a_turn_reads_is_marked_as_cut() -> None:
    aspects = ("music", "story", "combat", "art_style", "controls")
    request = _about(*(Subject(f"how is the {a}", AspectTarget(a)) for a in aspects))
    assert subjects_to_read(request) == tuple(range(MAX_SUBJECTS))
    readings = [subject_reading(subject, _ASKED, {}) for subject in request.subjects]
    material = one_game_material(request, _ASKED, readings, {})
    assert [s.read for s in material.subjects] == [
        *[ReadState.NOTHING_TO_READ] * MAX_SUBJECTS, ReadState.CUT_BY_CAP,
    ]


def test_would_it_suit_me_reads_the_game_against_the_standing_wants() -> None:
    """An untargeted subject on a request with wants. 7002 fails the online
    co-op must, and its row comes with the conflict and the reviews on it,
    numbered after the subjects' excerpts."""
    request = _about(
        Subject("is it a puzzle game", _PUZZLE), Subject("would it suit me", None),
        wants=_REQUEST.wants,
    )
    assert asks_whether_it_suits(request) and not asks_for_an_overview(request)
    game = _LIBRARY[0]
    hits = {_PUZZLE: {7002: 90, 7004: 120}}
    sheet = read_sheet(request, _LIBRARY, hits)
    row = next(row for row in sheet.rows if row.game.app_id == 7002)
    plan = read_plan(CandidatesDecision((PickCandidate(7002),)), request, sheet)
    material = one_game_material(
        request, game, [subject_reading(subject, game, hits) for subject in request.subjects],
        {0: (_excerpt(7002, "p1"),)},
        StandingWantsRead(row, plan, {(7002, 0): (_excerpt(7002, "b1"),)}),
    )

    assert material.subjects[1].finding is WantFinding.NO_DATA
    assert material.subjects[1].read is ReadState.NOTHING_TO_READ
    standing = material.standing_wants
    assert standing is not None and standing.standing is MustStanding.CONFLICTS
    assert standing.wants[0].status is WantStatus.FAILS
    assert [cited.identifier for cited in standing.wants[0].excerpts] == ["e2"]


def test_a_question_about_the_game_in_general_gets_what_reviewers_praise_and_criticise() -> None:
    """Only from a player who has stated no wants. The strongly praised
    aspects come first, then the criticised and divided ones, each most
    mentioned first. An aspect that is only mostly positive is in neither."""
    cells = (
        _cell("music", 65, 60, 5), _cell("story", 200, 190, 10),
        _cell("bugs", 64, 4, 60), _cell("combat", 100, 50, 50), _cell("controls", 100, 62, 38),
    )
    assert [cell.group for cell in cells] == [
        SentimentGroup.STRONGLY_POSITIVE, SentimentGroup.STRONGLY_POSITIVE,
        SentimentGroup.CLEARLY_NEGATIVE, SentimentGroup.SPLIT, SentimentGroup.MOSTLY_POSITIVE,
    ]
    game = _game(7009, *cells)
    request = _about(Subject("tell me about it", None))
    assert asks_for_an_overview(request) and not asks_whether_it_suits(request)
    material = one_game_material(
        request, game, [subject_reading(request.subjects[0], game, {})], {}
    )
    assert [(standing.aspect, standing.group) for standing in material.overview] == [
        ("story", SentimentGroup.STRONGLY_POSITIVE),
        ("music", SentimentGroup.STRONGLY_POSITIVE),
        ("combat", SentimentGroup.SPLIT),
        ("bugs", SentimentGroup.CLEARLY_NEGATIVE),
    ]

    with_wants = _about(Subject("tell me about it", None), wants=_REQUEST.wants)
    readings = [subject_reading(with_wants.subjects[0], game, {})]
    assert one_game_material(with_wants, game, readings, {}).overview == ()


def test_a_turn_about_one_game_has_one_reading_per_subject() -> None:
    request = _about(Subject("how is the music", AspectTarget("music")))
    with pytest.raises(ValueError, match="one reading per subject"):
        one_game_material(request, _ASKED, [], {})
