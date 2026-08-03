"""Fetch the fresh-buy session's review material — step 8's one shared fetch pass.

The fresh-buy session (DESIGN, "The fresh-buy session (step 8)") feeds three
consumers from one fetch: marked-window reviews for the mixing experiment,
whole-life long-tail corpora for the closing test, and both as draw material
for the human holdout. Everything goes through one ``SteamClient`` — the
production door, whose windowed-unfiltered walk this run exercises at its
broadest live scale yet (a 2019 window, an ongoing mark, three whole-life
spans); any WARN-narrated incompleteness lands in the manifest as step-8
evidence rather than a production surprise.

Marked windows are read live from each bomb game's ``past_events`` at run
time, never hardcoded from the pick probe — the manifest records the windows
the run actually fetched. Steam reports an ongoing mark as ``end_date=0``
(Book of Demons is the first such case this project has met, probe finding 6),
which the parser surfaces as an end at the epoch; the run substitutes its own
start instant as the concrete end and records the substitution. Long-tail
games get a whole-life window: first rollup bucket minus a margin through the
run's start — whole-life is the shape production reads, per the span-effect
ruling.

Reviews persist per game as ``<app_id>_reviews.jsonl`` in the corpus wire-key
format, so ``corpus.read_reviews_file`` — and with it labeling, the mixing
blends, and the holdout draw — consumes fresh material unchanged. Reception
metadata (playtime, helpful votes) is deliberately not retained: the ``Review``
contract leaves it off until a consumer needs it, and the manifest's window
records make a refetch cheap if the M4 reopener ever wants it for these six
games. Histogram snapshots persist in parsed form for window provenance; the
raw wire payloads already live in the pick probe's captures (bomb games) and
the discovery run (long-tail games).

Run from the repo root (~350 paced requests, ~10 minutes):
  uv run python scripts/fetch_freshbuy.py
"""

from __future__ import annotations

import argparse
import json
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Final, cast

from steamlens.contracts import (
    HistogramSnapshot,
    IdentityVerdict,
    Review,
    Sink,
    StageKind,
    WindowFetchResult,
)
from steamlens.dispatch.narration import TeeSink, narrate
from steamlens.dispatch.run_shell import write_manifest
from steamlens.dispatch.stamp import code_version, config_hash, mint_run_id
from steamlens.steam_client import SteamClient, SteamClientConfig, SteamClientError

_STAGE: Final = "m2.freshbuy.fetch"

# How far before the first histogram bucket a whole-life window opens: rollup
# buckets are stamped at period start, so the margin only needs to clear one
# bucket width (a month); a generous pad costs nothing on an empty span.
_WHOLE_LIFE_MARGIN: Final = timedelta(days=45)


@dataclass(frozen=True, slots=True)
class Pick:
    """One fresh-buy game: identity for the resolve guard, role for the manifest."""

    app_id: int
    name: str
    role: str  # "marked-window" | "long-tail"


# The step-8 picks as ruled (DESIGN, 2026-08-03); names are the store names
# the identity guard checks against.
PICKS: Final = (
    Pick(49520, "Borderlands 2", "marked-window"),
    Pick(449960, "Book of Demons", "marked-window"),
    Pick(292030, "The Witcher 3: Wild Hunt", "marked-window"),
    Pick(1918680, "Sword and Fairy Inn 2", "long-tail"),
    Pick(1863430, "Dragonkin: The Banished", "long-tail"),
    Pick(247000, "Talisman: Digital Classic Edition", "long-tail"),
)


