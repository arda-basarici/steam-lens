"""View models for the report page — stored contracts shaped for the template.

The rendering boundary's adaptation layer: pure builders, loaded contracts in,
display records out. Every displayed number traces to a stored record or a
certified seam — shares and whiskers compute through ``core.allowance``'s
shipped interval (never re-derived here), the narrative renders straight off
its span certificate (no prose re-scanning), and the interval regime
recomputes deterministically from the stored histogram (regenerate from the
layer below; the report row deliberately stores content, not presentation).
Presentation needs adapt HERE — never as new fields on the stored contracts,
which is the discipline that keeps a frontend swap rendering-only.

Two display-only narrowings this module owns (judged at the chunk-3
checkpoint): evidence quotes cap at three per aspect, dominant-polarity
first; candidate aspects mentioned once fold into a single disclosed count
instead of listing as rows.
"""

from __future__ import annotations

import math
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Final

from steamlens.contracts import (
    AspectAggregate,
    AspectSlot,
    EpisodeMarker,
    EvidenceQuote,
    GroundedSpan,
    HistogramBucket,
    HistogramSnapshot,
    NarrativeOutcome,
    Report,
    RollupUnit,
    Sentiment,
    SentimentCounts,
    SpanKind,
)
from steamlens.core.allowance import is_spiky_regime, peak_window_share, shipped_interval
from steamlens.dispatch.census_arm import PUBLISHED_READINGS

QUOTES_PER_ASPECT: Final = 3
"""Display cap on verbatim evidence per aspect row — enough to ground the
number in real voices without turning the table into a corpus dump."""

MARKED_SHARE_FLOOR: Final = 0.02
"""The ruled marked-share disclosure floor (the mixing study, DESIGN's
sampling-study rulings: holds at 2%, broken by 5%) — past it the trust panel
states the calibrated bars are not certified for this sample."""

# Timeline SVG geometry, in viewBox units — the template draws rects and
# labels from these coordinates and knows no dates or counts.
_VIEW_W: Final = 800.0
_VIEW_H: Final = 200.0
_PLOT_LEFT: Final = 6.0
_PLOT_RIGHT: Final = 794.0
_PLOT_TOP: Final = 12.0
_PLOT_BASE: Final = 172.0

# The nominal duration closing a histogram's last bucket — buckets stamp at
# period start, so the final bucket's extent is the rollup unit itself.
_UNIT_SPAN: Final = {RollupUnit.MONTH: timedelta(days=30), RollupUnit.WEEK: timedelta(days=7)}


@dataclass(frozen=True, slots=True)
class NarrativeSegment:
    """One run of narrative prose: plain model voice, or a certified span.

    ``kind`` is ``None`` for plain prose between spans; a ``NUMERAL`` segment
    is a minted fact, a ``QUOTE`` segment carries the review it verified
    against — the visual model-voice/minted-fact distinction the design rules,
    drawn from the certificate rather than re-scanning text.
    """

    text: str
    kind: SpanKind | None = None
    review_id: str | None = None


@dataclass(frozen=True, slots=True)
class WhiskerView:
    """One aspect bar's interval, as percentages of the section's axis."""

    low_pct: float
    high_pct: float


@dataclass(frozen=True, slots=True)
class QuoteView:
    """One verbatim evidence quote under an expanded aspect."""

    review_id: str
    sentiment: Sentiment
    text: str


@dataclass(frozen=True, slots=True)
class AspectRowView:
    """One pinned aspect's display row: the bar, its whisker, and its receipts.

    ``share_label`` is the honest number ("27.0% · 270 of 1,000 reviews");
    ``bar_pct``/``whisker`` scale to the section's axis maximum so the bars
    use the width without lying about the scale (the axis states its range).
    """

    aspect: str
    reviews_with_aspect: int
    share_label: str
    bar_pct: float
    whisker: WhiskerView | None
    counts: SentimentCounts
    quotes: tuple[QuoteView, ...]


@dataclass(frozen=True, slots=True)
class AspectSectionView:
    """The pinned-aspect table: rows over one stated axis."""

    rows: tuple[AspectRowView, ...]
    axis_label: str


