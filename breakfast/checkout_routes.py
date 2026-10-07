"""Finishing routes for the checkout trainer: the standard route of every score that can be finished
with three darts, which first darts are valid, and what a rest allows.

A finish ends on a double, the bull's eye counts as a double (`50`). Fields are written like the
board reports them: `S20`, `D16`, `T19`, `25` (outer bull) and `50` (bull's eye).

`STANDARD` is the usual checkout chart of tournament players. Any other route that finishes is valid
too, the table only says which one is shown and taught first.
"""

import random

BULL = "50"
OUTER_BULL = "25"

# Scores no three darts can finish.
BOGEY = frozenset({159, 162, 163, 165, 166, 168, 169})

_CHART = """
2 D1;3 S1 D1;4 D2;5 S1 D2;6 D3;7 S3 D2;8 D4;9 S1 D4
10 D5;11 S3 D4;12 D6;13 S5 D4;14 D7;15 S7 D4;16 D8;17 S1 D8;18 D9;19 S3 D8
20 D10;21 S5 D8;22 D11;23 S7 D8;24 D12;25 S9 D8;26 D13;27 S11 D8;28 D14;29 S13 D8
30 D15;31 S15 D8;32 D16;33 S1 D16;34 D17;35 S3 D16;36 D18;37 S5 D16;38 D19;39 S7 D16
40 D20;41 S9 D16;42 S10 D16;43 S3 D20;44 S4 D20;45 S13 D16;46 S6 D20;47 S7 D20;48 S16 D16;49 S9 D20
50 50;51 S11 D20;52 S12 D20;53 S13 D20;54 S14 D20;55 S15 D20;56 S16 D20;57 S17 D20;58 S18 D20;59 S19 D20
60 S20 D20;61 T15 D8;62 T10 D16;63 T13 D12;64 T16 D8;65 25 D20;66 T10 D18;67 T17 D8;68 T20 D4;69 T19 D6
70 T10 D20;71 T13 D16;72 T16 D12;73 T19 D8;74 T14 D16;75 T17 D12;76 T20 D8;77 T19 D10;78 T18 D12;79 T19 D11
80 T20 D10;81 T19 D12;82 50 D16;83 T17 D16;84 T20 D12;85 T15 D20;86 T18 D16;87 T17 D18;88 T16 D20;89 T19 D16
90 T20 D15;91 T17 D20;92 T20 D16;93 T19 D18;94 T18 D20;95 T19 D19;96 T20 D18;97 T19 D20;98 T20 D19;99 T19 S10 D16
100 T20 D20;101 T17 50;102 T20 S10 D16;103 T19 S10 D18;104 T18 50;105 T20 S13 D16;106 T20 S14 D16;107 T19 50;108 T20 S16 D16;109 T20 S17 D16
110 T20 50;111 T20 S19 D16;112 T20 S12 D20;113 T19 S16 D20;114 T20 S14 D20;115 T20 S15 D20;116 T20 S16 D20;117 T20 S17 D20;118 T20 S18 D20;119 T19 S12 50
120 T20 S20 D20;121 T20 S11 50;122 T20 T10 D16;123 T19 50 D8;124 T20 S14 50;125 25 T20 D20;126 T20 50 D8;127 T20 T9 D20;128 T20 T12 D16;129 T20 T15 D12
130 T20 S20 50;131 T20 T13 D16;132 50 50 D16;133 T20 T11 D20;134 T20 T14 D16;135 T20 T17 D12;136 T20 T12 D20;137 T20 T15 D16;138 T20 T18 D12;139 T20 T13 D20
140 T20 T16 D16;141 T20 T19 D12;142 T20 T14 D20;143 T20 T17 D16;144 T18 50 D20;145 T20 T15 D20;146 T20 T18 D16;147 T19 50 D20;148 T20 T16 D20;149 T20 T19 D16
150 T20 50 D20;151 T20 T17 D20;152 T20 T20 D16;153 T20 T19 D18;154 T20 T18 D20;155 T20 T15 50;156 T20 T20 D18;157 T20 T19 D20;158 T20 T16 50
160 T20 T20 D20;161 T20 T17 50;164 T20 T18 50;167 T20 T19 50
170 T20 T20 50
"""

