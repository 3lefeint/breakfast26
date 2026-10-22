import pytest
from starlette.testclient import TestClient

from breakfast.elimination import EliminationController
from breakfast.killer import KillerController
from breakfast.stats import StatsDB, StatsTracker
from breakfast.web import server
from tests.test_target_battle import FakeMqttPub


@pytest.fixture
def client(tmp_path):
    db = StatsDB(str(tmp_path / "s.db"))
    killer = KillerController(FakeMqttPub(), "autodarts", stats_db=db)
    elim = EliminationController(FakeMqttPub(), "autodarts", stats_db=db)
    for ctrl in (killer, elim):
        ctrl.bots._spawn = lambda fn: None          # no bot plays during these tests
    db.upsert_player("ana")
    server.wire(None, elim, stats_tracker=StatsTracker(db), killer_ctrl=killer)
    yield TestClient(server.app), elim, killer
    server.wire(None, None)


ELIM = {"players": ["ana", "bot 60"], "bots": {"bot 60": 60}}
KILLER = {"players": ["ana", "bot 60"], "bots": {"bot 60": 60}, "bull_off": False, "throw_numbers": False}


def test_a_bot_can_be_added_to_an_elimination_game(client):
    c, elim, _ = client
    assert c.post("/api/elimination/start", json=ELIM).json() == {"ok": True}
    assert elim.bots.levels == {"bot 60": 60}


def test_a_bot_can_be_added_to_a_killer_game(client):
    c, _, killer = client
    assert c.post("/api/killer/start", json=KILLER).json() == {"ok": True}
    assert killer.bots.levels == {"bot 60": 60}


def test_a_game_without_bots_has_none(client):
    c, elim, _ = client
    assert c.post("/api/elimination/start", json={"players": ["ana", "bo"]}).json() == {"ok": True}
    assert elim.bots.levels == {}


@pytest.mark.parametrize("path, body", [("/api/elimination/start", ELIM), ("/api/killer/start", KILLER)])
@pytest.mark.parametrize("bots, error", [
    ({"bot 60": 65}, "unknown bot level"),
    ({"Somebody": 60}, "a bot has to be one of the players"),
    ({"ana": 60}, "a bot cannot have the name of a player"),
    ({"ana": 60, "bot 60": 60}, "a bot cannot have the name of a player"),
])
def test_a_bot_that_does_not_fit_is_refused(client, path, body, bots, error):
    c, *_ = client
    assert c.post(path, json={**body, "bots": bots}).json() == {"error": error}


def test_the_computer_cannot_play_alone(client):
    c, *_ = client
    body = {"players": ["bot 30", "bot 60"], "bots": {"bot 30": 30, "bot 60": 60}}
    assert c.post("/api/elimination/start", json=body).json() == {"error": "at least one player has to be human"}


def test_in_dev_mode_the_computer_can_play_alone(client, monkeypatch):
    c, elim, _ = client
    monkeypatch.setattr(server, "_dev_unlocked", True)
    body = {"players": ["bot 30", "bot 60"], "bots": {"bot 30": 30, "bot 60": 60}}
    assert c.post("/api/elimination/start", json=body).json() == {"ok": True}
    assert elim.bots.levels == {"bot 30": 30, "bot 60": 60}
