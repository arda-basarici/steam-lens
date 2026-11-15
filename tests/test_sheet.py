"""Behavioral claims on the sheet's rules — real cells from the library, and the edges.

The named cases are combat readings from the serving database copy of
2026-11-14, the ones DESIGN's sheet section argues from: the two positive
tiers have to separate Hades from Dying Light 2, and the game with the worst
combat in the library has to land in "split" because mixed mentions sit in
the denominator. The edge cases pin the floor and the two ways a cell can
fail to say anything.

The second half reads a request. Its claims: each kind of want is read from
its own source, "cannot tell" always says what was looked at, and the sheet
leaves no game off on evidence.
"""

from __future__ import annotations

from datetime import UTC, date, datetime

import pytest

from steamlens.contracts import (
    AspectAggregate,
    AspectSlot,
    AspectTarget,
    ClassifierVersions,
    Feeling,
    Firmness,
    LibraryGame,
    MustStanding,
    NamedGame,
    NamedGameRole,
    NameMatch,
    PlayerRequest,
    ReleaseYearsTarget,
    RequestIntent,
    SentimentCounts,
    SentimentGroup,
    SheetCell,
    Stance,
    StoreFactTarget,
    StorefrontLabel,
    StorefrontMetadata,
    StorefrontTagCapture,
    TermTarget,
    Want,
    WantFinding,
    WantReading,
    WantStatus,
    WantTally,
    WantTarget,
)
from steamlens.core.sheet import (
    MENTION_FLOOR,
    WRITTEN_ABOUT_GAMES,
    aspect_reading,
    must_standing,
    read_sheet,
    sentiment_group,
    sheet_cells,
    term_clusters,
    term_reading,
    want_reading,
)


def _counts(positive: int, negative: int, mixed: int = 0, neutral: int = 0) -> SentimentCounts:
    return SentimentCounts(positive=positive, negative=negative, mixed=mixed, neutral=neutral)


def _group(positive: int, negative: int, mixed: int = 0, neutral: int = 0) -> SentimentGroup:
    counts = _counts(positive, negative, mixed, neutral)
    return sentiment_group(counts, positive + negative + mixed + neutral)


@pytest.mark.parametrize(
    ("game", "counts", "expected"),
    [
        ("Hades", (41, 4, 0, 0), SentimentGroup.STRONGLY_POSITIVE),
        ("Undertale", (31, 5, 0, 0), SentimentGroup.STRONGLY_POSITIVE),
        ("Dying Light 2", (49, 25, 4, 0), SentimentGroup.MOSTLY_POSITIVE),
        ("ELDEN RING", (35, 7, 8, 0), SentimentGroup.MOSTLY_POSITIVE),
        ("Rise of the Tomb Raider", (27, 12, 4, 0), SentimentGroup.SPLIT),
        ("Kingdom Come: Deliverance II", (34, 34, 12, 1), SentimentGroup.SPLIT),
    ],
)
def test_real_combat_cells_fall_where_the_design_says(
    game: str, counts: tuple[int, int, int, int], expected: SentimentGroup
) -> None:
    assert _group(*counts) is expected, game


def test_the_two_positive_tiers_separate_praise_from_a_bare_majority() -> None:
    """91% positive on 45 mentions and 63% on 78 are both a majority; only the
    first clears the strong line. One positive group held both."""
    assert _group(41, 4) is SentimentGroup.STRONGLY_POSITIVE
    assert _group(49, 25, mixed=4) is SentimentGroup.MOSTLY_POSITIVE


def test_mixed_mentions_keep_a_bad_reading_out_of_clearly_negative() -> None:
    """SILENT HILL: Townfall, the library's worst combat: 82 negative of 164
    is exactly half, the 29 mixed mentions hold the negative share's interval
    under the line, and the cell reads as split. Without the mixed mentions
    the same negatives would be a clear majority."""
    assert _group(50, 82, mixed=29, neutral=3) is SentimentGroup.SPLIT
    assert _group(50, 82) is SentimentGroup.CLEARLY_NEGATIVE


