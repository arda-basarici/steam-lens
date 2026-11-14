"""The sheet's rules — how the library reads against what a player asked for.

Pure functions, in two layers. The first turns a report's stored aggregates
into ``SheetCell`` records: a mention floor below which a game has no reading
on an aspect, then groups set by where the sentiment share's interval starts.
Beside it sits the one rule for wants the aspects cannot express: when a
search term counts as clustering in a game's reviews.

The second layer reads a request. ``want_reading`` gives one game's status on
one want with what was looked at, and ``read_sheet`` does that for every want
on every library game. The sheet is a reading, not a selection. It removes no
game on evidence, because a store genre can be wrong and a cluster of "timer"
can be reviewers writing that there is none; the chat's judge weighs those
with the reviews in front of it. The one thing left off is a game the player
said they had already played, which is an instruction and not evidence.

The sentiment share is the positive mentions over every review that mentions
the aspect, with mixed and neutral mentions in the denominator, since a mixed
mention is not praise. Its interval is a plain Wilson interval on the
mentions. That interval is not the one the report page draws: the sampling
study calibrated the mention share and treated the sentiment mix as
descriptive, so nothing certifies this interval for the windowed draw. It
prices sampling noise on that many mentions and nothing more, and the groups
are a policy for reading across games, not a measurement.

The constants are working values, cheap to move here and expensive to move
once measurements have been taken against them. They are to be re-read on
development cases, never tuned on reported ones.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from typing import Final

from steamlens.contracts import (
    AspectAggregate,
    AspectSlot,
    AspectTarget,
    Firmness,
    LibraryGame,
    MustStanding,
    NamedGameRole,
    PlayerRequest,
    ReleaseYearsTarget,
    SentimentCounts,
    SentimentGroup,
    Sheet,
    SheetCell,
    SheetRow,
    Stance,
    StoreFactTarget,
    TermTarget,
    Want,
    WantFinding,
    WantReading,
    WantStatus,
    WantTally,
)
from steamlens.core.intervals import wilson_interval
from steamlens.core.store_facts import release_years_reading, store_fact, store_fact_reading

MENTION_FLOOR: Final = 30
"""Fewer sampled reviews than this mention the aspect: no reading. At 30 the
widest interval is about 17 points either way; 20 would admit 20 points, and
50 leaves few aspects readable across many games."""

STRONG_LINE: Final = 0.70
"""The positive share's interval starts above this: strongly positive."""

MAJORITY_LINE: Final = 0.50
"""The positive (or negative) share's interval starts above this: a clear majority."""

SPLIT_HALF_WIDTH: Final = 0.15
"""No clear majority and an interval at most this wide either way: opinion is
split. Wider than this and the sample cannot say."""

TERM_SHARE_FLOOR: Final = 0.02
"""A search term clusters in a game when at least this share of the game's
counted reviews match it. Read against the store's tags on 2026-11-14, 2%
nominated no untagged game for "roguelike", "metroidvania", "racing" or "city
builder". It is too low for a word that names a part of many games
("puzzle"), which no single share separates."""

TERM_MIN_HITS: Final = 3
"""And at least this many matching reviews, so one or two reviews in a small
sample do not make a cluster."""

WRITTEN_ABOUT_GAMES: Final = 10
"""Reviewers do write about a thing when its phrases appear in the reviews of
at least this many library games. Read on 2026-11-14: "timer" and its
variants appear in 59 of 115 games and "red dress" in none. It decides what a
game with no matching review can honestly be told: that the thing comes up
elsewhere and not here, or that reviews do not go into it at all."""

_ASPECT_STATUS: Final = {
    SentimentGroup.STRONGLY_POSITIVE: WantStatus.MATCHES,
    SentimentGroup.MOSTLY_POSITIVE: WantStatus.MATCHES,
    SentimentGroup.CLEARLY_NEGATIVE: WantStatus.FAILS,
    SentimentGroup.SPLIT: WantStatus.FAILS,
    SentimentGroup.UNCLEAR: WantStatus.CANNOT_TELL,
    SentimentGroup.TOO_FEW_MENTIONS: WantStatus.CANNOT_TELL,
}

_STANDING_ORDER: Final = (MustStanding.MEETS, MustStanding.OPEN, MustStanding.CONFLICTS)


