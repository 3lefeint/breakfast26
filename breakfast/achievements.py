"""Achievements: definitions and the engine that awards and revokes them.

An achievement is either an *event* (earned once, by one match satisfying a check) or
a *counter* with tiers (a count summed over all of a player's matches, one tier per
threshold reached). The engine never adds to a running total. After a match changes it
re-derives what the stored data says and reconciles the earned rows with that, so an
undo or a correction that reopens a match takes the achievement back on its own.

Rules the engine applies:
- Only matches that started at or after the achievements start (set when the database
  first got the table) count, existing history is not evaluated.
- Only a closed match counts. A reopened match no longer counts.
- Hidden players do not earn achievements, every other player does.
- A Field Training run that is only practice (shorter than the standard length, or ended early)
  counts only for the achievements marked `practice`.
"""

import logging
import random
import re
import threading
import time
from collections import deque
from dataclasses import dataclass
from typing import Callable

from .target_battle_scoring import SCORING

log = logging.getLogger(__name__)

# A dart on the inner bull is "50" in Breakfast's own field names and "BULL" in some
# Autodarts events.
INNER_BULL = frozenset({"50", "BULL"})

X01 = "x01"
ELIMINATION = "elimination"
TARGET_BATTLE = "target_battle"
KILLER = "killer"
FIELD_TRAINING = "field_training"
BLACK_BELT = "black_belt"
ANY = "any"


def game_kind(game_mode: str) -> str:
    """The kind of game a match of this mode in the database is: anything that is not
    Elimination, Target Battle, Killer, Field Training or Black Belt is an X01 variant."""
    return {"Elimination": ELIMINATION, "Target Battle": TARGET_BATTLE, "Killer": KILLER,
            "Field Training": FIELD_TRAINING, "Black Belt": BLACK_BELT}.get(game_mode, X01)


@dataclass(frozen=True)
class Turn:
    number: int
    score: int | None
    is_bust: bool
    darts: tuple               # field names that can be trusted, e.g. ("T20", "S1", "BULL")
    is_checkout: bool = False  # X01: this turn finished the leg
    remaining_before: int | None = None   # X01: what was left before the turn
    leg: int = 1
    target: int | None = None  # Target Battle: the target number of the round; Field Training: the field
    round_no: int | None = None   # Target Battle: the round, or the tiebreak round
    tiebreak: bool = False     # Target Battle: a tiebreak round
    at: str | None = None      # X01: when the turn was stored (UTC, ISO)


class MatchContext:
    """One player's view of one match, loaded lazily for the checks."""

    def __init__(self, db, match: dict, player: str):
        self.db = db
        self.match = match
        self.player = player
        self._turns = None
        self._participants = None
        self._tb_results = None
        self._tb_turns = None
        self._elim_turns = None
        self._elim_results = None
        self._x01_turns = None
        self._killer_events = None
        self._killer_rules = False
        self._killer_results = None
        self._ft_run = None
        self._bb_run = None
        self._bb_darts = None

    @property
    def ft_run(self) -> dict:
        """Field Training: the run, see StatsDB.match_field_training_stats()."""
        if self._ft_run is None:
            self._ft_run = self.db.match_field_training_stats(self.match["match_id"])
        return self._ft_run

    @property
    def bb_run(self) -> dict:
        """Black Belt: the run, see StatsDB.match_black_belt_stats()."""
        if self._bb_run is None:
            self._bb_run = self.db.match_black_belt_stats(self.match["match_id"])
        return self._bb_run

    @property
    def bb_darts(self) -> list:
        """Black Belt: every dart of the run in the order thrown, see StatsDB.black_belt_dart_rows()."""
        if self._bb_darts is None:
            self._bb_darts = self.db.black_belt_dart_rows(self.match["match_id"])
        return self._bb_darts

    @property
    def turns(self) -> list:
        if self._turns is None:
            rows = self.db.turns_for_achievements(self.match["match_id"], self.player,
                                                  self.match["game_mode"])
            self._turns = [Turn(**r) for r in rows]
        return self._turns

    @property
    def participants(self) -> list:
        if self._participants is None:
            self._participants = self.db.match_participants(self.match["match_id"])
        return self._participants

    @property
    def tb_results(self) -> list:
        """Target Battle: everybody's placement and total."""
        if self._tb_results is None:
            self._tb_results = self.db.target_battle_results(self.match["match_id"])
        return self._tb_results

    @property
    def tb_turns(self) -> list:
        """Target Battle: every turn of every player."""
        if self._tb_turns is None:
            self._tb_turns = self.db.target_battle_turn_rows(self.match["match_id"])
        return self._tb_turns

    @property
    def killer_events(self) -> list:
        """Killer: every event of the game, see StatsDB.killer_event_rows()."""
        if self._killer_events is None:
            self._killer_events = self.db.killer_event_rows(self.match["match_id"])
        return self._killer_events

    @property
    def killer_rules(self) -> dict | None:
        """Killer: whether own goals and singles were on."""
        if self._killer_rules is False:
            self._killer_rules = self.db.killer_rules(self.match["match_id"])
        return self._killer_rules

    @property
    def killer_lives_left(self) -> int | None:
        """Killer: the lives the winner had left."""
        if self._killer_results is None:
            self._killer_results = self.db.killer_results(self.match["match_id"])
        return next((r["lives_left"] for r in self._killer_results if r["placement"] == 1), None)

    @property
    def x01_turns(self) -> list:
        """X01: every turn of every player, in the order played."""
        if self._x01_turns is None:
            self._x01_turns = self.db.x01_turn_rows(self.match["match_id"])
        return self._x01_turns

    @property
    def elim_turns(self) -> list:
        """Elimination: every turn of every player, in the order played."""
        if self._elim_turns is None:
            self._elim_turns = self.db.elimination_turn_rows(self.match["match_id"])
        return self._elim_turns

    @property
    def own_elim_turns(self) -> list:
        """Elimination: the player's own turns."""
        return [t for t in self.elim_turns if t["player"] == self.player]

    @property
    def elim_lives_left(self) -> int | None:
        """Elimination: the lives the winner had left."""
        if self._elim_results is None:
            self._elim_results = self.db.elimination_results(self.match["match_id"])
        return next((r["lives_left"] for r in self._elim_results if r["placement"] == 1), None)

    @property
    def won(self) -> bool:
        return self.match["winner"] == self.player


@dataclass(frozen=True)
class Achievement:
    id: str
    mode: str                  # general, x01, elimination, killer, target_battle, easter_egg
    difficulty: str            # easy ... extreme, endurance, hidden
    names: dict                # {"en": ..., "de": ...}
    descriptions: dict         # how to earn it, same languages
    game_modes: str = ANY      # which matches can decide it: x01, elimination, target_battle, killer or any
    hidden: bool = False       # shown as a silhouette until earned
    label: str | None = None   # short text drawn on the badge
    tiers: tuple | None = None  # counter thresholds, None for an event
    check: Callable | None = None   # event: does this match satisfy it
    count: Callable | None = None   # counter: what this match adds to the total
    peak: bool = False         # counter: the total is the highest value of any match, not the sum
    motif: str | None = None   # id of the badge motif to share, default: its own
    practice: bool = False     # also decided by a Field Training run that is only practice

    def applies_to(self, game_mode: str) -> bool:
        if self.game_modes == ANY:
            return True
        return game_kind(game_mode) == self.game_modes

    def counts_match(self, match: dict) -> bool:
        """Whether the match can decide this achievement: a Field Training run that is only
        practice does so for the achievements marked `practice` alone."""
        return match.get("ft_counts") != 0 or self.practice


# ── Checks ───────────────────────────────────────────────────────────────────

_FIELD = re.compile(r"^([SDT])(\d{1,2})$")


def _is_double(field):
    match = _FIELD.match(field)
    return field in INNER_BULL or bool(match and match.group(1) == "D")


def _is_maximum(turn):
    return not turn.is_bust and turn.darts == ("T20", "T20", "T20")


def _checkouts(ctx):
    return [turn for turn in ctx.turns if turn.is_checkout and not turn.is_bust]


def _bullseye(ctx):
    return any(dart in INNER_BULL for turn in ctx.turns for dart in turn.darts)


def _ton_up(ctx):
    return sum(1 for turn in ctx.turns if not turn.is_bust and (turn.score or 0) >= 100)


def _beast_mode(ctx):
    return any(turn.darts == ("S6", "S6", "S6") for turn in ctx.turns)


def _first_bite(ctx):
    return ctx.won and len(ctx.participants) >= 2


def _last_at_the_table(ctx):
    return ctx.won


_MISS = re.compile(r"^(MISS|M\d{1,2})$")


def _is_miss(field):
    """A dart outside every scoring field: a miss next to a number, or without any number."""
    return bool(_MISS.match(field))


def _field_points(field):
    if field in INNER_BULL:
        return 50
    if field == "25":
        return 25
    match = _FIELD.match(field)
    return int(match.group(2)) * {"S": 1, "D": 2, "T": 3}[match.group(1)] if match else 0


def _one_dart_finish(remaining):
    """Can this rest be finished with one dart: a double, or the inner bull."""
    return remaining == 50 or (remaining is not None and 2 <= remaining <= 40 and remaining % 2 == 0)


def _remaining_before_each_dart(turn):
    """What was left before each dart of an X01 turn, up to the dart that busts."""
    before = turn.remaining_before
    for field in turn.darts:
        if before is None or before < 2:
            return
        yield field, before
        before -= _field_points(field)


