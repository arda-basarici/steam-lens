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
from datetime import UTC, datetime

from httpx import ASGITransport, AsyncClient

from steamlens.contracts import (
    ClassifierVersions,
    ComposedNarrative,
    GameSearchHit,
    HistogramSnapshot,
    NarrativeOutcome,
    Provenance,
    Report,
    RollupUnit,
    StageEvent,
    StageKind,
)
from steamlens.serve import Job, JobQueue, JobState, ServeConfig, create_app
from steamlens.serve.gate import (
    DAY_USED_MESSAGE,
    IN_FLIGHT_MESSAGE,
    SEARCH_LIMIT_MESSAGE,
    UNLOCK_COOKIE,
    SearchLimiter,
    SubmitGate,
)
from steamlens.steam_client import SteamUnavailableError

_CONFIG = ServeConfig(sse_tick_s=0.001, sse_heartbeat_s=60.0)


def _no_search(_term: str) -> tuple[GameSearchHit, ...]:
    """The search seam's inert stand-in for tests that never search."""
    return ()


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
    app = create_app(queue, _CONFIG, lambda _: None, _no_search)

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
    app = create_app(queue, _CONFIG, lambda _: None, _no_search)

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


def _cached_report(app_id: int = 440) -> Report:
    """A minimal published report — the bypass seam needs identity + provenance,
    not the display structures, so those stay empty."""
    stamp = datetime(2026, 8, 1, tzinfo=UTC)
    return Report(
        run=Provenance(
            run_id="serve-old", code_version="abc1234", created_at=stamp,
            config_hash="cfg",
        ),
        app_id=app_id,
        game_name="Team Fortress 2",
        created_at=stamp,
        versions=ClassifierVersions(
            model_version="m", prompt_version="p", ontology_version="v"
        ),
        sample_size=250,
        take_all=False,
        windows=(),
        language_mix=(),
        narrative=ComposedNarrative(prose="", spans=(), outcome=NarrativeOutcome.WITHHELD),
        histogram=HistogramSnapshot(
            app_id=app_id, rollup_unit=RollupUnit.MONTH, rollups=(),
            recent_daily=(), past_events=(), fetched_at=stamp,
        ),
        episodes=(),
        marked_window_counts=(),
    )


def test_cached_game_answers_200_without_minting_a_job() -> None:
    """The cached-game bypass: a published report answers the POST instantly —
    200 with the report's identity and its date worn openly, no job, no spend —
    while an unanalyzed game still queues with the 202 receipt."""
    runner = GatedNarrator()
    runner.release.set()
    queue = JobQueue(runner)
    app = create_app(
        queue, _CONFIG, lambda app_id: _cached_report() if app_id == 440 else None, _no_search
    )

    async def drive() -> None:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            cached = await client.post(
                "/analyses", json={"app_id": 440, "requested_name": "Team Fortress 2"}
            )
            assert cached.status_code == 200
            body = cached.json()
            assert body["run_id"] == "serve-old"
            assert body["sample_size"] == 250
            assert body["analyzed_at"].startswith("2026-08-01")
            assert body["report_url"] == "/reports/440/team-fortress-2"
            assert queue.live(440) is None, "the cached answer must not have queued a job"

            fresh = await client.post(
                "/analyses", json={"app_id": 570, "requested_name": "Dota 2"}
            )
            assert fresh.status_code == 202
            assert fresh.json()["events_url"] == "/analyses/570/events"

    asyncio.run(asyncio.wait_for(drive(), timeout=10.0))
    deadline = time.monotonic() + 5.0
    while queue.live(570) is not None and time.monotonic() < deadline:
        time.sleep(0.005)
    assert runner.order == [570], "only the unanalyzed game may have run"
    queue.close()


def test_events_is_read_only_and_404s_without_a_live_job() -> None:
    """GET never mints a job: unknown apps 404, and a *finished* job 404s too —
    its report belongs to the persistence layer, not the queue."""
    runner = GatedNarrator()
    runner.release.set()
    queue = JobQueue(runner)
    app = create_app(queue, _CONFIG, lambda _: None, _no_search)

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


