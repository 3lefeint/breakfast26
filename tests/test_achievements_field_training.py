"""The Field Training achievements: each one with a run that earns it and one that does not."""
import pytest

from breakfast.achievements import ACHIEVEMENTS, AchievementEngine, FIELD_TRAINING
from breakfast.field_training import FieldTrainingGame
from tests.test_target_battle import BULL, FakeMqttClient, MISS, hit, play

OUTER_BULL = {"segment": {"name": "25", "number": 25, "multiplier": 1}, "coords": {"x": 0.05, "y": 0.02}}


@pytest.fixture
def engine(db):
    return AchievementEngine(db).attach()


def _earned(db, player="ana"):
    return {(r["achievement_id"], r["tier"]) for r in db.earned_for_player(player)}


def _ids(db, player="ana"):
    return {a for a, _ in _earned(db, player)}


def run(db, field, darts, pattern, player="ana"):
    """A run in which every turn throws `pattern`; a last turn takes what is left."""
    game = FieldTrainingGame(player, FakeMqttClient(), "autodarts", field, darts=darts, stats_db=db)
    game.announce_start()
    while game.state == "playing":
        play(game, *pattern)
    return game


def bull_run(db, pattern, darts=50):
    return run(db, 25, darts, pattern)


class TestDefinitions:
    def test_they_belong_to_field_training_and_only_decide_its_runs(self):
        mine = [a for a in ACHIEVEMENTS if a.mode == "field_training"]
        assert len(mine) == 4 and all(a.game_modes == FIELD_TRAINING for a in mine)
        assert all(a.applies_to("Field Training") and not a.applies_to("X01") and not a.applies_to("Killer")
                   for a in mine)
        assert sum(1 for a in mine if a.hidden) == 2
        assert [a.id for a in mine if a.practice] == ["triple_threat"]


class TestBullDrill:
    def test_the_tiers_are_20_40_and_50_points_at_the_bull(self, db, engine):
        bull_run(db, (OUTER_BULL, MISS, MISS))              # 17 points
        assert "bull_drill" not in _ids(db)
        bull_run(db, (BULL, MISS, MISS))                    # 34 points
        assert _earned(db) >= {("bull_drill", 1)} and ("bull_drill", 2) not in _earned(db)
        bull_run(db, (BULL, BULL, MISS))                    # 68 points
        assert {("bull_drill", 1), ("bull_drill", 2), ("bull_drill", 3)} <= _earned(db)

    def test_a_longer_run_counts_scaled_to_50_darts(self, db, engine):
        bull_run(db, (BULL, MISS, MISS), darts=100)         # 67 points in 100 darts: 33 on the scale of 50
        assert ("bull_drill", 1) in _earned(db) and ("bull_drill", 2) not in _earned(db)

    def test_a_run_that_is_only_practice_does_not_count(self, db, engine):
        bull_run(db, (BULL, BULL, BULL), darts=9)
        game = FieldTrainingGame("ana", FakeMqttClient(), "autodarts", 25, darts=50, stats_db=db)
        play(game, BULL, BULL, BULL)
        game.finish_early()
        assert "bull_drill" not in _ids(db)

    def test_an_undone_turn_takes_it_back(self, db, engine):
        game = bull_run(db, (BULL, BULL, MISS))
        assert ("bull_drill", 3) in _earned(db)
        game.undo()
        assert game.state == "playing" and not _ids(db)


class TestHundredDarts:
    def test_it_counts_complete_runs_at_a_number_with_tiers_1_5_and_20(self, db, engine):
        run(db, 20, 100, (MISS, MISS, MISS))
        assert _earned(db) >= {("hundred_darts", 1)} and ("hundred_darts", 2) not in _earned(db)
        for _ in range(4):
            run(db, 7, 100, (MISS, MISS, MISS))
        assert ("hundred_darts", 2) in _earned(db)

    def test_not_a_short_run_and_not_the_bull(self, db, engine):
        run(db, 20, 99, (MISS, MISS, MISS))
        bull_run(db, (MISS, MISS, MISS))
        assert "hundred_darts" not in _ids(db)


class TestTripleThreat:
    def test_three_triples_of_the_field_in_one_turn(self, db, engine):
        run(db, 19, 3, (hit(19, 3), hit(19, 3), hit(19, 3)))
        assert "triple_threat" in _ids(db)                  # a run of three darts is practice, it counts anyway

    def test_not_with_another_field_or_a_double(self, db, engine):
        run(db, 19, 3, (hit(19, 3), hit(19, 3), hit(19, 2)))
        run(db, 18, 3, (hit(19, 3), hit(19, 3), hit(19, 3)))
        assert "triple_threat" not in _ids(db)

    def test_a_dart_corrected_by_tapping_counts_with_its_field(self, db, engine):
        game = FieldTrainingGame("ana", FakeMqttClient(), "autodarts", 19, darts=3, stats_db=db)
        game.on_board_state(3, [hit(19, 3), hit(19, 3), MISS])
        game.correct_current_dart(2, "T19")
        game.on_board_state(0, [])
        assert "triple_threat" in _ids(db)


class TestGrandTour:
    def test_a_full_run_at_every_number_and_the_bull(self, db, engine):
        for number in range(1, 21):
            run(db, number, 100, (MISS, MISS, MISS))
        assert "grand_tour" not in _ids(db)                 # the bull is missing
        bull_run(db, (MISS, MISS, MISS))
        assert "grand_tour" in _ids(db)

    def test_practice_runs_do_not_count_towards_it(self, db, engine):
        for number in range(1, 21):
            run(db, number, 100, (MISS, MISS, MISS))
        bull_run(db, (MISS, MISS, MISS), darts=30)
        assert "grand_tour" not in _ids(db)


class TestPracticeRuns:
    def test_a_practice_run_earns_none_of_the_general_achievements(self, db, engine):
        run(db, 20, 6, (hit(20, 3), MISS, MISS))
        assert _ids(db) == set()

    def test_a_full_run_is_a_finished_match(self, db, engine):
        run(db, 20, 100, (MISS, MISS, MISS))
        assert "first_breakfast" in _ids(db)

    def test_the_overview_shows_the_progress(self, db, engine):
        run(db, 20, 100, (MISS, MISS, MISS))
        run(db, 20, 6, (hit(20, 1), MISS, MISS))
        item = {i["id"]: i for i in engine.overview("ana")}["hundred_darts"]
        assert (item["tier"], item["progress"], item["next"]) == (1, 1, 5)
