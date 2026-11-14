"""Behavioral claims on the storefront reads — pinned against the probe's capture.

The fixtures are the thirteen library games ``probes/store_metadata_probe.py``
read on 2026-11-14: each game's whole appdetails answer and the text of its
store page's tag call, as Steam sent them. They were picked for the awkward
cases (mature content, early access and after it, no longer sold, two category
ids under one description), so the claims here are about the wire as it is.
Hand-built payloads appear only for shapes no capture holds. The door tests
script the wire through ``httpx.MockTransport``.
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any, cast

import httpx
import pytest
from fakes import NullSink

from steamlens.contracts import StorefrontLabel, StorefrontTag
from steamlens.steam_client import (
    SteamClient,
    SteamClientConfig,
    SteamResponseError,
    SteamTransport,
    parse_storefront_metadata,
    parse_storefront_tags,
)

_CAPTURE = (
    Path(__file__).resolve().parent.parent
    / "probes" / "captures" / "store_metadata_20261114T152131Z.json"
)
_GAMES: dict[int, dict[str, Any]] = {
    game["app_id"]: game
    for game in json.loads(_CAPTURE.read_text(encoding="utf-8"))["games"]
}
_AT = datetime(2026, 11, 14, 15, 21, tzinfo=UTC)

_HADES = 1145360
_DOOM_ETERNAL = 782330
_GTA_V_ENHANCED = 3240220
_FIFA_22 = 1506830
_PALWORLD = 1623730
_LETHAL_COMPANY = 1966720
_SOLASTA_II = 2975950


def _details(app_id: int) -> dict[str, object]:
    return cast("dict[str, object]", _GAMES[app_id]["appdetails"]["body"])


def _tag_call(app_id: int) -> str:
    return cast("str", _GAMES[app_id]["tags"]["no_cookies"]["tag_call_text"])


def _hand_built(data: dict[str, object] | None = None) -> dict[str, object]:
    """A minimal appdetails answer for app 440: platforms present, the rest per test."""
    base: dict[str, object] = {"platforms": {"windows": True, "mac": False, "linux": False}}
    return {"440": {"success": True, "data": {**base, **(data or {})}}}


# --- metadata: the real captures -------------------------------------------------


def test_hades_reads_whole() -> None:
    """Genre ids arrive as strings and leave as integers, in the store's order;
    the display date becomes a calendar date with its text kept."""
    hades = parse_storefront_metadata(_details(_HADES), _HADES, _AT)
    assert hades is not None
    assert hades.genres == (
        StorefrontLabel(1, "Action"), StorefrontLabel(23, "Indie"), StorefrontLabel(3, "RPG"),
    )
    assert len(hades.categories) == 10
    assert hades.categories[0].description == "Single-player"
    assert (hades.windows, hades.mac, hades.linux) == (True, True, False)
    assert hades.release_date_text == "Sep 17, 2020"
    assert hades.release_date == date(2020, 9, 17)
    assert not hades.coming_soon
    assert len(hades.short_description) == 155
    assert hades.captured_at is _AT


@pytest.mark.parametrize("app_id", sorted(_GAMES))
def test_every_captured_game_parses_with_a_full_date(app_id: int) -> None:
    """All thirteen, including the two whose ``required_age`` is a string and
    the two no longer sold: none of the wire's variation reaches the fields
    the filters read."""
    metadata = parse_storefront_metadata(_details(app_id), app_id, _AT)
    assert metadata is not None
    assert metadata.genres and metadata.categories
    assert metadata.release_date is not None
    assert metadata.windows


def test_two_category_ids_can_share_one_description() -> None:
    """The reason filters compare ids: the store lists DualSense support twice."""
    gta = parse_storefront_metadata(_details(_GTA_V_ENHANCED), _GTA_V_ENHANCED, _AT)
    assert gta is not None
    dualsense = [c.id for c in gta.categories if c.description == "DualSense Controller Support"]
    assert dualsense == [57, 58]


def test_early_access_is_the_genre_row_and_ends_with_it() -> None:
    """A game in early access carries the genre and its early access launch
    date; one that has left carries neither the genre nor that date."""
    lethal = parse_storefront_metadata(_details(_LETHAL_COMPANY), _LETHAL_COMPANY, _AT)
    palworld = parse_storefront_metadata(_details(_PALWORLD), _PALWORLD, _AT)
    assert lethal is not None and palworld is not None
    assert lethal.in_early_access
    assert lethal.release_date == date(2023, 10, 23)
    assert not palworld.in_early_access
    assert palworld.release_date == date(2026, 7, 9)


def test_a_game_no_longer_sold_still_answers() -> None:
    fifa = parse_storefront_metadata(_details(_FIFA_22), _FIFA_22, _AT)
    assert fifa is not None
    assert [g.description for g in fifa.genres] == ["Simulation", "Sports"]


# --- metadata: shapes no capture holds -------------------------------------------


def test_no_data_is_none_like_the_name_read() -> None:
    assert parse_storefront_metadata({"224060": {"success": False}}, 224060, _AT) is None
    assert parse_storefront_metadata({"224060": None}, 224060, _AT) is None


def test_absent_optional_fields_parse_as_empty() -> None:
    """A game may honestly have no genres, categories, date or description."""
    bare = parse_storefront_metadata(_hand_built(), 440, _AT)
    assert bare is not None
    assert (bare.genres, bare.categories) == ((), ())
    assert (bare.release_date_text, bare.release_date, bare.coming_soon) == (None, None, False)
    assert bare.short_description == ""


@pytest.mark.parametrize("text", ["Coming soon", "2027", "Q2 2027", "To be announced"])
def test_a_release_text_that_is_not_a_date_is_kept_as_text(text: str) -> None:
    payload = _hand_built({"release_date": {"coming_soon": True, "date": text}})
    unreleased = parse_storefront_metadata(payload, 440, _AT)
    assert unreleased is not None
    assert (unreleased.release_date_text, unreleased.release_date) == (text, None)
    assert unreleased.coming_soon


def test_the_day_first_date_form_reads_too() -> None:
    payload = _hand_built({"release_date": {"coming_soon": False, "date": "17 Sep, 2020"}})
    metadata = parse_storefront_metadata(payload, 440, _AT)
    assert metadata is not None and metadata.release_date == date(2020, 9, 17)


def test_missing_platforms_fails_loud() -> None:
    """A platform flag has no honest default, so absence is damage here."""
    with pytest.raises(SteamResponseError, match="platforms"):
        parse_storefront_metadata({"440": {"success": True, "data": {"name": "X"}}}, 440, _AT)
    with pytest.raises(SteamResponseError, match="mac"):
        parse_storefront_metadata(
            {"440": {"success": True, "data": {"platforms": {"windows": True, "linux": False}}}},
            440, _AT,
        )


@pytest.mark.parametrize(
    ("data", "match"),
    [
        ({"genres": [{"id": "racing", "description": "Racing"}]}, r"genres\[0\].*id"),
        ({"genres": [{"id": True, "description": "Racing"}]}, r"genres\[0\].*id"),
        ({"categories": [{"id": 9}]}, r"categories\[0\].*description"),
        ({"genres": "Racing"}, "genres"),
        ({"short_description": 7}, "short_description"),
        ({"release_date": {"coming_soon": "no", "date": "Sep 17, 2020"}}, "coming_soon"),
    ],
)
def test_a_mistyped_field_fails_loud_naming_it(data: dict[str, object], match: str) -> None:
    with pytest.raises(SteamResponseError, match=match):
        parse_storefront_metadata(_hand_built(data), 440, _AT)


# --- tags: the real captures -----------------------------------------------------


def test_hades_tags_in_page_order() -> None:
    capture = parse_storefront_tags(_tag_call(_HADES), _HADES, _AT)
    assert capture is not None
    assert len(capture.tags) == 20
    assert capture.tags[0] == StorefrontTag(tag_id=42804, name="Action Roguelike", count=1466)
    assert (capture.tags[-1].name, capture.tags[-1].count) == ("Perma Death", 113)
    assert capture.captured_at is _AT


@pytest.mark.parametrize("app_id", sorted(_GAMES))
def test_every_captured_page_carries_twenty_tags_by_descending_count(app_id: int) -> None:
    capture = parse_storefront_tags(_tag_call(app_id), app_id, _AT)
    assert capture is not None
    counts = [tag.count for tag in capture.tags]
    assert len(counts) == 20
    assert counts == sorted(counts, reverse=True)


def test_a_row_without_browseable_parses() -> None:
    """Solasta II's first tag lacks the field every other probed row carries."""
    capture = parse_storefront_tags(_tag_call(_SOLASTA_II), _SOLASTA_II, _AT)
    assert capture is not None
    assert (capture.tags[0].name, capture.tags[0].count) == ("Early Access", 564)


