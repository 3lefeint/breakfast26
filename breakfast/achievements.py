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
"""

import logging
from dataclasses import dataclass
from typing import Callable

log = logging.getLogger(__name__)

# A dart on the inner bull is "50" in Breakfast's own field names and "BULL" in some
# Autodarts events.
INNER_BULL = frozenset({"50", "BULL"})

X01 = "x01"
ELIMINATION = "elimination"
ANY = "any"


@dataclass(frozen=True)
class Turn:
    number: int
    score: int | None
    is_bust: bool
    darts: tuple               # field names that can be trusted, e.g. ("T20", "S1", "BULL")
    is_checkout: bool = False  # X01: this turn finished the leg
    remaining_before: int | None = None   # X01: what was left before the turn
    leg: int = 1


class MatchContext:
    """One player's view of one match, loaded lazily for the checks."""

    def __init__(self, db, match: dict, player: str):
        self.db = db
        self.match = match
        self.player = player
        self._turns = None
        self._participants = None

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
    def won(self) -> bool:
        return self.match["winner"] == self.player


@dataclass(frozen=True)
class Achievement:
    id: str
    mode: str                  # general, x01, elimination, killer, target_battle, easter_egg
    difficulty: str            # easy ... extreme, endurance, hidden
    names: dict                # {"en": ..., "de": ...}
    descriptions: dict         # how to earn it, same languages
    game_modes: str = ANY      # which matches can decide it: x01, elimination or any
    hidden: bool = False       # shown as a silhouette until earned
    label: str | None = None   # short text drawn on the badge
    tiers: tuple | None = None  # counter thresholds, None for an event
    check: Callable | None = None   # event: does this match satisfy it
    count: Callable | None = None   # counter: what this match adds to the total
    motif: str | None = None   # id of the badge motif to share, default: its own

    def applies_to(self, game_mode: str) -> bool:
        if self.game_modes == ANY:
            return True
        is_elimination = game_mode == "Elimination"
        return is_elimination == (self.game_modes == ELIMINATION)


ACHIEVEMENTS = ()

BY_ID = {a.id: a for a in ACHIEVEMENTS}


# ── Engine ───────────────────────────────────────────────────────────────────

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

    def announce(self, push, audio=None):
        """Send every newly earned achievement to the browsers with `push` and play its
        sound: `achievement_<id>` if there is a file for that achievement, else the general
        `achievement`. No file means no sound. Revoked ones are not announced."""
        def on_earned(change):
            push(self.notification(change))
            if audio:
                audio.play(f"achievement_{change['achievement']}") or audio.play("achievement")
        self.on_earned = on_earned
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
                item["progress"] = sum(a.count(self._context(m, player)) for m in matches
                                       if a.applies_to(m["game_mode"]))
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
        qualifies = final and bool(a.check(self._context(match, player)))
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
            if other["match_id"] != match["match_id"] and a.check(self._context(other, player)):
                self.db.set_earned_match(row["id"], other["match_id"])
                return
        self.db.delete_earned(row["id"])
        result["revoked"].append(_change(player, a, 0))

    def _reconcile_counter(self, a, player, match, start, result):
        total = sum(a.count(self._context(m, player))
                    for m in self.db.player_final_matches(player, start))
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


def _change(player, achievement, tier):
    return {"player": player, "achievement": achievement.id, "tier": tier}
