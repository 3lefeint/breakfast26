"""The remaining X01, general and cross-game achievements: each one with a match that earns it and one that does not."""
import re

import pytest

from breakfast.achievements import AchievementEngine


@pytest.fixture
def engine(db):
    return AchievementEngine(db).attach()


def _value(field):
    if field in ("BULL", "50"):
        return 50
    if re.fullmatch(r"M\d*|MISS", field):
        return 0
    kind, number = re.match(r"^([SDT])(\d+)$", field).groups()
    return int(number) * {"S": 1, "D": 2, "T": 3}[kind]


def _earned(db, player="ana"):
    return {r["achievement_id"]: r["tier"] for r in db.earned_for_player(player)}


def throw(player, fields, before, leg=1, bust=False, at=None):
    return {"player": player, "fields": fields, "before": before, "leg": leg, "bust": bust, "at": at}


def x01(db, mid, turns, winner="ana", points_start=501, close=True):
    """Store an X01 match. A turn is a checkout when its darts take exactly what is left."""
    db.open_match(mid, "X01", points_start)
    numbers = {}
    for t in turns:
        numbers[t["player"]] = number = numbers.get(t["player"], 0) + 1
        rest, darts = t["before"], []
        for field in t["fields"]:
            rest -= _value(field)
            darts.append((field, _value(field), rest))
        total = sum(_value(f) for f in t["fields"])
        checkout = not t["bust"] and total == t["before"]
        db.insert_turn(mid, t["player"], t["leg"], number, t["before"], 0 if t["bust"] else total,
                       t["bust"], checkout, darts)
        if t["at"]:
            db._conn.execute("UPDATE turns SET created_at = ? WHERE id = (SELECT MAX(id) FROM turns)", (t["at"],))
            db._conn.commit()
    if not any(t["player"] == "bo" for t in turns):
        db.insert_turn(mid, "bo", 1, 1, 501, 20, False, False, [("S20", 20, 481)])
    if winner:
        db.set_winner(mid, winner)
    if close:
        db.close_match(mid)


def one_turn(db, fields, before=501, **kw):
    x01(db, "m1", [throw("ana", fields, before, **kw)])


class TestRegularGuest:
    def _day(self, db, n, day_no=None):
        """Match *n*, played on calendar day *day_no* (default: its own day)."""
        mid = f"d{n}"
        day_no = n if day_no is None else day_no
        x01(db, mid, [throw("ana", ["S20"], 501)])
        day = f"2031-{(day_no // 28) + 1:02d}-{(day_no % 28) + 1:02d}"
        db._conn.execute("UPDATE matches SET started_at = ?, ended_at = ? WHERE match_id = ?",
                         (f"{day}T12:00:00+00:00", f"{day}T12:30:00+00:00", mid))
        db._conn.commit()
        db.on_match_changed(mid)

    def test_thirty_different_days(self, db, engine):
        for n in range(29):
            self._day(db, n)
        assert "regular_guest" not in _earned(db)
        self._day(db, 29)
        assert "regular_guest" in _earned(db)

    def test_several_matches_on_one_day_count_once(self, db, engine):
        for n in range(30):
            self._day(db, n, day_no=n % 15)
        assert "regular_guest" not in _earned(db)

    def test_the_profile_shows_the_days_so_far(self, db, engine):
        for n in range(12):
            self._day(db, n)
        item = next(i for i in engine.overview("ana") if i["id"] == "regular_guest")
        assert item["progress"] == 12 and item["next"] == 30


class TestHeavyHitter:
    @pytest.mark.parametrize("fields, tier", [(["T20", "T20", "S20"], 1), (["T20", "T20", "D10"], 1), (["T20", "T20", "S19"], 0)])
    def test_a_turn_of_140_or_more(self, db, engine, fields, tier):
        one_turn(db, fields)
        assert _earned(db).get("heavy_hitter", 0) == tier

    def test_a_bust_does_not_count(self, db, engine):
        one_turn(db, ["T20", "T20", "T20"], before=100, bust=True)
        assert "heavy_hitter" not in _earned(db)


