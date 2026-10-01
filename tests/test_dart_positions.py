from unittest.mock import MagicMock

from breakfast.autodarts_client import AutodartsCloudClient
from breakfast.dartboard import field_centers
from breakfast.elimination import EliminationGame
from breakfast.mqtt_output import NullMqttPublisher
from breakfast.stats import StatsDB, StatsTracker

CENTERS = field_centers()


def _positions(db, **where):
    sql = "SELECT * FROM dart_positions" + "".join(f" WHERE {k} = ?" if i == 0 else f" AND {k} = ?"
                                                 for i, k in enumerate(where)) + " ORDER BY id"
    return [dict(r) for r in db._conn.execute(sql, tuple(where.values())).fetchall()]


def _pos(x, y, entry="detected"):
    return {"x": x, "y": y, "entry": entry}


class TestStoredPositions:
    def _db(self):
        db = StatsDB(":memory:")
        db.open_match("m1", "X01", 501)
        return db

    def test_a_turn_stores_the_position_of_every_dart(self):
        db = self._db()
        db.insert_turn("m1", "alice", 1, 1, 501, 100, False, False,
                       [("T20", 60, 441), ("S20", 20, 421), ("S20", 20, 401)],
                       positions=[_pos(0.01, 0.6), _pos(0.02, 0.8), None])
        rows = _positions(db)
        assert [(r["dart_number"], r["field"], r["x"], r["y"], r["corrected"]) for r in rows] == [
            (1, "T20", 0.01, 0.6, 0), (2, "S20", 0.02, 0.8, 0)]
        assert rows[0]["match_id"] == "m1" and rows[0]["game_mode"] == "X01" and rows[0]["turn"] == 1

    def test_a_dart_on_the_center_of_its_field_counts_as_corrected(self):
        db = self._db()
        c = CENTERS["T20"]
        db.insert_turn("m1", "alice", 1, 1, 501, 60, False, False, [("T20", 60, 441)],
                       positions=[_pos(c["x"], c["y"])])
        assert _positions(db)[0]["corrected"] == 1

    def test_a_dart_autodarts_did_not_detect_counts_as_corrected(self):
        db = self._db()
        db.insert_turn("m1", "alice", 1, 1, 501, 20, False, False, [("S20", 20, 481)],
                       positions=[_pos(0.01, 0.8, entry="manual")])
        assert _positions(db)[0]["corrected"] == 1

    def test_a_turn_without_positions_stores_none(self):
        db = self._db()
        db.insert_turn("m1", "alice", 1, 1, 501, 20, False, False, [("S20", 20, 481)])
        assert _positions(db) == []

    def test_an_older_database_gets_the_table(self, tmp_path):
        path = str(tmp_path / "old.db")
        db = StatsDB(path)
        db._conn.execute("DROP TABLE dart_positions")
        db._conn.commit()
        db._conn.close()
        reopened = StatsDB(path)
        assert reopened._conn.execute("SELECT COUNT(*) FROM dart_positions").fetchone()[0] == 0


class TestPlayerDartPositions:
    def _filled(self):
        db = StatsDB(":memory:")
        db.open_match("x", "X01", 501)
        db.open_match("e", "Elimination", 3)
        db.insert_turn("x", "alice", 1, 1, 501, 40, False, False, [("S20", 20, 481), ("S20", 20, 461)],
                       positions=[_pos(0.01, 0.8), _pos(CENTERS["S20"]["x"], CENTERS["S20"]["y"])])
        db.insert_elimination_turn("e", "alice", 1, score=5, positions=[{"field": "S5", "x": -0.2, "y": 0.7}])
        return db

    def test_x01_and_elimination_are_listed_apart(self):
        db = self._filled()
        assert [d["field"] for d in db.player_dart_positions("alice", "x01")["darts"]] == ["S20"]
        assert [d["field"] for d in db.player_dart_positions("alice", "elimination")["darts"]] == ["S5"]

    def test_corrected_darts_are_left_out_but_counted(self):
        res = self._filled().player_dart_positions("alice", "x01")
        assert len(res["darts"]) == 1 and res["corrected"] == 1 and res["total"] == 2

    def test_newest_darts_first_and_limited(self):
        db = StatsDB(":memory:")
        db.open_match("m", "X01", 501)
        for i in range(5):
            db.insert_turn("m", "alice", 1, i + 1, 501, 20, False, False, [("S20", 20, 481)],
                           positions=[_pos(0.01 * (i + 1), 0.8)])
        res = db.player_dart_positions("alice", "x01", limit=2)
        assert [d["x"] for d in res["darts"]] == [0.05, 0.04] and res["total"] == 5

    def test_unknown_player_has_none(self):
        assert StatsDB(":memory:").player_dart_positions("nobody") == {"darts": [], "corrected": 0, "total": 0}


