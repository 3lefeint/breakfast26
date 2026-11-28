"""Ulanzi D200H: the keys of the device behind the same calls as a Stream Deck of the `streamdeck` library.

The device is a USB HID device (vendor 2207, product 0019). Its protocol is based on the work in the MIT-licensed
project `ulanzi-d200-linux`:

    Copyright (c) the authors of ulanzi-d200-linux
    Permission is hereby granted, free of charge, to any person obtaining a copy of this software and associated
    documentation files (the "Software"), to deal in the Software without restriction, including without limitation
    the rights to use, copy, modify, merge, publish, distribute, sublicense, and/or sell copies of the Software, and to
    permit persons to whom the Software is furnished to do so, subject to the following conditions: The above copyright
    notice and this permission notice shall be included in all copies or substantial portions of the Software. THE
    SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND.

Packets are 1024 bytes: the header `7c 7c`, a 16-bit command, a length and the payload. Images go to the device as a ZIP
archive with a manifest; the first drawing is a full upload, later changes are partial updates. The device has 13 normal keys
(196x196 pixels, index 0 to 12) and a wide key (458x196, index 13) in a grid of 3 rows and 5 columns, the wide key
taking the last two places. The firmware drops the layout and shows its own design unless the host sends the window data
once a second, so a thread of this module does that, reads the key events and writes the images that have changed.

All the device I/O sits behind `UlanziDeck`, whose methods are the ones `StreamDeckService` calls on a Stream Deck; the HID
module is a parameter, so the tests run without a device.
"""
import io
import json
import logging
import queue
import struct
import threading
import time
import zipfile
from datetime import datetime

log = logging.getLogger(__name__)

VENDOR_ID = 0x2207
PRODUCT_ID = 0x0019
PACKET_SIZE = 1024
HEADER = b"\x7c\x7c"

CMD_SET_BUTTONS = 0x0001
CMD_GET_BASE = 0x0003
CMD_SET_SMALL_WINDOW_DATA = 0x0006
CMD_SET_BRIGHTNESS = 0x000A
CMD_PARTIALLY_UPDATE_BUTTONS = 0x000D
CMD_BUTTON = 0x0101
CMD_BUTTON_2 = 0x0102
CMD_CONFIGURATION_REQUEST = 0x010B
CMD_DEVICE_INFO = 0x0303

KEY_SIZE = (196, 196)
WIDE_SIZE = (458, 196)
WIDE_INDEX = 13
KEY_COUNT = 14
LAYOUT = (3, 5)             # rows, columns
COLUMNS = LAYOUT[1]
BACKGROUND_MODE = 2         # the wide key shows the picture that was sent (0 statistics, 1 clock)
KEEPALIVE_SECONDS = 1.0
POLL_SECONDS = 0.005
FLUSH_AFTER_SECONDS = 0.03  # changes of the images that arrive within this time go out as one update
SYNC_TIMEOUT_SECONDS = 5.0
ACK_SECONDS = 3.0           # a request for the configuration this soon after an update of ours is the answer to it
MODEL = "Ulanzi D200H"


def _load_hid():
    try:
        import hid
        return hid
    except ImportError:
        return None


def available(hid_module=None):
    """True when the HID library can be imported."""
    return (hid_module or _load_hid()) is not None


def enumerate_decks(hid_module=None):
    """The D200H that are plugged in, as `UlanziDeck` objects (not yet open). Empty when there is none or no HID library."""
    hid_module = hid_module or _load_hid()
    if hid_module is None:
        return []
    try:
        found = hid_module.enumerate(VENDOR_ID, PRODUCT_ID)
    except Exception as e:
        log.warning("Ulanzi: listing the USB devices failed: %s", e)
        return []
    if not found:
        return []
    # the second interface of the device is a keyboard and carries nothing of this protocol
    info = next((d for d in found if d.get("interface_number") == 0), found[0])
    return [UlanziDeck(info["path"], hid_module)]


def _packet(command, payload, length):
    packet = bytearray(PACKET_SIZE)
    packet[0:2] = HEADER
    packet[2:4] = struct.pack(">H", command)
    packet[4:8] = struct.pack("<I", length)
    packet[8:8 + len(payload)] = payload
    return bytes(packet)


def _black(size):
    from PIL import Image
    out = io.BytesIO()
    Image.new("RGB", size, (0, 0, 0)).save(out, "PNG")
    return out.getvalue()


def _size_of(index):
    return WIDE_SIZE if index == WIDE_INDEX else KEY_SIZE


