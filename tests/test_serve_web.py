"""Behavioral claims on the page renderer — the swappable frontend over stored contracts.

Same drive discipline as the HTTP-shell tests: the real app over httpx's
in-process ASGI transport, a report injected through the ``latest_report``
seam. The boundary test is the load-bearing one: the rendering ruling says a
future frontend swap touches ``serve.web`` alone, which stays true only while
the JSON surface never imports the renderer — the import-graph law ranks
whole subpackages and cannot see an edge inside ``serve``, so the wall gets
its own static scan here.
"""

from __future__ import annotations

import ast
import asyncio
from datetime import UTC, datetime
from pathlib import Path

from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient, Response

from steamlens.contracts import (
    ClassifierVersions,
    ComposedNarrative,
    HistogramSnapshot,
    NarrativeOutcome,
    Provenance,
    Report,
    RollupUnit,
)
from steamlens.serve.web import attach_web
from steamlens.serve.web.pages import provenance_line

_SERVE_DIR = Path(__file__).resolve().parent.parent / "src" / "steamlens" / "serve"


def _report(
    *,
    game_name: str = "Team Fortress 2",
    prose: str = "Players praise the gunplay.",
    take_all: bool = False,
) -> Report:
    """A published report with just enough flesh for the skeleton page."""
    stamp = datetime(2026, 8, 1, tzinfo=UTC)
    outcome = NarrativeOutcome.COMPOSED if prose else NarrativeOutcome.WITHHELD
    return Report(
        run=Provenance(
            run_id="serve-test", code_version="abc1234", created_at=stamp,
            config_hash="cfg",
        ),
        app_id=440,
        game_name=game_name,
        created_at=stamp,
        versions=ClassifierVersions(
            model_version="deepseek-v4-flash", prompt_version="p3", ontology_version="v2"
        ),
        sample_size=1_000,
        take_all=take_all,
        windows=(),
        language_mix=(),
        narrative=ComposedNarrative(prose=prose, spans=(), outcome=outcome),
        histogram=HistogramSnapshot(
            app_id=440, rollup_unit=RollupUnit.MONTH, rollups=(),
            recent_daily=(), past_events=(), fetched_at=stamp,
        ),
        episodes=(),
        marked_window_counts=(),
    )


def _get(app: FastAPI, path: str) -> Response:
    async def drive() -> Response:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            return await client.get(path)

    return asyncio.run(asyncio.wait_for(drive(), timeout=10.0))


def _page_app(report: Report | None) -> FastAPI:
    app = FastAPI()
    attach_web(app, lambda _: report)
    return app


def test_report_page_renders_the_stored_row() -> None:
    """The page is the stored report made visible: identity, the provenance
    one-liner with the date worn openly, the narrative prose, and the trust
    panel's run id — all server-rendered from the row, nothing recomputed."""
    response = _get(_page_app(_report()), "/reports/440")
    assert response.status_code == 200
    page = response.text
    assert "Team Fortress 2" in page
    assert "analyzed 2026-08-01" in page
    assert "sample of 1,000 English reviews" in page
    assert "Players praise the gunplay." in page
    assert "serve-test" in page


def test_withheld_narrative_renders_the_disclosure_not_a_hole() -> None:
    """A below-floor compose published honestly, so the page says so — the
    disclosed withholding is content, not an empty section."""
    response = _get(_page_app(_report(prose="")), "/reports/440")
    assert "Narrative withheld" in response.text


def test_unanalyzed_game_gets_an_honest_404_page() -> None:
    """No published report is a 404 with a human answer — the page names the
    app and says what would create a report, instead of a bare JSON error."""
    response = _get(_page_app(None), "/reports/999")
    assert response.status_code == 404
    assert "Not analyzed yet" in response.text
    assert "999" in response.text


def test_search_page_serves_at_the_root() -> None:
    """The front door: GET / is the search page, HTML, spine sentence on it."""
    response = _get(_page_app(None), "/")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/html")
    assert "Type a game name" in response.text


def test_hostile_review_content_renders_inert() -> None:
    """The escaping wall's first brick: model prose and game names are hostile
    by assumption, and autoescaping must neutralize markup in both. The full
    canary sweep through every rendered field is its own chunk; this pins the
    mechanism the moment the renderer is born."""
    hostile = _report(
        game_name="<script>alert('name')</script>",
        prose='<img src=x onerror="alert(1)"> praised the gunplay.',
    )
    page = _get(_page_app(hostile), "/reports/440").text
    assert "<script>" not in page
    assert "<img" not in page
    assert "&lt;script&gt;" in page
    assert "&lt;img" in page


def test_provenance_line_states_the_two_denominators() -> None:
    """Take-all is a complete count, a sampled run names its n — the two-track
    honesty rule surfacing in one line of header text."""
    assert (
        provenance_line(_report(take_all=True))
        == "analyzed 2026-08-01 · complete count of 1,000 English reviews"
    )
    assert (
        provenance_line(_report())
        == "analyzed 2026-08-01 · sample of 1,000 English reviews"
    )


def test_json_surface_never_imports_the_renderer() -> None:
    """The rendering boundary, pinned: only the composition root may import
    ``serve.web`` — the JSON surface staying renderer-blind is what keeps a
    future frontend swap a one-package change."""
    violations: list[str] = []
    for path in _SERVE_DIR.rglob("*.py"):
        relative = path.relative_to(_SERVE_DIR)
        if relative.parts[0] in {"web", "main.py"}:
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module:
                imported = node.module
            elif isinstance(node, ast.Import):
                imported = ",".join(a.name for a in node.names)
            else:
                continue
            if "serve.web" in imported:
                violations.append(f"{relative}: imports {imported}")
    assert not violations, (
        "the JSON surface imports the renderer (the rendering boundary ruling):\n"
        + "\n".join(violations)
    )
