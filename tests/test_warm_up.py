import pytest
from starlette.testclient import TestClient

from breakfast.black_belt import BlackBeltController
from breakfast.elimination import EliminationController
from breakfast.field_training import FieldTrainingController
from breakfast.stats import StatsDB, StatsTracker
from breakfast.warm_up import (KINDS, STEPS, Progress, WarmUpController, WarmUpGame, fields_for, is_hit, normalize_kinds, series,
                               single_ring, slowest, station_totals)
from breakfast.web import server
from tests.test_target_battle import FakeMqttClient, FakeMqttPub, MISS, play

BULL = {"segment": {"name": "25", "number": 25, "multiplier": 1}, "coords": {"x": 0.05, "y": 0.02}}
EYE = {"segment": {"name": "50", "number": 25, "multiplier": 2}, "coords": {"x": 0.02, "y": 0.01}}


def at(number, multiplier, radius_mm, bed=None):
    """A dart of a field at a distance from the center (straight up), as the board reports it."""
    seg = {"name": {1: "S", 2: "D", 3: "T"}[multiplier] + str(number), "number": number, "multiplier": multiplier}
    if bed:
        seg["bed"] = bed
    return {"segment": seg, "coords": {"x": 0.0, "y": radius_mm / 170}}


def big(n):
    return at(n, 1, 135)           # between the triple ring and the double ring


def small(n):
    return at(n, 1, 60)            # between the bull and the triple ring


def double(n):
    return at(n, 2, 165)


def triple(n):
    return at(n, 3, 103)


def new_game(db=None):
    game = WarmUpGame("ana", FakeMqttClient(), "autodarts", stats_db=db)
    game.announce_start()
    return game


@pytest.fixture
def db(tmp_path):
    return StatsDB(str(tmp_path / "s.db"))


def everything():
    """The darts that clear the whole series with one dart per field."""
    darts = []
    for kind, number, _ in STEPS:
        darts.append({"big": big, "small": small, "double": double, "triple": triple}.get(kind, lambda n: BULL if n == 25 else EYE)(number))
    return darts


class TestSeries:
    def test_eight_stations_in_the_order_of_the_ticket(self):
        steps = series()
        assert len(steps) == 84
        assert [k for k, _, _ in steps[:2]] == ["big", "big"] and steps[19] == ("big", 20, 0)
        assert steps[20] == ("bull", 25, 1) and steps[21] == ("small", 1, 2) and steps[40] == ("small", 20, 2)
        assert steps[41] == ("bull", 25, 3) and steps[42] == ("double", 1, 4) and steps[61] == ("double", 20, 4)
        assert steps[62] == ("bull", 25, 5) and steps[63] == ("triple", 1, 6) and steps[82] == ("triple", 20, 6)
        assert steps[83] == ("eye", 50, 7)

    def test_the_setup_lists_the_kinds_in_its_own_order(self):
        assert KINDS == ("big", "small", "double", "triple", "bull", "eye")


