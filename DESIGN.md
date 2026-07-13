# DESIGN — steam-lens

What is being built and why — the decisions and their reasoning, as a narrative
snapshot of the current design, edited in place as decisions evolve. **This document is
the living source of truth for decisions from the vision phase onward**; `VISION.md` is
the fixed vision-phase snapshot (2026-07-07) and is not updated as the design moves.
How it's built → ARCHITECTURE; the pitch → README.

*Snapshot of the design as of the system-flow settlement · last updated 2026-07-09 ·
system flow settled via the second design panel (4 blind proposals × 4 adversarial
critics); the module map lives in ARCHITECTURE.md.*

## Objective

An app where entering a game returns what players actually like and dislike — aspect-
level strengths/weaknesses with verbatim evidence, plus detected-and-explained events in
the review timeline — computed live at request time on real Steam data, with a rigorous,
honest evaluation of whether the LLM doing the reading is actually right. **Success
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
Adversarial inputs (prompt-injection strings among the eval canaries) are in the harness
from the start: the product's entire input is attacker-controlled text.

**Evals gate softly.** The harness runs in CI on prompt/model changes with tolerance
bands and trend reporting; a hard build-fail on a noisy LLM metric was rejected because
a red-X-then-override history is worse than no gate.

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

## The system flow — module boundaries, seams, contracts (settled 2026-07-09)

Settled through the second design panel: four blind proposals (simplicity / contract /
risk / practitioner-canon framings), four adversarial critics, synthesis arbitrated by
Arda; raw material in the private panel archive. The decisions and their reasoning;
the module map itself lives in ARCHITECTURE.md.

**Four strata, one import law.** Plain-data contracts (import nothing) → pure core
transforms → effect shells (Steam client, LLM client, store, narration sinks) →
orchestrator and entry shells (pipeline runners, serving, CLI, study drivers). Core
never imports a shell; nothing imports the eval harness; a CI import-graph test
asserts the whole table. All four blind proposals converged on this skeleton
independently.

**The sampling policy is core code, executed by shells.** A pure plan compiler turns
histogram + policy into a fetch plan; the Steam client executes plans against the live
API, the study runner executes the same plans against the corpus. This is the panel's
load-bearing repair: with policy logic inside the client shell, the sampling study (M2)
would certify a simulation while production ran a later reimplementation — a measured
tolerance describing code that never ships.

**Labels are a version-keyed pool, not sample property.** Per-review labels are keyed
by (review, model, prompt version, ontology version) and carry an origin tag (survey /
investigation / corpus). Aggregation takes a manifest + the pool + an explicit version
pin and folds only manifest members with survey origin. The alternative —
manifest-keyed labels, three of four proposals' instinct — died under critique: strict
origin-checked aggregation rejects exactly the offline resampling the sampling study
exists to perform.

**Two-track enforcement is defense-in-depth, never "impossible."** Every proposal
claimed structural impossibility; every critic found a concrete bypass. The honest
guarantee, adopted: independent walls — distinct container types at the sampler seam
(only the survey draw mints a sample manifest; the investigation's window fetch
returns a manifest-less type), the store's membership join carrying an origin
predicate, the CI import test — plus origin tags making any leak auditable after the
fact. "Impossible" is banned vocabulary in these docs.

**Numbers in prose are grounded like quotes.** The panel's most valuable single
discovery (three critics, independently): quote grounding cannot catch a phrasing
model writing "roughly 40%" over a 27% aggregate, or laundering an investigation count
into a percentage-shaped sentence. A numeric-grounding check joins report composition:
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

**Ops conventions adopted from the canon framing, fit-tested:** prompts as versioned
files with content hashes; one spend-ledger table powering the caps, the M1 cost
table, and the ops dashboard; classify-call caching keyed on content (review-text hash
+ prompt + model + ontology versions); the gold set as versioned files in the repo.

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

**Marked-window reviews: include + disclose** (settled 2026-07-09; all four panel
proposals converged on it blind, and no critic landed on the policy itself). Survey
numbers include sampled reviews falling inside Valve-marked off-topic windows; the
trust panel discloses the count per window and links the timeline event. Excluding
would re-apply, by hand, the blunt blanking the unfiltered fetch exists to avoid — the
probe's marked window split ~50/50, thousands of legitimate reviews inside — and
per-review classification absorbs bomb reviews into the aspects they actually complain
about, while the investigation track owns the bomb *story*. Two amendments the
adversarial round forced: (1) **membership is derived at read time** from the freshest
`past_events` snapshot — Valve marks windows retroactively, so a fetch-time stamp goes
stale exactly when it matters; (2) a **marked-share floor** — past a threshold
(provisional now; tuned at the sampling study, gated on the corpus off-topic probe) the
report degrades honestly rather than presenting a bomb-dominated sample at full
confidence, mirroring the language guard's precedent. The exclude-counterfactual stays
computable offline but is never displayed: at 500-review sample scale the delta is
noise inside the interval.

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

