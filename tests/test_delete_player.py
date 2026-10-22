import json

import pytest
from starlette.testclient import TestClient

from breakfast.stats import DELETED_PLAYER, StatsDB, StatsTracker
from breakfast.web import server


def _x01(db, match_id, players, winner=None):
    db.open_match(match_id, "X01", 501)
    for i, player in enumerate(players, 1):
        db.insert_turn(match_id, player, 1, i, 501, 60, False, False, [("T20", 60, 441)],
                       positions=[{"x": 0.0, "y": 0.1, "entry": "board"}])
    db.record_leg_win(match_id, 1, winner or players[0])
    db.set_winner(match_id, winner or players[0])
    db.close_match(match_id)


def _names(db, table, match_id):
    return sorted(r[0] for r in db._conn.execute(f"SELECT player FROM {table} WHERE match_id = ?", (match_id,)))


def _count(db, table, where="1", args=()):
    return db._conn.execute(f"SELECT COUNT(*) FROM {table} WHERE {where}", args).fetchone()[0]


@pytest.fixture
def pdb(tmp_path):
    db = StatsDB(str(tmp_path / "s.db"))
    for name in ("ana", "ben", "carl"):
        db.upsert_player(name)
    return db


def test_a_match_only_the_player_played_is_deleted(pdb):
    _x01(pdb, "solo", ["ana"])
    result = pdb.delete_player("ana")
    assert (result["matches_deleted"], result["matches_kept"]) == (1, 0)
    assert _count(pdb, "matches") == 0 and _count(pdb, "turns") == 0 and _count(pdb, "dart_positions") == 0
    assert _count(pdb, "players", "name = 'ana'") == 0


def test_a_shared_match_keeps_its_numbers_under_a_placeholder(pdb):
    _x01(pdb, "m1", ["ana", "ben"], winner="ana")
    pdb.delete_player("ana")
    assert _names(pdb, "turns", "m1") == sorted([DELETED_PLAYER, "ben"])
    row = pdb._conn.execute("SELECT winner, players FROM matches WHERE match_id = 'm1'").fetchone()
    assert row["winner"] == DELETED_PLAYER
    assert DELETED_PLAYER in json.loads(row["players"]) and "ana" not in json.loads(row["players"])
    assert pdb._conn.execute("SELECT winner FROM legs WHERE match_id = 'm1'").fetchone()[0] == DELETED_PLAYER
    # the deleted player's dart positions are gone, the other player's stay
    assert _count(pdb, "dart_positions", "player = ?", (DELETED_PLAYER,)) == 0
    assert _count(pdb, "dart_positions", "player = 'ben'") == 1


def test_several_deleted_players_in_one_match_get_numbers(pdb):
    _x01(pdb, "m1", ["ana", "ben", "carl"])
    pdb.delete_player("ana")
    pdb.delete_player("ben")
    assert _names(pdb, "turns", "m1") == sorted([DELETED_PLAYER, f"{DELETED_PLAYER} 2", "carl"])


def test_the_placeholder_is_left_out_of_rankings_and_the_hidden_list(pdb):
    _x01(pdb, "m1", ["ana", "ben"])
    pdb.delete_player("ana")
    assert [r["player"] for r in pdb.all_players_stats()] == ["ben"]
    assert pdb.listed_hidden_players() == []
    assert DELETED_PLAYER in pdb.hidden_players()


def test_a_match_against_a_bot_is_deleted_with_the_human(pdb):
    pdb.open_match("vs-bot", "X01", 501)
    pdb.insert_turn("vs-bot", "ana", 1, 1, 501, 60, False, False, [("T20", 60, 441)])
    pdb.insert_bot_turn("vs-bot", "bot", 1, 1, 501, 60, False, False, [("T20", 60, 441)])
    pdb.close_match("vs-bot")
    assert pdb.delete_player("ana")["matches_deleted"] == 1
    assert _count(pdb, "matches") == 0 and _count(pdb, "bot_turns") == 0


