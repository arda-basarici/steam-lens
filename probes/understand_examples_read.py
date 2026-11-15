"""Run the example conversations through the understand step, on the real model.

What it answers: what the understand step fills in for the twelve example
conversations the request structure was ruled from, read beside what each
should give. It prints every turn's request in full, the rung of the ladder
that produced it, and what the calls cost.

The examples are the players' messages as they were written. Where an
example has a second message, or points at an earlier reply ("the second
one"), the chat's reply in between is a stand-in written here, since the
judge step that would write it does not exist yet. The stand-ins name
library games and record the ones they offer, in order, the way a built
reply will; a stand-in whose offered title the library copy does not hold
stops the run.

After the twelve come contrast pairs: two requests that differ in one thing,
where a rule written for a misreading has to leave the neighbouring request
alone. The "should give" lines are reference readings for a person to
compare against. A filled request can differ from one and still be an
acceptable reading, so the probe prints both and scores nothing.

This makes paid calls: one per turn, two when an answer is retried. Answers
are archived in the database it is given, so a second run on the same copy
costs nothing.

Run:  python probes/understand_examples_read.py <path to a database copy>

The copy must be at the current schema; opening it migrates it forward, so
point this at a scratch copy and never at the dated copies under ``data/``.
The model's key is read from the environment (``DEEPSEEK_API_KEY``).
"""

from __future__ import annotations

import hashlib
import os
import sqlite3
import sys
import time
from datetime import UTC, datetime
from pathlib import Path

from steamlens.chat.sheet import load_library
from steamlens.chat.understand import understand, understand_route
from steamlens.contracts import (
    AspectTarget,
    ChatMessage,
    ChatRole,
    LlmStage,
    NameMatch,
    PlayerRequest,
    ReleaseYearsTarget,
    SinkEvent,
    StageEvent,
    StoreFactTarget,
    TermTarget,
    WantTarget,
)
from steamlens.core.game_names import resolve_name
from steamlens.core.understand import (
    UNDERSTAND_PROMPT_VERSION,
    build_understand_prompt,
    fixed_reply,
)
from steamlens.dispatch.census_arm import KEY_ENV, MODEL_ID, build_client
from steamlens.llm_client import openai_compat_entry
from steamlens.llm_client.openai_compat import DEEPSEEK_BASE_URL
from steamlens.ontology import load_ontology
from steamlens.store import Store, utc_isoformat

ONTOLOGY_PATH = Path(__file__).resolve().parent.parent / "src/steamlens/ontology/v2.toml"
BUDGET_USD = 0.25

type Turn = tuple[ChatRole, str, tuple[str, ...]]
"""One message: who wrote it, its text, and the titles of the games it offered."""

type Case = tuple[str, tuple[Turn, ...], tuple[str, ...]]
"""A title, the conversation, and what each player message should give."""


def said(text: str) -> Turn:
    """A player's message."""
    return (ChatRole.PLAYER, text, ())


def replied(text: str, *offered: str) -> Turn:
    """A stand-in reply, with the library titles of the games it offered, in order."""
    return (ChatRole.CHAT, text, offered)