class UlanziDeck:
    """One D200H. `open` starts a thread that owns the reading: it sends the keepalive, hands key events to the callback
    and writes the images that were set since the last round."""

    def __init__(self, path, hid_module=None):
        self._path = path
        self._hid = hid_module or _load_hid()
        self._device = None
        self._io = threading.RLock()        # every read and write of the HID handle
        self._pending_lock = threading.Lock()
        self._images = {}                   # index -> PNG bytes, the picture each key should show
        self._pending = {}                  # index -> PNG bytes not yet on the device
        self._pending_since = None
        self._uploaded = False              # the first drawing, a full upload, has been made
        self._last_upload = 0.0
        self._callback = None
        self._brightness = None
        self._thread = None
        self._events = queue.Queue()        # key events for the callback, in order, handled by their own thread
        self._dispatcher = None
        self._stop = threading.Event()
        self._failed = False

    # ---- what StreamDeckService asks of a deck ----
    def open(self):
        self._device = self._hid.device()
        self._device.open_path(self._path)
        self._device.set_nonblocking(True)
        self._failed = False
        self._stop.clear()
        self._events = queue.Queue()
        self._thread = threading.Thread(target=self._run, name="ulanzi", daemon=True)
        self._thread.start()
        self._dispatcher = threading.Thread(target=self._dispatch, name="ulanzi-keys", daemon=True)
        self._dispatcher.start()

    def close(self):
        self._stop.set()
        thread, self._thread = self._thread, None
        if thread is not None and thread is not threading.current_thread():
            thread.join(2)
        dispatcher, self._dispatcher = self._dispatcher, None
        if dispatcher is not None:
            self._events.put(None)          # a callback that is still busy is left to finish by itself
        with self._io:
            device, self._device = self._device, None
        if device is not None:
            try:
                device.close()
            except Exception:
                pass

    def reset(self):
        """Forget the pictures; the next drawing is a full upload. The device itself falls back to its own design when the
        keepalive stops."""
        with self._pending_lock:
            self._images.clear()
            self._pending.clear()
            self._pending_since = None
            self._uploaded = False

    def connected(self):
        return self._device is not None and not self._failed

    def is_open(self):
        return self._device is not None

    def deck_type(self):
        return MODEL

    def key_count(self):
        return KEY_COUNT

    def key_layout(self):
        return LAYOUT

    def key_image_format(self):
        return {"size": KEY_SIZE}

    def key_size(self, index):
        return _size_of(index)

    def wide_keys(self):
        return (WIDE_INDEX,)

    def to_native(self, image):
        out = io.BytesIO()
        image.convert("RGB").save(out, "PNG")
        return out.getvalue()

    def set_brightness(self, value):
        self._brightness = max(0, min(100, int(value)))
        self._write_guarded(lambda: self._send(CMD_SET_BRIGHTNESS, str(self._brightness).encode("ascii")))

    def set_key_callback(self, callback):
        self._callback = callback

    def set_key_image(self, index, image):
        """Remember the picture of a key; the thread sends it with the next update."""
        with self._pending_lock:
            if self._uploaded and index not in self._pending and self._images.get(index) == image:
                return          # the key shows it already: a redraw of keys that did not change must not flicker
            self._images[index] = image
            self._pending[index] = image
            if self._pending_since is None:
                self._pending_since = time.monotonic()

    # ---- the thread ----
    def _run(self):
        next_keepalive = 0.0
        while not self._stop.is_set():
            try:
                report = self._read()
                if report is not None:
                    self._handle(report)
                    continue
                now = time.monotonic()
                if now >= next_keepalive:
                    self._send_window_data()
                    next_keepalive = now + KEEPALIVE_SECONDS
                self._flush(now)
            except Exception as e:
                if not self._stop.is_set():
                    log.warning("Ulanzi: lost the device (%s)", e)
                self._failed = True
                return
            self._stop.wait(POLL_SECONDS)

    def _read(self):
        with self._io:
            if self._device is None:
                return None
            data = self._device.read(PACKET_SIZE)
        if not data or len(data) < 8:
            return None
        data = bytes(data)
        return data if data[:2] == HEADER else None

    def _handle(self, data):
        command = struct.unpack(">H", data[2:4])[0]
        if command == CMD_CONFIGURATION_REQUEST:
            # The firmware sends this after every update it has taken, and by itself when its program was restarted and
            # needs the layout again. Only the second kind is answered; sending everything again for the first kind
            # would start the next update, and so on, and every full upload throws away the key events that wait.
            since = time.monotonic() - self._last_upload
            log.debug("Ulanzi: request for the configuration, %.2f s after our last update (report %s)", since, data[8:24].hex())
            if since < ACK_SECONDS:
                return
            log.info("Ulanzi: the firmware asked for its layout, sending it again")
            with self._pending_lock:
                self._pending = dict(self._images)
                self._pending_since = time.monotonic()
                self._uploaded = False
            return
        if command not in (CMD_BUTTON, CMD_BUTTON_2):
            if command != CMD_DEVICE_INFO:
                log.debug("Ulanzi: report %04x (%s)", command, data[8:24].hex())
            return          # the heartbeat of the firmware and other reports
        index = data[9]
        # the wide key flags press and release in byte 10, the others in byte 11
        pressed = (data[10] if index == WIDE_INDEX else data[11]) == 0x01
        log.debug("Ulanzi key %d %s (report %s, t=%.3f)", index, "down" if pressed else "up", data[8:12].hex(), time.monotonic())
        self._events.put((index, pressed))

    def _dispatch(self):
        """Hand the key events to the callback one after the other. The callback can take long (an action that waits for
        something), and the thread that reads the device must go on sending the keepalive meanwhile."""
        while True:
            event = self._events.get()
            if event is None:
                return
            callback = self._callback
            if callback is None:
                continue
            log.debug("Ulanzi key %d %s handed on (t=%.3f)", event[0], "down" if event[1] else "up", time.monotonic())
            try:
                callback(self, *event)
            except Exception as e:
                log.error("Ulanzi: key %d: %s", event[0], e)

    def _send_window_data(self):
        payload = f"{BACKGROUND_MODE}|0|0|{datetime.now().strftime('%H:%M:%S')}|0".encode("ascii")
        self._send(CMD_SET_SMALL_WINDOW_DATA, payload)

    def _flush(self, now):
        with self._pending_lock:
            if not self._pending or now - (self._pending_since or now) < FLUSH_AFTER_SECONDS:
                return
            changes, self._pending, self._pending_since = self._pending, {}, None
            full = not self._uploaded
            if full:
                changes = {i: self._images.get(i) or _black(_size_of(i)) for i in range(KEY_COUNT)}
                self._uploaded = True
        self._upload(changes, partial=not full)
        if full and self._brightness is not None:
            self._write_guarded(lambda: self._send(CMD_SET_BRIGHTNESS, str(self._brightness).encode("ascii")))

    # ---- writing ----
    def _write_guarded(self, fn):
        with self._io:
            if self._device is None:
                return
            try:
                fn()
            except Exception:
                self._failed = True
                raise

    def _send(self, command, payload):
        self._write(_packet(command, payload, len(payload)))

    def _write(self, packet):
        # hidapi wants a report id (0) in front of the 1024 bytes; it is not sent to the device
        report = b"\x00" + packet
        written = self._device.write(report)
        if written != len(report):
            raise OSError(f"Ulanzi: write failed ({written}/{len(report)} bytes)")

    def _upload(self, images, partial):
        """Send the pictures as a ZIP with a manifest: all keys in a full upload, the changed ones in a partial update."""
        manifest, files = {}, {}
        for index, data in images.items():
            key = f"{index % COLUMNS}_{index // COLUMNS}"
            view = {"State": 0, "ViewParam": [{"Icon": f"icons/k{index}.png"}]}
            if index == WIDE_INDEX and not partial:
                view["SmallViewMode"] = BACKGROUND_MODE
            manifest[key] = view
            files[f"icons/k{index}.png"] = data
        archive = io.BytesIO()
        with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED, compresslevel=1) as zf:
            zf.writestr("manifest.json", json.dumps(manifest, sort_keys=True, separators=(",", ":")))
            for name, data in files.items():
                zf.writestr(name, data)
        data = archive.getvalue()
        started = time.monotonic()
        self._last_upload = started
        try:
            with self._io:
                if self._device is None:
                    return
                log.debug("Ulanzi %s update of keys %s (t=%.3f)", "partial" if partial else "full", sorted(images), started)
                if partial:
                    self._send_file(data, CMD_PARTIALLY_UPDATE_BUTTONS)
                else:
                    self._synchronize()
                    self._send_file(data, CMD_SET_BUTTONS)
                    self._synchronize()
                self._last_upload = time.monotonic()
        except Exception:
            self._failed = True
            raise

    def _send_file(self, data, command):
        first = data[:PACKET_SIZE - 8]
        self._write(_packet(command, first.ljust(PACKET_SIZE - 8, b"\x00"), len(data)))
        for i in range(PACKET_SIZE - 8, len(data), PACKET_SIZE):
            self._write(data[i:i + PACKET_SIZE].ljust(PACKET_SIZE, b"\x00"))

    def _synchronize(self):
        """Ask for the device info and wait for the answer: the firmware reuses its ZIP file, so the next upload must not
        start before it is done with the last one."""
        for _ in range(256):          # reports queued before this point
            if not self._device.read(PACKET_SIZE):
                break
        self._send(CMD_GET_BASE, b"")
        deadline = time.monotonic() + SYNC_TIMEOUT_SECONDS
        while time.monotonic() < deadline:
            data = bytes(self._device.read(PACKET_SIZE) or b"")
            if len(data) >= 8 and data[:2] == HEADER and struct.unpack(">H", data[2:4])[0] == CMD_DEVICE_INFO:
                try:
                    info = json.loads(data[8:].split(b"\x00", 1)[0])
                except ValueError as e:
                    raise RuntimeError("Ulanzi: invalid answer of the firmware") from e
                if not isinstance(info, dict) or info.get("error") not in (0, "0"):
                    raise RuntimeError(f"Ulanzi: the firmware is not ready: {info}")
                return
            time.sleep(0.01)
        raise TimeoutError("Ulanzi: the firmware did not answer")
