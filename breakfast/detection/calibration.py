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
STARTS = [(0, 0), (9, 0), (-9, 0), (0, 9), (0, -9), (18, 0), (-18, 0), (0, 18), (0, -18)]       # shifts of the whole model tried first
MAX_MOVE_PX = 30.0                             # a fit that moves a reference point farther than this is refused


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


def _search_h(gray, ref, radii, scales):
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
                        sc = score(emap, homography_from(t), radii)
                        if sc > best + 1e-6:
                            best, ref, improved = sc, t, True
            if not improved:
                step /= 2
    return ref, score(emap, homography_from(ref), radii)


def fit(frames, ref0, radii0):
    """frames: camera -> BGR picture of the empty board; ref0: camera -> 4 reference points (pixels). Returns the reference points
    and the radii after the fit."""
    ref = {c: np.array(ref0[c], float).reshape(4, 2) for c in ref0}
    radii = dict(radii0)
    for c in ref:                                                   # per camera: best of several starts, so a start a few
        gray = cv2.cvtColor(frames[c], cv2.COLOR_BGR2GRAY)          # wires away does not end on the wrong wire
        results = [_search_h(gray, ref[c] + [dx, dy], radii, SCALES[:2]) for dx, dy in STARTS]
        ref[c] = max(results, key=lambda r: r[1])[0]
    for sigma, step0, step1 in SCALES:
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


def calibrate(model, frames):
    """Fit the model on the empty-board pictures. Returns (new model, report) or (None, report) if the fit moved too far."""
    ref0 = reference_points(model)
    ref, radii = fit(frames, ref0, model.radii)
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


def save(model, path, report=None):
    """Write the model; the file it replaces is kept next to it as `.prev`."""
    path = Path(path)
    if path.exists():
        shutil.copy2(path, path.with_suffix(".prev.json"))
    path.write_text(json.dumps(model.to_json(report=report), indent=1))
