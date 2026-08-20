"""Behavioral claims on resolve — the identity guard's rules and the two-read op.

The guard tests pin the normalization order (the trademark-before-NFKD trap),
the match threshold's intent (decoration washes out, identity doesn't), and
the edition-prefix rule with its one-token refusal. The operation tests script
the wire through ``httpx.MockTransport`` and assert what actually reaches
Steam — the appdetails params and the totals-only read with the unfiltered
trio plus the off-topic restore flag.
"""

from __future__ import annotations

import json
from collections.abc import Iterator

import httpx
import pytest
from fakes import NullSink

from steamlens.contracts import IdentityVerdict
from steamlens.steam_client import (
    AppDetails,
    SteamClient,
    SteamClientConfig,
    SteamResponseError,
    SteamTransport,
    identity_verdict,
    normalize_name,
    parse_appdetails,
)


class Harness:
    """One client over a scripted response sequence, requests recorded."""

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
            )
        )


def _details_body(app_id: int, name: str, header_image: str | None = None) -> str:
    data: dict[str, str] = {"name": name}
    if header_image is not None:
        data["header_image"] = header_image
    return json.dumps({str(app_id): {"success": True, "data": data}})


def _totals_body(total: int, positive: int, negative: int) -> str:
    return json.dumps(
        {
            "success": 1,
            "query_summary": {
                "num_reviews": 0,
                "total_reviews": total,
                "total_positive": positive,
                "total_negative": negative,
            },
        }
    )


# --- normalization -------------------------------------------------------------


def test_normalization_washes_out_decoration() -> None:
    """Case, punctuation, accents, and trademark glyphs are not identity."""
    assert normalize_name("Half-Life 2: Episode Two™") == "half life 2 episode two"
    assert normalize_name("POKÉMON") == "pokemon"


def test_trademark_glyphs_strip_before_nfkd() -> None:
    """NFKD decomposes ™ to the letters "tm" — stripped first, or the name
    would grow a phantom token and matching would quietly degrade."""
    assert normalize_name("Rust™") == "rust"
    assert normalize_name("Game℠") == "game"


# --- the verdict rules ---------------------------------------------------------


def test_decorated_name_is_ok() -> None:
    """The store decorating a name with ® and casing is the same game."""
    verdict = identity_verdict("The Witcher 3: Wild Hunt", "The Witcher® 3: Wild Hunt")
    assert verdict is IdentityVerdict.OK


def test_edition_suffix_is_ok_via_the_prefix_rule() -> None:
    """"Half-Life 2" resolving to "Half-Life 2 Episode Two" extends the
    expectation the way editions do — below the ratio bar, caught by the
    prefix rule."""
    verdict = identity_verdict("Half-Life 2", "Half-Life 2: Episode Two")
    assert verdict is IdentityVerdict.OK


def test_one_token_expectation_refuses_the_prefix_rule() -> None:
    """"Rust" must not prefix-match an unrelated game that merely starts with
    the word — the rule demands at least two expected tokens."""
    assert identity_verdict("Rust", "Rust Belt Simulator") is IdentityVerdict.MISMATCH


def test_unrelated_game_is_a_mismatch() -> None:
    assert identity_verdict("Portal", "Dota 2") is IdentityVerdict.MISMATCH


@pytest.mark.parametrize(
    ("expected", "actual"),
    [
        ("Fallout 3", "Fallout 4"),
        ("Borderlands 2", "Borderlands 3"),
        ("Dark Souls II", "Dark Souls III"),
        ("Sid Meier's Civilization V", "Sid Meier's Civilization VI"),
        ("Counter-Strike", "Counter-Strike 2"),
        ("Left 4 Dead", "Left 4 Dead 2"),
        ("Portal", "Portal 2"),
    ],
)
def test_franchise_sibling_is_a_mismatch(expected: str, actual: str) -> None:
    """The likeliest wrong-id resolution is a series neighbor — near-identical
    names that sail past the ratio (Civ V/VI reaches 0.966) or extend the
    expectation like an edition would. The numeral gate refuses them all."""
    assert identity_verdict(expected, actual) is IdentityVerdict.MISMATCH


def test_roman_and_arabic_numerals_compare_equal() -> None:
    """Notation is decoration, the number is identity: "II" folds to 2, so a
    store answer in the other notation is still the same game."""
    assert identity_verdict("Half-Life 2", "Half-Life II") is IdentityVerdict.OK


def test_no_store_answer_is_its_own_verdict() -> None:
    """No data ≠ mismatch: there was no name to compare."""
    assert identity_verdict("Portal", None) is IdentityVerdict.NO_DATA


# --- parse_appdetails ----------------------------------------------------------


_HASHED_HEADER = (
    "https://shared.akamai.steamstatic.com/store_item_assets/steam/apps/3450310/"
    "9944293cf93d5c11430d3b69941221b614c3ea70/header.jpg?t=1783587668"
)
"""A real hashed-path header URL (Europa Universalis V, captured 2026-08-20) —
the shape identity-minting cannot produce, which is why the field is kept."""


def test_appdetails_reads_the_string_keyed_entry() -> None:
    payload = json.loads(_details_body(440, "Team Fortress 2"))
    assert parse_appdetails(payload, 440) == AppDetails(
        name="Team Fortress 2", header_image=None
    )


