"""The pick call's reading matter — a request and its sheet, rendered as text.

The pick call reads two things and nothing else: the request, and the
library read against it. This module renders both. The conversation is not
among them, so a pick is a function of the request and the sheet and can be
scored against the sheet it was made from.

The sheet is laid out so the games worth reading come first without code
choosing among them. Rows are grouped by standing on the musts, and inside a
standing by pattern: the statuses a game has across the wants. Patterns are
ordered by a plain count, fewest fails first and then most matches, which
never looks at firmness, since weighing a must against a nice-to-have is the
near-miss judgment the model is there for. Every row stays on the sheet.

A game's line carries an identifier, its store genres, its release year and
what was found on each want. It carries no title and no app id. The
identifier is made here and means nothing outside one render, so a pick can
only come from what the sheet says about a game and never from what a model
remembers of it. The cost is known: without a title the model cannot tell
that a game whose reviews say "puzzle" is not a puzzle game, and rests on
the match counts.

A want relative to a named game shows what its target found on each side in
words and no counts. Setting two counts side by side would invite the
comparison of shares that is declined everywhere else.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from typing import Final

from steamlens.contracts import (
    AspectTarget,
    LibraryGame,
    MustStanding,
    PlayerRequest,
    ReleaseYearsTarget,
    SentimentGroup,
    Sheet,
    SheetRow,
    SideFinding,
    Stance,
    StoreFactTarget,
    TermTarget,
    Want,
    WantFinding,
    WantReading,
    WantStatus,
)
from steamlens.core.store_facts import store_fact

_STANDING_HEADINGS: Final = (
    (MustStanding.MEETS, "Meets every must"),
    (MustStanding.OPEN, "Open on a must: at least one must could not be decided"),
    (MustStanding.CONFLICTS, "Conflicts with a must"),
)

_STATUS_WORDS: Final = {
    WantStatus.MATCHES: "matches",
    WantStatus.FAILS: "fails",
    WantStatus.CANNOT_TELL: "cannot tell",
}
_STATUS_ORDER: Final = (WantStatus.MATCHES, WantStatus.CANNOT_TELL, WantStatus.FAILS)

_GROUP_WORDS: Final = {
    SentimentGroup.STRONGLY_POSITIVE: "strongly positive",
    SentimentGroup.MOSTLY_POSITIVE: "mostly positive",
    SentimentGroup.CLEARLY_NEGATIVE: "mostly criticised",
    SentimentGroup.SPLIT: "opinions divided",
    SentimentGroup.UNCLEAR: "too mixed to place",
    SentimentGroup.TOO_FEW_MENTIONS: "too few reviews mention it",
}

# What a finding says with no count beside it. A term's count is added to
# these on a game's own line and left off both sides of a comparison.
_FINDING_WORDS: Final = {
    WantFinding.LISTED: "the store lists it",
    WantFinding.NOT_LISTED: "the store does not list it",
    WantFinding.NOT_DECLARED: "not declared, which says nothing",
    WantFinding.TAGGED_NOT_LISTED: "not listed by the store, tagged by players",
    WantFinding.TAGS_NOT_READ: "not listed by the store, player tags not read",
    WantFinding.NO_STORE_FACTS: "no store facts held",
    WantFinding.RELEASED_IN_RANGE: "released in the range",
    WantFinding.RELEASED_OUTSIDE_RANGE: "released outside the range",
    WantFinding.NO_RELEASE_DATE: "no release date held",
    WantFinding.TERM_CLUSTERS: "the words cluster in its reviews",
    WantFinding.TERM_BELOW_CLUSTER: "a few reviews use the words",
    # Whether other games' reviews use the words is the same for every game
    # with no match, so it is said once, in the note on the want.
    WantFinding.WRITTEN_ABOUT_ELSEWHERE: "no review uses the words",
    WantFinding.NOT_WRITTEN_ABOUT: "no review uses the words",
    WantFinding.NO_DATA: "nothing stored to read it against",
}

# What holds for a want on every game, said once above the games.
_WANT_NOTES: Final = {
    WantFinding.WRITTEN_ABOUT_ELSEWHERE: (
        "reviews of other library games do use these words, so a game with no match is one"
        " whose reviewers did not bring it up"
    ),
    WantFinding.NOT_WRITTEN_ABOUT: (
        "hardly any library review uses these words, so no match says nothing about a game"
    ),
    WantFinding.NAMED_GAME_NOT_IN_LIBRARY: (
        "relative to a game the library has not measured, so there is nothing to compare"
        " with; no verdict is given, and each line says what this game's reviews show"
    ),
    WantFinding.NAMED_GAME_UNRESOLVED: (
        "relative to a game whose name fits no single title, so there is nothing to compare"
        " with; no verdict is given, and each line says what this game's reviews show"
    ),
}


def pick_identifiers(sheet: Sheet) -> dict[int, str]:
    """Each row's identifier in the pick call, by app id: ``g1``, ``g2`` and on.

    Numbered over the sheet's rows in app-id order, whatever their standing,
    so an identifier says nothing about how a game reads. The map is what
    turns a pick back into app ids.
    """
    ordered = sorted(row.game.app_id for row in sheet.rows)
    return {app_id: f"g{number}" for number, app_id in enumerate(ordered, start=1)}


def render_wants(request: PlayerRequest) -> str:
    """The request's wants as the pick call reads them, numbered ``w1`` and on.

    One line a want: its number, how firmly it was meant, the player's own
    words, and what it is read against. The numbers are the ones the sheet's
    patterns and a pick's wants refer to. A request with no wants says so.
    """
    if not request.wants:
        return "The player has stated no wants."
    return "\n".join(
        f'w{number} · {want.firmness.value} · "{want.words}" · {_target_words(want)}'
        for number, want in enumerate(request.wants, start=1)
    )


def render_pick_sheet(
    request: PlayerRequest,
    sheet: Sheet,
    *,
    inner_order: Callable[[SheetRow], int] | None = None,
) -> str:
    """The sheet as the pick call reads it: standing, then pattern, then one line a game.

    ``inner_order`` keys the order of the games inside one pattern. The
    default is the app id, the order the sheet itself keeps and one that
    carries no reading. It is a parameter so the same request can be
    rendered in two orders, which is how it is measured whether a pick
    follows position.
    """
    identifiers = pick_identifiers(sheet)
    key = inner_order or _by_app_id
    lines = [
        f"{len(sheet.rows)} games. A game's line: identifier | store genres | release year"
        + (" | what was found on each want, in the order of the wants" if request.wants else "")
    ]
    lines.extend(_want_notes(sheet))
    for standing, heading in _STANDING_HEADINGS:
        rows = [row for row in sheet.rows if row.standing is standing]
        if not rows:
            continue
        lines.append("")
        lines.append(f"== {heading} ({_games(len(rows))})")
        for pattern, members in _by_pattern(rows):
            if pattern:
                statuses = ", ".join(
                    f"w{number} {_STATUS_WORDS[status]}"
                    for number, status in enumerate(pattern, start=1)
                )
                lines.append(f"-- {statuses} ({_games(len(members))})")
            lines.extend(_game_line(row, identifiers) for row in sorted(members, key=key))
    return "\n".join(lines)


def _want_notes(sheet: Sheet) -> list[str]:
    """One line for each want that has something true of every game, in the wants' order.

    The named game's side of a comparison, and whether a search term's
    words are used in the library at all, do not vary from game to game.
    Said once here, they are left off the games' lines.
    """
    notes: list[str] = []
    for index in range(len(sheet.tallies)):
        readings = [row.readings[index] for row in sheet.rows]
        said: dict[str, None] = {}
        for reading in readings:
            if reading.finding is WantFinding.RELATIVE_TO_NAMED_GAME:
                named = reading.on_named_game
                said[
                    "relative to the named game, whose own reviews show: "
                    + (_side_words(named) if named is not None else "nothing read")
                    + "; no verdict is given, and each line says what this game's reviews show"
                ] = None
            findings = [reading.finding]
            if reading.on_game is not None:
                findings.append(reading.on_game.finding)
            for finding in findings:
                if finding in _WANT_NOTES:
                    said[_WANT_NOTES[finding]] = None
        notes.extend(f"w{index + 1}: {note}" for note in said)
    return notes


def _by_app_id(row: SheetRow) -> int:
    return row.game.app_id


def _games(count: int) -> str:
    return "1 game" if count == 1 else f"{count} games"


def _by_pattern(
    rows: Sequence[SheetRow],
) -> list[tuple[tuple[WantStatus, ...], list[SheetRow]]]:
    """``rows`` gathered by their statuses across the wants, best count first.

    Fewest fails, then most matches. Two patterns level on both are put in a
    fixed order by their statuses, so a render is the same every time.
    """
    patterns: dict[tuple[WantStatus, ...], list[SheetRow]] = {}
    for row in rows:
        patterns.setdefault(tuple(reading.status for reading in row.readings), []).append(row)
    return sorted(
        patterns.items(),
        key=lambda item: (
            item[0].count(WantStatus.FAILS),
            -item[0].count(WantStatus.MATCHES),
            tuple(_STATUS_ORDER.index(status) for status in item[0]),
        ),
    )


def _game_line(row: SheetRow, identifiers: dict[int, str]) -> str:
    parts = [identifiers[row.game.app_id], *_store_parts(row.game)]
    if row.readings:
        parts.append("; ".join(_reading_words(reading, row.game) for reading in row.readings))
    line = " | ".join(parts)
    if row.like_this:
        line += ' | the game the player named as "like this": never a candidate'
    return line


def _store_parts(game: LibraryGame) -> tuple[str, str]:
    """A game's store genres and release year, each saying so when it is not held."""
    if game.storefront is None:
        return ("no store facts held", "year not held")
    genres = ", ".join(genre.description for genre in game.storefront.genres) or "no genre listed"
    released = game.storefront.release_date
    return (genres, str(released.year) if released is not None else "year not held")


