"""Stream Deck keys: layout checks, status colors, key drawing and the service against a fake device."""
import time

import pytest

from breakfast import config as cfg_mod
from breakfast import streamdeck as sd
from breakfast.state import GameState


class FakeDeck:
    def __init__(self, keys=6, layout=(2, 3), connected=True):
        self.keys, self.layout, self._connected = keys, layout, connected
        self.images, self.callback, self.brightness, self.opened, self.closed = {}, None, None, False, False

    def open(self): self.opened = True
    def close(self): self.closed = True
    def reset(self): pass
    def connected(self): return self._connected
    def deck_type(self): return "Fake Deck"
    def key_count(self): return self.keys
    def key_layout(self): return self.layout
    def key_image_format(self): return {"size": (72, 72)}
    def set_brightness(self, value): self.brightness = value
    def set_key_callback(self, cb): self.callback = cb
    def set_key_image(self, index, image): self.images[index] = image


class TestStatusColor:
    @pytest.mark.parametrize("status, color", [
        ("Throw", "green"), ("Takeout Finished", "green"),
        ("Takeout", "yellow"), ("Takeout in progress", "yellow"), ("Takeout Started", "yellow"), ("Board Starting", "yellow"),
        ("Board Stopped", "red"), ("Board Disconnected", "red"), ("Board Stopping", "red"),
        ("Stopped", "red"), ("Board Started", "green"), ("Calibration Started", "yellow"), ("Manual reset", "green"),
        (None, "off"), ("", "off"), ("something else", "off"),
    ])
    def test_status(self, status, color):
        assert sd.status_color(status) == color


class TestCleanKeys:
    def test_valid_keys_are_sorted_and_filled_in(self):
        keys = sd.clean_keys([{"key": 2, "action": "undo"}, {"key": 0, "action": "reset_board", "label": "Reset", "color": "#FF0000"}])
        assert keys == [{"key": 0, "action": "reset_board", "label": "Reset", "color": "#ff0000", "hold": 0, "image": "", "show": ""},
                        {"key": 2, "action": "undo", "label": "Undo", "color": "#000000", "hold": 0, "image": "", "show": ""}]

    def test_the_last_entry_for_a_key_wins(self):
        keys = sd.clean_keys([{"key": 1, "action": "undo"}, {"key": 1, "action": "next_game"}])
        assert [k["action"] for k in keys] == ["next_game"]

    @pytest.mark.parametrize("bad", [
        "x", [1], [{"key": -1, "action": "undo"}], [{"key": "0", "action": "undo"}], [{"key": True, "action": "undo"}],
        [{"key": 0, "action": "launch"}], [{"key": 0, "action": "undo", "color": "red"}], [{"key": 0, "action": "undo", "color": "#12345"}],
        [{"key": i, "action": "undo"} for i in range(65)],
        [{"key": 0, "action": "undo", "hold": -1}], [{"key": 0, "action": "undo", "hold": 6}], [{"key": 0, "action": "undo", "hold": "1"}],
        [{"key": 0, "action": "undo", "hold": True}],
        [{"key": 0, "action": "undo", "image": "../x.png"}], [{"key": 0, "action": "undo", "image": "x.gif"}], [{"key": 0, "action": "undo", "image": "symbol:nope"}],
        [{"key": 0, "action": "undo", "image": 5}], [{"key": 0, "action": "undo", "image": "dir/x.png"}],
    ])
    def test_bad_layouts_are_refused(self, bad):
        with pytest.raises(ValueError):
            sd.clean_keys(bad)


class TestRender:
    def test_the_key_has_the_color_and_the_size(self):
        pytest.importorskip("PIL")
        img = sd.render_key("", "#cc2a2a", (72, 72))
        assert img.size == (72, 72) and img.getpixel((0, 0)) == (0xcc, 0x2a, 0x2a)

    def test_a_label_changes_the_image_and_keeps_the_corner_color(self):
        pytest.importorskip("PIL")
        img = sd.render_key("Reset Board", "#1faa59", (72, 72))
        assert img.getpixel((0, 0)) == (0x1f, 0xaa, 0x59)
        assert img.tobytes() != sd.render_key("", "#1faa59", (72, 72)).tobytes()


