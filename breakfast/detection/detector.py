"""Locate one new dart from the pictures before and after it landed.

Per camera: the difference image of before and after, the biggest changed blob is the dart, the lower end of its shaft is the
tip (see `find_tip`), and the board model maps that pixel to a point on the board. The points of the cameras are fused by their median (the field and the
position are the median's); the fusion weighted by the uncertainty of every pixel only gives the `sigma`, because on the reviewed
throws it was wrong more often than the median. Ported from the evaluation tools in `data/detection/detect.py`, which measured it against the
hand reviews of the throws.
"""
import math
import statistics

import cv2
import numpy as np

from breakfast.dartboard import SEGMENT_ORDER
from breakfast.detection.geometry import R_OUT

THRESHOLD = 10              # gray-level difference that counts as changed
CLOSE = (5, 25)             # closing kernel (width, height) that joins the parts of one dart
MIN_AREA = 120              # smallest blob in pixels that is taken for a dart
OFF_MM = 190.0              # a camera point farther from the center than this is off the board
REJECT_D2 = 12.0            # squared Mahalanobis distance from the median above which a camera is ignored in the fusion
AGREE_MM = 25.0             # cameras whose points lie within this of the median agree on where the dart is
SIGMA_PX = 2.0              # assumed uncertainty of a tip pixel
AXIS_SPAN = 70              # rows above the lowest changed pixel that the line of the shaft is fitted to (barrel and tip)
AXIS_KEEP = 5.0             # pixels farther than this from the first fit are left out of the second
AXIS_NEAR = 3.0             # changed pixels within this of the line belong to the shaft
AXIS_GAP = 30.0             # the shaft ends where no changed pixel follows within this many pixels along the line
AXIS_MIN = 25               # fewer changed pixels than this give no line: the lowest point of the blob is the tip


def prepare(frame):
    """The gray, blurred picture the differences are made of."""
    return cv2.GaussianBlur(cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY), (5, 5), 0)


def highpass(prepared):
    """The picture without its slow brightness changes (daylight, a shadow far from the dart): what is left is edges and thin
    things like darts. Used to compare a picture with the empty board taken a long time ago."""
    g = prepared.astype(np.float32)
    return np.clip(g - cv2.GaussianBlur(g, (0, 0), 12) + 128, 0, 255).astype(np.uint8)


def _shaft_end(px, py):
    """The lower end of the shaft among the changed pixels of a blob, or None if they give no line. A line is fitted to the lower
    part of the dart (twice, the second time without the pixels far from the first); the tip is the last changed pixel on that line
    going down from the body, and it lies on the line. A shadow or a speck next to the tip, which the closing joins to the blob, is
    off the line and does not move the tip."""
    if len(py) < AXIS_MIN:
        return None
    low = py >= py.max() - AXIS_SPAN
    pts = np.stack([px[low], py[low]], axis=1).astype(np.float32)
    if len(pts) < AXIS_MIN:
        return None
    for _ in range(2):
        vx, vy, x0, y0 = (float(v) for v in cv2.fitLine(pts, cv2.DIST_HUBER, 0, 0.01, 0.01).ravel())
        if vy < 0:
            vx, vy = -vx, -vy
        kept = pts[np.abs((pts[:, 0] - x0) * vy - (pts[:, 1] - y0) * vx) <= AXIS_KEEP]
        if len(kept) < AXIS_MIN:
            break
        pts = kept
    if vy < 0.5:                                            # nearly flat in the picture: no shaft that points down
        return None
    across = np.abs((px - x0) * vy - (py - y0) * vx)
    along = np.sort(((px - x0) * vx + (py - y0) * vy)[across <= AXIS_NEAR])
    if len(along) < 5:
        return None
    end = float(np.median(along))
    for a in along[along >= end]:
        if a - end > AXIS_GAP:
            break
        end = float(a)
    return (x0 + end * vx, y0 + end * vy)


