# C0 bake-off — the comparison table

Generated 2026-07-19T11:32:03+00:00 · gold: 250 reviews / 333 pinned mentions (351 incl. 18 candidate) · bootstrap: 10,000 resamples over reviews, seed 20260718 · regenerate: `uv run python probes/bakeoff_table.py --seed 20260718`

| run | model | N | structured output | precision [95% CI] | recall [95% CI] | F1 [95% CI] | sentiment acc [95% CI] | parse fail | tokens in/out | flags |
|---|---|---|---|---|---|---|---|---|---|---|
| gold-assist (reference) | claude-sonnet-5 | — | session-agent | 0.857 [0.815–0.894] | 0.970 [0.950–0.987] | 0.910 [0.880–0.934] | 0.920 [0.889–0.951] | 0.0% | — | REFERENCE — competes with nobody |
| gemini-3-flash/n20 | gemini-3-flash-preview | 20 | gemini-responseSchema | 0.762 [0.710–0.809] | 0.844 [0.795–0.887] | 0.801 [0.756–0.840] | 0.883 [0.847–0.918] | 0.0% | 105,898p/12,922o | — |
| gemini-3.5-flash/n50 | gemini-3.5-flash | 50 | gemini-responseSchema | 0.833 [0.785–0.875] | 0.763 [0.706–0.813] | 0.796 [0.750–0.837] | 0.902 [0.866–0.939] | 0.0% | 50,802p/17,583o | — |
| gemini-3-flash/n50 | gemini-3-flash-preview | 50 | gemini-responseSchema | 0.786 [0.730–0.836] | 0.793 [0.736–0.844] | 0.789 [0.741–0.832] | 0.886 [0.850–0.924] | 0.0% | 50,802p/11,722o | — |
| gemini-3.5-flash/n20 | gemini-3.5-flash | 20 | gemini-responseSchema | 0.761 [0.640–0.851] | 0.793 [0.735–0.845] | 0.776 [0.698–0.837] | 0.909 [0.871–0.944] | 0.0% | 113,443p/17,906o | — |
| gemini-flash/n20 | gemini-2.5-flash | 20 | gemini-responseSchema | 0.747 [0.688–0.798] | 0.805 [0.751–0.854] | 0.775 [0.725–0.818] | 0.907 [0.873–0.943] | 0.0% | 255,302p/28,984o | — |
| gemini-3.1-flash-lite/n10 | gemini-3.1-flash-lite | 10 | gemini-responseSchema | 0.746 [0.687–0.799] | 0.796 [0.741–0.845] | 0.770 [0.719–0.816] | 0.887 [0.852–0.924] | 0.0% | 258,724p/21,586o | — |
| deepseek-v4-flash/n20 | deepseek-v4-flash | 20 | json_object | 0.732 [0.674–0.785] | 0.805 [0.751–0.855] | 0.767 [0.717–0.812] | 0.884 [0.847–0.924] | 0.0% | 248,719p/22,305o | — |
| gemini-3.1-flash-lite/n20 | gemini-3.1-flash-lite | 20 | gemini-responseSchema | 0.769 [0.707–0.825] | 0.760 [0.703–0.811] | 0.764 [0.710–0.812] | 0.893 [0.857–0.930] | 0.0% | 105,898p/15,298o | — |
| hunyuan-3/n20 | tencent/hy3:free | 20 | prompt-json | 0.695 [0.637–0.749] | 0.835 [0.782–0.880] | 0.759 [0.707–0.804] | 0.878 [0.831–0.919] | 0.0% | 248,316p/26,026o | — |
| gemini-3.1-flash-lite/n50 | gemini-3.1-flash-lite | 50 | gemini-responseSchema | 0.770 [0.706–0.828] | 0.745 [0.687–0.797] | 0.757 [0.702–0.807] | 0.911 [0.878–0.948] | 0.0% | 50,802p/11,088o | — |
| hunyuan-3/n50 | tencent/hy3:free | 50 | prompt-json | 0.682 [0.619–0.742] | 0.817 [0.759–0.868] | 0.743 [0.688–0.793] | 0.879 [0.837–0.922] | 0.0% | 49,625p/17,136o | — |
| gemini-3.1-flash-lite/n5 | gemini-3.1-flash-lite | 5 | gemini-responseSchema | 0.740 [0.689–0.786] | 0.727 [0.599–0.820] | 0.733 [0.655–0.792] | 0.901 [0.859–0.940] | 0.4% | 396,502p/21,653o | — |
| mistral-large/n20 | mistral-large-2512 | 20 | json_object | 0.707 [0.640–0.769] | 0.760 [0.705–0.810] | 0.732 [0.677–0.782] | 0.889 [0.851–0.929] | 0.0% | 104,557p/18,611o | — |
| mistral-medium/n20 | mistral-medium-2508 | 20 | json_object | 0.706 [0.642–0.767] | 0.757 [0.700–0.814] | 0.730 [0.675–0.784] | 0.893 [0.853–0.935] | 0.0% | 242,398p/22,593o | — |
| mistral-large/n50 | mistral-large-2512 | 50 | json_object | 0.727 [0.659–0.790] | 0.721 [0.655–0.781] | 0.724 [0.663–0.780] | 0.900 [0.860–0.942] | 0.0% | 50,399p/17,948o | — |
| mistral-medium/n50 | mistral-medium-2508 | 50 | json_object | 0.768 [0.702–0.827] | 0.667 [0.605–0.723] | 0.714 [0.658–0.762] | 0.851 [0.806–0.900] | 0.0% | 50,399p/16,731o | — |
| mistral-small/n5 | mistral-small-2603 | 5 | json_object | 0.671 [0.603–0.738] | 0.724 [0.662–0.781] | 0.697 [0.636–0.753] | 0.880 [0.841–0.920] | 0.0% | 355,286p/15,328o | — |
| ministral-14b/n20 | ministral-14b-2512 | 20 | json_object | 0.652 [0.584–0.718] | 0.727 [0.671–0.777] | 0.688 [0.630–0.742] | 0.880 [0.841–0.923] | 0.0% | 104,557p/16,684o | — |
| ministral-14b/n50 | ministral-14b-2512 | 50 | json_object | 0.645 [0.574–0.716] | 0.715 [0.652–0.772] | 0.678 [0.616–0.735] | 0.908 [0.868–0.948] | 0.0% | 50,399p/17,515o | — |
| mistral-small/n10 | mistral-small-2603 | 10 | json_object | 0.660 [0.594–0.719] | 0.676 [0.612–0.734] | 0.668 [0.607–0.722] | 0.893 [0.857–0.931] | 0.0% | 185,794p/14,973o | — |
| deepseek-v4-pro/n20 | deepseek-v4-pro | 20 | json_object | 0.662 [0.606–0.716] | 0.619 [0.497–0.734] | 0.640 [0.560–0.708] | 0.883 [0.839–0.925] | 16.8% | 535,115p/32,644o | DQ (parse gate) |
| mistral-small/n50 | mistral-small-2603 | 50 | json_object | 0.667 [0.587–0.742] | 0.607 [0.539–0.670] | 0.635 [0.567–0.698] | 0.876 [0.838–0.918] | 0.0% | 57,197p/13,827o | — |
| nemotron-ultra/n20 | nvidia/nemotron-3-ultra-550b-a55b:free | 20 | prompt-json | 0.642 [0.569–0.710] | 0.625 [0.558–0.685] | 0.633 [0.570–0.690] | 0.880 [0.839–0.923] | 1.6% | 369,983p/27,808o | PARTIAL |
| mistral-small/n20 | mistral-small-2603 | 20 | json_object | 0.638 [0.523–0.736] | 0.592 [0.499–0.677] | 0.614 [0.533–0.688] | 0.883 [0.840–0.922] | 0.8% | 152,437p/13,037o | — |
| mistral-nemo/n20 | open-mistral-nemo-2407 | 20 | json_object | 0.582 [0.492–0.671] | 0.544 [0.464–0.624] | 0.562 [0.483–0.640] | 0.878 [0.834–0.922] | 0.0% | 242,398p/19,974o | — |
| nemotron-ultra/n50 | nvidia/nemotron-3-ultra-550b-a55b:free | 50 | prompt-json | 0.610 [0.519–0.699] | 0.483 [0.391–0.576] | 0.539 [0.452–0.625] | 0.870 [0.813–0.921] | 26.0% | 281,678p/19,709o | DQ (parse gate), PARTIAL |
| mistral-nemo/n50 | open-mistral-nemo-2407 | 50 | json_object | 0.519 [0.425–0.614] | 0.411 [0.332–0.497] | 0.459 [0.377–0.545] | 0.832 [0.776–0.890] | 0.0% | 50,399p/14,195o | — |
| groq-llama-70b/n20 | llama-3.3-70b-versatile | 20 | prompt-json | 0.706 [0.625–0.778] | 0.339 [0.262–0.419] | 0.458 [0.375–0.535] | 0.929 [0.877–0.973] | 36.0% | 62,626p/7,118o | DQ (parse gate), PARTIAL |
| gemini-flash/n50 | gemini-2.5-flash | 50 | gemini-responseSchema | 0.000 [0.000–0.000] | 0.000 [0.000–0.000] | 0.000 [0.000–0.000] | 0.000 [0.000–0.000] | 100.0% | 0p/0o | DQ (parse gate), PARTIAL |

