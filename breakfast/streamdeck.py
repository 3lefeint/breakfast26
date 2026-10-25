"""Stream Deck at the board: keys that run board controls and show the board status.

The device is driven over USB by Breakfast itself (python-elgato-streamdeck), so no other software has to run next to
it. The layout lives in `[streamdeck]` of config.toml: `enabled`, `brightness` and `keys`, a list of
`{key, action, label, color}` (key counts from 0; color is `status` to follow the board or a `#rrggbb` value).

Everything that does not touch the USB device (layout checks, status colors, key drawing, the actions) works without
one, so it is tested without hardware; the device layer is a few calls on the object the library returns.
"""
import io
import logging
import threading

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


def clean_keys(keys):
    """The layout as stored: unknown actions and bad colors dropped, one entry per key, sorted by key.

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
        action = entry.get("action")
        if action not in ACTIONS:
            raise ValueError(f"unknown action: {action}")
        label = entry.get("label")
        label = ACTIONS[action] if label is None else str(label)[:40]
        color = entry.get("color", "status")
        if color != "status" and not _valid_hex(color):
            raise ValueError("color must be 'status' or #rrggbb")
        out[key] = {"key": key, "action": action, "label": label, "color": color.lower()}
    return [out[k] for k in sorted(out)]


def key_hex(entry, board_status):
    """The color a configured key shows right now, as #rrggbb."""
    if entry["color"] == "status":
        return STATUS_COLORS[status_color(board_status)]
    return entry["color"]


def _rgb(hex_color):
    return tuple(int(hex_color[i:i + 2], 16) for i in (1, 3, 5))


def render_key(label, hex_color, size):
    """A square key image: the color as background and the label centered, black or white text by brightness."""
    from PIL import Image, ImageDraw, ImageFont

    w, h = size
    rgb = _rgb(hex_color)
    img = Image.new("RGB", (w, h), rgb)
    if not label:
        return img
    ink = (0, 0, 0) if (rgb[0] * 299 + rgb[1] * 587 + rgb[2] * 114) / 1000 > 140 else (255, 255, 255)
    draw = ImageDraw.Draw(img)
    words = label.split()
    for pt in range(max(10, h // 4), 7, -1):
        font = ImageFont.load_default(size=pt)
        lines = _wrap(draw, words, font, w - 8)
        height = sum(draw.textbbox((0, 0), ln, font=font)[3] + 4 for ln in lines)
        if height <= h - 8 and all(draw.textlength(ln, font=font) <= w - 8 for ln in lines):
            break
    y = (h - height) // 2
    for ln in lines:
        box = draw.textbbox((0, 0), ln, font=font)
        draw.text(((w - draw.textlength(ln, font=font)) / 2, y - box[1]), ln, font=font, fill=ink)
        y += box[3] + 4
    return img


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

    `run_control(action)` runs a board control by its name (see ACTIONS); `enumerate_decks` and `to_native` are the
    two seams the tests replace."""

    def __init__(self, config_path, run_control, enumerate_decks=None, to_native=None, reconnect_seconds=RECONNECT_SECONDS):
        self.config_path = config_path
        self.run_control = run_control
        self._enumerate = enumerate_decks or _enumerate_decks
        self._to_native = to_native or _to_native
        self._reconnect = reconnect_seconds
        self._lock = threading.RLock()
        self._stop = threading.Event()
        self._thread = None
        self._deck = None
        self._error = None
        self.board_status = None

    # ---- config ----
    def _cfg(self):
        return cfg_mod.load(self.config_path).get("streamdeck", {}) if self.config_path else {}

    def enabled(self):
        return self._cfg().get("enabled") is True

    def keys(self):
        try:
            return clean_keys(self._cfg().get("keys", []))
        except ValueError:
            log.warning("The [streamdeck] keys in config.toml are not valid, ignored")
            return []

    def brightness(self):
        value = self._cfg().get("brightness", DEFAULT_BRIGHTNESS)
        return value if isinstance(value, int) and not isinstance(value, bool) and 0 <= value <= 100 else DEFAULT_BRIGHTNESS

    def update(self, enabled=None, brightness=None, keys=None):
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
        if keys is not None:
            changes["keys"] = clean_keys(keys)
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
        size = deck.key_image_format()["size"]
        by_key = {k["key"]: k for k in self.keys()}
        for index in range(deck.key_count()):
            entry = by_key.get(index)
            if entry:
                image = render_key(entry["label"], key_hex(entry, self.board_status), size)
            else:
                image = render_key("", STATUS_COLORS["off"], size)
            self._guard(lambda image=image, index=index: deck.set_key_image(index, self._to_native(deck, image)))

    def _on_key(self, deck, key, pressed):
        if not pressed:
            return
        entry = next((k for k in self.keys() if k["key"] == key), None)
        if entry is None:
            return
        log.info("Stream Deck key %d: %s", key, entry["action"])
        try:
            result = self.run_control(entry["action"])
            if isinstance(result, dict) and result.get("error"):
                log.warning("Stream Deck key %d: %s", key, result["error"])
        except Exception as e:
            log.error("Stream Deck key %d failed: %s", key, e)

    # ---- state for the page ----
    def snapshot(self):
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
                "actions": [{"id": k, "label": v} for k, v in ACTIONS.items()],
                "keys": [{**k, "shown": key_hex(k, self.board_status)} for k in keys],
            }
