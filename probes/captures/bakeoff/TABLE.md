# C0 bake-off — the comparison table

Generated 2026-07-17T22:13:32+00:00 · gold: 250 reviews / 333 pinned mentions (351 incl. 18 candidate) · bootstrap: 10,000 resamples over reviews, seed 20260718 · regenerate: `uv run python probes/bakeoff_table.py --seed 20260718`

| run | model | N | structured output | precision [95% CI] | recall [95% CI] | F1 [95% CI] | sentiment acc [95% CI] | parse fail | flags |
|---|---|---|---|---|---|---|---|---|---|
| gold-assist (reference) | claude-sonnet-5 | — | session-agent | 0.857 [0.815–0.894] | 0.970 [0.950–0.987] | 0.910 [0.880–0.934] | 0.920 [0.889–0.951] | 0.0% | REFERENCE — competes with nobody |

## Diagnostics (unscored, per the protocol)

| run | zero-share (gold 49.2%) | candidate emission (gold 5.1% of mentions) | candidate overlap with gold's 11 | tokens | cost USD |
|---|---|---|---|---|---|
| gold-assist (reference) | 44.8% | 4.8% | 7/11 (cutscenes, factions, grind, originality, romance, unique, worn-out) | — | 0.0000 |

Notes: parse-failed reviews score as zero predictions, never excluded; salvage-parsed rows count as parsed (rates in each capture's manifest). Candidate-slot mentions are excluded from the score on both sides. N is per-candidate by design (the batch-size amendment) — read quality differences with N in view.
