"""Marked-window pools — the fresh-buy run's bomb material, loaded and validated.

The mixing experiment's supply side. A fresh-buy run directory (the step-8
fetch-and-label session) holds each bomb game's marked-window reviews as a
``<app_id>_reviews.jsonl`` walk product, its bought labels in the run-local
``labels.sqlite3``, and the walk's own account of what was fetched in
``manifest.json``. This module reads that trio into per-game ``MarkedPool``
records: the survey-labeled usable reviews plus the pinned-aspect mention
index ``measure_draw`` consumes — the same index shape the curves sweep
builds over the corpus, minted here from the fresh store instead.

The manifest drives everything: which games are marked-window material (the
``role`` field — long-tail games in the same run are someone else's supply),
and what window each walk claimed. Validation at this boundary is the
trust-no-raw-data rule applied to our own artifacts: every labeled review
must exist in the file's usable slice (a miss means the store and the files
diverged — a measurement built on that would be confidently wrong), and every
pooled review's timestamp must sit inside the manifest's window, judged
inclusively on both ends exactly as the windowed walk judges (``walk.py``'s
zone rule) — the fetch recorded ``out_of_window: 0``, and this check keeps
that claim honest against the file actually on disk. Reviews the labeler
skipped (the durable-refusal case) drop out with a per-pool count, mirroring
the sweep's ``dropped_unlabeled`` accounting.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import cast

from steamlens.contracts import AspectSlot, ClassifierVersions, Review
from steamlens.corpus import read_reviews_file
from steamlens.store import Store


@dataclass(frozen=True, slots=True)
class MarkedPool:
    """One bomb game's marked-window material, labeled and blend-ready.

    ``reviews`` is the usable slice holding survey envelopes under the frozen
    triple — the only material the mixing experiment may draw, because a
    blended review must carry labels to move a measured share.
    ``aspect_reviews`` maps each pinned aspect to the ids of pool reviews
    mentioning it, ``measure_draw``'s index shape, so a mixed draw's scoring
    can union this with the base game's index. ``dropped_unlabeled`` counts
    usable reviews without envelopes (the labeler's durable refusals);
    ``source_run_id`` pins which fetch run supplied the material — provenance
    rides the pool, not the caller's memory.
    """

    app_id: int
    name: str
    window_start: datetime
    window_end: datetime
    reviews: tuple[Review, ...]
    aspect_reviews: dict[str, frozenset[str]]
    dropped_unlabeled: int
    source_run_id: str


def load_marked_pools(run_dir: Path, versions: ClassifierVersions) -> tuple[MarkedPool, ...]:
    """Read a fresh-buy run directory into its marked-window pools.

    Selects the manifest's ``marked-window`` games (in manifest order — the
    fetch's own ordering), intersects each game's usable file slice with the
    run-local label store's survey envelopes under ``versions``, and builds
    the per-game pinned mention index. Raises ``ValueError`` when the run
    holds no marked games, when a marked pool comes up empty (wrong
    ``versions`` triple, or wrong store), when a labeled review is missing
    from its file's usable slice, or when a pooled review's timestamp falls
    outside the manifest's window — each a wiring or artifact-integrity
    failure, never a sampling outcome.
    """
    manifest = read_fetch_manifest(run_dir)
    marked = [game for game in manifest.games if game.role == "marked-window"]
    if not marked:
        raise ValueError(f"{run_dir}: manifest holds no marked-window games — wrong run dir?")

    with Store(run_dir / "labels.sqlite3") as store:
        app_id_of = store.reviews.app_id_by_review()
        enveloped = _enveloped_ids_by_game(store, versions, app_id_of)
        mentions = _pinned_mentions_by_game(store, versions, app_id_of)

    pools: list[MarkedPool] = []
    for game in marked:
        result = read_reviews_file(run_dir / f"{game.app_id}_reviews.jsonl")
        usable_ids = {review.review_id for review in result.reviews}
        labeled = enveloped.get(game.app_id, frozenset())
        missing = labeled - usable_ids
        if missing:
            raise ValueError(
                f"app_id {game.app_id}: {len(missing)} labeled review(s) absent from the "
                f"usable file slice (first: {sorted(missing)[:3]}) — the label store and "
                "the review files have diverged"
            )
        pool = tuple(review for review in result.reviews if review.review_id in labeled)
        if not pool:
            raise ValueError(
                f"app_id {game.app_id}: no usable review holds a survey envelope under "
                f"{versions} — wrong versions triple or wrong store"
            )
        _assert_in_window(game, pool)
        pool_ids = {review.review_id for review in pool}
        index = {
            aspect: frozenset(ids & pool_ids)
            for aspect, ids in mentions.get(game.app_id, {}).items()
            if ids & pool_ids
        }
        pools.append(
            MarkedPool(
                app_id=game.app_id,
                name=game.name,
                window_start=game.window_start,
                window_end=game.window_end,
                reviews=pool,
                aspect_reviews=index,
                dropped_unlabeled=result.usable - len(pool),
                source_run_id=manifest.run_id,
            )
        )
    return tuple(pools)


@dataclass(frozen=True, slots=True)
class FetchManifestGame:
    """One manifest game entry, reduced to the fields the run's consumers stand on."""

    app_id: int
    name: str
    role: str
    window_start: datetime
    window_end: datetime


@dataclass(frozen=True, slots=True)
class FetchManifest:
    """A fetch manifest's consumer-facing slice: run identity plus its games."""

    run_id: str
    games: tuple[FetchManifestGame, ...]


def read_fetch_manifest(run_dir: Path) -> FetchManifest:
    """Parse a fetch run's ``manifest.json``, validating the fields consumers stand on.

    Public because the manifest is the run directory's single account of
    which game plays which role — this loader selects the ``marked-window``
    games and the closing test selects the ``long-tail`` ones from the same
    record, so the parse-and-validate lives once.
    """
    path = run_dir / "manifest.json"
    if not path.is_file():
        raise ValueError(f"no manifest.json under {run_dir} — not a fetch run directory")
    raw = cast(dict[str, object], json.loads(path.read_text(encoding="utf-8")))
    run_id = raw.get("run_id")
    games_raw = raw.get("games")
    if not isinstance(run_id, str) or not isinstance(games_raw, list):
        raise ValueError(f"{path}: manifest is missing 'run_id' or 'games'")
    games: list[FetchManifestGame] = []
    for entry in cast(list[dict[str, object]], games_raw):
        windows = entry.get("windows")
        if not isinstance(windows, list) or len(windows) != 1:
            raise ValueError(
                f"{path}: app_id {entry.get('app_id')} carries "
                f"{len(windows) if isinstance(windows, list) else 'no'} windows — "
                "a fetch-run game walks exactly one"
            )
        window = cast(dict[str, object], windows[0])
        try:
            games.append(
                FetchManifestGame(
                    app_id=int(cast(int, entry["app_id"])),
                    name=cast(str, entry["name"]),
                    role=cast(str, entry["role"]),
                    window_start=datetime.fromisoformat(cast(str, window["start"])),
                    window_end=datetime.fromisoformat(cast(str, window["end"])),
                )
            )
        except (KeyError, TypeError) as exc:
            raise ValueError(f"{path}: malformed game entry ({exc!r})") from exc
    return FetchManifest(run_id=run_id, games=tuple(games))


def _enveloped_ids_by_game(
    store: Store, versions: ClassifierVersions, app_id_of: dict[str, int]
) -> dict[int, frozenset[str]]:
    """Survey envelope ids under ``versions``, grouped per game."""
    grouped: dict[int, set[str]] = {}
    for review_id in store.labels.iter_survey_envelope_review_ids(versions):
        grouped.setdefault(_game_of(review_id, app_id_of), set()).add(review_id)
    return {app_id: frozenset(ids) for app_id, ids in grouped.items()}


def _pinned_mentions_by_game(
    store: Store, versions: ClassifierVersions, app_id_of: dict[str, int]
) -> dict[int, dict[str, set[str]]]:
    """Pinned aspect → mentioning review ids, per game — candidate slots stay out.

    The same display-vocabulary rule the sweep applies: the mixing gate reads
    displayed aspects, and the display vocabulary is pinned.
    """
    grouped: dict[int, dict[str, set[str]]] = {}
    for review_id, aspect, slot, _sentiment in store.labels.iter_survey_mentions(versions):
        if slot is not AspectSlot.PINNED:
            continue
        game = grouped.setdefault(_game_of(review_id, app_id_of), {})
        game.setdefault(aspect, set()).add(review_id)
    return grouped


def _game_of(review_id: str, app_id_of: dict[str, int]) -> int:
    """The game a stored label belongs to, or a loud integrity failure."""
    app_id = app_id_of.get(review_id)
    if app_id is None:
        raise ValueError(
            f"label store holds review_id {review_id!r} with no reviews row — "
            "the store's own referential integrity has failed"
        )
    return app_id


def _assert_in_window(game: FetchManifestGame, pool: tuple[Review, ...]) -> None:
    """Every pooled review inside the manifest window, inclusive on both ends.

    Mirrors the windowed walk's zone judgment: the walk collected within
    ``[start, end]`` and recorded zero out-of-window reviews, so a violation
    here means the files no longer match the walk that wrote them.
    """
    for review in pool:
        if not game.window_start <= review.created_at <= game.window_end:
            raise ValueError(
                f"app_id {game.app_id}: review {review.review_id} created "
                f"{review.created_at.isoformat()} sits outside the manifest window "
                f"{game.window_start.isoformat()}..{game.window_end.isoformat()} — "
                "the files no longer match the recorded walk"
            )
