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
}

STATUS_COLORS = {
    "green": "#1faa59",
    "yellow": "#e6a800",
    "red": "#cc2a2a",
    "off": "#2b2b2f",
}
DEFAULT_BRIGHTNESS = 60
# Shown while no device is connected, so the layout can be set up first (a 15-key Stream Deck).
DEFAULT_ROWS, DEFAULT_COLS = 3, 5
MAX_KEYS = 64
MAX_ACTIONS = 32
HTTP_METHODS = ("GET", "POST", "PUT", "PATCH", "DELETE")
REQUEST_TIMEOUT_SECONDS = 5
SYMBOLS = ("reset", "start", "undo", "next_player", "next_game")   # drawn by Breakfast, no file needed
SYMBOL_PREFIX = "symbol:"
SHOW_VALUES = ("player", "remaining", "lives", "darts", "round")   # what a display key shows of the game in play
FLASH_SECONDS = 3
FLASH_STEP_SECONDS = 0.4
FLASH_COLOR = "#e6a800"
IMAGE_NAME = re.compile(r"^\w[\w .\-]{0,78}\.(png|jpe?g|webp)$", re.IGNORECASE)
MAX_IMAGE_BYTES = 2_000_000
IMAGE_DIR_NAME = "streamdeck"       # next to config.toml
PREVIEW_SIZE = (96, 96)
MAX_HOLD_SECONDS = 5
DEFAULT_HOLD_SECONDS = 0.8
HOLD_STEP_SECONDS = 0.08   # how often the progress bar of a held key is drawn
RECONNECT_SECONDS = 3


def status_color(board_status):
    """The color name for a board status: green when ready to throw, yellow around the take-out and while the board
    starts, red when it is stopped or gone, off when unknown."""
    if not board_status:
        return "off"
    s = board_status.strip().lower()
    if s == "throw" or s == "takeout finished":
        return "green"
    if s.startswith("takeout") or s in ("board starting", "board started"):
        return "yellow"
    if s in ("board stopped", "board stopping", "board disconnected"):
        return "red"
    return "off"


def _valid_hex(value):
    return (isinstance(value, str) and len(value) == 7 and value[0] == "#"
            and all(c in "0123456789abcdefABCDEF" for c in value[1:]))


def clean_actions(actions):
    """The custom actions as stored: a list of `{id, name, kind, method, target, body}`.

    `kind` is `route` (a route of Breakfast, `target` is a path under /api/) or `url` (any http(s) address, with an
    optional `body`). An action without an id gets one. Raises ValueError with a message for the UI."""
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
                    "body": body if kind == "url" else ""})
    return out


