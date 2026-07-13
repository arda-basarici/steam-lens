"""The one door to models — the provider seam every LLM call goes through.

The public surface: ``LlmClient.complete`` over the contracts' stage-keyed
request, dialed by ``LlmClientConfig`` (routes, model envelopes, prices, the
budget cap), served by provider *functions* registered in ``registry``, with
typed failures in ``errors`` and in-memory cache/ledger bindings in ``memory``
until the durable pair lands with the store. Design record: DESIGN.md's two
``llm_client`` operational-decisions entries (2026-07-13).
"""

from steamlens.llm_client.client import LlmClient
from steamlens.llm_client.config import LlmClientConfig, ModelSpec, Route
from steamlens.llm_client.errors import (
    AtCapacityError,
    GenerationIncompleteError,
    LlmConfigError,
    LlmError,
    LlmUnavailableError,
    ProviderPermanentError,
    ProviderTransientError,
)
from steamlens.llm_client.gemini import gemini_entry
from steamlens.llm_client.memory import InMemoryClassifyCache, InMemorySpendLedger
from steamlens.llm_client.registry import (
    PROVIDERS,
    BuildPayload,
    ParseResponse,
    ProviderEntry,
    ProviderPayload,
    SendRequest,
    register_provider,
)

__all__ = [
    # the client
    "LlmClient",
    # config
    "LlmClientConfig",
    "Route",
    "ModelSpec",
    # registry
    "ProviderEntry",
    "ProviderPayload",
    "BuildPayload",
    "SendRequest",
    "ParseResponse",
    "PROVIDERS",
    "register_provider",
    # adapters
    "gemini_entry",
    # errors
    "LlmError",
    "LlmConfigError",
    "AtCapacityError",
    "LlmUnavailableError",
    "ProviderTransientError",
    "ProviderPermanentError",
    "GenerationIncompleteError",
    # in-memory bindings
    "InMemoryClassifyCache",
    "InMemorySpendLedger",
]
