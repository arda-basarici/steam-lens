"""The report surface — one completed analysis published whole, served as-is later.

``ReportLog`` owns the two publication tables. A report lands atomically: the
report row and its normalized aggregate-snapshot rows commit in one
transaction, so a reader can never observe a half-published analysis — the
snapshot table even declares its foreign key against ``reports`` to make the
"no snapshot without its report" invariant structural. A duplicate ``run_id``
fails loud (one run mints one report; overwriting would silently re-publish).

Validation is asymmetric by design. The scalar columns are trusted the way
every store column is — written from contracts, re-parsed through the read
boundary. The ``*_json`` columns hold display-only structure nothing queries
inside, so their check is *full reconstruction at read*: the stored payload
must rebuild into its contract records — enums re-proving vocabulary
membership, timestamps re-parsing, the narrative's span offsets landing on
the exact text they certify — or the read fails loud naming the row. Writing
rendered HTML here is what this module exists to prevent: content persists,
presentation stays free to change.
"""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Callable, Sequence
from typing import Any

from steamlens.contracts import (
    AspectAggregate,
    AspectSlot,
    ClassifierVersions,
    ComposedNarrative,
    EpisodeMarker,
    GroundedSpan,
    HistogramBucket,
    HistogramSnapshot,
    LanguageCount,
    MarkedWindowCount,
    NarrativeOutcome,
    PathOutcome,
    Provenance,
    Report,
    ReportCard,
    ReviewEvent,
    RollupUnit,
    SentimentCounts,
    SpanKind,
    WindowAccount,
)
from steamlens.store.convert import parse_enum, parse_utc_isoformat, utc_isoformat
from steamlens.store.errors import StoreDataError, StoreError

_CARD_ASPECT_LIMIT = 5
"""How many pinned aspects an index card previews — enough to characterize a
game's discussion, few enough to stay tags rather than a table."""

_REPORT_COLUMNS = (
    "p.run_id, p.app_id, p.game_name, p.created_at,"
    " p.model_version, p.prompt_version, p.ontology_version,"
    " p.sample_size, p.take_all,"
    " p.windowed_windows, p.fallback_windows, p.skipped_windows,"
    " p.narrative_outcome, p.narrative_json, p.histogram_json, p.episodes_json,"
    " p.language_mix_json, p.marked_windows_json, p.fetch_windows_json,"
    " r.code_version, r.created_at, r.config_hash"
)


