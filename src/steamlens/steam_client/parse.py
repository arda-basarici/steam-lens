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

import json
import re
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, date, datetime
from typing import cast

from steamlens.contracts import (
    GameSearchHit,
    HistogramBucket,
    HistogramSnapshot,
    Review,
    ReviewEvent,
    RollupUnit,
    StorefrontLabel,
    StorefrontMetadata,
    StorefrontTag,
    StorefrontTagCapture,
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
    """One parsed page of the review method — the walk's unit of progress.

    ``no_result`` is Steam's own "nothing for this id" answer: the method
    returns an empty ``response`` object (HTTP 200, ``X-eresult: 42``) for
    an id it has no reviews record for, kept as a flag for the walk to judge
    — an empty *window* is not this, it answers zero totals and no reviews.
    ``cursor`` is the next-page token (``None`` when Steam omitted it — a
    stop signal, not an error); ``summary`` is present only on pages whose
    ``query_summary`` carried the population totals — the first page of a
    walk; later pages send a degenerate ``num_reviews``-only stub that
    parses as no summary. Internal to the door: walks fold pages into a
    ``WindowFetchResult``, which is the record that crosses the seam.
    """

    no_result: bool
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
    """One GetAppReviews response as a ``ReviewPage``.

    The body rides under a ``response`` key — its absence is shape damage.
    The method has no ``success`` field (the HTTP status is the verdict, and
    the transport already judges it); an empty ``response`` object is its
    no-result answer. A missing ``reviews`` list parses as an empty page
    rather than failing — Steam omits it on empty answers, and whether an
    empty page is a retry, a stop, or a clean "no result" is the walk's
    judgment, not the parser's.
    """
    body = _object_field(payload.get("response"), "review page response")
    cursor = body.get("cursor")
    if cursor is not None and not isinstance(cursor, str):
        raise SteamResponseError(f"review page: cursor is {cursor!r}, expected a string")
    summary = None
    raw_summary = body.get("query_summary")
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
    for position, item in enumerate(_list_field(body, "reviews", optional=True)):
        raw_review = _object_field(item, f"review page reviews[{position}]")
        try:
            reviews.append(review_from_raw(raw_review, app_id))
        except ValueError as exc:
            raise SteamResponseError(f"review page reviews[{position}]: {exc}") from exc
    return ReviewPage(
        no_result=not body, cursor=cursor, summary=summary, reviews=tuple(reviews)
    )


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

    One tolerance, earned live: since 2026-09 Steam files many answers under
    a *related* app's id (a DLC's, typically) while the record inside still
    carries the requested ``steam_appid`` — that lone foreign-keyed entry is
    read as ours on the strength of the inner id, and nothing else is.
    """
    data = _appdetails_data(payload, app_id)
    if data is None:
        return None
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


def _appdetails_data(payload: Mapping[str, object], app_id: int) -> Mapping[str, object] | None:
    """The ``data`` object of ``app_id``'s appdetails entry, or ``None`` for no data.

    The entry lookup both appdetails parsers share, so the no-data answers and
    the foreign-key tolerance are decided once: a falsy ``success``, a missing
    ``data`` or a JSON-null entry is ``None``; an entry that is absent
    altogether fails loud unless a lone entry carries our id.
    """
    key = str(app_id)
    raw_entry = (
        payload[key] if key in payload else _entry_filed_under_a_foreign_key(payload, app_id)
    )
    if raw_entry is None:
        return None  # null is success:false's natural neighbor — no data, calmly
    entry = _object_field(raw_entry, f"appdetails[{app_id}]")
    if not entry.get("success") or "data" not in entry:
        return None
    return _object_field(entry.get("data"), f"appdetails[{app_id}].data")


_RELEASE_DATE_FORMATS = ("%b %d, %Y", "%d %b, %Y")
"""The store's display forms for a full date: ``Sep 17, 2020`` at the door's
parameters (probed 2026-11-14), and the day-first form other country codes
answer with. Anything else ("Coming soon", a bare year, a quarter) is kept as
text and yields no date."""


def parse_storefront_metadata(
    payload: Mapping[str, object], app_id: int, captured_at: datetime
) -> StorefrontMetadata | None:
    """The filterable store facts in one appdetails response, or ``None`` for no data.

    Reads the same response ``parse_appdetails`` does, with the same no-data
    answers and the same foreign-key tolerance. ``captured_at`` is the
    caller's clock stamp, so the parser stays pure.

    Absence and type surprises are treated differently. A game may honestly
    have no genres, no categories, no release date and no description, so
    those parse as empty. A field that is present with the wrong type fails
    loud, and so does a missing ``platforms`` object: a platform flag has no
    honest default, and guessing one would make a hard filter lie. Genre ids
    arrive as strings and category ids as integers (probed 2026-11-14); both
    forms are accepted for both, since the store has changed such details
    before.
    """
    data = _appdetails_data(payload, app_id)
    if data is None:
        return None
    context = f"appdetails[{app_id}]"
    platforms = _object_field(data.get("platforms"), f"{context}.platforms")
    release_text, release_date, coming_soon = _release_date(data.get("release_date"), context)
    description = data.get("short_description")
    if description is not None and not isinstance(description, str):
        raise SteamResponseError(
            f"{context}: short_description is {type(description).__name__}, expected a string"
        )
    return StorefrontMetadata(
        app_id=app_id,
        genres=_labels(data, "genres", context),
        categories=_labels(data, "categories", context),
        windows=_bool_field(platforms, "windows", f"{context}.platforms"),
        mac=_bool_field(platforms, "mac", f"{context}.platforms"),
        linux=_bool_field(platforms, "linux", f"{context}.platforms"),
        release_date_text=release_text,
        release_date=release_date,
        coming_soon=coming_soon,
        short_description=description or "",
        captured_at=captured_at,
    )


def _labels(data: Mapping[str, object], key: str, context: str) -> tuple[StorefrontLabel, ...]:
    """The genre or category rows under ``key``, in the store's order."""
    labels: list[StorefrontLabel] = []
    for position, item in enumerate(_list_field(data, key, optional=True)):
        row_context = f"{context}.{key}[{position}]"
        row = _object_field(item, row_context)
        description = row.get("description")
        if not isinstance(description, str) or not description:
            raise SteamResponseError(
                f"{row_context}: description is {description!r}, expected a non-empty string"
            )
        labels.append(
            StorefrontLabel(id=_label_id(row.get("id"), row_context), description=description)
        )
    return tuple(labels)


