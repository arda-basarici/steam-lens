"""The D2d registered-experiments dispatch — the census's model under controlled conditions.

Certification measured a real census-vs-lab gap (paired ΔF1 −0.033) with
batch composition as the registered prime suspect; this driver buys the
isolation evidence. Each *cell* re-labels a fixed review scope with the
census's model under one controlled condition — codebook render (full |
compact) × batch size (N=1 | N=10) — so the existing scorers can read the
batch effect and the codebook interaction off the same reviews. The ruled
cells, their decision rules, and the contingent follow-up are DESIGN's D2d
registered-experiments entry (2026-07-25); the registered readings live in
``probes/d2d_reads.py``.

Cell envelopes land in the label pool, but their ``model_version`` key
carries the batch condition — ``deepseek-v4-flash@n1`` — while the wire
request uses the real model id (the manifest records both). That tag is the
ruled cell-identity seam: the versions triple names the annotator whose
labels these are, and the experiment's premise is that batch condition
measurably changes the annotator — two label sets expected to differ must
not share an identity key (three of the four cells would otherwise collide,
full-N=1 with the census itself). Containment follows: production's folds
and certification filter on the untagged triple, so cell labels can never
leak into a displayed number.

The retry policy is condition-pure: a failed row in a flat N=10 cell
re-batches once at exactly N — a sub-N remainder takes durable marks
instead of dispatching the off-size request an N=10 label must never come
from, and the manifest lists every dispatched rebatch size so the purity is
auditable, not asserted. Never the census driver's N=1 isolate pass, which
would smuggle the other condition's labels into the cell. N=1 cells mark on
first failure (the judge precedent: a temperature-0 retry replays the
identical cached response). The recomposed cell is single-attempt for the
same reason seen from the other side: its condition IS the batch
composition, and a re-chunked retry would dispatch batches that are not
one-gold-among-nine-fresh-fillers under the very triple that promises they
are. A refused batch's
innocent-neighbor cost is accepted eyes-open: every text this driver
dispatches was already labeled cleanly by this very model at census scale,
so refusals are ~absent by construction and a run hitting the breaker means
a systemic request problem, never this much toxic text.

Lives in ``evals`` (not ``studies``) because the gold scope consumes the
gold artifact and nothing may import ``evals`` — the import law forces the
arrow, same as the judge shells.
"""

from __future__ import annotations

import argparse
import hashlib
import os
import random
import traceback
from collections.abc import Callable, Mapping, Sequence
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Final, Literal

from steamlens.contracts import (
    AspectOntology,
    ClassifierVersions,
    LlmRequest,
    LlmStage,
    Origin,
    Provenance,
    Review,
    ReviewClassification,
    Sink,
    StageKind,
    TokenUsage,
)
from steamlens.core.classify import (
    COMPACT_PROMPT_VERSION,
    PROMPT_VERSION,
    BatchParseResult,
    IdxFailure,
    build_classify_prompt,
    build_classify_prompt_compact,
    parse_classify_response,
)
from steamlens.core.normalize import build_surface_index
from steamlens.corpus import EXCLUDED_APP_IDS
from steamlens.dispatch import (
    BatchOutcome,
    DriftWatch,
    RunAbort,
    RunTotals,
    chunk,
    code_version,
    config_hash,
    mint_run_id,
    narrate,
    run_context,
    run_pass,
    write_manifest,
)
from steamlens.dispatch.census_arm import KEY_ENV, MODEL_ID, build_client
from steamlens.evals.gold import load_gold
from steamlens.evals.judge_gold import assert_gold_text_matches_pool
from steamlens.evals.judge_sample import load_sample, stored_reviews_matching_pins
from steamlens.llm_client import (
    AtCapacityError,
    GenerationIncompleteError,
    LlmClient,
    LlmUnavailableError,
    ProviderEntry,
    ProviderPermanentError,
    openai_compat_entry,
)
from steamlens.llm_client.openai_compat import DEEPSEEK_BASE_URL
from steamlens.ontology import load_ontology, load_ontology_version
from steamlens.store import Store

