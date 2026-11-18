"""Find the board in the picture of the empty board, without a model to start from.

The single fields alternate between light and dark, ten times around the center, and that pattern is what the search looks for:

1. Where the center can be: a map of how strongly the picture alternates ten times around each point (small circles), its best peaks.
2. Around each peak a grid of ellipse shapes and turns; a +1/-1 pattern of the single fields (light, dark, light, ...) is laid on the
   picture and the best fits are kept. The pattern repeats every 18 degrees, so a result is right up to a turn of the board by a
   multiple of 18 degrees.
3. Random starts around the best fits, each moved by a pattern search until the pattern lies best. Starts that end in the same place
   count as agreeing: that is the measure of how sure the finding is.
4. One click on the 20 tells which of the 20 positions is the right one.

The result is the start for `calibration.fit`, which moves it onto the rings and wires.
"""
import functools
import math

import cv2
import numpy as np

from breakfast.detection import calibration
from breakfast.detection.geometry import ANGLES, R_OUT, BoardModel, board_pt

WORK_W = 200                                   # width of the small picture the search for the center runs on
CENTER_RADII = (5, 8, 12, 16)                  # circles (pixels of that picture) around a point whose alternation is measured
CENTERS = 6                                    # peaks of the center map that are tried
CENTER_SEP = 15                                # pixels (small picture): two peaks closer than this are one
PROFILE_R = (0.04, 0.06, 0.08)                # radii (share of the picture width) of the circles whose light and dark is read around the center
PROFILE_N = 90                                 # points on each circle
SIZES = tuple(np.arange(0.15, 0.60, 0.006))    # semi-major axis of the outer double ring, as a share of the picture width
SHAPES_KEPT = 3                                # best shapes per center that are tried with every size
GRID_KEPT = 60                                 # best (shape, size) fits that get random neighbours
NEIGHBOURS = 6
SECOND_ROUND = 4                               # best results that get a second round of random tries
SPREAD_PX = 10                                 # how far the random neighbours lie from them
REFINED = 25                                   # best starts that are moved by the pattern search
SCALES = ((12, 2), (3, 0.5), (1, 0.1))         # pattern search steps in pixels (first, last)
MIN_INSIDE = 0.85                              # share of the pattern that must lie in the picture (the board may be cut off a little)
MIN_PATTERN = 0.04                             # strength of the field pattern; below: no board in the picture
MIN_AGREE = 3                                  # starts that must end in the same place
SAME_PX = 10.0                                 # two findings are the same board if the reference points are this close


def normalize(frame):
    """A grey picture with the contrast spread out, so a dark room and a bright one look alike."""
    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY) if frame.ndim == 3 else frame
    return cv2.createCLAHE(clipLimit=4.0, tileGridSize=(8, 8)).apply(gray)


def matrix(psi, ka, kb, beta=0.0):
    """Board millimetres (x right, y up) to pixels, without the shift: R(psi) diag(ka, kb) R(beta) F."""
    c, s = math.cos(psi), math.sin(psi)
    cb, sb = math.cos(beta), math.sin(beta)
    return np.array([[c, -s], [s, c]]) @ np.diag([ka, kb]) @ np.array([[cb, -sb], [sb, cb]]) @ np.diag([1.0, -1.0])


def center_map(gray, radii=CENTER_RADII, n=64):
    """For every point of a small grey picture, how strongly the picture alternates ten times around it on circles of the given radii."""
    h, w = gray.shape
    f = cv2.GaussianBlur(gray.astype(np.float32) / 255, (0, 0), 1.0)
    ys, xs = np.mgrid[0:h, 0:w]
    X, Y = xs.reshape(-1, 1).astype(np.float32), ys.reshape(-1, 1).astype(np.float32)
    theta = np.arange(n) * 2 * np.pi / n
    phase = np.exp(-2j * np.pi * 10 * np.arange(n) / n)
    total = np.zeros(h * w)
    for r in radii:
        mx, my = (X + r * np.cos(theta)[None, :]).astype(np.float32), (Y + r * np.sin(theta)[None, :]).astype(np.float32)
        s = np.concatenate([cv2.remap(f, mx[i:i + 30000], my[i:i + 30000], cv2.INTER_LINEAR, borderMode=cv2.BORDER_CONSTANT, borderValue=0)
                            for i in range(0, len(mx), 30000)])             # remap takes at most 32767 rows
        s = s - s.mean(1, keepdims=True)
        total += np.abs(s @ phase) / (np.abs(s).sum(1) + 1e-3)
    return (total / len(radii)).reshape(h, w)


