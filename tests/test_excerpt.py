"""Behavioral claims on how a review is cut down to what is read.

The sentence rule is the report page's, and its two claims came with it: a
line is a sentence, and a wall of text is windowed. The rest is what the chat
adds: the words a search matched are found the way the index matched them; a
review containing "spoiler" is recognised whatever the case; and the draw
over an aspect's labelled reviews keeps the sentiments in proportion and is
the same every time for the same seed.
"""

from __future__ import annotations

import pytest

from steamlens.contracts import EvidenceQuote, Sentiment
from steamlens.core.excerpt import (
    LABELLED_READ_FLOOR,
    QUOTE_DISPLAY_CHAR_CAP,
    mentions_spoiler,
    phrase_anchor,
    seeded_draw,
    sentence_display_text,
    term_excerpt_text,
)
from steamlens.serve.web.view import ASPECT_EVIDENCE_FLOOR


def test_sentence_expansion_breaks_on_newlines_and_keeps_terminal_marks() -> None:
    """Steam reviews often separate thoughts with bare newlines — a line is a
    sentence for display, and terminal punctuation stays with its sentence."""
    text = "story is great\nthe grind killed it for me\n10/10 anyway"
    assert (
        sentence_display_text("grind killed", text) == "the grind killed it for me"
    )


def test_sentence_expansion_caps_punctuation_poor_walls() -> None:
    """A review with no terminal punctuation must not expand a two-word span
    into the whole text: past the cap the display trims to a word-boundary
    window around the span, ellipses marking the trims openly."""
    wall = " ".join(f"word{i}" for i in range(120)) + " the span here " + " ".join(
        f"tail{i}" for i in range(120)
    )
    shown = sentence_display_text("span here", wall)
    assert len(shown) <= QUOTE_DISPLAY_CHAR_CAP + len("…  …")
    assert "span here" in shown
    assert shown.startswith("… ")
    assert shown.endswith(" …")


def test_a_span_the_review_no_longer_holds_is_shown_as_stored() -> None:
    assert sentence_display_text("tight combat", "A different text entirely.") == "tight combat"
    assert sentence_display_text("tight combat", None) == "tight combat"


# --- the words a search matched ------------------------------------------------


@pytest.mark.parametrize(
    ("text", "phrases", "anchor"),
    [
        ("The Co-Op mode is great", ["co-op"], "Co-Op"),
        ("played coop all night", ["co-op", "coop"], "coop"),
        ("a rogue   like with heart", ["rogue like"], "rogue   like"),
        ("First the timer, then co-op", ["co-op", "timer"], "timer"),
        ("an eco operation", ["co-op"], None),
        ("the mission timers", ["timer"], None),
        ("nothing here", ["!!"], None),
    ],
)
def test_the_anchor_is_the_matched_words_as_the_review_wrote_them(
    text: str, phrases: list[str], anchor: str | None
) -> None:
    """Words in order, any case, anything between them, and whole words only,
    which is how the index matched the review. With several phrases the one
    earliest in the text is the anchor."""
    assert phrase_anchor(text, phrases) == anchor


def test_a_search_match_is_cut_to_the_sentence_around_the_matched_words() -> None:
    text = "Bought it on sale. The co-op campaign is the best part! Runs fine."
    assert term_excerpt_text(text, ["co-op"]) == "The co-op campaign is the best part!"


def test_a_match_this_module_cannot_place_is_cut_from_the_reviews_start() -> None:
    """The index folds accents and this pattern does not, so a review can be
    a match with no place to grow a sentence from. It is still read, from its
    opening, under the same cap."""
    short = "Pokémon   vibes\nall the way"
    assert term_excerpt_text(short, ["pokemon"]) == "Pokémon vibes all the way"
    wall = "Pokémon " + " ".join(f"word{i}" for i in range(200))
    shown = term_excerpt_text(wall, ["pokemon"])
    assert shown.startswith("Pokémon word0 ") and shown.endswith(" …")
    assert len(shown) <= QUOTE_DISPLAY_CHAR_CAP + len(" …")


# --- the spoiler test ------------------------------------------------------------


def test_a_review_containing_spoiler_is_recognised_in_any_case_and_form() -> None:
    assert mentions_spoiler("Spoiler: he dies")
    assert mentions_spoiler("no SPOILERS, promise")
    assert mentions_spoiler("the spoilerific ending")
    assert not mentions_spoiler("the story spoils nothing early on")


# --- the draw over an aspect's labelled reviews ----------------------------------


def _quotes(positive: int, negative: int, mixed: int = 0) -> list[EvidenceQuote]:
    counts = ((Sentiment.POSITIVE, positive), (Sentiment.NEGATIVE, negative),
              (Sentiment.MIXED, mixed))
    return [
        EvidenceQuote(f"{sentiment.value}-{n:03}", "story", sentiment, "a span")
        for sentiment, count in counts
        for n in range(count)
    ]


def _shape(drawn: tuple[EvidenceQuote, ...]) -> dict[str, int]:
    shape: dict[str, int] = {}
    for quote in drawn:
        shape[quote.sentiment.value] = shape.get(quote.sentiment.value, 0) + 1
    return shape


def test_the_draw_keeps_the_sentiments_in_proportion() -> None:
    """Forty praising and twenty criticising at six places is four and two.
    Fifty, nine and one is five and one: the lone mixed review has the
    smallest share and gets no place."""
    assert _shape(seeded_draw(_quotes(40, 20), 6, "run:story")) == {"positive": 4, "negative": 2}
    assert _shape(seeded_draw(_quotes(50, 9, 1), 6, "run:story")) == {
        "positive": 5, "negative": 1,
    }


def test_the_same_seed_gives_the_same_draw_whatever_the_input_order() -> None:
    """A reply has to be regenerable from its inputs, and the labels arrive
    from the store in no promised order."""
    pool = _quotes(40, 20)
    first = seeded_draw(pool, 6, "serve-1:story")
    assert first == seeded_draw(list(reversed(pool)), 6, "serve-1:story")
    assert first != seeded_draw(pool, 6, "serve-2:story")
    assert len({quote.review_id for quote in first}) == 6


def test_a_pool_no_larger_than_the_limit_is_read_whole() -> None:
    pool = _quotes(3, 2)
    assert set(seeded_draw(pool, 6, "run:story")) == set(pool)
    assert seeded_draw([], 6, "run:story") == ()
    with pytest.raises(ValueError, match="at least one review"):
        seeded_draw(pool, 0, "run:story")


def test_the_chat_reads_no_aspect_the_report_page_would_not_show() -> None:
    """The floor is the page's, held in two modules because the chat may not
    import the serving shell. They have to move together."""
    assert LABELLED_READ_FLOOR == ASPECT_EVIDENCE_FLOOR
