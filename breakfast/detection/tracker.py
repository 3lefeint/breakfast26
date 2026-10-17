"""The state of the board over time, from the pictures of the cameras.

Rules (all thresholds are in `Settings` and tuned at the board):
* The board is *moving* while the pictures change from one to the next (a hand, a flying dart, a wobbling dart). When it has
  been still for `settle_s`, it is *settled* and compared with the picture after the last settled state (`ref`).
* A new dart: the settled picture differs from `ref` and `locate` finds the new tip. The dart count goes up, `ref` is the settled
  picture.
* The darts were taken out: darts were counted, and the settled picture equals the picture of the empty board.
* No change: `ref` follows the picture slowly, so light changes do not pile up as differences.
The first settled picture after the start is taken as the empty board.
"""
import logging
import time
from dataclasses import dataclass, field

import cv2
import numpy as np

from breakfast.detection import detector

log = logging.getLogger(__name__)


@dataclass
class Settings:
    settle_s: float = 0.35          # how long the board must be still before it is looked at
    motion_pixel: int = 16          # gray-level difference between two pictures that counts as moving
    motion_fraction: float = 0.002  # share of the pixels in the board region that must move
    min_cams: int = 2               # cameras that must see a new dart
    min_area: int = detector.MIN_AREA
    max_area: int = 13000           # a changed blob bigger than this in two cameras (or twice as big in one) is a hand or an arm
    support: float = 0.10           # share of changed pixels around a counted dart (against the empty board) below which it is gone
    same_spot_mm: float = 10.0      # a new dart this close to a counted one may be that dart, pushed by a bounce-out ...
    new_body_ratio: float = 1.15    # ... unless the picture around it has this much more changed than when it was counted (real darts: 1.4 to 2.5)
    patience: int = 40              # looks (about 0.3 s apart) at a blocked board before the picture is taken as it is
    retry_s: float = 1.0            # when a change could not be explained, look again after this long


@dataclass
class Event:
    kind: str                       # "dart", "takeout", "unclear", "empty", "baseline"
    t: float
    count: int                      # darts on the board after the event
    throw: dict | None = None       # the dart as the board manager reports it
    info: dict = field(default_factory=dict)
    before: dict | None = None      # pictures (camera -> BGR), for the log of events
    after: dict | None = None


