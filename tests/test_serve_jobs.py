"""Behavioral claims on the job queue — serialization, attach, containment, drain.

The queue's promises are lifecycle promises, so every test drives it with a
scripted stand-in for the pipeline (``run_job`` is the injection seam): a
gate the test releases makes concurrency observable deterministically, and
no test sleeps its way to an assertion — waits poll with a deadline.
"""

from __future__ import annotations

import threading
import time
from collections.abc import Callable

import pytest

from steamlens.contracts import StageEvent, StageKind
from steamlens.serve import Job, JobQueue, JobState


def _wait_for(predicate: Callable[[], bool], what: str, timeout_s: float = 5.0) -> None:
    """Poll ``predicate`` to true within ``timeout_s`` or fail with ``what``."""
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        if predicate():
            return
        time.sleep(0.005)
    raise AssertionError(f"timed out waiting for {what}")


class GatedRunner:
    """A pipeline stand-in the test opens and closes like a valve.

    Records the app ids it ran in order; ``started`` signals a job is inside;
    ``release`` lets it finish. ``fail_apps`` raise instead of returning —
    the containment claim's lever.
    """

    def __init__(self, fail_apps: frozenset[int] = frozenset()) -> None:
        self.order: list[int] = []
        self.started = threading.Event()
        self.release = threading.Event()
        self._fail_apps = fail_apps

    def __call__(self, job: Job) -> None:
        self.order.append(job.app_id)
        self.started.set()
        assert self.release.wait(5.0), "test never released the gated runner"
        if job.app_id in self._fail_apps:
            raise ValueError("scripted pipeline failure")


def test_jobs_run_serially_in_submission_order() -> None:
    """The second job must not start while the first is inside the runner —
    one politeness budget, one honest narration timeline."""
    runner = GatedRunner()
    queue = JobQueue(runner)
    first = queue.submit(440, "Team Fortress 2")
    second = queue.submit(570, "Dota 2")

    _wait_for(runner.started.is_set, "the first job to start")
    assert first.state is JobState.RUNNING
    assert second.state is JobState.QUEUED
    assert runner.order == [440]
    assert queue.position(second) == 1

    runner.release.set()
    _wait_for(lambda: second.state is JobState.DONE, "both jobs to finish")
    assert first.state is JobState.DONE
    assert runner.order == [440, 570]
    queue.close()


def test_same_game_attaches_to_the_live_job() -> None:
    """A request for the game already queued or running gets THE job back —
    one fetch, one spend, any number of viewers — and a finished game
    resubmits as a fresh job (the cache bypass lives above the queue)."""
    runner = GatedRunner()
    queue = JobQueue(runner)
    running = queue.submit(440, "Team Fortress 2")
    _wait_for(runner.started.is_set, "the job to start")

    assert queue.submit(440, "Team Fortress 2") is running

    queued = queue.submit(570, "Dota 2")
    assert queue.submit(570, "Dota 2") is queued

    runner.release.set()
    _wait_for(lambda: queued.state is JobState.DONE, "the queue to drain")
    assert queue.submit(440, "Team Fortress 2") is not running
    queue.close()


def test_a_failing_job_is_contained_and_the_queue_moves_on() -> None:
    """An exception escaping the pipeline fails THAT job — state, error, and
    a WARN event recorded — and the next job still runs."""
    runner = GatedRunner(fail_apps=frozenset({440}))
    runner.release.set()
    queue = JobQueue(runner)
    failing = queue.submit(440, "Team Fortress 2")
    surviving = queue.submit(570, "Dota 2")

    _wait_for(lambda: surviving.state is JobState.DONE, "both jobs to settle")
    assert failing.state is JobState.FAILED
    assert failing.error is not None and "scripted pipeline failure" in failing.error
    warns = [
        event
        for event in failing.events()
        if isinstance(event, StageEvent) and event.kind is StageKind.WARN
    ]
    assert any("analysis failed" in event.message for event in warns)
    assert surviving.error is None
    queue.close()


def test_the_event_history_replays_the_whole_story_in_order() -> None:
    """A viewer attaching after the fact sees queued → started → the
    pipeline's own narration → done, in arrival order — the SSE replay
    contract."""

    def narrating_pipeline(job: Job) -> None:
        job.emit(StageEvent(stage="serve.fetch", kind=StageKind.PROGRESS, message="window 1/3"))

    queue = JobQueue(narrating_pipeline)
    job = queue.submit(440, "Team Fortress 2")
    _wait_for(lambda: job.state is JobState.DONE, "the job to finish")

    stages = [
        (event.stage, event.kind)
        for event in job.events()
        if isinstance(event, StageEvent)
    ]
    assert stages == [
        ("serve.job", StageKind.PROGRESS),
        ("serve.job", StageKind.STARTED),
        ("serve.fetch", StageKind.PROGRESS),
        ("serve.job", StageKind.DONE),
    ]
    queue.close()


def test_close_drains_the_active_job_and_abandons_the_queue() -> None:
    """Close lets the running job finish, never runs the still-queued one,
    and refuses new work loudly afterwards."""
    runner = GatedRunner()
    queue = JobQueue(runner)
    active = queue.submit(440, "Team Fortress 2")
    abandoned = queue.submit(570, "Dota 2")
    _wait_for(runner.started.is_set, "the first job to start")

    closer = threading.Thread(target=queue.close)
    closer.start()
    runner.release.set()
    closer.join(5.0)
    assert not closer.is_alive(), "close never returned"

    assert active.state is JobState.DONE
    assert abandoned.state is JobState.QUEUED
    assert runner.order == [440]
    with pytest.raises(RuntimeError, match="closed"):
        queue.submit(730, "Counter-Strike 2")


def test_timed_events_stamp_arrival_and_stage_spans_derive_the_story() -> None:
    """Events stamp their arrival instants internally (the SSE-facing history
    unchanged), and stage_spans reads first-to-last narration per stage —
    overlapping stages show overlapping spans, which is the honest picture."""
    from datetime import UTC, datetime, timedelta

    from steamlens.serve import stage_spans

    base = datetime(2026, 8, 9, 12, 0, tzinfo=UTC)
    ticks = iter(base + timedelta(seconds=s) for s in (0, 10, 20, 30))
    job = Job(440, "TF2", base, now=lambda: next(ticks))
    for stage in ("serve.fetch", "serve.fetch", "serve.classify", "serve.fetch"):
        job.emit(StageEvent(stage=stage, kind=StageKind.PROGRESS, message="x"))

    assert len(job.events()) == 4, "the plain history keeps its shape"
    spans = stage_spans(job.timed_events())
    assert spans["serve.fetch"] == (base, base + timedelta(seconds=30))
    assert spans["serve.classify"] == (
        base + timedelta(seconds=20),
        base + timedelta(seconds=20),
    )
