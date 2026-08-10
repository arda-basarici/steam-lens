"""One cold analysis as an owned object, and the queue that runs them one at a time.

The deployment design's serving skeleton: only *jobs* — the minutes-long,
money-spending fetch→classify→mint→detect→compose pipeline — serialize, because
concurrent jobs would share the single Steam politeness budget anyway, making
both slower and the narration timings misleading. A ``Job`` carries its state
and its full event history; the history is the replay source the SSE bridge
serves on connect, so a viewer attaching mid-run (or after a reconnect) sees
the story from the start. A request for a game already queued or running
attaches to the existing job — one fetch, one spend, any number of viewers —
which is why the queue, not the caller, owns the app-id → live-job index.

What runs inside a job is injected (``run_job``): the queue owns lifecycle and
serialization only, so its tests need no pipeline and the runner's tests need
no queue. The accepted deployment cost stated once: a process death kills the
active job — jobs are re-runnable and the content-keyed archive makes the
re-run nearly free — so ``close`` drains, it does not interrupt.
"""

from __future__ import annotations

import threading
from collections import deque
from collections.abc import Callable
from datetime import UTC, datetime
from enum import StrEnum

from steamlens.contracts import SinkEvent, StageEvent, StageKind

_STAGE = "serve.job"


def _utc_now() -> datetime:
    return datetime.now(UTC)


class JobState(StrEnum):
    """Where a job stands in its one-way lifecycle.

    ``QUEUED`` → ``RUNNING`` → ``DONE`` or ``FAILED``; there is no retry state
    because a failed job is simply re-submittable — the archive makes the
    re-run cheap and the queue treats it as a fresh job.
    """

    QUEUED = "queued"
    RUNNING = "running"
    DONE = "done"
    FAILED = "failed"


class Job:
    """One cold analysis: identity, state, and the replayable narration history.

    Satisfies the ``Sink`` protocol — the runner narrates *into the job*, and
    every event lands in the history in arrival order. ``events`` snapshots
    under the same lock ``emit`` appends under, so a replay-then-follow
    consumer can take the snapshot, remember its length, and resume from
    there without losing or doubling an event. ``error`` is set exactly when
    the state is ``FAILED``.
    """

    def __init__(
        self,
        app_id: int,
        requested_name: str,
        created_at: datetime,
        client_ip: str | None = None,
        *,
        now: Callable[[], datetime] = _utc_now,
    ) -> None:
        self.app_id = app_id
        self.requested_name = requested_name
        self.created_at = created_at
        # Who asked — an opaque fairness tag the queue only ever compares
        # (the submit gate's one-in-flight-per-visitor read); None for
        # non-HTTP submitters (tests, a future CLI).
        self.client_ip = client_ip
        self._now = now
        self._lock = threading.Lock()
        self._state = JobState.QUEUED
        self._error: str | None = None
        # Arrival-stamped internally so stage timings derive from the story
        # the job already tells (no runner instrumentation); the SSE wire
        # sees plain events, unchanged.
        self._events: list[tuple[datetime, SinkEvent]] = []

    @property
    def state(self) -> JobState:
        with self._lock:
            return self._state

    @property
    def error(self) -> str | None:
        """Why the job failed — ``None`` unless the state is ``FAILED``."""
        with self._lock:
            return self._error

    def emit(self, event: SinkEvent) -> None:
        """Append one narration event to the history (the ``Sink`` contract)."""
        stamped = (self._now(), event)
        with self._lock:
            self._events.append(stamped)

    def events(self) -> tuple[SinkEvent, ...]:
        """The history so far, in arrival order — the SSE replay source."""
        with self._lock:
            return tuple(event for _, event in self._events)

    def timed_events(self) -> tuple[tuple[datetime, SinkEvent], ...]:
        """The history with each event's arrival instant — the stage-timing source.

        The journal wrapper derives per-stage spans from these at settlement
        (``stage_spans``); timing rides the narration the job already
        collects, so the runner needs no instrumentation of its own.
        """
        with self._lock:
            return tuple(self._events)

    def mark_started(self) -> None:
        """Flip to ``RUNNING`` and narrate it — the queue's call, nobody else's.

        Python has no friend classes, so the lifecycle transitions are public
        with their owner stated: the worker loop drives them; every other
        holder of a ``Job`` (the SSE bridge, a test) only reads.
        """
        with self._lock:
            self._state = JobState.RUNNING
        self.emit(StageEvent(stage=_STAGE, kind=StageKind.STARTED, message="analysis started"))

    def mark_finished(self, state: JobState, error: str | None) -> None:
        """Settle the job as ``DONE`` or ``FAILED`` and narrate the outcome —
        the queue's call, same ownership as ``mark_started``."""
        if state is JobState.FAILED:
            self.emit(
                StageEvent(
                    stage=_STAGE, kind=StageKind.WARN, message=f"analysis failed: {error}"
                )
            )
        else:
            self.emit(StageEvent(stage=_STAGE, kind=StageKind.DONE, message="analysis complete"))
        with self._lock:
            self._state = state
            self._error = error


