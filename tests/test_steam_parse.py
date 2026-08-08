"""Behavioral claims on the Steam-door parsers — pinned against the real captures.

The fixtures are the probe captures in ``probes/captures/`` — actual Steam
responses saved during the smoke-test and M1-entry probes — so every claim here
is about the wire format as it really is, not as documented: both rollup units,
a real ``past_events`` entry, and the blanked/restored page pair that proved
the off-topic filtering bug. Hand-built payloads appear only for shapes no
capture holds (the ``success == 2`` empty answer, malformed-field failures).
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import cast

import pytest

from steamlens.contracts import RollupUnit
from steamlens.steam_client import (
    QuerySummary,
    ReviewPage,
    SteamResponseError,
    parse_histogram,
    parse_review_page,
    parse_storesearch,
    review_from_raw,
)

_CAPTURES = Path(__file__).resolve().parent.parent / "probes" / "captures"
_FETCHED_AT = datetime(2026, 7, 27, tzinfo=UTC)


def _capture(name: str) -> dict[str, object]:
    return cast(
        "dict[str, object]", json.loads((_CAPTURES / f"{name}.json").read_text(encoding="utf-8"))
    )


# --- histogram: the real captures ----------------------------------------------


def test_old_large_game_rolls_up_by_month() -> None:
    """TF2's lifetime histogram: month rollup, 190 buckets, a 30-day recent strip,
    and no flagged events — with the first bucket's epoch landing as aware UTC."""
    snapshot = parse_histogram(_capture("histogram_old_large_440"), 440, _FETCHED_AT)
    assert snapshot.rollup_unit is RollupUnit.MONTH
    assert len(snapshot.rollups) == 190
    assert len(snapshot.recent_daily) == 30
    assert snapshot.past_events == ()
    first = snapshot.rollups[0]
    assert first.start == datetime(2010, 10, 1, tzinfo=UTC)
    assert (first.recommendations_up, first.recommendations_down) == (52, 1)
    assert snapshot.fetched_at is _FETCHED_AT


def test_recent_game_rolls_up_by_week() -> None:
    """A young game's histogram arrives in weeks — the unit is read, never assumed."""
    snapshot = parse_histogram(_capture("histogram_recent_4704690"), 4704690, _FETCHED_AT)
    assert snapshot.rollup_unit is RollupUnit.WEEK


def test_flagged_game_carries_its_past_events() -> None:
    """Borderlands 2's histogram carries the real review-bomb window Steam flagged
    — the exact window the blank/restore live smoke replays."""
    snapshot = parse_histogram(_capture("offtopic_hist_include_offtopic"), 49520, _FETCHED_AT)
    assert len(snapshot.past_events) >= 1
    event = snapshot.past_events[0]
    assert event.start == datetime(2019, 4, 3, tzinfo=UTC)
    assert event.end == datetime(2019, 4, 15, tzinfo=UTC)
    assert event.event_type == 0


# --- review pages: the real captures -------------------------------------------


def test_blanked_and_restored_pair() -> None:
    """The proven data-integrity bug, visible in the fixtures: the same window
    yields zero reviews under a default fetch and a full page with
    ``filter_offtopic_activity=0`` — and the blanked page even zeroes its totals."""
    blanked = parse_review_page(_capture("offtopic_reviews_default"), 49520)
    restored = parse_review_page(_capture("offtopic_reviews_include_offtopic"), 49520)
    assert (blanked.success, restored.success) == (1, 1)
    assert blanked.reviews == ()
    assert blanked.summary == QuerySummary(0, 0, 0)
    assert len(restored.reviews) == 100


def test_windowed_page_parses_reviews_and_summary() -> None:
    """A real windowed-unfiltered page: 100 reviews into the contract (aware
    timestamps, caller's app_id stamped) and the window-scoped totals captured."""
    page = parse_review_page(_capture("defaultwalk_windowed_unfiltered_236850"), 236850)
    assert page.success == 1
    assert page.summary == QuerySummary(total_reviews=1892, total_positive=881, total_negative=1011)
    assert page.cursor
    assert len(page.reviews) == 100
    first = page.reviews[0]
    assert first.app_id == 236850
    assert first.review_id
    assert first.created_at.tzinfo is not None
    assert first.text


# --- shapes no capture holds ---------------------------------------------------


def test_success_2_empty_answer_is_a_page_not_an_error() -> None:
    """Steam's "no result" answer parses clean: the walk judges what it means."""
    page = parse_review_page({"success": 2}, 440)
    assert page == ReviewPage(success=2, cursor=None, summary=None, reviews=())


def test_review_field_failures_name_the_position() -> None:
    """A bad review object fails loud with its page position, as the typed door
    error — not a bare ValueError from the shared record parser."""
    payload: dict[str, object] = {
        "success": 1,
        "reviews": [{"recommendationid": "", "language": "english"}],
    }
    with pytest.raises(SteamResponseError, match=r"reviews\[0\]"):
        parse_review_page(payload, 440)


def test_degenerate_later_page_summary_is_no_summary() -> None:
    """Later pages send query_summary as a num_reviews-only stub — observed on
    the live wire (2026-07-27), where the donor lore said the field is absent.
    That's no summary, not shape damage; a half-formed totals block still is."""
    page = parse_review_page({"success": 1, "query_summary": {"num_reviews": 0}}, 440)
    assert page.summary is None
    half_formed: dict[str, object] = {
        "success": 1,
        "query_summary": {"num_reviews": 0, "total_reviews": 5},
    }
    with pytest.raises(SteamResponseError, match="total_positive"):
        parse_review_page(half_formed, 440)


