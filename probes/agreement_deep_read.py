"""Deep read of the census agreement run — per-aspect, sentiment, per-game, exemplars.

Usage:
    uv run python probes/agreement_deep_read.py

Read-only exploration over the label pool, promoted from the 2026-07-23
evaluation session's scratchpad so its tables and the Δ-ranked disagreement
exemplars (the adjudication-sheet seed) stay regenerable. All numbers are
point estimates without intervals; journaling per-aspect agreement as eval-run
rows is a registered follow-up, deliberately separate.
"""

from __future__ import annotations

import json
import sqlite3
import sys
from collections import Counter, defaultdict
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "src"))

PROD = ("deepseek-v4-flash", "classify-v1", "v2")
JUDGE = ("gemini-3-flash-preview", "classify-v1", "v2")

ids = [
    json.loads(line)["review_id"]
    for line in (REPO / "eval/agreement/sample.jsonl").read_text(encoding="utf-8").splitlines()
    if line.strip()
]
app_by_id = {
    json.loads(line)["review_id"]: json.loads(line)["game"]
    for line in (REPO / "eval/agreement/sample.jsonl").read_text(encoding="utf-8").splitlines()
    if line.strip()
}

conn = sqlite3.connect(f"file:{(REPO / 'data/steamlens.sqlite3').as_posix()}?mode=ro", uri=True)
placeholders = ",".join("?" * len(ids))


def mentions_for(triple: tuple[str, str, str]) -> dict[str, dict[str, str]]:
    """review_id -> {aspect: sentiment} for pinned mentions under the triple."""
    rows = conn.execute(
        f"SELECT c.review_id, m.aspect, m.sentiment FROM mentions m"
        f" JOIN classifications c ON c.id = m.classification_id"
        f" WHERE c.model_version=? AND c.prompt_version=? AND c.ontology_version=?"
        f" AND m.slot='pinned' AND c.review_id IN ({placeholders})",
        triple + tuple(ids),
    ).fetchall()
    out: dict[str, dict[str, str]] = defaultdict(dict)
    for rid, aspect, sentiment in rows:
        out[str(rid)][str(aspect)] = str(sentiment)
    return out


prod = mentions_for(PROD)
judge = mentions_for(JUDGE)

# --- per-aspect table -------------------------------------------------------
per_aspect: dict[str, Counter[str]] = defaultdict(Counter)
sent_pairs: Counter[tuple[str, str]] = Counter()
per_game: dict[str, Counter[str]] = defaultdict(Counter)
per_review_disagreement: list[tuple[int, str]] = []

for rid in ids:
    p, j = prod.get(rid, {}), judge.get(rid, {})
    matched = p.keys() & j.keys()
    game = app_by_id[rid]
    for aspect in matched:
        per_aspect[aspect]["tp"] += 1
        per_game[game]["tp"] += 1
        sent_pairs[(j[aspect], p[aspect])] += 1
        if p[aspect] == j[aspect]:
            per_aspect[aspect]["sent_ok"] += 1
    for aspect in p.keys() - j.keys():
        per_aspect[aspect]["fp"] += 1
        per_game[game]["fp"] += 1
    for aspect in j.keys() - p.keys():
        per_aspect[aspect]["fn"] += 1
        per_game[game]["fn"] += 1
    per_review_disagreement.append((len(p.keys() ^ j.keys()), rid))


def f1(c: Counter[str]) -> float:
    tp, fp, fn = c["tp"], c["fp"], c["fn"]
    return 2 * tp / (2 * tp + fp + fn) if (2 * tp + fp + fn) else 0.0


print("== per-aspect agreement (judge n = tp+fn desc, top 20) ==")
print(f"{'aspect':<24}{'judge_n':>8}{'prod_n':>8}{'tp':>5}{'fp':>5}{'fn':>5}{'f1':>7}{'sent_ok/tp':>11}")
ranked = sorted(per_aspect.items(), key=lambda kv: -(kv[1]['tp'] + kv[1]['fn']))
for aspect, c in ranked[:20]:
    judge_n, prod_n = c["tp"] + c["fn"], c["tp"] + c["fp"]
    sent = f"{c['sent_ok']}/{c['tp']}" if c["tp"] else "-"
    print(f"{aspect:<24}{judge_n:>8}{prod_n:>8}{c['tp']:>5}{c['fp']:>5}{c['fn']:>5}{f1(c):>7.3f}{sent:>11}")
tail = ranked[20:]
if tail:
    tail_c = Counter()
    for _, c in tail:
        tail_c.update(c)
    label = f"(tail, {len(tail)} aspects)"
    print(f"{label:<24}{tail_c['tp'] + tail_c['fn']:>8}{tail_c['tp'] + tail_c['fp']:>8}"
          f"{tail_c['tp']:>5}{tail_c['fp']:>5}{tail_c['fn']:>5}{f1(tail_c):>7.3f}")

# --- sentiment confusion on matches ----------------------------------------
print("\n== sentiment on matched aspects (rows=judge, cols=production) ==")
sentiments = ["positive", "negative", "mixed", "neutral"]
print(f"{'':<10}" + "".join(f"{s:>10}" for s in sentiments))
for js in sentiments:
    print(f"{js:<10}" + "".join(f"{sent_pairs.get((js, ps), 0):>10}" for ps in sentiments))

# --- per-game spread ---------------------------------------------------------
print("\n== per-game agreement F1 (games with judge_n >= 15, sorted) ==")
rows = []
for game, c in per_game.items():
    judge_n = c["tp"] + c["fn"]
    if judge_n >= 15:
        rows.append((f1(c), game, judge_n))
for score, game, judge_n in sorted(rows):
    print(f"  {score:.3f}  {game[:40]:<42} (judge_n {judge_n})")

# --- worst disagreements -----------------------------------------------------
print("\n== largest per-review disagreements (symmetric diff of pinned aspect sets) ==")
for diff, rid in sorted(per_review_disagreement, reverse=True)[:8]:
    p, j = prod.get(rid, {}), judge.get(rid, {})
    only_p = sorted(p.keys() - j.keys())
    only_j = sorted(j.keys() - p.keys())
    text = conn.execute("SELECT text FROM reviews WHERE review_id=?", (rid,)).fetchone()[0]
    snippet = " ".join(str(text).split())[:110]
    print(f"  Δ{diff} · {rid} · {app_by_id[rid][:24]}")
    print(f"    prod-only: {only_p}")
    print(f"    judge-only: {only_j}")
    print(f"    text: {snippet}…")

conn.close()
