import random

import pytest
from starlette.testclient import TestClient

from breakfast.stats import StatsDB, StatsTracker
from breakfast.web import server
from tests.test_target_battle import MISS, hit, new_game, play


def played(db, players, rounds=1, targets=None, scoring="standard", turns=(), tiebreak=False, rng=None):
    """A finished game. *turns*: the darts of every turn in order, as lists of throws."""
    targets = targets or [20] * rounds
    game = new_game(players=players, db=db, rounds=rounds, targets=targets, scoring=scoring,
                    tiebreak=tiebreak, rng=rng)
    for darts in turns:
        play(game, *darts)
    assert game.state == "finished"
    return game


@pytest.fixture
def db():
    return StatsDB(":memory:")


class TestSetup:
    def test_the_rules_of_a_game_are_stored(self, db):
        game = played(db, ("ana",), turns=[[hit(20, 1)]], scoring="doubles")
        row = db._conn.execute("SELECT scoring, rounds, tiebreak, fixed_targets FROM target_battle_games").fetchone()
        assert tuple(row) == ("doubles", 1, 0, 1)
        assert game.match_id

    def test_the_players_of_a_closed_game_are_listed_with_the_match(self, db):
        game = played(db, ("ana", "bo"), turns=[[hit(20, 1)], [hit(20, 1)]])
        row = db._conn.execute("SELECT players FROM matches WHERE match_id = ?", (game.match_id,)).fetchone()
        assert sorted(__import__("json").loads(row[0])) == ["ana", "bo"]


