from breakfast import known_players as kp


class TestLoadAdd:
    def test_load_empty_db_returns_empty(self, db):
        assert kp.load(db) == []

    def test_load_none_db_returns_empty(self):
        assert kp.load(None) == []

    def test_add_persists_and_dedupes(self, db):
        kp.add("alice", db)
        kp.add("alice", db)
        assert kp.load(db) == ["alice"]

    def test_hiding_removes_from_load(self, db):
        """There's no separate roster any more — hiding (StatsDB.upsert_player)
        is the only way to keep a known player out of load()'s list."""
        kp.add("alice", db)
        kp.add("bob", db)
        db.upsert_player("alice", hidden=True)
        assert kp.load(db) == ["bob"]

    def test_hiding_does_not_delete_history(self, db):
        kp.add("alice", db)
        db.upsert_player("alice", hidden=True)
        rows = db._conn.execute("SELECT name FROM players WHERE name = 'alice'").fetchall()
        assert len(rows) == 1


class TestWins:
    def test_load_wins_empty_db_returns_empty(self, db):
        assert kp.load_wins(db) == {}

    def test_load_wins_none_db_returns_empty(self):
        assert kp.load_wins(None) == {}

    def test_wins_derived_from_elimination_results(self, db):
        db.record_elimination_result("m1", [("alice", 1, 3), ("bob", 2, None)])
        db.record_elimination_result("m2", [("alice", 1, 1), ("carol", 2, None)])
        assert kp.load_wins(db) == {"alice": 2}
