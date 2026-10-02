import asyncio

import pytest

from breakfast import config as cfg_mod
from breakfast import online as online_mod
from breakfast.elimination import EliminationController
from breakfast.mqtt_output import NullMqttPublisher
from breakfast.stats import StatsDB
from breakfast.web import server


class FakeSession:
    def __init__(self, active=False):
        self.calls = []
        self._active = active

    @property
    def active(self):
        return self._active

    def status(self):
        return {"phase": "lobby", "code": "K7M2QX"}

    def create(self, relay_url, site, password):
        self.calls.append(("create", relay_url, site, password))
        self._active = True
        return "K7M2QX"

    def join(self, relay_url, code, site, password):
        self.calls.append(("join", relay_url, code, site, password))
        if password == "bad":
            raise online_mod.RelayError("wrong password")

    def set_players(self, players):
        self.calls.append(("players", players))

    def start(self, lives, order):
        self.calls.append(("start", lives, order))

    def decide(self, choice):
        self.calls.append(("decide", choice))

    def rematch(self):
        self.calls.append(("rematch",))

    def leave(self):
        self.calls.append(("leave",))
        self._active = False


@pytest.fixture
def wired(tmp_path):
    config_path = tmp_path / "config.toml"
    cfg_mod.write(str(config_path), {"online": {"relay_url": "ws://relay", "site_name": "Home"}})
    ctrl = EliminationController(NullMqttPublisher(), "autodarts", stats_db=StatsDB(":memory:"))
    server.wire(None, ctrl, config_path=str(config_path))
    server._online = FakeSession()
    yield ctrl
    server.wire(None, None)


def run(coro):
    return asyncio.run(coro)


def test_status_says_whether_a_relay_is_configured(wired):
    res = run(server.online_status())
    assert res == {"configured": True, "site_name": "Home", "status": None}


def test_create_uses_the_configured_relay_and_site_name(wired):
    res = run(server.online_create(server.OnlineCreateBody(password="pw")))
    assert res == {"ok": True, "code": "K7M2QX"}
    assert server._online.calls == [("create", "ws://relay", "Home", "pw")]


def test_create_without_a_relay_says_so(tmp_path):
    config_path = tmp_path / "config.toml"
    cfg_mod.write(str(config_path), {})
    server.wire(None, EliminationController(NullMqttPublisher(), "autodarts"), config_path=str(config_path))
    server._online = FakeSession()
    try:
        res = run(server.online_create(server.OnlineCreateBody(password="pw")))
        assert "relay address" in res["error"]
    finally:
        server.wire(None, None)


def test_join_passes_the_code_and_reports_a_refusal(wired):
    run(server.online_join(server.OnlineJoinBody(code="k7m2qx", password="pw", site="Club")))
    assert server._online.calls[-1] == ("join", "ws://relay", "k7m2qx", "Club", "pw")
    res = run(server.online_join(server.OnlineJoinBody(code="k7m2qx", password="bad", site="Club")))
    assert res == {"error": "wrong password"}


def test_lobby_commands_reach_the_session(wired):
    run(server.online_players(server.OnlinePlayersBody(players=[" anna ", ""])))
    run(server.online_start(server.OnlineStartBody(lives=3, order=["anna", "carl"])))
    run(server.online_decision(server.OnlineDecisionBody(choice="continue")))
    run(server.online_rematch())
    assert server._online.calls == [("players", ["anna"]), ("start", 3, ["anna", "carl"]), ("decide", "continue"), ("rematch",)]


def test_a_local_game_cannot_start_while_an_online_match_is_open(wired):
    server._online._active = True
    res = run(server.elim_start(server.StartBody(players=["a", "b"], lives=3)))
    assert "online match" in res["error"]
    assert wired.game is None


def test_the_payload_carries_the_online_status_only_while_open(wired):
    assert server._build_payload()["online"] is None
    server._online._active = True
    assert server._build_payload()["online"] == {"phase": "lobby", "code": "K7M2QX"}


def test_stopping_the_game_leaves_the_online_match(wired):
    server._online._active = True
    run(server.elim_stop())
    assert server._online.calls == [("leave",)]
