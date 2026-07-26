"""Behavioral claims on the CI eval fixture — round-trips, the comparison contract, export.

The load-bearing claims: a pin survives its JSON round-trip exactly;
``pinned_view`` ignores precisely the fields a legitimate regeneration changes
and nothing else; ``run_discrepancies`` names every drifted digit and forgives
only what its two disclosed relaxations forgive; fixture rows rebuilt through
the real writer surfaces read back as the exact envelopes that were exported;
and the whole loop closes — a synthetic store exports a fixture whose pins the
rebuilt store reproduces to the digit, which is the CI gate's entire premise.
"""

from __future__ import annotations

import json
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path

import pytest

from steamlens.contracts import (
    AspectMention,
    AspectSlot,
    ClassifierVersions,
    EvalMetric,
    EvalRun,
    Origin,
    Provenance,
    ReferenceKind,
    Review,
    ReviewClassification,
    Sentiment,
)
from steamlens.core.classify import PROMPT_VERSION
from steamlens.evals.agreement import agreement_pool
from steamlens.evals.certify import certify_pool
from steamlens.evals.ci_fixture import (
    AGREEMENT_PIN_FILE,
    CERTIFY_PIN_FILE,
    ENVELOPES_FILE,
    HISTORICAL_AGREEMENT,
    HISTORICAL_CERTIFY,
    MANIFEST_FILE,
    REVIEWS_FILE,
    RUNS_FILE,
    collect_envelopes,
    envelope_from_row,
    envelope_to_row,
    eval_run_from_json,
    eval_run_to_json,
    export_fixture,
    load_fixture_into,
    pinned_view,
    provenance_to_row,
    review_to_row,
    run_discrepancies,
)
from steamlens.evals.judge_dispatch import JUDGE_MODEL_ID
from steamlens.ontology import load_ontology_version
from steamlens.store import Store

_NOON = datetime(2026, 7, 23, 12, 0, tzinfo=UTC)
_STAMP = load_ontology_version(None)
# The packaged (v1) ontology drives these tests, as in the certify suite: the
# scoring shells derive the triple's ontology slot from what they load.
_PRODUCTION = ClassifierVersions(
    model_version="model-t", prompt_version="prompt-t", ontology_version=_STAMP.version
)
_JUDGE = ClassifierVersions(
    model_version=JUDGE_MODEL_ID,
    prompt_version=PROMPT_VERSION,
    ontology_version=_STAMP.version,
)


def _eval_run(
    *, config_hash: str = "cfg", extra_metrics: tuple[EvalMetric, ...] = ()
) -> EvalRun:
    return EvalRun(
        run=Provenance(
            run_id="certify-t", code_version="sha-t", created_at=_NOON, config_hash=config_hash
        ),
        versions=_PRODUCTION,
        ontology_content_hash="och",
        reference_kind=ReferenceKind.GOLD_FILE,
        reference_id="eval/gold/gold.jsonl",
        reference_sha256="a" * 64,
        n_reference_reviews=10,
        n_scored_reviews=9,
        seed=7,
        n_resamples=50,
        scorer="census-vs-gold/1",
        metrics=(
            EvalMetric(metric="f1", value=0.75, ci_low=0.7, ci_high=0.8),
            EvalMetric(metric="n_zero_mention", value=3.0),
        )
        + extra_metrics,
    )


def _review(review_id: str, app_id: int) -> Review:
    return Review(
        review_id=review_id,
        app_id=app_id,
        created_at=_NOON,
        language="english",
        text=f"review {review_id}",
        voted_up=True,
    )


def _mention(
    aspect: str, sentiment: Sentiment, *, slot: AspectSlot = AspectSlot.PINNED,
    evidence: str | None = None,
) -> AspectMention:
    return AspectMention(aspect=aspect, slot=slot, sentiment=sentiment, evidence=evidence)


def _envelope(
    review_id: str,
    versions: ClassifierVersions,
    run: Provenance,
    mentions: tuple[AspectMention, ...],
) -> ReviewClassification:
    return ReviewClassification(
        review_id=review_id,
        origin=Origin.SURVEY,
        versions=versions,
        run=run,
        mentions=mentions,
    )