# --- tags: shapes no capture holds -----------------------------------------------


def test_a_page_without_the_tag_call_is_none_and_an_empty_array_is_not() -> None:
    """"Nothing was read" (a gate in place of the page) differs from a page
    whose game has no tags yet."""
    assert parse_storefront_tags("<html>Please enter your birth date</html>", 440, _AT) is None
    empty = parse_storefront_tags("InitAppTagModal( 440, [], [], 'x' );", 440, _AT)
    assert empty is not None and empty.tags == ()


def test_a_tag_call_for_another_game_fails_loud() -> None:
    with pytest.raises(SteamResponseError, match="for app 570, expected 440"):
        parse_storefront_tags('InitAppTagModal( 570, [{"tagid":1,"name":"A","count":2}],', 440, _AT)


def test_a_malformed_tag_array_or_row_fails_loud() -> None:
    with pytest.raises(SteamResponseError, match="does not decode"):
        parse_storefront_tags('InitAppTagModal( 440, [{"tagid":1,"name":', 440, _AT)
    with pytest.raises(SteamResponseError, match=r"\[440\]\[1\].*count"):
        parse_storefront_tags(
            'InitAppTagModal( 440, [{"tagid":1,"name":"A","count":2},{"tagid":2,"name":"B"}],',
            440, _AT,
        )