class ReportLog:
    """The published reports: minted once at job completion, cited unchanged after.

    Constructed by ``Store`` with the store's connection; never opens or owns
    one itself.
    """

    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn

    def put(self, report: Report, aggregates: Sequence[AspectAggregate]) -> None:
        """Publish one analysis — the report row and its snapshot rows, atomically.

        Raises ``ValueError`` when the pieces disagree before anything is
        written — an aggregate naming another game, sample, or versions than
        the report, a histogram for a different app, a narrative whose
        outcome and prose contradict each other: each is a runner bug, and
        publishing it would freeze the contradiction into a citable artifact.
        Raises ``StoreError`` on a duplicate ``run_id`` or an unrecorded run
        (foreign key).
        """
        _check_publishable(report, aggregates)
        cursor = self._conn.cursor()
        cursor.execute("BEGIN")
        try:
            cursor.execute(
                "INSERT INTO reports (run_id, app_id, game_name, created_at,"
                " model_version, prompt_version, ontology_version, sample_size,"
                " take_all, windowed_windows, fallback_windows, skipped_windows,"
                " narrative_outcome, narrative_json, histogram_json, episodes_json,"
                " language_mix_json, marked_windows_json, fetch_windows_json)"
                " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    report.run.run_id,
                    report.app_id,
                    report.game_name,
                    utc_isoformat(report.created_at),
                    report.versions.model_version,
                    report.versions.prompt_version,
                    report.versions.ontology_version,
                    report.sample_size,
                    int(report.take_all),
                    sum(1 for w in report.windows if w.outcome is PathOutcome.WINDOWED),
                    sum(
                        1 for w in report.windows
                        if w.outcome is PathOutcome.FALLBACK_WALKED
                    ),
                    sum(
                        1 for w in report.windows
                        if w.outcome is PathOutcome.SKIPPED_INFEASIBLE
                    ),
                    report.narrative.outcome,
                    narrative_payload(report.narrative),
                    _histogram_payload(report.histogram),
                    _episodes_payload(report.episodes),
                    _language_mix_payload(report.language_mix),
                    _marked_windows_payload(report.marked_window_counts),
                    _fetch_windows_payload(report.windows),
                ),
            )
            cursor.executemany(
                "INSERT INTO aggregate_snapshots (run_id, aspect, slot,"
                " reviews_with_aspect, positive, negative, mixed, neutral, sample_size)"
                " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    (
                        report.run.run_id,
                        a.aspect,
                        a.slot,
                        a.reviews_with_aspect,
                        a.counts.positive,
                        a.counts.negative,
                        a.counts.mixed,
                        a.counts.neutral,
                        a.sample_size,
                    )
                    for a in aggregates
                ),
            )
            cursor.execute("COMMIT")
        except sqlite3.IntegrityError as exc:
            cursor.execute("ROLLBACK")
            raise StoreError(
                f"report write rejected for run {report.run.run_id!r} — duplicate "
                f"report, duplicate (aspect, slot) snapshot row, or the run is not "
                f"recorded: {exc}"
            ) from exc
        except BaseException:
            cursor.execute("ROLLBACK")
            raise

    def get(self, run_id: str) -> Report | None:
        """The published report under ``run_id``, or None — fully reconstructed.

        Every JSON column rebuilds into its contract records on the way out;
        a payload that no longer reconstructs (edited file, drifted format)
        raises ``StoreDataError`` naming the run and column.
        """
        row = self._conn.execute(
            f"SELECT {_REPORT_COLUMNS} FROM reports p"
            " JOIN runs r ON r.run_id = p.run_id WHERE p.run_id = ?",
            (run_id,),
        ).fetchone()
        return None if row is None else _report_from_row(row)

    def latest_report(self, app_id: int) -> Report | None:
        """The newest published report for ``app_id``, or None if never analyzed.

        The cached-game instant read: ``POST /analyses`` consults this before
        queueing a job. Newest by completion time — multiple rows per app are
        the refresh-ready shape, and this read is why they never conflict.
        """
        row = self._conn.execute(
            f"SELECT {_REPORT_COLUMNS} FROM reports p"
            " JOIN runs r ON r.run_id = p.run_id WHERE p.app_id = ?"
            " ORDER BY p.created_at DESC LIMIT 1",
            (app_id,),
        ).fetchone()
        return None if row is None else _report_from_row(row)

    def cards(self) -> tuple[ReportCard, ...]:
        """Every analyzed game's newest publication as an index card, newest first.

        The reports-index read: re-runs collapse to the newest report per
        game (the same resolution ``latest_report`` serves), and each card
        carries its report's five most-mentioned pinned aspects in the report
        page's own bar order — a card previews exactly what its page leads
        with. Candidates stay out (the uncalibrated stratum), as do pins
        nobody mentioned. The per-card snapshot query rides the table's
        (run_id, aspect, slot) uniqueness index; at index-page row counts
        the loop is a read a page load cannot feel.
        """
        rows = self._conn.execute(
            "SELECT run_id, app_id, game_name, created_at, sample_size, take_all"
            " FROM reports ORDER BY created_at DESC, run_id"
        ).fetchall()
        cards: list[ReportCard] = []
        seen: set[int] = set()
        for run_id, app_id, game_name, created_at, sample_size, take_all in rows:
            if int(app_id) in seen:
                continue
            seen.add(int(app_id))
            aspects = self._conn.execute(
                "SELECT aspect FROM aggregate_snapshots"
                " WHERE run_id = ? AND slot = ? AND reviews_with_aspect > 0"
                " ORDER BY reviews_with_aspect DESC, aspect"
                f" LIMIT {_CARD_ASPECT_LIMIT}",
                (str(run_id), AspectSlot.PINNED.value),
            ).fetchall()
            cards.append(
                ReportCard(
                    app_id=int(app_id),
                    game_name=str(game_name),
                    created_at=parse_utc_isoformat(
                        str(created_at), context=f"reports[{run_id}].created_at"
                    ),
                    sample_size=int(sample_size),
                    take_all=bool(take_all),
                    top_aspects=tuple(str(aspect) for (aspect,) in aspects),
                )
            )
        return tuple(cards)

    def get_snapshot(self, run_id: str) -> tuple[AspectAggregate, ...]:
        """One run's frozen aggregate snapshot, rebuilt as full contracts.

        Rows come back in write order (the fold's own order). ``versions`` and
        ``app_id`` rejoin from the report row — normalized out at write, they
        are the same for every row of a run by the publish check. Empty for a
        run that never published; the caller distinguishes that through
        ``get``, not here.
        """
        rows = self._conn.execute(
            "SELECT s.aspect, s.slot, s.reviews_with_aspect,"
            " s.positive, s.negative, s.mixed, s.neutral, s.sample_size,"
            " p.app_id, p.model_version, p.prompt_version, p.ontology_version"
            " FROM aggregate_snapshots s JOIN reports p ON p.run_id = s.run_id"
            " WHERE s.run_id = ? ORDER BY s.id",
            (run_id,),
        ).fetchall()
        return tuple(
            AspectAggregate(
                app_id=int(row[8]),
                aspect=str(row[0]),
                slot=parse_enum(
                    AspectSlot, str(row[1]), context=f"aggregate_snapshots[{run_id}].slot"
                ),
                reviews_with_aspect=int(row[2]),
                counts=SentimentCounts(
                    positive=int(row[3]),
                    negative=int(row[4]),
                    mixed=int(row[5]),
                    neutral=int(row[6]),
                ),
                sample_size=int(row[7]),
                versions=ClassifierVersions(
                    model_version=str(row[9]),
                    prompt_version=str(row[10]),
                    ontology_version=str(row[11]),
                ),
                manifest_id=run_id,
            )
            for row in rows
        )


