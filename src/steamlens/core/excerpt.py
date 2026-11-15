"""Cutting a review down to what is read — one rule for the report page and the chat.

A stored evidence span is a few verbatim words, and a review can run to
thousands of characters. What a person or a model is shown sits between the
two: the span grown to its containing sentence, capped. The report page
adopted that rule for its quotes, and the chat reads its reviews under the
same one, so the chat and the report it links to show the same sentence for
the same review.

Around the rule sit the three things the chat needs that the page does not.
A review found by search has no stored span, so ``phrase_anchor`` finds the
words the search matched, as the review wrote them, and the sentence is grown
from there. ``mentions_spoiler`` is the test that keeps a review out of every
read: one that contains the word is never an excerpt, so it can be neither
quoted nor paraphrased. And ``seeded_draw`` picks which of an aspect's
labelled reviews are read: a draw in proportion to their sentiments, since
the labels give no query to rank by, and seeded so the same game and aspect
give the same excerpts every time.

Everything here is pure. The reads that feed it live in ``chat.evidence``.
"""

from __future__ import annotations

import hashlib
import random
import re
from collections.abc import Sequence
from typing import Final

from steamlens.contracts import EvidenceQuote, Sentiment

QUOTE_DISPLAY_CHAR_CAP: Final = 300
"""Ceiling on an expanded quote's display length. Sentence segmentation over
punctuation-poor reviews is heuristic — a review with no terminal punctuation
would expand a two-word span into the whole text — so past the cap the
display trims to a word-boundary window around the span, ellipses marking
the trims openly."""


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


LABELLED_READ_FLOOR: Final = 5
"""An aspect fewer of a game's reviews mention than this is not read by label.
The report page cuts such a row for the same reason: at one or two reviews
the label is as likely to be the classifier's background error as the
aspect, and the quotes behind it are about something else."""

_SENTIMENT_ORDER: Final = (
    Sentiment.POSITIVE, Sentiment.NEGATIVE, Sentiment.MIXED, Sentiment.NEUTRAL,
)
_LETTER: Final = r"[^\W_]"
_WORD: Final = _LETTER + "+"
_GAP: Final = r"[\W_]+"


def mentions_spoiler(review_text: str) -> bool:
    """Whether a review contains "spoiler", in any case and inside any word.

    Such a review is kept out of everything the chat reads. The test is the
    word and not the content: a reviewer who reveals plot without it is not
    caught here.

    >>> mentions_spoiler("SPOILERS AHEAD: the ending"), mentions_spoiler("no plot talk here")
    (True, False)
    """
    return "spoiler" in review_text.casefold()


def phrase_anchor(review_text: str, phrases: Sequence[str]) -> str | None:
    """The stretch of ``review_text`` that one of ``phrases`` matches, as written there.

    The search index reads a phrase as its words in order, whatever the case
    and whatever separates them, and a word is a whole word. The same
    reading is used here, so "co-op" finds "Co-Op" and "co op" and does not
    find "eco operation". Of the phrases that match, the one earliest in the
    text is returned. ``None`` when none does, which happens for a review
    the index matched on a spelling this pattern does not fold (an accented
    letter).

    >>> phrase_anchor("Great CO-OP with a friend, co op forever", ["coop", "co-op"])
    'CO-OP'
    >>> phrase_anchor("an eco operation", ["co-op"]) is None
    True
    """
    earliest: re.Match[str] | None = None
    for phrase in phrases:
        words: list[str] = re.findall(_WORD, phrase)
        if not words:
            continue
        run = _GAP.join(re.escape(word) for word in words)
        found = re.search(rf"(?<!{_LETTER}){run}(?!{_LETTER})", review_text, re.IGNORECASE)
        if found is not None and (earliest is None or found.start() < earliest.start()):
            earliest = found
    return None if earliest is None else earliest.group(0)


