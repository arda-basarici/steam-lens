"""The store facts the chat may match a want against, and how each is read on a game.

The store's metadata says what kind of game something is, and it says it
three ways. This module is the one place that tells them apart.

Play modes, platforms and early access are complete: every game declares
them, so a game without "Online Co-op" has no online co-op. All 115 library
games read on 2026-11-14 carried a single-player or a multi-player category.

Features are declared by choice: adjustable difficulty, saving anywhere,
controller support. 24 of those 115 games declared adjustable difficulty,
and the 91 that did not include games with difficulty settings, so only the
presence of such a fact is evidence.

Genres are complete and coarse, and they miss. The store does not list Dark
Souls III as an RPG, or Cities: Skylines II as a strategy game, while players
tag both. Review search does not fill the gap (genre words reach 1.3% of Dark
Souls III's reviews, under the cluster line), so each genre carries the
community tags that name the same kind. A game the store does not list and
players tag is "cannot tell": never a match, since the tags mislead too (Mad
Max is tagged Racing), and never a failure. This is the one place the chat's
pipeline reads the tags, and it never shows them.

The vocabulary is curated. Of the 57 category ids the library held, the ones
left out say nothing about the game a player would ask for: trading cards,
family sharing, cloud saves, sound formats, the controller brands. Early
access carries no tag, because the "Early Access" tag outlives the status
(10 tagged games, 4 in early access). Changing what the chat can match
against is an edit to ``STORE_FACTS`` and nothing else.

Each fact also carries the search words that find reviews about its subject.
The store's answer can be wrong or silent, so a game offered against it, or
asked about, is read in its reviews, and the words that fetch them are
written here once instead of by a model on each call: the same words run
every time and each list was read against the store's listing
(``probes/store_fact_words_probe.py``). The lists are short and literal,
since the index has no stemming. A word that also means something else was
left out when the reviews it found were about the other thing: "races" finds
a role-playing game's playable races, "simulator" a joke title, "versus" a
game's name. A match says a review is about the subject and not which way it
points, so matches are read and never counted.
"""

from __future__ import annotations

from collections.abc import Collection
from typing import Final

from steamlens.contracts import (
    EARLY_ACCESS_GENRE_ID,
    ReleaseYearsTarget,
    Stance,
    StoreFactDef,
    StoreFactSource,
    StorefrontMetadata,
    StorefrontTagCapture,
    WantFinding,
    WantReading,
    WantStatus,
)


def _genre(
    key: str, label: str, genre_id: int, *player_tags: str, words: tuple[str, ...]
) -> StoreFactDef:
    return StoreFactDef(
        key=key, label=label, source=StoreFactSource.GENRE, complete=True,
        ids=(genre_id,), player_tags=player_tags, search_words=words,
    )


def _category(
    key: str, label: str, category_id: int, *, complete: bool, words: tuple[str, ...],
    note: str = "", avoidable: bool = True,
) -> StoreFactDef:
    return StoreFactDef(
        key=key, label=label, source=StoreFactSource.CATEGORY, complete=complete,
        ids=(category_id,), note=note, avoidable=avoidable, search_words=words,
    )


def _platform(
    key: str, label: str, source: StoreFactSource, *, words: tuple[str, ...]
) -> StoreFactDef:
    return StoreFactDef(key=key, label=label, source=source, complete=True, search_words=words)


# Search words several facts share, since reviewers do not tell them apart.
_LOCAL_PLAY: Final = ("split screen", "splitscreen", "couch co-op", "couch coop")
_CONTROLLER: Final = ("controller", "gamepad")
_MMO: Final = ("mmo", "mmorpg", "massively multiplayer")
_LAN: Final = ("lan", "local network")

