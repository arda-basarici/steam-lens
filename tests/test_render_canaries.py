"""The render-side canary wall — every review-sourced string renders inert, in CI.

The model-side canary runs (``evals.canary_run``) buy fresh output and score
beacons; this half is deterministic and free: the same versioned attack set
rendered through the REAL templates, planted in every surface where
review-derived text lands — the game name, the narrative prose, the verbatim
evidence quotes, the candidate aspect names — asserting markup arrives
entity-escaped and no element or handler ever forms. The two drift guards are
the wall's enforcement arm: templates must never mark content safe, and the
vanilla-JS layer must never build DOM from strings — those are exactly the
two moves that would silently reopen what these tests pin shut.

The no-element assertions lean on a structural fact: the report template
itself contains no ``<script>`` or ``<img>`` today, so ANY occurrence in a
rendered hostile page is an injection. If capsule art or an inline script
legitimately joins the page later, tighten the assertion to count expected
occurrences rather than deleting it.
"""

from __future__ import annotations

import asyncio
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from markupsafe import escape

from steamlens.contracts import (
    AspectAggregate,
    AspectSlot,
    ClassifierVersions,
    ComposedNarrative,
    EvidenceQuote,
    GroundedSpan,
    HistogramSnapshot,
    NarrativeOutcome,
    Provenance,
    Report,
    RollupUnit,
    Sentiment,
    SentimentCounts,
    SpanKind,
)
from steamlens.evals.canaries import Canary, load_canaries
from steamlens.serve.web import ReportPageData, attach_web

_WEB_DIR = Path(__file__).resolve().parent.parent / "src" / "steamlens" / "serve" / "web"
_STAMP = datetime(2026, 8, 1, tzinfo=UTC)
_VERSIONS = ClassifierVersions(
    model_version="deepseek-v4-flash", prompt_version="p3", ontology_version="v2"
)

CANARIES = load_canaries()


def _hostile_page(text: str, *, review_id: str = "r1") -> ReportPageData:
    """A report bundle with ``text`` planted in every review-derived surface."""
    report = Report(
        run=Provenance(
            run_id="canary-render", code_version="abc1234", created_at=_STAMP,
            config_hash="cfg",
        ),
        app_id=440,
        game_name=f"Hostile {text}",
        created_at=_STAMP,
        versions=_VERSIONS,
        sample_size=100,
        take_all=True,
        windows=(),
        language_mix=(),
        narrative=ComposedNarrative(
            prose=f"Reviewers say: {text}", spans=(), outcome=NarrativeOutcome.COMPOSED
        ),
        histogram=HistogramSnapshot(
            app_id=440, rollup_unit=RollupUnit.MONTH, rollups=(),
            recent_daily=(), past_events=(), fetched_at=_STAMP,
        ),
        episodes=(),
        marked_window_counts=(),
    )
    def aggregate(aspect: str, slot: AspectSlot, n: int) -> AspectAggregate:
        return AspectAggregate(
            app_id=440, aspect=aspect, slot=slot, reviews_with_aspect=n,
            counts=SentimentCounts(positive=n, negative=0, mixed=0, neutral=0),
            sample_size=100, versions=_VERSIONS, manifest_id="canary-render",
        )
    return ReportPageData(
        report=report,
        aggregates=(
            aggregate("combat", AspectSlot.PINNED, 30),
            aggregate(text, AspectSlot.CANDIDATE, 5),
        ),
        evidence=(
            EvidenceQuote(
                review_id=review_id, aspect="combat",
                sentiment=Sentiment.POSITIVE, text=text,
            ),
        ),
    )


def _render(page: ReportPageData) -> str:
    app = FastAPI()
    attach_web(app, lambda _: page, lambda _: False)

    async def drive() -> str:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            return (await client.get("/reports/440")).text

    return asyncio.run(asyncio.wait_for(drive(), timeout=10.0))


@pytest.mark.parametrize("canary", CANARIES, ids=lambda c: c.canary_id)
def test_canary_text_renders_inert_on_every_surface(canary: Canary) -> None:
    """The whole attack set through the real templates: whatever the text
    tried, no element or handler forms — markup arrives entity-escaped (the
    quote surface shows the exact escaped text) and the page stays script- and
    image-free, which on this template means injection-free."""
    html = _render(_hostile_page(canary.text))
    lowered = html.casefold()
    assert "<script" not in lowered
    assert "<img" not in lowered
    assert "javascript:" not in lowered
    if any(ch in canary.text for ch in "<>&\""):
        assert canary.text not in html, "hostile text must not land verbatim"
    assert str(escape(canary.text)) in html, "the escaped text must still display"


def test_hostile_review_id_cannot_break_out_of_an_attribute() -> None:
    """Review ids render inside a ``title`` attribute on narrative spans; a
    quote-and-handler payload in the id must not mint a new attribute."""
    payload = '" onmouseover="alert(1)'
    prose = "Reviewers praise combat."
    page = _hostile_page("plain text", review_id=payload)
    hostile_span = ComposedNarrative(
        prose=prose,
        spans=(GroundedSpan(start=17, end=23, text="combat", kind=SpanKind.QUOTE,
                            review_id=payload),),
        outcome=NarrativeOutcome.COMPOSED,
    )
    page = ReportPageData(
        report=replace(page.report, narrative=hostile_span),
        aggregates=page.aggregates,
        evidence=page.evidence,
    )
    html = _render(page)
    assert 'onmouseover="alert' not in html
    assert "&#34;" in html or "&quot;" in html


def test_templates_never_disable_autoescaping() -> None:
    """The drift guard on the wall itself: no template marks content safe or
    toggles autoescape — the two Jinja moves that would reopen every claim the
    canary renders pin."""
    violations: list[str] = []
    for template in (_WEB_DIR / "templates").glob("*.html"):
        source = template.read_text(encoding="utf-8")
        for needle in ("| safe", "|safe", "{% autoescape"):
            if needle in source:
                violations.append(f"{template.name}: {needle}")
    assert not violations, "autoescaping bypassed:\n" + "\n".join(violations)


def test_js_layer_never_builds_dom_from_strings() -> None:
    """The client-side half of the wall: narration and search results are
    hostile input rendered by JS, so the static layer must never reach for
    string-to-DOM APIs — textContent is the only text sink."""
    violations: list[str] = []
    for script in (_WEB_DIR / "static").glob("*.js"):
        source = script.read_text(encoding="utf-8")
        for needle in ("innerHTML", "outerHTML", "insertAdjacentHTML", "document.write"):
            if needle in source:
                violations.append(f"{script.name}: {needle}")
    assert not violations, "string-to-DOM API in the JS layer:\n" + "\n".join(violations)
