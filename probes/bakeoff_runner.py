"""The C0 bake-off runner — one candidate, one N, the gold slice, captures out.

Usage (one scored run per candidate; the N-probe is this same script at
several N values on the two probe models):

    uv run python probes/bakeoff_runner.py gemini-flash --n 20
    uv run python probes/bakeoff_runner.py groq-llama-70b --n 50 --limit 10

C0.5 certification arms (prompt/ontology variants on one candidate — gold
itself stays pinned to the packaged v1 artifact; the run-side wording is the
experiment): ``--ontology`` swaps the codebook artifact, ``--compact`` renders
the decision-surface-only prompt variant, ``--tag`` keeps the arm's captures
in their own directory so ``bakeoff_table.py --compare`` can address them:

    uv run python probes/bakeoff_runner.py deepseek-v4-flash --n 10 \\
        --ontology src/steamlens/ontology/v2.toml --tag v2

Captures land in ``probes/captures/bakeoff/<candidate>/n<N>/``:

    raw.jsonl          one line per request — review ids, the extracted completion
                       text (not the wire body — that lives in the response archive),
                       reported model version, finish reason, the token split
    predictions.jsonl  one line per answered review — resolved mentions or a
                       failed marker, with the attempt that produced it
    manifest.json      the protocol's provenance fields (DESIGN C0 entries)

The run rides the full LlmClient: rpm pacing, bounded retries, the spend
ledger, and a durable response archive shared across runs (``bakeoff.sqlite3``
next to the captures) — a crashed or re-invoked run re-reads bought responses
for free. Failed rows get one re-batch pass at N=1 per the protocol's
unrecoverable definition ("failed in its production-shape batch AND alone").

The _CANDIDATES table below carries the scan's best-knowledge model ids,
pacing, and structured-output params — verify each against its console when
its key lands; edits here are config, and what actually ran is in the manifest.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

_REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO / "src"))

from steamlens.contracts import AspectMention, LlmRequest, LlmStage, SinkEvent  # noqa: E402
from steamlens.core.classify import (  # noqa: E402
    CLASSIFY_RESPONSE_SCHEMA,
    COMPACT_PROMPT_VERSION,
    PROMPT_VERSION,
    build_classify_prompt,
    build_classify_prompt_compact,
    parse_classify_response,
)
from steamlens.core.normalize import build_surface_index  # noqa: E402
from steamlens.evals import GoldRecord, load_gold  # noqa: E402
from steamlens.llm_client import (  # noqa: E402
    GenerationIncompleteError,
    LlmClient,
    LlmClientConfig,
    ModelSpec,
    Route,
    gemini_entry,
    openai_compat_entry,
)
from steamlens.llm_client.openai_compat import (  # noqa: E402
    DEEPSEEK_BASE_URL,
    GROQ_BASE_URL,
    MISTRAL_BASE_URL,
    OLLAMA_BASE_URL,
    OPENROUTER_BASE_URL,
)
from steamlens.ontology import load_ontology, load_ontology_version  # noqa: E402
from steamlens.store import Store  # noqa: E402

_GOLD_PATH = _REPO / "eval" / "gold" / "gold.jsonl"
_CAPTURES = _REPO / "probes" / "captures" / "bakeoff"

# Output sizing, raised 2026-07-19 from measured demand (the day-one 512+140
# formula truncated dense batches at five providers, cut exactly at the cap):
# a single dense review generated up to 1,359 tokens on the N=1 isolation
# path (and one retry was truncated at the old 652 cap), so the base alone
# must hold one worst-case review; dense full batches demanded >165
# tokens/review (batch p90 132). The per-candidate output_cap min() below
# stays as the runaway guard.
_OUTPUT_BASE = 2_048
_OUTPUT_PER_REVIEW = 200

_GEMINI_PARAMS: dict[str, object] = {
    "temperature": 0,
    "responseMimeType": "application/json",
    "responseSchema": CLASSIFY_RESPONSE_SCHEMA,
    "thinkingConfig": {"thinkingBudget": 0},
}
_JSON_OBJECT: dict[str, object] = {"temperature": 0, "response_format": {"type": "json_object"}}


@dataclass(frozen=True)
class Candidate:
    """One pool member's dial: identity, envelope, and structured-output mode."""

    kind: str  # 'gemini' | 'compat'
    model: str
    key_env: str | None  # None = keyless (local Ollama)
    structured_output: str  # the mode label the manifest records
    rpm: int
    rpd: int | None
    output_cap: int
    base_url: str | None = None
    params: dict[str, object] = field(default_factory=dict)
    # Ledger prices; free tiers carry honest zeros. For providers with prefix
    # caching, the input price is the CACHE-MISS ceiling — the ledger then
    # over-reports rather than flatters; true cost reads from the captured
    # usage's cache-hit/miss split.
    input_usd_per_1m: float = 0.0
    output_usd_per_1m: float = 0.0


