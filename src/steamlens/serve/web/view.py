"""View models for the report page — stored contracts shaped for the template.

The rendering boundary's adaptation layer: pure builders, loaded contracts in,
display records out. Every displayed number traces to a stored record or a
certified seam — shares and interval bands compute through ``core.allowance``'s
shipped interval (never re-derived here), the narrative renders straight off
its span certificate (no prose re-scanning), and the interval regime
recomputes deterministically from the stored histogram (regenerate from the
layer below; the report row deliberately stores content, not presentation).
Presentation needs adapt HERE — never as new fields on the stored contracts,
which is the discipline that keeps a frontend swap rendering-only.

Three display-only adaptations this module owns: evidence quotes cap at
three per aspect, dominant-polarity first, and candidate aspects mentioned
once fold into a single disclosed count instead of listing as rows (both
judged at the chunk-3 checkpoint); displayed quotes expand from the stored
minimal span to its containing sentence in the review (the evidence-display
ruling, 2026-07-17: spans read thin quoted bare — expansion is read-side and
heuristic, the stored evidence and the labeling contract stay untouched).
"""

from __future__ import annotations

import math
from collections.abc import Callable, Mapping
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
    Review,
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

ASPECT_DISPLAY_FLOOR: Final = 0.01
"""Share floor for the always-visible aspect rows. Below 1% of the sample
the interval swallows the value (0.4% ±0.4 is noise wearing a bar), so those
rows fold into a disclosed tail instead of stretching the table — folded,
never dropped."""

QUOTE_DISPLAY_CHAR_CAP: Final = 300
"""Ceiling on an expanded quote's display length. Sentence segmentation over
punctuation-poor reviews is heuristic — a review with no terminal punctuation
would expand a two-word span into the whole text — so past the cap the
display trims to a word-boundary window around the span, ellipses marking
the trims openly."""

MARKED_SHARE_FLOOR: Final = 0.02
"""The ruled marked-share disclosure floor (the mixing study, DESIGN's
sampling-study rulings: holds at 2%, broken by 5%) — past it the trust panel
states the calibrated bars are not certified for this sample."""

HEADER_ART_ORIGIN: Final = "https://shared.akamai.steamstatic.com"
"""The one external origin any page loads from — Steam's public asset CDN.
Public because the Content-Security-Policy (``csp``) must allow exactly this
origin for images: one constant, so the URL pattern and the policy cannot
drift apart."""

_HEADER_ART: Final = (
    HEADER_ART_ORIGIN + "/store_item_assets/steam/apps/{app_id}/header.jpg"
)
"""Steam's public CDN pattern for a game's header capsule — minted from the
stored ``app_id`` at display time (the report stores identity, never asset
URLs). A delisted game may 404 here; the header renders it as decoration
(empty ``alt``), so a missing capsule degrades to layout, not to a broken
claim."""

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
class BarSegment:
    """One polarity segment of an aspect's stacked share bar.

    ``kind`` is the visual role (``positive`` · ``split`` · ``negative``) the
    stylesheet and legend key off; ``label`` discloses the exact composition
    (the split segment folds mixed and neutral — the four-way counts stay in
    the row's detail line).
    """

    kind: str
    pct: float
    label: str


@dataclass(frozen=True, slots=True)
class QuoteView:
    """One verbatim evidence quote under an expanded aspect.

    ``date_label`` is the quoted review's posting date, empty when the bundle
    carries no record for the id (the quote still stands on its stored span).
    """

    review_id: str
    sentiment: Sentiment
    text: str
    date_label: str


@dataclass(frozen=True, slots=True)
class AspectRowView:
    """One pinned aspect's display row: the stacked bar, its numbers, its receipts.

    ``share_label`` is the honest number with its uncertainty riding along
    ("27.0% ±1.5 · 270 of 1,000 reviews" — the ± is the shipped interval's
    half-width, an honest compaction of a not-quite-symmetric interval whose
    exact bounds ride ``interval_title`` as the label's hover text).
    ``segments`` scale to the section's axis maximum so the bars use the
    width without lying about the scale (the axis states its range), and
    carry the polarity split visibly — the share alone says how much talk,
    the stack says what kind.
    """

    aspect: str
    reviews_with_aspect: int
    share_label: str
    interval_title: str | None
    segments: tuple[BarSegment, ...]
    counts: SentimentCounts
    quotes: tuple[QuoteView, ...]


@dataclass(frozen=True, slots=True)
class AspectSectionView:
    """The pinned-aspect table: visible rows over one stated axis, the
    sub-floor tail folded behind ``tail_label`` (empty tail = no fold)."""

    rows: tuple[AspectRowView, ...]
    tail: tuple[AspectRowView, ...]
    tail_label: str
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
    header_image_url: str
    provenance_line: str
    narrative: tuple[NarrativeSegment, ...]
    narrative_withheld: bool
    aspects: AspectSectionView
    candidates: CandidateSectionView
    timeline: TimelineView | None
    trust_entries: tuple[tuple[str, str], ...]
    trust_open: bool