## Diagnostics (unscored, per the protocol)

| run | zero-share (gold 49.2%) | candidate emission (gold 5.1% of mentions) | candidate overlap with gold's 11 | cost USD |
|---|---|---|---|---|
| gold-assist (reference) | 44.8% | 4.8% | 7/11 (cutscenes, factions, grind, originality, romance, unique, worn-out) | 0.0000 |
| gemini-3-flash/n20 | 43.6% | 7.3% | 5/11 (cutscenes, grind, romance, specialists, stealth) | 0.0000 |
| gemini-3.5-flash/n50 | 50.0% | 4.7% | 4/11 (cutscenes, grind, romance, stealth) | 0.0000 |
| gemini-3-flash/n50 | 46.8% | 5.1% | 5/11 (grind, originality, romance, specialists, stealth) | 0.0000 |
| gemini-3.5-flash/n20 | 48.0% | 6.0% | 7/11 (achievements, cutscenes, factions, grind, originality, romance, specialists) | 0.0000 |
| gemini-flash/n20 | 45.6% | 12.7% | 6/11 (achievements, cutscenes, factions, grind, originality, stealth) | 0.0000 |
| gemini-3.1-flash-lite/n10 | 44.0% | 4.1% | 4/11 (grind, originality, romance, specialists) | 0.0000 |
| deepseek-v4-flash/n20 | 46.4% | 2.4% | 5/11 (achievements, grind, originality, romance, specialists) | 0.0389 |
| gemini-3.1-flash-lite/n20 | 46.0% | 2.4% | 2/11 (grind, romance) | 0.0000 |
| hunyuan-3/n20 | 44.4% | 5.0% | 4/11 (factions, grind, originality, romance) | 0.0000 |
| gemini-3.1-flash-lite/n50 | 46.4% | 0.6% | 1/11 (romance) | 0.0000 |
| hunyuan-3/n50 | 42.8% | 2.0% | 1/11 (romance) | 0.0000 |
| gemini-3.1-flash-lite/n5 | 45.6% | 5.5% | 4/11 (cutscenes, grind, romance, specialists) | 0.0000 |
| mistral-large/n20 | 46.0% | 2.7% | 4/11 (achievements, grind, romance, stealth) | 0.0000 |
| mistral-medium/n20 | 44.4% | 2.2% | 4/11 (achievements, factions, grind, romance) | 0.0000 |
| mistral-large/n50 | 48.8% | 1.5% | 1/11 (stealth) | 0.0000 |
| mistral-medium/n50 | 47.2% | 0.7% | 1/11 (romance) | 0.0000 |
| mistral-small/n5 | 48.8% | 6.0% | 5/11 (achievements, cutscenes, grind, romance, stealth) | 0.0000 |
| ministral-14b/n20 | 49.2% | 4.6% | 2/11 (achievements, specialists) | 0.0000 |
| ministral-14b/n50 | 46.4% | 6.3% | 1/11 (factions) | 0.0000 |
| mistral-small/n10 | 47.6% | 3.9% | 3/11 (achievements, cutscenes, stealth) | 0.0000 |
| deepseek-v4-pro/n20 | 37.2% | 2.5% | 2/11 (grind, romance) | 0.2426 |
| mistral-small/n50 | 46.0% | 5.0% | 5/11 (achievements, cutscenes, romance, specialists, stealth) | 0.0000 |
| nemotron-ultra/n20 | 36.8% | 17.3% | 8/11 (achievements, cutscenes, endgame, factions, grind, originality, romance, stealth) | 0.0000 |
| mistral-small/n20 | 50.4% | 4.3% | 4/11 (cutscenes, romance, specialists, stealth) | 0.0000 |
| mistral-nemo/n20 | 41.2% | 4.6% | 4/11 (endgame, factions, originality, stealth) | 0.0000 |
| nemotron-ultra/n50 | 24.8% | 11.4% | 7/11 (achievements, cutscenes, endgame, factions, originality, romance, stealth) | 0.0000 |
| mistral-nemo/n50 | 38.8% | 3.3% | 2/11 (endgame, originality) | 0.0000 |
| groq-llama-70b/n20 | 27.2% | 5.3% | 2/11 (romance, specialists) | 0.0000 |
| gemini-flash/n50 | 0.0% | 0.0% | 0/11 | 0.0000 |

Notes: parse-failed reviews score as zero predictions, never excluded; salvage-parsed rows count as parsed (rates in each capture's manifest). Candidate-slot mentions are excluded from the score on both sides. N is per-candidate by design (the batch-size amendment) — read quality differences with N in view.
