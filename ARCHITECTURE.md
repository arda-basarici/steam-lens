# ARCHITECTURE — steam-lens

How it's built and why that structure — a narrative snapshot, edited in place, growing
with the build. Decisions and their rationale → DESIGN (cited by name); the pitch →
README.

*Pre-build snapshot · last updated 2026-07-09 · no modules exist yet — the module map
below was settled by the system-flow design panel (2026-07-09; decisions + reasoning
in DESIGN: the system flow); sections fill in as milestones land (M0–M4).*

## Design shape (intended)

The two-track engine from DESIGN, as a one-directional flow:

    steam_client (sampler boundary)
    ├──► survey track:  fixed sample ─► per-review classify ─► aggregate ─► numbers
    ├──► investigation: signals ─► hypotheses ─► targeted window fetch ─► verify ─► stories
    └──► histogram / totals (all languages, counting only)

    llm_client (provider seam) ◄── classify · synthesize · investigate
    aggregates + stories ─► report composer ─► FastAPI (REST + SSE) ─► frontend
    SQLite ◄── report cache · precompute store

The rules, stated once:

- **The two-track rule.** Displayed numbers come only from the survey track;
  investigation fetches never feed a percentage (DESIGN: the survey/investigation
  split). Enforcement is **defense-in-depth plus auditability** — distinct container
  types at the sampler seam, the store's membership join with an origin predicate, the
  CI import-graph test, origin tags on every label — never claimed "impossible"
  (DESIGN: the system flow).
- **Numbers in prose are grounded like quotes.** Report composition verifies every
  numeral in LLM-phrased narrative against the aggregates/events the claim cites —
  quote grounding's sibling, covering the gap where a phrasing model writes "roughly
  40%" over a 27% aggregate (DESIGN: the system flow).
- **One door to Steam.** All review access goes through the sampler module — windowed
  primary, documented fallback, path-reporting provenance (DESIGN: one sampler module
  owns all review access).
- **One door to the LLM.** All model calls go through the provider-agnostic client;
  concurrency is a config value (DESIGN: the tier deferral, made safe).
- **Functional core, effects at the shell.** Classification, aggregation, detection,
  and verification are pure transforms over plain data; Steam I/O, LLM I/O, SQLite, and
  streaming live at the edges.
- **Narration is an output with rules.** The stream labels hypotheses until their check
  passes — the honesty discipline applies to the process view, not just the report.

## Module responsibilities

The committed map (settled 2026-07-09, panel-deliberated; not yet code — modules land
milestone by milestone). Four strata, imports strictly downward:

    steamlens/
      contracts        — the plain-data spine: every cross-seam record; imports nothing
      core/            — pure transforms over plain data; no I/O imports, ever
        sampling       — plan compiler: histogram + policy → fetch plan (the same code the
                         sampling study certifies and the runtime executes — DESIGN: policy is core)
        classify       — classification prompt build + strict response parse (the LLM call stays in the shell)
        aggregate      — manifest + label pool + version pin → aspect aggregates; the only
                         number mint; folds survey-origin members only
        detect         — granularity-aware event detection over histogram buckets (rollup unit is data)
        investigate    — hypothesis generation + verification verdicts (the loop itself is a shell)
        compose        — report assembly: quote grounding, numeric grounding, trust panel,
                         marked-window membership derived here at read time from fresh past_events
      shells:
        steam_client   — the one door to Steam: executes fetch plans; windowed primary with
                         per-window cursor fallback under a feasibility bound, semantic window
                         validation, per-window provenance, past_events capture, always unfiltered
        llm_client     — the one door to models: per-stage routing table, concurrency as config,
                         atomic budget counter + spend ledger, judge-route refusals,
                         content-keyed classify cache
        store          — SQLite (WAL): reviews, manifests + membership, the label pool,
                         events + investigation rounds, report cache, spend ledger, eval runs
        pipeline/      — stage compositions + the survey/investigation/report runners + the
                         narration sink protocol; all narration emission lives here, never in core
        serve/         — FastAPI REST + the SSE sink + static frontend; translates typed errors
                         into the honest at-capacity state
        evals/         — the eval harness, first-class: gold set (versioned files in the repo),
                         judge calibration, metrics (incl. fabricated-quote and numeric-grounding
                         rates), run manifests, the CI entry point
        studies/       — thin offline drivers: corpus labeling (M1), the resampling study (M2)

    Dependency law: entry shells (serve, studies, cli) → pipeline → clients/store →
    contracts; core imports only contracts; nothing imports evals. A CI import-graph
    test asserts this table — it doubles as a two-track wall.

## Runtime & deployment topology