class TestAverageClass:
    def _match(self, db, mid, fields, turns=5):
        x01(db, mid, [throw("ana", fields, 501) for _ in range(turns)])

    def test_the_tier_is_the_best_average_of_one_match(self, db, engine):
        self._match(db, "m1", ["T20", "S20", "S20"])         # 100 per turn
        assert _earned(db)["average_class"] == 4

    def test_a_lower_average_gives_a_lower_tier(self, db, engine):
        self._match(db, "m1", ["S20", "S20", "S20"])         # 60
        assert _earned(db)["average_class"] == 2

    def test_under_five_turns_do_not_count(self, db, engine):
        self._match(db, "m1", ["T20", "T20", "T20"], turns=4)
        assert "average_class" not in _earned(db)

    def test_matches_are_not_added_up(self, db, engine):
        self._match(db, "m1", ["S20", "S10", "S10"])         # 40
        self._match(db, "m2", ["S20", "S10", "S10"])
        assert _earned(db)["average_class"] == 1
        item = next(i for i in engine.overview("ana") if i["id"] == "average_class")
        assert item["progress"] == 40 and item["next"] == 60


class TestShortOrder:
    def test_eighteen_darts(self, db, engine):
        rows = [throw("ana", ["S20", "S20", "S20"], 501 - 60 * i) for i in range(5)]
        x01(db, "m1", rows + [throw("ana", ["S20", "S20", "D20"], 80)])
        assert "short_order" in _earned(db)

    def test_nineteen_darts_are_too_many(self, db, engine):
        rows = [throw("ana", ["S20", "S20", "S20"], 501 - 60 * i) for i in range(6)]
        x01(db, "m1", rows + [throw("ana", ["D20"], 40)])
        assert "short_order" not in _earned(db)

    def test_only_a_501_game_counts(self, db, engine):
        rows = [throw("ana", ["S20", "S20", "S20"], 501 - 60 * i) for i in range(5)]
        x01(db, "m1", rows + [throw("ana", ["S20", "S20", "D20"], 80)], points_start=301)
        assert "short_order" not in _earned(db)


class TestBullseyeFinish:
    def test_the_last_dart_is_the_inner_bull(self, db, engine):
        one_turn(db, ["BULL"], before=50)
        assert "bullseye_finish" in _earned(db)

    def test_a_double_is_not_enough(self, db, engine):
        one_turn(db, ["D20"], before=40)
        assert "bullseye_finish" not in _earned(db)


class TestStreakMaster:
    def _match(self, db, mid, winner="ana"):
        x01(db, mid, [throw("ana", ["S20"], 501)], winner=winner)

    def test_three_wins_in_a_row(self, db, engine):
        self._match(db, "m1")
        self._match(db, "m2")
        assert "streak_master" not in _earned(db)
        self._match(db, "m3")
        assert "streak_master" in _earned(db)

    def test_a_loss_breaks_the_run(self, db, engine):
        self._match(db, "m1")
        self._match(db, "m2", winner="bo")
        self._match(db, "m3")
        self._match(db, "m4")
        assert "streak_master" not in _earned(db)

    def test_matches_of_another_game_do_not_count(self, db, engine):
        self._match(db, "m1")
        self._match(db, "m2")
        db.open_match("e1", "Elimination", 3)
        db.insert_elimination_turn("e1", "ana", 3, score=10, target=0, freipass=True, passed=True, lives_before=3)
        db.record_elimination_result("e1", [("ana", 2, None), ("bo", 1, 3)])
        db.set_winner("e1", "bo")
        db.close_match("e1")
        self._match(db, "m3")
        assert "streak_master" in _earned(db)


class TestClosingRoutine:
    def _legs(self, db, count):
        x01(db, "m1", [throw("ana", ["D20"], 40, leg=n) for n in range(1, count + 1)])

    def test_ten_checkouts_are_the_first_tier(self, db, engine):
        self._legs(db, 10)
        assert _earned(db)["closing_routine"] == 1

    def test_nine_are_not_enough(self, db, engine):
        self._legs(db, 9)
        assert "closing_routine" not in _earned(db)


