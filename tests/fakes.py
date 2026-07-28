"""Shared test doubles — sinks, the review seeder, and the scripted provider fakes.

A plain module imported by name (``from fakes import ...``; pytest's prepend
import mode puts ``tests/`` on ``sys.path``), so suites stop reaching into
each other's test modules for infrastructure. Only infrastructure lives here —
fixtures and helpers that encode a suite's own claims stay in that suite.
"""

from __future__ import annotations

import json
import re
import threading
from datetime import UTC, datetime
from pathlib import Path

from steamlens.contracts import FinishReason, LlmResponse, Review, SinkEvent, TokenUsage
from steamlens.dispatch.census_arm import MODEL_ID
from steamlens.evals.judge_dispatch import JUDGE_MODEL_ID
from steamlens.llm_client import ProviderEntry, ProviderPayload, ProviderPermanentError
from steamlens.store import Store

REVIEWS_BLOCK = re.compile(r"<reviews>\n(.*)\n</reviews>", re.DOTALL)
"""The classify prompt's data channel — what a scripted provider answers from."""


class NullSink:
    """Satisfies ``Sink`` structurally; swallows every event."""

    def emit(self, event: SinkEvent) -> None:
        pass


class CollectingSink:
    """Satisfies ``Sink`` structurally; keeps every event for assertions."""

    def __init__(self) -> None:
        self.events: list[SinkEvent] = []

    def emit(self, event: SinkEvent) -> None:
        self.events.append(event)


def prompt_batch(prompt: str) -> list[tuple[int, str]]:
    """The ``(idx, text)`` rows one dispatched classify prompt carried."""
    match = REVIEWS_BLOCK.search(prompt)
    assert match, "prompt carries no <reviews> data channel"
    rows = json.loads(match.group(1))
    return [(int(row["idx"]), str(row["text"])) for row in rows]


def seed_reviews(db_path: Path, rows: list[tuple[str, str]], *, app_id: int = 440) -> None:
    """Insert ``(review_id, text)`` rows as usable English reviews of one game."""
    with Store(db_path) as store:
        store.reviews.put_many(
            Review(
                review_id=rid,
                app_id=app_id,
                created_at=datetime(2026, 6, 1, tzinfo=UTC),
                language="english",
                text=text,
                voted_up=True,
            )
            for rid, text in rows
        )


class FakeProvider:
    """A scripted DeepSeek stand-in: answers per review text, records dispatches.

    ``send`` extracts the batch from the prompt's data channel and answers one
    row per idx — empty aspects by default, a ``gameplay`` mention when the
    review text asks for one, and *no row at all* for texts carrying ``FAIL``
    (the driver's re-batch path runs on missing idxs). Texts carrying
    ``REFUSE`` raise the request-level rejection. ``model_version`` for each
    call comes from ``version_for`` so drift is scriptable per call.
    """

    def __init__(self, version_for: list[str] | None = None) -> None:
        self.prompts: list[str] = []
        self._versions = version_for or []
        self._lock = threading.Lock()

    def entry(self) -> ProviderEntry:
        return ProviderEntry(build_payload=self._build, send=self._send, parse=self._parse)

    def dispatched_texts(self) -> list[str]:
        """Every review text sent to the provider, in dispatch order, flattened."""
        texts: list[str] = []
        for prompt in self.prompts:
            texts.extend(text for _, text in prompt_batch(prompt))
        return texts

    def _build(
        self, *, model: str, prompt: str, max_output_tokens: int, params: dict[str, object]
    ) -> ProviderPayload:
        return {"model": model, "prompt": prompt}

    def _send(self, *, model: str, payload: ProviderPayload) -> str:
        with self._lock:
            call_index = len(self.prompts)
            self.prompts.append(str(payload["prompt"]))
        if "REFUSE" in str(payload["prompt"]):
            raise ProviderPermanentError("HTTP 400: Content Exists Risk")
        version = (
            self._versions[call_index] if call_index < len(self._versions) else MODEL_ID
        )
        answers = [
            {"idx": idx, "aspects": self._aspects_for(text)}
            for idx, text in prompt_batch(str(payload["prompt"]))
            if "FAIL" not in text
        ]
        return json.dumps({"model_version": version, "answers": answers})

    @staticmethod
    def _aspects_for(text: str) -> list[dict[str, str]]:
        if "gameplay" in text:
            return [{"aspect": "gameplay", "sentiment": "positive"}]
        return []

    @staticmethod
    def _parse(raw: str) -> LlmResponse:
        body = json.loads(raw)
        return LlmResponse(
            text=json.dumps(body["answers"]),
            model_version=str(body["model_version"]),
            finish_reason=FinishReason.STOP,
            usage=TokenUsage(prompt_tokens=100, output_tokens=20, thinking_tokens=0),
        )


class FakeGemini:
    """A scripted judge-provider stand-in: answers per review text, records dispatches.

    Text markers script the failure shapes: ``REFUSE`` raises the
    request-level rejection, ``SAFETYBLOCK`` answers a Gemini-shaped
    generation refusal (``REFUSAL`` finish, empty body), ``MALFORMED``
    answers non-JSON. ``version_for`` scripts the reported model version per
    call so drift is testable.
    """

    def __init__(self, version_for: list[str] | None = None) -> None:
        self.prompts: list[str] = []
        self._versions = version_for or []
        self._lock = threading.Lock()

    def entry(self) -> ProviderEntry:
        return ProviderEntry(build_payload=self._build, send=self._send, parse=self._parse)

    @staticmethod
    def batch(prompt: str) -> list[tuple[int, str]]:
        return prompt_batch(prompt)

    def _build(
        self, *, model: str, prompt: str, max_output_tokens: int, params: dict[str, object]
    ) -> ProviderPayload:
        return {"model": model, "prompt": prompt}

    def _send(self, *, model: str, payload: ProviderPayload) -> str:
        prompt = str(payload["prompt"])
        with self._lock:
            call_index = len(self.prompts)
            self.prompts.append(prompt)
        if "REFUSE" in prompt:
            raise ProviderPermanentError("gemini HTTP 400: blocked request")
        version = (
            self._versions[call_index] if call_index < len(self._versions) else JUDGE_MODEL_ID
        )
        if "SAFETYBLOCK" in prompt:
            return json.dumps({"model_version": version, "finish": "refusal", "answers": None})
        if "MALFORMED" in prompt:
            return json.dumps({"model_version": version, "finish": "stop", "answers": "oops"})
        answers = [
            {"idx": idx, "aspects": self._aspects_for(text)}
            for idx, text in prompt_batch(prompt)
        ]
        return json.dumps({"model_version": version, "finish": "stop", "answers": answers})

    @staticmethod
    def _aspects_for(text: str) -> list[dict[str, str]]:
        if "gameplay" in text:
            return [{"aspect": "gameplay", "sentiment": "positive"}]
        return []

    @staticmethod
    def _parse(raw: str) -> LlmResponse:
        body = json.loads(raw)
        if body["finish"] == "refusal":
            return LlmResponse(
                text="",
                model_version=str(body["model_version"]),
                finish_reason=FinishReason.REFUSAL,
                usage=TokenUsage(prompt_tokens=100, output_tokens=0, thinking_tokens=0),
            )
        text = "not json at all" if body["answers"] == "oops" else json.dumps(body["answers"])
        return LlmResponse(
            text=text,
            model_version=str(body["model_version"]),
            finish_reason=FinishReason.STOP,
            usage=TokenUsage(prompt_tokens=100, output_tokens=20, thinking_tokens=0),
        )