@dataclass(frozen=True, slots=True)
class CandidateRowView:
    """One emergent candidate aspect — a count, never a calibrated bar."""

    aspect: str
    reviews_with_aspect: int


@dataclass(frozen=True, slots=True)
class CandidateSectionView:
    """The candidate stratum, honestly marked: rows plus the folded singletons."""

    rows: tuple[CandidateRowView, ...]
    singleton_count: int


@dataclass(frozen=True, slots=True)
class TimelineBar:
    """One histogram bucket as plot geometry, tooltip text riding along."""

    x: float
    width: float
    y: float
    height: float
    label: str


@dataclass(frozen=True, slots=True)
class TimelineSpan:
    """One overlay span (episode marker or Valve-marked window) in plot units."""

    x: float
    width: float
    label: str


@dataclass(frozen=True, slots=True)
class TimelineView:
    """The all-language timeline: volume bars plus the two marker layers.

    ``view_w``/``view_h`` are the SVG viewBox the coordinates live in;
    ``baseline_y`` is the x-axis position. The discipline line renders with
    the layer legend — detection stated as method, never cause.
    """

    bars: tuple[TimelineBar, ...]
    episodes: tuple[TimelineSpan, ...]
    valve_windows: tuple[TimelineSpan, ...]
    ticks: tuple[tuple[float, str], ...]
    peak_label: str
    view_w: float = _VIEW_W
    view_h: float = _VIEW_H
    baseline_y: float = _PLOT_BASE


@dataclass(frozen=True, slots=True)
class ReportView:
    """The whole report page, ready to render top to bottom."""

    game_name: str
    provenance_line: str
    narrative: tuple[NarrativeSegment, ...]
    narrative_withheld: bool
    aspects: AspectSectionView
    candidates: CandidateSectionView
    timeline: TimelineView | None
    trust_entries: tuple[tuple[str, str], ...]


@dataclass(frozen=True, slots=True)
class ReportPageData:
    """What the composition root loads for one report page — the render bundle.

    The report row, its frozen aggregate snapshot, and the membership-scoped
    evidence pool (the same read the composer quoted from, so the page's
    receipts and the narrative's grounding are one pool by construction).
    """

    report: Report
    aggregates: tuple[AspectAggregate, ...]
    evidence: tuple[EvidenceQuote, ...]


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


def narrative_segments(
    prose: str, spans: tuple[GroundedSpan, ...]
) -> tuple[NarrativeSegment, ...]:
    """The prose cut along its span certificate — no re-scanning, no markup parsing.

    Offsets refer to the stored prose exactly (the store validates the
    certificate still lands on it at read), so the walk is mechanical: plain
    prose between spans, certified segments at them, in order.
    """
    segments: list[NarrativeSegment] = []
    cursor = 0
    for span in sorted(spans, key=lambda s: s.start):
        if span.start > cursor:
            segments.append(NarrativeSegment(text=prose[cursor : span.start]))
        segments.append(
            NarrativeSegment(
                text=prose[span.start : span.end],
                kind=span.kind,
                review_id=span.review_id,
            )
        )
        cursor = span.end
    if cursor < len(prose):
        segments.append(NarrativeSegment(text=prose[cursor:]))
    return tuple(segments)


def build_report_view(page: ReportPageData) -> ReportView:
    """The one entry: a loaded bundle shaped into the page, top to bottom."""
    report = page.report
    spiky = _regime(report)
    return ReportView(
        game_name=report.game_name,
        provenance_line=provenance_line(report),
        narrative=narrative_segments(report.narrative.prose, report.narrative.spans),
        narrative_withheld=report.narrative.outcome is NarrativeOutcome.WITHHELD,
        aspects=_aspect_section(page, spiky),
        candidates=_candidate_section(page.aggregates),
        timeline=_timeline(report.histogram, report.episodes),
        trust_entries=_trust_entries(report, spiky),
    )