def _reading_words(reading: WantReading, game: LibraryGame) -> str:
    """What was found on one want, in words; the status is in the pattern's heading."""
    if reading.on_game is not None:
        return _side_words(reading.on_game)
    if reading.finding is WantFinding.ASPECT_GROUP:
        return _GROUP_WORDS[reading.group or SentimentGroup.TOO_FEW_MENTIONS]
    if reading.hits:
        tail = "a cluster" if reading.finding is WantFinding.TERM_CLUSTERS else "too few to count"
        return f"{reading.hits} of {game.sample_size} reviews use the words, {tail}"
    return _FINDING_WORDS[reading.finding]


def _side_words(side: SideFinding) -> str:
    if side.finding is WantFinding.ASPECT_GROUP:
        return _GROUP_WORDS[side.group or SentimentGroup.TOO_FEW_MENTIONS]
    return _FINDING_WORDS[side.finding]


def _target_words(want: Want) -> str:
    """What a want is read against, with its stance, as one phrase."""
    avoided = want.stance is Stance.AVOIDS
    relative = f', relative to "{want.compared_to}"' if want.compared_to else ""
    match want.target:
        case None:
            return "no stored field fits it" + relative
        case StoreFactTarget(key=key):
            label = store_fact(key).label
            return (f"avoids the store fact {label}" if avoided
                    else f"the store fact {label}") + relative
        case ReleaseYearsTarget(first=first, last=last):
            span = f"{first or 'any year'} to {last or 'now'}"
            return ("not released " if avoided else "released ") + span + relative
        case AspectTarget(aspect=aspect):
            partly = ", which covers the want only in part" if want.partial else ""
            return f"reviewers think well of the {aspect.replace('_', ' ')}{partly}{relative}"
        case TermTarget(phrases=phrases):
            words = ", ".join(f'"{phrase}"' for phrase in phrases)
            return ("avoids " if avoided else "") + f"reviews that use the words {words}" + relative