# The judge's scale of breaker, not the census's: cell runs are ≤ ~1,250
# requests over texts that all cleared DeepSeek's filter at the census
# (~1 refusal per 10K requests there), so a handful means systemic trouble.
REFUSED_LIMIT: Final = 5

_STAGE: Final = "d2d.driver"

Scope = Literal["sample", "gold", "gold-recomposed"]

DEFAULT_FILLERS_SEED: Final = 20260725
"""The registered composition seed — reproducibility-critical (it determines
batch composition and rides the config hash), so the dataclass default and
the CLI default both read this one constant."""

FILLERS_PER_GOLD: Final = 9
"""The recomposed cell's batch arithmetic: one gold review + nine fresh census
neighbors = the census's N=10. Fillers draw same-game by preference — a
premise measured FALSE after the buy (2026-07-27, the full-base review): the
census's ``ORDER BY review_id`` batches gave a review a mean 1.08 same-game
neighbors of 9 (~12%), not the overwhelmingly-same-game neighborhoods this
draw assumed, so the cell holds N and freshness constant while *installing*
an all-same-game neighbor structure the census never had. The composition
stays as registered — the run is bought and its null read stands as bought —
but any recomposed-vs-census interpretation carries that structure change as
a named confound (DESIGN's D2d executed entry, the corrected residue)."""


@dataclass(frozen=True, slots=True)
class ExperimentCell:
    """One registered condition: codebook render × batch size × review scope.

    ``prompt_version`` selects the render *and* rides the envelope key
    unchanged (the two renders are distinct annotation contracts with their
    own content pins); ``batch_size`` is the controlled condition and reaches
    the key only through the annotator tag (see ``annotator_model_version``).
    """

    name: str
    prompt_version: str
    batch_size: int
    scope: Scope


CELLS: Final[Mapping[str, ExperimentCell]] = {
    cell.name: cell
    for cell in (
        ExperimentCell("full-n1-gold", PROMPT_VERSION, 1, "gold"),
        ExperimentCell("full-n1-sample", PROMPT_VERSION, 1, "sample"),
        ExperimentCell("compact-n10-sample", COMPACT_PROMPT_VERSION, 10, "sample"),
        ExperimentCell("compact-n1-sample", COMPACT_PROMPT_VERSION, 1, "sample"),
        ExperimentCell("full-n10-gold-recomposed", PROMPT_VERSION, 10, "gold-recomposed"),
    )
}
"""The closed cell registry — the registration, in code.

``full-n1-gold`` is the contamination arm's gold-referenced recovery read
(the in-scope gold reviews, solo); ``full-n1-sample`` its judge-referenced
read at census scale; the two compact cells complete the codebook × batch
2×2 on the same sample. The fourth 2×2 cell — full × N=10 — is production's
census labels, already bought. ``full-n10-gold-recomposed`` is the
contingent lab-recomposition rerun, registered in DESIGN with its trigger
and built 2026-07-25 when the trigger fired (the gold read's ΔF1 failed to
exclude zero upward): each in-scope gold review re-labeled *today* embedded
among fresh census neighbors, separating provider drift from batch
composition on the acquittal branch. Free dials are deliberately absent —
an unregistered condition should not be one typo away.
"""


def annotator_model_version(batch_size: int) -> str:
    """The cell's pool identity: the wire model id tagged with its batch condition."""
    return f"{MODEL_ID}@n{batch_size}"


def cell_versions(cell: ExperimentCell, ontology_version: str) -> ClassifierVersions:
    """The versions triple a cell's envelopes and failure marks land under."""
    return ClassifierVersions(
        model_version=annotator_model_version(cell.batch_size),
        prompt_version=cell.prompt_version,
        ontology_version=ontology_version,
    )


def cell_prompt_builder(
    cell: ExperimentCell,
) -> Callable[[Sequence[str], AspectOntology], str]:
    """The render matching the cell's prompt-version pin — never mixed by construction."""
    if cell.prompt_version == COMPACT_PROMPT_VERSION:
        return build_classify_prompt_compact
    return build_classify_prompt


