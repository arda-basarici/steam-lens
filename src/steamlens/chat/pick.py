"""The pick step's shell — one model call, and a ladder for a faulty answer.

The step turns a request and the sheet read against it into a
``PickDecision``: candidates to read reviews on, a question, or the finding
that nothing fits. The prompt, the validation and the bounds are pure and
live in ``core.pick``; this module makes the call and decides what a faulty
answer costs.

The ladder is the understand step's. A valid answer is used as it stands.
An answer with any fault gets one corrective retry that names the faults,
which is a new question at temperature 0 and so a real second call. If
faults remain, what can be read is kept: a candidate the sheet does not
hold, one the player named as "like this", or one that fails a must no
review could set aside is removed and the rest of the decision stands, and
when the retry itself fails the first answer is salvaged the same way. An
answer that leaves no decision after the retry ends the turn with a fixed
reply.

An answer over a cap is not on the ladder. It is cut in the model's own
order and counted, with no retry spent on it.

Provider trouble is not retried here. The client already retried what a
retry can absorb, and a generation cut off at temperature 0 would be cut off
again. The spend cap refusing the call and provider trouble that outlasted
the client's retries end the turn as unavailable. A permanent rejection is a
configuration fault and propagates.

The step rides the labeler's model until the example conversations and the
development cases say otherwise; the route below is the one place that says
so.
"""

from __future__ import annotations

from typing import Final

from steamlens.contracts import (
    LlmRequest,
    LlmStage,
    MetricEvent,
    Pick,
    PickOutcome,
    PlayerRequest,
    Sheet,
    Sink,
    StageKind,
)
from steamlens.core.pick import (
    ParsedPick,
    build_pick_prompt,
    corrective_pick_prompt,
    parse_pick_response,
    shuffled_order,
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

PICK_STAGE: Final = "chat.pick"

# Six candidates with their wants are a few hundred tokens of JSON; the cap
# is headroom. An answer that reaches it is cut off and ends the turn.
_OUTPUT_CAP: Final = 1_024


def pick_route() -> Route:
    """The pick dial: the labeler's model, temperature 0, thinking off.

    A caller hands it to the client it builds as the ``PICK`` route. Moving
    the step to another model, or turning thinking on, is this one edit.
    """
    return Route(
        provider=PROVIDER,
        model=MODEL_ID,
        max_output_tokens=_OUTPUT_CAP,
        params={"temperature": 0, "thinking": {"type": "disabled"}},
    )


def pick(
    client: LlmClient,
    request: PlayerRequest,
    sheet: Sheet,
    sink: Sink,
    *,
    seed: str,
) -> Pick:
    """Decide a recommendation turn from ``request`` and ``sheet``, walking the ladder.

    ``sheet`` is the library read against ``request``. ``seed`` fixes the
    order of the games inside one pattern of the rendered sheet
    (``core.pick.shuffled_order``). A pick follows position, so the caller
    seeds it from the conversation and keeps the seed with the turn: the
    same request, sheet and seed give the same prompt. It has no default,
    since any fixed order would hand every player the same games. Every
    rung narrates, and faults, salvages, cuts and unreadable answers are
    journalled as metrics.

    The result always says how it was reached. A caller answers with a fixed
    text when it holds no decision and goes on to the fetch otherwise.
    """
    prompt = build_pick_prompt(request, sheet, inner_order=shuffled_order(seed))
    first = _attempt(client, prompt, request, sheet, sink)
    if isinstance(first, Pick):
        return first
    if not first.faults:
        return _decided(PickOutcome.DECIDED, first, sink)

    _count(sink, "pick_faults", len(first.faults))
    narrate(
        sink, PICK_STAGE, StageKind.WARN,
        f"the answer had {len(first.faults)} faults — corrective retry",
    )
    second = _attempt(
        client, corrective_pick_prompt(prompt, first.faults), request, sheet, sink
    )
    if isinstance(second, ParsedPick):
        if not second.faults:
            narrate(sink, PICK_STAGE, StageKind.DONE, "the corrective retry read cleanly")
            return _decided(PickOutcome.RETRIED, second, sink)
        _count(sink, "pick_faults", len(second.faults))

    for answer in (second, first):
        if isinstance(answer, ParsedPick) and answer.decision is not None:
            _count(sink, "pick_salvaged", len(answer.faults))
            narrate(
                sink, PICK_STAGE, StageKind.WARN,
                f"{len(answer.faults)} faults still standing — the decision is kept without"
                " what was faulty",
            )
            return _decided(PickOutcome.SALVAGED, answer, sink)
    if isinstance(second, Pick):
        return second
    _count(sink, "pick_unreadable", 1)
    narrate(
        sink, PICK_STAGE, StageKind.WARN,
        "the answer held no decision after the retry — fixed reply",
    )
    return Pick(PickOutcome.UNREADABLE, None, second.faults)


def _decided(outcome: PickOutcome, answer: ParsedPick, sink: Sink) -> Pick:
    """The step's result for an answer that holds a decision, with any cut journalled."""
    if answer.cut:
        _count(sink, "pick_cut", answer.cut)
        narrate(
            sink, PICK_STAGE, StageKind.WARN,
            f"the answer was {answer.cut} over a cap — cut from the end of its own order",
        )
    return Pick(outcome, answer.decision, answer.faults)


def _attempt(
    client: LlmClient, prompt: str, request: PlayerRequest, sheet: Sheet, sink: Sink
) -> ParsedPick | Pick:
    """One call, validated; a ``Pick`` when the call itself failed.

    Catches exactly what ends a turn with a fixed reply: the spend cap
    refusing, provider trouble that outlasted the client's retries, and a
    generation that did not finish. Anything else is a bug and propagates.
    """
    try:
        response = client.complete(LlmRequest(stage=LlmStage.PICK, prompt=prompt))
    except (AtCapacityError, LlmUnavailableError) as error:
        narrate(sink, PICK_STAGE, StageKind.WARN, f"the pick call failed: {error}")
        _count(sink, "pick_unavailable", 1)
        return Pick(PickOutcome.UNAVAILABLE, None, (str(error),))
    except GenerationIncompleteError as error:
        narrate(sink, PICK_STAGE, StageKind.WARN, f"the generation did not finish: {error}")
        _count(sink, "pick_unreadable", 1)
        return Pick(PickOutcome.UNREADABLE, None, (f"the generation did not finish: {error}",))
    return parse_pick_response(response.text, request, sheet)


def _count(sink: Sink, name: str, value: int) -> None:
    sink.emit(MetricEvent(stage=PICK_STAGE, name=name, value=float(value), unit="count"))
