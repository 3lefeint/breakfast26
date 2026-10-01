import contextlib
import json
import logging
import threading
import uuid

from . import known_players as kp

log = logging.getLogger(__name__)

# Give the browser time to redirect to /tv and reconnect its WebSocket with
# role=audio before the opening calls fire — a fresh game (the frontend's
# elimStart()/startRematch() redirect) POSTs, then immediately navigates,
# so the old page's audio-role connection is already gone and the new one
# hasn't registered yet by the time this would otherwise fire synchronously.
# Sound instructions are a live, ephemeral broadcast (unlike state, which
# new connections get resent via _last_payload), so anything sent into that
# gap is lost for good rather than merely delayed.
_START_ANNOUNCE_AUDIO_DELAY_S = 0.5


def _dart_value(throw):
    seg = throw.get("segment", {})
    multiplier = seg.get("multiplier")
    if not multiplier:  # 0 (miss) or None → 0 points
        return 0
    return (seg.get("number") or 0) * multiplier


def _parse_field(field):
    """Parse a field string ('T20', 'D16', 'S5', '25', '50', '0') into a
    synthetic throw object, same shape as a real board throw."""
    field = (field or "").strip().upper()
    if field in ("", "0", "MISS"):
        number, multiplier = 0, 0
    elif field == "25":
        number, multiplier = 25, 1
    elif field == "50":
        number, multiplier = 25, 2
    elif field and field[0] in ("S", "D", "T"):
        mult = {"S": 1, "D": 2, "T": 3}[field[0]]
        number, multiplier = int(field[1:]), mult
    else:
        number, multiplier = int(field), 1
    return {"segment": {"number": number, "multiplier": multiplier}}


