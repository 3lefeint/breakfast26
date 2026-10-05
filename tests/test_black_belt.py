import pytest
from starlette.testclient import TestClient

from breakfast.black_belt import BlackBeltController, BlackBeltGame, Progress, ladder
from breakfast.elimination import EliminationController
from breakfast.field_training import FieldTrainingController
from breakfast.stats import StatsDB, StatsTracker
from breakfast.web import server
from tests.test_target_battle import FakeMqttClient, FakeMqttPub, MISS, hit, play

BULLS_EYE = {"segment": {"name": "50", "number": 25, "multiplier": 2}, "coords": {"x": 0.02, "y": 0.01}}
OUTER = {"segment": {"name": "25", "number": 25, "multiplier": 1}, "coords": {"x": 0.05, "y": 0.02}}


def d(n):
    """A dart on the double of n."""
    return hit(n, 2)


def new_game(db=None, backwards=False):
    game = BlackBeltGame("ana", FakeMqttClient(), "autodarts", backwards=backwards, stats_db=db)
    game.announce_start()
    return game


@pytest.fixture
def db(tmp_path):
    return StatsDB(str(tmp_path / "s.db"))


def snap(game):
    return game.snapshot()


class TestLadder:
    def test_it_runs_up_or_down_and_ends_with_the_bulls_eye(self):
        assert ladder()[:3] == [1, 2, 3] and ladder()[-2:] == [20, 25] and len(ladder()) == 21
        assert ladder(True)[:3] == [20, 19, 18] and ladder(True)[-2:] == [1, 25]


class TestProgress:
    def test_a_hit_moves_on_and_the_darts_in_hand_are_bonus_darts(self):
        p = Progress()
        records = p.play([d(1), MISS, MISS])
        assert [(r["field"], r["hit"], r["bonus"]) for r in records] == [(1, True, False), (2, False, True), (2, False, True)]
        assert p.pos == 1 and p.own_left == 3 and p.restarts == 0       # D2 still has its three darts

    def test_bonus_darts_can_hit_one_after_another(self):
        p = Progress()
        p.play([d(1), d(2), d(3)])
        assert p.pos == 3 and p.own_left == 3 and p.furthest == 3

    def test_a_field_gets_three_darts_of_its_own_over_several_turns(self):
        p = Progress()
        p.play([MISS, MISS, d(1)])         # two darts used up at D1, the third hits
        assert p.pos == 1
        p.play([MISS, MISS])
        assert p.pos == 1 and p.own_left == 1
        p.play([MISS])
        assert (p.pos, p.restarts, p.attempts) == (0, 1, [1])

    def test_three_misses_at_a_field_start_the_ladder_again(self):
        p = Progress()
        p.play([d(1), d(2), d(3)])
        records = p.play([MISS, MISS, MISS])
        assert records[-1]["restart"] and (p.pos, p.restarts, p.own_left) == (0, 1, 3)
        assert p.furthest == 3 and p.attempts == [3]

    def test_darts_left_after_a_restart_are_own_darts_of_the_first_field(self):
        p = Progress()
        p.own_left = 1
        p.pos = 4
        p.play([MISS, MISS, MISS])        # the first miss ends the attempt, two darts at D1 follow
        assert (p.pos, p.own_left, p.restarts) == (0, 1, 1)

    def test_a_hit_with_a_bonus_dart_does_not_use_up_own_darts(self):
        p = Progress()
        p.play([d(1), MISS, MISS])        # bonus misses at D2
        p.play([MISS, MISS, MISS])        # now the three own darts of D2 are gone
        assert p.restarts == 1

    def test_the_belt_ends_the_run_and_later_darts_are_not_counted(self):
        p = Progress()
        darts = [d(n) for n in range(1, 21)] + [BULLS_EYE, MISS]
        records = p.play(darts)
        assert p.belt and len(records) == 21 and p.furthest == 21

    def test_the_outer_bull_and_single_are_no_hit(self):
        p = Progress()
        p.pos = 20
        p.play([OUTER, hit(25, 1), BULLS_EYE])
        assert p.belt

    def test_a_single_or_triple_is_no_hit(self):
        p = Progress()
        p.play([hit(1, 1), hit(1, 3), MISS])
        assert p.restarts == 1

    def test_backwards_starts_at_d20(self):
        p = Progress(backwards=True)
        p.play([d(20), d(19), MISS])
        assert p.pos == 2 and p.target == 18


