"""Standard dartboard geometry and the center of every field.

Coordinates follow the Autodarts convention: the unit is the outer edge of the
double ring, x points right and y points up, the 20 is at the top.
"""

import math

# Ring radii in millimetres from the center.
BULL_MM = 6.35
OUTER_BULL_MM = 15.9
TRIPLE_IN_MM = 99
TRIPLE_OUT_MM = 107
DOUBLE_IN_MM = 162
DOUBLE_OUT_MM = 170

# Clockwise from the top.
SEGMENT_ORDER = (20, 1, 18, 4, 13, 6, 10, 15, 2, 17, 3, 19, 7, 16, 8, 11, 14, 9, 12, 5)

# Where a miss lands: just beyond the double ring at the top.
MISS_POINT = {"x": 0.0, "y": 1.1}


def _point(radius_mm: float, degrees: float) -> dict:
    """A point `radius_mm` from the center, `degrees` clockwise from the top."""
    r = radius_mm / DOUBLE_OUT_MM
    a = math.radians(degrees)
    return {"x": r * math.sin(a), "y": r * math.cos(a)}


def field_centers() -> dict:
    """Field name (`S20`, `D16`, `T19`, `25`, `50`, `0`) -> center point."""
    centers = {"0": dict(MISS_POINT), "50": {"x": 0.0, "y": 0.0},
               "25": _point((BULL_MM + OUTER_BULL_MM) / 2, 0)}
    for i, n in enumerate(SEGMENT_ORDER):
        degrees = i * 18
        centers[f"S{n}"] = _point((TRIPLE_OUT_MM + DOUBLE_IN_MM) / 2, degrees)
        centers[f"T{n}"] = _point((TRIPLE_IN_MM + TRIPLE_OUT_MM) / 2, degrees)
        centers[f"D{n}"] = _point((DOUBLE_IN_MM + DOUBLE_OUT_MM) / 2, degrees)
    return centers
