"""SSE wire encoding and the replay-then-follow stream over one job's history.

The narration bridge's core, split the usual way: pure frame encoders (sink
event → server-sent-event text) that the doctests pin exactly, and the one
async generator the HTTP shell hands to a streaming response. The design ruled
SSE over WebSockets (one-directional typed events need no back-channel) and
full-history replay on connect — a viewer attaching mid-run, or reconnecting,
sees the story from the start because the job holds its event list in memory
anyway.

The follower *polls* snapshots rather than subscribing: narration arrives at
seconds scale, so a sub-second tick is invisible to a viewer, and per-viewer
listener queues on the job would be lifecycle machinery buying latency nobody
can perceive. Polling is also what keeps the bridge open to scaling past one
process: the generator consumes only a job's snapshot surface — ``events()``,
``state``, ``error`` — which an external event log (say, DB- or Redis-backed
behind several web replicas) satisfies just as well as the in-process ``Job``;
a subscriber registration would have bound it to process locality.

One ordering fact makes the ending safe: ``Job`` appends its terminal
narration *before* flipping to a settled state, so a snapshot taken after
observing ``DONE``/``FAILED`` is guaranteed complete — the stream can never
drop the tail of the story.
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator
from dataclasses import asdict
from typing import Final

from steamlens.contracts import SinkEvent, StageEvent
from steamlens.serve.jobs import Job, JobState

HEARTBEAT_FRAME: Final = ": heartbeat\n\n"
"""A comment frame — ignored by ``EventSource``, but traffic enough to keep a
proxy's idle timeout from severing a quiet stream (a long fetch window can
narrate nothing for tens of seconds)."""

_SETTLED: Final = frozenset({JobState.DONE, JobState.FAILED})


def event_frame(index: int, event: SinkEvent) -> str:
    """One history event as an SSE frame: ``id`` is the event's history index.

    The ``event:`` name discriminates the closed ``SinkEvent`` union — the
    browser subscribes per kind (``addEventListener("stage")``) instead of
    switching on a payload field. JSON escaping keeps the payload to a single
    ``data:`` line even when a message contains newlines, which is what makes
    the frame framing-safe. Indices as ids cost nothing and would let a later
    build honor ``Last-Event-ID`` resume; today reconnect replays whole, as
    ruled.

    >>> from steamlens.contracts import MetricEvent, StageEvent, StageKind
    >>> print(event_frame(3, StageEvent(stage="fetch", kind=StageKind.PROGRESS, message="pg 1")))
    id: 3
    event: stage
    data: {"stage": "fetch", "kind": "progress", "message": "pg 1"}
    <BLANKLINE>
    <BLANKLINE>
    >>> print(event_frame(4, MetricEvent(stage="classify", name="cost", value=0.01, unit="usd")))
    id: 4
    event: metric
    data: {"stage": "classify", "name": "cost", "value": 0.01, "unit": "usd"}
    <BLANKLINE>
    <BLANKLINE>
    """
    name = "stage" if isinstance(event, StageEvent) else "metric"
    data = json.dumps(asdict(event), ensure_ascii=False)
    return f"id: {index}\nevent: {name}\ndata: {data}\n\n"


def end_frame(state: JobState, error: str | None) -> str:
    """The terminal control frame: the settled state, and why if it failed.

    ``EventSource`` auto-reconnects forever after the server closes, so the
    stream must say "the story is over" in-band — the browser closes on this
    event. Carries no ``id``: it is a control signal, not a history entry.

    >>> end_frame(JobState.DONE, None)
    'event: end\\ndata: {"state": "done", "error": null}\\n\\n'
    >>> end_frame(JobState.FAILED, "RunAbort: over budget")
    'event: end\\ndata: {"state": "failed", "error": "RunAbort: over budget"}\\n\\n'
    """
    data = json.dumps({"state": state.value, "error": error})
    return f"event: end\ndata: {data}\n\n"


async def stream_job(job: Job, *, tick_s: float, heartbeat_s: float) -> AsyncIterator[str]:
    """Replay ``job``'s history from the start, then follow live until it settles.

    The async side's whole footprint: yields every history event as a frame in
    arrival order, polls for new ones at ``tick_s``, emits a heartbeat comment
    after ``heartbeat_s`` of narration silence (accumulated in ticks — keep-
    alive needs no precision), and ends with the terminal frame once the job
    settles and its history is fully drained. The settled check runs *before*
    each snapshot, so the terminal narration — appended before the state flip —
    is always delivered ahead of the end frame.
    """
    cursor = 0
    quiet_s = 0.0
    while True:
        state = job.state
        events = job.events()
        for index in range(cursor, len(events)):
            yield event_frame(index, events[index])
        if state in _SETTLED:
            yield end_frame(state, job.error)
            return
        if cursor == len(events):
            quiet_s += tick_s
            if quiet_s >= heartbeat_s:
                yield HEARTBEAT_FRAME
                quiet_s = 0.0
        else:
            quiet_s = 0.0
        cursor = len(events)
        await asyncio.sleep(tick_s)