def _regime(report: Report) -> bool | None:
    """The interval regime this game got — ``None`` for take-all (no intervals).

    Recomputed from the stored histogram (regenerate from the layer below):
    the same ``peak_window_share`` reading the study calibrated on, over the
    same snapshot the job planned from, so the answer is deterministic for a
    stored report.
    """
    if report.take_all:
        return None
    return is_spiky_regime(peak_window_share(report.histogram))


def _aspect_section(page: ReportPageData, spiky: bool | None) -> AspectSectionView:
    """Pinned aspects as share bars: sorted by weight, whiskers per the regime."""
    report = page.report
    pinned = sorted(
        (a for a in page.aggregates if a.slot is AspectSlot.PINNED),
        key=lambda a: (-a.reviews_with_aspect, a.aspect),
    )
    quotes = _quotes_by_aspect(page.evidence)
    shares = {a.aspect: a.reviews_with_aspect / a.sample_size for a in pinned}
    intervals = {
        a.aspect: shipped_interval(a.reviews_with_aspect, a.sample_size, spiky=spiky)
        for a in pinned
        if spiky is not None
    }
    edge = max(
        [
            *(shares.values()),
            *(interval.high for interval in intervals.values()),
            0.10,  # a floor so a thin report still gets a readable axis
        ]
    )
    axis_max = _axis_ceiling(edge)
    rows: list[AspectRowView] = []
    for aggregate in pinned:
        interval = intervals.get(aggregate.aspect)
        rows.append(
            AspectRowView(
                aspect=aggregate.aspect,
                reviews_with_aspect=aggregate.reviews_with_aspect,
                share_label=(
                    f"{shares[aggregate.aspect]:.1%} · {aggregate.reviews_with_aspect:,}"
                    f" of {aggregate.sample_size:,} reviews"
                ),
                bar_pct=shares[aggregate.aspect] / axis_max * 100,
                whisker=(
                    None
                    if interval is None
                    else WhiskerView(
                        low_pct=interval.low / axis_max * 100,
                        high_pct=interval.high / axis_max * 100,
                    )
                ),
                counts=aggregate.counts,
                quotes=quotes.get(aggregate.aspect, ()),
            )
        )
    whisker_note = (
        "no whiskers — complete count"
        if report.take_all
        else "whiskers: Wilson + the calibrated allowance"
    )
    return AspectSectionView(
        rows=tuple(rows),
        axis_label=f"share of sample, axis to {axis_max:.0%} · {whisker_note}",
    )


def _axis_ceiling(edge: float) -> float:
    """The bar axis maximum: the smallest 10% step at or above the widest mark.

    Rounded to two decimals so repeated 0.1 steps never leak float dust into
    the axis label or the percent geometry.
    """
    steps = max(1, math.ceil(round(min(edge, 1.0) / 0.10, 9)))
    return min(round(steps * 0.10, 2), 1.0)


def _quotes_by_aspect(
    evidence: tuple[EvidenceQuote, ...]
) -> dict[str, tuple[QuoteView, ...]]:
    """Up to the display cap per aspect, dominant polarity first.

    Dominance is per-aspect majority over the evidence pool itself; the cap
    keeps rows grounded without dumping the pool (a display narrowing, judged
    at the rendered-page checkpoint).
    """
    by_aspect: dict[str, list[EvidenceQuote]] = {}
    for quote in evidence:
        by_aspect.setdefault(quote.aspect, []).append(quote)
    capped: dict[str, tuple[QuoteView, ...]] = {}
    for aspect, pool in by_aspect.items():
        tallies: dict[Sentiment, int] = {}
        for quote in pool:
            tallies[quote.sentiment] = tallies.get(quote.sentiment, 0) + 1
        dominant = max(tallies, key=lambda s: tallies[s])
        ordered = sorted(
            enumerate(pool), key=lambda item: (item[1].sentiment is not dominant, item[0])
        )
        capped[aspect] = tuple(
            QuoteView(review_id=q.review_id, sentiment=q.sentiment, text=q.text)
            for _, q in ordered[:QUOTES_PER_ASPECT]
        )
    return capped


