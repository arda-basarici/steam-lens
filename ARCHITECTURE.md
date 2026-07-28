# ARCHITECTURE — steam-lens

How it's built and why that structure — a narrative snapshot, edited in place.
Decisions and their rationale → [DESIGN.md](DESIGN.md) (cited by name); the pitch →
[README.md](README.md).

*Snapshot of the build in progress · last updated 2026-07-28 · the extraction+eval
milestone (M1) is built and review-hardened; the sampling study (M2), deployment (M3),
and the chat milestone (M4) exist here only as declared ranks and recorded triggers.*

---

## Design shape

Five ranks, imports strictly downward, enforced by a CI test (below). The entry shells
at the top compose everything; nothing composes them.

```
  studies · evals            (4)  entry shells — import-forbidden to all other code
        │
        ▼
  dispatch                   (3)  generic run machinery the entry shells compose
        │
        ▼
  corpus · steam_client ·    (2)  the doors and loaders: frozen snapshot, live Steam,
  llm_client · store ·            LLM providers, SQLite, the ontology artifact
  ontology
        │
        ▼
  core                       (1)  pure transforms: normalize · classify · aggregate
        │
        ▼
  contracts                  (0)  the plain-data spine; imports nothing
```

The data flow those ranks carry today — the extraction+eval engine end to end:

```
  corpus files (frozen steam-reviews snapshot, on disk)
        │
        ▼
  corpus/ reader ──► studies/label_corpus ──► core/classify prompt/parse
        │                                          │
        │                                          ▼
        │                                    llm_client (CLASSIFY route)
        │                                          │
        ▼                                          ▼
  store: reviews table          label pool · response archive · spend ledger
        │
        ▼
  core/aggregate (survey-origin ∩ pinned version) ──► per-game aspect aggregates
        │
        ▼
  eval/gold artifact ──► evals: certify · judge calibration · agreement ·
                         registered experiments ──► eval-run journal + CI gate
```

The rules, stated once:

- **The dependency law fails closed.** The import-graph test asserts the rank table on
  every build — and refuses to fail open: every package under `src` must declare a rank
  to exist, relative imports are banned wholesale, and the entry shells (`evals`,
  `studies`) are import-forbidden to everything. A misplaced import is a red build,
  never a review finding.