def _recording_gate(
    queue: JobQueue,
    *,
    limit: int = 5,
    ip_limit: int = 5,
    backstop: float = 1.0,
    settled: float = 0.0,
    admin_token: str | None = None,
) -> tuple[SubmitGate, list[tuple[str, int, datetime]]]:
    """A gate over the real queue's in-flight read and an in-memory journal —
    the store never appears; the returned list is the admission record."""
    admitted: list[tuple[str, int, datetime]] = []
    gate = SubmitGate(
        daily_job_limit=limit,
        per_ip_daily_job_limit=ip_limit,
        daily_spend_backstop_usd=backstop,
        has_live_from=queue.has_live_from,
        admitted_since=lambda since: sum(1 for entry in admitted if entry[2] >= since),
        admitted_from_since=lambda ip, since: sum(
            1 for entry in admitted if entry[0] == ip and entry[2] >= since
        ),
        spent_since=lambda _since: settled,
        record_admission=lambda ip, app_id, at: admitted.append((ip, app_id, at)),
        admin_token=admin_token,
    )
    return gate, admitted


def test_gate_holds_one_slot_per_visitor_and_lets_attach_and_others_pass() -> None:
    """While a visitor's job runs: a second game from the same visitor is
    refused with the one-at-a-time message; re-asking the *same* game attaches
    ungated (no new admission); a different visitor (distinct forwarded IP)
    queues freely. The admission journal grows only for minted jobs."""
    runner = GatedNarrator()
    queue = JobQueue(runner)
    gate, admitted = _recording_gate(queue)
    app = create_app(queue, _CONFIG, lambda _: None, _no_search, gate=gate)

    async def drive() -> None:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            first = await client.post(
                "/analyses", json={"app_id": 440, "requested_name": "Team Fortress 2"}
            )
            assert first.status_code == 202
            assert len(admitted) == 1
            assert admitted[0][1] == 440

            second_game = await client.post(
                "/analyses", json={"app_id": 570, "requested_name": "Dota 2"}
            )
            assert second_game.status_code == 429
            assert second_game.json()["detail"] == IN_FLIGHT_MESSAGE

            attach = await client.post(
                "/analyses", json={"app_id": 440, "requested_name": "Team Fortress 2"}
            )
            assert attach.status_code == 202
            assert len(admitted) == 1, "an attach must not consume the day's allowance"

            other_visitor = await client.post(
                "/analyses",
                json={"app_id": 570, "requested_name": "Dota 2"},
                headers={"X-Forwarded-For": "203.0.113.9"},
            )
            assert other_visitor.status_code == 202
            assert admitted[1][:2] == ("203.0.113.9", 570)

    asyncio.run(asyncio.wait_for(drive(), timeout=10.0))
    runner.release.set()
    queue.close()


def test_gate_exhausted_day_refuses_with_the_honest_message() -> None:
    """The day's allowance consumed → 429 with the day-used text; the queue
    is never touched for the refused game."""
    runner = GatedNarrator()
    runner.release.set()
    queue = JobQueue(runner)
    gate, admitted = _recording_gate(queue, limit=1)
    app = create_app(queue, _CONFIG, lambda _: None, _no_search, gate=gate)

    async def drive() -> None:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            first = await client.post(
                "/analyses", json={"app_id": 440, "requested_name": "Team Fortress 2"}
            )
            assert first.status_code == 202
            await _until(lambda: queue.live(440) is None, "the first job to finish")

            refused = await client.post(
                "/analyses", json={"app_id": 570, "requested_name": "Dota 2"}
            )
            assert refused.status_code == 429
            assert refused.json()["detail"] == DAY_USED_MESSAGE
            assert queue.live(570) is None, "a refused game must never reach the queue"
            assert len(admitted) == 1

    asyncio.run(asyncio.wait_for(drive(), timeout=10.0))
    queue.close()


def test_gate_settled_spend_backstop_closes_the_day() -> None:
    """Settled spend at the backstop refuses even a first admission — the
    runaway-day guard is independent of the count."""
    runner = GatedNarrator()
    runner.release.set()
    queue = JobQueue(runner)
    gate, admitted = _recording_gate(queue, settled=1.0)
    app = create_app(queue, _CONFIG, lambda _: None, _no_search, gate=gate)

    async def drive() -> None:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            refused = await client.post(
                "/analyses", json={"app_id": 440, "requested_name": "Team Fortress 2"}
            )
            assert refused.status_code == 429
            assert refused.json()["detail"] == DAY_USED_MESSAGE
            assert admitted == []

    asyncio.run(asyncio.wait_for(drive(), timeout=10.0))
    queue.close()


