import hashlib
import json
import logging
import threading

from .turn_game import TurnGame, TurnGameController, dart_positions

log = logging.getLogger(__name__)

# Give the browser time to redirect to /tv and reconnect its WebSocket with
# role=audio before the opening calls fire — a fresh game (the frontend's
# elimStart()/startRematch() redirect) POSTs, then immediately navigates,
# so the old page's audio-role connection is already gone and the new one
# hasn't registered yet by the time this would otherwise fire synchronously.
# Sound instructions are a live, ephemeral broadcast (unlike state, which
# new connections get a fresh payload on connect), so anything sent into that
# gap is lost for good rather than merely delayed.
_START_ANNOUNCE_AUDIO_DELAY_S = 0.5


class EliminationGame(TurnGame):
    MODE = "Elimination"
    TOPIC = "elimination"

    def __init__(self, players, lives_count, client, base_topic, audio=None, on_change=None,
                 stats_db=None, match_id=None, online=None, local_players=None):
        # Elimination has no externally-supplied match id like X01's Autodarts
        # event id, so the base mints its own to give stats.db a matches/turns key
        # (an online match gets the one the relay assigned).
        super().__init__(client, base_topic, audio=audio, on_change=on_change,
                         stats_db=stats_db, match_id=match_id)
        self.lives_max = lives_count
        self.order = list(players)
        self.lives = {p: lives_count for p in players}
        self.active = list(players)
        self.current_idx = 0
        self.target = 0
        self.freipass = True  # first player only needs > 0
        self.winner = None
        self.elimination_order = []  # names in the order they were eliminated
        # Online play (see online.py): `online` sends this site's darts, turns and
        # state hashes to the relay, `local_players` are the players whose turns
        # are thrown at this site's board; None means every player is local.
        self.online = online
        self.local_players = set(local_players) if local_players is not None else None
        self.turn_seq = 0          # finished turns of this match, local and remote
        self._remote = False       # True while a remote turn is being replayed
        self._outcome_published = False
        self._preview_fired = False
        if self.stats_db:
            self.stats_db.open_match(self.match_id, self.MODE, lives_count)
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

    @property
    def current_player(self):
        if not self.active or self.current_idx >= len(self.active):
            return None
        return self.active[self.current_idx]

    def snapshot(self) -> dict:
        cp = self.current_player
        last_darts = [self.value_of(t) for t in self._last_throws] if self._last_throws else []
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

    def _dart_seen(self, count, is_new_dart, is_correction):
        if self.online and not self._remote:
            self.online.send_dart(self.turn_seq + 1, self.current_player, self._last_throws)
        if is_new_dart and self.audio and not self._remote:
            # Miss comment on any dart
            latest = self._current_darts[count - 1] if count <= len(self._current_darts) else 0
            if latest == 0:
                self.audio.play("miss", prob=0.35)
        if count == 3 and is_new_dart:
            self._publish_turn_preview()

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
                    eliminated_before = len(self.elimination_order)
                    self._finish_match(player, score)
                    self._after_turn(player, list(self._last_throws), eliminated_before)
                    return
                self._outcome_published = True
                if self.audio:
                    if event == "eliminated":
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
        self._record_result()
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

    def _record_result(self):
        """Store who won and how everybody placed, once the match is over."""
        if not self.stats_db:
            return
        placements = []
        if self.winner:
            placements.append((self.winner, 1, self.lives[self.winner]))
        placements += [
            (name, i + 2 if self.winner else i + 1, None)
            for i, name in enumerate(reversed(self.elimination_order))
        ]
        self.stats_db.record_elimination_result(self.match_id, placements)
        self.stats_db.set_winner(self.match_id, self.winner)
        self.stats_db.close_match(self.match_id)

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

    def _end_turn(self):
        player = self.current_player
        score = sum(self.value_of(t) for t in self._last_throws)
        throws = list(self._last_throws)
        eliminated_before = len(self.elimination_order)
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
        self._after_turn(player, throws, eliminated_before)

    def _after_turn(self, player, throws, eliminated_before):
        """A turn is done and applied. Online: a turn thrown here goes to the relay as
        the authoritative record, and either way the relay learns this site's state hash."""
        self.turn_seq += 1
        if not self.online:
            return
        if not self._remote:
            finished = self.state == "finished"
            self.online.send_turn(
                self.turn_seq, player, throws,
                next_player=None if finished else self.current_player,
                eliminated=list(self.elimination_order[eliminated_before:]),
                winner=self.winner if finished else None)
        self.online.send_ack(self.turn_seq, self.state_hash())

    def state_hash(self):
        """A short digest of everything that decides how the match goes on, equal on all
        sites that applied the same turns."""
        state = {
            "seq": self.turn_seq, "lives": self.lives, "active": self.active,
            "current": self.current_player, "target": self.target, "freipass": self.freipass,
            "state": self.state, "winner": self.winner, "eliminated": self.elimination_order,
        }
        return hashlib.sha256(json.dumps(state, sort_keys=True).encode()).hexdigest()[:16]

    def is_local(self, player):
        return self.local_players is None or player in self.local_players

    # ── online: what comes in from the relay ─────────────────────────────────────

    def remote_dart(self, player, throws):
        """The darts of a remote player's turn in progress, shown like local ones."""
        if self.state != "playing" or player != self.current_player or not throws:
            return
        self._replay(throws)

    def remote_turn(self, player, throws):
        """A remote player's finished turn: replay it through the same code a local turn
        runs through, so scores, calls, stats and the next player come out identical."""
        if self.state != "playing":
            return
        if player != self.current_player:
            log.warning("Remote turn of %s while %s is up", player, self.current_player)
            return
        self._replay(throws, pull=True)

    def _replay(self, throws, pull=False):
        self._remote = True
        try:
            if throws:
                self.on_board_state(len(throws), list(throws))
            if pull:
                self.on_board_state(0, [])
        finally:
            self._remote = False

    def drop_players(self, names, next_player):
        """The host chose to play on without a site: its players are out, in this order."""
        if self.state != "playing":
            return
        was_current = self.current_player in names
        for name in names:
            if name in self.active:
                self.active.remove(name)
                self.lives[name] = 0
                self.elimination_order.append(name)
        self._current_darts = []
        self._last_throws = []
        self._dart_overrides = {}
        self._prev_count = 0
        if len(self.active) <= 1:
            self.winner = self.active[0] if self.active else None
            self.state = "finished"
            self.current_idx = 0
            self._record_result()
        else:
            self.current_idx = self.active.index(next_player) if next_player in self.active else 0
            if was_current:
                self.freipass = True
        self._publish_state()
        self._publish_turn(reset=True)
        log.info("Dropped players %s, up next: %s", names, self.current_player)

    def apply_placements(self, placements):
        """The relay's result is the one every site stores."""
        if self.stats_db and placements:
            self.stats_db.replace_elimination_results(self.match_id, [
                (x["player"], x["placement"], self.lives.get(x["player"]) if x["placement"] == 1 else None)
                for x in placements])

    def _record_turn(self, player, score, darts_count):
        """Write a finished turn to the stats DB together with what it had to
        beat. Must run before _apply_turn() moves the target on."""
        if not self.stats_db:
            return
        to_beat = 0 if self.freipass else self.target
        self.stats_db.insert_elimination_turn(
            self.match_id, player, darts_count, score=score, target=to_beat,
            freipass=self.freipass, passed=score > to_beat, lives_before=self.lives[player],
            positions=dart_positions(self._last_throws))

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
        if self.online:
            log.warning("Correcting a finished turn is not available in an online match yet")
            return
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
        """Walk back the most recently completed turn, see TurnGame.undo(). Not available
        in an online match yet."""
        if self.online:
            log.warning("Undo is not available in an online match yet")
            return False
        return super().undo()

    def _restore(self, snap):
        self.lives = dict(snap["lives"])
        self.active = list(snap["active"])
        self.current_idx = snap["current_idx"]
        self.target = snap["target"]
        self.freipass = snap["freipass"]
        self.state = snap["state"]
        self.winner = snap["winner"]
        self.elimination_order = list(snap["elimination_order"])
        self._outcome_published = False
        self._preview_fired = False

    def _forget_stored_turn(self, snap, was_finished):
        if was_finished:
            self.stats_db.delete_elimination_results(self.match_id)
            self.stats_db.set_winner(self.match_id, None)
            self.stats_db.reopen_match(self.match_id)
        if snap["turn_recorded"]:
            self.stats_db.delete_last_elimination_turn(self.match_id, snap["player"])

    def correct_current_dart(self, dart_index, field):
        if self.online and not self.is_local(self.current_player):
            return      # a remote player's darts are corrected at their own site
        super().correct_current_dart(dart_index, field)

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

