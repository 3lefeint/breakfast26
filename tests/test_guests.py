import sqlite3

from breakfast import achievements as ach
from breakfast.achievements import AchievementEngine
from breakfast.stats import StatsDB

PILOT = tuple(ach.BY_ID[i] for i in ("ton_up",))


def test_a_guest_is_a_hidden_player_that_cannot_be_a_local_one(db):
    db.upsert_player("carl")
    name = db.guest_name("Carl", "Club")
    assert name == "carl@club"
    row = db._conn.execute("SELECT hidden, guest FROM players WHERE name = ?", (name,)).fetchone()
    assert (row["hidden"], row["guest"]) == (1, 1)
    assert db.guest_name("carl", "club") == name            # asking again changes nothing
    assert db.list_players() == ["carl"]
    assert db._conn.execute("SELECT hidden, guest FROM players WHERE name = 'carl'").fetchone()[:] == (0, 0)


def test_a_guest_is_not_offered_for_unhide_but_a_hidden_player_is(db):
    db.upsert_player("ben", hidden=True)
    guest = db.guest_name("carl", "club")
    assert db.hidden_players() == sorted(["ben", guest])
    assert db.listed_hidden_players() == ["ben"]


def test_a_guest_without_a_site_is_still_distinct(db):
    assert db.guest_name("carl", None) == "carl@unknown"


def test_a_guest_earns_no_achievements_and_a_local_player_does(db):
    engine = AchievementEngine(db, definitions=PILOT).attach()
    guest = db.guest_name("ana", "club")
    for match_id, player in (("m-guest", guest), ("m-local", "ana")):
        db.open_match(match_id, "X01", 501)
        db.insert_turn(match_id, player, 1, 1, 501, 180, False, False,
                       [("T20", 60, 441), ("T20", 60, 381), ("T20", 60, 321)])
        db.close_match(match_id)
    assert db.earned_for_player(guest) == []
    assert [r["achievement_id"] for r in db.earned_for_player("ana")] == ["ton_up"]


def test_a_guest_is_left_out_of_the_rankings_but_stays_in_the_match(db):
    guest = db.guest_name("carl", "club")
    db.upsert_player("ana")
    db.open_match("e1", "Elimination", 3)
    for player in ("ana", guest):
        db.insert_elimination_turn("e1", player, 3, score=60, target=0, freipass=True, passed=True, lives_before=3)
    db.record_elimination_result("e1", [("ana", 1, 2), (guest, 2, None)])
    db.close_match("e1")
    assert [m["players"] for m in db.recent_matches(mode="elimination")] == [["ana", "carl@club"]]
    assert "carl@club" in db.match_stats("e1")
    assert all(r["player"] != guest for r in db.all_players_stats())


def test_an_older_database_gets_the_guest_column(tmp_path):
    path = tmp_path / "old.db"
    conn = sqlite3.connect(path)
    conn.execute("CREATE TABLE players (name TEXT PRIMARY KEY, created_at TEXT NOT NULL, hidden INTEGER NOT NULL DEFAULT 0, color TEXT)")
    conn.execute("INSERT INTO players (name, created_at) VALUES ('ana', '2026-01-01')")
    conn.commit()
    conn.close()
    db = StatsDB(str(path))
    assert db._conn.execute("SELECT guest FROM players WHERE name = 'ana'").fetchone()[0] == 0
    assert db.guest_name("ben", "club") == "ben@club"