@pytest.fixture
def service(tmp_path):
    pytest.importorskip("PIL")
    path = tmp_path / "config.toml"
    calls = []
    deck = FakeDeck()
    svc = sd.StreamDeckService(str(path), calls.append, enumerate_decks=lambda: [deck], to_native=lambda d, img: img, reconnect_seconds=0.01)
    svc.deck, svc.calls = deck, calls
    return svc


class TestService:
    def test_disabled_does_not_open_the_device(self, service):
        assert service.enabled() is False
        assert service.snapshot()["connected"] is False

    def test_connects_and_draws_every_key(self, service):
        service.update(enabled=True, keys=[{"key": 0, "action": "reset_board", "color": "status"}])
        with service._lock:
            service._connect()
        deck = service.deck
        assert deck.opened and deck.brightness == sd.DEFAULT_BRIGHTNESS and set(deck.images) == set(range(6))
        assert deck.images[0].getpixel((0, 0)) == (0, 0, 0)          # status unknown: off
        service.on_board_status("Board Stopped")
        assert deck.images[0].getpixel((0, 0)) == (0xcc, 0x2a, 0x2a)
        assert deck.images[1].getpixel((0, 0)) == (0, 0, 0)          # an unassigned key stays dark

    def test_a_fixed_color_ignores_the_status(self, service):
        service.update(enabled=True, keys=[{"key": 0, "action": "undo", "color": "#0000ff"}])
        with service._lock:
            service._connect()
        service.on_board_status("Throw")
        assert service.deck.images[0].getpixel((0, 0)) == (0, 0, 0xff)

    def test_unused_keys_and_new_keys_are_black(self, service):
        service.update(enabled=True, keys=[{"key": 0, "action": "undo"}])
        with service._lock:
            service._connect()
        service.on_board_status("Throw")
        assert service.deck.images[0].getpixel((0, 0)) == (0, 0, 0)
        assert service.deck.images[1].getpixel((0, 0)) == (0, 0, 0)

    def test_a_reset_key_becomes_a_start_key_while_the_board_is_stopped(self, service):
        service.update(enabled=True, keys=[{"key": 0, "action": "reset_board", "image": "symbol:reset"}])
        with service._lock:
            service._connect()
        service.on_board_status("Stopped")
        service.deck.callback(service.deck, 0, True)
        assert service.calls == ["start_board"]
        assert service._effective(service.keys()[0])["label"] == "Start Board"
        service.on_board_status("Throw")
        service.deck.callback(service.deck, 0, True)
        assert service.calls == ["start_board", "reset_board"]

    def test_pressing_a_key_runs_its_action_and_release_does_nothing(self, service):
        service.update(enabled=True, keys=[{"key": 3, "action": "next_player"}])
        with service._lock:
            service._connect()
        service.deck.callback(service.deck, 3, True)
        service.deck.callback(service.deck, 3, False)
        service.deck.callback(service.deck, 4, True)
        assert service.calls == ["next_player"]

    def test_unplugging_closes_and_replugging_reconnects(self, service):
        service.update(enabled=True)
        service.start()
        try:
            _wait(lambda: service.snapshot()["connected"])
            first = service.deck
            first._connected = False
            fresh = FakeDeck()
            service._enumerate = lambda: [fresh]
            _wait(lambda: service.snapshot()["connected"] and service._deck is fresh)
            assert first.closed
        finally:
            service.stop()

    def test_no_hid_backend_is_reported(self, service):
        class ProbeError(Exception):
            pass

        def boom():
            raise ProbeError("no backend")
        service._enumerate = boom
        service.update(enabled=True)
        with service._lock:
            service._connect()
        snap = service.snapshot()
        assert snap["connected"] is False and snap["device_error"] == "no_hid_backend"
        assert "error" not in snap          # the page takes an `error` of the answer for a failed request

    def test_snapshot_of_an_unplugged_setup_shows_the_default_grid_and_the_layout(self, service):
        service.update(keys=[{"key": 1, "action": "start_board"}])
        service.on_board_status("Throw")
        snap = service.snapshot()
        assert (snap["rows"], snap["cols"]) == (sd.DEFAULT_ROWS, sd.DEFAULT_COLS)
        assert snap["keys"] == [{"key": 1, "action": "start_board", "label": "Start Board", "color": "#000000", "hold": 0, "image": "", "show": "", "shown": "#000000", "value": None}]

    def test_update_refuses_bad_values_and_writes_nothing(self, service):
        with pytest.raises(ValueError):
            service.update(brightness=101)
        with pytest.raises(ValueError):
            service.update(keys=[{"key": 0, "action": "nope"}])
        assert cfg_mod.load(service.config_path) == {}

    def test_brightness_is_applied_to_an_open_device(self, service):
        service.update(enabled=True)
        with service._lock:
            service._connect()
        service.update(brightness=20)
        assert service.deck.brightness == 20


