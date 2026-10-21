import asyncio

import pytest

from breakfast import config as cfg_mod
from breakfast.web import server


@pytest.fixture
def configure(tmp_path):
    path = tmp_path / "config.toml"

    def go(sections=None):
        cfg_mod.write(str(path), sections or {"web": {"port": 8080}})
        server.wire(None, None, config_path=str(path))
    yield go
    server.wire(None, None)


def patch(body):
    return asyncio.run(server.patch_config(body))


class TestRestartRequired:
    def test_a_value_that_did_not_change_needs_no_restart(self, configure):
        configure({"mqtt": {"host": "broker", "enabled": True}, "caller": {"enabled": True}})
        assert patch({"mqtt": {"host": "broker", "enabled": True}, "caller": {"enabled": True}}) == \
            {"saved": True, "restart_required": []}

    def test_a_changed_value_is_named_with_its_section(self, configure):
        configure({"mqtt": {"host": "broker"}})
        assert patch({"mqtt": {"host": "other"}, "caller": {"per_dart": False}})["restart_required"] == \
            ["mqtt.host", "caller.per_dart"]

    def test_removing_a_key_needs_a_restart_only_when_it_was_set(self, configure):
        configure({"mqtt": {"host": "broker"}})
        assert patch({"mqtt": {"host": None, "username": None}})["restart_required"] == ["mqtt.host"]

    def test_settings_that_apply_at_once_never_ask_for_a_restart(self, configure):
        configure()
        res = patch({"logging": {"level": "DEBUG"}, "online": {"relay_url": "wss://relay.example", "site_name": "Home"},
                     "telemetry": {"enabled": True}, "web": {"joke_of_the_day": False}})
        assert res == {"saved": True, "restart_required": []}


class TestWebPort:
    def test_outside_docker_the_port_is_the_one_of_the_config(self, configure, monkeypatch):
        configure({"web": {"port": 9000}})
        monkeypatch.setattr(server, "_in_docker", lambda: False)
        assert asyncio.run(server.web_port_get()) == {"mode": "config", "port": 9000}

    def test_in_docker_the_updater_answers(self, configure, monkeypatch):
        configure()
        monkeypatch.setattr(server, "_in_docker", lambda: True)
        monkeypatch.setattr(server, "_updater_get", lambda path: {"port": 9000, "supported": True, "phase": "idle"})
        assert asyncio.run(server.web_port_get()) == {"mode": "docker", "port": 9000, "supported": True, "phase": "idle"}

    def test_an_unreachable_updater_is_reported(self, configure, monkeypatch):
        configure()
        monkeypatch.setattr(server, "_in_docker", lambda: True)

        def boom(path):
            raise ConnectionError("refused")
        monkeypatch.setattr(server, "_updater_get", boom)
        res = asyncio.run(server.web_port_get())
        assert res["mode"] == "docker" and "refused" in res["error"]

    @pytest.mark.parametrize("port", [80, 70000, "9000", None, True])
    def test_a_port_out_of_range_is_refused(self, configure, monkeypatch, port):
        configure()
        monkeypatch.setattr(server, "_in_docker", lambda: True)
        monkeypatch.setattr(server, "_updater_post", lambda path, body=None: pytest.fail("must not be asked"))
        assert asyncio.run(server.web_port_set({"port": port}))["code"] == "invalid"

    def test_outside_docker_it_is_refused(self, configure, monkeypatch):
        configure()
        monkeypatch.setattr(server, "_in_docker", lambda: False)
        assert asyncio.run(server.web_port_set({"port": 9000}))["code"] == "not_docker"

    def test_in_docker_the_updater_is_asked(self, configure, monkeypatch):
        configure()
        monkeypatch.setattr(server, "_in_docker", lambda: True)
        calls = []
        monkeypatch.setattr(server, "_updater_post", lambda path, body=None: calls.append((path, body)) or {"ok": True})
        assert asyncio.run(server.web_port_set({"port": 9000})) == {"ok": True}
        assert calls == [("/port", {"port": 9000})]


class TestStartBoard:
    def test_the_cloud_client_starts_the_board(self, monkeypatch):
        from breakfast import autodarts_client

        calls = []
        client = object.__new__(autodarts_client.AutodartsCloudClient)
        monkeypatch.setattr(client, "_get_board_address", lambda: "http://10.0.0.5:3180", raising=False)
        monkeypatch.setattr(autodarts_client.requests, "put", lambda url, timeout: calls.append(url))
        client.start_board()
        assert calls == ["http://10.0.0.5:3180/api/start"]

    def test_the_route_needs_cloud_control(self):
        server.wire(None, None)
        assert asyncio.run(server.control_start_board()) == {"error": "cloud control not available"}