STANDARD = {int(entry.split()[0]): tuple(entry.split()[1:])
            for entry in _CHART.replace("\n", ";").split(";") if entry.strip()}

_FIELDS = (
    [f"S{n}" for n in range(1, 21)] + [f"D{n}" for n in range(1, 21)] + [f"T{n}" for n in range(1, 21)]
    + [OUTER_BULL, BULL]
)


def points(field):
    """What a dart on *field* is worth."""
    if field == "0":
        return 0
    if field == BULL:
        return 50
    if field == OUTER_BULL:
        return 25
    return int(field[1:]) * {"S": 1, "D": 2, "T": 3}[field[0]]


def is_double(field):
    return field == BULL or field[0] == "D"


def field_of(throw):
    """The field name of a throw as the board reports it: S20, D16, T19, 25, 50, or 0 for a miss."""
    seg = (throw or {}).get("segment") or {}
    number, multiplier = seg.get("number") or 0, seg.get("multiplier") or 0
    if not number or not multiplier:
        return "0"
    if number == 25:
        return BULL if multiplier == 2 else OUTER_BULL
    return {1: "S", 2: "D", 3: "T"}.get(multiplier, "S") + str(number)


_VALUES = {field: points(field) for field in _FIELDS}
_VALUES["0"] = 0          # a miss


def routes(score, darts=3):
    """Every way to finish *score* with at most *darts* darts, as tuples of fields: the last one a
    double, no dart takes the score below zero or to one."""
    found = []

    def walk(rest, left, path):
        for field in _FIELDS:
            after = rest - _VALUES[field]
            if after < 0 or after == 1:
                continue
            if after == 0:
                if is_double(field):
                    found.append(tuple(path) + (field,))
                continue
            if left > 1:
                walk(after, left - 1, path + [field])

    if score >= 2:
        walk(score, darts, [])
    return found


def finishable(score):
    """Whether three darts can finish *score*."""
    return 2 <= score <= 170 and score not in BOGEY


def standard_route(score):
    return list(STANDARD[score]) if score in STANDARD else None


def darts_to_finish(score, darts=3):
    """The fewest darts that finish *score*, or None if *darts* darts cannot."""
    for n in range(1, darts + 1):
        if routes(score, n):
            return n
    return None


def valid_first_darts(score):
    """Every field that starts a route finishing *score* with three darts or fewer."""
    return sorted({route[0] for route in routes(score)}, key=_FIELDS.index)


def judge_first_dart(score, field):
    """How a first dart at *score* is to be rated: "standard" (the dart the standard route starts
    with), "valid" (another route starts with it) or "invalid"."""
    route = STANDARD.get(score)
    if route and route[0] == field:
        return "standard"
    return "valid" if field in valid_first_darts(score) else "invalid"


def after_darts(score, fields):
    """What is left of *score* after the darts *fields*, and how that rest stands: "bust" (below
    zero, exactly one, or zero without a double), "finished" (zero on a double) or "open"."""
    rest = score
    for field in fields:
        value = _VALUES[field]
        rest -= value
        if rest < 0 or rest == 1 or (rest == 0 and not is_double(field)):
            return {"rest": score, "state": "bust"}      # the turn does not count, the score stays
        if rest == 0:
            return {"rest": 0, "state": "finished"}
    return {"rest": rest, "state": "open"}


def draw(low, high, rng=random, avoid=()):
    """A finishable score from *low* to *high*, not one of *avoid* if another is left."""
    pool = [s for s in range(max(low, 2), min(high, 170) + 1) if finishable(s)]
    if not pool:
        raise ValueError("no finishable score in that range")
    fresh = [s for s in pool if s not in avoid]
    return rng.choice(fresh or pool)