def _check_publishable(report: Report, aggregates: Sequence[AspectAggregate]) -> None:
    """The write-door consistency check — the pieces must describe one analysis."""
    if report.histogram.app_id != report.app_id:
        raise ValueError(
            f"report for app {report.app_id} carries a histogram for app "
            f"{report.histogram.app_id}"
        )
    withheld = report.narrative.outcome is NarrativeOutcome.WITHHELD
    if withheld != (not report.narrative.prose):
        raise ValueError(
            f"narrative outcome {report.narrative.outcome!r} contradicts its prose "
            f"({'empty' if not report.narrative.prose else f'{len(report.narrative.prose)} chars'})"
        )
    for a in aggregates:
        if (
            a.app_id != report.app_id
            or a.manifest_id != report.run.run_id
            or a.versions != report.versions
            or a.sample_size != report.sample_size
        ):
            raise ValueError(
                f"aggregate ({a.aspect!r}, {a.slot!r}) disagrees with its report: "
                f"app {a.app_id} vs {report.app_id}, manifest {a.manifest_id!r} vs "
                f"{report.run.run_id!r}, sample {a.sample_size} vs {report.sample_size}, "
                f"or versions differ"
            )


# --- the JSON codecs: contract -> payload at write, payload -> contract at read ---
# Timestamps use the store's one codec so JSON and columns stay comparable;
# enums serialize as their wire values and re-prove membership on the way back.


def narrative_payload(narrative: ComposedNarrative) -> str:
    """The narrative column's exact JSON — public so a repair that writes the
    column from outside the store (the 2026-08-16 re-grounding) encodes
    byte-for-byte what ``put`` would."""
    return json.dumps(
        {
            "prose": narrative.prose,
            "spans": [
                {
                    "start": s.start,
                    "end": s.end,
                    "text": s.text,
                    "kind": s.kind,
                    "value": s.value,
                    "review_id": s.review_id,
                }
                for s in narrative.spans
            ],
        }
    )


def _histogram_payload(histogram: HistogramSnapshot) -> str:
    def bucket(b: HistogramBucket) -> dict[str, Any]:
        return {
            "start": utc_isoformat(b.start),
            "up": b.recommendations_up,
            "down": b.recommendations_down,
        }

    return json.dumps(
        {
            "app_id": histogram.app_id,
            "rollup_unit": histogram.rollup_unit,
            "rollups": [bucket(b) for b in histogram.rollups],
            "recent_daily": [bucket(b) for b in histogram.recent_daily],
            "past_events": [
                {
                    "event_type": e.event_type,
                    "start": utc_isoformat(e.start),
                    "end": utc_isoformat(e.end),
                }
                for e in histogram.past_events
            ],
            "fetched_at": utc_isoformat(histogram.fetched_at),
        }
    )