class TestKinds:
    def test_none_is_all_and_the_order_is_the_one_of_the_series(self):
        assert normalize_kinds(None) == list(KINDS) and normalize_kinds([]) == list(KINDS)
        assert normalize_kinds(["triple", "big"]) == ["big", "triple"]

    def test_an_unknown_kind_is_refused(self):
        with pytest.raises(ValueError):
            normalize_kinds(["big", "nonsense"])

    def test_only_the_picked_fields_are_in_the_run_in_the_order_of_the_series(self):
        fields = fields_for(["triple", "big"])
        assert len(fields) == 40 and fields[0] == (0, "big", 1, 0) and fields[19] == (19, "big", 20, 0)
        assert fields[20] == (63, "triple", 1, 6) and fields[39] == (82, "triple", 20, 6)

    def test_all_the_kinds_are_the_whole_series(self):
        assert [(k, n, st) for _, k, n, st in fields_for(None)] == STEPS
        assert [f[0] for f in fields_for(list(KINDS))] == list(range(84))

    def test_the_bull_is_thrown_between_the_picked_stations_and_the_eye_comes_last(self):
        def order(kinds):
            seen = []
            for _, kind, _, station in fields_for(kinds):
                if not seen or seen[-1][1] != station:
                    seen.append((kind, station))
            return [kind for kind, _ in seen]
        assert order(["small", "bull", "triple"]) == ["small", "bull", "triple"]
        assert order(["triple", "bull", "double"]) == ["double", "bull", "triple"]
        assert order(["small", "double", "bull"]) == ["small", "bull", "double"]
        assert order(["big", "small", "double", "bull"]) == ["big", "bull", "small", "bull", "double"]
        assert order(["big", "small", "double", "triple", "bull", "eye"]) == [
            "big", "bull", "small", "bull", "double", "bull", "triple", "eye"]
        assert order(["eye", "big"]) == ["big", "eye"]

    def test_a_station_picked_alone_is_followed_by_the_bull_and_a_bull_alone_is_thrown_once(self):
        assert [f[1] for f in fields_for(["triple", "bull"])][-1] == "bull" and len(fields_for(["triple", "bull"])) == 21
        assert [f[1] for f in fields_for(["big", "bull"])][-1] == "bull"
        assert fields_for(["bull"]) == [(20, "bull", 25, 1)]
        assert fields_for(["bull", "eye"]) == [(20, "bull", 25, 1), (83, "eye", 50, 7)]
        assert fields_for(["eye"]) == [(83, "eye", 50, 7)]

    def test_every_field_of_a_run_has_its_own_place_in_the_series(self):
        for kinds in (None, ["small", "double", "bull"], ["bull", "eye"], ["triple", "bull", "eye"]):
            indexes = [f[0] for f in fields_for(kinds)]
            assert len(indexes) == len(set(indexes))


class TestHits:
    def test_the_big_and_the_small_single_are_told_apart_by_the_position(self):
        assert is_hit(big(7), ("big", 7, 0)) and not is_hit(small(7), ("big", 7, 0))
        assert is_hit(small(7), ("small", 7, 2)) and not is_hit(big(7), ("small", 7, 2))

    def test_the_bed_the_board_names_decides_before_the_position(self):
        inner = at(7, 1, 135, bed="SingleInner")
        assert single_ring(inner) == "inner" and is_hit(inner, ("small", 7, 2))
        assert single_ring(at(7, 1, 60, bed="SingleOuter")) == "outer"

    def test_a_single_without_a_position_sits_where_its_field_center_is_in_the_big_single(self):
        no_position = {"segment": {"number": 7, "multiplier": 1}}
        assert is_hit(no_position, ("big", 7, 0)) and not is_hit(no_position, ("small", 7, 2))

    def test_another_number_or_ring_is_no_hit(self):
        assert not is_hit(big(8), ("big", 7, 0))
        assert not is_hit(double(7), ("big", 7, 0)) and not is_hit(triple(7), ("small", 7, 2))
        assert not is_hit(MISS, ("big", 7, 0))

    def test_doubles_and_triples(self):
        assert is_hit(double(5), ("double", 5, 4)) and not is_hit(triple(5), ("double", 5, 4))
        assert is_hit(triple(5), ("triple", 5, 6)) and not is_hit(double(5), ("triple", 5, 6))

    def test_the_bull_takes_the_outer_bull_and_the_bulls_eye_but_the_eye_only_the_eye(self):
        assert is_hit(BULL, ("bull", 25, 1)) and is_hit(EYE, ("bull", 25, 1))
        assert is_hit(EYE, ("eye", 50, 5)) and not is_hit(BULL, ("eye", 50, 5))