def clean_keys(keys, custom_ids=()):
    """The layout as stored: unknown actions and bad colors refused, one entry per key, sorted by key.
    `custom_ids` are the ids of the custom actions a key may use besides the built-in ones.

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
            if action not in ACTIONS and action not in custom_ids:
                raise ValueError(f"unknown action: {action}")
        elif not show:
            raise ValueError("a key needs an action or a value to show")
        label = entry.get("label")
        label = ACTIONS.get(action, "") if label is None else str(label)[:40]
        color = entry.get("color", "status")
        if color != "status" and not _valid_hex(color):
            raise ValueError("color must be 'status' or #rrggbb")
        hold = entry.get("hold", 0)
        if isinstance(hold, bool) or not isinstance(hold, (int, float)) or not 0 <= hold <= MAX_HOLD_SECONDS:
            raise ValueError("hold must be a number of seconds from 0 to %d" % MAX_HOLD_SECONDS)
        image = entry.get("image", "")
        if not valid_image(image):
            raise ValueError("image must be empty, symbol:<name> or the name of an uploaded png, jpg or webp file")
        out[key] = {"key": key, "action": action, "label": label, "color": color.lower(), "hold": hold, "image": image, "show": show}
    return [out[k] for k in sorted(out)]


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
                 web_base=lambda: "http://127.0.0.1:8080", request=None, values=None):
        self.config_path = config_path
        self.run_control = run_control
        self._enumerate = enumerate_decks or _enumerate_decks
        self._to_native = to_native or _to_native
        self._reconnect = reconnect_seconds
        self._web_base = web_base           # where the routes of Breakfast itself answer
        self._values = values or (lambda: None)   # what a display key can show of the game in play
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
        self._holds = {}                    # key -> Event that cancels the hold of a key being held
        self._hold_step = HOLD_STEP_SECONDS
        self.board_status = None

    # ---- config ----
    def _cfg(self):
        return cfg_mod.load(self.config_path).get("streamdeck", {}) if self.config_path else {}

    def enabled(self):
        return self._cfg().get("enabled") is True

    def actions(self):
        try:
            return clean_actions(self._cfg().get("actions", []))
        except ValueError:
            log.warning("The [streamdeck] actions in config.toml are not valid, ignored")
            return []

    def keys(self):
        cfg = self._cfg()
        try:
            return clean_keys(cfg.get("keys", []), {a["id"] for a in self.actions()})
        except ValueError:
            log.warning("The [streamdeck] keys in config.toml are not valid, ignored")
            return []

    def brightness(self):
        value = self._cfg().get("brightness", DEFAULT_BRIGHTNESS)
        return value if isinstance(value, int) and not isinstance(value, bool) and 0 <= value <= 100 else DEFAULT_BRIGHTNESS

    def update(self, enabled=None, brightness=None, keys=None, actions=None):
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
        custom = clean_actions(actions) if actions is not None else self.actions()
        ids = {a["id"] for a in custom}
        if actions is not None:
            changes["actions"] = custom
        if keys is not None:
            changes["keys"] = clean_keys(keys, ids)
        elif actions is not None:
            # a key whose custom action was deleted goes with it
            changes["keys"] = [k for k in self.keys() if k["action"] in ACTIONS or k["action"] in ids]
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

    def _draw(self):
        deck = self._deck
        if deck is None:
            return
        by_key = {k["key"]: k for k in self.keys()}
        for index in range(deck.key_count()):
            self._draw_key(index, by_key.get(index))

    def _draw_key(self, index, entry, progress=None):
        deck = self._deck
        if deck is None:
            return
        size = deck.key_image_format()["size"]
        image = self._render(entry, size, progress)
        self._guard(lambda: deck.set_key_image(index, self._to_native(deck, image)))

    def _render(self, entry, size, progress=None):
        if not entry:
            return render_key("", STATUS_COLORS["off"], size)
        picture, symbol = self._picture(entry["image"])
        value = self._value_of(entry)
        self._shown[entry["key"]] = value
        color = FLASH_COLOR if self._flash_on(entry) else key_hex(entry, self.board_status)
        return render_key(entry["label"], color, size, progress, picture, symbol, value)

    def _value_of(self, entry):
        """The text a display key shows now, None for any other key or while the game has no such value."""
        if not entry["show"] or not self._vals:
            return None
        value = self._vals.get(entry["show"])
        return None if value is None else str(value)

    def _flash_on(self, entry):
        return bool(entry["show"]) and self._flash_phase and time.monotonic() < self._flash_until

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
            for entry in self.keys():
                if entry["show"] and self._value_of(entry) != self._shown.get(entry["key"]):
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
                for entry in self.keys():
                    if entry["show"]:
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
        keys = self.keys()
        if any(k["image"] == name for k in keys):
            self.update(keys=[{**k, "image": "" if k["image"] == name else k["image"]} for k in keys])
        else:
            with self._lock:
                self._draw()

    def preview(self, key):
        """The PNG of a configured key as the device shows it now (None for a key without an action)."""
        entry = next((k for k in self.keys() if k["key"] == key), None)
        if entry is None:
            return None
        self.refresh_values()
        out = io.BytesIO()
        self._render(entry, PREVIEW_SIZE).save(out, "PNG")
        return out.getvalue()

    def _on_key(self, deck, key, pressed):
        with self._lock:
            held = self._holds.pop(key, None)
            if held:
                held.set()                 # the key was let go before the hold was over, or pressed again
                self._draw_key(key, next((k for k in self.keys() if k["key"] == key), None))
            if not pressed:
                return
            entry = next((k for k in self.keys() if k["key"] == key), None)
            if entry is None:
                return
            if not entry["action"]:
                return
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
            if entry["action"] in ACTIONS:
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
                "custom_actions": self.actions(),
                "images": self.images(),
                "symbols": list(SYMBOLS),
                "show_values": list(SHOW_VALUES),
                "keys": [{**k, "shown": key_hex(k, self.board_status), "value": self._value_of(k)} for k in keys],
            }
