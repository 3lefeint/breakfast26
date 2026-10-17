"""Has a camera or the board moved? The picture of the empty board is compared with the one that was taken when the model was made
(the reference): the shift between the two, in pixels, from a phase correlation of the high-pass pictures inside the board area.

Measured on the recordings of the first matches (pictures of the empty board from many sessions on three days): the shift of a camera
stays within 0.7 px, with a correlation of 0.95 and more. A different picture (darts left on the board, other light) has a low
correlation; then nothing is said ("unknown") instead of a shift that means nothing."""
import cv2
import numpy as np

from breakfast.detection import detector

WARN_PX = 2.0           # a shift from here on is reported ...
BAD_PX = 5.0            # ... and from here on the model no longer fits the picture
MIN_RESPONSE = 0.5      # correlation below this: the picture is not the empty board of the reference
LEVELS = ("ok", "warn", "bad")


def _signal(prepared, mask):
    g = detector.highpass(prepared).astype(np.float32) - 128.0
    return g * (mask > 0)


def measure(model, reference, prepared):
    """Per camera {dx, dy, px, response, level}: how far the picture lies from the reference (both `detector.prepare`d empty-board
    pictures, camera -> picture). `level` is ok, warn, bad or unknown."""
    out = {}
    for cam in model.cams:
        if cam not in reference or cam not in prepared:
            continue
        h, w = prepared[cam].shape[:2]
        window = cv2.createHanningWindow((w, h), cv2.CV_32F)
        (dx, dy), response = cv2.phaseCorrelate(_signal(reference[cam], model.masks[cam]), _signal(prepared[cam], model.masks[cam]), window)
        px = float(np.hypot(dx, dy))
        level = "unknown" if response < MIN_RESPONSE else "bad" if px >= BAD_PX else "warn" if px >= WARN_PX else "ok"
        out[cam] = {"dx": round(float(dx), 2), "dy": round(float(dy), 2), "px": round(px, 2), "response": round(float(response), 2), "level": level}
    return out


def worst(result):
    """The level of the whole set: the worst of the cameras, `unknown` only when nothing could be judged."""
    levels = [r["level"] for r in result.values()]
    for level in ("bad", "warn", "ok"):
        if level in levels:
            return level
    return "unknown"


def save_reference(folder, prepared):
    folder.mkdir(parents=True, exist_ok=True)
    for cam, img in prepared.items():
        cv2.imwrite(str(folder / f"cam{cam}.png"), img)


def load_reference(folder, cams):
    """camera -> reference picture, or None when it is missing for a camera."""
    out = {}
    for cam in cams:
        img = cv2.imread(str(folder / f"cam{cam}.png"), cv2.IMREAD_GRAYSCALE)
        if img is None:
            return None
        out[cam] = img
    return out
