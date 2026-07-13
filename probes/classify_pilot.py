"""B4 classify pilot: first live contact between the classify prompt and real reviews.

One-shot qualitative read of prompt ``classify-v1`` on a handful of corpus reviews,
run BEFORE the store (B5) and the corpus-labeling driver (C1) build on the prompt —
the cheapest moment to catch a force-fit habit, a schema misread, or a codebook gap.
This is a probe, not the pipeline: it wires the real seams (ontology -> classify ->
llm_client with the responseSchema route -> parse -> normalize-resolved mentions)
but persists nothing except its own capture files.

Spend honesty: the default run is a DRY RUN — it builds and prints what would be
sent, spends nothing. Only ``--live`` sends requests (2 total: a 1-review batch and
a 5-review batch), against the free tier's small daily quota.
Requires GEMINI_API_KEY in the environment (never in source, never printed).

Dev-slice discipline (the gold-set leakage rule made operational): every review id
this pilot sends to the model is appended to ``captures/classify_pilot/dev_slice.json``.
Reviews the prompt was iterated against are disqualified from future gold-set
candidacy (D1 reads this file to exclude them).
"""

from __future__ import annotations

import argparse
import json
import os
import random
import sys
from datetime import datetime, timezone
from pathlib import Path

from steamlens.contracts import LlmRequest, LlmStage, MetricEvent, SinkEvent
from steamlens.core.classify import (
    CLASSIFY_RESPONSE_SCHEMA,
    PROMPT_VERSION,
    build_classify_prompt,
    parse_classify_response,
)
from steamlens.core.normalize import build_surface_index
from steamlens.llm_client import (
    GenerationIncompleteError,
    InMemoryClassifyCache,
    InMemorySpendLedger,
    LlmClient,
    LlmClientConfig,
    ModelSpec,
    Route,
    gemini_entry,
)
from steamlens.ontology import load_ontology

CORPUS_DATA = Path(__file__).resolve().parents[2] / "steam-reviews" / "data"
CAPTURE_DIR = Path(__file__).resolve().parent / "captures" / "classify_pilot"

SEED = 20260713
MODEL = "gemini-2.5-flash"
# Two contrasting corpus games: cozy-sim vocabulary vs tech/performance vocabulary.
GAMES = {"413150": "Stardew Valley", "1091500": "Cyberpunk 2077"}
BATCH_SIZES = (1, 5)  # a sanity single + a small real batch = 2 requests total

# The CLASSIFY route this pilot dials: schema-constrained JSON, temperature 0,
# thinking off (the classification tier hypothesis — D2 measures whether thinking
# buys agreement). Ceiling sized for the 5-batch: ~150 output tokens/review + slack.
ROUTE = Route(
    provider="gemini",
    model=MODEL,
    max_output_tokens=2048,
    params={
        "temperature": 0,
        "responseMimeType": "application/json",
        "responseSchema": CLASSIFY_RESPONSE_SCHEMA,
        "thinkingConfig": {"thinkingBudget": 0},
    },
)
# Free-tier envelope, conservative (the probe's dashboard reading); prices are
# honest zeros — quota, not dollars, is the binding constraint here.
CONFIG = LlmClientConfig(
    routes={LlmStage.CLASSIFY: ROUTE},
    models={MODEL: ModelSpec(rpm=5, rpd=20, input_usd_per_1m=0.0, output_usd_per_1m=0.0)},
)


class ConsoleSink:
    """Prints the client's metric events so spend/latency stay visible in the terminal."""

    def emit(self, event: SinkEvent) -> None:
        if isinstance(event, MetricEvent):
            print(f"    [metric] {event.stage}/{event.name}: {event.value:g} {event.unit}")


def load_review_slice() -> list[dict[str, str]]:
    """A seeded, reproducible sample of English corpus reviews across the pilot games.

    Three per game, no length filter beyond non-empty — short bare-verdict reviews
    are wanted (they exercise the zero-aspect behavior), long ones too.
    """
    rng = random.Random(SEED)
    picked: list[dict[str, str]] = []
    for app_id, name in GAMES.items():
        path = CORPUS_DATA / "raw" / "reviews" / f"{app_id}_reviews.jsonl"
        pool = []
        with path.open(encoding="utf-8") as f:
            for line in f:
                r = json.loads(line)
                text = (r.get("review") or "").strip()
                if text and r.get("language") == "english":
                    pool.append({"id": r["recommendationid"], "game": name, "text": text})
        picked.extend(rng.sample(pool, 3))
    return picked


