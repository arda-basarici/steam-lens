"""The turn runner — one chat turn over the serving store and the model door.

``chat.turn.turn`` knows nothing of where its store and its client come
from. This is where the serving process gives it both, once for each turn:
a store opened in the thread that runs the turn, as every serving read is,
and a model client that lives for that turn alone.

A client for each turn, where a report job has one for the whole job, for
three reasons. The turn's spend has its own ceiling, a tripwire far above
what a turn that works can cost. Its ledger rows carry a run identifier of
their own, so a turn's calls can be told from a job's and from another
turn's. And its response archive is in memory and goes with it: a model's
answer to the understand step holds the player's own words, and nothing of
a conversation is kept on disk before the chat's storage has its retention
period. The cost is that an identical turn is paid for twice.

The spend ledger is the store's, which is what the day's backstop reads.
The client's budget check sums that ledger since the client was built,
whoever spent, so a turn beside a running report job counts the job's
spend of those seconds against its own ceiling; the ceiling leaves room
for it.

The provider this runs on limits concurrency and not rate, so turns do not
share a pacer with each other or with a job. How many run at once is the
turn gate's to bound.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from steamlens.chat.turn import chat_routes, turn
from steamlens.contracts import AspectOntology, ChatMessage, Sink, Turn
from steamlens.dispatch import mint_run_id
from steamlens.dispatch.census_arm import MODEL_ID, MODEL_SPEC, PROVIDER
from steamlens.llm_client import (
    InMemoryResponseArchive,
    LlmClient,
    LlmClientConfig,
    ProviderEntry,
)
from steamlens.store import Store

RUN_PREFIX = "chat"
"""What a chat turn's run identifier starts with, in the spend ledger."""


def _utc_now() -> datetime:
    return datetime.now(UTC)


@dataclass(frozen=True, slots=True)
class TurnRunner:
    """Runs one turn for the serving route: ``runner(conversation, seed)``.

    ``entry`` is the provider entry the serving process composed, the one
    its report jobs use. ``ontology`` is the pinned aspect vocabulary,
    loaded once by the root. ``budget_usd`` is one turn's spend ceiling.
    ``sink`` takes the steps' narration and metrics. ``now`` is the clock
    the turn's year and its run identifier are read from.

    Whatever ``chat.turn.turn`` raises propagates; the route is where it
    stops.
    """

    entry: ProviderEntry
    db_path: Path
    ontology: AspectOntology
    budget_usd: float
    sink: Sink
    now: Callable[[], datetime] = _utc_now

    def __call__(self, conversation: Sequence[ChatMessage], seed: str) -> Turn:
        started = self.now()
        with Store(self.db_path) as store:
            client = LlmClient(
                LlmClientConfig(
                    routes=chat_routes(),
                    models={MODEL_ID: MODEL_SPEC},
                    budget_usd=self.budget_usd,
                ),
                InMemoryResponseArchive(),
                store.spend_ledger,
                self.sink,
                registry={PROVIDER: self.entry},
                run_id=mint_run_id(RUN_PREFIX, started),
            )
            return turn(
                client, store, conversation, self.ontology, self.sink,
                seed=seed, year=started.year,
            )
