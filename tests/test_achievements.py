import pytest

from breakfast.achievements import Achievement, AchievementEngine, ELIMINATION, INNER_BULL, X01
from breakfast.stats import StatsDB


# Stand-ins for the first five achievements, so the engine is tested without the full list.
PILOT = (
    Achievement("bullseye", "general", "easy", {"en": "Bullseye", "de": "Bullseye"},
                {"en": "Hit the inner bull.", "de": "Das innere Bull treffen."},
                check=lambda ctx: any(d in INNER_BULL for t in ctx.turns for d in t.darts)),
    Achievement("ton_up", "x01", "endurance", {"en": "Ton Up", "de": "Volle Hundert"},
                {"en": "Score 100 or more in a turn.", "de": "Mindestens 100 Punkte in einer Aufnahme."},
                game_modes=X01, label="100", tiers=(1, 10, 100, 1000),
                count=lambda ctx: sum(1 for t in ctx.turns if not t.is_bust and (t.score or 0) >= 100)),
    Achievement("beast_mode", "easter_egg", "hidden", {"en": "Beast Mode", "de": "Beast Mode"},
                {"en": "Hit three S6 in one turn.", "de": "Drei S6 in einer Aufnahme treffen."},
                hidden=True, label="666",
                check=lambda ctx: any(t.darts == ("S6", "S6", "S6") for t in ctx.turns)),
    Achievement("first_bite", "x01", "easy", {"en": "First Bite", "de": "Erster Bissen"},
                {"en": "Win a match against an opponent.", "de": "Ein Spiel gegen einen Gegner gewinnen."},
                game_modes=X01, check=lambda ctx: ctx.won and len(ctx.participants) >= 2),
    Achievement("last_at_the_table", "elimination", "easy",
                {"en": "Last at the Table", "de": "Letzter am Tisch"},
                {"en": "Win an Elimination match.", "de": "Ein Elimination-Spiel gewinnen."},
                game_modes=ELIMINATION, check=lambda ctx: ctx.won),
)


@pytest.fixture
def engine(db):
    return AchievementEngine(db, definitions=PILOT).attach()


def _x01_turn(db, match, player, number, fields, bust=False):
    """A turn with the given dart fields; the score is the sum of the face values."""
    values = {"S6": 6, "S20": 20, "T20": 60, "50": 50, "BULL": 50, "S1": 1}
    darts, rem = [], 501
    for field in fields:
        darts.append((field, values[field], rem - values[field]))
        rem -= values[field]
    score = 0 if bust else sum(v for _, v, _ in darts)
    db.insert_turn(match, player, 1, number, 501, score, bust, False, darts)


def _x01_match(db, mid, turns, winner=None, close=True):
    """turns: {player: [fields per turn]}"""
    db.open_match(mid, "X01", 501)
    for player, per_turn in turns.items():
        for number, fields in enumerate(per_turn, start=1):
            _x01_turn(db, mid, player, number, fields)
    if winner:
        db.set_winner(mid, winner)
    if close:
        db.close_match(mid)


def _elimination_match(db, mid, players, winner, fields_by_player=None, close=True):
    db.open_match(mid, "Elimination", 0)
    for player in players:
        fields = (fields_by_player or {}).get(player, ["S20", "S20", "S20"])
        positions = [{"field": f, "x": 0.3, "y": 0.2} for f in fields]
        db.insert_elimination_turn(mid, player, 3, score=60, target=0, freipass=True,
                                   passed=True, lives_before=3, positions=positions)
    if close:
        db.record_elimination_result(mid, [(p, 1 if p == winner else 2, 1 if p == winner else None)
                                           for p in players])
        db.set_winner(mid, winner)
        db.close_match(mid)


def _earned(db, player):
    return {(r["achievement_id"], r["tier"]) for r in db.earned_for_player(player)}