class TestCheckoutCollector:
    DOUBLES = [(f"D{n}", 2 * n) for n in range(1, 21)]

    def test_every_double_and_the_bull(self, db, engine):
        rows = [throw("ana", [f], v, leg=i) for i, (f, v) in enumerate(self.DOUBLES + [("BULL", 50)], start=1)]
        x01(db, "m1", rows)
        assert "checkout_collector" in _earned(db)

    def test_one_missing_is_not_enough_and_progress_shows(self, db, engine):
        rows = [throw("ana", [f], v, leg=i) for i, (f, v) in enumerate(self.DOUBLES, start=1)]
        x01(db, "m1", rows)
        assert "checkout_collector" not in _earned(db)
        item = next(i for i in engine.overview("ana") if i["id"] == "checkout_collector")
        assert item["progress"] == 20 and item["next"] == 21

    def test_it_adds_up_over_matches(self, db, engine):
        x01(db, "m1", [throw("ana", [f], v, leg=i) for i, (f, v) in enumerate(self.DOUBLES, start=1)])
        x01(db, "m2", [throw("ana", ["BULL"], 50)])
        assert "checkout_collector" in _earned(db)


class TestHiddenX01:
    @pytest.mark.parametrize("fields, before, rest_ok", [
        (["S20", "S20", "S20"], 374, "roughly_pi"),
        (["S20", "S20", "S20"], 375, None),
    ])
    def test_roughly_pi(self, db, engine, fields, before, rest_ok):
        one_turn(db, fields, before=before)
        assert ("roughly_pi" in _earned(db)) == (rest_ok == "roughly_pi")

    @pytest.mark.parametrize("before, earned", [(171, True), (282, True), (393, True), (504, True), (505, False)])
    def test_repdigit(self, db, engine, before, earned):
        one_turn(db, ["S20", "S20", "S20"], before=before)
        assert ("repdigit" in _earned(db)) == earned

    def test_a_bust_does_not_leave_a_repdigit(self, db, engine):
        one_turn(db, ["S20", "S20", "S20"], before=393, bust=True)
        assert "repdigit" not in _earned(db)

    @pytest.mark.parametrize("fields, earned", [(["S1", "S1", "S1"], True), (["S1", "S1", "D1"], False)])
    def test_small_fry(self, db, engine, fields, earned):
        one_turn(db, fields)
        assert ("small_fry" in _earned(db)) == earned

    @pytest.mark.parametrize("fields, earned", [(["M5", "MISS", "M12"], True), (["M5", "MISS", "S1"], False),
                                                 (["M5", "MISS"], False)])
    def test_fasting(self, db, engine, fields, earned):
        one_turn(db, fields)
        assert ("fasting" in _earned(db)) == earned

    def test_deja_vu_two_equal_turns_in_a_row(self, db, engine):
        x01(db, "m1", [throw("ana", ["T20", "S5", "S1"], 501), throw("ana", ["T20", "S5", "S1"], 435)])
        assert "deja_vu" in _earned(db)

    def test_deja_vu_needs_the_same_order(self, db, engine):
        x01(db, "m1", [throw("ana", ["T20", "S5", "S1"], 501), throw("ana", ["S5", "T20", "S1"], 435)])
        assert "deja_vu" not in _earned(db)

    def test_deja_vu_misses_do_not_count(self, db, engine):
        x01(db, "m1", [throw("ana", ["M5", "M5", "M5"], 501), throw("ana", ["M5", "M5", "M5"], 501)])
        assert "deja_vu" not in _earned(db)

    def test_jitters_nine_darts_at_a_finishable_rest(self, db, engine):
        x01(db, "m1", [throw("ana", ["M20", "M20", "M20"], 40) for _ in range(3)], winner="bo")
        assert "case_of_the_jitters" in _earned(db)

    def test_jitters_eight_darts_are_not_enough(self, db, engine):
        x01(db, "m1", [throw("ana", ["M20", "M20", "M20"], 40) for _ in range(2)] + [throw("ana", ["M20", "M20"], 40)],
            winner="bo")
        assert "case_of_the_jitters" not in _earned(db)

    def test_jitters_the_rest_must_be_finishable(self, db, engine):
        x01(db, "m1", [throw("ana", ["M20", "M20", "M20"], 41) for _ in range(3)], winner="bo")
        assert "case_of_the_jitters" not in _earned(db)

    def test_spoilsport_finishes_while_the_opponent_is_on_a_double(self, db, engine):
        x01(db, "m1", [throw("bo", ["S20"], 52), throw("ana", ["D20"], 40)])
        assert "spoilsport" in _earned(db)

    def test_spoilsport_not_when_the_opponent_is_on_an_odd_rest(self, db, engine):
        x01(db, "m1", [throw("bo", ["S20"], 61), throw("ana", ["D20"], 40)])
        assert "spoilsport" not in _earned(db)

    def test_lonely_one_a_bust_that_leaves_one(self, db, engine):
        one_turn(db, ["S2"], before=3, bust=True)
        assert "lonely_one" in _earned(db)

    def test_lonely_one_other_busts_do_not_count(self, db, engine):
        one_turn(db, ["T20"], before=5, bust=True)
        assert "lonely_one" not in _earned(db)

    def test_answer_to_everything(self, db, engine):
        one_turn(db, ["S10", "D16"], before=42)
        assert "answer_to_everything" in _earned(db)

    def test_answer_to_everything_other_darts_do_not_count(self, db, engine):
        one_turn(db, ["S2", "D20"], before=42)
        assert "answer_to_everything" not in _earned(db)

    def test_burnt_toast(self, db, engine):
        one_turn(db, ["T20"], before=2, bust=True)
        assert "burnt_toast" in _earned(db)

    def test_burnt_toast_needs_two_left(self, db, engine):
        one_turn(db, ["T20"], before=50, bust=True)
        assert "burnt_toast" not in _earned(db)

    def test_breakfast_switch(self, db, engine):
        one_turn(db, ["T20", "S10", "D20"], before=110)
        assert "breakfast_switch" in _earned(db)

    def test_breakfast_switch_needs_the_order(self, db, engine):
        one_turn(db, ["T20", "D20", "S10"], before=110)
        assert "breakfast_switch" not in _earned(db)


