"""The Target Battle achievements: each one with a game that earns it and one that does not."""
import random

import pytest

from breakfast.achievements import ACHIEVEMENTS, AchievementEngine, TARGET_BATTLE
from tests.test_target_battle import MISS, hit, new_game, play


@pytest.fixture
def engine(db):
    return AchievementEngine(db).attach()


def _earned(db, player="ana"):
    return {a for a, _ in ((r["achievement_id"], r["tier"]) for r in db.earned_for_player(player))}


def darts_for(points, target):
    """Darts at `target` that score exactly `points` (0 to 9) with the standard scoring."""
    kinds = {9: (3, 3, 3), 8: (3, 3, 2), 7: (3, 3, 1), 6: (3, 3), 5: (3, 2), 4: (3, 1), 3: (3,), 2: (2,), 1: (1,)}
    return [hit(target, m) for m in kinds[points]] if points else [MISS]


def game(db, scores, rounds=10, scoring="standard", targets=None, tiebreak=False, rng=None):
    """Play a game. *scores*: {player: points per round}, each turn thrown at the round's target
    as darts that score that much; a player's list may also hold ready-made throws."""
    players = list(scores)
    targets = targets or [(i % 19) + 1 for i in range(rounds)]       # 1 to 19, never 20
    g = new_game(players=players, db=db, rounds=rounds, targets=targets, scoring=scoring,
                 tiebreak=tiebreak, rng=rng)
    for r in range(rounds):
        for p in players:
            item = scores[p][r]
            play(g, *(item if isinstance(item, list) else darts_for(item, targets[r])))
    return g


class TestDefinitions:
    def test_they_belong_to_target_battle_and_only_decide_target_battle_games(self):
        mine = [a for a in ACHIEVEMENTS if a.mode == "target_battle"]
        assert len(mine) == 15 and all(a.game_modes == TARGET_BATTLE for a in mine)
        assert all(a.applies_to("Target Battle") and not a.applies_to("X01") and not a.applies_to("Elimination")
                   for a in mine)
        assert sum(1 for a in mine if a.hidden) == 5


class TestTargetAcquired:
    def test_three_darts_on_the_target_in_any_ring(self, db, engine):
        game(db, {"ana": [[hit(7, 1), hit(7, 2), hit(7, 3)]] + [0] * 2, "bo": [0] * 3}, rounds=3, targets=[7, 8, 9])
        assert "target_acquired" in _earned(db)

    def test_two_darts_are_not_enough(self, db, engine):
        game(db, {"ana": [[hit(7, 1), hit(7, 2), MISS]] + [0] * 2, "bo": [0] * 3}, rounds=3, targets=[7, 8, 9])
        assert "target_acquired" not in _earned(db)

    def test_it_counts_in_a_training_profile_too(self, db, engine):
        game(db, {"ana": [[hit(7, 1)] * 3] + [0], "bo": [0] * 2}, rounds=2, targets=[7, 8], scoring="doubles")
        assert "target_acquired" in _earned(db)


class TestNineOutOfNine:
    def test_three_triples_of_the_target_with_the_standard_scoring(self, db, engine):
        game(db, {"ana": [9] + [0] * 2, "bo": [0] * 3}, rounds=3)
        assert "nine_out_of_nine" in _earned(db)

    def test_not_with_a_training_profile_or_fewer_triples(self, db, engine):
        game(db, {"ana": [9] + [0] * 2, "bo": [0] * 3}, rounds=3, scoring="triples")
        game(db, {"ana": [8] + [0] * 2, "bo": [0] * 3}, rounds=3)
        assert "nine_out_of_nine" not in _earned(db)


class TestPointAchievements:
    def _total(self, db, per_round, **kw):
        """ana plays the given points per round against a bo who scores nothing."""
        game(db, {"ana": per_round, "bo": [0] * len(per_round)}, **kw)
        return _earned(db)

    def test_sixty_of_ninety_is_on_target_and_exactly_sixty(self, db, engine):
        earned = self._total(db, [9, 9, 9, 9, 9, 9, 6, 0, 0, 0])
        assert {"on_target", "exactly_sixty"} <= earned
        assert not ({"sharpshooter", "perfect_battle"} & earned)

    def test_fifty_nine_is_not_enough(self, db, engine):
        assert not ({"on_target", "exactly_sixty"} & self._total(db, [9, 9, 9, 9, 9, 9, 5, 0, 0, 0]))

    def test_seventy_five_is_a_sharpshooter_but_not_exactly_sixty(self, db, engine):
        earned = self._total(db, [9, 9, 9, 9, 9, 9, 9, 9, 3, 0])
        assert {"on_target", "sharpshooter"} <= earned and "exactly_sixty" not in earned

    def test_ninety_is_perfect(self, db, engine):
        assert {"on_target", "sharpshooter", "perfect_battle"} <= self._total(db, [9] * 10)

    def test_only_a_standard_game_of_ten_rounds_counts(self, db, engine):
        self._total(db, [9] * 5, rounds=5)
        self._total(db, [9] * 10, scoring="triples")
        assert not ({"on_target", "sharpshooter", "perfect_battle"} & _earned(db))

    def test_playing_alone_counts(self, db, engine):
        game(db, {"ana": [9] * 10})
        assert "perfect_battle" in _earned(db)

    def test_a_corrected_total_is_what_counts(self, db, engine):
        g = game(db, {"bo": [0] * 10, "ana": [9] * 9 + [0]})
        assert "perfect_battle" not in _earned(db)
        g.correct_turn(9)                       # ana's last turn was worth nine after all
        assert "perfect_battle" in _earned(db)

    def test_undoing_the_last_turn_takes_it_back(self, db, engine):
        g = game(db, {"ana": [9] * 10})
        assert "perfect_battle" in _earned(db)
        g.undo()
        assert "perfect_battle" not in _earned(db)