class TestGame:
    def test_the_state_follows_the_darts_of_the_turn_live(self):
        game = new_game()
        game.on_board_state(1, [d(1)])
        s = snap(game)
        assert (s["position"], s["target"], s["thrown"], s["bonus_darts"]) == (1, 2, 1, 2)
        assert s["current_darts"][0]["hit"] is True
        game.on_board_state(3, [d(1), MISS, MISS])
        assert snap(game)["bonus_darts"] == 0 and snap(game)["position"] == 1

    def test_a_turn_is_counted_when_the_darts_are_pulled(self):
        game = new_game()
        play(game, d(1), MISS, MISS)
        s = snap(game)
        assert (s["position"], s["thrown"], s["turn"], s["own_left"]) == (1, 3, 2, 3)

    def test_the_belt_finishes_the_run(self, db):
        game = new_game(db)
        play(game, d(1), d(2), d(3))
        for n in range(4, 22, 3):
            play(game, *[d(m) if m <= 20 else BULLS_EYE for m in (n, n + 1, n + 2)][:3])
        s = snap(game)
        assert s["state"] == "finished" and s["result"]["belt"] is True
        assert (s["result"]["furthest"], s["result"]["restarts"], s["result"]["darts"]) == (21, 0, 21)
        assert db._conn.execute("SELECT belt FROM black_belt_games").fetchone()[0] == 1

    def test_finishing_early_keeps_the_darts_thrown(self, db):
        game = new_game(db)
        play(game, d(1), d(2), MISS)
        game.on_board_state(1, [d(3)])           # an unfinished turn is not counted
        assert game.finish_early() is True
        r = snap(game)["result"]
        assert (r["belt"], r["furthest"], r["darts"]) == (False, 2, 3)
        assert db._conn.execute("SELECT ended_at FROM matches").fetchone()[0]

    def test_finishing_without_a_dart_keeps_nothing(self):
        assert new_game().finish_early() is False

    def test_the_attempts_are_listed_in_the_result(self):
        game = new_game()
        play(game, d(1), d(2), MISS)
        play(game, MISS, MISS, d(3))              # D3's three darts: bonus none, own 3 -> D3 hit
        play(game, MISS, MISS, MISS)
        game.finish_early()
        assert snap(game)["result"]["attempts"] == [3, 0]

    def test_a_dart_corrected_by_tapping_counts(self):
        game = new_game()
        game.on_board_state(1, [MISS])
        game.correct_current_dart(0, "D1")
        game.on_board_state(0, [])
        assert snap(game)["position"] == 1

    def test_undo_walks_back_a_turn_and_reopens_a_finished_run(self, db):
        game = new_game(db)
        play(game, d(1), d(2), d(3))
        play(game, d(4), MISS, MISS)
        game.finish_early()
        assert game.undo() is True and game.state == "playing"       # the last turn is gone, the run is open
        assert db._conn.execute("SELECT ended_at FROM matches").fetchone()[0] is None
        assert snap(game)["thrown"] == 3
        assert game.undo() is True and snap(game)["thrown"] == 0
        assert db._conn.execute("SELECT COUNT(*) FROM black_belt_darts").fetchone()[0] == 0
        assert db._conn.execute("SELECT COUNT(*) FROM dart_positions").fetchone()[0] == 0
        assert game.undo() is False

    def test_a_player_is_needed(self):
        with pytest.raises(ValueError):
            BlackBeltGame(" ", FakeMqttClient(), "autodarts")

    def test_the_controller_reads_the_mqtt_command(self, db):
        pub = FakeMqttPub()
        ctrl = BlackBeltController(pub, "autodarts", stats_db=db)
        pub.subscribed["autodarts/black_belt/command"]('{"action": "start", "player": "bo", "backwards": true}')
        assert ctrl.active and ctrl.game.player == "bo" and ctrl.game.backwards is True
        assert ctrl.finish_early() is False
        ctrl.stop()
        assert not ctrl.active


