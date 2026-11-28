"""The Ulanzi D200H adapter, with a fake HID module instead of a device."""
import io
import json
import struct
import threading
import time
import zipfile

import pytest

from breakfast import streamdeck as sd
from breakfast import ulanzi


def _png(color=(10, 20, 30), size=(8, 8)):
    from PIL import Image
    out = io.BytesIO()
    Image.new("RGB", size, color).save(out, "PNG")
    return out.getvalue()


class FakeHidDevice:
    def __init__(self):
        self.written = []        # the 1024 byte packets (without the report id)
        self.queue = []          # reports the device sends
        self.lock = threading.Lock()
        self.opened = None
        self.closed = False
        self.fail_read = False
        self.fail_write = False
        self.silent = False      # does not answer GETBASE

    def open_path(self, path): self.opened = path
    def set_nonblocking(self, flag): pass
    def close(self): self.closed = True

    def write(self, report):
        if self.fail_write:
            return -1
        assert report[0] == 0 and len(report) == 1025
        packet = bytes(report[1:])
        with self.lock:
            self.written.append(packet)
            if packet[:2] == ulanzi.HEADER and struct.unpack(">H", packet[2:4])[0] == ulanzi.CMD_GET_BASE and not self.silent:
                self.queue.append(_report(ulanzi.CMD_DEVICE_INFO, json.dumps({"error": "0", "DeviceType": "D200"}).encode()))
        return len(report)

    def read(self, size):
        if self.fail_read:
            raise OSError("read error")
        with self.lock:
            return list(self.queue.pop(0)) if self.queue else []


def _report(command, payload=b""):
    packet = bytearray(1024)
    packet[0:2] = ulanzi.HEADER
    packet[2:4] = struct.pack(">H", command)
    packet[4:8] = struct.pack("<I", len(payload))
    packet[8:8 + len(payload)] = payload
    return bytes(packet)


def _key_report(index, pressed):
    flag = 1 if pressed else 0
    # keys 0-12 flag it in byte 3, the wide key in byte 2 (byte 3 stays 1)
    payload = bytes([1, index, flag, 1]) if index == ulanzi.WIDE_INDEX else bytes([1, index, 1, flag])
    return _report(ulanzi.CMD_BUTTON, payload)


class FakeHid:
    def __init__(self, found=True):
        self.dev = FakeHidDevice()
        self.found = found

    def enumerate(self, vendor, product):
        assert (vendor, product) == (0x2207, 0x0019)
        if not self.found:
            return []
        return [{"path": b"2-2:1.1", "interface_number": 1}, {"path": b"2-2:1.0", "interface_number": 0}]

    def device(self):
        return self.dev


def _commands(dev, command):
    return [p for p in list(dev.written) if p[:2] == ulanzi.HEADER and struct.unpack(">H", p[2:4])[0] == command]


def _archive(packets):
    """The manifest and files of the ZIP that was sent in `packets` (the first of them carries the header)."""
    size = struct.unpack("<I", packets[0][4:8])[0]
    data = packets[0][8:] + b"".join(packets[1:])
    return zipfile.ZipFile(io.BytesIO(data[:size]))


def _wait(condition, seconds=3):
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        if condition():
            return True
        time.sleep(0.01)
    return False


@pytest.fixture
def deck(monkeypatch):
    monkeypatch.setattr(ulanzi, "FLUSH_AFTER_SECONDS", 0.0)
    monkeypatch.setattr(ulanzi, "POLL_SECONDS", 0.001)
    hid = FakeHid()
    d = ulanzi.enumerate_decks(hid)[0]
    d.open()
    yield d, hid.dev
    d.close()


class TestEnumerate:
    def test_finds_the_device_on_interface_zero(self):
        decks = ulanzi.enumerate_decks(FakeHid())
        assert len(decks) == 1
        decks[0].open()
        try:
            assert decks[0]._device.opened == b"2-2:1.0"
        finally:
            decks[0].close()

    def test_nothing_plugged_in(self):
        assert ulanzi.enumerate_decks(FakeHid(found=False)) == []

    def test_a_failing_enumerate_is_no_device(self):
        class Broken:
            def enumerate(self, vendor, product):
                raise OSError("no hidapi")
        assert ulanzi.enumerate_decks(Broken()) == []