EXAMPLES: tuple[Case, ...] = (
    (
        "1. An ordinary request",
        (said("i want a single player game with a good story and characters i actually care"
              " about. don't mind if it's long"),),
        ("single player: store, must · a good story: aspect story, want · characters: aspect"
         " characters, want · \"don't mind if it's long\" gives no want",),
    ),
    (
        "2. A near miss",
        (said("i want a game where my choices change the story, but i really don't want much"
              " reading. i'd prefer something short too"),),
        ("choices change the story: aspect player_choice, want (the default for an aspect) ·"
         " much reading: term, avoids, must · something short: term or none (never an"
         " aspect), nice-to-have",),
    ),
    (
        "3. Nothing fits",
        (said("got a realistic curling game? i want to play full matches, not a winter sports"
              " collection with one curling minigame"),),
        ("curling: term, must · realistic: aspect realism, or kept with none · full matches:"
         " a term, or kept with none · substitutes ruled out",),
    ),
    (
        "4. A condition that cannot be checked",
        (said("something relaxing that will run at 60 fps on my laptop. it's got intel"
              " integrated graphics but i don't know which one"),),
        ("relaxing: aspect relaxation, want · 60 fps on my laptop: aspect performance,"
         " partial, the words keeping the integrated graphics",),
    ),
    (
        "5. A requirement changed mid-chat",
        (
            said("looking for something scary to play alone, with a good story"),
            replied("Two from the library could suit you: SILENT HILL 2 and Little Nightmares."
                    " Both are played alone, and players who talk about the story mostly praise"
                    " it.",
                    "SILENT HILL 2", "Little Nightmares"),
            said("actually my friend wants to join. we each have a pc, so it needs online"
                 " co-op. story isn't important now"),
        ),
        (
            "scary: term, must (the default for a term that says what the game is) · alone:"
            " store single-player, must · good story: aspect story, want",
            "scary stays · online co-op: store online-co-op, must · single player and story"
            " are gone",
        ),
    ),
    (
        '6. "Like X", with X in the library',
        (said("something like Hades? loved the characters and having another go after dying,"
              " but i'd like something a bit less frantic"),),
        ("Hades: like-this, liked, in the library · the characters: aspect characters, want,"
         " liked in Hades · another go after dying: aspect replayability or a term, want,"
         " liked in Hades · less frantic: term, avoids, want, compared to Hades",),
    ),
    (
        '7. "Like X", with X not in the library',
        (said("anything like Balatro? been playing it loads lately"),),
        ("Balatro: like-this, liked, not in the library · no wants",),
    ),
    (
        "8. Too vague to pick usefully",
        (said("bored of everything lately. what should i play"),),
        ("recommend, no named game, no wants",),
    ),
    (
        "9. Already played a suggestion",
        (said("i want something peaceful where i can build a little place of my own. already"
              " played Stardew Valley, so something else please"),),
        ("Stardew Valley: not-this, unknown · peaceful: aspect relaxation, want · build a"
         " place of my own: term, want",),
    ),
    (
        "10. A follow-up without spoilers",
        (
            said("i want a game with a really good story"),
            replied("Three from the library stand out for their story: Disco Elysium - The Final"
                    " Cut, Baldur's Gate 3, and The Wolf Among Us.",
                    "Disco Elysium - The Final Cut", "Baldur's Gate 3", "The Wolf Among Us"),
            said("the second one sounds good. what do people like about the story? no spoilers"
                 " please"),
        ),
        (
            'a really good story: aspect story, want ("really" is degree here, not stress)',
            'about-game · "the second one": Baldur\'s Gate 3, ask-about · asks: aspect'
            ' story · the story want stays · "no spoilers" gives nothing · show evidence no',
        ),
    ),
    (
        "11. Understanding a number",
        (
            said("is hades any good?"),
            replied("Players who talk about the combat mostly praise it, and about 20% of the"
                    " reviews held for it mention the story."),
            said("when you say 20% mention the story, does that mean the other 80% didn't"
                 " like it?"),
        ),
        (
            "about-game · Hades: ask-about · asks whether it is any good: none",
            "about-numbers · the question kept as words, target none · no wants",
        ),
    ),
    (
        "12. Dropping one preference while keeping another",
        (
            said("i want a puzzle game, nothing with a timer. nice music would be a bonus"),
            replied("Blue Prince and Return of the Obra Dinn are both puzzle games here.",
                    "Blue Prince", "Return of the Obra Dinn"),
            said("forget the music, i usually play muted anyway"),
        ),
        (
            "puzzle: term, must · a timer: term, avoids, must · nice music: aspect music,"
            " nice-to-have",
            "the music want is gone · puzzle and no timer stay",
        ),
    ),
)

