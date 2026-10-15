import pytest
from starlette.testclient import TestClient

from breakfast.elimination import EliminationController
from breakfast.killer import KillerController
from breakfast.state import GameState
from breakfast.stats import StatsDB, StatsTracker
from breakfast.web import server
from breakfast.x01_game import X01Controller
from tests.test_target_battle import FakeMqttPub, hit, play


@pytest.fixture(autouse=True)
def no_start_delay(monkeypatch):
    monkeypatch.setattr("breakfast.x01_game.START_CALLS_DELAY_S", 0)


@pytest.fixture
def client(tmp_path):
    db = StatsDB(str(tmp_path / "s.db"))
    tracker = StatsTracker(db)
    state = GameState()

    def emit(data):
        state.update(data)
        tracker.process(data)

    x01 = X01Controller(emit, stats_db=db, on_change=server.push)
    elim = EliminationController(FakeMqttPub(), "autodarts", stats_db=db)
    killer = KillerController(FakeMqttPub(), "autodarts", stats_db=db)
    server.wire(state, elim, stats_tracker=tracker, killer_ctrl=killer, x01_ctrl=x01)
    yield TestClient(server.app), x01, elim, killer, state, db
    server.wire(None, None)


START = {"players": ["ana", "bo"], "bull_off": False}


def test_a_match_can_be_started_and_shows_up_in_the_state(client):
    c, x01, *_ = client
    assert server._build_payload()["x01"] == {"active": False}
    assert c.post("/api/x01/start", json=START).json() == {"ok": True}
    snap = server._build_payload()["x01"]
    assert snap["active"] and sorted(snap["order"]) == ["ana", "bo"] and snap["phase"] == "playing"   # drawn
    assert snap["rules"] == {"start": 501, "in_mode": "straight", "out_mode": "double", "legs": 1, "bull_off": False}
    assert [p["remaining"] for p in snap["players"]] == [501, 501]
    assert server._build_payload()["game"]["match_started"]


def test_the_options_reach_the_game(client):
    c, x01, *_ = client
    c.post("/api/x01/start", json={**START, "start": 301, "in_mode": "double", "out_mode": "master", "legs": 3})
    assert server._build_payload()["x01"]["setup"] == {
        "start": 301, "in_mode": "double", "out_mode": "master", "legs": 3, "bull_off": False}


def test_names_are_trimmed_and_empty_ones_dropped(client):
    c, x01, *_ = client
    c.post("/api/x01/start", json={**START, "players": [" ana ", "", "bo", "  "]})
    assert sorted(x01.game.order) == ["ana", "bo"]


@pytest.mark.parametrize("body, message", [
    ({"players": []}, "at least 1"),
    ({"players": ["ana", "ana"]}, "only play once"),
    ({"players": ["ana"], "start": 1}, "start score"),
    ({"players": ["ana"], "in_mode": "x"}, "straight, double or master"),
    ({"players": ["ana"], "legs": 0}, "legs"),
])
def test_a_setup_that_cannot_be_played_comes_back_as_an_error(client, body, message):
    c, *_ = client
    assert message in c.post("/api/x01/start", json=body).json()["error"]


def test_a_game_that_is_running_blocks_the_start(client):
    c, x01, elim, killer, *_ = client
    c.post("/api/elimination/start", json={"players": ["ana", "bo"]})
    assert "Elimination" in c.post("/api/x01/start", json=START).json()["error"]
    assert x01.game is None


def test_a_running_match_blocks_the_other_games(client):
    c, x01, elim, killer, *_ = client
    c.post("/api/x01/start", json=START)
    assert "X01" in c.post("/api/elimination/start", json={"players": ["ana", "bo"]}).json()["error"]
    assert "X01" in c.post("/api/killer/start", json={"players": ["ana", "bo"]}).json()["error"]
    assert elim.game is None and killer.game is None


def test_a_finished_match_is_closed_by_the_start_of_another_game(client):
    c, x01, elim, killer, state, db = client
    c.post("/api/x01/start", json={**START, "start": 40})
    play(x01.game, hit(20, 2))
    assert x01.game.snapshot()["state"] == "finished"
    assert c.post("/api/elimination/start", json={"players": ["ana", "bo"]}).json() == {"ok": True}
    assert x01.game is None and not state.match_started


def test_undo_next_and_the_corrections_work_through_the_routes(client):
    c, x01, *_ = client
    c.post("/api/x01/start", json=START)
    x01.on_board_state(1, [hit(20, 1)])
    assert c.post("/api/x01/correct-dart", json={"dart": 1, "field": "T20"}).json() == {"ok": True}
    assert c.post("/api/x01/next").json() == {"ok": True}
    assert server._build_payload()["x01"]["players"][0]["remaining"] == 441
    assert c.post("/api/x01/correct-last-dart", json={"dart": 1, "field": "T19"}).json() == {"ok": True}
    assert server._build_payload()["x01"]["players"][0]["remaining"] == 444
    assert c.post("/api/x01/undo").json() == {"ok": True}
    assert server._build_payload()["x01"]["players"][0]["remaining"] == 501
    assert c.post("/api/x01/undo").json() == {"error": "nothing to undo"}


def test_a_dart_other_than_1_to_3_is_refused(client):
    c, *_ = client
    c.post("/api/x01/start", json=START)
    assert "must be" in c.post("/api/x01/correct-dart", json={"dart": 4, "field": "T20"}).json()["error"]
    assert "must be" in c.post("/api/x01/correct-last-dart", json={"dart": 0, "field": "T20"}).json()["error"]


def test_without_a_match_the_routes_say_so(client):
    c, *_ = client
    assert c.post("/api/x01/undo").json() == {"error": "no active or finished match"}
    assert c.post("/api/x01/next").json() == {"error": "no active match"}
    assert c.post("/api/x01/stop").json() == {"ok": True}


def test_stop_ends_the_match_for_the_screens(client):
    c, x01, elim, killer, state, db = client
    c.post("/api/x01/start", json=START)
    assert state.match_started
    c.post("/api/x01/stop")
    assert x01.game is None and not state.match_started
    assert server._build_payload()["x01"] == {"active": False}
