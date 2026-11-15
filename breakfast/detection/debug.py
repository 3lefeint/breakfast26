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


def _draw(model, cam, frame, found):
    img = model.draw(cam, frame)
    changed = found["changed"]
    img[changed] = (0.35 * img[changed] + 0.65 * np.array([40, 40, 255])).astype(np.uint8)
    if found["blob"] is not None:
        contours, _ = cv2.findContours(found["blob"].astype(np.uint8), cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        cv2.drawContours(img, contours, -1, (255, 220, 0), 1, cv2.LINE_AA)
    tip = found["tip"]
    if tip is not None:
        if found["line"] is not None:
            _, _, vx, vy = found["line"]
            top = (int(round(tip[0] - LINE_PX * vx)), int(round(tip[1] - LINE_PX * vy)))
            cv2.line(img, top, (int(round(tip[0])), int(round(tip[1]))), (255, 0, 255), 1, cv2.LINE_AA)
        at = (int(round(tip[0])), int(round(tip[1])))
        cv2.drawMarker(img, at, (0, 0, 0), cv2.MARKER_CROSS, 19, 3, cv2.LINE_AA)
        cv2.drawMarker(img, at, (255, 255, 255), cv2.MARKER_CROSS, 17, 1, cv2.LINE_AA)
    return img


def explain(model, befores, afters, frames=None):
    """(info, pictures) for two sets of prepared pictures (camera -> picture) and the BGR pictures to draw on. `info` holds per
    camera the area of the biggest blob, the tip in pixels and in mm, how the tip was found and whether it is off the board, and
    under `fused` what `detector.locate` makes of all cameras (None if no camera sees a blob). `pictures` is camera -> JPEG; without
    `frames` only the numbers are worked out. The pictures are compared at the brightness of `befores`, as the tracker does."""
    cams, pictures = {}, {}
    afters = {cam: detector.level(model.masks[cam], befores[cam], afters[cam]) for cam in model.cams}
    for cam in model.cams:
        found = detector.explain_tip(model.masks[cam], befores[cam], afters[cam])
        row = {"area": found["area"], "tip": None, "mm": None, "off": None, "how": found["reason"]}
        if found["tip"] is not None:
            mm = model.to_board(cam, *found["tip"])
            row.update(tip=[round(found["tip"][0], 1), round(found["tip"][1], 1)], mm=[round(float(mm[0]), 1), round(float(mm[1]), 1)],
                       off=bool(math.hypot(*mm) > detector.OFF_MM), how="shaft line" if found["line"] is not None else "lowest point")
        cams[cam] = row
        if frames is None:
            continue
        ok, buf = cv2.imencode(".jpg", _draw(model, cam, frames[cam], found), [cv2.IMWRITE_JPEG_QUALITY, 80])
        pictures[cam] = buf.tobytes() if ok else None
    result = detector.locate(model, befores, afters, min_cams=1)
    fused = None
    if result is not None:
        fused = {"x": round(float(result["x"]), 1), "y": round(float(result["y"]), 1), "field": result["field"], "cams": result["cams"],
                 "agree": result["agree"], "off": result["off"], "spread": round(float(result["spread"]), 1),
                 "sigma": round(float(result["sigma"]), 2), "margin": round(float(result["margin"]), 1)}
    return {"cams": cams, "fused": fused}, pictures