def wire_row(review: Review) -> dict[str, object]:
    """One review as the corpus JSONL row shape ``review_from_raw`` reads back.

    The five keys are exactly the fields the corpus reader validates — the
    round-trip is the format contract, doctested here so a key drift fails
    loudly:

    >>> from datetime import UTC, datetime
    >>> from steamlens.contracts import Review
    >>> from steamlens.steam_client import review_from_raw
    >>> before = Review(review_id="7", app_id=1, language="english", text="hi",
    ...     created_at=datetime(2026, 1, 1, tzinfo=UTC), voted_up=True)
    >>> review_from_raw(wire_row(before), app_id=1) == before
    True
    """
    return {
        "recommendationid": review.review_id,
        "language": review.language,
        "review": review.text,
        "timestamp_created": int(review.created_at.timestamp()),
        "voted_up": review.voted_up,
    }


def snapshot_record(snapshot: HistogramSnapshot) -> dict[str, object]:
    """The parsed histogram as the run's provenance record (raw lives elsewhere)."""
    return {
        "app_id": snapshot.app_id,
        "rollup_unit": snapshot.rollup_unit.value,
        "fetched_at": snapshot.fetched_at.isoformat(),
        "rollups": [
            {"start": b.start.isoformat(), "up": b.recommendations_up,
             "down": b.recommendations_down}
            for b in snapshot.rollups
        ],
        "past_events": [
            {"type": e.event_type, "start": e.start.isoformat(),
             "end": e.end.isoformat()}
            for e in snapshot.past_events
        ],
    }


@dataclass(frozen=True, slots=True)
class WindowPlan:
    """One date window a pick asks for, with the note that explains it."""

    start: datetime
    end: datetime
    kind: str
    ongoing: bool


def plan_windows(
    pick: Pick, snapshot: HistogramSnapshot, run_start: datetime
) -> list[WindowPlan]:
    """The date windows this pick's role asks for, each with its provenance note.

    Marked-window picks fetch every flagged event; an event whose end does not
    follow its start is Steam's ongoing-mark encoding (``end_date=0`` parsed to
    the epoch) and gets the run's start as its concrete end, recorded as
    ``ongoing``. Long-tail picks fetch one whole-life window. A marked pick
    with no events on the wire returns an empty plan — the caller treats that
    as a loud failure, because the pick probe just verified the mark exists.
    """
    if pick.role == "long-tail":
        if not snapshot.rollups:
            return []
        start = snapshot.rollups[0].start - _WHOLE_LIFE_MARGIN
        return [WindowPlan(start, run_start, "whole-life", ongoing=False)]
    plans: list[WindowPlan] = []
    for event in snapshot.past_events:
        ongoing = event.end <= event.start
        plans.append(WindowPlan(
            event.start,
            run_start if ongoing else event.end,
            f"marked-window(type={event.event_type})",
            ongoing=ongoing,
        ))
    return plans


def window_record(
    plan: WindowPlan, result: WindowFetchResult, english: int
) -> dict[str, object]:
    """One fetched window's manifest entry — the walk's provenance, kept whole."""
    return {
        "kind": plan.kind,
        "ongoing": plan.ongoing,
        "start": result.window_start.isoformat(),
        "end": result.window_end.isoformat(),
        "outcome": result.outcome.value,
        "pages_fetched": result.pages_fetched,
        "retries": result.retries,
        "out_of_window": result.out_of_window_count,
        "reported_total": result.reported_total,
        "collected": len(result.reviews),
        "collected_english": english,
    }


