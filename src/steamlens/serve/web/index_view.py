"""View models for the reports index — the library of published analyses.

The listing page's rendering half, same discipline as ``view`` and
``ops_view``: pure builders, loaded cards in, display records out. The home
page's recently-analyzed strip renders through the same builder — a compact
picture-and-name cut of the same records, so a card links identically
wherever it appears. Each card
is an honest preview of its report page — the same header art, the
same provenance phrase, and the same aspects that lead the page's share bars
(the store's read orders them identically) — so clicking through confirms
the card rather than re-ranking it. Cards carry no sentiment or share
numbers by ruling: the page owns interpretation, the card only says what
the discussion is about.

Tag color encodes the ontology's own category layer ("organizational only" —
this page is the first organizational consumer): every aspect wears its
family's hue, seven families, seven validated categorical slots. Color
narrows, text decides — two same-family tags share a hue and are told apart
by their names, which is the honest reading of seven colors over 51 pins.
The composition root supplies the label→category mapping from the same
ontology artifact the runner labels with, so the coloring can never disagree
with the vocabulary that minted the tags; an unmapped label degrades to the
neutral pill, never to a wrong family.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

from steamlens.contracts import ReportCard
from steamlens.serve.links import report_path
from steamlens.serve.web.view import analyzed_line, display_name, header_art


@dataclass(frozen=True, slots=True)
class TagView:
    """One aspect tag: its display name and its family key (None = unmapped)."""

    name: str
    category: str | None


@dataclass(frozen=True, slots=True)
class CardView:
    """One clickable game card: where it links and what it shows."""

    href: str
    image_url: str
    name: str
    provenance: str
    tags: tuple[TagView, ...]


@dataclass(frozen=True, slots=True)
class IndexView:
    """Everything ``reports.html`` renders."""

    cards: tuple[CardView, ...]


def build_index_view(
    cards: tuple[ReportCard, ...], categories: Mapping[str, str]
) -> IndexView:
    """Shape the stored cards into the page — order is the store's, newest first."""
    return IndexView(
        cards=tuple(
            CardView(
                href=report_path(card.app_id, card.game_name),
                image_url=header_art(card.header_image, card.app_id),
                name=card.game_name,
                provenance=analyzed_line(
                    card.created_at, card.sample_size, card.take_all
                ),
                tags=tuple(
                    TagView(name=display_name(aspect), category=categories.get(aspect))
                    for aspect in card.top_aspects
                ),
            )
            for card in cards
        )
    )
