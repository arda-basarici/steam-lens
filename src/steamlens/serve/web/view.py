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

Display-only adaptations this module owns: evidence quotes cap at three per
aspect, dominant-polarity first (judged at the chunk-3 checkpoint);
displayed quotes expand from the stored minimal span to its containing
sentence in the review (the evidence-display ruling, 2026-07-17: spans read
thin quoted bare — expansion is read-side and heuristic, the stored evidence
and the labeling contract stay untouched); and the aspect display floors
(2026-08-14): any aspect, pinned or emergent, needs five supporting reviews
to appear at all, and the pinned table shows its top ten with the rest
behind "see more". The review timeline renders volume, Steam-marked
windows, and a positive-share companion chart; stored episode markers
deliberately stay off the page (2026-08-14) — the render rule forbids
attributing a cause, so a highlighted span was a question the report
refuses to answer.
"""

from __future__ import annotations

import math
import re
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Final

from steamlens.contracts import (
    AspectAggregate,
    AspectSlot,
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

ASPECT_EVIDENCE_FLOOR: Final = 5
"""Hard evidence floor for every displayed aspect, pinned and emergent alike.
Below five supporting reviews a count is indistinguishable from the
classifier's false-positive background — observed directly (2026-08-14):
one-and-two-count rows open onto unrelated quotes — so such rows are cut
from the page entirely, not folded; mislabeled evidence on display costs
more trust than a missing row. The trust panel states the rule."""

ASPECT_VISIBLE_ROWS: Final = 10
"""How many pinned rows show before the rest fold behind "see more". Purely
presentational: the evidence floor above carries the statistical judgment,
so this fold only manages page length — a fixed count keeps every report's
default view the same size."""

SHARE_SAMPLE_FLOOR: Final = 5
"""Buckets with fewer reviews than this render their positive share faded.
A percentage over a handful of reviews is binomial noise (two of three
reviews reads as 67% positive), but dropping the bar would misread as a
gap in Steam's series — so the bar stays, muted, its tooltip carrying the
count that explains the fade."""

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
"""The origin the header capsule is minted from — one host in Steam's asset
CDN family. The Content-Security-Policy (``csp``) allows that family by
wildcard; this stays public so a render test can pin the minted origin
inside it — the drift a shared constant would otherwise have prevented."""

_HEADER_ART: Final = (
    HEADER_ART_ORIGIN + "/store_item_assets/steam/apps/{app_id}/header.jpg"
)
"""Steam's public CDN pattern for a game's header capsule — minted from the
stored ``app_id`` at display time (the report stores identity, never asset
URLs). A delisted game may 404 here; the header renders it as decoration
(empty ``alt``), so a missing capsule degrades to layout, not to a broken
claim."""

# Timeline SVG geometry, in viewBox units — the template draws rects and
# labels from these coordinates and knows no dates or counts. Both plots
# live in ONE SVG on one x scale — volume bars on top, the positive-share
# line below — so a bucket-wide hover strip can span the pair and highlight
# a month in both at once without any script. Y anchors run top to bottom;
# the share plot's axis is absolute (0–100%), so its midline is exactly 50%.
_VIEW_W: Final = 800.0
_VIEW_H: Final = 326.0
_PLOT_LEFT: Final = 46.0
_PLOT_RIGHT: Final = 794.0
_VOL_CAPTION_Y: Final = 18.0
_PLOT_TOP: Final = 30.0
_PLOT_BASE: Final = 170.0
_SHARE_CAPTION_Y: Final = 206.0
_SHARE_TOP: Final = 218.0
_SHARE_BASE: Final = 298.0

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
    """The pinned-aspect table: the top rows over one stated axis, the rest
    folded behind a "see more" toggle (empty tail = no fold). Rows under the
    evidence floor were cut before this view existed; empty ``rows`` means
    nothing cleared it, and the template says so."""

    rows: tuple[AspectRowView, ...]
    tail: tuple[AspectRowView, ...]
    axis_label: str


@dataclass(frozen=True, slots=True)
class CandidateRowView:
    """One emergent candidate aspect — a count, never a calibrated bar."""

    aspect: str
    reviews_with_aspect: int


@dataclass(frozen=True, slots=True)
class CandidateSectionView:
    """The candidate stratum, honestly marked: the rows clearing the
    evidence floor (empty = the section stays off the page)."""

    rows: tuple[CandidateRowView, ...]


@dataclass(frozen=True, slots=True)
class TimelineBar:
    """One histogram bucket as volume-plot geometry (hover strips carry the text)."""

    x: float
    width: float
    y: float
    height: float


@dataclass(frozen=True, slots=True)
class TimelineSpan:
    """One Valve-marked window as an overlay span in plot units."""

    x: float
    width: float


@dataclass(frozen=True, slots=True)
class AxisMark:
    """One y-scale anchor: a gutter label at ``y``, ruling a faint line across
    the plot when ``ruled`` (marks whose line something else already draws —
    the baseline, the dashed midline — carry the label alone)."""

    y: float
    label: str
    ruled: bool


@dataclass(frozen=True, slots=True)
class ShareDot:
    """A share point drawn as a dot instead of joining the line: a low-sample
    bucket (faded — its share is binomial noise) or an isolated healthy bucket
    a one-point line could never show."""

    x: float
    y: float
    low_sample: bool


@dataclass(frozen=True, slots=True)
class HoverStrip:
    """One bucket-wide hover target spanning both plots. Its tooltip joins the
    month's whole story — volume, up/down split, positive share, a small-sample
    caveat, Steam-marked overlap — so hovering either chart reads both."""

    x: float
    width: float
    label: str


@dataclass(frozen=True, slots=True)
class ShareChartView:
    """The positive-share plot: a line where the data supports one, dots
    where it doesn't.

    ``line_segments`` are ready ``points`` strings, one polyline per
    contiguous run of healthy buckets — the line breaks at empty and
    low-sample months rather than interpolating through them. The axis is
    absolute 0–100% (a flat line near the top is stability, not a rendering
    problem); ``midline_y`` is the 50% reference and ``note`` the fine print.
    """

    line_segments: tuple[str, ...]
    dots: tuple[ShareDot, ...]
    marks: tuple[AxisMark, ...]
    caption: str
    note: str
    midline_y: float
    caption_y: float = _SHARE_CAPTION_Y
    baseline_y: float = _SHARE_BASE


@dataclass(frozen=True, slots=True)
class TimelineView:
    """The all-language timeline as one SVG: volume bars over a positive-share
    line, Steam-marked windows and year gridlines spanning both plots, and
    per-bucket hover strips tying the pair together.

    ``view_w``/``view_h`` are the SVG viewBox the coordinates live in;
    ``baseline_y`` is the volume plot's x-axis, ``overlay_top``/``overlay_bottom``
    bound the full-height layers. Stored episode markers deliberately do not
    render (ruled 2026-08-14): the render rule forbids attributing a cause,
    so a highlighted span was a question the report refuses to answer —
    detection stays in ``core/detect`` and in storage for the investigator
    milestone.
    """

    bars: tuple[TimelineBar, ...]
    valve_windows: tuple[TimelineSpan, ...]
    hover_strips: tuple[HoverStrip, ...]
    ticks: tuple[tuple[float, str], ...]
    marks: tuple[AxisMark, ...]
    caption: str
    peak_label: str
    share: ShareChartView
    caption_y: float = _VOL_CAPTION_Y
    overlay_top: float = _PLOT_TOP
    overlay_bottom: float = _SHARE_BASE
    plot_left: float = _PLOT_LEFT
    plot_right: float = _PLOT_RIGHT
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
    """The header one-liner: the date worn openly, and what the numbers stand on."""
    return analyzed_line(report.created_at, report.sample_size, report.take_all)


def analyzed_line(created_at: datetime, sample_size: int, take_all: bool) -> str:
    """The provenance phrase every report surface wears — page header and
    index card say it identically.

    A cached report serves as-is with its analysis date displayed — the
    staleness ruling made visible. The sample clause states the two-track
    denominators honestly: a take-all is a complete count, a sampled run names
    its n.

    >>> from datetime import UTC, datetime
    >>> analyzed_line(datetime(2026, 8, 10, tzinfo=UTC), 1000, take_all=False)
    'analyzed 2026-08-10 · sample of 1,000 English reviews'
    """
    date = created_at.date().isoformat()
    if take_all:
        return f"analyzed {date} · complete count of {sample_size:,} English reviews"
    return f"analyzed {date} · sample of {sample_size:,} English reviews"


def header_art_url(app_id: int) -> str:
    """The game's header capsule URL, minted from stored identity at display time."""
    return _HEADER_ART.format(app_id=app_id)


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