_CANDIDATES: dict[str, Candidate] = {
    # Gemini rpm/rpd are Arda's console-verified free-tier numbers (2026-07-18):
    # the 20-RPD models force N>=13 for a full 250-review run by quota alone.
    "gemini-flash": Candidate(
        kind="gemini", model="gemini-2.5-flash", key_env="GEMINI_API_KEY",
        structured_output="gemini-responseSchema", rpm=5, rpd=20, output_cap=65_536,
        params=_GEMINI_PARAMS,
    ),
    "gemini-flash-lite": Candidate(
        kind="gemini", model="gemini-2.5-flash-lite", key_env="GEMINI_API_KEY",
        structured_output="gemini-responseSchema", rpm=10, rpd=20, output_cap=65_536,
        params=_GEMINI_PARAMS,
    ),
    "gemini-3-flash": Candidate(
        kind="gemini", model="gemini-3-flash-preview", key_env="GEMINI_API_KEY",
        structured_output="gemini-responseSchema", rpm=5, rpd=20, output_cap=65_536,
        params=_GEMINI_PARAMS,
    ),
    "gemini-3.1-flash-lite": Candidate(
        kind="gemini", model="gemini-3.1-flash-lite", key_env="GEMINI_API_KEY",
        structured_output="gemini-responseSchema", rpm=15, rpd=500, output_cap=65_536,
        params=_GEMINI_PARAMS,
    ),
    "gemini-3.5-flash": Candidate(
        kind="gemini", model="gemini-3.5-flash", key_env="GEMINI_API_KEY",
        structured_output="gemini-responseSchema", rpm=5, rpd=20, output_cap=65_536,
        params=_GEMINI_PARAMS,
    ),
    # ENVELOPE EXIT (Arda's ruling 2026-07-19): 100K TPD vs ~113k tokens per
    # full 250-review run means 2 days per MEASUREMENT and ~22.5M tokens
    # (~225 days) for the ~50k-review survey — infeasible for dispatch at any
    # quality. Scored 160/250 PARTIAL, deliberately left incomplete. Lessons
    # kept for the record: Groq counts prompt + the max_tokens RESERVATION
    # against its 12K TPM per request (HTTP 413 at 12,072 requested) — hence
    # the 2,500 cap; json_object forces an object root on this route too
    # (batches wrapped the array in {"reviews": ...}) -> prompt-json, per the
    # OpenRouter lesson.
    "groq-llama-70b": Candidate(
        kind="compat", model="llama-3.3-70b-versatile", key_env="GROQ_API_KEY",
        structured_output="prompt-json", rpm=1, rpd=1_000, output_cap=2_500,
        base_url=GROQ_BASE_URL, params={"temperature": 0},
    ),
    # ENVELOPE-DEAD on the free tier (2026-07-18): 6K TPM < the ~7.6k-token
    # prompt — a single classify-v1 request is unservable at any batch size
    # (HTTP 413 at the smoke). Kept for the record; exits the pool by envelope.
    "groq-llama-8b": Candidate(
        kind="compat", model="llama-3.1-8b-instant", key_env="GROQ_API_KEY",
        structured_output="json_object", rpm=1, rpd=14_400, output_cap=8_192,
        base_url=GROQ_BASE_URL, params=_JSON_OBJECT,
    ),
    # Mistral throttles by RPS + TPM, no daily cap (console-verified 2026-07-18).
    # small-2603's 50K TPM binds harder than its 0.83 RPS at our ~10k-token
    # batches — rpm 5 encodes that; the dated ids are pinned because the API
    # echoes back the alias, which is too vague for a scored manifest.
    "mistral-small": Candidate(
        kind="compat", model="mistral-small-2603", key_env="MISTRAL_API_KEY",
        structured_output="json_object", rpm=5, rpd=None, output_cap=8_192,
        base_url=MISTRAL_BASE_URL, params=_JSON_OBJECT,
    ),
    "mistral-nemo": Candidate(
        kind="compat", model="open-mistral-nemo-2407", key_env="MISTRAL_API_KEY",
        structured_output="json_object", rpm=30, rpd=None, output_cap=8_192,
        base_url=MISTRAL_BASE_URL, params=_JSON_OBJECT,
    ),
    # Pool amendment 2026-07-18 (Arda): Mistral's free tier has no daily cap, so
    # its stronger tiers are survey-viable at zero cost — worth measuring.
    "mistral-medium": Candidate(
        kind="compat", model="mistral-medium-2508", key_env="MISTRAL_API_KEY",
        structured_output="json_object", rpm=20, rpd=None, output_cap=8_192,
        base_url=MISTRAL_BASE_URL, params=_JSON_OBJECT,
    ),
    "mistral-large": Candidate(
        kind="compat", model="mistral-large-2512", key_env="MISTRAL_API_KEY",
        structured_output="json_object", rpm=4, rpd=None, output_cap=8_192,
        base_url=MISTRAL_BASE_URL, params=_JSON_OBJECT,
    ),
    "ministral-14b": Candidate(
        kind="compat", model="ministral-14b-2512", key_env="MISTRAL_API_KEY",
        structured_output="json_object", rpm=30, rpd=None, output_cap=8_192,
        base_url=MISTRAL_BASE_URL, params=_JSON_OBJECT,
    ),
    # PAID — the pool's first (the ids replace deepseek-chat/-reasoner,
    # deprecated 2026-07-24; docs read 2026-07-19). Envelope: concurrency-only
    # (2500 concurrent for flash, no RPM/TPM/TPD), so rpm here is politeness.
    # Thinking DEFAULTS ON for v4 — disabled explicitly for pool parity.
    # Prices are the cache-miss ceiling; the automatic prefix cache bills
    # hits at ~98% off (usage carries prompt_cache_hit/miss_tokens), and our
    # ~88%-fixed prompt should hit from batch 2 on — true cost reads from
    # the captures, roughly a cent per full flash run.
    "deepseek-v4-flash": Candidate(
        kind="compat", model="deepseek-v4-flash", key_env="DEEPSEEK_API_KEY",
        structured_output="json_object", rpm=120, rpd=None, output_cap=8_192,
        base_url=DEEPSEEK_BASE_URL,
        params={
            "temperature": 0,
            "response_format": {"type": "json_object"},
            "thinking": {"type": "disabled"},
        },
        input_usd_per_1m=0.14, output_usd_per_1m=0.28,
    ),
    "deepseek-v4-pro": Candidate(
        kind="compat", model="deepseek-v4-pro", key_env="DEEPSEEK_API_KEY",
        structured_output="json_object", rpm=120, rpd=None, output_cap=8_192,
        base_url=DEEPSEEK_BASE_URL,
        params={
            "temperature": 0,
            "response_format": {"type": "json_object"},
            "thinking": {"type": "disabled"},
        },
        input_usd_per_1m=0.435, output_usd_per_1m=0.87,
    ),
    # Via the OpenRouter aggregator (free tier: ~20 rpm, 50 free-model req/day
    # account-wide; upstream routing varies per request — provenance rides in
    # the response's provider field, captured in raw.jsonl).
    "nemotron-ultra": Candidate(
        kind="compat", model="nvidia/nemotron-3-ultra-550b-a55b:free",
        key_env="OPENROUTER_API_KEY", structured_output="prompt-json",
        rpm=15, rpd=50, output_cap=16_384,
        base_url=OPENROUTER_BASE_URL,
        # reasoning disabled: at the first smoke the model spent the entire
        # generation ceiling on reasoning and emitted zero content. No
        # response_format: json_object forces an OBJECT root on this route and
        # our contract is an array (second smoke) — prompt-disciplined JSON is
        # this candidate's best native mechanism, recorded as such.
        params={"temperature": 0, "reasoning": {"enabled": False}},
    ),
    # Also via OpenRouter (the 50 free req/day pool is ACCOUNT-wide — shared
    # with nemotron, budget runs jointly). 262K route context: no truncation
    # wall; reasoning-capable, disabled for parity with the task; the :free
    # route lists structured_outputs but not response_format — prompt-json
    # per the object-root lesson.
    "hunyuan-3": Candidate(
        kind="compat", model="tencent/hy3:free",
        key_env="OPENROUTER_API_KEY", structured_output="prompt-json",
        rpm=15, rpd=50, output_cap=32_768,
        base_url=OPENROUTER_BASE_URL,
        params={"temperature": 0, "reasoning": {"enabled": False}},
    ),
    "ollama-8b": Candidate(
        kind="compat", model="llama3.1:8b", key_env=None,
        structured_output="json_object", rpm=600, rpd=None, output_cap=8_192,
        base_url=OLLAMA_BASE_URL, params=_JSON_OBJECT,
    ),
}