def _write_lf(path: Path, lines: list[str]) -> Path:
    """Write JSONL with LF bytes regardless of platform — the export guard checks bytes."""
    path.write_bytes(("\n".join(lines) + "\n").encode("utf-8"))
    return path


def _gold_line(review_id: str, app_id: str, mentions: list[dict[str, object]]) -> str:
    return json.dumps(
        {
            "review_id": review_id,
            "app_id": app_id,
            "text": f"review {review_id}",
            "mentions": mentions,
            "instructions_version": "gold-v1",
            "ontology_version": _STAMP.version,
            "ontology_content_hash": _STAMP.content_hash,
        }
    )


def _sample_line(item: int, review_id: str, app_id: int) -> str:
    return json.dumps(
        {
            "item": item,
            "review_id": review_id,
            "app_id": app_id,
            "empty_envelope": False,
            "text_sha256": "0" * 64,
        }
    )


def test_eval_run_survives_its_json_round_trip_exactly() -> None:
    original = _eval_run()
    rehydrated = eval_run_from_json(json.loads(json.dumps(eval_run_to_json(original))))
    assert rehydrated == original


def test_pinned_view_drops_execution_identity_and_keeps_config_hash() -> None:
    view = pinned_view(_eval_run(config_hash="cfg-x"))
    assert view["run"] == {"config_hash": "cfg-x"}
    assert view["scorer"] == "census-vs-gold/1"
    assert view["seed"] == 7


def test_run_discrepancies_is_silent_on_a_faithful_regeneration() -> None:
    reference = _eval_run()
    fresh = replace(
        reference,
        run=Provenance(
            run_id="certify-later", code_version="sha-2", created_at=_NOON,
            config_hash=reference.run.config_hash,
        ),
    )
    assert run_discrepancies(reference, fresh) == ()


def test_run_discrepancies_names_a_drifted_digit() -> None:
    reference = _eval_run()
    drifted_metrics = (
        replace(reference.metrics[0], value=0.7501),
    ) + reference.metrics[1:]
    problems = run_discrepancies(reference, replace(reference, metrics=drifted_metrics))
    assert len(problems) == 1
    assert "'f1'" in problems[0]


def test_metrics_prefix_accepts_growth_but_not_reordering() -> None:
    reference = _eval_run()
    grown = replace(
        reference,
        metrics=reference.metrics + (EvalMetric(metric="f1_multi_mention", value=0.6),),
    )
    assert run_discrepancies(reference, grown, metrics_prefix=True) == ()
    assert run_discrepancies(reference, grown) != ()
    reordered = replace(reference, metrics=tuple(reversed(reference.metrics)))
    assert run_discrepancies(reference, reordered, metrics_prefix=True) != ()


def test_ignore_config_hash_forgives_that_field_only() -> None:
    reference = _eval_run(config_hash="cfg-old")
    fresh = replace(
        reference,
        run=replace(reference.run, config_hash="cfg-new"),
    )
    assert run_discrepancies(reference, fresh) != ()
    assert run_discrepancies(reference, fresh, ignore_config_hash=True) == ()
    also_drifted = replace(fresh, scorer="census-vs-gold/2")
    assert run_discrepancies(reference, also_drifted, ignore_config_hash=True) != ()


def test_fixture_rows_rebuild_the_exact_envelopes(tmp_path: Path) -> None:
    run = Provenance(
        run_id="c1-test", code_version="sha-t", created_at=_NOON, config_hash="cfg"
    )
    envelopes = (
        _envelope(
            "r1", _PRODUCTION, run,
            (
                _mention("gameplay", Sentiment.POSITIVE, evidence="fun"),
                _mention("ship bilding", Sentiment.NEGATIVE, slot=AspectSlot.CANDIDATE),
            ),
        ),
        _envelope("r2", _JUDGE, run, ()),
    )
    reviews = (_review("r1", 10), _review("r2", 10))
    _write_lf(tmp_path / REVIEWS_FILE, [json.dumps(review_to_row(r)) for r in reviews])
    _write_lf(tmp_path / RUNS_FILE, [json.dumps(provenance_to_row(run))])
    _write_lf(tmp_path / ENVELOPES_FILE, [json.dumps(envelope_to_row(e)) for e in envelopes])

    with Store(":memory:") as store:
        counts = load_fixture_into(store, tmp_path)
        assert counts == (2, 1, 2)
        for envelope in envelopes:
            assert store.labels.get(envelope.review_id, envelope.versions) == envelope
        assert store.reviews.get("r1") == reviews[0]