def test_unlock_mints_the_cookie_and_exempts_from_every_abuse_guard() -> None:
    """The unlock round trip: a wrong token 403s; the right one redirects home
    and sets the cookie; the cookie then passes a day with zero allowance —
    and the operator's jobs never touch the public admission journal."""
    runner = GatedNarrator()
    runner.release.set()
    queue = JobQueue(runner)
    gate, admitted = _recording_gate(queue, limit=0, admin_token="sesame")
    app = create_app(queue, _CONFIG, lambda _: None, _no_search, gate=gate)

    async def drive() -> None:
        transport = ASGITransport(app=app)
        # https base URL: the unlock cookie is Secure, and the client's jar
        # (rightly) refuses to send a Secure cookie back over plain http.
        async with AsyncClient(transport=transport, base_url="https://test") as client:
            locked = await client.post(
                "/analyses", json={"app_id": 440, "requested_name": "Team Fortress 2"}
            )
            assert locked.status_code == 429, "a zero-allowance day refuses the public"

            wrong = await client.get("/unlock/open-sesame")
            assert wrong.status_code == 403

            unlock = await client.get("/unlock/sesame")
            assert unlock.status_code == 303
            assert unlock.headers["location"] == "/"
            assert client.cookies.get(UNLOCK_COOKIE) == "sesame"

            exempt = await client.post(
                "/analyses", json={"app_id": 440, "requested_name": "Team Fortress 2"}
            )
            assert exempt.status_code == 202
            assert admitted == [], "exempt admissions stay off the public journal"

    asyncio.run(asyncio.wait_for(drive(), timeout=10.0))
    queue.close()


def test_an_overlong_requested_name_is_refused_before_anything_runs() -> None:
    """The body-side half of the request-size guard (Caddy's ``max_size`` is
    the outer wall): a name past the search box's own 200-char cap 422s at
    validation — the gate never consults, the queue never sees it."""
    runner = GatedNarrator()
    runner.release.set()
    queue = JobQueue(runner)
    gate, admitted = _recording_gate(queue)
    app = create_app(queue, _CONFIG, lambda _: None, _no_search, gate=gate)

    async def drive() -> None:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            refused = await client.post(
                "/analyses", json={"app_id": 440, "requested_name": "x" * 201}
            )
            assert refused.status_code == 422
            assert admitted == [], "a rejected body must not consume the allowance"
            assert queue.live(440) is None, "a rejected body must never queue"

            at_the_cap = await client.post(
                "/analyses", json={"app_id": 440, "requested_name": "x" * 200}
            )
            assert at_the_cap.status_code == 202

    asyncio.run(asyncio.wait_for(drive(), timeout=10.0))
    queue.close()


def test_search_flood_is_refused_per_ip_and_the_unlock_cookie_exempts() -> None:
    """The politeness-budget guard on the wire: past the cap a visitor's
    searches 429 with the honest message and never reach the Steam seam;
    a different forwarded IP keeps its own allowance; the operator's unlock
    cookie searches uncapped."""
    runner = GatedNarrator()
    runner.release.set()
    queue = JobQueue(runner)
    gate, _admitted = _recording_gate(queue, admin_token="sesame")
    calls: list[str] = []

    def search_games(term: str) -> tuple[GameSearchHit, ...]:
        calls.append(term)
        return ()

    app = create_app(
        queue, _CONFIG, lambda _: None, search_games,
        gate=gate, search_limiter=SearchLimiter(2),
    )

    async def drive() -> None:
        transport = ASGITransport(app=app)
        # https base URL: the unlock leg mints a Secure cookie, which the
        # client's jar (rightly) refuses to send back over plain http.
        async with AsyncClient(transport=transport, base_url="https://test") as client:
            for _ in range(2):
                assert (await client.get("/search", params={"q": "team"})).status_code == 200
            refused = await client.get("/search", params={"q": "team"})
            assert refused.status_code == 429
            assert refused.json()["detail"] == SEARCH_LIMIT_MESSAGE
            assert len(calls) == 2, "a refused search must not reach Steam"

            other_visitor = await client.get(
                "/search", params={"q": "team"},
                headers={"X-Forwarded-For": "203.0.113.9"},
            )
            assert other_visitor.status_code == 200

            await client.get("/unlock/sesame")
            for _ in range(3):
                exempt = await client.get("/search", params={"q": "team"})
                assert exempt.status_code == 200

    asyncio.run(asyncio.wait_for(drive(), timeout=10.0))
    queue.close()


