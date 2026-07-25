"""Per-game agreement with CIs, and how much of it the aspect mix explains.

Usage:
    uv run python probes/per_game_agreement.py

Promoted from the 2026-07-24 content session's scratchpad so the per-game post's
numbers stay regenerable. Two questions, one read-only pass over the census
agreement sample:

1. Per-game judge-vs-production agreement F1 with 95% bootstrap CIs (reviews
   resampled within each game — the deep-read probe's point estimates carry
   n as low as 15 mentions, too noisy to publish bare).
2. Whether a game's agreement is just its mention mix inheriting per-aspect
   agreement: an expected F1 (the game's aspect counts weighted by census-wide
   per-aspect F1) against the actual. The 2026-07-23 deep read claimed "the
   per-aspect finding seen twice"; the correlation and the band-width contrast
   below say it's only partly that — the mix predicts a narrow band while
   actual agreement spans far wider, so the residual is a game-level effect
   (or noise; the CIs bound how much).

Games below JUDGE_N_FLOOR mentions are excluded from the table (tiny slices
make meaningless F1s), matching the deep-read probe's floor.
"""

from __future__ import annotations

import json
import random
import sqlite3
import statistics
import sys
from collections import Counter, defaultdict
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "src"))

PROD = ("deepseek-v4-flash", "classify-v1", "v2")
JUDGE = ("gemini-3-flash-preview", "classify-v1", "v2")
JUDGE_N_FLOOR = 15
N_RESAMPLES = 10_000
SEED = 20260724

lines = (REPO / "eval/agreement/sample.jsonl").read_text(encoding="utf-8").splitlines()
ids = [json.loads(line)["review_id"] for line in lines if line.strip()]
game_of = {json.loads(line)["review_id"]: json.loads(line)["game"] for line in lines if line.strip()}

conn = sqlite3.connect(f"file:{(REPO / 'data/steamlens.sqlite3').as_posix()}?mode=ro", uri=True)
placeholders = ",".join("?" * len(ids))


def aspect_sets(triple: tuple[str, str, str]) -> dict[str, set[str]]:
    """review_id -> pinned aspect set under the triple."""
    rows = conn.execute(
        f"SELECT c.review_id, m.aspect FROM mentions m"
        f" JOIN classifications c ON c.id = m.classification_id"
        f" WHERE c.model_version=? AND c.prompt_version=? AND c.ontology_version=?"
        f" AND m.slot='pinned' AND c.review_id IN ({placeholders})",
        triple + tuple(ids),
    ).fetchall()
    out: dict[str, set[str]] = defaultdict(set)
    for rid, aspect in rows:
        out[str(rid)].add(str(aspect))
    return out


prod = aspect_sets(PROD)
judge = aspect_sets(JUDGE)

# Per-review confusion contributions, grouped by game; per-aspect census-wide
# counters feed the expected-F1 side.
by_game: dict[str, list[tuple[int, int, int]]] = defaultdict(list)
per_aspect: dict[str, Counter[str]] = defaultdict(Counter)
mix: dict[str, Counter[str]] = defaultdict(Counter)

for rid in ids:
    p, j = prod.get(rid, set()), judge.get(rid, set())
    game = game_of[rid]
    tp, fp, fn = len(p & j), len(p - j), len(j - p)
    by_game[game].append((tp, fp, fn))
    for aspect in p & j:
        per_aspect[aspect]["tp"] += 1
        mix[game][aspect] += 1
    for aspect in p - j:
        per_aspect[aspect]["fp"] += 1
        mix[game][aspect] += 1
    for aspect in j - p:
        per_aspect[aspect]["fn"] += 1
        mix[game][aspect] += 1


def f1_of(tp: int, fp: int, fn: int) -> float:
    denom = 2 * tp + fp + fn
    return 2 * tp / denom if denom else 0.0


aspect_f1 = {a: f1_of(c["tp"], c["fp"], c["fn"]) for a, c in per_aspect.items()}

rng = random.Random(SEED)
rows = []
for game, contribs in by_game.items():
    tp, fp, fn = (sum(c[i] for c in contribs) for i in range(3))
    judge_n = tp + fn
    if judge_n < JUDGE_N_FLOOR:
        continue
    resamples = []
    for _ in range(N_RESAMPLES):
        rtp = rfp = rfn = 0
        for _ in contribs:
            ctp, cfp, cfn = contribs[rng.randrange(len(contribs))]
            rtp += ctp
            rfp += cfp
            rfn += cfn
        resamples.append(f1_of(rtp, rfp, rfn))
    resamples.sort()
    ci_lo = resamples[int(0.025 * N_RESAMPLES)]
    ci_hi = resamples[int(0.975 * N_RESAMPLES) - 1]
    total = sum(mix[game].values())
    expected = sum(aspect_f1[a] * n for a, n in mix[game].items()) / total
    rows.append((f1_of(tp, fp, fn), ci_lo, ci_hi, expected, game, judge_n, len(contribs)))

rows.sort(reverse=True)

print(f"== per-game agreement F1, 95% bootstrap CI ({N_RESAMPLES} resamples, seed {SEED}),"
      f" games with judge_n >= {JUDGE_N_FLOOR} ==")
print(f"{'game':<32}{'f1':>7}{'ci_lo':>7}{'ci_hi':>7}{'expected':>9}{'resid':>7}{'judge_n':>8}{'reviews':>8}")
for f1, lo, hi, exp, game, judge_n, n_reviews in rows:
    print(f"{game[:30]:<32}{f1:>7.3f}{lo:>7.3f}{hi:>7.3f}{exp:>9.3f}{f1 - exp:>+7.3f}{judge_n:>8}{n_reviews:>8}")

actual = [r[0] for r in rows]
expected = [r[3] for r in rows]
r = statistics.correlation(actual, expected)
print(f"\ngames: {len(rows)}   pearson r(actual, mix-expected) = {r:.3f}")
print(f"actual spread {min(actual):.3f}-{max(actual):.3f}"
      f" vs mix-expected band {min(expected):.3f}-{max(expected):.3f}")

conn.close()