def _event(name, player="alice", **game):
    return {"event": name, "player": player, "game": game}


class TestTrackerPositions:
    def _tracker(self):
        db = StatsDB(":memory:")
        return db, StatsTracker(db)

    def test_darts_with_coords_are_stored_with_the_turn(self):
        db, tracker = self._tracker()
        tracker.process({"event": "match-started", "id": "m1", "game": {"mode": "X01", "pointsStart": "501"}})
        tracker.process(_event("dart1-thrown", dartValue="60", pointsLeft="441", fieldName="t20",
                               coords={"x": 0.01, "y": 0.6}, entry="detected"))
        tracker.process(_event("dart2-thrown", dartValue="20", pointsLeft="421", fieldName="s20",
                               coords={"x": 0.02, "y": 0.8}, entry="detected"))
        tracker.process(_event("darts-pulled"))
        assert [(r["dart_number"], r["field"], r["x"]) for r in _positions(db)] == [(1, "T20", 0.01), (2, "S20", 0.02)]

    def test_the_dart_that_busts_is_stored_with_its_position(self):
        db, tracker = self._tracker()
        tracker.process({"event": "match-started", "id": "m1", "game": {"mode": "X01", "pointsStart": "40"}})
        tracker.process(_event("busted", dartNumber="1", dartValue="60", field_name="t20",
                               pointsBeforeTurn="40", coords={"x": 0.0, "y": 0.61}, entry="detected"))
        tracker.process(_event("darts-pulled"))
        assert [(r["dart_number"], r["field"], r["y"]) for r in _positions(db)] == [(1, "T20", 0.61)]

    def test_events_without_coords_store_no_positions(self):
        db, tracker = self._tracker()
        tracker.process({"event": "match-started", "id": "m1", "game": {"mode": "X01", "pointsStart": "501"}})
        tracker.process(_event("dart1-thrown", dartValue="60", pointsLeft="441", fieldName="t20"))
        tracker.process(_event("darts-pulled"))
        assert _positions(db) == []
        assert db._conn.execute("SELECT COUNT(*) FROM turns").fetchone()[0] == 1

    def test_a_corrected_turn_is_re_emitted_and_replaces_the_earlier_darts(self):
        db, tracker = self._tracker()
        tracker.process({"event": "match-started", "id": "m1", "game": {"mode": "X01", "pointsStart": "501"}})
        tracker.process(_event("dart1-thrown", dartValue="20", pointsLeft="481", fieldName="s20",
                               coords={"x": 0.0, "y": 0.8}, entry="detected"))
        # the correction re-emits the turn from dart 1
        tracker.process(_event("dart1-thrown", dartValue="60", pointsLeft="441", fieldName="t20",
                               coords={"x": 0.0, "y": CENTERS["T20"]["y"]}, entry="manual"))
        tracker.process(_event("darts-pulled"))
        (row,) = _positions(db)
        assert row["field"] == "T20" and row["corrected"] == 1