def _candidate_section(
    aggregates: tuple[AspectAggregate, ...]
) -> CandidateSectionView:
    """The emergent stratum: recurring candidates listed, singletons folded."""
    candidates = sorted(
        (a for a in aggregates if a.slot is AspectSlot.CANDIDATE),
        key=lambda a: (-a.reviews_with_aspect, a.aspect),
    )
    recurring = tuple(
        CandidateRowView(aspect=a.aspect, reviews_with_aspect=a.reviews_with_aspect)
        for a in candidates
        if a.reviews_with_aspect >= 2
    )
    singletons = sum(1 for a in candidates if a.reviews_with_aspect < 2)
    return CandidateSectionView(rows=recurring, singleton_count=singletons)


def _timeline(
    histogram: HistogramSnapshot, episodes: tuple[EpisodeMarker, ...]
) -> TimelineView | None:
    """The rollup buckets as plot geometry, marker layers mapped to the same scale.

    ``None`` when the histogram holds no populated bucket — a section absent
    is honest for a game Steam serves no volume series for. Bars sit on a
    linear time axis (buckets tile the lifetime, so index and time agree);
    heights scale to the busiest bucket, which the y-label states.
    """
    populated = [
        b for b in histogram.rollups if b.recommendations_up + b.recommendations_down > 0
    ]
    if not populated:
        return None
    start = histogram.rollups[0].start
    end = histogram.rollups[-1].start + _UNIT_SPAN[histogram.rollup_unit]
    peak = max(b.recommendations_up + b.recommendations_down for b in populated)
    scale_x = (_PLOT_RIGHT - _PLOT_LEFT) / (end - start).total_seconds()

    def x_of(moment: datetime) -> float:
        clamped = min(max(moment, start), end)
        return _PLOT_LEFT + (clamped - start).total_seconds() * scale_x

    unit = _UNIT_SPAN[histogram.rollup_unit]
    slot_w = unit.total_seconds() * scale_x
    gap = 2.0 if slot_w >= 8 else (1.0 if slot_w >= 3 else 0.0)

    def bar(bucket: HistogramBucket) -> TimelineBar:
        volume = bucket.recommendations_up + bucket.recommendations_down
        height = volume / peak * (_PLOT_BASE - _PLOT_TOP)
        return TimelineBar(
            x=x_of(bucket.start),
            width=max(slot_w - gap, 0.75),
            y=_PLOT_BASE - height,
            height=height,
            label=(
                f"{bucket.start.strftime('%b %Y')}: {volume:,} reviews"
                f" ({bucket.recommendations_up:,} up · {bucket.recommendations_down:,} down)"
            ),
        )

    bars = tuple(bar(bucket) for bucket in populated)
    return TimelineView(
        bars=bars,
        episodes=tuple(
            TimelineSpan(
                x=x_of(e.start),
                width=max(x_of(e.end) - x_of(e.start), 2.0),
                label=_episode_label(e),
            )
            for e in episodes
        ),
        valve_windows=tuple(
            TimelineSpan(
                x=x_of(event.start),
                width=max(x_of(event.end) - x_of(event.start), 2.0),
                label=(
                    f"Steam-marked period · {_span_dates(event.start, event.end)}"
                ),
            )
            for event in histogram.past_events
        ),
        ticks=_year_ticks(start, end, x_of),
        peak_label=f"peak {peak:,} reviews / {histogram.rollup_unit.value}",
    )


def _episode_label(episode: EpisodeMarker) -> str:
    """The marker's observation, in the render rule's vocabulary — no causal noun."""
    overlap = (
        " · overlaps a Steam-marked period" if episode.overlaps_marked_window else ""
    )
    return (
        f"review activity spike · {_span_dates(episode.start, episode.end)} · "
        f"{episode.reviews:,} reviews at {episode.peak_multiple:.1f}× baseline{overlap}"
    )


def _span_dates(start: datetime, end: datetime) -> str:
    return f"{start.strftime('%b %d, %Y')} – {end.strftime('%b %d, %Y')}"


