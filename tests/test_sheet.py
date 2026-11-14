"""Behavioral claims on the sheet's group rule — real cells from the library, and the edges.

The named cases are combat readings from the serving database copy of
2026-11-14, the ones DESIGN's sheet section argues from: the two positive
tiers have to separate Hades from Dying Light 2, and the game with the worst
combat in the library has to land in "split" because mixed mentions sit in
the denominator. The edge cases pin the floor and the two ways a cell can
fail to say anything.
"""

from __future__ import annotations

import pytest

from steamlens.contracts import (
    AspectAggregate,
    AspectSlot,
    ClassifierVersions,
    SentimentCounts,
    SentimentGroup,
)
from steamlens.core.sheet import MENTION_FLOOR, sentiment_group, sheet_cells, term_clusters


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