def test_a_complaint_aspect_reads_clearly_negative() -> None:
    assert _group(2, 40, mixed=3) is SentimentGroup.CLEARLY_NEGATIVE


def test_the_floor_is_inclusive_and_praise_below_it_reads_as_nothing() -> None:
    """Unanimous praise on 29 mentions is still no reading: by positive share
    alone the library's best combat belonged to a game with seven mentions."""
    assert _group(MENTION_FLOOR - 1, 0) is SentimentGroup.TOO_FEW_MENTIONS
    assert _group(7, 0) is SentimentGroup.TOO_FEW_MENTIONS
    assert _group(MENTION_FLOOR, 0) is SentimentGroup.STRONGLY_POSITIVE


def test_an_even_balance_is_unclear_at_the_floor_and_split_on_more_mentions() -> None:
    """The same 50% reads differently by how much evidence stands behind it:
    on 30 mentions the interval spans about 17 points either way, too wide to
    call a real balance; on 100 it is under 10."""
    assert _group(15, 15) is SentimentGroup.UNCLEAR
    assert _group(50, 50) is SentimentGroup.SPLIT


def test_counts_that_disagree_with_the_mentions_fail_loud() -> None:
    """The rule reads shares of reviews. If a label path ever stops collapsing
    repeats, counts would be shares of mentions, and the groups would
    silently mean something else."""
    with pytest.raises(ValueError, match="sum to 46 but 45"):
        sentiment_group(_counts(42, 4), 45)


def _aggregate(aspect: str, slot: AspectSlot, positive: int, negative: int) -> AspectAggregate:
    return AspectAggregate(
        app_id=1145360,
        aspect=aspect,
        slot=slot,
        reviews_with_aspect=positive + negative,
        counts=_counts(positive, negative),
        sample_size=602,
        versions=ClassifierVersions(
            model_version="m", prompt_version="p", ontology_version="v2"
        ),
        manifest_id="serve-1",
    )


def test_cells_cover_pinned_aspects_only_in_an_order_that_says_nothing() -> None:
    """Candidate aspects stay off the sheet, and the cells come back by name
    whatever order the report stored them in, so position carries no rank."""
    cells = sheet_cells([
        _aggregate("story", AspectSlot.PINNED, 60, 5),
        _aggregate("grind", AspectSlot.CANDIDATE, 3, 40),
        _aggregate("combat", AspectSlot.PINNED, 41, 4),
        _aggregate("bugs", AspectSlot.PINNED, 1, 9),
    ])
    assert [cell.aspect for cell in cells] == ["bugs", "combat", "story"]
    bugs, combat, _ = cells
    assert bugs.group is SentimentGroup.TOO_FEW_MENTIONS
    assert combat.group is SentimentGroup.STRONGLY_POSITIVE
    assert (combat.mentions, combat.sample_size) == (45, 602)
    assert combat.positive_share == pytest.approx(41 / 45)
    assert combat.mention_share == pytest.approx(45 / 602)


def test_a_term_clusters_on_share_and_on_count_together() -> None:
    """Real readings for "roguelike" and "souls-like": Hades clusters, Dark
    Souls III does not (the game that defines a kind is rarely called by it),
    and two reviews in a 72-review sample are a share above the floor that
    is still not a cluster."""
    assert term_clusters(77, 602)
    assert not term_clusters(8, 549)
    assert 2 / 72 > 0.02 and not term_clusters(2, 72)
    assert term_clusters(3, 150) and not term_clusters(3, 151)


def test_term_counts_that_cannot_be_a_share_fail_loud() -> None:
    with pytest.raises(ValueError, match="incoherent"):
        term_clusters(5, 4)
    with pytest.raises(ValueError, match="at least one review"):
        term_clusters(0, 0)


# --- reading a request -------------------------------------------------------

_READ = datetime(2026, 11, 14, tzinfo=UTC)
_HADES, _STARDEW, _PORTAL = 1145360, 413150, 620


def _cell(aspect: str, positive: int, negative: int, mixed: int = 0) -> SheetCell:
    counts = _counts(positive, negative, mixed)
    mentions = positive + negative + mixed
    return SheetCell(aspect, mentions, 600, counts, sentiment_group(counts, mentions))


