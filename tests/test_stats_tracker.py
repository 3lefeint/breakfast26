from breakfast.stats import StatsDB, StatsTracker


# ── event builders ────────────────────────────────────────────────────────────

def ev_match_started(match_id="m1", mode="X01", pts=501, player="alice"):
    return {"event": "match-started", "id": match_id, "player": player,
            "game": {"mode": mode, "pointsStart": str(pts)}}


def ev_dart(n, value, points_left, field="T20", player="alice"):
    """dart{n}-thrown: value = points scored, points_left = remaining after throw."""
    return {"event": f"dart{n}-thrown", "player": player,
            "game": {"dartValue": str(value), "pointsLeft": str(points_left),
                     "fieldName": field}}


def ev_darts_pulled(player="alice"):
    return {"event": "darts-pulled", "player": player, "game": {}}


def ev_busted(player="alice"):
    return {"event": "busted", "player": player, "game": {}}


def ev_game_won(player="alice"):
    return {"event": "game-won", "player": player, "game": {}}


def ev_match_won(player="alice"):
    return {"event": "match-won", "player": player, "game": {}}


# ── helpers ───────────────────────────────────────────────────────────────────

def _db_turns(db, match_id="m1"):
    with db._lock:
        return db._conn.execute(
            "SELECT * FROM turns WHERE match_id=? ORDER BY id", (match_id,)
        ).fetchall()


# ── tests ─────────────────────────────────────────────────────────────────────

