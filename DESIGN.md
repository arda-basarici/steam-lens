# DESIGN — steam-lens

What is being built and why — the decisions and their reasoning, as a narrative
snapshot of the current design, edited in place as decisions evolve. **This document is
the living source of truth for decisions from the vision phase onward**; `VISION.md` is
the fixed vision-phase snapshot (2026-07-07) and is not updated as the design moves.
How it's built → ARCHITECTURE; the pitch → README.

*System flow settled 2026-07-09 via the second design panel (4 blind proposals × 4
adversarial critics); the module map lives in ARCHITECTURE.md. Operational decisions
below are dated per entry.*

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

**`store`: scope and schema lifecycle** (settled 2026-07-14, six-fork design
discussion, forks 1–2). B5 lands only the tables with a landed or next-task consumer:
the durable `ClassifyCache` + `SpendLedger` pair (binding into the client's existing
constructor slots), `reviews`, and the label pool. The `aggregates` and `eval_runs`
tables named in the module map are deferred to their consumers (C2, D2) per *rules now,
fields later* — a table's first consumer forces its real design, and pre-building
`eval_runs` would guess at exactly what D2's run-manifest design exists to decide (the
pre-built-M4-contract critique, replayed). Schema lifecycle is a hand-rolled
ordered-steps **migration runner with exactly one step** — the full initial schema as a
reviewable constant, stamped via `PRAGMA user_version`; a file stamped newer than the
code fails loud with both numbers. Alembic was rejected (SQLAlchemy machinery on a raw
`sqlite3` store — infrastructure without a driving need), but so was a bare
create-if-missing: the runner's machinery costs ~ten lines more and means the first
real migration slots into standing structure instead of a reshape. The **freeze rule**
scopes the discipline to when it pays: until the first file holds paid data (C1), the
step list may be rewritten freely — schema churn during C2/D2 design edits step 1,
files are disposable; after C1, steps freeze append-only. Steps are **additive by
default** (`ADD COLUMN` with a default, `CREATE TABLE` — never transforming existing
rows); a data-rewriting step is a design smell requiring a stated reason. Underneath
sits the two-versionings distinction the discussion sharpened: the schema version
protects bought data from *our storage* changing; the content-version keys
(`ClassifierVersions`) protect correctness from *the question* changing — orthogonal
axes, never converted into each other (old-version labels aren't migrated, they
coexist under their own key, which is what makes the pool accretive).

**`store`: shape, schema, validation, tests** (same discussion, forks 3–6). One
`Store` class owns the file — connection, pragmas (WAL, foreign keys, busy timeout),
the migration runner — and the surfaces are small tenant classes handed that
connection, exposed as attributes (`classify_cache`, `spend_ledger`, `reviews`,
`labels`); composition wires `store.classify_cache` straight into the client's slot,
so the client never learns SQLite exists. The store adds **no locking of its own**: the
client already serializes every cache/ledger touch under its one lock (the discipline
the in-memory pair documents and the SQLite pair inherits); WAL + busy-timeout is the
safety net, not the concurrency design. The label pool is **normalized, never a JSON
blob** — the load-bearing queries (C2's origin ∩ version fold, the two-track wall's
origin predicate, denominator counts) all reach *inside* the envelope, and a blob would
make each one a scan-and-parse in Python. Four tables: `runs` (provenance normalized —
one C1 run stamps thousands of envelopes with identical values, `run_id` determines the
rest), `classifications` (UNIQUE on review_id + the versions triple; **origin
deliberately outside the key** — same review under same versions is the same answer
regardless of track, bought once, origin recording how it entered; the
investigation-labeled-then-surveyed edge is C2's membership-join question, its columns
already present), `mentions`, and `classification_failures` — separate from envelopes
because an empty-mentions envelope means "processed, found nothing" while a failure is
precisely not-an-envelope, and a durable failure mark is what stops the driver's
selection loop from re-buying the same failure every run (keyed by the same triple, so
a prompt bump correctly reopens failed reviews). Representation: datetimes as ISO-8601
text **normalized to UTC at write** — string order is chronological order only under a
single shared offset, so mixed-offset writes would silently corrupt every windowed
query (a build-time refinement: the design said "sortable as strings", the build made
it true); enums by value, the token split as three integers, cost as REAL. **Validation is asymmetric by design**: writes take frozen
contracts trusted by construction (structural constraints only — NOT NULL, FK, UNIQUE);
reads treat the file as raw external data and validate by *reconstruction* — enum
constructors plus a naive-timestamp-rejecting datetime parse, failing loud with the
offending row; pydantic stays at the JSON ingest points per contract modeling. No
value-set CHECK constraints (they duplicate the read parse and turn every enum addition
into a migration, against the additive rule). Write semantics follow each contract's
own docstring: cache `put` upserts, ledger `append` is insert-only, envelope/failure
inserts fail loud on UNIQUE violation — a duplicate envelope means the driver's
unlabeled-selection is broken, and `OR REPLACE` would hide exactly that bug. Tests:
one **protocol-compliance suite parametrized over the in-memory and SQLite pairs**
(substitutability is the claim the client's existing tests need, and it retroactively
deepens B3's coverage), contract round-trips (`==` on frozen dataclasses, including
empty mentions and `evidence=None`), runner behaviors, and the selection-query edges
C1's correctness hangs on — all against real SQLite files in `tmp_path`, no mocks. The
thread-hammer is deliberately *not* re-run against the SQLite pair (the client's lock
is the tested serializer; the store never sees concurrency by design), but one
end-to-end smoke binds the durable pair into a real client instance to pin the
constructor-slot substitution.

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

