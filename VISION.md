# SteamLens — Vision

The fixed vision for the project: what the product is, what it proves, how it is built,
and the milestone path — the document the design phase builds against. Decisions carry
their reasoning inline; the full deliberation record lives in the private panel archive
(design panel of 2026-07-07: three blind proposals, three adversarial critiques, six
arbitrated rulings).

*Vision fixed 2026-07-07 · evolved from the seed vision (Notion Projects card, 2026-07-02)
· name provisional: **SteamLens** (repo `steam-lens`; folder rename pending).*

---

## The product

**Type a game name. Watch an AI investigate its reviews. Get a report you can check.**

SteamLens answers the question every store page fails to answer: *what do players
actually like and dislike about this game — and is its review score telling the truth
right now?* One score hides everything interesting: the praised combat and the broken
netcode, the launch disaster that got patched, the spike of anger in March that was
about regional pricing, not the game. SteamLens reads the reviews the way an analyst
would — and, unlike every AI summary on the market, it shows its receipts and publishes
its own error rate.

### A session, walked through

A visitor lands on the page and types "Deep Rock Galactic." It's precomputed — the
report appears instantly, timestamped, with a one-line provenance stamp.

They type an obscure indie game instead. Cold path — and this is where SteamLens stops
looking like a dashboard and starts looking like an investigator. The screen narrates,
live:

```
▸ Resolving game… found: <game> (appid 1234567) — 41,203 reviews, 71% positive
▸ Review timeline fetched — one unusual episode detected: Nov 2024, negative spike (3.4× baseline)
▸ Sampling 500 reviews across the game's lifetime… 500/500
▸ Classifying batch 12/25… aspects so far: performance (−), co-op (+), progression (mixed)
▸ Hypothesis: the Nov 2024 spike may relate to the "1.3 rework" update — pulling 80
  reviews from that window to verify…
▸ Confirmed: 62 of 80 window reviews criticize the progression rework. Marking as
  explained event.
▸ Composing report…
```

The narration is honest by construction: suspicions are labeled as hypotheses and only
promoted to findings after they survive a check. A three-minute cold analysis is not a
loading screen — it is the product demonstrating how it thinks.

### The report

Four sections, every claim carrying its evidence:

1. **The verdict panel.** What players love, what they criticize, in plain prose — each
   claim stamped with its support: *"Performance criticized — 214 of 800 sampled reviews
   (27%, ±3)"*. Claims below an evidence floor render as "weak evidence," greyed, never
   silently dropped or confidently shown.
2. **The aspect breakdown.** Strengths and weaknesses by aspect (combat, story, price,
   performance, …), each expandable to its verbatim quotes — real review text, linked,
   never paraphrased into existence. A claim whose quote cannot be verified against the
   source review is never displayed.
3. **The timeline and its events.** The full review history as a chart (all languages,
   all reviews — this layer counts rather than reads), with detected episodes marked:
   *"Nov 2024 — negative spike, 3.4× baseline — explained: progression rework backlash
   (62/80 window reviews; update '1.3 rework' released Nov 12)."* Events that could not
   be explained say so: *"spike detected; reviews from this period predominantly
   non-English — explanation withheld."*
4. **The trust panel.** The part almost no product ships: sample size vs. population,
   sampling policy and window, language mix ("analysis covers the English 38% of this
   game's reviews"), cache age, and the system's own measured accuracy — scoped honestly:
   *"In offline evaluation on 50 games (English), this system's extraction precision was
   X% — methodology →"*. The app cites its own audit.

### What the product refuses to do

No fake-review verdicts (unverifiable accusation — it would make every other claim less
trustworthy). No confident answers from unread populations (the language guard). No
uncertainty theater — no "AI may make mistakes" banner; every caveat is a number attached
to a specific claim.

---

## Why it exists — the portfolio role

**The keystone of the portfolio's next phase.** Four completed projects (simulation
statistics, classical-ML evaluation, a 298k-review data pipeline, deep-RL with a
diagnosed negative result) established one brand: *rigorous evaluation — knowing whether
a result is real.* All four end at PDF reports. SteamLens converts that brand into the
missing evidence class: a **deployed, clickable, LLM-powered system** — closing
deployment, served APIs, CI/CD, databases, NLP, and GenAI in one project, each *through*
the evaluation differentiator rather than beside it.

