import pytest
from starlette.testclient import TestClient

from breakfast import achievements as ach
from breakfast.achievements import AchievementEngine
from breakfast.stats import StatsDB, StatsTracker
from breakfast.web import server

PILOT = tuple(ach.BY_ID[i] for i in ("bullseye", "ton_up"))


@pytest.fixture
def engine(db):
    return AchievementEngine(db, definitions=PILOT).attach()


def _earn(db, match_id, player, achievement, tier=0, finished=True):
    db.open_match(match_id, "X01", 501)
    db.add_earned(player, achievement, tier, match_id)
    if finished:
        db._conn.execute("UPDATE matches SET ended_at = '2099-01-01T00:00:00+00:00' WHERE match_id = ?", (match_id,))
        db._conn.commit()


def test_a_finished_match_lists_what_was_earned_in_it(db, engine):
    _earn(db, "m1", "ana", "bullseye")
    db.add_earned("ben", "ton_up", 2, "m1")
    db.open_match("m2", "X01", 501)
    db.add_earned("ana", "ton_up", 1, "m2")
    found = engine.match_achievements("m1")
    assert [(a["player"], a["id"], a["tier"]) for a in found] == [("ana", "bullseye", 1), ("ben", "ton_up", 2)]
    first = found[0]
    assert first["names"]["en"] == "Bullseye" and first["descriptions"] and first["motif"] and "earned_at" in first


def test_an_unfinished_or_unknown_match_lists_nothing(db, engine):
    _earn(db, "open", "ana", "bullseye", finished=False)
    assert engine.match_achievements("open") == []
    assert engine.match_achievements("nope") == []


def test_an_achievement_that_no_longer_exists_is_left_out(db, engine):
    _earn(db, "m1", "ana", "bullseye")
    db.add_earned("ana", "gone_for_good", 0, "m1")
    assert [a["id"] for a in engine.match_achievements("m1")] == ["bullseye"]


def test_the_route_answers_with_the_list(db, engine):
    _earn(db, "m1", "ana", "bullseye")
    server.wire(None, None, stats_tracker=StatsTracker(db))
    try:
        http = TestClient(server.app)
        body = http.get("/api/stats/match/m1/achievements").json()
        assert body["match_id"] == "m1" and [a["id"] for a in body["achievements"]] == ["bullseye"]
        assert http.get("/api/stats/match/other/achievements").json()["achievements"] == []
    finally:
        server.wire(None, None)


# ── the result pages need the id of the match ─────────────────────────────────

from breakfast.black_belt import BlackBeltController
from breakfast.checkout_training import CheckoutTrainingController
from breakfast.elimination import EliminationController
from breakfast.field_training import FieldTrainingController
from breakfast.killer import KillerController
from breakfast.target_battle import TargetBattleController
from breakfast.warm_up import WarmUpController
from tests.test_target_battle import FakeMqttPub


@pytest.mark.parametrize("make", [
    lambda pub, db: _started(FieldTrainingController(pub, "autodarts", stats_db=db), "ana", 20, darts=6),
    lambda pub, db: _started(BlackBeltController(pub, "autodarts", stats_db=db), "ana"),
    lambda pub, db: _started(WarmUpController(pub, "autodarts", stats_db=db), "ana", None),
    lambda pub, db: _started(CheckoutTrainingController(pub, "autodarts", stats_db=db), "ana"),
    lambda pub, db: _started(EliminationController(pub, "autodarts", stats_db=db), ["ana", "ben"], 3),
    lambda pub, db: _started(KillerController(pub, "autodarts", stats_db=db), ["ana", "ben"], bull_off=False, throw_numbers=False),
    lambda pub, db: _started(TargetBattleController(pub, "autodarts", stats_db=db), ["ana", "ben"]),
])
def test_the_snapshot_of_every_game_carries_its_match_id(db, make):
    ctrl = make(FakeMqttPub(), db)
    assert ctrl.game.snapshot()["match_id"] == ctrl.game.match_id


def _started(ctrl, *args, **kwargs):
    ctrl.start(*args, **kwargs)
    return ctrl
