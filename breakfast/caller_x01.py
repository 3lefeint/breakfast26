"""X01 call logic on the translated GameState event stream, modeled on the
X01 calling of darts-caller. The call keys follow its voice-pack naming, so
its packs work unchanged.

Trigger mapping:
- dart event        -> per-dart field call; turn total after the 3rd dart
- turn_end event    -> checkout call ("you require") for the incoming player
                       (the translator's darts-pulled already carries the
                       next player + their remaining), bogey numbers,
                       player-change announce/ambient
- bust / won / legs -> handled by the shared Caller lifecycle
"""

import logging

from breakfast.caller import AMBIENT_VOLUME_DEFAULT, ModeHandler

log = logging.getLogger(__name__)

# Scores <=170 you cannot check out with 3 darts.
BOGEY_NUMBERS = {159, 162, 163, 165, 166, 168, 169}


class X01Caller(ModeHandler):
    def __init__(self, per_dart=True, turn_total=True, checkout_limit=1,
                 announce_change=False, call_player=True,
                 ambient_volume=AMBIENT_VOLUME_DEFAULT, call_misses=True):
        """checkout_limit: how often the *same* remaining score is announced
        per player before going silent (0 disables checkout calls).
        announce_change: call the incoming player's name on every player
        change, even without a possible checkout.
        call_misses: announce "outside" on a missed dart; independent of
        per_dart so hit calls can stay on with miss calls silenced."""
        self.per_dart = per_dart
        self.turn_total = turn_total
        self.checkout_limit = checkout_limit
        self.announce_change = announce_change
        self.call_player = call_player
        self.ambient_volume = ambient_volume
        self.call_misses = call_misses
        self._checkout_counter = {}   # player_index -> [remaining, count]

    def on_match_start(self, snapshot):
        self._checkout_counter.clear()

    # ── per dart ──────────────────────────────────────────────────────────────

    def on_dart(self, evt, snapshot, audio):
        cur = snapshot.get("current") or {}
        remaining = cur.get("remaining")

        # The winning dart is followed immediately by the won event —
        # skip the field call so gameshot/matchshot isn't queued behind it.
        if remaining == 0:
            return

        if self.per_dart:
            self._call_field(evt, audio)

        if evt.get("dart") == 3 and self.turn_total:
            total = cur.get("turn_score") or 0
            audio.play(str(total))
            self._ambient_turn_ladder(cur, total, audio)

    def _call_field(self, evt, audio):
        number = evt.get("number")
        multiplier = evt.get("multiplier")

        if (evt.get("miss") or multiplier == 0) and not self.call_misses:
            return

        if number == 25 and multiplier == 2:
            key = "bullseye"
        elif number == 25:
            key = "bull"
        else:
            key = str(evt.get("field") or "").lower()

        if key and audio.play(key, break_last=True):
            return

        # Fallbacks per field type (original SINGLE-DART-NAME behavior):
        # singles announce the number, misses announce "outside",
        # double/triple announce the type then the number.
        if evt.get("miss") or multiplier == 0:
            audio.play("outside", break_last=True)
        elif multiplier == 1:
            audio.play(str(number), break_last=True)
        else:
            type_key = "double" if multiplier == 2 else "triple"
            if audio.play(type_key, break_last=True):
                audio.play(str(number))

    def _ambient_turn_ladder(self, cur, total, audio):
        if not self.ambient_volume:
            return
        vol = self.ambient_volume
        if total > 0:
            combo = "".join(str(cur.get(f"throw{i}_raw") or "").lower()
                            for i in (1, 2, 3))
            if combo and audio.play(f"ambient_{combo}", volume=vol):
                return
            if audio.play(f"ambient_{total}", volume=vol):
                return
            for threshold in (150, 120, 100, 50, 1):
                if total >= threshold:
                    audio.play(f"ambient_{threshold}more", volume=vol)
                    return
        else:
            audio.play("ambient_noscore", volume=vol)

    # ── turn end / player change ──────────────────────────────────────────────

    def on_turn_end(self, evt, snapshot, audio):
        cur = snapshot.get("current") or {}
        remaining = cur.get("remaining")
        idx = snapshot.get("active_player_index")
        called = False
        log.debug("on_turn_end: idx=%s remaining=%s checkout_limit=%s announce_change=%s "
                  "ambient_volume=%s players=%d",
                  idx, remaining, self.checkout_limit, self.announce_change,
                  self.ambient_volume, len(snapshot.get("players") or {}))

        with audio.batch():
            if self.checkout_limit and remaining is not None and 2 <= remaining <= 170:
                if remaining in BOGEY_NUMBERS:
                    if self.ambient_volume:
                        if not audio.play(f"ambient_bogey_number_{remaining}",
                                          volume=self.ambient_volume):
                            audio.play("ambient_bogey_number", volume=self.ambient_volume)
                elif self._under_checkout_limit(idx, remaining):
                    if self.call_player:
                        self._announce_player(snapshot, audio)
                    if audio.play("you_require"):
                        # Own namespace only — never fall back to the euphoric
                        # score number.
                        audio.play(f"require_{remaining}")
                        called = True
                elif self.ambient_volume:
                    audio.play("ambient_checkout_call_limit", volume=self.ambient_volume)

            if not called and self.announce_change and len(snapshot.get("players") or {}) > 1:
                self._announce_player(snapshot, audio)

            if not called and self.ambient_volume:
                name = snapshot.get("active_player_name")
                player = str(name).lower() if name else None
                if not (player and audio.play(f"ambient_playerchange_{player}",
                                              volume=self.ambient_volume)):
                    audio.play("ambient_playerchange", volume=self.ambient_volume)

        log.debug("on_turn_end done: called=%s announce_change_fired=%s",
                  called, not called and self.announce_change and len(snapshot.get("players") or {}) > 1)

    def _under_checkout_limit(self, idx, remaining):
        entry = self._checkout_counter.get(idx)
        if entry is None or entry[0] != remaining:
            self._checkout_counter[idx] = [remaining, 1]
            return True
        entry[1] += 1
        return entry[1] <= self.checkout_limit

    @staticmethod
    def _announce_player(snapshot, audio):
        name = snapshot.get("active_player_name")
        if name and audio.play(str(name).lower()):
            return
        audio.play("unknown_player")
