import json
import sqlite3
from datetime import datetime, timedelta, timezone

from breakfast.field_training import FieldTrainingController
from breakfast.resume import ResumeOffers
from breakfast.stats import StatsDB
from tests.test_target_battle import FakeMqttPub


def _match(db, match_id, finished=True, tournament_id=None, started=None):
    db.open_match(match_id, "X01", 501, tournament_id)
    db.insert_turn(match_id, "ana", 1, 1, 501, 60, False, False, [("T20", 60, 441)])
    db.record_leg_win(match_id, 1, "ana")
    if finished:
        db.close_match(match_id)
    if started:
        db._conn.execute("UPDATE matches SET started_at = ? WHERE match_id = ?", (started, match_id))
        db._conn.commit()


def _rows(db, table, match_id):
    return db._conn.execute(f"SELECT COUNT(*) FROM {table} WHERE match_id = ?", (match_id,)).fetchone()[0]


def test_every_table_with_a_match_id_is_deleted_with_the_match(db):
    tables = {r[0] for r in db._conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
    with_match_id = {t for t in tables
                     if "match_id" in [c[1] for c in db._conn.execute(f"PRAGMA table_info({t})")]}
    assert with_match_id - {"matches"} == set(db._DELETE_TABLES)


def test_delete_match_removes_it_with_its_rows_and_achievements(db):
    _match(db, "m1")
    _match(db, "m2")
    db._conn.execute("INSERT INTO achievements_earned (player, achievement_id, tier, earned_at, match_id)"
                     " VALUES ('ana', 'a', 0, 'now', 'm1')")
    db._conn.commit()
    assert db.delete_match("m1") == {"ok": True}
    for table in ("matches", "turns", "legs", "achievements_earned"):
        assert _rows(db, table, "m1") == 0
    assert _rows(db, "matches", "m2") == 1 and _rows(db, "turns", "m2") == 1


def test_delete_match_refuses_unknown_and_tournament_matches(db):
    _match(db, "m1", tournament_id="t1")
    assert "error" in db.delete_match("m1")
    assert "error" in db.delete_match("nope")
    assert _rows(db, "matches", "m1") == 1


def test_discard_unfinished_keeps_a_finished_match(db):
    _match(db, "done")
    _match(db, "open", finished=False)
    assert db.discard_unfinished("done") is False
    assert db.discard_unfinished("open") is True
    assert db.discard_unfinished("open") is False
    assert db.discard_unfinished(None) is False
    assert _rows(db, "matches", "done") == 1 and _rows(db, "matches", "open") == 0
    assert _rows(db, "turns", "open") == 0


def test_stale_unfinished_matches_are_purged_but_not_saved_or_finished_ones(db):
    old = (datetime.now(timezone.utc) - timedelta(days=8)).isoformat()
    recent = (datetime.now(timezone.utc) - timedelta(days=6)).isoformat()
    for match_id, finished in (("old-open", False), ("old-done", True), ("new-open", False), ("old-saved", False)):
        _match(db, match_id, finished=finished)
    for match_id, started in (("old-open", old), ("old-done", old), ("new-open", recent), ("old-saved", old)):
        db._conn.execute("UPDATE matches SET started_at = ? WHERE match_id = ?", (started, match_id))
    db.save_running_match("X01", {"match_id": "old-saved"})
    assert db.purge_stale_matches() == 1
    kept = {r[0] for r in db._conn.execute("SELECT match_id FROM matches")}
    assert kept == {"old-done", "new-open", "old-saved"}


def test_opening_a_match_purges_stale_ones(db):
    old = (datetime.now(timezone.utc) - timedelta(days=9)).isoformat()
    _match(db, "old-open", finished=False)
    db._conn.execute("UPDATE matches SET started_at = ? WHERE match_id = 'old-open'", (old,))
    db.open_match("fresh", "X01", 501)
    assert _rows(db, "matches", "old-open") == 0 and _rows(db, "matches", "fresh") == 1


def test_cancelling_a_game_discards_its_match_but_a_finished_one_stays(db):
    ctrl = FieldTrainingController(FakeMqttPub(), "autodarts", stats_db=db)
    ctrl.start("ana", 20, darts=6)
    match_id = ctrl.game.match_id
    assert _rows(db, "matches", match_id) == 1
    ctrl.stop()
    assert _rows(db, "matches", match_id) == 0
    ctrl.start("ana", 20, darts=6)
    match_id = ctrl.game.match_id
    db.close_match(match_id)
    ctrl.stop()
    assert _rows(db, "matches", match_id) == 1


def test_discarding_a_saved_match_deletes_it(db):
    _match(db, "saved", finished=False)
    db.save_running_match("X01", {"match_id": "saved", "players": ["ana"]})
    controllers = {"X01": type("C", (), {"game": None})()}
    offers = ResumeOffers(db, controllers)
    assert offers.discard("x01") is True
    assert _rows(db, "matches", "saved") == 0


# ── the route ─────────────────────────────────────────────────────────────────

import pytest
from starlette.testclient import TestClient

from breakfast.stats import StatsTracker
from breakfast.web import server


class _Pin:
    def __init__(self, pin):
        self.pin = pin

    def pin_required(self):
        return bool(self.pin)

    def verify_pin(self, pin):
        from breakfast.locations import LocationError
        if self.pin and pin != self.pin:
            raise LocationError("wrong PIN")


@pytest.fixture
def client(tmp_path):
    db = StatsDB(str(tmp_path / "s.db"))
    ft = FieldTrainingController(FakeMqttPub(), "autodarts", stats_db=db)
    server.wire(None, None, stats_tracker=StatsTracker(db), ft_ctrl=ft)
    yield TestClient(server.app), db, ft
    server.wire(None, None)
    server._locations = None


def test_delete_route_removes_the_match(client):
    http, db, _ = client
    _match(db, "m1")
    assert http.delete("/api/stats/match/m1").json() == {"ok": True}
    assert _rows(db, "matches", "m1") == 0
    assert "error" in http.delete("/api/stats/match/m1").json()


def test_delete_route_asks_for_the_pin_when_one_is_set(client):
    http, db, _ = client
    _match(db, "m1")
    assert http.get("/api/delete-guard").json() == {"pin_required": False}
    server._locations = _Pin("1234")
    assert http.get("/api/delete-guard").json() == {"pin_required": True}
    assert http.delete("/api/stats/match/m1").json() == {"error": "wrong PIN"}
    assert http.delete("/api/stats/match/m1", headers={"X-Pin": "0000"}).json() == {"error": "wrong PIN"}
    assert _rows(db, "matches", "m1") == 1
    assert http.delete("/api/stats/match/m1", headers={"X-Pin": "1234"}).json() == {"ok": True}


def test_a_match_in_play_cannot_be_deleted(client):
    http, db, ft = client
    ft.start("ana", 20, darts=6)
    match_id = ft.game.match_id
    assert http.delete(f"/api/stats/match/{match_id}").json() == {"error": "the match is in play"}
    assert _rows(db, "matches", match_id) == 1
