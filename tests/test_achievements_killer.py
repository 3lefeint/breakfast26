"""The Killer achievements and the Four-Course Meal: each one with a game that earns it and one that does not."""
import pytest

from breakfast.achievements import ACHIEVEMENTS, KILLER, AchievementEngine
from tests.test_achievements import _elimination_match
from tests.test_achievements_list import _match as _x01_match
from tests.test_achievements_target_battle import game as tb_game
from tests.test_killer_stats import NUMBERS, new_game
from tests.test_target_battle import MISS, hit, play


@pytest.fixture
def engine(db):
    return AchievementEngine(db).attach()


def earned(db, player="ana"):
    return {r["achievement_id"] for r in db.earned_for_player(player)}


NOTHING = hit(1, 1)       # a field nobody owns


def finish(game, winner):
    """Play on until `winner` has put everybody else out: the winner makes themselves a killer and
    attacks the first player still in, everybody else throws at nothing."""
    for _ in range(60):
        if game.state == "finished":
            return
        me = game.current_player
        if me != winner:
            play(game, NOTHING)
            continue
        darts, killer = [], winner in game.killers
        for _i in range(3):
            if not killer:
                darts.append(hit(NUMBERS[winner], 2))
                killer = True
            else:
                victim = next((p for p in game.order if p != winner and game.lives[p] > 0), None)
                darts.append(hit(NUMBERS[victim], 2) if victim else NOTHING)
        play(game, *darts)
    raise AssertionError("the game did not end")


class TestDefinitions:
    def test_the_killer_ones_belong_to_killer_and_only_decide_killer_games(self):
        mine = [a for a in ACHIEVEMENTS if a.mode == "killer"]
        assert len(mine) == 14 and all(a.game_modes == KILLER for a in mine)
        assert all(a.applies_to("Killer") and not a.applies_to("X01") and not a.applies_to("Elimination")
                   for a in mine)
        assert sum(1 for a in mine if a.hidden) == 4


class TestEasyOnes:
    def test_a_quick_duel_win(self, db, engine):
        game = new_game(db, players=("ana", "bo"))
        play(game, hit(20, 2))
        play(game, MISS)
        play(game, hit(5, 2), hit(5, 2), hit(5, 2))
        got = earned(db)
        assert {"licence_to_breakfast", "armed_immediately", "first_blood", "three_in_one", "finisher"} <= got
        assert not got & {"last_breath", "unscathed", "all_round_attack", "double_knockout", "double_agent"}
        assert not earned(db, "bo") & {a.id for a in ACHIEVEMENTS if a.mode == "killer"}

    def test_armed_immediately_needs_the_double_with_the_first_dart(self, db, engine):
        game = new_game(db, players=("ana", "bo"))
        play(game, NOTHING, hit(20, 2))
        play(game, MISS)
        play(game, hit(5, 2), hit(5, 2), hit(5, 2))
        assert "licence_to_breakfast" in earned(db) and "armed_immediately" not in earned(db)

    def test_a_double_thrown_for_the_number_is_a_killer_but_not_armed_immediately(self, db):
        from breakfast.killer import KillerGame
        from tests.test_target_battle import FakeMqttClient
        AchievementEngine(db).attach()
        game = KillerGame(["ana", "bo"], FakeMqttClient(), "autodarts", stats_db=db, throw_numbers=True)
        game.announce_start()
        play(game, hit(20, 2))                       # ana's number, with a double
        play(game, hit(5, 1))
        play(game, MISS)
        play(game, MISS)
        play(game, hit(5, 2), hit(5, 2), hit(5, 2))
        assert "licence_to_breakfast" in earned(db) and "armed_immediately" not in earned(db)

    def test_a_killer_who_never_hits_an_opponent_gets_no_blood(self, db, engine):
        game = new_game(db, players=("ana", "bo"))
        play(game, hit(20, 2))                                # ana is a killer, and that is all
        finish(game, "bo")
        got = earned(db)
        assert "licence_to_breakfast" in got and not got & {"first_blood", "finisher", "three_in_one"}
        assert {"first_blood", "finisher"} <= earned(db, "bo")


