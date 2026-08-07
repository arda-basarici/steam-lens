"""The HTML pages: search and report, server-rendered off the stored contracts.

Two pages are the whole product surface (the design's frontend ruling — no
SPA, no bundler): a search page and the report page in the ruled top-to-bottom
order. This skeleton chunk renders identity, provenance, and the narrative;
the aspect bars, timeline, and full trust panel land in their own chunks
against real rendered data. Presentation adaptation happens here in view-model
helpers — never by teaching the stored ``Report`` contract display shapes,
which is the discipline that keeps a future frontend swap rendering-only.

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

from steamlens.contracts import Report

_TEMPLATES_DIR: Final = Path(__file__).parent / "templates"
_STATIC_DIR: Final = Path(__file__).parent / "static"


def provenance_line(report: Report) -> str:
    """The header one-liner: the date worn openly, and what the numbers stand on.

    A cached report serves as-is with its analysis date displayed — the
    staleness ruling made visible. The sample clause states the two-track
    denominators honestly: a take-all is a complete count, a sampled run names
    its n.
    """
    date = report.created_at.date().isoformat()
    if report.take_all:
        return f"analyzed {date} · complete count of {report.sample_size:,} English reviews"
    return f"analyzed {date} · sample of {report.sample_size:,} English reviews"


def attach_web(app: FastAPI, latest_report: Callable[[int], Report | None]) -> None:
    """Mount the pages and static assets onto ``app`` — the composition root's call.

    The attach direction keeps the rendering boundary: the JSON surface never
    imports this module; the root composes both over the same injected
    ``latest_report`` read, so the page and the POST bypass can never disagree
    about which report is current.
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
        report = latest_report(app_id)
        if report is None:
            return templates.TemplateResponse(
                request, "report_missing.html", {"app_id": app_id}, status_code=404
            )
        return templates.TemplateResponse(
            request,
            "report.html",
            {"report": report, "provenance": provenance_line(report)},
        )

    app.include_router(router)
    app.mount("/static", StaticFiles(directory=_STATIC_DIR), name="static")
