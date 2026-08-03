"""Discover the long-tail game list and snapshot its histograms — stage 2's collector.

The long-tail frame checks (DESIGN, the study-design section) need a game list
nobody hand-picked: a hand-chosen list invites the selection-bias critique the
stage exists to answer. So discovery is criteria-driven by construction — a
seeded uniform probe over a persisted snapshot of Steam's full app list,
admitting a candidate exactly when the store calls it a game and its
whole-game, all-language review total lands in an open list band
(``studies.frame.list_band``: the take-all tail, the band where the size rule
engages, and the bridge toward corpus scale). The seed, the snapshot, and the
probe order are all recorded, so the same invocation reproduces the same list.

On admission the collector takes the two label-free snapshots the analyzer
needs: the live review histogram — the production instrument, persisted as the
raw wire payload (the irreproducible external snapshot; parsed views are
derivable) — and a one-request English-totals read, carried as metadata for
the fresh-buy session's picks (step 8 draws its games from this list). A
seeded handful of corpus games gets the same live histogram fetch, so the
analyzer can measure instrument agreement between the live histogram and the
corpus-built one before comparing regimes across them.

Composition note: everything speaks through one ``SteamTransport`` — one
politeness budget, per the door's own one-client rule. The door's operations
don't answer the applist or the appdetails ``type`` field (production never
asks), so this shell composes the transport and the exported parsers directly
rather than widening ``SteamClient`` for a study-only read; the two wire
shapes the door doesn't parse are read by script-local helpers with the same
boundary discipline. A candidate whose payload is damaged is logged and
skipped, never silently dropped and never fatal — but an exhausted retry
budget (Steam unreachable) aborts the run, with the manifest recording the
true progress.

Run from the repo root (defaults: 6 true-tail / 14 engaging / 4 bridge,
probe budget 1,200):
  uv run python scripts/discover_longtail_games.py
Reuse a prior run's applist snapshot (skips one large fetch):
  uv run python scripts/discover_longtail_games.py --applist data/longtail/<run>/applist.json
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import random
from collections.abc import Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import Final, TextIO, cast

from steamlens.contracts import Sink, StageKind
from steamlens.dispatch.narration import TeeSink, narrate
from steamlens.dispatch.run_shell import write_manifest
from steamlens.dispatch.stamp import code_version, config_hash, mint_run_id
from steamlens.steam_client import (
    SteamClientConfig,
    SteamResponseError,
    SteamTransport,
    parse_histogram,
    parse_review_page,
)
from steamlens.studies.frame import ListBand, list_band

_STAGE: Final = "m2.longtail.discover"

# The keyed catalogue endpoint — Valve retired the keyless
# ISteamApps/GetAppList in March 2026 (verified from two networks, 2026-08-03);
# IStoreService is the community-confirmed replacement and filters games-only
# at the source. The key crosses only the process environment.
_APPLIST_URL: Final = "https://api.steampowered.com/IStoreService/GetAppList/v1/"
_APPDETAILS_URL: Final = "https://store.steampowered.com/api/appdetails"
_REVIEWS_URL: Final = "https://store.steampowered.com/appreviews/{app_id}"
_HISTOGRAM_URL: Final = "https://store.steampowered.com/appreviewhistogram/{app_id}"

# The same bias-avoiding base the door's totals read uses: unfiltered, with
# the off-topic filter disabled (the proven data-integrity bug).
_TOTALS_BASE: Final[dict[str, str | int]] = {
    "json": 1,
    "purchase_type": "all",
    "review_type": "all",
    "filter_offtopic_activity": 0,
    "num_per_page": 0,
}

DEFAULT_TARGETS: Final[dict[ListBand, int]] = {
    ListBand.TRUE_TAIL: 6,
    ListBand.ENGAGING: 14,
    ListBand.BRIDGE: 4,
}
DEFAULT_PROBE_BUDGET: Final = 1_200
DEFAULT_SEED: Final = 20260803
DEFAULT_SWEEP_RUN: Final = Path("data/runs/m2sweep-20260802T132010Z-2969bcab")
DEFAULT_CORPUS_CHECK: Final = 5


def fetch_applist(transport: SteamTransport, path: Path) -> list[tuple[int, str]]:
    """Fetch and persist the games-only catalogue; returns (app_id, name) pairs.

    The snapshot is the probe's sampling frame — the raw pages are persisted
    as fetched so the run's selection is re-drawable, and validated here
    because the door has no applist parser (production never asks). Pages by
    ``last_appid`` until Steam reports no more results; the API key comes
    from the process environment and lands in no artifact — the pages carry
    only response bodies, and the transport's failure messages name the base
    URL without params.
    """
    key = os.environ.get("STEAM_WEB_API_KEY")
    if not key:
        raise SystemExit(
            "STEAM_WEB_API_KEY is not set in this process environment — "
            "bridge it from the User registry scope per api-key-onboarding"
        )
    pages: list[Mapping[str, object]] = []
    last_appid = 0
    while True:
        payload = transport.get_json(_APPLIST_URL, {
            "key": key,
            "include_games": "true",
            "include_dlc": "false",
            "include_software": "false",
            "include_videos": "false",
            "include_hardware": "false",
            "max_results": 50_000,
            "last_appid": last_appid,
        })
        response = _object(payload.get("response"), "applist response")
        pages.append(payload)
        if len(pages) > 20:
            raise SteamResponseError("applist: more than 20 pages — pagination is looping")
        if not response.get("have_more_results"):
            break
        more = response.get("last_appid")
        if isinstance(more, bool) or not isinstance(more, int):
            raise SteamResponseError(f"applist: last_appid is {more!r}, expected an integer")
        last_appid = more
    snapshot: dict[str, object] = {"pages": pages}
    path.write_text(json.dumps(snapshot), encoding="utf-8")
    return _applist_pairs(snapshot)


def load_applist(path: Path) -> list[tuple[int, str]]:
    """(app_id, name) pairs from a previously persisted applist snapshot."""
    payload = json.loads(path.read_text(encoding="utf-8"))
    return _applist_pairs(_object(payload, "applist snapshot"))


def _applist_pairs(payload: Mapping[str, object]) -> list[tuple[int, str]]:
    raw_pages = payload.get("pages")
    if not isinstance(raw_pages, list):
        raise SteamResponseError("applist snapshot: missing pages list")
    pairs: list[tuple[int, str]] = []
    for raw_page in cast("list[object]", raw_pages):
        response = _object(_object(raw_page, "applist page").get("response"), "applist response")
        apps = response.get("apps")
        if apps is None:
            continue  # a terminal page may answer without an apps list
        if not isinstance(apps, list):
            raise SteamResponseError("applist: apps is not a list")
        for item in cast("list[object]", apps):
            entry = _object(item, "applist app entry")
            app_id, name = entry.get("appid"), entry.get("name")
            if isinstance(app_id, bool) or not isinstance(app_id, int) or not isinstance(name, str):
                raise SteamResponseError(f"applist: malformed entry {entry!r}")
            pairs.append((app_id, name))
    return pairs


def _object(value: object, context: str) -> Mapping[str, object]:
    """``value`` as a JSON object, or the typed shape failure — parse.py's discipline."""
    if not isinstance(value, Mapping):
        raise SteamResponseError(f"{context} is {type(value).__name__}, expected an object")
    return cast("Mapping[str, object]", value)


