"""Voice caller: turns GameState events into audio calls.

The Caller handles the mode-independent lifecycle vocabulary (match/leg
start, leg/match won, bust) and
delegates per-dart / turn logic to a ModeHandler registered per game mode
(caller_x01.py, caller_cricket.py).

Wireup (source_direct / source_replay):

    caller = Caller(audio)
    ...
    evt = state.update(data)
    caller.on_event(evt, state.snapshot())
"""

import logging

log = logging.getLogger(__name__)

AMBIENT_VOLUME_DEFAULT = 0.6


def from_config(audio, cfg=None):
    """Build a Caller with registered mode handlers from a `[caller]` config
    dict. Returns None when the caller is disabled."""
    from breakfast.caller_x01 import X01Caller

    cfg = cfg or {}
    if not cfg.get("enabled", True):
        return None
    call_player = bool(cfg.get("call_player", True))
    ambient = float(cfg.get("ambient_volume", AMBIENT_VOLUME_DEFAULT))
    caller = Caller(audio, call_player=call_player, ambient_volume=ambient)
    caller.register("X01", X01Caller(
        per_dart=bool(cfg.get("per_dart", True)),
        turn_total=bool(cfg.get("turn_total", True)),
        checkout_limit=int(cfg.get("checkout_limit", 1)),
        announce_change=bool(cfg.get("announce_change", True)),
        call_player=call_player,
        ambient_volume=ambient,
        call_misses=bool(cfg.get("call_misses", True)),
    ))
    return caller


class ModeHandler:
    """Per-game-mode call logic. Override in caller_x01 / caller_cricket."""

    def on_dart(self, evt, snapshot, audio):
        pass

    def on_turn_end(self, evt, snapshot, audio):
        pass

    def on_match_start(self, snapshot):
        """Reset any per-match state."""


class Caller:
    def __init__(self, audio, call_player=True, ambient_volume=AMBIENT_VOLUME_DEFAULT):
        self.audio = audio
        self.call_player = call_player
        self.ambient_volume = ambient_volume
        self._handlers = {}
        self._match_won_seen = False

    def register(self, mode_prefix, handler):
        """Attach a ModeHandler for game modes starting with *mode_prefix*
        (e.g. "X01" also covers X01-with-settings variants)."""
        self._handlers[mode_prefix.lower()] = handler

    # ── event entry point ─────────────────────────────────────────────────────

    def on_event(self, evt, snapshot):
        if not evt or not self.audio:
            return
        try:
            self._dispatch(evt, snapshot)
        except Exception:
            log.exception("Caller error on %s", evt.get("type"))

    def _dispatch(self, evt, snapshot):
        etype = evt.get("type")
        handler = self._handler_for(evt.get("mode") or snapshot.get("game_mode"))
        # Every audio-triggering event flows through here — one exhaustive
        # line per event, same pattern as state.py's update(), rather than
        # a log call in every branch below.
        log.debug("dispatch: type=%s mode=%s", etype, snapshot.get("game_mode"))

        if etype == "match_started":
            self._match_won_seen = False
            if handler:
                handler.on_match_start(snapshot)
            with self.audio.batch():
                self._announce_player(snapshot)
                if not self.audio.play("matchon"):
                    self.audio.play("gameon")
                self._ambient_chain(snapshot, "matchon", "gameon")

        elif etype == "game_started":
            # Leg start (never the first leg — translator suppresses that one)
            with self.audio.batch():
                self._announce_player(snapshot)
                self.audio.play("gameon")
                self._ambient_chain(snapshot, "gameon")

        elif etype == "won":
            self._match_won_seen = True
            if evt.get("scope") == "match":
                with self.audio.batch():
                    self._announce_player(snapshot)
                    if not self.audio.play("matchshot"):
                        self.audio.play("gameshot")
                    self._ambient_chain(snapshot, "matchshot", "gameshot")
            else:
                self._leg_won(snapshot)

        elif etype == "match_ended":
            # Fires when the match closes; only a cancellation deserves a call
            # (a won match was already announced via matchshot).
            if not self._match_won_seen:
                self.audio.play("matchcancel")
                self._ambient_chain(snapshot, "matchcancel")

        elif etype == "bust":
            self.audio.play("busted")
            if self.ambient_volume:
                self.audio.play("ambient_noscore", volume=self.ambient_volume)

        elif etype == "dart":
            if handler:
                handler.on_dart(evt, snapshot, self.audio)

        elif etype == "turn_end":
            if handler:
                handler.on_turn_end(evt, snapshot, self.audio)

    # ── shared call helpers ───────────────────────────────────────────────────

    def _handler_for(self, mode):
        if not mode:
            return None
        m = str(mode).lower()
        for prefix, handler in self._handlers.items():
            if m.startswith(prefix):
                return handler
        return None

    def _announce_player(self, snapshot):
        if not self.call_player:
            return
        name = snapshot.get("active_player_name")
        if name and self.audio.play(str(name).lower()):
            return
        self.audio.play("unknown_player")

    def _leg_won(self, snapshot):
        # state.py increments current_leg on game-won before we run,
        # so the leg just finished is current_leg - 1.
        leg = max(1, (snapshot.get("current_leg") or 2) - 1)
        with self.audio.batch():
            self._announce_player(snapshot)
            # Real-life style first ("gameshot leg N" as one recording, which
            # the own sound set has); plain gameshot + leg number as fallback
            # chain.
            if not self.audio.play(f"gameshot_l{leg}_n"):
                gameshot_played = self.audio.play("gameshot")
                self.audio.play(f"leg_{leg}")
                if not gameshot_played:
                    log.debug("No gameshot sound for leg %d", leg)
            self._ambient_chain(snapshot, "gameshot")

    def _ambient_chain(self, snapshot, *bases):
        """Ambient fallback: for each base, try the
        player-specific key first, then the generic one; stop at the first
        that plays."""
        if not self.ambient_volume:
            return
        name = snapshot.get("active_player_name")
        player = str(name).lower() if name else None
        for base in bases:
            if player and self.audio.play(f"ambient_{base}_{player}",
                                          volume=self.ambient_volume):
                return
            if self.audio.play(f"ambient_{base}", volume=self.ambient_volume):
                return