def _history_through(ctx):
    """The player's closed matches since the achievements start, up to and including this one."""
    matches = [m for m in ctx.db.player_final_matches(ctx.player, ctx.db.achievements_start())
               if m.get("ft_counts") != 0]
    ids = [m["match_id"] for m in matches]
    if ctx.match["match_id"] not in ids:
        return []
    return matches[:ids.index(ctx.match["match_id"]) + 1]


def _won_in_a_row(ctx, kind, minimum_players, length):
    """This match is the last of `length` wins in a row among the player's closed matches of this
    kind that had `minimum_players` or more players (a smaller one neither counts nor breaks the run)."""
    played = [m for m in ctx.db.player_final_matches(ctx.player, ctx.db.achievements_start())
              if game_kind(m["game_mode"]) == kind
              and len(ctx.db.match_participants(m["match_id"])) >= minimum_players]
    ids = [m["match_id"] for m in played]
    if ctx.match["match_id"] not in ids:
        return False
    at = ids.index(ctx.match["match_id"])
    return at >= length - 1 and all(m["winner"] == ctx.player for m in played[at - length + 1:at + 1])


def _distinct_days(ctx):
    return len({ctx.db.local_time(m["ended_at"]).date() for m in _history_through(ctx)})


def _heavy_hitter(ctx):
    return sum(1 for turn in ctx.turns if not turn.is_bust and (turn.score or 0) >= 140)


def _best_average(ctx):
    """The 3-dart average of this match, rounded down, 0 under five turns."""
    turns = ctx.turns
    darts = sum(len(t.darts) for t in turns)
    if len(turns) < 5 or not darts:
        return 0
    return int(3 * sum(t.score or 0 for t in turns if not t.is_bust) / darts)


def _short_order(ctx):
    """A 501 leg finished in at most 18 darts."""
    if ctx.match.get("points_start") != 501:
        return False
    legs = {}
    for turn in ctx.turns:
        legs.setdefault(turn.leg, []).append(turn)
    return any(turns[0].remaining_before == 501 and turns[-1].is_checkout and not turns[-1].is_bust
               and sum(len(t.darts) for t in turns) <= 18 for turns in legs.values())


def _bullseye_finish(ctx):
    return any(turn.darts and turn.darts[-1] in INNER_BULL for turn in _checkouts(ctx))


def _streak_master(ctx):
    return ctx.won and len(ctx.participants) >= 2 and _won_in_a_row(ctx, X01, 2, 3)


def _closing_routine(ctx):
    return len(_checkouts(ctx))


_CHECKOUT_TARGETS = {f"D{n}" for n in range(1, 21)} | {"BULL"}


def _checkout_collection(ctx):
    """How many of the 21 finishing fields (D1 to D20, inner bull) the player has finished a leg on
    in the closed X01 matches up to this one."""
    found = set()
    for m in _history_through(ctx):
        if game_kind(m["game_mode"]) != X01:
            continue
        mine = ctx if m["match_id"] == ctx.match["match_id"] else MatchContext(ctx.db, m, ctx.player)
        for turn in _checkouts(mine):
            if turn.darts:
                found.add("BULL" if turn.darts[-1] in INNER_BULL else turn.darts[-1])
    return len(found & _CHECKOUT_TARGETS)


def _rest_after_turn_is(*rests):
    def check(ctx):
        return any(not t.is_bust and t.remaining_before - (t.score or 0) in rests for t in ctx.turns)
    return check


def _small_fry(ctx):
    return any(turn.darts == ("S1", "S1", "S1") for turn in ctx.turns)


def _fasting(ctx):
    return any(len(turn.darts) == 3 and all(_is_miss(d) for d in turn.darts) for turn in ctx.turns)


def _deja_vu(ctx):
    turns = ctx.turns
    return any(len(a.darts) == 3 and a.darts == b.darts and not any(_is_miss(d) for d in a.darts)
               for a, b in zip(turns, turns[1:]))


def _case_of_the_jitters(ctx):
    """At least nine darts in one leg thrown at a rest that one dart could finish, none of them finishing."""
    per_leg = {}
    for turn in ctx.turns:
        finishing = turn.is_checkout and not turn.is_bust
        for i, (field, before) in enumerate(_remaining_before_each_dart(turn)):
            if _one_dart_finish(before) and not (finishing and i == len(turn.darts) - 1):
                per_leg[turn.leg] = per_leg.get(turn.leg, 0) + 1
    return any(n >= 9 for n in per_leg.values())


def _spoilsport(ctx):
    """The player finishes a leg while an opponent has a rest that one dart could finish."""
    left = {}        # (leg, player) -> what the player had left after the latest turn of the leg
    for row in ctx.x01_turns:
        if row["player"] == ctx.player and row["is_checkout"] and not row["is_bust"]:
            if any(_one_dart_finish(rest) for (leg, who), rest in left.items()
                   if leg == row["leg"] and who != ctx.player):
                return True
        left[(row["leg"], row["player"])] = (row["remaining_before"] if row["is_bust"]
                                             else row["remaining_before"] - row["score"])
    return False


def _lonely_one(ctx):
    """A bust that left exactly one."""
    for turn in ctx.turns:
        if not turn.is_bust or turn.remaining_before is None:
            continue
        rest = turn.remaining_before
        for field in turn.darts:
            rest -= _field_points(field)
            if rest == 1:
                return True
            if rest < 1:
                break
    return False


def _finished_at(ctx, start_hour, end_hour):
    return any(turn.at and start_hour <= ctx.db.local_time(turn.at).hour < end_hour
               for turn in _checkouts(ctx))


def _early_bird(ctx):
    return _finished_at(ctx, 0, 7)


def _night_owl(ctx):
    return _finished_at(ctx, 0, 4)


def _answer_to_everything(ctx):
    return any(turn.remaining_before == 42 and turn.darts == ("S10", "D16") for turn in _checkouts(ctx))


def _burnt_toast(ctx):
    return any(field == "T20" and before == 2
               for turn in ctx.turns for field, before in _remaining_before_each_dart(turn))


def _breakfast_switch(ctx):
    return any(turn.remaining_before == 110 and turn.darts == ("T20", "S10", "D20") for turn in _checkouts(ctx))


def _not_found(ctx):
    return any(len(t.darts) == 3 and t.darts[0] == "S4" and _is_miss(t.darts[1]) and t.darts[2] == "S4"
               for t in ctx.turns)


def _service_unavailable(ctx):
    return any(len(t.darts) == 3 and t.darts[0] == "S5" and _is_miss(t.darts[1]) and t.darts[2] == "S3"
               for t in ctx.turns)


def _full_english(ctx):
    return any(sorted(t.darts) == ["D20", "S20", "T20"] for t in ctx.turns)


# Elimination. A turn "beats the bar" when it passes without a freipass; `to_beat` is what it had
# to beat, and a freipass turn has nothing to beat.

def _beats_the_bar(turn):
    return turn["passed"] and not turn["freipass"]


def _raising_the_bar(ctx):
    return any(_beats_the_bar(t) for t in ctx.own_elim_turns)


def _one_is_enough(ctx):
    return any(_beats_the_bar(t) and t["score"] == t["to_beat"] + 1 for t in ctx.own_elim_turns)


def _second_chance(ctx):
    turns = ctx.own_elim_turns
    return any(not before["passed"] and _beats_the_bar(after) for before, after in zip(turns, turns[1:]))


def _last_life_standing(ctx):
    return ctx.won and (ctx.match["points_start"] or 0) >= 2 and ctx.elim_lives_left == 1


def _untouchable(ctx):
    regular = sum(1 for t in ctx.own_elim_turns if not t["freipass"])
    return (ctx.won and len(ctx.participants) >= 3 and ctx.elim_lives_left == ctx.match["points_start"]
            and regular >= 3)


def _full_house(ctx):
    return ctx.won and len(ctx.participants) >= 6


def _hat_trick(ctx):
    return ctx.won and len(ctx.participants) >= 3 and _won_in_a_row(ctx, ELIMINATION, 3, 3)


def _no_free_ride(ctx):
    run = 0
    for turn in ctx.own_elim_turns:
        run = run + 1 if _beats_the_bar(turn) else 0
        if run >= 5:
            return True
    return False


def _maximum_beaten(ctx):
    return any(_beats_the_bar(t) and t["to_beat"] == 179 and t["score"] == 180 for t in ctx.own_elim_turns)


def _back_from_the_brink(ctx):
    """Won after falling to one life, with at least three regular turns passed since then."""
    if not (ctx.won and (ctx.match["points_start"] or 0) >= 3 and len(ctx.participants) >= 3):
        return False
    turns = ctx.own_elim_turns
    low = next((i for i, t in enumerate(turns) if t["lives_before"] == 1), None)
    return low is not None and sum(1 for t in turns[low:] if _beats_the_bar(t)) >= 3


def _copying_costs(ctx):
    return any(not t["freipass"] and not t["passed"] and t["score"] == t["to_beat"] for t in ctx.own_elim_turns)


def _a_new_low(ctx):
    """A turn below a positive bar without a free pass, and the next player below that new bar too."""
    rows = ctx.elim_turns
    for a, b in zip(rows, rows[1:]):
        if ctx.player in (a["player"], b["player"]) and a["player"] != b["player"] \
                and not a["freipass"] and not a["passed"] and a["to_beat"] > 0 and a["score"] < a["to_beat"] \
                and not b["freipass"] and not b["passed"] and b["score"] < a["score"]:
            return True
    return False


def _free_pass_failed(ctx):
    return any(t["freipass"] and t["score"] == 0 for t in ctx.own_elim_turns)


def _one_crumb_is_enough(ctx):
    return any(t["freipass"] and t["score"] == 1 for t in ctx.own_elim_turns)