def sentiment_group(counts: SentimentCounts, mentions: int) -> SentimentGroup:
    """The group for one game on one aspect, from its stored counts.

    ``mentions`` is the number of sampled reviews mentioning the aspect, and
    ``counts`` their sentiment breakdown. The two must agree (the counts sum
    to the mentions, which the classify stage guarantees by collapsing
    repeats); a mismatch raises ``ValueError``, because the rule was set on
    shares of reviews and would mean something else on shares of mentions.

    >>> sentiment_group(SentimentCounts(41, 4, 0, 0), 45)
    <SentimentGroup.STRONGLY_POSITIVE: 'strongly-positive'>
    >>> sentiment_group(SentimentCounts(49, 25, 4, 0), 78)
    <SentimentGroup.MOSTLY_POSITIVE: 'mostly-positive'>
    >>> sentiment_group(SentimentCounts(7, 0, 0, 0), 7)
    <SentimentGroup.TOO_FEW_MENTIONS: 'too-few-mentions'>
    """
    total = counts.positive + counts.negative + counts.mixed + counts.neutral
    if total != mentions:
        raise ValueError(
            f"sentiment counts sum to {total} but {mentions} reviews mention the aspect — "
            "the group rule reads shares of reviews and needs the two to agree"
        )
    if mentions < MENTION_FLOOR:
        return SentimentGroup.TOO_FEW_MENTIONS
    praise = wilson_interval(counts.positive, mentions)
    if praise.low > STRONG_LINE:
        return SentimentGroup.STRONGLY_POSITIVE
    if praise.low > MAJORITY_LINE:
        return SentimentGroup.MOSTLY_POSITIVE
    if wilson_interval(counts.negative, mentions).low > MAJORITY_LINE:
        return SentimentGroup.CLEARLY_NEGATIVE
    if (praise.high - praise.low) / 2 <= SPLIT_HALF_WIDTH:
        return SentimentGroup.SPLIT
    return SentimentGroup.UNCLEAR


def term_clusters(hits: int, sample_size: int) -> bool:
    """Whether a search term clusters in a game: ``hits`` of ``sample_size`` reviews match.

    Only a cluster is evidence. For something the player wants, a cluster
    puts the game forward; for something the player wants to avoid, a
    cluster counts against it. The absence of a cluster says nothing in
    either case: reviewers of the game that defines a kind rarely use the
    word for it, a store feature is rarely stated in a review at all, and a
    word like "grind" turns up at a low share in most games.

    >>> term_clusters(77, 602), term_clusters(8, 549), term_clusters(2, 72)
    (True, False, False)
    """
    if sample_size < 1:
        raise ValueError(f"sample_size is {sample_size} — a share needs at least one review")
    if not 0 <= hits <= sample_size:
        raise ValueError(f"{hits} matching reviews out of {sample_size} is incoherent")
    return hits >= TERM_MIN_HITS and hits / sample_size >= TERM_SHARE_FLOOR


def sheet_cells(aggregates: Iterable[AspectAggregate]) -> tuple[SheetCell, ...]:
    """One report's aggregates as sheet cells, pinned aspects only, by aspect name.

    Candidate aspects are left out: they are the uncalibrated stratum, and
    one concept fragments across many free-form strings, so a count under any
    one of them is not comparable between games. The order is alphabetical,
    which carries no reading.
    """
    return tuple(
        SheetCell(
            aspect=aggregate.aspect,
            mentions=aggregate.reviews_with_aspect,
            sample_size=aggregate.sample_size,
            counts=aggregate.counts,
            group=sentiment_group(aggregate.counts, aggregate.reviews_with_aspect),
        )
        for aggregate in sorted(aggregates, key=lambda a: a.aspect)
        if aggregate.slot is AspectSlot.PINNED
    )


def aspect_reading(aspect: str, cells: Iterable[SheetCell], *, partial: bool) -> WantReading:
    """One game read on a want that a pinned aspect be well received.

    Either positive group is a match. Clearly negative and split both fail,
    and the reading keeps the group so the wording can tell "mostly
    criticised" from "opinions are divided". Unclear and too few mentions
    are "cannot tell"; an aspect with no cell was mentioned by no sampled
    review and reads as too few.

    A ``partial`` want is one the aspect covers only in part ("runs at 60
    fps on my laptop" against ``performance``). Good reviews cannot confirm
    it, so it never matches, and only a clearly negative reading counts
    against it.

    Complaint aspects come out of this rule as exclude-only with no special
    case: reviewers rarely write that a game has no bugs, so no game is
    positive on ``bugs``.

    >>> combat = SheetCell(
    ...     aspect="combat", mentions=45, sample_size=602,
    ...     counts=SentimentCounts(positive=41, negative=4, mixed=0, neutral=0),
    ...     group=SentimentGroup.STRONGLY_POSITIVE,
    ... )
    >>> aspect_reading("combat", [combat], partial=False).status
    <WantStatus.MATCHES: 'matches'>
    >>> aspect_reading("story", [combat], partial=False).group
    <SentimentGroup.TOO_FEW_MENTIONS: 'too-few-mentions'>
    """
    group = next(
        (cell.group for cell in cells if cell.aspect == aspect), SentimentGroup.TOO_FEW_MENTIONS
    )
    if not partial:
        status = _ASPECT_STATUS[group]
    elif group is SentimentGroup.CLEARLY_NEGATIVE:
        status = WantStatus.FAILS
    else:
        status = WantStatus.CANNOT_TELL
    return WantReading(status, WantFinding.ASPECT_GROUP, group=group)


