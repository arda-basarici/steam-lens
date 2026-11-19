"""Run the example conversations through a whole chat turn, on the real model.

What it answers: what the chat says to the twelve example conversations the
request structure was ruled from, when every step runs as built: the
understand step, the sheet, the pick, the fetch, the answer with its check.
Each turn goes through ``chat.turn.turn``, the function the page will call,
so a reply read here went the way a reply shown to a player goes.

For each turn it prints the player's message, what a good reply would do
(the line ruled for that example), the request as read, each step's rung,
the pick's decision, the reply as the player reads it, and then the reply's
statements one by one with each cited excerpt beside the sentence that
rests on it, so the sentence can be read against the reviews behind it.
What the check objected to is printed with how each objection ended. The
probe scores nothing: whether a reply is good is read by hand against the
ruled line.

The conversations are the players' messages as they were written. Where an
example has a second message, the chat's reply in between is the real one
from the turn before. Example 10 ("the second one sounds good") needs an
earlier reply that offered games, and follows example 1's, which asked for
a story. When that reply offered fewer than two games the probe says so and
the turn runs as it falls.

Five examples need behaviour the first stage does not have: nothing fits
(3), an unmeasured game (7), a vague request (8), a question beside
suggestions (9) and the numbers question (11). They run like the others
and carry a note saying what the second stage adds.

Each example runs under one fixed seed, printed with it, since the pick
follows the order of the games on its sheet and the seed fixes that order.
``--seed`` runs the set under another. ``--sheets`` also prints the wants
and the sheet as the pick call read them.

This makes paid calls: three per turn at most times two, since each step
may retry once. Answers are archived in the database it is given, so a
second run on the same copy and seed costs nothing.

Run:  python probes/turn_examples_read.py <path to a database copy> [--sheets] [--seed NAME]

The copy must be at the current schema; opening it migrates it forward, so
point this at a scratch copy and never at the dated copies under ``data/``.
The model's key is read from the environment (``DEEPSEEK_API_KEY``).
"""

from __future__ import annotations

import argparse
import os
import sqlite3
import sys
import time
from collections import Counter
from dataclasses import dataclass
from datetime import UTC, datetime
from statistics import median

from understand_examples_read import BUDGET_USD, ONTOLOGY_PATH, PrintingSink, print_request

from steamlens.chat.sheet import load_library
from steamlens.chat.turn import chat_routes, turn
from steamlens.contracts import (
    AnswerBasis,
    AskDecision,
    CandidatesDecision,
    CandidatesMaterial,
    ChatMessage,
    ChatRole,
    CitedExcerpt,
    NothingFitsDecision,
    OneGameMaterial,
    Pick,
    PlayerRequest,
    Reply,
    Turn,
)
from steamlens.core.answer import ANSWER_PROMPT_VERSION
from steamlens.core.pick import (
    PICK_PROMPT_VERSION,
    render_pick_sheet,
    render_wants,
    shuffled_order,
)
from steamlens.core.understand import UNDERSTAND_PROMPT_VERSION
from steamlens.dispatch.census_arm import KEY_ENV, MODEL_ID, build_client
from steamlens.llm_client import openai_compat_entry
from steamlens.llm_client.openai_compat import DEEPSEEK_BASE_URL
from steamlens.ontology import load_ontology
from steamlens.store import Store, utc_isoformat


@dataclass(frozen=True)
class Example:
    """One example conversation: the player's messages and the line ruled for each.

    ``follows`` is the number of the example whose finished conversation
    this one continues. ``stage_two`` is set for an example the first stage
    cannot complete, and says what the second stage adds.
    """

    number: int
    title: str
    messages: tuple[str, ...]
    good_reply: tuple[str, ...]
    follows: int | None = None
    stage_two: str | None = None