class TestThreePlayers:
    def test_a_win_without_losing_a_life(self, db, engine):
        game = new_game(db, players=("ana", "bo", "cy"))
        finish(game, "ana")
        got = earned(db)
        assert {"unscathed", "double_agent", "finisher", "first_blood", "three_in_one"} <= got
        assert not got & {"last_breath", "double_knockout", "all_round_attack"}

    def test_two_players_are_not_enough_for_unscathed_and_double_agent(self, db, engine):
        game = new_game(db, players=("ana", "bo"))
        finish(game, "ana")
        assert not earned(db) & {"unscathed", "double_agent"}

    def test_a_lost_life_spoils_unscathed(self, db, engine):
        game = new_game(db, players=("ana", "bo", "cy"))
        play(game, NOTHING)                                   # ana
        play(game, hit(5, 2))                                 # bo: killer
        play(game, NOTHING)                                   # cy
        play(game, NOTHING)                                   # ana
        play(game, hit(20, 2))                                # bo: takes one of ana's lives
        play(game, NOTHING)
        finish(game, "ana")
        assert "unscathed" not in earned(db)

    def test_singles_that_take_lives_spoil_double_agent(self, db, engine):
        game = new_game(db, players=("ana", "bo", "cy"), singles=True)
        finish(game, "ana")
        assert "double_agent" not in earned(db) and "unscathed" in earned(db)

    def test_friendly_to_the_end_for_everybody_who_is_out_without_a_hit(self, db, engine):
        game = new_game(db, players=("ana", "bo", "cy"))
        play(game, NOTHING)                                   # ana
        play(game, hit(5, 2), hit(20, 2), hit(20, 2))         # bo: killer, takes two lives from ana
        play(game, NOTHING)                                   # cy
        play(game, NOTHING)                                   # ana
        play(game, hit(20, 2), hit(12, 2), hit(12, 2))        # bo: ana is out, cy loses two
        finish(game, "bo")
        assert "friendly_to_the_end" in earned(db, "ana") and "friendly_to_the_end" in earned(db, "cy")
        assert "friendly_to_the_end" not in earned(db, "bo")

    def test_friendly_to_the_end_needs_three_players(self, db, engine):
        game = new_game(db, players=("ana", "bo"))
        play(game, NOTHING)
        finish(game, "bo")
        assert "friendly_to_the_end" not in earned(db)


class TestFourPlayers:
    def test_three_different_opponents_in_one_turn(self, db, engine):
        game = new_game(db, players=("ana", "bo", "cy", "dan"))
        play(game, hit(20, 2))
        for _ in range(3):
            play(game, NOTHING)
        play(game, hit(5, 2), hit(12, 2), hit(3, 2))
        finish(game, "ana")
        assert "all_round_attack" in earned(db)

    def test_three_hits_on_two_opponents_are_not_enough(self, db, engine):
        game = new_game(db, players=("ana", "bo", "cy", "dan"))
        play(game, hit(20, 2))
        for _ in range(3):
            play(game, NOTHING)
        play(game, hit(5, 2), hit(5, 2), hit(12, 2))
        finish(game, "ana")
        assert "all_round_attack" not in earned(db) and "three_in_one" in earned(db)

    def test_three_opponents_in_one_turn_need_four_players(self, db, engine):
        game = new_game(db, players=("ana", "bo", "cy"))
        play(game, hit(20, 2))
        play(game, NOTHING); play(game, NOTHING)
        play(game, hit(5, 2), hit(12, 2), hit(5, 2))
        finish(game, "ana")
        assert "all_round_attack" not in earned(db)


class TestKnockouts:
    def _ready_for_two(self, db):
        """bo and cy are at one life each when ana is up."""
        game = new_game(db, players=("ana", "bo", "cy"))
        play(game, hit(20, 2))
        play(game, NOTHING); play(game, NOTHING)
        play(game, hit(5, 2), hit(5, 2), hit(12, 2))          # bo 1, cy 2
        play(game, NOTHING); play(game, NOTHING)
        play(game, hit(12, 2), NOTHING, NOTHING)              # cy 1
        play(game, NOTHING); play(game, NOTHING)
        return game

    def test_two_players_out_in_one_turn(self, db, engine):
        game = self._ready_for_two(db)
        play(game, hit(5, 2), hit(12, 2))
        assert game.state == "finished"
        assert "double_knockout" in earned(db)

    def test_two_knockouts_in_different_turns_are_not_a_double_knockout(self, db, engine):
        game = self._ready_for_two(db)
        play(game, hit(5, 2), NOTHING, NOTHING)
        play(game, NOTHING)
        play(game, hit(12, 2))
        assert game.state == "finished"
        assert "double_knockout" not in earned(db) and "finisher" in earned(db)


