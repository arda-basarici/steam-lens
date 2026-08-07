# Smoke-test findings (M0) — 2026-07-09

The smoke-test milestone's three unknowns, answered before any design or build.
Probe code: this folder · raw payloads: `captures/` ·
verdict: **all three pass; the live-compute premise stands.**

## 1. Datacenter-IP reachability — PASS (the fatal unknown, cleared)

Same probe code run from a residential IP and a GitHub Actions runner (Azure,
egress 20.102.223.147): identical data — HTTP 200 throughout, full 100-review
pages over a 5-page sequential cursor walk, identical histogram — and the
datacenter run was 3–6× *faster* (~300–500 ms/page vs. ~1–2.7 s residential).
No blocking, throttling, or challenge pages.
(`reachability_local_baseline.json` · `reachability_datacenter_ghactions.json`)

*Limits of the claim:* one run, five pages — reachability proven, the full
~200-req/5-min budget not stress-tested from a datacenter; GH Actions is Azure,
not the eventual host's IP range — the deployment milestone (M3) rechecks from
whatever host its fork picks (handoff rule, unchanged). The intended vehicle,
a free HF Docker Space, was repriced behind PRO mid-milestone — see the
2026-07-09 REPORT_NOTES entry and the DESIGN hosting question, both updated.

## 2. Histogram granularity — monthly history, daily last-30, age-dependent

`appreviewhistogram` returns two sections, same schema for every game probed
(TF2 ~1M reviews · a 30-day-old 57k-review top seller · a day-old 1-review
indie; buckets are `{date, recommendations_up, recommendations_down}`):

- `rollups`: full history; `rollup_type` **varies by game age** — `month` for
  TF2 (190 buckets to 2010), `week` for both young games. Not hardcodable.
- `recent`: daily buckets, exactly the trailing 30 days, always present.

Design consequence: the event detector must be granularity-aware; historic
events localize to a month (week for young games) from the histogram alone —
finer localization needs review-level timestamps via the sampler's date-window
params. Parked oddity: TF2's histogram starts 2010-10, predating Steam reviews'
public launch. (`histogram_old_large_440.json` · `histogram_recent_4704690.json`
· `histogram_tiny_indie_4773260.json`)

## 3. Off-topic (review-bomb) flag shape — per-window, and blunter than expected

Probed on Borderlands 2 (49520), the first officially marked bomb (Apr 2019):

- **Valve's annotation is per-window, not per-review:** top-level `past_events`
  = `[{type: 0, start_date, end_date}]` (here Apr 3–15 2019); present only on
  affected games. No per-review flag exists anywhere in the payloads.
- **Histogram buckets include bomb reviews unconditionally** (April 2019 bucket:
  3365 up / 2821 down vs. ~950/month neighbors) — detection signal intact.
- **The default review listing blanks the entire marked window** — zero reviews,
  zero counts, legitimate reviews included (the window actually splits 3462 up /
  3576 down); `filter_offtopic_activity=0` restores all 7,038.

Design consequence (for the system-flow session, flagged not solved): default-
filtered sampling has holes exactly where events live — the sampler likely
fetches unfiltered and carries `past_events` as metadata, and the two-track
numbers need a documented stance on marked-window reviews.
(`offtopic_hist_default.json` · `offtopic_reviews_default.json` ·
`offtopic_reviews_include_offtopic.json`)

---

# Extraction+eval entry findings (M1) — 2026-07-09

The two verification debts the system-flow panel surfaced, cleared before the
milestone opens. Probe code: this folder · raw payloads: `captures/`.

## 4. Corpus off-topic exposure — CLEAN, by coverage geometry, not by luck of the fetch

Refetched `appreviewhistogram` + `past_events` for all 50 corpus games
(`corpus_offtopic_probe.py`; 298,553 corpus reviews counted, matching the frozen
fetch manifest):

- **5 of 50 games carry Valve-marked windows** — Euro Truck Simulator 2
  (Feb–Jul 2022), Europa Universalis IV (Feb–Mar 2025), Rocket League (May 2019),
  Shadow of the Tomb Raider (Oct 2018), Cyberpunk 2077 (Mar 2022). Each window
  shows real review volume in the histogram (ETS2's spans ~36k recommendations).
- **Every marked window predates its game's corpus coverage** — the prior
  pipeline's recent-first capped walk reaches back weeks-to-months for these
  games, and all five windows are older. **Zero corpus reviews (0.000%) fall
  inside marked windows.** The corpus can't be bomb-blanked where it holds no
  reviews to blank. (`corpus_offtopic_summary.json` · `corpus_hist_<appid>.json`
  for the five flagged games)
- **The blanking mechanism is real, though — confirmed on the plain default
  walk** (`default_walk_blanking_probe.py`). The corpus couldn't testify (no
  overlap), so the probe walked EUIV's default listing — the prior pipeline's
  exact request shape, no date params, no off-topic flag — newest→oldest
  straight past its marked window: **76 pages, 7,597 reviews seen, 0 inside the
  window**, while the same window unfiltered holds **1,892 reviews (881 up /
  1,011 down)** and the windowed default reports 0. A plain default cursor walk
  silently skips marked windows, with no signal in the payload that anything was
  dropped. (`defaultwalk_summary_236850.json` ·
  `defaultwalk_windowed_default_236850.json` ·
  `defaultwalk_windowed_unfiltered_236850.json`)