**C0 provider bake-off: the protocol** (2026-07-17, six-fork design discussion). The
survey-slice labeler is chosen by measurement against the gold set, not by reputation.
**Pool — free tiers first** (per the 2026-07-17 landscape scan, live-verified): Gemini
2.5 Flash + Flash-Lite · Mistral Small 4 + Nemo · Groq Llama 3.3 70B + 3.1 8B ·
DeepSeek v4-flash (trial tokens) · self-hosted 8B (Ollama). Cerebras dropped (hard
5-RPM free ceiling, enterprise-only batch, and its speed sells latency — a ruled
non-goal for batch labeling); OpenAI dropped for round one (no free tier). Paid tiers
enter only if a winner needs throughput for the survey buy — a rate question, not a
model-choice question; the scan found cost a non-discriminator at our scale (every
realistic candidate labels the full survey slice for under ~$20 before batch
discounts), so the deciding axes are quality axes. **Metrics, frozen before any run**:
primary is mention-level precision/recall/F1 over pinned-slot mentions, paired by
label-within-review against gold's 351 — precision and recall always reported
separately because the known failure mode (flash-lite's over-extraction, the
calibration entry in ONTOLOGY_PRUNING.md) is directional and F1 alone would blur it;
sentiment scored as flat accuracy on matched pairs only (no adjacency credit — gold's
`mixed` rulings were hard-won and 4 classes are too few for a distance to mean much),
so polarity errors never double-punish detection errors. **One gate**: unrecoverable
parse failures above 2% disqualify outright — a labeler that drops reviews at survey
scale is missing-data bias no downstream metric repairs; below the gate a failed
review scores as zero predictions (never excluded — exclusion flatters the providers
that fail most). Salvage-parsed output counts as parsed, salvage rate reported.
Zero-share is a **diagnostic, not a gate** (gold's base rate: 49.2%) — the pairing
already prices fabrication as precision loss and misses as recall loss; zero-share
stays in the report as the readable summary of that story. **Candidate-slot mentions
stay out of the score** on both sides: n=11 in gold can't support a metric, and slot
discipline is already priced in (forcing a pin where gold ruled candidate is an
automatic precision hit; cowardly routing real aspects to candidates is a recall hit).
The dumping loophole gets a named diagnostic — candidate-emission rate vs gold's ~3% —
plus a qualitative overlap table against gold's 11, unscored. **Parity**: `classify-v1`
verbatim for every candidate, no per-model tuning (tuned prompts would measure our
effort, not the models); structured output deliberately non-parity — each candidate
runs its best native mechanism (strict schema, JSON mode, Ollama schema), recorded per
row, because that difference is part of the product being bought and flattening to the
weakest mode would erase what the parse metric exists to measure; batch size and
temperature held at the B4 pilot's values, context-forced deviations recorded, never
silent. One scored run per candidate; a repeat run only as a decode-variance probe if
leaders land within error bars. **Decision: frozen metrics, recorded judgment — no
pre-committed ranking.** Arda rules from the full table after the runs (his call,
2026-07-17); the guard against metric-shopping is that the metrics above are frozen
now, and the ruling lands in this file with its why at the moment it's made. Two
pieces of information ride with the table: a **reference line** — the gold-assist
model's own F1 vs final gold, computed from the persisted assist drafts (it competes
with nobody, it calibrates the field) — and a standing **no-buy exit**: the bake-off
may conclude nobody is buyable, and the recorded outcome is then tier escalation
(paid stronger models, round two), never buy-the-least-bad. **Lineage**:
`claude-sonnet-5` is banned from the pool (gold assist, INSTRUCTIONS §8); Gemini 2.5
Flash/Flash-Lite ran the *pruning probes* and shaped the vocabulary, not the gold
labels — seen, weighed, eligible. **Provenance**: runs land under
`probes/captures/bakeoff/<provider>/` — raw responses, parsed labels, and a manifest
each (model ID string, provider, `classify-v1`, ontology pin `v1`, structured-output
mode, batch size + deviations, date, token counts, actual cost); headline numbers
carry 95% bootstrap CIs resampled over the 250 *reviews* (mentions within a review
aren't independent); the comparison table is a generated artifact, regenerable from
captures.

**C0 bake-off: the scorer/runner design + the batch-size amendment** (2026-07-18,
five-fork design discussion). **The amendment — batch size moves from the parity
column to the part-of-the-product column**, joining structured output: the protocol
above froze "batch size held at the pilot's values," but the pilot only ever measured
N≤5, and free-tier daily request quotas make low N production-hostile (the ~50k-review
survey buy at N=5 is ~10,000 requests — weeks at a 250–500 RPD tier; N=50 cuts it to
~1,000). Since the bake-off's N becomes C1's production default and certify-what-ships
means measuring each candidate at its deployable shape, **each candidate runs at its
own N = min(envelope max, dilution ceiling)** — envelope max computed from the
provider's own caps (per-request/per-minute input tokens; the output ceiling usually
binds first: at ~120 output tokens per review, an 8k-output model caps near N≈60
regardless of context window), dilution ceiling established once by the reframed
N-probe. N is recorded in every manifest and shown per candidate in the comparison
table — a visible dimension of Arda's ruling, never a hidden confound. Honesty rider,
recorded so the choice reads correctly later: the free-tier RPD constraint motivated
maximizing N; if C1 ends up buying the winner's paid tier (where RPD stops binding),
high N was an operational choice, not a quality-driven one. **The N-probe** (runs
before any scored run): map the quality-vs-N curve at N ∈ {5, 10, 20, 50, envelope
max} on two structurally different free candidates — Gemini 2.5 Flash and Groq Llama
3.3 70B — scored against gold with the same scorer; the dilution ceiling is the
largest N where both hold quality within error bars. Two probe models rather than one
so the ceiling isn't quietly tuned to a single vendor's comfort; using gold to set an
operational parameter before the scored runs is calibration, not metric-shopping — the
parameter rule applies uniformly, and the probe is disclosed here rather than
discovered later. **Scoring core is library code** in `src/steamlens/evals/` (the
ARCHITECTURE-planned eval stratum: imports anything, nothing imports it) because the
gold-pairing metrics outlive the bake-off — evals-in-CI (D3) certifies against the
same gold set; the runner and the table generator stay `probes/` scripts (one-shot
orchestration whose findings, not style, are the artifact). **Pairing is set
intersection by label within review**: gold verified duplicate-free (250/250, no
repeated label in any review) and classify's parse collapses repeats on the prediction
side, so true positives are label matches, false positives unmatched predictions,
false negatives unmatched gold, pinned-slot only; sentiment is flat accuracy over the
matched pairs. **Both sides resolve pinned-vs-candidate through `core/normalize`'s
surface index** — one resolution authority, so the scorer and the candidates can never
disagree about what "pinned" means; gold's 11 candidate mentions fall out mechanically,
and a gold label drifting from the pinned vocabulary surfaces as a loud mismatch
instead of silently scoring as a candidate. **The runner rides the full `LlmClient`**
(fresh one-stage client per candidate) rather than raw provider entries: rpm pacing,
bounded retries, the spend ledger, and the durable cache give a crashed run free
resume — exactly the machinery free tiers need. **The 2% gate's "unrecoverable"
defined**: a failed row gets one re-batch pass at N=1; unrecoverable means it failed
in its production-shape batch *and* alone — crisp semantics ("fails even in the
easiest setting"), poison-review isolation so one pathological text can't drag batch
neighbors into the gate, ~5 extra requests at the gate boundary. Salvage-parsed rows
count as parsed with the salvage rate reported, per the protocol. **Bootstrap CIs**:
10,000 resamples over the 250 reviews, percentile intervals, fixed seed in the
manifest. Derived scores are never persisted per provider — the table regenerates from
captures + gold, one source of truth.

**C0 bake-off: the run campaign's envelope amendments** (2026-07-18/19, accumulated
during the runs; each lesson also lives as a comment on its candidate in
`probes/bakeoff_runner.py`). **Pool growth**: Gemini 3-flash-preview / 3.1-flash-lite /
3.5-flash (newer free tiers, console-verified quotas); Mistral Medium / Large /
Ministral-14B (Arda's amendment — Mistral's free tier has no daily cap, so its stronger
tiers are survey-viable at zero cost); nemotron-3-ultra and hunyuan-3 via OpenRouter
(50 free requests/day *account-wide*, shared across both); DeepSeek v4-flash + v4-pro —
**the pool's first paid tier**, with real prices in the ledger (flash $0.14/M in miss /
$0.0028/M cache-hit / $0.28/M out; ids pinned because `deepseek-chat` deprecates
2026-07-24 — five days' notice, the model-churn precedent named below). **Probe-model
substitution**: the N-probe's planned second curve (Groq 70B) can't ladder — its
envelope kills large batches — so the two dilution curves ran on gemini-3.1-flash-lite
and mistral-small. **Envelope exits, recorded**: Groq 8B is envelope-dead (6K TPM < the
~7.6k-token prompt — one request unservable at any N); Groq 70B is an **envelope exit
by ruling** (2026-07-19: 100K TPD ≈ 2 days per 250-review measurement, ~22.5M tokens
for the survey — infeasible for dispatch at any quality; its wire lessons stand: Groq
counts prompt + the `max_tokens` *reservation* against its 12K per-request TPM window,
and `json_object` forces an object root on this route too). **Retry three-staging**
(after nemotron burned a full daily quota on straight-to-N=1 isolation): initial batch →
re-batch failures at production N → isolate only survivors at N=1; the 2% gate's
"failed in its batch AND alone" semantics is preserved at a fraction of the requests.
**Decode tolerance ruled into core** (`core/classify`, not the probe — the bake-off
must measure the same pipeline C1 will run): strict `json.loads` first, then the first
fenced block that decodes, then the outermost `[...]` slice; object roots still fail
the array contract deliberately — shape indiscipline is signal, and it caught v4-pro.
**The output ceiling raised from measured demand** (2026-07-19): the day-one
512+140/review formula truncated dense batches at five providers (cut exactly at the
cap) and even one N=1 retry (a single dense review legitimately generates up to ~1,360
tokens); now 2048+200/review — base holds one worst-case review, per-review clears the
measured >165-token dense zone, the per-candidate `output_cap` min() stays as the
runaway guard. **v4-pro: DQ'd on root-shape instability** (16.8% unrecoverable under
`json_object`: object roots on 2/13 batches, bare `{"idx": 0, ...}` at N=1) — parsed-row
precision .662 vs flash's .732 at 3× the price made a prompt-json rechase not worth
buying; the row stands as measured. **Ollama: closed unwired, a value exit** — the
serverless argument (a labeler living on the local GPU can't serve the M3/M4 live path)
always limited local to the one-time survey batch, and DeepSeek's ~$1.4 true survey
cost collapsed the remaining pitch to "save a dollar against 8B-Q4 quality risk plus a
wiring session." **Two completions skipped by decision** (the Groq-exit precedent —
a recorded decision, not a gap): 2.5 Flash n50 (its RPD went to the n20 DQ-clearing
finish) and nemotron's last 3 reviews (row stands 247/250 PARTIAL) — both non-contenders
whose rows couldn't move the ruling, and the ceiling raise invalidated their cheap
cache-warm reruns.