class TestOwnGoals:
    def test_win_with_one_life_left(self, db, engine):
        game = new_game(db, players=("ana", "bo"), own_goal=True)
        play(game, hit(20, 2), hit(20, 2), hit(20, 2))        # killer, then two own goals
        play(game, NOTHING)
        play(game, hit(5, 2), hit(5, 2), hit(5, 2))
        assert game.winner == "ana" and "last_breath" in earned(db)

    def test_win_with_two_lives_left_is_not_the_last_breath(self, db, engine):
        game = new_game(db, players=("ana", "bo"), own_goal=True)
        play(game, hit(20, 2), hit(20, 2), hit(5, 2))
        play(game, NOTHING)
        play(game, hit(5, 2), hit(5, 2))
        assert game.winner == "ana" and "last_breath" not in earned(db)

    def test_losing_the_last_life_to_an_own_goal(self, db, engine):
        game = new_game(db, players=("ana", "bo"), own_goal=True)
        play(game, hit(20, 2), hit(20, 2), hit(20, 2))
        play(game, NOTHING)
        play(game, hit(20, 2))
        assert game.winner == "bo"
        got = earned(db)
        assert {"self_service", "own_worst_enemy"} <= got
        assert "last_breath" not in earned(db, "bo")

    def test_lives_lost_to_an_opponent_spoil_the_own_worst_enemy(self, db, engine):
        game = new_game(db, players=("ana", "bo", "cy"), own_goal=True)
        play(game, hit(20, 2), hit(20, 2), NOTHING)           # killer, one own goal
        play(game, hit(5, 2), hit(20, 2), NOTHING)            # bo: killer, takes a life from ana
        play(game, NOTHING)
        play(game, hit(20, 2), hit(20, 2), NOTHING)           # ana is out by own goals
        finish(game, "bo")
        assert "self_service" in earned(db) and "own_worst_enemy" not in earned(db)

    def test_two_hits_and_then_an_own_goal_that_puts_the_player_out(self, db, engine):
        game = new_game(db, players=("ana", "bo", "cy"), own_goal=True)
        play(game, hit(20, 2), hit(20, 2), hit(20, 2))        # killer, two own goals, one life left
        play(game, NOTHING); play(game, NOTHING)
        play(game, hit(5, 2), hit(12, 2), hit(20, 2))         # two hits, then out
        assert game.snapshot()["players"][0]["out"]
        finish(game, "bo")
        got = earned(db)
        assert "glass_cannon" in got and "friendly_to_the_end" not in got

    def test_an_own_goal_before_the_hits_is_no_glass_cannon(self, db, engine):
        game = new_game(db, players=("ana", "bo", "cy"), own_goal=True)
        play(game, hit(20, 2), hit(20, 2), hit(20, 2))
        play(game, NOTHING); play(game, NOTHING)
        play(game, hit(20, 2), hit(5, 2), hit(12, 2))         # out with the first dart, the rest does not count
        finish(game, "bo")
        assert "glass_cannon" not in earned(db)


class TestFourCourseMeal:
    def test_one_game_of_every_kind(self, db, engine):
        _x01_match(db, "x1", [["S20"]], winner="bo")
        _elimination_match(db, "e1", ["ana", "bo"], winner="bo")
        tb_game(db, {"ana": [1, 1], "bo": [0, 0]}, rounds=2)
        assert "four_course_meal" not in earned(db)
        game = new_game(db, players=("ana", "bo"))
        finish(game, "bo")
        assert "four_course_meal" in earned(db)

    def test_three_kinds_are_not_enough(self, db, engine):
        _x01_match(db, "x1", [["S20"]], winner="bo")
        _elimination_match(db, "e1", ["ana", "bo"], winner="bo")
        game = new_game(db, players=("ana", "bo"))
        finish(game, "bo")
        assert "four_course_meal" not in earned(db)

    def test_an_unfinished_game_does_not_count(self, db, engine):
        _x01_match(db, "x1", [["S20"]], winner="bo")
        _elimination_match(db, "e1", ["ana", "bo"], winner="bo")
        tb_game(db, {"ana": [1, 1], "bo": [0, 0]}, rounds=2)
        game = new_game(db, players=("ana", "bo"))
        play(game, hit(20, 2))
        assert "four_course_meal" not in earned(db)