def _game(
    app_id: int,
    *cells: SheetCell,
    categories: tuple[int, ...] = (2,),
    sample_size: int = 600,
) -> LibraryGame:
    return LibraryGame(
        app_id=app_id, name=f"game {app_id}", run_id=f"serve-{app_id}", reported_at=_READ,
        sample_size=sample_size, complete_count=False, labeler="m", cells=cells,
        storefront=StorefrontMetadata(
            app_id=app_id, genres=(StorefrontLabel(1, "Action"),),
            categories=tuple(StorefrontLabel(category, "") for category in categories),
            windows=True, mac=False, linux=False, release_date_text="Sep 17, 2020",
            release_date=date(2020, 9, 17), coming_soon=False, short_description="",
            captured_at=_READ,
        ),
        tags=StorefrontTagCapture(app_id=app_id, tags=(), captured_at=_READ),
    )


def _want(
    target: WantTarget | None,
    firmness: Firmness = Firmness.WANT,
    stance: Stance = Stance.WANTS,
    *,
    partial: bool = False,
) -> Want:
    return Want(words="as the player said it", firmness=firmness, stance=stance, target=target,
                partial=partial)


@pytest.mark.parametrize(
    ("counts", "group", "status"),
    [
        ((41, 4, 0), SentimentGroup.STRONGLY_POSITIVE, WantStatus.MATCHES),
        ((49, 25, 4), SentimentGroup.MOSTLY_POSITIVE, WantStatus.MATCHES),
        ((2, 40, 3), SentimentGroup.CLEARLY_NEGATIVE, WantStatus.FAILS),
        ((50, 50, 0), SentimentGroup.SPLIT, WantStatus.FAILS),
        ((15, 15, 0), SentimentGroup.UNCLEAR, WantStatus.CANNOT_TELL),
        ((7, 0, 0), SentimentGroup.TOO_FEW_MENTIONS, WantStatus.CANNOT_TELL),
    ],
)
def test_an_aspect_want_reads_its_status_off_the_group_and_keeps_the_group(
    counts: tuple[int, int, int], group: SentimentGroup, status: WantStatus
) -> None:
    """Split fails like clearly negative, and the group stays on the reading
    so "opinions are divided" is not worded as "mostly criticised"."""
    reading = aspect_reading("combat", [_cell("combat", *counts)], partial=False)
    assert (reading.status, reading.group) == (status, group)
    assert reading.finding is WantFinding.ASPECT_GROUP


def test_an_aspect_no_review_mentions_reads_as_too_few_mentions() -> None:
    """A report stores no row for an aspect nobody mentioned, so the missing
    cell is zero mentions and not a missing reading."""
    reading = aspect_reading("story", [_cell("combat", 41, 4)], partial=False)
    assert (reading.status, reading.group) == (
        WantStatus.CANNOT_TELL, SentimentGroup.TOO_FEW_MENTIONS,
    )


def test_a_partly_checkable_want_can_fail_and_can_never_match() -> None:
    """ "Runs at 60 fps on my laptop" against ``performance``: praise for how
    a game runs says nothing about one laptop, so only clear criticism counts
    and split opinion is not held against the game."""
    def partial(positive: int, negative: int) -> WantStatus:
        cells = [_cell("performance", positive, negative)]
        return aspect_reading("performance", cells, partial=True).status

    assert partial(41, 4) is WantStatus.CANNOT_TELL
    assert partial(50, 50) is WantStatus.CANNOT_TELL
    assert partial(2, 40) is WantStatus.FAILS


def test_only_a_cluster_is_evidence_for_a_wanted_and_for_an_avoided_term() -> None:
    """Graveyard Keeper's "grind" (81 of 447 reviews, in a library where 98
    of 115 games have a match) fails "not grindy" and would match a player
    who wanted it. A low share decides neither."""
    assert term_reading(Stance.AVOIDS, 81, 447, 98).status is WantStatus.FAILS
    assert term_reading(Stance.WANTS, 81, 447, 98).status is WantStatus.MATCHES
    for stance in (Stance.WANTS, Stance.AVOIDS):
        assert term_reading(stance, 8, 549, 98).status is WantStatus.CANNOT_TELL