class TestShape:
    def test_layout_of_the_device(self):
        d = ulanzi.enumerate_decks(FakeHid())[0]
        assert (d.key_count(), d.key_layout(), d.deck_type()) == (14, (3, 5), "Ulanzi D200H")
        assert d.key_size(0) == (196, 196) and d.key_size(12) == (196, 196)
        assert d.key_size(13) == (458, 196)
        assert d.wide_keys() == (13,)

    def test_native_image_is_a_png(self):
        from PIL import Image
        d = ulanzi.enumerate_decks(FakeHid())[0]
        data = d.to_native(Image.new("RGBA", (196, 196), (255, 0, 0, 255)))
        assert data[:8] == b"\x89PNG\r\n\x1a\n"


class TestImages:
    def test_first_drawing_is_a_full_upload_of_all_keys(self, deck, monkeypatch):
        d, dev = deck
        monkeypatch.setattr(ulanzi, "FLUSH_AFTER_SECONDS", 0.1)
        d.set_key_image(0, _png((255, 0, 0)))
        d.set_key_image(13, _png((0, 0, 255), (458, 196)))
        assert _wait(lambda: _commands(dev, ulanzi.CMD_SET_BUTTONS))
        sent = _commands(dev, ulanzi.CMD_SET_BUTTONS)
        assert len(sent) == 1 and not _commands(dev, ulanzi.CMD_PARTIALLY_UPDATE_BUTTONS)
        index = dev.written.index(sent[0])
        packets = [sent[0]] + dev.written[index + 1:index + 1 + 20]
        manifest = json.loads(_archive(_trim(packets, sent[0])).read("manifest.json"))
        assert len(manifest) == 14                                    # keys that were not set are black
        assert manifest["3_2"]["SmallViewMode"] == 2                  # index 13: the wide key shows the picture
        assert manifest["0_0"]["ViewParam"][0]["Icon"] == "icons/k0.png"

    def test_later_changes_are_partial_updates_of_the_changed_keys(self, deck):
        d, dev = deck
        d.set_key_image(0, _png())
        assert _wait(lambda: _commands(dev, ulanzi.CMD_SET_BUTTONS))
        d.set_key_image(4, _png((1, 2, 3)))
        assert _wait(lambda: _commands(dev, ulanzi.CMD_PARTIALLY_UPDATE_BUTTONS))
        sent = _commands(dev, ulanzi.CMD_PARTIALLY_UPDATE_BUTTONS)[0]
        index = dev.written.index(sent)
        manifest = json.loads(_archive(_trim([sent] + dev.written[index + 1:index + 5], sent)).read("manifest.json"))
        assert list(manifest) == ["4_0"]
        assert len(_commands(dev, ulanzi.CMD_SET_BUTTONS)) == 1

    def test_changes_that_come_together_go_out_as_one_update(self, monkeypatch):
        monkeypatch.setattr(ulanzi, "FLUSH_AFTER_SECONDS", 0.2)
        monkeypatch.setattr(ulanzi, "POLL_SECONDS", 0.001)
        hid = FakeHid()
        d = ulanzi.enumerate_decks(hid)[0]
        d.open()
        try:
            for i in range(14):
                d.set_key_image(i, _png((i, i, i)))
            assert _wait(lambda: _commands(hid.dev, ulanzi.CMD_SET_BUTTONS))
            time.sleep(0.4)
            assert len(_commands(hid.dev, ulanzi.CMD_SET_BUTTONS)) == 1
            assert not _commands(hid.dev, ulanzi.CMD_PARTIALLY_UPDATE_BUTTONS)
        finally:
            d.close()

    def test_a_picture_that_the_key_shows_already_is_not_sent_again(self, deck):
        d, dev = deck
        d.set_key_image(0, _png())
        d.set_key_image(1, _png())
        assert _wait(lambda: _commands(dev, ulanzi.CMD_SET_BUTTONS))
        d.set_key_image(0, _png())
        d.set_key_image(1, _png((9, 9, 9)))
        assert _wait(lambda: _commands(dev, ulanzi.CMD_PARTIALLY_UPDATE_BUTTONS))
        time.sleep(0.1)
        sent = _commands(dev, ulanzi.CMD_PARTIALLY_UPDATE_BUTTONS)
        assert len(sent) == 1
        index = dev.written.index(sent[0])
        manifest = json.loads(_archive(_trim([sent[0]] + dev.written[index + 1:index + 5], sent[0])).read("manifest.json"))
        assert list(manifest) == ["1_0"]

    def test_reset_makes_the_next_drawing_a_full_upload(self, deck):
        d, dev = deck
        d.set_key_image(0, _png())
        assert _wait(lambda: _commands(dev, ulanzi.CMD_SET_BUTTONS))
        d.reset()
        d.set_key_image(1, _png())
        assert _wait(lambda: len(_commands(dev, ulanzi.CMD_SET_BUTTONS)) == 2)

    def test_brightness_is_sent_and_again_after_a_full_upload(self, deck):
        d, dev = deck
        d.set_brightness(55)
        assert [p[8:10] for p in _commands(dev, ulanzi.CMD_SET_BRIGHTNESS)] == [b"55"]
        d.set_key_image(0, _png())
        assert _wait(lambda: len(_commands(dev, ulanzi.CMD_SET_BRIGHTNESS)) == 2)

    def test_the_firmware_asking_for_its_layout_later_gets_everything_again(self, deck):
        d, dev = deck
        d.set_key_image(0, _png())
        assert _wait(lambda: _commands(dev, ulanzi.CMD_SET_BUTTONS))
        d._last_upload -= 10          # long enough ago: the request is not the answer to an update
        with dev.lock:
            dev.queue.append(_report(ulanzi.CMD_CONFIGURATION_REQUEST))
        assert _wait(lambda: len(_commands(dev, ulanzi.CMD_SET_BUTTONS)) == 2)

    def test_a_request_right_after_an_update_is_its_answer_and_starts_no_full_upload(self, deck):
        d, dev = deck
        d.set_key_image(0, _png())
        assert _wait(lambda: _commands(dev, ulanzi.CMD_SET_BUTTONS))
        d.set_key_image(1, _png((5, 5, 5)))
        assert _wait(lambda: _commands(dev, ulanzi.CMD_PARTIALLY_UPDATE_BUTTONS))
        for _ in range(3):
            with dev.lock:
                dev.queue.append(_report(ulanzi.CMD_CONFIGURATION_REQUEST))
        time.sleep(0.3)
        assert len(_commands(dev, ulanzi.CMD_SET_BUTTONS)) == 1

    def test_key_events_that_follow_an_update_are_not_lost(self, deck):
        d, dev = deck
        events = []
        d.set_key_callback(lambda deck_, key, pressed: events.append((key, pressed)))
        d.set_key_image(0, _png())
        assert _wait(lambda: _commands(dev, ulanzi.CMD_SET_BUTTONS))
        d.set_key_image(0, _png((7, 7, 7)))
        with dev.lock:
            dev.queue += [_report(ulanzi.CMD_CONFIGURATION_REQUEST), _key_report(0, False)]
        assert _wait(lambda: events == [(0, False)])


