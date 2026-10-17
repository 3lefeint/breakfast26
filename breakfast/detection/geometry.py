"""The board model: one homography per camera (board millimetres to pixels) and the ring radii shared by all cameras.

Board coordinates: millimetres from the center, x to the right, y up; the wire between 20 and 1 lies 9 degrees clockwise from
the top. The model is stored as JSON (`calib_model.json`): `H` (camera -> 3x3, board to pixel), `radii` (the fitted rings) and
the `size` of the frames it was made for.
"""
import json
import math
from pathlib import Path

import cv2
import numpy as np

from breakfast.dartboard import SEGMENT_ORDER

R_OUT = 170.0                       # outer edge of the double ring
ANGLES = (9, 99, 189, 279)          # wires 20|1, 6|10, 3|19, 11|14 on the outer double ring, clockwise from the top
RING_R = (170.0, 162.0, 107.0, 99.0, 15.9, 6.35)
NOMINAL_RADII = {99.0: 99.0, 107.0: 107.0, 162.0: 162.0, 170.0: 170.0}   # triple in/out, double in/out


def board_pt(r, deg):
    return (r * math.sin(math.radians(deg)), r * math.cos(math.radians(deg)))


class BoardModel:
    def __init__(self, homographies, radii=None, size=(800, 600)):
        """homographies: camera index -> 3x3 matrix, board millimetres to pixels."""
        self.size = (int(size[0]), int(size[1]))
        self.H = {int(c): np.array(h, dtype=np.float64) for c, h in homographies.items()}
        self.inv = {c: np.linalg.inv(h) for c, h in self.H.items()}
        self.radii = dict(NOMINAL_RADII)
        self.radii.update({float(k): float(v) for k, v in (radii or {}).items()})
        self.cams = sorted(self.H)
        self.masks = {c: self._mask(c) for c in self.cams}

    @classmethod
    def from_file(cls, path):
        m = json.loads(Path(path).read_text())
        return cls(m["H"], m.get("radii"), m.get("size", (800, 600)))

    def to_json(self, **extra):
        return {"H": {str(c): self.H[c].tolist() for c in self.cams}, "radii": {str(k): v for k, v in self.radii.items()},
                "size": list(self.size), **extra}

    # ------------------------------------------------------------------ geometry

    def to_board(self, cam, x, y):
        v = self.inv[cam] @ np.array([x, y, 1.0])
        return v[0] / v[2], v[1] / v[2]

    def to_pixel(self, cam, x_mm, y_mm):
        v = self.H[cam] @ np.array([x_mm, y_mm, 1.0])
        return v[0] / v[2], v[1] / v[2]

    def pixel_cov(self, cam, tip, sigma_px=2.0):
        """Covariance on the board (mm^2) of a tip pixel: the pixel uncertainty carried through the transform."""
        x, y = tip
        base = np.array(self.to_board(cam, x, y))
        jx = np.array(self.to_board(cam, x + 1, y)) - base
        jy = np.array(self.to_board(cam, x, y + 1)) - base
        J = np.stack([jx, jy], axis=1)
        return (sigma_px ** 2) * J @ J.T

    def field(self, x_mm, y_mm):
        """The field at a point: `S20`, `D16`, `T19`, `25`, `50` or `0` (off the board), with the ring radii of this model."""
        radius = math.hypot(x_mm, y_mm)
        r = self.radii
        if radius > r[170.0]:
            return "0"
        if radius <= 6.35:
            return "50"
        if radius <= 15.9:
            return "25"
        number = SEGMENT_ORDER[int((math.degrees(math.atan2(x_mm, y_mm)) % 360 + 9) % 360 // 18)]
        if r[99.0] < radius <= r[107.0]:
            return f"T{number}"
        if radius > r[162.0]:
            return f"D{number}"
        return f"S{number}"

    def edge_distance(self, x_mm, y_mm):
        """Distance in mm from a point to the nearest field boundary (ring or wire): how safe the field is."""
        radius = math.hypot(x_mm, y_mm)
        d = min(abs(radius - r) for r in (self.radii[170.0], self.radii[162.0], self.radii[107.0], self.radii[99.0], 15.9, 6.35))
        if radius > 15.9:
            ang = (math.degrees(math.atan2(x_mm, y_mm)) - 9) % 18
            d = min(d, radius * math.sin(math.radians(min(ang, 18 - ang))))
        return d

    # ------------------------------------------------------------------ region of interest

    def _mask(self, cam, margin=25, up=130):
        """Where a dart can show up in the picture: the board circle projected, plus room above (the dart sticks out)."""
        w, h = self.size
        pts = np.array([self.to_pixel(cam, *board_pt(R_OUT, a)) for a in range(0, 360, 10)])
        x0 = max(0, int(pts[:, 0].min()) - margin)
        x1 = min(w, int(pts[:, 0].max()) + margin)
        y0 = max(0, int(pts[:, 1].min()) - up)
        y1 = min(h, int(pts[:, 1].max()) + margin)
        m = np.zeros((h, w), np.uint8)
        m[y0:y1, x0:x1] = 255
        return m

    def outline(self, cam, radius_mm=None):
        """Pixel polygon of a ring of the board, for drawing overlays."""
        r = radius_mm or R_OUT
        return np.array([self.to_pixel(cam, *board_pt(r, a)) for a in range(0, 360, 4)], np.int32)

    def draw(self, cam, frame):
        """The rings and wires of the model on a copy of the frame."""
        img = frame.copy()
        for r in (self.radii[170.0], self.radii[162.0], self.radii[107.0], self.radii[99.0], 15.9, 6.35):
            cv2.polylines(img, [self.outline(cam, r)], True, (0, 255, 255), 1, cv2.LINE_AA)
        for k in range(20):
            a = 9 + 18 * k
            p0 = self.to_pixel(cam, *board_pt(15.9, a))
            p1 = self.to_pixel(cam, *board_pt(self.radii[170.0], a))
            cv2.line(img, tuple(int(v) for v in p0), tuple(int(v) for v in p1), (0, 200, 0), 1, cv2.LINE_AA)
        return img