def test_a_cannot_tell_on_a_term_says_which_of_three_things_was_found() -> None:
    """ "Timer" appears in 59 library games and "red dress" in none. A game
    with no match is told the first comes up elsewhere and that reviews do
    not go into the second. A game with a few matches has reviews to read:
    seven of Dark Souls III's 549 mention "rpg", in a library where 79 games
    have a match."""
    below = term_reading(Stance.WANTS, 7, 549, 79)
    assert (below.finding, below.hits) == (WantFinding.TERM_BELOW_CLUSTER, 7)
    assert term_reading(Stance.AVOIDS, 0, 549, 59).finding is WantFinding.WRITTEN_ABOUT_ELSEWHERE
    assert term_reading(Stance.WANTS, 0, 549, 0).finding is WantFinding.NOT_WRITTEN_ABOUT
    assert term_reading(Stance.WANTS, 0, 549, WRITTEN_ABOUT_GAMES - 1).finding is (
        WantFinding.NOT_WRITTEN_ABOUT
    )
    assert term_reading(Stance.WANTS, 0, 549, WRITTEN_ABOUT_GAMES).finding is (
        WantFinding.WRITTEN_ABOUT_ELSEWHERE
    )


def test_a_want_with_no_target_is_kept_and_reads_cannot_tell() -> None:
    reading = want_reading(_want(None, Firmness.MUST), _game(_HADES), {})
    assert (reading.status, reading.finding) == (WantStatus.CANNOT_TELL, WantFinding.NO_DATA)


def test_each_kind_of_target_is_read_from_its_own_source() -> None:
    timer = TermTarget(phrases=("timer", "timed"))
    game = _game(_HADES, _cell("story", 60, 5), categories=(2, 38))
    hits = {timer: {_HADES: 30, _STARDEW: 1}}
    assert want_reading(_want(StoreFactTarget("online-co-op")), game, hits).finding is (
        WantFinding.LISTED
    )
    assert want_reading(_want(ReleaseYearsTarget(2020, None)), game, hits).finding is (
        WantFinding.RELEASED_IN_RANGE
    )
    assert want_reading(_want(AspectTarget("story")), game, hits).group is (
        SentimentGroup.STRONGLY_POSITIVE
    )
    avoided = want_reading(_want(timer, stance=Stance.AVOIDS), game, hits)
    assert (avoided.status, avoided.hits) == (WantStatus.FAILS, 30)


def test_wants_that_have_no_meaning_fail_loud() -> None:
    """An aspect says how well a part is received, so it has no avoided form;
    only an aspect can be partly checkable; a term needs its counts."""
    game = _game(_HADES)
    with pytest.raises(ValueError, match="has no avoided form"):
        want_reading(_want(AspectTarget("bugs"), stance=Stance.AVOIDS), game, {})
    with pytest.raises(ValueError, match="only a want on an aspect"):
        want_reading(_want(StoreFactTarget("mac"), partial=True), game, {})
    with pytest.raises(ValueError, match="no hit counts were supplied"):
        want_reading(_want(TermTarget(phrases=("curling",))), game, {})


def test_standing_reads_the_musts_only() -> None:
    """A failed nice-to-have is the judge's to weigh as a near miss. Only a
    must can put a game in conflict or leave it open."""
    must, soft = _want(None, Firmness.MUST), _want(None, Firmness.NICE_TO_HAVE)
    matches = WantReading(WantStatus.MATCHES, WantFinding.LISTED)
    fails = WantReading(WantStatus.FAILS, WantFinding.NOT_LISTED)
    open_ = WantReading(WantStatus.CANNOT_TELL, WantFinding.NO_DATA)
    assert must_standing([must, soft], [matches, fails]) is MustStanding.MEETS
    assert must_standing([must, must], [matches, open_]) is MustStanding.OPEN
    assert must_standing([must, must], [open_, fails]) is MustStanding.CONFLICTS
    assert must_standing([soft], [fails]) is MustStanding.MEETS
    assert must_standing([], []) is MustStanding.MEETS


