"""Backfill the storefront captures for library games published before the capture existed.

The report job records a game's store facts and tag block after it publishes
(``storefront_capture``). Games published before that shipped have neither,
and a game whose capture met Steam trouble has a gap. This entry reads the
library from the published reports at run time, finds every game owed a
capture, and runs the same capture routine the job runs, through the same
Steam door, so a backfilled game is recorded exactly as a fresh job would
record it. There is no list of games in this file and no second copy of the
parsing.

It runs as a second process beside the serving app, inside the app's
container, which is why it yields to the app: it refuses to start while an
analysis job is live and stops at the next game if one starts, because each
process paces its own requests and the two together would double the rate
Steam sees. A stopped or interrupted run is resumed by running it again; the
games already captured are no longer owed.

Without ``--apply`` it prints the plan and reads nothing from Steam.

Run (in the container, the database path comes from ``STEAMLENS_DB_PATH``):
    python -m steamlens.serve.backfill_storefront
    python -m steamlens.serve.backfill_storefront --apply --only 782330
    python -m steamlens.serve.backfill_storefront --apply
"""

from __future__ import annotations

import argparse
import os
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Final

from steamlens.contracts import JobRow, Sink, SinkEvent, StageEvent, StageKind, UncapturedGame
from steamlens.dispatch import narrate
from steamlens.serve.storefront_capture import STOREFRONT_STAGE, capture_storefront
from steamlens.steam_client import SteamClient, SteamClientConfig, SteamTransport
from steamlens.store import Store, parse_utc_isoformat

LIVE_JOB_WINDOW: Final = timedelta(minutes=30)
"""How recently an unsettled job must have started to count as live. A job a
process death interrupted stays unsettled forever, so age is what separates
it from a running one; real jobs settle in single-digit minutes. The deploy
script applies the same rule with the same number."""

_RECENT_JOBS: Final = 5
"""How many of the newest journal rows the live check reads. Jobs run one at a
time, so a live one is always among the newest few."""


@dataclass(frozen=True, slots=True)
class BackfillTally:
    """What one backfill run did.

    ``games_read`` counts the games the run asked Steam about. ``left`` is
    how many of the selected games are still owed a capture afterwards: the
    ones a live job cut the run short of, plus any whose read failed.
    ``stopped_for`` is the live job that stopped the run, ``None`` when the
    run went through its whole selection.
    """

    games_read: int
    metadata_stored: int
    tags_stored: int
    left: int
    stopped_for: JobRow | None


def live_job(store: Store, now: datetime) -> JobRow | None:
    """The analysis job running at ``now``, or ``None``.

    An unsettled journal row that started within ``LIVE_JOB_WINDOW``.
    """
    cutoff = now - LIVE_JOB_WINDOW
    for job in store.ops.recent_jobs(_RECENT_JOBS):
        started = parse_utc_isoformat(job.started_at, context=f"jobs[{job.run_id}]")
        if job.finished_at is None and started > cutoff:
            return job
    return None


def owed_games(store: Store, only: int | None) -> tuple[UncapturedGame, ...]:
    """The library games owed a capture, narrowed to ``only`` when it is given."""
    games = store.storefront.uncaptured_library_games()
    if only is None:
        return games
    return tuple(game for game in games if game.app_id == only)


def backfill(
    steam: SteamClient,
    store: Store,
    sink: Sink,
    *,
    now: Callable[[], datetime],
    only: int | None = None,
) -> BackfillTally:
    """Capture every owed game, yielding to a live analysis job.

    The live check runs before each game, so a job that starts mid-run costs
    at most the one game already in flight. Each game is asked only for the
    record it lacks. One game's Steam trouble is narrated and the run moves
    on; that game simply stays owed.
    """
    games_read = metadata_stored = tags_stored = 0
    stopped_for: JobRow | None = None
    for game in owed_games(store, only):
        stopped_for = live_job(store, now())
        if stopped_for is not None:
            narrate(
                sink, STOREFRONT_STAGE, StageKind.WARN,
                f"stopping: an analysis is live ({stopped_for.requested_name}, app "
                f"{stopped_for.app_id}, since {stopped_for.started_at}); run again once "
                "it has finished",
            )
            break
        result = capture_storefront(
            steam, store, game.app_id, sink,
            metadata=game.needs_metadata, tags=game.needs_tags,
        )
        games_read += 1
        metadata_stored += result.metadata
        tags_stored += result.tags
    return BackfillTally(
        games_read=games_read,
        metadata_stored=metadata_stored,
        tags_stored=tags_stored,
        left=len(owed_games(store, only)),
        stopped_for=stopped_for,
    )


class _ConsoleSink:
    """Stage narration to stdout, one line per event; metrics are dropped."""

    def emit(self, event: SinkEvent) -> None:
        if isinstance(event, StageEvent):
            print(f"{event.stage} {event.kind.value}: {event.message}", flush=True)


def _owed_line(game: UncapturedGame) -> str:
    owed = [
        label
        for label, needed in (("metadata", game.needs_metadata), ("tags", game.needs_tags))
        if needed
    ]
    return f"  {game.app_id}: {game.name} ({' and '.join(owed)})"


def main() -> None:
    """Print the plan, or with ``--apply`` run it; exits 1 when a live job stopped it."""
    parser = argparse.ArgumentParser(description=(__doc__ or "").splitlines()[0])
    parser.add_argument("--apply", action="store_true", help="read Steam and write (default: plan)")
    parser.add_argument("--only", type=int, metavar="APP_ID", help="restrict the run to one game")
    args = parser.parse_args()
    db_path = Path(os.environ.get("STEAMLENS_DB_PATH", "data/serve.db"))
    if not db_path.exists():
        raise SystemExit(f"no database at {db_path} (set STEAMLENS_DB_PATH)")

    with Store(db_path) as store:
        games = owed_games(store, args.only)
        print(f"library games owed a storefront capture: {len(games)}")
        if not args.apply:
            for game in games:
                print(_owed_line(game))
            print("plan only: pass --apply to read Steam and record")
            return
        sink = _ConsoleSink()
        with SteamTransport(SteamClientConfig(), sink) as transport:
            tally = backfill(
                SteamClient(transport), store, sink,
                now=lambda: datetime.now(UTC), only=args.only,
            )
    print(
        f"games read: {tally.games_read}; metadata recorded: {tally.metadata_stored}; "
        f"tag blocks recorded: {tally.tags_stored}; still owed: {tally.left}"
    )
    if tally.stopped_for is not None:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
