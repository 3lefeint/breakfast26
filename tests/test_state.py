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


def ev_busted(player="alice", player_index=0, points_left=501, dart_number=0,
              dart_value=0, field_name=None, field_number=None, field_multiplier=None):
    game = {"pointsLeft": points_left}
    if dart_number:
        game.update(dartNumber=str(dart_number), dartValue=str(dart_value),
                    field_name=field_name, field_number=field_number,
                    field_multiplier=field_multiplier)
    return {"event": "busted", "player": player, "playerIndex": player_index,
            "playerIsBot": False, "game": game}


# ── tests ─────────────────────────────────────────────────────────────────────

class TestGameState:
    def test_the_darts_of_a_turn_are_gone_from_the_card_once_they_are_pulled(self):
        gs = GameState()
        gs.update(ev_match_started())
        gs.update(ev_dart1(value=60, points_left=441))
        assert gs.snapshot()["current"]["throw1_raw"] == "T20"
        gs.update({"event": "darts-pulled", "player": "alice", "playerIndex": 0, "playerIsBot": False,
                   "game": {"pointsLeft": "441", "dartsThrown": "1", "dartsThrownValue": "60", "busted": "False",
                            "newTurn": "True"}})
        cur = gs.snapshot()["current"]
        assert cur["throw1_raw"] is None and cur["turn_score"] == 0 and cur["remaining"] == 441

    def test_checkout_hint_follows_the_darts_left_of_the_turn(self):
        gs = GameState()
        gs.update(ev_match_started(pts=170))
        gs.update(ev_dart1(value=60, points_left=110))
        assert gs.snapshot()["checkout"]["route"] == ["T20", "50"]
        dart2 = ev_dart1(value=20, points_left=90)
        dart2["event"] = "dart2-thrown"
        dart2["game"].update(dartNumber=2, fieldName="S20", dartValue=20)
        gs.update(dart2)
        assert gs.snapshot()["checkout"] is None     # 90 needs two darts, one is left

    def test_checkout_hint_is_empty_outside_x01_and_after_a_bust(self):
        gs = GameState()
        gs.update(ev_match_started(mode="Cricket"))
        assert gs.snapshot()["checkout"] is None
        gs = GameState()
        gs.update(ev_match_started(pts=40))
        gs.update(ev_busted(points_left=40))
        assert gs.snapshot()["checkout"] is None

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

    def test_bust_on_first_dart_clears_the_previous_turn_and_fills_d1(self):
        gs = GameState()
        gs.update(ev_match_started())
        gs.update(ev_dart1(value=60, points_left=441))  # previous turn's D1 still in its box
        gs.update(ev_busted(points_left=441, dart_number=1, dart_value=60,
                            field_name="t20", field_number=20, field_multiplier=3))
        cur = gs.players[0]
        assert cur["is_bust"] is True
        assert cur["turn_score"] == 0
        assert cur["throw1_raw"] == "t20" and cur["throw1_points"] == 60
        assert cur["throw2_raw"] is None and cur["throw3_raw"] is None
        assert cur["last_dart_number"] == 1
        assert cur["last_field_name"] == "t20"
        assert cur["last_is_miss"] is False

    def test_bust_on_second_dart_keeps_the_first_dart_and_fills_d2(self):
        gs = GameState()
        gs.update(ev_match_started())
        gs.update(ev_dart1(value=60, points_left=441))
        gs.update(ev_busted(points_left=441, dart_number=2, dart_value=60,
                            field_name="t20", field_number=20, field_multiplier=3))
        cur = gs.players[0]
        assert cur["throw1_raw"] == "T20" and cur["throw1_points"] == 60
        assert cur["throw2_raw"] == "t20" and cur["throw2_points"] == 60
        assert cur["throw3_raw"] is None
        assert cur["turn_score"] == 0
        assert cur["last_dart_number"] == 2

    def test_bust_on_third_dart_fills_d3(self):
        gs = GameState()
        gs.update(ev_match_started())
        gs.update(ev_dart1(value=60, points_left=441))
        dart2 = ev_dart1(value=20, points_left=421)
        dart2["event"] = "dart2-thrown"
        dart2["game"].update(dartNumber=2, fieldName="S20", dartValue=20)
        gs.update(dart2)
        gs.update(ev_busted(points_left=421, dart_number=3, dart_value=60,
                            field_name="t20", field_number=20, field_multiplier=3))
        cur = gs.players[0]
        assert cur["throw1_raw"] == "T20" and cur["throw1_points"] == 60
        assert cur["throw2_raw"] == "S20" and cur["throw2_points"] == 20
        assert cur["throw3_raw"] == "t20" and cur["throw3_points"] == 60
        assert cur["turn_score"] == 0
        assert cur["last_dart_number"] == 3

    def test_bust_without_a_dart_changes_no_box(self):
        gs = GameState()
        gs.update(ev_match_started())
        gs.update(ev_dart1(value=60, points_left=441))
        gs.update(ev_busted(points_left=441))
        cur = gs.players[0]
        assert cur["is_bust"] is True
        assert cur["turn_score"] == 0
        assert cur["throw1_raw"] == "T20" and cur["throw1_points"] == 60
        assert cur["throw2_raw"] is None and cur["throw3_raw"] is None

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