def _wait(cond, timeout=3.0):
    import time
    end = time.time() + timeout
    while time.time() < end:
        if cond():
            return
        time.sleep(0.01)
    raise AssertionError("condition not met")


class TestBoardStatusListener:
    def test_the_game_state_tells_its_listeners(self):
        state, seen = GameState(), []
        state.board_status_listeners.append(seen.append)
        state.update({"event": "Board Status", "data": {"status": "Throw"}})
        assert seen == ["Throw"]

    def test_a_failing_listener_does_not_stop_the_update(self):
        state = GameState()
        state.board_status_listeners.append(lambda s: 1 / 0)
        assert state.update({"event": "Board Status", "data": {"status": "Throw"}}) == {"type": "board_status", "status": "Throw"}


class TestCleanActions:
    def test_a_route_and_an_address_are_kept_and_get_an_id(self):
        actions = sd.clean_actions([
            {"name": " Undo twice ", "kind": "route", "method": "post", "target": "/api/control/undo"},
            {"name": "Light", "kind": "url", "method": "PUT", "target": "https://ha.example/api/webhook/x", "body": '{"on": true}'},
        ])
        assert [a["name"] for a in actions] == ["Undo twice", "Light"]
        assert actions[0]["method"] == "POST" and actions[0]["id"].startswith("custom-") and actions[0]["body"] == ""
        assert actions[1]["body"] == '{"on": true}' and actions[0]["id"] != actions[1]["id"]

    def test_the_id_is_kept_when_given(self):
        assert sd.clean_actions([{"id": "custom-a1", "name": "x", "kind": "route", "target": "/api/state"}])[0]["id"] == "custom-a1"

    @pytest.mark.parametrize("bad", [
        "x", [1], [{"name": "", "kind": "route", "target": "/api/x"}], [{"name": "x", "kind": "shell", "target": "/api/x"}],
        [{"name": "x", "kind": "route", "target": "/state"}], [{"name": "x", "kind": "route", "target": "/api/a b"}],
        [{"name": "x", "kind": "url", "target": "ftp://host/x"}], [{"name": "x", "kind": "url", "target": "file:///etc/passwd"}],
        [{"name": "x", "kind": "route", "method": "TRACE", "target": "/api/x"}], [{"name": "x", "kind": "route", "target": "/api/x", "body": 5}],
        [{"id": "other", "name": "x", "kind": "route", "target": "/api/x"}], [{"id": "reset_board", "name": "x", "kind": "route", "target": "/api/x"}],
        [{"id": "custom-1", "name": "x", "kind": "route", "target": "/api/x"}, {"id": "custom-1", "name": "y", "kind": "route", "target": "/api/y"}],
        [{"name": "x", "kind": "route", "target": "/api/x"}] * 33,
    ])
    def test_bad_actions_are_refused(self, bad):
        with pytest.raises(ValueError):
            sd.clean_actions(bad)

    def test_a_key_may_use_a_custom_action_only_when_it_exists(self):
        assert sd.clean_keys([{"key": 0, "action": "custom-a1"}], {"custom-a1"})[0]["label"] == ""
        with pytest.raises(ValueError):
            sd.clean_keys([{"key": 0, "action": "custom-a1"}])