def show_batch_result(texts: list[str], reviews: list[dict[str, str]], raw: str) -> dict:
    """Parse one response and print review -> mentions side by side; returns the record."""
    index = build_surface_index(load_ontology())
    result = parse_classify_response(raw, texts, index)
    parsed_by_idx = {p.idx: p for p in result.parsed}
    record: dict = {"parsed": [], "failures": [], "repairs": []}
    for idx, review in enumerate(reviews):
        preview = review["text"][:240].replace("\n", " ")
        print(f'\n  [{idx}] ({review["game"]}) "{preview}{"..." if len(review["text"]) > 240 else ""}"')
        if idx in parsed_by_idx:
            mentions = parsed_by_idx[idx].mentions
            if not mentions:
                print("      -> no aspects (zero-aspect review)")
            for m in mentions:
                slot = "pinned" if m.slot == "pinned" else "CANDIDATE"
                quote = f' | "{m.evidence}"' if m.evidence else ""
                print(f"      -> {m.aspect}  [{slot}, {m.sentiment}]{quote}")
            record["parsed"].append(
                {
                    "review_id": review["id"],
                    "mentions": [
                        {
                            "aspect": m.aspect,
                            "slot": str(m.slot),
                            "sentiment": str(m.sentiment),
                            "evidence": m.evidence,
                        }
                        for m in mentions
                    ],
                }
            )
    for failure in result.failures:
        print(f"      !! idx {failure.idx} FAILED: {failure.reason}")
        record["failures"].append({"idx": failure.idx, "reason": failure.reason})
    for repair in result.repairs:
        print(f'      ~~ evidence repaired on idx {repair.idx} ({repair.aspect}): "{repair.discarded_evidence}"')
        record["repairs"].append(
            {"idx": repair.idx, "aspect": repair.aspect, "discarded": repair.discarded_evidence}
        )
    return record


def record_dev_slice(review_ids: list[str]) -> None:
    """Append the ids the model saw to the cumulative dev-slice exclusion list."""
    path = CAPTURE_DIR / "dev_slice.json"
    known: list[str] = json.loads(path.read_text(encoding="utf-8")) if path.exists() else []
    merged = sorted(set(known) | set(review_ids))
    path.write_text(json.dumps(merged, indent=2), encoding="utf-8")
    print(f"\ndev slice: {len(merged)} review ids on record at {path}")


def main() -> None:
    # Windows consoles default to cp1252; the codebook's arrows and review text are UTF-8.
    sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[union-attr]
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--live", action="store_true", help="actually send (default: dry run)")
    args = parser.parse_args()

    ontology = load_ontology()
    reviews = load_review_slice()
    batches = []
    cursor = 0
    for size in BATCH_SIZES:
        batches.append(reviews[cursor : cursor + size])
        cursor += size

    if not args.live:
        prompt = build_classify_prompt([r["text"] for r in batches[-1]], ontology)
        print(f"DRY RUN - nothing sent. Prompt {PROMPT_VERSION}, ontology {ontology.version}.")
        print(f"Batches planned: {[len(b) for b in batches]} -> {len(batches)} requests, model {MODEL}.")
        print(f"Largest prompt: {len(prompt):,} chars (~{len(prompt) // 4:,} tokens).\n")
        print("--- full prompt of the largest batch follows ---\n")
        print(prompt)
        print("--- end of prompt; re-run with --live to send ---")
        return

    api_key = os.environ.get("GEMINI_API_KEY", "")
    if not api_key:
        sys.exit("GEMINI_API_KEY is not set; aborting before any request.")

    CAPTURE_DIR.mkdir(parents=True, exist_ok=True)
    client = LlmClient(
        CONFIG,
        InMemoryClassifyCache(),
        InMemorySpendLedger(),
        ConsoleSink(),
        registry={"gemini": gemini_entry(api_key)},
    )
    run: dict = {
        "started_at": datetime.now(timezone.utc).isoformat(),
        "prompt_version": PROMPT_VERSION,
        "ontology_version": ontology.version,
        "model": MODEL,
        "seed": SEED,
        "batches": [],
    }
    for batch in batches:
        texts = [r["text"] for r in batch]
        print(f"\n=== batch of {len(texts)} ===")
        try:
            response = client.complete(
                LlmRequest(stage=LlmStage.CLASSIFY, prompt=build_classify_prompt(texts, ontology))
            )
        except GenerationIncompleteError as error:
            print(f"  !! truncated ({error}); batch lost — resize ceiling or batch")
            run["batches"].append({"size": len(texts), "truncated": str(error)})
            continue
        usage = response.usage
        print(
            f"  model_version={response.model_version} finish={response.finish_reason} "
            f"tokens: prompt={usage.prompt_tokens} output={usage.output_tokens} "
            f"thinking={usage.thinking_tokens}"
        )
        batch_record = show_batch_result(texts, batch, response.text)
        run["batches"].append(
            {
                "size": len(texts),
                "review_ids": [r["id"] for r in batch],
                "model_version": response.model_version,
                "finish_reason": str(response.finish_reason),
                "usage": {
                    "prompt": usage.prompt_tokens,
                    "output": usage.output_tokens,
                    "thinking": usage.thinking_tokens,
                },
                "raw_response": response.text,
                **batch_record,
            }
        )

    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    out = CAPTURE_DIR / f"run_{stamp}.json"
    out.write_text(json.dumps(run, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"\ncapture written: {out}")
    record_dev_slice([rid for batch in run["batches"] for rid in batch.get("review_ids", [])])


if __name__ == "__main__":
    main()