def stage_spans(
    timed: tuple[tuple[datetime, SinkEvent], ...],
) -> dict[str, tuple[datetime, datetime]]:
    """Each stage's first and last narration instants — the derived stage timings.

    Approximate by nature and declared so: a stage's span is when it *spoke*,
    not instrumented boundaries, and overlapped stages (the fetch/classify
    seam) show overlapping spans — exactly the honest picture. This is what
    the journal settles as ``stage_timings_json`` and what the parked
    narration-ETA calibration will read.
    """
    spans: dict[str, tuple[datetime, datetime]] = {}
    for instant, event in timed:
        first, _ = spans.get(event.stage, (instant, instant))
        spans[event.stage] = (first, instant)
    return spans


class JobQueue:
    """The one-at-a-time cold-job queue with same-game attach.

    Construction starts the worker thread; jobs run strictly in submission
    order on that one thread. ``run_job`` is the pipeline seam — an exception
    escaping it fails that job (state, error, and a WARN event recorded) and
    the queue moves on; nothing a job does can take the queue down with it.
    ``now`` is the test seam for job timestamps.
    """

    def __init__(
        self,
        run_job: Callable[[Job], None],
        *,
        now: Callable[[], datetime] = _utc_now,
    ) -> None:
        self._run_job = run_job
        self._now = now
        self._wake = threading.Condition()
        self._pending: deque[Job] = deque()
        self._active: Job | None = None
        self._live: dict[int, Job] = {}
        self._closed = False
        self._thread = threading.Thread(
            target=self._work, name="steamlens-job-queue", daemon=True
        )
        self._thread.start()

    def submit(
        self, app_id: int, requested_name: str, *, client_ip: str | None = None
    ) -> Job:
        """Queue a cold analysis of ``app_id`` — or attach to the live one.

        Returns the already-queued-or-running job when one exists for this
        app id (the caller distinguishes by identity or state if it cares);
        otherwise a fresh ``QUEUED`` job, birth-narrated with its queue
        position and tagged with ``client_ip`` for the fairness read. An
        attach keeps the original job's tag — the first asker owns the
        in-flight slot. Raises ``RuntimeError`` after ``close`` — a draining
        queue must refuse work loudly, not accept jobs that will never run.
        """
        with self._wake:
            if self._closed:
                raise RuntimeError("job queue is closed — refusing a job that would never run")
            existing = self._live.get(app_id)
            if existing is not None:
                return existing
            job = Job(app_id, requested_name, self._now(), client_ip, now=self._now)
            self._live[app_id] = job
            self._pending.append(job)
            ahead = len(self._pending) - 1 + (1 if self._active is not None else 0)
            job.emit(
                StageEvent(
                    stage=_STAGE,
                    kind=StageKind.PROGRESS,
                    message=f"queued — {ahead} analysis(es) ahead",
                )
            )
            self._wake.notify()
            return job

    def live(self, app_id: int) -> Job | None:
        """The queued-or-running job for ``app_id``, or ``None`` — never creates.

        The side-effect-free read the SSE route attaches through: a GET must
        not mint a job, so lookup and submission are separate surfaces. A
        finished job is absent by design — its report is the persistence
        layer's to serve, not the queue's.
        """
        with self._wake:
            return self._live.get(app_id)

    def worker_alive(self) -> bool:
        """Whether the worker thread is running — the health check's liveness read.

        False means jobs would queue forever: the thread died (or the queue
        closed), which is exactly the state ``/healthz`` exists to surface.
        """
        return self._thread.is_alive()

    def has_live_from(self, client_ip: str) -> bool:
        """Whether ``client_ip`` already has a queued-or-running job — the
        submit gate's one-in-flight-per-visitor read. Scans the live index
        (dozens of jobs at most, by the daily allowance's construction)."""
        with self._wake:
            return any(job.client_ip == client_ip for job in self._live.values())

    def position(self, job: Job) -> int:
        """How many jobs run before ``job``: 0 means running (or already finished)."""
        with self._wake:
            for index, pending in enumerate(self._pending):
                if pending is job:
                    return index + (1 if self._active is not None else 0)
            return 0

    def close(self) -> None:
        """Stop accepting work, let the active job finish, abandon the rest.

        Blocks until the worker thread exits — at most one job's remaining
        runtime. Still-queued jobs are left ``QUEUED`` and never run: the
        process is going down anyway, and their games re-analyze nearly free
        on resubmission thanks to the content-keyed archive.
        """
        with self._wake:
            self._closed = True
            self._wake.notify()
        self._thread.join()

    def _work(self) -> None:
        while True:
            with self._wake:
                while not self._pending and not self._closed:
                    self._wake.wait()
                if self._closed:
                    return
                job = self._pending.popleft()
                self._active = job
            job.mark_started()
            try:
                self._run_job(job)
            except Exception as exc:  # noqa: BLE001 — the job fails; the queue survives
                outcome, error = JobState.FAILED, f"{type(exc).__name__}: {exc}"
            else:
                outcome, error = JobState.DONE, None
            job.mark_finished(outcome, error)
            with self._wake:
                self._active = None
                del self._live[job.app_id]