@dataclass(frozen=True, slots=True)
class ExperimentRunConfig:
    """One cell-dispatch invocation's resolved dial.

    ``ontology_path`` is required and explicit for the same reason as the
    judge shells': every cell must annotate under the census's v2 artifact,
    pinned by path — an accidental fall-through to packaged v1 would mint a
    whole envelope set under the wrong contract. ``limit`` is the pilot dial
    (reviews for the flat scopes, batches for the recomposed one); the
    unused scope's path is simply never read. ``fillers_seed`` drives the
    recomposed scope's filler draw and rides the config hash — composition
    must be regenerable, and a resume must re-form the same batches.
    """

    cell: ExperimentCell
    sample_path: Path
    gold_path: Path
    db_path: Path
    runs_dir: Path
    ontology_path: Path
    max_workers: int
    budget_usd: float
    limit: int | None
    fillers_seed: int = DEFAULT_FILLERS_SEED


def scope_reviews(
    cfg: ExperimentRunConfig, store: Store
) -> tuple[tuple[Review, ...], dict[str, object]]:
    """The cell's review rows in scope order, plus the manifest's scope descriptor.

    Both scopes prompt from *stored* text — condition parity with production,
    which read exactly these rows — after their own identity handshake: the
    sample's sha256 pin against the store, gold's strip-equality check. The
    gold scope is the in-scope slice only (``EXCLUDED_APP_IDS`` dropped):
    those reviews are the census-condition comparison set, and an
    out-of-scope row has no census-condition counterpart to pair with.
    """
    if cfg.cell.scope == "sample":
        sample = load_sample(cfg.sample_path)
        stored = stored_reviews_matching_pins(sample, store)
        return (
            tuple(stored[record.review_id] for record in sample),
            {
                "scope": "sample",
                "sample_path": cfg.sample_path.as_posix(),
                "sample_sha256": hashlib.sha256(cfg.sample_path.read_bytes()).hexdigest(),
            },
        )
    return (
        _in_scope_gold_rows(cfg.gold_path, store),
        {
            "scope": "gold",
            "gold_path": cfg.gold_path.as_posix(),
            "gold_sha256": hashlib.sha256(cfg.gold_path.read_bytes()).hexdigest(),
            "excluded_app_ids": sorted(EXCLUDED_APP_IDS),
        },
    )


def _in_scope_gold_rows(gold_path: Path, store: Store) -> tuple[Review, ...]:
    """The in-scope gold reviews' stored rows, gold-file order, handshaken."""
    in_scope = tuple(
        record for record in load_gold(gold_path) if record.app_id not in EXCLUDED_APP_IDS
    )
    assert_gold_text_matches_pool(in_scope, store)
    rows: list[Review] = []
    for record in in_scope:
        stored_row = store.reviews.get(record.review_id)
        if stored_row is None:  # unreachable: the handshake above already aborted
            raise RunAbort(f"gold review {record.review_id} vanished mid-run")
        rows.append(stored_row)
    return tuple(rows)


