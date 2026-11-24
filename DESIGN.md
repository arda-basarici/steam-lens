# DESIGN — steam-lens

What was built and why: the decisions and their reasoning, as a narrative
snapshot of the current design, edited in place as decisions evolve. **This document is
the living source of truth for decisions from the vision phase onward**; `VISION.md` is
the fixed vision-phase snapshot (2026-07-07) and is not updated as the design moves.
How it's built → ARCHITECTURE; the pitch → README. Executed experiments appear here
as conclusions with citations to their runs of record.

*Living snapshot · last updated 2026-11-19 · the project closed complete at
deployment (M3), live at steamlens.ardabasarici.dev; the chat milestone (M4) is
reopened as a recommender tab, whose steps are built and whose page is not (the
recommender chat section).*

---

## The map

One line per section, what's decided there:

- **Objective** — the product, and the success criterion every displayed claim must meet.
- **The evaluation spine** — trust earned in layers: the human gold anchor first, the calibrated judge on it, production under both.
- **The two-track engine** — per-review classification, deterministic aggregation; numbers and stories never mix.
- **The system flow** — module boundaries, the import law, the seams and the contracts crossing them.
- **Data access** — Steam's narrow, buggy, sufficient API, and the one sampler door that owns all review access.
- **The labeling engine** — the provider seam, the classify stage, the store, and the label pool's two consumers.
- **Choosing the labeler** — the bake-off: measured, not reputed; the per-stage tier rule.
- **The codebook** — the hybrid vocabulary: a pinned core, candidates preserved in reviewer wording.
- **The eval harness** — the scoring core, certification, and the exact-digit evals-in-CI gate.
- **The judge** — the second annotator: cross-family by rule, calibrated on gold before use.
- **The redirect & the product frame** — the investigator deferred, the grounded chat as the story channel, the M3 closure ruling, and the chat reopened as a recommender tab.
- **The sampling study (M2)** — the certified draw: the windowed policy, the measured tolerances, the shipped interval rule.
- **Deployment (M3)** — the serving skeleton · persistence · model prose · episode markers · the frontend · the box · the spend breaker · observability.
- **The recommender chat (M4)** — the steps of a turn and a first, unlisted tab built: fit to stated requirements, numbers read across games in groups, a fixed pipeline with the model judging inside bounds code checks, keyword retrieval first and the vector comparison as a committed stage.
- **Standing rules · Scope & non-goals · Open questions** — what always holds, what's deliberately out, what's parked with a trigger.

---

## Objective

An app where entering a game returns what players actually like and dislike (aspect-
level strengths/weaknesses with verbatim evidence and the review timeline),
computed live at request time on real Steam data, with a rigorous, honest
evaluation of whether the LLM doing the reading is actually right. The designed next
channel is a chat tab that recommends from the library of measured reports and answers
follow-up questions from a game's stored reviews (the recommender chat section; designed
2026-11-14, built as an unlisted first stage). **Success
criterion:** a stranger uses the deployed app unassisted and every claim they see is
attributable: to specific reviews (quotes), to a measured sampling tolerance, or to a
published error rate; and each shipped milestone ships a standalone postable
artifact. *Met at the M3 closure (2026-08-12): the app is live and public, and every
displayed claim carries its quote, its tolerance, or its published error rate.*

---

## The evaluation spine — trust must be earned in layers

**The human anchor.** All automatic checks fail precisely at interpretation of meaning:
grounding passes a sarcastic quote read upside-down; consistency passes a consistently
wrong system; an unvalidated LLM judge is a model grading its own blind spots. So the
eval anchors on ~250 reviews drafted by an assist model, with every label adjudicated
by a single annotator *before* any candidate model was scored and the assist model
excluded from the candidates, and a later self-relabel subset measuring labeling
consistency. Judge-only evaluation
was rejected as the industry's named anti-pattern (verified against current provider
guidance and practitioner canon, 2026-07-07); the single-annotator limitation is stated
in every artifact rather than hidden.

**The calibrated judge.** An LLM judge is used only after its agreement with the human
labels is measured (reported per category, since agreement varies by item type), and
scaled numbers carry the judge's measured error.

