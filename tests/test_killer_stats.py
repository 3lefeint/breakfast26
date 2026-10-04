import pytest
from starlette.testclient import TestClient

from breakfast.killer import KillerGame
from breakfast.stats import StatsDB, StatsTracker
from breakfast.web import server
from tests.test_target_battle import MISS, FakeMqttClient, hit, play

NUMBERS = {"ana": 20, "bo": 5, "cy": 12, "dan": 3}


def new_game(db, players=("ana", "bo", "cy"), **kw):
    game = KillerGame(list(players), FakeMqttClient(), "autodarts", stats_db=db,
                      numbers={p: NUMBERS[p] for p in players}, **kw)
    game.announce_start()
    return game


def game_a(db, **kw):
    """ana wins: bo is out after ana's second turn, cy becomes a killer on their second turn and goes out."""
    game = new_game(db, **kw)
    play(game, hit(20, 2))                                  # ana: killer
    play(game, MISS)                                        # bo
    play(game, MISS)                                        # cy
    play(game, hit(5, 2), hit(5, 2), hit(5, 2))             # ana: bo is out
    play(game, hit(12, 2))                                  # cy: killer (their second turn)
    play(game, hit(12, 2), hit(12, 2), hit(12, 2))          # ana: cy is out
    assert game.state == "finished" and game.winner == "ana"
    return game


@pytest.fixture
def db():
    return StatsDB(":memory:")


def row(overview, name):
    return next(p for p in overview["players"] if p["player"] == name)


class TestMatchStats:
    def test_a_game_with_the_rules_and_what_each_player_did(self, db):
        game = game_a(db, own_goal=True)
        detail = db.match_killer_stats(game.match_id)
        assert detail["rules"] == {"own_goal": True, "singles": False}
        by = {p["player"]: p for p in detail["players"]}
        assert [p["player"] for p in detail["players"]] == ["ana", "cy", "bo"]
        assert (by["ana"]["placement"], by["ana"]["number"], by["ana"]["lives_left"]) == (1, 20, 3)
        assert (by["ana"]["taken"], by["ana"]["knockouts"], by["ana"]["killer_turn"]) == (6, 2, 1)
        assert (by["bo"]["lost"], by["bo"]["killer_turn"], by["bo"]["turns"]) == (3, None, 1)
        assert (by["cy"]["lost"], by["cy"]["killer_turn"], by["cy"]["turns"]) == (3, 2, 2)

    def test_the_stats_of_a_match_are_served_by_the_generic_route(self, db):
        game = game_a(db)
        assert [p["player"] for p in db.match_stats(game.match_id)["players"]] == ["ana", "cy", "bo"]

    def test_an_own_goal_counts_as_a_life_lost_but_not_taken(self, db):
        game = new_game(db, players=("ana", "bo"), own_goal=True)
        play(game, hit(20, 2), hit(20, 2))                  # killer, then an own goal
        play(game, MISS)
        play(game, hit(20, 2), hit(20, 2))                  # two more, ana is out
        assert game.winner == "bo"
        by = {p["player"]: p for p in db.match_killer_stats(game.match_id)["players"]}
        assert (by["ana"]["own_goals"], by["ana"]["lost"], by["ana"]["taken"], by["ana"]["knockouts"]) == (3, 3, 0, 0)
        assert by["bo"]["placement"] == 1


