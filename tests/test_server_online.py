import asyncio

import pytest

from breakfast import config as cfg_mod
from breakfast import locations
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

    def create(self, relay_url, site, password="", sign=None):
        self.calls.append(("create", relay_url, site, password) if sign is None else ("create", relay_url, site, password, "signed"))
        self._active = True
        return "K7M2QX"

    def join(self, relay_url, code, site, password=None, ticket=None, game=None):
        self.calls.append(("join", relay_url, code, site, password) if ticket is None else ("join", relay_url, code, site, ticket))
        if game:
            self.calls.append(("game", game))
        if password == "bad":
            raise online_mod.RelayError("wrong password")

    def voice_url(self, lang="en"):
        self.calls.append(("voice", lang))
        return "https://relay/voice#code=K7M2QX"

    def set_ready(self, ready):
        self.calls.append(("ready", ready))

    def set_players(self, players):
        self.calls.append(("players", players))

    def start(self, lives, order, game="elimination", rules=None):
        self.calls.append(("start", lives, order) if game == "elimination" else ("start", game, rules, order))

    def set_rules(self, game, lives, rules):
        self.calls.append(("rules", game, lives, rules))

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
    assert res == {"configured": True, "site_name": "Home", "location_name": None, "status": None}


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


class FakeLocations:
    def __init__(self, name="Garage"):
        self.name = name
        self.tickets = []

    def status(self):
        return {"registered": True, "name": self.name}

    def signer_for(self, relay_url):
        return lambda method, path, raw: {"x-location": "a" * 32}

    def open_matches(self):
        return [{"code": "K7M2QX", "location": {"id": "b" * 32, "name": "Club"}, "site": "Club", "sites": 1, "players": 0}]

    def join_ticket(self, code):
        self.tickets.append(code)
        return "t" * 32

    def voice_channels(self):
        return [{"id": "d" * 32, "name": "Kitchen"}]

    def voice_channel_url(self, channel_id, lang="en"):
        if channel_id != "d" * 32:
            raise locations.LocationError("unknown channel")
        return f"https://relay/voice#channel={channel_id}&lang={lang}"


def test_a_host_needs_no_password_and_a_registered_location_signs_and_names_the_site(tmp_path):
    config_path = tmp_path / "config.toml"
    cfg_mod.write(str(config_path), {"online": {"relay_url": "ws://relay"}})
    server.wire(None, EliminationController(NullMqttPublisher(), "autodarts"), config_path=str(config_path))
    server._online = FakeSession()
    server._locations = FakeLocations()
    try:
        res = run(server.online_create(server.OnlineCreateBody()))
        assert res == {"ok": True, "code": "K7M2QX"}
        assert server._online.calls == [("create", "ws://relay", "Garage", "", "signed")]
        assert run(server.online_status())["location_name"] == "Garage"
    finally:
        server.wire(None, None)


def test_the_open_matches_of_linked_locations_are_listed_and_joined_with_a_ticket(tmp_path):
    config_path = tmp_path / "config.toml"
    cfg_mod.write(str(config_path), {"online": {"relay_url": "ws://relay", "site_name": "Home"}})
    server.wire(None, EliminationController(NullMqttPublisher(), "autodarts"), config_path=str(config_path))
    server._online = FakeSession()
    server._locations = FakeLocations()
    try:
        res = run(server.online_open())
        assert res["registered"] is True and res["matches"][0]["location"]["name"] == "Club"
        assert run(server.online_join_linked(server.OnlineLinkedJoinBody(code="K7M2QX"))) == {"ok": True}
        assert server._locations.tickets == ["K7M2QX"]
        assert server._online.calls == [("join", "ws://relay", "K7M2QX", "Home", "t" * 32)]
        run(server.online_ready(server.OnlineReadyBody(ready=True)))
        assert server._online.calls[-1] == ("ready", True)
    finally:
        server.wire(None, None)


def test_without_a_registered_location_there_is_no_list_and_no_linked_join(wired):
    assert run(server.online_open()) == {"ok": True, "registered": False, "matches": []}
    res = run(server.online_join_linked(server.OnlineLinkedJoinBody(code="K7M2QX")))
    assert "register" in res["error"]
    res = run(server.online_join(server.OnlineJoinBody(code="K7M2QX", site="Club")))
    assert "password" in res["error"]


def test_the_voice_address_is_asked_in_the_language_of_the_interface(wired, tmp_path):
    assert run(server.online_voice()) == {"ok": True, "url": "https://relay/voice#code=K7M2QX"}
    assert server._online.calls[-1] == ("voice", "en")
    cfg_mod.write(str(server._config_path), {"online": {"relay_url": "ws://relay"}, "web": {"language": "de"}})
    run(server.online_voice())
    assert server._online.calls[-1] == ("voice", "de")


def test_the_voice_channels_are_listed_and_opened_in_the_language_of_the_interface(tmp_path):
    config_path = tmp_path / "config.toml"
    cfg_mod.write(str(config_path), {"web": {"language": "de"}})
    server.wire(None, EliminationController(NullMqttPublisher(), "autodarts"), config_path=str(config_path))
    server._locations = FakeLocations()
    try:
        assert run(server.voice_channels()) == {"channels": [{"id": "d" * 32, "name": "Kitchen"}]}
        assert run(server.voice_channel_open("d" * 32)) == {"ok": True, "url": f"https://relay/voice#channel={'d' * 32}&lang=de"}
        assert run(server.voice_channel_open("e" * 32)) == {"error": "unknown channel"}
    finally:
        server.wire(None, None)


def test_without_locations_there_are_no_voice_channels(wired):
    server._locations = None
    assert "not available" in run(server.voice_channels())["error"]
    assert "not available" in run(server.voice_channel_open("d" * 32))["error"]


X01_RULES = {"start": 501, "in_mode": "straight", "out_mode": "double", "legs": 3, "bull_off": True, "max_rounds": None}


def test_the_rules_of_an_x01_lobby_are_checked_before_they_go_to_the_relay(wired):
    from breakfast.x01_game import X01Controller
    server._x01_ctrl = X01Controller(lambda e: None)
    try:
        assert run(server.online_rules(server.OnlineRulesBody(game="x01", rules=X01_RULES))) == {"ok": True}
        assert run(server.online_start(server.OnlineStartBody(game="x01", rules=X01_RULES, order=["anna", "carl"]))) == {"ok": True}
        assert server._online.calls[-2:] == [("rules", "x01", 3, X01_RULES), ("start", "x01", X01_RULES, ["anna", "carl"])]
        bad = run(server.online_start(server.OnlineStartBody(game="x01", rules={**X01_RULES, "legs": 0}, order=["anna", "carl"])))
        assert "legs" in bad["error"]
        assert "game" in run(server.online_rules(server.OnlineRulesBody(game="chess")))["error"]
    finally:
        server._x01_ctrl = None


def test_the_game_of_the_page_goes_with_a_join(tmp_path):
    config_path = tmp_path / "config.toml"
    cfg_mod.write(str(config_path), {"online": {"relay_url": "ws://relay", "site_name": "Home"}})
    server.wire(None, EliminationController(NullMqttPublisher(), "autodarts"), config_path=str(config_path))
    server._online = FakeSession()
    server._locations = FakeLocations()
    try:
        run(server.online_join(server.OnlineJoinBody(code="K7M2QX", password="pw", game="x01")))
        run(server.online_join_linked(server.OnlineLinkedJoinBody(code="K7M2QX", game="elimination")))
        assert ("game", "x01") in server._online.calls and ("game", "elimination") in server._online.calls
    finally:
        server.wire(None, None)