def test_bool_cannot_pass_as_integer() -> None:
    """``True`` is an ``int`` to Python; the boundary refuses the masquerade."""
    with pytest.raises(SteamResponseError, match="success is True"):
        parse_review_page({"success": True}, 440)


def test_unrecognized_rollup_unit_fails_loud() -> None:
    """A third rollup unit would be new wire knowledge — surfaced, never guessed."""
    payload: dict[str, object] = {
        "success": 1,
        "results": {"rollup_type": "day", "rollups": [], "recent": []},
    }
    with pytest.raises(SteamResponseError, match="unrecognized rollup_type 'day'"):
        parse_histogram(payload, 440, _FETCHED_AT)


def test_histogram_missing_bucket_series_fails_loud() -> None:
    """The rollup series is not optional — an absent list is damage, not emptiness."""
    payload: dict[str, object] = {
        "success": 1,
        "results": {"rollup_type": "month", "recent": []},
    }
    with pytest.raises(SteamResponseError, match="expected a list"):
        parse_histogram(payload, 440, _FETCHED_AT)


# --- review_from_raw: one review object across the boundary ---------------------


def _raw_review(**overrides: object) -> dict[str, object]:
    record: dict[str, object] = {
        "recommendationid": "227797385",
        "language": "english",
        "review": "Great gunplay, terrible servers.",
        "timestamp_created": 1_781_279_000,
        "voted_up": True,
    }
    record.update(overrides)
    return record


def test_review_from_raw_maps_fields() -> None:
    """The conversion: id verbatim, epoch to aware UTC, verdict preserved."""
    review = review_from_raw(_raw_review(voted_up=False), app_id=440)
    assert review.review_id == "227797385"
    assert review.app_id == 440
    assert review.created_at == datetime.fromtimestamp(1_781_279_000, tz=UTC)
    assert review.created_at.tzinfo is not None
    assert review.language == "english"
    assert review.voted_up is False


@pytest.mark.parametrize(
    ("overrides", "match"),
    [
        ({"recommendationid": None}, "recommendationid"),
        ({"recommendationid": ""}, "recommendationid"),
        ({"timestamp_created": "1781279000"}, "timestamp_created"),
        ({"timestamp_created": True}, "timestamp_created"),  # bool is not an epoch
        ({"voted_up": 1}, "voted_up"),
        ({"review": None}, "review text"),
    ],
)
def test_review_from_raw_fails_loud(overrides: dict[str, object], match: str) -> None:
    """A mistyped field in a frozen-corpus record is damage, not a skippable row."""
    with pytest.raises(ValueError, match=match):
        review_from_raw(_raw_review(**overrides), app_id=440)


# --- storesearch: the real captures ---------------------------------------------


def _storesearch_body(term: str) -> dict[str, object]:
    """The captured storesearch response for ``term`` (the probe stores a list
    of per-term reports, each embedding its raw body)."""
    reports = cast(
        "list[dict[str, object]]",
        json.loads((_CAPTURES / "storesearch_summary.json").read_text(encoding="utf-8")),
    )
    for report in reports:
        if report["term"] == term:
            return cast("dict[str, object]", report["body"])
    raise AssertionError(f"no capture for term {term!r}")


def test_storesearch_resolves_the_canonical_name_first() -> None:
    """TF2's capture: the expected game arrives as the first hit with its id,
    display name, and a CDN capsule URL — the row the search page renders."""
    hits = parse_storesearch(_storesearch_body("team fortress"))
    first = hits[0]
    assert first.app_id == 440
    assert first.name == "Team Fortress 2"
    assert first.capsule_url.startswith("https://")


def test_storesearch_drops_bundles_keeps_apps() -> None:
    """The Witcher capture carries a ``sub``-type Complete Edition bundle — a
    sub id is not an app id, so it must not become a pickable hit, while the
    base game and its ``app``-type DLC rows all pass through."""
    hits = parse_storesearch(_storesearch_body("witcher 3"))
    ids = [hit.app_id for hit in hits]
    assert 292030 in ids
    assert 124923 not in ids  # the 'sub' bundle
    assert len(hits) < 10  # something was actually dropped from the 10 raw items


def test_storesearch_unknown_term_is_an_empty_answer() -> None:
    """Steam answers a garbage term with ``total: 0, items: []`` — an empty
    tuple, not an error; and a body missing ``items`` entirely parses the
    same way (the optional-list rule)."""
    assert parse_storesearch(_storesearch_body("qzxqzxqzx no such game")) == ()
    assert parse_storesearch({"total": 0}) == ()


def test_storesearch_malformed_item_fails_loud() -> None:
    """A mistyped id or a missing name is Steam misbehaving, named by position."""
    with pytest.raises(SteamResponseError, match=r"items\[0\]"):
        parse_storesearch({"items": [{"type": "app", "name": "X", "tiny_image": "u", "id": "440"}]})
    with pytest.raises(SteamResponseError, match="name"):
        parse_storesearch({"items": [{"type": "app", "id": 440, "tiny_image": "u"}]})