EXAMPLES: tuple[Example, ...] = (
    Example(
        1, "An ordinary request",
        ("i want a single player game with a good story and characters i actually care about."
         " don't mind if it's long",),
        ("suggest a few library games whose evidence supports the story and character"
         " preferences, after checking single-player support. \"Don't mind if it's long\" says"
         " length does not matter, so it is not treated as a want.",),
    ),
    Example(
        2, "A near miss",
        ("i want a game where my choices change the story, but i really don't want much"
         " reading. i'd prefer something short too",),
        ("look for all three preferences. \"Really don't want much reading\" is stressed, so a"
         " text-heavy game is not offered. \"I'd prefer something short too\" is soft, so a"
         " longer game with meaningful choices and little reading may be offered as a near"
         " miss, with its length named. Whether the closest game is close enough to be worth"
         " offering is the chat's judgment, and it should not reach far.",),
    ),
    Example(
        3, "Nothing fits",
        ("got a realistic curling game? i want to play full matches, not a winter sports"
         " collection with one curling minigame",),
        ("say the library holds nothing for this, without substituting another sport or"
         " claiming no such game exists anywhere; say the library is a hand-picked set of"
         " measured games; link the report flow so a curling game the player knows can be"
         " analysed. No neighbour is offered, because this player ruled substitutes out.",),
        stage_two=(
            "the second stage adds a question about a neighbouring kind of game when the"
            " player did not rule substitutes out. This player did, so nothing of it is"
            " missing here. The link for adding a game is the page's to show."
        ),
    ),
    Example(
        4, "A condition the system probably cannot check",
        ("something relaxing that will run at 60 fps on my laptop. it's got intel integrated"
         " graphics but i don't know which one",),
        ("offer relaxing candidates and, next to each, say what was and was not looked at:"
         " nothing here tells how a game runs on a particular laptop; what the reports do hold"
         " is whether reviewers complain about performance, so games whose performance is"
         " clearly criticised are left out and that is said. No game is called a fit for the"
         " laptop.",),
    ),
    Example(
        5, "A requirement changed mid-chat",
        ("looking for something scary to play alone, with a good story",
         "actually my friend wants to join. we each have a pc, so it needs online co-op."
         " story isn't important now"),
        ("suggest supported single-player horror options with story evidence.",
         "replace solo play with online co-op, drop the story preference, keep the horror"
         " preference though the player did not repeat it, and redo the suggestions."),
    ),
    Example(
        6, '"Like X", with X in the library',
        ("something like Hades? loved the characters and having another go after dying, but"
         " i'd like something a bit less frantic",),
        ("use Hades's stored evidence and the player's stated likes (the characters, another"
         " go after dying) to find alternatives. On \"less frantic\", compare a suggestion with"
         " Hades in words when reviews of both games speak to pace, and otherwise say what the"
         " suggestion's own reviews do and do not show about pace.",),
    ),
    Example(
        7, '"Like X", with X not in the library',
        ("anything like Balatro? been playing it loads lately",),
        ("say Balatro is not measured here, offer to have it analysed first (the link to the"
         " report flow), and ask what the player likes about it, using what the model knows of"
         " the game only to make that question a good one. No suggestion is made from the"
         " model's memory of Balatro.",),
        stage_two=(
            "the second stage answers an unmeasured game by name: it is not measured, here is"
            " the link, what do you like in it. The first stage sends this request to the pick"
            " with no wants, and a reply that only asks is told to name no game."
        ),
    ),
    Example(
        8, "Too vague to pick usefully",
        ("bored of everything lately. what should i play",),
        ("ask instead of producing an unexplained list. With nothing at all to go on, up to"
         " two or three easy questions are fine. If the answers are still no help, offer a"
         " small varied handful of well-received games of different kinds, said plainly to be"
         " a starting set and not a fit.",),
        stage_two=(
            "the second stage adds the count of questions asked before suggesting, and the"
            " starting set once they are spent."
        ),
    ),
    Example(
        9, "Already played a suggestion",
        ("i want something peaceful where i can build a little place of my own. already played"
         " Stardew Valley, so something else please",),
        ("leave Stardew Valley out, and ask whether the player liked it and what they liked"
         " about it, since \"already played\" does not say. The stated wants are enough to"
         " suggest from, so the question can come alongside the suggestions.",),
        stage_two=(
            "the second stage adds the question put beside suggestions. In the first stage a"
            " reply that offers games asks nothing."
        ),
    ),
    Example(
        10, "A follow-up without spoilers",
        ("the second one sounds good. what do people like about the story? no spoilers"
         " please",),
        ("resolve \"the second one\" from the chat's previous reply (and ask which game if"
         " that is ambiguous), then say in plain words what reviewers praise about the story,"
         " with no plot events and no review quotes.",),
        follows=1,
    ),
    Example(
        11, "Understanding a number",
        ("when you say 20% mention the story, does that mean the other 80% didn't like it?",),
        ("explain that not mentioning the story is different from disliking it, without"
         " treating the player's illustrative numbers as verified report values.",),
        stage_two=(
            "the second stage adds the explanation. The first stage ends this turn on a"
            " stand-in text."
        ),
    ),
    Example(
        12, "Dropping one preference while keeping another",
        ("i want a puzzle game, nothing with a timer. nice music would be a bonus",
         "forget the music, i usually play muted anyway"),
        ("suggest puzzle games, treat music as an optional preference, and for the timer say"
         " what the search found and what that does not show.",
         "drop only the music preference and retain the puzzle and no-timer requirements."),
    ),
)


