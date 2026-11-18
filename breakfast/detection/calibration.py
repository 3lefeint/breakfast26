"""The automatic fit of the board model on the picture of the empty board.

Start: the model in use (one homography per camera, the ring radii). It is moved until the projected rings and wires lie on the
edges of the picture: coarse to fine over three blur sizes, a pattern search on the four reference points of every camera (pixels)
and on the ring radii (mm). Ported from `data/detection/calib_auto.py`, which agreed with 51 wire crossings clicked by hand.
"""
import json
import math
import shutil
from pathlib import Path

import cv2
import numpy as np

from breakfast.detection.geometry import ANGLES, RING_R, R_OUT, BoardModel, board_pt

FITTED = (162.0, 107.0, 99.0)                  # radii that are fitted; 170 stays the reference
SCALES = ((4.0, 3.0, 0.4), (2.5, 1.5, 0.15), (1.5, 0.8, 0.05))       # blur of the edge map, start step px, end step px
START_SIZES = (0.9, 0.94, 0.97, 1.0, 1.03, 1.06, 1.1)      # sizes of the whole model tried first (a model a tenth too small fits a ring next to the right one)
START_SHIFTS = (-16, -8, 0, 8, 16)                       # and shifts in x and y (pixels)
STARTS_KEPT = 6                                          # the best of these are moved by the search
MAX_MOVE_PX = 50.0                             # a fit that moves a reference point farther than this is refused


def edge_map(gray, sigma):
    g = cv2.GaussianBlur(gray.astype(np.float32), (0, 0), 1.0)
    mag = np.hypot(cv2.Sobel(g, cv2.CV_32F, 1, 0, ksize=3), cv2.Sobel(g, cv2.CV_32F, 0, 1, ksize=3))
    mag = np.minimum(mag, np.percentile(mag, 99))
    return cv2.GaussianBlur(mag, (0, 0), sigma)


def curve_points(radii):
    """Board points (mm) on all rings and wires, one array of (x, y)."""
    pts = []
    for r in RING_R:
        rr = radii.get(r, r)
        a = np.radians(np.linspace(0, 360, 360, endpoint=False))
        pts.append(np.stack([rr * np.sin(a), rr * np.cos(a)], 1))
    for k in range(20):
        a = math.radians(9 + 18 * k)
        r = np.linspace(radii.get(99.0, 99.0) * 0.2, radii.get(170.0, 170.0), 60)
        pts.append(np.stack([r * math.sin(a), r * math.cos(a)], 1))
    return np.concatenate(pts)


def homography_from(ref_px):
    """Board to pixel from the four reference points (the wires on the outer double ring) in pixels."""
    dst = np.float32([board_pt(R_OUT, a) for a in ANGLES])
    return cv2.getPerspectiveTransform(dst, np.float32(ref_px).reshape(4, 2))


def project(Hm, pts):
    v = np.c_[pts, np.ones(len(pts))] @ Hm.T
    return (v[:, :2] / v[:, 2:3]).astype(np.float32)


def score(emap, Hm, radii):
    p = project(Hm, curve_points(radii))
    h, w = emap.shape
    ok = (p[:, 0] > 1) & (p[:, 0] < w - 2) & (p[:, 1] > 1) & (p[:, 1] < h - 2)
    if ok.sum() < len(p) * 0.9:
        return -1e9
    v = cv2.remap(emap, p[:, 0:1].reshape(-1, 1), p[:, 1:2].reshape(-1, 1), cv2.INTER_LINEAR)
    return float(v.mean())


def _within(t, anchor, limit):
    return limit is None or float(np.abs(t - anchor).max()) <= limit


def _search_h(gray, ref, radii, scales, anchor=None, limit=None):
    ref = ref.copy()
    for sigma, step0, step1 in scales:
        emap = edge_map(gray, sigma)
        step = step0
        while step >= step1:
            improved = False
            for i in range(4):
                for j in range(2):
                    best = score(emap, homography_from(ref), radii)
                    for d in (step, -step):
                        t = ref.copy(); t[i, j] += d
                        if not _within(t, anchor, limit):
                            continue
                        sc = score(emap, homography_from(t), radii)
                        if sc > best + 1e-6:
                            best, ref, improved = sc, t, True
            if not improved:
                step /= 2
    return ref, score(emap, homography_from(ref), radii)