# --- the door: what reaches Steam, and what comes back ---------------------------


class Harness:
    """One client over a scripted response sequence, requests recorded, clock fixed."""

    def __init__(self, script: list[httpx.Response]) -> None:
        self.requests: list[httpx.Request] = []
        feed: Iterator[httpx.Response] = iter(script)

        def handler(request: httpx.Request) -> httpx.Response:
            self.requests.append(request)
            return next(feed)

        self.client = SteamClient(
            SteamTransport(
                SteamClientConfig(),
                NullSink(),
                transport=httpx.MockTransport(handler),
                sleep=lambda _: None,
                monotonic=lambda: 100.0,
            ),
            now=lambda: _AT,
        )


def test_storefront_metadata_is_one_appdetails_read_stamped_with_the_clock() -> None:
    h = Harness([httpx.Response(200, text=json.dumps(_details(_HADES)))])
    metadata = h.client.storefront_metadata(_HADES)
    assert metadata is not None and metadata.captured_at == _AT
    assert len(h.requests) == 1
    url = h.requests[0].url
    assert url.path == "/api/appdetails"
    assert dict(url.params) == {"appids": str(_HADES), "cc": "us", "l": "english"}


def test_storefront_tags_reads_the_default_page_first_and_stops_there() -> None:
    """No country is sent: the US store puts mature-content games behind an
    age check, and the store's default page for the caller does not."""
    page = f"<html><script>{_tag_call(_DOOM_ETERNAL)} [] );</script></html>"
    h = Harness([httpx.Response(200, text=page)])
    capture = h.client.storefront_tags(_DOOM_ETERNAL)
    assert capture is not None and capture.tags[0].name == "Gore"
    assert capture.captured_at == _AT
    url = h.requests[0].url
    assert (url.host, url.path) == ("store.steampowered.com", f"/app/{_DOOM_ETERNAL}/")
    assert dict(url.params) == {"l": "english"}
    assert len(h.requests) == 1


def test_a_page_without_tags_falls_back_to_the_us_page_once() -> None:
    """A game not sold in the caller's country answers an error page with no
    tag block; its US page is then asked for, and that answer stands."""
    site_error = httpx.Response(200, text="<html><title>Site Error</title></html>")
    us_page = httpx.Response(200, text=f"<script>{_tag_call(_HADES)} [] );</script>")
    h = Harness([site_error, us_page])
    capture = h.client.storefront_tags(_HADES)
    assert capture is not None and len(capture.tags) == 20
    assert [dict(request.url.params) for request in h.requests] == [
        {"l": "english"},
        {"cc": "us", "l": "english"},
    ]


def test_the_us_age_check_is_not_worked_around() -> None:
    """Unavailable here and behind the age check there: the redirect is not
    followed, no cookie is sent, and the read fails loud for the capture to
    absorb."""
    site_error = httpx.Response(200, text="<html><title>Site Error</title></html>")
    age_check = httpx.Response(
        302, headers={"location": "https://store.steampowered.com/agecheck/app/782330/"}
    )
    h = Harness([site_error, age_check])
    with pytest.raises(SteamResponseError, match="HTTP 302"):
        h.client.storefront_tags(_DOOM_ETERNAL)
    assert len(h.requests) == 2
    assert all("cookie" not in request.headers for request in h.requests)


def test_a_gate_page_answers_none_and_a_redirect_fails_loud() -> None:
    """A 200 that is not the game's page read nothing, from either country; a
    redirect did not answer for the game at all, and following it would read
    another page."""
    no_tags = httpx.Response(200, text="<html>no tag block here</html>")
    gated = Harness([no_tags, no_tags])
    assert gated.client.storefront_tags(_DOOM_ETERNAL) is None
    assert len(gated.requests) == 2

    moved = Harness([httpx.Response(302, headers={"location": "https://store.steampowered.com/"})])
    with pytest.raises(SteamResponseError, match="HTTP 302"):
        moved.client.storefront_tags(224060)
    assert len(moved.requests) == 1, "the redirect is not followed"
