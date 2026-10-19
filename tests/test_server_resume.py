import pytest
from starlette.testclient import TestClient

from breakfast.elimination import EliminationController
from breakfast.killer import KillerController
from breakfast.resume import ResumeOffers
from breakfast.stats import StatsDB, StatsTracker
from breakfast.target_battle import TargetBattleController
from breakfast.web import server
from breakfast.x01_game import X01Controller
from tests.test_target_battle import FakeMqttPub


def build(path):
    db = StatsDB(str(path))
    killer = KillerController(FakeMqttPub(), "autodarts", stats_db=db, on_change=server.push)
    elim = EliminationController(FakeMqttPub(), "autodarts", stats_db=db, on_change=server.push)
    tb = TargetBattleController(FakeMqttPub(), "autodarts", stats_db=db)
    x01 = X01Controller(lambda event: None, stats_db=db, on_change=server.push)
    offers = ResumeOffers(db, {"X01": x01, "Elimination": elim, "Killer": killer})
    server.wire(None, elim, stats_tracker=StatsTracker(db), tb_ctrl=tb, killer_ctrl=killer, x01_ctrl=x01,
                resume_offers=offers)
    return TestClient(server.app), x01, elim, killer, tb


@pytest.fixture
def site(tmp_path):
    yield lambda: build(tmp_path / "s.db")
    server.wire(None, None)


def test_a_match_in_play_is_reported_and_offered_after_a_restart(site):
    c, x01, *_ = site()
    assert server._build_payload()["running_game"] is None
    c.post("/api/x01/start", json={"players": ["ana", "bo"], "bull_off": False})
    assert server._build_payload()["running_game"] == {"mode": "X01", "resumable": True}
    c, x01, *_ = site()
    payload = server._build_payload()
    assert payload["running_game"] is None
    assert [(o["key"], o["players"]) for o in payload["resume"]] == [("x01", ["ana", "bo"])]


def test_it_can_be_resumed_through_the_route(site):
    c, *_ = site()
    c.post("/api/killer/start", json={"players": ["ana", "bo"], "bull_off": False, "throw_numbers": False})
    c, x01, elim, killer, tb = site()
    assert c.post("/api/resume/killer").json() == {"ok": True}
    assert killer.game is not None and server._build_payload()["resume"] == []
    assert c.post("/api/resume/killer").json() == {"error": "no such match to resume"}


def test_it_can_be_discarded_through_the_route(site):
    c, *_ = site()
    c.post("/api/elimination/start", json={"players": ["ana", "bo"], "lives": 3})
    c, x01, elim, *_ = site()
    assert c.post("/api/resume/elimination/discard").json() == {"ok": True}
    assert server._build_payload()["resume"] == [] and elim.game is None
    assert c.post("/api/resume/elimination/discard").json() == {"error": "nothing to discard"}


def test_a_game_that_a_restart_would_lose_is_reported_as_such(site):
    c, x01, elim, killer, tb = site()
    c.post("/api/target-battle/start", json={"players": ["ana", "bo"]})
    assert server._build_payload()["running_game"] == {"mode": "Target Battle", "resumable": False}