class TestStatsTracker:
    def test_full_turn_written_to_db(self, tracker, db):
        tracker.process(ev_match_started())
        tracker.process(ev_dart(1, 60, 441))        # remaining_before = 501
        tracker.process(ev_dart(2, 60, 381))
        tracker.process(ev_dart(3, 57, 324))
        tracker.process(ev_darts_pulled())
        rows = _db_turns(db)
        assert len(rows) == 1
        assert rows[0]["score"] == 177
        assert rows[0]["darts_count"] == 3
        assert rows[0]["remaining_before"] == 501

    def test_single_dart_turn(self, tracker, db):
        tracker.process(ev_match_started())
        tracker.process(ev_dart(1, 60, 441))
        tracker.process(ev_darts_pulled())
        rows = _db_turns(db)
        assert len(rows) == 1
        assert rows[0]["darts_count"] == 1
        assert rows[0]["score"] == 60

    def test_checkout_detected(self, tracker, db):
        # remaining_before == total → is_checkout
        tracker.process(ev_match_started(pts=32))
        tracker.process(ev_dart(1, 32, 0, field="D16"))   # remaining_before = 32
        tracker.process(ev_darts_pulled())
        rows = _db_turns(db)
        assert rows[0]["is_checkout"] == 1
        assert rows[0]["is_bust"] == 0

    def test_checkout_flushed_without_darts_pulled(self, tracker, db):
        # Regression test: the darts-pulled that would normally trigger
        # _flush_turn() only fires on the board's *next* poll after
        # game-won/match-won — racing against a following match-started
        # (e.g. an immediate rematch), which wipes self._buf unconditionally
        # if it wins that race. Flushing at game-won/match-won itself
        # removes the dependency on that later, racy event.
        tracker.process(ev_match_started(pts=32))
        tracker.process(ev_dart(1, 32, 0, field="D16"))   # checkout dart
        tracker.process(ev_match_won())                  # no darts-pulled first
        rows = _db_turns(db)
        assert len(rows) == 1
        assert rows[0]["is_checkout"] == 1
        assert rows[0]["score"] == 32

    def test_game_won_flushes_without_darts_pulled(self, tracker, db):
        tracker.process(ev_match_started(pts=32))
        tracker.process(ev_dart(1, 32, 0, field="D16"))
        tracker.process(ev_game_won())                    # no darts-pulled first
        rows = _db_turns(db)
        assert len(rows) == 1
        assert rows[0]["is_checkout"] == 1

    def test_bust_turn(self, tracker, db):
        tracker.process(ev_match_started())
        tracker.process(ev_dart(1, 20, 481))
        tracker.process(ev_busted())
        tracker.process(ev_darts_pulled())
        rows = _db_turns(db)
        assert rows[0]["is_bust"] == 1
        assert rows[0]["score"] == 0

    def test_game_won_increments_leg(self, tracker, db):
        tracker.process(ev_match_started())
        # leg 1
        tracker.process(ev_dart(1, 60, 441))
        tracker.process(ev_darts_pulled())
        # advance to leg 2
        tracker.process(ev_game_won())
        # leg 2
        tracker.process(ev_dart(1, 60, 441))
        tracker.process(ev_darts_pulled())
        rows = _db_turns(db)
        assert rows[0]["leg"] == 1
        assert rows[1]["leg"] == 2

    def test_match_lifecycle_opens_and_closes(self, tracker, db):
        tracker.process(ev_match_started(match_id="life-test"))
        tracker.process(ev_dart(1, 60, 441))
        tracker.process(ev_darts_pulled())
        tracker.process(ev_match_won())
        matches = db.recent_matches()
        ids = [m["match_id"] for m in matches]
        assert "life-test" in ids

    def test_co_pct_nonzero_after_checkout(self, tracker, db):
        tracker.process(ev_match_started(pts=32))
        tracker.process(ev_dart(1, 32, 0, field="D16"))
        tracker.process(ev_darts_pulled())
        tracker.process(ev_match_won())
        stats = db.session_stats("m1")
        assert stats["alice"]["co_pct"] == 100.0

    def test_multiple_players_in_match(self, tracker, db):
        tracker.process(ev_match_started())
        tracker.process(ev_dart(1, 60, 441, player="alice"))
        tracker.process(ev_darts_pulled(player="alice"))
        tracker.process(ev_dart(1, 60, 441, player="bob"))
        tracker.process(ev_darts_pulled(player="bob"))
        tracker.process(ev_match_won())
        stats = db.session_stats("m1")
        assert "alice" in stats
        assert "bob" in stats

    def test_no_tracking_outside_x01(self, tracker, db):
        # Cricket turns should not be recorded (no dart1/2/3-thrown events)
        tracker.process(ev_match_started(mode="Cricket"))
        # Simulate a Cricket "darts-thrown" (not dart1-thrown) — not buffered
        tracker.process({"event": "darts-pulled", "player": "alice", "game": {}})
        rows = _db_turns(db)
        assert rows == []

    def test_second_match_resets_leg_counter(self, tracker, db):
        tracker.process(ev_match_started(match_id="m1"))
        tracker.process(ev_dart(1, 60, 441))
        tracker.process(ev_darts_pulled())
        tracker.process(ev_game_won())     # _leg becomes 2
        tracker.process(ev_match_won())

        tracker.process(ev_match_started(match_id="m2"))
        tracker.process(ev_dart(1, 60, 441))
        tracker.process(ev_darts_pulled())
        rows = _db_turns(db, "m2")
        assert rows[0]["leg"] == 1

    def test_game_won_records_leg_in_db(self, tracker, db):
        tracker.process(ev_match_started())
        tracker.process(ev_dart(1, 60, 441))
        tracker.process(ev_darts_pulled())
        tracker.process({"event": "game-won", "player": "alice", "game": {"winner": "alice"}})
        tracker.process(ev_match_won())
        won = db.legs_won_by_player("m1")
        assert won.get("alice", 0) >= 1

    def test_match_won_records_final_leg(self, tracker, db):
        tracker.process(ev_match_started())
        tracker.process(ev_dart(1, 32, 0, field="D16"))
        tracker.process(ev_darts_pulled())
        tracker.process({"event": "match-won", "player": "alice", "game": {"winner": "alice"}})
        won = db.legs_won_by_player("m1")
        assert won.get("alice", 0) == 1

    def test_match_won_sets_matches_winner(self, tracker, db):
        """Regression for the X01 side of x01_win_counts(): matches.winner
        used to only ever be written by elimination.py, leaving every X01
        match's winner column NULL forever. Needs a second player's turn too
        (solo matches are excluded from x01_win_counts())."""
        tracker.process(ev_match_started())
        tracker.process(ev_dart(1, 32, 0, field="D16"))
        tracker.process(ev_darts_pulled())
        tracker.process(ev_dart(1, 32, 0, field="D16", player="bob"))
        tracker.process(ev_darts_pulled(player="bob"))
        tracker.process({"event": "match-won", "player": "alice", "game": {"winner": "alice"}})
        assert db.x01_win_counts() == {"alice": 1}