class EliminationGame:
    def __init__(self, players, lives_count, client, base_topic, audio=None, on_change=None,
                 stats_db=None):
        self.lives_max = lives_count
        self.order = list(players)
        self.lives = {p: lives_count for p in players}
        self.active = list(players)
        self.current_idx = 0
        self.target = 0
        self.freipass = True  # first player only needs > 0
        self.state = "playing"
        self.winner = None
        self.elimination_order = []  # names in the order they were eliminated
        self.client = client
        self.base_topic = base_topic
        self.audio = audio
        self.stats_db = stats_db
        # Elimination has no externally-supplied match id like X01's Autodarts
        # event id, so it mints its own to give stats.db a matches/turns key.
        self.match_id = uuid.uuid4().hex
        self._on_change = on_change
        self._prev_count = 0
        self._last_throws = []
        self._current_darts = []
        self._dart_overrides = {}  # dart index -> manually corrected throw
        self._turn_snapshot = None
        self._history = []  # stack of pre-turn snapshots, for undo()
        self._outcome_published = False
        self._preview_fired = False
        if self.stats_db:
            self.stats_db.open_match(self.match_id, "Elimination", lives_count)
        log.info("Game started: %s, %d lives", players, lives_count)

    def announce_start(self):
        """Publish the initial state and play the opening calls.

        Must only be called once this game is already assigned to
        `EliminationController.game` — `_publish_state()` triggers
        `on_change` (the WS push), and `_build_payload()` reads
        `_elim_ctrl.game` to build the `elimination` snapshot. Firing it
        from `__init__` would push before the caller had a chance to
        assign `self.game`, so the browser's first update would still see
        no active game.
        """
        self._publish_state()
        self._publish_turn(reset=True)
        self._publish_last_turn([])
        if self.audio:
            threading.Timer(_START_ANNOUNCE_AUDIO_DELAY_S, self._play_start_calls).start()

    def _play_start_calls(self):
        with self._audio_batch():
            self.audio.play("matchon")
            self._announce(self.current_player)
            self.audio.play("filler_after_name")

    def _announce(self, name):
        """Play *name*'s audio cue, falling back to the generic
        unknown_player key if this name has no recording — Elimination
        calls audio.play() directly rather than through Caller, so it
        needs its own copy of that name-lookup fallback."""
        if not self.audio.play(name.lower()):
            self.audio.play("unknown_player")

    def _audio_batch(self):
        """`self.audio.batch()`, or a no-op when audio is disabled — several
        call sites here group multiple sequential play() calls into one
        `with self._audio_batch():` block even though `self.audio` is
        optional."""
        return self.audio.batch() if self.audio else contextlib.nullcontext()

    @property
    def current_player(self):
        if not self.active or self.current_idx >= len(self.active):
            return None
        return self.active[self.current_idx]

    def snapshot(self) -> dict:
        cp = self.current_player
        last_darts = [_dart_value(t) for t in self._last_throws] if self._last_throws else []
        rotated = self.active[self.current_idx:] + self.active[:self.current_idx] \
            if self.active else []
        return {
            "active": self.state == "playing",
            "state": self.state,
            "winner": self.winner,
            "current_player": cp,
            "target": self.target,
            "freipass": self.freipass,
            "lives_max": self.lives_max,
            "current_darts": list(self._current_darts),
            "last_darts": last_darts,
            "elimination_order": list(self.elimination_order),
            "players": [
                {
                    "name": p,
                    "lives": self.lives[p],
                    "active": p in self.active,
                    "current": p == cp,
                }
                for p in self.order
            ],
            # Still-active players only, rotated so the current player is
            # first — the turn queue as seen on the TV Elimination view.
            "turn_order": [
                {"name": p, "lives": self.lives[p], "current": p == cp}
                for p in rotated
            ],
        }

    def on_board_state(self, count, throws):
        if self.state != "playing":
            return
        if count > 0:
            new_vals = [_dart_value(t) for t in throws]
            is_new_dart = count > self._prev_count
            is_correction = count == self._prev_count and new_vals != self._current_darts
            if is_new_dart or is_correction:
                self._last_throws = list(throws)
                self._current_darts = new_vals
                # Re-assert any manual per-dart corrections (tap-to-correct on
                # the TV view) on top of the board's own read — otherwise the
                # next dart landing would silently overwrite them, since the
                # board reports the whole turn's throws afresh each time.
                self._apply_dart_overrides()
                self._publish_turn()
                if self._on_change:
                    self._on_change()
                if is_correction:
                    log.debug("Live correction detected: %s", new_vals)
                if is_new_dart and self.audio:
                    # Miss comment on any dart
                    latest = new_vals[count - 1] if count <= len(new_vals) else 0
                    if latest == 0:
                        self.audio.play("miss", prob=0.35)
                if count == 3 and is_new_dart:
                    self._publish_turn_preview()
        if count == 0 and self._prev_count > 0:
            self._end_turn()
        self._prev_count = count

    def _publish_turn_preview(self):
        """Fire life_lost/eliminated events + audio immediately after the 3rd dart lands.

        Gives immediate visual and audio feedback without waiting for darts to be pulled.
        _apply_turn() skips re-firing these events via _outcome_published.
        _end_turn() skips re-announcing the score itself via _preview_fired.

        If this turn ends the match, the match is finished right here —
        see _finish_match()'s docstring for why _end_turn()/_apply_turn()
        never re-process this turn once darts are eventually pulled.
        """
        score = sum(self._current_darts)
        player = self.current_player
        passes = score > (0 if self.freipass else self.target)
        self._preview_fired = True

        with self._audio_batch():
            if self.audio:
                self.audio.play(str(score))

            if not passes:
                future_lives = self.lives[player] - 1
                event = "eliminated" if future_lives == 0 else "life_lost"
                is_match_over = future_lives == 0 and len(self.active) == 2
                self._publish_event(event, player, score)
                if is_match_over:
                    self._record_turn(player, score, len(self._last_throws))
                    self._push_history(self._snapshot_state(player), turn_recorded=self.stats_db is not None)
                    self.lives[player] = future_lives
                    self._finish_match(player, score)
                    return
                self._outcome_published = True
                if self.audio:
                    self._announce(player)
                    self.audio.play(event)
                    gap = self.target - score
                    if 1 <= gap <= 10:
                        self.audio.play("close", prob=0.7)
                    elif score < 5:
                        self.audio.play("too_low", prob=0.5)
            else:
                if self.audio and score >= 2 * self.target:
                    self.audio.play("nice", prob=0.4)

    def _finish_match(self, player, score):
        """Complete the match — *player* just spent their last life and
        only one active player remains. Shared by the normal 3-dart
        preview path (timing fix: the match ends the instant the
        dart is read, before darts are even pulled — on_board_state()'s
        `state != "playing"` guard means _end_turn() is simply never
        invoked again for this turn once state flips to "finished" here)
        and the rare <3-dart fallback in _apply_turn()."""
        self.active.pop(self.current_idx)
        self.elimination_order.append(player)
        self.winner = self.active[0]
        self.state = "finished"
        self.current_idx = 0
        if self.stats_db:
            placements = [(self.winner, 1, self.lives[self.winner])]
            placements += [
                (name, i + 2, None)
                for i, name in enumerate(reversed(self.elimination_order))
            ]
            self.stats_db.record_elimination_result(self.match_id, placements)
            self.stats_db.set_winner(self.match_id, self.winner)
            self.stats_db.close_match(self.match_id)
        if self.audio:
            # Winner name before matchshot — reversed
            # from the old matchshot-then-name order. Wrapped in its own
            # batch (re-entrant with _publish_turn_preview()'s already-open
            # one on the normal instant-finish path, so both merge into a
            # single wire message) so the winner name + matchshot fetch in
            # parallel rather than serially.
            with self._audio_batch():
                self._announce(self.winner)
                self.audio.play("matchshot")
        self._publish_event("game_won", self.winner, score)
        self._outcome_published = False
        self._preview_fired = False
        self._publish_state()
        self._publish_turn(reset=True)
        log.info("Winner: %s", self.winner)

    def _snapshot_state(self, player):
        """The game state as of right now, before this turn's outcome gets
        applied — shared by `correct_turn()`'s single-level correction and
        `undo()`'s multi-level history."""
        return {
            "player": player,
            "target": self.target,
            "freipass": self.freipass,
            "lives": dict(self.lives),
            "active": list(self.active),
            "current_idx": self.current_idx,
            "state": self.state,
            "winner": self.winner,
            "elimination_order": list(self.elimination_order),
            "darts": list(self._current_darts),
        }

    def _push_history(self, snapshot, turn_recorded):
        """*turn_recorded*: whether a DB row was written for the turn, so
        `undo()` knows whether there is one to delete (False without a stats DB)."""
        self._history.append({**snapshot, "turn_recorded": turn_recorded})

    def _end_turn(self):
        player = self.current_player
        score = sum(_dart_value(t) for t in self._last_throws)
        self._turn_snapshot = self._snapshot_state(player)
        self._push_history(self._turn_snapshot, turn_recorded=self.stats_db is not None)
        self._publish_last_turn(self._current_darts)
        self._record_turn(player, score, len(self._last_throws))
        # Clear the in-progress darts now that the turn is over, so the next
        # _apply_turn()'s state push shows an empty turn instead of leaving
        # this turn's values on screen until the next player's first dart
        # lands (_last_throws is kept — snapshot()'s last_darts/correction
        # flow still needs it).
        self._current_darts = []
        self._dart_overrides = {}
        # If preview didn't fire (< 3 darts detected), announce score now.
        # _outcome_published is only set on a *failed* turn, so it can't be
        # used here — a passing turn always left it False, causing the
        # preview's own score (already played) to be announced again.
        if not self._preview_fired and self.audio:
            self.audio.play(str(score))
        self._apply_turn(player, score)

    def _record_turn(self, player, score, darts_count):
        """Write a finished turn to the stats DB together with what it had to
        beat. Must run before _apply_turn() moves the target on."""
        if not self.stats_db:
            return
        to_beat = 0 if self.freipass else self.target
        self.stats_db.insert_elimination_turn(
            self.match_id, player, darts_count, score=score, target=to_beat,
            freipass=self.freipass, passed=score > to_beat, lives_before=self.lives[player],
            positions=self._dart_positions())

    def _dart_positions(self):
        """Where each dart of the turn landed, None for a dart without a position (one
        corrected by tapping carries none)."""
        positions = []
        for throw in self._last_throws:
            coords = throw.get("coords")
            if isinstance(coords, dict) and "x" in coords and "y" in coords:
                positions.append({"field": (throw.get("segment") or {}).get("name"),
                                  "x": float(coords["x"]), "y": float(coords["y"]),
                                  "entry": throw.get("entry")})
            else:
                positions.append(None)
        return positions

    def _apply_turn(self, player, score, silent=False):
        passes = score > (0 if self.freipass else self.target)
        self.target = score
        self.freipass = False

        with self._audio_batch():
            if passes:
                self._publish_event("turn_pass", player, score)
                self._advance()
            else:
                self.lives[player] -= 1
                if self.lives[player] == 0:
                    # Checked before popping, mirroring _publish_turn_preview()'s
                    # is_match_over check — _finish_match() does the pop itself.
                    is_match_over = len(self.active) == 2
                    if not self._outcome_published and not silent:
                        self._publish_event("eliminated", player, score)
                        if self.audio and not is_match_over:
                            self._announce(player)
                            self.audio.play("eliminated")
                    if is_match_over:
                        # Rare fallback only — the normal path already
                        # finished the match from the preview, before darts
                        # were even pulled (on_board_state()'s
                        # `state != "playing"` guard means this branch is
                        # unreachable then). This only runs when the preview
                        # itself never fired (<3 darts detected).
                        self._finish_match(player, score)
                        return
                    self.active.pop(self.current_idx)
                    self.elimination_order.append(player)
                    if self.current_idx >= len(self.active):
                        self.current_idx = 0
                    self.freipass = True
                else:
                    if not self._outcome_published and not silent:
                        self._publish_event("life_lost", player, score)
                        if self.audio:
                            self._announce(player)
                            self.audio.play("life_lost")
                    self._advance()

            self._outcome_published = False
            self._preview_fired = False
            self._publish_state()
            self._publish_turn(reset=True)
            if self.audio and not silent and self.state == "playing":
                self._announce(self.current_player)
                if self.freipass:
                    # Freipass replaces the target entirely — any score > 0
                    # passes, so there's nothing to announce a number for.
                    self.audio.play("freipass", prob=0.8)
                else:
                    self.audio.play("filler_target")
                    # passes = score > target, i.e. target itself is not
                    # enough — announce the actual minimum passing score.
                    self.audio.play(str(self.target + 1))

    def correct_turn(self, new_total):
        snap = self._turn_snapshot
        if not snap:
            log.warning("No turn to correct")
            return
        self.lives = dict(snap["lives"])
        self.active = list(snap["active"])
        self.current_idx = snap["current_idx"]
        self.target = snap["target"]
        self.freipass = snap["freipass"]
        self.state = snap["state"]
        self.winner = snap["winner"]
        self.elimination_order = list(snap["elimination_order"])
        if self.stats_db:
            self.stats_db.correct_last_elimination_turn(
                self.match_id, snap["player"], new_total,
                new_total > (0 if self.freipass else self.target))
        self._apply_turn(snap["player"], new_total, silent=True)
        log.info("Turn corrected: total=%d", new_total)

    def undo(self) -> bool:
        """Walk back the most recently completed turn — including
        reopening an already-finished match if the winning turn itself
        gets undone, so a misdetected match-ending dart doesn't
        permanently lock in a wrong result. Repeatable: call again to
        keep undoing further back. Returns False if there's nothing left
        to undo. Deliberately silent (no audio) — an undo is a
        correction, not a game event, same as `correct_turn()`."""
        if not self._history:
            return False
        snap = self._history.pop()
        was_finished = self.state == "finished"
        self.lives = dict(snap["lives"])
        self.active = list(snap["active"])
        self.current_idx = snap["current_idx"]
        self.target = snap["target"]
        self.freipass = snap["freipass"]
        self.state = snap["state"]
        self.winner = snap["winner"]
        self.elimination_order = list(snap["elimination_order"])
        if self.stats_db:
            if was_finished:
                self.stats_db.delete_elimination_results(self.match_id)
                self.stats_db.set_winner(self.match_id, None)
                self.stats_db.reopen_match(self.match_id)
            if snap["turn_recorded"]:
                self.stats_db.delete_last_elimination_turn(self.match_id, snap["player"])
        self._current_darts = []
        self._dart_overrides = {}
        self._outcome_published = False
        self._preview_fired = False
        self._turn_snapshot = None
        self._publish_state()
        self._publish_turn(reset=True)
        log.info("Turn undone: %s now up, target=%d", self.current_player, self.target)
        return True

    def correct_current_dart(self, dart_index, field):
        """Correct a single dart of the turn still in progress (darts not
        pulled yet) — e.g. tapping D1/D2/D3 on the TV view. Unlike
        correct_turn() (which reworks the *finished* turn's total after the
        fact), this patches one dart of the *live* turn before it ends, so
        the corrected value is what actually gets scored at turn-end."""
        if self.state != "playing":
            return
        if dart_index not in (0, 1, 2):
            return
        self._dart_overrides[dart_index] = _parse_field(field)
        self._apply_dart_overrides()
        self._publish_turn()
        if self._on_change:
            self._on_change()
        log.info("Dart %d corrected: %s", dart_index + 1, field)

    def _apply_dart_overrides(self):
        for idx, throw in self._dart_overrides.items():
            while len(self._last_throws) <= idx:
                self._last_throws.append({"segment": {"number": 0, "multiplier": 0}})
            while len(self._current_darts) <= idx:
                self._current_darts.append(0)
            self._last_throws[idx] = throw
            self._current_darts[idx] = _dart_value(throw)

    def _advance(self):
        self.current_idx = (self.current_idx + 1) % len(self.active)

    def _publish_event(self, event_type, player, score):
        payload = json.dumps({
            "type": event_type,
            "player": player,
            "score": score,
            "lives": self.lives.get(player, 0),
        })
        self.client.publish(
            f"{self.base_topic}/elimination/events/{event_type}", payload, retain=False
        )
        log.info("%s: %s score=%d", event_type, player, score)

    def _publish_state(self):
        cp = self.current_player
        state = {
            "state": self.state,
            "winner": self.winner,
            "current_player": cp,
            "target": self.target,
            "freipass": self.freipass,
            "lives_max": self.lives_max,
            "order": self.order,
            "active": self.active,
            "players": {
                p: {
                    "lives": self.lives[p],
                    "active": p in self.active,
                    "number": self.order.index(p) + 1,
                }
                for p in self.order
            },
        }
        b = f"{self.base_topic}/elimination"
        self.client.publish(
            f"{b}/state", json.dumps(state, ensure_ascii=False), retain=True
        )
        playing = self.state == "playing"
        self.client.publish(f"{b}/active", "true" if playing else "false", retain=True)
        self.client.publish(
            f"{b}/current_number",
            str(self.order.index(cp) + 1) if cp else "0",
            retain=True,
        )
        self.client.publish(
            f"{b}/current_lives", str(self.lives.get(cp, 0) if cp else 0), retain=True
        )
        self.client.publish(f"{b}/lives_max", str(self.lives_max), retain=True)
        self.client.publish(f"{b}/target", str(self.target), retain=True)
        self.client.publish(
            f"{b}/freipass", "true" if self.freipass else "false", retain=True
        )
        if self._on_change:
            self._on_change()

    def _publish_turn(self, reset=False):
        b = f"{self.base_topic}/elimination/current"
        darts = [] if reset else self._current_darts
        for i in range(3):
            val = str(darts[i]) if i < len(darts) else ""
            self.client.publish(f"{b}/dart{i + 1}", val, retain=True)
        self.client.publish(f"{b}/total", str(sum(darts)), retain=True)

    def _publish_last_turn(self, dart_vals):
        b = f"{self.base_topic}/elimination/last_turn"
        for i in range(3):
            val = str(dart_vals[i]) if i < len(dart_vals) else "0"
            self.client.publish(f"{b}/dart{i + 1}", val, retain=True)
        self.client.publish(f"{b}/total", str(sum(dart_vals)), retain=True)


