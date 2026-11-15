"""The structured request — what a chat turn asks for, in a fixed shape.

The recommender chat's understand step fills a ``PlayerRequest`` from the
whole conversation on every turn. Nothing else carries state between turns,
so a want the player withdrew is simply absent from the next request. Code
reads the sheet from it, the judge reads both, and the check uses it to see
that no want was dropped.

A ``Want`` keeps the player's own words and names exactly one target: a store
fact from a closed vocabulary, a range of release years, one pinned aspect, a
search term given as the spelling variants of one idea, or nothing. "Nothing"
is a real answer and is kept: the failure it guards against is a request
that loses its one unverifiable condition and still returns a confident
answer.

The records here hold what the understand step produced and are not checked
at construction, like every contract. The step's shell validates a model's
output into them; the reading rules in ``core.sheet`` name the combinations
that have no meaning (an avoided aspect, a partly checkable store fact) and
refuse them there.
"""

from __future__ import annotations

from dataclasses import dataclass

from steamlens.contracts.enums import (
    Feeling,
    Firmness,
    NamedGameRole,
    NameMatch,
    RequestIntent,
    Stance,
    StoreFactSource,
)


@dataclass(frozen=True, slots=True)
class StoreFactDef:
    """One store fact the chat may match a want against.

    ``key`` is what a target names and ``label`` what a person reads.
    ``source`` says where in a game's store metadata the fact sits, and
    ``ids`` are the store's genre or category ids that mean it (empty for a
    platform, which is a flag). A game has the fact when it carries any of
    them.

    ``complete`` says how absence is read. Every game declares its play
    modes, platforms and genres, so for those a missing fact is the store's
    answer. Features such as adjustable difficulty are declared by choice,
    and their absence says nothing.

    ``player_tags`` are community tag names that mean the same kind of game.
    A game the store does not list under the fact and players tag with one
    of them is neither a match nor a failure. Only genres carry them.

    ``note`` says what the fact is where the store's label alone invites a
    wrong reading. It is shown to the understand step beside the label and
    is empty for most facts.
    """

    key: str
    label: str
    source: StoreFactSource
    complete: bool
    ids: tuple[int, ...] = ()
    player_tags: tuple[str, ...] = ()
    note: str = ""


@dataclass(frozen=True, slots=True)
class StoreFactTarget:
    """A want about a store fact, named by its key in the store-fact vocabulary."""

    key: str


@dataclass(frozen=True, slots=True)
class ReleaseYearsTarget:
    """A want about when the game came out: a range of years, either end open.

    "From 2020" is ``first=2020``; "up to 2014" is ``last=2014``; both ends
    are inclusive. The year is the store's release date, which moves to the
    full release when a game leaves early access, so a game long playable in
    early access reads as new.
    """

    first: int | None
    last: int | None


@dataclass(frozen=True, slots=True)
class AspectTarget:
    """A want about how well one part of the game is received: a pinned aspect.

    It never expresses how much of something a game has. A game's length
    being praised does not make it short, so a wish about an amount goes to
    a search term or stays unmapped.
    """

    aspect: str


@dataclass(frozen=True, slots=True)
class TermTarget:
    """A want the store facts and aspects cannot express, as phrases to search for.

    ``phrases`` are the spelling variants of one idea, each matched
    literally: there is no stemming, so "roguelike" and "rogue like" are
    both listed.
    """

    phrases: tuple[str, ...]


type WantTarget = StoreFactTarget | ReleaseYearsTarget | AspectTarget | TermTarget
"""What a want or a subject is read against. ``None`` in its place means no
stored field fits, and the reading is always "cannot tell"."""


@dataclass(frozen=True, slots=True)
class Want:
    """One thing the player asked for, or asked to avoid.

    ``words`` are the player's own, an unbroken stretch of one of their
    messages, and are always kept; the understand step's validation checks
    them against the conversation. ``partial`` marks a
    want its target covers only in part: nothing says how a game runs on one
    laptop, but performance complaints are evidence against, so such a want
    can fail and can never match. ``compared_to`` holds the player's words
    for a named game the want is relative to ("less frantic than Hades");
    the comparison itself is the judge's, from reviews of both games.
    ``liked_in`` holds the words for a named game when the want is a part the
    player said they liked in it.

    >>> Want(
    ...     words="nothing with a timer", firmness=Firmness.MUST, stance=Stance.AVOIDS,
    ...     target=TermTarget(phrases=("timer", "timed", "time limit")),
    ... ).partial
    False
    """

    words: str
    firmness: Firmness
    stance: Stance
    target: WantTarget | None
    partial: bool = False
    compared_to: str | None = None
    liked_in: str | None = None


@dataclass(frozen=True, slots=True)
class NamedGame:
    """A game the player named, and what they said about it.

    ``words`` are what the player typed and ``title`` is the fuller title the
    understand step wrote for them ("bg3" becomes "Baldur's Gate 3"), or
    ``None`` when it could not tell which game was meant. Code matches both
    against the library's titles; the model never sees the library and never
    decides whether it holds the game.

    ``app_id`` is the library game the name resolves to, and ``match`` says
    how it was found. A name that several library titles hold resolves to
    none of them: ``app_id`` is ``None`` and ``candidates`` lists them, so
    the chat can ask which one. ``liked_parts`` are the player's words and
    are empty when they did not say, which is when the chat may ask.
    """

    words: str
    app_id: int | None
    match: NameMatch
    role: NamedGameRole
    feeling: Feeling
    liked_parts: tuple[str, ...] = ()
    title: str | None = None
    candidates: tuple[int, ...] = ()


@dataclass(frozen=True, slots=True)
class Subject:
    """One thing the player's latest message asks about.

    On a turn about one game it is a question about that game, with the same
    kinds of target as a want and no firmness or stance, since nothing is
    being matched. The player's question is never passed to a search as
    typed: a term subject carries search words the understand step wrote. On
    a turn about what the numbers mean it holds the question's words with no
    target, so the words reach the step that answers.
    """

    words: str
    target: WantTarget | None


@dataclass(frozen=True, slots=True)
class PlayerRequest:
    """One chat turn's request, rebuilt from the whole conversation.

    ``wants`` are everything the player wants from a game that still stands,
    whatever the latest message asks for. ``subjects`` are the questions of
    a turn about one game or about the numbers, one entry each, and are
    empty on a recommendation. ``substitutes_ruled_out`` records a player
    who said a neighbouring kind of game will not do, which decides whether
    a "nothing fits" reply may ask about one. ``show_evidence`` is set only
    when the player asks to be shown what reviewers wrote, or the figures on
    a game; asking what a number means does not set it. ``other_games``
    records a player who asked for games other than the ones the chat
    already offered ("anything else?"). Like an already-played game it is
    the player's say and not evidence, and it is what leaves the earlier
    offers out of the next suggestions.

    >>> request = PlayerRequest(intent=RequestIntent.RECOMMEND)
    >>> request.wants, request.subjects, request.show_evidence, request.other_games
    ((), (), False, False)
    """

    intent: RequestIntent
    named_games: tuple[NamedGame, ...] = ()
    wants: tuple[Want, ...] = ()
    subjects: tuple[Subject, ...] = ()
    substitutes_ruled_out: bool = False
    show_evidence: bool = False
    other_games: bool = False
