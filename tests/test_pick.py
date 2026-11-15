"""Behavioral claims on what the pick call reads — the request and the sheet as text.

The claims: a game reaches the model with no title and no app id; the
standings come in order and the patterns inside one by a count that never
looks at firmness; the order inside a pattern is the caller's to set and
changes nothing else; a want relative to a named game shows no count on
either side; and the game the player named is marked as not a candidate.
"""

from __future__ import annotations

from datetime import UTC, date, datetime

from steamlens.contracts import (
    AspectTarget,
    Feeling,
    Firmness,
    LibraryGame,
    NamedGame,
    NamedGameRole,
    NameMatch,
    PlayerRequest,
    RequestIntent,
    SentimentCounts,
    SheetCell,
    Stance,
    StoreFactTarget,
    StorefrontLabel,
    StorefrontMetadata,
    StorefrontTagCapture,
    TermTarget,
    Want,
    WantTarget,
)
from steamlens.core.pick import pick_identifiers, render_pick_sheet, render_wants
from steamlens.core.sheet import read_sheet, sentiment_group

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
        app_id=app_id, name=f"Secret Title {app_id}", run_id=f"serve-{app_id}",
        reported_at=_READ, sample_size=600, complete_count=False, labeler="m", cells=cells,
        storefront=StorefrontMetadata(
            app_id=app_id, genres=(StorefrontLabel(25, "Adventure"), StorefrontLabel(23, "Indie")),
            categories=tuple(StorefrontLabel(category, "") for category in categories),
            windows=True, mac=False, linux=False, release_date_text="Sep 17, 2020",
            release_date=date(2020, 9, 17), coming_soon=False, short_description="",
            captured_at=_READ,
        ),
        tags=StorefrontTagCapture(app_id=app_id, tags=(), captured_at=_READ),
    )


def _want(
    words: str, target: WantTarget | None, firmness: Firmness,
    stance: Stance = Stance.WANTS, compared_to: str | None = None,
) -> Want:
    return Want(words, firmness, stance, target, compared_to=compared_to)


def _lines(text: str, prefix: str) -> list[str]:
    return [line for line in text.split("\n") if line.startswith(prefix)]


# Four games against "online co-op (must), a puzzle game (want), nice music
# (nice-to-have)". 7001 and 7004 list online co-op; "puzzle" clusters in 7002
# and 7004; the music is praised in 7001 and criticised in 7003.
_LIBRARY = (
    _game(7001, _music(60, 5), online_coop=True),
    _game(7002),
    _game(7003, _music(4, 60)),
    _game(7004, online_coop=True),
)
_REQUEST = PlayerRequest(
    intent=RequestIntent.RECOMMEND,
    wants=(
        _want("online co-op", StoreFactTarget("online-co-op"), Firmness.MUST),
        _want("a puzzle game", _PUZZLE, Firmness.WANT),
        _want("nice music", AspectTarget("music"), Firmness.NICE_TO_HAVE),
    ),
)
_HITS = {_PUZZLE: {7002: 90, 7004: 120, 7001: 2}}


def _render() -> str:
    return render_pick_sheet(_REQUEST, read_sheet(_REQUEST, _LIBRARY, _HITS))


def test_a_game_reaches_the_pick_call_with_no_title_and_no_app_id() -> None:
    """A pick has to come from the sheet and not from what a model remembers
    of a game, so nothing that names the game is rendered. The identifier is
    numbered in app-id order whatever the standing, and maps back."""
    sheet = read_sheet(_REQUEST, _LIBRARY, _HITS)
    text = render_pick_sheet(_REQUEST, sheet)
    assert "Secret Title" not in text
    assert not any(str(game.app_id) in text for game in _LIBRARY)
    assert pick_identifiers(sheet) == {7001: "g1", 7002: "g2", 7003: "g3", 7004: "g4"}
    assert len(_lines(text, "g")) == 4
    assert "g2 | Adventure, Indie | 2020 | " in text


def test_standings_come_in_order_and_patterns_by_fails_then_matches() -> None:
    """The count is plain: a matched nice-to-have counts like a matched want,
    so 7004 (the store fact and the term) and 7001 (the store fact and the
    music) are level, and only the fixed tie order puts one first. Among the
    conflicts 7002 (one fail, one match) leads 7003 (two fails)."""
    text = _render()
    assert _lines(text, "==") == [
        "== Meets every must (2 games)",
        "== Conflicts with a must (2 games)",
    ]
    assert _lines(text, "--") == [
        "-- w1 matches, w2 matches, w3 cannot tell (1 game)",
        "-- w1 matches, w2 cannot tell, w3 matches (1 game)",
        "-- w1 fails, w2 matches, w3 cannot tell (1 game)",
        "-- w1 fails, w2 cannot tell, w3 fails (1 game)",
    ]
    assert [line.split(" | ")[0] for line in _lines(text, "g")] == ["g4", "g1", "g2", "g3"]