def term_excerpt_text(review_text: str, phrases: Sequence[str]) -> str:
    """The excerpt of a review that search matched on ``phrases``.

    The matched words are the anchor and the sentence around them is the
    excerpt, under the same rule and cap as a stored span. A review with no
    place this module can find is cut from its start to the cap.

    >>> term_excerpt_text("Loved it. The co-op is flawless! Buy it.", ["co-op"])
    'The co-op is flawless!'
    """
    anchor = phrase_anchor(review_text, phrases)
    if anchor is not None:
        return sentence_display_text(anchor, review_text)
    opening = " ".join(review_text.split())
    if len(opening) <= QUOTE_DISPLAY_CHAR_CAP:
        return opening
    kept = opening[:QUOTE_DISPLAY_CHAR_CAP]
    cut = kept.rfind(" ")
    return (kept[:cut] if cut != -1 else kept) + " …"


def seeded_draw(
    quotes: Sequence[EvidenceQuote], limit: int, seed: str
) -> tuple[EvidenceQuote, ...]:
    """At most ``limit`` of ``quotes``, in proportion to their sentiments, fixed by ``seed``.

    ``quotes`` are one aspect's labelled reviews in one game, a review
    appearing once. When there are no more than ``limit`` they are all
    returned. Otherwise the places are shared out between the sentiments by
    their counts (whole places first, then the largest remainders), and
    each sentiment's places are drawn without replacement. A sentiment held
    by few of the reviews can get no place, so a rare view is often absent
    from what is read.

    The same ``seed`` and the same quotes give the same draw on any machine
    and in any input order, so what a model read for a game and an aspect
    can be read again. The result is grouped by sentiment in a fixed order
    (positive, negative, mixed, neutral) and by review id inside one.

    Raises ``ValueError`` when ``limit`` is below one.

    >>> pool = [EvidenceQuote(f"r{n}", "story", Sentiment.POSITIVE, "x") for n in range(9)]
    >>> pool += [EvidenceQuote(f"n{n}", "story", Sentiment.NEGATIVE, "x") for n in range(3)]
    >>> drawn = seeded_draw(pool, 4, "run-1:story")
    >>> [quote.sentiment.value for quote in drawn]
    ['positive', 'positive', 'positive', 'negative']
    >>> drawn == seeded_draw(list(reversed(pool)), 4, "run-1:story")
    True
    """
    if limit < 1:
        raise ValueError(f"limit is {limit} — a draw reads at least one review")
    by_sentiment = {
        sentiment: sorted(
            (quote for quote in quotes if quote.sentiment is sentiment),
            key=lambda quote: quote.review_id,
        )
        for sentiment in _SENTIMENT_ORDER
    }
    if len(quotes) <= limit:
        return tuple(quote for pool in by_sentiment.values() for quote in pool)
    places = _shared_places({s: len(pool) for s, pool in by_sentiment.items()}, limit)
    generator = random.Random(int.from_bytes(hashlib.sha256(seed.encode()).digest()[:8], "big"))
    drawn: list[EvidenceQuote] = []
    for sentiment, pool in by_sentiment.items():
        picked = generator.sample(pool, places[sentiment])
        drawn.extend(sorted(picked, key=lambda quote: quote.review_id))
    return tuple(drawn)


def _shared_places(counts: dict[Sentiment, int], limit: int) -> dict[Sentiment, int]:
    """``limit`` places shared out in proportion to ``counts``, by largest remainder.

    Whole places first; what is left goes to the largest fractional parts,
    the fixed sentiment order settling a tie. No sentiment gets more places
    than it has reviews, since the total is above ``limit`` and each share
    is below its count.
    """
    total = sum(counts.values())
    exact = {sentiment: limit * count / total for sentiment, count in counts.items()}
    places = {sentiment: int(share) for sentiment, share in exact.items()}
    by_remainder = sorted(
        counts,
        key=lambda sentiment: (
            -(exact[sentiment] - places[sentiment]), _SENTIMENT_ORDER.index(sentiment),
        ),
    )
    for sentiment in by_remainder[: limit - sum(places.values())]:
        places[sentiment] += 1
    return places
