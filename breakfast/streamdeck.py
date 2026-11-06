"""Stream Deck at the board: keys that run board controls and show the board status.

The device is driven over USB by Breakfast itself (python-elgato-streamdeck), so no other software has to run next to
it. The layout lives in `[streamdeck]` of config.toml: `enabled`, `brightness` and `keys`, a list of
`{key, action, label, color, hold, image, show}` (key counts from 0; color is `status` to follow the board or a `#rrggbb` value;
`hold` is the seconds the key has to be held to run its action, 0 runs it on the press; `image` is empty, a symbol
of Breakfast (`symbol:undo`) or a png, jpg or webp file uploaded into the `streamdeck` folder next to config.toml; `show`
makes a display key that shows a value of the game in play (SHOW_VALUES), with or without an action). `actions` holds the custom
actions a key can run besides the built-in ones: `{id, name, kind, method, target, body}`, a route of Breakfast or any
web address.

Everything that does not touch the USB device (layout checks, status colors, key drawing, the actions) works without
one, so it is tested without hardware; the device layer is a few calls on the object the library returns.
"""
import io
import json
import logging
import os
import re
import math
import threading
import time
import uuid
from pathlib import Path

from breakfast import config as cfg_mod

log = logging.getLogger(__name__)

ACTIONS = {
    "reset_board": "Reset Board",
    "start_board": "Start Board",
    "undo": "Undo",
    "next_player": "Next Player",
    "next_game": "Next Game",
    "cancel_game": "Cancel Game",
    "fun_mode": "Fun Mode",
}
SOUND_PREFIX = "sound:"
SOUND_NAME = re.compile(r"^\w[\w .\-()]{0,98}\.(mp3|wav|ogg|m4a|flac|aac)$", re.IGNORECASE)

STATUS_COLORS = {
    "green": "#1faa59",
    "yellow": "#e6a800",
    "red": "#cc2a2a",
    "off": "#000000",
}
DEFAULT_BRIGHTNESS = 60
DEFAULT_COLOR = "#000000"
# Shown while no device is connected, so the layout can be set up first (a 15-key Stream Deck).
DEFAULT_ROWS, DEFAULT_COLS = 3, 5
MAX_KEYS = 64
MAX_PAGES = 10
MAX_FOLDERS = 16
FOLDER_PREFIX = "folder:"
NAV_BACK, NAV_PREV, NAV_NEXT = "nav:back", "nav:prev", "nav:next"
NAV_COLOR = "#20232a"
CORRECT_PREFIX = "correct_dart:"      # a key that opens the correction of a dart: correct_dart:1 to correct_dart:3
VIRTUAL = "@"                        # folder ids that begin with it are made on the fly (the dart correction)
RINGS = (("0", "Miss"), ("S", "Single"), ("D", "Double"), ("T", "Triple"))
MAX_ACTIONS = 32
HTTP_METHODS = ("GET", "POST", "PUT", "PATCH", "DELETE")
REQUEST_TIMEOUT_SECONDS = 5
SYMBOLS = ("reset", "start", "undo", "next_player", "next_game", "cancel", "sound", "fun", "folder", "back", "page_prev", "page_next")   # drawn by Breakfast, no file needed
SYMBOL_PREFIX = "symbol:"
SHOW_VALUES = ("player", "remaining", "lives", "darts", "round")   # what a display key shows of the game in play
FLASH_SECONDS = 3
FLASH_STEP_SECONDS = 0.4
FLASH_COLOR = "#e6a800"
IMAGE_NAME = re.compile(r"^\w[\w .\-]{0,78}\.(png|jpe?g|webp)$", re.IGNORECASE)
MAX_IMAGE_BYTES = 2_000_000
IMAGE_DIR_NAME = "streamdeck"       # next to config.toml
PREVIEW_SIZE = (96, 96)
EDITOR_PREVIEW_SIZE = (216, 216)
MAX_LAYERS = 8
MAX_BORDER = 24             # in 72nds of the key's side
EFFECTS = ("pulse", "blink", "chase")
OVERRIDE_STATUSES = ("green", "yellow", "red", "off")   # the color names of status_color
MAX_OVERRIDES = 8
EFFECT_TICK_SECONDS = 0.1
CHASE_STEPS = 32
PULSE_STEPS = 12
VALUE_TOKENS = ("player", "remaining", "lives", "darts", "round")
MAX_HOLD_SECONDS = 5
DEFAULT_HOLD_SECONDS = 0.8
HOLD_STEP_SECONDS = 0.08   # how often the progress bar of a held key is drawn
RECONNECT_SECONDS = 3


_GREEN = {"throw", "board started", "takeout finished", "calibration finished", "manual reset"}
_YELLOW = {"takeout", "takeout in progress", "takeout started", "calibration started", "board starting"}
_RED = {"stopped", "board stopped", "board stopping", "board disconnected"}


def status_color(board_status):
    """The color name for a board status, the same reading as the TV view: green when ready to throw, yellow around
    the take-out and while the board starts, red when it is stopped or gone, off when unknown."""
    s = (board_status or "").strip().lower()
    if s in _GREEN:
        return "green"
    if s in _YELLOW:
        return "yellow"
    if s in _RED:
        return "red"
    return "off"


def board_stopped(board_status):
    return status_color(board_status) == "red"


def _valid_hex(value):
    return (isinstance(value, str) and len(value) == 7 and value[0] == "#"
            and all(c in "0123456789abcdefABCDEF" for c in value[1:]))


def clean_actions(actions):
    """The custom actions as stored: a list of `{id, name, kind, method, target, body}`.

    `kind` is `route` (a route of Breakfast, `target` is a path under /api/) or `url` (any http(s) address), both with an
    optional `body`. An action without an id gets one. Raises ValueError with a message for the UI."""
    if not isinstance(actions, list):
        raise ValueError("actions must be a list")
    if len(actions) > MAX_ACTIONS:
        raise ValueError(f"at most {MAX_ACTIONS} custom actions")
    out, seen = [], set(ACTIONS)
    for entry in actions:
        if not isinstance(entry, dict):
            raise ValueError("every action must be an object")
        name = str(entry.get("name", "")).strip()[:40]
        if not name:
            raise ValueError("an action needs a name")
        kind = entry.get("kind")
        if kind not in ("route", "url"):
            raise ValueError("kind must be 'route' or 'url'")
        method = str(entry.get("method", "POST")).upper()
        if method not in HTTP_METHODS:
            raise ValueError("method must be one of " + ", ".join(HTTP_METHODS))
        target = str(entry.get("target", "")).strip()
        if kind == "route" and not (target.startswith("/api/") and " " not in target):
            raise ValueError("a route has to start with /api/")
        if kind == "url" and not (target.lower().startswith(("http://", "https://")) and " " not in target):
            raise ValueError("an address has to start with http:// or https://")
        body = entry.get("body", "")
        if not isinstance(body, str) or len(body) > 4000:
            raise ValueError("body must be text of at most 4000 characters")
        action_id = entry.get("id") or "custom-" + uuid.uuid4().hex[:8]
        if not isinstance(action_id, str) or not action_id.startswith("custom-") or action_id in seen:
            raise ValueError("bad or duplicate action id")
        seen.add(action_id)
        out.append({"id": action_id, "name": name, "kind": kind, "method": method, "target": target,
                    "body": body})
    return out