The spine sentence: **not "an app that reads reviews" — "an AI system that reads
reviews, investigates what it finds, and can prove how well it works — including where
it doesn't."**

The market context (verified against current provider guidance and practitioner canon,
2026-07-07): evaluating LLM systems is among the market's most-demanded and most-skipped
disciplines. The evaluation design below is standard-to-above-standard practice —
visibly executing what most teams skip is the positioning, made into a product.

---

## The two-track engine

The architecture's one load-bearing idea, and the guard that keeps the product honest:

**The survey track — where every number comes from.** A fixed, representative,
size-budgeted sample of reviews (policy chosen by the offline sampling study) →
**per-review classification** (each review independently tagged for aspects + polarity)
→ deterministic aggregation into counts, shares, and intervals → the LLM phrases the
narrative *over* those aggregates, never inventing them. Per-review classification is a
committed architectural decision, not a detail: it is what makes evidence counts
computable, the sampling study valid (labels can be resampled offline), and every claim
attributable to specific reviews.

**The investigation track — where every story comes from.** An agentic loop, born from
the observation that a fixed sample structurally cannot explain anomalies (a 500-review
sample of a 200k-review game holds ~a dozen reviews from any given spike). Signals — the
timeline histogram, the survey's aspect flags — generate hypotheses; each round makes a
*targeted* fetch (a time-windowed pull of the suspect period, a filtered pull of a
suspect stratum), checks the hypothesis against what it finds, and either promotes it to
an explained event or reports it unexplained. Rounds are hard-capped (2–3 per query)
inside a per-query budget.

**The one rule, stated once:** numbers from the survey, stories from the investigation,
and the UI labels which is which. The investigation track deliberately over-samples the
unusual — its fetches never feed the percentages. This single boundary is what lets an
adaptive, curiosity-driven loop coexist with defensible statistics.

**The narrated runtime.** Both tracks stream their progress (server-sent events) as the
session walkthrough shows. The narration is part of the trust design, not decoration:
hypotheses are labeled as hypotheses, findings appear only after their check passes, and
the latency problem becomes the product's most distinctive feature — users don't abandon
a process they can watch thinking.

---

## The evaluation spine

