"""The Elimination achievements: each one with a match that earns it and one that does not."""
import pytest

from breakfast.achievements import ACHIEVEMENTS, ELIMINATION, AchievementEngine


@pytest.fixture
def engine(db):
    return AchievementEngine(db).attach()


def _earned(db, player="ana"):
    return {r["achievement_id"] for r in db.earned_for_player(player)}


def turn(player, score, to_beat=None, lives=3, fields=None):
    """One turn. *to_beat* None is a freipass turn (any score above 0 passes), else the score it had to beat."""
    freipass = to_beat is None
    passed = score > (0 if freipass else to_beat)
    return {"player": player, "score": score, "to_beat": 0 if freipass else to_beat,
            "freipass": freipass, "passed": passed, "lives": lives, "fields": fields or ["S20"] * 3}


def match(db, mid, turns, players=("ana", "bo", "cy"), winner="ana", lives=3, lives_left=None, close=True):
    """Store an Elimination match from its turns (in the order played) and, when *close*, its result."""
    db.open_match(mid, "Elimination", lives)
    for t in turns:
        db.insert_elimination_turn(mid, t["player"], 3, score=t["score"], target=t["to_beat"],
                                   freipass=t["freipass"], passed=t["passed"], lives_before=t["lives"],
                                   positions=[{"field": f, "x": 0.3, "y": 0.2} for f in t["fields"]])
    if close:
        left = lives if lives_left is None else lives_left
        db.record_elimination_result(mid, [(p, 1 if p == winner else 2, left if p == winner else None)
                                           for p in players])
        db.set_winner(mid, winner)
        db.close_match(mid)


class TestDefinitions:
    def test_they_belong_to_elimination_and_only_decide_elimination_matches(self):
        mine = [a for a in ACHIEVEMENTS if a.mode == "elimination"]
        assert len(mine) == 19 and all(a.game_modes == ELIMINATION for a in mine)
        assert all(a.applies_to("Elimination") and not a.applies_to("X01") and not a.applies_to("Target Battle")
                   for a in mine)
        assert sum(1 for a in mine if a.hidden) == 8


class TestRaisingTheBar:
    def test_a_regular_turn_that_passes(self, db, engine):
        match(db, "m1", [turn("bo", 50), turn("ana", 60, to_beat=50)])
        assert "raising_the_bar" in _earned(db)

    def test_a_freipass_turn_does_not_count(self, db, engine):
        match(db, "m1", [turn("ana", 60), turn("bo", 50, to_beat=60)])
        assert "raising_the_bar" not in _earned(db)

    def test_a_regular_turn_that_fails_does_not_count(self, db, engine):
        match(db, "m1", [turn("bo", 50), turn("ana", 50, to_beat=50)])
        assert "raising_the_bar" not in _earned(db)


class TestOneIsEnough:
    def test_exactly_one_point_more(self, db, engine):
        match(db, "m1", [turn("bo", 50), turn("ana", 51, to_beat=50)])
        assert "one_is_enough" in _earned(db)

    def test_more_than_one_point_is_not_exact(self, db, engine):
        match(db, "m1", [turn("bo", 50), turn("ana", 52, to_beat=50)])
        assert "one_is_enough" not in _earned(db)

    def test_a_freipass_of_one_point_does_not_count(self, db, engine):
        match(db, "m1", [turn("ana", 1)])
        assert "one_is_enough" not in _earned(db)


class TestSecondChance:
    def test_a_regular_pass_right_after_losing_a_life(self, db, engine):
        match(db, "m1", [turn("ana", 10, to_beat=50), turn("bo", 70, to_beat=10), turn("ana", 80, to_beat=70, lives=2)])
        assert "second_chance" in _earned(db)

    def test_a_second_failure_does_not_count(self, db, engine):
        match(db, "m1", [turn("ana", 10, to_beat=50), turn("ana", 10, to_beat=70, lives=2)])
        assert "second_chance" not in _earned(db)

    def test_a_freipass_turn_after_the_loss_does_not_count(self, db, engine):
        match(db, "m1", [turn("ana", 10, to_beat=50), turn("ana", 40, lives=2)])
        assert "second_chance" not in _earned(db)

    def test_another_players_turn_in_between_does_not_matter_but_a_pass_without_a_loss_does_not_count(self, db, engine):
        match(db, "m1", [turn("ana", 60, to_beat=50), turn("ana", 70, to_beat=60)])
        assert "second_chance" not in _earned(db)


