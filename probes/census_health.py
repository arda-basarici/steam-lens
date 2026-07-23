"""The census's mechanical health audit — D2b's $0 sweep, regenerable any time.

Usage:
    uv run python probes/census_health.py

Three reads over the bought pool, rendered to ``captures/census_health/HEALTH.md``:

1. **The evidence invariant, verified.** The parse nulls any non-verbatim
   quote at write time, so the stored pool holds zero fabricated quotes *by
   construction* — this sweep re-checks every stored span against its review
   text so the claim is "zero, verified," not "zero, assumed." A violation is
   a parse-or-storage bug and exits nonzero.
2. **Attempted fabrication**, from the census run manifests' write-time
   repair counts — the model-quality diagnostic the stored data can no longer
   show (its fabricated quotes were repaired away before storage).
3. **Per-game distribution health**, deliberately threshold-free (ruled
   2026-07-23): the sorted table is for human reading; tolerance bands are
   D3's decision once the shape has been seen.

Derived and cheap → printed and rendered, never journaled: the eval-run
journal stays "scored against a measuring stick," and this audit has none.
"""

from __future__ import annotations

import json
import sys
from collections.abc import Iterator, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

_REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO / "src"))

import sqlite3  # noqa: E402

from steamlens.contracts import AspectAggregate, AspectSlot, ClassifierVersions  # noqa: E402
from steamlens.core.classify import PROMPT_VERSION  # noqa: E402
from steamlens.store.store import Store  # noqa: E402
from steamlens.studies.aggregate_corpus import mint_census_aggregates  # noqa: E402
from steamlens.studies.label_corpus import MODEL_ID  # noqa: E402

_DB = _REPO / "data" / "steamlens.sqlite3"
_RUNS_DIR = _REPO / "data" / "runs"
_APP_NAMES = _REPO / "data" / "app_names.json"
_OUT = _REPO / "probes" / "captures" / "census_health" / "HEALTH.md"
_VERSIONS = ClassifierVersions(
    model_version=MODEL_ID, prompt_version=PROMPT_VERSION, ontology_version="v2"
)
_TRIPLE_FILTER = (
    " c.origin = 'survey' AND c.model_version = ? AND c.prompt_version = ?"
    " AND c.ontology_version = ?"
)
_TRIPLE_ARGS = (_VERSIONS.model_version, _VERSIONS.prompt_version, _VERSIONS.ontology_version)


@dataclass(frozen=True)
class GameHealth:
    """One game's distribution row — raw quantities; the table renders the ratios."""

    app_id: int
    envelopes: int
    reviews_with_any: int
    mentions: int
    with_evidence: int
    candidates: int
    top_aspect: str
    top_aspect_mentions: int


def _iter_evidence_rows(conn: sqlite3.Connection) -> Iterator[tuple[str, str, str, str]]:
    """Stream (review_id, aspect, evidence, review_text) for every stored span."""
    cursor = conn.execute(
        "SELECT c.review_id, m.aspect, m.evidence, r.text"
        " FROM mentions m"
        " JOIN classifications c ON c.id = m.classification_id"
        " JOIN reviews r ON r.review_id = c.review_id"
        f" WHERE m.evidence IS NOT NULL AND {_TRIPLE_FILTER}",
        _TRIPLE_ARGS,
    )
    for row in cursor:
        yield str(row[0]), str(row[1]), str(row[2]), str(row[3])


def verify_evidence_invariant(conn: sqlite3.Connection) -> tuple[int, list[tuple[str, str]]]:
    """Every stored evidence span must be a verbatim substring of its review.

    Returns (spans checked, violations as (review_id, aspect)). The expected
    violation count is exactly zero — the write path already enforced this —
    so anything else means the parse or the storage drifted from the contract.
    """
    checked = 0
    violations: list[tuple[str, str]] = []
    for review_id, aspect, evidence, text in _iter_evidence_rows(conn):
        checked += 1
        if evidence not in text:
            violations.append((review_id, aspect))
    return checked, violations