def _tied_to_the_grave(ctx):
    return any(not t["freipass"] and not t["passed"] and t["score"] == t["to_beat"] and t["lives_before"] == 1
               for t in ctx.own_elim_turns)


def _after_me_the_deluge(ctx):
    rows = ctx.elim_turns
    return any(a["player"] == ctx.player and a["score"] == 180 and not b["freipass"] and not b["passed"]
               for a, b in zip(rows, rows[1:]))


def _chips_for_breakfast(ctx):
    darts = {t.number: t.darts for t in ctx.turns}
    return any(_beats_the_bar(t) and sorted(darts.get(number, ())) == ["S1", "S20", "S5"]
               for number, t in enumerate(ctx.own_elim_turns, start=1))


def _close_still_costs(ctx):
    return any(not t["freipass"] and not t["passed"] and t["to_beat"] > 0 and t["score"] == t["to_beat"] - 1
               for t in ctx.own_elim_turns)


# Killer. An event of the game has the player who did it, its kind (killer, hit, own_goal, out), the
# victim, the turn it happened in (`turn_id`) and the dart of that turn (0: thrown before the game).

def _own_killer(ctx, kind):
    return [e for e in ctx.killer_events if e["player"] == ctx.player and e["kind"] == kind]


def _killer_by_turn(ctx, kind):
    """The player's events of one kind, grouped by the turn they happened in."""
    turns = {}
    for e in _own_killer(ctx, kind):
        turns.setdefault(e["turn_id"], []).append(e)
    return list(turns.values())


def _knockouts(ctx):
    return [e for e in _own_killer(ctx, "out") if e["victim"] != ctx.player]


def _licence_to_breakfast(ctx):
    return bool(_own_killer(ctx, "killer"))


def _armed_immediately(ctx):
    """Became a killer with the first dart of the game: the first dart of the first own turn."""
    turn = next((e["turn_id"] for e in ctx.killer_events if e["player"] == ctx.player and e["dart_no"] > 0), None)
    return any(e["dart_no"] == 1 and e["turn_id"] == turn for e in _own_killer(ctx, "killer"))


def _first_blood(ctx):
    return bool(_own_killer(ctx, "hit"))


def _three_in_one(ctx):
    return any(len(hits) >= 3 for hits in _killer_by_turn(ctx, "hit"))


def _all_round_attack(ctx):
    return len(ctx.participants) >= 4 and any(len({h["victim"] for h in hits}) >= 3
                                              for hits in _killer_by_turn(ctx, "hit"))


def _finisher(ctx):
    return bool(_knockouts(ctx))


def _double_knockout(ctx):
    turns = {}
    for e in _knockouts(ctx):
        turns.setdefault(e["turn_id"], set()).add(e["victim"])
    return any(len(victims) >= 2 for victims in turns.values())


def _unscathed(ctx):
    return ctx.won and len(ctx.participants) >= 3 and ctx.killer_lives_left == ctx.match["points_start"]


def _last_breath(ctx):
    return ctx.won and ctx.killer_lives_left == 1


def _double_agent(ctx):
    rules = ctx.killer_rules
    return bool(rules) and not rules["singles"] and ctx.won and len(ctx.participants) >= 3 \
        and len(_own_killer(ctx, "hit")) >= 3


def _self_service(ctx):
    return any(e["victim"] == ctx.player for e in _own_killer(ctx, "out"))


def _glass_cannon(ctx):
    """A turn with two hits on others and then an own goal that puts the player out."""
    for turn in {e["turn_id"] for e in ctx.killer_events if e["player"] == ctx.player}:
        mine = [e for e in ctx.killer_events if e["player"] == ctx.player and e["turn_id"] == turn]
        hits = sorted(e["dart_no"] for e in mine if e["kind"] == "hit")
        out = any(e["kind"] == "out" and e["victim"] == ctx.player for e in mine)
        if len(hits) >= 2 and out and any(e["kind"] == "own_goal" and e["dart_no"] > hits[1] for e in mine):
            return True
    return False


def _friendly_to_the_end(ctx):
    return len(ctx.participants) >= 3 and not ctx.won and not _own_killer(ctx, "hit")


def _own_worst_enemy(ctx):
    """All lives lost to own goals and none to an opponent."""
    lost_to_others = any(e["kind"] == "hit" and e["victim"] == ctx.player for e in ctx.killer_events)
    return (not lost_to_others and len(_own_killer(ctx, "own_goal")) >= 3
            and any(e["victim"] == ctx.player for e in _own_killer(ctx, "out")))


def _four_course_meal(ctx):
    """One closed game of each kind: X01, Elimination, Killer and Target Battle."""
    kinds = {game_kind(m["game_mode"]) for m in _history_through(ctx)}
    return {X01, ELIMINATION, KILLER, TARGET_BATTLE} <= kinds


# Field Training. A run counts when every dart was thrown and there were at least the standard
# number of darts (100 at a number, 50 at the bull); the database only marks those with `ft_counts`.

def _bull_drill(ctx):
    """The points of a full run at the bull, on the scale of 50 darts."""
    if ctx.match.get("ft_field") != 25:
        return 0
    return int(ctx.ft_run.get("scaled_points") or 0)


def _hundred_darts(ctx):
    return 1 if ctx.match.get("ft_field") not in (None, 25) else 0


def _triple_threat(ctx):
    """Three triples of the field in one turn, also in a run that is only practice."""
    field = ctx.match.get("ft_field")
    if field in (None, 25):
        return False
    return any(len(t.darts) == 3 and all(d == f"T{field}" for d in t.darts) for t in ctx.turns)


def _grand_tour(ctx):
    """A full run at every number from 1 to 20 and at the bull, in the matches up to this one."""
    fields = {m["ft_field"] for m in _history_through(ctx) if game_kind(m["game_mode"]) == FIELD_TRAINING}
    return fields >= {*range(1, 21), 25}


# Black Belt. Every finished run counts, with or without the belt.

def _black_belt(ctx):
    return bool(ctx.bb_run.get("belt"))


def _belt_progress(ctx):
    """How many fields the run got through in one go."""
    return ctx.bb_run.get("furthest") or 0


def _dead_eye(ctx):
    """Five fields in a row, each hit with the first dart thrown at it. The first dart at a field is
    the one after a hit, after a restart, or the first of the run."""
    best = streak = 0
    first = True
    for dart in ctx.bb_darts:
        if first:
            streak = streak + 1 if dart["hit"] else 0
            best = max(best, streak)
        first = dart["hit"] or dart["restart"]
    return best >= 5


def _first_breakfast(ctx):
    return True


def _shanghai(ctx):
    for turn in ctx.turns:
        parts = [_FIELD.match(dart) for dart in turn.darts]
        if len(parts) == 3 and all(parts) and len({p.group(2) for p in parts}) == 1 \
                and {p.group(1) for p in parts} == {"S", "D", "T"}:
            return True
    return False


def _double_pack(ctx):
    return any(len(turn.darts) == 3 and all(_is_double(d) for d in turn.darts) for turn in ctx.turns)


def _maximum(ctx):
    return any(_is_maximum(turn) for turn in ctx.turns)


def _maximum_count(ctx):
    return sum(1 for turn in ctx.turns if _is_maximum(turn))


def _triple_bull(ctx):
    return any(len(turn.darts) == 3 and all(d in INNER_BULL for d in turn.darts) for turn in ctx.turns)


def _matches_played(ctx):
    return 1


def _job_done(ctx):
    return bool(_checkouts(ctx))


def _last_dart_finish(ctx):
    return any(len(turn.darts) == 3 for turn in _checkouts(ctx))


def _double_trouble(ctx):
    return any(turn.darts and turn.darts[-1] == "D1" for turn in _checkouts(ctx))


def _high_finish(ctx):
    return any((turn.remaining_before or 0) >= 100 for turn in _checkouts(ctx))


def _straight_to_the_double(ctx):
    return any(len(turn.darts) == 1 for turn in _checkouts(ctx))


def _big_fish(ctx):
    return any(turn.remaining_before == 170 and len(turn.darts) == 3
               and turn.darts[:2] == ("T20", "T20") and turn.darts[2] in INNER_BULL
               for turn in _checkouts(ctx))


def _perfect_leg(ctx):
    """A 501 leg the player finished in exactly nine darts."""
    if ctx.match.get("points_start") != 501:
        return False
    legs = {}
    for turn in ctx.turns:
        legs.setdefault(turn.leg, []).append(turn)
    return any(turns[-1].is_checkout and not turns[-1].is_bust
               and sum(len(t.darts) for t in turns) == 9 for turns in legs.values())


# Target Battle. The "standard game" of the descriptions is the standard scoring profile with ten
# rounds, the training games are the profiles with only doubles or only triples, also with ten.

def _dart_number(field):
    match = _FIELD.match(field)
    return int(match.group(2)) if match else None


def _standard_game(ctx):
    return ctx.match.get("scoring") == "standard" and ctx.match.get("points_start") == 10


def _tb_total(ctx):
    return sum(turn.score or 0 for turn in ctx.turns if not turn.tiebreak)


def _tb_dart_points(ctx, field, target):
    """What a dart is worth in this game: only a dart on the target scores."""
    match = _FIELD.match(field)
    if not match or int(match.group(2)) != target:
        return 0
    return SCORING[ctx.match.get("scoring", "standard")].get({"S": 1, "D": 2, "T": 3}[match.group(1)], 0)


def _target_acquired(ctx):
    return any(len(t.darts) == 3 and all(_dart_number(d) == t.target for d in t.darts) for t in ctx.turns)


def _nine_out_of_nine(ctx):
    return ctx.match.get("scoring") == "standard" and any(
        len(t.darts) == 3 and t.darts == (f"T{t.target}",) * 3 for t in ctx.turns)