**C0 bake-off: the paired read + the v4-flash N-freeze** (2026-07-19). **Paired
bootstrap added to the evals core** (`paired_bootstrap_ci`; `--compare` in the table
script): every run scores the *same* 250 gold reviews, so run-vs-run gaps are paired —
each resample draws one set of review indices and scores both runs on it. The
separate-interval read overstates the gap's uncertainty, and the correction cut both
ways on the same day: 3 Flash vs v4-flash at matched n20 — individual CIs overlap
heavily, paired gap **real** (F1 +0.034 [+0.002, +0.067], recall-driven); 3 Flash n20
vs v4-flash at its best N — **indistinguishable** (+0.025 [−0.004, +0.055]). Eyeballing
overlapping intervals would have called the first one wrong. **The v4-flash ladder**
(n5/10/20/50, all four 250/250 with zero parse failures): F1 .746 / **.776** / .767 /
.762 — the curve peaks at n10 with two-sided paired evidence (beats n5: F1 +0.029
[+0.009, +0.052], the n5 precision decay is the flash-lite pattern repeating; beats
n50 on recall: +0.042 [+0.013, +0.073], the depth-dilution direction every ladder
showed). **N frozen at 10 — quality's call alone**: true (cache-adjusted) cost is
N-independent in practice (the ~88%-fixed prompt makes codebook repeats nearly free at
the ~98%-off hit price; measured $0.006–$0.011 per 250 reviews across the ladder,
survey ≈ $1.1–1.6 at any N), and wall time washes out because DeepSeek's envelope is
concurrency-only (2,500 concurrent — the C1 driver gets bounded concurrency as config,
per the seam's existing design). This closes the batch-size amendment's honesty rider:
the free-tier RPD pressure that motivated maximizing N doesn't bind a paid
concurrency-only winner, and the freeze went to the measured quality peak, not the
operational ceiling.

**C0 ruling: DeepSeek v4-flash at N=10 labels the survey** (Arda's ruling, 2026-07-19,
from the regenerated table + paired comparisons; config: v4-flash · N=10 ·
`classify-v1` · ontology `v1`). **The honest sentence**: 3 Flash is measurably better
at matched N (+0.034 F1, paired CI excludes zero), the gap closes to indistinguishable
against v4-flash's frozen N, and it costs ~12× more (~$25 paid-Gemini survey vs ~$1.4
true) — v4-flash wins on cost-effectiveness with zero parse failures across its ladder,
a stable `json_object` mode, and no quota envelope. Not claimed: "as good as the
leader." The no-buy exit was live and not taken — top-cluster quality at survey cost
below lunch money is a clear buy. **Single-labeler discipline**: the free-Gemini-with-
DeepSeek-fallback hybrid was considered and rejected — savings bounded by the ~$1.4 it
competes with, free quotas would label under 1% of the pool, and a mixed-labeler pool
breaks measurement integrity (two error profiles inside every aggregate, and D2's
judge calibrates against one labeler). Provider fallback re-enters legitimately at
M3's design as an availability question, not a survey question. **Reopen conditions**:
(1) the pre-registered compact-codebook experiment (D2) changes the prompt, which
invalidates the dilution curve by construction — it re-certifies quality *and* N on
the gold slice; (2) DeepSeek repricing or model deprecation — the `deepseek-chat`
five-day retirement is the named precedent; (3) survey-scale anomalies the gold slice
couldn't show (drift, systematic per-game failure) surface through D2/D3, and tier
escalation per the protocol's no-buy clause is the recorded fallback, never
quiet tolerance.

