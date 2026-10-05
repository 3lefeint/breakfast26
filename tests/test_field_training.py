import pytest

from breakfast.field_training import (FieldTrainingController, FieldTrainingGame, rating,
                                       scaled_points, standard_darts)
from breakfast.stats import StatsDB
from tests.test_target_battle import BULL, FakeMqttClient, FakeMqttPub, MISS, hit, play

OUTER_BULL = {"segment": {"name": "25", "number": 25, "multiplier": 1}, "coords": {"x": 0.05, "y": 0.02}}


def new_game(field=20, darts=6, db=None, player="ana"):
    game = FieldTrainingGame(player, FakeMqttClient(), "autodarts", field, darts=darts, stats_db=db)
    game.announce_start()
    return game


@pytest.fixture
def db(tmp_path):
    return StatsDB(str(tmp_path / "s.db"))


def test_a_run_has_standard_lengths():
    assert standard_darts(20) == 100 and standard_darts(25) == 50
    game = FieldTrainingGame("ana", FakeMqttClient(), "autodarts", 5)
    assert game.darts == 100
    assert FieldTrainingGame("ana", FakeMqttClient(), "autodarts", 25).darts == 50


@pytest.mark.parametrize("kw", [{"field": 0}, {"field": 21}, {"field": 20, "darts": 0},
                                {"field": 20, "darts": 1000}])
def test_a_setup_that_cannot_be_played_is_refused(kw):
    with pytest.raises(ValueError):
        FieldTrainingGame("ana", FakeMqttClient(), "autodarts", **kw)


def test_a_player_is_needed():
    with pytest.raises(ValueError):
        FieldTrainingGame("  ", FakeMqttClient(), "autodarts", 20)


def test_a_number_scores_its_multiplier():
    game = new_game(darts=9)
    play(game, hit(20, 1), hit(20, 2), hit(20, 3))
    play(game, hit(19, 3), MISS, BULL)
    snap = game.snapshot()
    assert snap["points"] == 6 and snap["thrown"] == 6 and snap["remaining"] == 3
    assert snap["hits"] == {"singles": 1, "doubles": 1, "triples": 1}
    assert snap["turn_points"] == [6, 0]


def test_the_bull_scores_the_outer_bull_one_and_the_bulls_eye_two():
    game = new_game(field=25, darts=6)
    play(game, OUTER_BULL, BULL, hit(20, 3))
    snap = game.snapshot()
    assert snap["points"] == 3
    assert snap["hits"] == {"singles": 1, "doubles": 1, "triples": 0}


def test_the_last_turn_only_takes_the_darts_that_are_left():
    game = new_game(darts=4)
    play(game, hit(20, 1), hit(20, 1), hit(20, 1))
    play(game, hit(20, 3), hit(20, 3), hit(20, 3))      # three darts on the board, one is left
    snap = game.snapshot()
    assert snap["state"] == "finished" and snap["thrown"] == 4 and snap["points"] == 6
    assert len(snap["all_darts"]) == 4


def test_the_run_finishes_after_the_last_dart_and_is_a_full_run_only_at_the_standard_length(db):
    short = new_game(darts=3, db=db)
    play(short, hit(20, 3), hit(20, 3), hit(20, 3))
    assert short.snapshot()["result"]["counts"] is False       # 3 darts: practice
    full = new_game(field=25, darts=50, db=db)
    for _ in range(17):
        play(full, BULL, BULL, BULL)
    play(full, BULL, BULL)
    result = full.snapshot()["result"]
    assert full.state == "finished" and result["counts"] is True
    assert result["points"] == 100 and result["rating"] == "pro" and result["personal_best"] is True


def test_a_run_stopped_early_is_practice(db):
    game = new_game(field=25, darts=50, db=db)
    play(game, BULL, BULL, BULL)
    assert game.finish_early() is True
    result = game.snapshot()["result"]
    assert (result["counts"], result["rating"], result["personal_best"]) == (False, None, False)
    assert result["darts"] == 3 and result["points"] == 6
    assert db.field_training_best("ana", 25) is None


def test_stopping_without_a_dart_keeps_nothing(db):
    game = new_game(db=db)
    assert game.finish_early() is False and game.state == "playing"


def test_darts_of_an_unfinished_turn_are_not_counted_when_stopping():
    game = new_game(darts=9)
    play(game, hit(20, 1), hit(20, 1), hit(20, 1))
    game.on_board_state(1, [hit(20, 3)])
    game.finish_early()
    assert game.snapshot()["thrown"] == 3 and game.snapshot()["points"] == 3


