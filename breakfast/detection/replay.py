"""Play recorded clips (see `clips.py`) through the tracker again and print what it finds.

    python -m breakfast.detection.replay <model.json> <clip dir> [<clip dir> ...]
"""
import json
import sys
from pathlib import Path

import cv2

from breakfast.detection.geometry import BoardModel
from breakfast.detection.tracker import BoardTracker, Settings


def replay_clip(model, folder, settings=None, tracker=None):
    """Feed one clip to a tracker (a new one unless given). Returns (events, tracker); every event gets the time of the set."""
    folder = Path(folder)
    meta = json.loads((folder / "clip.json").read_text())
    tracker = tracker or BoardTracker(model, settings)
    out = []
    for s in meta["sets"]:
        frames = {}
        for c in model.cams:
            f = cv2.imread(str(folder / f"{s['i']:03d}_cam{c}.jpg"))
            if f is not None:
                frames[c] = f
        if len(frames) < len(model.cams):
            continue
        out += tracker.feed(s["t"], frames)
    return out, tracker


def main(argv):
    model = BoardModel.from_file(argv[1])
    tracker = None
    for d in argv[2:]:
        events, tracker = replay_clip(model, d, tracker=tracker)
        print(Path(d).name, [(e.kind, e.count, (e.throw or {}).get("segment", {}).get("name")) for e in events])


if __name__ == "__main__":
    main(sys.argv)