class TestProgress:
    def test_a_hit_moves_on_also_for_the_darts_left_in_the_turn(self):
        p = Progress()
        records = p.play([big(1), big(2), MISS])
        assert [(r["number"], r["hit"]) for r in records] == [(1, True), (2, True), (3, False)]
        assert p.pos == 2 and p.target == {"kind": "big", "number": 3, "station": 0}

    def test_there_is_no_limit_of_darts_per_field(self):
        p = Progress()
        for _ in range(10):
            p.play([MISS, MISS, MISS])
        assert p.pos == 0 and p.per_step[0] == 30
        p.play([big(1)])
        assert p.pos == 1 and p.per_step[0] == 31

    def test_the_darts_per_field_include_the_hit(self):
        p = Progress()
        p.play([MISS, big(1), small(2), big(2)])
        assert p.per_step[:3] == [2, 2, 0] and p.pos == 2

    def test_everything_hit_ends_the_run_and_later_darts_are_not_counted(self):
        p = Progress()
        records = p.play(everything() + [MISS, MISS])
        assert p.done and len(records) == 84 and sum(p.per_step) == 84

    def test_the_stations_and_the_slowest_fields(self):
        p = Progress()
        p.play([MISS, MISS, big(1), big(2)])
        p.play([MISS, big(3)])
        totals = station_totals(p.fields, p.per_step)
        assert (totals[0]["kind"], totals[0]["fields"], totals[0]["darts"]) == ("big", 20, 6) and len(totals) == 8
        assert [(s["kind"], s["number"], s["darts"]) for s in slowest(p.fields, p.per_step)] == [("big", 1, 3), ("big", 3, 2)]


class TestPickedStations:
    def test_the_progress_goes_from_the_last_big_single_to_the_first_triple(self):
        p = Progress(["big", "triple"])
        records = p.play([big(n) for n in range(1, 21)] + [triple(1)])
        assert p.pos == 21 and p.target == {"kind": "triple", "number": 2, "station": 6}
        assert [r["step"] for r in records][-2:] == [19, 63]            # the place in the full series

    def test_the_run_is_complete_when_every_picked_field_is_hit(self):
        p = Progress(["big", "triple"])
        p.play([big(n) for n in range(1, 21)] + [triple(n) for n in range(1, 21)] + [MISS])
        assert p.done and sum(p.per_step) == 40

    def test_the_snapshot_lists_only_the_picked_stations(self):
        game = WarmUpGame("ana", FakeMqttClient(), "autodarts", kinds=["triple", "big"])
        game.announce_start()
        s = game.snapshot()
        assert s["kinds"] == ["big", "triple"] and s["all"] is False and len(s["steps"]) == 40
        assert [(x["index"], x["kind"]) for x in s["stations"]] == [(0, "big"), (6, "triple")]
        assert s["setup"] == {"player": "ana", "stations": ["big", "triple"]}

    def test_a_run_over_the_picked_stations_finishes_with_its_own_totals(self, db):
        game = WarmUpGame("ana", FakeMqttClient(), "autodarts", kinds=["big", "triple"], stats_db=db)
        game.announce_start()
        darts = [big(n) for n in range(1, 21)] + [triple(n) for n in range(1, 21)]
        for i in range(0, 40, 3):
            play(game, *darts[i:i + 3])
        r = game.snapshot()["result"]
        assert r["complete"] is True and r["darts"] == 40 and r["fields"] == 40
        assert [(x["kind"], x["fields"], x["darts"]) for x in r["stations"]] == [("big", 20, 20), ("triple", 20, 20)]

    def test_all_the_darts_of_the_full_series_still_clear_a_full_run(self):
        p = Progress(None)
        p.play(everything())
        assert p.done and len(p.per_step) == 84


