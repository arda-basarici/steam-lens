"""Extraction+eval (M1) week-1 probe: what vocabulary does open aspect extraction produce?

The aspect-ontology decision (fixed vs. hybrid-with-fixed-core; pure open recorded as
dominated) turns on the shape of the vocabulary that emerges when a model names aspects
freely. Decision rule from the framing handoff: if a dozen-ish labels cover ~90% of
mentions across genres, fixed(+other) wins at minimum cost; a fat, game-specific tail
earns hybrid its normalization module.

Method: 100 uniformly sampled English reviews per game from 5 genre-diverse corpus
games (vehicle sim / story CRPG / competitive multiplayer / cozy farming / AAA
open-world), open extraction via Gemini (model pinned below), batched 10 reviews per
request under free-tier rate limits. English-only because DESIGN excludes multilingual
evaluation claims — the vocabulary is decided for the pipeline we will evaluate. No
minimum-length filter: short memey reviews are the real data, and the zero-aspect share
is itself a finding. The prompt deliberately names NO example aspects — seeding labels
would contaminate the emergent vocabulary this probe exists to observe.

This script produces the labeled captures + provenance; reading the vocabulary's shape
(coverage curves, cross-game overlap, tail composition) is a separate analysis pass.

Requires GEMINI_API_KEY in the environment (never in source, never printed).

Run: python probes/aspect_vocab_probe.py --smoke   (3 reviews, 1 request, no captures)
     python probes/aspect_vocab_probe.py           (full 5x100 run, ~50 requests, ~6 min)
"""
from __future__ import annotations

import argparse
import json
import os
import random
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import requests

CORPUS_DATA = Path(__file__).resolve().parents[2] / "steam-reviews" / "data"
CAPTURE_DIR = Path(__file__).resolve().parent / "captures" / "aspect_vocab"

# Tier-0 (fresh key) reality, read off the AI Studio dashboard 2026-07-09: the
# whole Gemini 3 generation is gated to 5 RPM / 20 RPD free — unusable for a
# 50-request run. The older 2.5 generation carries the roomier free quota.
MODEL = "gemini-2.5-flash"
API_URL = f"https://generativelanguage.googleapis.com/v1beta/models/{MODEL}:generateContent"
PROMPT_VERSION = "v1"
SEED = 20260709
N_PER_GAME = 100
# Tier 0 allows 20 requests/day per model: 34 reviews/request = 3 requests per
# game, 15 total, leaving slack for re-asks. Bigger batches exist to fit the
# quota, not for throughput.
BATCH_SIZE = 34
MIN_SECONDS_BETWEEN_REQUESTS = 13.0  # dashboard says 5 requests/minute on tier 0

GAMES = {
    "227300": "Euro Truck Simulator 2",
    "1086940": "Baldur's Gate 3",
    "252950": "Rocket League",
    "413150": "Stardew Valley",
    "1091500": "Cyberpunk 2077",
}

# No example aspect names anywhere in this prompt — examples would seed the vocabulary.
PROMPT_TEMPLATE = """\
You are extracting aspects from Steam reviews of the game {game_name}.

For each review, list the distinct aspects of the game the reviewer comments on.
Name each aspect yourself: a short lowercase noun phrase (1-3 words) that best
describes it. Do not use a predefined list. An aspect is a property of the game or
of the experience around it - not the reviewer's mood, and not a bare verdict with
no subject. If a review carries no aspect commentary (a joke, a meme, a plain
recommendation with no reasons), return an empty aspect list for it.

For each aspect, give the reviewer's sentiment toward it: "pos", "neg", or "mixed".

Reviews as JSON:
{reviews_json}

Return JSON only, one entry per input review, same idx values:
[{{"idx": 0, "aspects": [{{"aspect": "...", "sentiment": "pos"}}]}}, ...]
"""


def load_english_reviews(app_id: str) -> list[dict]:
    """One game's English, non-empty corpus reviews as {recommendationid, text}.

    English-only is a probe-scope decision (see module docstring), applied at load
    so sampling happens over the population the decision is actually about.
    """
    path = CORPUS_DATA / "raw" / "reviews" / f"{app_id}_reviews.jsonl"
    pool = []
    with path.open(encoding="utf-8") as f:
        for line in f:
            r = json.loads(line)
            text = (r.get("review") or "").strip()
            if r.get("language") == "english" and text:
                pool.append({"recommendationid": r["recommendationid"], "text": text})
    return pool


