"""The gold-set loader — the versioned human-labeled slice, validated at the boundary.

Gold is a repo-versioned JSONL artifact minted by the D1 adjudication pass;
this loader is its one door into code. Validation here is the trust-no-raw-data
boundary: every record must carry its identity, its provenance pins (ontology
version + content hash, instructions version), and mentions whose sentiments
are in the closed vocabulary. Two structural rules are enforced because the
scorer's pairing *assumes* them: review ids are unique across the file, and no
review carries the same aspect label twice — set-semantics pairing is only
sound if the gold side is duplicate-free, so a violation dies here, loudly,
not as a silently miscounted metric.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import cast

from steamlens.contracts import Sentiment

_SENTIMENT_VALUES = frozenset(s.value for s in Sentiment)


@dataclass(frozen=True, slots=True)
class GoldMention:
    """One adjudicated aspect mention — Arda's ruling, not a model draft.

    ``aspect`` is a bare label string: canonical snake_case when the ruling
    pinned it, free wording when it was ruled a candidate. Which stratum it
    belongs to is deliberately *not* stored — the scorer resolves both gold
    and predictions through the same ``core/normalize`` surface index, so the
    two sides can never disagree about what counts as pinned.
    """

    aspect: str
    sentiment: Sentiment
    evidence: str | None


@dataclass(frozen=True, slots=True)
class GoldRecord:
    """One adjudicated review: the text the candidates will see, and its truth.

    ``text`` rides along because the bake-off runner prompts from gold records
    directly — same text-alone horizon as the assist run. The ontology pins are
    the provenance handshake: a scorer should refuse to pair gold against
    predictions made under a different ontology content hash.
    """

    review_id: str
    app_id: str
    text: str
    mentions: tuple[GoldMention, ...]
    instructions_version: str
    ontology_version: str
    ontology_content_hash: str


def load_gold(path: Path) -> tuple[GoldRecord, ...]:
    """Read and validate the gold JSONL at ``path`` — every record, or a loud error.

    Raises ``ValueError`` naming the offending line and review on any violation:
    a missing field, an unknown sentiment, an empty aspect, a duplicated review
    id, or the same aspect appearing twice within one review (the set-pairing
    precondition). An unreadable file propagates as its natural ``OSError``.
    """
    records: list[GoldRecord] = []
    seen_ids: set[str] = set()
    for lineno, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        record = _parse_record(line, lineno)
        if record.review_id in seen_ids:
            raise ValueError(f"gold line {lineno}: duplicate review_id {record.review_id!r}")
        seen_ids.add(record.review_id)
        records.append(record)
    if not records:
        raise ValueError(f"gold file is empty: {path}")
    return tuple(records)


def _parse_record(line: str, lineno: int) -> GoldRecord:
    raw: object = json.loads(line)
    if not isinstance(raw, dict):
        raise ValueError(f"gold line {lineno}: record is not a JSON object")
    data = cast(dict[str, object], raw)
    review_id = _required_str(data, "review_id", lineno)
    mentions_raw = data.get("mentions")
    if not isinstance(mentions_raw, list):
        raise ValueError(f"gold line {lineno} ({review_id}): 'mentions' is not a list")
    mentions = tuple(
        _parse_mention(m, review_id, lineno) for m in cast(list[object], mentions_raw)
    )
    aspects = [m.aspect for m in mentions]
    if len(aspects) != len(set(aspects)):
        dupes = sorted({a for a in aspects if aspects.count(a) > 1})
        raise ValueError(
            f"gold line {lineno} ({review_id}): duplicate aspect within review: {dupes}"
        )
    return GoldRecord(
        review_id=review_id,
        app_id=_required_str(data, "app_id", lineno),
        text=_required_str(data, "text", lineno),
        mentions=mentions,
        instructions_version=_required_str(data, "instructions_version", lineno),
        ontology_version=_required_str(data, "ontology_version", lineno),
        ontology_content_hash=_required_str(data, "ontology_content_hash", lineno),
    )


def _parse_mention(raw: object, review_id: str, lineno: int) -> GoldMention:
    if not isinstance(raw, dict):
        raise ValueError(f"gold line {lineno} ({review_id}): mention is not a JSON object")
    mention = cast(dict[str, object], raw)
    aspect = mention.get("aspect")
    if not isinstance(aspect, str) or not aspect.strip():
        raise ValueError(f"gold line {lineno} ({review_id}): mention aspect missing or empty")
    sentiment = mention.get("sentiment")
    if not isinstance(sentiment, str) or sentiment not in _SENTIMENT_VALUES:
        raise ValueError(
            f"gold line {lineno} ({review_id}): sentiment {sentiment!r} not in "
            f"{sorted(_SENTIMENT_VALUES)}"
        )
    evidence = mention.get("evidence")
    if evidence is not None and not isinstance(evidence, str):
        raise ValueError(f"gold line {lineno} ({review_id}): evidence is neither string nor null")
    return GoldMention(aspect=aspect, sentiment=Sentiment(sentiment), evidence=evidence)


def _required_str(data: dict[str, object], field: str, lineno: int) -> str:
    value = data.get(field)
    if not isinstance(value, str) or not value:
        raise ValueError(f"gold line {lineno}: field {field!r} missing or not a non-empty string")
    return value
