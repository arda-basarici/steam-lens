"""Behavioral claims on the holdout scorer — the strict binary, routing, the gate.

The load-bearing claims: the human sheet takes the reference role and the
strict envelope binary never credits a partial or crashed read; each stratum's
predictions come from its own store (corpus vs the fresh-buy's contained
pool); the sheet gate collects every finding into one stop instead of raising
piecemeal; SKIPs narrow ``n_scored`` with the drop disclosed; and the minted
record journals as a ``gold-file`` run pinning the sheet's bytes, with a
bootstrap dial of 0/0 meaning "Wilson only, none ran".
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from steamlens.contracts import (
    AspectMention,
    AspectSlot,
    ClassifierVersions,
    Origin,
    Provenance,
    ReferenceKind,
    Review,
    ReviewClassification,
    Sentiment,
)
from steamlens.core.intervals import wilson_interval
from steamlens.core.normalize import build_surface_index
from steamlens.evals.holdout import (
    HOLDOUT_SCORER,
    HoldoutRow,
    ScoredReview,
    agrees,
    holdout_metrics,
    holdout_tallies,
    score_holdout,
    sheet_reference,
)
from steamlens.evals.scoring import ReviewTally, tally_review
from steamlens.ontology import load_ontology, load_ontology_version
from steamlens.store import Store

_NOON = datetime(2026, 8, 4, 12, 0, tzinfo=UTC)
_STAMP = load_ontology_version(None)
_PRODUCTION = ClassifierVersions(
    model_version="model-t", prompt_version="prompt-t", ontology_version=_STAMP.version
)
_INDEX = build_surface_index(load_ontology(None))


def _mention(aspect: str, sentiment: Sentiment) -> AspectMention:
    return AspectMention(
        aspect=aspect, slot=AspectSlot.PINNED, sentiment=sentiment, evidence=None
    )


def _store(
    review_ids: list[str],
    production: dict[str, tuple[AspectMention, ...]],
    *,
    failures: tuple[str, ...] = (),
) -> Store:
    store = Store(":memory:")
    store.reviews.put_many(
        Review(
            review_id=rid,
            app_id=10,
            created_at=_NOON,
            language="english",
            text=f"review {rid}",
            voted_up=True,
        )
        for rid in review_ids
    )
    run = Provenance(
        run_id="holdout-test", code_version="testsha", created_at=_NOON, config_hash="cfg"
    )
    store.labels.record_run(run)
    for rid, mentions in production.items():
        store.labels.put(
            ReviewClassification(
                review_id=rid,
                origin=Origin.SURVEY,
                versions=_PRODUCTION,
                run=run,
                mentions=mentions,
            )
        )
    for rid in failures:
        store.labels.record_failure(rid, _PRODUCTION, run.run_id, "malformed")
    return store


def _tally(gold: list[tuple[str, Sentiment]], pred: list[tuple[str, Sentiment]],
           *, parse_failed: bool = False) -> ReviewTally:
    return tally_review(gold, pred, _INDEX, parse_failed=parse_failed)


GP = ("gameplay", Sentiment.POSITIVE)
PN = ("performance", Sentiment.NEGATIVE)


def test_agrees_is_the_strict_envelope_match() -> None:
    assert agrees(_tally([GP, PN], [GP, PN]))
    assert agrees(_tally([], []))  # both-zero is genuine agreement
    assert not agrees(_tally([GP], [GP, PN]))  # prediction-only aspect
    assert not agrees(_tally([GP, PN], [GP]))  # reference-only aspect
    assert not agrees(_tally([GP], [("gameplay", Sentiment.NEGATIVE)]))  # sentiment flip
    assert not agrees(_tally([], [], parse_failed=True))  # a crash is not a zero


def test_candidates_stay_out_of_the_binary() -> None:
    # a candidate emission on either side is unscored, so it cannot break agreement
    assert agrees(_tally([GP, ("some novel thing", Sentiment.POSITIVE)], [GP]))
    assert agrees(_tally([GP], [GP, ("another novel thing", Sentiment.NEGATIVE)]))


def _sample() -> tuple[HoldoutRow, ...]:
    return (
        HoldoutRow(1, "c1", 10, "corpus", "text c1"),
        HoldoutRow(2, "m1", 20, "marked-window", "text m1"),
        HoldoutRow(3, "l1", 30, "long-tail", "text l1"),
    )


def test_tallies_route_each_stratum_to_its_store() -> None:
    corpus = _store(["c1"], {"c1": (_mention("gameplay", Sentiment.POSITIVE),)})
    fresh = _store(["m1", "l1"], {"m1": (_mention("performance", Sentiment.NEGATIVE),)},
                   failures=("l1",))
    stores = {"corpus": corpus, "marked-window": fresh, "long-tail": fresh}
    reference = {"c1": (GP,), "m1": (PN,), "l1": (GP,)}
    scored = holdout_tallies(stores, _sample(), reference, _INDEX, _PRODUCTION)
    by_id = {s.review_id: s for s in scored}
    assert agrees(by_id["c1"].tally) and agrees(by_id["m1"].tally)
    assert by_id["l1"].tally.parse_failed  # the failure mark scores as a parse failure
    assert [s.stratum for s in scored] == ["corpus", "marked-window", "long-tail"]


def test_tallies_skip_unreferenced_reviews_and_raise_on_silence() -> None:
    corpus = _store(["c1"], {"c1": ()})
    fresh = _store(["m1", "l1"], {})  # m1/l1 have neither envelope nor mark
    stores = {"corpus": corpus, "marked-window": fresh, "long-tail": fresh}
    scored = holdout_tallies(stores, _sample(), {"c1": ()}, _INDEX, _PRODUCTION)
    assert [s.review_id for s in scored] == ["c1"]  # m1/l1 SKIPped -> not consulted
    with pytest.raises(ValueError, match="neither an envelope nor a failure mark"):
        holdout_tallies(stores, _sample(), {"c1": (), "m1": (PN,)}, _INDEX, _PRODUCTION)


def test_metrics_carry_wilson_on_headline_and_strata_only() -> None:
    scored = tuple(
        ScoredReview(f"r{i}", stratum, _tally([GP], [GP] if hit else [PN]))
        for i, (stratum, hit) in enumerate(
            [("corpus", True), ("corpus", False), ("marked-window", True), ("long-tail", True)]
        )
    )
    rows = {m.metric: m for m in holdout_metrics(scored)}
    headline = rows["holdout_agreement"]
    assert headline.value == 0.75
    expected = wilson_interval(3, 4)
    assert (headline.ci_low, headline.ci_high) == (expected.low, expected.high)
    assert rows["holdout_n/corpus"].value == 2.0
    assert rows["holdout_agreement/corpus"].value == 0.5
    assert rows["holdout_agreement/corpus"].ci_low is not None
    assert rows["holdout_aspect_set_match"].value == 0.75  # the PN miss fails aspect too
    assert rows["holdout_sentiment_given_aspect_match"].value == 1.0
    assert rows["holdout_aspect_set_match"].ci_low is None  # disclosure, not a claim
    assert rows["parse_failure_rate"].value == 0.0


def test_sentiment_component_is_omitted_when_undefined() -> None:
    scored = (ScoredReview("r0", "corpus", _tally([GP], [PN])),)
    rows = {m.metric: m for m in holdout_metrics(scored)}
    assert rows["holdout_n_aspect_set_match"].value == 0.0
    assert "holdout_sentiment_given_aspect_match" not in rows


_SHEET_OK = """# Fresh human holdout — labeling sheet