def fit(frames, ref0, radii0, progress=None, limit=None):
    """frames: camera -> BGR picture of the empty board; ref0: camera -> 4 reference points (pixels). Returns the reference points
    and the radii after the fit. `progress(fraction, text)` is called as it goes (the first part, the search of several starts per
    camera, counts for 60 %, the three fine scales for the rest). `limit`: how far (pixels) a reference point may go from its start."""
    report = progress or (lambda fraction, text: None)
    ref = {c: np.array(ref0[c], float).reshape(4, 2) for c in ref0}
    radii = dict(radii0)
    anchor = {c: ref[c].copy() for c in ref}
    total = len(ref) * STARTS_KEPT
    done = 0
    for c in ref:                                                   # per camera: best of several starts, so a start a few wires away
        gray = cv2.cvtColor(frames[c], cv2.COLOR_BGR2GRAY)          # or a ring next to the right one does not win
        center = project(homography_from(ref[c]), np.array([[0.0, 0.0]]))[0]
        coarse = edge_map(gray, SCALES[0][0])
        starts = []
        for size in START_SIZES:
            for dx in START_SHIFTS:
                for dy in START_SHIFTS:
                    start = center + (ref[c] - center) * size + [dx, dy]
                    if _within(start, anchor[c], limit):
                        starts.append((score(coarse, homography_from(start), radii), start))
        starts.sort(key=lambda s: -s[0])
        results = []
        for _, start in starts[:STARTS_KEPT]:
            report(0.6 * done / total, f"camera {c + 1}: first search {done % STARTS_KEPT + 1} of {STARTS_KEPT}")
            results.append(_search_h(gray, start, radii, SCALES[:2], ref[c], limit))
            done += 1
        done += STARTS_KEPT - len(results)
        if results:
            ref[c] = max(results, key=lambda r: r[1])[0]
    for k, (sigma, step0, step1) in enumerate(SCALES):
        report(0.6 + 0.4 * k / len(SCALES), f"fine adjustment {k + 1} of {len(SCALES)}")
        emaps = {c: edge_map(cv2.cvtColor(frames[c], cv2.COLOR_BGR2GRAY), sigma) for c in frames}
        step = step0
        while step >= step1:
            improved = False
            for c in ref:
                for i in range(4):
                    for j in range(2):
                        best = score(emaps[c], homography_from(ref[c]), radii)
                        for d in (step, -step):
                            t = ref[c].copy(); t[i, j] += d
                            if not _within(t, anchor[c], limit):
                                continue
                            s = score(emaps[c], homography_from(t), radii)
                            if s > best + 1e-6:
                                best, ref[c], improved = s, t, True
            for r in FITTED:                                        # radii are shared: the sum over the cameras decides
                cur = sum(score(emaps[c], homography_from(ref[c]), radii) for c in ref)
                for d in (step / 3, -step / 3):
                    t = dict(radii); t[r] = radii[r] + d
                    s = sum(score(emaps[c], homography_from(ref[c]), t) for c in ref)
                    if s > cur + 1e-6:
                        cur, radii, improved = s, t, True
            if not improved:
                step /= 2
    return ref, radii


def reference_points(model):
    """The four reference points of every camera in pixels, from the model in use."""
    return {c: [model.to_pixel(c, *board_pt(R_OUT, a)) for a in ANGLES] for c in model.cams}


RING_IDS = (162.0, 107.0, 99.0)             # fitted radii; the outer double ring (170) stays the reference
POINT_RINGS = (170.0, 162.0, 107.0, 99.0)


def targets():
    """The 17 points per camera: the center and the crossings of the four sector wires (20|1, 6|10, 3|19, 11|14) with the four outer rings."""
    out = [{"id": "center", "r": 0.0, "a": 0}]
    for r in POINT_RINGS:
        for a in ANGLES:
            out.append({"id": f"{r:g}@{a}", "r": r, "a": a})
    return out


def model_points(model):
    """Where a model puts the 17 points in every camera's picture: {camera: {id: [x, y]}} in pixels."""
    pts = {}
    for c in model.cams:
        pts[c] = {}
        for t in targets():
            x, y = model.to_pixel(c, *board_pt(model.radii.get(t["r"], t["r"]), t["a"])) if t["id"] != "center" else model.to_pixel(c, 0.0, 0.0)
            pts[c][t["id"]] = [round(float(x), 2), round(float(y), 2)]
    return pts


def _project(Hm, r, deg):
    v = Hm @ np.array([r * math.sin(math.radians(deg)), r * math.cos(math.radians(deg)), 1.0])
    return v[:2] / v[2]


