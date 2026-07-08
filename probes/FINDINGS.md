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
