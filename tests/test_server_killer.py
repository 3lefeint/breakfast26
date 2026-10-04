import pytest
from starlette.testclient import TestClient

from breakfast.elimination import EliminationController
from breakfast.killer import KillerController
from breakfast.stats import StatsDB, StatsTracker
from breakfast.target_battle import TargetBattleController
from breakfast.web import server
from tests.test_target_battle import FakeMqttPub, hit, play


@pytest.fixture
def client(tmp_path):
    db = StatsDB(str(tmp_path / "s.db"))
    killer = KillerController(FakeMqttPub(), "autodarts", stats_db=db, on_change=server.push)
    elim = EliminationController(FakeMqttPub(), "autodarts", stats_db=db)
    tb = TargetBattleController(FakeMqttPub(), "autodarts", stats_db=db)
    server.wire(None, elim, stats_tracker=StatsTracker(db), tb_ctrl=tb, killer_ctrl=killer)
    yield TestClient(server.app), killer, elim, tb, db
    server.wire(None, None)


START = {"players": ["ana", "bo"], "bull_off": False, "throw_numbers": False}


def number(killer, name):
    return killer.game.numbers[name]


def test_a_game_can_be_started_and_shows_up_in_the_state(client):
    c, killer, *_ = client
    assert server._build_payload()["killer"] == {"active": False}
    assert c.post("/api/killer/start", json=START).json() == {"ok": True}
    snap = server._build_payload()["killer"]
    assert snap["active"] and snap["order"] == ["ana", "bo"]
    assert [p["lives"] for p in snap["players"]] == [3, 3]
    assert snap["rules"] == {"own_goal": False, "singles": False, "bull_off": False, "throw_numbers": False}


def test_the_options_reach_the_game(client):
    c, killer, *_ = client
    c.post("/api/killer/start", json={**START, "own_goal": True, "singles": True})
    assert killer.game.own_goal is True and killer.game.singles is True
    assert server._build_payload()["killer"]["setup"] == {
        "own_goal": True, "singles": True, "bull_off": False, "throw_numbers": False}


def test_the_bull_off_and_the_thrown_numbers_are_on_by_default(client):
    c, killer, *_ = client
    c.post("/api/killer/start", json={"players": ["ana", "bo"]})
    snap = server._build_payload()["killer"]
    assert snap["phase"] == "bull_off" and snap["current_player"] == "ana"
    assert snap["setup"]["bull_off"] is True and snap["setup"]["throw_numbers"] is True
    assert [p["number"] for p in snap["players"]] == [None, None]


def test_names_are_trimmed_and_empty_ones_dropped(client):
    c, killer, *_ = client
    c.post("/api/killer/start", json={**START, "players": [" ana ", "", "bo", "  "]})
    assert killer.game.order == ["ana", "bo"]


@pytest.mark.parametrize("body, message", [
    ({"players": []}, "at least 2"),
    ({"players": ["ana"]}, "at least 2"),
    ({"players": ["ana", "ana"]}, "only play once"),
])
def test_a_setup_that_cannot_be_played_comes_back_as_an_error(client, body, message):
    c, killer, *_ = client
    res = c.post("/api/killer/start", json=body).json()
    assert message in res["error"] and killer.game is None


def test_only_one_game_runs_at_a_time(client):
    c, killer, elim, tb, _ = client
    elim.start(["ana", "bo"], 3)
    assert "Elimination" in c.post("/api/killer/start", json=START).json()["error"]
    elim.stop()
    tb.start(["ana"], rounds=1)
    assert "Target Battle" in c.post("/api/killer/start", json=START).json()["error"]
    tb.stop()
    c.post("/api/killer/start", json=START)
    assert "Killer" in c.post("/api/elimination/start", json={"players": ["ana", "bo"], "lives": 3}).json()["error"]
    assert "Killer" in c.post("/api/target-battle/start", json={"players": ["ana"], "rounds": 1}).json()["error"]


def test_undo_and_stop(client):
    c, killer, *_ = client
    assert "no active" in c.post("/api/killer/undo").json()["error"]
    c.post("/api/killer/start", json=START)
    assert "nothing to undo" in c.post("/api/killer/undo").json()["error"]
    play(killer.game, hit(number(killer, "ana"), 2))
    assert server._build_payload()["killer"]["players"][0]["killer"] is True
    assert c.post("/api/killer/undo").json() == {"ok": True}
    assert server._build_payload()["killer"]["players"][0]["killer"] is False
    assert c.post("/api/killer/stop").json() == {"ok": True}
    assert killer.game is None and server._build_payload()["killer"] == {"active": False}


def test_a_dart_of_the_turn_can_be_corrected_by_tapping(client):
    c, killer, *_ = client
    c.post("/api/killer/start", json=START)
    n = number(killer, "ana")
    killer.game.on_board_state(1, [hit(n, 1)])
    assert c.post("/api/killer/correct-dart", json={"dart": 1, "field": f"D{n}"}).json() == {"ok": True}
    assert server._build_payload()["killer"]["players"][0]["killer"] is True
    assert "dart must be" in c.post("/api/killer/correct-dart", json={"dart": 4, "field": "T20"}).json()["error"]


def test_the_last_turn_can_be_corrected_when_it_ended_the_game(client):
    c, killer, *_ = client
    c.post("/api/killer/start", json=START)
    a, b = number(killer, "ana"), number(killer, "bo")
    play(killer.game, hit(a, 2))
    play(killer.game, hit(1 if b != 1 else 2, 1))
    play(killer.game, hit(b, 2), hit(b, 2), hit(b, 2))
    assert server._build_payload()["killer"]["state"] == "finished"
    assert c.post("/api/killer/correct-last-dart", json={"dart": 3, "field": f"S{b}"}).json() == {"ok": True}
    snap = server._build_payload()["killer"]
    assert snap["state"] == "playing" and snap["players"][1]["lives"] == 1
    assert "dart must be" in c.post("/api/killer/correct-last-dart", json={"dart": 0, "field": "T20"}).json()["error"]


def test_without_a_controller_there_is_nothing_to_start():
    server.wire(None, None)
    assert TestClient(server.app).post("/api/killer/start", json=START).json() == {"error": "no killer controller"}
    assert server._build_payload()["killer"] is None