def recomposed_batches(
    cfg: ExperimentRunConfig, store: Store
) -> tuple[tuple[tuple[Review, ...], ...], frozenset[str], dict[str, object]]:
    """Each in-scope gold review embedded among fresh census neighbors at N=10.

    Returns ``(batches, gold_ids, descriptor)`` — one batch per gold review,
    its position seeded within nine fillers. Composition draws only from
    stable inputs (the gold file's order, the reviews table's id→app map,
    ``fillers_seed``), so a resume re-forms identical batches and
    already-bought responses replay from the content-keyed cache. Fillers
    prefer the gold review's own game (a premise since measured false — the
    census's real batches were ~12% same-game; see ``FILLERS_PER_GOLD``)
    and are never reused across batches; a game too small to
    supply its gold tops up from the remaining corpus, seeded, with the
    crossover count disclosed in the descriptor. Raises ``RunAbort`` when
    the corpus cannot supply enough distinct fillers at all.
    """
    gold_rows = _in_scope_gold_rows(cfg.gold_path, store)
    gold_ids = frozenset(row.review_id for row in gold_rows)
    excluded = set(EXCLUDED_APP_IDS)
    by_app: dict[int, list[str]] = {}
    for review_id, app_id in store.reviews.app_id_by_review().items():
        if app_id not in excluded and review_id not in gold_ids:
            by_app.setdefault(app_id, []).append(review_id)
    for candidates in by_app.values():
        candidates.sort()

    rng = random.Random(cfg.fillers_seed)
    chosen: dict[str, list[str]] = {}
    deficits: list[tuple[str, int]] = []
    for row in gold_rows:
        candidates = by_app.get(row.app_id, [])
        take = min(FILLERS_PER_GOLD, len(candidates))
        picked = rng.sample(candidates, take)
        for review_id in picked:
            candidates.remove(review_id)
        chosen[row.review_id] = picked
        if take < FILLERS_PER_GOLD:
            deficits.append((row.review_id, FILLERS_PER_GOLD - take))
    topup_pool = sorted(rid for candidates in by_app.values() for rid in candidates)
    n_topup = 0
    for gold_id, deficit in deficits:
        if deficit > len(topup_pool):
            raise RunAbort(
                f"the corpus cannot supply {FILLERS_PER_GOLD} distinct fillers per gold "
                f"review — short {deficit - len(topup_pool)} at {gold_id}"
            )
        extra = rng.sample(topup_pool, deficit)
        for review_id in extra:
            topup_pool.remove(review_id)
        chosen[gold_id].extend(extra)
        n_topup += deficit

    batches: list[tuple[Review, ...]] = []
    for row in gold_rows:
        members: list[Review] = []
        for filler_id in chosen[row.review_id]:
            filler = store.reviews.get(filler_id)
            if filler is None:  # unreachable: ids came from the reviews table
                raise RunAbort(f"filler review {filler_id} vanished mid-run")
            members.append(filler)
        members.insert(rng.randrange(len(members) + 1), row)
        batches.append(tuple(members))
    descriptor: dict[str, object] = {
        "scope": "gold-recomposed",
        "gold_path": cfg.gold_path.as_posix(),
        "gold_sha256": hashlib.sha256(cfg.gold_path.read_bytes()).hexdigest(),
        "excluded_app_ids": sorted(EXCLUDED_APP_IDS),
        "fillers_seed": cfg.fillers_seed,
        "fillers_per_gold": FILLERS_PER_GOLD,
        "n_topup_cross_game": n_topup,
    }
    return tuple(batches), gold_ids, descriptor


def pending_recomposed_batches(
    batches: Sequence[tuple[Review, ...]],
    gold_ids: frozenset[str],
    store: Store,
    versions: ClassifierVersions,
) -> tuple[tuple[Review, ...], ...]:
    """The batches whose *gold* member is still unsettled — the resume unit.

    Fillers never drive selection: they are condition scenery, bought as a
    byproduct, and a settled filler inside a re-formed batch is skipped at
    write time (disclosed) rather than re-selected here.
    """
    def gold_unsettled(batch: tuple[Review, ...]) -> bool:
        for review in batch:
            if review.review_id in gold_ids:
                return (
                    store.labels.get(review.review_id, versions) is None
                    and store.labels.get_failure(review.review_id, versions) is None
                )
        raise RunAbort("a recomposed batch carries no gold member — composition bug")

    return tuple(batch for batch in batches if gold_unsettled(batch))


def pending_reviews(
    reviews: Sequence[Review], store: Store, versions: ClassifierVersions
) -> tuple[Review, ...]:
    """The scope's reviews still owed an envelope under the cell's triple — resume-clean.

    Same closure contract as every sibling driver: an envelope or a durable
    failure mark settles a review. Batch composition is deterministic over
    the remaining set in scope order, so a relaunch re-forms identical
    batches and the content-keyed cache makes already-bought responses free.
    """
    return tuple(
        review
        for review in reviews
        if store.labels.get(review.review_id, versions) is None
        and store.labels.get_failure(review.review_id, versions) is None
    )