class TestOverview:
    def test_without_games_there_is_nothing(self, db):
        data = db.killer_overview()
        assert data["summary"]["games"] == 0 and data["players"] == [] and data["head_to_head"] == []
        assert data["records"] == {"most_lives_taken": None, "most_knockouts": None, "fastest_killer": None}

    def test_an_unfinished_game_does_not_count(self, db):
        game = new_game(db)
        play(game, hit(20, 2))
        assert db.killer_overview()["summary"]["games"] == 0

    def test_the_numbers_of_one_game(self, db):
        game_a(db)
        data = db.killer_overview()
        assert data["summary"]["games"] == 1 and data["summary"]["avg_players"] == 3.0
        ana, bo, cy = row(data, "ana"), row(data, "bo"), row(data, "cy")
        assert (ana["games"], ana["wins"], ana["win_pct"]) == (1, 1, 100.0)
        assert (ana["lives_taken"], ana["knockouts"], ana["lives_lost"]) == (6, 2, 0)
        assert (ana["killer_games"], ana["killer_pct"], ana["avg_turns_to_killer"], ana["fastest_killer"]) == (1, 100.0, 1.0, 1)
        assert (cy["wins"], cy["killer_games"], cy["avg_turns_to_killer"], cy["lives_lost"]) == (0, 1, 2.0, 3)
        assert (bo["killer_games"], bo["killer_pct"], bo["avg_turns_to_killer"]) == (0, 0.0, None)
        assert ana["lives_taken_per_game"] == 6.0

    def test_placements_form_and_streaks_over_several_games(self, db):
        game_a(db)
        game_a(db)
        ana, cy = row(db.killer_overview(), "ana"), row(db.killer_overview(), "cy")
        assert ana["placements"] == {"first": 2, "second": 0, "third": 0, "other": 0}
        assert cy["placements"] == {"first": 0, "second": 2, "third": 0, "other": 0}
        assert ana["form"]["current_streak"] == 2 and ana["form"]["best_streak"] == 2
        assert [g["placement"] for g in ana["form"]["games"]] == [1, 1]
        assert ana["form"]["games"][0]["opponents"] == ["bo", "cy"]
        assert ana["expected_wins"] == pytest.approx(2 / 3, abs=0.01)

    def test_head_to_head(self, db):
        game_a(db)
        pair = {(e["a"], e["b"]): e for e in db.killer_overview()["head_to_head"]}
        assert pair[("ana", "bo")] == {"a": "ana", "b": "bo", "a_ahead": 1, "b_ahead": 0, "games": 1}
        assert pair[("bo", "cy")]["b_ahead"] == 1

    def test_records(self, db):
        game_a(db)
        records = db.killer_overview()["records"]
        assert records["most_lives_taken"]["count"] == 6 and records["most_lives_taken"]["player"] == "ana"
        assert records["most_knockouts"]["count"] == 2
        assert records["fastest_killer"] == {"turns": 1, "player": "ana"}

    def test_a_hidden_player_is_left_out(self, db):
        db.upsert_player("bo", hidden=True)
        game_a(db)
        data = db.killer_overview()
        assert "bo" not in [p["player"] for p in data["players"]]
        assert all(("bo" not in (e["a"], e["b"])) for e in data["head_to_head"])

    def test_an_undone_win_takes_the_game_out_again(self, db):
        game = game_a(db)
        game.undo()
        assert db.killer_overview()["summary"]["games"] == 0

    def test_a_double_thrown_for_the_number_counts_as_the_first_turn(self, db):
        game = KillerGame(["ana", "bo"], FakeMqttClient(), "autodarts", stats_db=db, throw_numbers=True)
        game.announce_start()
        play(game, hit(20, 2))                      # ana's number is 20 and she is a killer at once
        play(game, hit(5, 1))
        play(game, MISS); play(game, MISS)
        play(game, hit(5, 2), hit(5, 2), hit(5, 2))
        assert game.winner == "ana"
        ana = row(db.killer_overview(), "ana")
        assert ana["avg_turns_to_killer"] == 1.0 and ana["lives_taken"] == 3


@pytest.fixture
def client(tmp_path):
    db = StatsDB(str(tmp_path / "s.db"))
    server.wire(None, None, stats_tracker=StatsTracker(db))
    yield TestClient(server.app), db
    server.wire(None, None)


class TestRoutes:
    def test_the_overview_route(self, client):
        c, db = client
        game_a(db)
        data = c.get("/api/stats/killer/overview").json()
        assert data["summary"]["games"] == 1 and row(data, "ana")["wins"] == 1

    def test_the_match_list_and_detail_routes(self, client):
        c, db = client
        game = game_a(db)
        matches = c.get("/api/stats/matches?mode=killer").json()
        assert [m["match_id"] for m in matches] == [game.match_id] and matches[0]["game_mode"] == "Killer"
        assert sorted(matches[0]["players"]) == ["ana", "bo", "cy"]
        assert c.get(f"/api/stats/match/{game.match_id}").json()["players"][0]["player"] == "ana"
        assert c.get("/api/stats/matches?mode=x01").json() == []

    def test_a_killer_game_is_not_in_the_other_modes(self, client):
        c, db = client
        game_a(db)
        assert c.get("/api/stats/matches?mode=elimination").json() == []
        assert c.get("/api/stats/matches?mode=target_battle").json() == []
