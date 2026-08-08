"""The serving composition root — environment in, running app out, every seam wired once.

Everything the modules deliberately refuse to own lands here: the credential
read, the one ``SteamTransport`` (one politeness budget per process, by
construction), the DeepSeek provider entry, the runner over the store path,
the job queue, the per-read report lookup, and the page renderer attached
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

import os
from pathlib import Path

import uvicorn
from fastapi import FastAPI

from steamlens.contracts import EvidenceQuote, Report
from steamlens.dispatch import TeeSink
from steamlens.dispatch.census_arm import KEY_ENV
from steamlens.llm_client import openai_compat_entry
from steamlens.llm_client.openai_compat import DEEPSEEK_BASE_URL
from steamlens.serve import AnalysisRunner, Job, JobQueue, ServeConfig, create_app
from steamlens.serve.web import ReportPageData, attach_web
from steamlens.steam_client import SteamClient, SteamClientConfig, SteamTransport
from steamlens.store import Store


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

    config = ServeConfig()
    steam = SteamClient(SteamTransport(SteamClientConfig(), sink))
    entry = openai_compat_entry(key, base_url=DEEPSEEK_BASE_URL)
    runner = AnalysisRunner(config, steam, entry, db_path, ontology_path)

    def run_job(job: Job) -> None:
        runner.run(job.app_id, job.requested_name, job)

    def latest_report(app_id: int) -> Report | None:
        with Store(db_path) as store:
            return store.reports.latest_report(app_id)

    def load_report_page(app_id: int) -> ReportPageData | None:
        with Store(db_path) as store:
            report = store.reports.latest_report(app_id)
            if report is None:
                return None
            return ReportPageData(
                report=report,
                aggregates=store.reports.get_snapshot(report.run.run_id),
                evidence=tuple(
                    EvidenceQuote(
                        review_id=review_id, aspect=aspect, sentiment=sentiment, text=text
                    )
                    for review_id, aspect, sentiment, text in (
                        store.labels.iter_member_evidence(report.run.run_id, report.versions)
                    )
                ),
            )

    queue = JobQueue(run_job)
    app = create_app(
        queue, config, latest_report, steam.search_games, on_shutdown=[queue.close]
    )
    attach_web(app, load_report_page, lambda app_id: queue.live(app_id) is not None)
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