def find_tip(mask, before, after, threshold=THRESHOLD, min_area=MIN_AREA):
    """(tip pixel, info) of the biggest changed blob, or (None, reason). `before` and `after` come from `prepare`. The tip is the
    lower end of the shaft (`_shaft_end`); a blob that gives no line has it at its lowest point."""
    diff = cv2.absdiff(before, after)
    diff = cv2.bitwise_and(diff, diff, mask=mask)
    _, bw = cv2.threshold(diff, threshold, 255, cv2.THRESH_BINARY)
    opened = cv2.morphologyEx(bw, cv2.MORPH_OPEN, np.ones((3, 3), np.uint8))
    bw = cv2.morphologyEx(opened, cv2.MORPH_CLOSE, np.ones((CLOSE[1], CLOSE[0]), np.uint8))
    n, lab, stats, _ = cv2.connectedComponentsWithStats(bw, 8)
    if n <= 1:
        return None, "no change"
    k = max(range(1, n), key=lambda q: int(stats[q, cv2.CC_STAT_AREA]))
    area = int(stats[k, cv2.CC_STAT_AREA])
    if area < min_area:
        return None, "blob too small"
    py, px = np.nonzero((lab == k) & (opened > 0))
    tip = _shaft_end(px, py)
    if tip is None:
        ys, xs = np.nonzero(lab == k)
        ymax = ys.max()
        tip = (float(xs[ys >= ymax - 3].mean()), float(ymax))
    return tip, {"area": area, "bbox": [int(stats[k, 0]), int(stats[k, 1]), int(stats[k, 2]), int(stats[k, 3])]}


def changed_area(mask, before, after, threshold=THRESHOLD):
    """Area in pixels of the biggest changed blob between two prepared pictures (0 for none)."""
    diff = cv2.bitwise_and(cv2.absdiff(before, after), cv2.absdiff(before, after), mask=mask)
    _, bw = cv2.threshold(diff, threshold, 255, cv2.THRESH_BINARY)
    bw = cv2.morphologyEx(bw, cv2.MORPH_OPEN, np.ones((3, 3), np.uint8))
    bw = cv2.morphologyEx(bw, cv2.MORPH_CLOSE, np.ones((CLOSE[1], CLOSE[0]), np.uint8))
    n, _, stats, _ = cv2.connectedComponentsWithStats(bw, 8)
    return max((int(stats[k, cv2.CC_STAT_AREA]) for k in range(1, n)), default=0)


def appeared(mask, ref, empty, current, threshold=THRESHOLD, ref_hp=None):
    """Whether the biggest change between `ref` and `current` is something that *appeared*: the share of its pixels that also
    differ from the empty board. A dart that was taken out leaves a blob that looks like the empty board again (share near 0),
    a new dart does not (share near 1). 1.0 if there is no blob."""
    base = ref if ref_hp is None else ref_hp
    diff = cv2.bitwise_and(cv2.absdiff(base, current), cv2.absdiff(base, current), mask=mask)
    _, bw = cv2.threshold(diff, threshold, 255, cv2.THRESH_BINARY)
    bw = cv2.morphologyEx(bw, cv2.MORPH_OPEN, np.ones((3, 3), np.uint8))
    bw = cv2.morphologyEx(bw, cv2.MORPH_CLOSE, np.ones((CLOSE[1], CLOSE[0]), np.uint8))
    n, lab, stats, _ = cv2.connectedComponentsWithStats(bw, 8)
    if n <= 1:
        return 1.0
    k = max(range(1, n), key=lambda q: int(stats[q, cv2.CC_STAT_AREA]))
    blob = lab == k
    vs_empty = cv2.absdiff(empty, current) > threshold
    return float((vs_empty & blob).sum()) / max(1, int(blob.sum()))


def _fuse_weighted(items):
    """items: list of (mm point, covariance). Start from the median, drop the points far from it (in units of their own
    uncertainty), combine the rest weighted by the inverse covariance. Returns (point, sigma_mm, n_used)."""
    pts = np.array([m for m, _ in items])
    med = np.median(pts, axis=0)
    keep = [(m, C) for m, C in items if (np.array(m) - med) @ np.linalg.inv(C) @ (np.array(m) - med) <= REJECT_D2]
    if not keep:
        keep = items
    cov = np.linalg.inv(sum(np.linalg.inv(C) for _, C in keep))
    x = cov @ sum(np.linalg.inv(C) @ np.array(m) for m, C in keep)
    return (float(x[0]), float(x[1])), float(math.sqrt(np.trace(cov) / 2)), len(keep)