class TestLastLifeStanding:
    def test_win_with_one_of_three_lives_left(self, db, engine):
        match(db, "m1", [turn("ana", 60)], lives=3, lives_left=1)
        assert "last_life_standing" in _earned(db)

    def test_two_lives_left_is_not_enough(self, db, engine):
        match(db, "m1", [turn("ana", 60)], lives=3, lives_left=2)
        assert "last_life_standing" not in _earned(db)

    def test_a_single_life_game_does_not_count(self, db, engine):
        match(db, "m1", [turn("ana", 60, lives=1)], lives=1, lives_left=1)
        assert "last_life_standing" not in _earned(db)

    def test_losing_does_not_count(self, db, engine):
        match(db, "m1", [turn("ana", 60)], winner="bo", lives=3, lives_left=1)
        assert "last_life_standing" not in _earned(db)


def _three_regular(player="ana"):
    return [turn(player, 60), turn(player, 70, to_beat=60), turn(player, 80, to_beat=70), turn(player, 90, to_beat=80)]


class TestUntouchable:
    def test_win_without_losing_a_life_after_three_regular_turns(self, db, engine):
        match(db, "m1", _three_regular(), lives=3, lives_left=3)
        assert "untouchable" in _earned(db)

    def test_a_lost_life_spoils_it(self, db, engine):
        match(db, "m1", _three_regular(), lives=3, lives_left=2)
        assert "untouchable" not in _earned(db)

    def test_two_regular_turns_are_not_enough(self, db, engine):
        match(db, "m1", _three_regular()[:3], lives=3, lives_left=3)
        assert "untouchable" not in _earned(db)

    def test_two_players_are_not_enough(self, db, engine):
        match(db, "m1", _three_regular(), players=("ana", "bo"), lives=3, lives_left=3)
        assert "untouchable" not in _earned(db)


class TestFullHouse:
    @staticmethod
    def _big_match(db, count, winner="ana"):
        players = ("ana", "b", "c", "d", "e", "f")[:count]
        match(db, "m1", [turn(p, 60) for p in players], players=players, winner=winner)

    def test_win_with_six_players(self, db, engine):
        self._big_match(db, 6)
        assert "full_house" in _earned(db)

    def test_five_players_are_not_enough(self, db, engine):
        self._big_match(db, 5)
        assert "full_house" not in _earned(db)

    def test_losing_a_big_match_does_not_count(self, db, engine):
        self._big_match(db, 6, winner="b")
        assert "full_house" not in _earned(db)


class TestHatTrick:
    def _win(self, db, mid, winner="ana", players=("ana", "bo", "cy")):
        match(db, mid, [turn(p, 60) for p in players], players=players, winner=winner)

    def test_three_wins_in_a_row(self, db, engine):
        for mid in ("m1", "m2"):
            self._win(db, mid)
        assert "hat_trick" not in _earned(db)
        self._win(db, "m3")
        assert "hat_trick" in _earned(db)

    def test_a_loss_breaks_the_run(self, db, engine):
        self._win(db, "m1")
        self._win(db, "m2", winner="bo")
        self._win(db, "m3")
        self._win(db, "m4")
        assert "hat_trick" not in _earned(db)

    def test_a_two_player_match_neither_counts_nor_breaks(self, db, engine):
        self._win(db, "m1")
        self._win(db, "m2", winner="bo", players=("ana", "bo"))
        self._win(db, "m3")
        self._win(db, "m4")
        assert "hat_trick" in _earned(db)

    def test_it_is_taken_back_when_the_third_win_is_undone(self, db, engine):
        for mid in ("m1", "m2", "m3"):
            self._win(db, mid)
        assert "hat_trick" in _earned(db)
        db.reopen_match("m3")
        assert "hat_trick" not in _earned(db)


