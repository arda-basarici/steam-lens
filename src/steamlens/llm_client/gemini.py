"""The Gemini adapter — the aspect-vocab probe's earned mechanics behind the seam.

Raw httpx over the v1beta REST surface, per the seam design (an SDK's retry
machinery would double up against the client's own, fatal under 20-requests/day
quotas). Everything provider-specific is normalized here and only here: Gemini's
finish-reason vocabulary maps into ``FinishReason``, ``usageMetadata`` into the
required ``TokenUsage`` split — including ``thoughtsTokenCount``, the field
whose omission produced the probe's 8x sticker-price surprise. Donor reference:
``probes/aspect_vocab_probe.py`` (2.5-generation ``thinkingConfig`` syntax, the
transient-status set, the header-auth shape).

The API key travels only in the request header, bound by closure at
composition — never in source, never in an error message, never in a payload
(payloads are hashed into cache keys and stored).
"""

from __future__ import annotations

import json
from typing import cast

import httpx

from steamlens.contracts import FinishReason, LlmResponse, TokenUsage
from steamlens.llm_client.errors import (
    LlmConfigError,
    ProviderPermanentError,
    ProviderTransientError,
)
from steamlens.llm_client.registry import ProviderEntry, ProviderPayload

_API_BASE = "https://generativelanguage.googleapis.com/v1beta"
_TRANSIENT_STATUSES = frozenset({429, 500, 502, 503, 504})

# Gemini's vocabulary, normalized. Everything block-shaped (safety, recitation,
# blocklists) is a refusal; anything unlisted falls to OTHER — surfaced, never
# guessed into a clean stop.
_FINISH_REASONS: dict[str, FinishReason] = {
    "STOP": FinishReason.STOP,
    "MAX_TOKENS": FinishReason.LENGTH,
    "SAFETY": FinishReason.REFUSAL,
    "RECITATION": FinishReason.REFUSAL,
    "PROHIBITED_CONTENT": FinishReason.REFUSAL,
    "BLOCKLIST": FinishReason.REFUSAL,
    "SPII": FinishReason.REFUSAL,
}


def build_payload(
    *, model: str, prompt: str, max_output_tokens: int, params: dict[str, object]
) -> ProviderPayload:
    """The generateContent body: one user part, params merged into generationConfig.

    ``params`` is the route's opaque block in Gemini's own generationConfig
    vocabulary (``temperature``, ``responseMimeType``, ``thinkingConfig``, ...),
    passed through untranslated. ``maxOutputTokens`` comes from the route's
    typed field — Gemini 2.5 counts thinking tokens against it, which is exactly
    the "total ceiling" semantics the reservation estimator prices — so a params
    key claiming it too is a config contradiction and fails loud. ``model`` is
    accepted per the ``BuildPayload`` contract but rides in the URL, not the body.
    """
    if "maxOutputTokens" in params:
        raise LlmConfigError(
            "route params must not carry 'maxOutputTokens'; "
            "set the route's max_output_tokens field instead"
        )
    return {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {"maxOutputTokens": max_output_tokens, **params},
    }


def _as_dict(value: object) -> dict[str, object]:
    """The value as a JSON object, or empty — the untrusted-shape narrowing step."""
    return cast(dict[str, object], value) if isinstance(value, dict) else {}


def _as_list(value: object) -> list[object]:
    return cast(list[object], value) if isinstance(value, list) else []


def _as_int(value: object) -> int:
    return value if isinstance(value, int) else 0


def _as_str(value: object) -> str:
    return value if isinstance(value, str) else ""


def parse_response(raw: str) -> LlmResponse:
    """Normalize one raw generateContent body — pure, so cache hits re-parse identically.

    The usage split reads ``promptTokenCount`` / ``candidatesTokenCount`` /
    ``thoughtsTokenCount``; a count that is absent or not an integer reads as an
    explicit 0 (thinking off omits its field entirely). ``modelVersion`` is the
    provider-reported resolved version; an empty string records that the
    provider did not report one. A body with no candidates is a request blocked
    outright (``promptFeedback`` carries Gemini's reason) and normalizes to a
    refusal with no text; a body that is not a JSON object at all fails loud.
    """
    parsed: object = json.loads(raw)
    if not isinstance(parsed, dict):
        raise ProviderPermanentError(
            f"gemini body is not a JSON object: {type(parsed).__name__}"
        )
    data = cast(dict[str, object], parsed)
    usage_meta = _as_dict(data.get("usageMetadata"))
    usage = TokenUsage(
        prompt_tokens=_as_int(usage_meta.get("promptTokenCount")),
        output_tokens=_as_int(usage_meta.get("candidatesTokenCount")),
        thinking_tokens=_as_int(usage_meta.get("thoughtsTokenCount")),
    )
    model_version = _as_str(data.get("modelVersion"))
    candidates = _as_list(data.get("candidates"))
    if not candidates:
        return LlmResponse(
            text="", model_version=model_version, finish_reason=FinishReason.REFUSAL, usage=usage
        )
    candidate = _as_dict(candidates[0])
    parts = _as_list(_as_dict(candidate.get("content")).get("parts"))
    text = "".join(_as_str(_as_dict(p).get("text")) for p in parts)
    finish = _FINISH_REASONS.get(_as_str(candidate.get("finishReason")), FinishReason.OTHER)
    return LlmResponse(text=text, model_version=model_version, finish_reason=finish, usage=usage)


def gemini_entry(
    api_key: str, *, timeout_s: float = 120.0, transport: httpx.BaseTransport | None = None
) -> ProviderEntry:
    """One configured Gemini vendor entry, ready for the registry.

    The composition root reads the key from the environment and calls this —
    the key binds into ``send``'s closure and travels only in the request
    header. ``transport`` is the test seam: an ``httpx.MockTransport`` serves
    canned wire fixtures with no network. The one ``httpx.Client`` is shared
    across calls (connection pooling) and is thread-safe under the caller pool.
    """
    http = httpx.Client(timeout=timeout_s, transport=transport)

    def send(*, model: str, payload: ProviderPayload) -> str:
        """POST to generateContent; transient trouble raises retryable, the rest for keeps."""
        url = f"{_API_BASE}/models/{model}:generateContent"
        try:
            resp = http.post(url, headers={"x-goog-api-key": api_key}, json=payload)
        except httpx.TransportError as exc:
            raise ProviderTransientError(f"gemini transport failure: {exc!r}") from exc
        if resp.status_code in _TRANSIENT_STATUSES:
            raise ProviderTransientError(f"gemini HTTP {resp.status_code}: {resp.text[:200]}")
        if resp.is_error:
            raise ProviderPermanentError(f"gemini HTTP {resp.status_code}: {resp.text[:500]}")
        return resp.text

    return ProviderEntry(build_payload=build_payload, send=send, parse=parse_response)
