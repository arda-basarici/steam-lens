"""The compose-stage records — evidence in, certified spans out.

The composed narrative is model output fenced by deterministic gates, and these
records are the fence's wire: ``EvidenceQuote`` is the projection of stored
verbatim evidence the composer may quote from (and the grounding gate verifies
against), ``GroundedSpan`` is one certified span of gate-passed prose. The
certificate tuple is the load-bearing shape downstream: in gate-passed prose
every non-quote numeral matched a job-derived value by construction, so the
report row stores the spans and the renderer styles them straight from the
record — no re-scanning, no markup convention for the model to break.
"""

from __future__ import annotations

from dataclasses import dataclass

from steamlens.contracts.enums import Sentiment, SpanKind


@dataclass(frozen=True, slots=True)
class EvidenceQuote:
    """One verbatim evidence span, addressable back to its review.

    The shell projects these from stored survey mentions for the compose call:
    ``text`` is the span (verbatim by construction — the classify parse nulls
    any quote that fails the substring check before storage), ``review_id`` the
    review it came from, ``aspect`` and ``sentiment`` the mention that carried
    it (the selection rule prefers spans matching an aspect's dominant
    polarity). The same records double as the grounding gate's verification
    pool: a quotation in composed prose must be a verbatim substring of one of
    these texts, and the matching ``review_id`` rides into the certificate.
    """

    review_id: str
    aspect: str
    sentiment: Sentiment
    text: str


@dataclass(frozen=True, slots=True)
class GroundedSpan:
    """One certified span of gate-passed prose — where it sits, and what grounds it.

    ``start``/``end`` are character offsets into the quote-normalized prose the
    gate ran over; ``text`` is the exact span, carried redundantly so the record
    stands alone. A ``NUMERAL`` span carries ``value`` — the whitelisted value
    it matched at the numeral's own precision; a ``QUOTE`` span carries
    ``review_id`` — the evidence source it verified against. The unused field
    is ``None``: one record type, because the renderer walks one list.
    """

    start: int
    end: int
    text: str
    kind: SpanKind
    value: float | None = None
    review_id: str | None = None