class TestNoFreeRide:
    def test_five_regular_passes_in_a_row(self, db, engine):
        bar = [turn("ana", 10 + i * 10, to_beat=i * 10) for i in range(1, 6)]
        match(db, "m1", [turn("bo", 10)] + bar)
        assert "no_free_ride" in _earned(db)

    def test_four_are_not_enough(self, db, engine):
        bar = [turn("ana", 10 + i * 10, to_beat=i * 10) for i in range(1, 5)]
        match(db, "m1", [turn("bo", 10)] + bar)
        assert "no_free_ride" not in _earned(db)

    def test_a_freipass_turn_breaks_the_run(self, db, engine):
        bar = [turn("ana", 10 + i * 10, to_beat=i * 10) for i in range(1, 6)]
        bar[2] = turn("ana", 40)
        match(db, "m1", bar)
        assert "no_free_ride" not in _earned(db)

    def test_a_failed_turn_breaks_the_run(self, db, engine):
        bar = [turn("ana", 10 + i * 10, to_beat=i * 10) for i in range(1, 6)]
        bar[2] = turn("ana", 10, to_beat=40)
        match(db, "m1", bar)
        assert "no_free_ride" not in _earned(db)


class TestMaximumBeaten:
    def test_180_over_179(self, db, engine):
        match(db, "m1", [turn("bo", 179), turn("ana", 180, to_beat=179)])
        assert "maximum_beaten" in _earned(db)

    def test_180_over_something_lower_is_not_enough(self, db, engine):
        match(db, "m1", [turn("bo", 100), turn("ana", 180, to_beat=100)])
        assert "maximum_beaten" not in _earned(db)

    def test_a_freipass_180_does_not_count(self, db, engine):
        match(db, "m1", [turn("ana", 180)])
        assert "maximum_beaten" not in _earned(db)


class TestBackFromTheBrink:
    def _comeback(self, extra_regular):
        """ana falls to one life, then passes `extra_regular` regular turns."""
        turns = [turn("ana", 10, to_beat=50), turn("ana", 10, to_beat=70, lives=2)]
        turns += [turn("ana", 100 + i, to_beat=99 + i, lives=1) for i in range(extra_regular)]
        return turns

    def test_win_after_three_regular_turns_on_the_last_life(self, db, engine):
        match(db, "m1", self._comeback(3), lives=3, lives_left=1)
        assert "back_from_the_brink" in _earned(db)

    def test_two_regular_turns_are_not_enough(self, db, engine):
        match(db, "m1", self._comeback(2), lives=3, lives_left=1)
        assert "back_from_the_brink" not in _earned(db)

    def test_never_at_one_life_does_not_count(self, db, engine):
        match(db, "m1", [turn("ana", 100 + i, to_beat=99 + i) for i in range(4)], lives=3, lives_left=3)
        assert "back_from_the_brink" not in _earned(db)

    def test_losing_does_not_count(self, db, engine):
        match(db, "m1", self._comeback(3), winner="bo", lives=3, lives_left=1)
        assert "back_from_the_brink" not in _earned(db)

    def test_two_start_lives_do_not_count(self, db, engine):
        turns = [turn("ana", 10, to_beat=50, lives=2)] + [turn("ana", 100 + i, to_beat=99 + i, lives=1) for i in range(3)]
        match(db, "m1", turns, lives=2, lives_left=1)
        assert "back_from_the_brink" not in _earned(db)


