# DESIGN — steam-lens

What is being built and why — the decisions and their reasoning, as a narrative
snapshot of the current design, edited in place as decisions evolve. **This document is
the living source of truth for decisions from the vision phase onward**; `VISION.md` is
the fixed vision-phase snapshot (2026-07-07) and is not updated as the design moves.
How it's built → ARCHITECTURE; the pitch → README. Executed experiments appear here
as conclusions with citations to their runs of record.

*Living snapshot · last updated 2026-07-30.*

---

## Objective

An app where entering a game returns what players actually like and dislike — aspect-
level strengths/weaknesses with verbatim evidence, episode markers on the review
timeline, and a grounded chat that interrogates the report's evidence — computed live
at request time on real Steam data, with a rigorous, honest evaluation of whether
the LLM doing the reading is actually right. **Success
criterion:** a stranger uses the deployed app unassisted and every claim they see is
attributable — to specific reviews (quotes), to a measured sampling tolerance, or to a
published error rate; and each of the four milestones ships a standalone postable
artifact.

## The evaluation spine — trust must be earned in layers

**The human anchor.** All automatic checks fail precisely at interpretation of meaning —
grounding passes a sarcastic quote read upside-down; consistency passes a consistently
wrong system; an unvalidated LLM judge is a model grading its own blind spots. So the
eval anchors on ~250 reviews blind-labeled by the builder *before* seeing model output,
with a later self-relabel subset measuring labeling consistency. Judge-only evaluation
was rejected as the industry's named anti-pattern (verified against current provider
guidance and practitioner canon, 2026-07-07); the single-annotator limitation is stated
in every artifact rather than hidden.

**The calibrated judge.** An LLM judge is used only after its agreement with the human
labels is measured — reported per category, since agreement varies by item type — and
scaled numbers carry the judge's measured error.

**Precise metric naming.** The mechanical quote-check measures **fabricated-quote
rate** — it is deliberately not called a hallucination rate, because a real quote
attached to a wrong reading passes it. That failure class (misattribution — sarcasm is
Steam's native dialect) is measured separately by human audit of ~100 claims.
Adversarial inputs are a standing harness requirement — the product's entire input
is attacker-controlled text — but no prompt-injection canary set exists yet: it
lands with the first surface that renders model prose (deployment, M3), deferred
on the same grounds as the numeric-grounding check.

**Evals gate softly.** The harness runs in CI on prompt/model changes with tolerance
bands and trend reporting; a hard build-fail on a noisy LLM metric was rejected because
a red-X-then-override history is worse than no gate. (As built, the CI gate re-scores
stored output deterministically, where exact-digit failure *is* honest — see the
evals-in-CI decision; tolerance bands became the label re-buy rule.)

## The two-track engine — adaptive curiosity without corrupted statistics

**Per-review classification over holistic synthesis.** Each sampled review is
independently classified (aspects + polarity), then deterministically aggregated; the
LLM phrases narrative *over* the aggregates. Holistic read-the-sample-write-the-report
was rejected because evidence counts become uncountable, the sampling study loses its
object (stored per-review labels are what offline resampling resamples), and cost/
latency stop being analyzable.

**The survey/investigation split.** A fixed representative sample produces every
displayed number; an agentic investigation loop — hypotheses from the timeline and
survey signals, targeted windowed fetches, verify-then-explain, hard round caps —
produces every story. **The one rule: the investigation's deliberately biased fetches
never feed the percentages.** Without this rule the adaptive loop (which hunts the
unusual by design) would silently poison the statistics it sits beside; with it, an
investigator and defensible statistics coexist. Born from a real constraint: a fixed
500-review sample of a 200k-review game holds ~a dozen reviews from any spike — no
representative sample can explain an anomaly.

**The narrated runtime.** Both tracks stream progress; suspicions are labeled
hypotheses until their check passes. This is a trust feature first (the uncertainty
discipline extended to the process itself) and a latency solution second (a watchable
investigation replaces a spinner; minutes become acceptable).

*Redirect 2026-07-27: the story channel changed instruments — the agentic investigation
loop is deferred with its milestone, and a grounded RAG chat over labeled reviews
produces the stories instead. The one rule survives translated: chat answers quote
retrieved reviews and never mint numbers. See "The redirect & the product frame".*

## The system flow — module boundaries, seams, contracts

Settled 2026-07-09. The decisions and their reasoning; the module map itself lives in
ARCHITECTURE.md.

**Four strata, one import law.** Plain-data contracts (import nothing) → pure core
transforms → effect shells (Steam client, LLM client, store, narration sinks) →
orchestrator and entry shells (pipeline runners, serving, CLI, study drivers). Core
never imports a shell; the entry shells — the eval harness and the study drivers —
are import-forbidden to everything; a CI import-graph test asserts the whole table
and refuses to fail open (a package must declare its rank to exist, relative imports
are banned). Four independent design framings converged on this skeleton. The
build later inserted a generic run-machinery stratum between the doors and the entry
shells, after the full-base review (2026-07-27) showed the shells sharing that
machinery by reaching into each other's interiors instead — the as-built graph lives
in ARCHITECTURE.

**The sampling policy is core code, executed by shells.** A pure plan compiler turns
histogram + policy into a fetch plan; the Steam client executes plans against the live
API, the study runner executes the same plans against the corpus. The load-bearing
consideration: with policy logic inside the client shell, the sampling study (M2)
would certify a simulation while production ran a later reimplementation — a measured
tolerance describing code that never ships.

**Labels are a version-keyed pool, not sample property.** Per-review labels are keyed
by (review, model, prompt version, ontology version) and carry an origin tag (survey /
investigation / corpus). Aggregation takes a manifest + the pool + an explicit version
pin and folds only manifest members with survey origin. The alternative —
manifest-keyed labels — was rejected: strict
origin-checked aggregation rejects exactly the offline resampling the sampling study
exists to perform.

**Two-track enforcement is defense-in-depth, never "impossible."** Every claimed
structural impossibility fell to a concrete bypass under critique. The honest
guarantee, adopted: independent walls — distinct container types at the sampler seam
(only the survey draw mints a sample manifest; the investigation's window fetch
returns a manifest-less type), the store's membership join carrying an origin
predicate, the CI import test — plus origin tags making any leak auditable after the
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
and a finding event is constructible only from a verified conclusion — the honesty
rule lives in the type, from the first offline console sink onward.

**Budget enforcement is a simple atomic counter.** Reserve-before-dispatch against
per-query / daily / monthly scopes; typed exhaustion errors become the honest
at-capacity state; the provider-side cap is the named backstop. A reserve-commit lease
machine with TTLs was rejected — its own failure modes reintroduce the race it
prevents. Eval spend is separated from the production cap in config.

**Contracts: rules now, fields later.** Fixed from day one: the import law, the
membership join + origin predicate, label-pool keying, provenance stamps on every
persisted artifact, the event-status enum. Record field lists freeze when their first
consumer lands — pre-building every contract at M1 was rejected after critique showed
a pre-built M4 contract already missing what M4's own success criterion needs. The
interval method for displayed shares is likewise the sampling study's (M2) output
alongside the policy: a stratified design changes the variance math, so committing to
a formula now would ship a wrong error bar in the product whose thesis is honest
error bars.

**Ops conventions adopted from practitioner canon, fit-tested:** prompts as versioned
files with content hashes; one spend-ledger table powering the caps, the M1 cost
table, and the ops dashboard; classify-call caching keyed on content (review-text hash
+ prompt + model + ontology versions); the gold set as versioned files in the repo.

### The contracts

**Frozen dataclasses, validated at the shell** (2026-07-09, the M1 foundation). The
plain-data spine is `@dataclass(frozen=True, slots=True)` — immutable, hashable,
closed-shape, importing nothing; validation lives in the shells, where a pydantic
parser turns raw external JSON (Steam payloads, LLM responses) into a clean contract,
so *trust no raw data* and *plain data crossing the seam* are both honored and pydantic
never reaches core.

**The classification envelope.** One review yields one `ReviewClassification` —
recording *that* it was classified, under which versions, with zero-or-more aspect
mentions — rather than a flat mention list. Under a flat shape the probe's
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

## Data access — a narrow, buggy, sufficient API

*Verified data shapes from the smoke-test milestone (M0, 2026-07-09) live in
`probes/FINDINGS.md`: datacenter reachability PASS; histogram granularity
(monthly history + daily last-30, age-dependent rollup unit); off-topic flags
(per-window `past_events`, default listings blank whole marked windows).*

**One sampler module owns all review access.** Steam's keyless store API offers
sequential cursors (~200 req/5 min), an intermittent short-batch bug (no safe batch-size
constant — detect and retry instead), a cursor-loop bug on the helpfulness sort, and
undocumented date-window parameters (live-verified 2026-07-07) enabling temporal jumps.
The sampler uses **windowed access as the primary path** — it is the investigation
track's enabler — with the documented cursor-walk as automatic fallback and every
report's provenance stating which path ran. Refusing the undocumented params (considered
for volatility) was rejected: the documented surface is itself buggy, and the boundary +
fallback absorbs the volatility that refusal would only avoid by forfeiting the
product's best capability.

