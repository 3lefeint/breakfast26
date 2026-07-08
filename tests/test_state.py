from breakfast.state import GameState


# ── event builders ────────────────────────────────────────────────────────────

def ev_match_started(match_id="test-1", mode="X01", pts=501):
    return {"event": "match-started", "id": match_id, "player": "alice",
            "playerIndex": 0, "playerIsBot": False,
            "game": {"mode": mode, "pointsStart": pts},
            "remainingScores": {"0": pts}}


def ev_dart1(value=60, points_left=441, player="alice", player_index=0):
    return {"event": "dart1-thrown", "player": player, "playerIndex": player_index,
            "playerIsBot": False,
            "game": {"dartNumber": 1, "dartValue": value, "fieldName": "T20",
                     "fieldNumber": 20, "fieldMultiplier": 3, "pointsLeft": points_left,
                     "type": "segment"}}


def ev_busted(player="alice", player_index=0, points_left=501):
    return {"event": "busted", "player": player, "playerIndex": player_index,
            "playerIsBot": False, "game": {"pointsLeft": points_left}}


# ── tests ─────────────────────────────────────────────────────────────────────

class TestGameState:
    def test_match_started(self):
        gs = GameState()
        result = gs.update(ev_match_started())
        assert gs.match_started is True
        assert gs.match_id == "test-1"
        assert gs.game_mode == "X01"
        assert result == {"type": "match_started", "mode": "X01"}

    def test_dart_thrown_updates_remaining(self):
        gs = GameState()
        gs.update(ev_match_started())
        gs.update(ev_dart1(value=60, points_left=441))
        assert gs.players[0]["remaining"] == 441

    def test_dart_thrown_sets_throw_fields(self):
        gs = GameState()
        gs.update(ev_match_started())
        gs.update(ev_dart1(value=60, points_left=441))
        assert gs.players[0]["throw1_raw"] == "T20"
        assert gs.players[0]["throw1_points"] == 60
        assert gs.players[0]["turn_score"] == 60

    def test_bust_sets_flag(self):
        gs = GameState()
        gs.update(ev_match_started())
        gs.update(ev_dart1())
        gs.update(ev_busted())
        assert gs.players[0]["is_bust"] is True

    def test_bust_result_type(self):
        gs = GameState()
        gs.update(ev_match_started())
        gs.update(ev_dart1())
        result = gs.update(ev_busted())
        assert result is not None
        assert result["type"] == "bust"

    def test_snapshot_is_copy(self):
        gs = GameState()
        gs.update(ev_match_started())
        gs.update(ev_dart1())
        snap = gs.snapshot()
        snap["players"][0]["name"] = "MODIFIED"
        assert gs.players[0]["name"] == "alice"

    def test_reset_clears_state(self):
        gs = GameState()
        gs.update(ev_match_started())
        gs.reset()
        assert gs.match_started is False
        assert gs.players == {}
        assert gs.match_id is None
        assert gs.game_mode is None

    def test_unknown_event_returns_none(self):
        gs = GameState()
        result = gs.update({"event": "welcome"})
        assert result is None

    def test_throw_seq_increments(self):
        gs = GameState()
        gs.update(ev_match_started())
        gs.update(ev_dart1(value=60, points_left=441))
        assert gs.throw_seq == 1
        gs.update({"event": "dart2-thrown", "player": "alice", "playerIndex": 0,
                   "playerIsBot": False,
                   "game": {"dartNumber": 2, "dartValue": 60, "fieldName": "T20",
                            "fieldNumber": 20, "fieldMultiplier": 3, "pointsLeft": 381,
                            "type": "segment"}})
        assert gs.throw_seq == 2

    def test_remaining_scores_applied(self):
        gs = GameState()
        gs.update(ev_match_started(pts=501))
        assert gs.remaining_scores == {"0": 501}

    def test_current_leg_starts_at_one(self):
        gs = GameState()
        gs.update(ev_match_started())
        assert gs.current_leg == 1

    def test_current_leg_increments_on_game_won(self):
        gs = GameState()
        gs.update(ev_match_started())
        gs.update({"event": "game-won", "player": "alice", "playerIndex": 0,
                   "playerIsBot": False, "game": {"winner": "alice"}})
        assert gs.current_leg == 2

    def test_legs_won_tracked_for_winner(self):
        gs = GameState()
        gs.update(ev_match_started())
        gs.update(ev_dart1())
        gs.update({"event": "game-won", "player": "alice", "playerIndex": 0,
                   "playerIsBot": False, "game": {"winner": "alice"}})
        assert gs.players[0]["legs_won"] == 1

    def test_current_leg_in_snapshot(self):
        gs = GameState()
        gs.update(ev_match_started())
        snap = gs.snapshot()
        assert snap["current_leg"] == 1

    def test_current_leg_resets_on_new_match(self):
        gs = GameState()
        gs.update(ev_match_started(match_id="m1"))
        gs.update({"event": "game-won", "player": "alice", "playerIndex": 0,
                   "playerIsBot": False, "game": {}})
        assert gs.current_leg == 2
        gs.update(ev_match_started(match_id="m2"))
        assert gs.current_leg == 1
