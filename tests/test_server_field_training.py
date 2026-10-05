import pytest
from starlette.testclient import TestClient

from breakfast.elimination import EliminationController
from breakfast.field_training import FieldTrainingController
from breakfast.stats import StatsDB, StatsTracker
from breakfast.target_battle import TargetBattleController
from breakfast.web import server
from tests.test_target_battle import FakeMqttPub, hit, play


@pytest.fixture
def client(tmp_path):
    db = StatsDB(str(tmp_path / "s.db"))
    ft = FieldTrainingController(FakeMqttPub(), "autodarts", stats_db=db, on_change=server.push)
    tb = TargetBattleController(FakeMqttPub(), "autodarts", stats_db=db)
    elim = EliminationController(FakeMqttPub(), "autodarts", stats_db=db)
    server.wire(None, elim, stats_tracker=StatsTracker(db), tb_ctrl=tb, ft_ctrl=ft)
    yield TestClient(server.app), ft, tb, elim
    server.wire(None, None)


START = {"player": "ana", "field": 20, "darts": 6}


def test_a_run_can_be_started_and_shows_up_in_the_state(client):
    c, ft, *_ = client
    assert server._build_payload()["field_training"] == {"active": False}
    assert c.post("/api/field-training/start", json=START).json() == {"ok": True}
    snap = server._build_payload()["field_training"]
    assert (snap["active"], snap["field"], snap["darts"], snap["player"]) == (True, 20, 6, "ana")


def test_the_darts_default_to_the_standard_length(client):
    c, ft, *_ = client
    c.post("/api/field-training/start", json={"player": "ana", "field": 25})
    assert ft.game.darts == 50


@pytest.mark.parametrize("body, message", [
    ({"player": "", "field": 20}, "player"),
    ({"player": "ana", "field": 30}, "field"),
    ({"player": "ana", "field": 20, "darts": 0}, "darts"),
])
def test_a_setup_that_cannot_be_played_gets_an_error(client, body, message):
    c, ft, *_ = client
    assert message in c.post("/api/field-training/start", json=body).json()["error"]
    assert ft.game is None


def test_a_running_game_of_another_kind_blocks_a_start_and_the_other_way_round(client):
    c, ft, tb, _ = client
    c.post("/api/target-battle/start", json={"players": ["ana"], "rounds": 1})
    assert "Target Battle" in c.post("/api/field-training/start", json=START).json()["error"]
    c.post("/api/target-battle/stop")
    c.post("/api/field-training/start", json=START)
    assert "Field Training" in c.post("/api/target-battle/start", json={"players": ["ana"]}).json()["error"]
    assert "Field Training" in c.post("/api/elimination/start", json={"players": ["a", "b"]}).json()["error"]


def test_finish_keeps_what_was_thrown_and_drops_an_empty_run(client):
    c, ft, *_ = client
    c.post("/api/field-training/start", json=START)
    assert c.post("/api/field-training/finish").json() == {"ok": True}
    assert ft.game is None
    c.post("/api/field-training/start", json=START)
    play(ft.game, hit(20, 3), hit(20, 1), hit(20, 1))
    c.post("/api/field-training/finish")
    assert ft.game.state == "finished" and ft.game.snapshot()["result"]["points"] == 5


def test_undo_and_stop(client):
    c, ft, *_ = client
    assert "error" in c.post("/api/field-training/undo").json()
    c.post("/api/field-training/start", json=START)
    play(ft.game, hit(20, 3), hit(20, 1), hit(20, 1))
    assert c.post("/api/field-training/undo").json() == {"ok": True}
    assert ft.game.snapshot()["thrown"] == 0
    assert "nothing to undo" in c.post("/api/field-training/undo").json()["error"]
    c.post("/api/field-training/stop")
    assert server._build_payload()["field_training"] == {"active": False}


def test_a_dart_can_be_corrected_by_tapping(client):
    c, ft, *_ = client
    c.post("/api/field-training/start", json=START)
    ft.game.on_board_state(1, [hit(5, 1)])
    assert c.post("/api/field-training/correct-dart", json={"dart": 1, "field": "T20"}).json() == {"ok": True}
    assert ft.game.snapshot()["current_darts"] == [3]
    assert "error" in c.post("/api/field-training/correct-dart", json={"dart": 4, "field": "T20"}).json()


def test_the_statistics_endpoints(client):
    c, ft, *_ = client
    assert c.get("/api/stats/field-training/overview").json() == {"players": []}
    c.post("/api/field-training/start", json={"player": "ana", "field": 20, "darts": 3})
    play(ft.game, hit(20, 3), hit(20, 1), hit(20, 1))
    overview = c.get("/api/stats/field-training/overview").json()
    assert overview["players"][0]["fields"][0]["runs"][0]["points"] == 5
    (match,) = c.get("/api/stats/matches?mode=field_training").json()
    assert match["field"] == 20
    assert c.get(f"/api/stats/match/{match['match_id']}").json()["points"] == 5