class TestGame:
    def test_the_state_follows_the_darts_of_the_turn_live(self):
        game = new_game()
        game.on_board_state(1, [big(1)])
        s = game.snapshot()
        assert (s["position"], s["target"]["number"], s["thrown"], s["turn"]) == (1, 2, 1, 1)
        assert s["current_darts"] == [{"kind": "big", "number": 1, "hit": True}]
        assert s["steps"][0] == ["big", 1, 0] and len(s["steps"]) == 84

    def test_a_turn_is_counted_when_the_darts_are_pulled(self):
        game = new_game()
        play(game, big(1), MISS, MISS)
        s = game.snapshot()
        assert (s["position"], s["thrown"], s["turn"]) == (1, 3, 2)
        assert s["per_step"][:2] == [1, 2]

    def test_the_whole_series_finishes_the_run(self, db):
        game = new_game(db)
        darts = everything()
        for i in range(0, len(darts), 3):
            play(game, *darts[i:i + 3])
        s = game.snapshot()
        assert s["state"] == "finished" and s["result"]["complete"] is True
        assert s["result"]["darts"] == 84 and s["result"]["fields"] == 84
        assert [x["darts"] for x in s["result"]["stations"]] == [20, 1, 20, 1, 20, 1, 20, 1]
        assert db._conn.execute("SELECT complete FROM warm_up_games").fetchone()[0] == 1

    def test_finishing_early_keeps_the_darts_thrown(self, db):
        game = new_game(db)
        play(game, big(1), MISS, MISS)
        game.on_board_state(1, [big(2)])           # an unfinished turn is not counted
        assert game.finish_early() is True
        r = game.snapshot()["result"]
        assert (r["complete"], r["fields"], r["darts"]) == (False, 1, 3)
        assert db._conn.execute("SELECT ended_at FROM matches").fetchone()[0]
        assert db._conn.execute("SELECT complete FROM warm_up_games").fetchone()[0] == 0

    def test_finishing_without_a_dart_keeps_nothing(self):
        assert new_game().finish_early() is False

    def test_a_dart_corrected_by_pressing_a_spot_is_told_by_that_spot(self):
        game = new_game()
        game.on_board_state(1, [MISS])
        game.correct_current_dart(0, "S1", {"x": 0.0, "y": 135 / 170})         # the big single
        game.on_board_state(0, [])
        assert game.snapshot()["position"] == 1
        game.on_board_state(1, [MISS])
        game.correct_current_dart(0, "S1", {"x": 0.0, "y": 60 / 170})          # a small single is no hit at the big 2
        game.on_board_state(0, [])
        assert game.snapshot()["position"] == 1

    def test_a_field_without_a_spot_counts_as_the_big_single(self):
        game = new_game()
        game.on_board_state(1, [MISS])
        game.correct_current_dart(0, "S1")
        game.on_board_state(0, [])
        assert game.snapshot()["position"] == 1

    def test_undo_walks_back_a_turn_and_reopens_a_finished_run(self, db):
        game = new_game(db)
        play(game, big(1), big(2), big(3))
        play(game, big(4), MISS, MISS)
        game.finish_early()
        assert game.undo() is True and game.state == "playing"
        assert db._conn.execute("SELECT ended_at FROM matches").fetchone()[0] is None
        assert game.snapshot()["thrown"] == 3
        assert game.undo() is True and game.snapshot()["thrown"] == 0
        assert db._conn.execute("SELECT COUNT(*) FROM warm_up_darts").fetchone()[0] == 0
        assert db._conn.execute("SELECT COUNT(*) FROM dart_positions").fetchone()[0] == 0
        assert game.undo() is False

    def test_a_player_is_needed(self):
        with pytest.raises(ValueError):
            WarmUpGame(" ", FakeMqttClient(), "autodarts")

    def test_the_controller_reads_the_mqtt_command(self, db):
        pub = FakeMqttPub()
        ctrl = WarmUpController(pub, "autodarts", stats_db=db)
        pub.subscribed["autodarts/warm_up/command"]('{"action": "start", "player": "bo", "stations": ["double", "eye"]}')
        assert ctrl.active and ctrl.game.player == "bo" and ctrl.game.kinds == ["double", "eye"]
        assert ctrl.finish_early() is False
        ctrl.stop()
        assert not ctrl.active

    def test_next_ends_a_turn_without_a_dart_as_misses(self):
        game = new_game()
        assert game.next_turn() is True
        assert game.thrown == 3