## Operational decisions

**The tier deferral, made safe.** Free vs. cheap-paid LLM tier is decided at the
extraction+eval milestone's (M1) exit from the measured cost/quality table rather than
guessed now. Deferral is safe because
four things are built regardless: the provider-agnostic client seam, a concurrency-
capable classify stage (parallelism as config, not architecture), narrated progress,
and enforced budget caps with an honest at-capacity state. The vision's latency wording
is conditional by design.

**`steam_client`: donor, not template** (reframed 2026-07-09). The module is a fresh
build to the windowed-unfiltered sampler contract, *not* a copy of the prior
steam-reviews fetcher — that file is a **donor reference** whose paid-for Steam-API
knowledge (the retry/backoff GET, the identity guard against wrong-appid pulls, endpoint
quirks — `success==2` for no-reviews, the cursor-loop guard, edition-prefix name
matching) is deliberately harvested, while everything structural is rebuilt to this
project's bar. Three alternatives rejected: importing the frozen repo (a portfolio repo
must run standalone); rewriting from scratch (the API-quirk knowledge is paid for); and a
naive file copy — the frozen default-walk loop *is* the proven-unsafe blanking path (the
M1 entry probe showed a plain filtered walk silently skips Valve-marked windows), and its
silence on structured logs / cost / latency is exactly the observability gap this project
treats as a deliverable. Net: harvest the bones, rebuild the sampling brain, instrument
it. The reframe corrected an earlier "copy-and-adapt" shorthand that anchored on the old
code as the baseline.

**The aspect ontology: hybrid with a fixed core** (decided 2026-07-09, on the week-1
probe's evidence — `probes/FINDINGS.md` §6). Open extraction over 5 genre-diverse
games showed a flat, game-specific vocabulary (top-15 grouped labels cover only 28%
of mentions; half of all mentions are single-game vocabulary), so a fixed set would
flatten exactly the specificity the product sells, while pure open stays dominated
(normalization cost AND a blurred eval anchor). The working shape: the vocabulary is
a **versioned design-time artifact** (fixed core seeded from the probe's cross-game
groups, built/revised offline by a strong model, human-gated); runtime extraction is
**two-slot** — classify into the pinned vocabulary, or emit a free-form candidate
when nothing honestly fits; recurring candidates are counted and displayed as a
**disclosed emergent stratum** (real survey numbers, honestly marked uncalibrated —
include+disclose again); **promotion is offline and gated**, bumping the ontology
version, so every displayed number always knows which vocabulary produced it. The
aspect-normalization step this adds to core was a planned possibility, now real code
and part of the eval surface; the gold set and judge calibrate against the pinned
core, with honestly weaker claims on the tail.

**`llm_client`: the seam design** (settled 2026-07-13, five-fork design discussion).
The one door is a single generic entry point — `complete()` over a stage-keyed request —
never per-stage methods: the per-stage routing table stays *data* (stage → provider,
model, params), so retargeting a stage at the M1-exit tier decision is a config edit.
The request/response records live in contracts; the response carries everything guards,
ledger, and provenance need (token usage *split* including thinking tokens, normalized
finish reason, resolved model version) — downstream can only record what crosses the
seam, so the probe's sticker-price lesson is a required field, not a footnote. Each
route carries an opaque provider-params block passed to the adapter untranslated,
dodging the lowest-common-denominator squeeze without widening the seam. Providers are
registered *functions* (a dict registry, constructor-injectable for tests), speaking
raw HTTP via httpx; the aspect-vocab probe script is the Gemini adapter's donor
reference. Rejected: an aggregator library (litellm — a large fast-moving dependency
that normalizes away exactly the provider-specific fields the earned guards watch, and
whose own budget/rate features would sit ambiguously beside ours) and per-provider
SDKs (vendor retry machinery overlaps ours — double-retry against a 20-requests/day
quota; an SDK may still slot *inside* one adapter later without touching the seam).
Config is validated against the registry at construction — an unknown provider fails
at startup, never mid-run.

**`llm_client`: concurrency, persistence, errors** (same discussion). One code path,
concurrency-shaped, dialed to sequential: the client is synchronous (asyncio rejected —
coloring spreads to every caller while the throughput ceiling is the provider quota,
5–15 RPM free-tier, and the self-hosted column is GPU-serial; sync composes with M3's
async serve via standard thread offloading), its one stateful bundle (budget, pacer,
ledger appends) is lock-guarded and hammer-tested from commit one, and the worker pool
lives in the *caller* with `max_workers` as config defaulting to 1 — the paid-tier flip
is a route edit plus a number, zero code. Persistence: `ClassifyCache` and
`SpendLedger` are protocols in contracts (the `Sink` precedent — defined at the base,
implemented in shells, bound at composition); B3's own commits run on in-memory
implementations, the SQLite pair lands with the store (two small tables added to B5's
scope; the first corpus-labeling run requires the durable pair — the cache's whole job
is cross-run "bought labels never re-paid"). The RPM pacer stays in-memory (losing it
costs at worst a brief 429), while daily-quota and cost tracking are *derived by ledger
query*, so they survive restarts because the record is the counter. The cache stores
raw responses keyed by a content hash of (request payload + model) — which resolves the
parked `raw_label` question: pre-normalization phrases live in the cached raw
responses, normalization stays re-runnable over bought labels, no extra field on
`AspectMention`. Errors are typed in the client's public surface (contracts stays a
data spine): transients are retried inside with bounded backoff+jitter and surface as
`LlmUnavailableError` only when exhausted; `AtCapacityError` (our own reserve refusing
— budget cap or daily headroom) is never retried and is deliberately distinct — one is
the world failing, the other is us keeping a promise, and only the latter becomes the
honest at-capacity state; truncation (`GenerationIncompleteError`) is not retried
(temperature-0 classify re-truncates identically) and carries the normalized reason for
the caller to decide. Guards are placed once: adapters normalize finish reason and the
usage split, the client enforces and accounts above them, provider-independent. Open:
whether the module map's "judge-route refusals" phrase meant handling refusals on the
judge route or routing refused generations to the judge — settles at the judge's design
(D2); the typed-refusal mechanism serves either reading.