def _episodes_payload(episodes: tuple[EpisodeMarker, ...]) -> str:
    return json.dumps(
        [
            {
                "start": utc_isoformat(e.start),
                "end": utc_isoformat(e.end),
                "buckets": e.buckets,
                "reviews": e.reviews,
                "peak_multiple": e.peak_multiple,
                "overlaps_marked_window": e.overlaps_marked_window,
            }
            for e in episodes
        ]
    )


def _language_mix_payload(mix: tuple[LanguageCount, ...]) -> str:
    return json.dumps([{"language": m.language, "count": m.count} for m in mix])


def _marked_windows_payload(counts: tuple[MarkedWindowCount, ...]) -> str:
    return json.dumps(
        [
            {
                "start": utc_isoformat(c.start),
                "end": utc_isoformat(c.end),
                "members_inside": c.members_inside,
            }
            for c in counts
        ]
    )


def _fetch_windows_payload(windows: tuple[WindowAccount, ...]) -> str:
    return json.dumps(
        [
            {"start": utc_isoformat(w.start), "end": utc_isoformat(w.end), "outcome": w.outcome}
            for w in windows
        ]
    )


def _report_from_row(row: tuple[Any, ...]) -> Report:
    """One joined ``reports`` row back as its contract — reconstruction is the check.

    The JSON columns rebuild through ``_decode``, which turns any structural
    surprise (missing key, wrong type, unparseable JSON) into ``StoreDataError``
    naming the run and column; the enum and timestamp parsers keep their own,
    more precise errors. Two cross-checks close what per-column parsing can't
    see: the scalar path totals must re-derive from the stored windows, and
    the narrative's certificate must still land on the exact prose it signs.
    """
    run_id = str(row[0])
    prose, spans = _decode(run_id, "narrative_json", str(row[13]), _narrative_from)
    outcome = parse_enum(
        NarrativeOutcome, str(row[12]), context=f"reports[{run_id}].narrative_outcome"
    )
    narrative = ComposedNarrative(prose=prose, spans=spans, outcome=outcome)
    for span in narrative.spans:
        if narrative.prose[span.start : span.end] != span.text:
            raise StoreDataError(
                f"reports[{run_id}].narrative_json: span {span.text!r} at "
                f"[{span.start}:{span.end}] no longer matches its prose — the "
                f"certificate does not sign this text"
            )
    if (narrative.outcome is NarrativeOutcome.WITHHELD) != (not narrative.prose):
        raise StoreDataError(
            f"reports[{run_id}]: narrative_outcome {narrative.outcome!r} contradicts "
            f"the stored prose"
        )
    windows = _decode(run_id, "fetch_windows_json", str(row[18]), _windows_from)
    stored_totals = (int(row[9]), int(row[10]), int(row[11]))
    derived_totals = (
        sum(1 for w in windows if w.outcome is PathOutcome.WINDOWED),
        sum(1 for w in windows if w.outcome is PathOutcome.FALLBACK_WALKED),
        sum(1 for w in windows if w.outcome is PathOutcome.SKIPPED_INFEASIBLE),
    )
    if stored_totals != derived_totals:
        raise StoreDataError(
            f"reports[{run_id}]: stored path totals {stored_totals} disagree with "
            f"the stored windows {derived_totals}"
        )
    histogram = _decode(run_id, "histogram_json", str(row[14]), _histogram_from)
    app_id = int(row[1])
    if histogram.app_id != app_id:
        raise StoreDataError(
            f"reports[{run_id}]: histogram names app {histogram.app_id}, "
            f"the row names app {app_id}"
        )
    return Report(
        run=Provenance(
            run_id=run_id,
            code_version=str(row[19]),
            created_at=parse_utc_isoformat(str(row[20]), context=f"runs[{run_id}].created_at"),
            config_hash=str(row[21]),
        ),
        app_id=app_id,
        game_name=str(row[2]),
        created_at=parse_utc_isoformat(
            str(row[3]), context=f"reports[{run_id}].created_at"
        ),
        versions=ClassifierVersions(
            model_version=str(row[4]),
            prompt_version=str(row[5]),
            ontology_version=str(row[6]),
        ),
        sample_size=int(row[7]),
        take_all=bool(row[8]),
        windows=windows,
        language_mix=_decode(run_id, "language_mix_json", str(row[16]), _language_mix_from),
        narrative=narrative,
        histogram=histogram,
        episodes=_decode(run_id, "episodes_json", str(row[15]), _episodes_from),
        marked_window_counts=_decode(
            run_id, "marked_windows_json", str(row[17]), _marked_windows_from
        ),
    )