def test_a_line_says_what_was_found_and_leaves_the_status_to_the_heading() -> None:
    text = _render()
    assert (
        "g4 | Adventure, Indie | 2020 | the store lists it; 120 of 600 reviews use the words,"
        " a cluster; too few reviews mention it"
    ) in text
    assert (
        "g3 | Adventure, Indie | 2020 | the store does not list it; no review uses the words;"
        " mostly criticised"
    ) in text
    assert (
        "g1 | Adventure, Indie | 2020 | the store lists it; 2 of 600 reviews use the words,"
        " too few to count; strongly positive"
    ) in text


def test_the_order_inside_a_pattern_is_the_callers_and_moves_nothing_else() -> None:
    """Two games share a pattern here. Reversing the inner order swaps their
    lines and leaves every heading and identifier where it was."""
    library = (_game(7001), _game(7002), _game(7003, online_coop=True))
    request = PlayerRequest(
        intent=RequestIntent.RECOMMEND,
        wants=(_want("online co-op", StoreFactTarget("online-co-op"), Firmness.MUST),),
    )
    sheet = read_sheet(request, library, {})
    forward = render_pick_sheet(request, sheet)
    backward = render_pick_sheet(request, sheet, inner_order=lambda row: -row.game.app_id)

    def identifiers(text: str) -> list[str]:
        return [line.split(" | ")[0] for line in _lines(text, "g")]

    assert identifiers(forward) == ["g3", "g1", "g2"]
    assert identifiers(backward) == ["g3", "g2", "g1"]
    assert _lines(forward, "==") + _lines(forward, "--") == (
        _lines(backward, "==") + _lines(backward, "--")
    )


def test_a_relative_want_shows_no_count_and_says_the_named_side_once() -> None:
    """ "Less frantic than <a game>": the named game's side is the same for
    every row, so it stands in one note. A game's line says what its own
    reviews show, in words. The game the player named stays, marked."""
    named = NamedGame("that game", 7001, NameMatch.EXACT, NamedGameRole.LIKE_THIS, Feeling.LIKED)
    request = PlayerRequest(
        intent=RequestIntent.RECOMMEND,
        named_games=(named,),
        wants=(
            _want("less frantic", _FRANTIC, Firmness.MUST, Stance.AVOIDS, "that game"),
        ),
    )
    sheet = read_sheet(request, (_game(7001), _game(7002)), {_FRANTIC: {7001: 4, 7002: 80}})
    text = render_pick_sheet(request, sheet)

    assert _lines(text, "w1: ") == [
        "w1: relative to the named game, whose own reviews show: a few reviews use the words;"
        " no verdict is given, and each line says what this game's reviews show",
    ]
    assert " 80 " not in text and " 4 " not in text
    assert _lines(text, "--") == ["-- w1 cannot tell (2 games)"]
    assert _lines(text, "g") == [
        "g1 | Adventure, Indie | 2020 | a few reviews use the words"
        ' | the game the player named as "like this": never a candidate',
        "g2 | Adventure, Indie | 2020 | the words cluster in its reviews",
    ]
    assert 'relative to "that game"' in render_wants(request)


def test_a_request_with_no_wants_lists_every_game_by_its_store_facts_alone() -> None:
    request = PlayerRequest(intent=RequestIntent.RECOMMEND)
    text = render_pick_sheet(request, read_sheet(request, _LIBRARY, {}))
    assert _lines(text, "==") == ["== Meets every must (4 games)"]
    assert _lines(text, "--") == []
    assert _lines(text, "g")[0] == "g1 | Adventure, Indie | 2020"
    assert render_wants(request) == "The player has stated no wants."


def test_the_wants_are_numbered_with_the_players_words_and_what_each_is_read_against() -> None:
    assert render_wants(_REQUEST).split("\n") == [
        'w1 · must · "online co-op" · the store fact Online Co-op',
        'w2 · want · "a puzzle game" · reviews that use the words "puzzle", "puzzles"',
        'w3 · nice-to-have · "nice music" · reviewers think well of the music',
    ]