- **The two-track rule.** Every envelope carries an `Origin` tag and the number mint
  folds survey-origin members under the pinned version only — the only door to a
  displayed number. Today every label is survey-origin; a distinct eval origin is
  parked with its trigger (DESIGN's parked decisions) for when anything non-census
  nears the fold. The investigator track is deferred whole (DESIGN: the roadmap
  redirect) — no investigation machinery exists in this tree.
- **One door to Steam.** All live access goes through `steam_client`: one paced,
  retried GET chokepoint under every operation, identity guarded, provenance-reporting
  (DESIGN: one sampler module owns all review access).
- **One door to models.** All LLM calls go through `llm_client`: per-stage routing,
  an atomic budget reserve before dispatch, typed failures, and the content-keyed
  response archive — a bought response is never re-paid (DESIGN: the tier deferral,
  made safe).
- **Functional core, effects at the shell.** `core` is pure transforms over
  `contracts` records; every I/O lives at rank 2; the entry shells only compose.
- **Narration is a seam, not a habit.** Producers depend on the one-method `Sink`
  protocol from `contracts`; each running context binds its own sink (the drivers'
  tee'd log, ad-hoc collectors in tests). Observability is structural, not retrofitted.

### The life of a run

Every dispatch run — census, judge, experiment cell — is regenerable from its manifest,
and resumable by construction:

```
  RunConfig (the resolved dial)
        │
        ├── mint_run_id · code_version · config_hash   (dispatch/stamp)
        ▼
  Provenance record ──► runs/<run_id>/ opened by dispatch/run_context:
        │                 run.log (line-buffered, tee'd to console — tail it live)
        │                 two Store connections (client writes on worker threads,
        │                 driver writes on the main thread; WAL carries coordination)
        ▼
  resume-clean selection (an envelope or durable failure mark closes a review)
        ▼
  batch passes ──► LLM door ──► envelopes + archived responses + ledger rows
        ▼
  build_manifest ──► runs/<run_id>/manifest.json   (true counts even when aborted)
```

The eval side closes the provenance loop in CI: the committed `eval/ci/` fixture holds
the runs of record, and the gate regenerates their scores on every build — an
exact-digit mismatch fails; the deliberate-change path is a scorer-string bump plus
pin re-export (DESIGN: the evals-in-CI gate).

## Module responsibilities

One line per module; field detail and contracts live in the docstrings (pdoc renders
the reference — regen script committed, output never hand-edited).

| module | single job |
| --- | --- |
| `contracts/` | the frozen-dataclass records crossing every seam (review · classification envelope + mention · aggregate · ontology + version stamp · provenance two-layer · LLM request/response · Steam door records · eval run/metric) + the enums + the `Sink` narration protocol |
| `core/normalize` | two-slot label resolution: surface index over the pinned vocabulary, conservative match keys, candidates preserved in reviewer wording |
| `core/classify` | the versioned classify prompt build + strict response parse with per-idx salvage — the LLM call itself stays in the shell |
| `core/aggregate` | the number mint: label pool + scope → per-game aspect aggregates, raw tallies only |
| `ontology/` | the artifact loader + the versioned TOML codebooks (`v1` — gold's identity pin and packaged default; `v2` — the current codebook, pinned by explicit path) |
| `corpus/` | the frozen-snapshot reader beside the live door: usable filter, drop arithmetic, the door's own record parser (imported, never forked) |
| `steam_client/` | the live door: paced/retried transport chokepoint · wire parsers · identity guard · the shared walk engine with cursor fallback · feasibility estimate · the three-operation client |
| `llm_client/` | the model door: stage routing + budget/pacing config · the client (reserve, retries, cache/ledger composition) · Gemini and OpenAI-compat adapters · typed failures · in-memory bindings for rigs |
| `store/` | SQLite (WAL): schema + gated migrations · review/label/archive/ledger/eval-run surfaces · row converters + the published timestamp codec |
| `dispatch/` | generic run machinery, study-blind: tee'd narration sink + the one stage emitter · RunAbort + the drift watch · run/config/code stamps · the run-shell context · the chunk/pass batch engine — plus `census_arm`, the production annotator as a citable instrument |
| `studies/` | offline entry shells: the census labeling driver (`label_corpus`) and the aggregate minter (`aggregate_corpus`) |
| `evals/` | the certification harness: gold loader · pure scoring + bootstrap · the certify shell · the judge instrument + its two dispatch shells · the agreement scorer · the registered-experiments driver · the CI fixture exporter/gate |

Declared ahead of their milestones, rank reserved but no code: `pipeline` and `serve`
(deployment, M3 — report composition and the web runtime), `cli`, `core/sampling` (the
sampling study, M2), `core/detect` (display-only episode markers at M3), and the chat
milestone's retrieval modules (M4 — DESIGN: the RAG chat product frame).

## Structural stories

### The law is executable architecture, and it grew teeth after paying for it

The rank table began as documentation with a test; the full-base review (2026-07-27)
found the test blessing exactly the erosion it existed to stop — two entry shells
shared a rank, so `evals` imported eight names from the census driver's interior with a
green build, and unranked packages or relative imports were simply invisible. The
architecture pass inverted that: the shared machinery moved down into `dispatch`, the
misfiled reader moved to `corpus`, and only then was the law tightened to match —
entry shells import-forbidden, rank declaration a precondition of existence, relative
imports banned. Order mattered: the law locks the shape that should exist, not the one
that happened to.

### Drivers are composition roots; the machinery exists once

Four dispatch drivers (census, two judge shells, the experiment cells) once carried
private copies of the same run shell, batch engine, and stage emitter — and the copies
had measurably drifted. Now `dispatch` owns each mechanism once: `run_context` opens
the run directory, the tee'd log, and the deliberate two-connection store split (the
two-writer reasoning stated once, there); one `run_pass` engine dispatches
pre-composed batches and consumes outcomes as futures finish; the stamps mint identity.
What deliberately did **not** unify is policy: each driver keeps its own abort ladder,
manifest payload, retry semantics (the census's isolate pass vs the cells'
condition-purity), and outcome writer — a shared `Driver` framework was declined
because it would turn those real differences into callback plumbing.

### Two instrument blocks name the annotators

The production model's identity (`dispatch/census_arm`) and the judge's
(`evals/judge_dispatch`) are symmetric instrument blocks: model id, provider, prices,
generation config, and the client builder in one citable place each. Certification and
the agreement read import "the production model under judgment" as an instrument —
not a constant fished out of the labeling driver — and the D2d cells re-dispatch the
same instrument under controlled conditions without touching the driver that bought
the census.

### Certification consumes the system, never the reverse

`evals` sits at the top rank and is import-forbidden: the harness reads the same label
pool, the same ontology artifacts, and the same scoring core the production path uses,
and nothing in the production path can reach back into it. Gold is provider-neutral by
construction (minted before the bake-off chose the labeler), the judge is a second
annotator rather than a verifier (DESIGN: the judge design), and the CI gate re-scores
the committed runs of record to exact digits — so a quiet change to any scoring input
is a red build, not a drifted number.

### The label pool never pays twice

Resume is not a feature bolted onto the drivers; it falls out of three seams. The
response archive is content-keyed (model · prompt · ontology · text), so a relaunched
run's identical request is answered from disk; the selection query treats an envelope
or a durable failure mark as closing a review under its versions triple, so a
relaunch selects only what never settled; and the spend ledger journals every paid
call, so cost claims are read from the record, not inferred. The census was bought
once under this shape and every eval dispatch since has inherited it.

## Toolchain & layout

Python **3.13**, `src/steamlens/` **src-layout** (forces a real editable install);
**uv** for resolve + lock. Gates on every change: **ruff check** (lint only — code is
hand-formatted to house style; the formatter is deliberately unused), **pyright
`--strict`** (editor parity with Pylance), **pytest** with `--doctest-modules`, the
import-graph law, and the exact-digit eval gate over the committed fixture. **pdoc**
renders the API reference from docstrings; the regen script is committed, the output
is generated only.

## Deliberately not done (restraint)

- **No driver framework.** The shared machinery is functions and one context manager,
  not a base class — revisit only if a third batch-labeling driver makes the per-driver
  policy itself start duplicating.
- **No `pipeline/` package yet.** Stage composition lives in the entry shells; the
  reserved rank fills when the web runtime (deployment, M3) needs the same
  compositions the offline drivers use.
- **No investigation machinery.** The investigator was deferred whole at the roadmap
  redirect (DESIGN); `core/detect` returns at M3 as display-only episode markers, and
  the chat milestone (M4) gets its own architecture pass when it approaches.
- **No job queue / worker infrastructure.** A single narrated process is the starting
  shape; revisit if the deployed cold path hits host request timeouts (M3).
- **No hand-maintained API reference.** Docstrings + pdoc from day one.