def call_gemini(prompt: str, api_key: str) -> tuple[str, dict]:
    """One generateContent call; returns (response text, usage metadata).

    Temperature 0: the probe wants a stable instrument, not creative variety.
    Retries transient failures (429/5xx) with a flat backoff; anything else is
    a real error and raises with the response body (never the key).
    """
    body = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {
            "temperature": 0,
            "responseMimeType": "application/json",
            # Flash models think by default and thoughts bill against the output
            # budget (observed: 7,865 thought tokens on one 10-review batch, which
            # starved the JSON past maxOutputTokens). Extraction needs no deliberation:
            # thinking off (2.5-generation syntax; 3.x uses thinkingLevel instead).
            "maxOutputTokens": 32768,
            "thinkingConfig": {"thinkingBudget": 0},
        },
    }
    for attempt in range(4):
        resp = requests.post(
            API_URL, headers={"x-goog-api-key": api_key}, json=body, timeout=120
        )
        if resp.status_code in (429, 500, 503) and attempt < 3:
            wait = 30 * (attempt + 1)
            print(f"    HTTP {resp.status_code}, backing off {wait}s...")
            time.sleep(wait)
            continue
        if not resp.ok:
            raise RuntimeError(f"Gemini call failed HTTP {resp.status_code}: {resp.text[:500]}")
        data = resp.json()
        candidate = data["candidates"][0]
        finish = candidate.get("finishReason")
        if finish != "STOP":
            raise RuntimeError(
                f"generation did not finish cleanly (finishReason={finish}, "
                f"usage={data.get('usageMetadata')})"
            )
        parts = candidate["content"]["parts"]
        text = "".join(p.get("text", "") for p in parts)
        return text, data.get("usageMetadata", {})
    raise RuntimeError("unreachable")


def parse_extractions(text: str, expected_idxs: set[int]) -> dict[int, list[dict]]:
    """Validate the model's JSON against the batch contract; fail loud on drift.

    The contract: one entry per input idx, aspects as {aspect: str, sentiment in
    pos/neg/mixed}. A silent mismatch here would corrupt the vocabulary counts the
    whole probe exists to measure, so violations raise instead of being skipped.
    """
    entries = json.loads(text)
    if not isinstance(entries, list):
        raise ValueError(f"expected a JSON list, got {type(entries).__name__}")
    out: dict[int, list[dict]] = {}
    for e in entries:
        idx = e["idx"]
        aspects = []
        for a in e.get("aspects", []):
            label = str(a["aspect"]).strip().lower()
            sentiment = a["sentiment"]
            # The prompt asks for pos/neg/mixed, but the model (rightly) emits
            # "neutral" for sentiment-free mentions; recording what it said beats
            # forcing a lie through the enum. Prompt left untouched mid-corpus.
            if sentiment not in ("pos", "neg", "mixed", "neutral"):
                raise ValueError(f"bad sentiment {sentiment!r} for aspect {label!r}")
            if label:
                aspects.append({"aspect": label, "sentiment": sentiment})
        out[idx] = aspects
    if set(out) != expected_idxs:
        raise ValueError(f"idx mismatch: got {sorted(out)}, expected {sorted(expected_idxs)}")
    return out


def extract_batch(game_name: str, batch: list[dict], api_key: str) -> tuple[dict[int, list[dict]], dict]:
    """Extract one batch of reviews; one re-ask on a malformed response, then raise."""
    payload = [{"idx": i, "text": r["text"]} for i, r in enumerate(batch)]
    prompt = PROMPT_TEMPLATE.format(
        game_name=game_name, reviews_json=json.dumps(payload, ensure_ascii=False)
    )
    expected = set(range(len(batch)))
    text, usage = call_gemini(prompt, api_key)
    try:
        return parse_extractions(text, expected), usage
    except (ValueError, KeyError, json.JSONDecodeError) as err:
        print(f"    malformed response ({err}); tail of response text:\n"
              f"    ...{text[-300:]}\n    one re-ask...")
        text, usage = call_gemini(prompt, api_key)
        return parse_extractions(text, expected), usage


class Throttle:
    """Spaces requests to stay under the free tier's requests-per-minute cap."""

    def __init__(self, min_interval: float):
        self.min_interval = min_interval
        self._last = 0.0

    def wait(self) -> None:
        elapsed = time.monotonic() - self._last
        if elapsed < self.min_interval:
            time.sleep(self.min_interval - elapsed)
        self._last = time.monotonic()


def run_smoke(api_key: str, rng: random.Random) -> None:
    """3 reviews, 1 request: shows input -> output verbatim before the daily budget is spent."""
    app_id, game_name = "1086940", GAMES["1086940"]
    batch = rng.sample(load_english_reviews(app_id), 3)
    print(f"Smoke: 3 English reviews from {game_name}, model {MODEL}\n")
    extractions, usage = extract_batch(game_name, batch, api_key)
    for i, r in enumerate(batch):
        shown = r["text"][:300].replace("\n", " ")
        print(f"review {i} ({len(r['text'])} chars): {shown}")
        print(f"  -> {json.dumps(extractions[i], ensure_ascii=False)}\n")
    print(f"tokens: {usage}")