def appdetails_entry(
    transport: SteamTransport, app_id: int
) -> tuple[str, str, str | None] | None:
    """The store's (type, name, release date) for ``app_id``, or ``None`` on no data.

    Script-local wire knowledge: the door's appdetails parser answers only the
    name — its production question — and admission here needs the ``type``
    field, so this helper reads the same payload with the same boundary
    discipline instead of widening the door for a study-only read.
    """
    payload = transport.get_json(
        _APPDETAILS_URL, {"appids": app_id, "cc": "us", "l": "english"}
    )
    raw_entry = payload.get(str(app_id))
    if raw_entry is None:
        return None  # JSON-null entry: a delisted or invalid id — no data, calmly
    entry = _object(raw_entry, f"appdetails[{app_id}]")
    if not entry.get("success") or entry.get("data") is None:
        return None
    data = _object(entry.get("data"), f"appdetails[{app_id}].data")
    app_type, name = data.get("type"), data.get("name")
    if not isinstance(app_type, str) or not isinstance(name, str) or not name:
        raise SteamResponseError(
            f"appdetails[{app_id}]: type/name are {app_type!r}/{name!r}, expected strings"
        )
    raw_release = data.get("release_date")
    release_date = None
    if raw_release is not None:
        release_date = _object(raw_release, f"appdetails[{app_id}].release_date").get("date")
    return app_type, name, release_date if isinstance(release_date, str) else None


def review_totals(transport: SteamTransport, app_id: int, language: str) -> int | None:
    """Steam's whole-game review total under ``language``, ``None`` when unreported."""
    payload = transport.get_json(
        _REVIEWS_URL.format(app_id=app_id), {**_TOTALS_BASE, "language": language}
    )
    summary = parse_review_page(payload, app_id).summary
    return summary.total_reviews if summary else None