**The trust chain.** Four layers, each earning the next: (1) *mechanical grounding* —
every claim must cite verbatim quotes from identified reviews; a program verifies the
quote exists (measured as **fabricated-quote rate** — named precisely; it is not a full
hallucination measure); (2) *the human anchor* — ~250 reviews blind-labeled by the
builder **before** seeing model output, with a later self-relabel subset to measure
labeling consistency; the single-annotator limitation is stated in every artifact rather
than hidden; (3) *the calibrated judge* — an LLM judge is trusted only after its
agreement with the human labels is measured, **reported per category** (agreement is
known to vary by item type), and it scales the evaluation carrying its measured error;
(4) *misattribution audit* — the failure grounding cannot catch (real quote, wrong
interpretation — sarcasm is Steam's native dialect) is measured by human audit of
~100 claims. Adversarial inputs (prompt-injection strings seeded among eval canaries)
are part of the harness — a public app whose input is attacker-controlled text gets
probed for exactly that.

**The sampling study.** The 298k-review corpus from the prior pipeline project is a
local population: every runtime-expressible sampling policy is simulated against it —
classify once per review, then resample stored labels — measuring convergence of
aspect-level conclusions at 300 / 1k / 3k versus the (stated, imperfect) full-corpus
reference. Both the windowed-stratified policy and its documented-params fallback get
measured, so the runtime's honesty line quotes a measured tolerance, not a hope. Scope
caveat carried openly: the corpus is 50 popular games in a recent window — long-tail
transfer is characterized, not assumed.

**The investigation's own eval.** Explained events are checked against the game's public
update history (did the detector fire where a patch landed; does the explanation match
the patch's subject?) — an external, non-circular anchor. Valve's off-topic flags serve
as a comparison signal for the review-bombing subtype only, never as ground truth. The
language-coverage guard is itself a tested behavior: majority-non-English windows must
yield "explanation withheld," not confident fiction.

**Evals in CI, honestly.** The eval harness runs on prompt/model changes as a **soft
gate** — tolerance bands and trend reporting, not a hard build-fail on a noisy metric
(LLM eval numbers fluctuate run-to-run; a red-X-then-override history is worse than no
gate).

---

## Production shape

| Component | Decision |
|---|---|
| Serving | **FastAPI** REST + SSE streaming; hand-rolled JS frontend (3 years of game-dev JS — reads better than a Streamlit default and costs this builder little) |
| Data | **SQLite** — report cache + precompute store; persistence mechanism on the ephemeral host decided in design (bake-into-image / dataset sync / paid storage) |
| Deploy | **Docker** → free container host (HF Spaces Docker SDK primary candidate) with keep-alive ping; GitHub Actions **CI**: lint + tests + image build + eval soft-gate |
| LLM access | **Provider-agnostic thin client** (one seam, two providers tested in the M1 cost table), **concurrency-capable classify stage** (parallelism is a config value, not an architecture) |
| Steam access | **One sampler module owns all review access** — windowed date-params as primary path, documented cursor-walk as automatic fallback, every report's provenance stating which path ran |
| Cost control | Hard monthly LLM cap (~$5–10 if paid tier chosen), per-query round/budget caps, daily analysis budget with an honest "at capacity — cached reports available" state |

**The latency contract (conditional by design).** Cached: seconds (host awake). Cold
survey: ~30–60s on a paid cheap tier, ~2–4 min on a free tier — the tier is chosen at
the end of the first milestone from its measured cost/quality table, not guessed now.
Investigation rounds add narrated minutes, capped. The narration makes the cold path a
feature; the cache makes it rare; the contract never promises a number the undecided
tier could break.

**Cost reality, stated:** a fresh 500-review analysis costs cents on a cheap paid model;
the monthly ceiling is enforced provider-side and app-side, and the app degrades to
cached-only service rather than failing silently.

---

## Decisions ledger — fixed at vision level

- **The human anchor.** ~250 blind-labeled reviews + self-relabel consistency check +
  per-category judge calibration. The alternative — judge-only evaluation — is the
  industry's named anti-pattern and would hollow the project's central claim.
- **English-first, all-language counts.** Extraction reads English (the language the
  eval can verify); counting layers (timeline, totals, score context) always cover all
  languages; every report discloses the language mix; event explanations are withheld
  with a stated reason when the window is majority non-English. Turkish: informal
  spot-check only — a headline TR eval would be statistically hollow at gold-set scale.
  Multilingual extraction is a post-launch experiment, marked unverified if shipped.
- **Per-review classification over holistic synthesis.** Committed early because three
  independent critiques found everything downstream — evidence counts, sampling-study
  validity, cost/latency arithmetic — silently depends on it.
- **Windowed access in production, behind the sampler boundary.** The undocumented
  date params are the investigation track's enabler; volatility is absorbed by the
  boundary + fallback, not by refusing the capability (the documented surface is itself
  buggy — refusing bought less safety than it cost).
- **Tier deferral, made safe.** Free-vs-paid LLM tier decided at M1 exit from measured
  data; deferral is safe because the provider seam, concurrency-capable pipeline,
  narrated progress, and budget caps are built regardless.
- **Events, not accusations.** The anomaly layer detects and explains *episodes* (what
  happened, when, about what) — statistically over the full-population histogram, with
  targeted reads for explanation. Fake-review detection is cut entirely: no ground
  truth, unfalsifiable, reputational landmine. *(Tombstone: "fake-looking patterns" from
  the seed vision — cut 2026-07-07; the review-bombing subtype survives inside the
  events framing with Valve's flags as comparison signal.)*
- **Copy-and-adapt reuse.** The prior pipeline's battle-tested fetcher internals (retry
  discipline, cursor handling, short-batch defense) are lifted into a fresh
  `steam_client` module; the frozen repo is never imported (a portfolio repo must run
  standalone) and never rewritten from scratch (the API-quirk knowledge is paid for).
- **The post ships with the milestone.** Every milestone's public artifact ships when
  the milestone does, imperfect — the standing counterweight to the known
  over-investment pattern. No milestone is "done pending writing."

---

## Milestones — four mini-projects and a smoke-test day

Each milestone is independently meaningful with its own postable artifact; budgets are
stated honestly (adversarial critique priced the optimistic versions at 1.5–2×).

**M0 — Smoke tests (days).** The hello-world container deployed to the target host,
making a real Steam API call from datacenter IPs — the one assumption whose failure
would kill the product identity, tested for ~a day's work before anything is built on
it. Also verified: histogram granularity, off-topic-flag data shape. Plus repo bootstrap
per the standing checklist (public from first commit, gitleaks hook, CI skeleton).

**M1 — "Does the LLM actually work?" (2–3 weeks, declared honestly).** The extraction
pipeline + the full trust chain, offline, on the existing corpus. Week-1 decision:
the aspect ontology (open vs. fixed vs. hybrid vocabulary — the eval is ill-defined
until this is chosen). Success: a measured error profile — fabricated-quote rate,
misattribution rate, pooled precision/recall against the gold set with per-category
judge agreement — plus the 2–3-model cost table and an error taxonomy. **Artifact:** the
bridge post: *"How do you know an LLM system works? I measured mine."*

**M2 — "How few reviews do you need?" (1–1.5 weeks).** The sampling study, offline,
against the corpus. Success: a chosen runtime policy with measured convergence/bias for
both the windowed path and the fallback, long-tail transfer characterized. **Artifact:**
the sampling-honesty post: *"You don't need 250k reviews — measured."*

**M3 — The deployed product (2 weeks).** Survey track live at a public URL: FastAPI +
frontend + narrated streaming + SQLite cache + budget caps + CI with eval soft-gate.
Success: a stranger uses it unassisted; cold path within the contract; cached games
instant; provenance on everything. Under schedule pressure the trust panel is protected
and investigation features move to M4 — the differentiator is never cut to save the
commodity. **Artifact:** the URL + launch post.

**M4 — The investigator (1.5–2 weeks).** The agentic loop shipped into the live product:
detect → hypothesize → targeted fetch → verify → explain, round-capped, narrated, with
the language-coverage guard active. Success: explained events verified against patch
history on a curated set; the Valve-flag comparison sub-study for the bombing subtype.
**Artifact:** the post: *"I built an AI investigator and measured whether its
explanations hold up."*

**Envelope: 6–9 weeks (working target 6).**

---

## Deferred to the design phase (with triggers)

- **Aspect ontology** — decided week 1 of M1 (the eval harness blocks on it).
- **Cache persistence mechanism** on an ephemeral free host — decided in M3 design.
- **LLM tier** (free vs. cheap paid) — decided at M1 exit from the measured cost table.
- **Exact sampling policy and sizes** — M2's output, by construction.
- **System-flow detail** (module boundaries, seams, data contracts) — the design phase
  proper, against this vision.

## Known risks, named

Datacenter-IP reachability (retired at M0, deliberately first) · milestone overrun (the
declared budgets *are* the honest estimate; the anti-polish rule guards the tail) ·
single-annotator gold set (blind protocol, consistency check, stated limitation — and
the first interview question we answer before it's asked) · prompt injection (in the
eval harness from M1, not an afterthought) · free-host sleep and ephemerality (keep-alive
+ persistence decision in M3) · API volatility (the sampler boundary exists precisely
for this) · free-tier LLM rug-pulls (provider seam + measured fallback).