def term_reading(
    stance: Stance, hits: int, sample_size: int, library_games_with_hits: int
) -> WantReading:
    """One game read on a want about a search term.

    ``hits`` of the game's ``sample_size`` counted reviews match the term,
    and ``library_games_with_hits`` library games have at least one matching
    review. Only a cluster is evidence: it is a match for a wanted term and
    a failure for an avoided one. Anything less is "cannot tell", and the
    finding says which kind, because the three are worded differently: some
    of this game's reviews match (and can be read), none do while reviews of
    other games use the phrase, or reviews do not go into the thing at all.

    >>> term_reading(Stance.WANTS, 77, 602, 12).status
    <WantStatus.MATCHES: 'matches'>
    >>> term_reading(Stance.AVOIDS, 0, 602, 59).finding
    <WantFinding.WRITTEN_ABOUT_ELSEWHERE: 'written-about-elsewhere'>
    """
    if term_clusters(hits, sample_size):
        status = WantStatus.MATCHES if stance is Stance.WANTS else WantStatus.FAILS
        return WantReading(status, WantFinding.TERM_CLUSTERS, hits=hits)
    if hits > 0:
        finding = WantFinding.TERM_BELOW_CLUSTER
    elif library_games_with_hits >= WRITTEN_ABOUT_GAMES:
        finding = WantFinding.WRITTEN_ABOUT_ELSEWHERE
    else:
        finding = WantFinding.NOT_WRITTEN_ABOUT
    return WantReading(WantStatus.CANNOT_TELL, finding, hits=hits)


def want_reading(
    want: Want, game: LibraryGame, term_hits: Mapping[TermTarget, Mapping[int, int]]
) -> WantReading:
    """One game's status on one want, with what was looked at.

    ``term_hits`` holds, for each search term in the request, how many of
    each game's counted reviews match it; a game absent from a term's map
    has no matching review. A want with no target is always "cannot tell".

    Raises ``ValueError`` on a want that has no meaning: an avoided aspect
    (an aspect says how well a part is received, so "not buggy" is a wish
    that ``bugs`` read well, not an avoided aspect), a partly checkable want
    on anything but an aspect, or a search term with no supplied counts.
    """
    target = want.target
    if want.partial and not isinstance(target, AspectTarget):
        raise ValueError(
            f"want {want.words!r} is marked partly checkable — only a want on an aspect can be"
        )
    match target:
        case None:
            return WantReading(WantStatus.CANNOT_TELL, WantFinding.NO_DATA)
        case StoreFactTarget(key=key):
            return store_fact_reading(store_fact(key), want.stance, game.storefront, game.tags)
        case ReleaseYearsTarget():
            return release_years_reading(target, want.stance, game.storefront)
        case AspectTarget(aspect=aspect):
            if want.stance is Stance.AVOIDS:
                raise ValueError(
                    f"want {want.words!r} avoids the aspect {aspect!r} — an aspect want asks "
                    "that the part be well received and has no avoided form"
                )
            return aspect_reading(aspect, game.cells, partial=want.partial)
        case TermTarget():
            hits = term_hits.get(target)
            if hits is None:
                raise ValueError(
                    f"no hit counts were supplied for the search term {target.phrases!r}"
                )
            return term_reading(want.stance, hits.get(game.app_id, 0), game.sample_size, len(hits))


def must_standing(wants: Sequence[Want], readings: Sequence[WantReading]) -> MustStanding:
    """Where a game stands on the musts among ``wants``, given its reading on each.

    One failed must is a conflict. With none failed, one "cannot tell" on a
    must leaves the game open. A game with every must matched, or a request
    with no must, meets them. The softer wants do not enter: what a near
    miss may give on is the judge's call.
    """
    on_musts = {
        reading.status
        for want, reading in zip(wants, readings, strict=True)
        if want.firmness is Firmness.MUST
    }
    if WantStatus.FAILS in on_musts:
        return MustStanding.CONFLICTS
    if WantStatus.CANNOT_TELL in on_musts:
        return MustStanding.OPEN
    return MustStanding.MEETS


def read_sheet(
    request: PlayerRequest,
    library: Iterable[LibraryGame],
    term_hits: Mapping[TermTarget, Mapping[int, int]],
) -> Sheet:
    """The library read against ``request``: every game, a reading per want.

    Games the player named as already played are left off and listed. Every
    other library game gets a row, whatever its readings; the rows are
    grouped by standing on the musts and ordered by app id inside a group,
    so position carries no reading. The tallies count each want's statuses
    over the rows.
    """
    played = {
        named.app_id
        for named in request.named_games
        if named.role is NamedGameRole.NOT_THIS and named.app_id is not None
    }
    rows: list[SheetRow] = []
    for game in library:
        if game.app_id in played:
            continue
        readings = tuple(want_reading(want, game, term_hits) for want in request.wants)
        rows.append(SheetRow(game, readings, must_standing(request.wants, readings)))
    rows.sort(key=lambda row: (_STANDING_ORDER.index(row.standing), row.game.app_id))
    tallies = tuple(
        _tally([row.readings[index].status for row in rows])
        for index in range(len(request.wants))
    )
    return Sheet(rows=tuple(rows), tallies=tallies, already_played=tuple(sorted(played)))


def _tally(statuses: Sequence[WantStatus]) -> WantTally:
    return WantTally(
        matches=statuses.count(WantStatus.MATCHES),
        fails=statuses.count(WantStatus.FAILS),
        cannot_tell=statuses.count(WantStatus.CANNOT_TELL),
    )