class TestNoEmptyRounds:
    def test_a_point_in_every_round(self, db, engine):
        game(db, {"ana": [1] * 10, "bo": [0] * 10})
        assert "no_empty_rounds" in _earned(db) and "no_empty_rounds" not in _earned(db, "bo")

    def test_one_empty_round_spoils_it(self, db, engine):
        game(db, {"ana": [1] * 9 + [0], "bo": [0] * 10})
        assert "no_empty_rounds" not in _earned(db)

    def test_only_in_the_standard_game(self, db, engine):
        game(db, {"ana": [1] * 5, "bo": [0] * 5}, rounds=5)
        assert "no_empty_rounds" not in _earned(db)


class TestFocusGames:
    def test_fifteen_of_thirty_with_only_doubles(self, db, engine):
        game(db, {"ana": [[hit(t, 2)] * 3 for t in range(1, 6)] + [0] * 5, "bo": [0] * 10},
             scoring="doubles", targets=list(range(1, 11)))
        assert "double_focus" in _earned(db) and "triple_focus" not in _earned(db)

    def test_fourteen_are_not_enough(self, db, engine):
        game(db, {"ana": [[hit(t, 2)] * 3 for t in range(1, 5)] + [[hit(5, 2)] * 2] + [0] * 5, "bo": [0] * 10},
             scoring="doubles", targets=list(range(1, 11)))
        assert "double_focus" not in _earned(db)

    def test_fifteen_of_thirty_with_only_triples(self, db, engine):
        game(db, {"ana": [[hit(t, 3)] * 3 for t in range(1, 6)] + [0] * 5, "bo": [0] * 10},
             scoring="triples", targets=list(range(1, 11)))
        assert "triple_focus" in _earned(db) and "double_focus" not in _earned(db)

    def test_they_need_ten_rounds_and_their_own_profile(self, db, engine):
        game(db, {"ana": [[hit(t, 2)] * 3 for t in range(1, 6)], "bo": [0] * 5}, rounds=5, scoring="doubles",
             targets=list(range(1, 6)))
        game(db, {"ana": [[hit(t, 3)] * 3 for t in range(1, 6)] + [0] * 5, "bo": [0] * 10},
             scoring="standard", targets=list(range(1, 11)))
        assert not ({"double_focus", "triple_focus"} & _earned(db))


class TestWinningAchievements:
    def test_a_win_by_exactly_one_point(self, db, engine):
        game(db, {"ana": [1] * 10 + [], "bo": [1] * 9 + [0]})
        assert "photo_finish" in _earned(db) and "photo_finish" not in _earned(db, "bo")

    def test_two_points_are_a_clear_win(self, db, engine):
        game(db, {"ana": [1] * 10, "bo": [1] * 8 + [0, 0]})
        assert "photo_finish" not in _earned(db)

    def test_a_tie_is_no_win(self, db, engine):
        game(db, {"ana": [1] * 10, "bo": [1] * 10})
        assert "photo_finish" not in _earned(db)

    def test_a_win_by_one_point_in_a_tiebreak_does_not_count(self, db, engine):
        g = game(db, {"ana": [1] * 10, "bo": [1] * 10}, tiebreak=True, rng=random.Random(3))
        play(g, hit(g.target, 1))
        play(g, MISS)
        assert g.state == "finished" and "photo_finish" not in _earned(db)

    def test_alone_there_is_nobody_to_win_against(self, db, engine):
        game(db, {"ana": [1] * 10})
        assert "photo_finish" not in _earned(db)

    def test_behind_before_the_last_round_and_ahead_after_it(self, db, engine):
        game(db, {"ana": [1] * 9 + [9], "bo": [2] * 9 + [0]})       # 18 each at the end: a tie, nobody wins
        assert "final_round_comeback" not in _earned(db)
        game(db, {"ana": [1] * 9 + [9], "bo": [1] * 8 + [2, 0]})
        assert "final_round_comeback" in _earned(db)
        assert "final_round_comeback" not in _earned(db, "bo")

    def test_not_when_tied_for_the_lead_before_the_last_round(self, db, engine):
        game(db, {"ana": [1] * 9 + [3], "bo": [1] * 9 + [0], "cy": [0] * 10})
        assert "final_round_comeback" not in _earned(db)

    def test_not_when_the_leader_keeps_winning(self, db, engine):
        game(db, {"ana": [0] * 9 + [9], "bo": [3] * 10})
        assert "final_round_comeback" not in _earned(db)


