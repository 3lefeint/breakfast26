"""The colors the players of a game get, so that their darts can be told apart on one board.

A player's own color (picked in the profile) is used as it is. Players without one get a color
from a palette, one that is not close to a color already in the game. Players whose colors are
the same or very close are told apart by a ring around the marker in a contrasting color.
"""

import random

PALETTE = ["#ef4444", "#f97316", "#facc15", "#22c55e", "#14b8a6",
           "#3b82f6", "#8b5cf6", "#ec4899", "#a3e635", "#06b6d4"]

# Two colors closer than this (distance in RGB, 0 to 441) count as the same on the board.
CLOSE = 80


def _rgb(color):
    return tuple(int(color[i:i + 2], 16) for i in (1, 3, 5))


def distance(a, b):
    return sum((x - y) ** 2 for x, y in zip(_rgb(a), _rgb(b))) ** 0.5


def _is_light(color):
    r, g, b = _rgb(color)
    return 0.299 * r + 0.587 * g + 0.114 * b > 140


def _ring(color, nth):
    """The ring of the `nth` player (1 for the first, 2 for the second ...) whose color is close to
    one before: white or black, whichever stands out, then the other one, then dashed."""
    contrast, other = ("#000000", "#ffffff") if _is_light(color) else ("#ffffff", "#000000")
    if nth == 1:
        return {"color": contrast, "dash": False}
    if nth == 2:
        return {"color": other, "dash": False}
    return {"color": contrast, "dash": True}


def assign_colors(players, chosen, rng=None):
    """{player: {"color": "#rrggbb", "ring": None or {"color", "dash"}}} for the players of a game.
    *chosen*: the colors players picked in their profile, by name."""
    rng = rng or random.Random()
    colors = {p: chosen[p] for p in players if chosen.get(p)}
    free = [c for c in PALETTE if all(distance(c, u) >= CLOSE for u in colors.values())]
    rng.shuffle(free)
    for p in players:
        if p in colors:
            continue
        if free:
            colors[p] = free.pop()
        else:
            colors[p] = "#{:02x}{:02x}{:02x}".format(*(rng.randrange(40, 230) for _ in range(3)))
        free = [c for c in free if distance(c, colors[p]) >= CLOSE]
    result = {}
    for i, p in enumerate(players):
        close_before = sum(1 for q in players[:i] if distance(colors[q], colors[p]) < CLOSE)
        result[p] = {"color": colors[p], "ring": _ring(colors[p], close_before) if close_before else None}
    return result
