"""What the player said about the darts the detection reported (`labels.jsonl`, one row per correction or confirmation), turned
into numbers: how often it was right among the darts that were looked at, which mistakes it makes, how far off a corrected dart
was and whether the darts it flagged as uncertain were the wrong ones.

Only darts the player looked at are in the file (a flagged dart that was confirmed or corrected, a dart that was corrected), so the
shares below say how the looked-at darts went, not how the detection does over all darts."""
import json
import math
import sys
from collections import Counter
from pathlib import Path

from breakfast.dartboard import SEGMENT_ORDER

R_OUT_MM = 170.0
MARGIN_BUCKETS = ((0.0, 1.0), (1.0, 2.0), (2.0, 4.0), (4.0, 1e9))      # mm to the nearest wire or ring


def read(path):
    """The rows of a labels file; a missing file or a damaged line gives fewer rows, never an error."""
    rows = []
    try:
        with open(path) as f:
            for line in f:
                try:
                    rows.append(json.loads(line))
                except ValueError:
                    continue
    except OSError:
        pass
    return [r for r in rows if isinstance(r, dict)]


def _split(field):
    """(number, multiplier) of a field name, (25, 1) and (25, 2) for the bulls, None for a miss or an unknown name."""
    field = (field or "").upper()
    if field == "25":
        return 25, 1
    if field == "50":
        return 25, 2
    if field[:1] in ("S", "D", "T") and field[1:].isdigit():
        return int(field[1:]), "SDT".index(field[0]) + 1
    return None


def mistake_kind(detected, corrected):
    """How a wrong field differs from the right one: the same number in another ring (`ring`), the next number on the board
    (`neighbour`), a bull against its surroundings (`bull`), a dart that was or was not on the board (`miss`), or `other`."""
    a, b = _split(detected), _split(corrected)
    if a is None or b is None:
        return "miss"
    if 25 in (a[0], b[0]):
        return "bull"
    if a[0] == b[0]:
        return "ring"
    i, j = SEGMENT_ORDER.index(a[0]), SEGMENT_ORDER.index(b[0])
    return "neighbour" if (i - j) % 20 in (1, 19) else "other"


def _mm(a, b):
    return math.hypot(a["x"] - b["x"], a["y"] - b["y"]) * R_OUT_MM


def _spread(values):
    values = sorted(values)
    if not values:
        return None
    at = lambda q: values[min(len(values) - 1, int(q * len(values)))]
    return {"n": len(values), "mean": round(sum(values) / len(values), 2), "median": round(at(0.5), 2),
            "p90": round(at(0.9), 2), "max": round(values[-1], 2)}


def summarize(rows):
    """The numbers of a list of rows (see the module text)."""
    confirmed = [r for r in rows if r.get("confirmed")]
    changed = [r for r in rows if not r.get("confirmed") and r.get("corrected") != r.get("detected")]
    same = [r for r in rows if not r.get("confirmed") and r.get("corrected") == r.get("detected")]
    right = len(confirmed) + len(same)
    wrong_ids = {id(r) for r in changed}

    def flagged(r):
        return bool((r.get("detection") or {}).get("uncertain"))

    offsets = [(_mm(r["detected_at"], r["corrected_at"]), r["corrected_at"]["x"] - r["detected_at"]["x"],
                r["corrected_at"]["y"] - r["detected_at"]["y"]) for r in rows
               if isinstance(r.get("detected_at"), dict) and isinstance(r.get("corrected_at"), dict)]
    margins = []
    for lo, hi in MARGIN_BUCKETS:
        inside = [r for r in rows if lo <= ((r.get("detection") or {}).get("margin", -1)) < hi]
        margins.append({"from_mm": lo, "to_mm": None if hi > 1e8 else hi, "looked_at": len(inside),
                        "wrong": sum(1 for r in inside if id(r) in wrong_ids)})
    cams = {}
    for r in rows:
        det = r.get("detection") or {}
        key = f"{det.get('agree', '?')}/{det.get('cams', '?')}"
        entry = cams.setdefault(key, {"looked_at": 0, "wrong": 0})
        entry["looked_at"] += 1
        entry["wrong"] += id(r) in wrong_ids
    return {
        "looked_at": len(rows), "right": right, "confirmed": len(confirmed), "wrong": len(changed),
        "wrong_share": round(len(changed) / len(rows), 3) if rows else None,
        "flagged_looked_at": sum(1 for r in rows if flagged(r)),
        "wrong_and_flagged": sum(1 for r in changed if flagged(r)),         # how many of the wrong darts the detection had flagged
        "right_but_flagged": sum(1 for r in confirmed + same if flagged(r)),
        "mistakes": dict(Counter(mistake_kind(r["detected"], r["corrected"]) for r in changed)),
        "pairs": [{"detected": d, "corrected": c, "n": n} for (d, c), n in
                  Counter((r["detected"], r["corrected"]) for r in changed).most_common(10)],
        "offset_mm": _spread([o[0] for o in offsets]),
        "bias_mm": {"x": round(sum(o[1] for o in offsets) / len(offsets) * R_OUT_MM, 2),
                    "y": round(sum(o[2] for o in offsets) / len(offsets) * R_OUT_MM, 2)} if offsets else None,
        "by_margin": margins, "by_cameras": cams,
        "since": min((r["t"] for r in rows if r.get("t")), default=None),
    }


def summary_of(path):
    return summarize(read(path))


if __name__ == "__main__":
    print(json.dumps(summary_of(Path(sys.argv[1]) if len(sys.argv) > 1 else "labels.jsonl"), indent=1))