def _trim(packets, first):
    """The packets of one archive: the first carries the size, the following ones are data of that size."""
    size = struct.unpack("<I", first[4:8])[0]
    need = 1 + max(0, -(-(size - (ulanzi.PACKET_SIZE - 8)) // ulanzi.PACKET_SIZE))
    return packets[:need]


class TestKeepalive:
    def test_the_window_data_goes_out_every_second(self, deck, monkeypatch):
        d, dev = deck
        assert _wait(lambda: _commands(dev, ulanzi.CMD_SET_SMALL_WINDOW_DATA))
        payload = _commands(dev, ulanzi.CMD_SET_SMALL_WINDOW_DATA)[0][8:30].split(b"\x00")[0].decode()
        assert payload.startswith("2|0|0|") and payload.endswith("|0")

    def test_keepalive_keeps_coming(self, monkeypatch):
        monkeypatch.setattr(ulanzi, "KEEPALIVE_SECONDS", 0.05)
        monkeypatch.setattr(ulanzi, "POLL_SECONDS", 0.001)
        hid = FakeHid()
        d = ulanzi.enumerate_decks(hid)[0]
        d.open()
        try:
            assert _wait(lambda: len(_commands(hid.dev, ulanzi.CMD_SET_SMALL_WINDOW_DATA)) >= 3)
        finally:
            d.close()


class TestKeys:
    def test_press_and_release_reach_the_callback(self, deck):
        d, dev = deck
        events = []
        d.set_key_callback(lambda deck_, key, pressed: events.append((key, pressed)))
        with dev.lock:
            dev.queue += [_key_report(0, True), _key_report(0, False), _key_report(12, True), _key_report(12, False)]
        assert _wait(lambda: len(events) == 4)
        assert events == [(0, True), (0, False), (12, True), (12, False)]

    def test_every_report_reaches_the_callback_even_when_it_repeats(self, deck):
        d, dev = deck
        events = []
        d.set_key_callback(lambda deck_, key, pressed: events.append((key, pressed)))
        with dev.lock:
            dev.queue += [_key_report(2, True), _key_report(2, True), _key_report(2, False)]
        assert _wait(lambda: len(events) == 3)

    def test_the_wide_key_flags_the_press_in_another_byte(self, deck):
        d, dev = deck
        events = []
        d.set_key_callback(lambda deck_, key, pressed: events.append((key, pressed)))
        with dev.lock:
            dev.queue += [_key_report(13, True), _key_report(13, False)]
        assert _wait(lambda: len(events) == 2)
        assert events == [(13, True), (13, False)]

    def test_heartbeat_and_unknown_reports_are_no_key(self, deck):
        d, dev = deck
        events = []
        d.set_key_callback(lambda deck_, key, pressed: events.append((key, pressed)))
        with dev.lock:
            dev.queue += [_report(0x0103), _report(0x7777, b"1234"), _key_report(2, True)]
        assert _wait(lambda: events)
        assert events == [(2, True)]


class TestLostDevice:
    def test_a_read_error_means_not_connected(self, deck):
        d, dev = deck
        assert d.connected() and d.is_open()
        dev.fail_read = True
        assert _wait(lambda: not d.connected())

    def test_a_failed_write_means_not_connected(self, deck):
        d, dev = deck
        dev.fail_write = True
        d.set_key_image(0, _png())
        assert _wait(lambda: not d.connected())

    def test_close_closes_the_handle_and_can_be_repeated(self):
        hid = FakeHid()
        d = ulanzi.enumerate_decks(hid)[0]
        d.open()
        d.close()
        d.close()
        assert hid.dev.closed and not d.is_open()

    def test_a_silent_firmware_times_out_the_upload(self, monkeypatch):
        monkeypatch.setattr(ulanzi, "SYNC_TIMEOUT_SECONDS", 0.1)
        monkeypatch.setattr(ulanzi, "FLUSH_AFTER_SECONDS", 0.0)
        monkeypatch.setattr(ulanzi, "POLL_SECONDS", 0.001)
        hid = FakeHid()
        hid.dev.silent = True
        d = ulanzi.enumerate_decks(hid)[0]
        d.open()
        try:
            d.set_key_image(0, _png())
            assert _wait(lambda: not d.connected())
        finally:
            d.close()


class TestService:
    """The service with a D200H: key sizes, previews and the picture format."""

    @staticmethod
    def _service(tmp_path, deck):
        path = tmp_path / "config.toml"
        path.write_text("[streamdeck]\nenabled = true\n")
        svc = sd.StreamDeckService(str(path), lambda action: None, enumerate_decks=lambda: [deck], reconnect_seconds=60)
        return svc

    def test_every_key_is_drawn_in_its_own_size(self, tmp_path):
        from PIL import Image
        hid = FakeHid()
        deck = ulanzi.enumerate_decks(hid)[0]
        svc = self._service(tmp_path, deck)
        with svc._lock:
            svc._connect()
        try:
            sizes = {i: Image.open(io.BytesIO(deck._images[i])).size for i in range(14)}
            assert all(sizes[i] == (196, 196) for i in range(13))
            assert sizes[13] == (458, 196)
        finally:
            svc.stop()

    def test_snapshot_tells_the_grid_and_the_wide_key(self, tmp_path):
        hid = FakeHid()
        deck = ulanzi.enumerate_decks(hid)[0]
        svc = self._service(tmp_path, deck)
        with svc._lock:
            svc._connect()
        try:
            snap = svc.snapshot()
            assert (snap["rows"], snap["cols"], snap["key_count"], snap["wide"], snap["model"]) == (3, 5, 14, [13], "Ulanzi D200H")
        finally:
            svc.stop()

    def test_the_preview_of_the_wide_key_is_wide(self, tmp_path):
        from PIL import Image
        path = tmp_path / "config.toml"
        path.write_text('[streamdeck]\nenabled = true\nkeys = [{key = 13, action = "undo", label = "Undo"}, {key = 0, action = "undo", label = "Undo"}]\n')
        svc = sd.StreamDeckService(str(path), lambda action: None, enumerate_decks=lambda: [], reconnect_seconds=60)
        svc._wide = (13,)
        assert Image.open(io.BytesIO(svc.preview(0))).size == (96, 96)
        assert Image.open(io.BytesIO(svc.preview(13))).size == (224, 96)
        entry = {"key": 13, "action": "undo", "label": "Undo"}
        assert Image.open(io.BytesIO(svc.preview_entry(entry))).size == (505, 216)

    def test_no_wide_key_without_a_device_seen(self, tmp_path):
        path = tmp_path / "config.toml"
        path.write_text("[streamdeck]\nenabled = true\n")
        svc = sd.StreamDeckService(str(path), lambda action: None, enumerate_decks=lambda: [], reconnect_seconds=60)
        assert svc.snapshot()["wide"] == [] and svc.snapshot()["key_count"] == 15


class TestEnumerateBoth:
    def test_the_hid_error_of_the_other_library_is_not_shown_when_the_d200h_is_found(self, monkeypatch):
        import breakfast.ulanzi as u
        monkeypatch.setattr(u, "enumerate_decks", lambda hid_module=None: ["deck"])
        assert "deck" in sd._enumerate_decks()


class TestSlowCallback:
    def test_a_slow_callback_does_not_stop_the_keepalive_or_the_next_events(self, monkeypatch):
        monkeypatch.setattr(ulanzi, "KEEPALIVE_SECONDS", 0.05)
        monkeypatch.setattr(ulanzi, "POLL_SECONDS", 0.001)
        hid = FakeHid()
        d = ulanzi.enumerate_decks(hid)[0]
        gate = threading.Event()
        seen = []

        def callback(deck, key, pressed):
            seen.append((key, pressed))
            if key == 0:
                gate.wait(5)

        d.set_key_callback(callback)
        d.open()
        try:
            with hid.dev.lock:
                hid.dev.queue += [_key_report(0, True), _key_report(1, True)]
            assert _wait(lambda: seen)
            before = len(_commands(hid.dev, ulanzi.CMD_SET_SMALL_WINDOW_DATA))
            assert _wait(lambda: len(_commands(hid.dev, ulanzi.CMD_SET_SMALL_WINDOW_DATA)) >= before + 3)   # the callback is still busy
            d.set_key_image(2, _png())
            assert _wait(lambda: _commands(hid.dev, ulanzi.CMD_SET_BUTTONS))                                # and images still go out
            assert seen == [(0, True)]                                                                       # events stay in order
            gate.set()
            assert _wait(lambda: seen == [(0, True), (1, True)])
        finally:
            gate.set()
            d.close()

    def test_a_failing_callback_does_not_stop_the_keys(self, deck):
        d, dev = deck
        seen = []

        def callback(deck_, key, pressed):
            seen.append(key)
            if key == 0:
                raise RuntimeError("boom")

        d.set_key_callback(callback)
        with dev.lock:
            dev.queue += [_key_report(0, True), _key_report(1, True)]
        assert _wait(lambda: seen == [0, 1])
        assert d.connected()


class TestHoldWithTheDevice:
    """A key with a hold must not run its action when it is let go earlier, whatever the device does meanwhile."""

    def _run(self, tmp_path, monkeypatch, press_seconds, hold=0.5):
        monkeypatch.setattr(ulanzi, "FLUSH_AFTER_SECONDS", 0.0)
        monkeypatch.setattr(ulanzi, "POLL_SECONDS", 0.001)
        path = tmp_path / "config.toml"
        path.write_text('[streamdeck]\nenabled = true\nkeys = [{key = 0, action = "reset_board", label = "Reset", hold = %s}]\n' % hold)
        hid = FakeHid()
        deck = ulanzi.enumerate_decks(hid)[0]
        ran = []
        svc = sd.StreamDeckService(str(path), lambda action: ran.append(action) or {"ok": True}, enumerate_decks=lambda: [deck],
                                   reconnect_seconds=60)
        svc._hold_step = 0.02
        with svc._lock:
            svc._connect()
        try:
            with hid.dev.lock:
                hid.dev.queue.append(_key_report(0, True))
            time.sleep(press_seconds)
            with hid.dev.lock:
                hid.dev.queue.append(_key_report(0, False))
            time.sleep(hold + 0.5)
            return ran
        finally:
            svc.stop()

    def test_a_short_press_does_nothing(self, tmp_path, monkeypatch):
        assert self._run(tmp_path, monkeypatch, 0.15) == []

    def test_a_long_press_runs_the_action_once(self, tmp_path, monkeypatch):
        assert self._run(tmp_path, monkeypatch, 0.8) == ["reset_board"]