def run_full(api_key: str, rng: random.Random) -> None:
    """The 5x100 run: captures per-review extractions + provenance, narrates progress."""
    CAPTURE_DIR.mkdir(parents=True, exist_ok=True)
    log_path = CAPTURE_DIR / "run.log"
    out_path = CAPTURE_DIR / "extractions.jsonl"
    # Resume-aware against the daily quota: games already fully captured are
    # skipped (their sample is still drawn, so the shared rng replays identically);
    # a partially captured game is dropped from the file and redone whole.
    done_counts: dict[str, int] = {}
    if out_path.exists():
        kept_lines = []
        for line in out_path.read_text(encoding="utf-8").splitlines():
            rec = json.loads(line)
            done_counts[rec["app_id"]] = done_counts.get(rec["app_id"], 0) + 1
            kept_lines.append((rec["app_id"], line))
        complete = {a for a, n in done_counts.items() if n >= N_PER_GAME}
        with out_path.open("w", encoding="utf-8") as f:
            for app_id, line in kept_lines:
                if app_id in complete:
                    f.write(line + "\n")
        done_counts = {a: n for a, n in done_counts.items() if a in complete}
    throttle = Throttle(MIN_SECONDS_BETWEEN_REQUESTS)
    started = datetime.now(timezone.utc).isoformat()
    record_count, request_count = 0, 0
    tokens = {"prompt": 0, "output": 0}

    def narrate(line: str) -> None:
        stamped = f"{datetime.now().strftime('%H:%M:%S')}  {line}"
        print(stamped, flush=True)
        with log_path.open("a", encoding="utf-8") as f:
            f.write(stamped + "\n")

    narrate(f"run start: {len(GAMES)} games x {N_PER_GAME} reviews, model {MODEL}, seed {SEED}")
    for app_id, game_name in GAMES.items():
        pool = load_english_reviews(app_id)
        sample = rng.sample(pool, N_PER_GAME)
        if done_counts.get(app_id, 0) >= N_PER_GAME:
            narrate(f"{game_name}: already captured, skipping")
            record_count += done_counts[app_id]
            continue
        batches = [sample[i:i + BATCH_SIZE] for i in range(0, len(sample), BATCH_SIZE)]
        game_aspects = 0
        for b_num, batch in enumerate(batches, 1):
            throttle.wait()
            extractions, usage = extract_batch(game_name, batch, api_key)
            request_count += 1
            tokens["prompt"] += usage.get("promptTokenCount", 0)
            tokens["output"] += usage.get("candidatesTokenCount", 0)
            with out_path.open("a", encoding="utf-8") as f:
                for i, r in enumerate(batch):
                    rec = {
                        "app_id": app_id,
                        "game": game_name,
                        "recommendationid": r["recommendationid"],
                        "text": r["text"],
                        "aspects": extractions[i],
                    }
                    f.write(json.dumps(rec, ensure_ascii=False) + "\n")
                    record_count += 1
            game_aspects += sum(len(extractions[i]) for i in range(len(batch)))
            narrate(f"{game_name}: batch {b_num}/{len(batches)} ok ({game_aspects} aspect mentions so far)")

    meta = {
        "probe": "aspect_vocab_probe",
        "question": "emergent vocabulary shape under open extraction (fixed vs. hybrid ontology)",
        "model": MODEL,
        "prompt_version": PROMPT_VERSION,
        "prompt_template": PROMPT_TEMPLATE,
        "seed": SEED,
        "n_per_game": N_PER_GAME,
        "language_filter": "english",
        "games": GAMES,
        "source": "frozen steam-reviews corpus (data/raw/reviews/*.jsonl)",
        "requests": request_count,
        "tokens": tokens,
        "started_utc": started,
        "finished_utc": datetime.now(timezone.utc).isoformat(),
    }
    (CAPTURE_DIR / "run_meta.json").write_text(
        json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    narrate(f"done: {record_count} reviews, {request_count} requests, tokens {tokens}")
    narrate(f"captures: {out_path.name} + run_meta.json in {CAPTURE_DIR}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--smoke", action="store_true", help="3 reviews, 1 request, no captures")
    args = parser.parse_args()

    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        sys.exit("GEMINI_API_KEY is not set in this process environment")
    rng = random.Random(SEED)
    if args.smoke:
        run_smoke(api_key, rng)
    else:
        run_full(api_key, rng)


if __name__ == "__main__":
    main()