def _puzzle_request(*named: NamedGame) -> tuple[PlayerRequest, dict[TermTarget, dict[int, int]]]:
    """A puzzle game, nothing with a timer, and it needs online co-op: three
    musts on two kinds of target. The hit counts are made up for the claims
    below and are not library readings."""
    puzzle = TermTarget(phrases=("puzzle", "puzzles"))
    timer = TermTarget(phrases=("timer", "timed", "time limit"))
    request = PlayerRequest(
        intent=RequestIntent.RECOMMEND,
        named_games=named,
        wants=(
            _want(puzzle, Firmness.MUST),
            _want(timer, Firmness.MUST, Stance.AVOIDS),
            _want(StoreFactTarget("online-co-op"), Firmness.MUST),
        ),
    )
    hits = {puzzle: {_PORTAL: 120, _HADES: 2}, timer: {_HADES: 40}}
    return request, hits


def test_the_sheet_keeps_every_game_and_groups_by_standing() -> None:
    """Hades conflicts twice over (no online co-op, "timer" clusters) and
    Stardew Valley once, and both stay on the sheet for the judge: the
    cluster may be reviewers saying there is no timer. Portal 2 meets the
    two musts that can be decided and is open on the third."""
    request, hits = _puzzle_request()
    library = [_game(_HADES), _game(_STARDEW), _game(_PORTAL, categories=(2, 38))]
    sheet = read_sheet(request, library, hits)

    assert [(row.game.app_id, row.standing) for row in sheet.rows] == [
        (_PORTAL, MustStanding.OPEN),
        (_STARDEW, MustStanding.CONFLICTS),
        (_HADES, MustStanding.CONFLICTS),
    ]
    portal = sheet.rows[0]
    assert [reading.status for reading in portal.readings] == [
        WantStatus.MATCHES, WantStatus.CANNOT_TELL, WantStatus.MATCHES,
    ]
    assert portal.readings[1].finding is WantFinding.NOT_WRITTEN_ABOUT
    assert sheet.tallies == (
        WantTally(matches=1, fails=0, cannot_tell=2),
        WantTally(matches=0, fails=1, cannot_tell=2),
        WantTally(matches=1, fails=2, cannot_tell=0),
    )
    assert sheet.already_played == ()


def test_a_game_the_player_already_played_is_the_only_one_left_off() -> None:
    """ "Already played" is the player's instruction, not evidence, so it is
    not weighed. A liked game and an unmeasured one remove nothing."""
    request, hits = _puzzle_request(
        NamedGame("portal 2", _PORTAL, NameMatch.EXACT, NamedGameRole.NOT_THIS, Feeling.UNKNOWN),
        NamedGame("hades", _HADES, NameMatch.EXACT, NamedGameRole.LIKE_THIS, Feeling.LIKED),
        NamedGame(
            "balatro", None, NameMatch.NOT_IN_LIBRARY, NamedGameRole.NOT_THIS, Feeling.UNKNOWN
        ),
    )
    library = [_game(_HADES), _game(_STARDEW), _game(_PORTAL, categories=(2, 38))]
    sheet = read_sheet(request, library, hits)
    assert sorted(row.game.app_id for row in sheet.rows) == [_STARDEW, _HADES]
    assert sheet.already_played == (_PORTAL,)
    assert sheet.tallies[0] == WantTally(matches=0, fails=0, cannot_tell=2)


def test_a_request_with_no_wants_lists_the_whole_library_as_meeting_them() -> None:
    """ "What should I play": nothing to read against, so nothing is ruled
    out and the chat asks."""
    sheet = read_sheet(
        PlayerRequest(intent=RequestIntent.RECOMMEND), [_game(_STARDEW), _game(_HADES)], {}
    )
    assert [row.game.app_id for row in sheet.rows] == [_STARDEW, _HADES]
    assert all(row.standing is MustStanding.MEETS and row.readings == () for row in sheet.rows)
    assert sheet.tallies == ()
