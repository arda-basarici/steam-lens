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

from collections.abc import Callable
from pathlib import Path
from typing import Final

from fastapi import APIRouter, FastAPI, Request, Response
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from steamlens.serve.web.view import ReportPageData, build_report_view

_TEMPLATES_DIR: Final = Path(__file__).parent / "templates"
_STATIC_DIR: Final = Path(__file__).parent / "static"


def attach_web(app: FastAPI, load_report_page: Callable[[int], ReportPageData | None]) -> None:
    """Mount the pages and static assets onto ``app`` — the composition root's call.

    The attach direction keeps the rendering boundary: the JSON surface never
    imports this module; the root composes both. ``load_report_page`` is the
    persistence layer's render bundle behind whatever store lifetime the root
    chooses — the report row plus its aggregate snapshot and evidence pool.
    """
    templates = Jinja2Templates(directory=_TEMPLATES_DIR)
    router = APIRouter()

    # The route functions are "unused" to a type checker — the decorators
    # register them with the router; the suppressions state that, nothing more.
    @router.get("/", response_class=Response)
    def search_page(request: Request) -> Response:  # pyright: ignore[reportUnusedFunction]
        """The search page — the product's front door."""
        return templates.TemplateResponse(request, "search.html")

    @router.get("/reports/{app_id}", response_class=Response)
    def report_page(request: Request, app_id: int) -> Response:  # pyright: ignore[reportUnusedFunction]
        """The newest published report for ``app_id``, or an honest 404 page."""
        page = load_report_page(app_id)
        if page is None:
            return templates.TemplateResponse(
                request, "report_missing.html", {"app_id": app_id}, status_code=404
            )
        return templates.TemplateResponse(
            request, "report.html", {"view": build_report_view(page)}
        )

    app.include_router(router)
    app.mount("/static", StaticFiles(directory=_STATIC_DIR), name="static")