def find_centers(gray, count=CENTERS):
    """The best peaks of the center map, as (x, y) in the pixels of `gray` (the small picture)."""
    cm = center_map(gray)
    out = []
    for _ in range(count):
        _, top, _, loc = cv2.minMaxLoc(cm)
        if top <= 0:
            break
        out.append(loc)
        cv2.circle(cm, loc, CENTER_SEP, 0, -1)
    return out


def reference_from(par, turn_deg=0.0):
    """The four reference points (wires on the outer double ring) in pixels for the affine model of an ellipse turned by `turn_deg`."""
    cx, cy, psi, a, b = par
    M = matrix(psi, a / R_OUT, b / R_OUT, math.radians(turn_deg))
    return np.array([M @ np.array(board_pt(R_OUT, ang)) + [cx, cy] for ang in ANGLES])


def _pattern():
    """Sample points inside the single fields (clear of the wires and the rings) and +1 / -1 for light / dark, alternating."""
    pts, sign = [], []
    for k in range(20):
        for off in np.linspace(-5.5, 5.5, 5):
            a = math.radians(18 * k + off)
            for r in list(np.linspace(22, 94, 8)) + list(np.linspace(112, 157, 5)):
                pts.append((r * math.sin(a), r * math.cos(a)))
                sign.append(1.0 if k % 2 == 0 else -1.0)
    return np.array(pts), np.array(sign)


PATTERN, SIGNS = _pattern()


def pattern_score(img, H):
    """How well the alternating field pattern lies on the picture `img` (0 to 1, blurred grey) for the board-to-pixel matrix `H`."""
    p = calibration.project(H, PATTERN)
    h, w = img.shape
    inside = (p[:, 0] > 1) & (p[:, 0] < w - 2) & (p[:, 1] > 1) & (p[:, 1] < h - 2)
    if inside.mean() < MIN_INSIDE:
        return -1.0
    v = cv2.remap(img, p[:, 0:1].copy(), p[:, 1:2].copy(), cv2.INTER_LINEAR).reshape(-1)
    return abs(float((SIGNS * v)[inside].sum())) / len(v)


def _search(img, ref):
    ref = ref.copy()
    for step0, step1 in SCALES:
        step = step0
        while step >= step1:
            improved = False
            for i in range(4):
                for j in range(2):
                    best = pattern_score(img, calibration.homography_from(ref))
                    for d in (step, -step):
                        t = ref.copy()
                        t[i, j] += d
                        s = pattern_score(img, calibration.homography_from(t))
                        if s > best + 1e-6:
                            best, ref, improved = s, t, True
            if not improved:
                step /= 2
    return ref


def _turn(H, deg):
    d = math.radians(deg)
    return H @ np.array([[math.cos(d), -math.sin(d), 0], [math.sin(d), math.cos(d), 0], [0, 0, 1]])


def reference_points(H):
    return np.array([calibration.project(H, np.array([board_pt(R_OUT, a)]))[0] for a in ANGLES])


def same_board(H1, H2):
    """Whether two board-to-pixel matrices are the same up to a turn of the board by a multiple of 18 degrees."""
    r2 = reference_points(H2)
    return min(float(np.linalg.norm(reference_points(_turn(H1, 18 * k)) - r2, axis=1).mean()) for k in range(20)) < SAME_PX


def profile(img, cx, cy):
    """Light and dark on circles around (cx, cy): the mean over the radii of the zero-centered picture values, PROFILE_N points around."""
    theta = np.arange(PROFILE_N) * 2 * np.pi / PROFILE_N
    total = np.zeros(PROFILE_N)
    for share in PROFILE_R:
        r = share * img.shape[1]
        v = cv2.remap(img, (cx + r * np.cos(theta)).astype(np.float32).reshape(-1, 1), (cy + r * np.sin(theta)).astype(np.float32).reshape(-1, 1),
                      cv2.INTER_LINEAR, borderMode=cv2.BORDER_CONSTANT, borderValue=0).reshape(-1)
        total += v - v.mean()
    return total / len(PROFILE_R)