def _year_ticks(
    start: datetime, end: datetime, x_of: Callable[[datetime], float]
) -> tuple[tuple[float, str], ...]:
    """January-first ticks across the span; a young game gets its start month."""
    ticks = [
        (x_of(datetime(year, 1, 1, tzinfo=start.tzinfo)), str(year))
        for year in range(start.year + 1, end.year + 1)
    ]
    if not ticks:
        ticks = [(x_of(start), start.strftime("%b %Y"))]
    return tuple(ticks)


def _trust_entries(report: Report, spiky: bool | None) -> tuple[tuple[str, str], ...]:
    """The trust panel as (label, value) rows — the protected element, complete.

    Every value is a stored fact or a deterministic recomputation from one;
    the instrument block quotes the published readings that ride the model
    identity (``dispatch.census_arm``).
    """
    entries = [
        ("Sample", _sample_entry(report)),
        ("Interval regime", _regime_entry(spiky)),
        ("Fetch paths", _paths_entry(report)),
        ("Language mix", _language_entry(report)),
        ("Steam-marked windows", _marked_entry(report)),
        ("Marked share", _marked_share_entry(report)),
        ("Narrative", _narrative_entry(report.narrative.outcome)),
        *[(f"Instrument: {name}", value) for name, value in PUBLISHED_READINGS.items()],
        (
            "Versions",
            f"{report.versions.model_version} · prompt {report.versions.prompt_version}"
            f" · ontology {report.versions.ontology_version}",
        ),
        ("Run", f"{report.run.run_id} · code {report.run.code_version}"),
    ]
    return tuple(entries)


def _sample_entry(report: Report) -> str:
    if report.take_all:
        return (
            f"complete count — every usable English review ({report.sample_size:,}), "
            "fetched whole-life"
        )
    return (
        f"{report.sample_size:,} reviews, time-proportional draw over "
        f"{len(report.windows)} windows (newest-first within each)"
    )


def _regime_entry(spiky: bool | None) -> str:
    if spiky is None:
        return "exact counts — no sampling intervals to calibrate"
    if spiky:
        return (
            "spiky (one window holds ≥ ⅔ of the pool) — whiskers widened by the "
            "calibrated allowance"
        )
    return "calm — Wilson whiskers, zero allowance needed at calibration"


def _paths_entry(report: Report) -> str:
    if not report.windows:
        return "no windows recorded"
    tallies: dict[str, int] = {}
    for window in report.windows:
        tallies[window.outcome.value] = tallies.get(window.outcome.value, 0) + 1
    return " · ".join(f"{count} {path}" for path, count in sorted(tallies.items()))


def _language_entry(report: Report) -> str:
    if not report.language_mix:
        return "no fetch mix recorded"
    total = sum(row.count for row in report.language_mix)
    top = report.language_mix[:3]
    rest = len(report.language_mix) - len(top)
    parts = [f"{row.language} {row.count:,}" for row in top]
    if rest > 0:
        parts.append(f"{rest} more")
    return f"{total:,} fetched: " + " · ".join(parts)


def _marked_entry(report: Report) -> str:
    if not report.marked_window_counts:
        return "none flagged by Steam"
    return "; ".join(
        f"{_span_dates(row.start, row.end)} — {row.members_inside:,} sampled inside"
        for row in report.marked_window_counts
    )


def _marked_share_entry(report: Report) -> str:
    inside = sum(row.members_inside for row in report.marked_window_counts)
    share = inside / report.sample_size if report.sample_size else 0.0
    if share > MARKED_SHARE_FLOOR:
        return (
            f"{share:.1%} of sample inside marked windows — over the 2% floor; "
            "the calibrated bars are not certified at this admixture"
        )
    return f"{share:.1%} of sample inside marked windows — under the 2% floor"


def _narrative_entry(outcome: NarrativeOutcome) -> str:
    return {
        NarrativeOutcome.COMPOSED: "passed the grounding gate first try",
        NarrativeOutcome.RETRIED: "passed the grounding gate after one corrective retry",
        NarrativeOutcome.TRIMMED: "sentences failing the grounding gate were removed",
        NarrativeOutcome.WITHHELD: "withheld — numbers and quotes render without prose",
    }[outcome]
