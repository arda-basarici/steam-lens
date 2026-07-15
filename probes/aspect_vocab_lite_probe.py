"""Second-instrument extraction: gemini-2.5-flash-lite over the pruning doubt rows.

Free-tier quotas are per model, so flash-lite carries its own 20-requests/day budget
— but a different model is a different instrument, and its counts must not silently
merge with the flash captures. This run therefore starts with a CALIBRATION game
(Elden Ring, already measured by flash) so instrument agreement is a measured fact,
not an assumption; the merge-vs-separate decision is made at analysis time against
that comparison. Until then, captures live in their own directory and every record
carries the model.

After calibration, the slate walks the rows the pruning interview still holds open:
Dark Souls III re-tests the camera demotion on a second souls-like AND a second
instrument; Goat Simulator / Garry's Mod / Surgeon Simulator are the physics test;
Persona 5 Royal is the pacing test.

Requires GEMINI_API_KEY in the environment (never in source, never printed).

Run: python probes/aspect_vocab_lite_probe.py   (6 games x 100, 18 requests; resume
                                                 skips completed games on rerun)
"""
from __future__ import annotations

import json
import os
import random
import sys
from datetime import datetime, timezone
from pathlib import Path

from aspect_vocab_probe import (
    BATCH_SIZE,
    N_PER_GAME,
    PROMPT_TEMPLATE,
    PROMPT_VERSION,
    Throttle,
    extract_batch,
    load_english_reviews,
)

CAPTURE_DIR = Path(__file__).resolve().parent / "captures" / "aspect_vocab_lite"
# gemini-2.5-flash-lite is closed to new keys (404, tried 2026-07-15); 3.1-flash-lite
# carries the roomiest free quota on this key's dashboard: 15 RPM / 500 RPD —
# enough for the whole remaining corpus in one day, at a 5s request spacing.
MODEL = "gemini-3.1-flash-lite"
MIN_SECONDS_BETWEEN_REQUESTS = 5.0
SEED = 20260715  # same convention (run date); the rng seeds THIS capture's sampling

GAMES = {
    # Calibration first: flash already measured this game (aspect_vocab_ext),
    # so the two instruments can be compared on identical task and pool. The
    # sample is drawn with a different rng stream, so agreement is judged on
    # distribution shape (zero-share, mentions/review, vocabulary), not per-review.
    "1245620": "Elden Ring",
    "374320": "Dark Souls III",
    "265930": "Goat Simulator",
    "4000": "Garry's Mod",
    "233720": "Surgeon Simulator",
    "1687950": "Persona 5 Royal",
    # Full-corpus completion (2026-07-15, same session): calibration passed
    # (vague-verdict noise aside, real-aspect readings track flash; see the
    # ledger), and the 500 RPD quota covers everything the flash drip would
    # have taken a week to reach. Order: doubt rows first, breadth after.
    # Excluded: Counter-Strike 2 (19 English reviews) and the six games the
    # flash extension already captured (OW2/BF2042/PoE/Phasmo/FFXIV/Satisfactory).
    "367520": "Hollow Knight",
    "620": "Portal 2",
    "632470": "Disco Elysium",
    "391540": "Undertale",
    "501300": "What Remains of Edith Finch",
    "236850": "Europa Universalis IV",
    "268910": "Cuphead",
    "698780": "Doki Doki Literature Club!",
    "553850": "Helldivers 2",
    "1372880": "The Day Before",
    "1328670": "Mass Effect Legendary Edition",
    "252490": "Rust",
    "275850": "No Man's Sky",
    "239030": "Papers, Please",
    "262060": "Darkest Dungeon",
    "255710": "Cities: Skylines",
    "1716740": "Starfield",
    "377160": "Fallout 4",
    "881100": "Noita",
    "8870": "BioShock Infinite",
    "550": "Left 4 Dead 2",
    "261550": "Mount & Blade II: Bannerlord",
    "1919590": "NBA 2K23",
    "1294810": "Redfall",
    "1265780": "The Lord of the Rings: Gollum",
    "1222700": "A Way Out",
    "719040": "Wasteland 3",
    "750920": "Shadow of the Tomb Raider",
    "70300": "VVVVVV",
    "659540": "Warsim: The Realm of Aslona",
    "1525700": "Tavern Master",
    "245470": "Democracy 3",
}


def run_full(api_key: str, rng: random.Random) -> None:
    """The 6x100 run: same capture/provenance/resume discipline as the extension probe."""
    CAPTURE_DIR.mkdir(parents=True, exist_ok=True)
    log_path = CAPTURE_DIR / "run.log"
    out_path = CAPTURE_DIR / "extractions.jsonl"
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
            extractions, usage = extract_batch(game_name, batch, api_key, model=MODEL)
            request_count += 1
            tokens["prompt"] += usage.get("promptTokenCount", 0)
            tokens["output"] += usage.get("candidatesTokenCount", 0)
            with out_path.open("a", encoding="utf-8") as f:
                for i, r in enumerate(batch):
                    rec = {
                        "app_id": app_id,
                        "game": game_name,
                        "model": MODEL,
                        "recommendationid": r["recommendationid"],
                        "text": r["text"],
                        "aspects": extractions[i],
                    }
                    f.write(json.dumps(rec, ensure_ascii=False) + "\n")
                    record_count += 1
            game_aspects += sum(len(extractions[i]) for i in range(len(batch)))
            narrate(f"{game_name}: batch {b_num}/{len(batches)} ok ({game_aspects} aspect mentions so far)")

    meta = {
        "probe": "aspect_vocab_lite_probe",
        "question": "second-instrument check + doubt-row evidence (B1 pruning pass)",
        "relation": "instrument differs from aspect_vocab_probe (flash-lite vs flash); "
                    "calibrated on Elden Ring vs the flash capture in aspect_vocab_ext; "
                    "counts merge only if calibration supports it",
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
    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        sys.exit("GEMINI_API_KEY is not set in this process environment")
    run_full(api_key, random.Random(SEED))


if __name__ == "__main__":
    main()