class TestCustomActions:
    @pytest.fixture
    def sent(self, service):
        sent = []

        class Response:
            status_code = 200
        service._request = lambda method, url, **kw: sent.append((method, url, kw)) or Response()
        service._web_base = lambda: "http://127.0.0.1:8080"
        return sent

    def _press(self, service, actions, action_id=None):
        service.update(enabled=True, actions=actions)
        action_id = action_id or service.actions()[0]["id"]
        service.update(keys=[{"key": 0, "action": action_id, "label": "x"}])
        with service._lock:
            service._connect()
        service.deck.callback(service.deck, 0, True)

    def test_a_route_is_called_on_breakfast_itself(self, service, sent):
        self._press(service, [{"name": "Undo", "kind": "route", "method": "POST", "target": "/api/control/undo"}])
        _wait(lambda: sent)
        assert sent == [("POST", "http://127.0.0.1:8080/api/control/undo", {"timeout": sd.REQUEST_TIMEOUT_SECONDS})]
        assert service.calls == []                                    # not a built-in control

    def test_an_address_is_called_with_a_json_body(self, service, sent):
        self._press(service, [{"name": "Light", "kind": "url", "method": "PUT", "target": "http://lamp.local/on", "body": '{"on": true}'}])
        _wait(lambda: sent)
        method, url, kw = sent[0]
        assert (method, url, kw["json"]) == ("PUT", "http://lamp.local/on", {"on": True})

    def test_a_body_that_is_no_json_goes_out_as_text(self, service, sent):
        self._press(service, [{"name": "Hook", "kind": "url", "method": "POST", "target": "http://h.local/x", "body": "on"}])
        _wait(lambda: sent)
        assert sent[0][2]["data"] == b"on" and "text/plain" in sent[0][2]["headers"]["Content-Type"]

    def test_a_slow_or_failing_target_does_not_block_or_raise(self, service):
        def hang(method, url, **kw):
            time.sleep(0.3)
            raise TimeoutError()
        service._request = hang
        started = time.time()
        self._press(service, [{"name": "Slow", "kind": "url", "method": "GET", "target": "http://slow.local/"}])
        assert time.time() - started < 0.25

    def test_deleting_an_action_takes_its_keys_with_it(self, service):
        service.update(actions=[{"id": "custom-a", "name": "A", "kind": "route", "target": "/api/x"},
                                {"id": "custom-b", "name": "B", "kind": "route", "target": "/api/y"}])
        service.update(keys=[{"key": 0, "action": "custom-a"}, {"key": 1, "action": "custom-b"}, {"key": 2, "action": "undo"}])
        service.update(actions=[{"id": "custom-b", "name": "B", "kind": "route", "target": "/api/y"}])
        assert [k["action"] for k in service.keys()] == ["custom-b", "undo"]

    def test_a_key_with_an_unknown_custom_action_is_refused(self, service):
        with pytest.raises(ValueError):
            service.update(keys=[{"key": 0, "action": "custom-zzz"}])

    def test_the_snapshot_lists_built_in_and_custom_actions(self, service):
        service.update(actions=[{"id": "custom-a", "name": "Lamp", "kind": "url", "target": "http://l.local/"}])
        snap = service.snapshot()
        assert {"id": "custom-a", "label": "Lamp", "custom": True} in snap["actions"]
        assert {"id": "undo", "label": "Undo", "custom": False} in snap["actions"]
        assert snap["custom_actions"][0]["target"] == "http://l.local/"


def _png(color=(200, 50, 50), size=(40, 30)):
    import io
    from PIL import Image
    out = io.BytesIO()
    Image.new("RGB", size, color).save(out, "PNG")
    return out.getvalue()