def _per_game_counts(conn: sqlite3.Connection, sql: str) -> dict[int, int]:
    return {int(row[0]): int(row[1]) for row in conn.execute(sql, _TRIPLE_ARGS)}


def game_health_rows(
    conn: sqlite3.Connection, aggregates: tuple[AspectAggregate, ...]
) -> list[GameHealth]:
    """Fold the raw per-game quantities; aspect-side facts come from the minted fold."""
    envelopes = _per_game_counts(
        conn,
        "SELECT r.app_id, COUNT(*) FROM classifications c"
        " JOIN reviews r ON r.review_id = c.review_id"
        f" WHERE {_TRIPLE_FILTER} GROUP BY r.app_id",
    )
    reviews_with_any = _per_game_counts(
        conn,
        "SELECT r.app_id, COUNT(DISTINCT c.review_id) FROM mentions m"
        " JOIN classifications c ON c.id = m.classification_id"
        " JOIN reviews r ON r.review_id = c.review_id"
        f" WHERE {_TRIPLE_FILTER} GROUP BY r.app_id",
    )
    with_evidence = _per_game_counts(
        conn,
        "SELECT r.app_id, COUNT(*) FROM mentions m"
        " JOIN classifications c ON c.id = m.classification_id"
        " JOIN reviews r ON r.review_id = c.review_id"
        f" WHERE m.evidence IS NOT NULL AND {_TRIPLE_FILTER} GROUP BY r.app_id",
    )

    mentions: dict[int, int] = {}
    candidates: dict[int, int] = {}
    top: dict[int, tuple[str, int]] = {}
    for agg in aggregates:
        total = agg.counts.positive + agg.counts.negative + agg.counts.mixed + agg.counts.neutral
        mentions[agg.app_id] = mentions.get(agg.app_id, 0) + total
        if agg.slot is AspectSlot.CANDIDATE:
            candidates[agg.app_id] = candidates.get(agg.app_id, 0) + total
        if total > top.get(agg.app_id, ("", 0))[1]:
            top[agg.app_id] = (agg.aspect, total)
    return [
        GameHealth(
            app_id=app_id,
            envelopes=n,
            reviews_with_any=reviews_with_any.get(app_id, 0),
            mentions=mentions.get(app_id, 0),
            with_evidence=with_evidence.get(app_id, 0),
            candidates=candidates.get(app_id, 0),
            top_aspect=top.get(app_id, ("—", 0))[0],
            top_aspect_mentions=top.get(app_id, ("—", 0))[1],
        )
        for app_id, n in envelopes.items()
    ]


def manifest_repairs(runs_dir: Path) -> tuple[int, int] | None:
    """(labeled, evidence repairs) summed over local run manifests, or None if absent.

    Manifests live under the git-ignored ``data/runs`` — write-time counts the
    stored pool cannot reproduce (its bad quotes were nulled before storage).
    """
    if not runs_dir.exists():
        return None
    labeled = repairs = 0
    for manifest_path in sorted(runs_dir.glob("*/manifest.json")):
        reviews = json.loads(manifest_path.read_text(encoding="utf-8")).get("reviews", {})
        labeled += int(reviews.get("labeled", 0))
        repairs += int(reviews.get("evidence_repairs", 0))
    return labeled, repairs


def _app_names() -> Mapping[str, str]:
    if not _APP_NAMES.exists():
        return {}
    return {str(k): str(v) for k, v in json.loads(_APP_NAMES.read_text(encoding="utf-8")).items()}


def _pct(numerator: int, denominator: int) -> str:
    return f"{numerator / denominator:.1%}" if denominator else "—"