**Backfill recommendation: none.** Nothing inside corpus coverage was blanked, so
there is nothing to backfill. The forward-looking rule the mechanism finding
hardens: *every* future fetch — the production sampler and any corpus refresh —
carries `filter_offtopic_activity=0`, which is already the settled marked-window
stance (DESIGN); a default fetch is now a proven data-integrity bug, not a
style choice. One knock-on for the sampling study (M2): the marked-share floor
can't be tuned on this corpus (it contains no marked-window reviews); tuning
needs windows fetched fresh via the windowed unfiltered path.

*Flagged in passing (FIXLOG'd, out of scope here):* corpus per-game coverage is
far thinner and more variable than "10k most recent" — the prior fetcher stopped
on any short page, so e.g. Counter-Strike 2 holds 79 reviews spanning a single
day and Portal 2 1,359 over 19 days. Matters for extraction+eval sample framing.

## 5. Windowed params from a datacenter — local baseline green, datacenter leg pending

The production primary path (undocumented `start_date`/`end_date` +
`filter_offtopic_activity=0`, composed with cursor pagination) had never run from
a datacenter IP — the smoke tests exercised only the documented cursor path. The
reachability probe (`reachability/app.py`, same dual-mode code) is extended with:

- a **windowed cursor walk** — one full TF2 month, 2 pages × 100 reviews, every
  timestamp inside the window;
- a **marked-window blank/restore check** on Borderlands 2 — window taken from
  the live histogram's `past_events`, default listing must return 0, the
  unfiltered flag must restore it;
- two new verdict booleans: `windowed_ok`, `offtopic_filter_ok`.

Residential baseline: both true, all statuses 200
(`reachability_local_windowed_baseline.json`). **Datacenter verdict: PASS** — the
same probe from a GitHub Actions runner (Azure, egress 20.51.199.19) returned
identical behavior: `windowed_ok` and `offtopic_filter_ok` both true, all
statuses 200, windowed pages at ~210–310 ms (vs. ~640–670 ms residential), the
marked window blanked by default and fully restored by the flag. The production
primary path is verified from a datacenter IP.
(`reachability_datacenter_windowed_ghactions.json`)

*Limits of the claim, unchanged from the smoke tests:* one run; GH Actions is
Azure, not the eventual host's IP range — the deployment milestone (M3) rechecks
from whatever host its fork picks.

---

# Sampling-study findings (M2) — 2026-08-03

## 6. Bomb-pick verification — all three marks real, English pools sized

The fresh-buy session's gate (`bomb_pick_probe.py`): the step-8 bomb picks were
nominated by web research, and nomination is not evidence — per pick, does the
`past_events` mark exist, does *this* game's window blank-and-restore, and how
large is the in-window English pool the label buy actually consumes (windowed
totals-only queries; a sample page checks every timestamp lands in-window).

| game | marked window (wire) | default | unfiltered | English |
|---|---|---:|---:|---:|
| Borderlands 2 | 2019-04-03 → 04-15 | 0 | 7,030 | 4,085 |
| Book of Demons | 2022-03-01 → **ongoing** (`end_date=0`) | 0 | 2,349 | 823 |
| The Witcher 3 | 2022-03-03 → 03-17 | 0 | 8,992 | 1,546 |

- **All three marks exist (type 0), all three windows blank by default and
  restore under the flag** — the mechanism now confirmed on every pick, not a
  stand-in. Sample pages: 100/100 timestamps in-window on each.
- **Combined English pool 6,454** against the mixing experiment's ~1–2k
  appetite — the buy is not supply-constrained, and the three games' English
  shares (58% / 35% / 17%) mean blends can vary the source mix.
- **Two research claims corrected by the wire:** The Witcher 3's marked span is
  **14 days**, not the reported ~9 months; Book of Demons' mark is **ongoing**
  (`end_date=0` — the first such case this project has fetched; the buy must
  substitute a concrete end, and `fetch_window` requires one anyway).
- *Probe artifact, not a data problem:* the histogram cross-check reads 0 for
  sub-month windows — rollup buckets are stamped at period start, so a window
  opening mid-month contains no bucket date. The check's real purpose held:
  every windowed total is window-sized, not whole-game-sized, so the
  undocumented params are honored by `query_summary`.

(`bombpick_summary.json` · `bombpick_hist_<appid>.json` ·
`bombpick_page_<appid>.json`)

## 6. The aspect-ontology probe — the emergent vocabulary is flat-tailed and game-specific; ruling: hybrid with a fixed core

The week-1 discriminator from the framing handoff: run open extraction (the model
names aspects freely) and read the vocabulary's shape. Method: 100 seeded-random
English reviews from each of 5 genre-diverse corpus games (ETS2 / Baldur's Gate 3 /
Rocket League / Stardew Valley / Cyberpunk 2077), single instrument
(gemini-2.5-flash, temperature 0, thinking disabled, prompt v1 — deliberately zero
example labels, so no vocabulary seeding), 34-review batches. Captures + provenance:
`captures/aspect_vocab/` (`extractions.jsonl`, `run_meta.json`, `label_groups.json`,
`build_groups.py`); analysis: `aspect_vocab_analysis.py`.

- **Raw shape:** 500 reviews → 704 aspect mentions, 406 distinct labels; top-15
  coverage 27%; 46% of reviews yield zero aspects (memes/bare verdicts).
- **Grouped shape (the decision-grade view, conservative LLM merging, human-reviewed
  mapping):** 406 labels collapse only to 313 groups — top-15 coverage 28%, top-50
  under 50%, and **52% of mentions live in groups appearing in exactly one game**
  (`coziness`/`farming` vs `realism`/`scenery` vs `dlc`/`night city believability`).
  Surface-form variance was NOT what flattened the curve; the tail is real,
  game-specific player vocabulary. 17 groups recur in ≥3 of 5 games — the natural
  fixed-core candidates (`gameplay, story, replayability, graphics, characters,
  bugs, multiplayer, music, relaxation, updates, combat, …`).
- **Verdict (pre-registered criterion fired):** a dozen-ish labels do NOT cover ~90%
  — **hybrid-with-fixed-core wins**; pure open stays dominated (pays normalization
  AND blurs the eval anchor). Ruling + runtime mechanics recorded in DESIGN.md
  (two-slot extraction, disclosed emergent stratum, offline gated promotion).

*Instrument facts learned in passing (feed the M1-exit cost table):* tier-0 Gemini
free keys give 5 RPM / 20 RPD **per model** on the main Flash lines (3.1-flash-lite:
15 RPM / 500 RPD — the free headroom lives in the lite tier; dashboard beats docs);
thinking models bill thoughts as output tokens (observed 7,865 thought tokens on one
10-review batch, 8× the answer — sticker price understates real cost).

*Limits of the claim:* one instrument (a second-instrument shape check is parked in
the stream FIXLOG, Grok's signup credit as candidate); English-only by design
(multilingual claims are out of scope); 500 reviews — coverage points are noisy but
the shape gap (28% vs the 90% criterion) dwarfs the noise; grouping is a reviewed
artifact, not a seeded computation (`label_groups.json` carries its provenance).

# Deployment findings (M3) — 2026-08-07

## 7. Whole-game English totals read — PASS, exact against row-counted references

The serving size rule branches on the English pool ("English-only stands
everywhere"), and the only pre-fetch way to know it is a totals-only read
(`num_per_page=0`) with `language=english` over the production param base.
The bomb-pick probe had validated that read *windowed*; this one validates it
whole-game, against the fresh-buy run's independently row-counted English
totals (whole-life fetches, 2026-08-03):

- Sword and Fairy Inn 2: wire 36 vs reference 36 — **exact**; all-language
  2,278 vs 2,277 (+1, four days of drift).
- Dragonkin: The Banished: 1,318 vs 1,312 (+6) · Talisman: 6,110 vs 6,108 (+2).
- TF2 as the big-game coherence check: English 739,856 of 1,245,415.

The branch preview shows the ruling doing its work: both long-tail games FLIP
to take-all under English branching (all-language branching would sample
them — the certified behavior for a tiny English pool is take-all), Talisman
correctly samples either way. (`english_totals_probe.py` ·
`captures/english_totals_summary.json`)

*Limits of the claim:* one snapshot from a residential IP; the reference
comparison covers pools up to ~10k (TF2 is coherence-only, no reference);
Steam's English count may include empty-text rows the usable filter later
drops — the branch reads Steam's claim, the realized sample is counted and
disclosed at fetch time.