class TestImages:
    def test_valid_image_values(self):
        assert all(sd.valid_image(v) for v in ("", "symbol:undo", "logo.png", "My logo 2.JPG", "a-b_c.webp", "x.jpeg"))
        assert not any(sd.valid_image(v) for v in ("symbol:nope", "x.gif", "../x.png", "a/b.png", ".png", None, 3))

    def test_a_key_keeps_its_image(self):
        assert sd.clean_keys([{"key": 0, "action": "undo", "image": "symbol:undo"}])[0]["image"] == "symbol:undo"

    def test_uploaded_pictures_are_listed_and_a_wrong_file_is_refused(self, service):
        service.save_image("logo.png", _png())
        service.save_image("b.png", _png())
        assert service.images() == ["b.png", "logo.png"] and service.image_dir().name == "streamdeck"
        for name, data in (("x.png", b"not a picture"), ("x.gif", _png()), ("../x.png", _png()), ("x.png", b""),
                           ("x.png", _png() + b"0" * sd.MAX_IMAGE_BYTES), ("x.png", _png(size=(4001, 10)))):
            with pytest.raises(ValueError):
                service.save_image(name, data)
        assert service.images() == ["b.png", "logo.png"]

    def test_a_key_with_a_picture_is_drawn_with_it_and_in_the_frame_color(self, service):
        service.save_image("logo.png", _png(color=(0, 0, 255), size=(30, 30)))
        service.update(enabled=True, keys=[{"key": 0, "action": "undo", "label": "", "image": "logo.png", "color": "status"}])
        with service._lock:
            service._connect()
        service.on_board_status("Board Stopped")
        img = service.deck.images[0]
        assert img.getpixel((0, 0)) == (0xcc, 0x2a, 0x2a)          # the frame follows the status
        assert img.getpixel((36, 36)) == (0, 0, 255)               # the picture fills the middle

    def test_a_symbol_is_drawn_on_the_color(self, service):
        service.update(enabled=True, keys=[{"key": 0, "action": "undo", "label": "", "image": "symbol:start"}])
        with service._lock:
            service._connect()
        img = service.deck.images[0]
        assert img.getpixel((0, 0)) == (0, 0, 0) and img.getpixel((36, 36)) == (255, 255, 255)

    def test_a_missing_file_draws_the_key_without_a_picture(self, service):
        service.update(enabled=True, keys=[{"key": 0, "action": "undo", "label": "", "image": "gone.png"}])
        with service._lock:
            service._connect()
        assert service.deck.images[0].getpixel((36, 36)) == (0, 0, 0)

    def test_deleting_a_picture_clears_the_keys_that_use_it(self, service):
        service.save_image("logo.png", _png())
        service.update(keys=[{"key": 0, "action": "undo", "image": "logo.png"}, {"key": 1, "action": "undo", "image": "symbol:undo"}])
        service.delete_image("logo.png")
        assert service.images() == [] and [k["image"] for k in service.keys()] == ["", "symbol:undo"]
        with pytest.raises(ValueError):
            service.delete_image("logo.png")

    def test_a_replaced_file_is_loaded_again(self, service):
        service.save_image("logo.png", _png(color=(0, 0, 255)))
        service.update(keys=[{"key": 0, "action": "undo", "label": "", "image": "logo.png"}])
        first = service.preview(0)
        service.save_image("logo.png", _png(color=(0, 255, 0)))
        assert service.preview(0) != first

    def test_the_preview_is_a_png_of_the_key_and_empty_keys_have_none(self, service):
        service.update(keys=[{"key": 0, "action": "undo", "label": "Undo", "image": "symbol:undo"}])
        png = service.preview(0)
        assert png.startswith(b"\x89PNG") and service.preview(1) is None

    def test_every_symbol_draws(self):
        pytest.importorskip("PIL")
        blank = sd.render_key("", "#1faa59", (72, 72)).tobytes()
        for name in sd.SYMBOLS:
            assert sd.render_key("", "#1faa59", (72, 72), symbol=name).tobytes() != blank