def _no_empty_rounds(ctx):
    rounds = [t for t in ctx.turns if not t.tiebreak]
    return _standard_game(ctx) and len(rounds) == 10 and all((t.score or 0) >= 1 for t in rounds)


def _points_at_least(minimum):
    return lambda ctx: _standard_game(ctx) and _tb_total(ctx) >= minimum


def _training_focus(profile):
    return lambda ctx: (ctx.match.get("scoring") == profile and ctx.match.get("points_start") == 10
                        and _tb_total(ctx) >= 15)


def _decided_without_tiebreak(ctx):
    return ctx.won and len(ctx.participants) >= 2 and not any(t["tiebreak"] for t in ctx.tb_turns)


def _photo_finish(ctx):
    if not (_standard_game(ctx) and _decided_without_tiebreak(ctx)):
        return False
    others = [r["score"] for r in ctx.tb_results if r["player"] != ctx.player]
    mine = next((r["score"] for r in ctx.tb_results if r["player"] == ctx.player), None)
    return mine is not None and bool(others) and mine - max(others) == 1


def _final_round_comeback(ctx):
    if not (_standard_game(ctx) and _decided_without_tiebreak(ctx)):
        return False
    before_last = {}
    for t in ctx.tb_turns:
        if not t["tiebreak"] and t["round_no"] <= 9:
            before_last[t["player"]] = before_last.get(t["player"], 0) + t["score"]
    best = max(before_last.values(), default=None)
    leaders = [p for p, total in before_last.items() if total == best]
    return len(leaders) == 1 and leaders[0] != ctx.player


def _either_side_of_twenty(ctx):
    for t in ctx.turns:
        numbers = {_dart_number(d) for d in t.darts}
        if t.target == 20 and len(t.darts) == 3 and numbers == {1, 5}:
            return True
    return False


def _wrong_maximum(ctx):
    return ctx.match.get("scoring") == "standard" and any(
        t.target != 20 and t.darts == ("T20",) * 3 for t in ctx.turns)


def _better_late_than_never(ctx):
    return any(
        len(t.darts) == 3 and _tb_dart_points(ctx, t.darts[0], t.target) == 0
        and _tb_dart_points(ctx, t.darts[1], t.target) == 0 and t.darts[2] == f"T{t.target}"
        for t in ctx.turns)


def _exactly_sixty(ctx):
    return _standard_game(ctx) and _tb_total(ctx) == 60


def _extended_breakfast(ctx):
    tiebreak_rounds = {t["round_no"] for t in ctx.tb_turns if t["tiebreak"]}
    return ctx.won and len(ctx.participants) >= 2 and len(tiebreak_rounds) >= 3


