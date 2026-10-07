"""Achievements that can be decided while a match runs are announced at once as provisional and made
final when the match closes (#44)."""
import pytest

from breakfast import achievements as ach
from breakfast.achievements import AchievementEngine
from tests.test_achievements import _earned, _elimination_match, _x01_match

DEFINITIONS = tuple(ach.BY_ID[i] for i in ("bullseye", "raising_the_bar", "last_at_the_table", "ton_up"))


@pytest.fixture
def announced():
    return []


@pytest.fixture
def engine(db, announced):
    db.set_achievements_start("2000-01-01T00:00:00")
    return AchievementEngine(db, definitions=DEFINITIONS,
                             on_earned=lambda c: announced.append((c["player"], c["achievement"]))).attach()


def _beat_the_bar(db, mid, player):
    """A regular elimination turn that passes: 60 against a bar of 40."""
    db.insert_elimination_turn(mid, player, 3, score=60, target=40, freipass=False, passed=True, lives_before=3,
                               positions=[{"field": "S20", "x": 0.3, "y": 0.2}] * 3)


class TestLive:
    def test_a_live_achievement_is_announced_when_its_turn_is_stored_and_nothing_is_stored(self, db, engine, announced):
        _x01_match(db, "m1", {"ana": [["S20", "50", "S1"]], "bo": [["S20"]]}, close=False)
        assert announced == [("ana", "bullseye")]
        assert _earned(db, "ana") == set()

    def test_it_is_not_announced_again_by_the_next_turns(self, db, engine, announced):
        _x01_match(db, "m1", {"ana": [["S20", "50", "S1"], ["S20", "S20", "S20"], ["S20", "S20", "S20"]]}, close=False)
        assert announced == [("ana", "bullseye")]

    def test_closing_the_match_stores_it_without_announcing_it_a_second_time(self, db, engine, announced):
        _x01_match(db, "m1", {"ana": [["S20", "50", "S1"]]}, close=False)
        db.close_match("m1")
        assert _earned(db, "ana") == {("bullseye", 0)}
        assert announced == [("ana", "bullseye")]

    def test_one_that_needs_the_result_comes_when_the_match_closes(self, db, engine, announced):
        _elimination_match(db, "e1", ["ana", "bo"], winner="ana", close=False)
        assert ("ana", "last_at_the_table") not in announced
        db.record_elimination_result("e1", [("ana", 1, 1), ("bo", 2, None)])
        db.set_winner("e1", "ana")
        db.close_match("e1")
        assert ("ana", "last_at_the_table") in announced
        assert ("ana", "last_at_the_table") in {(p, a) for p in ("ana",) for a, _ in _earned(db, p)}

    def test_what_was_earned_before_is_not_announced_again(self, db, engine, announced):
        _x01_match(db, "m1", {"ana": [["S20", "50", "S1"]]})
        announced.clear()
        _x01_match(db, "m2", {"ana": [["S20", "50", "S1"]]}, close=False)
        assert announced == []

    def test_counters_stay_at_the_end_of_the_match(self, db, engine, announced):
        _x01_match(db, "m1", {"ana": [["T20", "T20", "T20"]] * 6}, close=False)
        assert [a for _, a in announced] == []
        assert not any(a.live for a in ach.ACHIEVEMENTS if a.count)

    def test_a_hidden_player_earns_nothing(self, db, engine, announced):
        db.upsert_player("ana", hidden=True)
        _x01_match(db, "m1", {"ana": [["S20", "50", "S1"]], "bo": [["S20", "50", "S1"]]}, close=False)
        assert announced == [("bo", "bullseye")]

    def test_a_match_from_before_the_achievements_began_counts_nothing(self, db, engine, announced):
        db.set_achievements_start("2999-01-01T00:00:00")
        _x01_match(db, "m1", {"ana": [["S20", "50", "S1"]]}, close=False)
        assert announced == []

    def test_an_abandoned_match_stores_nothing_and_is_forgotten(self, db, engine, announced):
        _x01_match(db, "m1", {"ana": [["S20", "50", "S1"]]}, close=False)       # never closed
        assert _earned(db, "ana") == set()
        _x01_match(db, "m2", {"ana": [["S20", "50", "S1"]]}, close=False)       # the next one announces its own
        assert announced == [("ana", "bullseye"), ("ana", "bullseye")]
        assert set(engine._shown) == {"m2"}


class TestUndo:
    def test_taking_the_turn_back_forgets_it_so_it_is_announced_again(self, db, engine, announced):
        db.open_match("e1", "Elimination", 3)
        _beat_the_bar(db, "e1", "ana")
        assert announced == [("ana", "raising_the_bar")]
        db.delete_last_elimination_turn("e1", "ana")              # what an undo does
        assert announced == [("ana", "raising_the_bar")] and _earned(db, "ana") == set()
        _beat_the_bar(db, "e1", "ana")
        assert announced == [("ana", "raising_the_bar")] * 2

    def test_a_turn_still_there_is_not_announced_again_by_another_players_undo(self, db, engine, announced):
        db.open_match("e1", "Elimination", 3)
        _beat_the_bar(db, "e1", "ana")
        _beat_the_bar(db, "e1", "bo")
        db.delete_last_elimination_turn("e1", "bo")
        assert announced == [("ana", "raising_the_bar"), ("bo", "raising_the_bar")]

    def test_reopening_a_closed_match_does_not_announce_what_it_held_again(self, db, engine, announced):
        db.open_match("e1", "Elimination", 3)
        _beat_the_bar(db, "e1", "ana")
        db.record_elimination_result("e1", [("ana", 1, 1), ("bo", 2, None)])
        db.set_winner("e1", "ana")
        db.close_match("e1")
        assert ("raising_the_bar", 0) in _earned(db, "ana")
        announced.clear()
        db.delete_elimination_results("e1")                        # what undoing the winning turn does
        db.set_winner("e1", None)
        db.reopen_match("e1")
        assert announced == []
        assert ("raising_the_bar", 0) not in _earned(db, "ana")    # taken back until the match closes again
        db.record_elimination_result("e1", [("ana", 1, 1), ("bo", 2, None)])
        db.set_winner("e1", "ana")
        db.close_match("e1")
        assert ("raising_the_bar", 0) in _earned(db, "ana")
        assert announced == [("ana", "last_at_the_table")]         # only what needed the result again


class TestMarker:
    def test_only_events_are_live(self):
        assert not any(a.live and a.count for a in ach.ACHIEVEMENTS)

    def test_what_needs_the_result_or_the_whole_match_is_not_live(self):
        for aid in ("first_breakfast", "first_bite", "last_at_the_table", "untouchable", "full_house", "hat_trick",
                    "no_empty_rounds", "exactly_sixty", "photo_finish", "extended_breakfast", "friendly_to_the_end",
                    "unscathed", "four_course_meal", "streak_master", "black_belt", "dead_eye", "triple_threat"):
            assert not ach.BY_ID[aid].live, aid

    def test_the_drills_are_not_live(self):
        assert not any(a.live for a in ach.ACHIEVEMENTS if a.mode in ("field_training", "black_belt"))

    def test_a_well_known_live_one_is_marked(self):
        for aid in ("bullseye", "maximum", "raising_the_bar", "first_blood", "target_acquired", "job_done"):
            assert ach.BY_ID[aid].live, aid