class EliminationController:
    def __init__(self, mqtt_pub, base_topic, stats_db=None, audio=None, on_change=None):
        self.mqtt_pub = mqtt_pub
        self.base_topic = base_topic
        self.stats_db = stats_db
        self.audio = audio
        self.game = None
        self._on_change = on_change

        mqtt_pub.subscribe(f"{base_topic}/elimination/command", self._handle_command)
        mqtt_pub.client.publish(
            f"{base_topic}/elimination/active", "false", retain=True
        )
        b = f"{base_topic}/elimination/last_turn"
        for i in range(1, 4):
            mqtt_pub.client.publish(f"{b}/dart{i}", "0", retain=True)
        mqtt_pub.client.publish(f"{b}/total", "0", retain=True)
        self._publish_known_players()

    @property
    def active(self):
        return self.game is not None and self.game.state == "playing"

    def on_board_state(self, count, throws):
        if self.game:
            self.game.on_board_state(count, throws)

    def start(self, players: list, lives: int):
        self.game = EliminationGame(
            players, lives, self.mqtt_pub.client, self.base_topic,
            audio=self.audio, on_change=self._on_change,
            stats_db=self.stats_db,
        )
        self.game.announce_start()

    def stop(self):
        self.game = None
        b = f"{self.base_topic}/elimination"
        self.mqtt_pub.client.publish(f"{b}/active", "false", retain=True)
        self.mqtt_pub.client.publish(f"{b}/state", "", retain=True)
        for i in range(1, 4):
            self.mqtt_pub.client.publish(f"{b}/current/dart{i}", "", retain=True)
            self.mqtt_pub.client.publish(f"{b}/last_turn/dart{i}", "", retain=True)
        self.mqtt_pub.client.publish(f"{b}/current/total", "", retain=True)
        self.mqtt_pub.client.publish(f"{b}/last_turn/total", "", retain=True)
        if self._on_change:
            self._on_change()
        log.info("Game stopped")

    def _handle_command(self, payload):
        try:
            cmd = json.loads(payload)
        except Exception:
            return
        action = cmd.get("action", "")

        if action == "start":
            players = [str(p) for p in cmd.get("players", []) if str(p).strip()]
            lives = max(1, int(cmd.get("lives", 3)))
            if len(players) >= 2:
                self.start(players, lives)

        elif action == "stop":
            self.stop()

        elif action == "correct_turn":
            new_total = int(cmd.get("total", 0))
            if self.game:
                self.game.correct_turn(new_total)

        elif action == "undo":
            if self.game:
                self.game.undo()

        elif action == "add_player":
            name = cmd.get("name", "").strip()
            if name:
                kp.add(name, self.stats_db)
                self._publish_known_players()

        elif action == "remove_player":
            # Kept the MQTT action name for wire-compatibility (e.g. existing
            # HA automations) — "remove" is now implemented as hiding, since
            # there's no more separate roster to remove someone from.
            name = cmd.get("name", "").strip()
            if name and self.stats_db:
                self.stats_db.upsert_player(name, hidden=True)
                self._publish_known_players()

    def _publish_known_players(self):
        players = kp.load(self.stats_db)
        self.mqtt_pub.client.publish(
            f"{self.base_topic}/elimination/known_players",
            json.dumps(players, ensure_ascii=False),
            retain=True,
        )
