"""The persisted report — everything a report page shows, as structured data.

One completed analysis becomes one ``Report``: the record the persistence
layer stores and the frontend renders, holding content and never presentation
(DESIGN's serving-persistence ruling — caching structured data lets the
frontend iterate freely without invalidating or lying about a cached report).
The display-side records here are deliberate projections, not the pipeline's
working types: an ``EpisodeMarker`` is a detected episode *plus* the
Valve-overlap fact a marker may state, a ``WindowAccount`` is a fetch window
reduced to the path outcome the trust panel discloses. Each carries exactly
what the page may say — the render rules ("no causal noun", "totals, not
per-window English detail") are enforced by what these records omit.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from steamlens.contracts.compose import ComposedNarrative
from steamlens.contracts.enums import PathOutcome
from steamlens.contracts.provenance import ClassifierVersions, Provenance
from steamlens.contracts.steam import HistogramSnapshot


@dataclass(frozen=True, slots=True)
class WindowAccount:
    """One fetch window's account for the trust panel: bounds and the path taken.

    Deliberately the ruled grain and nothing more — which path delivered each
    window is provenance the panel discloses; per-window realized-English
    detail was ruled out (the step-5 design), so this record cannot carry it.
    Totals live on the report as scalars.
    """

    start: datetime
    end: datetime
    outcome: PathOutcome


@dataclass(frozen=True, slots=True)
class LanguageCount:
    """One language's share of the fetched reviews — the mix disclosure's row."""

    language: str
    count: int


@dataclass(frozen=True, slots=True)
class EpisodeMarker:
    """One displayed episode: a detected span plus the one external fact it may state.

    The projection of ``core/detect``'s episode for the report page — span,
    magnitude, review count, and whether the span overlaps a Valve-marked
    anomalous window (a fact about Steam's own flagging, stated plainly; its
    absence says nothing). No cause, no label: markers render observations
    only, and the record has no field a causal noun could ride in on.
    """

    start: datetime
    end: datetime
    buckets: int
    reviews: int
    peak_multiple: float
    overlaps_marked_window: bool


@dataclass(frozen=True, slots=True)
class MarkedWindowCount:
    """How many sample members fell inside one Valve-marked window.

    The trust panel's disclosure grain: sampled reviews inside marked windows
    are *kept* in the numbers (the unfiltered-fetch ruling), and this record
    is what makes the keeping honest — the count per window, displayed beside
    the timeline event rather than silently folded away.
    """

    start: datetime
    end: datetime
    members_inside: int


@dataclass(frozen=True, slots=True)
class Report:
    """One completed analysis, frozen: the page's whole content with its provenance.

    ``run`` stamps the job that bought this report (its ``run_id`` is the
    report's identity and names the stored sample membership — the manifest
    the mint folded); ``created_at`` is the completion moment, distinct from
    the run stamp's start; ``versions`` pins the label versions every number
    was folded under. ``sample_size`` and ``take_all`` say what the numbers
    rest on; ``windows`` and ``language_mix`` are the trust panel's fetch
    provenance. ``narrative`` is the gate-passed prose with its certificate
    (outcome recorded, never inferred), ``histogram`` the timeline as Steam
    served it at job time, ``episodes`` and ``marked_window_counts`` the
    timeline's marker layers. A dated report served later is this record
    unchanged, its date worn openly.
    """

    run: Provenance
    app_id: int
    game_name: str
    created_at: datetime
    versions: ClassifierVersions
    sample_size: int
    take_all: bool
    windows: tuple[WindowAccount, ...]
    language_mix: tuple[LanguageCount, ...]
    narrative: ComposedNarrative
    histogram: HistogramSnapshot
    episodes: tuple[EpisodeMarker, ...]
    marked_window_counts: tuple[MarkedWindowCount, ...]
