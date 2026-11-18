"""What the detection sees between two picture sets, drawn for the diagnostics page.

Per camera the picture with the board model and on top of it: the changed pixels (red), the outline of the biggest blob (cyan),
the line of the shaft (magenta) and the tip (white cross). With it the numbers: the area of the blob, the tip in pixels and on the
board, and where the cameras together put the dart. Nothing in here is used to count a dart; it runs only when the page asks.
"""
import math

import cv2
import numpy as np

from breakfast.detection import detector

LINE_PX = 140               # how far the line of the shaft is drawn up from the tip


LIVE = {"changed": (40, 40, 255), "blob": (255, 220, 0), "line": (255, 0, 255), "tip": (255, 255, 255)}
DART_COLORS = [(67, 159, 255), (143, 255, 107), (255, 181, 107)]       # BGR of the first, second and third dart of a turn: orange, green, blue


def _palette(color):
    return {"changed": color, "blob": color, "line": color, "tip": color}


def _draw(img, found, palette=LIVE):
    """Mark what `found` (detector.explain_tip) has on `img`, in place: the changed pixels, the outline of the biggest blob, the line
    of the shaft and the tip."""
    changed = found["changed"]
    img[changed] = (0.35 * img[changed] + 0.65 * np.array(palette["changed"])).astype(np.uint8)
    if found["blob"] is not None:
        contours, _ = cv2.findContours(found["blob"].astype(np.uint8), cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        cv2.drawContours(img, contours, -1, palette["blob"], 1, cv2.LINE_AA)
    tip = found["tip"]
    if tip is not None:
        if found["line"] is not None:
            _, _, vx, vy = found["line"]
            top = (int(round(tip[0] - LINE_PX * vx)), int(round(tip[1] - LINE_PX * vy)))
            cv2.line(img, top, (int(round(tip[0])), int(round(tip[1]))), palette["line"], 1, cv2.LINE_AA)
        at = (int(round(tip[0])), int(round(tip[1])))
        cv2.drawMarker(img, at, (0, 0, 0), cv2.MARKER_CROSS, 19, 3, cv2.LINE_AA)
        cv2.drawMarker(img, at, palette["tip"], cv2.MARKER_CROSS, 17, 1, cv2.LINE_AA)
    return img


def _jpeg(img):
    ok, buf = cv2.imencode(".jpg", img, [cv2.IMWRITE_JPEG_QUALITY, 80])
    return buf.tobytes() if ok else None


def plain(model, frames):
    """camera -> JPEG of the picture with the board model drawn in and nothing marked."""
    return {cam: _jpeg(model.draw(cam, frames[cam])) for cam in model.cams if cam in frames}


def _analyse(model, befores, afters):
    """(info, found per camera) for two sets of prepared pictures; see `explain` for `info`."""
    cams, founds = {}, {}
    afters = {cam: detector.level(model.masks[cam], befores[cam], afters[cam]) for cam in model.cams}
    for cam in model.cams:
        found = founds[cam] = detector.explain_tip(model.masks[cam], befores[cam], afters[cam])
        row = {"area": found["area"], "tip": None, "mm": None, "off": None, "how": found["reason"]}
        if found["tip"] is not None:
            mm = model.to_board(cam, *found["tip"])
            row.update(tip=[round(found["tip"][0], 1), round(found["tip"][1], 1)], mm=[round(float(mm[0]), 1), round(float(mm[1]), 1)],
                       off=bool(math.hypot(*mm) > detector.OFF_MM), how="shaft line" if found["line"] is not None else "lowest point")
        cams[cam] = row
    result = detector.locate(model, befores, afters, min_cams=1)
    fused = None
    if result is not None:
        fused = {"x": round(float(result["x"]), 1), "y": round(float(result["y"]), 1), "field": result["field"], "cams": result["cams"],
                 "agree": result["agree"], "off": result["off"], "spread": round(float(result["spread"]), 1),
                 "sigma": round(float(result["sigma"]), 2), "margin": round(float(result["margin"]), 1)}
    return {"cams": cams, "fused": fused}, founds


def explain(model, befores, afters, frames=None):
    """(info, pictures) for two sets of prepared pictures (camera -> picture) and the BGR pictures to draw on. `info` holds per
    camera the area of the biggest blob, the tip in pixels and in mm, how the tip was found and whether it is off the board, and
    under `fused` what `detector.locate` makes of all cameras (None if no camera sees a blob). `pictures` is camera -> JPEG; without
    `frames` only the numbers are worked out. The pictures are compared at the brightness of `befores`, as the tracker does."""
    info, founds = _analyse(model, befores, afters)
    pictures = {cam: _jpeg(_draw(model.draw(cam, frames[cam]), founds[cam])) for cam in model.cams} if frames is not None else {}
    return info, pictures


def explain_turn(model, darts, frames):
    """(infos, pictures) of the darts of a turn on one picture per camera. `darts` is a list of (befores, afters) pairs of prepared
    pictures, None for a dart without a picture from before; `frames` the BGR pictures to draw on (camera -> picture, the ones after
    the last dart, so every dart of the turn sticks in the board). Dart 1, 2 and 3 are marked in DART_COLORS; `infos` has one
    entry per dart like `explain` gives it (empty cameras for a dart without pictures)."""
    imgs = {cam: model.draw(cam, frames[cam]) for cam in model.cams}
    infos = []
    for i, d in enumerate(darts):
        if d is None:
            infos.append({"cams": {}, "fused": None})
            continue
        info, founds = _analyse(model, *d)
        infos.append(info)
        for cam in model.cams:
            _draw(imgs[cam], founds[cam], _palette(DART_COLORS[i % len(DART_COLORS)]))
    return infos, {cam: _jpeg(img) for cam, img in imgs.items()}