def _humanize_echoed_keys(
    segments: tuple[NarrativeSegment, ...], aspect_keys: Iterable[str]
) -> tuple[NarrativeSegment, ...]:
    """Model-voice segments with echoed ontology keys worn spaced.

    The composer is prompted with the vocabulary's keys and sometimes writes
    one verbatim into prose ("the most notable split is game_length") — the
    same reader-facing cleanup the aspect rows get, applied to the report
    text. Display-only and scoped to this report's own aspect keys at word
    boundaries, never generic underscore stripping. Certified segments pass
    untouched: a quote stays verbatim from its review, and rewriting any
    certified span would misstate the certificate.
    """
    keyed = sorted((k for k in aspect_keys if "_" in k), key=len, reverse=True)
    if not keyed:
        return segments
    echoed = re.compile("|".join(rf"\b{re.escape(key)}\b" for key in keyed))
    return tuple(
        segment
        if segment.kind is not None
        else NarrativeSegment(
            text=echoed.sub(lambda hit: display_name(hit.group()), segment.text)
        )
        for segment in segments
    )


def build_report_view(page: ReportPageData) -> ReportView:
    """The one entry: a loaded bundle shaped into the page, top to bottom."""
    report = page.report
    spiky = _regime(report)
    return ReportView(
        game_name=report.game_name,
        header_image_url=header_art_url(report.app_id),
        provenance_line=provenance_line(report),
        narrative=_humanize_echoed_keys(
            narrative_segments(report.narrative.prose, report.narrative.spans),
            {a.aspect for a in page.aggregates},
        ),
        narrative_withheld=report.narrative.outcome is NarrativeOutcome.WITHHELD,
        aspects=_aspect_section(page, spiky),
        candidates=_candidate_section(page.aggregates),
        timeline=_timeline(report.histogram),
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
    """Pinned aspects as share bars: sorted by weight, whiskers per the regime,
    the evidence floor cut before anything renders."""
    report = page.report
    pinned = sorted(
        (
            a
            for a in page.aggregates
            if a.slot is AspectSlot.PINNED
            and a.reviews_with_aspect >= ASPECT_EVIDENCE_FLOOR
        ),
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
    rows: list[AspectRowView] = []
    for aggregate in pinned:
        interval = intervals.get(aggregate.aspect)
        plus_minus = (
            ""
            if interval is None
            else f" ±{(interval.high - interval.low) / 2 * 100:.1f}"
        )
        rows.append(
            AspectRowView(
                aspect=display_name(aggregate.aspect),
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
            )
        )
    interval_note = (
        "exact counts — no sampling interval"
        if report.take_all
        else "± is the sampling interval (Wilson + the calibrated allowance)"
    )
    return AspectSectionView(
        rows=tuple(rows[:ASPECT_VISIBLE_ROWS]),
        tail=tuple(rows[ASPECT_VISIBLE_ROWS:]),
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


def display_name(aspect: str) -> str:
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
    """The emergent stratum: candidates clearing the evidence floor, counts only.

    The same floor as the pinned table, for the same reason — a free-form
    candidate under it is even likelier to be classifier noise than a pinned
    aspect is (uncalibrated by design), and its quotes read just as wrong.
    """
    candidates = sorted(
        (
            a
            for a in aggregates
            if a.slot is AspectSlot.CANDIDATE
            and a.reviews_with_aspect >= ASPECT_EVIDENCE_FLOOR
        ),
        key=lambda a: (-a.reviews_with_aspect, a.aspect),
    )
    return CandidateSectionView(
        rows=tuple(
            CandidateRowView(
                aspect=display_name(a.aspect),
                reviews_with_aspect=a.reviews_with_aspect,
            )
            for a in candidates
        )
    )


def _timeline(histogram: HistogramSnapshot) -> TimelineView | None:
    """The rollup buckets as plot geometry: volume bars, the positive-share
    line, Steam-marked windows, and per-bucket hover strips on one x scale.

    ``None`` when the histogram holds no populated bucket — a section absent
    is honest for a game Steam serves no volume series for. Bars sit on a
    linear time axis (buckets tile the lifetime, so index and time agree);
    volume heights scale to the busiest bucket, which the y-label states,
    while share heights are absolute (the plot's top is 100% positive). The
    share line joins only contiguous healthy buckets: it breaks at empty
    months instead of interpolating data that isn't there, and low-sample
    months fall out of the line as faded dots instead of lending their
    binomial noise the authority of a trend.
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
        )

    def center_x(bucket: HistogramBucket) -> float:
        return x_of(bucket.start) + slot_w / 2

    def share_y(bucket: HistogramBucket) -> float:
        total = bucket.recommendations_up + bucket.recommendations_down
        share = bucket.recommendations_up / total
        return _SHARE_BASE - share * (_SHARE_BASE - _SHARE_TOP)

    segments: list[str] = []
    dots: list[ShareDot] = []
    run: list[HistogramBucket] = []

    def close_run() -> None:
        if len(run) == 1:
            dots.append(ShareDot(x=center_x(run[0]), y=share_y(run[0]), low_sample=False))
        elif run:
            segments.append(
                " ".join(f"{center_x(b):.2f},{share_y(b):.2f}" for b in run)
            )
        run.clear()

    for bucket in histogram.rollups:
        total = bucket.recommendations_up + bucket.recommendations_down
        if total == 0:
            close_run()
        elif total < SHARE_SAMPLE_FLOOR:
            close_run()
            dots.append(
                ShareDot(x=center_x(bucket), y=share_y(bucket), low_sample=True)
            )
        else:
            run.append(bucket)
    close_run()

    def strip(bucket: HistogramBucket) -> HoverStrip:
        total = bucket.recommendations_up + bucket.recommendations_down
        share = bucket.recommendations_up / total
        marked = any(
            event.start < bucket.start + unit and bucket.start < event.end
            for event in histogram.past_events
        )
        label = (
            f"{bucket.start.strftime('%b %Y')} · {total:,} reviews"
            f" ({bucket.recommendations_up:,} up · {bucket.recommendations_down:,} down)"
            f" · {share:.0%} positive"
        )
        if total < SHARE_SAMPLE_FLOOR:
            label += " · small sample"
        if marked:
            label += " · Steam-marked period"
        return HoverStrip(x=x_of(bucket.start), width=slot_w, label=label)

    unit_name = histogram.rollup_unit.value
    adverb = {"month": "monthly", "week": "weekly"}[unit_name]
    midline_y = (_SHARE_TOP + _SHARE_BASE) / 2
    return TimelineView(
        bars=tuple(bar(bucket) for bucket in populated),
        valve_windows=tuple(
            TimelineSpan(
                x=x_of(event.start),
                width=max(x_of(event.end) - x_of(event.start), 2.0),
            )
            for event in histogram.past_events
        ),
        hover_strips=tuple(strip(bucket) for bucket in populated),
        ticks=_year_ticks(start, end, x_of),
        marks=_volume_marks(peak),
        caption="review volume",
        peak_label=f"{adverb} peak {peak:,} reviews",
        share=ShareChartView(
            line_segments=tuple(segments),
            dots=tuple(dots),
            marks=(
                AxisMark(y=_SHARE_TOP, label="100%", ruled=True),
                AxisMark(y=midline_y, label="50%", ruled=False),
                AxisMark(y=_SHARE_BASE, label="0%", ruled=False),
            ),
            caption="positive review share",
            note=(
                f"{adverb} share rated positive · 50% reference · "
                f"{unit_name}s with <{SHARE_SAMPLE_FLOOR} reviews faded"
            ),
            midline_y=midline_y,
        ),
    )


def _volume_marks(peak: int) -> tuple[AxisMark, ...]:
    """Round-number scale anchors for the peak-scaled volume plot.

    The step is the smallest 1/2/5×10ᵏ giving at most four lines under the
    peak (floored at one review), so the axis reads in round numbers at any
    magnitude while the bars keep their exact peak-anchored scale. The
    baseline carries an unruled "0" — the axis line itself already draws it.
    """
    raw = peak / 4
    if raw < 1:
        step = 1
    else:
        magnitude = 10.0 ** math.floor(math.log10(raw))
        step = int(next(c * magnitude for c in (1, 2, 5, 10) if c * magnitude >= raw))

    def y_of(volume: int) -> float:
        return _PLOT_BASE - volume / peak * (_PLOT_BASE - _PLOT_TOP)

    ruled = tuple(
        AxisMark(y=y_of(volume), label=f"{volume:,}", ruled=True)
        for volume in range(step, peak + 1, step)
    )
    return ruled + (AxisMark(y=_PLOT_BASE, label="0", ruled=False),)


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
        (
            "Evidence floor",
            f"aspects and emergent themes appear only with "
            f"{ASPECT_EVIDENCE_FLOOR}+ supporting reviews — smaller counts "
            "sit at the classifier's false-positive floor",
        ),
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