**Precise metric naming.** The mechanical quote-check measures **fabricated-quote
rate**; it is deliberately not called a hallucination rate, because a real quote
attached to a wrong reading passes it. That failure class (misattribution: sarcasm is
Steam's native dialect) is measured separately by human audit of ~100 claims.
Adversarial inputs are a standing harness requirement (the product's entire input
is attacker-controlled text), met at deployment (M3) by the prompt-injection canary
set (its own section under Deployment): beacon-scored synthetic attacks over both
model surfaces, the render-side walls gating deterministically in CI. Building it
was deliberately deferred until the first surface rendering model prose existed,
on the same grounds as the numeric-grounding check.

**Evals gate hard only where determinism makes it honest** (evolved from the
vision-phase "gate softly" ruling). A hard build-fail on a noisy live LLM metric
stays rejected (a red-X-then-override history is worse than no gate), so
fresh-output harness runs report with tolerance bands, and tolerance bands became
the label re-buy rule. The CI gate as built re-scores *stored* runs of record
deterministically, where exact-digit failure *is* honest (the evals-in-CI
decision): soft where the metric is noisy, hard where it cannot be.

---

## The two-track engine — adaptive curiosity without corrupted statistics

**Per-review classification over holistic synthesis.** Each sampled review is
independently classified (aspects + polarity), then deterministically aggregated; the
LLM phrases narrative *over* the aggregates. Holistic read-the-sample-write-the-report
was rejected because evidence counts become uncountable, the sampling study loses its
object (stored per-review labels are what offline resampling resamples), and cost/
latency stop being analyzable.

**The survey/investigation split.** A fixed representative sample produces every
displayed number; an agentic investigation loop (hypotheses from the timeline and
survey signals, targeted windowed fetches, verify-then-explain, hard round caps)
produces every story. **The one rule: the investigation's deliberately biased fetches
never feed the percentages.** Without this rule the adaptive loop (which hunts the
unusual by design) would silently poison the statistics it sits beside; with it, an
investigator and defensible statistics coexist. Born from a real constraint: a fixed
500-review sample of a 200k-review game holds ~a dozen reviews from any spike; no
representative sample can explain an anomaly.

**The narrated runtime.** Both tracks stream progress; suspicions are labeled
hypotheses until their check passes. This is a trust feature first (the uncertainty
discipline extended to the process itself) and a latency solution second (a watchable
investigation replaces a spinner; minutes become acceptable).

*Redirect 2026-07-27: the story channel changed instruments: the agentic investigation
loop is deferred with its milestone, and a grounded RAG chat over labeled reviews
produces the stories instead. The one rule survives translated: chat answers quote
retrieved reviews and never mint numbers. See "The redirect & the product frame".*

---

## The system flow — module boundaries, seams, contracts

Settled 2026-07-09. The decisions and their reasoning; the module map itself lives in
ARCHITECTURE.md.

**Four strata, one import law.** Plain-data contracts (import nothing) → pure core
transforms → effect shells (Steam client, LLM client, store, narration sinks) →
orchestrator and entry shells (pipeline runners, serving, CLI, study drivers). Core
never imports a shell; the entry shells (the eval harness and the study drivers)
are import-forbidden to everything; a CI import-graph test asserts the whole table
and refuses to fail open (a package must declare its rank to exist, relative imports
are banned). Four independent design framings converged on this skeleton. The
build later inserted a generic run-machinery stratum between the doors and the entry
shells, after the full-base review (2026-07-27) showed the shells sharing that
machinery by reaching into each other's interiors instead; the as-built graph lives
in ARCHITECTURE.

**The sampling policy is core code, executed by shells.** A pure plan compiler turns
histogram + policy into a fetch plan; the Steam client executes plans against the live
API, the study runner executes the same plans against the corpus. The load-bearing
consideration: with policy logic inside the client shell, the sampling study (M2)
would certify a simulation while production ran a later reimplementation: a measured
tolerance describing code that never ships.

**Labels are a version-keyed pool, not sample property.** Per-review labels are keyed
by (review, model, prompt version, ontology version) and carry an origin tag (survey /
investigation / corpus). Aggregation takes a manifest + the pool + an explicit version
pin and folds only manifest members with survey origin. The alternative
(manifest-keyed labels) was rejected: strict
origin-checked aggregation rejects exactly the offline resampling the sampling study
exists to perform.

**Two-track enforcement is defense-in-depth, never "impossible."** Every claimed
structural impossibility fell to a concrete bypass under critique. The honest
guarantee, adopted: independent walls (distinct container types at the sampler seam
(only the survey draw mints a sample manifest; the investigation's window fetch
returns a manifest-less type), the store's membership join carrying an origin
predicate, the CI import test) plus origin tags making any leak auditable after the
fact. "Impossible" is banned vocabulary in these docs.

**Numbers in prose are grounded like quotes.** Quote grounding cannot catch a
phrasing model writing "roughly 40%" over a 27% aggregate, or laundering an
investigation count into a percentage-shaped sentence. A numeric-grounding check
joins report composition:
every numeral in rendered narrative must match a value in the aggregates or events the
claim cites. Harness-side at extraction+eval (M1); a runtime gate at deployment (M3).

**Narration emits from the orchestrator layer.** Core transforms return data; the
stage/runner shells emit typed narration events between steps (batch-progress loops
live in the stage layer). Hypothesis→finding promotion is a typed status transition,
and a finding event is constructible only from a verified conclusion; the honesty
rule lives in the type, from the first offline console sink onward.

**Budget enforcement is a simple atomic counter.** Reserve-before-dispatch against
per-query / daily / monthly scopes; typed exhaustion errors become the honest
at-capacity state; the provider-side cap is the named backstop. A reserve-commit lease
machine with TTLs was rejected: its own failure modes reintroduce the race it
prevents. Eval spend is separated from the production cap in config.

**Contracts: rules now, fields later.** Fixed from day one: the import law, the
membership join + origin predicate, label-pool keying, provenance stamps on every
persisted artifact, the event-status enum. Record field lists freeze when their first
consumer lands; pre-building every contract at M1 was rejected after critique showed
a pre-built M4 contract already missing what M4's own success criterion needs. The
interval method for displayed shares was likewise deferred to the sampling study
(M2) alongside the policy: a stratified design changes the variance math, and
committing early would have shipped a wrong error bar in the product whose thesis
is honest error bars; the study delivered Wilson plus a regime-conditioned
allowance (the sampling-study rulings).

**Ops conventions adopted from practitioner canon, fit-tested:** prompts as versioned
files with content hashes; one spend-ledger table powering the caps, the M1 cost
table, and the ops dashboard; classify-call caching keyed on content (review-text hash
+ prompt + model + ontology versions); the gold set as versioned files in the repo.

### The contracts

**Frozen dataclasses, validated at the shell** (2026-07-09, the M1 foundation). The
plain-data spine is `@dataclass(frozen=True, slots=True)`: immutable, hashable,
closed-shape, importing nothing; validation lives in the shells, where a pydantic
parser turns raw external JSON (Steam payloads, LLM responses) into a clean contract,
so *trust no raw data* and *plain data crossing the seam* are both honored and pydantic
never reaches core.

**The classification envelope.** One review yields one `ReviewClassification`
(recording *that* it was classified, under which versions, with zero-or-more aspect
mentions) rather than a flat mention list. Under a flat shape the probe's
46%-yield-nothing reviews make an empty result indistinguishable from an unprocessed
one, which breaks resume/caching (empty reviews re-paid every run) and honest
denominators ("46% yield zero" is only statable if *processed* counts separately from
*produced mentions*).

**Dual sentiment.** The reviewer's overall verdict (`voted_up`) and per-aspect
sentiment are separate fields, because they dissociate constantly ("refunded it, but
the soundtrack is gorgeous") and both are needed to say things like "70% of negative
reviews still praise the art."

**Provenance is two-layer.** A universal run stamp (run id, code sha, config hash)
orthogonal to the content-cache key (model + prompt + ontology versions). The
narration/telemetry **sink is a Protocol in contracts**, so every shell inherits one
emission contract and the ops-story observability is structural from the first commit
rather than retrofitted.

---

## Data access — a narrow, buggy, sufficient API

*Verified data shapes from the smoke-test milestone (M0, 2026-07-09) live in
`probes/FINDINGS.md`: datacenter reachability PASS; histogram granularity
(monthly history + daily last-30, age-dependent rollup unit); off-topic flags
(per-window `past_events`, default listings blank whole marked windows).*

**One sampler module owns all review access.** Steam's keyless store API offers
sequential cursors (~200 req/5 min), an intermittent short-batch bug (no safe batch-size
constant; detect and retry instead), a cursor-loop bug on the helpfulness sort, and
undocumented date-window parameters (live-verified 2026-07-07) enabling temporal jumps.
The sampler uses **windowed access as the primary path** (it is the investigation
track's enabler), with the documented cursor-walk as automatic fallback and every
report's provenance stating which path ran. Refusing the undocumented params (considered
for volatility) was rejected: the documented surface is itself buggy, and the boundary +
fallback absorbs the volatility that refusal would only avoid by forfeiting the
product's best capability.

*Amendment 2026-10-23: Valve retired the store review endpoint on 2026-10-22
(announced 2026-10-02) and replaced it with the keyless WebAPI method
`IUserReviewsService/GetAppReviews`; the old URL answers a 302 to the store front,
and every fresh analysis failed at its first review read until the door moved.
The date-window parameters are documented on the new method (`date_range_start`,
`date_range_end`), so the volatility the fallback was built against has, for now,
resolved in the window's favor; the fallback and the per-response window check
stay as cheap insurance. The method's enums are integers and an unknown word
reads as the enum's zero (Helpful sort, Steam-only purchases), so the parameter
map is probed, not transliterated; the off-topic blanking bug is unchanged on the
new method (a marked-window day: 0 reviews by default, 958 restored). The
histogram, appdetails and storesearch endpoints stay on the store domain,
unannounced either way.*

**Marked-window reviews: include + disclose** (settled 2026-07-09). Survey
numbers include sampled reviews falling inside Valve-marked off-topic windows; the
trust panel discloses the count per window and links the timeline event. Excluding
would re-apply, by hand, the blunt blanking the unfiltered fetch exists to avoid (the
probe's marked window split ~50/50, thousands of legitimate reviews inside), and
per-review classification absorbs bomb reviews into the aspects they actually complain
about, while the story track owns the bomb *story*. Two amendments: (1)
**membership is derived at read time** from the freshest
`past_events` snapshot: Valve marks windows retroactively, so a fetch-time stamp goes
stale exactly when it matters; (2) a **marked-share floor**: past a threshold
(tuned by the sampling study's mixing experiment: 2% marked share) the report
degrades honestly rather than presenting a bomb-dominated sample at full
confidence. The exclude-counterfactual
stays computable offline but is never displayed: at 500-review sample scale the delta
is noise inside the interval.

**English-first, all-language counts.** Extraction reads English, the language the
gold set can verify; an unevaluated multilingual layer would contradict the project's
thesis. Counting layers (timeline, totals, score context) always cover all languages;
every report discloses the language mix; event explanations are **withheld with a
stated reason** when a window is majority non-English: the alternative was confidently
explaining a Chinese-language backlash from the English 30%, a fluent wrong answer in
the flagship feature. Turkish: informal spot-check only (a headline TR eval would be
statistically hollow at gold-set scale).

**Events, not accusations.** The anomaly layer detects and explains episodes (what
happened, when, about what): statistical detection over the full-population histogram,
explanation from targeted reads, verification against the game's public patch history
(an external, non-circular anchor). Valve's off-topic flags are a comparison signal for
the review-bombing subtype only. *(Tombstone: fake-review detection, cut 2026-07-07;
no ground truth exists, the claim is unfalsifiable, and an unvalidatable accusation
makes every other claim less trustworthy.)*

*Redirect 2026-07-27: the explanation half is deferred with the investigator:
deployment (M3) built display-only episode markers, pure statistics over the
all-language histogram; the detection layer and the tombstone stand. The
markers have since left the report display too — the marker design's
2026-08-14 ruling. See "The redirect & the product frame".*

### The door as built (`steam_client`)

**Donor, not template.** The module is a fresh build to the windowed-unfiltered
sampler contract, *not* a copy of the prior steam-reviews fetcher: that file is a
**donor reference** whose paid-for Steam-API knowledge (the retry/backoff GET, the
identity guard against wrong-appid pulls, endpoint quirks) is deliberately harvested,
while everything structural is rebuilt to this project's bar. Importing the frozen
repo, rewriting from scratch, and a naive file copy were each rejected, the last
because the frozen default-walk loop *is* the proven-unsafe blanking path, and its
silence on logs/cost/latency is exactly the observability gap this project treats as
a deliverable.

**Three operations, both paths** (ruled 2026-07-27).
The build scope is resolve-game (appdetails + the donor's identity guard), the
histogram snapshot, and the window-fetch primitive, deliberately *not* `FetchPlan`
execution or `SampleManifest` minting, whose producer (`core/sampling`, the policy
the sampling study certifies) doesn't exist yet. Three contracts froze with their
consumer: `GameRef` (identity-guard verdict absorbed into the record: a MISMATCH
`GameRef` is an honest answer about what Steam returned), `HistogramSnapshot`
(rollup unit never hardcoded, per the M0 probe), and `WindowFetchResult` (per-window
provenance: path outcome, pages, retries, and a semantic-validation verdict; the
window params were undocumented when built, so every response is checked against
the requested window, never trusted — a discipline kept after the 2026-10-22
endpoint change documented them).

**The cursor fallback is built, not stubbed.** It is the same machinery as the
windowed walk under timestamp-gated loop control, plus a pure feasibility estimate
(SKIPPED_INFEASIBLE, disclosed, never a silent hole). Stop discipline everywhere:
the walk stops on the window boundary, a repeated cursor, or a missing cursor;
**short or empty pages inside a window are suspicious, not conclusive: retried,
never a stop** (the donor's proven-unsafe stopping rule, inverted). Standing
correction on the donor's confident comment: **no page size is universally safe**
(FIXLOG 2026-07-07): page size is a non-load-bearing config knob (default 100;
a live probe showed >100 clamps to 100), and safety lives in detect-and-retry plus
the window-bounded stops, not in a magic constant.

**Politeness is inherited by construction.** A configurable inter-request delay
(default 1.5s ≡ the ~200-req/5-min folklore budget) sits at the top of the one
retry-GET chokepoint, so every attempt, every endpoint, every caller inherits it;
adaptive backoff on 429/5xx lives in the same function. A token bucket was rejected
(bursts buy nothing; clock-carrying state costs testability).

---

## The labeling engine

How a review becomes a labeled envelope and then a number: the provider seam that
buys model output, the classify stage that turns it into contracts, the store that
makes both durable, and the two consumers: the census dispatch that bought the pool
and the aggregate mint that folds it.

### The provider seam (`llm_client`)

**One generic door, routing as data** (settled 2026-07-13). The client exposes a
single `complete()` over a stage-keyed request, never per-stage methods: the
per-stage routing table (stage → provider, model, params)
stays *data*, so retargeting a stage is a config edit. Each route carries an opaque
provider-params block passed to the adapter untranslated, dodging the
lowest-common-denominator squeeze without widening the seam; the one field lifted out
of it is `max_output_tokens`, because the budget reservation must price it. The
response carries everything downstream needs (the token-usage split (thinking tokens
included), normalized finish reason, resolved model version), since guards, ledger,
and provenance can only record what crosses the seam.

**Raw HTTP through registered functions; no aggregator, no SDKs.** Providers are
registered functions (a dict registry, constructor-injectable for tests) speaking
httpx. litellm was rejected: a large fast-moving dependency that normalizes away
exactly the provider-specific fields the earned guards watch; per-provider SDKs were
rejected because vendor retry machinery overlaps ours (double-retry against tight
quotas), though an SDK may still slot *inside* one adapter later without touching the
seam. Config validates against the registry at construction: an unknown provider
fails at startup, never mid-run.

**Synchronous, concurrency-shaped, dialed to sequential.** asyncio was rejected:
coloring spreads to every caller while the throughput ceiling is the provider quota,
and sync composes with M3's async serve via standard thread offloading. The one
stateful bundle (budget, pacer, ledger appends) is lock-guarded and hammer-tested;
the worker pool lives in the *caller* with `max_workers` as config defaulting to 1:
a throughput flip is a route edit plus a number, zero code.

**Budgets reserve before dispatch.** An atomic worst-case reservation (pessimistic
prompt estimate + the route's full output ceiling, priced) settles to actual cost on
completion (overshoot impossible by construction), and daily-quota admission counts
ledger rows *plus in-flight calls*, since the ledger alone lags dispatch by exactly
the racing window. Rate and quota limits key by *model*, never by route, so two
stages sharing a model share one real quota pool. Token prices are data in the
per-model config table (free tier is honest zeros; a paid flip is a number edit).
The hammer tests pin the exact-admission property; finer build detail lives in the
module docstrings.

**Errors are typed, and the two capacity states never blur.** Transients retry
inside with bounded backoff and surface as `LlmUnavailableError` only when exhausted.
`AtCapacityError` (our own reserve refusing) is never retried and is deliberately
distinct: one is the world failing, the other is us keeping a promise, and only the
latter becomes the honest at-capacity state. Truncation is not retried (temperature-0
re-truncates identically) and carries its normalized reason for the caller to decide.

### The classify stage (`core/classify`)

**The prompt renders the codebook full-fidelity** (settled 2026-07-13). A
versioned artifact (file + content hash + changelog) carrying
every field, all aspects, category-grouped, so the machine annotator reads the same
instructions the human annotator reads at gold labeling, keeping the agreement number
clean of instruction gaps. The compact decision-surface rendering was pre-registered
as an experiment and later **closed on measured evidence**: a confirmed recall loss
at both gold and census scale (see the codebook section).

**Batch-native with size as config.** The builder takes idx-tagged review tuples,
the parser returns per-idx envelopes, one prompt version serves every batch size, and
N rides in the run's config hash. Gold-set evals run at the production batch size:
certify what ships. The never-re-paid promise lives in the *label pool*, not the
response archive: the driver selects only reviews lacking labels under the current
version key, so batch composition varies freely across runs.

**The model emits label strings only.** Pinned-vs-candidate resolution belongs to
`core/normalize`'s deterministic surface index, never to the model's
self-declaration: the prompt teaches the two-slot *behavior* (never force-fit; the
reviewer's own words when nothing fits), code decides the slot. Output shape is
enforced twice: a provider-side response schema (sentiment a closed enum; the aspect
field deliberately a *free string*: an enum of pinned labels would structurally
forbid candidates, silently) and one provider-portable shape line in the prompt.
Three synthetic few-shot examples cover the edge behavior (the zero-aspect review,
dissociated sentiments, a candidate emission), synthetic so gold disjointness is
structural, mid-tail so the frequency thumb stays off the headline aspects.

**The parse is pure and salvages per idx.** Every valid entry becomes an envelope;
every failed idx lands in a typed failure report the driver must handle: one bad row
costs one review, never the batch. Evidence failing the verbatim-substring check is
**repaired, not fatal**: the mention survives with evidence=None and the repair is
counted through the sink (a rising repair rate is the early smell of what the
fabricated-quote metric measures properly).

**Retry is re-batching, not corrective prompting.** At temperature 0 an identical
request re-buys the identical wrong answer (and the archive would return it without
even spending), so the retry must vary the request; failed reviews re-entering the
driver's selection loop regroup into fresh batches, which *is* the variation, for
free. One round, then the review is marked unclassifiable-under-this-version and
disclosed in the run report: include-and-disclose applied to our own failures.

### The store

**Tables land with their first consumer** (settled 2026-07-14), the *rules now,
fields later* principle applied to schema: pre-building
`eval_runs` would have guessed at exactly what the eval-journal design existed to
decide. Schema lifecycle is a hand-rolled ordered-steps **migration runner** stamped
via `PRAGMA user_version`; Alembic was rejected (SQLAlchemy machinery on a raw
`sqlite3` store), but so was bare create-if-missing: the runner costs ~ten lines
more and means the first real migration slots into standing structure. The **freeze
rule** scopes the discipline to when it pays: steps froze append-only the moment the
first file held paid data, and steps are **additive by default**: a data-rewriting
step is a design smell requiring a stated reason.

**Two versionings, never converted into each other.** The schema version protects
bought data from *our storage* changing; the content-version keys protect correctness
from *the question* changing: old-version labels aren't migrated, they coexist under
their own key, which is what makes the pool accretive.

**Validation is asymmetric by design.** Writes take frozen contracts trusted by
construction (structural constraints only: NOT NULL, FK, UNIQUE); reads treat the
file as raw external data and validate by *reconstruction*: enum constructors plus a
naive-timestamp-rejecting datetime parse, failing loud with the offending row.
The label pool is
**normalized, never a JSON blob**: the load-bearing queries (the origin ∩ version
fold, the two-track wall's origin predicate, denominator counts) all reach *inside*
the envelope. Write semantics follow each contract: archive `put` upserts, ledger
`append` is insert-only, envelope inserts **fail loud on UNIQUE violation**: a
duplicate envelope means the driver's selection is broken, and `OR REPLACE` would
hide exactly that bug. Table shapes and the test strategy live in ARCHITECTURE and
the module docstrings.

### The response archive — raw provenance, not a cache

The store of bought provider responses is named `ResponseArchive` (renamed from
`ClassifyCache`, 2026-07-21) because it is a durable, content-addressed record of
*unreproducible* raw provider output: an LLM reply can't be regenerated, and the
archive is its only durable copy, so "clear it to reclaim space" must read as the
data loss it is. Re-pay-avoidance (the `get` before dispatch that lets a run resume
without re-buying) is a *free consequence* of a permanent content-addressed store,
not a second design goal. The seam stays text-only: raw is a *forensic* affordance
(reading a model's discarded reasoning trace during disagreement investigation),
never an input to a metric; retrieval is by reconstructing the content-hash key on
demand, sound because version pinning makes the recompute exact. Splitting a
disposable cache from the archive was rejected (identical bytes under an identical
key: structure with no operational teeth), as was carrying raw bytes on every
response.

### The census dispatch (`studies/`)

**A thin entry shell over the seams** (settled 2026-07-19). The driver composes
corpus reader → store ingest → selection → batch → classify → client → label
pool, narrating through the sink. Resume needs no
checkpoint ledger by construction: `unlabeled_under` *is* the checkpoint, batch
composition is deterministic over the remaining set, and the content-keyed archive
makes a re-formed batch whose response was already bought free: crash anywhere,
relaunch, pay only for what never completed.

**The label key's `model_version` is the requested id, never the response's
self-report.** Keys are contracts, observations are evidence: the reported string
journals per call in the spend ledger, and a mid-run change from the first-seen value
**aborts loud** rather than warn-and-continue: a silent provider model roll is
exactly the event that would split the pool's "one annotator" claim, and resume makes
the abort cheap.

**Failure policy: the three-pass sweep, then a durable mark.** Initial batches →
failed idxs re-batched at production N → survivors isolated at N=1 → still-failing
reviews marked durably (excluded from future selection under this versions triple).
Amended on live census evidence (2026-07-20): a provider's *permanent* rejection
(DeepSeek's content filter refused one review's Tiananmen line) fails the batch's
rows into that same sweep, so innocent co-batched reviews label on isolation and only
the trigger review takes a durable mark carrying the refusal verbatim. The pool
honestly records "the annotator refused this text", an instrument-limitation
footnote the milestone post carries: a Chinese-hosted annotator imposes its content
policy on the census. Two guards from the same incident: a circuit breaker still
aborts on systemic refusals (a revoked key must surface as an abort, never as
thousands of quiet marks), and an aborting run cancels its queued batches: abort
means stop by construction.

**Budget caps sit below the balance.** The invocation cap is set deliberately under
the provider balance so our clean `AtCapacityError` always fires before the
provider's insufficient-balance error; the driver narrates the ledger's lifetime
total at startup, and a pilot slice gates the full buy on measured cost-per-review.
Ingest asserts the ruled census size (135,260) and fails loud before any money
moves; the slice ruling became a runtime check. Concurrency topology (two store
connections, worker pool shape) is structural detail: ARCHITECTURE.

### The number mint (`core/aggregate`)

**A pure fold with persistence pushed to the shell** (settled 2026-07-20).
Survey-origin, version-pinned envelopes → `AspectAggregate` records; the
core stores nothing, because the fold is cheap and fully reproducible
(keep-vs-regenerate: regenerate the cheap middle). Persistence is taken deliberately
only when a number is *published*: a snapshot stamped with full provenance, a
frozen citable artifact rather than a live cache, so staleness is a non-issue.

**The grain is per game.** A number is minted per `(app_id, aspect, slot)`: every
consumer lives at the per-game grain, a global fold blends incomparable populations
and can never be re-split, and per-game rows always roll back up. Per-game is also
the only grain honest about thin games: a small title's few mentions show *as* thin
instead of dissolving into a large pile. `app_id` joined the contract as a
first-class field: hiding the game inside `manifest_id` fails the
references-carry-their-meaning rule.

**Candidates fold exactly like pinned: no fuzzy merge, singletons kept.**
Candidates group by their exact stored string; `grind`/`grinding` stay distinct,
because a false merge silently corrupts two aspects at once while a false miss lands
recoverably in the candidate stratum for human-gated alias promotion (an offline
loop: new ontology version + cheap deterministic re-normalize, no LLM re-buy). No
floor at mint: the contract keeps the number a raw tally and the floor a display
rule, so C2 has exactly one job (count everything, honestly) and every policy
question lives downstream in one place. One typographic fold does apply before
the exact grouping (ruled 2026-08-17): underscores become spaces in the candidate
normal form. A reviewer never writes ``base_building``; that spelling is the
classifier echoing the pinned snake_case keys it was shown, and it had split one
theme into two rows that render identically on a live report (``base building 6 ·
base building 6``, 2026-08-14). Hyphens and phrasing still survive as the
reviewer's wording. The stored labels of the affected runs were folded in place
by ``scripts/fold_candidate_underscores.py`` (8 mention rows, 3 snapshot rows,
merges verified disjoint), because cached labels are reused by later runs of the
same reviews and would otherwise reproduce the split.

**The denominator is the per-game survey envelope count, empties included.**
Dropping the ~46% empty-mentions envelopes would inflate every share; this is
exactly why the empty envelope is a first-class contract state. Only survey-origin,
version-matching labels fold, pinned **v2 by explicit path**: the packaged ontology
default stays v1 (gold's identity pin), so every pool consumer pins v2 explicitly;
flipping the default is a deliberate later step that must rework the runner's
gold-pin check, never a side effect.

> [!IMPORTANT]
> **Outcome.** The census is bought and settled (2026-07-20): 135,259 envelopes + 1
> durable content-filter refusal = 135,260 exact under
> `deepseek-v4-flash / classify-v1 / v2`, true cost $3.80 all-in, Drive-backed with
> a hash manifest. The mint verified on the real pool: 49 games, 170,532 mentions,
> the reviews_with_aspect invariant holding wholesale.

---

## Choosing the labeler — measured, not reputed

**The tier rule: per stage, not global.** The provider seam routes each stage
independently, and the small-vs-frontier gap is stage-dependent: near-zero for
phrasing, modest-and-measurable for classification, largest for agentic reasoning.
The judge is exempt from cost optimization entirely: always a stronger model than
the one it grades, low volume, API. Deferring each tier choice to its stage's design
point is safe because four things are built regardless: the provider-agnostic seam,
a concurrency-capable classify stage, narrated progress, and enforced budget caps
with an honest at-capacity state.

**The bake-off protocol: frozen metrics, recorded judgment** (2026-07-17). The
survey labeler is chosen by measurement against the gold
set, not by reputation, with the metrics frozen *before* any run so the ruling can't
metric-shop:

| Rule | Why |
|---|---|
| Primary: mention-level P/R/F1, paired by label within review, pinned-slot only | the known failure mode (over-extraction) is directional; F1 alone would blur it |
| Sentiment: flat accuracy on matched pairs only | polarity errors never double-punish detection errors |
| One gate: >2% unrecoverable parse failures disqualifies | dropped reviews at survey scale are missing-data bias no metric repairs; below the gate a failed review scores as zero predictions, never excluded |
| Candidate-slot mentions unscored on both sides | n=11 in gold can't support a metric; slot discipline is already priced in |
| Parity: `classify-v1` verbatim, no per-model tuning; structured output deliberately non-parity | tuned prompts would measure our effort; the native output mechanism is part of the product being bought |

Bootstrap CIs resample over *reviews* (mentions within a review aren't independent);
every run lands as captures + a manifest, and the comparison table regenerates from
captures + gold: one source of truth. Lineage: the gold-assist model is banned from
the pool (INSTRUCTIONS §8). A standing no-buy exit was live: the recorded outcome
could have been "nobody is buyable, escalate tiers", never buy-the-least-bad.

**Batch size is part of the product, not a parity constant** (amended 2026-07-18).
The bake-off's N becomes production's default and certify-what-ships means measuring
each candidate at its deployable shape; a disclosed N-probe set the dilution ceiling
on two structurally different candidates before any scored run. The campaign's
operational lessons (envelope exits, the three-stage retry that preserves the gate's
semantics at a fraction of the requests) live as comments on their candidates in
`probes/bakeoff_runner.py`.

**Paired reads, not interval eyeballing** (2026-07-19). Every run scores the same
250 gold reviews, so run-vs-run gaps are paired: `paired_bootstrap_ci` resamples
one set of review indices and scores both runs on it. The correction cut both ways
on the same day: one gap with heavily overlapping individual CIs was **real** under
pairing, a second was **indistinguishable**; eyeballing would have called both
wrong. **N froze at 10 on quality's call alone**: the v4-flash ladder peaked at n10
two-sided, and true cache-adjusted cost is N-independent in practice, which closed
the amendment's honesty rider: the free-tier pressure that motivated maximizing N
never bound the paid winner.

**The ruling: DeepSeek v4-flash at N=10 labels the survey** (ruled 2026-07-19).
The honest sentence: Gemini 3 Flash is measurably better at matched N
(+0.034 F1, paired CI excludes zero), the gap closes to indistinguishable against
v4-flash's frozen N, and it costs ~12× more; v4-flash wins on cost-effectiveness
with zero parse failures across its ladder. Not claimed: "as good as the leader."
**Single-labeler discipline**: a free-Gemini-with-DeepSeek-fallback hybrid was
rejected: a mixed-labeler pool breaks measurement integrity (two error profiles
inside every aggregate; the judge calibrates against one labeler). Reopen
conditions, recorded with the ruling: a prompt change (re-certifies quality *and* N
on gold; exercised at the v2 codebook certification), provider repricing or
deprecation (the `deepseek-chat` five-day retirement is the named precedent), and
survey-scale anomalies surfacing through the eval harness; tier escalation is the
recorded fallback, never quiet tolerance.

**The slice ruling: census of the usable pool** (ruled 2026-07-19). The
survey labels **every English-nonempty corpus review: 135,260 across 49 games**.
This deliberately reopened and superseded the earlier "full corpus is never
labeled" ruling on its collapsed premises: the labelable pool measured 135K, not
the 298K headline, and the cost base was v4-flash's true ~$3–6, not Gemini's ~$25;
census costs 2.9× the sampled alternative and buys no shortfall policy, zero
sampling error against the corpus, and a sampling study never capped by today's
choice. **No pre-filtering beyond usable**: "no aspects" is the certified
classifier's own verdict and a measured quantity (gold zero-share 49.2%); a
usefulness heuristic would be an unvalidated second classifier standing in front of
the certified one. Instrument lesson recorded: 100-review/game probes cannot
resolve mention rates under ~1%; tail pins are only visible at the n≈1,200–1,900
the census provides anyway.

---

## The codebook

**Hybrid with a fixed core** (decided 2026-07-09 on the week-1 probe's evidence,
`probes/FINDINGS.md` §6). Open extraction showed a flat, game-specific vocabulary
(top-15 grouped labels cover only 28% of mentions; half of all mentions are
single-game vocabulary), so a fixed set would flatten exactly the specificity the
product sells, while pure open stays dominated (normalization cost and a blurred
eval anchor). The shape: the vocabulary is a **versioned design-time artifact**
(human-gated, built offline); runtime extraction is **two-slot**: classify into
the pinned vocabulary or emit a free-form candidate; recurring candidates are
displayed as a **disclosed emergent stratum** (real numbers, honestly marked
uncalibrated); **promotion is offline and gated**, bumping the ontology version, so
every displayed number knows which vocabulary produced it. The v1 ratification
record (the pruning criterion, every per-aspect ruling, reopen conditions) is the
repo's `ONTOLOGY_PRUNING.md` (ratified 2026-07-15; 55 → 51 pins).

**The v2 wording batch** (ruled 2026-07-19; the sanctioned reopen under
the labeler ruling's prompt-change condition). The gold ledger's routing rulings
postdate classify-v1's frozen wording, so the labeler had never seen the semantics
gold grades it against, and the survey pool is the durable asset every downstream
consumer folds, so it gets bought at aligned semantics. The distillation was one
shot by design (wording never iterated against gold F1): a triage pass over
the 33-ruling gold ledger settled what rides vs what stays gold-process-only,
landing in `src/steamlens/ontology/v2.toml`: same 51 pins, aliases byte-identical,
every example freshly constructed so no gold span reaches the machine's contract.

> [!IMPORTANT]
> **Outcome.** v2 vs the frozen v1 baseline on gold: precision **+0.066
> [+0.039, +0.098]** (real), recall −0.030 (borderline), F1 +0.020: the honest
> sentence is *not-worse-and-leaning-better with a confirmed precision gain*. The
> mention-economy diagnostic explains the shape: the baseline over-mints, v2 lands
> on gold's economy: the ruling batch is precision-lifting deletion, working as
> designed. The N-peak reproduced under new wording. Captures:
> `probes/captures/bakeoff/deepseek-v4-flash-v2*/`.

**The compact rendering is closed.** The decision-surface-only render
(`classify-v1-compact`, a first-class versioned variant) was rejected for dispatch
at the v2 certification (confirmed recall loss, token savings immaterial under
prefix caching), and the census-scale experiment closed it: drift-clean, compact
measures **−0.018 F1 real vs full** (the judge-referenced same-day read, 2026-07-25).
It remains a versioned artifact; reopening requires new evidence, not new hope.

**The codebook-overfit disclosure** (ruled 2026-07-21). Gold was
adjudicated before any candidate model was scored (the safe direction), but the v2
distillation was tuned *on* gold's 250 reviews, so every v2-on-gold number is
**development-grade**: the instrument was refined against the set it is scored on.
The mitigation landed as the sampling study's 150-review holdout under **frozen**
v2 (2026-08-04/05: agreement 0.557 with a steep stratum gradient, the
sampling-study outcome); hard cases feed v3 notes, never back-edits to v2: a
back-edit would restart the contamination clock. Published v2-on-gold numbers keep
the development-grade disclosure, now read beside the held-out bound.

---

## The eval harness

**The scoring core is library code.** The gold-pairing metrics outlive any one
study: the bake-off, certification, and CI all score through
`src/steamlens/evals/` (imports anything, nothing imports it), while runners and
table generators stay `probes/` scripts. Both sides of every comparison resolve
pinned-vs-candidate through `core/normalize`'s surface index: one resolution
authority, so the scorer and the candidates can never disagree about what "pinned"
means.

**The certified object is the pool, not the configuration** (settled 2026-07-23).
The bake-off certified model + prompt + codebook on lab-composed batches; the
certification of record scores the bought envelopes themselves (the labels every
displayed number folds) against gold through the same frozen scorer. Scope rule:
gold predates the census scope and holds 5 out-of-scope reviews; certification
scores the 245-review intersection, with the narrowing stored on the run row, never
buried in prose: skipped, not counted as failures, which would fabricate a penalty
for reviews the model never saw.

**One journal, name-keyed metrics, a generalized reference** (settled 2026-07-23).
`eval_runs` holds the regenerability set (versions triple, ontology content hash,
reference id + sha256, counts, seed, resamples, scorer identity), and
`eval_metrics` holds name-keyed child rows, because the metric family grows: a new
metric is new rows, never a migration on minted runs. The reference is generalized
past gold: a `reference_kind` tag (closed contract enum: `gold-file`,
`pool-labels`) lets judge-vs-production agreement runs share the journal: every
run kind answers the same sentence, *this label set, scored against that pinned
reference, by this scorer*. The accepted cost, eyes open: one flat table quietly
holding a sum type. For pool-label references the pinning property survives by
digest over the canonically-serialized label set: same tamper-evidence as a file
hash.

> [!IMPORTANT]
> **Outcome.** The production census labels certify at **F1 0.766 [0.713–0.811]**
> against gold on the 245-review intersection (run
> `certify-20260728T184100Z-5f3f4652`, scorer `census-vs-gold/2`), the number
> every M1 claim rides on. The −0.033 gap to the lab arm was chased to ground by
> the registered experiments below: buy-time variance, not batch composition.

> [!IMPORTANT]
> **Re-certification after a provider swap (2026-09-24).** DeepSeek retired V4
> Flash on 2026-09-10 and routed the requested id `deepseek-v4-flash` to V4.1
> Flash (reported as `deepseek-flash`). The drift watch compared versions within
> a run only, so the swap went unflagged for eight days and three reports
> shipped on the swapped model. Two cells on the recomposed gold scope under a
> fresh fillers seed (20260924) measured the request shape on the new model:
> json mode as certified **F1 0.700 [0.624–0.766]** with 24.9% of gold reviews
> lost to shape failures (the model answers json mode with an object root, or
> echoes the directive back as the whole answer); prompt-only JSON **F1 0.801
> [0.752–0.844]** with none (run `certify-20260924T222850Z-b7092393`, scorer
> `census-vs-gold/2`). Ruled: production sends prompt-only JSON, the requested
> id is pinned to `deepseek-flash` with the declared version guarding it across
> runs, and the label-pool namespace moves with the id. The re-certified F1
> overlaps the original's interval; the claim is "at least as certified", not
> improvement. The misattribution audit and the judge agreement were measured on
> the retired model and stand with that caveat until re-measured.

**The fabricated-quote metric decomposes honestly** (settled 2026-07-23). The parse
already enforces the verbatim check at write time (bad quotes are nulled before
storage), so the stored pool holds zero fabricated quotes *by construction*, and the
metric splits into: the **invariant audit** (every stored span re-checked as a
verbatim substring of its review; **0 violations over 163,842 spans**: "zero,
verified," not "zero, assumed"), the **attempted-fabrication rate** (write-time
repair counts: ~2.9% of attempted quotes; the model-quality diagnostic the cleaned
pool can no longer show), and the standing spine caveat that verbatim passes a quote
read upside-down; misattribution stays the human audit. Audits stay out of the
eval-run journal (`eval_runs` means "scored against a measuring stick"; an audit has
none) and render as regenerable health reports; per-game health carries no
thresholds: inventing cutoffs before seeing the distribution tunes alarms to
nothing.

**The misattribution audit.** Unit: the claim, one evidence-carrying mention in
its review; metric: the share whose verbatim-true quote is attached to the wrong
aspect or an uncarried sentiment. The draw is a seeded systematic pass over the
sorted frame: implicit proportional stratification, self-weighting, so the
audited rate estimates the population rate with no reweighting. 100 primary + 10
ordered reserves in `eval/audits/misattribution/`.

> [!IMPORTANT]
> **Outcome.** The audit landed 2026-08-05 (the human pass, 100 claims; two
> non-English primaries skipped and replaced from the ordered reserves):
> misattribution **11.6% [6.6–19.6]** Wilson over 95 decidable claims, 5
> undecided disclosed. Decomposed: aspect-side 10.4% vs sentiment-side 3.1%,
> and the aspect misses are dominated by close-family routing
> (bugs↔stability, updates↔developer_conduct, ai_behavior↔balance
> number-tuning) plus wish-quotes, with zero far-field misreads. Verdict-frame
> rulings (quote-judged-in-context, field independence, the wish-rule) in
> `eval/audits/misattribution/NOTES.md`; regenerable numbers + failing claims
> in `report.json` beside the sheet, both pinned by sha256.

**The numeric-grounding checker is deferred to its first consumer.** Its input
contract (what a numeric claim *is*) is undiscoverable until composed prose
exists (M3's composer at the earliest); building it now would freeze a guessed
seam. Recorded so the metric list stays honest: classification agreement
(journaled), fabricated-quote (decomposed above), numeric grounding (deferred, with
this reason).

**A statistic says "undefined", never 0.0** (ruled 2026-07-28). The scoring
core's empty-denominator convention (0.0, honest for a
reported point value with its `n` beside it) silently corrupts a bootstrap
distribution: an undefined resample contributes 0.0 as if it were measured
badness, dragging the interval's lower tail. The fix lives in the core's types:
ratios return `float | None`, F1 is None iff a component is (P=0 and R=0 both
*defined* still gives 0.0, the correct measured-badness limit), the bootstrap
loops drop undefined draws on an unchanged RNG stream and **raise past a 1%
undefined share**: above the floor the slice is too sparse for the statistic and
the honest output is no number, not a wide one. A headline statistic undefined on
the full frame raises loud; an undefined slice statistic skips its row while its
`n` still journals ("no stat row" always means "nothing scoreable there").

**Evals-in-CI: a deterministic re-score pinned to the runs of record** (ruled
2026-07-26). The premise that shapes everything: CI produces no fresh model
output (re-scoring stored envelopes against pinned references under a fixed seed
is deterministic and free), so the gate catches *code/scorer/artifact* drift, never
model drift, which only enters at a label re-buy. Both runs of record regenerate in
CI from a committed, diffable JSONL fixture rebuilt through the real writer
surfaces, so CI's read path is production's. **Exact-digit mismatch fails; harness
errors fail; nothing merely annotates**: in a deterministic re-score a digit
mismatch is an unintended behavior change or an undeclared semantics change, and
both demand in-PR action. The escape hatch is the scorer-identity discipline: a
deliberate semantics change bumps the scorer string and re-exports the pins in the
same commit (exercised once: the undefined-statistics fix bumped all three
scorers to /2 and retired the exporter's relaxations). Byte-hashed artifacts are
held at LF by `.gitattributes` and the exporter refuses a CRLF working copy: a
platform-varying hash can never gate a
Linux checkout. **Tolerance bands exit CI entirely** and become the **re-buy
decision rule**: a recertification after any label re-buy reads against a band
floored at the measured ~0.03 buy-time variance: tighter would alarm on the
instrument's own noise. Trend stays M1-minimal: the journal *is* the trend store;
a rendered trend view waits for deployment, when re-buys become routine.

---

## The judge

**No gold-entangled model as an instrument** (ruled 2026-07-21). The gold ledger's
§8 ban on the gold-assist model extends to every instrument whose calibration rides
on gold: the assist model's reference row is *self-agreement* (it drafted what
gold was adjudicated from), so a same-family judge would inherit self-agreement as
apparent validity. The judge is also a different family from the labeler: a
labeler-family judge would import self-preference into the agreement metrics.

**A second annotator, not a verifier** (settled 2026-07-23). The judge never sees
production's answer: it labels the review fresh under the same frozen artifacts,
and agreement is computed mechanically afterwards.
Verifier-shaped judging was rejected: showing the prediction anchors the judge
toward endorsing it, leniency in exactly the direction a self-certification can't
afford. The re-labeler also makes infrastructure reuse total: a judge run is an
envelope set under its own versions triple, so calibration and the census-sample
read are the existing scorer pointed at different pairs. Riders: **single-review
dispatch, temperature 0**; the instrument must not inherit a variable it exists to
measure. Standing caveat: two models can share blind spots, so agreement is an
optimistic bound, mitigated by the cross-family pick, backstopped by the human
holdout.

**The calibration rule was pre-registered** so the number can't be rationalized
after the fact: the paired Δ(judge − production) on shared gold:

| Verdict | Reading | Consequence |
|---|---|---|
| pass — significantly above production | the judge is a valid quality reader | census-sample verdicts are reference-grade |
| marginal — indistinguishable | the judge is a disagreement flagger | the sample reports agreement rates, never "judge-corrected quality" |
| fail — significantly below | reported as a finding | certification stands on the mechanical layers |

Frontier escalation is proposed only from marginal/fail, never auto-fired. Refusal
routing resolved both ways at once: labeler-refused reviews are *not* patched by the
judge (a substitute label is a different annotator's triple that can't quietly join
the displayed numbers, and patching would launder the content-policy footnote out of
the record); the judge's own refusals take durable marks, with agreement computed
over the mutually-labeled intersection and refusal counts disclosed: an instrument
that declines to read didn't read wrong.

**The build amendments** (2026-07-23). The generic
"Gemini flash" resolved to `gemini-3-flash-preview` on assembled evidence (the only
flash candidate consistently above production's certified F1, where a weaker judge
near-guarantees a demoted instrument), with two caveats recorded: selection optimism
(the same gold measures the pick and the calibration) and preview-id retirement risk,
mitigated by running calibration and the census sample close together. Routing is
direct Gemini API for instrument continuity with the bake-off's measured
generation config. Gold's out-of-scope reviews are **backfilled honestly** (true
metadata from corpus files, never fabricated rows, scoped out of every labeling
run's selection); a **text handshake** guards instrument identity: an envelope must
never claim text the judge never read.

> [!IMPORTANT]
> **Outcome.** Calibration **PASS** (2026-07-23): judge F1 0.816 vs gold, paired
> Δ **+0.050 [+0.019, +0.083]** over production on the shared reviews: census-
> sample verdicts are reference-grade; frontier escalation moot. Instrument caveats
> on record: the preview id survived a load-shedding capacity event and has a named
> successor, so a re-run may need recalibration; the Batch API cost lever carries a
> stuck-jobs strike.

**The census-sample read: reviews, n=1,000, sync** (ruled + built 2026-07-23). The
frame is reviews, not mentions: the judge's unit of work is a review, and a
mention frame would overweight multi-mention reviews with no clean review-level
interpretation; zero-mention reviews stay in ("both instruments say no aspects" is
agreement worth measuring). n=1,000 roughly halves gold's interval; the Batch API's
50% saving doesn't pay for its job-submit/poll/download build at this scale. The
sample pins text by sha256, not by copy: the dispatch refuses a store whose text no
longer hashes to its pin. Everything instrument-defining lives once in a shared
dispatch engine consumed by two thin shells (gold calibration, census sample), so
the two runs cannot drift apart.

> [!IMPORTANT]
> **Outcome.** Judge-vs-production agreement **F1 0.791 [0.772–0.810]** on
> 1,000/1,000 (run of record `agree-20260728T184121Z-7c975c95`, scorer
> `judge-vs-production/2`), between production-vs-gold 0.766 and judge-vs-gold
> 0.816, so no quality cliff outside gold. Per-aspect agreement rows journaled with
> CIs at a judge-n floor of 30; the top-disagreement exemplars seed the human
> adjudication sheet (open: decides whether `updates` 0.611 is production
> under-detecting or the judge over-finding).

**The registered experiments closed the census-vs-lab gap** (designed, executed,
and self-refuted 2026-07-25). Two arms rode existing references (the judge never
ran again, gold is gold): a contamination isolation (production's model at N=1
against both references, plus a registered contingent that fired) and a compact-
codebook 2×2. Experiment envelopes stay in the pool with the batch condition tagged
into `model_version` (`@n1`/`@n10`): two label sets expected to differ must not
share an identity, and the tag buys containment (production folds filter the
untagged triple) plus verbatim scorer reuse.

> [!IMPORTANT]
> **Outcome.** **Batch composition is acquitted**: every same-day composition
> comparison is null, every cross-day comparison shows a ~0.02–0.03 gap including
> with composition held fixed: the census-vs-lab −0.033 is **buy-time variance of
> the served model** (non-monotone timeline at temperature 0 throughout).
> Consequences: the N=10 batching lever is vindicated; the compact codebook is
> closed on measured evidence; **any cross-day label comparison carries a buy-time
> rider, and re-certification after a re-buy is not optional**; production's 0.766
> stands: it certifies the labels actually bought. Named residue, eyes open: the
> recomposed cell's same-game premise was measured false after the buy (corrected
> 2026-07-27), so recomposed-vs-census interpretations carry a neighbor-structure
> confound; the census's true mixed-game structure is untested. Readings regenerate
> via `probes/d2d_reads.py`.

**The self-grading 2×2 is closed unexecuted (2026-07-30).** Under a re-labeler
judge, "the labeler judging its own labels" survived only as a verifier-shaped
bias demonstration: each model verifying its own and the other's gold labels,
self-preference = endorsing your own beyond what correctness explains. It was
registered off the critical path (~$1) with the milestone post as its decision
point; the post declined the demonstration. The no-self-grading stance needs no
empirical receipt here: it rests on the independent-judge calibration itself
(judge F1 0.816 vs gold, +0.050 paired over production), and self-preference
bias is well-documented in the literature. No number depends on the arm.

---

## The redirect & the product frame

**The investigator is deferred; a grounded RAG chat is the story channel**
(ruled 2026-07-27). The agentic verify-then-explain loop is **deferred
indefinitely**; a RAG chat over the labeled reviews takes its milestone slot.
Why: the chat monetizes
M1's assets directly (the labeled envelopes are a metadata-filtered retrieval index
most RAG systems lack; the calibrated judge machinery extends to groundedness /
faithfulness / retrieval-quality evals), the evaluation thesis becomes more
market-legible ("built and measured a RAG system" is understood in one sentence),
and it fits the Data/ML/AI transition better than the bespoke loop. Cost named
openly: the verify-then-explain differentiator goes dormant: deferred, not
deleted. Blast radius verified small: nothing built depends on investigation
machinery; the exposure is docs + product story.

**The two-track rule survives translated.** Every displayed number still comes from
the survey mint alone; stories now come from grounded retrieval: the chat quotes
retrieved reviews and never mints numbers, retrieval counts in provenance stamps
are process disclosure rather than statistics, and non-survey envelopes are
excluded from the mint by construction (the same origin-tag wall the import-graph
test guards). Roadmap shape: the chat is **the new M4**, sequenced after the
sampling study (M2) and deployment (M3): M3 ships a URL sooner, and the chat's
offline prototype + eval can run against the 49-game census before deployment
exists, so the eval story is never hostage to M3. `core/detect` survives as
**stored episode markers** built at M3: pure statistics over the
all-language histogram, no explainer — persisted with every report, no
longer rendered (the marker design's 2026-08-14 ruling). The M1 post tells the redirect straight: a
measured scope call on stated grounds, not a retreat.

**Type a game name, get the report, then interrogate it** (product frame ruled
2026-07-27; architecture rules at the M4 design session). The report stays the
product; the chat is its **interrogation channel** inside the report page: never
chat-first, never a standalone surface. It interrogates *this report's evidence
base*, so chat coverage equals report coverage by construction. The design fitness
test: every downstream choice must serve at least one of the three claims a stock
RAG app cannot make, or it is commodity weight:

1. **retrieval over self-labeled structure** — "why do people hate the grind?"
   resolves to aspect ∧ sentiment ∧ game ∧ window filters before any embedding
   runs, with a measured classifier (published F1 + CI) as the index;
2. **RAG evals on the already-calibrated judge**;
3. **a chat that structurally cannot fabricate statistics**.

**Question scope.** In: aspect why/what (the core), sub-ontology drill-down (the
one place semantic search earns its keep), time-scoped questions, and number
questions answered as **mint citations**. Refused: advice and speculation
("should I buy it?"), honestly and specifically. Out entirely: cross-game
comparison: it breaks the per-report frame, which is the product's identity
rather than a v1 limitation.

**The answer contract: claims with receipts.** Short prose composed only over what
was retrieved; each claim pinned to verbatim quotes passed through the
fabricated-quote verifier before display (a claim whose quote does not verify is
dropped, never shown); numbers appear only as visually distinct mint citations,
never phrased by the model; every answer carries a one-line provenance stamp; and
answers walk a three-state ladder: grounded answer → **thin-evidence answer,
named as such** → honest refusal. **No free-composition mode**: the moment one
answer type may speak without receipts, the differentiator is gone.

**Leanings recorded for the M4 design session** (leanings, not rulings): a
background chat pool beyond the survey (~5k, plain most-recent order, disclosed;
never targeted: a steered fill is the investigation track reborn) with
progressive labeling over a raw tier; **a small local pinned embedder**: pinned
weights make the index immortal where an API embedder's retirement orphans every
stored vector, and a 5k pool is ~8 MB of vectors, so brute-force cosine beside
SQLite, no vector DB; **no RAG framework**: the chat is a pipeline, not a graph,
and a framework layer would hide exactly the visible engineering the portfolio
exists to show (LangGraph is named as the tool for the next complexity tier,
adopted when a real loop appears, not before). The session's docket: pool tiering ·
embedder choice · retrieval mechanics · eval design on the judge machinery ·
cost caps · the composition prompt · the `Review` reception-metadata deferral
reopened as a retrieval signal.

**The M3 closure (ruled 2026-08-12).** The project closed complete at deployment:
the report product stands on its own (live, evidenced, and coherent without the
chat), and the chat keeps its milestone slot *deferred*: not cancelled, not
scheduled. The deferral is revisited explicitly after the polish run and the
public link, weighed against opening a new project; if taken up, the design
session works the docket above with the recorded leanings as its starting
positions.

**The chat reopened as a recommender tab (ruled 2026-11-14).** The deferral
was revisited and the chat taken up in a different shape from the one ruled
above. Three parts of the product frame are reversed. The chat is its own tab
and the conversation starts there, where the frame had it inside the report
page and never chat-first. It works across the library, where cross-game
comparison was out entirely. It recommends, where advice was refused. The
reason: a library of measured reports now exists, each with its labelled
reviews stored beneath it, and a question that library can answer with
evidence is "which of these games fits what I am looking for"; a chat confined
to one report had no user asking for it. The risk that kept cross-game
comparison out was real, since every number was certified inside one report,
and it is handled by reading numbers across games in groups above a mention
floor and never as a ranking. What stays from the frame: every number the chat
shows comes from the survey mint, no answer is shown without evidence, and the
honest-refusal ladder continues with "nothing in the library fits" and "that
game is not measured yet" as named answers. The advice line moves without
disappearing: the chat says which games fit a stated request and gives no
verdict on buying or enjoyment. Interrogating one report's evidence survives
as the follow-up turn inside the tab. The design is the recommender chat
section, below deployment.

---

## The sampling study (M2)

*(Designed 2026-08-02; measurements complete 2026-08-04; report frozen
2026-08-05. The design ruled how the study runs and what gates its answers;
the values (the winning policy, the tolerance table, the size rule, the
floor) are the study's measured output. Every constant and figure
regenerates from a named run of record.)*

### The study design

**The convergence target: two gates, per displayed aspect, at the 95%
register.** A sample size is acceptable when, against the full-census fold as
reference, (1) every per-aspect share the report would display lands within
tolerance of the census share, and (2) the quoted interval covers the census
value at its nominal rate: the error bar keeps its promise. Share error is
what the displayed number claims; interval calibration is the product's
actual thesis, and a policy can pass one while failing the other. Rank
stability and praise/criticism direction are measured and reported but never
gate: both follow from shares being right. Certification reads at the **95%
register** (95% of population cells within tolerance) because deterministic
draws offer no per-cell guarantee to certify, and the register puts both
gates in one probability language, the one the interval quotes. The display
evidence floor still excludes the sparse tail before any promise applies.

**The replication unit: query anchors × games × aspects.** Windowed draws
are fully deterministic (same corpus, same plan, same sample, true of the
live runtime too), so error distributions and coverage rates need a
population of report runs to be statements about. Each game's corpus
truncates at fixed quantiles of its own review-time span (40/55/70/85/100%;
never an absolute calendar grid, which would predate thin-coverage games),
reproducing exactly what a live query at that moment would have seen. This
makes the rulings claims about report runs generally rather than one
snapshot date, and makes the closing test a genuine held-out draw from the
certified population: a fresh game queried at a fresh time. Two disclosures
ride the report: anchors within one game are nested, widening the population
without being independent replications; and truncating today's corpus at T
assumes Steam would have served the same rows at T, an approximation only
the live tests ground.

**Four raced policies; two diagnostic axes.** Raced: **uniform random** (the
textbook reference; not runtime-expressible, free to simulate against a
held corpus) · **time-proportional windowed** (the runtime primary path's
hypothesis) · **equal-per-window** · **cursor-prefix** (the documented
fallback as it actually behaves: a most-recent prefix, biased by
construction; its measured bias is the trust-panel disclosure whenever a
report runs on the fallback path). Playtime and vote-type are
representativeness diagnostics on the winner, not raced candidates: runtime
expressibility of those axes is unverified against the probes' recorded
parameter surface.

**Curves first; the deliverable is a rule, not a number.** The size ladder
densifies at the low end (100–5,000, nine tiers), a few hundred seeded draws
per game × policy × size (resampling stored labels is CPU-only). Tolerance
and size were picked at a review checkpoint over the real curves, not fixed
in advance: the tolerance is a product decision (promise strength vs.
per-report fetch+classify cost) better made looking at reachable tradeoffs.
Games vary by orders of magnitude, so the rule takes the form: take all
below a population cutoff, sample above it. Interval methods raced inside
the same simulation (design-naive binomial, design-aware stratified,
bootstrap-over-reviews, all computed on every draw), with the calibration
gate itself the test: ship the *simplest* method whose coverage is honest,
because the formula ships in production. Resampling draws whole reviews,
never mentions: mentions within one review move together, and treating them
as independent fakes precision.

**Long-tail transfer: staged evidence, ending in a held-out test.** The
corpus is ~50 popular games in a recent window; the deployed app will be
pointed at anything. Three stages: within-corpus convergence splits by game
shape (if curves vary with shape, the rule conditions on it: the transfer
risk measured rather than suspected); label-free frame checks on genuinely
long-tail games (fresh histograms through the existing sampler, no LLM
spend); and a committed closing test: three long-tail games labeled fully
under the frozen versions, validating the finished rule off-corpus rather
than arguing transfer.

**The marked-share floor tunes by mixing experiment.** The corpus holds zero
marked-window reviews, so the floor is the study's one path off stored
labels: fetch marked windows fresh from documented-bomb games, label under
the frozen versions, then blend into normal samples offline at increasing
shares (0–50%, densified at the low end). The floor is the marked share at
which the certified 95%-register promise breaks: the same tolerance table,
coverage gate, and pass/fail machinery, one honesty standard end to end
replacing a guessed percentage. Blends replace members at fixed n (addition
would grow the sample and entangle two effects); one curve per bomb game
with the worst source ruling, because pooling would average away exactly the
spread the picks were chosen to cover.

**The human holdout folds into M2; the rest of the human track stays
parallel.** The census reference is machine-labeled: the study measures
*sampling* error while the classifier's own error rides silently on top. A
fresh 150-review human pass under frozen codebook v2 (60 corpus / 45
marked-window / 45 long-tail, the fresh material deliberately oversampled:
out-of-distribution against gold's popular-game 250 is exactly where the
reference is newly trusted), labeled blind to machine labels, scored as
review-level agreement against production with a Wilson interval; the number
lands in the report's limitations as the measured bound on the reference's
imperfection.

> [!IMPORTANT]
> **Outcome.** The holdout landed 2026-08-04/05 (run of record
> `holdout-20260804T215600Z-c0edb01a`, journaled + mirrored in
> `eval/holdout/agreement.json`): strict-envelope review-level agreement
> **0.557 [0.477–0.634]** over 149 scored. The stratum gradient is the
> finding (corpus 0.678, marked-window 0.511, long-tail 0.444): the
> reference is weakest exactly where the study newly trusts it, which is
> the limitations sentence the report quotes. Sentiment-given-matched-
> aspects 0.988: aspect-set selection is the entire disagreement;
> polarity is near-noise-free. Pass rulings + the batch-review disclosure
> in `eval/holdout/NOTES.md`.

### The rulings — the certified instrument

*(Ruled at the curves checkpoint, 2026-08-02, over run of record
`m2sweep-20260802T132010Z-2969bcab`: 49 games · 243 anchor pools · 255,744
cells; regime-refined 2026-08-03 at the long-tail splits, regenerable via
``scripts/split_sweep_by_shape.py`` and ``scripts/mint_allowances.py``.
Constants re-derive from the run of record, never hand-carried.)*

- **Policy: time-proportional windowed is the primary path.** It dominated
  every implementable rival on every slice: pooled p90 error, per-band
  error, Wilson coverage at every n. Equal-per-window is eliminated: its
  quiet-month over-weighting never paid for itself anywhere. Cursor-prefix
  keeps its designed fallback role; the signed-bias view showed no net
  direction for any policy (misses are symmetric spread), so the fallback's
  disclosure is a spread statement, not a drift correction.
- **Size rule: take all at pool ≤ 2,000; otherwise sample n = 1,000
  time-proportional.** n = 1,000 sits one tier above the smallest
  tolerance-passing size (750 passes with no margin against off-corpus
  drift) and returns flatten beyond it (1,500 buys 0.2 points for 50% more
  cost). The cutoff takes the 2×n shape: below it, sampling saves less than
  half the fetch+classify cost, so exactness (including headline
  exactness) is nearly free; above it, per-report cost caps at 2,000
  fetched+classified reviews (the thesis made concrete: at most 2k reviews
  per report, not 250k). Convergence rides absolute n, not sampling
  fraction, so pool size doesn't otherwise condition the rule; at pools just
  over the cutoff, Wilson's missing FPC errs conservative.
- **Interval method: Wilson plus a per-band constant bias allowance on
  sampled draws; take-all pools quote the exact number and no sampling
  interval**: a swallowed pool is a census of itself. Bootstrap is
  eliminated (the percentile interval collapses to lattice points at small
  n·p̂: ~60% measured coverage at n=100); stratified-with-FPC is eliminated
  (its within-window-SRS pretense is exactly what a prefix draw violates).
  The allowance exists because the windowed penalty concentrates in
  **≥15%-share aspects** and is bias-dominated there: error runs flat from
  n=100 to ~1500 while interval widths shrink like 1/√n, so coverage
  *worsens* as n grows (Wilson ~88% at n=100 falling to ~75–78% by
  1500–2000). The ruling follows the study's own thesis (price the
  pretense): **larger n is rejected** as an answer (the curves are flat in n;
  the cost is linear), and the **micro-window variant is parked**: the one
  candidate attacking the cause rather than repricing it, but it carries an
  unsolved compiler question (windows mint from monthly rollups) and an
  unknown payoff without a re-sweep. Its closing-test reopen trigger fired
  and did not trip; the remaining trigger is deployment (M3) finding the
  headline widths product-unacceptable.
- **The allowance and the mid tolerance condition on the spikiness regime.**
  The long-tail splits located the entire windowed penalty in temporal
  spikiness: with spiky pools set aside, no band at any pool size needs any
  allowance, while spiky pools need roughly double the flat price; a flat
  constant would over-cover calm pools and under-cover spiky ones, the same
  dishonesty the checkpoint refused, one level down. Boundary: **peak window
  share ≥ 2/3**, the pool share of the busiest histogram bucket, computable
  from the live histogram before any draw, so the conditioning adds no data
  dependency. Calm constants sit at zero for every candidate cut from 0.50
  to 0.75, so only the spiky side's calibration hinged on the choice, and
  2/3 puts the full measured price on the units that measured it. The
  constants, smoothed conservatively against order-statistic noise
  (tail / mid / headline): primary path calm **0.000 / 0.000 / 0.000**,
  spiky **0.000 / 0.017 / 0.127**: calm headline ships at roughly ±2.5
  points, spiky at roughly ±15; fallback path calm **0.000 / 0.004 /
  0.065**, spiky **0.000 / 0.022 / 0.130**: the cursor path's newest-first
  bias needs no spike, so even its calm regime carries real allowances, and
  its disclosure stays regime-aware.
- **Tolerance, band-conditioned at the 95% register:** tail (<5% census
  share) **±1 point** everywhere · mid (5–15%) **±2.5 points** in the calm
  regime, with spiky mid joining the headline treatment (spiky-mid error
  breaks ±2.5 regardless of the interval quoted, and a tolerance minted to
  fit would restate the interval) · headline (≥15%) carries **no separate
  error tolerance**: its promise is the calibrated interval plus take-all
  exactness; a tolerance number there would either restate the interval
  width or claim a precision the windowed draw cannot deliver.
- **The marked-share floor: 2%, worst-source, grid-located** (holds at 2%,
  broken by 5%; resolution inside that interval was deliberately not
  bought: no product decision changes with it). Consequences: Steam's
  default marked-window blanking, which the production fetch inherits and
  the probes verified on the wire, is certified **load-bearing** (even a 5%
  bomb admixture voids the calibrated bars), and marked windows stay
  a display overlay, never folded into displayed numbers.
- **Standing caveat, carried to the report:** the constants are
  self-calibrated on the study corpus, with the spiky calibration resting on
  thin cells and its off-corpus transfer undemonstrated (the closing test's
  lone spiky exemplar is take-all: nothing sampled exists to validate the
  spiky allowance held out, and the report says so plainly).

### The evidence

**The long-tail frame checks — the off-corpus regime distribution, passed
2026-08-03** *(discovery run ``longtail-20260802T232206Z-9bf61718``: 24
games admitted from 959 seeded-uniform probes of a 177,272-game catalogue
snapshot; regenerable via ``scripts/discover_longtail_games.py`` and
``scripts/frame_check_longtail.py``)*. Discovery is criteria-driven by
construction (the selection-bias critique answered before it is raised):
three review-count bands with edges aligned to the ruled take-all cutoff, so
each band asks a distinct question (the true tail production fetches whole ·
the engaging band where the size rule actually samples · a bridge toward
corpus scale), admission decided only by the store calling the probe a game
with totals in an open band; seed, snapshot, and probe order all recorded.
(The catalogue frame is the keyed ``IStoreService`` endpoint; Valve retired
the keyless applist in March 2026.) The answer: **the long tail is calm
territory.** 4.2% of (game, anchor) units spiky against the corpus's
33.1%, no band spiky-heavy, and fresh peak shares sitting entirely inside
corpus support, so the conditioning never extrapolates; deployed against
the long tail, the runtime overwhelmingly quotes calm Wilson-only
intervals. The span effect explains the corpus rate: the same games'
whole-life histograms read far flatter than their recent-window pools; the
corpus's 33% spiky rate is largely a property of *windowed pools*, and
production, reading whole-life histograms, meets that shape mainly in games
whose whole life is one event; the spiky constants stay as ruled because
the mechanism transfers by shape, not by span. Instrument disclosure: Steam
serves weekly rollup buckets for some games; the regime is computed on
native buckets deliberately: the windowed compiler plans one window per
native bucket, so the native series is the shape the draw experiences.

**The fresh-buy session — one fetch-and-label pass serving the mixing
experiment, the closing test, and the holdout** *(ruled 2026-08-03)*. The
bomb games spread the marked-window population three ways: Borderlands 2
(the canonical tight ~2-week window), Book of Demons (a small ongoing
mark), The Witcher 3 (a tight window with a low English share); the
long-tail games make the frame checks' leaning concrete: Sword and Fairy
Inn 2 (the lone spiky admit, 36 usable English reviews of 2,277; also the
language case), Dragonkin: The Banished (weekly-served, exercising the
rollup-unit disclosure live), Talisman: Digital Classic Edition (the one
pick whose *English* pool crosses the sampling cutoff; the criterion rides
the English pool because a pick under it would quietly turn the closing
test into three take-all games and validate nothing). English-only stands
everywhere, including the 36-of-2,277 game: take-all over a tiny English
pool *is* the honest production behavior, and labeling non-English would
test an instrument never certified. A wire-level probe gated the buy on
pick verification: every mark exists, every window blanks by default and
restores under the flag, and the combined in-window English pool (6,454)
covers the ~1–2k mixing appetite; wire truth corrected two research claims
(The Witcher 3's span is 14 days, not the researched 9 months; Book of
Demons' mark is ongoing). Containment by storage: the fresh labels land in
the fetch run's own label store, never the production pool, so the parked
`Origin.EVAL` trigger's condition never arises and the census driver runs
unchanged. The buy-time rider is binding: a fresh gold re-certification
under the frozen triple accompanied the buy, dispatched under its own
identity tag with a fresh fillers seed (a first attempt reusing the prior
seed replayed the earlier responses at $0 from the content-keyed archive:
identical composition is identical request content), and its number is the
fresh buy's buy-time certificate in the report's limitations.

**The mixing experiment — the floor's measurement, ruled 2026-08-04.** The
drifted number measures against the census share: the study's exact gates
re-run with contamination, because the displayed number's promise is
tolerance-of-truth (measuring drift against the unmixed sample's own
conclusion was declined: it applies the tolerance to a quantity it was
never minted for). Base cells reuse the certified population grid with the
same seeded-draw discipline; blending is offline resampling of stored
labels, zero LLM spend.

> [!IMPORTANT]
> **Outcome.** Off run of record `m2mix-20260804T120612Z-c31f92fe`
> (49 games × anchors × the three sources × the 8-share grid, 200 seeded
> blends per cell; verdict and figures regenerable via
> ``scripts/analyze_mix_floor.py``): the share-0 baselines restate the
> certified promise (coverage 0.958–0.959, tolerance 0.982–0.983; the run
> agrees with the certification before any contamination), and per-source
> floors land at Borderlands 2 **0.02** / Book of Demons **0.02** /
> The Witcher 3 **0.05**, the worst source ruling. **Coverage is the
> binding gate everywhere**: headline intervals break their promise
> (0.93 at 5%, 0.78 at 10% contamination) long before raw share errors
> grow conspicuous: the silent-lying-error-bars failure mode. Named
> residual for the report's limitations: an **unmarked** bomb bypasses the
> blanking and lands in samples as ordinary reviews; the experiment
> measures that scenario's damage rate, not its frequency, which is
> unmeasurable by construction (partially mitigated by the spiky-regime
> allowance and the timeline markers).

**The closing test — the size rule validated held-out, ruled 2026-08-04.**
The held-out games run the certified own-span anchor grid, and the verdict
reads over all measured cells (the certification's own population
reading), with the full-corpus anchor as the report's headline unit ("a
fresh game queried today"); one game's displayed aspects are too thin a
base for a register claim. Truth is each game's own full-pool fold under
the frozen triple, read from the fresh-buy run's own store. The size rule
runs as shipped and **both of its sides are under test**: pools above the
cutoff sample through the certified seams and read the certified gates per
cell; take-all pools are recorded with an exactness verification rather
than skipped: in the convergence sweeps take-all was free flattery, here
the cutoff side is itself part of the promise being validated.

> [!IMPORTANT]
> **Outcome: the closing test passes; the size rule holds held-out.** Off
> run of record `m2close-20260804T140340Z-1cc06586` (3 games, 15 cells,
> 605 rows; verdict and figures regenerable via
> ``scripts/analyze_closing_test.py``): the two games under the take-all
> cutoff reproduced their reference exactly (Sword and Fairy Inn 2 and
> Dragonkin, 360/360 rows at error zero; the cutoff side's promise is
> exactness, delivered), and Talisman, the one game above it, sampled at
> n = 1,000 across five admitted anchors, held the certified 95% register
> on the pooled population reading: **coverage 0.971, tolerance 0.991**
> over 245 cells, and 0.980 / 0.979 at the full anchor, the report's
> headline unit. Two disclosures ride the report: the mid band's coverage
> alone reads 0.902, driven by one aspect missing at three *nested*
> anchors: one correlated miss counted three times, the recorded
> nested-anchors caveat made concrete; and no sampled draw exercised the
> spiky-regime conditioning off-corpus: the lone spiky exemplar is
> take-all, itself the language-reality disclosure. The verdict gates on
> the certified pooled reading (the floor analyzer's own); band slices
> print as diagnosis, never a gate.

**The M2 report.** A standalone frozen PDF (the per-milestone precedent):
the question · method (census as ground truth, the raced policies, the two
gates, seeds) · the curves as centerpiece · the rulings that fell out (policy,
tolerance, size rule, interval method with measured coverage) · the fallback's
disclosed bias · the long-tail evidence and closing test · the mixing curves
and the floor · limitations stated plainly (popular-games corpus, English-only,
buy-time variance, the reference-imperfection bound) · provenance, every figure
regenerable. No artifact references REPORT_NOTES.md.

> [!IMPORTANT]
> **Outcome (frozen 2026-08-05): "Sampling Without Random Access."**
> 22 pages, question-driven structure (the three reader questions as the
> spine, pollution and ground truth as peer chapters), 32 numbers pinned
> to live artifacts by the generator's `verify_data()`
> (`report/generate_m2_report.py`, the single prose source;
> `report/sampling-without-random-access.pdf`). Panel-read by four
> simulated readers, revised on their consensus findings (Q1's evidence
> restored, the front matter rebuilt skim-friendly), then frozen. The
> milestone's post shipped 2026-08-07, closing the sampling study.

---

## Deployment (M3)

*(Entry gates passed and design session held 2026-08-07. The rulings below are
the deployment design; build decomposition follows them. Worker counts, pacing,
and thresholds are deliberately config; the skeleton's own narration timings
are the instrument that tunes them.)*

**The entry state.** The box is a netcup VPS Lite 1 G12s (2 vCPU / 4 GB / 80 GB
SSD, 6-month term, €4.10/mo), bought outright and hardened hands-on: key-only
SSH, root login off, ufw default-deny, unattended-upgrades; verified by
test-the-lockout, with the provider web console as the emergency path. Both
entry gates passed from the host itself: the reused M0 reachability probe
all-true (egress verified from the box; capture
`probes/captures/reachability_datacenter_netcup.json`), and the rate-budget
probe clean: 200 requests at the 1.5 s cadence all 200, a 60-request unpaced
burst refused nothing, no 429 ever seen
(`probes/captures/rate_budget_netcup.json`). The settled
429-on-the-5xx-ladder ruling stays closed, now with host-local evidence.

### The serving skeleton

**One in-process job queue; one cold analysis at a time.** A *job* is the
minutes-long, money-spending pipeline (fetch → classify → mint → detect →
compose); only jobs serialize. A request for the game a job is already
analyzing attaches to that job's narration stream: one fetch, one spend, any
number of viewers; a cached game bypasses the queue entirely and renders
instantly; only a cold request for a *different* game waits, behind an honest
position-and-ETA message. Serialization is the honest shape for one box:
concurrent jobs would share the single Steam politeness budget anyway, making
both slower and the narration timings misleading. External queue machinery
(Redis, Celery) buys nothing at this scale; the accepted cost is that a
deploy kills a running job; jobs are re-runnable and the content-keyed
archive makes the re-run nearly free. The concurrency constant is config, not
architecture.

**Fetch and classify overlap inside the job.** A bounded producer-consumer
queue feeds each completed *window's* reviews to classify workers batching as
they land: total time becomes max(fetch leg, classify leg) rather than their
sum, and the first narrated labels appear seconds after the request. (The
streaming unit was narrowed from pages to windows at build time: a windowed
walk that goes dirty discards its pages and re-walks via the cursor fallback,
so a page's sample membership is not final until its whole window's path
outcome is known.) Two receipts make
the overlap safe: sample membership is fixed by the fetch plan and manifest,
never by classification order, so nothing statistical moves; and
arrival-order batch composition is exactly the freedom the registered
composition experiments measured as null. Census ledger evidence sizes the
legs: ~9 s per batch call at N=10 (the census ran up to 30 workers against
the provider without complaint), so a 1,000-review report classifies in
~1.5 min at 10 workers and a cold report lands in roughly 1.5–2.5 min
end-to-end. Structure now, numbers later: the overlap seam is built in from
the start (retrofitting it into a sequential runner would rework the runner's
spine), while worker count and pacing stay tunable config.

**The Steam cadence stays at the certified 1.5 s.** Dialing to 1.0 s was
considered and declined: under overlap the fetch leg hides behind
classification, so the dial buys almost no wall-clock, and 1.5 s is the
cadence the rate-budget gate actually certified from this host. If deployed
timings ever show fetch binding, the move is to re-run the existing probe at
the faster cadence first, then edit the config: evidence before dial.

**The live executor's English-pool semantics** *(ruled at the runner build,
2026-08-07)*. The sampling study certified draws over English pools
("English-only stands everywhere"), a gap the design session never had to
bridge because live histograms and fetches are all-language. Four rulings
close it. The size rule branches on the **English pool**, read pre-fetch by
a whole-game totals query with `language=english`: outside the probes'
recorded surface until the English-totals probe validated it exactly against
the fresh-buy run's row-counted references (36 = 36 on the language case,
and both long-tail picks flip to take-all under English branching, exactly
the "take-all over a tiny English pool" behavior the certification demands;
`probes/captures/english_totals_summary.json`). **Take-all** fetches one
whole-life window through the validated windowed path, English-filtering
after. A **sampled plan** compiles at the certified n = 1,000 against the
all-language histogram, and per-window quotas execute as an early walk stop:
the contract's "newest-first, up to quota" read literally, which is what
keeps a window's cost proportional to its quota rather than its volume
(compiled windows tile the whole lifetime bucket-wide, so
fetch-whole-then-truncate would walk the entire game). English members filter
from the quota prefix *after* selection, so windows under-deliver English at
any share below 100%: accepted and disclosed (the realized n is honest;
Wilson at the actual n errs conservative) rather than inflated by an
uncertified share correction, which stays parked as a candidate re-ruling
once deployed narrations show real language mixes. A **page-budget guard**
prices every plan before fetching: an over-budget take-all (a tiny English
pool inside a huge all-language game) degrades to the sampled draw with
disclosure, and a sampled plan still over budget refuses the job loudly: a
public box never self-inflicts an hour-long fetch.

**The share correction's trigger has fired; the correction is designed, not
built (2026-08-17).** Deployed reports show the real language mixes the
ruling above waited for: a minority-English game realizes roughly n × its
English share (a 25%-English game near 250 of the 1,000 drawn). Three
findings, in weight order. *The shape is right:* each window's English yield
is its all-language quota × its English share, i.e. proportional to the
window's English volume — the shape the study certified from the English
pool's own histogram — so the draw follows English density, as a survey of
English reviews should. *The n is short,* so the precision the study
certified at 1,000 is not reached on those games; every share and interval
computes honestly at the realized n, and the app never promised the target
(the design number stays off the page; the trust panel's Sample row names
the mechanism and where the whiskers are computed, and the README's results
section says the gap in one paragraph). *Two calibration inputs are applied a
little outside their minted conditions,* unmeasured: the within-window time
slice is shorter for English (kept from the newest q all-language reviews,
not the newest q English), so the recency skew inside a window is somewhat
stronger at low share than the spiky-regime allowance priced; and the regime
itself is judged on the all-language histogram where the study judged it on
the English pool (usually the conservative direction, a non-English review
bomb widening a calm English pool's whiskers; the reverse possible in
principle). **The designed correction:** over-fetch every window's quota by
1/s, where s is the English claim over the all-language claim (both already
read pre-fetch by the two totals queries), then English-filter as now. It
preserves the certified shape by construction (the same post-filter keeps
weighting windows by their English share; the constant lifts the total) and
returns the expected English n to the target; pages scale by 1/s (the
page-budget guard already prices, degrades, or refuses), LLM calls do not
(still ~1,000 English classified). It can be certified rather than argued:
the raw corpus files are all-language (the reader drops non-English at
read), so the closing study re-runs with the exact live policy — all-language
newest-first prefix at quota/s, English kept — against the same census fold
and gates, at zero LLM spend. Storage riders: planned n, s, realized n on the
report (the "planned n" the Draw row could not show, 2026-08-16). Rejected:
`language=english` on the walk with today's quotas — it fills each window's
all-language-sized quota with English, so per-window n follows all-language
volume, not English (a non-English review-bomb era over-drawn from its few
English reviews): n reaches the target, the shape drifts from certification;
the walk under a language filter was never wire-probed (only the totals
query was), the sample-based language mix collapses, and LLM cost per report
scales by 1/s. Deferred to a future increment at the project's closure; the
derivation lived on the whiteboard and is captured here.

**Narration streams over SSE, with history replay.** The stream is
one-directional typed events, which is precisely what server-sent events are:
plain HTTP that Caddy proxies without ceremony, browser-native `EventSource`
with built-in reconnect. WebSockets were rejected as bidirectional weight
nothing uses; even the chat milestone's shape (post a question, stream the
answer) fits SSE. On connect or reconnect the server replays the job's event
history from the start, then follows live; the job holds its event list in
memory anyway. Two wire details settled at the bridge build (2026-08-07):
the stream closes with an in-band terminal frame carrying the settled state,
because browser ``EventSource`` otherwise reconnects forever after a server
close, and a quiet stream emits comment heartbeats well inside proxy idle
timeouts (a long fetch window can narrate nothing for tens of seconds). The
HTTP surface split by verb the same day: ``POST /analyses`` is the only job
creator (submit-or-attach is the queue's own semantics, making the POST
idempotent per live app), while the events ``GET`` attaches through a
read-only queue lookup and 404s without a live job; a *finished* job's
absence there is by design, its report being the persistence layer's to
serve.

**The sync pipeline runs untouched under the async shell.** FastAPI owns
HTTP (request intake, cache reads, the SSE response); the whole certified
sync pipeline runs in a plain worker thread; the only place the two worlds
touch is the job's thread-safe event history: the narration sink appends
typed events, the SSE generator polls snapshots out at a config tick
(narrowed at the bridge build from the planned separate hand-off queue: the
job already holds the replayable history, so replay and live-follow become
one read path, and narration lands at seconds scale, making a sub-second poll
invisible while per-viewer listener registration would be lifecycle machinery
buying imperceptible latency, and would bind the bridge to process locality,
where the polled snapshot surface is exactly what an external event log
behind several web replicas would satisfy unchanged). No async creeps into
core or the shells. The composition rider lands here: `SteamClient`'s transport
becomes injectable, so the server, the live smoke test, and any future caller
share one pacer by construction instead of each minting a second politeness
budget.

### Serving persistence

**Three layers, two of them already ruled.** The labels layer persists by
construction: the cold job writes reviews, envelopes (survey origin), and
raw provider bodies through the existing store surfaces, so the expensive
asset is durable the moment it is bought and a crashed job resumes nearly
free. The aggregates layer is the mint rule firing at its first real
consumer: serving a stranger *is* publication, so the folded per-(app,
aspect, slot) numbers persist at job completion as a provenance-stamped
snapshot: the frozen numbers this report displays, not a live cache. The
report layer is one row per completed analysis holding everything the user
sees as **structured data, never rendered HTML**: the gate-passed prose, the
aggregates reference, the histogram snapshot and episode markers, and the
full provenance stamp (versions triple, fetch path, language mix,
marked-window counts, sample size or take-all). Caching content rather than
presentation means the frontend iterates freely without invalidating or
lying about a single cached report; each layer regenerates from the one
below.

**Staleness: serve as-is, date worn openly.** A cached report serves
unchanged with its analysis date and sample provenance displayed on the
page: a dated report served as dated is a frozen artifact being cited, not
a stale answer. A user-facing refresh is deferred deliberately: a public
refresh button is a spend amplifier, and the trigger should not exist until
it is decided who may pull it. When added, it is structurally free: a
refresh is a new job for the same game, minting a new report row beside the
old.

**Build-time narrowings (step 5, landed 2026-08-08).** The stored sample
manifest is the piece the design prose implied but never named: a
`sample_members` table filed window by window as members land, which gives
the mint's `manifest_id` (the run id) a stored referent. Membership scopes
both sides of the label economy (classify selects the members still owed a
verdict under the versions triple, the mint folds membership ∩ label pool),
so a verdict bought by any prior run counts for this job's numbers, which is
simultaneously the re-run collision fix (a selection that skips
already-answered members cannot die on a duplicate envelope) and the
resumes-nearly-free promise made real. The aggregate snapshot persists
normalized per (run, aspect, slot) with the sample size on every row: each
row a self-contained citable number. The report row keeps a scalar/JSON
split: columns a query may touch (identity, the versions triple, sample size,
take-all, the fetch-path totals, the narrative's recorded ladder rung) are
scalar; display-only structure (prose with its span certificate, the
histogram, episode markers, language mix, marked-window member counts,
per-window path outcomes) stores as JSON validated by full reconstruction at
read, including that the certificate still lands on the exact prose it
signs, and that the stored path totals re-derive from the stored windows.
Fetch provenance persists at the ruled trust-panel grain: totals plus
per-window path outcomes, no per-window realized-English detail. Snapshot
rows and the report row commit in one transaction; a job that classified
nothing publishes no report, so the next request re-queues honestly. The
cached-game read is POST-level: a published report answers 200 with a
receipt naming the run and wearing its date (no job, no spend), which also
settles that the POST alone never refreshes a game.

**The report keeps Steam's header-art URL (2026-08-20).** The renderer had
minted every header capsule from the stored app id alone (the legacy
``…/store_item_assets/steam/apps/{app_id}/header.jpg`` pattern), on the
belief that identity could always reconstruct the URL — the report row
deliberately stored no asset URLs. That belief quietly expired: Steam now
serves newer titles' assets only under a per-game content-hash path segment
(``apps/{app_id}/{hash}/header.jpg``), and the hash-free pattern 404s for
them on every asset name and on both legacy CDN hosts (probed live
2026-08-20, after visitor-submitted new releases put four broken cards on
the library page — the same minted URL also feeds those report pages'
``og:image``). The hash is unguessable, so the only honest source is
Steam's own answer: the job's existing appdetails read (the resolve step —
no new request) already carries ``header_image``, which now lands verbatim
on the report row (schema step 8, additive). The renderer prefers the
stored URL and keeps the minted pattern as the fallback for pre-capture
rows, whose older games mostly still resolve;
``scripts/backfill_header_art.py`` resolves those rows one paced appdetails
read per game, and a game the store no longer answers for stays NULL. The
stored URL is content-shaped provenance (what Steam said at capture time),
not rendered presentation, so the content-never-presentation ruling stands;
it renders verbatim under the CSP's existing ``*.steamstatic.com``
allowance, the same argument the search thumbnails carry.

### Model prose

**The composer routes to the survey labeler's model, cross-family from the
judge.** Composition is one call per report over the mint's aggregates and
selected quotes: orders of magnitude cheaper than labeling, so the tier
rule's cost pressure vanishes and the choice is quality per call. DeepSeek
v4-flash starts: phrasing is the tier rule's named near-zero-gap stage, the
model is fenced on both sides by deterministic gates so its failures become
retries rather than corruption, and (the load-bearing constraint) the
composer stays **cross-family from the Gemini judge**, because the chat
milestone plans groundedness evals on the judge machinery whose object is
composed prose, and a same-family composer would import exactly the
self-preference the no-gold-entangled-instrument rule exists to block.
Promotion is a route edit, on evidence; the prose-voice caveat (v4-flash had
only ever emitted JSON for this product) settled positive at the first live
canary readings (2026-08-08): three composed narratives over the canary
fixture, all clean, report-shaped English, correctly grouped and hedged. The
first real reports (step 5 onward) read against that evidence rather than
against nothing. At the build (2026-08-07) the composer's
route joined the *classify* client rather than standing up a second one: both
stages share one budget, one quota pool, and one pacer by construction, the
config module's own two-tables reasoning (two stages on one model must not
each believe they own its quota), and the reason the instrument block gained
an extra-routes door instead of the runner assembling a client of its own.

**Two strata, two treatments — numbers for the calibrated, names for the
rest** (ruled at the build). Pinned aspects enter the prompt as full fact
blocks; recurring *candidates* enter as theme names with no counts attached,
so a genuinely recurring concern is sayable without an uncertified number
being stated. The holdout certified the pinned stratum only, and the flagship
voice is the last place an uncalibrated share belongs. The gate enforces the
ruling structurally rather than by instruction: candidate values never enter
the whitelist, so a candidate-derived numeral in prose has no match and dies
like any other ungrounded number. Both strata pass one evidence floor first:
a compose-time display rule, per the aggregate contract's ruling that the
stored number stays a faithful tally.

**The numeric-grounding gate runs once, at job time, before the report row
persists**: cached prose is verified prose by construction. The gate
derives a whitelist of every number the prose may say from the job's own
outputs (aggregates snapshot, histogram and episode values, sample counts)
and requires every numeral in the composed text to match a whitelisted value
at the numeral's own precision: honest rounding passes, "roughly 40%" over
a 27% aggregate has no match and dies, which is the laundering case the
check exists for. Numerals inside verbatim quotes are exempt (the quote
verifier owns those spans, and reviewers say "60 fps" constantly); the
composer's prompt keeps numbers to mint citations anyway, making the gate
backstop rather than primary discipline. The failure ladder degrades
honestly: one corrective retry naming the violations (legitimate here where
corrective prompting was rejected for classify, because naming violations
*changes the request* at temperature 0), then offending sentences drop and
survivors render, and past that the report renders aggregates-and-quotes-only
with a disclosed line. The numbers and evidence are the product; prose is
garnish; failure counts journal through the sink.

**A pass is a certificate, not a verdict** (settled at the build, 2026-08-07).
The design's "mint citations rendered visually distinct from prose" asked for
a way to show the reader what is model voice versus minted fact, and the gate
already computes it: in gate-passed prose every non-quote numeral *is* a
whitelisted value by construction, so the gate emits the matched spans
(each numeral with the value it resolved to, each quotation with its source
review), and the report row stores those spans beside the prose. The renderer
styles from the record rather than re-scanning, and no markup convention is
placed in the model's hands to break. The composer may also quote, which the
numerals-inside-quotes exemption already implied: it is told to quote only
from the supplied evidence, and the gate verifies each quotation as a
verbatim substring of that pool, failing one like any other violation.
Numerals inside a *failed* quotation get no exemption. The standing spine
caveat rides unchanged (verbatim passes a quote used misleadingly out of
context, which is the judge machinery's territory at the chat milestone, not
this gate's), and the canary set's quote-laundering pair exists to quantify
exactly that cost.

**Verbatim is judged on the quoted words, not the closing punctuation**
(ruled 2026-08-16). The composer closes quotations in the American
convention, sentence punctuation inside the mark ("…too high," / "…tear
up."), while evidence spans end without it, so the substring check failed on
the period, never on the words. The ruling came from a full replay of the
gate over the archive: 37 compose drafts behind 22 published reports, 122
violations, every one a quotation, the numeric fence never fired; 119 of the
122 vanished with the trailing punctuation stripped, and the three that
remained were real light edits (a dropped word, a tense change, a case
change), each caught in a first draft whose corrective retry passed. Under
the strict reading eight reports had paid a retry and seven had published
with true sentences cut, two of them down to a single sentence. The gate now
strips closing punctuation from the quoted words before the check
(punctuation mid-quote still must be verbatim, and a punctuation-only
quotation is empty, never a match to everything); the certified span still
covers the quotation as written. This is the same class of normalization as
folding curly quotes: typography, not content. The prompt-side alternative
was not merely declined, it had already lost: the compose prompt's quote rule
tells the model, with a worked example, to put its own punctuation outside
the closing mark, and the model disobeyed in fifteen of twenty-two runs. A
convention that ingrained is absorbed by the deterministic side, not
requested of the model (and a prompt edit would bump the prompt version to
repair a defect that was the gate's own). The affected reports are repaired from their runs'
own archived first drafts, which pass under the corrected gate, no new model
call and no re-sample (the ledger-repricing precedent: exact recovery from
archived provider bodies); they read as ``composed``, the rung the corrected
ladder would have recorded, so their ledgers still show the two compose calls
the strict gate bought (a distinct "regrounded" rung that would disclose the
repair on the page was considered and set aside for now, 2026-08-16). The
repair reached twelve reports: the seven trimmed, and the five retried whose
corrective retries had obeyed "remove or replace the violating quotations"
by dropping quotations wholesale, one to none at all. The same convention had
a second-order effect on the trim rung: the sentence splitter read a period
inside a closing mark as mid-quote and never split there, so a sentence
ending on a quotation merged with its neighbour and both fell when either
violated. The splitter now ends a sentence just past a closing mark that
swallowed the punctuation, unless what follows reads as the sentence
continuing (a lowercase word); punctuation deeper inside a quotation still
never splits (2026-08-16).

Prose failure never fails a job: a compose call that hits our own capacity
refusal, outlives the client's transient retries, or finishes uncleanly
degrades to the disclosed withholding rather than aborting a pipeline whose
labels are already bought and banked. Ladder rungs are recorded, not
inferred: the report carries which one produced its narrative, so the page
discloses without re-deriving: a trimmed or withheld rung wears a notice on
the report page itself, not only in the folded trust panel, and the caption
under the prose names only the span kinds the certificate actually holds
(a narrative that quotes nothing does not promise verbatim quotes; one that
certifies nothing says so). The stored record carries no count of removed
sentences, so the trimmed notice stays generic (2026-08-16).

**The prompt-injection canary set lands with this milestone**: the first
surface rendering model prose, over a product whose entire input is
attacker-controlled text. A small versioned set of synthetic adversarial
reviews (committed like gold; synthetic so no real review is enrolled as an
attacker) covers the distinct shapes: direct instruction override, role
confusion, parser format-breaking, quote-laundering, and markup payloads
aimed at the render layer. The model-side run needs fresh output, so it is a
harness probe at prompt/model-change cadence (the evals-in-CI
deterministic-re-score boundary stays intact), while the render-side half
*is* deterministic and gates in CI: every review-sourced string renders
escaped, payloads inert. The set does not add a defense; it measures whether
the existing walls hold.

Scoring is a substring check, by construction (built 2026-08-07). Each canary
carries a **beacon** (a distinctive token its attack asks the model to emit),
so a breach is detected mechanically, with no judge in the loop and nothing
to calibrate; a test asserts every beacon actually appears in its own attack
text, since a canary that never asks for its beacon would score clean forever.
Two expectation classes keep the verdict honest: a *blocked* canary's beacon
reaching output is a wall failing, while the quote-laundering pair is
*measured*: a verbatim quotation of a planted claim passes the grounding gate
by construction, so those beacons quantify the named spine caveat instead of
registering as regressions. The run drives both surfaces, because the walls
differ: at classify the canaries ride the reviews block and the parse answers
the structural question a beacon cannot (did the answer still carry one
well-formed row per review, what a format-break actually targets), and at
compose they ride the evidence block as quotable spans, which is exactly how
attacker text reaches that stage in production. A per-run nonce keeps the
archive out of the loop (an archived reply would report last month's walls as
holding today), and the run uses in-memory bindings throughout, so adversarial
text never enters the durable provenance archive and a measurement never
charges a spend row.

> [!IMPORTANT]
> **Outcome.** The first live readings (2026-08-08, three runs, captures in
> `probes/captures/canaries/`): **every wall held on both surfaces**: no
> beacon leaked, classify parsed 7/7 rows cleanly under every attack, and the
> laundering pair never surfaced even as its expected measured limitation.
> The instrument's first catch was internal instead: the composer bent
> quotes' casing and punctuation to fit its prose (American comma-inside-quote
> typography, sentence-initial lowercasing), which the gate rightly refused.
> The quote rule was spelled out character-exact in **compose-v2**; casing
> edits vanished and first-attempt quote violations fell 7 → 4 on the fixture.
> The residual comma habit rides the retry ladder (the corrective rung names
> the exact spans), and the journaled rung counts on deployed jobs are the
> evidence for any further prompt tightening.

### Episode markers (`core/detect`)

**Spike-versus-trailing-median on the native histogram, kept deliberately
dumb.** A bucket flags when its volume exceeds k× the trailing median of
preceding buckets (a median resists being dragged by the spike itself);
adjacent flags merge into one episode span. The transform is pure core
(histogram in, episode list out, no LLM) and computes on the native rollup
unit, never a hardcoded month. The threshold is picked by looking, not
guessing: an offline pass over every histogram the project holds shows what
each k would actually mark, and k ships as config carrying that provenance.

**What the calibration pass found, including where this section's own
premise failed** (built and run 2026-08-07, `studies/detect_corpus`, capture
`probes/captures/detect_calibration.json`). Two planned inputs did not
survive contact with the data, and the ruling rests on what did.

The **49 corpus histograms are unusable for this**, and permanently so. The
frozen corpus was built by the predecessor `steam-reviews` project by
fetching each game's *recent* reviews directly: a newest-first prefix per
game, not a draw across its lifetime (Arda's account, 2026-08-08, confirmed
in the data: 48 of the 49 games' newest bucket falls in 2026-06, the fetch
month, while their oldest scatters from 2011 to 2026-05). Rebuilt into
histograms those slices span a median of five monthly buckets, with 29 of 49
at six or fewer: fewer than the trailing window a baseline needs before
anything can flag. Worse than short, they are *systematically* wrong for this
question: because each game's prefix fills at a per-game cap, span runs
inversely to review velocity, so the only corpus games with enough history to
flag are the slow ones: exactly the population the volume floor exists to
suppress. Calibrating there would have measured the corpus's fetch shape and
called it game behavior. This is not a gap a later pass closes; the corpus
holds recency prefixes by construction. The pass reads them only to report
it, and the evidence base is the 35 live snapshots (24 long-tail, 5
corpus-check, 6 fresh-buy), which carry all-language volume at the native
rollup unit, the production instrument's own shape.

The **Valve-marked windows cannot validate k either**, for a granularity
reason worth stating: three exist on disk, one of them a degenerate
four-year span that any detector "catches" for free, and the other two are
sub-bucket events: a two-week window in a monthly series. The 2022 window on
one fresh-buy game is never caught at any k, because a fortnight of bombing
dilutes into a month that never triples. So marked-window overlap stays what
the render rule always said it was (a fact stated when present) and is not
evidence for a threshold. Claiming otherwise would have been the calibration
flattering itself.

What the live snapshots do support is a **marking-rate** ruling, and it is
robust. Across k, the number of episodes a marked game carries barely moves
(median 2 at k = 3, 4, and 5); what k actually controls is *how many games
show any marker at all*: 29, 25, and 21 of 35. The choice is therefore about
how often a timeline says anything, not about clutter. **k = 4** ships, with
a trailing window of 6 buckets and an absolute floor of 30 reviews: roughly
70% of games carry a marker, about two each, marked buckets are ~2.6% of a
timeline (visually sparse), and the median flagged bucket runs ~6× its
baseline: unmistakably a spike rather than a wobble. Sensitivity is
reassuring rather than knife-edge: sweeping the window over 4/6/8 and the
floor over 10/30/50 moves the marked-game count only between 22 and 28 of 35.
The floor itself is load-bearing for the long tail, where a ratio over a
near-zero baseline is arithmetic noise wearing a large number. Markers render observations only
(span, magnitude, review count, and overlap with a Valve-marked window stated
as fact), with no causal noun anywhere: "review activity spike," never
"backlash," because an unverified cause in the flagship timeline is the
fluent-wrong-answer failure the English-first ruling refused. A one-line
legend states the discipline ("statistical detection over all-language
volume; no cause attributed"), turning the absence of explanation into
visible method. The chat milestone becomes where "what happened here?" gets
asked, with receipts.

**The markers do not render on the report page (ruled 2026-08-14, the polish
run).** However disciplined the vocabulary, a highlighted span puts a
question on the page the report refuses to answer — the reader sees
"something happened here" and the product declines to say what, which reads
as withholding rather than method. Detection still runs and every report
persists its episode list (the investigator milestone's raw material); the
report page simply doesn't draw it. The timeline's reading instead comes
from pairing volume bars with a positive-share line on the same time axis:
a reader spots the telling conjunctions themselves — a volume spike wearing
a share dip — without the page asserting a detection it cannot explain.

### The frontend

**Server-rendered pages plus a small vanilla-JS layer; no SPA, no bundler.**
The product is two pages (search and report) with one dynamic surface, the
narration stream, which browser-native `EventSource` and DOM code handle in
tens of lines. A SPA would be toolchain weight signaling nothing this
milestone needs (the portfolio pillar here is the ops story, not framework
fluency); hypermedia libraries solve interactivity this page doesn't have.
Jinja2 rendering keeps the persistence seam clean: the report row's
structured content renders server-side, presentation iterates freely.
Skeleton first, polish after it demonstrably works; the app-UI aesthetics
plugin styles the shell at build time and the dataviz conventions own the
charts.

**The live page's checklist lists the stages in the pipeline's own order
(2026-08-17).** Episode markers detect off the planning histogram before the
first window is fetched, so their row sits after plan and before fetch;
listed after classify, the early tick read as a state bug (the sweep's two
live lenses called it legitimate parallelism showing through, but the cause
was a mis-ordered list). Fetch and classify do overlap, as a producer-consumer
pair, and neither narrates a done of its own; on a clean run classify narrates
nothing at all (its messages are rebatch, isolate, and refusal warns), so the
"labels banked" line is the pair's joint completion and settles both rows on
the page. A classify pulse of its own on clean runs would add narration in
the interleaved path, which the job journal reads for stage timings — a
pipeline change, recorded not built. Lanes for parallel stages (the sweep's
item) dissolve once the order tells the truth: fetch and classify are the only
real overlap.

**The report page, top to bottom:** header with capsule art and the
provenance one-liner (analysis date, sample-of-population, path, language
note); the composed narrative with mint citations rendered visually distinct
from prose (the reader sees what is model voice versus minted fact); the
aspect table as polarity-stacked share bars (the diverging blue/red pair,
mixed+neutral folded gray; the share says how much talk, the stack says
what kind) with the interval carried as the share label's ± (Wilson plus the
regime allowance, half-width; exact bounds on hover; take-all games show no
± and read "exact counts"), rows under the five-review evidence floor cut
entirely and the table folding past its top ten behind "see more" (the
display floors, 2026-08-14: counts under five sit at the classifier's
false-positive floor, so a cut costs less trust than mislabeled evidence),
each aspect expanding to verbatim evidence quotes (sentence-expanded from
the review at display time and dated), the candidate stratum below honestly
marked emergent-uncalibrated; the all-language timeline as one panel —
volume bars over a positive-share line on a shared time axis with numeric
scales, one per-month hover joining both readings, Valve-marked windows
overlaid, episode markers deliberately unrendered (the marker design above
carries that 2026-08-14 ruling); and the trust panel (the
protected element under any schedule pressure, folded as reference material
but born open whenever the marked-share caveat says the calibrated bars are
not certified), carrying the sample method, the interval regime this game
got, language mix, marked-share state against the 2% floor, the evidence
floor rule, the published instrument numbers (classifier F1 with CI,
misattribution rate, judge agreement), the versions triple, and the
methodology link. (The aspect
table's encoding was re-ruled at the aesthetics pass, 2026-08-08: drawn
whisker hardware read badly and a shaded interval band proved confusable
with the gray polarity segment, so uncertainty moved off the chart into the
label; the polarity stack answered the "13.5% of what kind of talk?" gap.)
During a cold job the page *is* the narration: stage progress streaming,
sections filling in as their data lands. The parked
micro-window variant gets its trigger judged here, at real rendered
whiskers: calm ±2.5 and spiky ±15 seen with eyes, reopened only if that
judgment fails.

> [!IMPORTANT]
> **Outcome (2026-08-08).** The judgment ran at the step-6 build: the calm
> case read live (the first real report, Baldur's Gate 3, n=711, Wilson
> whiskers), the spiky case at the rendered fixture (the widths are the
> ruled constants through the shipped seam; only the game was synthetic,
> live whole-life pools smoothing spikes into rarity). Ruled acceptable:
> the wide bar is the honesty working: rare, explained by the trust
> panel's regime line, and preferable to more sampling machinery narrowing
> a bar that is wide because the data is genuinely lumpy. **The
> micro-window variant is closed permanently**; its last trigger fired and
> did not trip.

**Build-time rulings (step 6, 2026-08-08).** The renderer is the one
swappable module: everything presentational (templates, static assets,
view-model helpers) lives in ``serve.web``, attached over the JSON app by
the composition root, so the JSON surface never imports the renderer (a
dedicated import-scan test pins the wall; the package-grained dependency
law cannot see an edge inside ``serve``). The renderer consumes only the
published surfaces an external frontend would: the ``Report`` contract and
the JSON/SSE routes. A later frontend rewrite therefore replaces this one
package and rebuilds its escaping tests (the wall is per-rendering-
technology by design) and touches nothing below. Two disciplines keep the
claim true: presentation adaptation happens in view-model helpers, never as
display-shaped fields on the stored contracts or the SSE event vocabulary;
and hostile-content escaping belongs to whatever renders. The composition
root (``serve.main``, env-wired: key, db path, explicit ontology-v2 pin,
uvicorn) pulled forward from the containers step, because the frontend
chunk is look-at-it development: judging rendered pages needs a running
server, and the entry was going to exist anyway; the containers step now
containerizes an entry that already runs. The shipped interval rule
(bands, regime test, the ruled allowance constants, ``peak_window_share``,
and the composed ``shipped_interval``) relocated from the study shells to
``core.allowance`` when the report page became its first production
consumer: the study packages are import-forbidden to everything, so the
whisker math had no legal home until it graduated; the mint arithmetic
that re-derives the constants stays in ``studies.allowance``.

**The Content-Security-Policy (2026-08-12).** The second wall behind Jinja
autoescaping: the policy ratifies what the pages already do (same-origin
external scripts only, one stylesheet, self-hosted fonts, same-origin
fetch/SSE, images from Steam's CDN), and the browser refuses everything
else, so an escaping gap stops yielding execution. Strict except two narrow,
argued allowances: ``style-src-attr 'unsafe-inline'`` for the report bars'
per-report percentage widths (attribute-level CSS can neither run script nor
use selectors; injected ``<style>`` elements (the real CSS vector) stay
blocked), and Valve's asset-CDN family in ``img-src`` as the wildcard
``https://*.steamstatic.com``: the search thumbnails arrive verbatim from
Steam's storesearch answer and Valve serves them from several hosts in that
family, so an exact-host allowance would break them silently the day Steam
shifts or regionalizes the field; the header-art origin the app itself
mints is pinned inside the family by test. The header is stamped by the
app (``serve.web.csp``, HTML responses only), not the proxy's static header
block, because it carries a per-response nonce with exactly one consumer:
**Cloudflare's bot detection injects an inline bootstrap into proxied HTML**
(per-response values, unhashable), and its injector reads the CSP response
header and stamps the nonce onto what it injects (documented behavior,
verified live 2026-08-12; on the free plan the injection is not
switch-offable, and disabling Bot Fight Mode traded away bot cover in front
of a money-spending endpoint). ``frame-ancestors 'none'`` supersedes the
interim ``X-Frame-Options`` at the proxy. The known coupling, recorded
rather than hidden: if pages ever break with a CSP violation on an inline
``__CF$cv$params`` script, the injector's nonce behavior or the zone's bot
settings changed; the policy is where to look. The pass's side catch:
FastAPI's auto-docs (``/docs``, ``/redoc``, ``/openapi.json``) had shipped
public as an unexamined framework default: an interactive console to the
money-spending submit route, rendered off the app's only third-party CDN
load. Declined deliberately (no consumer exists; the JSON surface feeds
this app's own pages), pinned by test.

**Accessibility (2026-08-17, the polish run).** The automated audit is a
floor, not a verdict: every page scored 100 on Lighthouse's accessibility
category while three real gaps stood, all of the kind an axe rule cannot
see (data behind a mouse hover, a silent visual, an accepted-but-weaker
labeling form). The rulings: the timeline's per-bucket numbers, previously
hover-only tooltips, are restated as a collapsed table under the chart (the
chart's text alternative — keyboard and screen-reader path in one, and the
exact month for a sighted reader who wants it), over a tab stop per bucket,
which would make a long history a hundred stops to cross; the tooltip and
the table row render from one story, so they cannot drift. Each aspect bar
is one accessible object (``role="img"`` named by the four-way sentiment
split, its segments hidden from assistive technology), since a screen
reader on a collapsed row otherwise heard the aspect and its share and
nothing about polarity; visible counts inside the segments were declined
(thin segments cannot hold them; the detail line already carries them). The
search input gained a real off-screen ``<label>``. Artwork alt text was
declined twice over: the library cards' images sit inside a link whose text
already names the game (a non-empty alt double-announces), and the report
header's capsule keeps its recorded empty alt (a delisted game's 404 would
render a real alt as broken-image text) with the h1 beside it. The library
page's provenance line, tags, and the site footer rose to 12px, the phone
legibility floor Lighthouse's mobile run flagged (only 14% of that page's
text cleared it). Method: Lighthouse and axe as the regression floor, one
keyboard-only pass and one screen-reader pass as the audit. The gap that
pass left, closed the same day: the live progress page filled its stage
checklist in silence for a screen reader (no live region anywhere in the
templates or scripts). It now carries an off-screen ``role="status"`` region,
present from first paint (a region inserted later is announced unreliably),
that the script feeds transitions only: a stage's first activity, each done,
each warn, and the terminal failure. Per-window and per-batch progress stays
visual, since read aloud it would drown the run, and the compose stage
narrates its whole prose as progress, which the report page reads anyway.
The set of announced transitions survives the reconnect replay on purpose,
so a replay rebuilds the visible rows without narrating the run twice.

### The box

**Docker Compose behind one shared Caddy; SQLite bind-mounted on the host.**
Each project on the box is a self-contained compose stack; Caddy runs once as
the box-owned proxy (automatic HTTPS, an SSE-clean config measured in lines)
on a shared Docker network, and a new project is a new compose file plus one
Caddyfile stanza: the multi-project box made mechanical. Containers on an
owned box earn their ~250 MB: the deploy unit becomes an image, so what CI
tested is byte-for-byte what runs; rollback is the previous tag; and the
compose files are themselves the provision-as-code portfolio artifact. The
database lives on the host filesystem bind-mounted in, outliving every
container rebuild, readable by backups without entering Docker.

**The domain is deferred to launch.** The skeleton serves on the bare IP;
a free dynamic-DNS subdomain gives Caddy a real hostname for Let's Encrypt
if a shareable HTTPS link is wanted mid-build; the bought domain plus
Cloudflare free tier (DNS + proxy, hiding the box's IP) land when the
public-URL moment actually approaches. Nothing built earlier changes: the
Caddy config swaps a hostname. GitHub Pages was considered for an interim
front and rejected on mechanics: static hosting cannot run the server that
renders the report or hold the SSE stream open; the portfolio site's role is
the project page that links to the deployed app.

**Deploy: CI builds the image, the box pulls it.** GitHub Actions builds on
push to main and pushes to GHCR; a short deploy script on the box pulls and
restarts: triggered manually at first, automatable later. The box only ever
runs an image that passed CI, and the 4 GB box is never a build server.

**"Automatable later" arrived as approval-gated delivery, deliberately
short of continuous deployment** (2026-08-11, superseding the launch-era
"the box never auto-pulls" manual pull). The deploy job sits behind a
required-review GitHub environment: green main mints the image, a
deliberate click ships it. Mechanics chosen for the trust direction: the
pipeline's ssh key is forced-command (`restrict,command=` pinned to the
box's deploy script) so a leaked Actions secret can trigger a deploy and
nothing else; the box's address rides environment secrets, keeping the
origin out of the repo. The job hands the script the run's *own* image sha:
approval hours after a push ships exactly what was reviewed, immune to
`:latest` moving underneath; the box retags its `latest` to mean "last
approved deploy", so rollback stays the previous sha tag. The script
refuses, naming the job, while an analysis is live (a recreate cuts a
visitor's minutes-long, money-spending job mid-run, which is the argument
that kept a human on the trigger at all), and the job goes green only
after the new container answers `/healthz` through the visitor path. The
manual pull survives as the runbook fallback.

**Monitoring lives off the box.** A `/healthz` endpoint checks the real
things cheaply (database opens, job worker alive); an external free pinger
watches it (a monitor self-hosted beside the app dies with it). The richer
observability (spend totals, job history, failure rates) is the in-app ops
dashboard reading the same store, a product page rather than infrastructure.

**Backups: nightly `sqlite3 .backup`, gzipped, off-box to Drive via
rclone**: the corpus and study-run precedent extended to the live store.
The online-backup API is used deliberately (a plain copy of a live file can
snapshot a torn state); retention keeps roughly seven dailies and four
weeklies; the file carries the always-keep class: the label pool and the
response archive, the genuinely unreproducible layer. The discipline that
makes it real: verified by restore at setup, not by upload: a backup never
restored is a hope. Litestream stays parked; its trigger remains the chat
milestone's write pattern.

**The box layer left this repository on 2026-08-27.** Everything above
describes the box as it was designed and built here: `deploy/box/` carried
the proxy stack, the Caddyfile, the firewall and backup units and the
runbook, because the first tenant had to carry the box. A second tenant
(the leave-impact Frappe stack, 2026-08-26) made "first project in carries
it" the wrong owner: the shared layer was extracted into the platform
repository (github.com/arda-basarici/platform) and cut over live; this repo
keeps its deployment entrypoint and its application secrets, and
`deploy/box/README.md` records file by file what moved where. The design
choices stand unchanged; only their home moved.

### The spend breaker

**The public submit gate counts jobs, not dollars: a daily fresh-analysis cap,
checked at admission.** A dollar ledger settles late: a burst of
submissions all pass a spend check before any call lands a cost row, and
closing that hole needs worst-case reservation math. A count increments at
the moment of admission (there is nothing deferred to reserve against), and
it is honest to the visitor in a way a budget figure is not: "today's fresh
analyses are used, published reports stay open." Two counts stack (the
2026-08-10 re-sizing): a *per-visitor-IP* daily cap (default 5) is the
fairness rule (every visitor gets their own allowance, one curious visitor
cannot drain the day for everyone), and the *pooled* daily cap (default 50,
raised from the launch 5 once the ledger's true prices landed) remains the
un-burstable outer wall: only the pooled count bounds the admitted-but-
unsettled backlog, so a per-IP cap alone would leave the hostile ceiling
scaling with attacker IPs. Dollars still guard the
day, demoted to backstop: a third refusal condition on the ledger's settled
spend for the day (default $2, one `cost_since` read) exists to stop a
runaway *day* (jobs running hot toward their per-job cap), not bursts. The
numbers agreed by the ledger's real prices at sizing: live jobs settled
$0.007–0.017, a maxed-out 50-job day ≈ $0.85–1.00, so the $2 backstop cleared
every legitimate day and fired only on pathology. Re-read 2026-09-24 at the
repriced ledger (V4.1 Flash, rate-period pricing): completed jobs settle
$0.006–0.058 off-peak, median $0.032, double in peak hours, so a maxed-out
day lands ≈ $1.60 off-peak and ≈ $3.20 at the peak median. Ruled: the $2
dial stays — in peak hours the backstop doubles as a volume cap on
legitimate demand, an accepted trade at this traffic; the hostile ceiling under
all guards stays pool cap × per-job budget for a burst that admits before
anything settles. All three numbers are env dials
(`STEAMLENS_DAILY_JOB_LIMIT`, `STEAMLENS_PER_IP_DAILY_JOB_LIMIT`,
`STEAMLENS_DAILY_SPEND_BACKSTOP_USD`): spend
comfort is an ops setting, not a code commit.

**One in-flight job per visitor IP, from queue memory: no storage.** The
queue already knows what is pending and live; the fairness check is a lookup
against state that restarts honestly (a restarted queue is empty, and its
jobs are gone). The launch design accepted a residual here (a patient IP
draining the day's slots sequentially, ruled "not worth per-IP daily
bookkeeping in a portfolio demo" while the pool was 5), overturned by the
2026-08-10 re-sizing: with the pool at 50 the drain stops being cosmetic,
and the bookkeeping turned out already paid for (the admissions journal
records the IP per row; the per-IP count is the same table asked with one
more WHERE clause). The client IP is read as the *last* entry
of `X-Forwarded-For`: the one entry the box's own Caddy appended, which a
visitor's forged header cannot displace (their fabrications sit to its
left); absent the header (dev, no proxy), the socket peer. Uvicorn's proxy
trust stays unwidened.

**Check order: attach → exempt → in-flight → your count → pool count →
backstop.** A request
for an already-queued app attaches to the existing job before any guard
runs: no new spend, no new job, so re-clicks and shared curiosity stay
free. The personal guards answer before the day-wide ones so a refusal
explains the visitor's own situation whenever both apply. Exemption is an
unlock cookie, not an IP allowlist: a secret in the
box env (`STEAMLENS_ADMIN_TOKEN`), a one-time visit to `/unlock/<token>`
setting a long-lived HttpOnly cookie (survives home-IP rotation, works
from any device, revoked by rotating the token). Exempt requests skip the
abuse guards but keep the per-job $1 budget: that one is a
correctness guard, not an abuse guard.

**The submit is id-only; the store names the job (2026-08-17).** The
endpoint is the product surface and the page is one client of it: a
scripted `POST` reaches `/analyses` through Cloudflare exactly as the search
page's own fetch does, bounded by the same walls (verified live: a curl
submit ran and published Dwarf Fortress under the visitor's ordinary
allowance). A `GET` never triggers anything, by the safe-method rule the
whole internet relies on (crawlers and link previews fetch every URL). What
the walls did not bound was one string: the request carried a
`requested_name` for the runner's identity guard — a CLI-era protection
against a wrong-appid pull that the storefront pick, made by id, cannot
produce — and that string was the only visitor-typed text the app stored
and rendered (the ops trace table's game column from the row's insert; a
pulled game's report title via the runner's fallback). Ruled: the request
carries the app id alone; after the gate has agreed to admit and before the
admission is journaled, the door asks the Steam door's name-only read
(`SteamClient.store_name`, one paced appdetails call — a refused caller
never makes the app call Steam, a Steam hiccup burns no allowance slot and
answers the same 502 as `/search`), and the job is named by the store or,
honestly, `app N`. An attach reuses the live job's name; a cached answer
never reaches the door. The receipt returns `game_name`; an old client's
extra field is ignored, not refused. The identity guard stays in the Steam
door for its CLI callers; in the serving path its mismatch case cannot
arise, and its no-data case narrates plainly ("the store has no record for
app N — analyzing its reviews as 'app N'"): a game pulled from the store
keeps its reviews (Deadpool, 224060: no page, 3,311 reviews, probed
2026-08-17) and is analyzable by a direct submit only — the storefront search
cannot offer it — so `app N` is its honest title. Refusing no-data ids at
the door was considered and set aside: appdetails alone cannot tell a false
id from a pulled game, and the runner already settles a review-less id
failed at no LLM cost.

**Admissions persist; the day is UTC midnight, computed in the serve
layer.** A new `admissions` table (timestamp, ip, app id; the schema's
append-only migration discipline) makes the daily count survive restarts
and doubles as the ops dashboard's "did anything happen today" read. The
parked `daily_reset_utc_hour` knob was inspected for reuse and stays
parked: it is an `llm_client` concept, the *provider's* free-quota rollover
on the rpd path, dead on the serving path, and the serving provider is
pay-per-token with no daily window to align with. The spend day is purely
this app's accounting day; plain UTC midnight, owned where it is used.

**Refusals render where the visitor already is.** The submit is JS-driven,
so the refusal is a 429 with a JSON detail the search box displays inline:
three distinct honest texts (your analyses used / day's analyses used / one
analysis at a time), each naming the UTC-midnight reset, rather than a
page navigation. Reports
stay browsable untouched; the breaker guards only the submit route.

### The observability step (LLMOps, designed 2026-08-09)

**The ops surface is public read-only, aggregates only.** The monitoring
ruling's "in-app ops dashboard" ships as `/ops`: a portfolio app's ops
surface is itself on display, so it renders for any visitor, and the
security audit's no-raw-IPs constraint is enforced by *shape*, not renderer
discipline: the store's ops read model (`OpsReads`, a read-only tenant over
the journals the writing tenants own) produces contract rows that
structurally cannot carry an IP. Flipping the page behind the unlock cookie
later is one wiring change. `/healthz` answers the two real things cheaply
(worker thread alive, database opens) with the failing check named in the
503; deliberately no Steam or provider probe: their hiccups must not read
as this app's downtime.

**Ledger cost is billed truth, not list price.** The provider's prefix-cache
discount is 50x on hit tokens and ~90% of a classify prompt is the shared
ontology prefix, so flat list pricing overstated the ledger ~5x against the
dashboard (reconciled 2026-08-09; the fresh-buy note had measured the same
4.9x gap from the other side). The fix runs the full seam: the adapter reads
the cache split off the wire (either spelling; capped at the prompt total),
`TokenUsage` carries it as a defaulted subset field (omission degrades
conservative: cost overstated, never hidden, the inverse of the
thinking-token failure mode), the spec prices a cache-hit rate verified
against the provider's published table at encode time, and the worst-case
reservation stays flat-priced on purpose (a guard, not accounting).
Pre-existing rows initially kept their stored costs (forward-only ruling: an
append-only ledger is not rewritten for a formula bug measured in cents),
with the ops page disclosing the overstatement; overturned 2026-08-10, one
day later, on a reason the ruling hadn't weighed: every *all-time* surface
(spend per report, stage totals, screenshots leaving the site) kept
broadcasting the ~5x-inflated numbers, and the response archive made an
*exact* repricing possible; each pre-fix row's true cache split recomputed
from its archived provider body by the live pricing formula, matched on full
token tuples, never estimated (`scripts/reprice_ledger.py`, dry-run +
self-check: post-fix rows must recompute to their stored cost exactly). The
ledger's one sanctioned revision, run once against a snapshot-backed db; the
provider dashboard remains billing truth to reconcile against.

**Every journaled call carries its duration and its run.** The client
already measures dispatch-to-response latency for telemetry; the ledger now
records it (retries included, NULL on pre-step-6 rows: "not measured",
never a fabricated zero). Attribution is constructor-level: the shells build
one client per job or study run, so a `run_id` stamped at construction is
exact by construction, and jobs, reports, and spend all join on one key.

**The job journal makes job outcomes survive the queue's memory.** One row
per job in `jobs`, keyed by a run id minted *before* the pipeline starts
(the runner receives it rather than minting internally). The composition
root's `run_job` wrapper owns the row (insert at start, settle at finish),
keeping the queue storage-free and the runner unchanged in responsibility;
an escaping exception settles `failed` with its error text. Settling is an
UPDATE, deliberately the first non-append tenant: a job row is a lifecycle
record, and a started-but-never-settled row is the honest trace of a process
death. Banked at settlement: labeled, reused (the label-pool cache
economics), durable failures, refused batches; the runner's remaining
totals stay narration-only. Stage timings derive from the job's own
narration history (events stamped at arrival; no runner instrumentation),
stored as display JSON: approximate by nature, declared, and what the
parked narration-ETA calibration needs. Gate refusals journal to `refusals`
(timestamp and which guard fired, no IP by shape) so "how often does the
breaker fire" is answerable from the store.

**The trace table states what the journal cannot see (2026-08-17).** The
ops page's "recent analyses" table is one row per journaled job, and the
journal is younger than the store: ten reports were published before it
existed, their calls carry no run id, and both lenses of the live-app sweep
read the missing rows as an unstated operator exclusion (tier 3 #11). The
query excludes nothing; the rows predate the instrument. Ruled: the
aggregates stay all-time (they reconcile with the library and the bill),
the heading stays, and the collapsed about block carries one computed line:
how many published reports no job row accounts for and how much ledger
spend joins no job row (`OpsReads.unjournaled_totals`, keyed on the one
structural marker, no job row, never on a date, so the number stays true
should a report ever lack a job row for another reason; absent on a store
born after the journal). The cost is defined as "joins no job", not
"carries no run id", off the live verification: run attribution and the
journal's insert shipped in two deploys 57 minutes apart on 2026-08-09,
and one report (Europa Universalis IV, 00:38 UTC) ran in the gap,
attributed but unjournaled; the narrower definition left $0.0138 of the
skeptic's arithmetic unexplained, the wider one makes all-time spend equal
the table's rows plus the line by construction. Considered and set aside: a caption under
the table (the 2026-08-14 simplification pass folded per-table captions
into the about block, and this is provenance); scoping the whole page to
the journal's era (trades an in-page mismatch for a cross-page one against
the library and understates spend against the provider dashboard the page
names as billing truth); deleting or re-running the pre-journal reports
(destroys or re-buys real history to fit a heading; the ledger rows would
still join no job).

**Tier-3 platforms, named and rejected.** Langfuse (now wanting Postgres +
ClickHouse), Prometheus+Grafana, and LangSmith all fail the standing "does
*this product* need it?" test on a 4 GB box running one process over one
SQLite file: a second stack to babysit, monitoring the monitor. The
concepts those platforms embody (traces (a job), spans (its stages and
calls), cost per token, latency percentiles, failure rates, cache hit
rates) are exactly what the journals above implement natively, so the
LLMOps story is told in its real vocabulary while the architecture stays
honest. The platform *tool experience*, if ever wanted, is an experiment-lab
afternoon on a hosted free tier, not this box.

> [!IMPORTANT]
> **Outcome (M3, closed 2026-08-12).** Live and public at
> steamlens.ardabasarici.dev: the domain behind Cloudflare's proxy, the origin
> firewalled to the edge, approval-gated delivery shipping since 2026-08-11. The
> first real report (Baldur's Gate 3, n=711) landed 2026-08-08 inside the designed
> envelope, and Hades was the first served through the domain (2026-08-10); live
> jobs settle at $0.007–0.017 against the $1 per-job cap, read from the same
> journals the ops page renders. The serving walls (edge, gate, canaries) were
> each probed live at go-public. Product refinement continues as the polish track
> between milestones, not as milestone remainder.

---

## The recommender chat (M4)

*Designed 2026-11-14. The steps of a turn are built and run end to end since
2026-11-19, and the tab with its caps since 2026-11-20, unlisted; the second
stage is not built. Figures in this section were read from the 2026-09-24 copy of the
serving database (53 reports, 27,163 stored reviews) unless a different date
is given. They illustrate the design and are not published readings.*

**One tab: recommending games, and discussing one.** A player describes what
they want and the chat suggests games from the library of measured reports.
It asks before it suggests when it has to. A request that carries something
gets at most one clarifying question. A request that carries nothing at all
("what should I play") may get two or three, in one message, so the chat has a
few things to work with; after that it answers regardless, with a small varied
set of well-received games said plainly to be a starting set and not a fit.
Asking until something turns up was declined, since it makes the tab a
questionnaire.

The player can also discuss one game, which is a different kind of turn from
asking for one. Any library game can be discussed, not only one the chat
suggested. Those answers draw mainly on that game's stored reviews and its
report, and also on the store data held for it. Nothing comes from the model's
own memory of a game, so the tab gives no walkthroughs, tips or opinions.
There is no separate chat on the report page. A report is what makes a game
recommendable, and everything stored under it is readable: the frozen
aggregates, the labelled mentions with their evidence quotes, the review text,
and the game's store metadata.

**The promise is fit to what the player stated.** The chat says which library
games fit the request and why. It does not predict enjoyment, say a game is
worth its price, or tell anyone to buy; "should I buy it?" is answered with
what reviewers say about the aspects the player cares about, or with a question
about which aspects matter.

**A named game is read by what the player said about it.** *Ruled 2026-11-15,
with the paragraphs that follow through the structured request, from twelve
example conversations written before the request structure was seen. Their
figures are from the copy of the serving database taken on the evening of
2026-11-14 (115 games, 60,514 counted reviews).* "Something like X", with X in
the library: the parts the player says they liked become wants like any other,
so "like X because of this and that" and "I want this and that" run through
one mechanism. When the player did not say which parts, the chat may ask. The
first design read "like X" as a request for X's measured profile; a profile
says what reviewers think of a game, not which part this player cared about.
"Already played X" removes X from the suggestions and does not say whether the
player liked it, so the chat may ask that too, and steers toward or away from
similar games by the answer.

A game outside the library gets a named answer, "not measured yet", with the
link to the ordinary report flow so the player can have it analysed, and a
question about what they like in it. The model may use what it knows of an
unmeasured game to ask that question well, and for nothing else. Suggesting
from that knowledge was declined: the model's memory of a game is not
evidence, and for a game newer than the model it is invention. The first
stage does not write this answer: a turn about an unmeasured game ends on a
short text that says the library holds nothing measured for it (the turn and
how it ends).

A comparison with a named game ("less frantic than X") is the model's
judgment, made in words from review evidence on both games. Code gives such a
want no verdict: it reads "cannot tell" on every game, whatever its target
shows, because "less frantic than Hades" read as "not frantic" would fail
every game where the word clusters. The check holds a statement that cites
the named game's reviews to citing its own game's as well; a comparison made
in words with only one side cited is not seen by code. Ranking the two on how
often a word appears was declined as noise: "frantic", "hectic" and "chaotic"
appear in 86 of the library's reviews across 49 games. That the judgment did
not come from the model's memory cannot be checked by code, so comparative
answers are read by hand.

**Wants carry how firmly they were meant, and none may disappear.** The first
design marked a requirement as defining or quality. The examples showed that
what may give in a near miss is decided by how the player said it, so each
want carries a firmness: a must, a want, or a nice-to-have. The wording sets
it ("really", "it needs", against "I'd prefer", "would be a bonus"). Where the
wording is neutral, a want about what kind of game it is (a racing game,
co-op, runs on Mac) is a must, and a want about how good a part is (a strong
story) is a want. The number of wants matters as well: three wants are each
meant, ten describe a wish, and a game that meets most of ten is a good
answer. Two things never give, whatever the count: a want the player stressed,
and the kind of game. A game that is not a racing game is never offered for a
racing request.

For each want and each library game the chat holds one of three statuses:
matches, fails, or cannot tell. A game that fails a must is never suggested
as a fit, however well it fits the rest. A game that misses a softer want may be offered
as a near miss with every mismatch named. How far to reach is the model's
judgment, weighed against how many wants were stated, and it should not reach
far: a game that misses most of what was asked is "nothing fits". A fixed
limit of one miss was declined, and so was offering the closest game however
far off. When nothing fits, the chat says so, never substitutes, never claims
no such game exists, says the library is a hand-picked set, and links the
report flow; it may ask about a neighbouring kind of game only if the player
has not ruled substitutes out.

**Code reads the evidence and removes no game on it.** *Ruled 2026-11-15.*
The first design had code drop every game that failed a must before the model
saw the sheet. That makes the tab a filter with a model writing its
sentences, and the readings it would filter on are not certain enough to act
alone: the store does not list Dark Souls III as an RPG, and a cluster of
"timer" can be reviewers writing that a game has none. So the sheet holds
every library game with its reading on every want, grouped by whether the
game meets the musts, is "cannot tell" on one, or conflicts with one, and the
pick is made with the conflicts in front of it. One kind of conflict may be
put forward: a must that avoids words, failed because the words cluster. A
store fact that fails, a release year outside the range and a criticised or
divided aspect are the store's answer or the reviewers', and a candidate that
fails a must on one of those is a fault of the pick's answer, named in its one
retry and removed after it. When a reply offers a game that conflicts with a
must, the offer stands only if a statement about the game names the want and
cites reviews of that game read on it, and the game is then offered with the
conflict named, never as a fit. A reply that does not do so draws the check's
objection, which states the reading, at most once; if the fault still stands
after the retry, code removes the game. A justification in the model's own
words does not count, because a model
asked to justify a pick always can. A pick with no review to cite cannot be
made, which is how a farming game stays out of a racing request. Two rules
have no exception: only library games are offered, and a game the player said
they had already played is left off the sheet. The cost is that "a must is
never relaxed" becomes "a must is never relaxed silently". Code checks that
the statement lists the want and that a cited excerpt was fetched for that
game and that want. Whether the excerpts support the offer is read by hand.

"Cannot tell" counts for neither side: few mentions of grind is not evidence
of little grind. A game that is "cannot tell" on a must may still be offered,
because most real requests carry one condition that cannot be checked. It is
never called a fit, and a bare "unverified" is not enough: the reply says what
was looked at, what was found, and what that does not show. It is not offered
when two or more of the passages read on that must describe the game itself
as going against it, such as reviewers describing the thing the player wants
to avoid, and the reply may then say it was left out and cite them. *Ruled
2026-11-24*, from a reply that offered two games against a stressed "not much
reading" with a warning, where the ruling on near misses has a stressed want
never be the one that gives. One such passage is not enough, nor is a passage
about another game. The judgment is the answer call's, code cannot check it,
and on the revision's own comparison run the call did not make it: under both
wordings tried it still offered such a game with a warning. Which sentence is
used is decided by a count and not by the model. Read on the library's 60,514
counted reviews, "timer" and its variants appear in 133 reviews across 59
games and "red dress" in none. So when reviewers do write about the thing
(the phrase appears in about ten or more of the library's games), the reply
says it comes up in reviews of games here, that none of this game's reviews
mention it, and that this does not mean the game lacks it. When a few of the
game's own reviews mention it, too few to count as a cluster, the judge has
those reviews to read. When reviewers do
not write about it, the reply says reviews do not go into that kind of detail
and gives no count, since reporting an empty search would present it as a
check. When no data of any kind exists (how a game runs on one laptop), the
reply says so and uses whatever partial evidence the reports hold, such as
leaving out games whose performance is clearly criticised.

A want about how much ("short", "hard", "lots of content") never maps to an
aspect. An aspect's sentiment says how well a part is received, and a game's
length being praised does not make it short. Such a want becomes a search term
when there are words to look for and is otherwise kept as it was said. A want
that maps to no stored field at all is kept in the player's own words and
reported as "cannot tell"; the failure this guards against is a request that
loses its one unverifiable condition and still returns a confident answer.
Indifference ("don't mind if it's long") is not a want.

**The structured request.** The understand step fills one fixed structure from
the whole conversation on every turn, so a want the player withdrew is absent
from the next one, and nothing is carried from turn to turn but the
conversation and the seed that orders the sheet the pick call reads. It holds the
intent (a recommendation, a discussion of one game, a question about what the
numbers mean, or out of scope); the games the player named, each with the
library game it resolves to if any, its role (like this, not this, or the
subject of a question), how the player felt about it (liked, disliked or
unknown) and the parts they liked; the wants; whether substitutes were ruled
out; whether the player asked for other games than the ones already offered;
and whether the player asked to see quotes or numbers. A want keeps the
player's own words, its firmness, whether it is wanted or avoided, and exactly
one target: a store fact from a curated vocabulary, a range of release years,
one of the pinned aspects, a search term given as the spelling variants of
one idea, or nothing.
It can also be marked as only partly checkable, and as a comparison with a
named game. Code resolves a named game against the library; the model never
does.

The intent says what the latest message asks for, and the wants are whatever
still stands in the conversation under any intent. A question about one game
carries its questions as subjects, one each, with the same kinds of target
and no firmness, since nothing is being matched; a question about the
numbers carries its words as a subject with no target. *Revised 2026-11-15.*
The first ruling had a discussion turn carry a subject in place of wants.
That lost nothing between turns, since the conversation is re-read every
time, but it left "would the second one suit me?" with nothing to be
answered against, and one subject could not hold "does it have online co-op,
and do people complain about crashes?". A question is never turned into a
want: "does it have a good story?" asks, and "it needs a good story" wants.

| Target | Wanted or avoided | Matches | Fails | Cannot tell |
|---|---|---|---|---|
| store fact every game declares | wanted | the store lists it | the store does not list it | no stored facts for the game |
| store fact every game declares | avoided | the store does not list it | the store lists it | no stored facts for the game |
| store fact declared by choice | wanted | the store lists it | never | the store does not list it |
| store fact declared by choice | avoided | never | the store lists it | the store does not list it |
| genre | wanted | the store lists it | neither the store nor a player tag has it | players tag it and the store does not list it |
| genre | avoided | neither the store nor a player tag has it | the store lists it | players tag it and the store does not list it |
| release years | wanted | released inside the range | released outside it | no stored release date |
| aspect | wanted | strongly or mostly positive | clearly negative, split | unclear, too few mentions |
| aspect, partly checkable | wanted | never | clearly negative | everything else |
| search term | wanted | the term clusters | never | no cluster |
| search term | avoided | never | the term clusters | no cluster |
| nothing | either | never | never | always |
| any target, relative to a named game | either | never | never | always, with what the target shows on each of the two games |

An aspect has no avoided form. It says how well a part is received, so "not
buggy" is a wish that `bugs` read well. An avoided release range reads the
other way round from a wanted one.

**A store fact is read by what its absence means.** *Ruled 2026-11-15;
figures from the copy of the serving database taken on the evening of
2026-11-14 (115 games).* The first status table read every missing store fact
as a failure. That holds for some facts and not for others, and the library
shows three kinds.

- *Facts every game declares:* play modes, platforms and early access. All
  115 games carry a single-player or a multi-player category, so a game
  without "Online Co-op" has none.
- *Facts declared by choice:* adjustable difficulty, saving anywhere,
  controller support and the like. 24 games declare adjustable difficulty,
  and the 91 that do not include Hades and both Civilization games. Only the
  presence of such a fact is evidence, the same rule as for a search term.
- *Genres.* Every game has them, and they are coarse enough to miss. The
  store does not list Dark Souls III as an RPG, where RPG is the fourth tag
  on its page, or Cities: Skylines II and Oxygen Not Included as strategy
  games. Four games carry the RPG tag without the genre, seven the Strategy
  tag and nine the Simulation tag. Review search does not fill the gap: genre
  words reach 1.3% of Dark Souls III's reviews and cluster in none of the
  four RPG cases, and they nominate wrongly besides ("strategy", "tactical"
  and their variants together cluster in Mass Effect 2 at 2.9%).

So a genre the store does not list is a failure only when no player tag
names it either. A game that players tag and the store does not list is
"cannot tell", worded as exactly that, and its reviews are there for the
judge to read. A tag never makes a match, because the tags mislead too: Mad
Max is tagged Racing, and Ori and the Blind Forest is tagged RPG in twentieth
place. The other way round has no fix here: the store lists Rust as an RPG,
and it reads as a match.

A release date is matched as a range of years with either end open. The year
is the store's, which moves to the full release when a game leaves early
access, so Palworld reads as a 2026 game. "Retro" and "old-school" name a
style and go to a search term.

Of the 57 category ids the library holds, the vocabulary offers the play
modes and thirteen features. The rest say nothing about the game a player
would ask for: trading cards, family sharing, cloud saves, sound formats,
controller brands.

**What kind of game it is comes from the store and from the reviews.** An
aspect profile says how reviewers feel about parts of a game, which is not what
kind of game it is. Three sources cover the difference:

- *Store metadata.* The appdetails answer the job already reads carries genres,
  categories (single-player, co-op, controller support), platforms, release date
  and a short description; until now the job kept only the name and header art.
  These are stored per game and are what a want about a store fact is read
  against. Price is left out: it
  changes, varies by region, and adds nothing to review evidence.
- *The reviews themselves.* The genres are coarse (Hades reads "Action, Indie,
  RPG"). Reviewers supply the finer words. No report narrative of the 53
  contained "rogue", while a keyword search of the stored reviews found it in
  15.8% of Dead Cells' reviews and 14.6% of Hades', three more games between
  4.5% and 6.8%, and no other game above two mentions. A term nominates a game
  only when it clusters, counted as a share of that game's stored reviews; a
  single mention can be a negation or a comparison.
- *Community tags.* The store page carries the top twenty tags, each with a
  count. They are finer than genres and noisier: the counts do not separate
  apt tags from inapt ones. Tags are
  recorded with their capture date and are never shown to the player or given
  to the judge. Their first job is as an outside reference for how well
  review search identifies a kind of game. Their one use inside the pipeline
  is to withhold a genre failure, as described above. A tag's absence from
  the top twenty is not a negative label.

**The store's facts are kept per game, beside the reports.** *Storage and the
capture in the report job built 2026-11-14; every library game held both
captures by 2026-11-15.* The alternative was columns
on the report row, the way the header art is kept. It was declined because a
report is a frozen sample and these facts are revised by the store: Palworld's
release date reads Jul 9, 2026, the day it left early access, and 534 of its
607 stored reviews are older than that. "Runs on Mac" should be as fresh as
the last capture, whatever the report's age. Each game holds one capture of
the metadata and one of the tag block, each replaced whole when read again,
each with its capture date. No history is kept; an earlier state of the
library is a dated copy of the database, which is also what the coverage
measurement reads. The tags have their own capture because they come from a
different page and may fail while the metadata succeeds.

The report job captures both after it publishes, with two more store reads.
Both fail soft: Steam trouble on either is narrated as a warning and the job
still completes, because the report is the product and a later capture can
fill the gap. The metadata is read with its own appdetails request, separate
from the name lookup the job depends on, so a surprise in one of the five new
fields cannot fail a job that would have succeeded before. A game with no
store record is not asked, and a job that publishes no report records nothing.
A store page without a tag block (a gate in place of the page) is recorded as
nothing read, never as a game without tags.

Games published before the capture existed are filled by a backfill that runs
the same capture routine through the same Steam door, as a module inside the
image (`python -m steamlens.serve.backfill_storefront`). A standalone script
on the box's system Python, the form the header-art repair took, was declined
here: it would have carried a second copy of the five-field parse and the tag
extraction. The backfill reads the library from the published reports when it
runs, asks each game only for the record it lacks, and can be run again after
any interruption. It is a second process beside the app with its own request
pacing, so it yields: it does not start while an analysis job is live and
stops at the next game if one begins.

What the wire looks like, from thirteen library games read on 2026-11-14
(`probes/store_metadata_probe.py`, one address): all five fields were present
on every game and every store page carried exactly twenty tags. Genre ids
arrive as strings and category ids as integers. Two category ids can share one
description, so filters compare ids. A game in early access carries genre id
70 and its early access launch date. The two games no longer sold answered in
full, without a price. The mature-content pages answered without an age gate,
from that address and, the same day, from the serving host. The count attached
to a tag does not track the size of the game (a game
with 72 stored reviews showed counts above 400), so it orders tags within one
page and is not compared across games.

The backfill's first run on the serving host (2026-11-14, 115 games) added two
facts. A page can carry fewer than twenty tags: Commandos: Behind Enemy Lines
has 18. And the store page depends on the country the store assigns the
caller. The host has a German address, and one game of the 115 is not sold in
the German store: its page there is a "Site Error" reading "This item is
currently unavailable in your region", with no tag block, while its US page is
whole. The capture recorded that page as nothing read, which is the behaviour
the "no tag block" answer exists for.

The first fix sent `cc=us` on every page read, as the appdetails read does,
and it was wrong. The country also decides the age check: the US store
redirects a mature-content game to one, while the store's default page for the
host's address, and for a second address, is the game's own page with its
tags. While that fix was live, eight newly analysed games kept their store
facts and lost their tags. Two mature-content games were then read directly
(DOOM Eternal, and PAYDAY 2 from the eight): with `cc=us` both redirect to
`/agecheck/`, and without it both answer whole. The fix had been verified on
the one game it was written for and not on a mature-content game. The page read now asks for the default page first and
for the US page only when the first carries no tag block. The age check is
never worked around: no age cookie is sent and the redirect is not followed,
so a game that is both unavailable in the host's country and behind the US age
check keeps no tag capture. The soft failure and the backfill did what they
were built for: no report was lost, and the eight games are refilled by one
backfill run.

**Across games, measured numbers are read in groups.** Every number in the
library was certified inside one report, and the samples differ (158 to 837
reviews, median 507). Each aspect gets two readings per game: the share of
stored reviews that mention it, and how positive those mentions are. The first
reading says how much the game is about the thing. Story is mentioned in 30.7%
of Clair Obscur's reviews and one review in 700 for Civilization V; Symphony of
War has the most story talk in the library (37.7%) with 48% of it positive, so
the two readings are kept apart. The second reading is trusted only above a
mention floor set from the data, stricter than the report page's display floor
of five: by positive share alone the library's best combat belongs to a game
with seven mentions. Games fall into groups (strongly positive, mostly
positive, clearly negative, split, unclear, too few mentions), where "split"
means enough mentions that the balance is real and "unclear" means the
interval is too wide to say. Games inside a group are not ordered by the
number. That is a policy, since a five-point gap between two games on fifty
mentions each is noise.

**The sheet.** *Specified 2026-11-14; figures from the copy of the serving
database taken that day (107 games, 4,524 game-and-aspect cells), regenerated
by `probes/sheet_groups_read.py`. The floor, the lines and the width are
working values held as constants, to be re-read on the development cases and
never tuned on the reported ones.* The sheet has one row per library game and
one cell per pinned aspect. Candidate aspects stay off
it: they are the uncalibrated stratum, and one concept fragments across many
strings.

- *The report.* A game is represented by its newest report, the one the
  library links to. The row carries that report's date, sample size, labeler
  version and whether it was a complete count. Every reading describes that
  stored sample and says nothing about reviews written since.
- *The mention share* is the reviews that mention the aspect over the report's
  sample size, the number the report page shows, with the interval the
  sampling study shipped (a complete count has none).
- *The sentiment share* is the positive mentions over all reviews that mention
  the aspect. Mixed and neutral mentions stay in the denominator, since a
  mixed mention is not praise. They are a median 5.5% of the mentions in cells
  above the floor and reach 45.7%, and 171 of those 892 cells would change
  group without them. The cost is that "clearly negative" is hard to reach: a
  game with 82 negative, 50 positive and 29 mixed combat mentions reads as
  split.
- *The sentiment interval* is a plain Wilson interval on the mentions. The
  sampling study calibrated the mention share and treated the sentiment mix as
  descriptive, so the shipped interval does not apply here, and this one is
  not certified for the windowed draw. It prices sampling noise only. Label
  error on polarity is small by the holdout's reading (0.988 agreement on
  sentiment where the aspect matched). Complete counts get the same interval:
  across games the question is how settled the opinion is on that many
  mentions.
- *The floor* is 30 mentions; below it the cell reads "too few mentions". At
  30 the widest interval is ±17 points and 15 aspects are readable in twenty
  or more games. A floor of 50 leaves 6 such aspects, and a floor of 20 admits
  intervals of ±20 points. 3,632 of the 4,524 cells sit below the floor.
- *The groups above the floor.* Strongly positive: the sentiment interval
  starts above 70%. Mostly positive: it starts above 50%. Clearly negative:
  the negative share's interval starts above 50%. Split: none of these, with
  a half-width of at most 15 points. Unclear: none of these and wider. There
  are two positive tiers because one did not select. Combat is readable in 46
  games and a single positive group held 36 of them; the tiers hold 12 and 24.
- *Status for a want on an aspect.* Either positive tier is "matches".
  Clearly negative and split are both "fails", and the cell keeps its group so
  the wording can tell "mostly criticised" from "opinions are divided".
  Unclear and too few mentions are "cannot tell".
- *Complaint aspects can only exclude.* Reviewers rarely write that a game has
  no bugs. On `bugs` no game is positive, 21 are clearly negative and 83 have
  too few mentions, so a request for a game that is not buggy returns "fails"
  or "cannot tell" and never "matches". The same holds for `performance` (2
  positive, 11 clearly negative, 85 too few).
- *No order inside a group.* The sheet lists a group's games in an order
  unrelated to the share. Where the pick call reads the sheet, games that read
  alike are in an order shuffled by a seed from the conversation (the sheet as
  the pick call reads it).

Two limits on comparing across games. The library was labelled by two models
(51 reports on the earlier one, 56 on the current), and whether they detect an
aspect at the same rate has not been measured. And the keyword share that
review search computes is a nomination signal inside the pipeline; it is not a
survey number and is never shown.

**A fixed order of steps, with the model's freedom in the judging.**

1. *Understand.* A model turns the conversation into the structured request.
   This step is also the scope gate.
2. *Build the sheet.* Code computes the readings, groups and statuses for
   every library game and removes none on evidence. At library size the sheet
   covers all of them, so review search nominates only for wants the aspect
   vocabulary cannot express.
3. *Pick.* A model reads the request and the sheet and returns one decision
   as data: candidates to read reviews on, a question, or the finding that
   nothing fits. Which games fit and which near miss is worth reading is its
   judgment.
4. *Fetch.* Code reads the candidates' reviews on the wants, inside a cap, and
   puts together what the reply is written from.
5. *Answer.* A second model call writes the reply as ordered statements, each
   citing by identifier the excerpts it rests on. It may set a candidate aside
   after reading.
6. *Check.* Code verifies that each cited excerpt was fetched for the game it
   is used for, and holds the reply to the rules it can see: a conflict with a
   must named and cited, a missed want spoken to, an offered game named, no
   numeral and no quote, no library game outside the turn. Its objections go
   back to the answer call once, together with the faults of the parse, and
   what still stands after that is removed.

A turn about one game has no pick: code fetches reviews for what the player
asked about that game, reading it against the sheet as well when a question
fits no stored field and wants stand, and the answer and the check run as
above.
The paragraphs after the understand step's take the pick, the fetch, the
answer, the check and the turn one by one.

The check establishes source integrity and constraint compliance. Whether the
cited evidence supports the sentence built on it is a judgment, and it is
measured in the evaluation instead of being claimed as a guarantee. No step
writes a link into the text: the links to a game's report are read off the
reply's record by the page. Quotes and numbers shown on request are supplied
by code from the cited identifiers, so a quote or figure cannot be misstated,
and that part belongs to the second stage.

**The steps live in their own package, below the shells that run them.**
*Ruled 2026-11-15.* The tab's route is one caller of the chat's steps. The
end-to-end run of the example conversations and the stage measurements are
the others, and they run without HTTP. With the steps inside the serving
package, the evaluation harness would import each step's module from another
entry shell's interior, and the import law would pass it, since both sit at
the top rank and only the harness and the study drivers are closed to
imports. That is the shape the full-base review removed when it moved the
shared run machinery into `dispatch`. So the steps are a package, `chat`, at
the rank of `dispatch`. It may import the doors, the core and the run
machinery beside it, and it never imports the serving shell, which keeps the
route, the caps and the HTTP. Each step's rules stay pure in `core`, as the
compose stage's do. The reserved `pipeline` package was the other candidate
at that rank; its name stays with the analysis pipeline it was reserved for.

**The understand step as built.** *Built 2026-11-15 and not yet measured;
the name-matching figures are from the copy of the serving database taken on
the evening of 2026-11-14 (115 titles).* The step is one model call that
returns one JSON object shaped like the structured request, with a tagged
target on each want. It rides the labeler's model at temperature 0 until the
development cases choose one, and the route is the one place that says so.

The model is asked for JSON in the prompt and the provider's JSON mode stays
off. The classify stage lost 24.9% of its gold reviews under JSON mode on
this model, because its prompt asks for an array and JSON mode means an
object. That cause would not apply to an object, but JSON mode with an
object has not been measured here, so it is a cell for the development
cases and not the starting point.

An answer can be faulty in two ways, and they are handled differently. A
fault in the structure (no JSON object, no intent, a value outside a closed
set, a want without the player's words) leaves nothing to read. A fault in
one want's target (a store fact outside the vocabulary, an aspect outside
the pinned list, an avoided aspect, a partly checkable mark on anything but
an aspect, a release range the wrong way round, a term with no phrases)
leaves the rest of the request sound. Any fault gets one corrective retry
that names the faults, which is a new question at temperature 0. If a
target is still faulty after the retry, that want keeps the player's words
and loses its target, so it reads "cannot tell" on every game and no want
disappears; when the retry itself fails, the first answer is salvaged the
same way. A structure that cannot be read after the retry ends the turn
with a fixed reply.

There is a third fault that code can detect and cannot repair. The words of
every want, subject and named game have to be one unbroken stretch of a
player message, compared on letters and digits, so that a want with words
the player never wrote does not pass as theirs. The first prompt asked for
the player's words "with any detail needed to read them", and the model
answered by joining two sentences into one the player had not written. A
miss goes to the same corrective retry; a want that still fails is kept as
it came, with the fault recorded. A detail that follows a want (the laptop's
graphics chip) stays with it by the excerpt running on through it. Rejecting the whole answer on any fault was declined,
since one bad key would lose a turn that was otherwise read correctly.
Salvaging without a retry was declined too: the retry is the only way an
avoided aspect ("not buggy" written as avoiding `bugs`) is repaired to what
the player meant, and code flipping it would be code interpreting. A
generation that is cut off is not retried, and neither is provider trouble
the client already retried; the spend cap and provider trouble end the turn
with their own fixed reply.

Everything outside the scope gets one fixed refusal. A reason field with a
text per reason (off-topic, help with playing a game, an attempt on the
instructions) was declined for the first stage: it is one more thing the
model can get wrong, and it would change only the wording. The gate
measurement reads whether one text misleads the people it refuses.

The prompt shows the aspect vocabulary as each label with its one-line
definition, about 1,300 tokens against the 5,700 of the compact codebook
the labeler reads. Names alone were declined: `game_length`,
`content_amount` and `difficulty` read like amounts, and `multiplayer` and
`platform_access` sit beside store facts of nearly the same name. The cost
of the short form is that the labeler drew the line between neighbouring
labels (`bugs` against `stability`) with rules the understand model does
not see, so a wish can land on the neighbour; the target of each recovered
want is what the understand measurement scores. Adding the aliases was
declined because they work against the amount rule: the aliases of
`game_length` include "too short". The definitions were written for
labelling a review, so the prompt states what an aspect target means for a
wish. The codebook itself is unchanged and stays available to every later
step.

A named game is resolved in two parts. The model writes the game's full
title beside the player's words, which is where a nickname is expanded
("bg3"), a typo corrected and "the second one" read off the chat's earlier
reply. Code then matches the title, and after it the player's own words,
against the library's titles, and the model never sees the library. The
match is literal: case, accents, trademark signs, apostrophes and
punctuation are folded and Roman numerals read as numbers; a whole title
matches first, then a name that sits as a run of words inside one longer
title. On 39 spellings a player might type, written for the trial and not
sampled from players, code alone found the right game for 20, rightly
found none for 3 the library lacks, asked on 4 names that several titles
hold, missed 8 nicknames, and resolved 4 series names to the one entry the
library has ("doom" to DOOM Eternal). The
misses are why the model writes the title, and the series names are why
the request records how each name matched: exactly, as part of a longer
title, as several titles with the candidates and no game chosen, or not at
all. A partial match resolves, and the reply names the title it took. When
the model cannot tell which game is meant ("that one" after several were
mentioned) it writes no title, and a name with no title that matches
nothing is recorded as unclear, which the chat asks about, and never as a
game the library has not measured. A
hand-kept table of nicknames was declined, since it needs an entry per
game and per nickname as the library grows. Letting the model expand a
name uses its memory of game titles, which the design otherwise keeps out;
whether the library holds the game stays code's decision. The step will
expand a wrong title for a game newer than the model, and the player's own
words are the fallback for a new game typed in full.

Three rules in the prompt keep the structure from saying something easier
than the player did. Firmness is read from the whole clause: stress counts
when it sits on the want itself ("i really don't want much reading") and
not elsewhere in the sentence ("i really liked Hades"), need or exclusion
outranks soft wording, and a word of degree ("a bit") says how much and not
how firmly. A want that no single target and stance can say without
changing its meaning, such as an either-or or a bound in numbers, is kept
whole with no target. And a term's phrases name the thing itself, one to
six close wordings with no related kind of game and no stronger or weaker
form, because the sheet reads a cluster as the thing being present; words
that fetch evidence in both directions would make a cluster mean nothing.

A want that is relative to a named game ("less frantic than Hades") is
written as an avoided term with the game it is compared with. Read on its
own, that term would fail a game whose reviews call it frantic even when it
is calmer than Hades, so the sheet gives such a want no verdict and the
comparison is made in the reply, from reviews of both games.

The conversation reaches the prompt as one delimited block of both sides'
messages, introduced as data and never instructions, with "<" escaped so a
typed message cannot close the block. The chat's own messages are context
for a reference such as "the second one" and never a source of wants. The
prompt's worked examples are not the example conversations the step is
assessed on.

**The first read of the step.** *2026-11-15, on the labeler's model and the
copy of the serving database taken on the evening of 2026-11-14: three runs
of `probes/understand_examples_read.py` over the twelve example
conversations (16 player turns), the last two with contrast pairs added (24
and 27 turns). Each run is one pass read by hand against reference
readings, so what follows is observation and not a rate, and the twelve
are development cases from here on.* Every answer was valid on the first
call in all three runs, so in these runs the retry ladder ran only in tests;
it first fired on the real model in the revision described below. A call
took 0.7 to 1.8 seconds. The prompt is about 6,300 tokens, and the provider
served about 6,100 of them from its prefix cache on every call after a
run's first: the first call cost about $0.0011 and the others $0.0001 to
$0.0002, which makes these warm-cache figures.

The first run returned three readings that would have sent the sheet the
wrong way, each a valid structure. "A puzzle game" became the store genre
Casual. "Nothing with a timer" became avoiding the store fact "Playable
without timed input", which 26 of the 115 games declare, so the games most
likely to suit the player would have conflicted with a must. And "to play
alone" stayed a must after "actually my friend wants to join". The rules
that came of it: a target has to say what the player asked, with no
broader, neighbouring or commonly associated one in its place; a genre key
is for a player who names that genre; the stance is read against what the
target means and not against a negative word in the sentence; a replaced
want is removed and not kept at a lower firmness. Two things besides rules
were at fault. The prompt told the model to take the first kind of target
that fits, with the store first, which pushed it toward a store fact; that
order now only decides between two kinds that fit equally. And the label of
the timed-input fact reads like "no timer", so the vocabulary carries a
note on that fact saying what it is. Banning the avoided form of a store
fact was declined, since "no in-app purchases" is a real want.

By the third run the puzzle and the timer were read as search terms in
every place they appear, a paraphrase of each included, and the contrast
cases held: "something casual" still reads as the genre, and "i also want
to be able to play it alone" keeps the co-op want and adds the other. Three
things were still open. "To play alone" survives "actually my friend wants
to join" as a want, where two other replacements worded differently are
read correctly. The laptop's graphics chip, which sits in the sentence
after the want, is not carried in its words. And a reading can change
between turns with nothing new said: in the first two runs the timer was a
store fact on one turn and a search term on the next. That last one follows
from re-reading the whole conversation every turn, and how often it happens
is a measurement the stage owes.

The reference readings were corrected by the same pass. "Having another go
after dying" was expected as a roguelike search term, and the model's first
answer, the aspect `replayability`, follows that aspect's definition
("returning after completion/failure"); both are accepted. "Realistic" as
the aspect `realism` is accepted. "A really good story" is a want, since
"really" there is a degree and not stress.

**The understand step was revised once for the judge.** *2026-11-15.* Three
changes went in together, and the example conversations and contrast pairs
were run again on the same probe before the commit. A want that is compared
with a game, or that names the game a liked part belongs to, has to point at
one of the request's named games. A miss goes to the corrective retry, and a
comparison that still points at none loses its target and reads "cannot
tell". The conversation block shows each chat
message's offered games as a numbered list with the library's exact titles,
written by code from the message's record, so "the second one" is read
against that list and never against the reply's prose, where a game
mentioned and turned down can come first. And one field records that the
player asked for other games, read from the latest message only.

The re-run found one regression: "no timers please" was read again as
avoiding the store fact "Playable without timed input". Changing the
prompt's worked example repaired it and moved another reading, a want that
became a must, so the prompt was left as it was and a code check holds the
case. That one fact has no avoided form, and an answer that avoids it
carries a target fault, which goes to the corrective retry. This is where
the ladder first fired on the real model. A ban on the avoided form of every
store fact stays declined, since "no in-app purchases" is a real want.

**The judge is two calls, with code reading reviews between them.** *Ruled
2026-11-15, built by 2026-11-19 and not yet measured.* The pick call reads
the request and the sheet and returns one decision as data: candidates to
read reviews on, a question with what it needs to know, or the finding that
nothing fits with the wants that could not be met. Code fetches reviews for
the candidates. The answer call writes the reply, cites by identifier, and
may set a candidate aside after reading. One call was declined: it can cite
counts and never a review, so reading the reviews behind a "cannot tell",
citing reviews against a conflict with a must, and a comparison from
evidence on both games have nothing to stand on, and loading reviews ahead
for the likeliest games is a shortlist made by code. A tool loop was
declined too, for unbounded cost and latency and for stages that can no
longer be measured apart. The accepted cost is a second model call on every
recommendation turn. The pick cannot go back for another game after
reading, which is answered by picking more candidates than a reply offers,
six against three.

The pick call does not read the conversation. Picking stays a function of
the request and the sheet, so a pick can be scored against the sheet it was
made from and regenerated. The answer call gets the conversation as a data
block, the way the understand step does, with the request stated as the
reading of record, so the reply follows what was said. Giving both calls
the conversation was declined: a pick could then depend on text the request
does not hold, and a wrong pick would no longer be traceable to one stage.
The cost is that a detail the understand step missed cannot change which
games are picked, which raises the weight of the understand measurement.

Every reply is written by the answer call, a question and a "nothing fits"
reply included. There is one writer, so the wording rules and the check
apply in one place, and the pick call's output is a pure decision that can
be scored, including whether it was right to ask. Fixed texts for those two
replies were declined: they depend on the request and would read like a
form.

Both calls start on the labeler's model at temperature 0 with thinking off,
each on a route of its own. Temperature 0 keeps every reply regenerable
from its inputs. A stronger model for the answer call from the start was
declined as a guess, and thinking on for the pick call as an unmeasured
latency cost on every recommendation turn; the register below says what
reopens each. The two stages are named for the calls, pick and answer,
because "judge" already names the evaluation harness's second annotator.

**The sheet as the pick call reads it.** The sheet is laid out so the games
worth reading come first without code choosing among them. Rows are grouped
by standing on the musts, and inside a standing by pattern: the statuses a
game has across the wants. Patterns are ordered by a plain count, fewest
fails first and then most matches, which never looks at firmness, since
weighing a must against a nice-to-have is the near-miss judgment the model
is there for. Every row stays on the sheet. One line per game in app-id
order was declined, since the oldest games would lead every request, and so
was a shortlist made by code, which is the filter already ruled out. The
accepted cost is that the count order is a soft ranking that counts a
nice-to-have match like a want match.

Inside a pattern the games read alike, and the model takes the ones it
meets first. The pick call was run on handwritten requests with those games
in app-id order and in the reverse, in a run made outside the repository
and not reproducible from it, and the picked games changed wherever more
games read alike than a decision can hold. In app-id order that is the same
oldest games for every player. So the order inside a pattern is a shuffle
seeded by the conversation, which breaks the tie differently for each
conversation and keeps a pick regenerable from its inputs. A game's place
depends on the seed and the game alone, so leaving a game off the sheet
moves no other game past another. The costs are that two players with the
same request get different suggestions, and that every pick measurement
fixes or records its seed.

A game's line carries an identifier, its store genres, its release year and
what was found on each want. It carries no title and no app id. The
identifier is made for one render and means nothing outside it, so a pick
can only come from what the sheet says about a game and never from what a
model remembers of it. The cost is known: without a title the model cannot
tell that a game whose reviews say "puzzle" is not a puzzle game, and rests
on the match counts. A want relative to a named game shows what its target
found on each side in words and no counts, since two counts side by side
would invite the comparison of shares that is declined everywhere else. A
relative must therefore never narrows: every game is open on it, and none
is called a fit on that want.

Three kinds of game are handled on the player's say and never on evidence.
A game the player said they had already played is left off. When the player
asked for other games, the games the chat already offered in this
conversation are left off too, and the reply says it left them out; without
that request they stay, so a player who adds a want can be offered a game
they were shown before. A game named as "like this" stays on the sheet,
marked, since its readings serve the comparison, and is never a candidate:
the pick's parse removes it.

The pick's bounds are working values, and the judging inside them is the
model's: at most six candidates, and at most three things a question may
need to know. A decision over a cap is not a fault. It is cut in the
model's own order, so its first choices survive and no retry is spent. A
faulty answer is handled as the understand step handles one: one corrective
retry that names the faults, then the faulty item removed and the rest of
the decision kept. An answer that leaves no decision after the retry ends
the turn on a fixed text and is never turned into "nothing fits" by code.

**Code owns what is read.** The first ruling had the pick call name, for
each candidate, the wants it wanted reviews on, with code capping the pairs.
On the real model that list was not steady, in runs made outside the
repository: under one wording of the instruction the same request got every
want in one order of the sheet and only the want in doubt in the other, and
under a second wording a request for a story and characters asked to read
nothing for any of its six candidates. A third wording was the tempting
fix. Nothing is being judged there, since the question is one of budget
with an obvious answer whenever everything fits, so code took it and the
pick's list was kept as an order.

The reads are scheduled in three ranks. A must comes first, listed or not:
a game offered against a conflict has to cite reviews on that want, a
game open on a must is offered with what was found said beside it or set
aside when its passages show it going against the must, and a
must matched on searched words is matched on how often the words come up,
which does not say what the reviews say with them. Then the wants the pick
listed, in its order. Then every other want, so that a reply can say what
reviewers wrote on each thing the player asked for without the model having
to remember to ask. At most 24 pairs of a game and a want are read. The cap
is filled rank by rank and, inside a rank, candidate by candidate. On a
short request everything fits and the pick's list changes nothing; on a
long one it decides what survives, and a request with enough musts leaves
some of them unread for its last candidates. A pair known to have no
reviews uses no place: a want with no target, a release year, a store fact
the game already matches on, and searched words none of the game's reviews
use. Two kinds of pair take a place whatever they return: an aspect, which
reads nothing when too few of the game's reviews mention it, and a want
relative to a named game, unless that want has no target or names release
years.
The named game's own side of a comparison is read once for the turn,
outside the count. The pairs the cap cut are journalled, and the three ways
a want can have no excerpts reach the answer call apart, because a reply
has to say different things for them: its reviews were read, the read budget did
not reach them, or there was nothing to read.

The unit of evidence is an excerpt under the report page's display rule:
the stored span grown to its containing sentence, capped at 300 characters,
so the chat and the report it links to show the same sentence for the same
review. A review found by search has no stored span, and its sentence is
grown from the words the search matched. Whole reviews were declined, since
the long ones dominate and are mostly off the want, and so was the label's
evidence quote alone, which is too short to support a comparison or say
why. The accepted cost is that code chooses the cut, so a qualification
outside the window can make a review read more positive than it is.

A want is read one of two ways, by its target. An aspect is read by label:
the reviews the classifier marked with it, six of them, by a draw in
proportion to their sentiments, since the labels give no query to rank by,
seeded so the same game and aspect give the same excerpts every time. None
is drawn for an aspect with fewer than five mentions in the game, the
report page's own floor. Everything else that has reviews is read by words:
a search term's phrases, and for a store fact the search words its
vocabulary entry carries, taking the game's six best-ranked matches. Six is
enough to see an off-meaning use of a word. At six, a sentiment held by
fewer than about one review in ten will usually not appear in a draw, and
the group states it. The index's rank favours short reviews that repeat the
term, which is why a seeded draw over the matches is one cell of the
retrieval experiment.

Each of the forty store facts carries a short list of search words, 145
phrases in all, written once in the vocabulary and read by hand. Having the
pick call write the words was declined: they would differ from call to call
and could not be tested ahead, and "timer" showed how a plausible word
matches the wrong thing. A match does not say which way it points, so the
excerpts are read and code does not count them. Read against the store's
own listing on the 115-game copy of 2026-11-14
(`probes/store_fact_words_probe.py`), the facts reviewers name are covered:
45 of the 46 games the store lists as RPGs have a review to read, and 37 of
37 for co-op. LAN play, Remote Play Together, a level editor, split screen,
timed input and subtitle options stay thin whatever the words.

A turn about one game has no pick. Each thing the player asked is read by
its target the same way, up to four subjects in the player's order, and a
subject on a store fact is read whether or not the store lists it. Two
questions have no target of their own, and code cannot tell one from the
other, so a question with no target gets what answers either (*revised
2026-11-24*). "Would it suit me" is answered by the game read against the
wants that still stand, as a candidate is read, under the same ranks and
cap; that read is made when wants stand and is skipped for a game that is
off the sheet, which is one the player said they had played. A question
about the game in general, or about what its reviewers complain of, is
answered by the aspects they praise strongly and the ones they criticise or
are divided on, as groups, and no review is read for it. The answer call has
the question's words and uses the one they ask for. The list was first given
only to a player who had stated no wants. A player with wants standing who
asked what people complain about in an offered game was then told its
reviews carried no complaints, of a game whose report has stability
criticised in 107 of the 112 reviews that raise it. A planning call for
the one game was declined as another call on every such turn, and so was
the player's message as the search query: the built search matches literal
phrases, so a whole question matches almost nothing.

**A reply is ordered statements.** The answer is data, not prose: ordered
statements, each with the game it is about, whether it offers that game,
the wants it speaks to and the excerpts it cites. Structured output is
chosen over a citation markup in running text for the reason the composed
narrative stores spans: the games a reply offered and the reviews behind a
sentence are then fields, read without parsing prose a model wrote. The
offered games are derived from the offering statements, in order, and are
what the chat message stores. A separate list of offers beside the
statements was declined, since two places would say which games are offered
and could disagree.

What a statement is about and whether it offers it are two fields because a
reply speaks about games it does not suggest: a candidate set aside with a
reason, the game the player named for a comparison, the one game a turn is
about. Run with one field for both, a reply that explained why it left a
game out had nothing it could cite. Only a candidate of a recommendation
turn can be offered, and at most three; a reply that offers more is cut in
the model's own order with no retry. A statement lists the wants it speaks
to because a want with nothing to read cannot be reached through a cite: a
want no stored field fits, a release year, a store fact that fails. Code
checks that label and not the sentence, which is the limit a cite already
has.

The call's input carries readings in words and no count. Each want's line
says what was found in a sentence the reply can be worded from, so which of
the things there are to say about an undecided want is chosen by what code
found and never by the model. A line says what was looked at and stops
there: "none of the reviews held use these words" is what a search can
show, and "its reviewers never bring it up" is not. An excerpt is shown
without the sentiment its review was labelled with. Where reviewers stand
is the group's to say, and six labels would be a second, coarser statement
of it that can be counted. The cost is that a sarcastic or mixed excerpt is
read on its text alone. A game has a title here for the first time in a
turn, since a reply has to name it, and the games left off the sheet on the
player's say are listed by title so the reply can say it left them out.

A reply that offers nothing has no reviews to read, and still has to tell
"the store lists no such game" from "nothing stored could decide it". It
gets how the library divides on each want, as presence and never as a
count: whether any game matches, fails, or could not be decided. The three
counts per want were declined. They would be the first counts the answer
call sees, with only the check's numeral rule between them and a sentence
that states one. The game named as "like this" is left out of that tally,
so "some games match" is never true because of it alone.

The message a turn appends is the statements' text joined in order by one
space, with the reply's offered games and its kind. That text is what later
turns read as the conversation. A paragraph for each game was declined as a
layout choice inside the stored text. On a recommendation turn the kind is
code's, from the pick's decision; on a turn about one game the model
reports whether it answered or asked.

**The check runs inside the answer's one round.** *Built 2026-11-19 and not
yet measured.* The answer call's output is read twice before it is shown.
The parse asks whether the answer can be read as a record over the turn's
material, and the check asks whether a readable record keeps the chat's
rules. The first answer is parsed and checked, and every fault of both kinds
goes into one corrective retry. Code then removes what is still faulty. The
worst case is two answer calls a turn. Two ladders, a retry on parse faults
and then an objection round of the check's own, were declined: three or four
answer calls a turn, on the largest prompt of the three. The cost of one
round is that when the first answer cannot be read at all, the retry's
answer gets its first check with no round left, and code removes what fails.

One bound holds every rule: a reply that follows the answer prompt as
committed draws no objection. A rule stricter than the prompt would send the
model back to correct what it was told to write.

The parse leaves the check nothing to add on four points. A statement's game
is one the turn put in front of the call. Only a candidate of a
recommendation turn can be offered, so a game named as "like this" never is.
Every cite was issued for this turn and every want number is the request's.
At most three games are offered.

The check's rules are of two kinds. Rules over the record are certain,
because they read fields: where a cited excerpt was fetched from, which
wants a statement says it speaks to, which games are offered. Rules over the
text see a pattern and not a meaning: a numeral, a passage in quotation
marks, a title. Neither kind says whether a sentence is true to the reviews
behind it. That is read by hand.

Each rule names what its fault costs when it still stands after the retry:

| Rule | If the fault stands |
|---|---|
| A cite is in place: its excerpt was fetched for the statement's game | the cite is removed and the statement stays |
| An offered game that fails a must has a statement about it that lists the want and cites an excerpt fetched for that game and want | the game is removed |
| Every other want an offered game fails, and every must it is "cannot tell" on, is listed by a statement about that game or about no game | the game is removed |
| The first statement about an offered game names it: its title whole, the title's first distinctive word, or a run of its words that holds two or more distinctive ones | the game is removed |
| No numeral, unless the same digits are in the title of one of the turn's games, are a release year in the material or in a want, or are in one of the player's messages | the statement is removed |
| No passage in quotation marks, two words or more, that appears in one of the turn's excerpts | the statement is removed |
| No whole title of a library game that is none of the turn's games | the statement is removed; a one-word title is only recorded |
| Reviewers' wording relayed with "call" as a verb; one of the material's labels or a working word; more than 150 words | nothing, and the fault is recorded |

Removal is by the smallest unit the fault is in. After a removal the rules
are run again on what is left, until nothing changes, which is how a game
loses its offer when the statement that named it or named its conflict was
the one removed. Always removing the whole game was declined, since one
relayed word would cost an offer. Cutting single sentences inside a
statement, as the compose stage does, was declined too: the statement's
wants and cites would then label text that is gone. A reply that offered
games and offers none after the removals, or has no statement left, is
withheld. When the retry's answer is withheld or holds no reply, the first
answer is put through the same removals, and the turn answers with a fixed text only when
neither leaves a reply. A withheld reply is counted apart from
an unreadable answer, since a broken answer and a check that removed what a
readable one said are different things to count.

Three points of the rules carry a decision of their own. An excerpt of the
named game's side of a comparison may be cited by a statement about another
game; that statement is a comparison to code, and it has to list the
relative want the side belongs to and cite at least one excerpt of its own
game fetched for that want. A statement about no game may cite any of the
turn's excerpts and may carry a limit that holds for every offered game, so
the limit is said once and the check does not ask for the repetition the
voice rule forbids. And the wants a reply has to speak to are the ones where
silence would mislead: a want the game matches and the reply does not
mention draws no objection. A turn about one game owes none of this
(*revised 2026-11-24*). The game read against the standing wants comes with
every question no stored field fits, so code cannot tell a question about
fit, where the prompt has an undecided must named, from one about what
reviewers criticise, where naming it again is the retelling the prompt
forbids. The rule had asked for the musts there, and a reply that followed
the revised prompt would have been sent back to say them.

The three recorded rules are named in the retry when one runs and do not ask
for one by themselves. Two trial runs, made outside the repository and not
reproducible from it, are behind that. With thinking off, relayed wording
was in most replies, so a retry on it alone would be a second answer call on
most turns. And with the three rules asking, the retry removed the faults it
was given and also changed sentences no fault named, in one reply dropping a
statement an earlier ruling asks for. Whether a rule asks is one value per
rule, and the setting is compared on the answer measurement.

Two replies with little in them are allowed in the first stage. A reply that
cites nothing because nothing was read (a request the store's facts settle,
or "tell me about it") stands under the text rules,
and its offered games with no cite are counted for the second stage's rule
that every offer cites a review. A reply that offers no game on a turn that
had candidates, by the answer call's own choice, stands and is counted;
asking for an offer would go against offering fewer when fewer are worth
offering.

Every objection is recorded with how it ended: corrected by the retry,
withdrawn (the retry no longer offers the game), removed by code, or left
standing. That record is what the measurement of the picks counts.

The compose stage's grounding gate is not called. It certifies each numeral
against a minted value at the numeral's own precision and refuses every
quotation outside its evidence. A chat reply has no minted value to match
and keeps no certificate: its numeral is either the digits of a title, a
year or the player's own number, or it is not allowed. The spoiler rules
need no rule of their own in the first stage. A review that contains
"spoiler" never reaches a turn's material, and a reply holds no quote of any
aspect, by the quote rule.

What code does not see. A number written as a word. A title's numeral or the
player's number used for something else. A library title shortened in a
sentence about another game, and a game outside the library named from
memory. A comparison made in words with only one side cited. A reviewer's
wording carried without quotation marks, except where "call" marks it. For
an offer against a failed must, code checks that the want is listed and
where the cite came from; whether the excerpt shows the reading is wrong is
read by hand, and the misattribution rate of the labels and the looseness of
a word match are the known weaknesses of "fetched for that want".

**The turn, and how it ends.** *Built 2026-11-19.* A turn is one function.
It takes a conversation, a seed and the year, runs the steps in their fixed
order and returns a record: the message the chat appends, how the turn
ended, the seed, and what each step made on the way, a step the turn did not
reach being absent. It is the one entry for an evaluation run and for the
page's route, so a reply read by hand goes the same way a reply shown on the
page does. A
turn that returns the message only, with the evaluation composing the steps
itself, was declined: the hand reading would then run on a second copy of
the routing. Nothing is stored by the turn. The conversation is the
caller's, and so are the seed and the clock. The library is read once a
turn, so the titles the understand step resolved a name against are the
titles of the games the sheet and the fetch read.

A request for games goes to the sheet and the pick, and then follows the
pick's decision: reviews are fetched for candidates, the library's standing
on the wants is put together when nothing fits, and a decision to ask goes
on as it is. A request about one game goes on when the game it asks about
resolved to a library title. When several games are asked about in one
message, the turn ends on a text that asks for one at a time (*revised
2026-11-24*): reading the first and counting the rest gave a reply about
one game of three that read as if it covered all. The understand step is
still asked for one game, so the text shows only when the step returns
several against its prompt; reading "these games" as several is left to
that step's own revision, since a one-line edit to its prompt for this
moved the search words of unrelated wants. A recommendation turn
never ends on a name: a named game that did
not resolve is read through the sheet's own finding for it, and the pick
decides what the request can still give.

Every way a turn can end has a name, and every ending but a written reply
has one text written in advance:

| The turn ended | When |
|---|---|
| on the answer call's reply | the steps ran and a reply was kept |
| on the refusal | the request is out of scope |
| not understood | the understand step could not read the conversation into a request |
| unavailable | a step could not be served, whichever step it was |
| with no answer | the request was read and no reply came of it: the pick held no decision, the answer could not be read, or the check left nothing of it |
| asking for the title | a turn about one game whose name fits several library titles or could not be tied to a game, or whose request marks no game as the one asked about |
| saying the game is not measured | a turn about a game the library does not hold |
| saying the numbers are not explained yet | a question about what the numbers mean |
| asking for one game at a time | a message that asks about more than one game |

The record carries the ending as a field of its own. Every text written in
advance has the same message kind, so without the field a caller that wants
to tell "asks for the title" from "not measured" would run the routing
again. The three cases with no answer share one text, which says no answer
could be put together and asks the player to put it another way; a text for
each was declined, since the player can do nothing different with the
difference, and the three stay apart where they are counted. The understand
step's text for a message it could not read is not used for them: there the
request was read, and the text would put the fault on the player's message.

The last four endings are stand-ins. The first stage does not write the
question that lists the titles a name could mean, the answer for a game the
library has not measured, the explanation of what the numbers mean, or an
answer about several games at once. A
turn that needs one of them ends on a short text that says so, with no model
call. Each stand-in is replaced by the reply it stands for when that reply
is built, and the ending's name stays. The out-of-scope refusal was declined
for them, since they are in scope, and so was the answer call with
nothing to write from. The cost is that an unclear "the second one" gets the
question with no titles listed. The refusal named the explanation of the
numbers until 2026-11-24, which sent a player who asked for it to the
stand-in. It now names only what the chat does, and the clause returns when
the explanation is built.

**The first end-to-end run.** *2026-11-19, `probes/turn_examples_read.py` on
the copy of the serving database taken on the evening of 2026-11-14 (115
games) and the labeler's model: the twelve example conversations, fourteen
turns, one fixed seed for each example. One run, so each line is an
observation and not a rate, and the reading by hand that assesses the
replies had not been made when this was written.* 13 turns ended on a
written reply and 1 on the stand-in for the numbers. No step used its retry
in 14 understand, 12 pick and 13 answer calls, and the check raised no
objection that costs a reply anything. Two replies ran over 150 words, at
159 and 160, and relayed wording was recorded in most of them. A turn took
a median 5.5 seconds and 6.3 at the longest, and the run's 38 paid calls
cost $0.0159, one answer having come from the response archive.

The routing held: "the second one" resolved to the second game the first
example's reply had offered, with that conversation's three wants still
standing. Five things were seen that the stage measurements now count. A
request with a wanted word no review of any game uses went forward as six
candidates to be read, and the reply offered none of them. Two readings the
understand step is known to get wrong reached a reply: a wish to play alone kept beside a new must
for online co-op, and "scary" weakened from a must to a want. Two replies
rested a sentence on an excerpt their statement did not cite, which shows
only when the material is printed whole and not the cited excerpts alone.
One reply attributed to a game a passage that is about its predecessor. And
one reply offered two games that are "cannot tell" on a stressed must and
whose own excerpts describe the unwanted thing, which follows the answer
prompt as committed and goes against the reply ruled for that example.

Four rulings waited on the reading by hand and were made on 2026-11-24. A
game undecided on a stressed must is set aside when its excerpts plainly
show the unwanted thing. A message that asks about several games gets a
text asking for one at a time, until a turn can answer about each. A liked
game the library has not measured, on a request with no wants, stays a
recommendation turn, and the question names the game and asks what the
player likes about it. And the refusal no longer names the explanation of
the numbers. They were ruled on those four cases; the run as a whole has
not been read by hand. One revision of the answer prompt followed, compared
with the committed prompt on the same fourteen turns and on one
conversation from the public page (`probes/turn_examples_read.py`, with
`--message` for the latter; one run and one seed each, so observations).
What hands the answer call new material showed in the replies: the list of
praised and criticised parts answered a general question about a game where
the standing wants had been walked again, and every offered game that
carried a heavily criticised part had it said. What asks the call to judge
or to hold back was kept unsteadily: the undecided must set aside was not
kept at all, and a follow-up still retold one want in two runs of three.

**Ruled for the second stage, and not built.** The first stage answers
under the base rules only. What the second stage adds is ruled in outline
and enters this section with its reasons when it is built: an allowance of
questions asked before suggesting, counted by code from the pick's stored
decisions (one for a request that carries something, up to three for one
that carries nothing), with "ask" withheld from the pick once it is spent; a
question put alongside suggestions, outside that allowance and at most one
a reply; the question that lists the titles a name could mean, a text
filled in by code; for a liked game with no parts stated, its strongly
positive aspects added to the sheet as columns that are never musts; the
starting set for a request that carries nothing; quotes and figures
appended by code beneath a statement when the player asks, with the report
link in their place for the story aspects and search match counts never
shown; a review cited behind every offered game; and the full title in the
reply for a partial match and for a game left off the sheet. Until then the
pick may always ask, so two questions in a row are possible, and a game the
player said they had played is left off only when its name resolved to one
title.

**The chat talks, and the evidence works underneath.** In the chat the player
reads natural talk, in plain words scoped to the people who mentioned the
thing: "players who talk about the story mostly praise it". It carries no
review quotes and no numbers. The evidence is still underneath: a statement
cites by identifier the review excerpts it rests on, code verifies where each
was fetched from, and the record is kept for the evaluation. No count reaches
the call that writes the reply, which reads groups and findings in words.
Quotes and numbers are shown when the player asks, supplied by code, which is
the second stage's to build. Each suggested game links to its report, where the
full evidence already sits, and the survey mint remains the only source of any
number the chat shows. The first design had code insert quotes into every
answer; that made the tab read like a report. The cost of the change is
accepted and named: with no quote on screen, the model's paraphrase is all the
player reads, so reading answers against the reviews behind them is the main
guard on what the chat claims.

**No spoilers, on every answer.** The chat does not reveal plot, whether or
not the player asks for that, and a player who asks to be spoiled changes
nothing. It holds in three parts. For the story aspects (story, characters,
writing, lore, emotional impact) the chat shows no review quote, even on
request; it describes in plain words and links the report. A review that
contains the word "spoiler" is never read: both reads leave it out, so it is
never an excerpt, reaches no prompt and can be neither quoted nor
paraphrased; 514 of the library's reviews across 87 games contain it.
Leaving it as a rule about quotes was declined, since the model's paraphrase
of what it read is then the leak. And the model is instructed never to state
plot events in its own sentences, a rule that also covers what it takes from
the store's description. The first two are held by code: the spoiler filter
sits in the reads, and in the first stage no reply carries a review quote at
all, by the check's quote rule. The third cannot be, since a spoiler can come
from the model as well as from a quote, and a reviewer can reveal plot
without using the word, so it is read by hand. The report pages already show
quotes picked with no regard for spoilers; whether any reveal plot has not been checked.

**Scope and the gate.** In scope: recommendations from the library, questions
about a library game, and questions about what the tab's numbers mean.
Everything else gets a fixed refusal written in advance. The gate is a model
and can be talked around, and review text, the store's descriptions and the
player's own messages reach the answer call without passing it, so the
protection is layered. The understand step returns a fixed structure. The
pick call reads the request and the sheet and never the conversation, so
player text reaches it only inside the request. The answer call can
offer only the pick's candidates, so an injection there can change the
wording and which candidates are offered and cannot add a game. The model
holds no tool that changes anything and no secret. A game offered against a
failed must without cited reviews is removed from the reply. The
conversation, the request and the fetched material enter a prompt as
delimited blocks introduced as data, with "<" escaped. The conversation is
kept by the server, so a visitor sends an identifier and a new message and
cannot write the chat's earlier lines or the games it offered. Turns, message
length and requests per address are capped by a gate of the chat's own, which
counts at admission as the spend breaker does, and daily spend by the
breaker's own backstop, which the chat and the report flow share. The gate is measured in both
directions, attempts stopped and real requests wrongly refused.

**Retrieval starts with the stored samples and keyword search.** The pool is
each report's own sample, already on the box and already labelled, so what the
chat can discuss is what the report was built from. Every read is restricted
to one game. A read driven by words, which is a search term or the search
words a store fact carries, takes the game's best-ranked matches from SQLite's
built-in full-text search behind one search interface. A want on an aspect
has no query, so the reviews labelled with it are read by a seeded draw in
proportion to their sentiments. Using the label as a filter there is the
first stage's default; filter, ranking boost or unused stays the retrieval
experiment's measurement, since a mistaken label used as a filter hides a
relevant review. Vector retrieval is a committed
second stage: a small open embedding model run locally with its version pinned
(a retired or silently changed provider model would orphan every stored
vector), chosen by a test of two or three candidates on these reviews, with the
vectors in a vector-search extension inside the existing SQLite file. Keyword,
vector and combined retrieval are all reported, including the case where
vectors add little. This supersedes two leanings recorded under the redirect:
the background pool of extra unlabelled reviews is deferred until misses can be
split into "not in the stored sample" and "not found by the search", and
brute-force comparison beside SQLite gives way to the extension. The third
leaning stands: no framework, since the chat is a fixed pipeline.

**The keyword search as built.** *Built 2026-11-14; figures from a copy of the
serving database taken that evening (115 games, 60,514 counted reviews),
regenerated by `probes/review_search_probe.py`.* The index is an FTS5 table
holding its own copy of each review's text, kept exact by an insert trigger on
the reviews table, which is insert-only. An index-only table was the
alternative; the reviews are keyed by a text id, so it would have needed a
second table mapping ids to row numbers, and two objects to keep in step were
not worth the 20 MB saved. The index is derived data: it adds 34 MB to a 104 MB
database, fills in under a second, and can be dropped and refilled at no loss.
Refreshing it after each publish, the way the store's facts are captured, was
declined: that cannot touch a job, but the index can then lag or miss reviews.

A search reads one pool per game: the members of its newest report's sample
that hold a label under that report's versions, which is exactly what the
report's sample size counts. Four samples hold members without such a label
(Fallout 4: 711 members, 565 counted), so "the sample's members" would be the
wrong pool. Two reads sit on it: how many of each game's counted reviews match
a set of phrases, and which of one game's counted reviews match best. They
return counts and identifiers; a caller knows nothing of how matching is done,
and that is the seam the vector stage replaces or joins.

Search terms are plain phrases. Code quotes each one before it reaches the
index, because FTS5's match argument is a query language and the phrases come
from a model's reading of a visitor's message. There is no stemming and no
prefix matching, and spelling variants are listed by the caller. The reason is
measured: `rogue*` nominates six games without a roguelike tag at a 1% share,
because a rogue is also a character class, where the spelled-out forms
nominate none.

A term clusters in a game at a 2% share of its counted reviews with at least
three matches. Read against the store's tags at that line, "roguelike" finds 8
of the 10 tagged games, "metroidvania" 3 of 4, "racing" 3 of 5 and "city
builder" 4 of 10, each with no untagged game nominated. Three limits came with
it, and they shape what a term may be used for:

- *Only presence is evidence.* For a wanted term a cluster is "matches" and
  anything less is "cannot tell", never "fails". The game that defines a kind
  is rarely called by it: the two Dark Souls games read 1.6% and 1.5% on
  "souls-like" while Lies of P reads 31.2%. For an avoided term ("not
  grindy") a cluster is "fails" and anything less is again "cannot tell":
  "grind" clusters at 18.1% of Graveyard Keeper's sample and appears in 98 of
  115 games, so a low share is the common case and says nothing. This mirrors
  the complaint aspects, which can only exclude.
- *Store features are rarely said in reviews.* "Co-op" finds 7 of 38 tagged
  games, which is why play modes are read from the store's categories. "Open
  world" finds 16 of 50 and has no category, so for traits only a tag carries,
  review search reaches a minority. That is evidence for the deferred decision
  on giving tags to the chat.
- *No single share fits every term.* "Puzzle" names a part of many games:
  tagged games sit at a median 9.4% and untagged ones reach 6.4%.

The tags are an incomplete reference, so an untagged nomination can be a game
that fits and lacks the tag in its top twenty.

**Each evaluation reference has one job.**

| Measurement | What it establishes |
|---|---|
| Recovering requests the test messages were generated from | parsing on that generation process |
| Requests written without sight of the request structure | whether wants outside the structure are kept or lost |
| Picks against the sheet | compliance with the evidence and the selection rules |
| Review search against community tags | agreement with an incomplete outside reference |
| Answers read against the retrieved reviews | support within the retrieved evidence |
| Whole conversations read by a person | whether the exchange answered the request usefully |

Test messages are built from the request outward: the structured request is
written first, with each want's firmness and target, and a model writes how a
player would say it, so the right reading is known by construction. Paraphrases
of one request stay together, and the cases are split before any tuning:
development cases choose prompts, models and thresholds, and separate cases
carry the reported results. The set includes multi-turn conversations in which
a requirement is added or withdrawn, requests too vague to act on, requests
nothing fits, off-topic messages and injection attempts. Relevance for
retrieval is judged on results pooled across the competing methods, without
knowing which method returned each one. Answer support is read by hand on a
small set first; an automated grader is calibrated only when repeated runs
justify one, and the labelling judge's calibration does not transfer to that
task. Five kinds of answer rest on the model's judgment where no code check
reaches, and are read by hand for that reason: near misses (was the game
worth offering), offers made against a conflict with a must (did the cited
reviews support it), answers to long lists of wants, comparisons with a named game
(did the claim come from the reviews of both), and anything about a story
(did it reveal plot). The test set includes wants about how much, loose
descriptions of a liked part, and stressed and soft wordings, since those are
where the understand step is most likely to misread. None of this measures
whether a player would enjoy a game.

**Three stages.** The first is one complete path through the real tab, kept
unlisted: a request, the sheet, keyword search, a few suggestions and
their follow-ups. The second makes it releasable: clarifying questions,
requirement changes across turns, the measurements above, coverage, storage,
the notice, and the security pass. The third is the retrieval experiment.
Nothing public describes the tab as vector retrieval before the third stage
reports.

**Conversations are stored for checking only.** Text is kept without the
sender's address, for a fixed retention period, with a one-line notice on the
tab. Players get no history feature. Stored conversations never enter the
repository; a real message that becomes a test case is rewritten first.

**The library grows by hand.** Games are added by the operator and by visitor
requests, with no claim to cover Steam, and the tab says so. Coverage is
measured as the share of test requests the library answers with at least one
fitting game and with at least three, against a dated library snapshot, since
the right answer to a request changes as games are added.

**Deferred, each with its trigger.** Tags given to the chat, and the extra
review pool: decided when the retrieval experiment reports. A comparison
against a full vector database with an approximate index: measured or skipped
after the same report; at this corpus size nothing needs one. The chat starting
a report job for an unmeasured game: after the tab has run under real traffic,
since it is public spend.

**The provisional choices, in one place.** Each was set on one library on one
day, with a reason and without a measurement of the chat. They are listed here
so that a disappointing result is traced to a choice and that choice is
reopened, instead of the nearest number being adjusted. The stage measurements
say which stage a fault sits in. Values are moved on the development cases
only.

| Choice | Now | Where it lives | Cost to change | What would reopen it |
|---|---|---|---|---|
| Mention floor | 30 | `core/sheet.py` | one constant; re-run the pick and coverage measurements | too few readable games per request, or picks resting on noisy cells |
| Positive tiers | interval starts above 70% and above 50% | `core/sheet.py` | one constant each | the strong tier too small to pick from, or too wide to select |
| Mixed and neutral in the sentiment share | counted against it | `core/sheet.py`, the sheet's definition | a rule change; every group moves (171 of 892 cells) | clearly negative games reading as split in the answers |
| Split and unclear | half-width within 15 points | `core/sheet.py` | one constant | "unclear" staying near empty, which makes it a second floor |
| Sentiment interval | plain Wilson on the mentions, uncalibrated | `core/sheet.py` | a calibration study on sentiment shares | groups disagreeing with a census reading |
| Split counts as "fails" for a want on an aspect | yes | the sheet's definition | one mapping | near misses the assessor judges unfair |
| Term cluster line | 2% share and three matches | `core/sheet.py` | two constants | wrong nominations, or kinds of game going unfound |
| Only a cluster is evidence, for a wanted and for an avoided term | yes | the sheet's definition | a rule change | answers that offer games plainly outside a stated kind |
| "Reviewers do write about it" | the phrase appears in ten of the library's games | `core/sheet.py` | one constant | the reply reporting an empty search as a finding, or refusing to report a real one |
| Which store facts every game declares | play modes, platforms, early access and genres; thirteen features are declared by choice | `core/store_facts.py` | one flag per fact | a feature most games turn out to declare, or a play mode some do not |
| A player tag withholds a genre failure | the genre's own tag and the tags naming a kind of it | `core/store_facts.py` | the tag list per genre | mistagged games crowding the "cannot tell" group, or tagged games still read as failures |
| No game removed on evidence | the sheet holds every library game; a conflict with a must is answered with cited reviews | `core/sheet.py`; the objection in `core/check.py` | a filter over the statuses | offers against a conflict that the hand reading finds unsupported, or a sheet too long for the judge to read |
| Default firmness | by target: a store fact and a term that says what the game is are a must; an aspect, an amount, a release range and a want with no target are a want | the prompt in `core/understand.py` | a prompt rule; re-run the understand measurement | near misses on the kind of game, good games withheld, or a want that names the kind of game reading as soft because its evidence is an aspect ("a game where my choices change the story") |
| A want's words | one unbroken stretch of a player message, checked by code on letters and digits | `core/understand.py` | the check, or the contract to "a faithful description" | retries spent on harmless rewordings, or details lost because they sit apart from the want |
| Aspect vocabulary shown to the understand model | each label with its one-line definition | `core/understand.py` | one render function; the compact codebook is the named alternative | wants landing on a neighbouring aspect |
| "Recent" as a release range | from three years before the current year | the prompt in `core/understand.py` | a prompt rule | players calling the range too wide or too narrow |
| Understand model and output mode | the labeler's model, temperature 0, JSON asked for in the prompt | `chat/understand.py` | one route; JSON mode is one parameter | the understand measurement, or a high rate of retried answers |
| A faulty answer | one corrective retry, then the faulty target removed and the want kept | `chat/understand.py`, `core/understand.py` | the ladder's rungs | turns lost to unreadable answers, or musts read as "cannot tell" after a salvage |
| Out-of-scope reply | one fixed text for every reason | `core/understand.py` | a reason field and a text per reason | refused players misled about what the tab does |
| Named-game matching | the model writes the title; code matches literally, whole title then a run of words | `core/game_names.py` | the matching rule | library games answered as "not measured", or a wrong game taken without the reply naming it |
| Questions before answering | one, or up to three for a request with nothing in it | not built (the second stage); until then the pick may always ask | a prompt rule | players leaving before a suggestion, or suggestions with nothing behind them |
| Quotes and numbers in the chat | only when the player asks | not built (the second stage); the first stage shows none | an interface addition | hand reading that finds claims the player could not have checked |
| Search matching | literal phrases, no stemming, variants listed | `store/review_search.py`, the schema's tokenizer | drop and refill the index | wants missed for spelling |
| Index kept by a trigger | yes | schema step 10 | drop the trigger, add a refresh | any job failure traced to the index write |
| Store facts captured after the publish, failing soft | yes | `serve/storefront_capture.py` | one call site | library games left without facts |
| Tags kept from the judge and the player | yes; code reads them only to withhold a genre failure | `core/store_facts.py` | a design decision at the retrieval report | kinds of game the reviews do not name |
| Retrieval method | keyword only | the two search reads | the vector stage | the retrieval experiment's result |
| Models of the pick and the answer call | the labeler's model, temperature 0, thinking off, a route each | `chat/pick.py`, `chat/answer.py` | one route each | picks that break the sheet's rules or show poor judgment on a hand reading (thinking on, or a stronger model, for the pick); replies that read like a report or state what the excerpts do not support (the answer prompt first, then a stronger model, kept cross-family from the judge) |
| Candidates a pick may name | 6, twice what a reply offers | `core/pick.py` | one constant | good games never read on a broad request, or a prompt too long to pick well from |
| Games offered in a reply | 3 | `core/answer.py` | one constant | replies too long to read, or sound candidates cut |
| Things a question may need to know | 3 | `core/pick.py` | one constant | questions that read as a questionnaire |
| Pairs of a game and a want read a turn | 24, musts first, then the pick's list, then the rest | `core/pick.py` | one constant; the ranks are a rule | pairs cut on requests of ordinary length |
| Excerpts a read | 6, each capped at 300 characters; an aspect is read by label from five mentions up | `chat/evidence.py`, `core/excerpt.py` | one constant each; the cap and the floor are the report page's | replies resting on too little, or six excerpts that misstate an aspect's balance |
| Subjects read on a turn about one game | 4, in the player's order | `core/material.py` | one constant | questions left unread |
| Reviews read for a general question about a game | none: the reply names the parts reviewers praise and criticise and may offer to go into one | `core/material.py` | a read plan and cite rules for that turn | answers that read as empty, detail filled in from the model's memory, or the retrieval experiment's result |
| Passages that set an undecided game aside | two or more that describe the game itself as going against a must | the answer prompt in `core/answer.py` | the wording, with its pin | the answer measurement: the call did not keep it on the comparison run |
| An offered game's criticism said unasked | its most mentioned clearly negative aspect, when a tenth of the sample or more mention it and no want targets that aspect | `core/material.py` | one constant | replies crowded by the clause, or a heavily criticised game offered with none |
| Order inside a pattern of the pick's sheet | shuffled by a seed from the conversation | `core/pick.py` | one function; app-id order is the alternative it replaced | picks that still follow position, or a need for one request to give every player the same games |
| A game's line in the pick's sheet | an identifier, genres, release year and readings, with no title | `core/pick.py` | one render function | picks of the wrong kind of game on a word match |
| Which failed must may be put forward | only an avoided word that clusters | the pick's parse in `core/pick.py` | one rule | sound offers against a store fact or an aspect found removed |
| Reply length | about 150 words, recorded and not enforced | `core/check.py` | one constant | replies players stop reading |
| A quote of a review | two words or more in quotation marks that appear in one of the turn's excerpts | `core/check.py` | one constant | single quoted words carrying a reviewer's phrase, or ordinary phrases refused |
| Recorded rules asking for the retry | no: relayed wording, a working word and length are named in a retry that runs for another reason | `core/check.py` | one value per rule | the answer measurement, weighing faults removed against sentences changed |
| Fixed texts of a turn | one text for a turn that was read and got no answer; four stand-ins for replies the first stage does not write | `core/turn.py` | the wording | players misled about what went wrong, and each stand-in when its reply is built |
| A message that asks about several games | a fixed text asking for one at a time | `core/turn.py` | one rule; an answer about each is ruled for the second stage | that build, or players put off by being asked |
| Where a conversation is kept | the server's memory, between turns; a restart ends every open one, and the browser holds only an identifier | `serve/conversations.py` | what sits behind four methods; the database comes with the chat's storage | the storage design, or conversations lost to deploys often enough to matter |
| A conversation's bounds | 12 turns, a message of 1,000 characters, two idle hours, 500 kept at once | `serve/config.py` | one constant each | players reaching the end mid-thought |
| Chat turns a day | 60 an address and 300 for everyone, counted at admission, in memory | `serve/chat_gate.py`, `serve/config.py` | one constant each; a table for counts that survive a restart | the shared spend backstop firing on a day of ordinary traffic, or the tab being linked |
| Chat turns at once | one an address, four in the process | `serve/chat_gate.py` | one constant | waits that read as a hang, or a chat route moved to a provider with a rate quota, which needs a shared pacer |
| A turn's spend ceiling | $0.05 on a model client built for the turn, with its response archive in memory | `serve/chat_turns.py` | one constant; the archive is one argument | a turn refused for a report job's spend, or the storage design giving the answers a retention period |
| What the chat's route answers | one request, answered when the turn has ended | `serve/chat_api.py` | a stream of the steps beside it | retried turns common enough that the wait reads as a hang |
| How the tab stays unlisted | an unlinked address that asks not to be indexed; anyone who has it can use it | `serve/web/` | a pass in front of the page and the route | chat turns or refusals that are not the operator's |
| What a page links under a reply | the report of each game the reply offers, apart from each it speaks of, and the way to add a game under a reply that found nothing | `core/turn.py` | one rule | a reply whose sentence about the page is untrue |

Not on this list, because they are not switches: the library's size, the
stored sample as the only pool, the aspect vocabulary, and the fixed order of
steps. A fault traced to one of those is a design question.

---

## Standing rules

**The post ships with the milestone.** Every milestone's public artifact ships when
the milestone does, imperfect: shipping deliberately outranks polish.

**The ops story is a deliverable, not plumbing** (2026-07-08). Two-sided stance: no
infrastructure without a driving product need (the Kubernetes/Terraform tombstone
stands), but no skipping an ops opportunity the product genuinely justifies:
DevOps/MLOps depth is a deliberate portfolio pillar here. What the product already
justifies, made visible instead of silent: evals-in-CI, observability surfaced in a
small ops dashboard, versioned provenance on every artifact, and a deploy pipeline
as code. The test for any addition stays: does *this product* need it?

---

## Scope & non-goals

- In: aspect reports with receipts, narrated live analysis, the volume +
  positive-share timeline (episode detection stored, not rendered), the
  trust panel, Docker/FastAPI/SQLite/CI deployment,
  the evaluation methodology as a public artifact, the ops story as a public
  artifact. The recommender chat's steps and a first tab are built, and the
  tab is unlisted (the recommender chat section): in the design, not in the
  shipped scope.
- Deliberately out: fake-review verdicts (tombstoned under Data access) ·
  multilingual evaluation claims (post-launch experiment, unverified if shipped) ·
  Kubernetes/Terraform/cloud MLOps (zero marginal signal for a portfolio app) ·
  ranking games against each other by a measured number (the recommender chat reads
  numbers across games in groups; cross-game comparison itself was out until the
  2026-11-14 reversal) · verdicts on buying or enjoyment ·
  the agentic investigator (deferred 2026-07-27, the redirect above) · any displayed
  number sourced from outside the survey mint (the old investigation-track wall, now
  also covering the chat pool).

---

## Open questions / deferred

- **LLM tier for the chat's stages** — the understand, pick and answer calls
  each get their model by measurement on the development cases, per the tier rule (the
  recommender chat section). The survey-labeling stage is decided (the
  labeler ruling); the composition stage is decided (the deployment design:
  v4-flash, cross-family from the judge). The judge stays exempt: always a
  stronger model than the one it grades. *(Resolved at M3: cache persistence —
  the ephemeral-host premise dissolved with the bought box, the serving
  persistence rulings cover it; hosting shape — the netcup box, the entry
  state above.)*
- **The user-facing report refresh** — deferred from the staleness ruling: a
  public refresh trigger is a spend amplifier, added only once it is decided
  who may pull it. Structurally free when taken (a new job, a new report row).
- **The human annotation track's parallel remainder** — never gating any
  milestone: the self-relabel consistency subset · judge-disagreement
  adjudication (sheet seeded from the top-disagreement exemplars; decides
  whether `updates` 0.611 is production under-detecting or the judge
  over-finding). The fresh v2 holdout and the misattribution audit both
  landed 2026-08-04/05; outcomes in their sections.
