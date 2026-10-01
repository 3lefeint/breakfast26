"""Darts currently on the board, as read from the local board stream.

The board manager reports every dart of the turn in progress together with
its segment and position (`coords`: unit = outer edge of the double ring, x to
the right, y up). This keeps that list independent of the game mode, so X01,
Elimination and Freeplay all show the same thing.
"""

import threading

from breakfast.autodarts_client import _FIELD_COORDS

_MULTIPLIER = {"S": 1, "D": 2, "T": 3}


def _dart(throw):
    """One dart as {field, points, x, y}; x and y are None if the position is unknown."""
    segment = throw.get("segment") or {}
    field = segment.get("name")
    points = (segment.get("number") or 0) * (segment.get("multiplier") or 0)
    coords = throw.get("coords")
    if not (isinstance(coords, dict) and "x" in coords and "y" in coords):
        # No coordinates delivered: fall back to the center of the field.
        coords = _FIELD_COORDS.get(field) or {}
    return {"field": field, "points": points, "x": coords.get("x"), "y": coords.get("y")}


def _field_points(field):
    """Points of a field name like `T20`, `D16`, `S5`, `25`, `50` or `0`."""
    if field in ("25", "50"):
        return int(field)
    if field[:1] in _MULTIPLIER and field[1:].isdigit():
        return _MULTIPLIER[field[0]] * int(field[1:])
    return 0


class BoardDarts:
    def __init__(self):
        self._lock = threading.Lock()
        self._connected = False
        self._darts = []       # one entry per dart on the board
        self._overrides = {}   # dart index -> dart set by a correction
        self._shown = []

    def set_connected(self, connected) -> bool:
        """Returns True if the connection state changed."""
        with self._lock:
            if self._connected == connected:
                return False
            self._connected = connected
            if not connected:
                self._darts, self._overrides = [], {}
            self._shown = self._merge()
            return True

    def update(self, throws) -> bool:
        """Takes the board's `throws` list. Returns True if what is shown changed."""
        with self._lock:
            self._darts = [_dart(t) for t in throws]
            self._overrides = {i: d for i, d in self._overrides.items() if i < len(self._darts)}
            return self._refresh()

    def override(self, index, field) -> bool:
        """Moves a dart to the center of a corrected field. Returns True if it changed."""
        field = field.upper()
        center = _FIELD_COORDS.get(field)
        with self._lock:
            if center is None or not 0 <= index < len(self._darts):
                return False
            self._overrides[index] = {
                "field": field, "points": _field_points(field), "x": center["x"], "y": center["y"]}
            return self._refresh()

    def snapshot(self):
        """List of {n, field, points, x, y}, or None while the board stream is not connected."""
        with self._lock:
            return list(self._shown) if self._connected else None

    def _merge(self):
        return [{"n": i + 1, **self._overrides.get(i, d)} for i, d in enumerate(self._darts)]

    def _refresh(self):
        shown = self._merge()
        changed = shown != self._shown
        self._shown = shown
        return changed