class TestStats:
    def run(self, db, turns, finish=True):
        game = new_game(db)
        for t in turns:
            play(game, *t)
        if finish and game.state == "playing":
            game.finish_early()
        return game

    def full_run(self, db):
        darts = everything()
        return self.run(db, [tuple(darts[i:i + 3]) for i in range(0, len(darts), 3)])

    def test_the_overview_compares_the_complete_runs(self, db):
        self.run(db, [(big(1), MISS, MISS)])                                  # a run that was ended early
        self.full_run(db)
        (player,) = db.warm_up_overview()["players"]
        (mode,) = player["modes"]
        assert mode["complete_runs"] == 1 and mode["fewest_darts"] == 84 and mode["average_darts"] == 84.0
        partial, complete = mode["runs"]
        assert (partial["complete"], partial["darts"], partial["fields"], partial["total"]) == (False, 3, 1, 84)
        assert complete["complete"] is True and complete["fields"] == 84

    def test_the_slowest_fields_are_averaged_over_the_complete_runs(self, db):
        darts = everything()
        turns = [(MISS, MISS, darts[0])] + [tuple(darts[i:i + 3]) for i in range(1, 83, 3)]   # three darts at the first field
        game = self.run(db, turns)
        assert game.state == "finished"
        (player,) = db.warm_up_overview()["players"]
        assert player["modes"][0]["slowest"][0] == {"kind": "big", "number": 1, "average": 3.0}

    def test_runs_over_different_stations_are_never_mixed(self, db):
        self.full_run(db)
        game = WarmUpGame("ana", FakeMqttClient(), "autodarts", kinds=["eye"], stats_db=db)
        game.announce_start()
        play(game, MISS, MISS, EYE)                                            # three darts for the bull's eye
        (player,) = db.warm_up_overview()["players"]
        everything_mode, eye_mode = player["modes"]                            # all stations first
        assert everything_mode["kinds"] == list(KINDS) and everything_mode["fewest_darts"] == 84
        assert (eye_mode["kinds"], eye_mode["complete_runs"], eye_mode["fewest_darts"]) == (["eye"], 1, 3)
        assert eye_mode["runs"][0]["total"] == 1 and player["run_count"] == 2

    def test_an_open_run_and_a_hidden_player_are_left_out(self, db):
        game = new_game(db)
        play(game, big(1), MISS, MISS)
        assert db.warm_up_overview() == {"players": []}
        game.finish_early()
        db.upsert_player("ana", hidden=True)
        assert db.warm_up_overview() == {"players": []}

    def test_the_match_list_the_detail_and_the_other_statistics(self, db):
        game = self.run(db, [(big(1), MISS, MISS)])
        (match,) = db.recent_matches(10, "warm_up")
        assert (match["game_mode"], match["players"], match["kinds"]) == ("Warm-up", ["ana"], list(KINDS))
        assert db.recent_matches(10, "x01") == []
        detail = db.match_stats(game.match_id)
        assert (detail["player"], detail["darts"], detail["complete"]) == ("ana", 3, False)
        assert detail["per_field"][:2] == [1, 2]

    def test_deleting_the_player_takes_the_runs_with_it(self, db):
        self.run(db, [(big(1), MISS, MISS)])
        db.delete_player("ana")
        assert db.warm_up_overview() == {"players": []}
        assert db._conn.execute("SELECT COUNT(*) FROM dart_positions").fetchone()[0] == 0

    def test_merging_two_players_moves_the_runs(self, db):
        self.run(db, [(big(1), MISS, MISS)])
        db.upsert_player("bo")
        db.merge_players("ana", "bo")
        (player,) = db.warm_up_overview()["players"]
        assert player["player"] == "bo"


@pytest.fixture
def client(tmp_path):
    db = StatsDB(str(tmp_path / "s.db"))
    wu = WarmUpController(FakeMqttPub(), "autodarts", stats_db=db, on_change=server.push)
    bb = BlackBeltController(FakeMqttPub(), "autodarts", stats_db=db)
    ft = FieldTrainingController(FakeMqttPub(), "autodarts", stats_db=db)
    elim = EliminationController(FakeMqttPub(), "autodarts", stats_db=db)
    server.wire(None, elim, stats_tracker=StatsTracker(db), ft_ctrl=ft, bb_ctrl=bb, wu_ctrl=wu)
    yield TestClient(server.app), wu, bb, ft, elim
    server.wire(None, None)