def clean_keys(keys, custom_ids=(), folder_ids=()):
    """The layout as stored: unknown actions and bad colors refused, one entry per key, sorted by key.
    `custom_ids` are the ids of the custom actions a key may use besides the built-in ones, `folder_ids` the folders it may open.
    A key sits on a `page` (0 to 9) of its layout; the entry for the same key on the same page is the last one given.

    Raises ValueError with a message for the UI when the layout is not a list of key entries."""
    if not isinstance(keys, list):
        raise ValueError("keys must be a list")
    if len(keys) > MAX_KEYS:
        raise ValueError(f"at most {MAX_KEYS} keys")
    out = {}
    for entry in keys:
        if not isinstance(entry, dict):
            raise ValueError("every key must be an object")
        key = entry.get("key")
        if not isinstance(key, int) or isinstance(key, bool) or not 0 <= key < MAX_KEYS:
            raise ValueError("key must be a number from 0 to %d" % (MAX_KEYS - 1))
        action = entry.get("action") or ""
        show = entry.get("show") or ""
        if show and show not in SHOW_VALUES:
            raise ValueError(f"unknown value to show: {show}")
        if action:
            is_folder = action.startswith(FOLDER_PREFIX) and action[len(FOLDER_PREFIX):] in folder_ids
            is_correct = action in ("correct_dart:1", "correct_dart:2", "correct_dart:3")
            is_sound = action.startswith(SOUND_PREFIX) and SOUND_NAME.match(action[len(SOUND_PREFIX):]) is not None
            if action not in ACTIONS and action not in custom_ids and not is_folder and not is_sound and not is_correct:
                raise ValueError(f"unknown action: {action}")
        design = clean_design(entry.get("design"))
        if not action and not show and design is None and not entry.get("effect"):
            raise ValueError("a key needs an action, a value to show or a design")
        label = entry.get("label")
        label = ACTIONS.get(action, "") if label is None else str(label)[:40]
        color = entry.get("color", DEFAULT_COLOR)
        if color != "status" and not _valid_hex(color):
            raise ValueError("color must be 'status' or #rrggbb")
        hold = entry.get("hold", 0)
        if isinstance(hold, bool) or not isinstance(hold, (int, float)) or not 0 <= hold <= MAX_HOLD_SECONDS:
            raise ValueError("hold must be a number of seconds from 0 to %d" % MAX_HOLD_SECONDS)
        image = entry.get("image", "")
        if not valid_image(image):
            raise ValueError("image must be empty, symbol:<name> or the name of an uploaded png, jpg or webp file")
        page = entry.get("page", 0)
        if isinstance(page, bool) or not isinstance(page, int) or not 0 <= page < MAX_PAGES:
            raise ValueError("page must be a number from 0 to %d" % (MAX_PAGES - 1))
        slot = (page, key)
        out[slot] = {"key": key, "action": action, "label": label, "color": color.lower(), "hold": hold, "image": image, "show": show}
        if page:
            out[slot]["page"] = page
        if design is not None:
            out[slot]["design"] = design
        effect = clean_effect(entry.get("effect"))
        if effect is not None:
            out[slot]["effect"] = effect
        if entry.get("ignore_override") is True:
            out[slot]["ignore_override"] = True
    return [out[k] for k in sorted(out)]


def clean_folders(folders, custom_ids=()):
    """The folders as stored: `[{id, name, keys}]`. A folder's keys are laid out like the root layout and may open
    folders again. An entry without an id gets one. Raises ValueError with a message for the UI."""
    if not isinstance(folders, list) or len(folders) > MAX_FOLDERS:
        raise ValueError("folders must be a list of at most %d" % MAX_FOLDERS)
    named, ids = [], []
    for folder in folders:
        if not isinstance(folder, dict):
            raise ValueError("every folder must be an object")
        name = str(folder.get("name", "")).strip()[:40]
        if not name:
            raise ValueError("a folder needs a name")
        folder_id = folder.get("id") or "f" + uuid.uuid4().hex[:8]
        if not isinstance(folder_id, str) or not re.fullmatch(r"\w{1,20}", folder_id) or folder_id in ids:
            raise ValueError("bad or duplicate folder id")
        ids.append(folder_id)
        named.append((folder_id, name, folder.get("keys", [])))
    return [{"id": i, "name": n, "keys": clean_keys(k, custom_ids, ids)} for i, n, k in named]


def prune_keys(keys, custom_ids, folder_ids):
    """The keys without the ones whose custom action or folder is gone."""
    return [k for k in keys if not k["action"] or k["action"] in ACTIONS or k["action"] in custom_ids
            or k["action"][len(FOLDER_PREFIX):] in folder_ids and k["action"].startswith(FOLDER_PREFIX)]


def page_count(keys):
    return max((k.get("page", 0) for k in keys), default=0) + 1


def _unit(value, name, low, high):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not low <= value <= high:
        raise ValueError(f"{name} must be a number from {low} to {high}")
    return round(float(value), 4)


def clean_design(design):
    """The drawn layout of a key as stored, or None for a key drawn the plain way: `{layers, border}`. A layer is a
    `text` (`text`, `x`, `y`, `size`, `color`) or an `image` (`image`, `x`, `y`, `size`); x and y are the center as a
    fraction of the key, `size` the height of the text or the side of the image as a fraction of the key. The text may
    hold {player}, {remaining}, {lives}, {darts} and {round}. Raises ValueError with a message for the UI."""
    if design in (None, {}, ""):
        return None
    if not isinstance(design, dict):
        raise ValueError("design must be an object")
    layers = design.get("layers", [])
    if not isinstance(layers, list) or len(layers) > MAX_LAYERS:
        raise ValueError(f"design layers must be a list of at most {MAX_LAYERS}")
    out = []
    for layer in layers:
        if not isinstance(layer, dict):
            raise ValueError("every layer must be an object")
        kind = layer.get("kind")
        item = {"kind": kind, "x": _unit(layer.get("x", 0.5), "x", 0, 1), "y": _unit(layer.get("y", 0.5), "y", 0, 1)}
        if kind == "text":
            item["text"] = str(layer.get("text", ""))[:60]
            item["size"] = _unit(layer.get("size", 0.25), "size", 0.05, 1)
            color = layer.get("color", "auto")
            if color != "auto" and not _valid_hex(color):
                raise ValueError("text color must be 'auto' or #rrggbb")
            item["color"] = color.lower()
        elif kind == "image":
            image = layer.get("image", "")
            if not image or not valid_image(image):
                raise ValueError("image must be symbol:<name> or the name of an uploaded png, jpg or webp file")
            item["image"] = image
            item["size"] = _unit(layer.get("size", 0.6), "size", 0.1, 2)
        else:
            raise ValueError("a layer is a text or an image")
        out.append(item)
    border = design.get("border") or {}
    if not isinstance(border, dict):
        raise ValueError("border must be an object")
    color = border.get("color", "#ffffff")
    if not _valid_hex(color):
        raise ValueError("border color must be #rrggbb")
    width = border.get("width", 0)
    if isinstance(width, bool) or not isinstance(width, (int, float)) or not 0 <= width <= MAX_BORDER:
        raise ValueError("border width must be a number from 0 to %d" % MAX_BORDER)
    return {"layers": out, "border": {"color": color.lower(), "width": int(width)}}