**`llm_client`: the build-time refinements** (2026-07-13, three forks ruled at the
client-core build; the code docstrings carry the detail). Token prices are *data in the
config's per-model table* alongside rpm/rpd (free tier is honest zeros; the paid flip
stays a number edit) — not computed in adapters, not deferred. "Reserve before
dispatch" means an atomic worst-case reservation (pessimistic prompt estimate + the
route's full output ceiling, priced) settled to the actual cost on completion —
overshoot impossible by construction, and daily-quota admission counts ledger rows
*plus in-flight calls*, since the ledger alone lags dispatch by exactly the racing
window. Rate and quota limits key by *model*, never by route, so two stages sharing a
model share one real quota pool instead of each believing it owns the whole one.
Consequence of the reservation: `max_output_tokens` is the one field lifted out of the
opaque provider-params block into the typed route — the estimator must price it. The
hammer tests pin the exact-admission property (cap of N admits exactly N under racing
threads — overshoot catches a racy check, undershoot catches a leaked reservation).

**`core/classify`: the prompt** (settled 2026-07-13, six-fork design discussion, forks
1–5). The prompt is a versioned artifact (file + content hash + changelog, per the ops
conventions) rendering the codebook **full-fidelity** — every field, all aspects,
category-grouped — so the machine annotator reads the same instructions the human
annotator reads at gold labeling, keeping the agreement number clean of instruction
gaps; the compact rendering (decision surface only: definition + label_when +
do_not_label_when) is pre-registered twice — as the cost fallback if the M1-exit table
demands it, and as the first prompt *experiment* once the judge exists (D2), because
"does a leaner rule set beat a muddier context" is measurable, not arguable.
Classification is **batch-native with size as config**: the builder takes idx-tagged
review tuples, the parser returns per-idx envelopes, one prompt version serves every
batch size (the template never changes, only the data channel grows), and N rides in
the run's config hash. The never-re-paid promise lives in the *label pool*, not the
response cache — the driver selects only reviews lacking labels under the current
version key before composing batches, so batch composition varies freely across runs;
gold-set evals run at the production batch size (certify what ships), and batch-size
contamination (N=1 vs production-N agreement) is a registered D2 experiment. **The
model emits label strings only**: pinned-vs-candidate resolution belongs to
`core/normalize`'s deterministic surface index, never to the model's self-declaration —
the prompt teaches the two-slot *behavior* (never force-fit; the reviewer's own words
when nothing fits), code decides the slot. Output shape is enforced twice: Gemini
`responseSchema` rides in the route's opaque provider-params block (constrained
decoding kills the malformed-syntax class server-side; the aspect field stays a *free
string* — an enum of the pinned labels there would structurally forbid candidates,
silently — while sentiment is a closed enum), and the prompt still states the shape in
one line (provider-portable, and models track formats they understand). **Three
synthetic few-shot examples** demonstrate the edge behavior the codebook's per-aspect
examples can't: the zero-aspect review, a multi-label review with dissociated
sentiments (one evidence quote present, one honestly omitted), a candidate emission.
Synthetic so gold-set disjointness is structural rather than remembered; mid-tail
labels so the frequency thumb stays off the aspects reports will headline; a sarcasm
example deliberately omitted (one example teaches over-reading irony, not sarcasm —
that stays a measured model property), kept as a future option.