def classify_cell_batch(
    client: LlmClient,
    ontology: AspectOntology,
    surface_index: Mapping[str, str],
    batch: tuple[Review, ...],
    build_prompt: Callable[[Sequence[str], AspectOntology], str],
) -> BatchOutcome:
    """One batch through the cell's prompt → door → parse; the worker-side unit.

    The census worker's semantics under an injected prompt render: a
    truncated generation is salvaged (its spend is already journaled and
    cached), and a provider-rejected request becomes an all-rows-failed
    outcome so the retry policy — not the whole run — absorbs it. Provider
    trouble outliving the client's retries and budget refusals propagate and
    end the run.
    """
    texts = [review.text for review in batch]
    prompt = build_prompt(texts, ontology)
    try:
        response = client.complete(LlmRequest(stage=LlmStage.CLASSIFY, prompt=prompt))
        finish = response.finish_reason.value
    except GenerationIncompleteError as exc:
        response = exc.response
        finish = f"incomplete:{exc.reason.value}"
    except ProviderPermanentError as exc:
        reason = f"provider refused the request: {exc}"
        return BatchOutcome(
            batch=batch,
            parse=BatchParseResult(
                parsed=(),
                failures=tuple(IdxFailure(idx, reason) for idx in range(len(batch))),
                repairs=(),
            ),
            model_version="",
            finish="refused",
            usage=TokenUsage(prompt_tokens=0, output_tokens=0, thinking_tokens=0),
            refusal=str(exc),
        )
    return BatchOutcome(
        batch=batch,
        parse=parse_classify_response(response.text, texts, surface_index),
        model_version=response.model_version,
        finish=finish,
        usage=response.usage,
    )


@dataclass(slots=True)
class ExperimentTotals(RunTotals):
    """The census counters plus the recomposed scope's disclosed skip.

    ``skipped_settled`` counts writes skipped because the member was already
    settled under the cell's triple — legitimate only for recomposed batches
    re-formed across a resume (fillers don't drive selection), disclosed in
    the manifest rather than silently absorbed. ``rebatch_sizes`` lists every
    dispatched rebatch request's size so a run record proves — not asserts —
    that no label was bought at an off-size N.
    """

    skipped_settled: int = 0
    rebatch_sizes: list[int] = field(default_factory=list[int])


def _write_outcome(
    outcome: BatchOutcome,
    store: Store,
    versions: ClassifierVersions,
    run: Provenance,
    final: bool,
    totals: ExperimentTotals,
    drift: DriftWatch,
    sink: Sink,
    *,
    skip_settled: bool,
) -> list[Review]:
    """Consume one outcome on the main thread: envelopes in, failures forward.

    Returns the batch members owed the rebatch attempt; on a ``final``
    attempt nothing is returned — remaining failures take their durable
    marks, closing selection under the cell's triple. There is deliberately
    no isolate stage behind this (the module docstring's condition-purity
    rule). A provider-refused outcome skips the drift watch (nothing served
    the call) and counts toward the refusal circuit breaker. With
    ``skip_settled`` (the recomposed scope), a member already settled under
    the triple is counted and skipped instead of failing the duplicate-write
    guard — a re-formed batch legitimately contains settled fillers.
    """
    if outcome.refusal is not None:
        totals.refused_batches += 1
        narrate(
            sink, _STAGE, StageKind.WARN,
            f"provider refused a batch ({len(outcome.batch)} reviews): {outcome.refusal}",
        )
        if totals.refused_batches > REFUSED_LIMIT:
            raise RunAbort(
                f"{totals.refused_batches} provider refusals exceeds the "
                f"{REFUSED_LIMIT}-request circuit breaker — these texts labeled cleanly "
                f"at census scale, so suspect a systemic request problem"
            )
    else:
        drift.check(outcome.model_version)
        totals.model_versions_seen.add(outcome.model_version)
    totals.batches += 1
    totals.prompt_tokens += outcome.usage.prompt_tokens
    totals.output_tokens += outcome.usage.output_tokens
    totals.thinking_tokens += outcome.usage.thinking_tokens
    totals.repairs += len(outcome.parse.repairs)
    def settled(review: Review) -> bool:
        return (
            store.labels.get(review.review_id, versions) is not None
            or store.labels.get_failure(review.review_id, versions) is not None
        )

    had_failures = bool(outcome.parse.failures)
    for parsed in outcome.parse.parsed:
        review = outcome.batch[parsed.idx]
        if skip_settled and settled(review):
            totals.skipped_settled += 1
            continue
        store.labels.put(
            ReviewClassification(
                review_id=review.review_id,
                origin=Origin.SURVEY,
                versions=versions,
                run=run,
                mentions=parsed.mentions,
            )
        )
        totals.labeled += 1
        if not parsed.mentions:
            totals.empty_envelopes += 1
        if had_failures:
            totals.salvaged += 1
    retry: list[Review] = []
    for failure in outcome.parse.failures:
        if failure.idx is None or not 0 <= failure.idx < len(outcome.batch):
            totals.unattributable += 1
            continue
        review = outcome.batch[failure.idx]
        if final:
            if skip_settled and settled(review):
                totals.skipped_settled += 1
                continue
            store.labels.record_failure(
                review.review_id, versions, run.run_id, failure.reason
            )
            totals.failed_durable += 1
            narrate(
                sink, _STAGE, StageKind.WARN,
                f"review {review.review_id} took a durable mark: {failure.reason}",
            )
        else:
            retry.append(review)
    return retry