@dataclass(frozen=True, slots=True)
class ReportPageData:
    """What the composition root loads for one report page — the render bundle.

    The report row, its frozen aggregate snapshot, the membership-scoped
    evidence pool (the same read the composer quoted from, so the page's
    receipts and the narrative's grounding are one pool by construction), and
    the reviews that pool quotes — the sentence-expansion and date-stamp
    source (an id absent from the map degrades that quote to its stored
    span, undated).
    """

    report: Report
    aggregates: tuple[AspectAggregate, ...]
    evidence: tuple[EvidenceQuote, ...]
    quoted_reviews: Mapping[str, Review]


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
        header_image_url=_HEADER_ART.format(app_id=report.app_id),
        provenance_line=provenance_line(report),
        narrative=narrative_segments(report.narrative.prose, report.narrative.spans),
        narrative_withheld=report.narrative.outcome is NarrativeOutcome.WITHHELD,
        aspects=_aspect_section(page, spiky),
        candidates=_candidate_section(page.aggregates),
        timeline=_timeline(report.histogram, report.episodes),
        trust_entries=_trust_entries(report, spiky),
        # The panel folds by default (reference material), but a report whose
        # calibrated bars are not certified must not hide that disclosure
        # behind a click — the caveat forces it open.
        trust_open=_marked_share(report) > MARKED_SHARE_FLOOR,
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
    quotes = _quotes_by_aspect(page.evidence, page.quoted_reviews)
    shares = {a.aspect: a.reviews_with_aspect / a.sample_size for a in pinned}
    intervals = {
        a.aspect: shipped_interval(a.reviews_with_aspect, a.sample_size, spiky=spiky)
        for a in pinned
        if spiky is not None
    }
    edge = max(
        [
            *(shares.values()),
            0.10,  # a floor so a thin report still gets a readable axis
        ]
    )
    axis_max = _axis_ceiling(edge)
    rows: list[tuple[float, AspectRowView]] = []
    for aggregate in pinned:
        interval = intervals.get(aggregate.aspect)
        plus_minus = (
            ""
            if interval is None
            else f" ±{(interval.high - interval.low) / 2 * 100:.1f}"
        )
        rows.append(
            (
                shares[aggregate.aspect],
                AspectRowView(
                    aspect=_display_name(aggregate.aspect),
                    reviews_with_aspect=aggregate.reviews_with_aspect,
                    share_label=(
                        f"{shares[aggregate.aspect]:.1%}{plus_minus}"
                        f" · {aggregate.reviews_with_aspect:,}"
                        f" of {aggregate.sample_size:,} reviews"
                    ),
                    interval_title=(
                        None
                        if interval is None
                        else f"sampling interval {interval.low:.1%}–{interval.high:.1%}"
                    ),
                    segments=_segments(
                        aggregate.counts, aggregate.sample_size, axis_max
                    ),
                    counts=aggregate.counts,
                    quotes=quotes.get(aggregate.aspect, ()),
                ),
            )
        )
    interval_note = (
        "exact counts — no sampling interval"
        if report.take_all
        else "± is the sampling interval (Wilson + the calibrated allowance)"
    )
    visible = [row for share, row in rows if share >= ASPECT_DISPLAY_FLOOR]
    tail = [row for share, row in rows if share < ASPECT_DISPLAY_FLOOR]
    if not visible:
        visible, tail = tail, []
    return AspectSectionView(
        rows=tuple(visible),
        tail=tuple(tail),
        tail_label=f"{len(tail)} more aspects under 1% of the sample",
        axis_label=f"share of sample, axis to {axis_max:.0%} · {interval_note}",
    )


def _segments(
    counts: SentimentCounts, sample_size: int, axis_max: float
) -> tuple[BarSegment, ...]:
    """The polarity stack for one bar: poles at the ends, the split fold between.

    Widths share the bar's own scale (counts over ``sample_size``, stretched
    to the section axis), so the segments tile exactly the length the share
    claims; empty segments vanish rather than rendering zero-width slivers.
    """
    scale = 100 / (sample_size * axis_max)
    parts = (
        ("positive", counts.positive, f"{counts.positive:,} positive"),
        (
            "split",
            counts.mixed + counts.neutral,
            f"{counts.mixed:,} mixed · {counts.neutral:,} neutral",
        ),
        ("negative", counts.negative, f"{counts.negative:,} negative"),
    )
    return tuple(
        BarSegment(kind=kind, pct=count * scale, label=label)
        for kind, count, label in parts
        if count > 0
    )