**`core/classify`: parse and failure policy** (same discussion, fork 6). The parse is
pure and **salvages per idx**: every valid entry becomes an envelope, every failed idx
lands in a typed failure report — one bad row costs one review, never the batch, and
the report is data the driver must handle, not a log line. Evidence failing the
verbatim-substring check is **repaired, not fatal** — the mention survives with
evidence=None and the repair is counted through the sink (the label may be right while
the quote is sloppy; a rising repair rate is the early smell of what the
fabricated-quote metric measures properly at D2). Retry is **re-batching, not
corrective prompting**: at temperature 0 an identical request re-buys the identical
wrong answer (and our cache would return it without even spending), so the retry must
vary the request — and failed reviews re-entering the driver's unlabeled-selection loop
regroup into fresh batches, which *is* the variation, for free. One round, then the
review is marked unclassifiable-under-this-version and disclosed in the run report —
the include-and-disclose spirit, applied to our own failures. Truncation stays the
client's typed error, answered operationally (batch size and the route's output ceiling
are sized together, conservatively — the reservation prices the full ceiling). All
failure classes are instrumented from the first call; the policy dials (retry rounds,
batch-halving, corrective prompting if ever) reopen on pilot numbers, not guesses.

**The post ships with the milestone.** Every milestone's public artifact ships when the
milestone does, imperfect — the standing counterweight to a known over-investment
pattern.

**The ops story is a deliverable, not plumbing** (2026-07-08). Two-sided stance: no
infrastructure without a driving product need (the Kubernetes/Terraform tombstone
stands), but no skipping an ops opportunity the product genuinely justifies as "not our
focus" — DevOps/MLOps depth is a deliberate portfolio pillar here. What the product
already justifies, made visible instead of silent: evals-in-CI regression against the
gold set, observability (structured logs, cost-per-request, latency, token accounting)
surfaced in a small ops dashboard, versioned provenance (prompt/model/gold-set versions
stamped on every artifact), and a deploy pipeline as code. The test for any addition
stays: does *this product* need it?

**Contract modeling: frozen dataclasses, validated at the shell** (2026-07-09, the M1
foundation). The plain-data spine is `@dataclass(frozen=True, slots=True)` — immutable,
hashable, closed-shape, importing nothing; validation lives in the shells, where a
pydantic parser turns raw external JSON (Steam payloads, LLM responses) into a clean
contract, so *trust no raw data* and *plain data crossing the seam* are both honored and
pydantic never reaches core. Two record-design calls carry weight. **(1) The
classification envelope:** one review yields one `ReviewClassification` — recording *that*
it was classified, under which versions, with zero-or-more aspect mentions — rather than a
flat mention list, because the probe's 46%-yield-nothing reviews make an empty result
indistinguishable from an unprocessed one under a flat shape, which breaks resume/caching
(empty reviews re-paid every run) and honest denominators ("46% yield zero" is only
statable if *processed* counts separately from *produced mentions*). **(2) Dual
sentiment:** the reviewer's overall verdict (`voted_up`) and per-aspect sentiment are
separate fields, because they dissociate constantly ("refunded it, but the soundtrack is
gorgeous") and both are needed to say things like "70% of negative reviews still praise
the art." Provenance is **two-layer** — a universal run stamp (run id, code sha, config
hash) orthogonal to the content-cache key (model + prompt + ontology versions) — and the
narration/telemetry **sink is a Protocol in contracts**, so every shell inherits one
emission contract and the ops-story observability is structural from the first commit
rather than retrofitted. These are the first fields to freeze under *rules now, fields
later*: their consumers all land at M1, and the field lists become authoritative in code.