def fetch_pick(
    client: SteamClient, sink: Sink, pick: Pick, run_dir: Path, run_start: datetime
) -> dict[str, object]:
    """One game end to end: resolve, snapshot, fetch its windows, persist.

    Returns the pick's manifest record. A resolve that fails the identity
    guard skips the fetch — a hundred pages of the wrong game is worse than a
    recorded hole — and an empty window plan on a marked pick is recorded the
    same way (the probe said the mark exists; silence here means the wire
    changed and the buy must not proceed on this game).
    """
    ref = client.resolve_game(pick.app_id, pick.name)
    record: dict[str, object] = {
        "app_id": pick.app_id, "name": pick.name, "role": pick.role,
        "identity": ref.verdict.value, "store_name": ref.store_name,
        "store_total_reviews": ref.total_reviews,
    }
    if ref.verdict is not IdentityVerdict.OK:
        narrate(sink, _STAGE, StageKind.WARN,
                f"{pick.name}: identity {ref.verdict.value} "
                f"(store says {ref.store_name!r}) — skipping the fetch")
        record["windows"] = []
        return record

    snapshot = client.fetch_histogram(pick.app_id)
    (run_dir / "histograms").mkdir(parents=True, exist_ok=True)
    (run_dir / "histograms" / f"{pick.app_id}.json").write_text(
        json.dumps(snapshot_record(snapshot), indent=1), encoding="utf-8")

    plans = plan_windows(pick, snapshot, run_start)
    if not plans:
        narrate(sink, _STAGE, StageKind.WARN,
                f"{pick.name}: no fetchable window on the wire — skipping")
        record["windows"] = []
        return record

    windows: list[dict[str, object]] = []
    reviews_path = run_dir / f"{pick.app_id}_reviews.jsonl"
    with reviews_path.open("w", encoding="utf-8") as out:
        for plan in plans:
            result = client.fetch_window(pick.app_id, plan.start, plan.end)
            english = sum(r.language == "english" for r in result.reviews)
            for review in result.reviews:
                out.write(json.dumps(wire_row(review), ensure_ascii=False) + "\n")
            windows.append(window_record(plan, result, english))
            narrate(
                sink, _STAGE, StageKind.PROGRESS,
                f"{pick.name}: {plan.kind} "
                f"{result.window_start.date()} -> {result.window_end.date()} · "
                f"{result.outcome.value} · {len(result.reviews):,} reviews "
                f"(en {english:,}) · reported {result.reported_total} · "
                f"{result.pages_fetched} pages",
            )
    record["windows"] = windows
    return record


def main() -> int:
    """Compose the run: resolve and fetch each pick, manifest the whole pass."""
    parser = argparse.ArgumentParser(
        description="Fetch the fresh-buy session's marked-window and long-tail reviews."
    )
    parser.add_argument("--out", type=Path, default=Path("data/freshbuy"))
    args = parser.parse_args()

    started = datetime.now(UTC)
    run_id = mint_run_id("freshbuy", started)
    run_dir = args.out / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    code = code_version()

    aborted: str | None = None
    games: list[dict[str, object]] = []
    with (run_dir / "run.log").open("a", encoding="utf-8", buffering=1) as log:
        sink: Sink = TeeSink(log)
        config = SteamClientConfig()
        narrate(sink, _STAGE, StageKind.STARTED,
                f"run {run_id} · code {code} · {len(PICKS)} picks")
        client = SteamClient(config, sink)
        try:
            for pick in PICKS:
                games.append(fetch_pick(client, sink, pick, run_dir, started))
        except KeyboardInterrupt:
            aborted = "keyboard interrupt"
        except SteamClientError as exc:
            aborted = f"{type(exc).__name__}: {exc}"
        finally:
            client.close()

        collected_total = sum(
            int(cast(int, w["collected"]))
            for g in games
            for w in cast("list[dict[str, object]]", g["windows"])
        )
        write_manifest(run_dir, {
            "run_id": run_id,
            "code_version": code,
            "config_hash": config_hash({
                "picks": [[p.app_id, p.name, p.role] for p in PICKS],
                "whole_life_margin_days": _WHOLE_LIFE_MARGIN.days,
                "pacing_floor_s": config.pacing_floor_s,
                "num_per_page": config.num_per_page,
            }),
            "games": games,
            "started_at": started.isoformat(),
            "finished_at": datetime.now(UTC).isoformat(),
            "aborted": aborted,
        })
        narrate(sink, _STAGE,
                StageKind.WARN if aborted else StageKind.DONE,
                f"{'aborted: ' + aborted if aborted else 'done'} · "
                f"{collected_total:,} reviews across {len(games)} games · {run_dir}")
    return 1 if aborted else 0


if __name__ == "__main__":
    raise SystemExit(main())