---

## 1 · review c1

- [x] reviewed

```text
text c1
```

- gameplay / positive / "text c1"

## 2 · review m1

- [x] reviewed

```text
text m1
```

Zero mentions.

## 3 · review l1

- [x] reviewed

```text
text l1
```

SKIP: non_english
"""


def _write_draw(tmp_path: Path, sheet: str) -> tuple[Path, Path]:
    sample_path = tmp_path / "sample.jsonl"
    sample_path.write_text(
        "\n".join(
            json.dumps(
                {"position": r.position, "review_id": r.review_id, "app_id": r.app_id,
                 "stratum": r.stratum, "text": r.text}
            )
            for r in _sample()
        )
        + "\n",
        encoding="utf-8",
    )
    sheet_path = tmp_path / "SHEET.md"
    sheet_path.write_text(sheet, encoding="utf-8")
    return sample_path, sheet_path


def test_sheet_gate_collects_every_finding_into_one_stop(tmp_path: Path) -> None:
    broken = _SHEET_OK.replace("- [x] reviewed\n\n```text\ntext m1",
                               "- [ ] reviewed\n\n```text\ntext m1")
    broken = broken.replace('"text c1"', '"drifted span"')
    _, sheet_path = _write_draw(tmp_path, broken)
    with pytest.raises(ValueError) as excinfo:
        sheet_reference(sheet_path, _sample())
    message = str(excinfo.value)
    assert "2 finding(s)" in message
    assert "not a verbatim substring" in message and "unreviewed" in message


def test_score_holdout_journals_the_sheet_pinned_run(tmp_path: Path) -> None:
    sample_path, sheet_path = _write_draw(tmp_path, _SHEET_OK)
    corpus = _store(["c1"], {"c1": (_mention("gameplay", Sentiment.POSITIVE),)})
    fresh = _store(["m1", "l1"], {"m1": ()})
    eval_run = score_holdout(
        corpus,
        fresh,
        sample_path=sample_path,
        sheet_path=sheet_path,
        ontology_path=None,
        model_version="model-t",
        prompt_version="prompt-t",
        freshbuy_run="freshbuy-test",
        started=_NOON,
    )
    assert eval_run.scorer == HOLDOUT_SCORER
    assert eval_run.reference_kind is ReferenceKind.GOLD_FILE
    assert eval_run.reference_id == sheet_path.as_posix()
    assert (eval_run.n_reference_reviews, eval_run.n_scored_reviews) == (3, 2)  # l1 SKIPped
    assert (eval_run.seed, eval_run.n_resamples) == (0, 0)  # Wilson only, no bootstrap
    rows = {m.metric: m for m in eval_run.metrics}
    assert rows["holdout_agreement"].value == 1.0
    assert "holdout_agreement/long-tail" not in rows  # the stratum SKIPped away entirely
    corpus.eval_runs.record(eval_run)
    assert corpus.eval_runs.get(eval_run.run.run_id) == eval_run