def test_an_envelope_referencing_an_unknown_run_is_loud() -> None:
    row = envelope_to_row(
        _envelope(
            "r1", _PRODUCTION,
            Provenance(run_id="ghost", code_version="x", created_at=_NOON, config_hash="c"),
            (),
        )
    )
    with pytest.raises(ValueError, match="ghost"):
        envelope_from_row(row, runs={})


def test_collect_envelopes_stops_loud_on_a_failure_mark() -> None:
    with Store(":memory:") as store:
        store.reviews.put_many([_review("r1", 10)])
        run = Provenance(
            run_id="c1-test", code_version="sha-t", created_at=_NOON, config_hash="cfg"
        )
        store.labels.record_run(run)
        store.labels.record_failure("r1", _PRODUCTION, "c1-test", "content filter")
        with pytest.raises(ValueError, match="failure mark"):
            collect_envelopes(store, ["r1"], _PRODUCTION)
        with pytest.raises(ValueError, match="no envelope"):
            collect_envelopes(store, ["r-absent"], _PRODUCTION)


def test_export_refuses_a_crlf_pinned_artifact(tmp_path: Path) -> None:
    crlf_gold = tmp_path / "gold.jsonl"
    crlf_gold.write_bytes(b'{"review_id": "r1"}\r\n')
    sample = _write_lf(tmp_path / "sample.jsonl", [_sample_line(1, "s1", 20)])
    with Store(":memory:") as store, pytest.raises(ValueError, match="CRLF"):
        export_fixture(
            store, tmp_path / "ci", source_db=Path(":memory:"),
            gold_path=crlf_gold, sample_path=sample, ontology_path=None,
        )


