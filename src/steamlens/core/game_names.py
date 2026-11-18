"""Matching a game's name against the library's titles.

A player names a game the way they say it ("dark souls 3", "nier automata")
and the store writes it the way it is sold ("DARK SOULS™ III",
"NieR:Automata™"). ``title_words`` reduces both to the same plain words, and
``resolve_name`` looks a name up among the library's titles: the whole title
first, then the name as a run of words inside a longer one, which is how a
subtitle or an edition is skipped ("Disco Elysium - The Final Cut").

The match is literal on purpose. There is no spelling tolerance and no
nickname table here; the understand step's model writes the fuller title for
a nickname, and this module decides whether the library holds it. Read on
the library of 2026-11-14 (115 titles) with 39 spellings a player might
type, the rule found the right game for 20, rightly found none for 3 the
library lacks, asked on 4 that several titles hold, missed 8 nicknames
("bg3", "civ 5"), and resolved 4 series names to the one entry the library
has ("doom" to DOOM Eternal). The last kind is why a partial match is
reported as partial.

``referenced_game`` is the other lookup: from a want that points at a named
game ("less frantic than Hades") to that game's entry in the same request.

``names_title`` reads the other way, from a sentence the chat wrote to a
title: whether the sentence names the game at all, in full or the way a
title is shortened in talk ("Dying Light 2", "Obra Dinn").
"""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Final

from steamlens.contracts import NamedGame, NameMatch

# Removed before the Unicode folding, which would spell a trademark sign out
# as the letters "TM" and glue them to the word before it.
_MARKS: Final = re.compile("[™®©]")
_APOSTROPHES: Final = re.compile("['‘’`]")
_WORD: Final = re.compile(r"[a-z0-9]+")
_ROMAN: Final = {
    "i": "1", "ii": "2", "iii": "3", "iv": "4", "v": "5",
    "vi": "6", "vii": "7", "viii": "8", "ix": "9", "x": "10",
    "xi": "11", "xii": "12", "xiii": "13", "xiv": "14", "xv": "15",
    "xvi": "16", "xvii": "17", "xviii": "18", "xix": "19", "xx": "20",
}

# Words a title shares with any sentence. A run made of these and one more
# word ("return of the") does not show that a sentence names the game.
_FILLER: Final = frozenset({"a", "an", "and", "at", "for", "in", "of", "on", "the", "to"})


@dataclass(frozen=True, slots=True)
class NameResolution:
    """Where a name landed among the library's titles.

    ``app_id`` is set for an exact and for a partial match. ``candidates``
    are the library games a name shared by several titles could mean,
    ordered by app id.
    """

    match: NameMatch
    app_id: int | None = None
    candidates: tuple[int, ...] = ()


def title_words(title: str) -> tuple[str, ...]:
    """A title as plain comparable words.

    Case, accents, trademark signs, apostrophes and punctuation go. "&"
    reads as "and", and a Roman numeral up to twenty reads as its number, on
    both sides of a comparison, so a stray "I" or "X" changes nothing.

    >>> title_words("DARK SOULS™ III")
    ('dark', 'souls', '3')
    >>> title_words("baldurs gate 3") == title_words("Baldur's Gate 3")
    True
    >>> title_words("God of War Ragnarök")
    ('god', 'of', 'war', 'ragnarok')
    >>> title_words("Mount & Blade II: Bannerlord")
    ('mount', 'and', 'blade', '2', 'bannerlord')
    """
    text = _MARKS.sub("", title).replace("&", " and ")
    text = unicodedata.normalize("NFKD", text)
    text = "".join(char for char in text if not unicodedata.combining(char)).casefold()
    text = _APOSTROPHES.sub("", text)
    words: list[str] = _WORD.findall(text)
    return tuple(_ROMAN.get(word, word) for word in words)


