import logging
from copy import deepcopy

from breakfast.board_darts import BoardDarts

log = logging.getLogger(__name__)


def _to_int(value, default=0):
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _str_to_bool(value, default=False):
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.lower() == "true"
    return default


def _safe_player_name(raw):
    """Handles RTW caller bug where player field can be a dict instead of a string."""
    if isinstance(raw, str):
        return raw
    if isinstance(raw, dict):
        return raw.get("name") or str(raw)
    return str(raw) if raw is not None else None


class GameState:
    def __init__(self):
        # Lives outside reset(): it follows the local board stream, not the match.
        self.board_darts = BoardDarts()
        self.cloud_darts = None     # the darts of the turn of a match played in Autodarts, with their positions; None without one
        self.reset()

    def reset(self):
        self.board_status = None
        self.last_event = None
        self.match_started = False
        self.match_id = None
        self.game_mode = None
        self.points_start = None
        self.special = None
        self.active_player_index = None
        self.active_player_name = None
        self.players = {}
        self.remaining_scores = {}
        self.throw_seq = 0
        self.current_leg = 1
        # Track whether the current turn had per-dart events (dart1/2/3-thrown).
        # False for Cricket/CountUp/RTW/Gotcha which only emit darts-thrown.
        self._turn_had_per_dart_events = False
        # Player index at the last dart event — used to detect player changes.
        self._last_dart_player_index = None

    def _ensure_player(self, player_index, player_name=None, is_bot=None):
        if player_index is None:
            return None
        idx = int(player_index)
        if idx not in self.players:
            self.players[idx] = {
                "name": player_name,
                "is_bot": is_bot,
                "remaining": None,
                "turn_score": 0,
                "turn_active": False,
                "is_bust": False,
                "last_is_miss": False,
                "throw1_raw": None,
                "throw2_raw": None,
                "throw3_raw": None,
                "throw1_points": 0,
                "throw2_points": 0,
                "throw3_points": 0,
                "last_field_name": None,
                "last_field_number": None,
                "last_field_multiplier": None,
                "last_dart_number": None,
                "last_dart_value": None,
                "legs_won": 0,
            }
        player = self.players[idx]
        if player_name is not None:
            player["name"] = player_name
        if is_bot is not None:
            player["is_bot"] = is_bot
        return player

    def _clear_turn(self, player):
        player["turn_active"] = False
        player["turn_score"] = 0
        player["is_bust"] = False
        player["last_is_miss"] = False
        player["throw1_raw"] = None
        player["throw2_raw"] = None
        player["throw3_raw"] = None
        player["throw1_points"] = 0
        player["throw2_points"] = 0
        player["throw3_points"] = 0

    def _sync_players(self, data, new_leg=False):
        """A match played in Breakfast names all its players at its start (`game.players`, in the order of the
        scores), so they are there before they throw: the table shows them and the calls know them. A new leg
        sets everybody's score again and clears what is left of their last turn."""
        names = (data.get("game") or {}).get("players")
        if not isinstance(names, list):
            return
        scores = data.get("remainingScores") or {}
        for idx, name in enumerate(names):
            player = self._ensure_player(idx, name)
            if new_leg:
                self._clear_turn(player)
            player["remaining"] = _to_int(scores.get(f"player{idx + 1}"), player["remaining"])

    def _extract_player(self, data):
        player_name = _safe_player_name(data.get("player"))
        raw_idx = data.get("playerIndex")
        player_index = _to_int(raw_idx, None) if raw_idx is not None else None
        is_bot = _str_to_bool(data.get("playerIsBot"))
        return player_index, player_name, is_bot

    def _apply_remaining_scores(self, data):
        rs = data.get("remainingScores", {})
        if rs:
            self.remaining_scores = {k: _to_int(v, 0) for k, v in rs.items()}

    def update(self, data):
        """Process one caller event. Returns an event dict for downstream consumers or None."""
        event = data.get("event")
        # The first thing every incoming dart/board event passes through —
        # one exhaustive line per event here covers all of them cheaply,
        # rather than needing a log call in every branch below.
        log.debug("update: event=%s data=%s", event, data)
        self.last_event = event

        if event in ("welcome", "mirror"):
            return None

        if event == "Board Status":
            status = data.get("data", {}).get("status")
            self.board_status = status
            return {"type": "board_status", "status": status}

        if event == "match-started":
            self.match_started = True
            self.match_id = data.get("id")
            game = data.get("game", {})
            self.game_mode = game.get("mode")
            self.points_start = _to_int(game.get("pointsStart"), None)
            self.special = game.get("special")
            self.players = {}
            self.throw_seq = 0
            self.current_leg = 1
            self._turn_had_per_dart_events = False
            self._last_dart_player_index = None
            self._apply_remaining_scores(data)
            self._sync_players(data)
            self.active_player_name = _safe_player_name(data.get("player"))
            self.active_player_index = _to_int(data.get("playerIndex"), None)
            return {"type": "match_started", "mode": self.game_mode}

        if event == "match-ended":
            self.match_started = False
            return {"type": "match_ended"}

        if event == "game-started":
            self._turn_had_per_dart_events = False
            self._apply_remaining_scores(data)
            self._sync_players(data, new_leg=True)
            player_index, player_name, _ = self._extract_player(data)
            if player_index is not None:
                self.active_player_index = player_index
                self.active_player_name = player_name
            # Emitted per leg except the first (the translator suppresses it
            # when the leg start coincides with match start).
            return {"type": "game_started", "mode": self.game_mode}

        if event == "x01-resync":
            # A match played in Breakfast went back to before a turn (undo, correction): the scores,
            # the player who is up, the legs and the turn in progress are set again from the event.
            self.match_started = True
            self._apply_remaining_scores(data)
            game = data.get("game", {})
            legs_won = game.get("legsWon") or {}
            self.current_leg = _to_int(game.get("leg"), self.current_leg)
            names = {i: n for i, n in enumerate(game.get("players") or [])}
            for idx, name in names.items():
                player = self._ensure_player(idx, name)
                self._clear_turn(player)
                player["remaining"] = _to_int((data.get("remainingScores") or {}).get(f"player{idx + 1}"), player["remaining"])
                player["legs_won"] = _to_int(legs_won.get(name), 0)
            player_index, player_name, _ = self._extract_player(data)
            if player_index is not None:
                self.active_player_index = player_index
                self.active_player_name = player_name
            self._turn_had_per_dart_events = False
            self._last_dart_player_index = None
            return None

        if event in ("bulling-start", "bulling-end", "lobby", "board"):
            return None

        # All remaining events carry player context
        player_index, player_name, player_is_bot = self._extract_player(data)
        game = data.get("game", {})
        self._apply_remaining_scores(data)

        if player_index is not None:
            player = self._ensure_player(player_index, player_name, player_is_bot)
            self.active_player_index = player_index
            self.active_player_name = player_name
        else:
            player = None

        if event in ("dart1-thrown", "dart2-thrown", "dart3-thrown"):
            if player is None:
                return None

            self.throw_seq += 1
            self._turn_had_per_dart_events = True

            dart_number = _to_int(game.get("dartNumber"), 0)
            dart_value = _to_int(game.get("dartValue"), 0)
            field_name = game.get("fieldName")
            field_number = game.get("fieldNumber")
            field_multiplier = game.get("fieldMultiplier")
            points_left = _to_int(game.get("pointsLeft"), None)
            field_type = str(game.get("type", "")).lower()

            if dart_number == 1:
                self._clear_turn(player)

            if points_left is not None:
                player["remaining"] = points_left

            is_miss = bool(
                (isinstance(field_name, str) and field_name.lower().startswith("m"))
                or field_multiplier == 0
                or field_type == "outside"
                or dart_value == 0
            )

            player["last_field_name"] = field_name
            player["last_field_number"] = field_number
            player["last_field_multiplier"] = field_multiplier
            player["last_dart_number"] = dart_number
            player["last_dart_value"] = dart_value
            player["last_is_miss"] = is_miss
            player["turn_active"] = True

            if dart_number == 1:
                player["throw1_raw"] = field_name
                player["throw1_points"] = dart_value
            elif dart_number == 2:
                player["throw2_raw"] = field_name
                player["throw2_points"] = dart_value
            elif dart_number == 3:
                player["throw3_raw"] = field_name
                player["throw3_points"] = dart_value

            player["turn_score"] = (
                player["throw1_points"] + player["throw2_points"] + player["throw3_points"]
            )

            player_changed = (
                self._last_dart_player_index is not None
                and player_index != self._last_dart_player_index
            )
            self._last_dart_player_index = player_index

            return {
                "type": "dart",
                "seq": self.throw_seq,
                "dart": dart_number,
                "miss": is_miss,
                "points": dart_value,
                "field": field_name,
                "number": field_number,
                "multiplier": field_multiplier,
                "mode": self.game_mode,
                "player_changed": player_changed,
            }

        if event == "darts-thrown":
            if player is None:
                return None

            dart_value = _to_int(game.get("dartValue"), 0)
            points_left = _to_int(game.get("pointsLeft"), None)
            if points_left is not None:
                player["remaining"] = points_left

            if self._turn_had_per_dart_events:
                # X01/Bermuda/Shanghai: per-dart events already handled; just sync total score.
                if dart_value:
                    player["turn_score"] = dart_value
                return None

            # Cricket/CountUp/RTW/Gotcha: darts-thrown is the only dart event this turn.
            self.throw_seq += 1
            player["turn_score"] = dart_value
            player["turn_active"] = True

            player_changed = (
                self._last_dart_player_index is not None
                and player_index != self._last_dart_player_index
            )
            self._last_dart_player_index = player_index

            return {
                "type": "dart",
                "seq": self.throw_seq,
                "dart": 3,
                "miss": False,
                "points": dart_value,
                "field": None,
                "multiplier": None,
                "mode": self.game_mode,
                "player_changed": player_changed,
            }

        if event == "busted":
            if player is None:
                return None
            player["is_bust"] = True
            player["turn_active"] = False
            # busted in X01 uses underscore field names (field_name, not fieldName)
            points_left = _to_int(game.get("pointsLeft"), None)
            if points_left is not None:
                player["remaining"] = points_left
            return {"type": "bust", "mode": self.game_mode}

        if event == "darts-pulled":
            if player is None:
                return None
            points_left = _to_int(game.get("pointsLeft"), None)
            if points_left is not None:
                player["remaining"] = points_left
            player["turn_score"] = _to_int(game.get("dartsThrownValue"), player["turn_score"])
            player["is_bust"] = _str_to_bool(game.get("busted"))
            player["turn_active"] = False
            if _str_to_bool(game.get("newTurn")):
                # The player who is up now has nothing of a turn yet: what the event says about the turn
                # that ended (its total, the bust) does not belong on their card.
                self._clear_turn(player)
            self._turn_had_per_dart_events = False
            return {"type": "turn_end", "mode": self.game_mode}

        if event in ("game-won", "match-won"):
            scope = "game" if event == "game-won" else "match"
            if player is not None and not game.get("decidedBy"):
                player["remaining"] = 0          # a finish; a leg decided by the bull-off keeps what is left
            # Track legs won — winner from event (direct mode) or fall back to current player
            winner_name = game.get("winner") or (player_name if player is not None else None)
            if winner_name:
                for p in self.players.values():
                    if p.get("name") == winner_name:
                        p["legs_won"] = p.get("legs_won", 0) + 1
                        break
            if event == "game-won":
                self.current_leg += 1
            return {"type": "won", "scope": scope, "mode": self.game_mode}

        return None

    def snapshot(self):
        current = None
        if self.active_player_index is not None and self.active_player_index in self.players:
            current = deepcopy(self.players[self.active_player_index])
        return {
            "board_status": self.board_status,
            "last_event": self.last_event,
            "match_started": self.match_started,
            "match_id": self.match_id,
            "game_mode": self.game_mode,
            "points_start": self.points_start,
            "special": self.special,
            "active_player_index": self.active_player_index,
            "active_player_name": self.active_player_name,
            "remaining_scores": deepcopy(self.remaining_scores),
            "throw_seq": self.throw_seq,
            "current_leg": self.current_leg,
            "current": current,
            "players": deepcopy(self.players),
        }