STORE_FACTS: Final[tuple[StoreFactDef, ...]] = (
    # Genres, each with the community tags that name the genre or a kind of it.
    _genre("action", "Action", 1,
           "Action", "Action-Adventure", "Action RPG", "Action Roguelike", "Action RTS",
           "Character Action Game",
           words=("action game", "action games", "action packed", "fast paced action")),
    _genre("adventure", "Adventure", 25,
           "Adventure", "Action-Adventure", "Choose Your Own Adventure",
           words=("adventure game", "adventure games", "action adventure", "point and click")),
    _genre("rpg", "RPG", 3,
           "RPG", "Action RPG", "CRPG", "JRPG", "MMORPG", "Party-Based RPG", "Strategy RPG",
           "Tactical RPG",
           words=("rpg", "rpgs", "role playing", "roleplaying", "jrpg", "crpg")),
    _genre("strategy", "Strategy", 2,
           "Strategy", "4X", "Grand Strategy", "RTS", "Action RTS", "Real Time Tactics",
           "Strategy RPG", "Turn-Based Strategy", "Turn-Based Tactics",
           words=("strategy game", "strategy games", "rts", "4x", "grand strategy",
                  "turn based strategy")),
    _genre("simulation", "Simulation", 28,
           "Simulation", "Automobile Sim", "Colony Sim", "Farming Sim", "Life Sim",
           "Space Sim",
           words=("simulation", "sim", "sim game", "sim games")),
    _genre("casual", "Casual", 4, "Casual", words=("casual",)),
    _genre("sports", "Sports", 18, "Sports", words=("sports", "sport")),
    _genre("racing", "Racing", 9, "Racing", "Combat Racing",
           words=("racing", "racer")),
    _genre("indie", "Indie", 23, "Indie", words=("indie",)),
    _genre("massively-multiplayer", "Massively Multiplayer", 29,
           "Massively Multiplayer", "MMORPG", words=_MMO),
    _genre("free-to-play", "Free To Play", 37, "Free to Play",
           words=("free to play", "f2p", "free game")),
    _genre("early-access", "Early Access", EARLY_ACCESS_GENRE_ID, words=("early access",)),
    # Play modes: every game declares them.
    _category("single-player", "Single-player", 2, complete=True,
              words=("single player", "singleplayer", "solo", "offline")),
    _category("multi-player", "Multi-player", 1, complete=True,
              words=("multiplayer", "multi player", "with friends", "online play")),
    _category("co-op", "Co-op", 9, complete=True,
              words=("co-op", "coop", "cooperative", "with a friend", "with friends")),
    _category("online-co-op", "Online Co-op", 38, complete=True,
              words=("online co-op", "online coop", "co-op", "coop", "online multiplayer")),
    _category("lan-co-op", "LAN Co-op", 48, complete=True, words=_LAN),
    _category("split-screen", "Shared/Split Screen", 24, complete=True,
              words=(*_LOCAL_PLAY, "local multiplayer", "same screen")),
    _category("split-screen-co-op", "Shared/Split Screen Co-op", 39, complete=True,
              words=(*_LOCAL_PLAY, "local co-op", "local coop")),
    _category("split-screen-pvp", "Shared/Split Screen PvP", 37, complete=True,
              words=(*_LOCAL_PLAY, "local multiplayer")),
    _category("pvp", "PvP", 49, complete=True,
              words=("pvp", "player versus player", "competitive")),
    _category("online-pvp", "Online PvP", 36, complete=True,
              words=("online pvp", "pvp", "ranked", "matchmaking")),
    _category("lan-pvp", "LAN PvP", 47, complete=True, words=_LAN),
    _category("mmo", "MMO", 20, complete=True, words=_MMO),
    # Platforms.
    _platform("windows", "Runs on Windows", StoreFactSource.WINDOWS, words=("windows",)),
    _platform("mac", "Runs on Mac", StoreFactSource.MAC,
              words=("mac", "macos", "macbook")),
    _platform("linux", "Runs on Linux", StoreFactSource.LINUX,
              words=("linux", "proton", "steam deck")),
    # Features a game declares by choice: only presence is evidence.
    _category("full-controller-support", "Full controller support", 28, complete=False,
              words=_CONTROLLER),
    _category("partial-controller-support", "Partial controller support", 18, complete=False,
              words=_CONTROLLER),
    _category("adjustable-difficulty", "Adjustable difficulty", 78, complete=False,
              words=("difficulty settings", "difficulty setting", "difficulty options",
                     "difficulty levels", "easy mode", "hard mode")),
    _category("save-anytime", "Save anytime", 79, complete=False,
              words=("save anywhere", "save anytime", "quicksave", "quick save", "manual save",
                     "save points", "checkpoints", "autosave")),
    # Read as "no timer" by the understand step's model on its first runs,
    # and then avoided, which turned the player's wish round. The note
    # stopped it and a later, unrelated edit to the prompt brought it back,
    # so the avoided form is also refused in code.
    _category("playable-without-timed-input", "Playable without timed input", 74,
              complete=False, avoidable=False,
              words=("quick time events", "quick time event", "qte", "qtes", "button mashing"),
              note="an accessibility option: no timed button presses are needed; it says"
                   " nothing about time limits or timers in the game"),
    # The store sends this one as a raw key, so the label is written here.
    _category("playable-at-your-own-pace", "Playable at your own pace", 80, complete=False,
              words=("own pace", "no rush", "time pressure", "time limit", "timer")),
    _category("steam-workshop", "Steam Workshop", 30, complete=False,
              words=("workshop", "mods", "mod support", "modding")),
    _category("level-editor", "Includes level editor", 17, complete=False,
              words=("level editor", "map editor", "custom levels", "custom maps")),
    _category("in-app-purchases", "In-app purchases", 35, complete=False,
              words=("microtransactions", "microtransaction", "in app purchases", "pay to win",
                     "p2w", "cash shop", "battle pass")),
    _category("cross-platform-multiplayer", "Cross-platform multiplayer", 27, complete=False,
              words=("crossplay", "cross play", "cross platform")),
    _category("remote-play-together", "Remote Play Together", 44, complete=False,
              words=("remote play",)),
    _category("vr-supported", "VR supported", 53, complete=False,
              words=("vr", "virtual reality")),
    _category("subtitle-options", "Subtitle options", 65, complete=False,
              words=("subtitles", "subtitle", "captions")),
)
"""Every store fact a want may name, in the order the vocabulary is shown."""