**C1 slice ruling: census of the usable pool** (Arda's ruling, 2026-07-19; full
narrative in the stream SESSION_LOG same date). The survey labels **every
English-nonempty corpus review — 135,260 across the 49 usable games** (measured by
`probes/survey_supply_counts.py`; ~45% of the 298K headline once English-first and
Unicode-honest emptiness shrink the denominator; per-game min 195 / median ~2,100 /
max 6,869). This deliberately reopens and supersedes the 2026-07-16 "full corpus is
never labeled" ruling on its collapsed premises: the labelable pool is 135K, not 298K,
and the cost base is v4-flash's true ~$3–6, not Gemini's ~$25 — census costs 2.9× the
1,000/game alternative. What the census buys: no shortfall policy (small games are
censuses under any scheme), zero sampling error against the corpus for every displayed
number, and the sampling study (M2) is never capped by today's choice. **No
pre-filtering beyond usable** (ruled same day): "no aspects" is the certified
classifier's own verdict and a measured quantity (gold zero-share 49.2%), a usefulness
heuristic would be an unvalidated second classifier standing in front of the certified
one ("runs bad" is 8 characters of real signal), and exact-duplicate texts already
cost once through the content-keyed label cache. **Instrument lesson recorded**:
100-review/game probes cannot resolve mention rates under ~1% — the floor-clearance
projection (`probes/floor_clearance_projection.py`) returns identical results at every
candidate size — so tail pins (matchmaking, cheating, physics, servers_netcode at
0.27–0.43% corpus-pooled) are only visible at n≈1,200–1,900, where the census lives
anyway. Slice-size math in the stream WHITEBOARD (2026-07-19).