class TestServer:
    def test_start_and_state(self, client):
        c, wu, *_ = client
        assert server._build_payload()["warm_up"] == {"active": False}
        assert c.post("/api/warm-up/start", json={"player": "ana"}).json() == {"ok": True}
        s = server._build_payload()["warm_up"]
        assert (s["active"], s["player"], s["target"]["kind"], s["target"]["number"]) == (True, "ana", "big", 1)

    def test_the_stations_are_picked_with_the_start(self, client):
        c, wu, *_ = client
        assert c.post("/api/warm-up/start", json={"player": "ana", "stations": ["triple", "big"]}).json() == {"ok": True}
        s = server._build_payload()["warm_up"]
        assert s["kinds"] == ["big", "triple"] and len(s["steps"]) == 40

    def test_an_unknown_station_is_refused(self, client):
        c, wu, *_ = client
        assert "unknown station" in c.post("/api/warm-up/start", json={"player": "ana", "stations": ["nope"]}).json()["error"]
        assert wu.game is None

    def test_a_player_is_needed(self, client):
        c, wu, *_ = client
        assert "player" in c.post("/api/warm-up/start", json={"player": " "}).json()["error"]
        assert wu.game is None

    def test_another_running_game_blocks_a_start_and_the_other_way_round(self, client):
        c, wu, bb, ft, elim = client
        c.post("/api/black-belt/start", json={"player": "ana"})
        assert "Black Belt" in c.post("/api/warm-up/start", json={"player": "ana"}).json()["error"]
        c.post("/api/black-belt/stop")
        c.post("/api/warm-up/start", json={"player": "ana"})
        assert "Warm-up" in c.post("/api/black-belt/start", json={"player": "ana"}).json()["error"]
        assert "Warm-up" in c.post("/api/field-training/start", json={"player": "ana", "field": 20}).json()["error"]
        assert "Warm-up" in c.post("/api/elimination/start", json={"players": ["a", "b"]}).json()["error"]

    def test_finish_undo_stop_and_correct_dart(self, client):
        c, wu, *_ = client
        c.post("/api/warm-up/start", json={"player": "ana"})
        assert c.post("/api/warm-up/finish").json() == {"ok": True} and wu.game is None
        c.post("/api/warm-up/start", json={"player": "ana"})
        play(wu.game, big(1), MISS, MISS)
        assert c.post("/api/warm-up/undo").json() == {"ok": True}
        assert "nothing to undo" in c.post("/api/warm-up/undo").json()["error"]
        wu.game.on_board_state(1, [MISS])
        c.post("/api/warm-up/correct-dart", json={"dart": 1, "field": "S1", "x": 0.0, "y": 0.8})
        assert wu.game.snapshot()["position"] == 1
        assert "error" in c.post("/api/warm-up/correct-dart", json={"dart": 4, "field": "S1"}).json()
        c.post("/api/warm-up/stop")
        assert server._build_payload()["warm_up"] == {"active": False}

    def test_the_statistics_endpoints(self, client):
        c, wu, *_ = client
        c.post("/api/warm-up/start", json={"player": "ana"})
        play(wu.game, big(1), big(2), MISS)
        c.post("/api/warm-up/finish")
        over = c.get("/api/stats/warm-up/overview").json()
        assert over["players"][0]["modes"][0]["runs"][0]["darts"] == 3
        (match,) = c.get("/api/stats/matches?mode=warm_up").json()
        assert c.get(f"/api/stats/match/{match['match_id']}").json()["darts"] == 3


def test_a_database_from_before_the_stations_gets_the_column_and_counts_its_runs_as_full_runs(tmp_path):
    import sqlite3
    path = str(tmp_path / "old.db")
    StatsDB(path)
    conn = sqlite3.connect(path)
    conn.executescript("DROP TABLE warm_up_games; CREATE TABLE warm_up_games ("
                       "match_id TEXT PRIMARY KEY, player TEXT NOT NULL, complete INTEGER NOT NULL DEFAULT 0);"
                       "INSERT INTO matches (match_id, game_mode, points_start, started_at, ended_at, players)"
                       " VALUES ('m1', 'Warm-up', 0, '2026-10-17T10:00:00', '2026-10-17T10:05:00', '[\"ana\"]');"
                       "INSERT INTO warm_up_games VALUES ('m1', 'ana', 0);"
                       "INSERT INTO warm_up_darts (match_id, player, turn_no, dart_no, step, hit) VALUES ('m1', 'ana', 1, 1, 0, 1);")
    conn.commit()
    conn.close()
    db = StatsDB(path)
    (mode,) = db.warm_up_overview()["players"][0]["modes"]
    assert mode["kinds"] == list(KINDS) and mode["runs"][0]["darts"] == 1
    game = WarmUpGame("ana", FakeMqttClient(), "autodarts", kinds=["big"], stats_db=db)       # a new run stores its kinds
    assert db._conn.execute("SELECT kinds FROM warm_up_games WHERE match_id = ?", (game.match_id,)).fetchone()[0] == "big"
