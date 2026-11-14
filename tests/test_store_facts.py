"""Behavioral claims on the store-fact vocabulary — three ways a missing fact reads.

The cases are library games as the store described them on 2026-11-14, cut
down to the rows each claim needs. A play mode the store does not list is the
store's answer. A feature it does not list says nothing. A genre it does not
list is a failure only when no player tag speaks for the game, which is what
keeps Dark Souls III on the sheet for a player who asked for an RPG.
"""

from __future__ import annotations

from datetime import UTC, date, datetime

import pytest

from steamlens.contracts import (
    ReleaseYearsTarget,
    Stance,
    StoreFactSource,
    StorefrontLabel,
    StorefrontMetadata,
    StorefrontTag,
    StorefrontTagCapture,
    WantFinding,
    WantStatus,
)
from steamlens.core.store_facts import (
    STORE_FACTS,
    release_years_reading,
    store_fact,
    store_fact_reading,
)

_READ = datetime(2026, 11, 14, tzinfo=UTC)
_ACTION = StorefrontLabel(1, "Action")
_RPG = StorefrontLabel(3, "RPG")
_RACING = StorefrontLabel(9, "Racing")
_SINGLE = StorefrontLabel(2, "Single-player")
_ONLINE_COOP = StorefrontLabel(38, "Online Co-op")
_IN_APP = StorefrontLabel(35, "In-App Purchases")


def _game(
    *,
    genres: tuple[StorefrontLabel, ...] = (_ACTION,),
    categories: tuple[StorefrontLabel, ...] = (_SINGLE,),
    mac: bool = False,
    released: date | None = date(2016, 4, 11),
) -> StorefrontMetadata:
    return StorefrontMetadata(
        app_id=374320, genres=genres, categories=categories,
        windows=True, mac=mac, linux=False,
        release_date_text=None if released is None else f"{released:%b %d, %Y}",
        release_date=released, coming_soon=False, short_description="", captured_at=_READ,
    )


def _tags(*names: str) -> StorefrontTagCapture:
    return StorefrontTagCapture(
        app_id=374320,
        tags=tuple(StorefrontTag(tag_id=index, name=name, count=100) for index, name in
                   enumerate(names)),
        captured_at=_READ,
    )


def _read(
    key: str, stance: Stance, game: StorefrontMetadata | None,
    tags: StorefrontTagCapture | None = None,
) -> tuple[WantStatus, WantFinding]:
    """Status and finding for ``key``; a game given no tags has a tag block with none in it."""
    captured = tags if tags is not None else _tags()
    reading = store_fact_reading(store_fact(key), stance, game, captured)
    return reading.status, reading.finding


def test_a_listed_fact_decides_for_the_player_who_wants_it_and_against_the_one_who_avoids_it(
) -> None:
    game = _game(categories=(_SINGLE, _ONLINE_COOP, _IN_APP))
    assert _read("online-co-op", Stance.WANTS, game) == (WantStatus.MATCHES, WantFinding.LISTED)
    assert _read("online-co-op", Stance.AVOIDS, game) == (WantStatus.FAILS, WantFinding.LISTED)
    assert _read("in-app-purchases", Stance.AVOIDS, game) == (
        WantStatus.FAILS, WantFinding.LISTED,
    )


def test_a_play_mode_the_store_does_not_list_is_the_stores_answer() -> None:
    """Every game declares its play modes, so a single-player game fails a
    want for online co-op and satisfies a player avoiding it."""
    game = _game()
    assert _read("online-co-op", Stance.WANTS, game) == (
        WantStatus.FAILS, WantFinding.NOT_LISTED,
    )
    assert _read("online-co-op", Stance.AVOIDS, game) == (
        WantStatus.MATCHES, WantFinding.NOT_LISTED,
    )
    assert _read("mac", Stance.WANTS, game) == (WantStatus.FAILS, WantFinding.NOT_LISTED)
    assert _read("mac", Stance.WANTS, _game(mac=True)) == (
        WantStatus.MATCHES, WantFinding.LISTED,
    )


def test_a_feature_the_store_does_not_list_says_nothing_either_way() -> None:
    """Hades and both Civilization games have difficulty settings and declare
    no "Adjustable Difficulty". Absence cannot count against a wanted
    feature, and it cannot clear an avoided one."""
    game = _game()
    for stance in (Stance.WANTS, Stance.AVOIDS):
        assert _read("adjustable-difficulty", stance, game) == (
            WantStatus.CANNOT_TELL, WantFinding.NOT_DECLARED,
        )


def test_a_genre_players_tag_and_the_store_does_not_list_is_cannot_tell() -> None:
    """Dark Souls III: the store lists Action, players tag RPG and Action RPG.
    A must on "an RPG" would otherwise drop it with no one to notice."""
    dark_souls = _game(genres=(_ACTION,))
    tagged = _tags("Souls-like", "Dark Fantasy", "RPG", "Action RPG")
    for stance in (Stance.WANTS, Stance.AVOIDS):
        assert _read("rpg", stance, dark_souls, tagged) == (
            WantStatus.CANNOT_TELL, WantFinding.TAGGED_NOT_LISTED,
        )


def test_a_tag_never_makes_a_match_and_a_listed_genre_needs_no_tag() -> None:
    """Mad Max is tagged Racing and is not a racing game, so the tag only
    withholds the failure. A game the store lists matches whatever its tags."""
    mad_max = _game(genres=(_ACTION,))
    assert _read("racing", Stance.WANTS, mad_max, _tags("Open World", "Racing"))[0] is (
        WantStatus.CANNOT_TELL
    )
    listed = _game(genres=(_RACING,))
    assert _read("racing", Stance.WANTS, listed, _tags("Open World")) == (
        WantStatus.MATCHES, WantFinding.LISTED,
    )


