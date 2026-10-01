"""Darts currently on the board, as read from the local board stream.

The board manager reports every dart of the turn in progress together with
its position (`coords`: unit = outer edge of the double ring, x to the right,
y up). This keeps that list independent of the game mode, so X01, Elimination
and Freeplay all show the same thing.
"""

import threading

from breakfast.autodarts_client import _FIELD_COORDS


def _position(throw):
    coords = throw.get("coords")
    if isinstance(coords, dict) and "x" in coords and "y" in coords:
        return {"x": coords["x"], "y": coords["y"]}
    # No coordinates delivered: fall back to the center of the field.
    center = _FIELD_COORDS.get((throw.get("segment") or {}).get("name"))
    return dict(center) if center else None


class BoardDarts:
    def __init__(self):
        self._lock = threading.Lock()
        self._connected = False
        self._positions = []   # one entry per dart on the board, None if unknown
        self._overrides = {}   # dart index -> position set by a correction
        self._shown = []

    def set_connected(self, connected) -> bool:
        """Returns True if the connection state changed."""
        with self._lock:
            if self._connected == connected:
                return False
            self._connected = connected
            if not connected:
                self._positions, self._overrides = [], {}
            self._shown = self._merge()
            return True

    def update(self, throws) -> bool:
        """Takes the board's `throws` list. Returns True if what is shown changed."""
        with self._lock:
            self._positions = [_position(t) for t in throws]
            if not self._positions:
                self._overrides = {}
            else:
                self._overrides = {i: p for i, p in self._overrides.items() if i < len(self._positions)}
            return self._refresh()

    def override(self, index, field) -> bool:
        """Moves a dart to the center of a corrected field. Returns True if it changed."""
        center = _FIELD_COORDS.get(field.upper())
        with self._lock:
            if center is None or not 0 <= index < len(self._positions):
                return False
            self._overrides[index] = dict(center)
            return self._refresh()

    def snapshot(self):
        """List of {n, x, y}, or None while the board stream is not connected."""
        with self._lock:
            return list(self._shown) if self._connected else None

    def _merge(self):
        merged = []
        for i, pos in enumerate(self._positions):
            pos = self._overrides.get(i, pos)
            if pos is not None:
                merged.append({"n": i + 1, "x": pos["x"], "y": pos["y"]})
        return merged

    def _refresh(self):
        shown = self._merge()
        changed = shown != self._shown
        self._shown = shown
        return changed