class TestEarlyBirdAndNightOwl:
    def test_a_leg_won_at_half_past_five(self, db, engine):
        one_turn(db, ["D20"], before=40, at="2031-01-01T05:30:00+00:00")
        assert "early_bird" in _earned(db) and "night_owl" not in _earned(db)

    def test_a_leg_won_at_three_in_the_morning_is_both(self, db, engine):
        one_turn(db, ["D20"], before=40, at="2031-01-01T03:00:00+00:00")
        assert {"early_bird", "night_owl"} <= set(_earned(db))

    def test_a_leg_won_at_eight_is_neither(self, db, engine):
        one_turn(db, ["D20"], before=40, at="2031-01-01T08:00:00+00:00")
        assert not {"early_bird", "night_owl"} & set(_earned(db))

    def test_only_the_winner_of_the_leg_gets_it(self, db, engine):
        x01(db, "m1", [throw("ana", ["S20"], 501, at="2031-01-01T03:00:00+00:00"),
                       throw("bo", ["D20"], 40, at="2031-01-01T03:05:00+00:00")], winner="bo")
        assert not {"early_bird", "night_owl"} & set(_earned(db, "ana"))
        assert {"early_bird", "night_owl"} <= set(_earned(db, "bo"))

    def test_the_local_time_counts(self, db, engine):
        db.tz = __import__("zoneinfo").ZoneInfo("Europe/Zurich")      # UTC+1 in winter
        one_turn(db, ["D20"], before=40, at="2031-01-01T06:30:00+00:00")       # 7:30 local
        assert "early_bird" not in _earned(db)


class TestEasterEggs:
    @pytest.mark.parametrize("fields, earned", [
        (["S4", "M3", "S4"], True), (["S4", "MISS", "S4"], True), (["S4", "S5", "S4"], False), (["S4", "M3"], False)])
    def test_not_found(self, db, engine, fields, earned):
        one_turn(db, fields)
        assert ("not_found" in _earned(db)) == earned

    @pytest.mark.parametrize("fields, earned", [(["S5", "M2", "S3"], True), (["S3", "M2", "S5"], False)])
    def test_service_unavailable(self, db, engine, fields, earned):
        one_turn(db, fields)
        assert ("service_unavailable" in _earned(db)) == earned

    @pytest.mark.parametrize("fields, earned", [(["D20", "S20", "T20"], True), (["T20", "D20", "S20"], True),
                                                 (["S20", "D20", "S20"], False)])
    def test_full_english(self, db, engine, fields, earned):
        one_turn(db, fields)
        assert ("full_english" in _earned(db)) == earned

    def test_they_count_in_elimination_too(self, db, engine):
        from tests.test_achievements_elimination import match, turn as etn
        match(db, "e1", [etn("ana", 60, fields=["S4", "M3", "S4"])], players=("ana", "bo"))
        assert "not_found" in _earned(db)
