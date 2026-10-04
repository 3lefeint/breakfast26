"""The achievements beyond the first five: each one with a case that earns it and one that does not."""
import re

import pytest

from breakfast.achievements import ACHIEVEMENTS, AchievementEngine


@pytest.fixture
def engine(db):
    return AchievementEngine(db).attach()


def _value(field):
    if field in ("BULL", "50"):
        return 50
    if field == "25":
        return 25
    kind, number = re.match(r"^([SDT])(\d+)$", field).groups()
    return int(number) * {"S": 1, "D": 2, "T": 3}[kind]


def _turn(db, mid, player, number, fields, before=501, leg=1, bust=False):
    """One X01 turn. It is a checkout when the darts take exactly what is left."""
    darts, rem = [], before
    for field in fields:
        rem -= _value(field)
        darts.append((field, _value(field), rem))
    total = sum(_value(f) for f in fields)
    checkout = not bust and total == before
    db.insert_turn(mid, player, leg, number, before, 0 if bust else total, bust, checkout, darts)


def _match(db, mid, turns, winner="ana", points_start=501, close=True):
    """turns: list of (fields, kwargs) for ana, plus an opponent turn so there are two players."""
    db.open_match(mid, "X01", points_start)
    for number, item in enumerate(turns, start=1):
        fields, kwargs = item if isinstance(item, tuple) else (item, {})
        _turn(db, mid, "ana", number, fields, **kwargs)
    _turn(db, mid, "bo", 1, ["S20"])
    if winner:
        db.set_winner(mid, winner)
    if close:
        db.close_match(mid)


def _earned(db, player="ana"):
    return {(r["achievement_id"], r["tier"]) for r in db.earned_for_player(player)}


def _has(db, achievement, player="ana"):
    return any(a == achievement for a, _ in _earned(db, player))


class TestGeneral:
    def test_first_breakfast_comes_with_any_closed_match(self, db, engine):
        _match(db, "m1", [["S20"]], close=False)
        assert not _has(db, "first_breakfast")
        db.close_match("m1")
        assert _has(db, "first_breakfast") and _has(db, "first_breakfast", "bo")

    @pytest.mark.parametrize("fields, earned", [
        (["S20", "D20", "T20"], True),
        (["T5", "S5", "D5"], True),
        (["S20", "D20", "T19"], False),
        (["S20", "S20", "D20"], False),
        (["S20", "D20"], False),
    ])
    def test_shanghai(self, db, engine, fields, earned):
        _match(db, "m1", [fields])
        assert _has(db, "shanghai") == earned

    @pytest.mark.parametrize("fields, earned", [
        (["D20", "D16", "BULL"], True),
        (["D1", "D2", "D3"], True),
        (["D20", "D16", "25"], False),
        (["D20", "D16", "T20"], False),
        (["D20", "D16"], False),
    ])
    def test_triple_double(self, db, engine, fields, earned):
        _match(db, "m1", [fields])
        assert _has(db, "double_pack") == earned

    def test_maximum_needs_three_treble_twenties_and_no_bust(self, db, engine):
        _match(db, "m1", [["T20", "T20", "T19"]])
        assert not _has(db, "maximum")
        db.open_match("m2", "X01", 501)
        _turn(db, "m2", "ana", 1, ["T20", "T20", "T20"], before=150, bust=True)
        db.close_match("m2")
        assert not _has(db, "maximum")
        _match(db, "m3", [["T20", "T20", "T20"]])
        assert _has(db, "maximum")

    @pytest.mark.parametrize("fields, earned", [
        (["BULL", "BULL", "BULL"], True),
        (["50", "BULL", "50"], True),
        (["BULL", "BULL", "25"], False),
        (["BULL", "BULL"], False),
    ])
    def test_triple_bull(self, db, engine, fields, earned):
        _match(db, "m1", [fields])
        assert _has(db, "triple_bull") == earned

    def test_maximum_collector_counts_180s_in_tiers(self, db, engine):
        _match(db, "m1", [["T20", "T20", "T20"]] * 9)
        assert not _has(db, "maximum_collector")
        _match(db, "m2", [["T20", "T20", "T20"]])
        assert ("maximum_collector", 1) in _earned(db)
        db.reopen_match("m2")
        assert not _has(db, "maximum_collector")

    def test_a_hundred_served_counts_finished_matches(self, db, engine):
        for i in range(99):
            _match(db, f"m{i}", [["S20"]])
        assert not _has(db, "a_hundred_served")
        item = {i["id"]: i for i in engine.overview("ana")}["a_hundred_served"]
        assert (item["progress"], item["next"]) == (99, 100)
        _match(db, "last", [["S20"]])
        assert ("a_hundred_served", 1) in _earned(db)