ACHIEVEMENTS = (
    Achievement("first_breakfast", "general", "easy",
                {"en": "First Breakfast", "de": "Erstes Frühstück"},
                {"en": "Finish your first match.", "de": "Das erste Spiel abschliessen."},
                check=_first_breakfast),
    Achievement("bullseye", "general", "easy", {"en": "Bullseye", "de": "Bullseye"},
                {"en": "Hit the inner bull.", "de": "Das innere Bull treffen."},
                check=_bullseye),
    Achievement("shanghai", "general", "medium", {"en": "Shanghai", "de": "Shanghai"},
                {"en": "Hit a single, a double and a triple of the same number in one turn, in any order.",
                 "de": "Single, Double und Triple derselben Zahl in einer Aufnahme treffen, Reihenfolge beliebig."},
                label="SDT", check=_shanghai),
    Achievement("double_pack", "general", "hard", {"en": "Triple Double", "de": "Doppelpack"},
                {"en": "Hit a double with all three darts of a turn, the bull counts.",
                 "de": "Mit allen drei Darts einer Aufnahme ein Double treffen, das Bull zählt."},
                check=_double_pack),
    Achievement("maximum", "general", "hard", {"en": "180!", "de": "180!"},
                {"en": "Hit three treble 20s in one turn.", "de": "Drei T20 in einer Aufnahme treffen."},
                label="180", check=_maximum),
    Achievement("triple_bull", "general", "very_hard", {"en": "Triple Bull", "de": "Bull-Trio"},
                {"en": "Hit the inner bull with all three darts of a turn.",
                 "de": "Mit allen drei Darts einer Aufnahme das innere Bull treffen."},
                check=_triple_bull),
    Achievement("maximum_collector", "general", "endurance",
                {"en": "Maximum Collector", "de": "Maximum-Sammler"},
                {"en": "Score 180 again and again: 10, 100 and 1,000 times.",
                 "de": "Immer wieder 180 erzielen: zehnmal, hundertmal und tausendmal."},
                label="180", tiers=(10, 100, 1000), count=_maximum_count, motif="maximum"),
    Achievement("a_hundred_served", "general", "endurance",
                {"en": "A Hundred Served", "de": "Hundert auf dem Teller"},
                {"en": "Finish 100 matches.", "de": "100 Spiele abschliessen."},
                label="100", tiers=(100,), count=_matches_played),
    Achievement("ton_up", "x01", "endurance", {"en": "Ton Up", "de": "Volle Hundert"},
                {"en": "Score 100 or more in a turn of an X01 match.",
                 "de": "In einer Aufnahme eines X01-Spiels mindestens 100 Punkte erzielen."},
                game_modes=X01, label="100", tiers=(1, 10, 100, 1000), count=_ton_up),
    Achievement("first_bite", "x01", "easy", {"en": "First Bite", "de": "Erster Bissen"},
                {"en": "Win your first X01 match against at least one opponent.",
                 "de": "Das erste X01-Spiel gegen mindestens einen Gegner gewinnen."},
                game_modes=X01, check=_first_bite),
    Achievement("job_done", "x01", "easy", {"en": "Job Done", "de": "Feierabend"},
                {"en": "Finish a leg with a checkout.", "de": "Ein Leg mit einem Checkout beenden."},
                game_modes=X01, check=_job_done),
    Achievement("last_dart_finish", "x01", "easy",
                {"en": "Last-Dart Finish", "de": "Auf den letzten Drücker"},
                {"en": "Check out with the third dart of a turn.",
                 "de": "Mit dem dritten Dart einer Aufnahme auschecken."},
                game_modes=X01, check=_last_dart_finish),
    Achievement("double_trouble", "x01", "easy", {"en": "Double Trouble", "de": "Double Trouble"},
                {"en": "Finish a leg on D1.", "de": "Ein Leg auf D1 beenden."},
                game_modes=X01, label="D1", check=_double_trouble),
    Achievement("high_finish", "x01", "medium", {"en": "High Finish", "de": "High Finish"},
                {"en": "Check out from 100 or more in one turn.",
                 "de": "Aus mindestens 100 Rest in einer Aufnahme auschecken."},
                game_modes=X01, label="100+", check=_high_finish),
    Achievement("straight_to_the_double", "x01", "easy",
                {"en": "Straight to the Double", "de": "Ohne Umweg"},
                {"en": "Check out with the first dart of a turn.",
                 "de": "Mit dem ersten Dart einer Aufnahme auschecken."},
                game_modes=X01, check=_straight_to_the_double),
    Achievement("big_fish", "x01", "very_hard", {"en": "Big Fish", "de": "Big Fish"},
                {"en": "Check out 170 with T20, T20 and the inner bull.",
                 "de": "170 Rest mit T20, T20 und dem inneren Bull auschecken."},
                game_modes=X01, label="170", check=_big_fish),
    Achievement("perfect_leg", "x01", "extreme", {"en": "Perfect Leg", "de": "Perfektes Leg"},
                {"en": "Win a 501 leg in exactly nine darts.",
                 "de": "Ein 501-Leg in genau neun Darts beenden."},
                game_modes=X01, label="501", check=_perfect_leg),
    Achievement("last_at_the_table", "elimination", "easy",
                {"en": "Last at the Table", "de": "Letzter am Tisch"},
                {"en": "Win an Elimination match.", "de": "Ein Elimination-Spiel gewinnen."},
                game_modes=ELIMINATION, check=_last_at_the_table),
    Achievement("raising_the_bar", "elimination", "easy",
                {"en": "Raising the Bar", "de": "Latte höher"},
                {"en": "Beat the previous score without a free pass for the first time.",
                 "de": "Ohne Freipass erstmals die Punktzahl des Vorgängers überbieten."},
                game_modes=ELIMINATION, check=_raising_the_bar),
    Achievement("one_is_enough", "elimination", "easy",
                {"en": "One Is Enough", "de": "Ein Punkt reicht"},
                {"en": "Beat the previous score by exactly one point, without a free pass.",
                 "de": "Ohne Freipass die Punktzahl des Vorgängers um genau einen Punkt überbieten."},
                game_modes=ELIMINATION, label="+1", check=_one_is_enough),
    Achievement("second_chance", "elimination", "easy",
                {"en": "Second Chance", "de": "Zweite Chance"},
                {"en": "Lose a life and beat the score to beat in your very next turn, without a free pass.",
                 "de": "Nach einem Lebensverlust in der nächsten eigenen Aufnahme ohne Freipass die Vorgabe überbieten."},
                game_modes=ELIMINATION, check=_second_chance),
    Achievement("last_life_standing", "elimination", "medium",
                {"en": "Last Life Standing", "de": "Letztes Leben"},
                {"en": "Win a match that started with at least two lives with exactly one life left.",
                 "de": "Ein Spiel mit mindestens zwei Startleben mit genau einem verbleibenden Leben gewinnen."},
                game_modes=ELIMINATION, check=_last_life_standing),
    Achievement("untouchable", "elimination", "hard",
                {"en": "Untouchable", "de": "Unantastbar"},
                {"en": "Win a match of at least three players without losing a life, after at least three turns without a free pass.",
                 "de": "Ein Spiel mit mindestens drei Teilnehmern ohne Lebensverlust gewinnen, nach mindestens drei eigenen Aufnahmen ohne Freipass."},
                game_modes=ELIMINATION, check=_untouchable),
    Achievement("full_house", "elimination", "hard",
                {"en": "Full House", "de": "Volles Haus"},
                {"en": "Win a match with at least six players.",
                 "de": "Ein Spiel mit mindestens sechs Teilnehmern gewinnen."},
                game_modes=ELIMINATION, label="6", check=_full_house),
    Achievement("hat_trick", "elimination", "hard",
                {"en": "Hat-Trick", "de": "Hattrick"},
                {"en": "Win three of your Elimination matches in a row, each with at least three players.",
                 "de": "Drei eigene Elimination-Spiele in Folge gewinnen, jeweils mit mindestens drei Teilnehmern."},
                game_modes=ELIMINATION, label="3", check=_hat_trick),
    Achievement("no_free_ride", "elimination", "hard",
                {"en": "No Free Ride", "de": "Aus eigener Kraft"},
                {"en": "Beat the score to beat in five turns in a row, none of them with a free pass.",
                 "de": "Fünf eigene Aufnahmen hintereinander ohne Freipass spielen und jedes Mal die Vorgabe überbieten."},
                game_modes=ELIMINATION, label="5", check=_no_free_ride),
    Achievement("maximum_beaten", "elimination", "very_hard",
                {"en": "Maximum Beaten", "de": "Maximum geknackt"},
                {"en": "Beat a score of 179 with 180.", "de": "Eine Vorgabe von 179 mit 180 überbieten."},
                game_modes=ELIMINATION, label="180", check=_maximum_beaten),
    Achievement("back_from_the_brink", "elimination", "hard",
                {"en": "Back from the Brink", "de": "Dem Tod von der Schippe"},
                {"en": "With at least three lives and three players, fall to one life, pass at least three turns without a free pass from there and win.",
                 "de": "Bei mindestens drei Startleben und drei Teilnehmern auf ein Leben fallen, danach mindestens drei eigene Aufnahmen ohne Freipass überstehen und gewinnen."},
                game_modes=ELIMINATION, check=_back_from_the_brink),
    Achievement("target_acquired", "target_battle", "easy",
                {"en": "Target Acquired", "de": "Ziel erfasst"},
                {"en": "Hit the target number with all three darts of a turn.",
                 "de": "Mit allen drei Darts einer Aufnahme die Zielzahl treffen."},
                game_modes=TARGET_BATTLE, check=_target_acquired),
    Achievement("nine_out_of_nine", "target_battle", "hard",
                {"en": "Nine out of Nine", "de": "Neun von neun"},
                {"en": "Hit three triples of the target in a turn, nine points, with the standard scoring.",
                 "de": "Im Standard-Wertungsprofil mit drei Triples der Zielzahl neun Punkte in einer Aufnahme erzielen."},
                game_modes=TARGET_BATTLE, label="9", check=_nine_out_of_nine),
    Achievement("no_empty_rounds", "target_battle", "medium",
                {"en": "No Empty Rounds", "de": "Keine leere Runde"},
                {"en": "Score at least one point in every round of a standard game of ten rounds.",
                 "de": "Im Standardspiel mit zehn Runden in jeder Runde mindestens einen Punkt erzielen."},
                game_modes=TARGET_BATTLE, check=_no_empty_rounds),
    Achievement("on_target", "target_battle", "hard",
                {"en": "On Target", "de": "Treffsicher"},
                {"en": "Score at least 60 of 90 points in a standard game of ten rounds.",
                 "de": "Im Standardspiel mit zehn Runden mindestens 60 von 90 Punkten erzielen."},
                game_modes=TARGET_BATTLE, label="60", check=_points_at_least(60)),
    Achievement("sharpshooter", "target_battle", "very_hard",
                {"en": "Sharpshooter", "de": "Meisterschütze"},
                {"en": "Score at least 75 of 90 points in a standard game of ten rounds.",
                 "de": "Im Standardspiel mit zehn Runden mindestens 75 von 90 Punkten erzielen."},
                game_modes=TARGET_BATTLE, label="75", check=_points_at_least(75)),
    Achievement("perfect_battle", "target_battle", "extreme",
                {"en": "Perfect Battle", "de": "Perfektes Battle"},
                {"en": "Score all 90 of 90 points in a standard game of ten rounds.",
                 "de": "Im Standardspiel mit zehn Runden 90 von 90 Punkten erzielen."},
                game_modes=TARGET_BATTLE, label="90", check=_points_at_least(90)),
    Achievement("photo_finish", "target_battle", "medium",
                {"en": "Photo Finish", "de": "Fotofinish"},
                {"en": "Win a standard game against at least one opponent by exactly one point, without a tiebreak.",
                 "de": "Ein Standardspiel gegen mindestens einen Gegner mit genau einem Punkt Vorsprung auf den Zweitplatzierten gewinnen, ohne Stechen."},
                game_modes=TARGET_BATTLE, check=_photo_finish),
    Achievement("final_round_comeback", "target_battle", "hard",
                {"en": "Final-Round Comeback", "de": "Schlussattacke"},
                {"en": "Be behind the only leader before the last round of a standard game and win it alone, without a tiebreak.",
                 "de": "Vor der letzten regulären Runde hinter dem alleinigen Führenden liegen und nach dieser Runde allein gewinnen, ohne Stechen."},
                game_modes=TARGET_BATTLE, check=_final_round_comeback),
    Achievement("double_focus", "target_battle", "hard",
                {"en": "Double Focus", "de": "Double-Fokus"},
                {"en": "Score at least 15 of 30 points in the doubles-only profile with ten rounds.",
                 "de": "Im Trainingsprofil „Nur Doubles“ mit zehn Runden mindestens 15 von 30 Punkten erzielen."},
                game_modes=TARGET_BATTLE, label="15", check=_training_focus("doubles")),
    Achievement("triple_focus", "target_battle", "very_hard",
                {"en": "Triple Focus", "de": "Triple-Fokus"},
                {"en": "Score at least 15 of 30 points in the triples-only profile with ten rounds.",
                 "de": "Im Trainingsprofil „Nur Triples“ mit zehn Runden mindestens 15 von 30 Punkten erzielen."},
                game_modes=TARGET_BATTLE, label="15", check=_training_focus("triples")),
    Achievement("either_side_of_twenty", "target_battle", "hidden",
                {"en": "Either Side of Twenty", "de": "Rechts und links vorbei"},
                {"en": "With target 20, hit only 1 and 5 with the three darts of a turn, both of them.",
                 "de": "Bei Zielzahl 20 mit allen drei Darts ausschliesslich die Zahlen 1 oder 5 treffen, beide müssen vorkommen."},
                game_modes=TARGET_BATTLE, hidden=True, label="1 5", check=_either_side_of_twenty),
    Achievement("wrong_maximum", "target_battle", "hidden",
                {"en": "Wrong Maximum", "de": "Falsches Maximum"},
                {"en": "Hit three T20 in a turn when the target is not 20, with the standard scoring.",
                 "de": "Im Standard-Wertungsprofil bei einer anderen Zielzahl als 20 drei T20 treffen."},
                game_modes=TARGET_BATTLE, hidden=True, label="180", check=_wrong_maximum),
    Achievement("better_late_than_never", "target_battle", "hidden",
                {"en": "Better Late Than Never", "de": "Besser spät als nie"},
                {"en": "Score nothing with the first two darts of a turn and hit the triple of the target with the third.",
                 "de": "In einer Aufnahme mit den ersten beiden Darts keine Punkte erzielen und mit dem dritten Dart das Triple der Zielzahl treffen."},
                game_modes=TARGET_BATTLE, hidden=True, check=_better_late_than_never),
    Achievement("exactly_sixty", "target_battle", "hidden",
                {"en": "Exactly Sixty", "de": "Punktlandung"},
                {"en": "Finish a standard game of ten rounds with exactly 60 points.",
                 "de": "Ein Standardspiel mit zehn Runden mit genau 60 Punkten abschliessen."},
                game_modes=TARGET_BATTLE, hidden=True, label="60", check=_exactly_sixty),
    Achievement("extended_breakfast", "target_battle", "hidden",
                {"en": "Extended Breakfast", "de": "Verlängerter Frühstückstisch"},
                {"en": "Win a Target Battle after at least three tiebreak rounds.",
                 "de": "Ein Target-Battle-Spiel gewinnen, nachdem mindestens drei Stechrunden gespielt wurden."},
                game_modes=TARGET_BATTLE, hidden=True, check=_extended_breakfast),
    Achievement("bull_drill", "field_training", "endurance",
                {"en": "Bull Drill", "de": "Bull-Drill"},
                {"en": "Score 20, 40 and 50 points in a run of 50 darts at the bull; a longer run counts scaled to 50 darts.",
                 "de": "In einem Lauf mit 50 Darts auf das Bull 20, 40 und 50 Punkte erzielen; ein längerer Lauf zählt auf 50 Darts umgerechnet."},
                game_modes=FIELD_TRAINING, label="50", tiers=(20, 40, 50), peak=True, count=_bull_drill),
    Achievement("hundred_darts", "field_training", "endurance",
                {"en": "Hundred Darts", "de": "Hundert Darts"},
                {"en": "Complete a run of 100 darts at a number once, 5 times and 20 times.",
                 "de": "Einen Lauf mit 100 Darts auf eine Zahl 1, 5 und 20 Mal abschliessen."},
                game_modes=FIELD_TRAINING, label="100", tiers=(1, 5, 20), count=_hundred_darts),
    Achievement("triple_threat", "field_training", "hidden",
                {"en": "Triple Threat", "de": "Dreifache Bedrohung"},
                {"en": "Hit the triple of your field with all three darts of one turn in Field Training.",
                 "de": "Im Field Training mit allen drei Darts einer Aufnahme das Triple des Zielfelds treffen."},
                game_modes=FIELD_TRAINING, hidden=True, label="3T", practice=True, check=_triple_threat),
    Achievement("grand_tour", "field_training", "hidden",
                {"en": "Grand Tour", "de": "Grand Tour"},
                {"en": "Complete a full run at every number from 1 to 20 and at the bull.",
                 "de": "Einen vollständigen Lauf auf jede Zahl von 1 bis 20 und auf das Bull abschliessen."},
                game_modes=FIELD_TRAINING, hidden=True, label="21", check=_grand_tour),
    Achievement("black_belt", "black_belt", "extreme",
                {"en": "Black Belt", "de": "Schwarzer Gürtel"},
                {"en": "Get through the whole ladder of the Black Belt drill, D1 to D20 and the bull's eye, without a restart.",
                 "de": "Die ganze Leiter des Black-Belt-Drills, D1 bis D20 und das Bull's Eye, ohne Neustart schaffen."},
                game_modes=BLACK_BELT, check=_black_belt),
    Achievement("belt_progress", "black_belt", "endurance",
                {"en": "Coloured Belts", "de": "Farbige Gürtel"},
                {"en": "Get through 5, 10 and 15 fields of the Black Belt ladder in one go.",
                 "de": "Im Black Belt 5, 10 und 15 Felder der Leiter in einem Durchgang schaffen."},
                game_modes=BLACK_BELT, label="15", tiers=(5, 10, 15), peak=True, count=_belt_progress),
    Achievement("dead_eye", "black_belt", "hidden",
                {"en": "Dead Eye", "de": "Falkenauge"},
                {"en": "Hit five fields in a row of the Black Belt ladder, each with the first dart thrown at it.",
                 "de": "Im Black Belt fünf Felder der Leiter hintereinander treffen, jedes mit dem ersten Dart darauf."},
                game_modes=BLACK_BELT, hidden=True, label="5", check=_dead_eye),
    Achievement("regular_guest", "general", "endurance",
                {"en": "Regular Guest", "de": "Stammgast"},
                {"en": "Finish at least one match on 30 different calendar days.",
                 "de": "An 30 unterschiedlichen lokalen Kalendertagen mindestens ein Spiel abschliessen."},
                game_modes=ANY, label="30", tiers=(30,), peak=True, count=_distinct_days),
    Achievement("heavy_hitter", "x01", "endurance",
                {"en": "Heavy Hitter", "de": "Schwerer Brocken"},
                {"en": "Score 140 or more in a turn of an X01 match.",
                 "de": "In einer Aufnahme eines X01-Spiels mindestens 140 Punkte erzielen."},
                game_modes=X01, label="140", tiers=(1, 10, 100), count=_heavy_hitter),
    Achievement("average_class", "x01", "endurance",
                {"en": "Average Class", "de": "Durchschnittsklasse"},
                {"en": "Reach a 3-dart average of 40, 60, 80 or 100 in a match with at least five turns of your own.",
                 "de": "In einem Spiel mit mindestens fünf eigenen Aufnahmen einen 3-Dart-Schnitt von 40, 60, 80 und 100 erreichen."},
                game_modes=X01, tiers=(40, 60, 80, 100), peak=True, count=_best_average),
    Achievement("short_order", "x01", "medium",
                {"en": "Short Order", "de": "Kurzer Prozess"},
                {"en": "Finish a 501 leg in at most 18 darts.",
                 "de": "Ein 501-Leg in höchstens 18 Darts beenden."},
                game_modes=X01, label="18", check=_short_order),
    Achievement("bullseye_finish", "x01", "medium",
                {"en": "Bullseye Finish", "de": "Volltreffer"},
                {"en": "Finish a leg on the inner bull.",
                 "de": "Ein Leg mit dem inneren Bull beenden."},
                game_modes=X01, check=_bullseye_finish),
    Achievement("streak_master", "x01", "hard",
                {"en": "Streak Master", "de": "Serienmeister"},
                {"en": "Win three X01 matches in a row.",
                 "de": "Drei X01-Spiele in Folge gewinnen."},
                game_modes=X01, label="3", check=_streak_master),
    Achievement("closing_routine", "x01", "endurance",
                {"en": "Closing Routine", "de": "Abschluss-Routine"},
                {"en": "Finish legs with a checkout: 10, 50 and 250 times.",
                 "de": "Legs mit einem Checkout beenden: zehnmal, 50-mal und 250-mal."},
                game_modes=X01, tiers=(10, 50, 250), count=_closing_routine),
    Achievement("checkout_collector", "x01", "endurance",
                {"en": "Checkout Collector", "de": "Checkout-Sammler"},
                {"en": "Finish a leg on every double D1 to D20 and on the inner bull.",
                 "de": "Auf jedem Double D1 bis D20 und auf dem inneren Bull mindestens ein Leg beenden."},
                game_modes=X01, label="21", tiers=(21,), peak=True, count=_checkout_collection),
    Achievement("roughly_pi", "x01", "hidden",
                {"en": "Roughly Pi", "de": "Pi mal Daumen"},
                {"en": "Leave exactly 314 after a turn.",
                 "de": "Nach einer Aufnahme stehen genau 314 Punkte aus."},
                game_modes=X01, hidden=True, label="314", check=_rest_after_turn_is(314)),
    Achievement("repdigit", "x01", "hidden",
                {"en": "Repdigit", "de": "Schnapszahl"},
                {"en": "Leave exactly 111, 222, 333 or 444 after a turn.",
                 "de": "Nach einer Aufnahme stehen genau 111, 222, 333 oder 444 Punkte aus."},
                game_modes=X01, hidden=True, label="333", check=_rest_after_turn_is(111, 222, 333, 444)),
    Achievement("small_fry", "x01", "hidden",
                {"en": "Small Fry", "de": "Kleinvieh macht auch Mist"},
                {"en": "Hit three S1 in one turn.",
                 "de": "Drei S1 in einer Aufnahme treffen."},
                game_modes=X01, hidden=True, label="111", check=_small_fry),
    Achievement("fasting", "x01", "hidden",
                {"en": "Fasting", "de": "Diät"},
                {"en": "Throw all three darts of a turn outside every scoring field.",
                 "de": "Alle drei Darts einer Aufnahme ausserhalb aller Wertungsfelder werfen."},
                game_modes=X01, hidden=True, check=_fasting),
    Achievement("deja_vu", "x01", "hidden",
                {"en": "Déjà Vu", "de": "Déjà-vu"},
                {"en": "Hit the same three fields in the same order in two turns in a row.",
                 "de": "In zwei aufeinanderfolgenden eigenen Aufnahmen dieselben drei Felder in derselben Reihenfolge treffen."},
                game_modes=X01, hidden=True, check=_deja_vu),
    Achievement("case_of_the_jitters", "x01", "hidden",
                {"en": "Case of the Jitters", "de": "Nervenflattern"},
                {"en": "Throw at least nine darts in one leg at a rest that one dart could finish, without finishing.",
                 "de": "In einem Leg mindestens neun Darts werfen, bei denen der Rest mit einem Dart auscheckbar war, ohne auszuchecken."},
                game_modes=X01, hidden=True, check=_case_of_the_jitters),
    Achievement("spoilsport", "x01", "hidden",
                {"en": "Spoilsport", "de": "Spielverderber"},
                {"en": "Finish a leg while an opponent has a rest that one dart could finish.",
                 "de": "Ein Leg beenden, während ein Gegner einen Rest hat, der mit einem Dart auscheckbar ist."},
                game_modes=X01, hidden=True, check=_spoilsport),
    Achievement("lonely_one", "x01", "hidden",
                {"en": "Lonely One", "de": "Einsamer Einser"},
                {"en": "Bust by leaving exactly one.",
                 "de": "Einen Bust verursachen, der 1 Rest hinterlassen würde."},
                game_modes=X01, hidden=True, check=_lonely_one),
    Achievement("early_bird", "x01", "hidden",
                {"en": "Early Bird", "de": "Frühaufsteher"},
                {"en": "Win a leg before 7:00 local time.",
                 "de": "Ein Leg vor 7:00 Uhr lokaler Zeit gewinnen."},
                game_modes=X01, hidden=True, check=_early_bird),
    Achievement("night_owl", "x01", "hidden",
                {"en": "Night Owl", "de": "Nachtschwärmer"},
                {"en": "Win a leg between 0:00 and 4:00 local time.",
                 "de": "Ein Leg zwischen 0:00 und 4:00 Uhr lokaler Zeit gewinnen."},
                game_modes=X01, hidden=True, check=_night_owl),
    Achievement("answer_to_everything", "x01", "hidden",
                {"en": "Answer to Everything", "de": "Antwort auf alles"},
                {"en": "Check out 42 with S10 and then D16 in one turn.",
                 "de": "42 Rest mit S10 und anschliessend D16 in einer Aufnahme auschecken."},
                game_modes=X01, hidden=True, label="42", check=_answer_to_everything),
    Achievement("burnt_toast", "x01", "hidden",
                {"en": "Burnt Toast", "de": "Toast verbrannt"},
                {"en": "Hit T20 with 2 left and bust.",
                 "de": "Bei 2 Rest T20 treffen und dadurch einen Bust verursachen."},
                game_modes=X01, hidden=True, check=_burnt_toast),
    Achievement("breakfast_switch", "x01", "hidden",
                {"en": "Breakfast Switch", "de": "Frühstückswechsel"},
                {"en": "Check out 110 with T20, S10 and D20 in this order.",
                 "de": "110 Rest mit T20, S10 und D20 in dieser Reihenfolge auschecken."},
                game_modes=X01, hidden=True, check=_breakfast_switch),
    Achievement("not_found", "easter_egg", "hidden",
                {"en": "Not Found", "de": "Nicht gefunden"},
                {"en": "Throw S4, a miss outside every scoring field and S4, in this order in one turn.",
                 "de": "S4, einen Fehlwurf ausserhalb aller Wertungsfelder und S4 in genau dieser Reihenfolge in einer Aufnahme werfen."},
                game_modes=ANY, hidden=True, label="404", check=_not_found),
    Achievement("service_unavailable", "easter_egg", "hidden",
                {"en": "Service Unavailable", "de": "Dienst nicht verfügbar"},
                {"en": "Throw S5, a miss outside every scoring field and S3, in this order in one turn.",
                 "de": "S5, einen Fehlwurf ausserhalb aller Wertungsfelder und S3 in genau dieser Reihenfolge in einer Aufnahme werfen."},
                game_modes=ANY, hidden=True, label="503", check=_service_unavailable),
    Achievement("full_english", "easter_egg", "hidden",
                {"en": "Full English", "de": "Englisches Frühstück"},
                {"en": "Hit S20, D20 and T20 in one turn, in any order.",
                 "de": "S20, D20 und T20 in einer Aufnahme treffen, Reihenfolge beliebig."},
                game_modes=ANY, hidden=True, check=_full_english),
    Achievement("copying_costs", "elimination", "hidden",
                {"en": "Copying Costs", "de": "Kopieren kostet"},
                {"en": "Score exactly the score to beat without a free pass and lose a life.",
                 "de": "Ohne Freipass genau die Vorgabe werfen und dadurch ein Leben verlieren."},
                game_modes=ELIMINATION, hidden=True, label="=", check=_copying_costs),
    Achievement("a_new_low", "elimination", "hidden",
                {"en": "A New Low", "de": "Tiefer geht immer"},
                {"en": "Score below a positive score to beat without a free pass, and the next player scores below that new score too. Both of you lose a life and earn it.",
                 "de": "Eine positive Vorgabe ohne Freipass unterbieten, der nächste Spieler unterbietet ohne Freipass auch diese neue Vorgabe. Beide verlieren ein Leben und erhalten den Erfolg."},
                game_modes=ELIMINATION, hidden=True, check=_a_new_low),
    Achievement("free_pass_failed", "elimination", "hidden",
                {"en": "Free Pass, Failed", "de": "Freipass verpasst"},
                {"en": "Score nothing with a free pass and lose a life.",
                 "de": "Bei einem Freipass null Punkte werfen und ein Leben verlieren."},
                game_modes=ELIMINATION, hidden=True, label="0", check=_free_pass_failed),
    Achievement("one_crumb_is_enough", "elimination", "hidden",
                {"en": "One Crumb Is Enough", "de": "Ein Krümel genügt"},
                {"en": "Score exactly one point with a free pass and keep your life.",
                 "de": "Bei einem Freipass insgesamt genau einen Punkt werfen und das Leben behalten."},
                game_modes=ELIMINATION, hidden=True, label="1", check=_one_crumb_is_enough),
    Achievement("tied_to_the_grave", "elimination", "hidden",
                {"en": "Tied to the Grave", "de": "Gleichstand im Grab"},
                {"en": "Score exactly the score to beat with your last life, without a free pass, and be out.",
                 "de": "Mit dem letzten Leben ohne Freipass genau die Vorgabe treffen und dadurch ausscheiden."},
                game_modes=ELIMINATION, hidden=True, label="=", check=_tied_to_the_grave),
    Achievement("after_me_the_deluge", "elimination", "hidden",
                {"en": "After Me, the Deluge", "de": "Nach mir die Sintflut"},
                {"en": "Score 180, and the next player loses a life without a free pass.",
                 "de": "180 werfen, der nächste Spieler spielt ohne Freipass und verliert ein Leben."},
                game_modes=ELIMINATION, hidden=True, label="180", check=_after_me_the_deluge),
    Achievement("chips_for_breakfast", "elimination", "hidden",
                {"en": "Chips for Breakfast", "de": "Chips zum Frühstück"},
                {"en": "Hit S5, S20 and S1 without a free pass and beat the score to beat with the 26 points, in any order.",
                 "de": "Ohne Freipass je S5, S20 und S1 treffen und mit den 26 Punkten die Vorgabe überbieten, Reihenfolge beliebig."},
                game_modes=ELIMINATION, hidden=True, check=_chips_for_breakfast),
    Achievement("close_still_costs", "elimination", "hidden",
                {"en": "Close Still Costs", "de": "Knapp vorbei ist auch verloren"},
                {"en": "Stay exactly one point below the score to beat without a free pass and lose a life.",
                 "de": "Ohne Freipass genau einen Punkt unter der Vorgabe bleiben und ein Leben verlieren."},
                game_modes=ELIMINATION, hidden=True, label="-1", check=_close_still_costs),
    Achievement("four_course_meal", "general", "easy",
                {"en": "Four-Course Meal", "de": "Vier-Gänge-Menü"},
                {"en": "Finish a match of X01, Elimination, Killer and Target Battle each.",
                 "de": "Je ein Spiel X01, Elimination, Killer und Target Battle abschliessen."},
                check=_four_course_meal),
    Achievement("licence_to_breakfast", "killer", "easy",
                {"en": "Licence to Breakfast", "de": "Lizenz zum Frühstücken"},
                {"en": "Become a killer for the first time.", "de": "Erstmals den Killer-Status aktivieren."},
                game_modes=KILLER, check=_licence_to_breakfast),
    Achievement("armed_immediately", "killer", "medium",
                {"en": "Armed Immediately", "de": "Sofort scharf"},
                {"en": "Become a killer with your first dart of the game.",
                 "de": "Mit dem ersten eigenen Dart des Spiels den Killer-Status aktivieren."},
                game_modes=KILLER, check=_armed_immediately),
    Achievement("first_blood", "killer", "easy", {"en": "First Blood", "de": "Erster Treffer"},
                {"en": "Take a life from an opponent for the first time.",
                 "de": "Erstmals einem Gegner ein Leben abziehen."},
                game_modes=KILLER, check=_first_blood),
    Achievement("three_in_one", "killer", "medium", {"en": "Three in One", "de": "Drei auf einen Streich"},
                {"en": "Take three lives from opponents in one turn.",
                 "de": "In einer Aufnahme insgesamt drei gegnerische Leben abziehen."},
                game_modes=KILLER, label="3", check=_three_in_one),
    Achievement("all_round_attack", "killer", "hard", {"en": "All-Round Attack", "de": "Rundumschlag"},
                {"en": "Take a life from three different opponents in one turn, in a game of at least four players.",
                 "de": "In einer Aufnahme drei unterschiedlichen Gegnern je ein Leben abziehen, bei mindestens vier Teilnehmern."},
                game_modes=KILLER, label="3", check=_all_round_attack),
    Achievement("finisher", "killer", "easy", {"en": "Finisher", "de": "Vollstrecker"},
                {"en": "Put an opponent out with one of your hits.",
                 "de": "Mit einem eigenen Treffer einen Gegner auf null Leben bringen."},
                game_modes=KILLER, check=_finisher),
    Achievement("double_knockout", "killer", "hard", {"en": "Double Knockout", "de": "Doppeltes Aus"},
                {"en": "Put two different opponents out in one turn.",
                 "de": "In einer Aufnahme zwei unterschiedliche Gegner durch eigene Treffer ausschalten."},
                game_modes=KILLER, label="2", check=_double_knockout),
    Achievement("unscathed", "killer", "hard", {"en": "Unscathed", "de": "Unversehrt"},
                {"en": "Win a game of at least three players without losing a life.",
                 "de": "Mit mindestens drei Teilnehmern gewinnen, ohne ein Leben zu verlieren."},
                game_modes=KILLER, check=_unscathed),
    Achievement("last_breath", "killer", "medium", {"en": "Last Breath", "de": "Letzter Atemzug"},
                {"en": "Win with exactly one life left.", "de": "Mit genau einem verbleibenden Leben gewinnen."},
                game_modes=KILLER, check=_last_breath),
    Achievement("double_agent", "killer", "hard", {"en": "Double Agent", "de": "Double-Agent"},
                {"en": "With only doubles taking lives, win a game of at least three players and take at least three lives yourself.",
                 "de": "Bei deaktivierten Single-Angriffen ein Spiel mit mindestens drei Teilnehmern gewinnen und selbst mindestens drei gegnerische Leben abziehen."},
                game_modes=KILLER, check=_double_agent),
    Achievement("self_service", "killer", "hidden", {"en": "Self-Service", "de": "Selbstbedienung"},
                {"en": "Lose your last life to your own hit and be out, with own goals on.",
                 "de": "Bei aktivierten Eigentoren durch einen eigenen Treffer das letzte Leben verlieren und ausscheiden."},
                game_modes=KILLER, hidden=True, check=_self_service),
    Achievement("glass_cannon", "killer", "hidden", {"en": "Glass Cannon", "de": "Glaskanone"},
                {"en": "As a killer with one life left, take two lives from opponents in a turn and then put yourself out with an own goal.",
                 "de": "Als aktiver Killer mit einem verbleibenden Leben in einer Aufnahme zuerst zwei gegnerische Leben abziehen und anschliessend durch ein Eigentor ausscheiden."},
                game_modes=KILLER, hidden=True, check=_glass_cannon),
    Achievement("friendly_to_the_end", "killer", "hidden", {"en": "Friendly to the End", "de": "Freundlich bis zuletzt"},
                {"en": "Be out in a game of at least three players without having taken a life from anyone.",
                 "de": "In einem Spiel mit mindestens drei Teilnehmern ausscheiden, ohne einem Gegner ein Leben abgezogen zu haben."},
                game_modes=KILLER, hidden=True, check=_friendly_to_the_end),
    Achievement("own_worst_enemy", "killer", "hidden", {"en": "Own Worst Enemy", "de": "Eigene Baustelle"},
                {"en": "Lose all three lives to own goals alone, with own goals on.",
                 "de": "Bei aktivierten Eigentoren alle drei eigenen Leben ausschliesslich durch Eigentore verlieren."},
                game_modes=KILLER, hidden=True, check=_own_worst_enemy),
    Achievement("beast_mode", "easter_egg", "hidden", {"en": "Beast Mode", "de": "Beast Mode"},
                {"en": "Hit three S6 in one turn.", "de": "Drei S6 in einer Aufnahme treffen."},
                hidden=True, label="666", check=_beast_mode),
)

