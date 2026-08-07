"""Behavioral claims on the HTTP shell — intake receipts, attach, the SSE wire end to end.

Every test drives the real app over httpx's in-process ASGI transport — no
server, no sockets — with a scripted, gated pipeline injected through the
queue's ``run_job`` seam, the same valve discipline as the queue tests: the
gate makes mid-run states observable deterministically, and waits poll with a
deadline instead of sleeping to an assertion.

One transport fact shapes the streaming test: ``ASGITransport`` runs the app
to *completion* before handing back any of the response (probed 2026-08-07 —
even response-start waits), so a client-side read can never sequence a mid-
stream event. The mid-run attach is therefore sequenced by a server-side
observable — a test queue whose read-only ``live`` lookup signals the moment
the SSE route attached — and the claim here is composition: a viewer who
attached mid-run receives the COMPLETE story through HTTP. Client-side *live*
frame delivery is the generator's own claim, pinned in ``test_serve_sse``;
end-to-end liveness belongs to the real-server deployment smoke.
"""

from __future__ import annotations

import asyncio
import threading
import time
from collections.abc import Callable

from httpx import ASGITransport, AsyncClient

from steamlens.contracts import StageEvent, StageKind
from steamlens.serve import Job, JobQueue, JobState, ServeConfig, create_app

_CONFIG = ServeConfig(sse_tick_s=0.001, sse_heartbeat_s=60.0)


async def _until(predicate: Callable[[], bool], what: str, timeout_s: float = 5.0) -> None:
    """Poll ``predicate`` to true within ``timeout_s`` or fail with ``what``."""
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        if predicate():
            return
        await asyncio.sleep(0.005)
    raise AssertionError(f"timed out waiting for {what}")


class GatedNarrator:
    """A pipeline stand-in that narrates one window, then holds until released."""

    def __init__(self) -> None:
        self.order: list[int] = []
        self.release = threading.Event()

    def __call__(self, job: Job) -> None:
        self.order.append(job.app_id)
        job.emit(StageEvent(stage="serve.fetch", kind=StageKind.PROGRESS, message="window 1/1"))
        assert self.release.wait(5.0), "test never released the gated pipeline"


def test_submit_receipts_honestly_and_same_game_attaches() -> None:
    """POST answers 202 with state, queue position, and the stream URL; a
    second POST for the same game attaches — one fetch, one spend — while a
    different game queues behind with its position told straight."""
    runner = GatedNarrator()
    queue = JobQueue(runner)
    app = create_app(queue, _CONFIG)

    async def drive() -> None:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            first = await client.post(
                "/analyses", json={"app_id": 440, "requested_name": "Team Fortress 2"}
            )
            assert first.status_code == 202
            receipt = first.json()
            assert receipt["app_id"] == 440
            assert receipt["state"] in {JobState.QUEUED, JobState.RUNNING}
            assert receipt["position"] == 0
            assert receipt["events_url"] == "/analyses/440/events"

            attach = await client.post(
                "/analyses", json={"app_id": 440, "requested_name": "Team Fortress 2"}
            )
            assert attach.status_code == 202

            behind = await client.post(
                "/analyses", json={"app_id": 570, "requested_name": "Dota 2"}
            )
            assert behind.json()["state"] == JobState.QUEUED
            assert behind.json()["position"] == 1

    asyncio.run(asyncio.wait_for(drive(), timeout=10.0))
    runner.release.set()
    deadline = time.monotonic() + 5.0
    while queue.live(570) is not None and time.monotonic() < deadline:
        time.sleep(0.005)
    assert runner.order == [440, 570], "attach must not have minted a second 440 job"
    queue.close()


class AttachObservableQueue(JobQueue):
    """The real queue plus one test-only observable: the SSE route's read-only
    ``live`` lookup signals — the race-free moment to release the gated
    pipeline, since the buffering transport lets no client-side read do it."""

    def __init__(self, run_job: Callable[[Job], None]) -> None:
        super().__init__(run_job)
        self.attached = threading.Event()

    def live(self, app_id: int) -> Job | None:
        job = super().live(app_id)
        self.attached.set()
        return job


def test_a_mid_run_attach_streams_the_complete_story_to_the_end_frame() -> None:
    """A viewer whose GET verifiably attached while the job was still running
    (the gate held until the route's lookup) receives the whole story over
    HTTP — queued, started, the pipeline's own narration, completion — closed
    by the terminal end frame, on one connection."""
    runner = GatedNarrator()
    queue = AttachObservableQueue(runner)
    app = create_app(queue, _CONFIG)

    async def collect(client: AsyncClient) -> list[str]:
        async with client.stream("GET", "/analyses/440/events") as response:
            assert response.status_code == 200
            assert response.headers["content-type"].startswith("text/event-stream")
            return [line async for line in response.aiter_lines()]

    async def drive() -> list[str]:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            await client.post(
                "/analyses", json={"app_id": 440, "requested_name": "Team Fortress 2"}
            )
            await _until(lambda: bool(runner.order), "the pipeline to start")
            reader = asyncio.create_task(collect(client))
            await _until(queue.attached.is_set, "the SSE route to attach")
            runner.release.set()
            return await asyncio.wait_for(reader, timeout=5.0)

    lines = asyncio.run(asyncio.wait_for(drive(), timeout=10.0))
    story = [line for line in lines if line.startswith("data:")]
    assert any("queued" in line for line in story[:1])
    assert any("analysis started" in line for line in story)
    assert any("window 1/1" in line for line in story)
    assert any("analysis complete" in line for line in story)
    assert story[-1] == 'data: {"state": "done", "error": null}'
    meaningful = [line for line in lines if line]
    assert meaningful[-2] == "event: end", "the end frame must close the stream"
    queue.close()


def test_events_is_read_only_and_404s_without_a_live_job() -> None:
    """GET never mints a job: unknown apps 404, and a *finished* job 404s too —
    its report belongs to the persistence layer, not the queue."""
    runner = GatedNarrator()
    runner.release.set()
    queue = JobQueue(runner)
    app = create_app(queue, _CONFIG)

    async def drive() -> None:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            missing = await client.get("/analyses/999/events")
            assert missing.status_code == 404

            await client.post(
                "/analyses", json={"app_id": 440, "requested_name": "Team Fortress 2"}
            )
            await _until(lambda: queue.live(440) is None, "the job to finish and leave the index")
            finished = await client.get("/analyses/440/events")
            assert finished.status_code == 404
            assert runner.order == [440], "the GETs must not have queued anything"

    asyncio.run(asyncio.wait_for(drive(), timeout=10.0))
    queue.close()