def test_search_answers_typed_hits_and_translates_steam_trouble() -> None:
    """GET /search serializes the seam's hits, each saying what its click
    does: a hit with a published report carries the report's canonical
    address (open, no request), an unanalyzed one carries none (analyze); a
    Steam-door failure surfaces as 502 (the upstream broke, not the request);
    a blank query is the request being wrong — 422 before the seam is ever
    called."""
    runner = GatedNarrator()
    runner.release.set()
    queue = JobQueue(runner)
    calls: list[str] = []

    def search_games(term: str) -> tuple[GameSearchHit, ...]:
        calls.append(term)
        if term == "down":
            raise SteamUnavailableError("storefront 503 outlived the retry budget")
        return (
            GameSearchHit(app_id=440, name="Team Fortress 2", capsule_url="https://c/t.jpg"),
            GameSearchHit(app_id=570, name="Dota 2", capsule_url="https://c/d.jpg"),
        )

    app = create_app(
        queue, _CONFIG, lambda _: None, search_games,
        published_names=lambda: {440: "Team Fortress 2"},
    )

    async def drive() -> None:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            found = await client.get("/search", params={"q": "team fortress"})
            assert found.status_code == 200
            assert found.json() == [
                {"app_id": 440, "name": "Team Fortress 2", "capsule_url": "https://c/t.jpg",
                 "report_url": "/reports/440/team-fortress-2"},
                {"app_id": 570, "name": "Dota 2", "capsule_url": "https://c/d.jpg",
                 "report_url": None},
            ]

            down = await client.get("/search", params={"q": "down"})
            assert down.status_code == 502
            assert "storefront search unavailable" in down.json()["detail"]

            blank = await client.get("/search", params={"q": ""})
            assert blank.status_code == 422
            assert calls == ["team fortress", "down"], "a rejected query must not reach Steam"
            assert queue.live(440) is None, "search must never mint a job"

    asyncio.run(asyncio.wait_for(drive(), timeout=10.0))
    queue.close()


def test_healthz_answers_ok_then_names_the_dead_worker() -> None:
    """200 with both checks ok while the worker lives; after the queue closes
    the worker is genuinely gone, and the answer flips to a 503 naming it —
    the pinger alerts on the status code, the operator reads the culprit."""
    runner = GatedNarrator()
    runner.release.set()
    queue = JobQueue(runner)
    app = create_app(queue, _CONFIG, lambda _: None, _no_search, database_ok=lambda: True)

    async def drive() -> None:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            alive = await client.get("/healthz")
            assert alive.status_code == 200
            assert alive.json() == {"status": "ok", "worker": "ok", "database": "ok"}

            queue.close()
            dead = await client.get("/healthz")
            assert dead.status_code == 503
            assert dead.json()["worker"] == "dead"

    asyncio.run(asyncio.wait_for(drive(), timeout=10.0))


def test_healthz_names_a_failing_database_and_says_unchecked_when_unwired() -> None:
    """A failing store check 503s with the culprit named; an app composed
    without one (tests, private dev) says "unchecked" honestly rather than
    reporting a health it never verified."""
    runner = GatedNarrator()
    runner.release.set()
    queue = JobQueue(runner)
    broken = create_app(queue, _CONFIG, lambda _: None, _no_search, database_ok=lambda: False)
    unwired = create_app(queue, _CONFIG, lambda _: None, _no_search)

    async def drive() -> None:
        async with AsyncClient(
            transport=ASGITransport(app=broken), base_url="http://test"
        ) as client:
            answer = await client.get("/healthz")
            assert answer.status_code == 503
            assert answer.json() == {"status": "failing", "worker": "ok", "database": "failing"}
        async with AsyncClient(
            transport=ASGITransport(app=unwired), base_url="http://test"
        ) as client:
            answer = await client.get("/healthz")
            assert answer.status_code == 200
            assert answer.json()["database"] == "unchecked"

    asyncio.run(asyncio.wait_for(drive(), timeout=10.0))
    queue.close()


def test_the_framework_auto_docs_stay_declined() -> None:
    """/docs, /redoc, and /openapi.json answer 404: FastAPI mounts them by
    default, and the default shipped unexamined for a month — an open
    interactive console to the money-spending submit route, rendered off a
    third-party CDN. The decline is deliberate (the CSP pass, 2026-08-12);
    this pins it against any future re-composition quietly restoring it."""
    runner = GatedNarrator()
    runner.release.set()
    queue = JobQueue(runner)
    app = create_app(queue, _CONFIG, lambda _: None, _no_search)

    async def drive() -> None:
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            for path in ("/docs", "/redoc", "/openapi.json"):
                assert (await client.get(path)).status_code == 404

    asyncio.run(asyncio.wait_for(drive(), timeout=10.0))
    queue.close()
