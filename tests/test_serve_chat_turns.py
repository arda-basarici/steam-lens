"""Behavioral claims on the turn runner — what the serving process puts under a turn.

The claims: a turn's model calls are journalled in the store's spend
ledger, which is what the day's backstop reads, under a run identifier that
says chat and is the turn's own; the model's answers are kept nowhere on
disk; and a turn that would pass its spend ceiling ends as unavailable
before anything is sent.

The turns here are read as out of scope, which ends them after the one
understand call, so the store needs no library.
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest
from fakes import AnswerScript, CollectingSink

from steamlens.contracts import (
    AspectDef,
    AspectOntology,
    ChatMessage,
    ChatRole,
    TurnEnding,
)
from steamlens.serve.chat_turns import RUN_PREFIX, TurnRunner
from steamlens.store import Store

_ONTOLOGY = AspectOntology(
    version="test",
    aspects=(AspectDef("story", "The plot and how it is told.", (), "narrative", "", "", ()),),
    global_rules=(),
)
_OUT_OF_SCOPE = json.dumps({"intent": "out-of-scope"})
_ASKED = (ChatMessage(ChatRole.PLAYER, "write me a poem"),)


@pytest.fixture
def store_path(tmp_path: Path) -> Path:
    path = tmp_path / "steamlens.sqlite3"
    with Store(path):
        pass
    return path


def _rows(path: Path, query: str) -> list[tuple[object, ...]]:
    conn = sqlite3.connect(path)
    try:
        return conn.execute(query).fetchall()
    finally:
        conn.close()


def test_a_turns_calls_are_journalled_in_the_stores_ledger_under_the_turns_own_run(
    store_path: Path,
) -> None:
    script = AnswerScript([_OUT_OF_SCOPE, _OUT_OF_SCOPE])
    runner = TurnRunner(script.entry(), store_path, _ONTOLOGY, 0.05, CollectingSink())
    first = runner(_ASKED, "seed-a")
    second = runner((ChatMessage(ChatRole.PLAYER, "and a song"),), "seed-b")
    assert (first.ending, second.ending) == (TurnEnding.OUT_OF_SCOPE, TurnEnding.OUT_OF_SCOPE)
    journalled = _rows(store_path, "SELECT stage, run_id FROM spend_ledger ORDER BY id")
    assert [stage for stage, _ in journalled] == ["understand", "understand"]
    runs = [str(run_id) for _, run_id in journalled]
    assert all(run.startswith(f"{RUN_PREFIX}-") for run in runs)
    assert runs[0] != runs[1]


def test_the_models_answers_are_kept_nowhere_on_disk(store_path: Path) -> None:
    """The understand step's answer holds the player's own words, and
    nothing of a conversation is stored before the chat's storage has its
    retention period. The archive table is the report jobs' alone."""
    script = AnswerScript([_OUT_OF_SCOPE])
    TurnRunner(script.entry(), store_path, _ONTOLOGY, 0.05, CollectingSink())(_ASKED, "seed-a")
    assert len(script.prompts) == 1
    assert _rows(store_path, "SELECT COUNT(*) FROM classify_cache") == [(0,)]


def test_a_turn_that_would_pass_its_ceiling_ends_unavailable_before_anything_is_sent(
    store_path: Path,
) -> None:
    script = AnswerScript([_OUT_OF_SCOPE])
    runner = TurnRunner(script.entry(), store_path, _ONTOLOGY, 0.0, CollectingSink())
    assert runner(_ASKED, "seed-a").ending is TurnEnding.UNAVAILABLE
    assert script.prompts == []
    assert _rows(store_path, "SELECT COUNT(*) FROM spend_ledger") == [(0,)]