class TestOverview:
    def test_without_games_everything_is_empty(self, db):
        out = db.target_battle_overview()
        assert out["summary"]["games"] == 0 and out["players"] == [] and out["head_to_head"] == []
        assert out["records"] == {"best_game": None, "best_turn": None}

    def test_wins_placements_and_the_chance_of_winning(self, db):
        played(db, ("ana", "bo", "cy"), turns=[[hit(20, 3)], [hit(20, 2)], [hit(20, 1)]])
        played(db, ("ana", "bo"), turns=[[hit(20, 1)], [hit(20, 3)]])
        players = {p["player"]: p for p in db.target_battle_overview()["players"]}
        assert (players["ana"]["games"], players["ana"]["wins"]) == (2, 1)
        assert players["ana"]["placements"] == {"first": 1, "second": 1, "third": 0, "other": 0}
        assert players["cy"]["placements"] == {"first": 0, "second": 0, "third": 1, "other": 0}
        assert players["ana"]["expected_wins"] == pytest.approx(1 / 3 + 1 / 2, abs=0.01)
        assert players["ana"]["win_pct"] == 50.0

    def test_playing_alone_counts_for_the_throwing_but_not_for_wins(self, db):
        played(db, ("ana",), turns=[[hit(20, 3), hit(20, 3), hit(20, 3)]])
        ana = db.target_battle_overview()["players"][0]
        assert (ana["games"], ana["wins"], ana["solo_games"]) == (0, 0, 1)
        assert (ana["turns"], ana["avg_points_per_round"], ana["perfect_turns"]) == (1, 9.0, 1)
        assert db.target_battle_overview()["head_to_head"] == [] and ana["form"]["games"] == []

    def test_the_throwing_numbers(self, db):
        played(db, ("ana", "bo"), rounds=2, targets=[20, 5], turns=[
            [hit(20, 3), hit(20, 1), MISS], [hit(5, 1)],            # round 1: ana 4, bo 1
            [hit(5, 2), hit(5, 2), hit(5, 2)], [hit(19, 1), MISS],  # round 2: ana 6, bo 0
        ])
        ana = next(p for p in db.target_battle_overview()["players"] if p["player"] == "ana")
        assert ana["turns"] == 2 and ana["avg_points_per_round"] == 5.0
        assert (ana["darts"], ana["hits"], ana["hit_pct"]) == (6, 5, 83.3)
        assert ana["best_turn"]["score"] == 6 and ana["perfect_turns"] == 0
        assert {b["target"]: (b["darts"], b["hits"]) for b in ana["by_target"]} == {20: (3, 2), 5: (3, 3)}

    def test_a_perfect_turn_is_the_best_a_profile_can_give(self, db):
        played(db, ("ana", "bo"), scoring="triples", turns=[[hit(20, 3)] * 3, [hit(20, 3), hit(20, 3)]])
        ana = next(p for p in db.target_battle_overview("triples")["players"] if p["player"] == "ana")
        assert ana["perfect_turns"] == 1 and ana["best_turn"]["score"] == 3

    def test_each_profile_has_its_own_numbers_and_old_games_count_as_standard(self, db):
        played(db, ("ana", "bo"), turns=[[hit(20, 3)], [hit(20, 1)]])
        played(db, ("ana", "bo"), scoring="singles", turns=[[hit(20, 1)], [hit(20, 1)]])
        db._conn.execute("DELETE FROM target_battle_games")      # games from before the rules were stored
        db._conn.commit()
        assert db.target_battle_overview("standard")["summary"]["games"] == 2
        assert db.target_battle_overview("singles")["summary"]["games"] == 0

    def test_a_tiebreak_is_no_part_of_the_throwing_numbers(self, db):
        game = new_game(players=("ana", "bo"), db=db, rounds=1, targets=[20], tiebreak=True, rng=random.Random(3))
        play(game, hit(20, 1))
        play(game, hit(20, 1))
        play(game, hit(game.target, 1))
        play(game, MISS)
        assert game.state == "finished"
        ana = next(p for p in db.target_battle_overview()["players"] if p["player"] == "ana")
        assert ana["turns"] == 1 and ana["darts"] == 1

    def test_the_darts_of_a_corrected_total_are_not_counted(self, db):
        game = new_game(players=("ana", "bo"), db=db, rounds=1, targets=[20])
        play(game, hit(20, 3), hit(20, 3), hit(20, 3))
        game.correct_turn(3)
        play(game, hit(20, 1))
        ana = next(p for p in db.target_battle_overview()["players"] if p["player"] == "ana")
        assert ana["turns"] == 1 and ana["darts"] == 0 and ana["avg_points_per_round"] == 3.0

    def test_records_and_the_summary(self, db):
        played(db, ("ana", "bo"), rounds=2, targets=[20, 5], turns=[
            [hit(20, 3)], [hit(20, 1)], [hit(5, 3), hit(5, 3), hit(5, 3)], [hit(5, 1)]])
        out = db.target_battle_overview()
        assert out["summary"]["games"] == 1
        assert out["records"]["best_game"]["score"] == 12 and out["records"]["best_game"]["player"] == "ana"
        assert out["records"]["best_game"]["rounds"] == 2
        assert out["records"]["best_turn"]["score"] == 9

    def test_form_and_streaks_come_from_games_against_others(self, db):
        for scores in ((3, 1), (3, 1), (1, 3), (3, 1)):
            played(db, ("ana", "bo"), turns=[[hit(20, scores[0])], [hit(20, scores[1])]])
        ana = next(p for p in db.target_battle_overview()["players"] if p["player"] == "ana")
        assert [g["placement"] for g in ana["form"]["games"]] == [1, 1, 2, 1]
        assert (ana["form"]["current_streak"], ana["form"]["best_streak"]) == (1, 2)
        assert ana["form"]["games"][0]["opponents"] == ["bo"] and ana["form"]["games"][0]["size"] == 2

    def test_head_to_head_counts_who_finished_ahead(self, db):
        played(db, ("ana", "bo"), turns=[[hit(20, 3)], [hit(20, 1)]])
        played(db, ("ana", "bo"), turns=[[hit(20, 1)], [hit(20, 3)]])
        played(db, ("ana", "bo"), turns=[[hit(20, 3)], [hit(20, 1)]])
        played(db, ("ana", "bo"), turns=[[hit(20, 1)], [hit(20, 1)]])      # a tie is ahead for nobody
        pair = db.target_battle_overview()["head_to_head"][0]
        assert (pair["a"], pair["b"], pair["games"], pair["a_ahead"], pair["b_ahead"]) == ("ana", "bo", 4, 2, 1)

    def test_hidden_players_are_left_out_everywhere(self, db):
        db.upsert_player("ghost", hidden=True)
        played(db, ("ana", "ghost"), turns=[[hit(20, 1)], [hit(20, 3)]])
        out = db.target_battle_overview()
        assert [p["player"] for p in out["players"]] == ["ana"]
        assert out["head_to_head"] == [] and out["records"]["best_game"]["player"] == "ana"
        assert out["records"]["best_turn"]["player"] == "ana"
        # ...but they still count as an opponent: ana is on the chance of two players
        assert out["players"][0]["expected_wins"] == 0.5

    def test_unfinished_games_are_not_counted(self, db):
        game = new_game(players=("ana", "bo"), db=db, rounds=2, targets=[20, 20])
        play(game, hit(20, 3))
        assert db.target_battle_overview()["summary"]["games"] == 0