def locate(model, befores, afters, min_cams=1, masks=None):
    """The new dart between two picture sets (camera -> prepared picture). Returns a dict with `x`, `y` (mm), `field`, the
    `sigma` of the position, `margin` (distance to the nearest field boundary), `cams` (cameras that saw it), `off` (cameras
    that put it off the board) and `tips`; or None if fewer than `min_cams` cameras saw a new dart. `masks` (camera -> mask)
    replaces the areas of the board model: the parts of a picture to look at."""
    pts, tips = [], {}
    masks = masks or model.masks
    for cam in model.cams:
        tip, info = find_tip(masks[cam], befores[cam], afters[cam])
        if tip is None:
            continue
        mm = model.to_board(cam, *tip)
        pts.append((mm, model.pixel_cov(cam, tip, SIGMA_PX)))
        tips[cam] = {"px": [round(tip[0], 1), round(tip[1], 1)], "mm": [round(mm[0], 1), round(mm[1], 1)], "area": info["area"]}
    if len(pts) < min_cams or not pts:
        return None
    med = np.median(np.array([m for m, _ in pts]), axis=0)
    agree = sum(1 for m, _ in pts if math.dist(m, med) <= AGREE_MM)       # cameras that put the dart at about the same place
    spread = max((math.dist(a[0], b[0]) for i, a in enumerate(pts) for b in pts[i + 1:]), default=0.0)
    hits = [(m, c) for m, c in pts if math.hypot(*m) <= OFF_MM]
    off = len(pts) - len(hits)
    if off > len(hits):                                    # most cameras put it beyond the board: a miss
        mx = statistics.median(m[0] for m, _ in pts)
        my = statistics.median(m[1] for m, _ in pts)
        return {"x": mx, "y": my, "field": "0", "sigma": 0.0, "margin": 99.0, "cams": len(pts), "off": off, "agree": agree, "spread": spread, "tips": tips}
    fx = statistics.median(m[0] for m, _ in hits)
    fy = statistics.median(m[1] for m, _ in hits)
    _, sigma, used = _fuse_weighted(hits)
    field = model.field(fx, fy)
    # A dart off the board is only close to the outer edge of the double ring; the wires do not run out there.
    margin = abs(math.hypot(fx, fy) - model.radii[170.0]) if field == "0" else model.edge_distance(fx, fy)
    return {"x": fx, "y": fy, "field": field, "sigma": sigma, "margin": margin,
            "cams": len(pts), "off": off, "agree": agree, "spread": spread, "used": used, "median": [fx, fy], "tips": tips}


def support(mask_shape, model, cam, x_mm, y_mm, empty_hp, current_hp, threshold=THRESHOLD):
    """The share of changed pixels (against the empty board, high-pass pictures) in a window around where a dart at the board point
    would stand in this camera's picture: the dart and its shaft above the tip. Real darts give 0.2 and more, an empty spot 0."""
    h, w = mask_shape
    changed = cv2.absdiff(empty_hp, current_hp) > threshold
    best = 0.0
    for dx in (-10.0, -5.0, 0.0, 5.0, 10.0):                 # a dart can be pushed a little by the next one: the best place nearby counts
        for dy in (-10.0, -5.0, 0.0, 5.0, 10.0):
            px, py = model.to_pixel(cam, x_mm + dx, y_mm + dy)
            x0, x1 = max(0, int(px - 14)), min(w, int(px + 14))
            y0, y1 = max(0, int(py - 75)), min(h, int(py + 6))
            if x1 > x0 and y1 > y0:
                best = max(best, float(changed[y0:y1, x0:x1].mean()))
    return best


def to_throw(result):
    """The throw as the board manager reports it: the segment and the position (unit: the outer edge of the double ring,
    x to the right, y up). A dart off the board has no position."""
    field = result["field"]
    if field == "0":                                        # like the board manager: M<number of the sector it is outside of>
        number = SEGMENT_ORDER[int((math.degrees(math.atan2(result["x"], result["y"])) % 360 + 9) % 360 // 18)]
        coords = {"x": result["x"] / R_OUT, "y": result["y"] / R_OUT}
        return {"segment": {"name": f"M{number}", "number": number, "bed": "Outside", "multiplier": 0}, "coords": coords}
    if field in ("25", "50"):
        seg = {"name": field, "number": 25, "bed": "Single" if field == "25" else "Double", "multiplier": 1 if field == "25" else 2}
    else:
        mult = "SDT".index(field[0]) + 1
        seg = {"name": field, "number": int(field[1:]), "multiplier": mult,
               "bed": {1: "SingleOuter", 2: "Double", 3: "Triple"}[mult]}
    return {"segment": seg, "coords": {"x": result["x"] / R_OUT, "y": result["y"] / R_OUT}}