class TestStats:
    def run(self, db, turns, finish=True):
        game = new_game(db)
        for t in turns:
            play(game, *t)
        if finish and game.state == "playing":
            game.finish_early()
        return game

    def test_the_overview_has_runs_belts_furthest_and_darts(self, db):
        self.run(db, [(d(1), d(2), MISS), (MISS, MISS, MISS)])                # restarts once, 6 darts
        belt = self.run(db, [(d(n), d(n + 1), d(n + 2)) for n in range(1, 19, 3)]
                        + [(d(19), d(20), BULLS_EYE)])
        assert belt.state == "finished"
        (player,) = db.black_belt_overview()["players"]
        assert player["belts"] == 1 and player["furthest"] == 21 and player["fewest_darts"] == 21
        first, second = player["runs"]
        assert (first["darts"], first["restarts"], first["furthest"], first["belt"]) == (6, 1, 2, False)
        assert second["belt"] is True and player["average_darts"] == round((6 + 21) / 2, 1)

    def test_an_open_run_and_a_hidden_player_are_left_out(self, db):
        game = new_game(db)
        play(game, d(1), MISS, MISS)
        assert db.black_belt_overview() == {"players": []}
        game.finish_early()
        db.upsert_player("ana", hidden=True)
        assert db.black_belt_overview() == {"players": []}

    def test_the_match_list_the_detail_and_the_other_statistics(self, db):
        game = self.run(db, [(d(1), MISS, MISS)])
        (match,) = db.recent_matches(10, "black_belt")
        assert (match["game_mode"], match["backwards"], match["players"]) == ("Black Belt", False, ["ana"])
        assert db.recent_matches(10, "x01") == []
        detail = db.match_stats(game.match_id)
        assert (detail["player"], detail["furthest"], detail["darts"]) == ("ana", 1, 3)

    def test_deleting_the_player_takes_the_runs_with_it(self, db):
        self.run(db, [(d(1), MISS, MISS)])
        db.delete_player("ana")
        assert db.black_belt_overview() == {"players": []}
        assert db._conn.execute("SELECT COUNT(*) FROM dart_positions").fetchone()[0] == 0

    def test_every_dart_is_stored_with_its_step(self, db):
        game = self.run(db, [(d(1), MISS, MISS)])
        rows = db.black_belt_dart_rows(game.match_id)
        assert [(r["step"], r["field"], r["hit"], r["bonus"]) for r in rows] == [
            (0, 1, True, False), (1, 2, False, True), (1, 2, False, True)]


@pytest.fixture
def client(tmp_path):
    db = StatsDB(str(tmp_path / "s.db"))
    bb = BlackBeltController(FakeMqttPub(), "autodarts", stats_db=db, on_change=server.push)
    ft = FieldTrainingController(FakeMqttPub(), "autodarts", stats_db=db)
    elim = EliminationController(FakeMqttPub(), "autodarts", stats_db=db)
    server.wire(None, elim, stats_tracker=StatsTracker(db), ft_ctrl=ft, bb_ctrl=bb)
    yield TestClient(server.app), bb, ft, elim
    server.wire(None, None)


class TestServer:
    def test_start_state_and_options(self, client):
        c, bb, *_ = client
        assert server._build_payload()["black_belt"] == {"active": False}
        assert c.post("/api/black-belt/start", json={"player": "ana", "backwards": True}).json() == {"ok": True}
        s = server._build_payload()["black_belt"]
        assert (s["active"], s["backwards"], s["target"], s["player"]) == (True, True, 20, "ana")

    def test_a_player_is_needed(self, client):
        c, bb, *_ = client
        assert "player" in c.post("/api/black-belt/start", json={"player": " "}).json()["error"]
        assert bb.game is None

    def test_another_running_game_blocks_a_start_and_the_other_way_round(self, client):
        c, bb, ft, elim = client
        c.post("/api/field-training/start", json={"player": "ana", "field": 20})
        assert "Field Training" in c.post("/api/black-belt/start", json={"player": "ana"}).json()["error"]
        c.post("/api/field-training/stop")
        c.post("/api/black-belt/start", json={"player": "ana"})
        assert "Black Belt" in c.post("/api/field-training/start", json={"player": "ana", "field": 20}).json()["error"]
        assert "Black Belt" in c.post("/api/elimination/start", json={"players": ["a", "b"]}).json()["error"]

    def test_finish_undo_stop_and_correct_dart(self, client):
        c, bb, *_ = client
        c.post("/api/black-belt/start", json={"player": "ana"})
        assert c.post("/api/black-belt/finish").json() == {"ok": True} and bb.game is None
        c.post("/api/black-belt/start", json={"player": "ana"})
        play(bb.game, d(1), MISS, MISS)
        assert c.post("/api/black-belt/undo").json() == {"ok": True}
        assert "nothing to undo" in c.post("/api/black-belt/undo").json()["error"]
        bb.game.on_board_state(1, [hit(5, 1)])
        c.post("/api/black-belt/correct-dart", json={"dart": 1, "field": "D1"})
        assert bb.game.snapshot()["position"] == 1
        assert "error" in c.post("/api/black-belt/correct-dart", json={"dart": 4, "field": "D1"}).json()
        c.post("/api/black-belt/stop")
        assert server._build_payload()["black_belt"] == {"active": False}

    def test_the_statistics_endpoints(self, client):
        c, bb, *_ = client
        c.post("/api/black-belt/start", json={"player": "ana"})
        play(bb.game, d(1), d(2), MISS)
        c.post("/api/black-belt/finish")
        over = c.get("/api/stats/black-belt/overview").json()
        assert over["players"][0]["runs"][0]["furthest"] == 2
        (match,) = c.get("/api/stats/matches?mode=black_belt").json()
        assert c.get(f"/api/stats/match/{match['match_id']}").json()["darts"] == 3
