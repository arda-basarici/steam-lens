"""The HTTP shell — request intake and the SSE narration endpoint over the queue.

FastAPI's whole footprint is this module: an app *factory* over injected,
already-composed dependencies (the queue, the serving dials), so the
composition root stays outside and a test injects a scripted pipeline exactly
as the queue tests do. Framework types stop here — nothing below the HTTP
surface imports FastAPI, and the routes hold to one abstraction level:
validate at the boundary, delegate to the queue, serialize a typed receipt.

Intake and streaming are deliberately separate surfaces with separate verbs.
``POST /analyses`` is the only creator, and it consults the persistence layer
before creating: a game with a published report answers 200 with the
cached-game receipt — no job, no spend, the analysis date worn openly — which
also means the POST alone never refreshes a game (the refresh trigger is
deferred until it is decided who may pull it). Only an unanalyzed game queues;
submit-or-attach is the queue's own semantics, which makes the POST idempotent
per app id while a job is live. ``GET /analyses/{app_id}/events`` is
side-effect-free: it attaches to a live job's stream through the queue's
read-only lookup and 404s otherwise — a GET must never mint a minutes-long,
money-spending job, and a *finished* job's absence here is by design (its
report is the persistence layer's to serve).

The scaling seam, stated once: routes talk only to the queue's
``submit``/``live``/``position`` surface and the stream generator's snapshot
contract, so scaling past one process is swapping what the factory is handed —
an external job queue, an external event log — with the routes untouched.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Annotated

from fastapi import FastAPI, HTTPException, Query, Request, Response
from fastapi.responses import RedirectResponse, StreamingResponse
from pydantic import Field

from steamlens.contracts import GameSearchHit, Report
from steamlens.serve.config import ServeConfig
from steamlens.serve.gate import UNLOCK_COOKIE, SearchLimiter, SubmitGate, client_ip
from steamlens.serve.jobs import JobQueue, JobState
from steamlens.serve.sse import stream_job
from steamlens.steam_client import SteamClientError


@dataclass(frozen=True, slots=True)
class AnalysisRequest:
    """What a viewer asks for: the app and the name they typed.

    The name rides along for the runner's identity guard — a mismatch against
    the store's name is narrated, never silently corrected. Its cap matches
    ``/search``'s query cap, so no name the search box accepts can fail here;
    an over-long body 422s cleanly inside the proxy's request-size envelope
    (the audit's body-limit finding — Caddy's ``max_size`` is the outer wall).
    """

    app_id: int
    requested_name: Annotated[str, Field(max_length=200)]


@dataclass(frozen=True, slots=True)
class AnalysisAccepted:
    """The intake receipt: where the job stands and where its story streams.

    ``position`` counts jobs ahead (0 = running) — the honest wait message the
    design promised a queued viewer; ``events_url`` is the SSE stream to attach
    to, handed out so the client never constructs paths.
    """

    app_id: int
    requested_name: str
    state: JobState
    position: int
    events_url: str


@dataclass(frozen=True, slots=True)
class HealthReport:
    """What ``/healthz`` answers: the two real things, checked cheaply.

    ``status`` is the pinger's one-word read; ``worker`` and ``database`` name
    which check failed when it isn't ``"ok"`` — a 503 with the culprit named
    beats a bare status code when the operator reads the pinger's alert.
    ``database`` is ``"unchecked"`` when no check was wired (tests; production
    always wires one).
    """

    status: str
    worker: str
    database: str


@dataclass(frozen=True, slots=True)
class ReportReady:
    """The cached-game receipt: a published report already answers this game.

    No job, no stream — the client reads the report instead of attaching to
    SSE. ``analyzed_at`` is the staleness ruling made visible: the report
    serves as-is with its date worn openly, and the receipt carries what the
    client needs to say so. ``run_id`` names the exact publication (multiple
    reports per game are the refresh-ready shape; this one is the newest).
    """

    app_id: int
    game_name: str
    analyzed_at: datetime
    sample_size: int
    run_id: str


def create_app(
    queue: JobQueue,
    config: ServeConfig,
    latest_report: Callable[[int], Report | None],
    search_games: Callable[[str], tuple[GameSearchHit, ...]],
    *,
    gate: SubmitGate | None = None,
    search_limiter: SearchLimiter | None = None,
    database_ok: Callable[[], bool] | None = None,
    on_shutdown: Sequence[Callable[[], None]] = (),
) -> FastAPI:
    """The served app over an already-composed queue — the one HTTP seam.

    The caller owns the queue's lifecycle (construction and drain-close live
    with the composition root, not the web framework); the factory only wires
    routes over it — ``on_shutdown`` is the hook the root hangs the queue's
    drain-close on, passed through rather than owned here. ``latest_report``
    is the persistence layer's instant read
    (``ReportLog.latest_report`` behind whatever store lifetime the
    composition root chooses) — injected as a callable so this module keeps
    zero knowledge of SQLite; ``search_games`` is the Steam door's storefront
    search behind the same discipline (the route knows nothing of pacing or
    the transport — a failure there surfaces as an honest 502). ``config``
    carries the SSE dials so a test can tighten the poll tick without
    touching production defaults. ``gate`` is the submit gate (the spend
    breaker) — ``None`` composes an ungated app (tests, private dev);
    production always wires one, and with it the ``/unlock/{token}`` route
    that mints the operator's exemption cookie. ``search_limiter`` guards
    ``/search`` the same way (the politeness-budget guard) — ``None``
    composes an unlimited search; production always wires one. ``database_ok`` is
    ``/healthz``'s injected store check (does the file open?) — ``None``
    composes an app whose health answer says so honestly; production always
    wires one, same language as the gate.
    """
    app = FastAPI(title="steam-lens", on_shutdown=list(on_shutdown))

    @app.get("/healthz")
    def healthz(response: Response) -> HealthReport:  # pyright: ignore[reportUnusedFunction]
        """The off-box pinger's read: 200 when the real things hold, 503 naming the culprit.

        Two checks, both cheap (DESIGN: monitoring lives off the box; the
        endpoint only answers): the job worker thread is alive — dead means
        every submitted job would queue forever — and the database opens.
        Deliberately no Steam or provider probe: those fail per-job with
        narrated errors, and a health check that calls third parties turns
        their hiccups into our downtime.
        """
        worker = "ok" if queue.worker_alive() else "dead"
        database = (
            "unchecked" if database_ok is None
            else ("ok" if database_ok() else "failing")
        )
        healthy = worker == "ok" and database != "failing"
        if not healthy:
            response.status_code = 503
        return HealthReport(
            status="ok" if healthy else "failing", worker=worker, database=database
        )

    @app.get("/search")
    def search(  # pyright: ignore[reportUnusedFunction]
        q: Annotated[str, Query(min_length=1, max_length=200)],
        http_request: Request,
    ) -> tuple[GameSearchHit, ...]:
        """Typed hits for a game-name query — resolution, never job creation.

        Read-only and spend-free by construction: the only job creator stays
        ``POST /analyses``. Every query does spend the box's Steam politeness
        budget, so the limiter refuses a scripted per-IP flood (429, honest
        message) before the seam is called; the unlock cookie exempts, the
        same as the submit guards. The storefront failing is the one error
        translated here — 502, because the upstream broke, not the request.
        """
        if search_limiter is not None:
            peer = http_request.client.host if http_request.client else ""
            ip = client_ip(http_request.headers.get("x-forwarded-for"), peer)
            exempt = gate is not None and gate.is_exempt(
                http_request.cookies.get(UNLOCK_COOKIE)
            )
            if not exempt:
                message = search_limiter.refusal(ip)
                if message is not None:
                    raise HTTPException(status_code=429, detail=message)
        try:
            return search_games(q)
        except SteamClientError as exc:
            raise HTTPException(
                status_code=502, detail=f"storefront search unavailable: {exc}"
            ) from exc

    # The route functions are "unused" to a type checker — the decorators
    # register them with the app; the suppressions state that, nothing more.
    @app.post("/analyses", status_code=202)
    def submit_analysis(  # pyright: ignore[reportUnusedFunction]
        request: AnalysisRequest, http_request: Request, response: Response
    ) -> ReportReady | AnalysisAccepted:
        """Answer from the published report, or queue/attach a cold analysis.

        The gate runs only for a genuinely *fresh* job — cached answers and
        attaches to a live job spend nothing, so they pass ungated (the
        design's check order). A refusal is a 429 whose detail is the honest
        visitor-facing message the search box displays verbatim.
        """
        cached = latest_report(request.app_id)
        if cached is not None:
            response.status_code = 200
            return ReportReady(
                app_id=cached.app_id,
                game_name=cached.game_name,
                analyzed_at=cached.created_at,
                sample_size=cached.sample_size,
                run_id=cached.run.run_id,
            )
        ip: str | None = None
        if gate is not None and queue.live(request.app_id) is None:
            peer = http_request.client.host if http_request.client else ""
            ip = client_ip(http_request.headers.get("x-forwarded-for"), peer)
            if not gate.is_exempt(http_request.cookies.get(UNLOCK_COOKIE)):
                message = gate.refusal(ip)
                if message is not None:
                    raise HTTPException(status_code=429, detail=message)
                # Journaled here rather than after submit: if a same-app race
                # turns this submit into an attach, the one extra row errs on
                # the conservative side of the day's allowance.
                gate.admit(ip, request.app_id)
        job = queue.submit(request.app_id, request.requested_name, client_ip=ip)
        return AnalysisAccepted(
            app_id=job.app_id,
            requested_name=job.requested_name,
            state=job.state,
            position=queue.position(job),
            events_url=f"/analyses/{job.app_id}/events",
        )

    @app.get("/analyses/{app_id}/events")
    def analysis_events(app_id: int) -> StreamingResponse:  # pyright: ignore[reportUnusedFunction]
        """The live job's narration as SSE: full-history replay, then follow."""
        job = queue.live(app_id)
        if job is None:
            raise HTTPException(
                status_code=404,
                detail=f"no live analysis for app {app_id} — submit one via POST /analyses",
            )
        return StreamingResponse(
            stream_job(job, tick_s=config.sse_tick_s, heartbeat_s=config.sse_heartbeat_s),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache"},
        )

    if gate is not None:
        wired_gate = gate

        @app.get("/unlock/{token}")
        def unlock(token: str) -> RedirectResponse:  # pyright: ignore[reportUnusedFunction]
            """Mint the operator's exemption cookie and land on the front door.

            One visit per device; the cookie then rides every submit. The
            token in a URL is an accepted trade (it can land in proxy logs)
            for working from any device with zero client setup — rotating
            ``STEAMLENS_ADMIN_TOKEN`` in the box env revokes every cookie at
            once, because the cookie's *value* is what gets re-compared.
            """
            if not wired_gate.unlock_ok(token):
                raise HTTPException(status_code=403, detail="invalid unlock token")
            landing = RedirectResponse("/", status_code=303)
            landing.set_cookie(
                UNLOCK_COOKIE,
                token,
                max_age=365 * 24 * 3600,
                httponly=True,
                samesite="lax",
                # HTTPS-only since the domain cutover (2026-08-10): the flag
                # keeps the operator token off any plaintext hop. Dev on
                # http://localhost is unaffected — browsers exempt localhost.
                secure=True,
            )
            return landing

    return app