# Pairs that differ in one thing, written after the first run of the examples
# above. Each pair checks that a rule added for a misreading does not reach
# the neighbouring case it should leave alone.
CONTRASTS: tuple[Case, ...] = (
    (
        "A1. A want replaced without saying so",
        (
            said("something eerie i can play on my own"),
            replied("Two from the library could suit you: SILENT HILL 2 and Little Nightmares.",
                    "SILENT HILL 2", "Little Nightmares"),
            said("my friend is joining instead, so it has to be online co-op"),
        ),
        (
            "eerie: term, must · on my own: store single-player, must",
            "eerie stays · online co-op: store, must · single player is gone",
        ),
    ),
    (
        "A2. A want added beside the first",
        (
            said("something eerie with online co-op for me and a friend"),
            replied("Lethal Company is the one here that fits both.", "Lethal Company"),
            said("i also want to be able to play it alone when he is busy"),
        ),
        (
            "eerie: term, must · online co-op: store, must",
            "eerie and online co-op stay · play it alone: store single-player",
        ),
    ),
    (
        "A3. A replacement with no signal word",
        (
            said("a farming game i can play solo"),
            replied("Stardew Valley and Graveyard Keeper are both here.",
                    "Stardew Valley", "Graveyard Keeper"),
            said("change of plans, my sister wants in. we would play online together"),
        ),
        (
            "farming: term, must · solo: store single-player, must",
            "farming stays · playing online together: store online co-op · solo is gone,"
            " not kept at a lower firmness",
        ),
    ),
    (
        "B1. A kind of game the store list does not name",
        (said("a puzzle game"),),
        ("puzzle: term, must",),
    ),
    (
        "B2. A genre the store list does name",
        (said("something casual"),),
        ("casual: store casual, must",),
    ),
    (
        "C1. A thing to avoid",
        (said("no timers please"),),
        ("timers: term, avoids, must · never the timed-input store fact",),
    ),
    (
        "C2. The same thing wanted",
        (said("i enjoy timed puzzles"),),
        ("timed puzzles: a term, wants · never avoids",),
    ),
    (
        "C3. The thing to avoid, said another way",
        (said("a strategy game without time limits"),),
        ("strategy: store strategy, must · time limits: term, avoids · never the timed-input"
         " store fact",),
    ),
    (
        "D1. Other games asked for",
        (
            said("a farming game i can play solo"),
            replied("Stardew Valley and Graveyard Keeper are both here.",
                    "Stardew Valley", "Graveyard Keeper"),
            said("anything else?"),
        ),
        (
            "farming: term, must · solo: store single-player, must",
            "both wants stay · other games yes · no named game",
        ),
    ),
    (
        "D2. A want added after the offers",
        (
            said("a farming game i can play solo"),
            replied("Stardew Valley and Graveyard Keeper are both here.",
                    "Stardew Valley", "Graveyard Keeper"),
            said("it should have nice music too"),
        ),
        (
            "farming: term, must · solo: store single-player, must",
            "both wants stay · nice music: aspect music · other games no",
        ),
    ),
    (
        "D3. An offer pointed at by its place in the list",
        (
            said("a farming game i can play solo. already played stardew valley"),
            replied("Leaving Stardew Valley out, since you have played it: Graveyard Keeper and"
                    " Farming Simulator 25 are both here.",
                    "Graveyard Keeper", "Farming Simulator 25"),
            said("is the first one relaxing?"),
        ),
        (
            "farming: term, must · solo: store single-player, must · Stardew Valley: not-this",
            'about-game · "the first one": Graveyard Keeper, the first offered and not the'
            " first mentioned · asks: aspect relaxation · Stardew Valley stays not-this ·"
            " other games no",
        ),
    ),
)


class PrintingSink:
    """Prints the understand step's narration, so a retry is visible as it happens."""

    def emit(self, event: SinkEvent) -> None:
        if isinstance(event, StageEvent) and event.stage.startswith("chat."):
            print(f"      [{event.kind.value}] {event.message}")


def offered_ids(titles: tuple[str, ...], names: dict[int, str]) -> tuple[int, ...]:
    """The app ids of a stand-in's offered games, each title exactly as the library has it.

    A stand-in that offers a game the copy does not hold would test nothing
    the built chat can do, so a title that is not one whole library title
    stops the run.
    """
    ids: list[int] = []
    for title in titles:
        found = resolve_name([title], names)
        if found.match is not NameMatch.EXACT or found.app_id is None:
            raise SystemExit(
                f"the stand-in offers {title!r}, which is not one whole title in this"
                f" library copy ({found.match.value}) — offer a game the copy holds"
            )
        ids.append(found.app_id)
    return tuple(ids)


def describe_target(target: WantTarget | None) -> str:
    match target:
        case None:
            return "none"
        case StoreFactTarget(key=key):
            return f"store {key}"
        case ReleaseYearsTarget(first=first, last=last):
            return f"years {first or '..'} to {last or '..'}"
        case AspectTarget(aspect=aspect):
            return f"aspect {aspect}"
        case TermTarget(phrases=phrases):
            return "term " + " / ".join(phrases)