class BoardTracker:
    def __init__(self, model, settings=None):
        self.model = model
        self.s = settings or Settings()
        self.count = 0
        self.throws = []
        self.sup0 = []              # per counted dart: its support in every camera when it was counted (see `_pushed`)
        self.ref = None             # camera -> prepared picture after the last settled state
        self.empty = None           # camera -> prepared picture of the empty board
        self.empty_hp = None        # the same, high-pass filtered (see `detector.highpass`)
        self.ref_raw = None
        self._prev = None           # camera -> small gray picture of the previous call
        self._still_since = None
        self._handled = True        # the current still period has been looked at
        self._retry_at = 0.0
        self.moving = False
        self._unclear = 0           # changes in a row that could not be explained
        self._blocked = 0           # looks in a row at a board that something is in the way of
        self.status = "starting"
        small = {c: cv2.resize(m, None, fx=0.25, fy=0.25, interpolation=cv2.INTER_NEAREST) > 0 for c, m in model.masks.items()}
        self._small_mask = small

    # ------------------------------------------------------------------ helpers

    def _small(self, frame, cam):
        g = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        return cv2.GaussianBlur(cv2.resize(g, None, fx=0.25, fy=0.25, interpolation=cv2.INTER_AREA), (3, 3), 0)

    def _motion(self, small):
        if self._prev is None:
            return 1.0
        frac = 0.0
        for c, img in small.items():
            m = self._small_mask[c]
            moved = (cv2.absdiff(img, self._prev[c]) > self.s.motion_pixel) & m
            frac = max(frac, float(moved.sum()) / max(1, int(m.sum())))
        return frac

    def reset(self):
        """Take the next settled picture as the empty board again (and forget the darts)."""
        self.count, self.throws, self.sup0, self.ref, self.empty, self.empty_hp, self.ref_raw = 0, [], [], None, None, None, None
        self._handled = False

    # ------------------------------------------------------------------ main step

    def feed(self, t, frames):
        """One set of pictures (camera -> BGR). Returns the events it caused."""
        small = {c: self._small(f, c) for c, f in frames.items()}
        frac = self._motion(small)
        self._prev = small
        if frac > self.s.motion_fraction:
            self._still_since, self._handled, self.moving = None, False, True
            return []
        self.moving = False
        if self._still_since is None:
            self._still_since = t
        if self._handled or t - self._still_since < self.s.settle_s or t < self._retry_at:
            return []
        return self._settled(t, frames)

    def _settled(self, t, frames):
        prepared = {c: detector.prepare(f) for c, f in frames.items()}
        if self.ref is None:
            self.ref, self.empty, self.ref_raw = prepared, prepared, frames
            self.empty_hp = {c: detector.highpass(p) for c, p in prepared.items()}
            self._handled = True
            self.status = "ready"
            return [Event("baseline", t, 0, info={"note": "empty board taken"})]
        hp = {c: detector.highpass(p) for c, p in prepared.items()}
        if self.count:                                      # the darts were taken out (checked first: three darts that go are a big change)
            gone = {c: detector.changed_area(self.model.masks[c], self.empty_hp[c], hp[c]) for c in prepared}
            if self._is_empty(gone):
                return self._takeout(t, frames, prepared)
        changed = {c: detector.changed_area(self.model.masks[c], self.ref[c], prepared[c]) for c in prepared}
        if max(changed.values()) > 2 * self.s.max_area or sum(1 for a in changed.values() if a > self.s.max_area) >= 2:
            return self._blocked_board(t, frames, prepared, {"changed": changed, "why": "big change: a hand or an arm"})
        self._blocked = 0
        seen = [c for c, a in changed.items() if a >= self.s.min_area]
        if not seen:
            # nothing new: follow the light, and notice that the board is empty again
            self.ref, self.ref_raw = prepared, frames
            if self.count == 0:
                self.empty = prepared
                self.empty_hp = {c: detector.highpass(p) for c, p in prepared.items()}
            self._handled = True
            return self._drop_unsupported(t, frames, prepared)     # nothing new: check that every counted dart is still there
        result = detector.locate(self.model, self.ref, prepared, min_cams=self.s.min_cams)
        if result is None:
            return self._unclear_change(t, frames, prepared, {"changed": changed})
        if result["cams"] >= 2 and result["agree"] < 2:
            return self._blocked_board(t, frames, prepared, {"changed": changed, "spread": round(result["spread"], 1),
                                                             "why": "the cameras disagree: a hand or an arm"})
        shares = [detector.appeared(self.model.masks[c], self.ref[c], self.empty_hp[c], hp[c], ref_hp=detector.highpass(self.ref[c])) for c in seen]
        if self.count and float(np.median(shares)) < 0.5:
            return self._removed(t, frames, prepared, result, shares)
        self._unclear = 0
        near = self._pushed(result, hp)
        if near is not None:
            self.ref, self.ref_raw = prepared, frames
            self._handled = True
            return [Event("moved", t, self.count, info={"field": self.throws[near]["segment"]["name"], "now": result["field"]}, before=None, after=frames)]
        throw = detector.to_throw(result)
        self.count += 1
        self.throws.append(throw)
        self.sup0.append(self._support_of(result["x"], result["y"], hp))
        before, self.ref, self.ref_raw = self.ref_raw, prepared, frames
        self._handled = True
        self.status = "takeout" if self.count >= 3 else "ready"
        return [Event("dart", t, self.count, throw=throw, info={**result, "changed": changed}, before=before, after=frames)]

    def _support_of(self, x_mm, y_mm, hp):
        h, w = self.model.size[1], self.model.size[0]
        return {c: detector.support((h, w), self.model, c, x_mm, y_mm, self.empty_hp[c], hp[c]) for c in self.model.cams}

    def _pushed(self, result, hp):
        """Index of the counted dart that the new change is only a push of (a bounce-out nudged it), or None. A new dart close to a counted
        one adds a body to the picture around it (more changed pixels than when that dart was counted); a pushed dart does not."""
        for i, th in enumerate(self.throws):
            x, y = th["coords"]["x"] * 170.0, th["coords"]["y"] * 170.0
            if ((x - result["x"]) ** 2 + (y - result["y"]) ** 2) ** 0.5 > self.s.same_spot_mm:
                continue
            now = self._support_of(x, y, hp)
            ratios = sorted(now[c] / max(self.sup0[i][c], 0.05) for c in now)
            if ratios[len(ratios) // 2] < self.s.new_body_ratio:
                return i
        return None

    def _removed(self, t, frames, prepared, result, shares):
        """A change that is no new dart: a dart was pulled out (or fell out). The nearest counted dart goes."""
        pos = (result["x"], result["y"])
        near = None
        for i, th in enumerate(self.throws):
            d = ((th["coords"]["x"] * 170.0 - pos[0]) ** 2 + (th["coords"]["y"] * 170.0 - pos[1]) ** 2) ** 0.5
            if d <= 15.0 and (near is None or d < near[1]):
                near = (i, d)
        if near is None:
            return self._unclear_change(t, frames, prepared, {"removed_share": shares, "pos": pos})
        gone = self.throws.pop(near[0])
        self.sup0.pop(near[0])
        self.count -= 1
        self.ref, self.ref_raw = prepared, frames
        self._handled = True
        if self.count == 0:
            self.empty = prepared
            self.empty_hp = {c: detector.highpass(p) for c, p in prepared.items()}
            self.status = "ready"
        return [Event("removed", t, self.count, info={"field": gone["segment"]["name"], "left": self.count}, after=frames)]

    def _blocked_board(self, t, frames, prepared, info):
        """Something is in the way (a hand, an arm): wait and look again, `ref` stays. After `patience` looks the picture is taken as
        it is, so a lasting change (a lamp, a moved camera) does not block the board for good."""
        self._blocked += 1
        self.status = "blocked"
        self._handled = False
        self._retry_at = t + 0.3
        if self._blocked >= self.s.patience:
            self._blocked = 0
            self.ref, self.ref_raw = prepared, frames
            self._handled = True
            return [Event("unclear", t, self.count, info={**info, "accepted": True, "why": "blocked for a long time"}, before=None, after=frames)]
        return []

    def _drop_unsupported(self, t, frames, prepared):
        """Counted darts that are not on the board any more (a phantom, a dart that fell out or was pulled): checked against the empty
        board in every camera. Returns the events of the darts that went."""
        if not self.count:
            return []
        hp = {c: detector.highpass(p) for c, p in prepared.items()}
        h, w = self.model.size[1], self.model.size[0]
        keep, keep_sup, events = [], [], []
        for th, sup in zip(self.throws, self.sup0):
            x, y = th["coords"]["x"] * 170.0, th["coords"]["y"] * 170.0
            votes = sum(1 for c in self.model.cams
                        if detector.support((h, w), self.model, c, x, y, self.empty_hp[c], hp[c]) >= self.s.support)
            if votes >= min(2, len(self.model.cams)):
                keep.append(th)
                keep_sup.append(sup)
            else:
                events.append(th)
        if not events:
            return []
        self.throws, self.sup0 = keep, keep_sup
        self.count = len(keep)
        self.ref, self.ref_raw = prepared, frames           # the picture as it is now: the missing darts are no new change
        self._handled = True
        self.status = "takeout" if self.count >= 3 else "ready"
        if self.count == 0:
            self.empty, self.empty_hp = prepared, hp
            self.status = "ready"
            return [Event("takeout", t, 0, info={"darts_removed": len(events)}, after=frames)]
        return [Event("removed", t, self.count, info={"field": th["segment"]["name"], "left": self.count, "why": "no longer on the board"}, after=frames)
                for th in events]

    def _unclear_change(self, t, frames, prepared, info):
        """A change nobody can explain (a hand, a bounce, a lost dart). Look again a moment later; after three times the picture
        is taken as it is (the count stays) so the same change is not reported again and again."""
        self._unclear += 1
        before = self.ref_raw
        if self._unclear >= 3:
            self._unclear = 0
            self.ref, self.ref_raw = prepared, frames
            self._handled = True
            info = {**info, "accepted": True}
        else:
            self._handled = False
            self._retry_at = t + self.s.retry_s
        return [Event("unclear", t, self.count, info=info, before=before, after=frames)]

    def _is_empty(self, gone):
        """The board looks like the empty one: all but at most one camera see no difference (one camera may see a reflection or a
        shadow)."""
        quiet = sum(1 for a in gone.values() if a < self.s.min_area)
        return quiet >= max(1, len(gone) - 1)

    def _takeout(self, t, frames, prepared):
        n = self.count
        self.count, self.throws, self.sup0 = 0, [], []
        self.ref, self.ref_raw, self.empty = prepared, frames, prepared
        self.empty_hp = {c: detector.highpass(p) for c, p in prepared.items()}
        self._handled = True
        self.status = "ready"
        return [Event("takeout", t, 0, info={"darts_removed": n}, after=frames)]