class TestEvents:
    def test_bullseye_is_awarded_when_the_match_closes_not_before(self, db, engine):
        _x01_match(db, "m1", {"ana": [["S20", "50", "S1"]], "bo": [["S20"]]}, close=False)
        assert _earned(db, "ana") == set()
        db.close_match("m1")
        assert _earned(db, "ana") == {("bullseye", 0)}
        assert _earned(db, "bo") == set()

    def test_bull_name_from_autodarts_counts_too(self, db, engine):
        _x01_match(db, "m1", {"ana": [["BULL", "S1", "S1"]]}, winner="ana")
        assert ("bullseye", 0) in _earned(db, "ana")

    def test_beast_mode_needs_three_sixes_in_one_turn(self, db, engine):
        _x01_match(db, "m1", {"ana": [["S6", "S6", "S20"], ["S6", "S6", "S6"]],
                              "bo": [["S6", "S6", "S20"]]})
        assert ("beast_mode", 0) in _earned(db, "ana")
        assert ("beast_mode", 0) not in _earned(db, "bo")

    def test_first_bite_needs_a_win_with_an_opponent(self, db, engine):
        _x01_match(db, "solo", {"ana": [["S20", "S20", "S20"]]}, winner="ana")
        assert ("first_bite", 0) not in _earned(db, "ana")
        _x01_match(db, "duel", {"ana": [["S20"]], "bo": [["S20"]]}, winner="ana")
        assert ("first_bite", 0) in _earned(db, "ana")
        assert ("first_bite", 0) not in _earned(db, "bo")

    def test_an_event_is_awarded_once_for_the_first_match(self, db, engine):
        _x01_match(db, "m1", {"ana": [["50", "S1", "S1"]]})
        _x01_match(db, "m2", {"ana": [["50", "S1", "S1"]]})
        rows = db.earned_rows("ana", "bullseye")
        assert len(rows) == 1 and rows[0]["match_id"] == "m1"

    def test_elimination_win_earns_last_at_the_table_x01_win_does_not(self, db, engine):
        _elimination_match(db, "e1", ["ana", "bo"], winner="ana")
        assert ("last_at_the_table", 0) in _earned(db, "ana")
        assert _earned(db, "bo") == set()
        _x01_match(db, "x1", {"cy": [["S20"]], "di": [["S20"]]}, winner="cy")
        assert ("last_at_the_table", 0) not in _earned(db, "cy")

    def test_elimination_darts_come_from_recorded_positions(self, db, engine):
        _elimination_match(db, "e1", ["ana", "bo"], winner="bo",
                           fields_by_player={"ana": ["S6", "S6", "S6"], "bo": ["50", "S1", "S1"]})
        assert ("beast_mode", 0) in _earned(db, "ana")
        assert ("bullseye", 0) in _earned(db, "bo")

    def test_a_corrected_elimination_turn_does_not_count_for_hits(self, db, engine):
        _elimination_match(db, "e1", ["ana", "bo"], winner="bo",
                           fields_by_player={"ana": ["50", "S1", "S1"]}, close=False)
        db.correct_last_elimination_turn("e1", "ana", 10, False)   # the darts were misread
        db.record_elimination_result("e1", [("ana", 2, None), ("bo", 1, 1)])
        db.set_winner("e1", "bo")
        db.close_match("e1")
        assert ("bullseye", 0) not in _earned(db, "ana")


class TestTiers:
    def _ton_matches(self, db, n, player="ana", prefix="m"):
        for i in range(n):
            _x01_match(db, f"{prefix}{i}", {player: [["T20", "S20", "S20"]], "bo": [["S1"]]})

    def test_first_hundred_turn_earns_tier_one(self, db, engine):
        _x01_match(db, "m1", {"ana": [["S20", "S20", "S20"], ["T20", "S20", "S20"]]})
        assert _earned(db, "ana") == {("ton_up", 1)}

    def test_a_bust_never_counts(self, db, engine):
        db.open_match("m1", "X01", 501)
        _x01_turn(db, "m1", "ana", 1, ["T20", "T20", "T20"], bust=True)
        db.close_match("m1")
        assert ("ton_up", 1) not in _earned(db, "ana")

    def test_tiers_add_up_across_matches(self, db, engine):
        self._ton_matches(db, 9)
        assert _earned(db, "ana") == {("ton_up", 1)}
        self._ton_matches(db, 1, prefix="n")
        assert _earned(db, "ana") == {("ton_up", 1), ("ton_up", 2)}

    def test_elimination_turns_do_not_count(self, db, engine):
        _elimination_match(db, "e1", ["ana", "bo"], winner="ana")
        assert ("ton_up", 1) not in _earned(db, "ana")

    def test_reopening_a_match_takes_a_tier_back(self, db, engine):
        self._ton_matches(db, 10)
        assert ("ton_up", 2) in _earned(db, "ana")
        db.reopen_match("m3")
        assert ("ton_up", 2) not in _earned(db, "ana")
        assert ("ton_up", 1) in _earned(db, "ana")
        db.close_match("m3")
        assert ("ton_up", 2) in _earned(db, "ana")


