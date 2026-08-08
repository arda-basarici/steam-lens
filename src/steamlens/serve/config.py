"""The serving runner's dials — the numbers the design ruled tunable, in one place.

Structure now, numbers later (the deployment ruling): the runner's spine —
overlap seam, serialization, the retry ladder — is architecture and lives in
code; everything a deployed timing might legitimately move is here, each
default carrying the evidence it was set from. The skeleton's own narration
timings are the instrument that tunes these.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class ServeConfig:
    """One serving process's runner dials.

    ``take_all_cutoff`` and ``sample_target`` are the sampling study's (M2)
    shipped size rule — take all at pool ≤ 2,000, otherwise sample n = 1,000
    time-proportional — certified held-out by the closing test, so changing
    either is a re-ruling, not a tune. ``batch_n`` is the certified reviews-
    per-request (N=10, the census dispatch config). ``classify_workers``
    paces the classify leg: the census dispatched at 10 and the provider
    tolerated 30, so 10 is evidence-backed headroom, not a guess.
    ``job_budget_usd`` caps one job's spend the same way every dispatch
    driver caps a run's — a public-facing job must not be an unbounded
    buy (a 2,000-review take-all prices ~$0.12 at census rates, so 1.00
    is an order-of-magnitude ceiling, no legitimate job approaches it).
    ``window_buffer`` bounds the fetch→classify hand-off queue, in windows:
    the producer stalls rather than racing unboundedly ahead of a slow
    classify leg. ``fetch_page_budget`` caps one job's planned fetch cost, in
    pages: a take-all whose pool implies more degrades to the sampling branch
    (disclosed), and a sampled plan over it is refused loudly. The default's
    shape: a sampled plan's floor cost is one page per populated histogram
    bucket (~190 for a monthly-rollup veteran, hundreds for weekly-served
    long-lived games), so 600 admits every realistic plan while capping a
    job's fetch leg at ~15 minutes of pacing floor — a box-safety ceiling,
    not a tuning. ``sse_tick_s`` is the SSE follower's poll cadence over a
    job's event history: narration lands at seconds scale, so a quarter-second
    tick is invisible to a viewer and costs one snapshot per tick per viewer.
    ``sse_heartbeat_s`` paces the keep-alive comments on a quiet stream —
    it only needs to sit safely under proxy idle timeouts (minutes-scale for
    the Caddy front), and 15 s is the conventional SSE keep-alive.
    ``compose_floor`` is the evidence floor the narrative applies at compose
    time (the stored aggregate stays a faithful tally): below ~5 distinct
    reviews of a 1,000-sample a share is noise dressed as signal, so such
    aspects stay out of the prompt. ``compose_quotes_per_aspect`` and
    ``compose_max_themes`` bound what the prompt offers — a couple of verbatim
    spans per aspect, a handful of candidate theme names (names only, never
    numbers); all three get judged against real rendered reports at the
    frontend step. ``daily_job_limit`` is the submit gate's public allowance
    of fresh analyses per UTC day, counted at admission (a count cannot be
    burst past the way a settling dollar total can): observed live jobs price
    $0.01–0.02, so 5 is a ~$0.10 typical day, and the hostile ceiling stays
    limit × ``job_budget_usd``. ``daily_spend_backstop_usd`` is the second,
    silent refusal condition on the ledger's *settled* spend for the day —
    the runaway-day guard for jobs running hot toward their per-job cap, not
    a burst guard. Both are env dials at the composition root
    (``STEAMLENS_DAILY_JOB_LIMIT``, ``STEAMLENS_DAILY_SPEND_BACKSTOP_USD``):
    spend comfort is an ops setting, not a code commit.
    """

    take_all_cutoff: int = 2_000
    sample_target: int = 1_000
    batch_n: int = 10
    classify_workers: int = 10
    job_budget_usd: float = 1.0
    window_buffer: int = 2
    fetch_page_budget: int = 600
    sse_tick_s: float = 0.25
    sse_heartbeat_s: float = 15.0
    compose_floor: int = 5
    compose_quotes_per_aspect: int = 2
    compose_max_themes: int = 5
    daily_job_limit: int = 5
    daily_spend_backstop_usd: float = 1.0