def snapshot_histogram(transport: SteamTransport, app_id: int, out_dir: Path) -> None:
    """Fetch, validate, and persist one live histogram as its raw wire payload.

    Parsing before persisting keeps the boundary discipline — a damaged
    payload fails here, at fetch time, not in the analyzer days later. The
    raw payload is what's kept (the parse is derivable, the snapshot is not),
    wrapped with the fetch instant the parser needs.
    """
    fetched_at = datetime.now(UTC)
    payload = transport.get_json(_HISTOGRAM_URL.format(app_id=app_id), {"l": "english"})
    parse_histogram(payload, app_id, fetched_at)
    out_dir.mkdir(parents=True, exist_ok=True)
    record = {"app_id": app_id, "fetched_at": fetched_at.isoformat(), "payload": payload}
    (out_dir / f"{app_id}.json").write_text(json.dumps(record), encoding="utf-8")


def sweep_corpus_app_ids(sweep_run: Path) -> list[int]:
    """The corpus app ids the run of record swept — the instrument-check frame."""
    manifest = _object(
        json.loads((sweep_run / "manifest.json").read_text(encoding="utf-8")),
        "sweep manifest",
    )
    games = _object(manifest.get("games"), "sweep manifest games")
    return sorted(int(app_id) for app_id in games)


def probe(
    transport: SteamTransport,
    sink: Sink,
    candidates: list[tuple[int, str]],
    targets: dict[ListBand, int],
    budget: int,
    run_dir: Path,
    probe_log: TextIO,
) -> tuple[list[dict[str, object]], int]:
    """The admission loop: probe candidates until the bands fill or the budget ends.

    Returns the admitted-game records and the number of candidates probed.
    Every candidate lands in the probe log with its verdict — the log doubles
    as an unbiased popularity-distribution sample of the catalogue, free data
    the probe pays for anyway.
    """
    admitted: list[dict[str, object]] = []
    filled: dict[ListBand, int] = {band: 0 for band in targets}
    probed = 0
    for app_id, name in candidates:
        if probed >= budget or all(filled[b] >= targets[b] for b in targets):
            break
        probed += 1
        entry: dict[str, object] = {"probe": probed, "app_id": app_id, "name": name}
        try:
            details = appdetails_entry(transport, app_id)
            if details is None:
                entry["verdict"] = "no-data"
                _log_probe(probe_log, entry)
                continue
            app_type, store_name, release_date = details
            if app_type != "game":
                entry["verdict"] = f"not-a-game:{app_type}"
                _log_probe(probe_log, entry)
                continue
            total = review_totals(transport, app_id, "all")
            entry["total_reviews"] = total
            band = list_band(total) if total is not None else None
            if band is None:
                entry["verdict"] = "out-of-band"
                _log_probe(probe_log, entry)
                continue
            entry["band"] = band.value
            if filled[band] >= targets[band]:
                entry["verdict"] = "band-full"
                _log_probe(probe_log, entry)
                continue
            snapshot_histogram(transport, app_id, run_dir / "histograms")
            english_total = review_totals(transport, app_id, "english")
            filled[band] += 1
            entry["verdict"] = "admitted"
            _log_probe(probe_log, entry)
            admitted.append({
                "app_id": app_id,
                "applist_name": name,
                "store_name": store_name,
                "release_date": release_date,
                "total_reviews": total,
                "english_total_reviews": english_total,
                "band": band.value,
                "probe": probed,
            })
            narrate(
                sink, _STAGE, StageKind.PROGRESS,
                f"probe {probed}: ADMIT {store_name!r} (app {app_id}) · "
                f"{band.value} · totals {total:,} (en {english_total}) · "
                + " · ".join(f"{b.value} {filled[b]}/{targets[b]}" for b in targets),
            )
        except SteamResponseError as exc:
            # One damaged payload must not kill a 40-minute unattended run;
            # recorded in the log and narrated, never swallowed.
            entry["verdict"] = f"response-error: {exc}"
            _log_probe(probe_log, entry)
            narrate(sink, _STAGE, StageKind.WARN, f"probe {probed}: app {app_id}: {exc}")
    return admitted, probed


def _log_probe(probe_log: TextIO, entry: dict[str, object]) -> None:
    probe_log.write(json.dumps(entry, ensure_ascii=False) + "\n")