One container, few wires — the module map above is the real communication diagram:

    Browser ── REST (reports) + SSE (narration) ──► FastAPI app (one process, one container)
                                                     ├── serves the static frontend
                                                     ├── SQLite file, in-process (WAL)
                                                     ├──► Steam store API   (steam_client's door)
                                                     └──► LLM provider APIs (llm_client's door)
    GitHub Actions ── lint · tests · import-graph test · image build · eval soft-gate ──► repo/registry

Deferred to the deployment milestone's (M3) design, plugging into these interfaces
without refactor: the host (VPS vs HF), the SQLite file's durable home (Litestream is
the noted candidate), the deploy pipeline's concrete shape, keep-alive.

## The life of a request (the cold path, stage by stage)

The committed flow for a cold (uncached) analysis — each stage names its module, what
crosses the seam, what lands in the store, and which guards are active at exactly that
point. Narration accompanies every stage over SSE; offline runs get the same lines on a
console sink.

| # | Stage | Module | Consumes → produces | Persists | Guards active here |
|---|-------|--------|---------------------|----------|--------------------|
| 1 | Resolve game | `serve` → `steam_client` | query → `GameRef` (appid, population totals, score) | `games` | input validation at the web edge |
| 2 | Cache check | `serve` + `store` | `GameRef` → fresh `ReportDocument` or miss | `reports` (read) | freshness rule; cache age disclosed in the trust panel |
| 3 | Histogram fetch | `steam_client` | appid → `HistogramSnapshot` (buckets + rollup unit + daily last-30 + `past_events`) | `histograms` | always unfiltered; shape validation at ingest |
| 4 | Event detection | `core/detect` | snapshot → `DetectedEvent[]` (bucket-aligned, unit carried, Valve-overlap flag) | `events` | granularity-aware thresholds per rollup unit; localization honesty (a month-resolution event is only month-accurate) |
| 5 | Plan compilation | `core/sampling` | histogram + policy → `FetchPlan` (windows + quotas) | (inside the manifest) | the same pure code the sampling study (M2) certifies — policy is never reimplemented in a shell |
| 6 | Survey draw | `steam_client` | `FetchPlan` → reviews + `SampleManifest` (the only minter) | `reviews`, `sample_manifests`, `sample_members` | windowed primary with semantic validation (returned timestamps ∈ requested window); per-window cursor fallback under a feasibility bound (estimated depth vs the rate budget → skip-and-disclose); per-window provenance |
| 7 | Classification | `pipeline` loop → `core/classify` + `llm_client` (CLASSIFY) | reviews → `PerReviewLabel[]`, origin=survey, keyed (review, model, prompt, ontology versions) | label pool; content-keyed cache — bought labels never re-paid | atomic budget counter (reserve before dispatch); English-first filter; review text in a delimited data channel, output parsed against a closed schema |
| 8 | Aggregation | `core/aggregate` | manifest + label pool + version pin → `AspectAggregate[]` | `aggregates` | folds manifest members ∩ origin=survey ∩ pinned version only — the number mint's one door; evidence floor |
| 9 | Investigation (the investigator milestone, M4) | see the loop below | events + survey signals → explained / withheld / unexplained | `investigation_rounds` | round cap, per-query budget, language guard, manifest-less types |
| 10 | Compose + phrase | `core/compose` + `llm_client` (PHRASE) | aggregates + events + manifest → `ReportDocument` | `reports` (cache write) | quote grounding; numeric grounding (every numeral in prose matches a cited value); unreferenced claims refused; marked-window membership derived here at read time from the freshest `past_events`; the marked-share floor; weak evidence greyed, never dropped |
| 11 | Serve | `serve` | report → REST; narration → SSE | — | typed at-capacity errors become the honest degraded state; quotes rendered as text, never HTML |

**The investigation loop, one round** (hard-capped per query): signals → ranked
hypothesis (`core/investigate`, narrated as a hypothesis by type) → targeted
`fetch_window` (manifest-less by construction, same rate bucket as the survey) →
window reviews classified with origin=investigation (never foldable) → verification
(`core/investigate`; counts stay scoped — "62 of 80 fetched from this window", a
`WindowEvidence` value with no path into an aggregate) → verdict, where a *finding*
narration event is constructible only from a verified conclusion and the language
guard yields "explanation withheld" with its stated reason.

**The offline runs — same core, different shells** (DESIGN: the system flow; this is
the offline/runtime unification made concrete):

    corpus labeling (M1) ──► corpus source (local_corpus manifests) ──► the same classify stages ──► label pool
    eval runs (M1)       ──► gold set (versioned files) + judge stage ──► metrics ──► EvalRunManifest
    resampling study (M2)──► the same plan compiler over the corpus ──► simulated manifests
                             ──► re-fold stored labels with the same aggregate ──► policy + interval method + tolerance
    CI (prompt/config changes) ──► eval suite ──► run manifest + trend vs tolerance bands
                             (metric drift annotates — the soft gate; harness errors fail)

*Eval-run provenance detail (config + model + prompt version + gold-set version → the
measured numbers the docs cite) gets its own diagram when the first artifacts exist at
the extraction+eval milestone (M1).*

## Deliberately not done (restraint)

- No job queue / worker infrastructure until the narrated cold path proves it needs one
  (SSE from a single service is the starting shape; revisit if host request timeouts
  force background jobs).
- No Kubernetes/Terraform/cloud MLOps — per DESIGN's non-goals.
- No hand-maintained API reference — docstrings + pdoc from day one; the rendered
  reference is generated, never edited.