def excerpts_of(basis: AnswerBasis | None) -> dict[str, str]:
    """Every excerpt of a turn's material by its identifier, with the title of its game."""

    def under(title: str, cited: tuple[CitedExcerpt, ...]) -> dict[str, str]:
        return {one.identifier: f"[{title}] {one.excerpt.text}" for one in cited}

    found: dict[str, str] = {}
    match basis:
        case CandidatesMaterial():
            games = basis.games
        case OneGameMaterial():
            for subject in basis.subjects:
                found |= under(basis.title, subject.excerpts)
            games = (basis.standing_wants,) if basis.standing_wants is not None else ()
        case _:
            return found
    for game in games:
        for want in game.wants:
            found |= under(game.title, want.excerpts)
    for side in basis.named_sides:
        found |= under(f"{side.title}, the named game", side.excerpts)
    return found


def describe_pick(pick: Pick, names: dict[int, str]) -> str:
    """The pick's decision in one line.

    The wants beside a candidate are the ones the pick asked reviews on.
    They set an order only: code decides what is read, so a candidate with
    none listed is still read on its wants.
    """
    match pick.decision:
        case None:
            return "no decision"
        case CandidatesDecision(candidates=candidates):
            return "candidates: " + " · ".join(
                names[candidate.app_id]
                + (" (asks for " + ", ".join(f"w{want + 1}" for want in candidate.wants) + ")"
                   if candidate.wants else " (asks for no want)")
                for candidate in candidates
            )
        case AskDecision(needs=needs):
            return "ask, needing: " + " · ".join(needs)
        case NothingFitsDecision(unmet=unmet):
            return "nothing fits, unmet: " + (", ".join(f"w{want + 1}" for want in unmet) or "-")


def print_reply(reply: Reply, basis: AnswerBasis | None, names: dict[int, str]) -> None:
    """The reply's statements, each with its game, its wants and its cited excerpts."""
    excerpts = excerpts_of(basis)
    for number, statement in enumerate(reply.statements, start=1):
        game = "-"
        if statement.game is not None:
            game = names[statement.game] + (" · OFFERS" if statement.offers else " · about")
        wants = ", ".join(f"w{position + 1}" for position in statement.wants) or "-"
        print(f"      {number}. [{game}] [wants: {wants}] {statement.text}")
        for cite in statement.cites:
            print(f"            {cite}: {excerpts[cite][:280]!r}")
    words = sum(len(statement.text.split()) for statement in reply.statements)
    print(f"      {words} words")
    if isinstance(basis, CandidatesMaterial):
        spoken = {statement.game for statement in reply.statements}
        aside = [
            game.title for game in basis.games
            if game.app_id in spoken and game.app_id not in reply.offered
        ]
        silent = [game.title for game in basis.games if game.app_id not in spoken]
        print(f"      set aside with a statement: {', '.join(aside) or 'none'}")
        print(f"      left out unmentioned: {', '.join(silent) or 'none'}")


def print_turn(
    result: Turn, seconds: float, names: dict[int, str], *, sheets: bool
) -> None:
    understanding = result.understanding
    print(f"   understand: {understanding.outcome.value}")
    request: PlayerRequest | None = understanding.request
    if request is not None:
        print_request(request, names)
    for fault in understanding.faults:
        print(f"      fault: {fault}")
    if sheets and request is not None and result.sheet is not None:
        print("   the wants and the sheet, as the pick call read them:")
        rendered = render_pick_sheet(
            request, result.sheet, inner_order=shuffled_order(result.seed)
        )
        for line in (*render_wants(request).splitlines(), *rendered.splitlines()):
            print(f"      | {line}")
    if result.pick is not None:
        print(f"   pick: {result.pick.outcome.value} · {describe_pick(result.pick, names)}")
        for fault in result.pick.faults:
            print(f"      fault: {fault}")
    if isinstance(result.basis, OneGameMaterial):
        print(f"   about one game: {result.basis.title}")
    if result.answer is not None:
        print(f"   answer: {result.answer.outcome.value}")
        for fault in result.answer.faults:
            print(f"      fault: {fault}")
        for settled in result.answer.objections:
            objection = settled.objection
            about = names.get(objection.game, "-") if objection.game is not None else "-"
            want = f"w{objection.want + 1}" if objection.want is not None else "-"
            print(
                f"      objection: {objection.rule.value} ({about}, {want})"
                f" -> {settled.rung.value}"
            )
    message = result.message
    kind = message.kind.value if message.kind is not None else "-"
    print(f"   ended: {result.ending.value} · message kind {kind} · {seconds:.1f} s")
    print(f"   THE CHAT SAYS: {message.text}")
    if message.offered:
        numbered = (f"{n}. {names[app_id]}" for n, app_id in enumerate(message.offered, start=1))
        print(f"      offered: {' · '.join(numbered)}")
    if result.answer is not None and result.answer.reply is not None:
        print_reply(result.answer.reply, result.basis, names)


