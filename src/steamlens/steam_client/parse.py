"""Wire-format parsers for the Steam door — raw payloads into trusted records.

Everything Steam-shaped is translated here and only here: epoch seconds become
timezone-aware ``datetime``\\ s, the histogram's age-dependent rollup unit is
read (never assumed), and every field crosses a type check before it enters a
contract — trust-no-raw-data at the boundary, so a built record is trusted by
construction. The parsers are pure (payload in, record out; the clock comes in
as an argument), which is what lets the suite pin them against the real probe
captures byte-for-byte. A payload that fails its shape check raises
``SteamResponseError`` — Steam answered in a way retrying cannot improve.

``review_from_raw`` lives here because the wire format is the door's knowledge:
the frozen corpus files hold the same Steam review objects on disk, so the
offline reader (``corpus.local``) imports this parser rather than
keeping a drifting copy.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import cast

from steamlens.contracts import (
    GameSearchHit,
    HistogramBucket,
    HistogramSnapshot,
    Review,
    ReviewEvent,
    RollupUnit,
)
from steamlens.steam_client.errors import SteamResponseError


@dataclass(frozen=True, slots=True)
class QuerySummary:
    """Steam's own population claim for a review query — captured, never trusted.

    The three totals from a first page's ``query_summary``. What they describe
    depends on the query that produced them: window-scoped under the windowed
    params, whole-game under a plain walk — the caller knows which question it
    asked.
    """

    total_reviews: int
    total_positive: int
    total_negative: int


@dataclass(frozen=True, slots=True)
class ReviewPage:
    """One parsed page of the review endpoint — the walk's unit of progress.

    ``success`` is Steam's own status field (2 is the documented "no result"
    answer, kept verbatim for the walk to judge); ``cursor`` is the next-page
    token (``None`` when Steam omitted it — a stop signal, not an error);
    ``summary`` is present only on pages whose ``query_summary`` carried the
    population totals — the first page of a walk; later pages send a
    degenerate ``num_reviews``-only stub that parses as no summary. Internal
    to the door: walks fold pages into a ``WindowFetchResult``, which is the
    record that crosses the seam.
    """

    success: int
    cursor: str | None
    summary: QuerySummary | None
    reviews: tuple[Review, ...]


def review_from_raw(raw: Mapping[str, object], app_id: int) -> Review:
    """One raw Steam review object as its contract, validated at the boundary.

    ``app_id`` comes from the caller (Steam keys the request by app, not the
    row). Steam's epoch seconds become the timezone-aware ``created_at`` here —
    the contract never sees the raw number. Raises ``ValueError`` naming the
    field (and the review id once known) on a missing or mistyped field; the
    callers wrap it with their own context — a corpus file and line offline, a
    page position at the live door.
    """
    review_id = raw.get("recommendationid")
    if not isinstance(review_id, str) or not review_id:
        raise ValueError(f"recommendationid is {review_id!r}, expected a non-empty string")
    language = raw.get("language")
    if not isinstance(language, str):
        raise ValueError(f"review {review_id}: language is {language!r}, expected a string")
    text = raw.get("review")
    if not isinstance(text, str):
        raise ValueError(f"review {review_id}: review text is {text!r}, expected a string")
    timestamp = raw.get("timestamp_created")
    if isinstance(timestamp, bool) or not isinstance(timestamp, int):
        raise ValueError(
            f"review {review_id}: timestamp_created is {timestamp!r}, expected an integer"
        )
    voted_up = raw.get("voted_up")
    if not isinstance(voted_up, bool):
        raise ValueError(f"review {review_id}: voted_up is {voted_up!r}, expected a boolean")
    return Review(
        review_id=review_id,
        app_id=app_id,
        created_at=datetime.fromtimestamp(timestamp, tz=UTC),
        language=language,
        text=text,
        voted_up=voted_up,
    )


def parse_review_page(payload: Mapping[str, object], app_id: int) -> ReviewPage:
    """One review-endpoint response as a ``ReviewPage``.

    A missing ``reviews`` list parses as an empty page rather than failing —
    Steam omits it on empty answers, and whether an empty page is a retry, a
    stop, or a clean "no result" is the walk's judgment, not the parser's.
    """
    success = _int_field(payload, "success", "review page")
    cursor = payload.get("cursor")
    if cursor is not None and not isinstance(cursor, str):
        raise SteamResponseError(f"review page: cursor is {cursor!r}, expected a string")
    summary = None
    raw_summary = payload.get("query_summary")
    if raw_summary is not None:
        summary_map = _object_field(raw_summary, "review page query_summary")
        # Later pages carry a degenerate {"num_reviews": N} stub with no totals
        # (live-smoke observation 2026-07-27) — that is "no summary", not damage;
        # a summary that *starts* the totals must carry all three or fail loud.
        if "total_reviews" in summary_map:
            summary = QuerySummary(
                total_reviews=_int_field(summary_map, "total_reviews", "query_summary"),
                total_positive=_int_field(summary_map, "total_positive", "query_summary"),
                total_negative=_int_field(summary_map, "total_negative", "query_summary"),
            )
    reviews: list[Review] = []
    for position, item in enumerate(_list_field(payload, "reviews", optional=True)):
        raw_review = _object_field(item, f"review page reviews[{position}]")
        try:
            reviews.append(review_from_raw(raw_review, app_id))
        except ValueError as exc:
            raise SteamResponseError(f"review page reviews[{position}]: {exc}") from exc
    return ReviewPage(success=success, cursor=cursor, summary=summary, reviews=tuple(reviews))


@dataclass(frozen=True, slots=True)
class AppDetails:
    """The store's answer about one app — the fields production reads, typed.

    ``name`` is what the store currently calls the app (the identity guard's
    comparand and the id-only submit's job name). ``header_image`` is Steam's
    own URL for the game's header art, verbatim including its cache-buster —
    it cannot be minted from the app id alone, because newer titles' assets
    live under a per-game content-hash path segment (probed live 2026-08-20:
    the hash-free pattern 404s for every post-migration title on every asset
    name and CDN host). ``None`` when the store offered no usable URL: art is
    garnish, and a game page without an image field is an answer, not damage.
    Internal to the door like ``QuerySummary``; ``GameRef`` carries the
    fields across the seam.
    """

    name: str
    header_image: str | None


def parse_appdetails(payload: Mapping[str, object], app_id: int) -> AppDetails | None:
    """The store's current record for ``app_id``, or ``None`` when it has no data.

    The appdetails response is keyed by the app id *as a string*; the entry
    answers no-data (falsy ``success``, no ``data``, or a JSON-null entry —
    a delisted or invalid id) as ``None``, which the identity guard turns
    into its no-data verdict. A *missing* key is different — the response
    doesn't answer the id at all — and fails loud, as does a successful
    entry whose ``name`` is missing or mistyped. ``header_image`` is softer
    on absence (absent or empty parses as ``None`` — the store may honestly
    have no art) but stays loud on a type surprise, like every field here.
    """
    key = str(app_id)
    if key in payload and payload[key] is None:
        return None  # null is success:false's natural neighbor — no data, calmly
    entry = _object_field(payload.get(key), f"appdetails[{app_id}]")
    if not entry.get("success") or "data" not in entry:
        return None
    data = _object_field(entry.get("data"), f"appdetails[{app_id}].data")
    name = data.get("name")
    if not isinstance(name, str) or not name:
        raise SteamResponseError(
            f"appdetails[{app_id}]: name is {name!r}, expected a non-empty string"
        )
    header_image = data.get("header_image")
    if header_image is not None and not isinstance(header_image, str):
        raise SteamResponseError(
            f"appdetails[{app_id}]: header_image is "
            f"{type(header_image).__name__}, expected a string"
        )
    return AppDetails(name=name, header_image=header_image or None)


def parse_storesearch(payload: Mapping[str, object]) -> tuple[GameSearchHit, ...]:
    """One storesearch response as typed hits, ``app``-type rows only.

    Bundles (``type: "sub"``) are dropped here — a sub id is not an app id,
    so offering one would request an analysis of nothing. DLC and
    soundtracks pass through: the wire carries no field separating them from
    base games (probed 2026-08-08), so the filter is the viewer's pick plus
    the identity guard downstream. An unknown term is an empty tuple
    (``total: 0`` with an empty ``items`` — a finding, not a failure); a
    malformed item fails loud with its position named.
    """
    hits: list[GameSearchHit] = []
    for position, item in enumerate(_list_field(payload, "items", optional=True)):
        row = _object_field(item, f"storesearch items[{position}]")
        if row.get("type") != "app":
            continue
        name = row.get("name")
        capsule = row.get("tiny_image")
        if not isinstance(name, str) or not name:
            raise SteamResponseError(
                f"storesearch items[{position}]: name is {name!r}, expected a non-empty string"
            )
        if not isinstance(capsule, str):
            raise SteamResponseError(
                f"storesearch items[{position}]: tiny_image is {type(capsule).__name__}, "
                "expected a string"
            )
        hits.append(
            GameSearchHit(
                app_id=_int_field(row, "id", f"storesearch items[{position}]"),
                name=name,
                capsule_url=capsule,
            )
        )
    return tuple(hits)


def parse_histogram(
    payload: Mapping[str, object], app_id: int, fetched_at: datetime
) -> HistogramSnapshot:
    """One histogram-endpoint response as a ``HistogramSnapshot``.

    The rollup unit is read from Steam's ``rollup_type`` — the smoke probes
    caught both months and weeks on real games, so an unrecognized unit is a
    loud failure, never a guess. ``past_events`` is optional on the wire (most
    games have none) and parses to an empty tuple when absent. ``fetched_at``
    is the caller's clock stamp — the parser stays pure.
    """
    success = _int_field(payload, "success", "histogram")
    if success != 1:
        raise SteamResponseError(f"histogram: success is {success}, expected 1")
    results = _object_field(payload.get("results"), "histogram results")
    rollup_type = results.get("rollup_type")
    if not isinstance(rollup_type, str):
        raise SteamResponseError(
            f"histogram: rollup_type is {rollup_type!r}, expected a string"
        )
    try:
        rollup_unit = RollupUnit(rollup_type)
    except ValueError as exc:
        raise SteamResponseError(
            f"histogram: unrecognized rollup_type {rollup_type!r} "
            f"(known: {[u.value for u in RollupUnit]})"
        ) from exc
    events: list[ReviewEvent] = []
    for position, item in enumerate(_list_field(payload, "past_events", optional=True)):
        raw_event = _object_field(item, f"histogram past_events[{position}]")
        context = f"past_events[{position}]"
        events.append(
            ReviewEvent(
                event_type=_int_field(raw_event, "type", context),
                start=_epoch_field(raw_event, "start_date", context),
                end=_epoch_field(raw_event, "end_date", context),
            )
        )
    return HistogramSnapshot(
        app_id=app_id,
        rollup_unit=rollup_unit,
        rollups=_buckets(results, "rollups"),
        recent_daily=_buckets(results, "recent"),
        past_events=tuple(events),
        fetched_at=fetched_at,
    )


def _buckets(results: Mapping[str, object], key: str) -> tuple[HistogramBucket, ...]:
    """A histogram bucket series under ``key``, each element shape-checked."""
    parsed: list[HistogramBucket] = []
    for position, item in enumerate(_list_field(results, key, optional=False)):
        raw_bucket = _object_field(item, f"histogram {key}[{position}]")
        context = f"{key}[{position}]"
        parsed.append(
            HistogramBucket(
                start=_epoch_field(raw_bucket, "date", context),
                recommendations_up=_int_field(raw_bucket, "recommendations_up", context),
                recommendations_down=_int_field(raw_bucket, "recommendations_down", context),
            )
        )
    return tuple(parsed)


def _int_field(raw: Mapping[str, object], key: str, context: str) -> int:
    """The integer at ``key``, bool-guarded — ``True`` must not pass as ``1``."""
    value = raw.get(key)
    if isinstance(value, bool) or not isinstance(value, int):
        raise SteamResponseError(f"{context}: {key} is {value!r}, expected an integer")
    return value


def _epoch_field(raw: Mapping[str, object], key: str, context: str) -> datetime:
    """The epoch-seconds integer at ``key`` as a timezone-aware UTC datetime."""
    return datetime.fromtimestamp(_int_field(raw, key, context), tz=UTC)


def _object_field(value: object, context: str) -> Mapping[str, object]:
    """``value`` as a JSON object, or the typed shape failure."""
    if not isinstance(value, Mapping):
        raise SteamResponseError(f"{context} is {type(value).__name__}, expected an object")
    return cast("Mapping[str, object]", value)


def _list_field(raw: Mapping[str, object], key: str, *, optional: bool) -> list[object]:
    """The list at ``key``; an absent optional list is empty, anything else is loud."""
    value = raw.get(key)
    if value is None and optional:
        return []
    if not isinstance(value, list):
        raise SteamResponseError(
            f"{type(value).__name__ if value is not None else 'nothing'} at {key!r}, "
            "expected a list"
        )
    return cast("list[object]", value)