def render(
    checked: int,
    violations: list[tuple[str, str]],
    total_mentions: int,
    rows: list[GameHealth],
    repairs: tuple[int, int] | None,
    manifest_id: str,
) -> str:
    names = _app_names()
    lines = [
        "# Census health — the mechanical audit (D2b)",
        "",
        f"Generated {datetime.now(UTC).isoformat(timespec='seconds')} · "
        f"pool: {_VERSIONS.model_version} / {_VERSIONS.prompt_version} / "
        f"{_VERSIONS.ontology_version} · fold: {manifest_id} · "
        "regenerate: `uv run python probes/census_health.py`",
        "",
        "## The evidence invariant, verified",
        "",
        f"- stored evidence spans: {checked:,} of {total_mentions:,} mentions "
        f"({_pct(checked, total_mentions)} coverage)",
        f"- verbatim violations: **{len(violations)}** — the write-path invariant "
        "(non-verbatim quotes are repaired to null before storage), re-checked census-wide",
    ]
    if violations:
        lines += ["", "VIOLATIONS (parse-or-storage bug — investigate before trusting spans):"]
        lines += [f"- review {rid}, aspect {aspect}" for rid, aspect in violations[:50]]
    lines += ["", "## Attempted fabrication (write-time counts, from the run manifests)", ""]
    if repairs is None:
        lines.append(
            "- run manifests not present on this machine (`data/runs` is local) — "
            "rates unavailable here; the stored-pool invariant above is unaffected"
        )
    else:
        labeled, repaired = repairs
        attempts = checked + repaired
        lines += [
            f"- evidence repairs across the census dispatch: {repaired:,} "
            f"(over {labeled:,} labeled reviews)",
            f"- approximate attempt base (stored spans + repairs): {attempts:,} → "
            f"~{repaired / attempts:.1%} of attempted quotes were non-verbatim and "
            "were nulled at parse; the stored rate is 0% by construction",
            "- approximate because repairs are counted per raw model row, before "
            "same-aspect rows collapse into one mention",
        ]
    lines += [
        "",
        "## Per-game distribution health",
        "",
        "No thresholds by design (ruled 2026-07-23): read the shape, flag by eye; "
        "tolerance bands are D3's decision.",
        "",
        "| game | envelopes | zero-share | mentions/review | evidence cov "
        "| candidate share | top aspect (share) |",
        "|---|---|---|---|---|---|---|",
    ]
    for row in sorted(rows, key=lambda r: r.envelopes, reverse=True):
        name = names.get(str(row.app_id), str(row.app_id))
        zero = row.envelopes - row.reviews_with_any
        top_share = _pct(row.top_aspect_mentions, row.mentions)
        lines.append(
            f"| {name} | {row.envelopes:,} | {_pct(zero, row.envelopes)} "
            f"| {row.mentions / row.envelopes:.2f} | {_pct(row.with_evidence, row.mentions)} "
            f"| {_pct(row.candidates, row.mentions)} | {row.top_aspect} ({top_share}) |"
        )
    total_env = sum(r.envelopes for r in rows)
    total_zero = total_env - sum(r.reviews_with_any for r in rows)
    total_ev = sum(r.with_evidence for r in rows)
    total_cand = sum(r.candidates for r in rows)
    lines += [
        f"| **all {len(rows)} games** | {total_env:,} | {_pct(total_zero, total_env)} "
        f"| {total_mentions / total_env:.2f} | {_pct(total_ev, total_mentions)} "
        f"| {_pct(total_cand, total_mentions)} | — |",
    ]
    return "\n".join(lines) + "\n"


def main() -> None:
    with Store(_DB) as store:
        aggregates = mint_census_aggregates(store, versions=_VERSIONS)
    conn = sqlite3.connect(f"file:{_DB.as_posix()}?mode=ro", uri=True)
    try:
        checked, violations = verify_evidence_invariant(conn)
        total_mentions = int(
            conn.execute(
                "SELECT COUNT(*) FROM mentions m"
                " JOIN classifications c ON c.id = m.classification_id"
                f" WHERE {_TRIPLE_FILTER}",
                _TRIPLE_ARGS,
            ).fetchone()[0]
        )
        rows = game_health_rows(conn, aggregates)
    finally:
        conn.close()
    report = render(
        checked,
        violations,
        total_mentions,
        rows,
        manifest_repairs(_RUNS_DIR),
        aggregates[0].manifest_id if aggregates else "—",
    )
    _OUT.parent.mkdir(parents=True, exist_ok=True)
    _OUT.write_text(report, encoding="utf-8")
    print(report)
    print(f"written -> {_OUT.relative_to(_REPO)}")
    if violations:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