def main() -> int:
    """Compose the run: frame, probe loop, instrument fetches, manifest."""
    parser = argparse.ArgumentParser(
        description="Discover the long-tail game list and snapshot its histograms."
    )
    parser.add_argument("--out", type=Path, default=Path("data/longtail"))
    parser.add_argument("--seed", type=int, default=DEFAULT_SEED)
    parser.add_argument("--probe-budget", type=int, default=DEFAULT_PROBE_BUDGET)
    parser.add_argument("--applist", type=Path, default=None,
                        help="reuse a persisted applist snapshot instead of fetching")
    parser.add_argument("--sweep-run", type=Path, default=DEFAULT_SWEEP_RUN,
                        help="the m2sweep run whose corpus games seed the instrument check")
    parser.add_argument("--corpus-check", type=int, default=DEFAULT_CORPUS_CHECK)
    for band, target in DEFAULT_TARGETS.items():
        parser.add_argument(
            f"--{band.value}", type=int, default=target, dest=band.name.lower(),
            help=f"target count for the {band.value} band (default {target})",
        )
    args = parser.parse_args()
    targets = {band: int(getattr(args, band.name.lower())) for band in DEFAULT_TARGETS}

    started = datetime.now(UTC)
    run_id = mint_run_id("longtail", started)
    run_dir = args.out / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    code = code_version()

    aborted: str | None = None
    admitted: list[dict[str, object]] = []
    probed = 0
    corpus_checked: list[int] = []

    with (
        (run_dir / "run.log").open("a", encoding="utf-8", buffering=1) as log,
        (run_dir / "probes.jsonl").open("w", encoding="utf-8", buffering=1) as probe_log,
    ):
        sink: Sink = TeeSink(log)
        transport = SteamTransport(SteamClientConfig(), sink)
        narrate(
            sink, _STAGE, StageKind.STARTED,
            f"run {run_id} · code {code} · seed {args.seed} · budget {args.probe_budget} · "
            + " · ".join(f"{b.value} target {targets[b]}" for b in targets),
        )
        try:
            if args.applist is not None:
                pairs = load_applist(args.applist)
                applist_path = args.applist
            else:
                applist_path = run_dir / "applist.json"
                pairs = fetch_applist(transport, applist_path)
            applist_sha = hashlib.sha256(applist_path.read_bytes()).hexdigest()
            narrate(
                sink, _STAGE, StageKind.PROGRESS,
                f"applist: {len(pairs):,} apps ({applist_path}, sha256 {applist_sha[:12]}…)",
            )
            candidates = sorted(pairs)  # deterministic base order before the shuffle
            random.Random(args.seed).shuffle(candidates)

            admitted, probed = probe(
                transport, sink, candidates, targets, args.probe_budget, run_dir, probe_log
            )

            corpus_ids = sweep_corpus_app_ids(args.sweep_run)
            corpus_checked = sorted(
                random.Random(args.seed).sample(corpus_ids, k=args.corpus_check)
            )
            for app_id in corpus_checked:
                snapshot_histogram(transport, app_id, run_dir / "histograms_corpus")
                narrate(sink, _STAGE, StageKind.PROGRESS,
                        f"instrument check: corpus app {app_id} histogram snapped")
        except KeyboardInterrupt:
            aborted = "keyboard interrupt"
        except Exception as exc:  # manifest still written even when dying loud
            aborted = f"{type(exc).__name__}: {exc}"
        finally:
            transport.close()

        (run_dir / "admitted.json").write_text(
            json.dumps(admitted, indent=2, ensure_ascii=False), encoding="utf-8"
        )
        counts = {band.value: sum(1 for g in admitted if g["band"] == band.value)
                  for band in targets}
        write_manifest(run_dir, {
            "run_id": run_id,
            "code_version": code,
            "config_hash": config_hash({
                "seed": args.seed,
                "probe_budget": args.probe_budget,
                "targets": {b.value: targets[b] for b in targets},
                "corpus_check": args.corpus_check,
            }),
            "seed": args.seed,
            "probe_budget": args.probe_budget,
            "targets": {b.value: targets[b] for b in targets},
            "applist_path": str(args.applist) if args.applist is not None else "applist.json",
            "sweep_run": str(args.sweep_run),
            "corpus_check_app_ids": corpus_checked,
            "probed": probed,
            "admitted": counts,
            "started_at": started.isoformat(),
            "finished_at": datetime.now(UTC).isoformat(),
            "aborted": aborted,
        })
        narrate(
            sink, _STAGE,
            StageKind.WARN if aborted else StageKind.DONE,
            f"{'aborted: ' + aborted if aborted else 'done'} · probed {probed} · "
            f"admitted {counts} · {run_dir}",
        )
    return 1 if aborted else 0


if __name__ == "__main__":
    raise SystemExit(main())