def test_a_genre_with_no_listing_and_no_tag_fails() -> None:
    """Stardew Valley for a racing request: neither source speaks for it."""
    stardew = _game(genres=(_RPG,))
    assert _read("racing", Stance.WANTS, stardew, _tags("Farming Sim", "Life Sim")) == (
        WantStatus.FAILS, WantFinding.NOT_LISTED,
    )
    assert _read("racing", Stance.AVOIDS, stardew, _tags("Farming Sim"))[0] is WantStatus.MATCHES


def test_a_genre_is_not_failed_on_tags_that_were_never_read() -> None:
    """A store page without a tag block is recorded as nothing read. Failing
    the genre there would treat a missing capture as a game without tags."""
    reading = store_fact_reading(store_fact("rpg"), Stance.WANTS, _game(), None)
    assert (reading.status, reading.finding) == (
        WantStatus.CANNOT_TELL, WantFinding.TAGS_NOT_READ,
    )
    # A play mode carries no tags, so an unread tag block does not soften it.
    reading = store_fact_reading(store_fact("online-co-op"), Stance.WANTS, _game(), None)
    assert reading.status is WantStatus.FAILS


def test_early_access_is_read_from_the_genre_row_and_not_from_the_lingering_tag() -> None:
    """Ten library games carried the "Early Access" tag and four were in
    early access: the tag outlives the status, so it is not consulted."""
    left_early_access = _game(genres=(_ACTION,))
    assert _read("early-access", Stance.WANTS, left_early_access, _tags("Early Access")) == (
        WantStatus.FAILS, WantFinding.NOT_LISTED,
    )
    in_early_access = _game(genres=(_ACTION, StorefrontLabel(70, "Early Access")))
    assert _read("early-access", Stance.AVOIDS, in_early_access)[0] is WantStatus.FAILS


def test_a_game_with_no_stored_store_facts_is_cannot_tell_on_every_fact() -> None:
    for key in ("rpg", "online-co-op", "mac", "adjustable-difficulty"):
        assert _read(key, Stance.WANTS, None) == (
            WantStatus.CANNOT_TELL, WantFinding.NO_STORE_FACTS,
        )


@pytest.mark.parametrize(
    ("first", "last", "status", "finding"),
    [
        (2015, None, WantStatus.MATCHES, WantFinding.RELEASED_IN_RANGE),
        (2016, 2016, WantStatus.MATCHES, WantFinding.RELEASED_IN_RANGE),
        (2017, None, WantStatus.FAILS, WantFinding.RELEASED_OUTSIDE_RANGE),
        (None, 2015, WantStatus.FAILS, WantFinding.RELEASED_OUTSIDE_RANGE),
        (2010, 2019, WantStatus.MATCHES, WantFinding.RELEASED_IN_RANGE),
    ],
)
def test_a_release_year_range_is_inclusive_and_open_at_either_end(
    first: int | None, last: int | None, status: WantStatus, finding: WantFinding
) -> None:
    reading = release_years_reading(ReleaseYearsTarget(first, last), Stance.WANTS, _game())
    assert (reading.status, reading.finding) == (status, finding)


def test_an_avoided_release_range_reads_the_other_way() -> None:
    """ "Nothing older than 2015" said as an avoided range up to 2014."""
    old = _game(released=date(2010, 9, 21))
    target = ReleaseYearsTarget(None, 2014)
    assert release_years_reading(target, Stance.AVOIDS, old).status is WantStatus.FAILS
    assert release_years_reading(target, Stance.AVOIDS, _game()).status is WantStatus.MATCHES


def test_a_game_without_a_full_release_date_is_cannot_tell() -> None:
    """Kingdoms of Amalur holds no parsed date in the library."""
    reading = release_years_reading(
        ReleaseYearsTarget(2010, None), Stance.WANTS, _game(released=None)
    )
    assert (reading.status, reading.finding) == (
        WantStatus.CANNOT_TELL, WantFinding.NO_RELEASE_DATE,
    )
    assert release_years_reading(ReleaseYearsTarget(2010, None), Stance.WANTS, None).finding is (
        WantFinding.NO_STORE_FACTS
    )


def test_a_range_that_names_no_years_fails_loud() -> None:
    with pytest.raises(ValueError, match="needs a first or a last year"):
        release_years_reading(ReleaseYearsTarget(None, None), Stance.WANTS, _game())
    with pytest.raises(ValueError, match="from 2020 to 2010"):
        release_years_reading(ReleaseYearsTarget(2020, 2010), Stance.WANTS, _game())


def test_an_unknown_key_fails_loud_and_names_the_vocabulary() -> None:
    with pytest.raises(ValueError, match="no store fact is named 'roguelike'"):
        store_fact("roguelike")


def test_the_vocabulary_is_coherent() -> None:
    """Keys are unique, a genre or category names at least one store id, a
    platform names none, and only complete genres carry player tags: a tag
    softens a failure, and a fact declared by choice has no failure to soften."""
    keys = [fact.key for fact in STORE_FACTS]
    assert len(keys) == len(set(keys))
    for fact in STORE_FACTS:
        by_id = fact.source in (StoreFactSource.GENRE, StoreFactSource.CATEGORY)
        assert bool(fact.ids) == by_id, fact.key
        if fact.player_tags:
            assert fact.source is StoreFactSource.GENRE and fact.complete, fact.key
    ids = [(fact.source, store_id) for fact in STORE_FACTS for store_id in fact.ids]
    assert len(ids) == len(set(ids))