class ConsoleSink:
    """Narrates client events to stdout — the probe's live pane."""

    def emit(self, event: SinkEvent) -> None:
        print(f"    · {event}")


@dataclass
class RunTotals:
    """The run's accumulating counters — one place, printed and manifested."""

    prompt_tokens: int = 0
    output_tokens: int = 0
    thinking_tokens: int = 0
    salvaged: int = 0
    repairs: int = 0
    unattributable: int = 0


def _api_key(candidate: Candidate) -> str:
    if candidate.key_env is None:
        return ""
    key = os.environ.get(candidate.key_env)
    if not key:
        raise SystemExit(f"missing {candidate.key_env} in the environment — set it and rerun")
    return key


def _build_client(name: str, candidate: Candidate, n: int, store: Store) -> LlmClient:
    entry = (
        gemini_entry(_api_key(candidate))
        if candidate.kind == "gemini"
        else openai_compat_entry(_api_key(candidate), base_url=candidate.base_url or "")
    )
    config = LlmClientConfig(
        routes={
            LlmStage.CLASSIFY: Route(
                provider=name,
                model=candidate.model,
                max_output_tokens=min(candidate.output_cap, _OUTPUT_BASE + _OUTPUT_PER_REVIEW * n),
                params=dict(candidate.params),
            )
        },
        models={
            candidate.model: ModelSpec(
                rpm=candidate.rpm, rpd=candidate.rpd,
                input_usd_per_1m=candidate.input_usd_per_1m,
                output_usd_per_1m=candidate.output_usd_per_1m,
            )
        },
        daily_reset_utc_hour=8 if candidate.kind == "gemini" else 0,
    )
    return LlmClient(
        config, store.responses, store.spend_ledger, ConsoleSink(), registry={name: entry}
    )


