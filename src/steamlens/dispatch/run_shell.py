"""The run shell's mechanical pieces — one lifetime for the log, the sink, and the stores.

Every dispatch driver opens the same shell around its run: the run directory,
a line-buffered ``run.log`` tee'd with the console, and two ``Store``
connections over the one database file. The two-connection split is the
two-writer design, stated once here instead of re-derived per driver: the
client's cache/ledger writes happen on worker threads over the first
connection, the driver's envelope writes on the main thread over the second —
transactions are connection-scoped, so a worker's mid-call cache write can
never land inside (and be rolled back with) a driver-side transaction; the
store's WAL + busy-timeout provisioning carries the coordination.

Deliberately not a driver framework: selection, dispatch shape, the abort
ladder, and manifest content differ between drivers for real reasons and
stay in each composition root.
"""

from __future__ import annotations

import json
from collections.abc import Generator, Mapping
from contextlib import contextmanager
from pathlib import Path

from steamlens.dispatch.narration import TeeSink
from steamlens.store import Store


@contextmanager
def run_context(
    runs_dir: Path, run_id: str, db_path: Path
) -> Generator[tuple[TeeSink, Store, Store]]:
    """The run's shell, open for exactly the run's duration.

    Creates ``runs_dir/<run_id>``, opens its ``run.log`` append/UTF-8/
    line-buffered (so a second-pane ``tail`` follows the run live), and yields
    ``(sink, client_store, driver_store)`` — the tee'd sink plus the
    two-writer connection pair (module docstring). Everything closes on exit,
    normal or aborting.
    """
    run_dir = runs_dir / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    with (
        (run_dir / "run.log").open("a", encoding="utf-8", buffering=1) as log,
        Store(db_path) as client_store,
        Store(db_path) as driver_store,
    ):
        yield TeeSink(log), client_store, driver_store


def write_manifest(run_dir: Path, payload: Mapping[str, object]) -> Path:
    """Write the run's ``manifest.json`` and return its path.

    Human-first rendering (indented, unescaped non-ASCII) — the manifest is
    the run's read-me-later record, not a wire format.
    """
    path = run_dir / "manifest.json"
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    return path