_BY_KEY: Final = {fact.key: fact for fact in STORE_FACTS}


def store_fact(key: str) -> StoreFactDef:
    """The store fact named ``key``; ``ValueError`` when the vocabulary has none.

    >>> store_fact("online-co-op").label
    'Online Co-op'
    """
    fact = _BY_KEY.get(key)
    if fact is None:
        raise ValueError(
            f"no store fact is named {key!r} — a target names one of {sorted(_BY_KEY)}"
        )
    return fact


def is_listed(fact: StoreFactDef, metadata: StorefrontMetadata) -> bool:
    """Whether the store lists ``fact`` for the game ``metadata`` describes."""
    match fact.source:
        case StoreFactSource.GENRE:
            return any(genre.id in fact.ids for genre in metadata.genres)
        case StoreFactSource.CATEGORY:
            return any(category.id in fact.ids for category in metadata.categories)
        case StoreFactSource.WINDOWS:
            return metadata.windows
        case StoreFactSource.MAC:
            return metadata.mac
        case StoreFactSource.LINUX:
            return metadata.linux


def store_fact_reading(
    fact: StoreFactDef,
    stance: Stance,
    metadata: StorefrontMetadata | None,
    tags: StorefrontTagCapture | None,
) -> WantReading:
    """One game read on a want about ``fact``.

    A listed fact decides it: a match for a player who wants it, a failure
    for one who avoids it. An unlisted fact decides it the other way only
    when the fact is complete and no player tag speaks for it. Otherwise the
    reading is "cannot tell", with the finding that says why: the fact is
    declared by choice, or players tag what the store does not list, or the
    game's tags or store facts were never captured.

    Raises ``ValueError`` for an avoided want on a fact that is never
    avoided. The understand step's validation removes such a target, so one
    arriving here is a caller's bug.

    >>> from datetime import UTC, date, datetime
    >>> from steamlens.contracts import StorefrontLabel
    >>> hades = StorefrontMetadata(
    ...     app_id=1145360, genres=(StorefrontLabel(1, "Action"), StorefrontLabel(3, "RPG")),
    ...     categories=(StorefrontLabel(2, "Single-player"),),
    ...     windows=True, mac=True, linux=False,
    ...     release_date_text="Sep 17, 2020", release_date=date(2020, 9, 17),
    ...     coming_soon=False, short_description="",
    ...     captured_at=datetime(2026, 11, 14, tzinfo=UTC),
    ... )
    >>> store_fact_reading(store_fact("online-co-op"), Stance.WANTS, hades, None).status
    <WantStatus.FAILS: 'fails'>
    >>> store_fact_reading(store_fact("adjustable-difficulty"), Stance.WANTS, hades, None).finding
    <WantFinding.NOT_DECLARED: 'not-declared'>
    """
    if stance is Stance.AVOIDS and not fact.avoidable:
        raise ValueError(
            f"a want avoids the store fact {fact.key!r} — that fact is never avoided, and the "
            "wish that reads this way is about something else"
        )
    if metadata is None:
        return WantReading(WantStatus.CANNOT_TELL, WantFinding.NO_STORE_FACTS)
    if is_listed(fact, metadata):
        return WantReading(_decided(stance, has_fact=True), WantFinding.LISTED)
    if not fact.complete:
        return WantReading(WantStatus.CANNOT_TELL, WantFinding.NOT_DECLARED)
    if fact.player_tags:
        if tags is None:
            return WantReading(WantStatus.CANNOT_TELL, WantFinding.TAGS_NOT_READ)
        if _tagged(fact.player_tags, tags):
            return WantReading(WantStatus.CANNOT_TELL, WantFinding.TAGGED_NOT_LISTED)
    return WantReading(_decided(stance, has_fact=False), WantFinding.NOT_LISTED)


