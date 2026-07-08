# ARCHITECTURE — steam-lens

How it's built and why that structure — a narrative snapshot, edited in place, growing
with the build. Decisions and their rationale → DESIGN (cited by name); the pitch →
README.

*Pre-build snapshot: committed structural intents only · last updated 2026-07-07 · no
modules exist yet — sections fill in as milestones land (M0–M4).*

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
  split).
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

*To be filled as modules come into existence (extraction+eval, M1, onward). Planned seams: `steam_client`
(lifted-and-adapted from the frozen steam-reviews pipeline — see DESIGN: copy-and-adapt
reuse) · `llm_client` · survey pipeline · investigator · report composer · serving
shell · eval harness (a first-class module, not a script pile).*

## The life of a run

*To be diagrammed when the first artifacts exist (extraction+eval, M1): eval runs and
their provenance
(config + model + prompt version + gold-set version → measured numbers the docs cite).*

## Deliberately not done (restraint)

- No job queue / worker infrastructure until the narrated cold path proves it needs one
  (SSE from a single service is the starting shape; revisit if host request timeouts
  force background jobs).
- No Kubernetes/Terraform/cloud MLOps — per DESIGN's non-goals.
- No hand-maintained API reference — docstrings + pdoc from day one; the rendered
  reference is generated, never edited.