def _config_hash(
    cfg: ExperimentRunConfig,
    ontology_version: str,
    ontology_content_hash: str,
    scope_descriptor: Mapping[str, object],
) -> str:
    """A fingerprint of the decision-relevant config — checkable, never trusted."""
    return config_hash({
        "cell": cfg.cell.name,
        "annotator_model_version": annotator_model_version(cfg.cell.batch_size),
        "wire_model": MODEL_ID,
        "prompt_version": cfg.cell.prompt_version,
        "batch_size": cfg.cell.batch_size,
        "ontology_version": ontology_version,
        "ontology_content_hash": ontology_content_hash,
        "scope": dict(scope_descriptor),
        "max_workers": cfg.max_workers,
        "budget_usd": cfg.budget_usd,
        "limit": cfg.limit,
    })


def execute_experiment_run(
    cfg: ExperimentRunConfig, entry: ProviderEntry, started: datetime | None = None
) -> int:
    """One cell-dispatch invocation end to end; returns the process exit code.

    The composition root, mirroring the sibling drivers: identity, the
    two-store split (the client's cache/ledger on worker threads over
    connection one, envelope writes on the main thread over connection two),
    client, ontology, sink — then the scope handshake, selection, the
    condition-pure pass structure, and the manifest whether the run finished
    or aborted. ``entry`` is injected so tests drive the whole path with a
    fake provider; production passes the DeepSeek entry.
    """
    started = started if started is not None else datetime.now(UTC)
    cell = cfg.cell
    run_id = mint_run_id(f"d2d-{cell.name}", started)
    run_dir = cfg.runs_dir / run_id

    stamp = load_ontology_version(cfg.ontology_path)
    ontology = load_ontology(cfg.ontology_path)
    surface_index = build_surface_index(ontology)
    versions = cell_versions(cell, stamp.version)
    build_prompt = cell_prompt_builder(cell)

    totals = ExperimentTotals()
    drift = DriftWatch()
    aborted: str | None = None
    selected = in_scope = already_settled = 0
    scope_descriptor: dict[str, object] = {"scope": cell.scope}

    with run_context(cfg.runs_dir, run_id, cfg.db_path) as (sink, client_store, driver_store):
        client = build_client(entry, cfg.budget_usd, cell.batch_size, client_store, sink)
        narrate(
            sink, _STAGE, StageKind.STARTED,
            f"run {run_id} · code {code_version()} · cell {cell.name} · "
            f"{versions.model_version} (wire {MODEL_ID}) · N={cell.batch_size} · "
            f"{cell.prompt_version} · workers {cfg.max_workers} · "
            f"ontology {stamp.version} · budget ${cfg.budget_usd:.2f}",
        )
        try:
            skip_settled = cell.scope == "gold-recomposed"
            if skip_settled:
                composed, gold_ids, scope_descriptor = recomposed_batches(cfg, driver_store)
                in_scope = len(composed)
                pending_batches = pending_recomposed_batches(
                    composed, gold_ids, driver_store, versions
                )
                already_settled = in_scope - len(pending_batches)
                if cfg.limit is not None:
                    pending_batches = pending_batches[: cfg.limit]
                batches: Sequence[tuple[Review, ...]] = pending_batches
                selected = len(batches)
                unit = "gold-anchored batches"
            else:
                reviews, scope_descriptor = scope_reviews(cfg, driver_store)
                in_scope = len(reviews)
                pending = pending_reviews(reviews, driver_store, versions)
                already_settled = in_scope - len(pending)
                if cfg.limit is not None:
                    pending = pending[: cfg.limit]
                selected = len(pending)
                batches = chunk(pending, cell.batch_size)
                unit = "reviews"
            run = Provenance(
                run_id=run_id,
                code_version=code_version(),
                created_at=started,
                config_hash=_config_hash(cfg, stamp.version, stamp.content_hash,
                                         scope_descriptor),
            )
            narrate(
                sink, _STAGE, StageKind.PROGRESS,
                f"selection: {selected} {unit} to label under {versions.model_version}/"
                f"{versions.prompt_version}/{versions.ontology_version} "
                f"({already_settled} of {in_scope} already settled"
                + (f", limit {cfg.limit})" if cfg.limit is not None else ")"),
            )
            if batches:
                driver_store.labels.record_run(run)

                def worker(batch: tuple[Review, ...]) -> BatchOutcome:
                    return classify_cell_batch(
                        client, ontology, surface_index, batch, build_prompt
                    )

                def consume(outcome: BatchOutcome, final: bool) -> list[Review]:
                    return _write_outcome(
                        outcome, driver_store, versions, run, final, totals, drift,
                        sink, skip_settled=skip_settled,
                    )

                # The recomposed cell never retries: its condition IS the batch
                # composition, and any re-chunked retry would dispatch a batch
                # that is not one-gold-among-nine-fresh-fillers under its triple.
                single_attempt = cell.batch_size == 1 or cell.scope == "gold-recomposed"
                with ThreadPoolExecutor(max_workers=cfg.max_workers) as pool:
                    failed = run_pass(
                        batches, "initial", worker,
                        lambda o: consume(o, single_attempt), pool, sink,
                        stage=_STAGE, warmup=True, progress_every=25,
                    )
                    if failed:
                        rebatch_chunks = chunk(failed, cell.batch_size)
                        remainder: tuple[Review, ...] = ()
                        if len(rebatch_chunks[-1]) < cell.batch_size:
                            remainder = rebatch_chunks.pop()
                        totals.rebatch_sizes = [len(batch) for batch in rebatch_chunks]
                        totals.rebatched = sum(totals.rebatch_sizes)
                        for review in remainder:
                            driver_store.labels.record_failure(
                                review.review_id, versions, run.run_id,
                                "sub-N rebatch remainder — durable mark, never "
                                "an off-size request",
                            )
                            totals.failed_durable += 1
                            narrate(
                                sink, _STAGE, StageKind.WARN,
                                f"review {review.review_id} took a durable mark: "
                                f"sub-N rebatch remainder ({len(remainder)} rows "
                                f"below N={cell.batch_size})",
                            )
                        if rebatch_chunks:
                            narrate(
                                sink, _STAGE, StageKind.PROGRESS,
                                f"rebatch: {totals.rebatched} failed rows retried at "
                                f"exactly N={cell.batch_size} — the final, "
                                "condition-pure attempt",
                            )
                            run_pass(
                                rebatch_chunks, "rebatch", worker,
                                lambda o: consume(o, True), pool, sink,
                                stage=_STAGE, warmup=False, progress_every=25,
                            )
        except KeyboardInterrupt:
            aborted = "keyboard interrupt"
        except (RunAbort, LlmUnavailableError, AtCapacityError) as exc:
            aborted = str(exc)
        except Exception as exc:  # manifest still written even when dying loud
            aborted = f"{type(exc).__name__}: {exc}"
            traceback.print_exc()

        run_cost = driver_store.spend_ledger.cost_since(started)
        finished = datetime.now(UTC)
        manifest: dict[str, object] = {
            "run_id": run_id,
            "code_version": code_version(),
            "cell": cell.name,
            "annotator_model_version": versions.model_version,
            "wire_model": MODEL_ID,
            "model_versions_seen": sorted(totals.model_versions_seen),
            "prompt_version": cell.prompt_version,
            "batch_size": cell.batch_size,
            "ontology_version": stamp.version,
            "ontology_content_hash": stamp.content_hash,
            "scope": scope_descriptor,
            "max_workers": cfg.max_workers,
            "budget_usd": cfg.budget_usd,
            "limit": cfg.limit,
            "started_at": started.isoformat(),
            "finished_at": finished.isoformat(),
            "reviews": {
                "in_scope": in_scope,
                "already_settled": already_settled,
                "selected": selected,
                "labeled": totals.labeled,
                "empty_envelopes": totals.empty_envelopes,
                "salvaged_from_partial_batches": totals.salvaged,
                "evidence_repairs": totals.repairs,
                "unattributable_rows": totals.unattributable,
                "rebatched": totals.rebatched,
                "rebatch_sizes": totals.rebatch_sizes,
                "failed_durable": totals.failed_durable,
                "refused_batches": totals.refused_batches,
                "skipped_settled": totals.skipped_settled,
            },
            "requests": totals.batches,
            "tokens": {
                "prompt": totals.prompt_tokens,
                "output": totals.output_tokens,
                "thinking": totals.thinking_tokens,
            },
            "cost_usd_run": run_cost,
            "aborted": aborted,
        }
        manifest_path = write_manifest(run_dir, manifest)
        outcome_kind = StageKind.WARN if aborted else StageKind.DONE
        narrate(
            sink, _STAGE, outcome_kind,
            (f"ABORTED: {aborted}" if aborted else "run complete")
            + f" · labeled {totals.labeled}/{selected} (empty {totals.empty_envelopes}, "
            f"failed durable {totals.failed_durable}) · ${run_cost:.4f} this run · "
            f"manifest {manifest_path}",
        )
    return 1 if aborted else 0


