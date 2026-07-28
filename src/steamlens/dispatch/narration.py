"""Run narration — the tee'd sink and the one stage emitter every driver shares."""

from __future__ import annotations

import sys
import threading
from datetime import UTC, datetime
from typing import TextIO

from steamlens.contracts import Sink, SinkEvent, StageEvent, StageKind


class TeeSink:
    """Narration to the console and a tail-able run log; metrics to the log only.

    Stage events are the human story — both surfaces get them. Metric events
    (six per model call) would drown a console at census scale, so they land
    only in the log file, greppable after the fact. The file is line-buffered
    so a second-pane ``tail`` follows the run live. ``emit`` is called from
    the client's worker threads, so each surface takes exactly one write per
    event under a lock — without it, lines interleave mid-line in the very
    file that exists to be tailed and grepped.
    """

    def __init__(self, log: TextIO) -> None:
        self._log = log
        self._lock = threading.Lock()

    def emit(self, event: SinkEvent) -> None:
        stamp = datetime.now(UTC).strftime("%H:%M:%S")
        if isinstance(event, StageEvent):
            line = f"[{stamp}] {event.stage} {event.kind.value}: {event.message}\n"
            with self._lock:
                sys.stdout.write(line)
                self._log.write(line)
        else:
            line = f"[{stamp}] metric {event.stage} {event.name}={event.value} {event.unit}\n"
            with self._lock:
                self._log.write(line)


def narrate(sink: Sink, stage: str, kind: StageKind, message: str) -> None:
    """One driver stage event onto the run's sink — the shared emitter.

    Every dispatch driver narrates through this one function with its own
    ``stage`` vocabulary; the three per-driver copies it replaced had already
    begun to drift apart in signature.
    """
    sink.emit(StageEvent(stage=stage, kind=kind, message=message))
