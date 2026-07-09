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
(`reachability_local_windowed_baseline.json`). **Datacenter verdict: PENDING** —
run the `Steam reachability probe` workflow (GitHub Actions) after this lands on
main; its artifact becomes `reachability_datacenter_windowed_ghactions.json` and
this line gets replaced with the verdict.