def test_appdetails_keeps_the_header_art_url_verbatim() -> None:
    """The header URL carries a content hash and cache-buster only this read
    knows — stored as Steam spoke it, never reconstructed."""
    payload = json.loads(_details_body(3450310, "Europa Universalis V", _HASHED_HEADER))
    details = parse_appdetails(payload, 3450310)
    assert details is not None
    assert details.header_image == _HASHED_HEADER


def test_appdetails_header_art_is_soft_on_absence_loud_on_type() -> None:
    """Art is garnish: a store page without the field (or with it empty) answers
    None rather than failing a paid job — but a type surprise is a wire-shape
    change and stays loud like every field."""
    empty = {"440": {"success": True, "data": {"name": "TF2", "header_image": ""}}}
    parsed = parse_appdetails(empty, 440)
    assert parsed is not None and parsed.header_image is None
    mistyped = {"440": {"success": True, "data": {"name": "TF2", "header_image": 7}}}
    with pytest.raises(SteamResponseError, match="header_image is int"):
        parse_appdetails(mistyped, 440)


def test_appdetails_no_data_is_none() -> None:
    """Falsy success or a missing data block answers None — the guard's no-data."""
    assert parse_appdetails({"440": {"success": False}}, 440) is None
    assert parse_appdetails({"440": {"success": True}}, 440) is None


def test_appdetails_null_entry_is_no_data_not_damage() -> None:
    """A JSON-null under our key is success:false's natural neighbor — the id
    resolved to nothing, which is the guard's calm no-data verdict, while a
    *missing* key stays loud (the response didn't answer the id at all)."""
    assert parse_appdetails({"440": None}, 440) is None


def test_appdetails_missing_entry_fails_loud() -> None:
    """A response without our app id's key is shape damage, not no-data."""
    with pytest.raises(SteamResponseError, match=r"appdetails\[440\]"):
        parse_appdetails({}, 440)


def test_appdetails_success_without_name_fails_loud() -> None:
    with pytest.raises(SteamResponseError, match="name is None"):
        parse_appdetails({"440": {"success": True, "data": {}}}, 440)


# --- the resolve operation -----------------------------------------------------


def test_resolve_assembles_the_ref_from_both_reads() -> None:
    """Two paced requests — appdetails, then the totals-only read — land in one
    honest record: verdict OK, store name verbatim, Steam's totals captured."""
    h = Harness(
        [
            httpx.Response(200, text=_details_body(440, "Team Fortress 2", _HASHED_HEADER)),
            httpx.Response(200, text=_totals_body(1_000_000, 900_000, 100_000)),
        ]
    )
    ref = h.client.resolve_game(440, "Team Fortress 2")
    assert ref.verdict is IdentityVerdict.OK
    assert ref.store_name == "Team Fortress 2"
    assert ref.header_image == _HASHED_HEADER
    assert ref.requested_name == "Team Fortress 2"
    assert (ref.total_reviews, ref.total_positive, ref.total_negative) == (
        1_000_000,
        900_000,
        100_000,
    )

    details_req, totals_req = h.requests
    assert details_req.url.path == "/api/appdetails"
    assert details_req.url.params["appids"] == "440"
    assert details_req.url.params["cc"] == "us"
    assert totals_req.url.path == "/appreviews/440"
    assert totals_req.url.params["num_per_page"] == "0"
    assert totals_req.url.params["language"] == "all"
    assert totals_req.url.params["purchase_type"] == "all"
    assert totals_req.url.params["review_type"] == "all"
    assert totals_req.url.params["filter_offtopic_activity"] == "0"


def test_resolve_no_data_still_captures_totals() -> None:
    """A delisted id keeps its reviews: the verdict says no-data while the
    totals read still answers — the two reads are independent by design."""
    h = Harness(
        [
            httpx.Response(200, text=json.dumps({"49520": {"success": False}})),
            httpx.Response(200, text=_totals_body(5000, 4000, 1000)),
        ]
    )
    ref = h.client.resolve_game(49520, "Borderlands 2")
    assert ref.verdict is IdentityVerdict.NO_DATA
    assert ref.store_name is None
    assert ref.header_image is None
    assert ref.total_reviews == 5000


def test_store_name_is_the_one_read_the_submit_door_makes() -> None:
    """The name-only read behind the id-only submit: one appdetails request,
    the store's name back, ``None`` when the store has no record — the
    Deadpool shape (page gone, reviews kept; probed live 2026-08-17)."""
    named = Harness([httpx.Response(200, text=_details_body(440, "Team Fortress 2"))])
    assert named.client.store_name(440) == "Team Fortress 2"
    assert len(named.requests) == 1, "the door pays one request, not resolve_game's two"
    assert "appdetails" in str(named.requests[0].url)

    pulled = Harness([httpx.Response(200, text=json.dumps({"224060": {"success": False}}))])
    assert pulled.client.store_name(224060) is None


def test_resolve_without_summary_leaves_totals_none() -> None:
    """A totals read that comes back without query_summary answers None, not 0 —
    an absent claim is not a zero claim."""
    h = Harness(
        [
            httpx.Response(200, text=_details_body(440, "Team Fortress 2")),
            httpx.Response(200, text=json.dumps({"success": 2})),
        ]
    )
    ref = h.client.resolve_game(440, "Team Fortress 2")
    assert ref.total_reviews is None
    assert ref.verdict is IdentityVerdict.OK