**Marked-window reviews: include + disclose** (settled 2026-07-09). Survey
numbers include sampled reviews falling inside Valve-marked off-topic windows; the
trust panel discloses the count per window and links the timeline event. Excluding
would re-apply, by hand, the blunt blanking the unfiltered fetch exists to avoid — the
probe's marked window split ~50/50, thousands of legitimate reviews inside — and
per-review classification absorbs bomb reviews into the aspects they actually complain
about, while the story track owns the bomb *story*. Two amendments: (1)
**membership is derived at read time** from the freshest
`past_events` snapshot — Valve marks windows retroactively, so a fetch-time stamp goes
stale exactly when it matters; (2) a **marked-share floor** — past a threshold
(provisional now; tuned at the sampling study) the report degrades honestly rather
than presenting a bomb-dominated sample at full confidence. The exclude-counterfactual
stays computable offline but is never displayed: at 500-review sample scale the delta
is noise inside the interval.

**English-first, all-language counts.** Extraction reads English — the language the
gold set can verify; an unevaluated multilingual layer would contradict the project's
thesis. Counting layers (timeline, totals, score context) always cover all languages;
every report discloses the language mix; event explanations are **withheld with a
stated reason** when a window is majority non-English — the alternative was confidently
explaining a Chinese-language backlash from the English 30%, a fluent wrong answer in
the flagship feature. Turkish: informal spot-check only (a headline TR eval would be
statistically hollow at gold-set scale).

**Events, not accusations.** The anomaly layer detects and explains episodes (what
happened, when, about what) — statistical detection over the full-population histogram,
explanation from targeted reads, verification against the game's public patch history
(an external, non-circular anchor). Valve's off-topic flags are a comparison signal for
the review-bombing subtype only. *(Tombstone: fake-review detection — cut 2026-07-07;
no ground truth exists, the claim is unfalsifiable, and an unvalidatable accusation
makes every other claim less trustworthy.)*

*Redirect 2026-07-27: the explanation half is deferred with the investigator —
deployment (M3) ships display-only episode markers, pure statistics over the
all-language histogram; the detection layer and the tombstone stand. See "The
redirect & the product frame".*

### The door as built (`steam_client`)

**Donor, not template.** The module is a fresh build to the windowed-unfiltered
sampler contract, *not* a copy of the prior steam-reviews fetcher — that file is a
**donor reference** whose paid-for Steam-API knowledge (the retry/backoff GET, the
identity guard against wrong-appid pulls, endpoint quirks) is deliberately harvested,
while everything structural is rebuilt to this project's bar. Importing the frozen
repo, rewriting from scratch, and a naive file copy were each rejected — the last
because the frozen default-walk loop *is* the proven-unsafe blanking path, and its
silence on logs/cost/latency is exactly the observability gap this project treats as
a deliverable.