def _chunk(records: tuple[GoldRecord, ...], n: int) -> list[tuple[GoldRecord, ...]]:
    return [records[i : i + n] for i in range(0, len(records), n)]


def _mention_row(mention: AspectMention) -> dict[str, object]:
    return {
        "aspect": mention.aspect,
        "slot": mention.slot.value,
        "sentiment": mention.sentiment.value,
        "evidence": mention.evidence,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Run one bake-off candidate over the gold slice.")
    parser.add_argument("candidate", choices=sorted(_CANDIDATES))
    parser.add_argument("--n", type=int, required=True, help="batch size (reviews per request)")
    parser.add_argument("--limit", type=int, default=None, help="first K reviews only (smoke)")
    parser.add_argument(
        "--ontology", type=Path, default=None,
        help="ontology artifact override (default: the packaged v1) — a C0.5 arm",
    )
    parser.add_argument(
        "--compact", action="store_true",
        help="render the decision-surface-only prompt variant (COMPACT_PROMPT_VERSION)",
    )
    parser.add_argument(
        "--tag", default=None,
        help="capture-directory suffix for an arm (e.g. 'v2' -> <candidate>-v2/n<N>)",
    )
    args = parser.parse_args()

    candidate = _CANDIDATES[args.candidate]
    records = load_gold(_GOLD_PATH)
    if args.limit:
        records = records[: args.limit]
    # Gold's pin is checked against the PACKAGED v1 artifact always — that is
    # gold's identity. An --ontology override changes what the RUN reads, and
    # that mismatch is the C0.5 experiment, recorded in the manifest, never a
    # silent substitution.
    gold_pin = load_ontology_version()
    if {r.ontology_content_hash for r in records} != {gold_pin.content_hash}:
        raise SystemExit("gold's ontology pin does not match the packaged v1 artifact — refusing")
    ontology = load_ontology(args.ontology)
    stamp = load_ontology_version(args.ontology)
    index = build_surface_index(ontology)
    build_prompt = build_classify_prompt_compact if args.compact else build_classify_prompt
    prompt_version = COMPACT_PROMPT_VERSION if args.compact else PROMPT_VERSION
    label = args.candidate + (f"-{args.tag}" if args.tag else "")

    out_dir = _CAPTURES / label / f"n{args.n}"
    out_dir.mkdir(parents=True, exist_ok=True)
    store = Store(_CAPTURES / "bakeoff.sqlite3")
    client = _build_client(args.candidate, candidate, args.n, store)

    started = datetime.now(UTC)
    totals = RunTotals()
    raw_rows: list[dict[str, object]] = []
    predictions: dict[str, dict[str, object]] = {}
    failed_initial: list[GoldRecord] = []
    still_failed: list[GoldRecord] = []
    aborted: str | None = None

    def run_batch(batch: tuple[GoldRecord, ...], attempt: str) -> list[GoldRecord]:
        texts = [r.text for r in batch]
        prompt = build_prompt(texts, ontology)
        try:
            response = client.complete(LlmRequest(stage=LlmStage.CLASSIFY, prompt=prompt))
            finish = response.finish_reason.value
        except GenerationIncompleteError as exc:
            response = exc.response  # spend already journaled; salvage what parsed
            finish = f"incomplete:{exc.reason.value}"
        totals.prompt_tokens += response.usage.prompt_tokens
        totals.output_tokens += response.usage.output_tokens
        totals.thinking_tokens += response.usage.thinking_tokens
        raw_rows.append(
            {
                "attempt": attempt,
                "review_ids": [r.review_id for r in batch],
                "model_version": response.model_version,
                "finish_reason": finish,
                "usage": {
                    "prompt": response.usage.prompt_tokens,
                    "output": response.usage.output_tokens,
                    "thinking": response.usage.thinking_tokens,
                },
                # The extracted completion text, honestly named: the provider's
                # full wire body lives in the shared cache DB (bakeoff.sqlite3),
                # keyed by payload hash — exposing it at the seam is a parked
                # contract question (FIXLOG 2026-07-18).
                "text": response.text,
            }
        )
        result = parse_classify_response(response.text, texts, index)
        had_failures = bool(result.failures)
        totals.repairs += len(result.repairs)
        for parsed in result.parsed:
            record = batch[parsed.idx]
            predictions[record.review_id] = {
                "review_id": record.review_id,
                "mentions": [_mention_row(m) for m in parsed.mentions],
                "failed": False,
                "attempt": attempt,
            }
            if had_failures:
                totals.salvaged += 1
        failed: list[GoldRecord] = []
        for failure in result.failures:
            # None = no usable idx; out-of-range = the model answered an idx we
            # never sent (seen live: Nemo emitting idx 73 in a 50-review batch).
            if failure.idx is None or not 0 <= failure.idx < len(batch):
                totals.unattributable += 1
                continue
            record = batch[failure.idx]
            failed.append(record)
            if attempt == "retry":  # the final stage: failed even alone
                predictions[record.review_id] = {
                    "review_id": record.review_id,
                    "mentions": [],
                    "failed": True,
                    "attempt": attempt,
                    "reason": failure.reason,
                }
        return failed

    batches = _chunk(records, args.n)
    try:
        for i, batch in enumerate(batches, start=1):
            print(f"batch {i}/{len(batches)} ({len(batch)} reviews)")
            failed_initial += run_batch(batch, "initial")
        if failed_initial:
            # Wholesale batch failures make straight-to-N=1 isolation quota-
            # catastrophic (nemotron burned a full daily budget on it,
            # 2026-07-18): re-batch the failures at production N first, then
            # isolate only the survivors — the gate's "failed in its batch AND
            # alone" semantics is preserved.
            print(f"re-batch pass: {len(failed_initial)} failed rows at N={args.n}")
            for chunk in _chunk(tuple(failed_initial), args.n):
                still_failed += run_batch(chunk, "rebatch")
        if still_failed:
            print(f"isolation pass: {len(still_failed)} rows alone at N=1")
            for record in still_failed:
                run_batch((record,), "retry")
    except KeyboardInterrupt:
        aborted = "keyboard interrupt"
    except Exception as exc:  # persist partial captures before dying loud
        aborted = f"{type(exc).__name__}: {exc}"

    unrecoverable = sum(1 for p in predictions.values() if p["failed"])
    (out_dir / "raw.jsonl").write_text(
        "\n".join(json.dumps(r, ensure_ascii=False) for r in raw_rows), encoding="utf-8"
    )
    (out_dir / "predictions.jsonl").write_text(
        "\n".join(
            json.dumps(predictions[r.review_id], ensure_ascii=False)
            for r in records
            if r.review_id in predictions
        ),
        encoding="utf-8",
    )
    manifest = {
        "candidate": label,
        "base_candidate": args.candidate,
        "provider_kind": candidate.kind,
        "model": candidate.model,
        "model_versions": sorted({str(r["model_version"]) for r in raw_rows}),
        "prompt_version": prompt_version,
        "ontology_version": stamp.version,
        "ontology_content_hash": stamp.content_hash,
        "ontology_override": str(args.ontology) if args.ontology else None,
        "gold_ontology_pin": gold_pin.content_hash,
        "structured_output": candidate.structured_output,
        "params": candidate.params,
        "n": args.n,
        "limit": args.limit,
        "gold_path": str(_GOLD_PATH.relative_to(_REPO)),
        "started_at": started.isoformat(),
        "finished_at": datetime.now(UTC).isoformat(),
        "requests": len(raw_rows),
        "tokens": {
            "prompt": totals.prompt_tokens,
            "output": totals.output_tokens,
            "thinking": totals.thinking_tokens,
        },
        "cost_usd": store.spend_ledger.cost_since(started),
        "reviews": {
            "total": len(records),
            "answered": len(predictions),
            "salvaged_from_partial_batches": totals.salvaged,
            "failed_initial": len(failed_initial),
            "isolation_retries": len(still_failed),
            "unrecoverable": unrecoverable,
            "unattributable_rows": totals.unattributable,
            "evidence_repairs": totals.repairs,
        },
        "aborted": aborted,
        "argv": sys.argv[1:],
    }
    (out_dir / "manifest.json").write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8"
    )

    print(f"\n{'ABORTED: ' + aborted if aborted else 'DONE'}")
    print(
        f"  answered {len(predictions)}/{len(records)}, unrecoverable {unrecoverable} "
        f"({unrecoverable / len(records):.1%} vs the 2% gate), "
        f"salvaged {totals.salvaged}, repairs {totals.repairs}"
    )
    print(
        f"  tokens: prompt {totals.prompt_tokens:,} · output {totals.output_tokens:,} · "
        f"thinking {totals.thinking_tokens:,} across {len(raw_rows)} requests"
    )
    print(f"  captures -> {out_dir.relative_to(_REPO)}")
    if aborted:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