def fit_points(points, model):
    """The board model that fits the clicked points best: one homography per camera and one effective radius per ring (shared by all
    cameras), least squares on the pixel error (Levenberg-Marquardt), started from `model`. `points`: {camera: {id: [x, y]}}.
    Returns (new model, report with rms and max error per camera, the radii and warnings about unusual radii)."""
    tg = {t["id"]: t for t in targets()}
    cams = list(model.cams)
    data = {c: [(tg[i]["r"], tg[i]["a"], xy) for i, xy in points[c].items() if xy and i in tg] for c in cams}
    H0 = {c: model.H[c] / model.H[c][2, 2] for c in cams}

    def unpack(x):
        H = {c: np.append(x[8 * k:8 * k + 8], 1.0).reshape(3, 3) for k, c in enumerate(cams)}
        radii = dict(zip(RING_IDS, x[8 * len(cams):8 * len(cams) + len(RING_IDS)]))
        radii[170.0] = 170.0
        return H, radii

    def residual(x):
        H, radii = unpack(x)
        out = []
        for c in cams:
            for r, a, xy in data[c]:
                out.extend(_project(H[c], radii.get(r, r), a) - np.array(xy))
        return np.array(out)

    x = np.concatenate([np.concatenate([H0[c].flatten()[:8] for c in cams]), [model.radii.get(r, r) for r in RING_IDS]])
    lam = 1e-2
    cost = float(residual(x) @ residual(x))
    for _ in range(80):
        r0 = residual(x)
        J = np.empty((len(r0), len(x)))
        for j in range(len(x)):
            d = np.zeros(len(x)); d[j] = 1e-6 * max(1.0, abs(x[j]))
            J[:, j] = (residual(x + d) - r0) / d[j]
        A = J.T @ J
        step = np.linalg.solve(A + lam * np.diag(np.diag(A) + 1e-9), -J.T @ r0)
        c2 = float(residual(x + step) @ residual(x + step))
        if c2 < cost:
            x, cost, lam = x + step, c2, lam * 0.5
            if np.max(np.abs(step)) < 1e-9:
                break
        else:
            lam *= 4
    H, radii = unpack(x)
    report = {"radii_mm": {f"{r:g}": round(float(v), 2) for r, v in sorted(radii.items())}, "rms_px": {}, "max_px": {}}
    for c in cams:
        e = [float(np.linalg.norm(_project(H[c], radii.get(r, r), a) - np.array(xy))) for r, a, xy in data[c]]
        report["rms_px"][str(c)] = round(float(np.sqrt(np.mean(np.square(e)))), 2) if e else None
        report["max_px"][str(c)] = round(max(e), 2) if e else None
    report["unusual"] = [{"ring": r, "delta_mm": round(float(radii[r] - r), 1)} for r in RING_IDS if abs(radii[r] - r) > 6.0]
    return BoardModel(H, radii, model.size), report


def calibrate(model, frames, progress=None, limit=None):
    """Fit the model on the empty-board pictures. Returns (new model, report) or (None, report) if the fit moved too far.
    `limit`: how far (pixels) a reference point may go from where the model has it."""
    ref0 = reference_points(model)
    ref, radii = fit(frames, ref0, model.radii, progress, limit)
    moves = {c: float(np.max(np.linalg.norm(np.array(ref[c]) - np.array(ref0[c]), axis=1))) for c in ref}
    scores = {}
    for c in ref:
        emap = edge_map(cv2.cvtColor(frames[c], cv2.COLOR_BGR2GRAY), 2.5)
        scores[c] = (score(emap, model.H[c], model.radii), score(emap, homography_from(ref[c]), radii))
    report = {"moved_px": {str(c): round(v, 2) for c, v in moves.items()},
              "score_before_after": {str(c): [round(a, 2), round(b, 2)] for c, (a, b) in scores.items()},
              "radii": {str(k): round(v, 2) for k, v in radii.items()}}
    if max(moves.values()) > MAX_MOVE_PX:
        report["refused"] = f"a reference point moved more than {MAX_MOVE_PX:.0f} px: is the board empty and are the cameras where they were?"
        return None, report
    new = BoardModel({c: homography_from(ref[c]) for c in ref}, radii, model.size)
    return new, report


def revert(path):
    """Take the model that `save` kept as `.prev.json` back. Returns the model, or None if there is none."""
    path = Path(path)
    prev = path.with_suffix(".prev.json")
    if not prev.exists():
        return None
    shutil.copy2(prev, path)
    return BoardModel.from_file(path)


def save(model, path, report=None):
    """Write the model; the file it replaces is kept next to it as `.prev`."""
    path = Path(path)
    if path.exists():
        shutil.copy2(path, path.with_suffix(".prev.json"))
    path.write_text(json.dumps(model.to_json(report=report), indent=1))