def test_the_personal_best_compares_with_earlier_full_runs(db):
    def run(points_per_turn):
        game = new_game(field=25, darts=50, db=db)
        for _ in range(16):
            play(game, *points_per_turn)
        play(game, *points_per_turn)
        play(game, points_per_turn[0])
        return game.snapshot()["result"]
    first = run((BULL, MISS, MISS))
    second = run((OUTER_BULL, MISS, MISS))
    third = run((BULL, BULL, MISS))
    assert first["personal_best"] is True and first["previous_best"] is None
    assert second["personal_best"] is False and second["previous_best"] == first["scaled_points"]
    assert third["personal_best"] is True


def test_the_rating_uses_the_scale_of_the_standard_length():
    assert rating(25, 19, 50) == "beginner" and rating(25, 30, 50) == "advanced"
    assert rating(25, 50, 50) == "advanced" and rating(25, 51, 50) == "pro"
    assert rating(25, 15, 25) == "advanced"          # half the darts, the double of the points
    assert rating(20, 59, 100) == "beginner" and rating(20, 101, 100) == "pro"
    assert scaled_points(25, 20, 25) == 40.0


def test_everything_is_stored_and_the_match_is_closed(db):
    game = new_game(darts=4, db=db)
    play(game, hit(20, 1), hit(20, 2), MISS)
    play(game, hit(20, 3))
    row = db._conn.execute("SELECT * FROM field_training_games").fetchone()
    assert (row["player"], row["field"], row["darts"], row["counts"]) == ("ana", 20, 4, 0)
    turns = db._conn.execute("SELECT darts_count, score, singles, doubles, triples"
                             " FROM field_training_turns ORDER BY id").fetchall()
    assert [tuple(t) for t in turns] == [(3, 3, 1, 1, 0), (1, 3, 0, 0, 1)]
    assert db._conn.execute("SELECT COUNT(*) FROM dart_positions WHERE game_mode = 'Field Training'"
                            ).fetchone()[0] == 4
    match = db._conn.execute("SELECT game_mode, ended_at FROM matches").fetchone()
    assert match["game_mode"] == "Field Training" and match["ended_at"]


def test_undo_walks_back_a_turn_and_reopens_a_finished_run(db):
    game = new_game(darts=4, db=db)
    play(game, hit(20, 1), hit(20, 1), hit(20, 1))
    play(game, hit(20, 3))
    assert game.state == "finished"
    assert game.undo() is True
    assert game.state == "playing" and game.snapshot()["thrown"] == 3
    assert db._conn.execute("SELECT ended_at FROM matches").fetchone()[0] is None
    assert db._conn.execute("SELECT COUNT(*) FROM field_training_turns").fetchone()[0] == 1
    assert db._conn.execute("SELECT COUNT(*) FROM dart_positions").fetchone()[0] == 3
    assert game.undo() is True and game.snapshot()["thrown"] == 0
    assert game.undo() is False


def test_a_dart_corrected_by_tapping_is_what_counts():
    game = new_game(darts=6)
    game.on_board_state(1, [MISS])
    game.correct_current_dart(0, "T20")
    game.on_board_state(0, [])
    assert game.snapshot()["points"] == 3


def test_practice_runs_stay_out_of_the_other_statistics(db):
    game = new_game(darts=3, db=db)
    play(game, hit(20, 3), hit(20, 3), hit(20, 3))
    assert db.recent_matches(10, "x01") == []
    assert [m["game_mode"] for m in db.recent_matches(10)] == ["Field Training"]
    assert db.match_participants(game.match_id) == []          # not a full run: no achievements
    assert db.player_final_matches("ana", "2000-01-01") == []


def test_a_full_run_is_a_match_of_the_player(db):
    full = new_game(field=25, darts=50, db=db)
    for _ in range(16):
        play(full, BULL, BULL, BULL)
    play(full, BULL, BULL)
    assert db.match_participants(full.match_id) == ["ana"]
    assert [m["match_id"] for m in db.player_final_matches("ana", "2000-01-01")] == [full.match_id]


def test_the_controller_starts_a_run_and_reads_the_mqtt_command(db):
    pub = FakeMqttPub()
    ctrl = FieldTrainingController(pub, "autodarts", stats_db=db)
    ctrl.start("ana", 20, darts=6)
    assert ctrl.active and ctrl.game.field == 20
    ctrl.stop()
    assert not ctrl.active
    pub.subscribed["autodarts/field_training/command"](
        '{"action": "start", "player": "bo", "field": 25}')
    assert ctrl.game.player == "bo" and ctrl.game.darts == 50
    assert ctrl.finish_early() is False
    pub.subscribed["autodarts/field_training/command"]('{"action": "correct_turn", "total": 3}')
