import pytest
from starlette.testclient import TestClient

from breakfast.elimination import EliminationController
from breakfast.stats import StatsDB, StatsTracker
from breakfast.target_battle import TargetBattleController
from breakfast.web import server
from tests.test_target_battle import FakeMqttPub, hit, play


@pytest.fixture
def client(tmp_path):
    db = StatsDB(str(tmp_path / "s.db"))
    tb = TargetBattleController(FakeMqttPub(), "autodarts", stats_db=db, on_change=server.push)
    elim = EliminationController(FakeMqttPub(), "autodarts", stats_db=db)
    server.wire(None, elim, stats_tracker=StatsTracker(db), tb_ctrl=tb)
    yield TestClient(server.app), tb, elim, db
    server.wire(None, None)


START = {"players": ["ana", "bo"], "rounds": 2, "targets": [20, 5]}


def test_a_game_can_be_started_and_shows_up_in_the_state(client):
    c, tb, _, _ = client
    assert server._build_payload()["target_battle"] == {"active": False}
    assert c.post("/api/target-battle/start", json=START).json() == {"ok": True}
    snap = server._build_payload()["target_battle"]
    assert (snap["active"], snap["round"], snap["rounds"], snap["target"]) == (True, 1, 2, 20)
    assert snap["order"] == ["ana", "bo"] and snap["scoring"] == "standard"


def test_the_setup_options_reach_the_game(client):
    c, tb, _, _ = client
    c.post("/api/target-battle/start", json={**START, "scoring": "doubles", "tiebreak": True})
    assert tb.game.scoring == "doubles" and tb.game.tiebreak_enabled is True
    assert tb.game.fixed_targets == [20, 5]


def test_names_are_trimmed_and_empty_ones_dropped(client):
    c, tb, _, _ = client
    c.post("/api/target-battle/start", json={"players": [" ana ", "", "  "], "rounds": 1})
    assert tb.game.order == ["ana"]


@pytest.mark.parametrize("body, message", [
    ({"players": []}, "at least one player"),
    ({"players": ["ana"], "rounds": 0}, "rounds"),
    ({"players": ["ana"], "scoring": "bulls"}, "scoring"),
    ({"players": ["ana"], "rounds": 2, "targets": [20]}, "targets"),
])
def test_a_setup_that_cannot_be_played_comes_back_as_an_error(client, body, message):
    c, tb, _, _ = client
    res = c.post("/api/target-battle/start", json=body).json()
    assert message in res["error"] and tb.game is None


def test_it_cannot_start_while_an_elimination_game_runs_and_the_other_way_round(client):
    c, tb, elim, _ = client
    elim.start(["ana", "bo"], 3)
    assert "Elimination" in c.post("/api/target-battle/start", json=START).json()["error"]
    elim.stop()
    c.post("/api/target-battle/start", json=START)
    assert "Target Battle" in c.post("/api/elimination/start", json={"players": ["ana", "bo"], "lives": 3}).json()["error"]


def test_undo_correct_and_stop(client):
    c, tb, _, _ = client
    assert "no active" in c.post("/api/target-battle/undo").json()["error"]
    c.post("/api/target-battle/start", json=START)
    assert "nothing to undo" in c.post("/api/target-battle/undo").json()["error"]
    play(tb.game, hit(20, 3))
    assert c.post("/api/target-battle/correct", json={"total": 1}).json() == {"ok": True}
    assert server._build_payload()["target_battle"]["players"][0]["score"] == 1
    assert c.post("/api/target-battle/undo").json() == {"ok": True}
    assert server._build_payload()["target_battle"]["current_player"] == "ana"
    assert c.post("/api/target-battle/stop").json() == {"ok": True}
    assert tb.game is None and server._build_payload()["target_battle"] == {"active": False}


def test_a_dart_can_be_corrected_by_tapping(client):
    c, tb, _, _ = client
    c.post("/api/target-battle/start", json=START)
    tb.game.on_board_state(1, [hit(19, 1)])
    assert c.post("/api/target-battle/correct-dart", json={"dart": 1, "field": "T20"}).json() == {"ok": True}
    assert tb.game.snapshot()["current_darts"] == [3]
    assert "dart must be" in c.post("/api/target-battle/correct-dart", json={"dart": 4, "field": "T20"}).json()["error"]


def test_without_a_controller_there_is_nothing_to_start():
    server.wire(None, None)
    assert TestClient(server.app).post("/api/target-battle/start", json=START).json() == {
        "error": "no target battle controller"}
    assert server._build_payload()["target_battle"] is None