class EliminationController(TurnGameController):
    TOPIC = "elimination"

    def on_board_state(self, count, throws):
        with self._lock:
            game = self.game
            if not game:
                return
            if game.online and game.state == "playing" and (
                    not game.is_local(game.current_player) or not game.online.can_play()):
                return      # online: only the board of the site whose player is up counts
            game.on_board_state(count, throws)

    def start_online(self, order, lives, match_id, local_players, online):
        """The host started an online match: every player in `order` plays, the ones in
        `local_players` at this site's board."""
        with self._lock:
            self.game = EliminationGame(
                order, lives, self.mqtt_pub.client, self.base_topic,
                audio=self.audio, on_change=self._on_change, stats_db=self.stats_db,
                match_id=match_id, online=online, local_players=local_players,
            )
            self.game.announce_start()

    def remote_dart(self, player, throws):
        with self._lock:
            if self.game:
                self.game.remote_dart(player, throws)

    def remote_turn(self, player, throws):
        with self._lock:
            if self.game:
                self.game.remote_turn(player, throws)

    def drop_players(self, names, next_player):
        with self._lock:
            if self.game:
                self.game.drop_players(names, next_player)

    def apply_placements(self, placements):
        with self._lock:
            if self.game:
                self.game.apply_placements(placements)

    def start(self, players: list, lives: int):
        self.game = EliminationGame(
            players, lives, self.mqtt_pub.client, self.base_topic,
            audio=self.audio, on_change=self._on_change,
            stats_db=self.stats_db,
        )
        self.game.announce_start()

    def _command_start(self, cmd):
        players = [str(p) for p in cmd.get("players", []) if str(p).strip()]
        lives = max(1, int(cmd.get("lives", 3)))
        if len(players) >= 2:
            self.start(players, lives)
