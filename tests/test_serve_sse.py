"""Behavioral claims on the SSE stream — replay, live follow, ending, keep-alive.

Every test drives the async generator over a bare ``Job`` (the bridge needs no
queue and no HTTP): a settled job's stream is fully collectable because the
generator terminates itself, and live-follow claims advance frame by frame with
``anext`` under a deadline — the generator suspends in its poll sleep between
frames, so the test controls exactly what the next snapshot sees. No test
sleeps its way to an assertion. The frame encoders' exact wire text is pinned
by their doctests; these tests compose the encoders to state *order* claims
without re-spelling the wire format.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from datetime import UTC, datetime

from steamlens.contracts import MetricEvent, StageEvent, StageKind
from steamlens.serve import Job, JobState
from steamlens.serve.sse import HEARTBEAT_FRAME, end_frame, event_frame, stream_job

_TICK_S = 0.001
_QUIET_HEARTBEAT_S = 60.0  # far beyond any test's runtime — heartbeats stay out of the way


def _job() -> Job:
    return Job(440, "Team Fortress 2", datetime.now(UTC))


def _stage(message: str) -> StageEvent:
    return StageEvent(stage="serve.fetch", kind=StageKind.PROGRESS, message=message)


async def _next(stream: AsyncIterator[str]) -> str:
    """The next frame within a deadline — a hung generator fails, never hangs the suite."""
    return await asyncio.wait_for(anext(stream), timeout=5.0)


def test_a_settled_job_replays_its_whole_history_then_ends() -> None:
    """A viewer attaching after the fact gets every event in arrival order,
    ids sequential from 0, the end frame last — and the stream closes itself."""
    job = _job()
    job.emit(_stage("window 1/2"))
    job.emit(MetricEvent(stage="serve.classify", name="cost", value=0.01, unit="usd"))
    job.mark_finished(JobState.DONE, None)

    async def collect() -> list[str]:
        return [
            frame
            async for frame in stream_job(job, tick_s=_TICK_S, heartbeat_s=_QUIET_HEARTBEAT_S)
        ]

    frames = asyncio.run(asyncio.wait_for(collect(), timeout=5.0))
    expected = [event_frame(index, event) for index, event in enumerate(job.events())]
    assert frames == expected + [end_frame(JobState.DONE, None)]


def test_a_live_viewer_follows_new_events_without_loss_or_doubling() -> None:
    """Attach mid-run: the history replays first, then each event emitted
    while the stream is live arrives exactly once, ids continuing where the
    replay left off — the snapshot-cursor contract across the boundary."""
    job = _job()
    job.emit(_stage("window 1/3"))

    async def drive() -> None:
        stream = stream_job(job, tick_s=_TICK_S, heartbeat_s=_QUIET_HEARTBEAT_S)
        assert await _next(stream) == event_frame(0, job.events()[0])

        job.emit(_stage("window 2/3"))
        assert await _next(stream) == event_frame(1, job.events()[1])

        job.mark_finished(JobState.DONE, None)
        assert await _next(stream) == event_frame(2, job.events()[2])
        assert await _next(stream) == end_frame(JobState.DONE, None)
        try:
            await _next(stream)
        except StopAsyncIteration:
            return
        raise AssertionError("the stream kept going after its end frame")

    asyncio.run(drive())


def test_a_failed_job_ends_with_the_error_on_the_wire() -> None:
    """The end frame carries FAILED and the why — the browser's one chance to
    tell the viewer what happened before closing."""
    job = _job()
    job.mark_finished(JobState.FAILED, "RunAbort: over budget")

    async def collect() -> list[str]:
        return [
            frame
            async for frame in stream_job(job, tick_s=_TICK_S, heartbeat_s=_QUIET_HEARTBEAT_S)
        ]

    frames = asyncio.run(asyncio.wait_for(collect(), timeout=5.0))
    assert frames[-1] == end_frame(JobState.FAILED, "RunAbort: over budget")


def test_a_quiet_stream_heartbeats_then_resumes_narration() -> None:
    """Narration silence produces keep-alive comments, and the first real
    event after a heartbeat still arrives with its true history id — quiet
    time never consumes or reorders events."""
    job = _job()

    async def drive() -> None:
        stream = stream_job(job, tick_s=_TICK_S, heartbeat_s=2 * _TICK_S)
        assert await _next(stream) == HEARTBEAT_FRAME

        job.emit(_stage("window 1/1"))
        frame = await _next(stream)
        while frame == HEARTBEAT_FRAME:  # one more may already be due — never an event loss
            frame = await _next(stream)
        assert frame == event_frame(0, job.events()[0])

    asyncio.run(drive())
