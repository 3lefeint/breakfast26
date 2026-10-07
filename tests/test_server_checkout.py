import pytest
from starlette.testclient import TestClient

from breakfast.black_belt import BlackBeltController
from breakfast.checkout_training import CheckoutTrainingController
from breakfast.elimination import EliminationController
from breakfast.stats import StatsDB, StatsTracker
from breakfast.web import server
from tests.test_checkout_training import th
from tests.test_target_battle import FakeMqttPub


@pytest.fixture
def client(tmp_path):
    db = StatsDB(str(tmp_path / "s.db"))
    co = CheckoutTrainingController(FakeMqttPub(), "autodarts", stats_db=db, on_change=server.push)
    elim = EliminationController(FakeMqttPub(), "autodarts", stats_db=db)
    bb = BlackBeltController(FakeMqttPub(), "autodarts", stats_db=db)
    server.wire(None, elim, stats_tracker=StatsTracker(db), co_ctrl=co, bb_ctrl=bb)
    yield TestClient(server.app), co, elim, bb, db
    server.wire(None, None)


START = {"player": "ana", "range": "mid", "attempts": 3}


class TestTraining:
    def test_a_run_starts_with_a_named_range_and_shows_up_in_the_state(self, client):
        c, co, *_ = client
        assert server._build_payload()["checkout_training"] == {"active": False}
        assert c.post("/api/checkout-training/start", json=START).json() == {"ok": True}
        snap = server._build_payload()["checkout_training"]
        assert snap["active"] and (snap["low"], snap["high"], snap["attempts"]) == (41, 100, 3)
        assert 41 <= snap["score"] <= 100

    def test_a_free_range_and_the_route_setting_reach_the_game(self, client):
        c, co, *_ = client
        c.post("/api/checkout-training/start", json={"player": "ana", "low": 10, "high": 20, "attempts": 2, "show_route": True})
        assert (co.game.low, co.game.high, co.game.show_route) == (10, 20, True)

    def test_bad_setups_are_refused_with_a_reason(self, client):
        c, *_ = client
        assert "range" in c.post("/api/checkout-training/start", json={**START, "range": "huge"}).json()["error"]
        assert "error" in c.post("/api/checkout-training/start", json={"player": "", "attempts": 3}).json()
        assert "error" in c.post("/api/checkout-training/start", json={**START, "attempts": 0}).json()

    def test_it_does_not_start_beside_another_game_and_the_other_way_round(self, client):
        c, co, elim, bb, _ = client
        c.post("/api/elimination/start", json={"players": ["a", "b"], "lives": 3})
        assert "Elimination" in c.post("/api/checkout-training/start", json=START).json()["error"]
        elim.stop()
        assert c.post("/api/checkout-training/start", json=START).json() == {"ok": True}
        assert "Checkout" in c.post("/api/elimination/start", json={"players": ["a", "b"], "lives": 3}).json()["error"]
        assert "Checkout" in c.post("/api/black-belt/start", json={"player": "ana"}).json()["error"]

    def test_darts_play_an_attempt_and_stop_clears_the_run(self, client):
        c, co, *_ = client
        c.post("/api/checkout-training/start", json=START)
        co.game.score = 40
        co.on_board_state(1, [th("D20")])
        co.on_board_state(0, [])
        assert server._build_payload()["checkout_training"]["successes"] == 1
        assert c.post("/api/checkout-training/undo").json() == {"ok": True}
        assert server._build_payload()["checkout_training"]["successes"] == 0
        assert c.post("/api/checkout-training/stop").json() == {"ok": True}
        assert server._build_payload()["checkout_training"] == {"active": False}

    def test_correct_dart_and_finish(self, client):
        c, co, *_ = client
        c.post("/api/checkout-training/start", json=START)
        co.game.score = 40
        co.on_board_state(1, [th("S20")])
        assert c.post("/api/checkout-training/correct-dart", json={"dart": 1, "field": "D20"}).json() == {"ok": True}
        co.on_board_state(0, [])
        assert co.game.results[0]["success"] is True
        assert c.post("/api/checkout-training/correct-dart", json={"dart": 4, "field": "D20"}).json()["error"]
        assert c.post("/api/checkout-training/finish").json() == {"ok": True}
        assert server._build_payload()["checkout_training"]["state"] == "finished"


class TestTheTrainerWithoutDarts:
    def test_a_random_score_is_finishable_and_inside_the_range(self, client):
        c, *_ = client
        for _ in range(30):
            score = c.get("/api/checkout/random", params={"low": 100, "high": 170}).json()["score"]
            assert 100 <= score <= 170 and score not in (162, 163, 165, 166, 168, 169)
        assert c.get("/api/checkout/random", params={"low": 169, "high": 169}).json()["error"]

    def test_the_route_of_a_score(self, client):
        c, *_ = client
        r = c.get("/api/checkout/route", params={"score": 170}).json()
        assert r["finishable"] and r["route"] == ["T20", "T20", "50"] and r["darts"] == 3 and r["first_darts"] == ["T20"]
        bogey = c.get("/api/checkout/route", params={"score": 169}).json()
        assert bogey["finishable"] is False and bogey["route"] is None and bogey["darts"] is None

    def test_judging_a_first_dart(self, client):
        c, *_ = client
        assert c.post("/api/checkout/judge", json={"score": 81, "field": "T19"}).json()["verdict"] == "standard"
        assert c.post("/api/checkout/judge", json={"score": 81, "field": "T15"}).json()["verdict"] == "valid"
        assert c.post("/api/checkout/judge", json={"score": 170, "field": "S1"}).json()["verdict"] == "invalid"
        assert "error" in c.post("/api/checkout/judge", json={"score": 169, "field": "T20"}).json()
        assert c.post("/api/checkout/judge", json={"score": 81, "field": "X9"}).status_code == 422

    def test_what_a_rest_allows_after_the_setup_darts(self, client):
        c, *_ = client
        r = c.post("/api/checkout/setup", json={"score": 81, "fields": ["T19"]}).json()
        assert r["rest"] == 24 and r["state"] == "open" and r["darts_to_finish"] == 1 and r["route"] == ["D12"]
        r = c.post("/api/checkout/setup", json={"score": 81, "fields": ["S1"]}).json()
        assert r["rest"] == 80 and r["darts_to_finish"] == 2
        r = c.post("/api/checkout/setup", json={"score": 81, "fields": ["T20", "T20"]}).json()
        assert r["state"] == "bust"
        r = c.post("/api/checkout/setup", json={"score": 170, "fields": ["T20", "T20", "S1"]}).json()
        assert r["darts_to_finish"] is None and r["darts_left"] == 0


class TestStats:
    def test_the_overview_and_the_match_list_know_the_mode(self, client):
        c, co, _, _, db = client
        c.post("/api/checkout-training/start", json={**START, "attempts": 1})
        co.game.score = 40
        co.on_board_state(1, [th("D20")])
        co.on_board_state(0, [])
        overview = c.get("/api/stats/checkout-training/overview").json()
        assert overview["players"][0]["attempts"] == 1 and overview["players"][0]["successes"] == 1
        assert [m["game_mode"] for m in c.get("/api/stats/matches", params={"mode": "checkout_training"}).json()] == ["Checkout Training"]
        assert c.get("/api/stats/matches", params={"mode": "x01"}).json() == []