class TestRevocation:
    def test_undoing_the_winning_turn_revokes_last_at_the_table(self, db, engine):
        _elimination_match(db, "e1", ["ana", "bo"], winner="ana")
        assert ("last_at_the_table", 0) in _earned(db, "ana")
        # What EliminationGame does when the winning turn is undone.
        db.delete_elimination_results("e1")
        db.set_winner("e1", None)
        db.reopen_match("e1")
        db.delete_last_elimination_turn("e1", "bo")
        assert _earned(db, "ana") == set()
        _elimination_match(db, "e1", [], winner="ana")   # the rematch ends the same match again
        assert ("last_at_the_table", 0) in _earned(db, "ana")

    def test_a_revoked_event_moves_to_another_match_that_still_earns_it(self, db, engine):
        _x01_match(db, "m1", {"ana": [["50", "S1", "S1"]]})
        _x01_match(db, "m2", {"ana": [["50", "S1", "S1"]]})
        assert db.earned_rows("ana", "bullseye")[0]["match_id"] == "m1"
        db.reopen_match("m1")
        rows = db.earned_rows("ana", "bullseye")
        assert len(rows) == 1 and rows[0]["match_id"] == "m2"
        db.reopen_match("m2")
        assert db.earned_rows("ana", "bullseye") == []

    def test_callbacks_report_what_changed(self, db):
        earned, revoked = [], []
        AchievementEngine(db, definitions=PILOT, on_earned=earned.append, on_revoked=revoked.append).attach()
        _elimination_match(db, "e1", ["ana", "bo"], winner="ana")
        assert {"player": "ana", "achievement": "last_at_the_table", "tier": 0} in earned
        db.reopen_match("e1")
        assert revoked == [{"player": "ana", "achievement": "last_at_the_table", "tier": 0}]

    def test_a_failing_callback_does_not_break_the_game(self, db):
        def boom(change):
            raise RuntimeError("nope")
        AchievementEngine(db, definitions=PILOT, on_earned=boom).attach()
        _elimination_match(db, "e1", ["ana", "bo"], winner="ana")
        assert ("last_at_the_table", 0) in _earned(db, "ana")


class TestScope:
    def test_hidden_players_do_not_earn_but_still_count_as_opponents(self, db, engine):
        db.upsert_player("ghost", hidden=True)
        _x01_match(db, "m1", {"ana": [["S20"]], "ghost": [["50", "S1", "S1"]]}, winner="ana")
        assert _earned(db, "ghost") == set()
        assert ("first_bite", 0) in _earned(db, "ana")

    def test_matches_before_the_start_do_not_count(self, db, engine):
        db.set_achievements_start("2999-01-01T00:00:00+00:00")
        _x01_match(db, "m1", {"ana": [["50", "S1", "S1"]], "bo": [["S20"]]}, winner="ana")
        assert _earned(db, "ana") == set()

    def test_the_start_is_set_once_and_survives_a_restart(self, tmp_path):
        path = str(tmp_path / "stats.db")
        first = StatsDB(path).achievements_start()
        assert StatsDB(path).achievements_start() == first

    def test_deleting_a_player_removes_their_achievements(self, db, engine):
        _x01_match(db, "m1", {"ana": [["50", "S1", "S1"]], "bo": [["S20"]]})
        db.delete_player("ana")
        assert db.earned_for_player("ana") == []

    def test_a_failing_listener_never_reaches_the_caller(self, db):
        def boom(match_id):
            raise RuntimeError("listener bug")
        db.on_match_changed = boom
        _x01_match(db, "m1", {"ana": [["S20"]]})           # closes the match, must not raise
        assert db.match_row("m1")["ended_at"] is not None

    def test_without_an_engine_nothing_is_evaluated(self, db):
        _x01_match(db, "m1", {"ana": [["50", "S1", "S1"]]})
        assert db.earned_for_player("ana") == []