def test_export_fixture_closes_the_loop(tmp_path: Path) -> None:
    """Export from a synthetic store, rebuild from the fixture, reproduce the pins.

    This is the CI gate's whole premise exercised end to end on synthetic data:
    the rebuilt store's re-score must show zero discrepancies against the pins
    the exporter minted.
    """
    gold_path = _write_lf(
        tmp_path / "gold.jsonl",
        [
            _gold_line("r1", "10", [{"aspect": "gameplay", "sentiment": "positive"}]),
            _gold_line("r2", "10", []),
        ],
    )
    sample_path = _write_lf(
        tmp_path / "sample.jsonl",
        [_sample_line(1, "s1", 20), _sample_line(2, "s2", 20)],
    )
    with Store(":memory:") as store:
        store.reviews.put_many(
            [_review("r1", 10), _review("r2", 10), _review("s1", 20), _review("s2", 20)]
        )
        run = Provenance(
            run_id="c1-test", code_version="sha-t", created_at=_NOON, config_hash="cfg"
        )
        store.labels.record_run(run)
        for review_id, mentions in {
            "r1": (_mention("gameplay", Sentiment.POSITIVE),),
            "r2": (),
            "s1": (_mention("performance", Sentiment.NEGATIVE),),
            "s2": (),
        }.items():
            store.labels.put(_envelope(review_id, _PRODUCTION, run, mentions))
        for review_id, mentions in {
            "s1": (_mention("performance", Sentiment.NEGATIVE),),
            "s2": (_mention("gameplay", Sentiment.MIXED),),
        }.items():
            store.labels.put(_envelope(review_id, _JUDGE, run, mentions))

        # Journal the anchors as re-stamped copies of a first scoring pass —
        # the exporter inherits its dials from them, then must reproduce them.
        anchor_certify = replace(
            certify_pool(
                store, gold_path=gold_path, ontology_path=None,
                model_version=_PRODUCTION.model_version,
                prompt_version=_PRODUCTION.prompt_version, seed=7, n_resamples=50,
            ),
            run=Provenance(
                run_id=HISTORICAL_CERTIFY, code_version="sha-t", created_at=_NOON,
                config_hash="anchor-cfg-ignored",
            ),
        )
        store.eval_runs.record(anchor_certify)
        anchor_agreement = replace(
            agreement_pool(
                store, sample_path=sample_path, ontology_path=None,
                model_version=_PRODUCTION.model_version,
                prompt_version=_PRODUCTION.prompt_version, seed=7, n_resamples=50,
            ),
            run=Provenance(
                run_id=HISTORICAL_AGREEMENT, code_version="sha-t", created_at=_NOON,
                config_hash="anchor-cfg-ignored",
            ),
        )
        store.eval_runs.record(anchor_agreement)

        fixture_dir = tmp_path / "ci"
        with pytest.raises(ValueError, match="does not reproduce"):
            # The certify anchor's config hash must genuinely match — only the
            # agreement comparison forgives it, so a bogus certify hash is loud.
            export_fixture(
                store, fixture_dir, source_db=Path(":memory:"),
                gold_path=gold_path, sample_path=sample_path, ontology_path=None,
            )

    # Rebuild the store with a faithful certify anchor and export for real.
    with Store(":memory:") as store:
        store.reviews.put_many(
            [_review("r1", 10), _review("r2", 10), _review("s1", 20), _review("s2", 20)]
        )
        run = Provenance(
            run_id="c1-test", code_version="sha-t", created_at=_NOON, config_hash="cfg"
        )
        store.labels.record_run(run)
        for review_id, versions, mentions in (
            ("r1", _PRODUCTION, (_mention("gameplay", Sentiment.POSITIVE),)),
            ("r2", _PRODUCTION, ()),
            ("s1", _PRODUCTION, (_mention("performance", Sentiment.NEGATIVE),)),
            ("s2", _PRODUCTION, ()),
            ("s1", _JUDGE, (_mention("performance", Sentiment.NEGATIVE),)),
            ("s2", _JUDGE, (_mention("gameplay", Sentiment.MIXED),)),
        ):
            store.labels.put(_envelope(review_id, versions, run, mentions))
        first_certify = certify_pool(
            store, gold_path=gold_path, ontology_path=None,
            model_version=_PRODUCTION.model_version,
            prompt_version=_PRODUCTION.prompt_version, seed=7, n_resamples=50,
        )
        store.eval_runs.record(
            replace(
                first_certify,
                run=replace(first_certify.run, run_id=HISTORICAL_CERTIFY),
            )
        )
        first_agreement = agreement_pool(
            store, sample_path=sample_path, ontology_path=None,
            model_version=_PRODUCTION.model_version,
            prompt_version=_PRODUCTION.prompt_version, seed=7, n_resamples=50,
        )
        store.eval_runs.record(
            replace(
                first_agreement,
                run=replace(first_agreement.run, run_id=HISTORICAL_AGREEMENT),
            )
        )
        fixture_dir = tmp_path / "ci2"
        pin_certify, pin_agreement = export_fixture(
            store, fixture_dir, source_db=Path(":memory:"),
            gold_path=gold_path, sample_path=sample_path, ontology_path=None,
        )

    for name in (
        REVIEWS_FILE, RUNS_FILE, ENVELOPES_FILE,
        CERTIFY_PIN_FILE, AGREEMENT_PIN_FILE, MANIFEST_FILE,
    ):
        assert (fixture_dir / name).exists()
    assert eval_run_from_json(
        json.loads((fixture_dir / CERTIFY_PIN_FILE).read_text(encoding="utf-8"))
    ) == pin_certify

    with Store(":memory:") as rebuilt:
        load_fixture_into(rebuilt, fixture_dir)
        regenerated_certify = certify_pool(
            rebuilt, gold_path=gold_path, ontology_path=None,
            model_version=pin_certify.versions.model_version,
            prompt_version=pin_certify.versions.prompt_version,
            seed=pin_certify.seed, n_resamples=pin_certify.n_resamples,
        )
        regenerated_agreement = agreement_pool(
            rebuilt, sample_path=sample_path, ontology_path=None,
            model_version=pin_agreement.versions.model_version,
            prompt_version=pin_agreement.versions.prompt_version,
            seed=pin_agreement.seed, n_resamples=pin_agreement.n_resamples,
        )
    assert run_discrepancies(pin_certify, regenerated_certify) == ()
    assert run_discrepancies(pin_agreement, regenerated_agreement) == ()