class TestMatches:
    def test_a_game_has_its_rules_placements_and_rounds(self, db):
        game = played(db, ("ana", "bo"), rounds=2, targets=[20, 5], scoring="singles", turns=[
            [hit(20, 1)], [hit(20, 1)], [hit(5, 1)], [MISS]])
        out = db.match_stats(game.match_id)
        assert (out["scoring"], out["rounds"]) == ("singles", 2)
        assert [(p["player"], p["placement"], p["score"]) for p in out["players"]] == [("ana", 1, 2), ("bo", 2, 1)]
        assert out["history"] == [
            {"round": 1, "tiebreak": False, "target": 20, "scores": {"ana": 1, "bo": 1}},
            {"round": 2, "tiebreak": False, "target": 5, "scores": {"ana": 1, "bo": 0}}]

    def test_the_recent_matches_list_knows_the_game(self, db):
        game = played(db, ("ana", "bo"), turns=[[hit(20, 1)], [hit(20, 3)]])
        matches = db.recent_matches(mode="target_battle")
        assert [m["match_id"] for m in matches] == [game.match_id]
        assert matches[0]["players"] and matches[0]["game_mode"] == "Target Battle"
        assert db.recent_matches(mode="x01") == [] and db.recent_matches(mode="elimination") == []
        assert [m["match_id"] for m in db.recent_matches()] == [game.match_id]


class TestEndpoints:
    @pytest.fixture
    def client(self, tmp_path):
        db = StatsDB(str(tmp_path / "s.db"))
        server.wire(None, None, stats_tracker=StatsTracker(db))
        yield TestClient(server.app), db
        server.wire(None, None)

    def test_the_overview_follows_the_profile(self, client):
        c, db = client
        played(db, ("ana", "bo"), scoring="triples", turns=[[hit(20, 3)], [hit(20, 1)]])
        assert c.get("/api/stats/target-battle/overview").json()["summary"]["games"] == 0
        out = c.get("/api/stats/target-battle/overview?scoring=triples").json()
        assert out["summary"]["games"] == 1 and out["scoring"] == "triples"

    def test_an_unknown_profile_is_refused(self, client):
        c, _ = client
        assert c.get("/api/stats/target-battle/overview?scoring=bulls").status_code == 422

    def test_matches_and_a_match_can_be_fetched(self, client):
        c, db = client
        game = played(db, ("ana", "bo"), turns=[[hit(20, 1)], [hit(20, 3)]])
        assert [m["match_id"] for m in c.get("/api/stats/matches?mode=target_battle").json()] == [game.match_id]
        assert c.get(f"/api/stats/match/{game.match_id}").json()["players"][0]["player"] == "bo"

    def test_without_a_database_the_overview_is_empty(self):
        server.wire(None, None)
        out = TestClient(server.app).get("/api/stats/target-battle/overview").json()
        assert out["players"] == [] and out["summary"] == {}