class TestDisplayKeys:
    @pytest.fixture
    def game(self, service):
        game = {"values": None}
        service._values = lambda: game["values"]
        service.draws = []
        original = FakeDeck.set_key_image
        service.deck.set_key_image = lambda i, img: (service.draws.append(i), original(service.deck, i, img))[1]
        service.update(enabled=True, keys=[{"key": 0, "action": "", "show": "remaining", "label": "Score", "color": "#0000ff"},
                                           {"key": 1, "action": "undo", "show": "player", "label": "Who"}])
        with service._lock:
            service._connect()
        service.draws.clear()
        return game

    def test_a_key_needs_an_action_or_a_value(self):
        assert sd.clean_keys([{"key": 0, "show": "round"}])[0]["action"] == ""
        for bad in ([{"key": 0}], [{"key": 0, "action": ""}], [{"key": 0, "show": "nonsense"}], [{"key": 0, "action": "undo", "show": 5}]):
            with pytest.raises(ValueError):
                sd.clean_keys(bad)

    def test_the_key_shows_the_label_until_a_game_runs(self, service, game):
        before = service.deck.images[0].tobytes()
        game["values"] = {"remaining": 170, "player": "anna"}
        service.on_game_change()
        assert service.deck.images[0].tobytes() != before
        assert service.snapshot()["keys"][0]["value"] == "170" and service.snapshot()["keys"][1]["value"] == "anna"
        game["values"] = None
        service.on_game_change()
        assert service.deck.images[0].tobytes() == before and service.snapshot()["keys"][0]["value"] is None

    def test_only_a_changed_value_is_drawn_again(self, service, game):
        game["values"] = {"remaining": 170, "player": "anna"}
        service.on_game_change()
        assert sorted(service.draws) == [0, 1]
        service.draws.clear()
        service.on_game_change()
        game["values"] = {"remaining": 130, "player": "anna"}
        service.on_game_change()
        assert service.draws == [0]

    def test_a_value_that_does_not_apply_falls_back_to_the_label(self, service, game):
        game["values"] = {"remaining": None, "player": "ben"}
        service.on_game_change()
        assert service.snapshot()["keys"][0]["value"] is None

    def test_a_display_key_without_action_does_nothing_when_pressed(self, service, game):
        service.deck.callback(service.deck, 0, True)
        assert service.calls == []
        service.deck.callback(service.deck, 1, True)           # a display key with an action still runs it
        assert service.calls == ["undo"]

    def test_a_failing_game_read_shows_the_labels(self, service, game):
        def broken():
            raise RuntimeError
        service._values = broken
        service.on_game_change()
        assert service.snapshot()["keys"][0]["value"] is None

    def test_the_display_keys_flash_and_are_normal_again(self, service, game, monkeypatch):
        monkeypatch.setattr(sd, "FLASH_STEP_SECONDS", 0.02)
        normal = service.deck.images[0].tobytes()
        service.flash(0.15)
        _wait(lambda: service.deck.images[0].getpixel((0, 0)) == (0xe6, 0xa8, 0x00))
        _wait(lambda: service.deck.images[0].tobytes() == normal and not service._flash_phase)

    def test_a_flash_without_a_device_does_nothing(self, service):
        service.flash()
        assert service._flash_until == 0


class TestGameValues:
    class Ctrl:
        def __init__(self, snap, state="playing"):
            self.game = type("G", (), {"state": state, "snapshot": lambda self_: snap})()

    def test_x01_gives_the_player_on_turn_and_his_score(self):
        from breakfast.web import server
        snap = {"current_player": "anna", "round": 3, "current_darts": [20, 5],
                "players": [{"name": "ben", "remaining": 301, "current": False}, {"name": "anna", "remaining": 170, "current": True}]}
        server.wire(None, None, x01_ctrl=self.Ctrl(snap))
        try:
            assert server._game_values() == {"player": "anna", "remaining": 170, "lives": None, "darts": 2, "round": 3}
        finally:
            server.wire(None, None)

    def test_elimination_gives_the_lives(self):
        from breakfast.web import server
        snap = {"current_player": "ben", "current_darts": [], "players": [{"name": "ben", "lives": 2, "current": True}]}
        server.wire(None, self.Ctrl(snap))
        try:
            assert server._game_values() == {"player": "ben", "remaining": None, "lives": 2, "darts": 0, "round": None}
        finally:
            server.wire(None, None)

    def test_nothing_while_no_game_plays(self):
        from breakfast.web import server
        server.wire(None, None, x01_ctrl=self.Ctrl({}, state="finished"))
        try:
            assert server._game_values() is None
        finally:
            server.wire(None, None)

    def test_a_push_and_an_earned_achievement_reach_the_service(self, tmp_path):
        from breakfast.web import server
        path = tmp_path / "config.toml"
        path.write_text('mode = "direct"\n')
        server.wire(GameState(), None, config_path=str(path))
        seen = []
        server._streamdeck.on_game_change = lambda: seen.append("change")
        server._streamdeck.flash = lambda: seen.append("flash")
        try:
            server.push()
            server.push_achievement({"type": "achievement"})
        finally:
            server.wire(None, None)
        assert seen == ["change", "flash"]