class TestCheckouts:
    def test_job_done_needs_a_checkout_not_a_bust(self, db, engine):
        _match(db, "m1", [["S20", "S20", "S20"]])
        assert not _has(db, "job_done")
        _match(db, "m2", [(["D20"], {"before": 40})])
        assert _has(db, "job_done")

    def test_last_dart_finish_needs_the_third_dart(self, db, engine):
        _match(db, "m1", [(["S20", "S20", "D10"], {"before": 60})])
        assert _has(db, "last_dart_finish")
        _match(db, "m2", [(["S20", "D20"], {"before": 60})], winner=None)
        assert db.earned_rows("ana", "last_dart_finish")[0]["match_id"] == "m1"

    def test_last_dart_finish_not_with_two_darts(self, db, engine):
        _match(db, "m1", [(["S20", "D20"], {"before": 60})])
        assert _has(db, "job_done") and not _has(db, "last_dart_finish")

    def test_double_trouble_is_a_finish_on_d1(self, db, engine):
        _match(db, "m1", [(["D16"], {"before": 32})])
        assert not _has(db, "double_trouble")
        _match(db, "m2", [(["D1"], {"before": 2})])
        assert _has(db, "double_trouble")

    @pytest.mark.parametrize("before, fields, earned", [
        (120, ["T20", "S20", "D20"], True),
        (100, ["T20", "S20", "D10"], True),
        (99, ["T19", "S10", "D16"], False),
        (40, ["D20"], False),
    ])
    def test_high_finish_needs_at_least_100_left(self, db, engine, before, fields, earned):
        if sum(_value(f) for f in fields) != before:
            pytest.skip("not a checkout")
        _match(db, "m1", [(fields, {"before": before})])
        assert _has(db, "high_finish") == earned

    def test_straight_to_the_double_is_a_one_dart_checkout(self, db, engine):
        _match(db, "m1", [(["S20", "D10"], {"before": 40})])
        assert not _has(db, "straight_to_the_double")
        _match(db, "m2", [(["D20"], {"before": 40})])
        assert _has(db, "straight_to_the_double")

    @pytest.mark.parametrize("fields, earned", [
        (["T20", "T20", "BULL"], True),
        (["T20", "T20", "50"], True),
        (["T20", "T19", "BULL"], False),
    ])
    def test_big_fish_is_the_170_checkout(self, db, engine, fields, earned):
        before = sum(_value(f) for f in fields)
        _match(db, "m1", [(fields, {"before": before})])
        assert _has(db, "big_fish") == earned


class TestPerfectLeg:
    NINE = [(["T20", "T20", "T20"], {"before": 501}),
            (["T20", "T20", "T20"], {"before": 321}),
            (["T20", "T19", "D12"], {"before": 141})]

    def test_nine_darts_in_a_501_leg(self, db, engine):
        _match(db, "m1", self.NINE)
        assert _has(db, "perfect_leg")

    def test_ten_darts_are_not_enough(self, db, engine):
        turns = [self.NINE[0], self.NINE[1], (["T20", "T19", "S4"], {"before": 141}),
                 (["D12"], {"before": 24})]
        _match(db, "m1", turns)
        assert _has(db, "job_done") and not _has(db, "perfect_leg")

    def test_only_a_501_game_counts(self, db, engine):
        _match(db, "m1", [(["T20", "T20", "T20"], {"before": 301}), (["T20", "T20", "S1"], {"before": 121})],
               points_start=301)
        assert not _has(db, "perfect_leg")

    def test_a_later_leg_in_nine_darts_counts(self, db, engine):
        slow = [(["S20", "S20", "S20"], {"before": 501, "leg": 1}),
                (["T20", "T20", "T20"], {"before": 441, "leg": 1}),
                (["T20", "T20", "T20"], {"before": 261, "leg": 1}),
                (["T20", "T20", "T20"], {"before": 81, "leg": 1}),
                (["T20", "S1"], {"before": 21, "leg": 1})]
        fast = [(f, dict(kw, leg=2)) for f, kw in self.NINE]
        _match(db, "m1", slow + fast)
        assert _has(db, "perfect_leg")


class TestDefinitionsAndSharedMotif:
    def test_maximum_collector_shares_the_motif_of_maximum(self, db, engine):
        items = {i["id"]: i for i in engine.overview("ana")}
        assert items["maximum_collector"]["motif"] == "maximum"
        assert items["maximum"]["motif"] == "maximum"
        note = engine.notification({"player": "ana", "achievement": "maximum_collector", "tier": 2})
        assert note["motif"] == "maximum"

    def test_all_x01_achievements_ignore_elimination_matches(self, db, engine):
        x01_ids = {a.id for a in ACHIEVEMENTS if a.game_modes == "x01"}
        assert {"job_done", "perfect_leg", "big_fish"} <= x01_ids
        db.open_match("e1", "Elimination", 0)
        db.insert_elimination_turn("e1", "ana", 3, score=60, target=0, freipass=True, passed=True, lives_before=3)
        db.insert_elimination_turn("e1", "bo", 3, score=10, target=60, freipass=False, passed=False, lives_before=3)
        db.record_elimination_result("e1", [("ana", 1, 3), ("bo", 2, None)])
        db.set_winner("e1", "ana")
        db.close_match("e1")
        assert _earned(db) == {("first_breakfast", 0), ("last_at_the_table", 0)}