class TestOverview:
    def _by_id(self, engine, player):
        return {i["id"]: i for i in engine.overview(player)}

    def test_lists_every_achievement_with_state(self, db, engine):
        _x01_match(db, "m1", {"ana": [["50", "S1", "S1"], ["T20", "S20", "S20"]], "bo": [["S20"]]},
                   winner="ana")
        items = self._by_id(engine, "ana")
        assert set(items) == {a.id for a in PILOT}
        assert items["bullseye"]["tier"] == 1 and items["bullseye"]["earned_at"]
        assert items["bullseye"]["tiers"] is None and items["bullseye"]["progress"] is None
        assert items["last_at_the_table"]["tier"] == 0 and items["last_at_the_table"]["earned_at"] is None

    def test_counter_reports_tier_progress_and_next_threshold(self, db, engine):
        _x01_match(db, "m1", {"ana": [["T20", "S20", "S20"]] * 3, "bo": [["S20"]]})
        item = self._by_id(engine, "ana")["ton_up"]
        assert (item["tier"], item["progress"], item["next"], item["tiers"]) == (1, 3, 10, [1, 10, 100, 1000])

    def test_counter_without_progress_has_the_first_threshold_next(self, db, engine):
        item = self._by_id(engine, "ana")["ton_up"]
        assert (item["tier"], item["progress"], item["next"]) == (0, 0, 1)

    def test_a_hidden_achievement_keeps_its_name_secret_until_earned(self, db, engine):
        before = self._by_id(engine, "ana")["beast_mode"]
        assert before["hidden"] and before["names"] is None and before["label"] is None
        assert before["descriptions"] is None
        _x01_match(db, "m1", {"ana": [["S6", "S6", "S6"]], "bo": [["S20"]]})
        after = self._by_id(engine, "ana")["beast_mode"]
        assert after["tier"] == 1 and after["names"]["en"] == "Beast Mode" and after["label"] == "666"

    def test_a_revoked_achievement_shows_as_not_earned(self, db, engine):
        _x01_match(db, "m1", {"ana": [["50", "S1", "S1"]], "bo": [["S20"]]})
        db.reopen_match("m1")
        assert self._by_id(engine, "ana")["bullseye"]["tier"] == 0

    def test_percent_is_the_share_of_players_with_a_counted_match(self, db, engine):
        _x01_match(db, "m1", {"ana": [["50", "S1", "S1"]], "bo": [["S20"]], "cy": [["S20"]]})
        percent = lambda p: self._by_id(engine, p)["bullseye"]["percent"]
        assert percent("ana") == percent("bo") == 33.3

    def test_hidden_players_and_open_matches_are_not_counted(self, db, engine):
        db.upsert_player("ghost", hidden=True)
        _x01_match(db, "m1", {"ana": [["50", "S1", "S1"]], "bo": [["S20"]], "ghost": [["S20"]]})
        _x01_match(db, "m2", {"cy": [["S20"]], "di": [["S20"]]}, close=False)
        assert self._by_id(engine, "ana")["bullseye"]["percent"] == 50.0

    def test_nobody_played_means_no_percent(self, db, engine):
        assert self._by_id(engine, "ana")["bullseye"]["percent"] is None

    def test_a_tiered_achievement_uses_the_shown_tier(self, db, engine):
        _x01_match(db, "m1", {"ana": [["T20", "S20", "S20"]] * 10, "bo": [["T20", "S20", "S20"]], "cy": [["S20"]]})
        ana, bo, cy = (self._by_id(engine, p)["ton_up"] for p in ("ana", "bo", "cy"))
        assert (ana["tier"], ana["percent"]) == (2, 33.3)    # tier 2: only ana
        assert (bo["tier"], bo["percent"]) == (1, 66.7)      # tier 1: ana and bo
        assert (cy["tier"], cy["percent"]) == (0, 66.7)      # nothing earned: the first tier

    def test_a_secret_one_has_no_percent_until_it_is_earned(self, db, engine):
        _x01_match(db, "m1", {"ana": [["S6", "S6", "S6"]], "bo": [["S20"]]})
        assert self._by_id(engine, "bo")["beast_mode"]["percent"] is None
        assert self._by_id(engine, "ana")["beast_mode"]["percent"] == 50.0