class TestHold:
    def _connect(self, service, hold):
        service._hold_step = 0.01
        service.update(enabled=True, keys=[{"key": 0, "action": "reset_board", "hold": hold}])
        with service._lock:
            service._connect()
        return service.deck

    def test_a_key_without_hold_runs_on_the_press(self, service):
        deck = self._connect(service, 0)
        deck.callback(deck, 0, True)
        assert service.calls == ["reset_board"]

    def test_a_held_key_runs_its_action_after_the_time_and_only_once(self, service):
        deck = self._connect(service, 0.1)
        deck.callback(deck, 0, True)
        assert service.calls == []
        _wait(lambda: service.calls == ["reset_board"])
        deck.callback(deck, 0, False)
        time.sleep(0.05)
        assert service.calls == ["reset_board"]

    def test_a_key_let_go_early_does_nothing_and_is_drawn_normally_again(self, service):
        deck = self._connect(service, 0.3)
        normal = deck.images[0].tobytes()
        deck.callback(deck, 0, True)
        _wait(lambda: deck.images[0].tobytes() != normal)             # the progress bar is drawn
        deck.callback(deck, 0, False)
        time.sleep(0.4)
        assert service.calls == [] and deck.images[0].tobytes() == normal

    def test_pressing_again_starts_the_hold_over(self, service):
        deck = self._connect(service, 0.2)
        deck.callback(deck, 0, True)
        time.sleep(0.1)
        deck.callback(deck, 0, False)
        deck.callback(deck, 0, True)
        time.sleep(0.15)
        assert service.calls == []
        _wait(lambda: service.calls == ["reset_board"])

    def test_closing_the_device_cancels_a_hold(self, service):
        deck = self._connect(service, 0.2)
        deck.callback(deck, 0, True)
        with service._lock:
            service._close()
        time.sleep(0.35)
        assert service.calls == []

    def test_the_progress_bar_fills_with_the_progress(self):
        pytest.importorskip("PIL")
        empty, half, full = (sd.render_key("", "#cc2a2a", (72, 72), p) for p in (0, 0.5, 1))
        dark, white = (20, 20, 20), (255, 255, 255)
        assert empty.getpixel((10, 70)) == dark
        assert half.getpixel((10, 70)) == white and half.getpixel((60, 70)) == dark
        assert full.getpixel((70, 70)) == white and full.getpixel((10, 10)) == (0xcc, 0x2a, 0x2a)