def _axis_ceiling(edge: float) -> float:
    """The bar axis maximum: the smallest 10% step at or above the widest mark.

    Rounded to two decimals so repeated 0.1 steps never leak float dust into
    the axis label or the percent geometry.
    """
    steps = max(1, math.ceil(round(min(edge, 1.0) / 0.10, 9)))
    return min(round(steps * 0.10, 2), 1.0)


def _display_name(aspect: str) -> str:
    """The ontology key as reader-facing text — underscores become spaces.

    Display-only: stored identities, quote grouping, and the label pool all
    keep the exact key (``voice_acting``); only the rendered row wears the
    spaced form.
    """
    return aspect.replace("_", " ")


def _quotes_by_aspect(
    evidence: tuple[EvidenceQuote, ...], quoted_reviews: Mapping[str, Review]
) -> dict[str, tuple[QuoteView, ...]]:
    """Up to the display cap per aspect, dominant polarity first, each quote
    expanded to its containing sentence and stamped with its review's date.

    Dominance is per-aspect majority over the evidence pool itself; the cap
    keeps rows grounded without dumping the pool (a display narrowing, judged
    at the rendered-page checkpoint). Expansion runs only on the quotes that
    survive the cap — the pool's spans stay as stored.
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
        views: list[QuoteView] = []
        for _, q in ordered[:QUOTES_PER_ASPECT]:
            review = quoted_reviews.get(q.review_id)
            views.append(
                QuoteView(
                    review_id=q.review_id,
                    sentiment=q.sentiment,
                    text=sentence_display_text(
                        q.text, None if review is None else review.text
                    ),
                    date_label=(
                        "" if review is None else review.created_at.strftime("%b %d, %Y")
                    ),
                )
            )
        capped[aspect] = tuple(views)
    return capped


_SENTENCE_BREAKS: Final = frozenset(".!?…\n")


def sentence_display_text(span: str, review_text: str | None) -> str:
    """``span`` grown to its containing sentence in ``review_text``, capped.

    The evidence-display ruling made concrete: stored spans are minimal
    verbatim substrings and read thin quoted bare, so the display walks out
    to sentence boundaries (terminal punctuation or a line break — Steam
    reviews often separate thoughts with newlines) and keeps the closing
    mark. Purely read-side: a missing text, or a span the text no longer
    contains, falls back to the stored span unchanged. Past the display cap
    the sentence trims to a word-boundary window around the span, ellipses
    marking the trims.
    """
    if review_text is None:
        return span
    at = review_text.find(span)
    if at == -1:
        return span
    start = at
    while start > 0 and review_text[start - 1] not in _SENTENCE_BREAKS:
        start -= 1
    end = at + len(span)
    while end < len(review_text) and review_text[end] not in _SENTENCE_BREAKS:
        end += 1
    if end < len(review_text) and review_text[end] != "\n":
        end += 1
    sentence = review_text[start:end].strip()
    return _window_around(sentence, span) if len(sentence) > QUOTE_DISPLAY_CHAR_CAP else sentence


def _window_around(sentence: str, span: str) -> str:
    """The over-cap trim: equal word-boundary margins around ``span``, ellipsized."""
    margin = (QUOTE_DISPLAY_CHAR_CAP - len(span)) // 2
    if margin <= 0:
        return span
    at = sentence.find(span)
    lead, tail = sentence[:at], sentence[at + len(span) :]
    if len(lead) > margin:
        kept = lead[-margin:]
        cut = kept.find(" ")
        lead = "… " + (kept[cut + 1 :] if cut != -1 else kept)
    if len(tail) > margin:
        kept = tail[:margin]
        cut = kept.rfind(" ")
        tail = (kept[:cut] if cut != -1 else kept) + " …"
    return lead + span + tail


def _candidate_section(
    aggregates: tuple[AspectAggregate, ...]
) -> CandidateSectionView:
    """The emergent stratum: recurring candidates listed, singletons folded."""
    candidates = sorted(
        (a for a in aggregates if a.slot is AspectSlot.CANDIDATE),
        key=lambda a: (-a.reviews_with_aspect, a.aspect),
    )
    recurring = tuple(
        CandidateRowView(
            aspect=_display_name(a.aspect), reviews_with_aspect=a.reviews_with_aspect
        )
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
            "spiky (one window holds ≥ ⅔ of the pool) — intervals widened by the "
            "calibrated allowance"
        )
    return "calm — Wilson intervals, zero allowance needed at calibration"


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


def _marked_share(report: Report) -> float:
    """The sample share drawn inside Steam-marked windows — the floor's input."""
    inside = sum(row.members_inside for row in report.marked_window_counts)
    return inside / report.sample_size if report.sample_size else 0.0


def _marked_share_entry(report: Report) -> str:
    share = _marked_share(report)
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
