# DESIGN — steam-lens

What is being built and why — the decisions and their reasoning, as a narrative
snapshot of the current design, edited in place as decisions evolve. **This document is
the living source of truth for decisions from the vision phase onward**; `VISION.md` is
the fixed vision-phase snapshot (2026-07-07) and is not updated as the design moves.
How it's built → ARCHITECTURE; the pitch → README.

*Snapshot of the design as of the fixed vision · last updated 2026-07-07 · system-flow
design pending (next phase).*

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

**Copy-and-adapt reuse.** The prior steam-reviews pipeline's battle-tested fetcher
internals are lifted into a fresh `steam_client` module. Importing the frozen repo was
rejected (a portfolio repo must run standalone); rewriting fresh was rejected (the
API-quirk knowledge is paid for).

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

- **Aspect ontology** (open vs. fixed vs. hybrid vocabulary) — decided in week 1 of
  extraction+eval (M1); the eval harness is ill-defined until it lands.
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
  construction.
- **System flow** (module boundaries, seams, data contracts) — the next design phase,
  against the fixed vision.
