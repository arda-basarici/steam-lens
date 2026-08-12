"""The HTML pages: search and report, server-rendered off the stored contracts.

Two pages are the whole product surface (the design's frontend ruling — no
SPA, no bundler): a search page and the report page in the ruled top-to-bottom
order — header and provenance, the narrative with its certificate rendered
visibly, aspect share bars with calibrated whiskers, the candidate stratum,
the timeline with its marker layers, and the trust panel. The routes stay one
abstraction level up: load the bundle through the injected seam, shape it
with ``view``'s pure builders, hand the view to the template.

Review-derived text is hostile input by assumption (the canary set is the
instrument), so templates rely on Jinja's autoescaping and never mark content
safe; the render-side canary tests pin that wall in CI.
"""

from __future__ import annotations

import hashlib
from collections.abc import Callable
from pathlib import Path
from typing import Final, cast

from fastapi import APIRouter, FastAPI, Request, Response
from fastapi.exception_handlers import http_exception_handler
from fastapi.responses import PlainTextResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.exceptions import HTTPException as StarletteHTTPException

from steamlens.serve.web.csp import ContentSecurityPolicy, fresh_policy
from steamlens.serve.web.ops_view import OpsData, build_ops_view
from steamlens.serve.web.view import ReportPageData, build_report_view

_TEMPLATES_DIR: Final = Path(__file__).parent / "templates"
_STATIC_DIR: Final = Path(__file__).parent / "static"


def _static_version() -> str:
    """A short stamp over the static files' bytes — the cache-busting token.

    Templates append it as ``?v=…`` on static links so a deploy that changes
    any asset changes every URL, and a returning browser can never keep
    running last deploy's script against this deploy's pages (the exact
    stale-JS failure the first live-run watch hit, 2026-08-08). Content
    beats mtime here: rebuilt-but-identical files keep their cache.
    """
    digest = hashlib.md5()
    for path in sorted(_STATIC_DIR.rglob("*")):
        if path.is_file():
            digest.update(path.relative_to(_STATIC_DIR).as_posix().encode())
            digest.update(path.read_bytes())
    return digest.hexdigest()[:10]


def attach_web(
    app: FastAPI,
    load_report_page: Callable[[int], ReportPageData | None],
    job_live: Callable[[int], bool],
    load_ops_data: Callable[[], OpsData] | None = None,
) -> None:
    """Mount the pages and static assets onto ``app`` — the composition root's call.

    The attach direction keeps the rendering boundary: the JSON surface never
    imports this module; the root composes both. ``load_report_page`` is the
    persistence layer's render bundle behind whatever store lifetime the root
    chooses — the report row plus its aggregate snapshot and evidence pool —
    and ``job_live`` is the queue's read-only is-there-a-live-job answer,
    injected as a bare callable so the renderer never learns the queue's
    shape (during a cold job the page IS the narration, and this one bit is
    all the server-side branch needs; everything else arrives over SSE).
    ``load_ops_data`` is the ops page's aggregate bundle behind the same
    discipline — ``None`` composes an app without the page (tests that only
    render reports); production always wires it.

    Attaching also registers the app-wide 404 and 500 pages — here rather
    than on the JSON surface because a styled error page is rendering, and
    the boundary ruling keeps every rendered byte inside ``serve.web`` — and
    the Content-Security-Policy middleware (``csp``), which stamps every HTML
    response and only HTML responses: the policy is a property of the pages,
    so it attaches with them, not with the proxy's static header block.
    """
    app.add_middleware(ContentSecurityPolicy)
    templates = Jinja2Templates(directory=_TEMPLATES_DIR)
    # The stub types env.globals to jinja's own builtins; it is a plain dict.
    cast(dict[str, object], templates.env.globals)["static_v"] = _static_version()
    router = APIRouter()

    # The route functions are "unused" to a type checker — the decorators
    # register them with the router; the suppressions state that, nothing more.
    @router.get("/", response_class=Response)
    def search_page(request: Request) -> Response:  # pyright: ignore[reportUnusedFunction]
        """The search page — the product's front door."""
        return templates.TemplateResponse(request, "search.html")

    @router.get("/reports/{app_id}", response_class=Response)
    def report_page(request: Request, app_id: int) -> Response:  # pyright: ignore[reportUnusedFunction]
        """The report if published, the live narration if a job runs, else an honest 404.

        Publication wins over a live job by order here — today the POST never
        queues a job for an already-reported game, so the branch order is
        belt-and-suspenders, not policy.
        """
        page = load_report_page(app_id)
        if page is not None:
            return templates.TemplateResponse(
                request, "report.html", {"view": build_report_view(page)}
            )
        if job_live(app_id):
            return templates.TemplateResponse(
                request, "report_live.html", {"app_id": app_id}
            )
        return templates.TemplateResponse(
            request, "report_missing.html", {"app_id": app_id}, status_code=404
        )

    if load_ops_data is not None:
        wired_ops = load_ops_data

        @router.get("/ops", response_class=Response)
        def ops_page(request: Request) -> Response:  # pyright: ignore[reportUnusedFunction]
            """The public read-only ops surface — aggregates off the app's own journals."""
            return templates.TemplateResponse(
                request, "ops.html", {"view": build_ops_view(wired_ops())}
            )

    @app.exception_handler(404)
    async def not_found(  # pyright: ignore[reportUnusedFunction]
        request: Request, exc: StarletteHTTPException
    ) -> Response:
        """The 404 wearing the site's face — for browser navigations only.

        Content negotiation is the load-bearing part: the JSON surface's 404s
        (a dead SSE attach, an API typo) keep FastAPI's exact default answer
        because clients read ``detail`` programmatically, while a browser
        (``Accept: text/html``) gets a page pointing home instead of bare
        JSON. The echoed path rides Jinja's autoescaping like all hostile
        input.
        """
        if "text/html" in request.headers.get("accept", ""):
            return templates.TemplateResponse(
                request, "not_found.html", {"path": request.url.path},
                status_code=404,
            )
        return await http_exception_handler(request, exc)

    @app.exception_handler(Exception)
    async def server_error(  # pyright: ignore[reportUnusedFunction]
        request: Request, exc: Exception
    ) -> Response:
        """The unhandled-error page — the 404's sibling, same negotiation.

        Starlette's error middleware sends this response and then re-raises,
        so the traceback still lands in the server journal — the visitor
        loses the stack, never the operator. Non-browser clients keep the
        framework's exact plain-text default; programmatic consumers never
        traded on its body, so there is nothing richer to preserve.

        The CSP is stamped here by hand: the error middleware answering this
        sits outside every user middleware, so the stamper never sees the
        response it sends.
        """
        if "text/html" in request.headers.get("accept", ""):
            response = templates.TemplateResponse(
                request, "server_error.html", status_code=500
            )
            response.headers["Content-Security-Policy"] = fresh_policy()
            return response
        return PlainTextResponse("Internal Server Error", status_code=500)

    app.include_router(router)
    app.mount("/static", StaticFiles(directory=_STATIC_DIR), name="static")
