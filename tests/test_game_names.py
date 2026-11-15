"""Behavioral claims on matching a named game against the library's titles.

The claims: a name written the way a player types it finds the title the
store sells; the whole title wins over a longer one that holds it; a name
inside one longer title resolves and says it was partial; a name several
titles hold resolves to none of them; and the first spelling that finds
anything decides.
"""

from __future__ import annotations

import pytest

from steamlens.contracts import NameMatch
from steamlens.core.game_names import NameResolution, resolve_name, title_words

_LIBRARY = {
    10: "DARK SOULS™ II",
    11: "DARK SOULS™ III",
    20: "God of War",
    21: "God of War Ragnarök",
    30: "Disco Elysium - The Final Cut",
    40: "Sid Meier's Civilization® V",
    50: "NieR:Automata™",
    60: "DOOM Eternal",
    70: "Mount & Blade II: Bannerlord",
    80: "Baldur's Gate 3",
}


@pytest.mark.parametrize(
    ("typed", "app_id", "match"),
    [
        ("dark souls 3", 11, NameMatch.EXACT),
        ("nier automata", 50, NameMatch.EXACT),
        ("baldurs gate 3", 80, NameMatch.EXACT),
        ("mount and blade 2 bannerlord", 70, NameMatch.EXACT),
        ("civilization 5", 40, NameMatch.PARTIAL),
        ("disco elysium", 30, NameMatch.PARTIAL),
        ("ragnarok", 21, NameMatch.PARTIAL),
    ],
)
def test_a_name_as_a_player_types_it_finds_the_title_the_store_sells(
    typed: str, app_id: int, match: NameMatch
) -> None:
    """Case, accents, apostrophes, "&" and Roman numerals differ between the
    two; a trademark sign must not glue itself to the word before it, which
    is what a plain Unicode folding does to "SOULS™"."""
    assert resolve_name([typed], _LIBRARY) == NameResolution(match, app_id)


def test_the_whole_title_wins_over_a_longer_title_that_holds_it() -> None:
    assert resolve_name(["god of war"], _LIBRARY) == NameResolution(NameMatch.EXACT, 20)


def test_a_series_name_resolves_to_the_only_entry_and_says_it_was_partial() -> None:
    """ "doom" may mean another DOOM. The match kind is what lets a reply
    name the title it took."""
    assert resolve_name(["doom"], _LIBRARY) == NameResolution(NameMatch.PARTIAL, 60)


def test_a_name_several_titles_hold_resolves_to_none_of_them() -> None:
    found = resolve_name(["dark souls"], _LIBRARY)
    assert found == NameResolution(NameMatch.SEVERAL, None, (10, 11))


def test_two_library_games_with_one_title_are_several_and_not_a_guess() -> None:
    found = resolve_name(["hades"], {1: "Hades", 2: "HADES"})
    assert found == NameResolution(NameMatch.SEVERAL, None, (1, 2))


@pytest.mark.parametrize("typed", ["skyrim", "bg3", "souls dark", "???", ""])
def test_a_name_no_title_holds_is_not_in_the_library(typed: str) -> None:
    """A nickname is not matched here, and neither are a title's words out
    of order; a spelling with no words in it is skipped."""
    assert resolve_name([typed], _LIBRARY) == NameResolution(NameMatch.NOT_IN_LIBRARY)


def test_the_first_spelling_that_finds_anything_decides() -> None:
    """The model's title goes first and the player's words second. A title
    that finds nothing falls through; one that finds something is not
    overruled by the words after it."""
    assert resolve_name(["Baldur's Gate 3", "bg3"], _LIBRARY).app_id == 80
    assert resolve_name(["Hades II", "disco elysium"], _LIBRARY).app_id == 30
    assert resolve_name(["dark souls", "dark souls 3"], _LIBRARY).match is NameMatch.SEVERAL


def test_a_roman_numeral_reads_as_its_number_on_both_sides() -> None:
    assert title_words("Final Fantasy XV") == title_words("final fantasy 15")
    assert title_words("The Last of Us™ Part I") == ("the", "last", "of", "us", "part", "1")