def clean_effect(effect):
    """An effect as stored, or None for no effect: `{type, color, speed, width}`. `speed` is the number of cycles a second
    (a lap of the frame for a chase), `width` the thickness of the frame in 72nds of the key. Raises ValueError."""
    if effect in (None, {}, ""):
        return None
    if not isinstance(effect, dict):
        raise ValueError("effect must be an object")
    kind = effect.get("type")
    if kind not in EFFECTS:
        raise ValueError("effect type must be one of " + ", ".join(EFFECTS))
    color = effect.get("color", "#ff0000")
    if not _valid_hex(color):
        raise ValueError("effect color must be #rrggbb")
    speed = _unit(effect.get("speed", 1), "effect speed", 0.1, 5)
    width = effect.get("width", 6)
    if isinstance(width, bool) or not isinstance(width, (int, float)) or not 1 <= width <= MAX_BORDER:
        raise ValueError("effect width must be a number from 1 to %d" % MAX_BORDER)
    return {"type": kind, "color": color.lower(), "speed": speed, "width": int(width)}


def clean_overrides(overrides):
    """The rules that put an effect on every key while the board has a status: `[{status, effect}]`, one per status."""
    if not isinstance(overrides, list) or len(overrides) > MAX_OVERRIDES:
        raise ValueError("overrides must be a list of at most %d rules" % MAX_OVERRIDES)
    out, seen = [], set()
    for rule in overrides:
        if not isinstance(rule, dict) or rule.get("status") not in OVERRIDE_STATUSES:
            raise ValueError("an override needs a status: " + ", ".join(OVERRIDE_STATUSES))
        if rule["status"] in seen:
            raise ValueError("one override per status")
        seen.add(rule["status"])
        effect = clean_effect(rule.get("effect"))
        if effect is None:
            raise ValueError("an override needs an effect")
        out.append({"status": rule["status"], "effect": effect})
    return out


def effect_signature(effect, t):
    """What the effect looks like at time `t`, reduced to the few steps it can show: a key is drawn again only when it changes."""
    cycle = (t * effect["speed"]) % 1
    if effect["type"] == "pulse":
        return round((0.5 - 0.5 * math.cos(2 * math.pi * cycle)) * PULSE_STEPS)
    if effect["type"] == "blink":
        return cycle < 0.5
    return int(cycle * CHASE_STEPS)


