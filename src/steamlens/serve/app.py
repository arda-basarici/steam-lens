"""The HTTP shell — request intake and the SSE narration endpoint over the queue.

FastAPI's whole footprint is this module: an app *factory* over injected,
already-composed dependencies (the queue, the serving dials), so the
composition root stays outside and a test injects a scripted pipeline exactly
as the queue tests do. Framework types stop here — nothing below the HTTP
surface imports FastAPI, and the routes hold to one abstraction level:
validate at the boundary, delegate to the queue, serialize a typed receipt.

Intake and streaming are deliberately separate surfaces with separate verbs.
``POST /analyses`` is the only creator — submit-or-attach is the queue's own
semantics, which makes the POST idempotent per app id while a job is live.
``GET /analyses/{app_id}/events`` is side-effect-free: it attaches to a live
job's stream through the queue's read-only lookup and 404s otherwise — a GET
must never mint a minutes-long, money-spending job, and a *finished* job's
absence here is by design (its report is the persistence layer's to serve).

The scaling seam, stated once: routes talk only to the queue's
``submit``/``live``/``position`` surface and the stream generator's snapshot
contract, so scaling past one process is swapping what the factory is handed —
an external job queue, an external event log — with the routes untouched.
"""

from __future__ import annotations

from dataclasses import dataclass

from fastapi import FastAPI, HTTPException
from fastapi.responses import StreamingResponse

from steamlens.serve.config import ServeConfig
from steamlens.serve.jobs import JobQueue, JobState
from steamlens.serve.sse import stream_job


@dataclass(frozen=True, slots=True)
class AnalysisRequest:
    """What a viewer asks for: the app and the name they typed.

    The name rides along for the runner's identity guard — a mismatch against
    the store's name is narrated, never silently corrected.
    """

    app_id: int
    requested_name: str


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


def create_app(queue: JobQueue, config: ServeConfig) -> FastAPI:
    """The served app over an already-composed queue — the one HTTP seam.

    The caller owns the queue's lifecycle (construction and drain-close live
    with the composition root, not the web framework); the factory only wires
    routes over it. ``config`` carries the SSE dials so a test can tighten the
    poll tick without touching production defaults.
    """
    app = FastAPI(title="steam-lens")

    # The route functions are "unused" to a type checker — the decorators
    # register them with the app; the suppressions state that, nothing more.
    @app.post("/analyses", status_code=202)
    def submit_analysis(request: AnalysisRequest) -> AnalysisAccepted:  # pyright: ignore[reportUnusedFunction]
        """Queue a cold analysis — or attach to the live one for this app."""
        job = queue.submit(request.app_id, request.requested_name)
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

    return app
