import pytest
from starlette.testclient import TestClient

from breakfast.elimination import EliminationController
from breakfast.stats import StatsDB, StatsTracker
from breakfast.web import server
from tests.test_elimination import _throw
from tests.test_target_battle import FakeMqttPub


@pytest.fixture
def client(tmp_path):
    db = StatsDB(str(tmp_path / "s.db"))
    elim = EliminationController(FakeMqttPub(), "autodarts", stats_db=db, on_change=server.push)
    server.wire(None, elim, stats_tracker=StatsTracker(db))
    yield TestClient(server.app), elim
    server.wire(None, None)


def test_elimination_correct_last_dart_resumes_a_match_that_ended_at_the_third_dart(client):
    c, elim = client
    assert c.post("/api/elimination/start", json={"players": ["ben", "anna"], "lives": 1}).json() == {"ok": True}
    elim.on_board_state(1, [_throw(13, 3)])
    elim.on_board_state(0, [])
    elim.on_board_state(3, [_throw(10, 1), _throw(12, 1), _throw(1, 1)])
    assert server._build_payload()["elimination"]["state"] == "finished"

    assert c.post("/api/elimination/correct-last-dart", json={"dart": 3, "field": "S20"}).json() == {"ok": True}

    snap = server._build_payload()["elimination"]
    assert snap["state"] == "playing" and snap["target"] == 42 and snap["current_player"] == "ben"


def test_elimination_correct_last_dart_refuses_what_it_cannot_do(client):
    c, elim = client
    assert "error" in c.post("/api/elimination/correct-last-dart", json={"dart": 1, "field": "S20"}).json()
    c.post("/api/elimination/start", json={"players": ["ben", "anna"], "lives": 3})
    assert c.post("/api/elimination/correct-last-dart", json={"dart": 1, "field": "S20"}).json() == {"error": "no turn to correct"}
    assert c.post("/api/elimination/correct-last-dart", json={"dart": 4, "field": "S20"}).json() == {"error": "dart must be 1, 2, or 3"}