def apply_effect(img, effect, t):
    """The key with the effect at time `t`: a frame that pulses (fades in and out), blinks (on and off) or chases (a lit
    stretch running round the edge)."""
    from PIL import Image, ImageDraw

    w, h = img.size
    color = _rgb(effect["color"])
    thick = max(1, round(effect["width"] * h / 72))
    sig = effect_signature(effect, t)
    if effect["type"] == "blink" and not sig:
        return img
    framed = img.copy()
    draw = ImageDraw.Draw(framed)
    if effect["type"] == "chase":
        for i in range(min(thick, w // 2, h // 2)):
            ring = ([(x, i) for x in range(i, w - i)] + [(w - 1 - i, y) for y in range(i + 1, h - i)]
                    + [(x, h - 1 - i) for x in range(w - 2 - i, i - 1, -1)] + [(i, y) for y in range(h - 2 - i, i, -1)])
            n = len(ring)
            for k, point in enumerate(ring):
                if ((k / n) - sig / CHASE_STEPS) % 1 < 0.25:
                    draw.point(point, fill=color)
        return framed
    _draw_frame(framed, color, thick)
    if effect["type"] == "pulse":
        return Image.blend(img, framed, sig / PULSE_STEPS)
    return framed


def valid_image(value):
    """No image, a built-in symbol (`symbol:undo`) or the name of a file in the image folder."""
    if value == "":
        return True
    if not isinstance(value, str):
        return False
    if value.startswith(SYMBOL_PREFIX):
        return value[len(SYMBOL_PREFIX):] in SYMBOLS
    return IMAGE_NAME.match(value) is not None


def key_hex(entry, board_status):
    """The color a configured key shows right now, as #rrggbb."""
    if entry["color"] == "status":
        return STATUS_COLORS[status_color(board_status)]
    return entry["color"]


def _rgb(hex_color):
    return tuple(int(hex_color[i:i + 2], 16) for i in (1, 3, 5))


def render_key(label, hex_color, size, progress=None, image=None, symbol=None, value=None):
    """A square key image: the color as background and the label centered, black or white text by brightness.
    With a picture (`image`, a PIL image) the picture fills the key inside a frame of the color and the label sits on a
    band at the bottom; with a `symbol` the symbol is drawn on the color. `progress` (0 to 1) adds a bar along the
    bottom, the hold of a key that has to be held. A `value` (text) is drawn large with the label small below it."""
    from PIL import Image, ImageDraw

    w, h = size
    rgb = _rgb(hex_color)
    ink = (0, 0, 0) if (rgb[0] * 299 + rgb[1] * 587 + rgb[2] * 114) / 1000 > 140 else (255, 255, 255)
    img = Image.new("RGB", (w, h), rgb)
    draw = ImageDraw.Draw(img)
    if value is not None:
        top = round(h * 0.68) if label else h
        _draw_label(img, value, ink, (0, 0, w, top), big=True)
        if label:
            _draw_label(img, label, ink, (0, top - 2, w, h))
    elif image is not None:
        frame = max(3, h // 10)
        img.paste(_cover(image, (w - 2 * frame, h - 2 * frame)), (frame, frame))
        if label:
            band = round(h * 0.34)
            shade = Image.new("RGB", (w - 2 * frame, band), (0, 0, 0))
            region = (frame, h - frame - band, w - frame, h - frame)
            img.paste(Image.blend(img.crop(region), shade, 0.65), region[:2])
            _draw_label(img, label, (255, 255, 255), (region[0], region[1], region[2], region[3]))
    elif symbol is not None:
        top = round(h * 0.68) if label else h
        _draw_symbol(draw, symbol, (0, 0, w, top), ink)
        if label:
            _draw_label(img, label, ink, (0, top - 2, w, h))
    elif label:
        _draw_label(img, label, ink, (0, 0, w, h))
    if progress is not None:
        _draw_progress(img, progress)
    return img


def render_design(design, hex_color, size, picture_of, values=None, progress=None):
    """A key drawn from its layers on the color, with the border on top. `picture_of(name)` gives `(picture, symbol)` for
    an image layer; `values` fills the {tokens} of the text layers."""
    from PIL import Image, ImageDraw

    w, h = size
    rgb = _rgb(hex_color)
    ink = (0, 0, 0) if (rgb[0] * 299 + rgb[1] * 587 + rgb[2] * 114) / 1000 > 140 else (255, 255, 255)
    img = Image.new("RGB", (w, h), rgb)
    for layer in design["layers"]:
        cx, cy = layer["x"] * w, layer["y"] * h
        if layer["kind"] == "text":
            text = layer["text"]
            for token in VALUE_TOKENS:
                value = (values or {}).get(token)
                text = text.replace("{%s}" % token, "" if value is None else str(value))
            if text.strip():
                color = ink if layer["color"] == "auto" else _rgb(layer["color"])
                _draw_text_at(img, text, cx, cy, max(6, round(layer["size"] * h)), color)
        else:
            side = max(4, round(layer["size"] * w))
            picture, symbol = picture_of(layer["image"])
            box = (round(cx - side / 2), round(cy - side / 2))
            if picture is not None:
                fitted = picture.copy()
                fitted.thumbnail((side, side), Image.LANCZOS)
                img.paste(fitted, (round(cx - fitted.width / 2), round(cy - fitted.height / 2)))
            elif symbol is not None:
                _draw_symbol(ImageDraw.Draw(img), symbol, (box[0], box[1], box[0] + side, box[1] + side), ink)
    border = design["border"]
    if border["width"]:
        _draw_frame(img, _rgb(border["color"]), border["width"] * h / 72)
    if progress is not None:
        _draw_progress(img, progress)
    return img


def _draw_frame(img, color, width):
    """A frame of `color` along the edge of the key, `width` pixels thick."""
    from PIL import ImageDraw

    w, h = img.size
    t = max(1, round(width))
    draw = ImageDraw.Draw(img)
    for i in range(t):
        draw.rectangle((i, i, w - 1 - i, h - 1 - i), outline=color)


def _draw_text_at(img, text, cx, cy, px, ink):
    """The text centered on (cx, cy) with letters `px` high, broken into lines at the width of the key, kept inside it."""
    from PIL import ImageDraw, ImageFont

    w, h = img.size
    draw = ImageDraw.Draw(img)
    font = ImageFont.load_default(size=px)
    lines = _wrap(draw, text.split(), font, w - 4) or [""]
    gap = max(1, px // 8)
    heights = [draw.textbbox((0, 0), ln, font=font)[3] for ln in lines]
    total = sum(heights) + gap * (len(lines) - 1)
    y = min(max(cy - total / 2, 0), max(h - total, 0))
    for ln, lh in zip(lines, heights):
        box = draw.textbbox((0, 0), ln, font=font)
        width = draw.textlength(ln, font=font)
        x = min(max(cx - width / 2, 0), max(w - width, 0))
        draw.text((x, y - box[1] + (lh - box[3] + box[1]) * 0), ln, font=font, fill=ink)
        y += lh + gap


def _cover(image, size):
    """The picture scaled to fill `size`, the overflow cut off evenly."""
    from PIL import Image

    w, h = size
    scale = max(w / image.width, h / image.height)
    scaled = image.convert("RGB").resize((max(w, round(image.width * scale)), max(h, round(image.height * scale))), Image.LANCZOS)
    left, top = (scaled.width - w) // 2, (scaled.height - h) // 2
    return scaled.crop((left, top, left + w, top + h))


def _draw_progress(img, progress):
    from PIL import ImageDraw

    w, h = img.size
    bar = max(4, h // 8)
    draw = ImageDraw.Draw(img)
    draw.rectangle((0, h - bar, w, h), fill=(20, 20, 20))
    draw.rectangle((0, h - bar, round(w * min(max(progress, 0), 1)), h), fill=(255, 255, 255))


def _draw_symbol(draw, name, area, ink):
    """One of the built-in symbols, drawn with shapes so it stays sharp at any key size."""
    import math

    x0, y0, x1, y1 = area
    cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
    r = min(x1 - x0, y1 - y0) * 0.36
    lw = max(2, round(r * 0.3))

    def arrow_head(angle, forward):
        """A head at the point of the circle of radius r at `angle` degrees (clockwise from 3 o'clock), pointing
        along the circle (`forward` 1 clockwise, -1 counterclockwise)."""
        a = math.radians(angle)
        px, py = cx + r * math.cos(a), cy + r * math.sin(a)
        nx, ny = math.cos(a), math.sin(a)                       # outward
        tx, ty = -math.sin(a) * forward, math.cos(a) * forward   # direction of travel
        wide, long_ = r * 0.62, r * 0.85
        draw.polygon([(px + nx * wide, py + ny * wide), (px - nx * wide, py - ny * wide), (px + tx * long_, py + ty * long_)], fill=ink)

    if name == "start":
        draw.polygon([(cx - r * 0.7, cy - r), (cx - r * 0.7, cy + r), (cx + r * 0.95, cy)], fill=ink)
    elif name == "next_game":
        for shift in (-0.5, 0.5):
            x = cx + shift * r
            draw.polygon([(x - r * 0.55, cy - r * 0.85), (x - r * 0.55, cy + r * 0.85), (x + r * 0.55, cy)], fill=ink)
    elif name == "cancel":
        draw.line([(cx - r * 0.85, cy - r * 0.85), (cx + r * 0.85, cy + r * 0.85)], fill=ink, width=lw)
        draw.line([(cx - r * 0.85, cy + r * 0.85), (cx + r * 0.85, cy - r * 0.85)], fill=ink, width=lw)
    elif name == "sound":
        draw.polygon([(cx - r * 1.0, cy - r * 0.35), (cx - r * 0.45, cy - r * 0.35), (cx + r * 0.15, cy - r * 0.9),
                      (cx + r * 0.15, cy + r * 0.9), (cx - r * 0.45, cy + r * 0.35), (cx - r * 1.0, cy + r * 0.35)], fill=ink)
        for k in (0.55, 1.0):
            draw.arc((cx + r * 0.15 - r * k * 0.5, cy - r * k * 0.8, cx + r * 0.15 + r * k * 1.0, cy + r * k * 0.8), start=-50, end=50, fill=ink, width=max(2, lw // 2))
    elif name == "fun":
        draw.ellipse((cx - r, cy - r, cx + r, cy + r), outline=ink, width=lw)
        for dx in (-0.4, 0.4):
            draw.ellipse((cx + r * dx - r * 0.13, cy - r * 0.4 - r * 0.13, cx + r * dx + r * 0.13, cy - r * 0.4 + r * 0.13), fill=ink)
        draw.arc((cx - r * 0.55, cy - r * 0.35, cx + r * 0.55, cy + r * 0.6), start=20, end=160, fill=ink, width=max(2, lw // 2))
    elif name == "folder":
        draw.rectangle((cx - r * 1.1, cy - r * 0.6, cx + r * 1.1, cy + r * 0.8), fill=ink)
        draw.rectangle((cx - r * 1.1, cy - r * 0.95, cx - r * 0.1, cy - r * 0.5), fill=ink)
    elif name == "back":
        draw.polygon([(cx - r * 0.2, cy - r), (cx - r * 1.0, cy), (cx - r * 0.2, cy + r)], fill=ink)
        draw.rectangle((cx - r * 0.2, cy - r * 0.3, cx + r * 0.95, cy + r * 0.3), fill=ink)
    elif name in ("page_prev", "page_next"):
        sign = -1 if name == "page_prev" else 1
        draw.line([(cx - sign * r * 0.45, cy - r), (cx + sign * r * 0.55, cy), (cx - sign * r * 0.45, cy + r)], fill=ink, width=lw, joint="curve")
    elif name == "reset":
        draw.arc((cx - r, cy - r, cx + r, cy + r), start=-50, end=235, fill=ink, width=lw)
        arrow_head(235, 1)
    elif name == "undo":
        draw.arc((cx - r, cy - r, cx + r, cy + r), start=270, end=130, fill=ink, width=lw)
        arrow_head(270, -1)
    elif name == "next_player":
        draw.ellipse((cx - r * 0.95, cy - r * 0.95, cx - r * 0.15, cy - r * 0.15), fill=ink)
        draw.pieslice((cx - r * 1.2, cy, cx, cy + r * 1.6), start=180, end=360, fill=ink)
        draw.polygon([(cx + r * 0.15, cy - r * 0.55), (cx + r * 0.15, cy + r * 0.75), (cx + r * 1.0, cy + r * 0.1)], fill=ink)


def _draw_label(img, label, ink, area, big=False):
    """The label centered in `area` (x0, y0, x1, y1), as large as fits (`big` starts from a larger size, for a value)."""
    from PIL import ImageDraw, ImageFont

    x0, y0, x1, y1 = (round(v) for v in area)
    w, h = x1 - x0, y1 - y0
    draw = ImageDraw.Draw(img)
    words = label.split()
    for pt in range(max(10, round(h * 0.8) if big else (h // 3 if h < img.size[1] else img.size[1] // 4)), 7, -1):
        font = ImageFont.load_default(size=pt)
        lines = _wrap(draw, words, font, w - 8)
        height = sum(draw.textbbox((0, 0), ln, font=font)[3] + 4 for ln in lines)
        if height <= h - 6 and all(draw.textlength(ln, font=font) <= w - 8 for ln in lines):
            break
    y = y0 + (h - height) // 2
    for ln in lines:
        box = draw.textbbox((0, 0), ln, font=font)
        draw.text((x0 + (w - draw.textlength(ln, font=font)) / 2, y - box[1]), ln, font=font, fill=ink)
        y += box[3] + 4


def _wrap(draw, words, font, width):
    lines, line = [], ""
    for word in words:
        trial = f"{line} {word}".strip()
        if line and draw.textlength(trial, font=font) > width:
            lines.append(line)
            line = word
        else:
            line = trial
    if line:
        lines.append(line)
    return lines


def library_available():
    """True when the USB library and Pillow can be imported (the HID backend itself is only known at enumerate)."""
    try:
        import PIL  # noqa: F401
        import StreamDeck  # noqa: F401
        return True
    except Exception:
        return False


def _enumerate_decks():
    from StreamDeck.DeviceManager import DeviceManager
    return DeviceManager().enumerate()


def _to_native(deck, image):
    from StreamDeck.ImageHelpers import PILHelper
    return PILHelper.to_native_key_format(deck, image)


class StreamDeckService:
    """Keeps the first Stream Deck found open, draws the keys and runs the action of a pressed key.

    `run_control(action)` runs a board control by its name (see ACTIONS); `enumerate_decks`, `to_native` and `request` are
    the seams the tests replace."""

    def __init__(self, config_path, run_control, enumerate_decks=None, to_native=None, reconnect_seconds=RECONNECT_SECONDS,
                 web_base=lambda: "http://127.0.0.1:8080", request=None, values=None, flags=None, sounds=None):
        self.config_path = config_path
        self.run_control = run_control
        self._enumerate = enumerate_decks or _enumerate_decks
        self._to_native = to_native or _to_native
        self._reconnect = reconnect_seconds
        self._web_base = web_base           # where the routes of Breakfast itself answer
        self._values = values or (lambda: None)   # what a display key can show of the game in play
        self._flags = flags or (lambda: {})       # switches a key shows the state of, e.g. {"fun_mode": True}
        self._sounds = sounds or (lambda: [])     # the sound files a key can play
        self._vals = None                   # the last result of it, read outside the lock
        self._shown = {}                    # key -> the value text the key shows now
        self._flash_until = 0
        self._flash_phase = False
        self._request = request             # the HTTP call of a custom action, replaced in the tests
        self._lock = threading.RLock()
        self._stop = threading.Event()
        self._thread = None
        self._deck = None
        self._error = None
        self._pictures = {}                 # file name -> (mtime, PIL image), the pictures of the keys
        self._cfg_stamp, self._cfg_cached = None, {}
        self._virtual_pages = 1
        self._folder, self._page, self._trail = None, 0, []   # the folder and page in view on the device, and the way back
        self._effect_drawn = {}             # key -> what its effect looked like when it was drawn last
        self._holds = {}                    # key -> Event that cancels the hold of a key being held
        self._hold_step = HOLD_STEP_SECONDS
        self.board_status = None

    # ---- config ----
    def _cfg(self):
        """The [streamdeck] table, read again only when the file has changed."""
        if not self.config_path:
            return {}
        try:
            stat = os.stat(self.config_path)
            stamp = (stat.st_mtime_ns, stat.st_size)
        except OSError:
            stamp = None
        if stamp is None or stamp != self._cfg_stamp:
            self._cfg_cached = cfg_mod.load(self.config_path).get("streamdeck", {})
            self._cfg_stamp = stamp
        return self._cfg_cached

    def enabled(self):
        return self._cfg().get("enabled") is True

    def actions(self):
        try:
            return clean_actions(self._cfg().get("actions", []))
        except ValueError:
            log.warning("The [streamdeck] actions in config.toml are not valid, ignored")
            return []

    def folders(self):
        try:
            return clean_folders(self._cfg().get("folders", []), {a["id"] for a in self.actions()})
        except ValueError:
            log.warning("The [streamdeck] folders in config.toml are not valid, ignored")
            return []

    def keys(self):
        cfg = self._cfg()
        try:
            return clean_keys(cfg.get("keys", []), {a["id"] for a in self.actions()}, {f["id"] for f in self.folders()})
        except ValueError:
            log.warning("The [streamdeck] keys in config.toml are not valid, ignored")
            return []

    def overrides(self):
        try:
            return clean_overrides(self._cfg().get("overrides", []))
        except ValueError:
            log.warning("The [streamdeck] overrides in config.toml are not valid, ignored")
            return []

    def brightness(self):
        value = self._cfg().get("brightness", DEFAULT_BRIGHTNESS)
        return value if isinstance(value, int) and not isinstance(value, bool) and 0 <= value <= 100 else DEFAULT_BRIGHTNESS

    def update(self, enabled=None, brightness=None, keys=None, actions=None, overrides=None, folders=None):
        """Save a change of the settings and apply it at once. Raises ValueError for a bad value."""
        changes = {}
        if enabled is not None:
            if not isinstance(enabled, bool):
                raise ValueError("enabled must be true or false")
            changes["enabled"] = enabled
        if brightness is not None:
            if not isinstance(brightness, int) or isinstance(brightness, bool) or not 0 <= brightness <= 100:
                raise ValueError("brightness must be a number from 0 to 100")
            changes["brightness"] = brightness
        if overrides is not None:
            changes["overrides"] = clean_overrides(overrides)
        custom = clean_actions(actions) if actions is not None else self.actions()
        ids = {a["id"] for a in custom}
        if actions is not None:
            changes["actions"] = custom
        if folders is not None:
            new_folders = clean_folders(folders, ids)
        else:
            new_folders = self.folders()
        folder_ids = {f["id"] for f in new_folders}
        if folders is not None:
            # a key that opened a deleted folder goes with it
            changes["folders"] = [{**f, "keys": prune_keys(f["keys"], ids, folder_ids)} for f in new_folders]
        if keys is not None:
            changes["keys"] = clean_keys(keys, ids, folder_ids)
        elif actions is not None or folders is not None:
            # a key whose custom action or folder was deleted goes with it
            changes["keys"] = prune_keys(self.keys(), ids, folder_ids)
        if actions is not None:
            for f in (changes.get("folders") or new_folders):
                f["keys"] = prune_keys(f["keys"], ids, folder_ids)
            changes["folders"] = changes.get("folders") or new_folders
        if changes:
            cfg_mod.write(self.config_path, {"streamdeck": changes})
        with self._lock:
            if self._deck is not None:
                if brightness is not None:
                    self._guard(lambda: self._deck.set_brightness(self.brightness()))
                self._draw()

    # ---- life cycle ----
    def start(self):
        if self._thread is None:
            self._thread = threading.Thread(target=self._run, name="streamdeck", daemon=True)
            self._thread.start()
            threading.Thread(target=self._animate, name="streamdeck-effects", daemon=True).start()

    def _animate(self):
        """Draw the keys with an effect again whenever the effect has moved on to another step."""
        while not self._stop.wait(EFFECT_TICK_SECONDS):
            try:
                with self._lock:
                    if self._deck is None:
                        continue
                    by_key = self._view_keys()
                    now = time.monotonic()
                    for index in range(self._deck.key_count()):
                        entry = by_key.get(index)
                        effect = self._effect_for(entry)
                        if effect and index not in self._holds and self._effect_drawn.get(index) != effect_signature(effect, now):
                            self._draw_key(index, entry)
            except Exception as e:
                log.error("Stream Deck effects: %s", e)

    def stop(self):
        self._stop.set()
        with self._lock:
            self._close()

    def _run(self):
        while not self._stop.is_set():
            try:
                if self._deck is not None:
                    self.refresh_values()
                with self._lock:
                    if not self.enabled():
                        self._close()
                        self._error = None
                    elif self._deck is not None and not self._deck.connected():
                        log.info("The Stream Deck was unplugged")
                        self._close()
                    if self.enabled() and self._deck is None:
                        self._connect()
            except Exception as e:
                log.error("Stream Deck: %s", e)
            self._stop.wait(self._reconnect)

    def _connect(self):
        self._vals = None            # read again with the next round of the loop; the first drawing shows the labels
        try:
            decks = self._enumerate()
        except Exception as e:
            self._error = "no_hid_backend" if type(e).__name__ == "ProbeError" else str(e)
            return
        if not decks:
            self._error = None
            return
        deck = decks[0]
        deck.open()
        deck.reset()
        deck.set_brightness(self.brightness())
        deck.set_key_callback(self._on_key)
        self._deck = deck
        self._error = None
        log.info("Stream Deck connected: %s", deck.deck_type())
        self._draw()

    def _close(self):
        for held in self._holds.values():
            held.set()
        self._holds.clear()
        deck, self._deck = self._deck, None
        if deck is None:
            return
        try:
            deck.reset()
            deck.close()
        except Exception:
            pass

    def _guard(self, fn):
        try:
            fn()
        except Exception as e:
            log.warning("Stream Deck: %s", e)

    # ---- keys ----
    def on_board_status(self, status):
        with self._lock:
            if status == self.board_status:
                return
            self.board_status = status
            if self._deck is not None:
                self._draw()

    def _view_keys(self):
        """The keys the device shows now, by position: those of the folder and page in view, and the keys that go back and
        page, which take the place of whatever the layout has there."""
        count = self._deck.key_count() if self._deck is not None else DEFAULT_ROWS * DEFAULT_COLS
        if self._folder and self._folder.startswith(VIRTUAL):
            return self._correction_view(count)
        folder = next((f for f in self.folders() if f["id"] == self._folder), None) if self._folder else None
        if self._folder and folder is None:
            self._folder, self._page, self._trail = None, 0, []
        keys = folder["keys"] if folder else self.keys()
        pages = page_count(keys)
        self._page = min(self._page, pages - 1)
        view = {k["key"]: k for k in keys if k.get("page", 0) == self._page and k["key"] < count}

        def nav(index, action, label, symbol):
            view[index] = {"key": index, "action": action, "label": label, "color": NAV_COLOR, "hold": 0, "image": SYMBOL_PREFIX + symbol,
                           "show": ""}
        if folder and count > 0:
            nav(0, NAV_BACK, "Back", "back")
        if pages > 1 and count > 2:
            nav(count - 2, NAV_PREV, "", "page_prev")
            nav(count - 1, NAV_NEXT, f"{self._page + 1}/{pages}", "page_next")
        return view

    def _draw(self):
        deck = self._deck
        if deck is None:
            return
        view = self._view_keys()
        self._effect_drawn.clear()
        for index in range(deck.key_count()):
            self._draw_key(index, view.get(index))

    def _correction_items(self):
        """The keys of the dart correction in view: first the kind of hit, then the number of the field."""
        parts = self._folder[len(VIRTUAL):].split(":")      # ["1"] or ["1", "T"]
        dart = parts[0]
        if len(parts) == 1:
            return [{"action": f"{CORRECT_PREFIX}{dart}:{code}", "label": name, "color": "#000000", "image": "", "design": None}
                    for code, name in RINGS]
        ring = parts[1]
        numbers = [str(n) for n in range(1, 21)] + ([] if ring == "T" else ["25"])
        return [{"action": f"{CORRECT_PREFIX}{dart}:{ring}:{n}", "label": ("Bull" if n == "25" and ring == "D" else n),
                 "color": "#000000", "image": "", "design": None} for n in numbers]

    def _correction_view(self, count):
        """The device while a dart is being corrected: Back at key 0, the choices after it and, when they do not fit, page keys."""
        items = self._correction_items()
        paged = len(items) > count - 1
        capacity = max(1, count - 3 if paged else count - 1)
        pages = -(-len(items) // capacity)
        self._page = min(self._page, pages - 1)
        view = {}
        for slot, item in enumerate(items[self._page * capacity:(self._page + 1) * capacity], start=1):
            view[slot] = {"key": slot, "hold": 0, "show": "", **item}
        view[0] = {"key": 0, "action": NAV_BACK, "label": "Back", "color": NAV_COLOR, "hold": 0, "image": SYMBOL_PREFIX + "back", "show": ""}
        if paged and count > 3:
            view[count - 2] = {"key": count - 2, "action": NAV_PREV, "label": "", "color": NAV_COLOR, "hold": 0,
                               "image": SYMBOL_PREFIX + "page_prev", "show": ""}
            view[count - 1] = {"key": count - 1, "action": NAV_NEXT, "label": f"{self._page + 1}/{pages}", "color": NAV_COLOR, "hold": 0,
                               "image": SYMBOL_PREFIX + "page_next", "show": ""}
        self._virtual_pages = pages
        return view

    def _correct(self, action):
        """A choice of the dart correction: a ring opens the numbers, a number (or a miss) corrects the dart and goes back to
        the key that opened the correction."""
        _, dart, *rest = action.split(":")
        if len(rest) == 1 and rest[0] in ("S", "D", "T"):
            self._trail.append((self._folder, self._page))
            self._folder, self._page = f"{VIRTUAL}{dart}:{rest[0]}", 0
            self._draw()
            return
        if len(rest) == 2:
            ring, number = rest
            field = number if number == "25" and ring == "S" else "50" if number == "25" else f"{ring}{number}"
        else:
            field = "0"
        while self._folder and self._folder.startswith(VIRTUAL):
            self._folder, self._page = self._trail.pop() if self._trail else (None, 0)
        self._draw()
        self._run_action(-1, {"action": f"correct_dart:{dart}:{field}"})

    def _navigate(self, action):
        """Go back, to the next or previous page, or into a folder; then draw the keys of the new view."""
        if action == NAV_BACK:
            self._folder, self._page = self._trail.pop() if self._trail else (None, 0)
        elif action in (NAV_NEXT, NAV_PREV):
            if self._folder and self._folder.startswith(VIRTUAL):
                self._view_keys()
                pages = self._virtual_pages
            else:
                folder = next((f for f in self.folders() if f["id"] == self._folder), None)
                pages = page_count(folder["keys"] if folder else self.keys())
            self._page = (self._page + (1 if action == NAV_NEXT else -1)) % pages
        elif action.startswith(CORRECT_PREFIX):
            self._trail.append((self._folder, self._page))
            self._folder, self._page = f"{VIRTUAL}{action[len(CORRECT_PREFIX):]}", 0
        else:
            self._trail.append((self._folder, self._page))
            self._folder, self._page = action[len(FOLDER_PREFIX):], 0
        self._draw()

    def _sound_list(self):
        try:
            return [n for n in self._sounds() if SOUND_NAME.match(n)]
        except Exception:
            return []

    def go_home(self):
        """Show the first page of the main layout again."""
        with self._lock:
            self._folder, self._page, self._trail = None, 0, []
            self._draw()

    def _draw_key(self, index, entry, progress=None):
        deck = self._deck
        if deck is None:
            return
        size = deck.key_image_format()["size"]
        now = time.monotonic()
        effect = self._effect_for(entry)
        self._effect_drawn[index] = effect_signature(effect, now) if effect else None
        image = self._render(entry, size, progress, now)
        self._guard(lambda: deck.set_key_image(index, self._to_native(deck, image)))

    def on_flags_change(self):
        """A switch a key shows has changed (the fun mode): draw the keys again."""
        with self._lock:
            if self._deck is not None:
                self._draw()

    def _effective(self, entry):
        """The key as it works now: while the board is stopped a Reset Board key becomes a Start Board key, and a Fun Mode
        key says whether the mode is on."""
        if entry["action"] == "fun_mode" and entry["label"] == ACTIONS["fun_mode"]:
            try:
                on = bool(self._flags().get("fun_mode"))
            except Exception:
                on = False
            return {**entry, "label": ACTIONS["fun_mode"] + (" on" if on else " off")}
        if entry["action"] == "reset_board" and board_stopped(self.board_status):
            changes = {"action": "start_board"}
            if entry["label"] == ACTIONS["reset_board"]:
                changes["label"] = ACTIONS["start_board"]
            if entry["image"] == SYMBOL_PREFIX + "reset":
                changes["image"] = SYMBOL_PREFIX + "start"
            if entry.get("design"):
                layers = [{**la, "text": ACTIONS["start_board"]} if la["kind"] == "text" and la["text"] == ACTIONS["reset_board"]
                          else {**la, "image": SYMBOL_PREFIX + "start"} if la["kind"] == "image" and la["image"] == SYMBOL_PREFIX + "reset"
                          else la for la in entry["design"]["layers"]]
                changes["design"] = {**entry["design"], "layers": layers}
            return {**entry, **changes}
        return entry

    def _effect_for(self, entry):
        """The effect a key shows now: the rule of the board status when there is one (unless the key ignores the rules),
        else the effect of the key itself."""
        if not (entry and entry.get("ignore_override")):
            status = status_color(self.board_status)
            for rule in self.overrides():
                if rule["status"] == status:
                    return rule["effect"]
        return entry.get("effect") if entry else None

    def _render(self, entry, size, progress=None, now=None):
        image = self._base(entry, size, progress)
        effect = self._effect_for(entry)
        return apply_effect(image, effect, time.monotonic() if now is None else now) if effect else image

    def _base(self, entry, size, progress=None):
        if not entry:
            return render_key("", STATUS_COLORS["off"], size)
        entry = self._effective(entry)
        picture, symbol = self._picture(entry["image"])
        value = self._value_of(entry)
        self._shown[entry["key"]] = value
        color = FLASH_COLOR if self._flash_on(entry) else key_hex(entry, self.board_status)
        if entry.get("design"):
            return render_design(entry["design"], color, size, self._picture, self._vals, progress)
        return render_key(entry["label"], color, size, progress, picture, symbol, value)

    @staticmethod
    def _live(entry):
        """True for a key that shows something of the game: a display key or a design with a {token} in a text."""
        if entry["show"]:
            return True
        return any(token in layer["text"] for layer in (entry.get("design") or {}).get("layers", []) if layer["kind"] == "text"
                   for token in ("{%s}" % t for t in VALUE_TOKENS))

    def _value_of(self, entry):
        """The text a display key shows now, None for any other key or while the game has no such value."""
        if not self._live(entry) or not self._vals:
            return None
        if entry["show"]:
            value = self._vals.get(entry["show"])
            return None if value is None else str(value)
        return "|".join(str(self._vals.get(t)) for t in VALUE_TOKENS)

    def _flash_on(self, entry):
        return self._live(entry) and self._flash_phase and time.monotonic() < self._flash_until

    # ---- the game ----
    def refresh_values(self):
        """Read the game once, outside the lock of the device: a game holds its own lock while it tells the page."""
        try:
            self._vals = self._values()
        except Exception:
            self._vals = None

    def on_game_change(self):
        """Called whenever the state of a game changes: redraw the display keys whose value is not the one shown."""
        if self._deck is None:
            return
        self.refresh_values()
        with self._lock:
            for entry in self._view_keys().values():
                if self._live(entry) and self._value_of(entry) != self._shown.get(entry["key"]):
                    self._draw_key(entry["key"], entry)

    def flash(self, seconds=FLASH_SECONDS):
        """Make the display keys flash, for an earned achievement."""
        if self._deck is None:
            return
        with self._lock:
            running = time.monotonic() < self._flash_until
            self._flash_until = time.monotonic() + seconds
        if not running:
            threading.Thread(target=self._flash, name="streamdeck-flash", daemon=True).start()

    def _flash(self):
        self._flash_phase = True
        while time.monotonic() < self._flash_until and not self._stop.is_set():
            with self._lock:
                for entry in self._view_keys().values():
                    if self._live(entry):
                        self._draw_key(entry["key"], entry)
            self._flash_phase = not self._flash_phase
            time.sleep(FLASH_STEP_SECONDS)
        self._flash_phase = False
        with self._lock:
            self._draw()

    # ---- images ----
    def image_dir(self):
        return Path(self.config_path).parent / IMAGE_DIR_NAME

    def _picture(self, value):
        """(picture, symbol) of an `image` value: a PIL image of the uploaded file, or the name of a symbol. A missing or
        broken file draws the key without a picture."""
        if value.startswith(SYMBOL_PREFIX):
            return None, value[len(SYMBOL_PREFIX):]
        if not value:
            return None, None
        path = self.image_dir() / value
        try:
            mtime = path.stat().st_mtime
            cached = self._pictures.get(value)
            if cached is None or cached[0] != mtime:
                from PIL import Image
                with Image.open(path) as opened:
                    cached = self._pictures[value] = (mtime, opened.convert("RGB"))
            return cached[1], None
        except Exception:
            self._pictures.pop(value, None)
            return None, None

    def images(self):
        folder = self.image_dir()
        if not folder.is_dir():
            return []
        return sorted(f.name for f in folder.iterdir() if f.is_file() and IMAGE_NAME.match(f.name))

    def save_image(self, name, data):
        """Store an uploaded picture; raises ValueError with a message for the UI."""
        if not IMAGE_NAME.match(name or ""):
            raise ValueError("the file name has to end in .png, .jpg or .webp and may not contain a path")
        if not data or len(data) > MAX_IMAGE_BYTES:
            raise ValueError("the image has to be at most %d MB" % (MAX_IMAGE_BYTES // 1_000_000))
        try:
            from PIL import Image
            with Image.open(io.BytesIO(data)) as opened:
                opened.verify()
            with Image.open(io.BytesIO(data)) as opened:
                if opened.width > 4000 or opened.height > 4000:
                    raise ValueError("the image is larger than 4000 pixels")
        except ValueError:
            raise
        except Exception:
            raise ValueError("the file is not a picture")
        folder = self.image_dir()
        folder.mkdir(parents=True, exist_ok=True)
        tmp = folder / (name + ".part")
        tmp.write_bytes(data)
        os.replace(tmp, folder / name)
        self._pictures.pop(name, None)
        with self._lock:
            self._draw()

    def delete_image(self, name):
        """Delete an uploaded picture; the keys that showed it lose their image."""
        if not IMAGE_NAME.match(name or ""):
            raise ValueError("unknown image")
        path = self.image_dir() / name
        if not path.is_file():
            raise ValueError("unknown image")
        path.unlink()
        self._pictures.pop(name, None)
        keys, folders = self.keys(), self.folders()
        clear = lambda ks: [{**k, "image": "" if k["image"] == name else k["image"]} for k in ks]
        if any(k["image"] == name for k in keys + [k for f in folders for k in f["keys"]]):
            self.update(keys=clear(keys), folders=[{**f, "keys": clear(f["keys"])} for f in folders])
        else:
            with self._lock:
                self._draw()

    def preview(self, key, folder=None, page=0):
        """The PNG of a configured key as the device shows it now (None for a key without an action)."""
        layout = next((f["keys"] for f in self.folders() if f["id"] == folder), []) if folder else self.keys()
        entry = next((k for k in layout if k["key"] == key and k.get("page", 0) == page), None)
        if entry is None:
            return None
        self.refresh_values()
        out = io.BytesIO()
        self._render(entry, PREVIEW_SIZE).save(out, "PNG")
        return out.getvalue()

    def preview_entry(self, entry, size=EDITOR_PREVIEW_SIZE):
        """The PNG of a key that is still being edited (not saved), as the device would draw it now. Raises ValueError."""
        clean = clean_keys([{**entry, "key": 0}], {a["id"] for a in self.actions()})[0]
        self.refresh_values()
        out = io.BytesIO()
        self._render(clean, size).save(out, "PNG")
        return out.getvalue()

    def _on_key(self, deck, key, pressed):
        with self._lock:
            held = self._holds.pop(key, None)
            if held:
                held.set()                 # the key was let go before the hold was over, or pressed again
                self._draw_key(key, self._view_keys().get(key))
            if not pressed:
                return
            entry = self._view_keys().get(key)
            if entry is None:
                return
            if not entry["action"]:
                return
            if entry["action"] in (NAV_BACK, NAV_NEXT, NAV_PREV) or entry["action"].startswith(FOLDER_PREFIX):
                self._navigate(entry["action"])
                return
            if entry["action"] in ("correct_dart:1", "correct_dart:2", "correct_dart:3"):
                self._navigate(entry["action"])
                return
            if entry["action"].startswith(CORRECT_PREFIX):
                self._correct(entry["action"])
                return
            entry = self._effective(entry)
            if entry["hold"] > 0:
                cancelled = self._holds[key] = threading.Event()
                threading.Thread(target=self._hold, args=(key, entry, cancelled), name="streamdeck-hold", daemon=True).start()
                return
        self._run_action(key, entry)

    def _hold(self, key, entry, cancelled):
        """Draw the progress of a held key; run its action when the hold is over."""
        start = time.monotonic()
        while True:
            elapsed = time.monotonic() - start
            if cancelled.is_set():
                return
            if elapsed >= entry["hold"]:
                break
            with self._lock:
                if not cancelled.is_set():
                    self._draw_key(key, entry, elapsed / entry["hold"])
            cancelled.wait(self._hold_step)
        with self._lock:
            if cancelled.is_set():
                return
            self._holds.pop(key, None)
            self._draw_key(key, entry)
        self._run_action(key, entry)

    def _run_action(self, key, entry):
        log.info("Stream Deck key %d: %s", key, entry["action"])
        try:
            if entry["action"] in ACTIONS or entry["action"].startswith((SOUND_PREFIX, CORRECT_PREFIX)):
                result = self.run_control(entry["action"])
                if isinstance(result, dict) and result.get("error"):
                    log.warning("Stream Deck key %d: %s", key, result["error"])
                return
            action = next((a for a in self.actions() if a["id"] == entry["action"]), None)
            if action is None:
                log.warning("Stream Deck key %d: the action %s no longer exists", key, entry["action"])
                return
            self._run_custom(key, action)
        except Exception as e:
            log.error("Stream Deck key %d failed: %s", key, e)

    def _run_custom(self, key, action):
        """Send the request of a custom action in a thread of its own, so a slow target holds up no other key. Only the
        name of the action is logged: an address can carry a secret."""
        url = action["target"] if action["kind"] == "url" else self._web_base().rstrip("/") + action["target"]
        kwargs = {"timeout": REQUEST_TIMEOUT_SECONDS}
        if action["body"]:
            try:
                kwargs["json"] = json.loads(action["body"])
            except ValueError:
                kwargs["data"] = action["body"].encode()
                kwargs["headers"] = {"Content-Type": "text/plain; charset=utf-8"}

        def send():
            request = self._request
            if request is None:
                import requests
                request = requests.request
            try:
                response = request(action["method"], url, **kwargs)
                if response.status_code >= 400:
                    log.warning("Stream Deck key %d: %s answered %s", key, action["name"], response.status_code)
                else:
                    log.info("Stream Deck key %d: %s sent", key, action["name"])
            except Exception as e:
                log.error("Stream Deck key %d: %s failed: %s", key, action["name"], type(e).__name__)

        threading.Thread(target=send, name="streamdeck-request", daemon=True).start()

    # ---- state for the page ----
    def snapshot(self):
        self.refresh_values()
        with self._lock:
            deck = self._deck
            rows, cols = (deck.key_layout() if deck is not None else (DEFAULT_ROWS, DEFAULT_COLS))
            keys = self.keys()
            describe = lambda k: {**k, "shown": key_hex(k, self.board_status), "value": self._value_of(k)}
            return {
                "enabled": self.enabled(),
                "library": library_available(),
                "connected": deck is not None,
                "device_error": self._error,
                "model": deck.deck_type() if deck is not None else None,
                "rows": rows,
                "cols": cols,
                "brightness": self.brightness(),
                "board_status": self.board_status,
                "status_color": status_color(self.board_status),
                "colors": STATUS_COLORS,
                "actions": [{"id": k, "label": v, "custom": False} for k, v in ACTIONS.items()]
                           + [{"id": a["id"], "label": a["name"], "custom": True} for a in self.actions()],
                "sounds": self._sound_list(),
                "folder_actions": [{"id": FOLDER_PREFIX + f["id"], "label": f["name"]} for f in self.folders()],
                "custom_actions": self.actions(),
                "images": self.images(),
                "symbols": list(SYMBOLS),
                "show_values": list(SHOW_VALUES),
                "value_tokens": list(VALUE_TOKENS),
                "effects": list(EFFECTS),
                "override_statuses": list(OVERRIDE_STATUSES),
                "overrides": self.overrides(),
                "keys": [describe(k) for k in keys],
                "folders": [{**f, "keys": [describe(k) for k in f["keys"]]} for f in self.folders()],
                "max_pages": MAX_PAGES,
            }