class TestClientEmitsPositions:
    def _run(self, monkeypatch, states):
        import base64, json
        payload = base64.urlsafe_b64encode(json.dumps({"sub": "u"}).encode()).rstrip(b"=").decode()
        login = MagicMock(raise_for_status=lambda: None,
                          json=lambda: {"access_token": f"h.{payload}.s", "refresh_token": "r", "expires_in": 900})
        monkeypatch.setattr("breakfast.autodarts_client.requests.post", lambda *a, **kw: login)
        monkeypatch.setattr("breakfast.autodarts_client.requests.get", lambda *a, **kw: MagicMock(json=lambda: {}))
        events = []
        client = AutodartsCloudClient(email="e", password="p", board_id="b", on_event=events.append)
        for state in states:
            client._process_x01(state)
        return events

    @staticmethod
    def _state(throws, remaining, busted=False):
        return {"variant": "X01", "players": [{"name": "Alice"}], "player": 0, "gameScores": [remaining],
                "turns": [{"throws": throws, "points": sum(t["segment"]["number"] * t["segment"]["multiplier"] for t in throws),
                           "busted": busted}],
                "settings": {"baseScore": 501}, "winner": -1, "gameWinner": -1}

    @staticmethod
    def _throw(name, number, multiplier, x, y, entry="detected"):
        return {"segment": {"name": name, "number": number, "multiplier": multiplier, "bed": "x"},
                "coords": {"x": x, "y": y}, "entry": entry}

    def test_a_dart_event_carries_the_position(self, monkeypatch):
        events = self._run(monkeypatch, [self._state([self._throw("T20", 20, 3, 0.01, 0.6)], 441)])
        game = events[0]["game"]
        assert game["coords"] == {"x": 0.01, "y": 0.6} and game["entry"] == "detected"

    def test_the_busted_event_carries_the_position_of_the_busting_dart(self, monkeypatch):
        events = self._run(monkeypatch, [self._state([self._throw("T20", 20, 3, 0.0, 0.61)], 40, busted=True)])
        game = events[0]["game"]
        assert game["dartNumber"] == "1" and game["coords"] == {"x": 0.0, "y": 0.61}

    def test_a_throw_without_coords_adds_nothing(self, monkeypatch):
        throw = {"segment": {"name": "T20", "number": 20, "multiplier": 3, "bed": "x"}}
        events = self._run(monkeypatch, [self._state([throw], 441)])
        assert "coords" not in events[0]["game"]


def _t(number, multiplier, x, y, name=None):
    seg = {"number": number, "multiplier": multiplier}
    if name:
        seg["name"] = name
    return {"segment": seg, "coords": {"x": x, "y": y}}


class TestEliminationPositions:
    def _game(self, lives=3):
        db = StatsDB(":memory:")
        return db, EliminationGame(["alice", "bob"], lives, NullMqttPublisher().client, "autodarts", stats_db=db)

    def test_the_positions_of_a_turn_are_stored_with_it(self):
        db, game = self._game()
        throws = [_t(20, 3, 0.0, 0.6, "T20"), _t(5, 1, -0.2, 0.7, "S5"), {"segment": {"number": 1, "multiplier": 1}}]
        game.on_board_state(3, throws)
        game.on_board_state(0, [])
        rows = _positions(db, game_mode="Elimination")
        assert [(r["player"], r["dart_number"], r["field"], r["turn"]) for r in rows] == [
            ("alice", 1, "T20", 1), ("alice", 2, "S5", 1)]

    def test_the_match_ending_turn_is_stored_too(self):
        db, game = self._game(lives=1)
        game.on_board_state(3, [_t(20, 3, 0.0, 0.6, "T20")] * 3)
        game.on_board_state(0, [])
        game.on_board_state(3, [_t(1, 1, 0.1, 0.7, "S1")] * 3)
        assert game.state == "finished"
        assert {r["player"] for r in _positions(db, game_mode="Elimination")} == {"alice", "bob"}

    def test_undo_removes_the_positions_of_the_turn(self):
        db, game = self._game()
        game.on_board_state(3, [_t(20, 3, 0.0, 0.6, "T20")] * 3)
        game.on_board_state(0, [])
        assert len(_positions(db)) == 3
        assert game.undo() is True
        assert _positions(db) == []

    def test_correcting_the_total_marks_the_darts_as_corrected(self):
        db, game = self._game()
        game.on_board_state(3, [_t(20, 3, 0.0, 0.6, "T20")] * 3)
        game.on_board_state(0, [])
        game.correct_turn(100)
        assert {r["corrected"] for r in _positions(db)} == {1}