## Scope & non-goals

- In: aspect reports with receipts, narrated live analysis, the event investigator, the
  trust panel, Docker/FastAPI/SQLite/CI deployment, the evaluation methodology as a
  public artifact, the ops story as a public artifact (dashboard + pipeline, per the
  operational decision above).
- Deliberately out: fake-review verdicts (tombstoned above) · multilingual evaluation
  claims (post-launch experiment, unverified if shipped) · Kubernetes/Terraform/cloud
  MLOps (zero marginal signal for a portfolio app) · any displayed number sourced from
  the investigation track.

## Open questions / deferred

- **Aspect ontology** — DECIDED 2026-07-09: hybrid with a fixed core (see Operational
  decisions; evidence in `probes/FINDINGS.md` §6). The eval harness is now definable:
  gold set + judge calibrate against the pinned core vocabulary.
- **Cache persistence on an ephemeral free host** — decided in the deployment
  milestone's (M3) design (bake-into-image / dataset sync / paid storage).
- **LLM tier** — extraction+eval (M1) exit, from the measured cost/quality table, now
  with three columns:
  free API tier, cheap paid API, and **self-hosted open-weight** (added 2026-07-08).
  Decided **per stage, not globally** (refined 2026-07-08): the seam routes each stage
  independently, and the gap between small and frontier models is stage-dependent —
  near-zero for phrasing, modest-and-measurable for classification (sarcasm is where it
  concentrates), largest for the investigation loop's agentic reasoning. The judge is
  exempt from the choice entirely: always a stronger model than the one it grades
  (self-preference bias), low volume, API.
  The self-hosted candidate costs nothing to evaluate — that milestone is offline
  work, so a small
  open-weight model (Qwen/Llama/Gemma class) runs on the local machine behind the same
  provider seam. Its deployment path, if it wins or ties: serverless GPU with
  scale-to-zero (pay-per-second fits the budget cap; the cold start is absorbed by the
  narrated runtime — "waking the model up…" is a legitimate stream line).
- **Hosting shape: HF Spaces vs. a cheap VPS** — decided in the deployment milestone's
  (M3) design. The VPS
  (~$5/mo, docker-compose, own deploy pipeline + monitoring) is stronger DevOps signal
  and solves cache ephemerality for free; HF Spaces is fewer moving parts. Interacts
  with the cache-persistence question above. **The free-host premise fell 2026-07-09**
  (verified on the create-Space form during the smoke-test milestone, M0): compute
  Spaces — Gradio and Docker alike — now require PRO ($9/mo); only Static Spaces stay
  free. Hosting therefore costs money on either fork, and the VPS is the *cheaper*
  option as well as the stronger signal; HF's remaining case is fewer moving parts
  plus ZeroGPU quota if PRO were bought anyway. Decision stays at M3, on this
  corrected footing.
- **Runtime sampling policy and sizes** — the sampling study's (M2) output, by
  construction — now joined by the **interval method** for displayed shares (stratified
  designs change the variance math; decided with the policy, not before it).
- **Marked-share floor threshold** — the degradation trigger for bomb-dominated
  samples: provisional value set during extraction+eval (M1), tuned at the sampling
  study (M2). The corpus off-topic probe resolved its gate with a twist: the corpus
  holds zero marked-window reviews, so tuning can't use it — it needs windows fetched
  fresh through the windowed unfiltered path.
- **Verification debts at extraction+eval (M1) entry** (both from the panel's
  critique round) — **corpus off-topic probe: CLEARED 2026-07-09** (corpus clean by
  coverage geometry — no marked window overlaps any game's coverage, 0 of 298,553
  reviews affected, no backfill; the blanking mechanism itself confirmed real on a
  plain default walk, making unfiltered fetching a data-integrity requirement, not a
  preference); **datacenter windowed-params probe: CLEARED 2026-07-09** (the
  production primary path — date-window params + the unfiltered flag with cursor
  pagination — verified identical from a GitHub Actions datacenter IP, faster than
  residential). Verdicts and evidence: `probes/FINDINGS.md`, extraction+eval entry
  findings.