BY_ID = {a.id: a for a in ACHIEVEMENTS}


# ── Engine ───────────────────────────────────────────────────────────────────

# How long one unlock banner stays on /tv (the animation in AchievementBanner.svelte) and a short
# pause after it, so that two sounds never run into each other.
BANNER_SECONDS = 5.2
UNLOCK_SPACING = BANNER_SECONDS + 0.3


class _Pacer:
    """Runs actions one *spacing* apart: the first at once, each of the next ones when the one
    before it has had its time. Used to give every unlock its own moment when a match earns
    several achievements together."""

    def __init__(self, spacing, clock=time.monotonic):
        self.spacing = spacing
        self._clock = clock
        self._lock = threading.Lock()
        self._pending = deque()
        self._next = 0.0
        self._timer = None

    def submit(self, action):
        with self._lock:
            self._pending.append(action)
            waiting = self._timer is not None
        if not waiting:
            self._release()

    def _release(self):
        with self._lock:
            self._timer = None
            if not self._pending:
                return
            wait = self._next - self._clock()
            if wait > 0:
                self._schedule(wait)
                return
            action = self._pending.popleft()
            self._next = self._clock() + self.spacing
        try:
            action()
        except Exception:
            log.exception("Releasing an achievement failed")
        with self._lock:
            if self._pending and self._timer is None:
                self._schedule(max(0.0, self._next - self._clock()))

    def _schedule(self, wait):
        self._timer = threading.Timer(wait, self._release)
        self._timer.daemon = True
        self._timer.start()


