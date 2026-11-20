"""The serving composition root — environment in, running app out, every seam wired once.

Everything the modules deliberately refuse to own lands here: the credential
read, the one ``SteamTransport`` (one politeness budget per process, by
construction), the DeepSeek provider entry, the runner over the store path,
the job queue, the submit gate over per-call store reads (with its unlock
token), the per-read report lookup, the recommender chat's route with its
turn runner, conversation book and turn gate, and the page renderer attached
over the JSON surface. Run as ``python -m steamlens.serve.main``; every dial
is an environment variable so the containers step overrides without a code
touch. Pulled forward from the containers step (2026-08-08) because the
frontend chunk is look-at-it development — judging rendered pages needs a
running server, and this entry was going to exist anyway.

The ontology pin is explicit v2 by path (the M1 carry: the packaged default
stays v1, gold's identity pin). The report read opens a store per call — the
cached-game bypass is one indexed SELECT, and a per-call open sidesteps every
cross-thread connection question at a cost the read cannot feel.
"""

from __future__ import annotations

import json
import os
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path

import uvicorn
from fastapi import FastAPI

from steamlens.contracts import EvidenceQuote, Report, ReportCard
from steamlens.dispatch import TeeSink, mint_run_id
from steamlens.dispatch.census_arm import KEY_ENV
from steamlens.llm_client import openai_compat_entry
from steamlens.llm_client.openai_compat import DEEPSEEK_BASE_URL
from steamlens.ontology import load_ontology
from steamlens.serve import (
    AnalysisRunner,
    Job,
    JobQueue,
    JobSummary,
    SearchLimiter,
    ServeConfig,
    SubmitGate,
    create_app,
    stage_spans,
)
from steamlens.serve.chat_api import GameLink, attach_chat
from steamlens.serve.chat_gate import TurnGate
from steamlens.serve.chat_turns import TurnRunner
from steamlens.serve.conversations import ConversationBook
from steamlens.serve.gate import utc_day_start
from steamlens.serve.links import report_path
from steamlens.serve.web import OpsData, ReportPageData, attach_web
from steamlens.serve.web.view import header_art
from steamlens.steam_client import SteamClient, SteamClientConfig, SteamTransport
from steamlens.store import Store, utc_isoformat