@functools.lru_cache(maxsize=4)
def _sign_table(psi_step, ratio_step, turn_step):
    """For every shape (psi, ratio, turn) of a grid: +1 / -1 for light / dark of the sector that lies in each of the PROFILE_N directions
    around the center. Near the center the picture is an affine view of the board, so the directions of the 20 wires depend on the shape only."""
    psi = np.radians(np.arange(0, 180, psi_step))[:, None, None, None]
    ratio = np.arange(0.3, 1.0001, ratio_step)[None, :, None, None]
    turn = np.radians(np.arange(0, 18, turn_step))[None, None, :, None]
    th = (np.arange(PROFILE_N) * 2 * np.pi / PROFILE_N)[None, None, None, :]
    ux, uy = np.cos(th), np.sin(th)
    v1x, v1y = np.cos(psi) * ux + np.sin(psi) * uy, -np.sin(psi) * ux + np.cos(psi) * uy          # R(-psi) u
    v2y = v1y / ratio                                                                             # D^-1
    v3x, v3y = np.cos(turn) * v1x + np.sin(turn) * v2y, -np.sin(turn) * v1x + np.cos(turn) * v2y  # R(-turn)
    alpha = np.degrees(np.arctan2(v3x, -v3y))                                                    # F, then the angle clockwise from the top
    sign = (1 - 2 * (np.floor((alpha + 9) / 18).astype(int) % 2)).astype(np.float32)
    shape = sign.shape[:3]
    params = np.stack(np.broadcast_arrays(np.degrees(psi[..., 0]), ratio[..., 0], np.degrees(turn[..., 0])), -1).reshape(-1, 3)
    return sign.reshape(-1, PROFILE_N), params, shape


def fit_shape(prof, psi_step=3.0, ratio_step=0.025, turn_step=1.0):
    """The shape of the board near its center from the light and dark around it: the (psi, ratio, turn) whose sector signs fit the profile
    best. Returns [(score, psi, ratio, turn_degrees)], best first, without near-equal shapes."""
    signs, params, _ = _sign_table(psi_step, ratio_step, turn_step)
    score = np.abs(signs @ prof.astype(np.float32)) / (np.abs(prof).sum() + 1e-9)
    out = []
    for i in np.argsort(-score)[:400]:
        par = (float(score[i]), *(float(v) for v in params[i]))
        if all(abs(par[1] - o[1]) > 12 or abs(par[2] - o[2]) > 0.12 for o in out):
            out.append(par)
        if len(out) == SHAPES_KEPT:
            break
    return out


def refine_center(img, x, y, reach=24, step=4):
    """The point near (x, y) around which the light and dark fit a board best, with the shapes that fit there."""
    best = (-1.0, x, y, None)
    for dx in range(-reach, reach + 1, step):
        for dy in range(-reach, reach + 1, step):
            shapes = fit_shape(profile(img, x + dx, y + dy), psi_step=6.0, ratio_step=0.05, turn_step=3.0)
            if shapes and shapes[0][0] > best[0]:
                best = (shapes[0][0], x + dx, y + dy, shapes)
    return best


