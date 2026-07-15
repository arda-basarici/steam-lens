"""Extension of the aspect-vocabulary probe: the rest of the corpus, gap-genres first.

Grew in three steps during the B1 pruning pass (see the GAMES comments): a 5-game
gap slate, a targeted FFXIV grind check, then the whole remaining corpus queued in
pruning-value order under the free-tier quota (20 requests/day = ~6 games/day; the
run dies loud at the wall and resumes clean, so re-running daily drips it in).

The original probe (aspect_vocab_probe.py, captures/aspect_vocab/) sampled a
vehicle sim / story CRPG / competitive multiplayer / cozy farming / AAA open-world
slate. Its evidence now grounds the B1 codebook pruning pass — and several pinned
aspects sit at zero-to-thin mentions precisely because no probed game is of the
genre where they carry the buyer's question: camera/balance (souls-like), cheating/
matchmaking/servers (competitive FPS), stability/developer_conduct (broken AAA
launch), grind/monetization (F2P live service), sound_design (horror). This run
points the SAME instrument (prompt v1 verbatim, same model, same n, same English
filter, same corpus source) at a slate chosen to stress exactly those rows, so the
pruning interview rules on evidence instead of on the first slate's genre skew.

Deliberately unfixable here, flagged in the analysis instead: accessibility (no
accessibility-flagship game in the corpus) and localization (starved by
construction — the probe is English-only per DESIGN's evaluation scope).

Captures to captures/aspect_vocab_ext/ — the original capture stays frozen.

Requires GEMINI_API_KEY in the environment (never in source, never printed).

Run: python probes/aspect_vocab_ext_probe.py --smoke   (3 reviews, 1 request, no captures)
     python probes/aspect_vocab_ext_probe.py           (full run, 3 requests/game, ~6 min;
                                                        resume skips completed games)
"""
from __future__ import annotations

import argparse
import json
import os
import random
import sys
from datetime import datetime, timezone
from pathlib import Path

# The instrument is imported, not copied: same prompt, extractor, validation, and
# throttle as the original run — the whole point is comparability of the two captures.
from aspect_vocab_probe import (
    BATCH_SIZE,
    MIN_SECONDS_BETWEEN_REQUESTS,
    MODEL,
    N_PER_GAME,
    PROMPT_TEMPLATE,
    PROMPT_VERSION,
    Throttle,
    extract_batch,
    load_english_reviews,
)

CAPTURE_DIR = Path(__file__).resolve().parent / "captures" / "aspect_vocab_ext"
SEED = 20260715  # run date, matching the original's seed convention

GAMES = {
    "1245620": "Elden Ring",
    # Counter-Strike 2 was the first pick for this slot, but its corpus capture
    # holds only 19 English reviews — Overwatch 2 carries the same rows
    # (matchmaking, balance, servers, community, monetization) with a 5.8k pool.
    "2357570": "Overwatch 2",
    "1517290": "Battlefield 2042",
    "238960": "Path of Exile",
    "739630": "Phasmophobia",
    # Added mid-pruning-interview (2026-07-15): the grind ruling needed an MMO —
    # Path of Exile's sample gave zero grind mentions and the question is whether
    # that is slate luck or real rarity. Resume logic makes this a 3-request add.
    "39210": "Final Fantasy XIV Online",
    # Second enlargement (2026-07-15, Arda's call: grow evidence within the free
    # quota, no commitment to a full-corpus sweep): ten games aimed at the rows
    # still thin or untested after the first extension — physics (Satisfactory,
    # Goat Simulator), level_design + sound_design (Hollow Knight, Portal 2),
    # writing/player_choice/pacing (Disco Elysium, Undertale, Persona 5 Royal),
    # emotional_impact (Edith Finch), ui/dlc (EU4), animation/art_style (Cuphead).
    "526870": "Satisfactory",
    "265930": "Goat Simulator",
    "367520": "Hollow Knight",
    "620": "Portal 2",
    "632470": "Disco Elysium",
    "391540": "Undertale",
    "1687950": "Persona 5 Royal",
    "501300": "What Remains of Edith Finch",
    "236850": "Europa Universalis IV",
    "268910": "Cuphead",
    # Third enlargement (2026-07-15, Arda's call: queue the whole remaining corpus
    # and let the 20-requests/day free quota decide the daily cut — resume makes
    # each run a stateless drip). Ordered by pruning value: rows still in doubt
    # first (physics, camera confirmation, dev_conduct extremes, story/voice),
    # breadth after. Counter-Strike 2 (730) excluded: only 19 English reviews.
    "374320": "Dark Souls III",
    "4000": "Garry's Mod",
    "233720": "Surgeon Simulator",
    "553850": "Helldivers 2",
    "1372880": "The Day Before",
    "1328670": "Mass Effect Legendary Edition",
    "252490": "Rust",
    "275850": "No Man's Sky",
    "698780": "Doki Doki Literature Club!",
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


def run_smoke(api_key: str, rng: random.Random) -> None:
    """3 reviews, 1 request: shows input -> output verbatim before the budget is spent."""
    app_id, game_name = "1245620", GAMES["1245620"]
    batch = rng.sample(load_english_reviews(app_id), 3)
    print(f"Smoke: 3 English reviews from {game_name}, model {MODEL}\n")
    extractions, usage = extract_batch(game_name, batch, api_key)
    for i, r in enumerate(batch):
        shown = r["text"][:300].replace("\n", " ")
        print(f"review {i} ({len(r['text'])} chars): {shown}")
        print(f"  -> {json.dumps(extractions[i], ensure_ascii=False)}\n")
    print(f"tokens: {usage}")


def run_full(api_key: str, rng: random.Random) -> None:
    """The 5x100 run: captures per-review extractions + provenance, narrates progress.

    Same resume discipline as the original: games already fully captured are skipped
    (their sample is still drawn, so the shared rng replays identically); a partially
    captured game is dropped from the file and redone whole.
    """
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
        "probe": "aspect_vocab_ext_probe",
        "question": "evidence for the genre-starved pinned aspects (B1 pruning pass)",
        "extends": "aspect_vocab_probe (captures/aspect_vocab/), same instrument verbatim",
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