def resolve_name(spellings: Sequence[str], library: Mapping[int, str]) -> NameResolution:
    """Look a named game up among the library's titles.

    ``spellings`` are tried in order and the first one that finds anything
    decides, so a caller puts the more reliable spelling first. ``library``
    maps each library game's app id to its title.

    A spelling equal to one whole title is exact. Otherwise it matches every
    title that holds its words as an unbroken run: one such title is a
    partial match, more than one is ``SEVERAL`` with the candidates and no
    game chosen.

    >>> library = {1: "God of War", 2: "God of War Ragnarök", 3: "DOOM Eternal"}
    >>> resolve_name(["god of war"], library)
    NameResolution(match=<NameMatch.EXACT: 'exact'>, app_id=1, candidates=())
    >>> resolve_name(["doom"], library).match
    <NameMatch.PARTIAL: 'partial'>
    >>> resolve_name(["war"], library).candidates
    (1, 2)
    >>> resolve_name(["Hades II", "hades"], library).match
    <NameMatch.NOT_IN_LIBRARY: 'not-in-library'>
    """
    titles = {app_id: title_words(title) for app_id, title in library.items()}
    for spelling in spellings:
        words = title_words(spelling)
        if not words:
            continue
        exact = sorted(app_id for app_id, title in titles.items() if title == words)
        if len(exact) == 1:
            return NameResolution(NameMatch.EXACT, exact[0])
        held = exact or sorted(
            app_id for app_id, title in titles.items() if holds_run(title, words)
        )
        if len(held) == 1:
            return NameResolution(NameMatch.PARTIAL, held[0])
        if held:
            return NameResolution(NameMatch.SEVERAL, candidates=tuple(held))
    return NameResolution(NameMatch.NOT_IN_LIBRARY)


def referenced_game(reference: str, named_games: Sequence[NamedGame]) -> NamedGame | None:
    """The named game a want's ``compared_to`` or ``liked_in`` points at, or ``None``.

    A reference repeats the player's words for the game. It is compared as
    plain title words with each named game's words and then with each
    fuller title, so "Hades" finds the game the player typed as "hades" and
    "Baldur's Gate 3" finds the one typed as "bg3". The first entry that
    matches is returned. ``None`` means the reference names no game of the
    request, which the understand step's validation treats as a fault.

    >>> from steamlens.contracts import Feeling, NamedGameRole
    >>> bg3 = NamedGame(
    ...     "bg3", 1086940, NameMatch.EXACT, NamedGameRole.LIKE_THIS, Feeling.LIKED,
    ...     title="Baldur's Gate 3",
    ... )
    >>> referenced_game("BG3", [bg3]) is bg3, referenced_game("baldurs gate 3", [bg3]) is bg3
    (True, True)
    >>> referenced_game("hades", [bg3]) is None
    True
    """
    words = title_words(reference)
    if not words:
        return None
    for game in named_games:
        if title_words(game.words) == words:
            return game
    for game in named_games:
        if game.title is not None and title_words(game.title) == words:
            return game
    return None


def names_title(text: str, title: str) -> bool:
    """Whether ``text`` names the game titled ``title``, in full or shortened.

    A sentence names a game when it holds the title's first word that is
    not a filler ("Stardew", "the Sims"), or any unbroken run of the title
    with two or more such words ("Obra Dinn" for "Return of the Obra
    Dinn"). The rule is generous on purpose. Its caller removes a game the
    reply offered and never named, so reading a named game as unnamed is
    the costly mistake, and reading "a return to form" as naming a game
    only lets a fault pass.

    >>> names_title("Dying Light 2 lists online co-op.", "Dying Light 2 Stay Human")
    True
    >>> names_title("Obra Dinn has no clock.", "Return of the Obra Dinn")
    True
    >>> names_title("Its reviewers praise the story.", "Return of the Obra Dinn")
    False
    """
    words = title_words(text)
    wanted = title_words(title)
    content = [word for word in wanted if word not in _FILLER]
    if not content:
        return holds_run(words, wanted)
    if content[0] in words:
        return True
    for start in range(len(wanted)):
        for end in range(start + 2, len(wanted) + 1):
            run = wanted[start:end]
            if sum(word not in _FILLER for word in run) >= 2 and holds_run(words, run):
                return True
    return False


def holds_run(words: tuple[str, ...], run: tuple[str, ...]) -> bool:
    """Whether ``run`` appears in ``words`` as one unbroken stretch.

    >>> holds_run(("god", "of", "war", "ragnarok"), ("of", "war"))
    True
    >>> holds_run(("god", "of", "war"), ("war", "of"))
    False
    """
    span = len(run)
    return any(words[start:start + span] == run for start in range(len(words) - span + 1))