class AchievementEngine:
    def __init__(self, db, definitions=ACHIEVEMENTS, on_earned=None, on_revoked=None):
        """on_earned / on_revoked are called with {"player", "achievement", "tier"} for each
        change, after the database is updated. A failing callback is only logged."""
        self.db = db
        self.definitions = tuple(definitions)
        self.on_earned = on_earned
        self.on_revoked = on_revoked

    def attach(self):
        """Evaluate a match whenever the database reports it changed."""
        self.db.on_match_changed = self.evaluate_match
        self.db.achievement_engine = self
        return self

    def notification(self, change: dict) -> dict:
        """The message the browsers get for one earned achievement: everything the badge
        needs, with the name shown (it is earned now, a secret one too)."""
        a = next(d for d in self.definitions if d.id == change["achievement"])
        return {"type": "achievement", "player": change["player"], "id": a.id,
                "mode": a.mode, "difficulty": a.difficulty, "hidden": a.hidden, "motif": a.motif or a.id,
                "names": a.names, "descriptions": a.descriptions, "label": a.label,
                "tiers": list(a.tiers) if a.tiers else None,
                "tier": change["tier"] or 1}

    def announce(self, push, audio=None, sounds=None, spacing=UNLOCK_SPACING):
        """Send every newly earned achievement to the browsers with `push` and play its sound.
        `sounds(id)` gives the files assigned to the achievement; one of them is played. Without
        one: `achievement_<id>` if there is a file for that achievement, else the general
        `achievement`. No file means no sound. Revoked ones are not announced.
        Several unlocks of one match come one banner apart, each with its own banner and sound."""
        pacer = _Pacer(spacing)

        def release(change):
            push(self.notification(change))
            if not audio:
                return
            assigned = sounds(change["achievement"]) if sounds else []
            if assigned and audio.play_file(random.choice(assigned)):
                return
            audio.play(f"achievement_{change['achievement']}") or audio.play("achievement")

        self.on_earned = lambda change: pacer.submit(lambda: release(change))
        return self

    def overview(self, player: str) -> list:
        """Every achievement with the player's state, for the profile. `tier` is how many
        tiers are earned (an event counts as one), `progress` and `next` only exist for
        counters. `percent` is the share of players who have the shown tier. What a hidden achievement is called, how it is earned and how many have it stays secret until it is earned."""
        rows = {}
        for r in self.db.earned_for_player(player):
            rows.setdefault(r["achievement_id"], {})[r["tier"]] = r
        start = self.db.achievements_start()
        matches = self.db.player_final_matches(player, start)
        players, counts = self.db.achievement_distribution(start)
        items = []
        for a in self.definitions:
            earned = rows.get(a.id, {})
            item = {"id": a.id, "mode": a.mode, "difficulty": a.difficulty, "hidden": a.hidden,
                    "motif": a.motif or a.id,
                    "names": a.names, "descriptions": a.descriptions, "label": a.label,
                    "tiers": list(a.tiers) if a.tiers else None,
                    "tier": 0, "earned_at": None, "progress": None, "next": None,
                    "percent": None}
            if a.count:
                item["tier"] = max(earned) if earned else 0
                item["progress"] = _total(a, [a.count(self._context(m, player)) for m in matches
                                              if a.applies_to(m["game_mode"]) and a.counts_match(m)])
                item["next"] = a.tiers[item["tier"]] if item["tier"] < len(a.tiers) else None
            else:
                item["tier"] = 1 if earned else 0
            if earned:
                item["earned_at"] = earned[max(earned)]["earned_at"]
            if players:
                # The share of players with the tier the badge shows: the highest earned,
                # or the first one while nothing is earned.
                shown = max(item["tier"], 1) if a.count else 0
                item["percent"] = round(100 * counts.get((a.id, shown), 0) / players, 1)
            if a.hidden and not earned:
                item["names"] = item["descriptions"] = item["label"] = item["percent"] = None
            items.append(item)
        return items

    def evaluate_match(self, match_id: str) -> dict:
        """Reconcile the earned achievements of every player of a match with the stored data."""
        result = {"earned": [], "revoked": []}
        match = self.db.match_row(match_id)
        if not match:
            return result
        start = self.db.achievements_start()
        if match["started_at"] < start:
            return result
        hidden = set(self.db.hidden_players())
        for player in self.db.match_participants(match_id):
            if player in hidden:
                continue
            for achievement in self.definitions:
                if not achievement.applies_to(match["game_mode"]):
                    continue
                if achievement.check:
                    self._reconcile_event(achievement, player, match, start, result)
                else:
                    self._reconcile_counter(achievement, player, match, start, result)
        self._notify(result)
        return result

    def _context(self, match, player):
        return MatchContext(self.db, match, player)

    def _reconcile_event(self, a, player, match, start, result):
        final = match["ended_at"] is not None
        qualifies = final and a.counts_match(match) and bool(a.check(self._context(match, player)))
        rows = self.db.earned_rows(player, a.id)
        if not rows:
            if qualifies:
                self.db.add_earned(player, a.id, 0, match["match_id"])
                result["earned"].append(_change(player, a, 0))
            return
        row = rows[0]
        if row["match_id"] != match["match_id"] or qualifies:
            return
        # The match that earned it no longer does: another match may still earn it.
        for other in self.db.player_final_matches(player, start):
            if (other["match_id"] != match["match_id"] and a.counts_match(other)
                    and a.check(self._context(other, player))):
                self.db.set_earned_match(row["id"], other["match_id"])
                return
        self.db.delete_earned(row["id"])
        result["revoked"].append(_change(player, a, 0))

    def _reconcile_counter(self, a, player, match, start, result):
        total = _total(a, [a.count(self._context(m, player))
                           for m in self.db.player_final_matches(player, start)
                           if a.applies_to(m["game_mode"]) and a.counts_match(m)])
        reached = sum(1 for threshold in a.tiers if total >= threshold)
        rows = {r["tier"]: r for r in self.db.earned_rows(player, a.id)}
        for tier in range(1, reached + 1):
            if tier not in rows:
                self.db.add_earned(player, a.id, tier, match["match_id"])
                result["earned"].append(_change(player, a, tier))
        for tier, row in rows.items():
            if tier > reached:
                self.db.delete_earned(row["id"])
                result["revoked"].append(_change(player, a, tier))

    def _notify(self, result):
        for key, callback in (("earned", self.on_earned), ("revoked", self.on_revoked)):
            if not callback:
                continue
            for change in result[key]:
                try:
                    callback(change)
                except Exception:
                    log.exception("Achievement callback failed for %s", change)


def _total(a, values):
    """What a counter has reached: the sum of the matches, or for a `peak` counter the best one."""
    return (max(values, default=0) if a.peak else sum(values))


def _change(player, achievement, tier):
    return {"player": player, "achievement": achievement.id, "tier": tier}
