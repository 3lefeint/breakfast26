import pytest

from breakfast.field_training import FieldTrainingGame
from breakfast.stats import StatsDB
from tests.test_target_battle import BULL, FakeMqttClient, MISS, hit, play

OUTER_BULL = {"segment": {"name": "25", "number": 25, "multiplier": 1}, "coords": {"x": 0.05, "y": 0.02}}


@pytest.fixture
def db(tmp_path):
    return StatsDB(str(tmp_path / "s.db"))


def run(db, player, field, darts, turns, finish=False):
    """A run: `turns` is a list of dart lists, one per turn."""
    game = FieldTrainingGame(player, FakeMqttClient(), "autodarts", field, darts=darts, stats_db=db)
    game.announce_start()
    for throws in turns:
        play(game, *throws)
    if finish:
        game.finish_early()
    return game


def full_bull_run(db, player, pattern):
    """50 darts at the bull, every turn the same three darts, the last one a single dart."""
    return run(db, player, 25, 50, [pattern] * 16 + [pattern[:2]])


def test_the_overview_has_the_best_and_the_average_of_the_runs_that_count(db):
    full_bull_run(db, "ana", (BULL, MISS, MISS))
    full_bull_run(db, "ana", (BULL, BULL, MISS))
    over = db.field_training_overview()
    (player,) = over["players"]
    (field,) = player["fields"]
    runs = field["runs"]
    assert [r["counts"] for r in runs] == [True, True]
    assert field["counted"] == 2 and field["practice"] == 0
    assert field["best"] == max(r["scaled_points"] for r in runs)
    assert field["average"] == pytest.approx(sum(r["scaled_points"] for r in runs) / 2, abs=0.1)
    assert field["field"] == 25 and field["standard_darts"] == 50


def test_practice_runs_are_listed_but_not_counted(db):
    run(db, "ana", 20, 6, [(hit(20, 3), hit(20, 3), hit(20, 3)), (hit(20, 1), MISS, MISS)])
    run(db, "ana", 25, 50, [(BULL, BULL, BULL)], finish=True)
    over = db.field_training_overview()
    fields = {f["field"]: f for f in over["players"][0]["fields"]}
    assert [f["field"] for f in over["players"][0]["fields"]] == [20, 25]       # the bull last
    assert fields[20]["counted"] == 0 and fields[20]["best"] is None and fields[20]["practice"] == 1
    assert fields[20]["runs"][0]["points"] == 10 and fields[20]["runs"][0]["rating"] is None
    assert fields[25]["runs"][0]["darts"] == 3 and fields[25]["runs"][0]["counts"] is False


def test_the_hit_rate_covers_all_darts_and_the_positions_are_listed(db):
    run(db, "ana", 20, 6, [(hit(20, 1), MISS, MISS), (hit(20, 2), hit(20, 3), MISS)])
    (field,) = db.field_training_overview()["players"][0]["fields"]
    assert field["hit_rate"] == round(3 / 6, 3)
    assert len(field["positions"]["darts"]) == 6 and field["positions"]["corrected"] == 0


def test_an_open_run_and_a_hidden_player_are_left_out(db):
    game = FieldTrainingGame("ana", FakeMqttClient(), "autodarts", 20, darts=6, stats_db=db)
    play(game, hit(20, 1), hit(20, 1), hit(20, 1))
    assert db.field_training_overview() == {"players": []}
    run(db, "bo", 20, 3, [(hit(20, 1), hit(20, 1), hit(20, 1))])
    db.upsert_player("bo", hidden=True)
    assert db.field_training_overview() == {"players": []}


def test_a_player_deleted_takes_the_runs_with_it(db):
    run(db, "ana", 20, 3, [(hit(20, 1), hit(20, 1), hit(20, 1))])
    db.delete_player("ana")
    assert db.field_training_overview() == {"players": []}
    assert db._conn.execute("SELECT COUNT(*) FROM dart_positions").fetchone()[0] == 0


def test_the_match_list_and_the_detail_of_a_run(db):
    game = run(db, "ana", 25, 6, [(BULL, OUTER_BULL, MISS), (MISS, MISS, MISS)])
    (match,) = db.recent_matches(10, "field_training")
    assert (match["game_mode"], match["field"], match["points_start"], match["players"]) == (
        "Field Training", 25, 6, ["ana"])
    detail = db.match_stats(game.match_id)
    assert (detail["player"], detail["field"], detail["points"], detail["darts"]) == ("ana", 25, 3, 6)
    assert detail["singles"] == 1 and detail["doubles"] == 1 and detail["hit_rate"] == round(2 / 6, 3)