def release_years_reading(
    target: ReleaseYearsTarget, stance: Stance, metadata: StorefrontMetadata | None
) -> WantReading:
    """One game read on a want about its release year.

    The year is the store's release date, so a game still in early access is
    dated by its early access launch and one that left it by its full
    release. A game with no stored date, or one that is not a full date, is
    "cannot tell". Raises ``ValueError`` on a range with no end or with its
    ends reversed, which names no years.
    """
    if target.first is None and target.last is None:
        raise ValueError("a release-year range needs a first or a last year")
    if target.first is not None and target.last is not None and target.first > target.last:
        raise ValueError(
            f"release-year range runs from {target.first} to {target.last} — "
            "the first year must not be after the last"
        )
    if metadata is None:
        return WantReading(WantStatus.CANNOT_TELL, WantFinding.NO_STORE_FACTS)
    if metadata.release_date is None:
        return WantReading(WantStatus.CANNOT_TELL, WantFinding.NO_RELEASE_DATE)
    year = metadata.release_date.year
    in_range = (target.first is None or year >= target.first) and (
        target.last is None or year <= target.last
    )
    finding = WantFinding.RELEASED_IN_RANGE if in_range else WantFinding.RELEASED_OUTSIDE_RANGE
    return WantReading(_decided(stance, has_fact=in_range), finding)


def _decided(stance: Stance, *, has_fact: bool) -> WantStatus:
    """The status when the store's answer is known: wanted and present, or avoided and absent."""
    return WantStatus.MATCHES if has_fact == (stance is Stance.WANTS) else WantStatus.FAILS


def _tagged(player_tags: Collection[str], tags: StorefrontTagCapture) -> bool:
    return any(tag.name in player_tags for tag in tags.tags)