def main() -> None:
    """Parse the cell, build the DeepSeek entry, run. The D2d dispatch front door."""
    parser = argparse.ArgumentParser(
        description="Dispatch one registered D2d experiment cell into the pool "
                    "under its condition-tagged triple. Pilot with --limit first."
    )
    parser.add_argument("--cell", required=True, choices=sorted(CELLS),
                        help="the registered cell to dispatch")
    parser.add_argument("--sample", type=Path, default=Path("eval/agreement/sample.jsonl"),
                        help="the minted agreement sample (sample-scope cells)")
    parser.add_argument("--gold", type=Path, default=Path("eval/gold/gold.jsonl"),
                        help="the gold JSONL artifact (gold-scope cells)")
    parser.add_argument("--db", type=Path, default=Path("data/steamlens.sqlite3"),
                        help="the label-pool database (default: data/steamlens.sqlite3)")
    parser.add_argument("--runs-dir", type=Path, default=Path("data/runs"),
                        help="where run manifests and logs land (default: data/runs)")
    parser.add_argument("--ontology", type=Path, required=True,
                        help="ontology artifact path — explicit on purpose; every cell "
                             "pins v2 by path like every consumer of the census pool")
    parser.add_argument("--max-workers", type=int, default=4,
                        help="concurrent requests (default 4)")
    parser.add_argument("--budget-usd", type=float, required=True,
                        help="this run's spend cap (see the D2d dispatch proposal)")
    parser.add_argument("--limit", type=int, default=None,
                        help="label only the first K selected units (the pilot dial; "
                             "reviews for flat scopes, batches for the recomposed one)")
    parser.add_argument("--fillers-seed", type=int, default=DEFAULT_FILLERS_SEED,
                        help="the recomposed scope's filler-draw seed (default: "
                             f"{DEFAULT_FILLERS_SEED}; rides the config hash)")
    args = parser.parse_args()

    key = os.environ.get(KEY_ENV)
    if not key:
        raise SystemExit(f"missing {KEY_ENV} in the environment — set it and rerun")
    cfg = ExperimentRunConfig(
        cell=CELLS[args.cell],
        sample_path=args.sample,
        gold_path=args.gold,
        db_path=args.db,
        runs_dir=args.runs_dir,
        ontology_path=args.ontology,
        max_workers=args.max_workers,
        budget_usd=args.budget_usd,
        limit=args.limit,
        fillers_seed=args.fillers_seed,
    )
    entry = openai_compat_entry(key, base_url=DEEPSEEK_BASE_URL)
    raise SystemExit(execute_experiment_run(cfg, entry))


if __name__ == "__main__":
    main()
