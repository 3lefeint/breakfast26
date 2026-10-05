"""The Black Belt achievements: each one with a run that earns it and one that does not."""
import pytest

from breakfast.achievements import ACHIEVEMENTS, AchievementEngine, BLACK_BELT
from breakfast.black_belt import BlackBeltGame
from tests.test_black_belt import BULLS_EYE, d
from tests.test_target_battle import FakeMqttClient, MISS, play


@pytest.fixture
def engine(db):
    return AchievementEngine(db).attach()


def _earned(db, player="ana"):
    return {(r["achievement_id"], r["tier"]) for r in db.earned_for_player(player)}


def _ids(db, player="ana"):
    return {a for a, _ in _earned(db, player)}


def run(db, turns, finish=True, backwards=False):
    game = BlackBeltGame("ana", FakeMqttClient(), "autodarts", backwards=backwards, stats_db=db)
    game.announce_start()
    for t in turns:
        play(game, *t)
    if finish and game.state == "playing":
        game.finish_early()
    return game


def ladder_darts(upto):
    """One dart on every double of the ladder up to `upto` fields (21 is the whole ladder)."""
    return [d(n) if n <= 20 else BULLS_EYE for n in range(1, upto + 1)]


def in_turns(darts):
    return [tuple(darts[i:i + 3]) for i in range(0, len(darts), 3)]


class TestDefinitions:
    def test_they_belong_to_black_belt_and_only_decide_its_runs(self):
        mine = [a for a in ACHIEVEMENTS if a.mode == "black_belt"]
        assert len(mine) == 3 and all(a.game_modes == BLACK_BELT for a in mine)
        assert all(a.applies_to("Black Belt") and not a.applies_to("X01") and not a.applies_to("Field Training")
                   for a in mine)
        assert sum(1 for a in mine if a.hidden) == 1


class TestBlackBelt:
    def test_the_whole_ladder_without_a_restart(self, db, engine):
        run(db, in_turns(ladder_darts(21)))
        assert "black_belt" in _ids(db)

    def test_a_belt_in_a_later_attempt_counts_after_earlier_restarts(self, db, engine):
        run(db, [(d(1), MISS, MISS), (MISS, MISS, MISS)] + in_turns(ladder_darts(21)))
        assert "black_belt" in _ids(db)

    def test_not_for_a_run_that_was_finished_early(self, db, engine):
        run(db, in_turns(ladder_darts(20)))
        assert "black_belt" not in _ids(db)

    def test_it_works_backwards_too(self, db, engine):
        darts = [d(n) for n in range(20, 0, -1)] + [BULLS_EYE]
        run(db, in_turns(darts), backwards=True)
        assert "black_belt" in _ids(db)

    def test_an_undone_turn_takes_it_back(self, db, engine):
        game = run(db, in_turns(ladder_darts(21)))
        game.undo()
        assert "black_belt" not in _ids(db)


class TestBeltProgress:
    def test_the_tiers_are_5_10_and_15_fields_in_one_go(self, db, engine):
        run(db, in_turns(ladder_darts(7)))
        assert _earned(db) >= {("belt_progress", 1)} and ("belt_progress", 2) not in _earned(db)
        run(db, in_turns(ladder_darts(16)))
        assert {("belt_progress", 1), ("belt_progress", 2), ("belt_progress", 3)} <= _earned(db)

    def test_fields_of_different_attempts_do_not_add_up(self, db, engine):
        run(db, [(d(1), d(2), d(3)), (d(4), MISS, MISS), (MISS, MISS, MISS)]
            + [(d(1), d(2), d(3)), (d(4), MISS, MISS)])
        assert "belt_progress" not in _ids(db)        # 4 and 4, never 5

    def test_a_run_of_a_few_darts_earns_nothing(self, db, engine):
        run(db, [(d(1), MISS, MISS)])
        assert "belt_progress" not in _ids(db)


class TestDeadEye:
    def test_five_fields_in_a_row_with_the_first_dart_each(self, db, engine):
        run(db, in_turns(ladder_darts(5)))
        assert "dead_eye" in _ids(db)

    def test_a_miss_in_between_starts_the_count_again(self, db, engine):
        run(db, [(d(1), d(2), MISS), (d(3), d(4), d(5))])        # D3 needed a second dart
        assert "dead_eye" not in _ids(db)

    def test_four_in_a_row_are_not_enough(self, db, engine):
        run(db, in_turns(ladder_darts(4)))
        assert "dead_eye" not in _ids(db)

    def test_the_count_starts_again_after_a_restart(self, db, engine):
        run(db, [(d(1), d(2), d(3)), (MISS, MISS, MISS), (d(1), d(2), d(3)), (d(4), d(5), MISS)])
        assert "dead_eye" in _ids(db)                           # D1 to D5 of the second attempt

    def test_a_hit_with_a_later_dart_at_a_field_does_not_count(self, db, engine):
        run(db, [(d(1), d(2), d(3)), (MISS, d(4), d(5)), (d(6), MISS, MISS)])
        assert "dead_eye" not in _ids(db)


class TestRuns:
    def test_a_finished_run_is_a_match_of_the_player(self, db, engine):
        run(db, [(d(1), MISS, MISS)])
        assert "first_breakfast" in _ids(db)

    def test_the_overview_shows_the_progress(self, db, engine):
        run(db, in_turns(ladder_darts(7)))
        item = {i["id"]: i for i in engine.overview("ana")}["belt_progress"]
        assert (item["tier"], item["progress"], item["next"]) == (1, 7, 10)