**Three operations, both paths** (ruled 2026-07-27).
The build scope is resolve-game (appdetails + the donor's identity guard), the
histogram snapshot, and the window-fetch primitive — deliberately *not* `FetchPlan`
execution or `SampleManifest` minting, whose producer (`core/sampling`, the policy
the sampling study certifies) doesn't exist yet. Three contracts froze with their
consumer: `GameRef` (identity-guard verdict absorbed into the record — a MISMATCH
`GameRef` is an honest answer about what Steam returned), `HistogramSnapshot`
(rollup unit never hardcoded, per the M0 probe), and `WindowFetchResult` (per-window
provenance: path outcome, pages, retries, and a semantic-validation verdict — the
window params are undocumented, so every response is checked against the requested
window, never trusted).

**The cursor fallback is built, not stubbed.** It is the same machinery as the
windowed walk under timestamp-gated loop control, plus a pure feasibility estimate
(SKIPPED_INFEASIBLE, disclosed, never a silent hole). Stop discipline everywhere:
the walk stops on the window boundary, a repeated cursor, or a missing cursor —
**short or empty pages inside a window are suspicious, not conclusive: retried,
never a stop** (the donor's proven-unsafe stopping rule, inverted). Standing
correction on the donor's confident comment: **no page size is universally safe**
(FIXLOG 2026-07-07) — page size is a non-load-bearing config knob (default 100;
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
makes both durable, and the two consumers — the census dispatch that bought the pool
and the aggregate mint that folds it.

### The provider seam (`llm_client`)

**One generic door, routing as data** (settled 2026-07-13). The client exposes a
single `complete()` over a stage-keyed request — never per-stage methods: the
per-stage routing table (stage → provider, model, params)
stays *data*, so retargeting a stage is a config edit. Each route carries an opaque
provider-params block passed to the adapter untranslated, dodging the
lowest-common-denominator squeeze without widening the seam; the one field lifted out
of it is `max_output_tokens`, because the budget reservation must price it. The
response carries everything downstream needs — the token-usage split (thinking tokens
included), normalized finish reason, resolved model version — since guards, ledger,
and provenance can only record what crosses the seam.

**Raw HTTP through registered functions; no aggregator, no SDKs.** Providers are
registered functions (a dict registry, constructor-injectable for tests) speaking
httpx. litellm was rejected — a large fast-moving dependency that normalizes away
exactly the provider-specific fields the earned guards watch; per-provider SDKs were
rejected because vendor retry machinery overlaps ours (double-retry against tight
quotas), though an SDK may still slot *inside* one adapter later without touching the
seam. Config validates against the registry at construction — an unknown provider
fails at startup, never mid-run.

**Synchronous, concurrency-shaped, dialed to sequential.** asyncio was rejected:
coloring spreads to every caller while the throughput ceiling is the provider quota,
and sync composes with M3's async serve via standard thread offloading. The one
stateful bundle (budget, pacer, ledger appends) is lock-guarded and hammer-tested;
the worker pool lives in the *caller* with `max_workers` as config defaulting to 1 —
a throughput flip is a route edit plus a number, zero code.

**Budgets reserve before dispatch.** An atomic worst-case reservation (pessimistic
prompt estimate + the route's full output ceiling, priced) settles to actual cost on
completion — overshoot impossible by construction — and daily-quota admission counts
ledger rows *plus in-flight calls*, since the ledger alone lags dispatch by exactly
the racing window. Rate and quota limits key by *model*, never by route, so two
stages sharing a model share one real quota pool. Token prices are data in the
per-model config table (free tier is honest zeros; a paid flip is a number edit).
The hammer tests pin the exact-admission property; finer build detail lives in the
module docstrings.

**Errors are typed, and the two capacity states never blur.** Transients retry
inside with bounded backoff and surface as `LlmUnavailableError` only when exhausted.
`AtCapacityError` — our own reserve refusing — is never retried and is deliberately
distinct: one is the world failing, the other is us keeping a promise, and only the
latter becomes the honest at-capacity state. Truncation is not retried (temperature-0
re-truncates identically) and carries its normalized reason for the caller to decide.

### The classify stage (`core/classify`)

**The prompt renders the codebook full-fidelity** (settled 2026-07-13). A
versioned artifact (file + content hash + changelog) carrying
every field, all aspects, category-grouped — so the machine annotator reads the same
instructions the human annotator reads at gold labeling, keeping the agreement number
clean of instruction gaps. The compact decision-surface rendering was pre-registered
as an experiment and later **closed on measured evidence** — a confirmed recall loss
at both gold and census scale (see the codebook section).

**Batch-native with size as config.** The builder takes idx-tagged review tuples,
the parser returns per-idx envelopes, one prompt version serves every batch size, and
N rides in the run's config hash. Gold-set evals run at the production batch size —
certify what ships. The never-re-paid promise lives in the *label pool*, not the
response archive: the driver selects only reviews lacking labels under the current
version key, so batch composition varies freely across runs.

**The model emits label strings only.** Pinned-vs-candidate resolution belongs to
`core/normalize`'s deterministic surface index, never to the model's
self-declaration — the prompt teaches the two-slot *behavior* (never force-fit; the
reviewer's own words when nothing fits), code decides the slot. Output shape is
enforced twice: a provider-side response schema (sentiment a closed enum; the aspect
field deliberately a *free string* — an enum of pinned labels would structurally
forbid candidates, silently) and one provider-portable shape line in the prompt.
Three synthetic few-shot examples cover the edge behavior — the zero-aspect review,
dissociated sentiments, a candidate emission — synthetic so gold disjointness is
structural, mid-tail so the frequency thumb stays off the headline aspects.

**The parse is pure and salvages per idx.** Every valid entry becomes an envelope;
every failed idx lands in a typed failure report the driver must handle — one bad row
costs one review, never the batch. Evidence failing the verbatim-substring check is
**repaired, not fatal**: the mention survives with evidence=None and the repair is
counted through the sink (a rising repair rate is the early smell of what the
fabricated-quote metric measures properly).

**Retry is re-batching, not corrective prompting.** At temperature 0 an identical
request re-buys the identical wrong answer — and the archive would return it without
even spending — so the retry must vary the request; failed reviews re-entering the
driver's selection loop regroup into fresh batches, which *is* the variation, for
free. One round, then the review is marked unclassifiable-under-this-version and
disclosed in the run report — include-and-disclose applied to our own failures.

### The store

**Tables land with their first consumer** (settled 2026-07-14) — the *rules now,
fields later* principle applied to schema: pre-building
`eval_runs` would have guessed at exactly what the eval-journal design existed to
decide. Schema lifecycle is a hand-rolled ordered-steps **migration runner** stamped
via `PRAGMA user_version`; Alembic was rejected (SQLAlchemy machinery on a raw
`sqlite3` store), but so was bare create-if-missing — the runner costs ~ten lines
more and means the first real migration slots into standing structure. The **freeze
rule** scopes the discipline to when it pays: steps froze append-only the moment the
first file held paid data, and steps are **additive by default** — a data-rewriting
step is a design smell requiring a stated reason.

**Two versionings, never converted into each other.** The schema version protects
bought data from *our storage* changing; the content-version keys protect correctness
from *the question* changing — old-version labels aren't migrated, they coexist under
their own key, which is what makes the pool accretive.

**Validation is asymmetric by design.** Writes take frozen contracts trusted by
construction (structural constraints only — NOT NULL, FK, UNIQUE); reads treat the
file as raw external data and validate by *reconstruction* — enum constructors plus a
naive-timestamp-rejecting datetime parse, failing loud with the offending row.
The label pool is
**normalized, never a JSON blob** — the load-bearing queries (the origin ∩ version
fold, the two-track wall's origin predicate, denominator counts) all reach *inside*
the envelope. Write semantics follow each contract: archive `put` upserts, ledger
`append` is insert-only, envelope inserts **fail loud on UNIQUE violation** — a
duplicate envelope means the driver's selection is broken, and `OR REPLACE` would
hide exactly that bug. Table shapes and the test strategy live in ARCHITECTURE and
the module docstrings.

### The response archive — raw provenance, not a cache

The store of bought provider responses is named `ResponseArchive` (renamed from
`ClassifyCache`, 2026-07-21) because it is a durable, content-addressed record of
*unreproducible* raw provider output — an LLM reply can't be regenerated, and the
archive is its only durable copy, so "clear it to reclaim space" must read as the
data loss it is. Re-pay-avoidance (the `get` before dispatch that lets a run resume
without re-buying) is a *free consequence* of a permanent content-addressed store,
not a second design goal. The seam stays text-only: raw is a *forensic* affordance
(reading a model's discarded reasoning trace during disagreement investigation),
never an input to a metric — retrieval is by reconstructing the content-hash key on
demand, sound because version pinning makes the recompute exact. Splitting a
disposable cache from the archive was rejected (identical bytes under an identical
key — structure with no operational teeth), as was carrying raw bytes on every
response.

### The census dispatch (`studies/`)

**A thin entry shell over the seams** (settled 2026-07-19). The driver composes
corpus reader → store ingest → selection → batch → classify → client → label
pool, narrating through the sink. Resume needs no
checkpoint ledger by construction: `unlabeled_under` *is* the checkpoint, batch
composition is deterministic over the remaining set, and the content-keyed archive
makes a re-formed batch whose response was already bought free — crash anywhere,
relaunch, pay only for what never completed.

**The label key's `model_version` is the requested id, never the response's
self-report.** Keys are contracts, observations are evidence: the reported string
journals per call in the spend ledger, and a mid-run change from the first-seen value
**aborts loud** rather than warn-and-continue — a silent provider model roll is
exactly the event that would split the pool's "one annotator" claim, and resume makes
the abort cheap.

**Failure policy: the three-pass sweep, then a durable mark.** Initial batches →
failed idxs re-batched at production N → survivors isolated at N=1 → still-failing
reviews marked durably (excluded from future selection under this versions triple).
Amended on live census evidence (2026-07-20): a provider's *permanent* rejection —
DeepSeek's content filter refused one review's Tiananmen line — fails the batch's
rows into that same sweep, so innocent co-batched reviews label on isolation and only
the trigger review takes a durable mark carrying the refusal verbatim. The pool
honestly records "the annotator refused this text" — an instrument-limitation
footnote the milestone post carries: a Chinese-hosted annotator imposes its content
policy on the census. Two guards from the same incident: a circuit breaker still
aborts on systemic refusals (a revoked key must surface as an abort, never as
thousands of quiet marks), and an aborting run cancels its queued batches — abort
means stop by construction.

**Budget caps sit below the balance.** The invocation cap is set deliberately under
the provider balance so our clean `AtCapacityError` always fires before the
provider's insufficient-balance error; the driver narrates the ledger's lifetime
total at startup, and a pilot slice gates the full buy on measured cost-per-review.
Ingest asserts the ruled census size (135,260) and fails loud before any money
moves — the slice ruling became a runtime check. Concurrency topology (two store
connections, worker pool shape) is structural detail: ARCHITECTURE.

### The number mint (`core/aggregate`)

**A pure fold with persistence pushed to the shell** (settled 2026-07-20).
Survey-origin, version-pinned envelopes → `AspectAggregate` records; the
core stores nothing, because the fold is cheap and fully reproducible
(keep-vs-regenerate: regenerate the cheap middle). Persistence is taken deliberately
only when a number is *published* — a snapshot stamped with full provenance, a
frozen citable artifact rather than a live cache, so staleness is a non-issue.

**The grain is per game.** A number is minted per `(app_id, aspect, slot)` — every
consumer lives at the per-game grain, a global fold blends incomparable populations
and can never be re-split, and per-game rows always roll back up. Per-game is also
the only grain honest about thin games: a small title's few mentions show *as* thin
instead of dissolving into a large pile. `app_id` joined the contract as a
first-class field — hiding the game inside `manifest_id` fails the
references-carry-their-meaning rule.

**Candidates fold exactly like pinned — no fuzzy merge, singletons kept.**
Candidates group by their exact stored string; `grind`/`grinding` stay distinct,
because a false merge silently corrupts two aspects at once while a false miss lands
recoverably in the candidate stratum for human-gated alias promotion (an offline
loop: new ontology version + cheap deterministic re-normalize, no LLM re-buy). No
floor at mint: the contract keeps the number a raw tally and the floor a display
rule, so C2 has exactly one job — count everything, honestly — and every policy
question lives downstream in one place.

**The denominator is the per-game survey envelope count, empties included.**
Dropping the ~46% empty-mentions envelopes would inflate every share — this is
exactly why the empty envelope is a first-class contract state. Only survey-origin,
version-matching labels fold, pinned **v2 by explicit path**: the packaged ontology
default stays v1 (gold's identity pin), so every pool consumer pins v2 explicitly —
flipping the default is a deliberate later step that must rework the runner's
gold-pin check, never a side effect.

> **Outcome.** The census is bought and settled (2026-07-20): 135,259 envelopes + 1
> durable content-filter refusal = 135,260 exact under
> `deepseek-v4-flash / classify-v1 / v2`, true cost $3.80 all-in, Drive-backed with
> a hash manifest. The mint verified on the real pool: 49 games, 170,532 mentions,
> the reviews_with_aspect invariant holding wholesale.

---

## Choosing the labeler — measured, not reputed

**The tier rule: per stage, not global.** The provider seam routes each stage
independently, and the small-vs-frontier gap is stage-dependent — near-zero for
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
| Primary: mention-level P/R/F1, paired by label within review, pinned-slot only | the known failure mode (over-extraction) is directional — F1 alone would blur it |
| Sentiment: flat accuracy on matched pairs only | polarity errors never double-punish detection errors |
| One gate: >2% unrecoverable parse failures disqualifies | dropped reviews at survey scale are missing-data bias no metric repairs; below the gate a failed review scores as zero predictions, never excluded |
| Candidate-slot mentions unscored on both sides | n=11 in gold can't support a metric; slot discipline is already priced in |
| Parity: `classify-v1` verbatim, no per-model tuning; structured output deliberately non-parity | tuned prompts would measure our effort; the native output mechanism is part of the product being bought |

Bootstrap CIs resample over *reviews* (mentions within a review aren't independent);
every run lands as captures + a manifest, and the comparison table regenerates from
captures + gold — one source of truth. Lineage: the gold-assist model is banned from
the pool (INSTRUCTIONS §8). A standing no-buy exit was live: the recorded outcome
could have been "nobody is buyable, escalate tiers" — never buy-the-least-bad.

**Batch size is part of the product, not a parity constant** (amended 2026-07-18).
The bake-off's N becomes production's default and certify-what-ships means measuring
each candidate at its deployable shape; a disclosed N-probe set the dilution ceiling
on two structurally different candidates before any scored run. The campaign's
operational lessons (envelope exits, the three-stage retry that preserves the gate's
semantics at a fraction of the requests) live as comments on their candidates in
`probes/bakeoff_runner.py`.

**Paired reads, not interval eyeballing** (2026-07-19). Every run scores the same
250 gold reviews, so run-vs-run gaps are paired — `paired_bootstrap_ci` resamples
one set of review indices and scores both runs on it. The correction cut both ways
on the same day: one gap with heavily overlapping individual CIs was **real** under
pairing, a second was **indistinguishable** — eyeballing would have called both
wrong. **N froze at 10 on quality's call alone**: the v4-flash ladder peaked at n10
two-sided, and true cache-adjusted cost is N-independent in practice, which closed
the amendment's honesty rider — the free-tier pressure that motivated maximizing N
never bound the paid winner.

**The ruling: DeepSeek v4-flash at N=10 labels the survey** (ruled 2026-07-19).
The honest sentence: Gemini 3 Flash is measurably better at matched N
(+0.034 F1, paired CI excludes zero), the gap closes to indistinguishable against
v4-flash's frozen N, and it costs ~12× more — v4-flash wins on cost-effectiveness
with zero parse failures across its ladder. Not claimed: "as good as the leader."
**Single-labeler discipline**: a free-Gemini-with-DeepSeek-fallback hybrid was
rejected — a mixed-labeler pool breaks measurement integrity (two error profiles
inside every aggregate; the judge calibrates against one labeler). Reopen
conditions, recorded with the ruling: a prompt change (re-certifies quality *and* N
on gold — exercised at the v2 codebook certification), provider repricing or
deprecation (the `deepseek-chat` five-day retirement is the named precedent), and
survey-scale anomalies surfacing through the eval harness — tier escalation is the
recorded fallback, never quiet tolerance.

**The slice ruling: census of the usable pool** (ruled 2026-07-19). The
survey labels **every English-nonempty corpus review — 135,260 across 49 games**.
This deliberately reopened and superseded the earlier "full corpus is never
labeled" ruling on its collapsed premises: the labelable pool measured 135K, not
the 298K headline, and the cost base was v4-flash's true ~$3–6, not Gemini's ~$25 —
census costs 2.9× the sampled alternative and buys no shortfall policy, zero
sampling error against the corpus, and a sampling study never capped by today's
choice. **No pre-filtering beyond usable**: "no aspects" is the certified
classifier's own verdict and a measured quantity (gold zero-share 49.2%); a
usefulness heuristic would be an unvalidated second classifier standing in front of
the certified one. Instrument lesson recorded: 100-review/game probes cannot
resolve mention rates under ~1% — tail pins are only visible at the n≈1,200–1,900
the census provides anyway.

---

## The codebook

**Hybrid with a fixed core** (decided 2026-07-09 on the week-1 probe's evidence,
`probes/FINDINGS.md` §6). Open extraction showed a flat, game-specific vocabulary —
top-15 grouped labels cover only 28% of mentions; half of all mentions are
single-game vocabulary — so a fixed set would flatten exactly the specificity the
product sells, while pure open stays dominated (normalization cost and a blurred
eval anchor). The shape: the vocabulary is a **versioned design-time artifact**
(human-gated, built offline); runtime extraction is **two-slot** — classify into
the pinned vocabulary or emit a free-form candidate; recurring candidates are
displayed as a **disclosed emergent stratum** (real numbers, honestly marked
uncalibrated); **promotion is offline and gated**, bumping the ontology version, so
every displayed number knows which vocabulary produced it. The v1 ratification
record — the pruning criterion, every per-aspect ruling, reopen conditions — is the
repo's `ONTOLOGY_PRUNING.md` (ratified 2026-07-15; 55 → 51 pins).

**The v2 wording batch** (ruled 2026-07-19 — the sanctioned reopen under
the labeler ruling's prompt-change condition). The gold ledger's routing rulings
postdate classify-v1's frozen wording, so the labeler had never seen the semantics
gold grades it against — and the survey pool is the durable asset every downstream
consumer folds, so it gets bought at aligned semantics. The distillation was one
shot by design (wording never iterated against gold F1): a triage pass over
the 33-ruling gold ledger settled what rides vs what stays gold-process-only,
landing in `src/steamlens/ontology/v2.toml` — same 51 pins, aliases byte-identical,
every example freshly constructed so no gold span reaches the machine's contract.

> **Outcome.** v2 vs the frozen v1 baseline on gold: precision **+0.066
> [+0.039, +0.098]** (real), recall −0.030 (borderline), F1 +0.020 — the honest
> sentence is *not-worse-and-leaning-better with a confirmed precision gain*. The
> mention-economy diagnostic explains the shape: the baseline over-mints, v2 lands
> on gold's economy — the ruling batch is precision-lifting deletion, working as
> designed. The N-peak reproduced under new wording. Captures:
> `probes/captures/bakeoff/deepseek-v4-flash-v2*/`.

**The compact rendering is closed.** The decision-surface-only render
(`classify-v1-compact`, a first-class versioned variant) was rejected for dispatch
at the v2 certification — confirmed recall loss, token savings immaterial under
prefix caching — and the census-scale experiment closed it: drift-clean, compact
measures **−0.018 F1 real vs full** (the judge-referenced same-day read, 2026-07-25).
It remains a versioned artifact; reopening requires new evidence, not new hope.

**The codebook-overfit disclosure** (ruled 2026-07-21). Gold was
blind-labeled before any model output — the safe direction — but the v2
distillation was tuned *on* gold's 250 reviews, so every v2-on-gold number is
**development-grade**: the instrument was refined against the set it is scored on.
Standing mitigation: a fresh human holdout (~100–150 reviews, random + stratified,
labeled under **frozen** v2 inside M1); hard cases feed v3 notes, never back-edits
to v2 — a back-edit would restart the contamination clock. Until the holdout lands,
every published v2-on-gold number carries the disclosure.

---

## The eval harness

**The scoring core is library code.** The gold-pairing metrics outlive any one
study — the bake-off, certification, and CI all score through
`src/steamlens/evals/` (imports anything, nothing imports it), while runners and
table generators stay `probes/` scripts. Both sides of every comparison resolve
pinned-vs-candidate through `core/normalize`'s surface index — one resolution
authority, so the scorer and the candidates can never disagree about what "pinned"
means.

**The certified object is the pool, not the configuration** (settled 2026-07-23).
The bake-off certified model + prompt + codebook on lab-composed batches; the
certification of record scores the bought envelopes themselves — the labels every
displayed number folds — against gold through the same frozen scorer. Scope rule:
gold predates the census scope and holds 5 out-of-scope reviews; certification
scores the 245-review intersection, with the narrowing stored on the run row, never
buried in prose — skipped, not counted as failures, which would fabricate a penalty
for reviews the model never saw.

**One journal, name-keyed metrics, a generalized reference** (settled 2026-07-23).
`eval_runs` holds the regenerability set — versions triple, ontology content hash,
reference id + sha256, counts, seed, resamples, scorer identity — and
`eval_metrics` holds name-keyed child rows, because the metric family grows: a new
metric is new rows, never a migration on minted runs. The reference is generalized
past gold: a `reference_kind` tag (closed contract enum: `gold-file`,
`pool-labels`) lets judge-vs-production agreement runs share the journal — every
run kind answers the same sentence, *this label set, scored against that pinned
reference, by this scorer*. The accepted cost, eyes open: one flat table quietly
holding a sum type. For pool-label references the pinning property survives by
digest over the canonically-serialized label set — same tamper-evidence as a file
hash.

> **Outcome.** The production census labels certify at **F1 0.766 [0.713–0.811]**
> against gold on the 245-review intersection (run
> `certify-20260728T184100Z-5f3f4652`, scorer `census-vs-gold/2`) — the number
> every M1 claim rides on. The −0.033 gap to the lab arm was chased to ground by
> the registered experiments below: buy-time variance, not batch composition.

**The fabricated-quote metric decomposes honestly** (settled 2026-07-23). The parse
already enforces the verbatim check at write time — bad quotes are nulled before
storage — so the stored pool holds zero fabricated quotes *by construction*, and the
metric splits into: the **invariant audit** (every stored span re-checked as a
verbatim substring of its review — **0 violations over 163,842 spans**: "zero,
verified," not "zero, assumed"), the **attempted-fabrication rate** (write-time
repair counts: ~2.9% of attempted quotes — the model-quality diagnostic the cleaned
pool can no longer show), and the standing spine caveat that verbatim passes a quote
read upside-down — misattribution stays the human audit. Audits stay out of the
eval-run journal (`eval_runs` means "scored against a measuring stick"; an audit has
none) and render as regenerable health reports; per-game health carries no
thresholds — inventing cutoffs before seeing the distribution tunes alarms to
nothing.

**The misattribution audit sample is minted, awaiting the human pass.** Unit: the
claim — one evidence-carrying mention in its review; metric: the share whose
verbatim-true quote is attached to the wrong aspect or an uncarried sentiment.
The draw is a seeded systematic pass over the sorted frame — implicit proportional
stratification, self-weighting, so the audited rate estimates the population rate
with no reweighting. 100 primary + 10 ordered reserves in
`eval/audits/misattribution/`; the rate+CI scorer builds after the audit.

**The numeric-grounding checker is deferred to its first consumer.** Its input
contract — what a numeric claim *is* — is undiscoverable until composed prose
exists (M3's composer at the earliest); building it now would freeze a guessed
seam. Recorded so the metric list stays honest: classification agreement
(journaled), fabricated-quote (decomposed above), numeric grounding (deferred, with
this reason).

**A statistic says "undefined", never 0.0** (ruled 2026-07-28). The scoring
core's empty-denominator convention (0.0, honest for a
reported point value with its `n` beside it) silently corrupts a bootstrap
distribution — an undefined resample contributes 0.0 as if it were measured
badness, dragging the interval's lower tail. The fix lives in the core's types:
ratios return `float | None`, F1 is None iff a component is (P=0 and R=0 both
*defined* still gives 0.0 — the correct measured-badness limit), the bootstrap
loops drop undefined draws on an unchanged RNG stream and **raise past a 1%
undefined share** — above the floor the slice is too sparse for the statistic and
the honest output is no number, not a wide one. A headline statistic undefined on
the full frame raises loud; an undefined slice statistic skips its row while its
`n` still journals ("no stat row" always means "nothing scoreable there").

**Evals-in-CI: a deterministic re-score pinned to the runs of record** (ruled
2026-07-26). The premise that shapes everything: CI produces no fresh model
output — re-scoring stored envelopes against pinned references under a fixed seed
is deterministic and free — so the gate catches *code/scorer/artifact* drift, never
model drift, which only enters at a label re-buy. Both runs of record regenerate in
CI from a committed, diffable JSONL fixture rebuilt through the real writer
surfaces, so CI's read path is production's. **Exact-digit mismatch fails; harness
errors fail; nothing merely annotates** — in a deterministic re-score a digit
mismatch is an unintended behavior change or an undeclared semantics change, and
both demand in-PR action. The escape hatch is the scorer-identity discipline: a
deliberate semantics change bumps the scorer string and re-exports the pins in the
same commit (exercised once: the undefined-statistics fix bumped all three
scorers to /2 and retired the exporter's relaxations). Byte-hashed artifacts are
held at LF by `.gitattributes` and the exporter refuses a CRLF working copy — a
platform-varying hash can never gate a
Linux checkout. **Tolerance bands exit CI entirely** and become the **re-buy
decision rule**: a recertification after any label re-buy reads against a band
floored at the measured ~0.03 buy-time variance — tighter would alarm on the
instrument's own noise. Trend stays M1-minimal: the journal *is* the trend store;
a rendered trend view waits for deployment, when re-buys become routine.

---

## The judge

**No gold-entangled model as an instrument** (ruled 2026-07-21). The gold ledger's
§8 ban on the gold-assist model extends to every instrument whose calibration rides
on gold: the assist model's reference row is *self-agreement* — it drafted what
gold was adjudicated from — so a same-family judge would inherit self-agreement as
apparent validity. The judge is also a different family from the labeler: a
labeler-family judge would import self-preference into the agreement metrics.

**A second annotator, not a verifier** (settled 2026-07-23). The judge never sees
production's answer: it labels the review fresh under the same frozen artifacts,
and agreement is computed mechanically afterwards.
Verifier-shaped judging was rejected — showing the prediction anchors the judge
toward endorsing it, leniency in exactly the direction a self-certification can't
afford. The re-labeler also makes infrastructure reuse total: a judge run is an
envelope set under its own versions triple, so calibration and the census-sample
read are the existing scorer pointed at different pairs. Riders: **single-review
dispatch, temperature 0** — the instrument must not inherit a variable it exists to
measure. Standing caveat: two models can share blind spots, so agreement is an
optimistic bound — mitigated by the cross-family pick, backstopped by the human
holdout.

**The calibration rule was pre-registered** so the number can't be rationalized
after the fact — the paired Δ(judge − production) on shared gold:

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
over the mutually-labeled intersection and refusal counts disclosed — an instrument
that declines to read didn't read wrong.

**The build amendments** (2026-07-23). The generic
"Gemini flash" resolved to `gemini-3-flash-preview` on assembled evidence — the only
flash candidate consistently above production's certified F1, where a weaker judge
near-guarantees a demoted instrument — with two caveats recorded: selection optimism
(the same gold measures the pick and the calibration) and preview-id retirement risk,
mitigated by running calibration and the census sample close together. Routing is
direct Gemini API for instrument continuity with the bake-off's measured
generation config. Gold's out-of-scope reviews are **backfilled honestly** (true
metadata from corpus files, never fabricated rows, scoped out of every labeling
run's selection); a **text handshake** guards instrument identity — an envelope must
never claim text the judge never read.

> **Outcome.** Calibration **PASS** (2026-07-23): judge F1 0.816 vs gold, paired
> Δ **+0.050 [+0.019, +0.083]** over production on the shared reviews — census-
> sample verdicts are reference-grade; frontier escalation moot. Instrument caveats
> on record: the preview id survived a load-shedding capacity event and has a named
> successor, so a re-run may need recalibration; the Batch API cost lever carries a
> stuck-jobs strike.

**The census-sample read: reviews, n=1,000, sync** (ruled + built 2026-07-23). The
frame is reviews, not mentions — the judge's unit of work is a review, and a
mention frame would overweight multi-mention reviews with no clean review-level
interpretation; zero-mention reviews stay in ("both instruments say no aspects" is
agreement worth measuring). n=1,000 roughly halves gold's interval; the Batch API's
50% saving doesn't pay for its job-submit/poll/download build at this scale. The
sample pins text by sha256, not by copy — the dispatch refuses a store whose text no
longer hashes to its pin. Everything instrument-defining lives once in a shared
dispatch engine consumed by two thin shells (gold calibration, census sample), so
the two runs cannot drift apart.

> **Outcome.** Judge-vs-production agreement **F1 0.791 [0.772–0.810]** on
> 1,000/1,000 (run of record `agree-20260728T184121Z-7c975c95`, scorer
> `judge-vs-production/2`) — between production-vs-gold 0.766 and judge-vs-gold
> 0.816, so no quality cliff outside gold. Per-aspect agreement rows journaled with
> CIs at a judge-n floor of 30; the top-disagreement exemplars seed the human
> adjudication sheet (open: decides whether `updates` 0.611 is production
> under-detecting or the judge over-finding).

**The registered experiments closed the census-vs-lab gap** (designed, executed,
and self-refuted 2026-07-25). Two arms rode existing references — the judge never
ran again, gold is gold: a contamination isolation (production's model at N=1
against both references, plus a registered contingent that fired) and a compact-
codebook 2×2. Experiment envelopes stay in the pool with the batch condition tagged
into `model_version` (`@n1`/`@n10`) — two label sets expected to differ must not
share an identity, and the tag buys containment (production folds filter the
untagged triple) plus verbatim scorer reuse.

> **Outcome.** **Batch composition is acquitted**: every same-day composition
> comparison is null, every cross-day comparison shows a ~0.02–0.03 gap including
> with composition held fixed — the census-vs-lab −0.033 is **buy-time variance of
> the served model** (non-monotone timeline at temperature 0 throughout).
> Consequences: the N=10 batching lever is vindicated; the compact codebook is
> closed on measured evidence; **any cross-day label comparison carries a buy-time
> rider, and re-certification after a re-buy is not optional**; production's 0.766
> stands — it certifies the labels actually bought. Named residue, eyes open: the
> recomposed cell's same-game premise was measured false after the buy (corrected
> 2026-07-27), so recomposed-vs-census interpretations carry a neighbor-structure
> confound; the census's true mixed-game structure is untested. Readings regenerate
> via `probes/d2d_reads.py`.

**The self-grading 2×2 is closed unexecuted (2026-07-30).** Under a re-labeler
judge, "the labeler judging its own labels" survived only as a verifier-shaped
bias demonstration — each model verifying its own and the other's gold labels,
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
openly: the verify-then-explain differentiator goes dormant — deferred, not
deleted. Blast radius verified small: nothing built depends on investigation
machinery; the exposure is docs + product story.

**The two-track rule survives translated.** Every displayed number still comes from
the survey mint alone; stories now come from grounded retrieval — the chat quotes
retrieved reviews and never mints numbers, retrieval counts in provenance stamps
are process disclosure rather than statistics, and non-survey envelopes are
excluded from the mint by construction (the same origin-tag wall the import-graph
test guards). Roadmap shape: the chat is **the new M4**, sequenced after the
sampling study (M2) and deployment (M3) — M3 ships a URL sooner, and the chat's
offline prototype + eval can run against the 49-game census before deployment
exists, so the eval story is never hostage to M3. `core/detect` survives as
**display-only episode markers** built at M3: pure statistics over the
all-language histogram, no explainer. The M1 post tells the redirect straight — a
measured scope call on stated grounds, not a retreat.

**Type a game name, get the report — then interrogate it** (product frame ruled
2026-07-27; architecture rules at the M4 design session). The report stays the
product; the chat is its **interrogation channel** inside the report page — never
chat-first, never a standalone surface. It interrogates *this report's evidence
base*, so chat coverage equals report coverage by construction. The design fitness
test: every downstream choice must serve at least one of the three claims a stock
RAG app cannot make, or it is commodity weight —

1. **retrieval over self-labeled structure** — "why do people hate the grind?"
   resolves to aspect ∧ sentiment ∧ game ∧ window filters before any embedding
   runs, with a measured classifier (published F1 + CI) as the index;
2. **RAG evals on the already-calibrated judge**;
3. **a chat that structurally cannot fabricate statistics**.

**Question scope.** In: aspect why/what (the core), sub-ontology drill-down (the
one place semantic search earns its keep), time-scoped questions, and number
questions answered as **mint citations**. Refused: advice and speculation
("should I buy it?"), honestly and specifically. Out entirely: cross-game
comparison — it breaks the per-report frame, which is the product's identity
rather than a v1 limitation.

**The answer contract: claims with receipts.** Short prose composed only over what
was retrieved; each claim pinned to verbatim quotes passed through the
fabricated-quote verifier before display (a claim whose quote does not verify is
dropped, never shown); numbers appear only as visually distinct mint citations,
never phrased by the model; every answer carries a one-line provenance stamp; and
answers walk a three-state ladder — grounded answer → **thin-evidence answer,
named as such** → honest refusal. **No free-composition mode**: the moment one
answer type may speak without receipts, the differentiator is gone.

**Leanings recorded for the M4 design session** (leanings, not rulings): a
background chat pool beyond the survey (~5k, plain most-recent order, disclosed;
never targeted — a steered fill is the investigation track reborn) with
progressive labeling over a raw tier; **a small local pinned embedder** — pinned
weights make the index immortal where an API embedder's retirement orphans every
stored vector, and a 5k pool is ~8 MB of vectors, so brute-force cosine beside
SQLite, no vector DB; **no RAG framework** — the chat is a pipeline, not a graph,
and a framework layer would hide exactly the visible engineering the portfolio
exists to show (LangGraph is named as the tool for the next complexity tier,
adopted when a real loop appears, not before). The session's docket: pool tiering ·
embedder choice · retrieval mechanics · eval design on the judge machinery ·
cost caps · the composition prompt · the `Review` reception-metadata deferral
reopened as a retrieval signal.

---

## The sampling study (M2) — the study design

*(Ruled 2026-08-02. The design session's output: how the study runs and what gates
its answers. The values themselves — the winning policy, the tolerance, the size
rule, the floor — are the study's output, landed at the checkpoints below.)*

**The convergence target: two gates, per displayed aspect.** A sample size is
acceptable when, against the full-census fold as reference, (1) every per-aspect
share the report would display lands within tolerance of the census share, and
(2) the quoted interval covers the census value at its nominal rate — the error
bar keeps its promise. Share error is what the displayed number claims; interval
calibration is the product's actual thesis (honest error bars), and a policy can
pass one while failing the other. Rank stability of the top aspects and
praise/criticism direction are measured and reported but never gate — both follow
from shares being right, so gating them adds criteria without information. The
tolerance applies per share band and is certified at the **95% register** — 95%
of population cells within tolerance (refined at the curves checkpoint,
2026-08-02: deterministic draws offer no per-cell guarantee to certify, and the
95% register puts both gates in one probability language, the same one the
interval quotes). The display evidence floor still excludes the sparse tail
before any promise applies.

**Four raced policies; two diagnostic axes.** Raced: **uniform random** (not
runtime-expressible — the textbook reference every other policy is judged
against, free to simulate against a held corpus); **time-proportional windowed**
(budget spread across date windows by review volume — the runtime primary path's
hypothesis, approximating uniform random through windowed fetches);
**equal-per-window** (over-represents quiet periods; likely rejected, and then
the rejection carries numbers); **cursor-prefix** (the documented fallback as it
actually behaves — a most-recent prefix, biased by construction; its measured
bias becomes the trust-panel disclosure quoted whenever a report runs on the
fallback path). Playtime and vote-type are *representativeness diagnostics* on
the winner, not raced candidates: time is the axis the windowed path natively
speaks, and runtime expressibility of the other axes is unverified against the
probes' recorded parameter surface.

**Curves first; the deliverable is a size rule.** The size ladder densifies at
the low end (100 / 250 / 500 / 750 / 1000 / 1500 / 2000 / 3000 / 5000), a few
hundred independent draws per game × policy × size — resampling stored labels is
CPU-only, so density costs minutes. Tolerance and size are picked at a **review
checkpoint over the real curves**, not fixed in advance: the tolerance is a
product decision (promise strength vs. per-report fetch+classify cost) better
made looking at reachable tradeoffs than guessed blind. The deliverable is a
rule, not a number — games vary by orders of magnitude, so: take-all below a
population cutoff, sample n by the winning policy above it; the curves locate
the cutoff.

**Interval methods race inside the same simulation.** The candidate formulas —
design-naive binomial, design-aware stratified, bootstrap-over-reviews — are all
computed on every simulated draw, and the calibration gate is itself the test:
ship the *simplest* method whose coverage is honest under the winning policy.
Simplicity is the tiebreak because the formula ships in production; the fancier
method earns its place only when the simple one's coverage measurably fails.
Constraint carried from the eval harness: resampling intervals draw whole
reviews, never mentions — mentions within one review move together, and
treating them as independent fakes precision.

**Long-tail transfer: staged evidence, ending in a held-out test.** The corpus
is ~50 popular games in a recent window; the deployed app will be pointed at
anything. Three stages: (1) **within-corpus splits** — convergence results split
by game shape (population, temporal spikiness, aspect concentration); if curves
vary with shape, the size rule conditions on it, and the transfer risk is
measured rather than suspected; (2) **label-free frame checks** — fresh
histograms for genuinely long-tail games through the existing sampler, no LLM
spend, testing whether their temporal structures fall inside the range the
corpus spans; (3) a **committed closing test** — ~3 long-tail games labeled
fully under the frozen versions once the size rule exists, validating the
finished rule off-corpus rather than arguing transfer. Fresh buys carry the
buy-time re-certification rider (the D2d ruling).

**The marked-share floor tunes by mixing experiment.** The corpus holds zero
marked-window reviews, so this is the study's one path off stored labels: fetch
marked windows fresh from 2–3 documented-bomb games through `steam_client`'s
windowed path (the wire-level caveat parked in the probes' findings gets its
check here), label ~1–2k marked-window reviews under the frozen versions, then
blend them into normal samples at increasing shares offline. The floor is the
marked share at which a sample's conclusions drift beyond **the same tolerance
the curves checkpoint set** — one honesty standard end to end, replacing a
guessed percentage. Sequencing falls out: the mixing experiment runs after the
tolerance ruling and shares one fetch-and-label session with the long-tail
closing test.

**The human holdout folds into M2; the rest of the human track stays parallel.**
The census reference is machine-labeled — the study measures *sampling* error
while the classifier's own error rides silently on top. The fresh human holdout
(~100–150 reviews under frozen v2) is drawn as an M2 step, scoped across corpus
material *and* the fresh buys — marked-window and long-tail reviews are
out-of-distribution against gold's popular-game 250, exactly where the
classifier is newly trusted — and its number lands in the report's limitations
as the measured bound on the reference's imperfection. The misattribution audit,
self-relabel subset, and judge-disagreement adjudication stay the parallel
human-time track, not gating M2.

**The replication unit: query anchors × games × aspects** *(ruled 2026-08-02,
the step-4 design pass — settling the question the build flagged)*. Windowed
draws are fully deterministic — same corpus, same plan, same sample, true of
the live runtime too — so repeat-variance exists only for the uniform
reference, and error distributions and coverage rates need a population of
report runs to be statements about. The certified population is the composed
one: **query anchors** (each game's corpus truncated at fixed quantiles of its
own review-time span — 40/55/70/85/100%, never an absolute calendar grid that
would predate thin-coverage games; compiling from the truncated histogram
reproduces exactly what a live query at that moment would have seen) ×
**games** × **displayed aspects**. This makes the checkpoint's rulings claims
about report runs generally rather than one snapshot date, and makes the
committed closing test a genuine held-out draw from the certified population —
a fresh game queried at a fresh time. Two disclosures ride the report, not the
code: anchors within one game are nested (later corpora contain earlier ones),
widening the population without being independent replications; and truncating
today's corpus at T assumes Steam would have served the same rows at T —
edits and deletions make that an approximation only the live tests ground.
Sweep hygiene falls out of the ruling: an anchor whose truncated pool
duplicates an earlier anchor's is dropped (truncation is monotone — equal size
is the identical pool, and re-measuring adds correlated copies), and a cell
whose ladder size reaches its pool is recorded take-all and skipped — a
take-all draw's zero error is free flattery for a convergence curve.

**The curves checkpoint — the study's values, ruled 2026-08-02** *(over run of
record `m2sweep-20260802T132010Z-2969bcab`: 49 games · 243 anchor pools ·
255,744 cells; every figure and constant regenerable from the run)*.

- **Policy: time-proportional windowed is the primary path.** It dominated the
  other implementable draws on every slice — pooled p90 error, per-band error,
  and Wilson coverage at every n. Equal-per-window is eliminated: its
  quiet-month over-weighting never paid for itself anywhere. Cursor-prefix
  keeps its designed fallback role; the sweep's signed-bias view showed **no
  net direction for any policy** — misses are symmetric spread — so the
  fallback's trust-panel disclosure is a spread statement, not a drift
  correction.
- **The big-share finding, and pricing it rather than fixing it.** The windowed
  penalty concentrates almost entirely in **≥15%-share aspects**: p90 error
  7–11 points, bias-dominated — a newest-first prefix's bias does not shrink
  like √n, so the error curves run flat from n=100 to ~1500 and collapse only
  when growing quotas swallow whole windows. In that band every interval
  method under-covers, *worse as n grows* (Wilson ~88% at n=100 falling to
  ~75–78% by 1500–2000): the width shrinks like 1/√n while the bias stays
  put. The ruling follows the study's own thesis — price the pretense: the
  shipped interval carries a measured bias allowance and the tolerance
  conditions on share band. **Larger n is rejected** as an answer (the curves
  are flat in n; the cost is linear). **The micro-window variant is parked** —
  the one candidate that attacks the cause rather than repricing it, but it
  carries an unsolved compiler question (windows mint from monthly rollups;
  finer grain needs the deliberately-unused daily strips or a within-window
  multi-cursor draw) and an unknown payoff without a re-sweep. Reopen
  triggers: the closing test failing held-out, or the deployment milestone
  (M3) finding the headline widths product-unacceptable.
- **Interval method: Wilson plus a per-band constant allowance.** Bootstrap is
  eliminated — the percentile interval collapses to lattice points at small
  n·p̂ (measured ~60% coverage at n=100). Stratified-with-FPC is eliminated —
  its within-window-SRS pretense is exactly what the prefix draw violates
  (bias-centered intervals, and quota-1 windows reporting zero variance).
  Form: one constant per share band added to Wilson's half-width on sampled
  draws; **take-all pools quote the exact number and no sampling interval** —
  a swallowed pool is a census of itself. Constants pin at the shipped n,
  smoothed conservatively against order-statistic noise (the max of the
  flat-inflation calibration over the shipped tier and its neighbors): **tail
  0.000 · mid 0.005 · headline 0.073** — a headline aspect displays at roughly
  ±10 points. The constants are self-calibrated on the study corpus; the
  closing test is their held-out check, and they re-derive from the run of
  record, never hand-carried. The fallback path, where its numbers quote an
  interval, calibrates its own (larger) allowance from the same rows'
  cursor-prefix column.
- **Tolerance, band-conditioned at the 95% register:** tail (<5% census share)
  **±1 point** · mid (5–15%) **±2.5 points** · headline (≥15%) carries **no
  separate error tolerance** — its promise is the calibrated interval plus
  take-all exactness; a tolerance number there would either restate the
  interval width or claim a precision the windowed draw cannot deliver.
- **Size rule: take all at pool ≤ 2,000; otherwise sample n = 1,000
  time-proportional.** n=1,000 sits one tier above the smallest
  tolerance-passing size (750 passes the mid band at 2.3 vs 2.5 — no margin
  against off-corpus drift) and returns flatten beyond it (1,500 buys 0.2
  points for 50% more cost). The cutoff takes the 2×n shape: below it,
  sampling saves less than half the fetch+classify cost, so exactness —
  including headline exactness — is nearly free; above it, per-report cost
  caps at 2,000 fetched+classified reviews (the thesis made concrete: at most
  2k reviews per report, not 250k). Pool size otherwise doesn't condition the
  rule — the pool-size slice showed convergence rides absolute n, not
  sampling fraction. At pools just over the cutoff, Wilson's missing FPC errs
  conservative — over-covers, never under.

**The long-tail stage-1 splits — the regime refinement, ruled 2026-08-03**
*(over the same run of record; the splits, threshold sweep, and constants
regenerable via ``scripts/split_sweep_by_shape.py`` and
``scripts/mint_allowances.py``)*.

- **The finding: the windowed penalty lives entirely in temporal
  spikiness.** Convergence split by game shape at the (game, anchor) grain —
  population, peak window share, headline-aspect count — showed all three
  axes breaking the ruled tolerances in their top groups, but conditioning
  untangles it: with spiky pools set aside, no band at any pool size needs
  any allowance (constants 0.000 across pool terciles), while spiky pools
  need roughly double the flat price. The checkpoint's flat constants were
  an average of two regimes — over-covering calm pools (~100% measured
  coverage, ±10-point headline bars where Wilson alone suffices) and
  under-covering spiky ones (~87% at the shipped n) — the same dishonesty
  the checkpoint refused, one level down.
- **The ruling: the allowance conditions on the spikiness regime.** Boundary:
  peak window share at or above **2/3** — the pool share of the busiest
  histogram bucket, computable from the live histogram before any draw, so
  the conditioning adds no data dependency. Ruled over a threshold sweep:
  calm constants sit at zero for every candidate cut from 0.50 to 0.75, so
  only the spiky side's calibration hinged on the choice, and 2/3 puts the
  full measured price on the units that measured it (0.50 would dilute the
  spiky calibration with borderline units that need nothing). The
  regime-conditioned constants supersede the flat ones (kept above as the
  checkpoint's record): primary path calm **0.000 / 0.000 / 0.000** and
  spiky **0.000 / 0.017 / 0.127** — calm headline ships at roughly ±2.5
  points, spiky headline at roughly ±15; fallback path calm
  **0.000 / 0.004 / 0.065** and spiky **0.000 / 0.022 / 0.130** — the
  cursor path's newest-first bias needs no spike, so even its calm regime
  carries real allowances, and its disclosure stays regime-aware.
- **Spiky mid joins the headline treatment.** In the spiky regime, mid
  aspects carry no separate error tolerance — spiky-mid p95 error (~3.5
  points) breaks ±2.5 regardless of the interval quoted, and a tolerance
  minted to fit would restate the interval — the same reasoning that left
  headline tolerance-free at the checkpoint. Calm mid keeps ±2.5 points,
  tail keeps ±1 point everywhere; the tolerance table is regime-aware in
  exactly one cell.
- **Caveats carried to the report, not the code.** The spiky calibration
  rests on thin cells (48 headline cells at the shipped tier; the smoothing
  max is the deliberate conservatism), and the constants remain
  self-calibrated on-corpus — the closing test and the fresh buys are the
  held-out check of the *conditioned* constants now. Stage 2's label-free
  frame checks gain a sharper question than they were designed with:
  whether genuinely long-tail games land in the spiky regime at all — the
  off-corpus regime distribution is the transfer risk that remains.

**The long-tail stage-2 frame checks — the off-corpus regime distribution,
measured and ruled passed 2026-08-03** *(over discovery run
``longtail-20260802T232206Z-9bf61718``: 24 games admitted from 959
seeded-uniform probes of a 177,272-game catalogue snapshot; every table and
figure regenerable via ``scripts/discover_longtail_games.py`` and
``scripts/frame_check_longtail.py``)*.

- **The list nobody picked.** Discovery is criteria-driven by construction —
  the selection-bias critique is answered before it is raised. Three
  review-count bands on the whole-game, all-language totals read, edges
  aligned to the ruled take-all cutoff so each band asks a distinct question:
  the true tail at 200–2,000 (production fetches these whole — 6 games), the
  engaging band strictly above 2,000 through 20,000 (the only place the size
  rule actually samples — 14 games), and a bridge at 20,000–60,000 toward
  corpus scale (4 games). Candidates were drawn by seeded uniform probing of
  a persisted games-only catalogue snapshot, admitted exactly when the store
  called them a game and the totals landed in an open band; seed, snapshot,
  and probe order are all recorded, so the list re-draws. (The frame itself
  is the keyed ``IStoreService`` catalogue — Valve retired the keyless
  applist endpoint in March 2026; the key crosses only the process
  environment.) The probe log doubles as an unbiased catalogue sample, kept
  with the run.
- **The regime answer: the long tail is calm territory.** One game in 24 is
  spiky on the production instrument (peak window share ≥ 2/3 over the live
  histogram's native buckets); 5 of 120 (game, anchor) units — 4.2%, against
  the corpus's 33.1%. No band is spiky-heavy (true tail 0%, engaging 7.1%,
  bridge 0%). Deployed against the long tail, the runtime will overwhelmingly
  quote the calm constants — Wilson-only intervals — with the spiky treatment
  reserved for the rare whole-life-event game the boundary exists for. Fresh
  peak shares (0.022–0.813) sit entirely inside corpus support (0.036–1.000):
  the conditioning never extrapolates. Fresh whole-life pools exceed corpus
  pool support on the high side (to 63k against 6.9k) — a report disclosure,
  not a gap, pool size being the axis stage 1 cleared of any conditioning.
- **The span effect — what the corpus regime rate actually measured.** The
  instrument-agreement handful (five corpus games, live histograms fetched
  alongside the fresh ones) shows the two instruments agreeing decently over
  the same month range, while the same games' whole-life histograms read far
  flatter (0.503 → 0.042; 0.415 → 0.059). The corpus's 33% spiky rate is
  therefore largely a property of *windowed pools*, not of popular games:
  the calibration measured the penalty mechanism — one window swallowing the
  draw's quota — on recent-window pools, and production, reading whole-life
  histograms, will meet that shape mainly in games whose whole life is one
  event. The spiky constants stay as ruled (the mechanism transfers by
  shape, not by span); the closing test remains the held-out check that the
  calm-regime promise holds off-corpus.
- **The instrument disclosure.** Steam serves weekly rollup buckets for some
  games (5 of the 24) and monthly for the rest; weekly-native readings sit at
  or below their month-rolled counterparts, and no admitted game flips across
  the 2/3 boundary by unit choice. The regime is computed on the native
  buckets deliberately: the windowed compiler plans one window per native
  bucket, so the native series is the shape the draw actually experiences.
- **Carried to the fresh-buy session (step 8):** the ~3 long-tail games
  labeled fully should span the regimes this check surfaced — the one spiky
  admit (Sword and Fairy Inn 2, whose 36 English reviews of 2,277 also
  exercise the language question), one weekly-unit young game, one flat
  mid-band game.

**The fresh-buy session (step 8) — selections and design, ruled 2026-08-03**
*(the one shared fetch-and-label pass serving the mixing experiment, the
closing test, and the human holdout; bomb candidates nominated by web
research, verified only by the wire-level probe below — nomination is not
evidence)*.

- **The bomb games: Borderlands 2, Book of Demons, The Witcher 3.** Chosen to
  spread the marked-window population three ways: the canonical first-ever
  off-topic mark (Borderlands 2 — the April 2019 Epic-exclusivity bomb, a
  tight ~2-week window, 7,030 reviews on the wire), a small-volume ongoing
  mark (Book of Demons — the March 2022 regional-pricing bomb; `end_date=0`
  on the wire, 2,349 reviews to date), and a second tight window with a low
  English share (The Witcher 3 — March 3–17 2022; the researched "9-month
  span" was corrected to 14 days by the probe, finding 6).
  Cyberpunk 2077 was excluded on corpus overlap: fresh material stays
  disjoint from the 49 corpus games. Alternates on record if a pick fails
  the probe: IL-2 Sturmovik (a ~25-month window), Slay the Spire 2 (the 2026
  mega-bomb; mark dates unverified).
- **The long-tail games: Sword and Fairy Inn 2, Dragonkin: The Banished,
  Talisman: Digital Classic Edition** — the stage-2 leaning made concrete
  from the discovery run's admitted list: the one spiky admit (peak 0.756,
  the language case), the youngest weekly-served admit (Mar 2026, 1,312
  English; native 0.166 vs month-rolled 0.383 exercises the unit disclosure
  live), and the flattest mid-band admit with real English headroom (6,108
  English, peak 0.033).
- **The mid-band criterion rides the English pool, not the total.** The size
  rule samples only above the 2,000-review take-all cutoff, and the
  labelable pool is English — a pick whose English subset falls under the
  cutoff would quietly turn the closing test into three take-all games and
  validate nothing.
- **English-only stands everywhere, including the 36-of-2,277 game.** The
  classifier's certified contract and the codebook are English; production
  faces the same 36-review reality for that game, and take-all over a tiny
  English pool *is* the honest production behavior. Labeling non-English
  would test an instrument never certified.
- **The probe gates the buy — pick verification, not mechanism.** The
  blank/restore mechanism is already proven (the M0/M1 probe findings:
  default listings blank marked windows, `filter_offtopic_activity=0`
  restores them, verified locally and from a datacenter; every future fetch
  carries the flag). What no probe has done is verify the *picks*: that
  each bomb game's `past_events` mark exists with usable window dates, and
  that the in-window **English** pool — the only labelable material — is
  large enough to feed the mixing experiment. A bomb pick failing either
  check is replaced from the alternates, not forced.
- **The holdout: 150 reviews, 60 corpus / 45 marked-window / 45 long-tail.**
  Seeded stratified draw with the fresh material deliberately oversampled
  relative to volume — out-of-distribution against gold's popular-game 250
  is exactly where the reference is newly trusted. Labeled blind to machine
  labels under frozen codebook v2 (the misattribution-sheet precedent);
  scored as review-level agreement against production labels (the judge's
  frame — reviews, not mentions) with a Wilson interval; the number lands in
  the report's limitations as the measured bound on the reference's
  imperfection. Overall agreement reads at roughly ±6 points, per-stratum at
  roughly ±12 — coarse but honest.
- **The cost frame, priced per the standing rule.** At the census rate
  ($3.80 for 135,260 reviews, ~$0.03 per thousand) the whole session —
  ~1–2k marked-window reviews, three long-tail English pools, the gold
  re-certification run — prices well under a dollar. The Batch API option
  is priced and declined: 50% of cents does not pay for the
  job-submit/poll/download path (the recorded n=1,000 reasoning, one scale
  smaller). The D2d rider is binding: a fresh certification run against
  gold under the frozen triple accompanies the buy — the census's 0.766
  certifies only the census's labels, never these.
- **Containment and the re-cert instrument (ruled 2026-08-03).** The fresh
  labels land in **their own store** (`labels.sqlite3` inside the fetch
  run's directory), never the production pool — containment by storage, so
  the parked `Origin.EVAL` trigger's condition (non-census labels in the
  production pool) never arises, and the census driver runs unchanged
  (`--corpus` at the fetch run, `--expect-supply` 13,887 — the fresh usable
  count through the corpus reader). The re-certification is a registered
  D2d cell, `full-n10-gold-recert-freshbuy`: the recomposed scope
  re-dispatched under its own identity tag (a same-tag re-run would resume,
  not re-buy) with a **fresh fillers seed** — the first attempt reused
  July's seed for exact-composition comparability and the content-keyed
  cache replayed the July responses at $0 (identical composition IS
  identical request content; the replayed envelopes were deleted). The
  instrument stays comparable the honest way: same scope, fresh draw, with
  the composition acquittal pricing the difference at null. Two runs of one
  instrument remain a two-point drift series. Scored against gold by the certify
  shell pointed at the tagged annotator; the number is the fresh buy's
  buy-time certificate and lands in the M2 report's limitations beside the
  reference-imperfection bound.

> **Outcome.** The pick probe **PASSED** all three bomb games (2026-08-03,
> finding 6): every mark exists, every window blanks by default and restores
> under the flag, sample timestamps all in-window. Combined in-window English
> pool **6,454** (4,085 / 823 / 1,546) against the mixing appetite of ~1–2k —
> the buy is not supply-constrained. Wire truth corrected two research claims
> (The Witcher 3's span is 14 days; Book of Demons' mark is ongoing), and the
> ongoing mark needs a concrete end date substituted at fetch time.

**The mixing experiment (step 9) — design, ruled 2026-08-04** *(the
floor-tuning procedure made concrete; the procedure's charter is in the
study-design section above, and the floor value itself lands at this
experiment's checkpoint)*.

- **The drifted number measures against the census share — the study's exact
  gates, re-run with contamination.** The displayed number's promise is
  tolerance-of-truth, so the floor is the last marked share at which the
  certified 95%-register promise still holds: same regime-aware tolerance
  table, same coverage gate, same pass/fail machinery. Measuring drift
  against the unmixed sample's own conclusion was considered and declined —
  it isolates the marginal contamination effect, but applies the tolerance
  to a quantity it was never minted for.
- **Replacement at fixed n.** A mixed draw keeps the ruled sample size: the
  certified plan draws the full n, then a seeded random subset of
  round(s·n) members is swapped for marked-window reviews. Contamination is
  the same-size sample a report would take with a fraction of it being bomb
  material; addition would grow the sample and entangle two effects. The
  share grid densifies at the low end, mirroring the size ladder:
  0 / 2 / 5 / 10 / 15 / 20 / 30 / 50%.
- **Three curves, one per bomb game; the floor reads from the worst.** The
  marks were picked to spread the marked-window population (the canonical
  tight window / a small ongoing mark / a low-English tight window); pooling
  would average away exactly that spread, and per-source curves tell the
  report which bomb flavor bites first.
- **Base cells reuse the certified population grid** (query anchors × corpus
  games) with the same seeded-draw discipline as the curves sweep. Blending
  is offline resampling of stored labels — CPU-only, zero LLM spend; the
  marked labels come from the fresh-buy run's own store, read through the
  same corpus reader the re-certification used.

**The M2 report.** A standalone frozen PDF (the per-milestone precedent):
the question · method (census as ground truth, the raced policies, the two
gates, seeds) · the curves as centerpiece · the rulings that fell out (policy,
tolerance, size rule, interval method with measured coverage) · the fallback's
disclosed bias · the long-tail evidence and closing test · the mixing curves
and the floor · limitations stated plainly (popular-games corpus, English-only,
buy-time variance, the reference-imperfection bound) · provenance, every figure
regenerable. No artifact references REPORT_NOTES.md.

---

## Standing rules

**The post ships with the milestone.** Every milestone's public artifact ships when
the milestone does, imperfect — shipping deliberately outranks polish.

**The ops story is a deliverable, not plumbing** (2026-07-08). Two-sided stance: no
infrastructure without a driving product need (the Kubernetes/Terraform tombstone
stands), but no skipping an ops opportunity the product genuinely justifies —
DevOps/MLOps depth is a deliberate portfolio pillar here. What the product already
justifies, made visible instead of silent: evals-in-CI, observability surfaced in a
small ops dashboard, versioned provenance on every artifact, and a deploy pipeline
as code. The test for any addition stays: does *this product* need it?

---

## Scope & non-goals

- In: aspect reports with receipts, narrated live analysis, the report-interrogation
  RAG chat, display-only episode markers on the timeline, the trust panel,
  Docker/FastAPI/SQLite/CI deployment, the evaluation methodology as a public
  artifact, the ops story as a public artifact.
- Deliberately out: fake-review verdicts (tombstoned under Data access) ·
  multilingual evaluation claims (post-launch experiment, unverified if shipped) ·
  Kubernetes/Terraform/cloud MLOps (zero marginal signal for a portfolio app) ·
  cross-game chat comparison (the product frame's identity, not a v1 limitation) ·
  the agentic investigator (deferred 2026-07-27, the redirect above) · any displayed
  number sourced from outside the survey mint (the old investigation-track wall, now
  also covering the chat pool).

## Open questions / deferred

- **Cache persistence on an ephemeral host** — decided in the deployment
  milestone's (M3) design (bake-into-image / dataset sync / paid storage).
- **LLM tier for the remaining stages** — per stage, at each stage's design point
  (the tier rule above). The survey-labeling stage is decided (the labeler ruling);
  the phrasing/composition stage and the chat's stages decide at M3/M4. The judge
  stays exempt: always a stronger model than the one it grades.
- **Hosting shape** — decided at deployment (M3). The free-host premise fell
  2026-07-09 (compute Spaces are PRO-gated), so hosting costs money on either fork
  and a cheap VPS is the cheaper option as well as the stronger DevOps signal; a
  provider direction exists and is re-decided at M3 entry, gated on a
  reachability probe from the actual host.
- **Runtime sampling policy, sizes, and the interval method for displayed
  shares** — RESOLVED at the M2 curves checkpoint (2026-08-02, rulings in the
  study-design section above): time-proportional primary · take-all at pool
  ≤ 2,000, else n = 1,000 · Wilson + per-band constant bias allowance ·
  band-conditioned tolerance at the 95% register. Refined at the long-tail
  stage-1 splits (2026-08-03, same section): the allowance and the mid
  tolerance condition on the spikiness regime (peak window share ≥ 2/3).
  The stage-2 frame checks passed 2026-08-03 (same section): the long tail
  is calm territory, the conditioning never extrapolates. Still ahead of
  the study: the mixing floor and the closing test that validates the rule
  held-out.
- **Marked-share floor threshold** — tuning procedure ruled (the mixing
  experiment, study-design section above); the value lands after the curves
  checkpoint sets the tolerance it measures against.
- **The human annotation track** — re-timed at the M2 design session
  (2026-08-02): the fresh v2 holdout folds into M2 (drawn across corpus + the
  fresh buys; its number bounds the reference's imperfection in the M2 report).
  Parallel, not gating: the self-relabel consistency subset · the
  misattribution audit sheet (minted, awaiting the pass) · judge-disagreement
  adjudication (sheet seeded from the top-disagreement exemplars).