def main(db_path: str, *, sheets: bool, seed_name: str) -> None:
    key = os.environ.get(KEY_ENV)
    if not key:
        raise SystemExit(f"{KEY_ENV} is not set — the probe calls the real model and needs it")
    ontology = load_ontology(ONTOLOGY_PATH)
    year = datetime.now(UTC).year
    started_at = datetime.now(UTC)
    sink = PrintingSink()

    with Store(db_path) as store:
        names = {game.app_id: game.name for game in load_library(store)}
        client = build_client(
            openai_compat_entry(key, base_url=DEEPSEEK_BASE_URL), BUDGET_USD, 1, store, sink,
            extra_routes=chat_routes(),
        )
        print(
            f"model {MODEL_ID} · prompts {UNDERSTAND_PROMPT_VERSION}, {PICK_PROMPT_VERSION},"
            f" {ANSWER_PROMPT_VERSION} · library {len(names)} games · year {year}\n"
        )
        finished: dict[int, list[ChatMessage]] = {}
        endings: Counter[str] = Counter()
        durations: list[float] = []
        for example in EXAMPLES:
            seed = f"{seed_name}-{example.number}"
            print(f"{example.number}. {example.title} · seed {seed}")
            if example.stage_two is not None:
                print(f"   INCOMPLETE BY DESIGN: {example.stage_two}")
            conversation: list[ChatMessage] = []
            if example.follows is not None:
                conversation = list(finished[example.follows])
                earlier = conversation[-1]
                print(f"   continues example {example.follows}, whose reply was: {earlier.text}")
                print(
                    "      offered: "
                    + (" · ".join(names[app_id] for app_id in earlier.offered) or "no game")
                )
                if len(earlier.offered) < 2:
                    print(
                        "      NOTE: that reply offered fewer than two games, so this"
                        " example's reference to one of them has nothing to land on"
                    )
            for text, good_reply in zip(example.messages, example.good_reply, strict=True):
                conversation.append(ChatMessage(ChatRole.PLAYER, text))
                print(f"   player: {text}")
                print(f"   a good reply would: {good_reply}")
                clock = time.perf_counter()
                result = turn(client, store, conversation, ontology, sink, seed=seed, year=year)
                seconds = time.perf_counter() - clock
                durations.append(seconds)
                endings[result.ending.value] += 1
                print_turn(result, seconds, names, sheets=sheets)
                conversation.append(result.message)
                print()
            finished[example.number] = conversation

    print(
        f"{len(durations)} turns · endings: "
        + ", ".join(f"{count} {ending}" for ending, count in sorted(endings.items()))
    )
    print(f"seconds a turn: median {median(durations):.1f}, longest {max(durations):.1f}")
    rows = sqlite3.connect(db_path).execute(
        "SELECT stage, COUNT(*), SUM(prompt_tokens), SUM(output_tokens), SUM(cost)"
        " FROM spend_ledger WHERE created_at >= ? GROUP BY stage ORDER BY stage",
        (utc_isoformat(started_at),),
    ).fetchall()
    if not rows:
        print("no paid call in this run: every answer came from the archive")
        return
    print(f"paid calls in this run (the cap is ${BUDGET_USD}):")
    print(f"   {'stage':<12} {'calls':>6} {'prompt tok':>11} {'output tok':>11} {'usd':>9}")
    for stage, calls, prompt, output, cost in rows:
        print(f"   {stage:<12} {calls:>6} {prompt:>11} {output:>11} {cost:>9.5f}")
    print(f"   total ${sum(row[4] for row in rows):.5f}")


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[union-attr]
    parser = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    parser.add_argument("database", help="a scratch copy of the serving database")
    parser.add_argument("--sheets", action="store_true", help="print the pick's wants and sheet")
    parser.add_argument("--seed", default="example", help="the seed's name; the number is added")
    arguments = parser.parse_args()
    main(arguments.database, sheets=arguments.sheets, seed_name=arguments.seed)