class TestRoutes:
    @pytest.fixture
    def server(self, tmp_path):
        pytest.importorskip("PIL")
        from breakfast.web import server
        path = tmp_path / "config.toml"
        path.write_text('mode = "direct"\n')
        state = GameState()
        server.wire(state, None, config_path=str(path))
        yield server, state, path
        server.wire(None, None)

    def test_get_shows_the_settings_and_follows_the_board_status(self, server):
        import asyncio
        srv, state, _ = server
        state.update({"event": "Board Status", "data": {"status": "Board Stopped"}})
        snap = asyncio.run(srv.streamdeck_get())
        assert snap["enabled"] is False and snap["board_status"] == "Board Stopped" and snap["status_color"] == "red"

    def test_put_saves_the_layout_into_the_config(self, server):
        import asyncio
        srv, _, path = server
        body = srv.StreamDeckBody(enabled=True, brightness=40, keys=[{"key": 0, "action": "reset_board", "label": "Reset"}])
        snap = asyncio.run(srv.streamdeck_put(body))
        assert snap["enabled"] and snap["brightness"] == 40 and snap["keys"][0]["label"] == "Reset"
        assert cfg_mod.load(path)["streamdeck"]["keys"] == [{"key": 0, "action": "reset_board", "label": "Reset", "color": "#000000", "hold": 0, "image": "", "show": ""}]

    def test_put_answers_a_bad_layout_with_an_error(self, server):
        import asyncio
        srv, _, path = server
        res = asyncio.run(srv.streamdeck_put(srv.StreamDeckBody(keys=[{"key": 0, "action": "nope"}])))
        assert "unknown action" in res["error"] and "streamdeck" not in cfg_mod.load(path)

    def test_upload_serve_and_delete_a_picture_over_the_routes(self, server):
        import asyncio
        srv, _, path = server

        class Req:
            async def body(self):
                return _png()
        assert asyncio.run(srv.streamdeck_image_upload(Req(), name="logo.png")) == {"ok": True, "file": "logo.png"}
        assert (path.parent / "streamdeck" / "logo.png").is_file()
        assert asyncio.run(srv.streamdeck_image("logo.png")).path == path.parent / "streamdeck" / "logo.png"
        assert "error" in asyncio.run(srv.streamdeck_image_upload(Req(), name="../logo.png"))
        assert asyncio.run(srv.streamdeck_image_delete("logo.png"))["images"] == []
        with pytest.raises(Exception):
            asyncio.run(srv.streamdeck_image("../../config.toml"))

    def test_the_key_preview_route(self, server):
        import asyncio
        srv, _, _ = server
        asyncio.run(srv.streamdeck_put(srv.StreamDeckBody(keys=[{"key": 0, "action": "undo", "image": "symbol:undo"}])))
        assert asyncio.run(srv.streamdeck_key_png(0)).media_type == "image/png"
        with pytest.raises(Exception):
            asyncio.run(srv.streamdeck_key_png(1))

    def test_a_status_change_reaches_the_service(self, server):
        srv, state, _ = server
        state.update({"event": "Board Status", "data": {"status": "Throw"}})
        assert srv._streamdeck.board_status == "Throw"


class TestRunControl:
    def test_every_stream_deck_action_is_a_control(self):
        from breakfast.web import server
        assert set(sd.ACTIONS) == set(server._CONTROLS)

    def test_the_cloud_client_runs_the_action(self, monkeypatch):
        from breakfast.web import server

        class Client:
            def __init__(self): self.calls = []
            def undo_throw(self): self.calls.append("undo_throw")
        client = Client()
        server.wire(None, None, cloud_client=client)
        monkeypatch.setattr(server, "_run_in_thread", lambda fn: fn())
        try:
            assert server.run_control("undo") == {"ok": True}
        finally:
            server.wire(None, None)
        assert client.calls == ["undo_throw"]

    def test_without_a_client_or_url_the_answer_is_an_error(self):
        from breakfast.web import server
        server.wire(None, None)
        assert server.run_control("next_game") == {"error": "cloud control not available"}


class TestLocalGameControls:
    @pytest.fixture
    def local(self, tmp_path):
        from types import SimpleNamespace
        from breakfast.web import server
        calls = []
        game = SimpleNamespace(state="playing", undo=lambda: calls.append("undo") or True)
        ctrl = SimpleNamespace(game=game, next_turn=lambda: calls.append("next") or True, stop=lambda: calls.append("stop"))
        server.wire(GameState(), None, config_path=str(tmp_path / "config.toml"), x01_ctrl=ctrl)
        yield server, calls
        server.wire(None, None)

    @pytest.mark.parametrize("action, expected", [("undo", "undo"), ("next_player", "next"), ("cancel_game", "stop")])
    def test_a_game_run_by_breakfast_takes_the_controls(self, local, action, expected):
        srv, calls = local
        assert srv.run_control(action) == {"ok": True}
        _wait(lambda: calls == [expected])

    def test_without_a_game_a_local_only_control_is_refused(self, tmp_path):
        from breakfast.web import server
        server.wire(GameState(), None, config_path=str(tmp_path / "config.toml"))
        try:
            assert "error" in server.run_control("cancel_game")
        finally:
            server.wire(None, None)