def build_app() -> FastAPI:
    """The production app off the environment — fail loud before serving a byte.

    The queue's drain-close registers as the app's shutdown handler (lifecycle
    stays with the root, per the queue's contract), and the store opens once
    up front so a fresh database migrates at boot, never inside a request.
    """
    key = os.environ.get(KEY_ENV)
    if not key:
        raise SystemExit(f"missing {KEY_ENV} in the environment — set it and rerun")
    ontology_path = Path(
        os.environ.get("STEAMLENS_ONTOLOGY_PATH", "src/steamlens/ontology/v2.toml")
    )
    if not ontology_path.exists():
        raise SystemExit(
            f"ontology artifact not found at {ontology_path} — production pins v2 "
            "explicitly (set STEAMLENS_ONTOLOGY_PATH)"
        )
    db_path = Path(os.environ.get("STEAMLENS_DB_PATH", "data/serve.db"))
    db_path.parent.mkdir(parents=True, exist_ok=True)
    with Store(db_path):
        pass
    log_path = Path(os.environ.get("STEAMLENS_SERVE_LOG", "data/serve.log"))
    # Line-buffered so a second-pane tail follows the narration live; the
    # handle lives as long as the process, closed by exit like the sink's
    # stdout half.
    sink = TeeSink(log_path.open("a", buffering=1, encoding="utf-8"))

    # The dataclass defaults are the single source of the numbers; the env
    # only ever overrides, so an unset variable can never drift from them.
    config = ServeConfig()
    if (raw_limit := os.environ.get("STEAMLENS_DAILY_JOB_LIMIT")) is not None:
        config = replace(config, daily_job_limit=int(raw_limit))
    if (raw_ip_limit := os.environ.get("STEAMLENS_PER_IP_DAILY_JOB_LIMIT")) is not None:
        config = replace(config, per_ip_daily_job_limit=int(raw_ip_limit))
    if (raw_backstop := os.environ.get("STEAMLENS_DAILY_SPEND_BACKSTOP_USD")) is not None:
        config = replace(config, daily_spend_backstop_usd=float(raw_backstop))
    if (raw_search := os.environ.get("STEAMLENS_SEARCH_PER_MINUTE")) is not None:
        config = replace(config, search_per_minute=int(raw_search))
    if (raw_turns := os.environ.get("STEAMLENS_CHAT_DAILY_TURN_LIMIT")) is not None:
        config = replace(config, chat_daily_turn_limit=int(raw_turns))
    if (raw_ip_turns := os.environ.get("STEAMLENS_CHAT_PER_IP_DAILY_TURN_LIMIT")) is not None:
        config = replace(config, chat_per_ip_daily_turn_limit=int(raw_ip_turns))
    # `or None`: an empty value in .env must mean "no exemption door", never a
    # token an empty cookie could match. The ascii check is the boot-time half
    # of the gate's guard: compare_digest raises on non-ascii, so a non-ascii
    # token would break every unlock at request time — fail here instead.
    admin_token = os.environ.get("STEAMLENS_ADMIN_TOKEN") or None
    if admin_token is not None and not admin_token.isascii():
        raise SystemExit(
            "STEAMLENS_ADMIN_TOKEN must be ascii — the constant-time compare "
            "rejects anything else, which would break every unlock"
        )
    steam = SteamClient(SteamTransport(SteamClientConfig(), sink))
    entry = openai_compat_entry(key, base_url=DEEPSEEK_BASE_URL)
    runner = AnalysisRunner(config, steam, entry, db_path, ontology_path)

    def settle_job(
        run_id: str, job: Job, outcome: str, error: str | None, summary: JobSummary | None
    ) -> None:
        # Stage timings derive from the narration the job already collected —
        # the journal's ETA-calibration payload, approximate and declared so.
        timings = json.dumps({
            stage: [utc_isoformat(first), utc_isoformat(last)]
            for stage, (first, last) in stage_spans(job.timed_events()).items()
        })
        with Store(db_path) as store:
            store.jobs.settle(
                run_id,
                at=datetime.now(UTC),
                outcome=outcome,
                error=error,
                labeled=summary.labeled if summary else None,
                reused=summary.reused if summary else None,
                failed_durable=summary.failed_durable if summary else None,
                refused_batches=summary.refused_batches if summary else None,
                stage_timings_json=timings,
            )

    def run_job(job: Job) -> None:
        # The job-journal wrapper (DESIGN: the job journal): the row's run id
        # is minted BEFORE the pipeline so jobs, reports, and ledger
        # attribution share one key; an escaping exception settles the row
        # failed and re-raises — the queue's own failure handling unchanged.
        started = datetime.now(UTC)
        run_id = mint_run_id("serve", started)
        with Store(db_path) as store:
            store.jobs.start(run_id, job.app_id, job.requested_name, at=started)
        try:
            summary = runner.run(job.app_id, job.requested_name, job, run_id=run_id)
        except BaseException as exc:
            settle_job(run_id, job, "failed", f"{type(exc).__name__}: {exc}", None)
            raise
        settle_job(run_id, job, "done", None, summary)

    def latest_report(app_id: int) -> Report | None:
        with Store(db_path) as store:
            return store.reports.latest_report(app_id)

    def load_report_page(app_id: int) -> ReportPageData | None:
        with Store(db_path) as store:
            report = store.reports.latest_report(app_id)
            if report is None:
                return None
            evidence = tuple(
                EvidenceQuote(
                    review_id=review_id, aspect=aspect, sentiment=sentiment, text=text
                )
                for review_id, aspect, sentiment, text in (
                    store.labels.iter_member_evidence(report.run.run_id, report.versions)
                )
            )
            return ReportPageData(
                report=report,
                aggregates=store.reports.get_snapshot(report.run.run_id),
                evidence=evidence,
                aspect_bearing_reviews=store.labels.count_members_with_mentions(
                    report.run.run_id, report.versions
                ),
                quoted_reviews=store.reviews.get_many(
                    {quote.review_id for quote in evidence}
                ),
            )

    def load_report_cards() -> tuple[ReportCard, ...]:
        with Store(db_path) as store:
            return store.reports.cards()

    def published_names() -> dict[int, str]:
        with Store(db_path) as store:
            return store.reports.published_names()

    def chat_report_links() -> dict[int, GameLink]:
        # The chat's cards and links, one per published game. The header art
        # is the renderer's rule (the stored Steam URL, else the minted
        # fallback), so it is applied here at the root and the chat's JSON
        # surface only passes the address on.
        return {
            card.app_id: GameLink(
                title=card.game_name,
                url=report_path(card.app_id, card.game_name),
                image_url=header_art(card.header_image, card.app_id),
            )
            for card in load_report_cards()
        }

    def admitted_since(since: datetime) -> int:
        with Store(db_path) as store:
            return store.admissions.count_since(since)

    def admitted_from_since(ip: str, since: datetime) -> int:
        with Store(db_path) as store:
            return store.admissions.count_from_since(ip, since)

    def spent_since(since: datetime) -> float:
        with Store(db_path) as store:
            return store.spend_ledger.cost_since(since)

    def record_admission(ip: str, app_id: int, at: datetime) -> None:
        with Store(db_path) as store:
            store.admissions.record(ip, app_id, at=at)

    def record_refusal(kind: str, at: datetime) -> None:
        with Store(db_path) as store:
            store.refusals.record(kind, at=at)

    def record_report_view(run_id: str) -> None:
        with Store(db_path) as store:
            store.report_views.record(run_id, at=datetime.now(UTC))

    def load_ops_data() -> OpsData:
        # One clock reading for the whole page: the "today" reads and the
        # generated-at stamp tell one story. 14 days of history is the dial
        # the ops view's daily table names in its title.
        now = datetime.now(UTC)
        day = utc_day_start(now)
        since = day - timedelta(days=13)
        with Store(db_path) as store:
            return OpsData(
                now=now,
                admissions_today=store.admissions.count_since(day),
                daily_job_limit=config.daily_job_limit,
                per_ip_daily_job_limit=config.per_ip_daily_job_limit,
                spend_today_usd=store.spend_ledger.cost_since(day),
                daily_spend_backstop_usd=config.daily_spend_backstop_usd,
                daily_ledger=store.ops.daily_ledger(since),
                daily_admissions=store.ops.daily_admissions(since),
                stage_model=store.ops.stage_model_totals(),
                report_count=store.ops.report_count(),
                daily_refusals=store.ops.daily_refusals(since),
                jobs=store.ops.recent_jobs(20),
                stage_latencies=store.ops.stage_latencies(),
                unjournaled=store.ops.unjournaled_totals(),
            )

    def database_ok() -> bool:
        # The health check's store probe: opening runs the pragmas and the
        # migration check, so "opens" means "usable at the current schema".
        # Broad catch is the point — any failure IS the unhealthy answer,
        # surfaced as the 503 the pinger alerts on, never swallowed.
        try:
            with Store(db_path):
                return True
        except Exception:
            return False

    queue = JobQueue(run_job)
    gate = SubmitGate(
        daily_job_limit=config.daily_job_limit,
        per_ip_daily_job_limit=config.per_ip_daily_job_limit,
        daily_spend_backstop_usd=config.daily_spend_backstop_usd,
        has_live_from=queue.has_live_from,
        admitted_since=admitted_since,
        admitted_from_since=admitted_from_since,
        spent_since=spent_since,
        record_admission=record_admission,
        record_refusal=record_refusal,
        admin_token=admin_token,
    )
    app = create_app(
        queue,
        config,
        latest_report,
        steam.search_games,
        gate=gate,
        search_limiter=SearchLimiter(
            config.search_per_minute, record_refusal=record_refusal
        ),
        published_names=published_names,
        resolve_name=steam.store_name,
        database_ok=database_ok,
        on_shutdown=[queue.close],
    )
    ontology = load_ontology(ontology_path)
    # The recommender chat's one route. It shares three things with the
    # report flow on purpose: the provider entry, the day's spend wall (the
    # same ledger read), and the operator's unlock cookie. Its conversations
    # and its counts live in this process's memory and end with it.
    attach_chat(
        app,
        TurnRunner(entry, db_path, ontology, config.chat_turn_budget_usd, sink),
        ConversationBook(
            max_turns=config.chat_turns_per_conversation,
            max_open=config.chat_max_open_conversations,
            idle_expiry=timedelta(minutes=config.chat_idle_expiry_minutes),
        ),
        TurnGate(
            daily_turn_limit=config.chat_daily_turn_limit,
            per_ip_daily_turn_limit=config.chat_per_ip_daily_turn_limit,
            turns_in_flight=config.chat_turns_in_flight,
            daily_spend_backstop_usd=config.daily_spend_backstop_usd,
            spent_since=spent_since,
            record_refusal=record_refusal,
        ),
        config,
        chat_report_links,
        sink,
        is_exempt=gate.is_exempt,
    )
    # The tag-coloring map reads the same pinned artifact the runner labels
    # with, so the library's families can never disagree with the vocabulary
    # that minted the tags.
    aspect_categories = {aspect.label: aspect.category for aspect in ontology.aspects}
    attach_web(
        app,
        load_report_page,
        lambda app_id: queue.live(app_id) is not None,
        load_ops_data,
        load_report_cards,
        aspect_categories,
        record_report_view=record_report_view,
        chat_message_max_chars=config.chat_message_max_chars,
    )
    return app


def main() -> None:
    """Serve on the env-dialed host and port — the dev entry the containers step reuses."""
    uvicorn.run(
        build_app(),
        host=os.environ.get("STEAMLENS_HOST", "127.0.0.1"),
        port=int(os.environ.get("STEAMLENS_PORT", "8000")),
    )


if __name__ == "__main__":
    main()