def find_board(frame, seed=0, progress=None):
    """Look for the board in one picture of the empty board. Returns {H, score, agree} (H: board millimetres to pixels, right up to a
    turn by a multiple of 18 degrees; agree: how many of the best starts ended there), or None if the picture shows no board."""
    report = progress or (lambda fraction: None)
    gray = normalize(frame)
    width = frame.shape[1]
    scale = WORK_W / width
    centers = find_centers(cv2.resize(gray, None, fx=scale, fy=scale, interpolation=cv2.INTER_AREA))
    report(0.1)
    img = cv2.GaussianBlur(gray.astype(np.float32) / 255, (0, 0), 1.5)
    rng = np.random.default_rng(seed)
    grid = []
    for k, (x, y) in enumerate(centers):
        _, cx, cy, _ = refine_center(img, x / scale, y / scale)
        for sc_, psi, ratio, turn in fit_shape(profile(img, cx, cy)):
            for a in SIZES:
                ref = reference_from((cx, cy, math.radians(psi), a * width, a * width * ratio), turn)
                grid.append((pattern_score(img, calibration.homography_from(ref)), ref))
        report(0.1 + 0.2 * (k + 1) / len(centers))
    grid.sort(key=lambda g: -g[0])
    starts = list(grid[:GRID_KEPT])
    for _, ref in grid[:GRID_KEPT]:
        for _ in range(NEIGHBOURS):
            st = ref + rng.normal(0, SPREAD_PX, (4, 2))
            starts.append((pattern_score(img, calibration.homography_from(st)), st))
    starts.sort(key=lambda s: -s[0])
    found = []
    for k, (_, st) in enumerate(starts[:REFINED]):
        ref = _search(img, st)
        H = calibration.homography_from(ref)
        found.append((pattern_score(img, H), H))
        report(0.3 + 0.7 * (k + 1) / REFINED)
    found.sort(key=lambda f: -f[0])
    if not found:
        return None
    for _, H in found[:SECOND_ROUND]:                                  # a second round around the best: a few tries more than one start gets
        for _ in range(NEIGHBOURS):
            ref = _search(img, reference_points(H) + rng.normal(0, SPREAD_PX / 2, (4, 2)))
            H2 = calibration.homography_from(ref)
            found.append((pattern_score(img, H2), H2))
    found.sort(key=lambda f: -f[0])
    score, H = found[0]
    agree = sum(1 for s, h in found if same_board(H, h))
    if score < MIN_PATTERN or agree < MIN_AGREE:
        return None
    return {"H": H, "score": round(score, 3), "agree": agree}


def turn_for_click(H, click):
    """`H` turned so that the clicked point (x, y in pixels) lies in the 20. `H` is right up to a multiple of 18 degrees."""
    v = np.linalg.inv(H) @ np.array([click[0], click[1], 1.0])
    angle = math.degrees(math.atan2(v[0] / v[2], v[1] / v[2]))      # clockwise from the top, where the click lies on the board now
    return _turn(H, -18.0 * round(angle / 18.0))


def start_model(homographies, size):
    """The board model to start the fit from: one homography per camera, the nominal ring radii."""
    return BoardModel(homographies, None, size)


def draw(frame, H, marked=False):
    """The rings and wires of a finding on a copy of the picture; `marked`: the 20 is written into its field."""
    img = BoardModel({0: H}, None, (frame.shape[1], frame.shape[0])).draw(0, frame)
    if marked:
        x, y = calibration.project(H, np.array([board_pt(135.0, 0)]))[0]
        cv2.putText(img, "20", (int(x) - 14, int(y) + 8), cv2.FONT_HERSHEY_SIMPLEX, 0.9, (0, 0, 255), 2, cv2.LINE_AA)
    return img


FIT_LIMIT_PX = 20.0            # the fit may move a reference point this far from the search result
FIT_TRUST_PX = 12.0            # a camera whose reference points the fit moved farther than this keeps its search result
KEEP_RATIO = 0.8               # a camera keeps its search result if the fit lowers the field pattern below this share of it


def fit_model(homographies, frames, progress=None):
    """The board model from the search results (`homographies`: camera -> board-to-pixel matrix, turned by the click) and the pictures
    of the empty board. The fit of `calibration` moves the reference points onto the rings and wires and finds the ring radii. On a
    camera whose picture is too dark for the edges the fit can end on something else; there the field pattern, which the search used,
    does not agree with it, and the camera keeps the search result; so does one whose points the fit moved far (the search is within a few pixels, so a long move is the fit
    following something else). Returns (model, report)."""
    size = (frames[0].shape[1], frames[0].shape[0])
    grays = {c: cv2.cvtColor(normalize(f), cv2.COLOR_GRAY2BGR) for c, f in frames.items()}
    new, report = calibration.calibrate(start_model(homographies, size), grays, progress, limit=FIT_LIMIT_PX)
    kept = []
    H = {}
    for c, start in homographies.items():
        img = cv2.GaussianBlur(cv2.cvtColor(grays[c], cv2.COLOR_BGR2GRAY).astype(np.float32) / 255, (0, 0), 1.5)
        before, after = pattern_score(img, start), pattern_score(img, new.H[c])
        if after < KEEP_RATIO * before or report["moved_px"].get(str(c), 0.0) > FIT_TRUST_PX:
            H[c] = start
            kept.append(c)
        else:
            H[c] = new.H[c]
    report["kept_search_result"] = kept
    return BoardModel(H, new.radii, size), report
