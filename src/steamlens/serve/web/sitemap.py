"""The sitemap — every page a search engine is invited to, as one XML document.

A crawler finds a report by following a link to it, and the library page is
the only page that links them all. The sitemap states the same list directly:
the front door, the library, and each published report at its canonical
address. It is built from the library's own cards, so it can never name a
report the library would not show.
"""

from __future__ import annotations

from collections.abc import Iterable
from xml.sax.saxutils import escape

from steamlens.contracts import ReportCard
from steamlens.serve.links import public_url, report_path

_INDEX_PATHS = ("/", "/reports")
"""The pages listed beside the reports. They carry no modification date. The
only time on hand is the newest report's completion, which says when the
list last grew and which that report's own entry already states."""


def sitemap_xml(cards: Iterable[ReportCard]) -> str:
    """The sitemap document for the given library cards.

    Each report's ``lastmod`` is its completion date, the one stored time at
    which its content changed. A re-run publishes a new report under the
    same address, and the card the library keeps is the newest, so the date
    moves with it.
    """
    urls = [_url_element(public_url(path)) for path in _INDEX_PATHS]
    urls.extend(
        _url_element(
            public_url(report_path(card.app_id, card.game_name)),
            lastmod=card.created_at.date().isoformat(),
        )
        for card in cards
    )
    return (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n'
        + "".join(urls)
        + "</urlset>\n"
    )


def _url_element(location: str, lastmod: str | None = None) -> str:
    # Slugs are ascii letters, digits and hyphens, so nothing here needs
    # escaping today; the escape keeps the document well-formed if an address
    # ever gains a query string.
    modified = "" if lastmod is None else f"<lastmod>{lastmod}</lastmod>"
    return f"  <url><loc>{escape(location)}</loc>{modified}</url>\n"