**C0.5 certification: the v2 wording batch, ruled** (Arda's ruling, 2026-07-19: **the
v2 full-fidelity codebook labels the survey, N=10 stands** — the sanctioned reopen
under the C0 ruling's condition #1). **Why it ran**: the gold ledger's routing rulings
(2026-07-16/17) postdate classify-v1's frozen wording (2026-07-13), so the labeler had
never seen the semantics gold grades it against, and the survey pool is the durable
asset C2, D2, and M2 all fold — it gets bought at aligned semantics. **The
distillation** (one shot, by design — wording was never iterated against gold F1):
triage interview over the 33-ruling ledger settled what rides (routing/semantic
rulings 1–3, 8–16, 18–25, 27–33, the two FIXLOG wording riders, and machine-side
demotion guards for camera/accessibility that v1 only carried for grind/localization)
vs what stays gold-process-only (4–6, 17, 26); the ride-list landed in
`src/steamlens/ontology/v2.toml` — same 51 pins, aliases byte-identical (the
normalize surface index is unchanged), global rules 8 → 13, every real-pass example
freshly constructed so no gold span reaches the machine's contract. The compact
render became a first-class prompt variant (`classify-v1-compact`, own content pin) —
template code, selected per run. **The arms** (gold slice, N=10, paired bootstrap
10,000 resamples, seed 20260718, all runs 250/250 with zero parse failures): v2 vs the
frozen v1 baseline — precision **+0.066 [+0.039, +0.098]** (real), recall −0.030
[−0.062, +0.000] (borderline), F1 +0.020 [−0.003, +0.045], sentiment +0.015; v2-compact
vs baseline — precision +0.073 (real) but recall **−0.057 [−0.097, −0.020] confirmed
worse**; compact vs full — indistinguishable on all four metrics. The mention-economy
diagnostic explains the shape: baseline over-mints (386 mentions vs gold's 351,
zero-share 48.0% vs 49.2%), v2 lands on gold's economy (339 / 52.4%), compact folds
too hard (329 / 54.0%) — the ruling batch is precision-lifting deletion, working as
designed. **The honest sentence**: v2's F1 is not-worse-and-leaning-better, its
precision gain is confirmed; "confirmed better F1" is not claimed. **Compact rejected
for dispatch, kept for D2**: its token cut measured 26% (9,940 → 7,330 prompt
tokens/request — the pre-registered ~60% was estimated against the leaner v1
codebook), worth ~$0.10 across the whole census under prefix caching — immaterial next
to a confirmed recall loss and broken human/machine contract parity. **The N re-check
on the winner** (n5/n10/n20, C0's ladder shape): F1 .786 / **.796** / .752 — n10 beats
n20 two-sided (+0.043 [+0.020, +0.071]), n5 is indistinguishable and dearer per
request; the peak-at-10 shape reproduces under new wording. **Dispatch config for C1**:
v4-flash · N=10 · `classify-v1` template · **ontology `v2`** (selected by explicit
path; the packaged default stays v1 because gold's identity pin is v1 — flipping the
default is a deliberate later step that must rework the runner's gold-pin check, not a
side effect). Captures: `probes/captures/bakeoff/deepseek-v4-flash-v2*/`; cost of the
whole certification ≈ $0.15.

**C1 `studies/` labeling driver: the census dispatch design** (settled 2026-07-19,
seven-fork design discussion; dispatch config itself frozen at the C0.5 ruling —
v4-flash · N=10 · `classify-v1` · ontology v2 by explicit path). **Shape**: a thin
`studies/` entry shell (per the module map) plus a local-corpus reader — raw frozen
JSONL → `Review` records with the usable filter as a pure, tested predicate; the
driver composes reader → `ReviewStore` ingest → selection → batch → `core/classify`
prompt/parse → `LlmClient` → `LabelPool`, narrating through the sink. Resume needs no
checkpoint ledger by construction: `unlabeled_under` *is* the checkpoint (envelopes +
failure marks anti-joined), batch composition is deterministic over the remaining set,
and the content-keyed cache makes a re-formed batch whose response was already bought
free — crash anywhere, relaunch, pay only for what never completed. **Fork 1, store
concurrency — two `Store` instances over the one file**: the client's cache/ledger
bind to connection #1 (touched from worker threads under the client's lock), all
label-pool writes go through connection #2 from the main thread only. Rationale: a
transaction is connection-scoped, so on the shared single connection a worker's
mid-`complete` cache write could land inside the main thread's open envelope
`BEGIN…COMMIT` and be erased by its rollback — silently re-buying a bought response.
Two connections make the interleave impossible structurally; WAL + the existing 5s
busy timeout (the store docstring's "safety net for an unexpected second connection")
get promoted to designed-for, docstring updated. Worker topology: the pool runs
call+parse only; the main thread consumes completed futures, writes envelopes/failure
marks, and owns the narration — the fail-loud duplicate-envelope discipline stays
single-threaded. **Fork 2, ingest scope — usable pool only**: English + Unicode-honest
nonempty + CS2 (app 730, named constant) excluded at the reader, so the `reviews`
table, the ruled census, and the selection query are the same set and
`unlabeled_under` means "remaining work" unmodified. After ingest the driver asserts
the total equals the ruled **135,260** and fails loud before any money moves — the
slice ruling becomes a runtime check. The ingest narration states the drop arithmetic
(total on disk / non-English / empty / ingested), and the raw files stay the
re-ingestable source of truth for any future non-English question. The no-usefulness-
prefiltering ruling is untouched: low-content English reviews are bought, and their
empty-mentions envelopes are the measured zero-share. **Fork 3, the label key's
`model_version` — the requested id** (`deepseek-v4-flash`), never the response's
self-reported version: keys are contracts, observations are evidence. The reported
string journals per call in the spend ledger (already the `SpendRecord` shape) and the
run manifest records the set seen; a mid-run change from the first-seen value **aborts
loud** rather than warn-and-continue — a silent provider model roll is exactly the
event that would split the pool's "one annotator" claim, and resume makes the abort
cheap. Caveat on record: if DeepSeek merely echoes the alias, the drift watch watches
a mirror — the per-call ledger is then the only real trace, which is why it is
per-call. **Fork 4, throughput dials — run config, not design**: `max_workers`
defaults to 1 (sequential resting state), the census dispatches explicitly at 10;
client rpm for v4-flash set to 600 so pacing demotes to a runaway backstop under the
worker bound (DeepSeek's envelope is concurrency-only, 2,500 concurrent for flash —
console-verified 2026-07-19); the first batch runs solo before the pool opens so the
provider's prefix cache seeds once instead of ~10 concurrent cold misses — pennies,
but the pilot's cost-per-review extrapolation then measures steady-state behavior.
These dials never enter the cache/envelope key — retunable per dispatch. **Failure
policy — the bake-off's three-pass shape**: initial batches → failed idxs re-batched
at production N → survivors isolated at N=1 → still-failing reviews marked durably via
`record_failure` (excluded from future selection under this versions triple).
`LlmUnavailableError` and `AtCapacityError` abort the run loud; both are resume-clean.
Amended 2026-07-20 on live census evidence (DeepSeek's content filter 400'd one
request over a single review's Tiananmen line, and the pre-fix abort would have
re-formed the same batch every relaunch — a permanent wall): a
`ProviderPermanentError` now fails the batch's rows into that same sweep, so the
innocent co-batched reviews label on isolation and only the trigger review takes a
durable mark carrying the provider's refusal verbatim — the pool honestly records
"the annotator refused this text" (an instrument-limitation footnote the milestone
post should carry: a Chinese-hosted annotator imposes its content policy on the
census). Guard: a >20-refused-batches circuit breaker still aborts — a systemic 4xx
(revoked key, broken payload) must surface as an abort, never as thousands of quiet
marks. Same incident's second lesson: an aborting run now cancels its queued batches
(the executor's context manager otherwise *waits* for the queue, which kept buying
~11 minutes of responses behind the dying run — recoverable money since the cache
serves them to the next tranche, but abort must mean stop by construction).
**Fork 6, artifact homes**: the pool lives at `data/steamlens.sqlite3` (`data/`
gitignored; the bought census joins the Drive backup with a hash manifest, post-census
TODO), and each run also writes `data/runs/<run_id>/manifest.json` bakeoff-style —
resolved config, versions triple + ontology content hash, counts, token totals,
ledger cost, reported-version set, timestamps, aborted-or-clean. The `runs` table is
the database's memory; the file is the human's citable one. **Fork 7, budget caps
under the real balance** (~$9.80 DeepSeek credit at ruling time): pilot `--budget-usd
1`, census `--budget-usd 8` — 2× the ruled $3–6 estimate's midpoint but deliberately
*below* the balance so our clean `AtCapacityError` always fires before the provider's
insufficient-balance error; the cap is per-invocation (the client counts from its own
construction), so the driver narrates the ledger's lifetime total at startup — every
relaunch shows cumulative census spend next to the fresh cap. Pilot gate before the
census: a `--limit` slice (~300 reviews) certifies cost-per-review and throughput;
census projection above ~$6 pauses for a top-up-or-reconsider ruling.

**C2 `core/aggregate`: the number mint** (settled 2026-07-20, design discussion over
five decisions; folds the census the C1 driver bought). **Shape**: a pure fold —
survey-origin, version-pinned envelopes → `AspectAggregate` records — with persistence
and the `aggregates` table pushed to the shell and deferred to their first consumer. The
contract already fixes what a number *is* (`AspectAggregate`: raw counts only, the
evidence floor deliberately a compose-time presentation rule, never baked into the
stored tally); C2 is the first thing that fills it. **Decision 1, the grain — fold per
game, `app_id` promoted onto the record.** A number is minted per `(app_id, aspect,
slot)`, not once globally per aspect. Rationale: every consumer — a single-game report, a
cross-game "best combat" leaderboard, the eventual product screen — lives at the per-game
grain; a global fold blends incomparable populations (combat across an RPG, a farming
sim, a city-builder is an average nobody wants) and, being lossy, can never be re-split
into games, whereas per-game rows always roll back up to a global view. Per-game is also
the only grain that stays honest about thin games: a small title's few mentions show *as*
thin (wide error bars, greyed by the floor) instead of dissolving into a large pile. The
cross-game leaderboard is then a *transpose* of the same table (fix an aspect, read down
the games), needing no separate artifact. **Contract amendment**: `app_id: int` joins
`AspectAggregate`. A2 froze the record before any consumer existed to reveal the grain;
C2 is that consumer. Hiding the game inside `manifest_id` was rejected — it fails the
"references carry their meaning, no decoder required" rule: every ranking query would
decode the manifest to learn which game a number names. The game is part of the number's
identity, so it is a first-class field. **Decision 2, candidates fold exactly like pinned
— no fuzzy merge, singletons kept.** Candidates group by their exact stored
(already-normalized) string, in the same table, `slot` carrying the pinned/candidate
distinction. Two things are deliberately *not* done: (a) no machine merge of
near-duplicates (`grind`/`grinding` stay distinct) — `core/normalize` (B2) already ran at
label-buy time and by design only casefolds/collapses whitespace, never stems, because a
false merge silently corrupts two aspects at once while a false miss lands recoverably in
the candidate stratum for human-gated alias promotion; re-introducing fuzzy merging in C2
would relitigate that at a layer further from review. (b) No floor at mint — singleton
candidates mint as faithful (thin) rows, because the contract keeps the number a raw
tally and the floor a display rule; keeping singletons means C2 has exactly one job
(count everything, honestly) and *every* policy question (report floor, promotion
threshold) lives downstream in one place. Consolidation for readability is deferred to
the consumer: pinned aspects are already de-fragmented (aliases fold at label time), and
residual candidate fragmentation is smoothed at consumption — an LLM composer naturally
writes "excessive grinding" once (a *story*-track cosmetic merge, permitted; never a
number merge), and a published *number* freezes its fold via offline alias promotion (a
new ontology version + a cheap deterministic re-normalize over stored candidate strings —
no LLM re-buy). C2 itself folds whatever version it is pinned to and stays the dumb
faithful counter. **Decision 3, the denominator — per-game survey envelope count, empties
included.** `sample_size` is that game's total survey envelopes under the pin, counting
the ~46% empty-mentions envelopes; dropping them would inflate every share.
`reviews_with_aspect` is the distinct reviews in the game mentioning the aspect (≤
`sample_size`, and it differs from the mention total when one review mentions an aspect
twice). This is exactly why the empty envelope is a first-class contract state (classify's
envelope-over-flat-list call): the honest denominator is a stored quantity, not a guess.
**Decision 4, provenance — the version pin and the manifest.** Only `survey`-origin,
version-matching labels fold (contract-mandated; investigation-track labels never touch a
number). The pin is **v2 by explicit path** — the C1 remainder: the packaged ontology
default stays v1 (gold's identity pin), so every pool consumer, C2 included, pins v2
explicitly. `manifest_id` names the fold — the version triple, the game set, when — tying
each number back to the census sample it came from; the contract's deliberately loose
manifest linkage (awaiting the M2 sampling machinery) is filled now with the census run's
identity. **Decision 5, persistence — pure fold by default, snapshot on publish, table
deferred.** C2's core is a pure function (`classifications → aggregates`,
data-in/assert-out testable); it stores nothing. Recompute-on-demand is the default
because the fold is cheap *and* fully reproducible (keep-vs-regenerate: regenerate the
cheap middle). Persistence is an effect at the shell, taken deliberately only when a
number is *published*: a snapshot step writes the fold into the `aggregates` table
stamped with full provenance, giving a frozen, citable artifact — a snapshot store, not a
live cache, so staleness is a non-issue (a persisted row is explicitly the record of run
X). The `aggregates` table (B5-deferred to this consumer) is deferred *again* to its real
first need — a published post (F1) — since D2 judges *labels* against gold and reads the
pool, not the aggregate table. **Build note — never fold through the fat `reviews`
join.** Measured on the census (135,259 envelopes / 170,532 mentions): the counting fold
is ~150 ms, but joining the 169 MB `reviews` table merely to read each review's `app_id`
drags text pages off disk and costs ~800 ms; prebuilding a skinny `review_id→app_id` map
(110 ms, two columns) and folding against it lands the whole per-game pass at ~230 ms.
Get `app_id` via the skinny map (or, only if ever needed, an append-only
`app_id`-on-`classifications` migration); the ~1.5 s naive path is a fat-table smell, not
an inherent cost.

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
  **The survey-labeling stage is decided as of 2026-07-19** — cheap paid API (DeepSeek
  v4-flash at N=10, the C0 ruling above), with the self-hosted column closed unwired
  for this stage (the Ollama value exit); the remaining stages (judge, phrasing, the
  investigator) still decide at their own design points per the per-stage rule.
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