def _label_id(value: object, context: str) -> int:
    """A genre or category id as an integer, from an integer or a digit string."""
    if isinstance(value, int) and not isinstance(value, bool):
        return value
    if isinstance(value, str) and value.isascii() and value.isdigit():
        return int(value)
    raise SteamResponseError(f"{context}: id is {value!r}, expected an integer or a digit string")


def _release_date(raw: object, context: str) -> tuple[str | None, date | None, bool]:
    """The store's release text, that text as a date when it is one, and ``coming_soon``."""
    if raw is None:
        return None, None, False
    release = _object_field(raw, f"{context}.release_date")
    text = release.get("date")
    if text is not None and not isinstance(text, str):
        raise SteamResponseError(
            f"{context}.release_date: date is {type(text).__name__}, expected a string"
        )
    coming_soon = release.get("coming_soon", False)
    if not isinstance(coming_soon, bool):
        raise SteamResponseError(
            f"{context}.release_date: coming_soon is {coming_soon!r}, expected a boolean"
        )
    if not text:
        return None, None, coming_soon
    for form in _RELEASE_DATE_FORMATS:
        try:
            return text, datetime.strptime(text, form).date(), coming_soon
        except ValueError:
            continue
    return text, None, coming_soon


_TAG_CALL = re.compile(r"InitAppTagModal\(\s*(\d+)\s*,\s*(?=\[)")
"""The store page's script call that carries the community tags: the app id,
then a JSON array of tag rows (probed 2026-11-14 on thirteen pages)."""


def parse_storefront_tags(
    html: str, app_id: int, captured_at: datetime
) -> StorefrontTagCapture | None:
    """The community tag block of one store page, or ``None`` when the page has none.

    The tags sit in the page's script as the second argument of an
    ``InitAppTagModal`` call, a JSON array of ``{tagid, name, count}`` rows in
    descending count. A page without the call is not the game's page (an age
    gate, a regional notice) and answers ``None``: nothing was read, which
    differs from a page whose array is empty. A call naming another app, an
    array that does not decode, or a malformed row fails loud. The
    ``browseable`` field is ignored; one probed row lacked it.
    """
    match = _TAG_CALL.search(html)
    if match is None:
        return None
    called_for = int(match.group(1))
    if called_for != app_id:
        raise SteamResponseError(
            f"store page tags: the page's tag call is for app {called_for}, expected {app_id}"
        )
    try:
        raw_tags, _ = json.JSONDecoder().raw_decode(html, match.end())
    except json.JSONDecodeError as exc:
        raise SteamResponseError(
            f"store page tags[{app_id}]: the tag array does not decode: {exc}"
        ) from exc
    if not isinstance(raw_tags, list):
        raise SteamResponseError(
            f"store page tags[{app_id}]: the tag argument is "
            f"{type(raw_tags).__name__}, expected a list"
        )
    tags: list[StorefrontTag] = []
    for position, item in enumerate(cast("list[object]", raw_tags)):
        context = f"store page tags[{app_id}][{position}]"
        row = _object_field(item, context)
        name = row.get("name")
        if not isinstance(name, str) or not name:
            raise SteamResponseError(f"{context}: name is {name!r}, expected a non-empty string")
        tags.append(
            StorefrontTag(
                tag_id=_int_field(row, "tagid", context),
                name=name,
                count=_int_field(row, "count", context),
            )
        )
    return StorefrontTagCapture(app_id=app_id, tags=tuple(tags), captured_at=captured_at)


def _entry_filed_under_a_foreign_key(payload: Mapping[str, object], app_id: int) -> object:
    """The one entry Steam filed under another id, when its record is ours.

    Observed 2026-09-24, dated to the week before: appdetails answers under
    a related app's id for most games with DLC (Darkest Dungeon under its
    DLC 345800), and the requested key is simply absent. The inner
    ``steam_appid`` is the anchor — a lone entry claiming our id is
    accepted; a differing id, several entries, or an empty response stay
    the loud missing-key failure, so a record about another game is never
    taken as ours.
    """
    if len(payload) == 1:
        ((_, raw_entry),) = payload.items()
        if isinstance(raw_entry, Mapping):
            entry = cast("Mapping[str, object]", raw_entry)
            data = entry.get("data")
            claimed = (
                cast("Mapping[str, object]", data).get("steam_appid")
                if isinstance(data, Mapping) else None
            )
            if claimed == app_id:
                return entry
    raise SteamResponseError(
        f"appdetails[{app_id}] is missing — the response answers {sorted(payload)!r}, "
        "and no lone entry carries our steam_appid"
    )


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


def _bool_field(raw: Mapping[str, object], key: str, context: str) -> bool:
    """The boolean at ``key`` — a missing flag is as loud as a mistyped one."""
    value = raw.get(key)
    if not isinstance(value, bool):
        raise SteamResponseError(f"{context}: {key} is {value!r}, expected a boolean")
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
