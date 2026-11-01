"""X01 call logic on the translated GameState event stream, modeled on the
X01 calling of darts-caller. The call keys follow its voice-pack naming, so
its packs work unchanged.

In code stays the call of each dart. The rest of the X01 calls are the standard
scenes (scenes_default.py); this module tells them what the settings and the
checkout state allow (`turn_facts`, and the turn total switch).
"""

import logging

from breakfast.caller import AMBIENT_VOLUME_DEFAULT, ModeHandler

log = logging.getLogger(__name__)

# Scores <=170 you cannot check out with 3 darts.
BOGEY_NUMBERS = {159, 162, 163, 165, 166, 168, 169}


class X01Caller(ModeHandler):
    def __init__(self, per_dart=True, turn_total=True, checkout_limit=1,
                 announce_change=True, call_player=True,
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
        log.debug("on_dart: dart=%s field=%s remaining=%s", evt.get("dart"), evt.get("field"), remaining)

        # The winning dart is followed immediately by the won event —
        # skip the field call so gameshot/matchshot isn't queued behind it.
        if remaining == 0:
            return

        if self.per_dart:
            self._call_field(evt, audio)

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

    # ── turn end / player change ──────────────────────────────────────────────

    def turn_facts(self, snapshot, audio, announce):
        """The facts the standard scene of a turn start needs. `checkout`: 1 the checkout is called, 2 the remaining
        score is a bogey number, 3 it was called often enough, 0 nothing to call. `change`: the incoming player is called
        by name."""
        cur = snapshot.get("current") or {}
        remaining = cur.get("remaining")
        idx = snapshot.get("active_player_index")
        checkout = 0
        if self.checkout_limit and remaining is not None and 2 <= remaining <= 170:
            if remaining in BOGEY_NUMBERS:
                checkout = 2
            elif self._under_checkout_limit(idx, remaining):
                # Own namespace only — never fall back to the euphoric score number. Without the number the whole call
                # is skipped rather than ending on "you require".
                if audio and audio.has_audio("you_require") and audio.has_audio(f"require_{remaining}"):
                    checkout = 1
            else:
                checkout = 3
        change = self.announce_change and announce and len(snapshot.get("players") or {}) > 1
        return {"checkout": checkout, "change": 1 if change else 0}

    def _under_checkout_limit(self, idx, remaining):
        entry = self._checkout_counter.get(idx)
        if entry is None or entry[0] != remaining:
            self._checkout_counter[idx] = [remaining, 1]
            return True
        entry[1] += 1
        return entry[1] <= self.checkout_limit