class TestHiddenElimination:
    def test_copying_costs_needs_the_exact_bar_without_a_freipass(self, db, engine):
        match(db, "m1", [turn("bo", 50), turn("ana", 50, to_beat=50)], winner="bo")
        assert "copying_costs" in _earned(db)

    def test_copying_costs_not_with_a_lower_or_higher_score(self, db, engine):
        match(db, "m1", [turn("bo", 50), turn("ana", 49, to_beat=50), turn("cy", 60, to_beat=49)])
        assert "copying_costs" not in _earned(db)

    def test_a_new_low_is_earned_by_both_players(self, db, engine):
        match(db, "m1", [turn("cy", 100), turn("ana", 80, to_beat=100), turn("bo", 60, to_beat=80)])
        assert "a_new_low" in _earned(db, "ana") and "a_new_low" in _earned(db, "bo")
        assert "a_new_low" not in _earned(db, "cy")

    def test_a_new_low_needs_the_second_player_below_the_new_bar(self, db, engine):
        match(db, "m1", [turn("cy", 100), turn("ana", 80, to_beat=100), turn("bo", 90, to_beat=80)])
        assert "a_new_low" not in _earned(db, "ana")

    def test_a_new_low_not_when_a_freipass_follows(self, db, engine):
        match(db, "m1", [turn("cy", 100), turn("ana", 80, to_beat=100, lives=1), turn("bo", 60)])
        assert "a_new_low" not in _earned(db, "ana")

    def test_free_pass_failed(self, db, engine):
        match(db, "m1", [turn("ana", 0), turn("bo", 10, to_beat=0)])
        assert "free_pass_failed" in _earned(db)

    def test_one_crumb_is_enough_needs_exactly_one_point(self, db, engine):
        match(db, "m1", [turn("ana", 1), turn("bo", 2, to_beat=1)])
        assert "one_crumb_is_enough" in _earned(db)

    def test_one_crumb_is_enough_not_with_two_points(self, db, engine):
        match(db, "m1", [turn("ana", 2), turn("bo", 3, to_beat=2)])
        assert "one_crumb_is_enough" not in _earned(db)

    def test_tied_to_the_grave_on_the_last_life(self, db, engine):
        match(db, "m1", [turn("bo", 50), turn("ana", 50, to_beat=50, lives=1)], winner="bo")
        assert "tied_to_the_grave" in _earned(db)

    def test_tied_to_the_grave_not_with_lives_left(self, db, engine):
        match(db, "m1", [turn("bo", 50), turn("ana", 50, to_beat=50, lives=2)], winner="bo")
        assert "tied_to_the_grave" not in _earned(db)

    def test_after_me_the_deluge_needs_the_next_player_to_lose_a_life(self, db, engine):
        match(db, "m1", [turn("ana", 180), turn("bo", 60, to_beat=180)])
        assert "after_me_the_deluge" in _earned(db)

    def test_after_me_the_deluge_not_with_a_lower_score(self, db, engine):
        match(db, "m1", [turn("ana", 179), turn("bo", 60, to_beat=179)])
        assert "after_me_the_deluge" not in _earned(db)

    def test_chips_for_breakfast_with_any_order(self, db, engine):
        match(db, "m1", [turn("bo", 20), turn("ana", 26, to_beat=20, fields=["S1", "S20", "S5"])])
        assert "chips_for_breakfast" in _earned(db)

    def test_chips_for_breakfast_must_beat_the_bar(self, db, engine):
        match(db, "m1", [turn("bo", 30), turn("ana", 26, to_beat=30, fields=["S1", "S20", "S5"])], winner="bo")
        assert "chips_for_breakfast" not in _earned(db)

    def test_chips_for_breakfast_other_darts_do_not_count(self, db, engine):
        match(db, "m1", [turn("bo", 20), turn("ana", 26, to_beat=20, fields=["S1", "S20", "D2.5"])])
        assert "chips_for_breakfast" not in _earned(db)

    def test_close_still_costs(self, db, engine):
        match(db, "m1", [turn("bo", 50), turn("ana", 49, to_beat=50)], winner="bo")
        assert "close_still_costs" in _earned(db)

    def test_close_still_costs_not_two_below(self, db, engine):
        match(db, "m1", [turn("bo", 50), turn("ana", 48, to_beat=50)], winner="bo")
        assert "close_still_costs" not in _earned(db)