def print_request(request: PlayerRequest, names: dict[int, str]) -> None:
    flags = [
        name for name, on in (
            ("substitutes ruled out", request.substitutes_ruled_out),
            ("show evidence", request.show_evidence),
            ("other games", request.other_games),
        ) if on
    ]
    print(f"      intent {request.intent.value}" + "".join(f" · {flag}" for flag in flags))
    for game in request.named_games:
        landed = (
            names[game.app_id] if game.app_id is not None
            else "one of " + "; ".join(names[app_id] for app_id in game.candidates)
            if game.candidates else "-"
        )
        print(
            f"      named  {game.words!r} · title {game.title!r} · {game.match.value}: {landed}"
            f" · {game.role.value} · {game.feeling.value}"
            + (f" · liked: {'; '.join(game.liked_parts)}" if game.liked_parts else "")
        )
    for want in request.wants:
        marks = "".join(
            f" · {mark}" for mark in (
                "partial" if want.partial else "",
                f"compared to {want.compared_to!r}" if want.compared_to else "",
                f"liked in {want.liked_in!r}" if want.liked_in else "",
            ) if mark
        )
        print(
            f"      {want.firmness.value:<12} {want.stance.value:<6} {want.words!r}"
            f"  ->  {describe_target(want.target)}{marks}"
        )
    for subject in request.subjects:
        print(f"      asks   {subject.words!r}  ->  {describe_target(subject.target)}")


def main(db_path: str) -> None:
    key = os.environ.get(KEY_ENV)
    if not key:
        raise SystemExit(f"{KEY_ENV} is not set — the probe calls the real model and needs it")
    ontology = load_ontology(ONTOLOGY_PATH)
    year = datetime.now(UTC).year
    started_at = datetime.now(UTC)
    sink = PrintingSink()

    with Store(db_path) as store:
        library = load_library(store)
        names = {game.app_id: game.name for game in library}
        client = build_client(
            openai_compat_entry(key, base_url=DEEPSEEK_BASE_URL), BUDGET_USD, 1, store, sink,
            extra_routes={LlmStage.UNDERSTAND: understand_route()},
        )
        sample = build_understand_prompt(
            (ChatMessage(ChatRole.PLAYER, "hi"),), ontology, names, year=year
        )
        print(
            f"model {MODEL_ID} · prompt {UNDERSTAND_PROMPT_VERSION} · stable part"
            f" {len(sample):,} characters, sha256 "
            f"{hashlib.sha256(sample.encode('utf-8')).hexdigest()[:12]} · library"
            f" {len(library)} games · year {year}\n"
        )
        outcomes: list[str] = []
        for title, turns, expected in (*EXAMPLES, *CONTRASTS):
            print(title)
            conversation: list[ChatMessage] = []
            player_turn = 0
            for role, text, offered in turns:
                conversation.append(ChatMessage(role, text, offered_ids(offered, names)))
                if role is ChatRole.CHAT:
                    print(f"   chat (stand-in): {text}")
                    if offered:
                        numbered = (f"{n}. {name}" for n, name in enumerate(offered, start=1))
                        print(f"      offered: {' · '.join(numbered)}")
                    continue
                print(f"   player: {text}")
                print(f"   should give: {expected[player_turn]}")
                player_turn += 1
                clock = time.perf_counter()
                understanding = understand(client, conversation, ontology, names, sink, year=year)
                seconds = time.perf_counter() - clock
                outcomes.append(understanding.outcome.value)
                print(f"   filled in ({understanding.outcome.value}, {seconds:.1f} s):")
                if understanding.request is not None:
                    print_request(understanding.request, names)
                for fault in understanding.faults:
                    print(f"      fault: {fault}")
                reply = fixed_reply(understanding)
                if reply is not None:
                    print(f"      fixed reply: {reply}")
            print()

    print("outcomes: " + ", ".join(f"{outcomes.count(o)} {o}" for o in sorted(set(outcomes))))
    rows = sqlite3.connect(db_path).execute(
        "SELECT prompt_tokens, cached_prompt_tokens, output_tokens, duration_s, cost"
        " FROM spend_ledger WHERE stage = 'understand' AND created_at >= ? ORDER BY id",
        (utc_isoformat(started_at),),
    ).fetchall()
    if not rows:
        print("no paid call in this run: every answer came from the archive")
        return
    print(f"paid calls in this run: {len(rows)} · total ${sum(row[4] for row in rows):.5f}")
    print(
        f"   {'prompt tok':>10} {'of them cached':>15} {'output tok':>11} {'seconds':>8}"
        f" {'usd':>9}"
    )
    for prompt, cached, output, duration, cost in rows:
        print(f"   {prompt:>10} {cached or 0:>15} {output:>11} {duration:>8.2f} {cost:>9.5f}")


if __name__ == "__main__":
    main(sys.argv[1])