def test_elimination_results_and_achievements_follow(pdb):
    pdb.open_match("e1", "Elimination", 3)
    pdb.record_elimination_result("e1", [("ana", 1, 2), ("ben", 2, None)])
    pdb.close_match("e1")
    pdb._conn.execute("INSERT INTO achievements_earned (player, achievement_id, tier, earned_at, match_id)"
                      " VALUES ('ana', 'a', 0, 'now', 'e1'), ('ben', 'b', 0, 'now', 'e1')")
    pdb._conn.commit()
    result = pdb.delete_player("ana")
    assert result["achievements"] == 1
    assert _names(pdb, "elimination_results", "e1") == sorted([DELETED_PLAYER, "ben"])
    assert _count(pdb, "achievements_earned", "player = 'ana'") == 0
    assert _count(pdb, "achievements_earned", "player = 'ben'") == 1


def test_a_tournament_bracket_shows_the_placeholder(pdb):
    pdb.save_tournament("t1", "finished", {"players": ["ana", "ben"], "rounds": [[{"a": "ana", "b": "ben"}]]})
    _x01(pdb, "m1", ["ana", "ben"])
    pdb.delete_player("ana")
    data = json.loads(pdb._conn.execute("SELECT data FROM tournaments WHERE id = 't1'").fetchone()[0])
    assert data == {"players": [DELETED_PLAYER, "ben"], "rounds": [[{"a": DELETED_PLAYER, "b": "ben"}]]}


def test_the_preview_counts_what_would_happen_and_changes_nothing(pdb):
    _x01(pdb, "solo", ["ana"])
    _x01(pdb, "shared", ["ana", "ben"])
    assert pdb.delete_player_preview("ana") == {"matches_deleted": 1, "matches_kept": 1, "achievements": 0}
    assert _count(pdb, "matches") == 2 and _count(pdb, "players", "name = 'ana'") == 1


def test_a_copy_of_the_database_is_made_first(pdb, tmp_path):
    _x01(pdb, "m1", ["ana", "ben"])
    result = pdb.delete_player("ana")
    import sqlite3
    copy = sqlite3.connect(result["backup"])
    assert copy.execute("SELECT COUNT(*) FROM players WHERE name = 'ana'").fetchone()[0] == 1
    copy.close()


# ── the routes ────────────────────────────────────────────────────────────────

class _Pin:
    def pin_required(self):
        return True

    def verify_pin(self, pin):
        from breakfast.locations import LocationError
        if pin != "1234":
            raise LocationError("wrong PIN")


@pytest.fixture
def client(pdb):
    server.wire(None, None, stats_tracker=StatsTracker(pdb))
    yield TestClient(server.app), pdb
    server.wire(None, None)
    server._locations = None


def test_the_route_previews_and_deletes(client):
    http, db = client
    _x01(db, "m1", ["ana", "ben"])
    assert http.get("/api/players/delete-preview", params={"name": "ana"}).json()["matches_kept"] == 1
    assert http.delete("/api/stats/player/ana").json()["matches_kept"] == 1
    assert _count(db, "players", "name = 'ana'") == 0


def test_the_route_asks_for_the_pin_when_one_is_set(client):
    http, db = client
    server._locations = _Pin()
    assert http.delete("/api/stats/player/ana").json() == {"error": "wrong PIN"}
    assert _count(db, "players", "name = 'ana'") == 1
    assert "backup" in http.delete("/api/stats/player/ana", headers={"X-Pin": "1234"}).json()


def test_the_route_refuses_while_a_game_is_running(client, monkeypatch):
    http, db = client
    monkeypatch.setattr(server, "_a_game_is_running", lambda: True)
    assert http.delete("/api/stats/player/ana").json() == {"error": "finish the running game first"}
    assert _count(db, "players", "name = 'ana'") == 1