class TestHiddenOnes:
    def test_one_and_five_around_the_twenty(self, db, engine):
        game(db, {"ana": [[hit(1, 1), hit(5, 2), hit(1, 3)], 0, 0], "bo": [0] * 3}, rounds=3, targets=[20, 3, 4])
        assert "either_side_of_twenty" in _earned(db)

    def test_both_numbers_have_to_appear_and_the_target_has_to_be_twenty(self, db, engine):
        game(db, {"ana": [[hit(1, 1)] * 3, [hit(1, 1), hit(5, 1), hit(5, 2)], 0], "bo": [0] * 3},
             rounds=3, targets=[20, 19, 4])
        assert "either_side_of_twenty" not in _earned(db)

    def test_three_t20_on_another_target(self, db, engine):
        game(db, {"ana": [[hit(20, 3)] * 3, 0], "bo": [0] * 2}, rounds=2, targets=[19, 20])
        assert "wrong_maximum" in _earned(db)

    def test_not_on_target_twenty_or_with_a_training_profile(self, db, engine):
        game(db, {"ana": [[hit(20, 3)] * 3, 0], "bo": [0] * 2}, rounds=2, targets=[20, 19])
        game(db, {"ana": [[hit(20, 3)] * 3, 0], "bo": [0] * 2}, rounds=2, targets=[19, 18], scoring="triples")
        assert "wrong_maximum" not in _earned(db)

    def test_two_misses_and_then_the_triple(self, db, engine):
        game(db, {"ana": [[MISS, hit(5, 1), hit(17, 3)], 0], "bo": [0] * 2}, rounds=2, targets=[17, 3])
        assert "better_late_than_never" in _earned(db)

    def test_a_hit_in_front_of_it_spoils_it(self, db, engine):
        game(db, {"ana": [[hit(17, 1), MISS, hit(17, 3)], 0], "bo": [0] * 2}, rounds=2, targets=[17, 3])
        assert "better_late_than_never" not in _earned(db)

    def test_it_follows_the_scoring_of_the_profile(self, db, engine):
        # With only triples counting, a single on the target scores nothing either.
        game(db, {"ana": [[hit(17, 1), MISS, hit(17, 3)], 0], "bo": [0] * 2}, rounds=2, targets=[17, 3],
             scoring="triples")
        assert "better_late_than_never" in _earned(db)

    def test_they_stay_secret_until_earned(self, db, engine):
        game(db, {"ana": [9] + [0] * 9, "bo": [0] * 10})
        overview = {i["id"]: i for i in engine.overview("ana")}
        assert overview["exactly_sixty"]["names"] is None and overview["wrong_maximum"]["hidden"]


class TestExtendedBreakfast:
    def _tied_game(self, db, tiebreak_ties):
        """A game that ends level, then `tiebreak_ties` tiebreak rounds that end level again, then one
        that ana wins."""
        g = game(db, {"ana": [1] * 10, "bo": [1] * 10}, tiebreak=True, rng=random.Random(5))
        for _ in range(tiebreak_ties):
            play(g, hit(g.target, 1))
            play(g, hit(g.target, 1))
        play(g, hit(g.target, 3))
        play(g, MISS)
        assert g.state == "finished"
        return g

    def test_a_win_after_three_tiebreak_rounds(self, db, engine):
        self._tied_game(db, tiebreak_ties=2)       # the third round decides
        assert "extended_breakfast" in _earned(db) and "extended_breakfast" not in _earned(db, "bo")

    def test_two_tiebreak_rounds_are_not_enough(self, db, engine):
        self._tied_game(db, tiebreak_ties=1)
        assert "extended_breakfast" not in _earned(db)

    def test_a_win_is_needed_not_just_the_rounds(self, db, engine):
        g = game(db, {"ana": [1] * 10, "bo": [1] * 10}, tiebreak=True, rng=random.Random(5))
        for _ in range(2):
            play(g, hit(g.target, 1))
            play(g, hit(g.target, 1))
        play(g, MISS)
        play(g, hit(g.target, 3))
        assert g.state == "finished"
        assert "extended_breakfast" not in _earned(db) and "extended_breakfast" in _earned(db, "bo")


class TestOtherModesAreNotAffected:
    def test_the_general_achievements_still_count_in_target_battle(self, db, engine):
        game(db, {"ana": [9] + [0] * 2, "bo": [0] * 3}, rounds=3)
        assert "first_breakfast" in _earned(db)

    def test_an_x01_match_decides_none_of_them(self, db, engine):
        db.open_match("m1", "X01", 501)
        db.insert_turn("m1", "ana", 1, 1, 501, 60, False, False, [("T20", 60, 441)] * 1)
        db.close_match("m1")
        assert not any(a.mode == "target_battle" for a in ACHIEVEMENTS if a.id in _earned(db))
