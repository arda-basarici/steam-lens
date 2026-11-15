"""The understand step's shell — one model call, and a ladder for a faulty answer.

The step turns a conversation into a ``PlayerRequest``. The prompt and the
validation are pure and live in ``core.understand``; this module makes the
call and decides what a faulty answer costs.

The ladder has three rungs. A valid answer is used as it stands. An answer
with any fault gets one corrective retry that names the faults, which is a
new question at temperature 0 and so a real second call. If faults remain,
what can be read is kept: a want whose target is still faulty keeps the
player's words and loses the target, so it reads "cannot tell" and no want
disappears; a want whose words are not the player's stays as it is with the
fault recorded; and when the retry itself fails the first answer is salvaged
the same way. An answer whose structure cannot be read after the retry ends the
turn with a fixed reply.

Provider trouble is not retried here. The client already retried what a
retry can absorb, and a generation cut off at temperature 0 would be cut off
again. The spend cap refusing the call and provider trouble that outlasted
the client's retries end the turn as unavailable. A permanent rejection is a
configuration fault and propagates.

The step rides the labeler's model until the development cases choose one;
the route below is the one place that says so.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Final

from steamlens.contracts import (
    AspectOntology,
    ChatMessage,
    LlmRequest,
    LlmStage,
    MetricEvent,
    Sink,
    StageKind,
    Understanding,
    UnderstandOutcome,
)
from steamlens.core.understand import (
    ParsedUnderstanding,
    build_understand_prompt,
    corrective_prompt,
    parse_understand_response,
)
from steamlens.dispatch import narrate
from steamlens.dispatch.census_arm import MODEL_ID, PROVIDER
from steamlens.llm_client import (
    AtCapacityError,
    GenerationIncompleteError,
    LlmClient,
    LlmUnavailableError,
    Route,
)

UNDERSTAND_STAGE: Final = "chat.understand"

# A request with ten wants is under a thousand tokens of JSON; the cap is
# headroom. An answer that reaches it is cut off and ends the turn.
_OUTPUT_CAP: Final = 2_048


def understand_route() -> Route:
    """The understand dial: the labeler's model, temperature 0, thinking off.

    A caller hands it to the client it builds as the ``UNDERSTAND`` route.
    Moving the step to another model is this one edit.
    """
    return Route(
        provider=PROVIDER,
        model=MODEL_ID,
        max_output_tokens=_OUTPUT_CAP,
        params={"temperature": 0, "thinking": {"type": "disabled"}},
    )


def understand(
    client: LlmClient,
    conversation: Sequence[ChatMessage],
    ontology: AspectOntology,
    library: Mapping[int, str],
    sink: Sink,
    *,
    year: int,
) -> Understanding:
    """Read ``conversation`` into a request, walking the ladder on a faulty answer.

    ``conversation`` ends with the player's latest message. ``library`` maps
    each library game's app id to its title, which a caller takes from the
    library it loads for the sheet, and ``year`` is the current year; the
    caller reads the clock. Every rung narrates, and faults, salvages
    and unreadable answers are journalled as metrics.

    The result always says how it was reached. A caller answers with a fixed
    text when ``core.understand.fixed_reply`` gives one and goes on to the
    sheet otherwise.
    """
    prompt = build_understand_prompt(conversation, ontology, library, year=year)
    first = _attempt(client, prompt, conversation, ontology, library, sink)
    if isinstance(first, Understanding):
        return first
    if not first.faults:
        return Understanding(UnderstandOutcome.UNDERSTOOD, first.request)

    _count(sink, "understand_faults", len(first.faults))
    narrate(
        sink, UNDERSTAND_STAGE, StageKind.WARN,
        f"the answer had {len(first.faults)} faults — corrective retry",
    )
    second = _attempt(
        client, corrective_prompt(prompt, first.faults), conversation, ontology, library, sink
    )
    if isinstance(second, ParsedUnderstanding):
        if not second.faults:
            narrate(sink, UNDERSTAND_STAGE, StageKind.DONE, "the corrective retry read cleanly")
            return Understanding(UnderstandOutcome.RETRIED, second.request)
        _count(sink, "understand_faults", len(second.faults))

    for answer in (second, first):
        if isinstance(answer, ParsedUnderstanding) and answer.request is not None:
            _count(sink, "understand_salvaged", len(answer.faults))
            narrate(
                sink, UNDERSTAND_STAGE, StageKind.WARN,
                f"{len(answer.faults)} faults still standing — every want is kept, and one"
                " with a faulty target reads as cannot tell",
            )
            return Understanding(UnderstandOutcome.SALVAGED, answer.request, answer.faults)
    if isinstance(second, Understanding):
        return second
    _count(sink, "understand_unreadable", 1)
    narrate(
        sink, UNDERSTAND_STAGE, StageKind.WARN,
        "the answer's structure could not be read after the retry — fixed reply",
    )
    return Understanding(UnderstandOutcome.UNREADABLE, None, second.faults)


def _attempt(
    client: LlmClient,
    prompt: str,
    conversation: Sequence[ChatMessage],
    ontology: AspectOntology,
    library: Mapping[int, str],
    sink: Sink,
) -> ParsedUnderstanding | Understanding:
    """One call, validated; an ``Understanding`` when the call itself failed.

    Catches exactly what ends a turn with a fixed reply: the spend cap
    refusing, provider trouble that outlasted the client's retries, and a
    generation that did not finish. Anything else is a bug and propagates.
    """
    try:
        response = client.complete(LlmRequest(stage=LlmStage.UNDERSTAND, prompt=prompt))
    except (AtCapacityError, LlmUnavailableError) as error:
        narrate(sink, UNDERSTAND_STAGE, StageKind.WARN, f"the understand call failed: {error}")
        _count(sink, "understand_unavailable", 1)
        return Understanding(UnderstandOutcome.UNAVAILABLE, None, (str(error),))
    except GenerationIncompleteError as error:
        narrate(
            sink, UNDERSTAND_STAGE, StageKind.WARN, f"the generation did not finish: {error}"
        )
        _count(sink, "understand_unreadable", 1)
        return Understanding(
            UnderstandOutcome.UNREADABLE, None, (f"the generation did not finish: {error}",)
        )
    return parse_understand_response(response.text, ontology, library, conversation)


def _count(sink: Sink, name: str, value: int) -> None:
    sink.emit(MetricEvent(stage=UNDERSTAND_STAGE, name=name, value=float(value), unit="count"))