type _Rebuild[T] = Callable[[str, Any], T]


def _decode[T](run_id: str, column: str, payload: str, rebuild: _Rebuild[T]) -> T:
    """Parse and rebuild one JSON column, failing loud with the row named.

    ``StoreDataError`` from the inner parsers passes through untouched — it
    already names the offending value more precisely than this wrapper could.
    """
    try:
        return rebuild(run_id, json.loads(payload))
    except StoreDataError:
        raise
    except (json.JSONDecodeError, KeyError, TypeError, ValueError) as exc:
        raise StoreDataError(
            f"reports[{run_id}].{column}: stored payload no longer reconstructs: {exc}"
        ) from exc


def _narrative_from(run_id: str, data: Any) -> tuple[str, tuple[GroundedSpan, ...]]:
    """The narrative column's halves — the outcome lives in its own scalar column."""
    return str(data["prose"]), tuple(
        GroundedSpan(
            start=int(s["start"]),
            end=int(s["end"]),
            text=str(s["text"]),
            kind=parse_enum(
                SpanKind, str(s["kind"]),
                context=f"reports[{run_id}].narrative_json.spans.kind",
            ),
            value=None if s["value"] is None else float(s["value"]),
            review_id=None if s["review_id"] is None else str(s["review_id"]),
        )
        for s in data["spans"]
    )


def _histogram_from(run_id: str, data: Any) -> HistogramSnapshot:
    context = f"reports[{run_id}].histogram_json"

    def bucket(b: Any, series: str) -> HistogramBucket:
        return HistogramBucket(
            start=parse_utc_isoformat(str(b["start"]), context=f"{context}.{series}"),
            recommendations_up=int(b["up"]),
            recommendations_down=int(b["down"]),
        )

    return HistogramSnapshot(
        app_id=int(data["app_id"]),
        rollup_unit=parse_enum(
            RollupUnit, str(data["rollup_unit"]), context=f"{context}.rollup_unit"
        ),
        rollups=tuple(bucket(b, "rollups") for b in data["rollups"]),
        recent_daily=tuple(bucket(b, "recent_daily") for b in data["recent_daily"]),
        past_events=tuple(
            ReviewEvent(
                event_type=int(e["event_type"]),
                start=parse_utc_isoformat(str(e["start"]), context=f"{context}.past_events"),
                end=parse_utc_isoformat(str(e["end"]), context=f"{context}.past_events"),
            )
            for e in data["past_events"]
        ),
        fetched_at=parse_utc_isoformat(str(data["fetched_at"]), context=f"{context}.fetched_at"),
    )


def _episodes_from(run_id: str, data: Any) -> tuple[EpisodeMarker, ...]:
    context = f"reports[{run_id}].episodes_json"
    return tuple(
        EpisodeMarker(
            start=parse_utc_isoformat(str(e["start"]), context=context),
            end=parse_utc_isoformat(str(e["end"]), context=context),
            buckets=int(e["buckets"]),
            reviews=int(e["reviews"]),
            peak_multiple=float(e["peak_multiple"]),
            overlaps_marked_window=bool(e["overlaps_marked_window"]),
        )
        for e in data
    )


def _language_mix_from(run_id: str, data: Any) -> tuple[LanguageCount, ...]:
    del run_id  # no timestamps or enums to contextualize
    return tuple(
        LanguageCount(language=str(m["language"]), count=int(m["count"])) for m in data
    )


def _marked_windows_from(run_id: str, data: Any) -> tuple[MarkedWindowCount, ...]:
    context = f"reports[{run_id}].marked_windows_json"
    return tuple(
        MarkedWindowCount(
            start=parse_utc_isoformat(str(c["start"]), context=context),
            end=parse_utc_isoformat(str(c["end"]), context=context),
            members_inside=int(c["members_inside"]),
        )
        for c in data
    )


def _windows_from(run_id: str, data: Any) -> tuple[WindowAccount, ...]:
    context = f"reports[{run_id}].fetch_windows_json"
    return tuple(
        WindowAccount(
            start=parse_utc_isoformat(str(w["start"]), context=context),
            end=parse_utc_isoformat(str(w["end"]), context=context),
            outcome=parse_enum(PathOutcome, str(w["outcome"]), context=f"{context}.outcome"),
        )
        for w in data
    )
