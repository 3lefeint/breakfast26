import json
import os
import sqlite3

import pytest
from starlette.testclient import TestClient

from breakfast import names
from breakfast import voicepack_overlay as vo
from breakfast.field_training import FieldTrainingController
from breakfast.stats import StatsDB, StatsTracker
from breakfast.web import server
from tests.test_target_battle import FakeMqttPub


def test_a_name_is_stripped_and_lower_case():
    assert names.normalize("  Dora ") == "dora"
    assert names.normalize("BÄR") == "bär"
    assert names.normalize(None) is None
    assert names.normalize_all([" Ana", "BEN"]) == ["ana", "ben"]


def test_the_names_of_an_mqtt_command_are_normalised():
    cmd = names.normalize_command({"action": "start", "players": ["Ana", " BEN "], "player": "Cy", "name": "Di", "lives": 3})
    assert cmd == {"action": "start", "players": ["ana", "ben"], "player": "cy", "name": "di", "lives": 3}


def test_a_start_command_over_mqtt_starts_with_the_lower_case_name(db):
    ctrl = FieldTrainingController(FakeMqttPub(), "autodarts", stats_db=db)
    ctrl._handle_command(json.dumps({"action": "start", "player": "Ana", "field": 20, "darts": 6}))
    assert ctrl.game.player == "ana"


@pytest.fixture
def client(tmp_path):
    db = StatsDB(str(tmp_path / "s.db"))
    ft = FieldTrainingController(FakeMqttPub(), "autodarts", stats_db=db)
    server.wire(None, None, stats_tracker=StatsTracker(db), ft_ctrl=ft)
    yield TestClient(server.app), db, ft
    server.wire(None, None)


def test_a_player_added_over_rest_is_stored_in_lower_case(client):
    http, db, _ = client
    assert http.post("/api/players", json={"name": " Dora "}).json() == ["dora"]
    assert db.list_players() == ["dora"]


def test_a_game_started_over_rest_uses_lower_case_names(client):
    http, _, ft = client
    http.post("/api/field-training/start", json={"player": "Ana", "field": 20, "darts": 6})
    assert ft.game.player == "ana"


def test_names_from_the_board_service_are_stored_in_lower_case(db, tracker):
    tracker.process({"event": "match-started", "id": "m1", "game": {"mode": "X01", "pointsStart": 501}})
    tracker.process({"event": "dart1-thrown", "player": "Ana", "game": {"dartValue": 60, "pointsLeft": 441, "fieldName": "T20"}})
    tracker.process({"event": "darts-pulled", "player": "Ana", "game": {}})
    assert db.match_participants("m1") == ["ana"]


# ── the one-time change of an older database ──────────────────────────────────

def _old_db(path):
    """A database as an older version made it: names as they were typed."""
    db = StatsDB(str(path))
    for name in ("Anna", "Ben", "ben", "Carl"):
        db._conn.execute("INSERT OR IGNORE INTO players (name, created_at, hidden) VALUES (?, '2026-01-01', ?)",
                         (name, 1 if name == "Carl" else 0))
    db._conn.commit()
    return db


def _match(db, match_id, players, winner=None):
    db.open_match(match_id, "X01", 501)
    for i, player in enumerate(players, 1):
        db.insert_turn(match_id, player, 1, i, 501, 60, False, False, [("T20", 60, 441)])
    if winner:
        db.record_leg_win(match_id, 1, winner)
        db.set_winner(match_id, winner)
    db.close_match(match_id)


def _stored_names(path):
    conn = sqlite3.connect(path)
    try:
        return {r[0] for r in conn.execute("SELECT name FROM players")}, {r[0] for r in conn.execute("SELECT player FROM turns")}
    finally:
        conn.close()


def test_old_names_are_changed_to_lower_case_at_the_start(tmp_path):
    path = tmp_path / "s.db"
    db = _old_db(path)
    _match(db, "m1", ["Anna", "Carl"], winner="Anna")
    db._conn.execute("INSERT INTO achievements_earned (player, achievement_id, tier, earned_at, match_id)"
                     " VALUES ('Anna', 'a', 0, 'now', 'm1')")
    db._conn.execute("UPDATE players SET color = '#aabbcc' WHERE name = 'Anna'")
    db._conn.commit()
    db._conn.close()

    db = StatsDB(str(path))
    players, turn_names = _stored_names(path)
    assert players == {"anna", "ben", "carl"}
    assert turn_names == {"anna", "carl"}
    assert db._conn.execute("SELECT winner FROM matches").fetchone()[0] == "anna"
    assert db._conn.execute("SELECT winner FROM legs").fetchone()[0] == "anna"
    assert json.loads(db._conn.execute("SELECT players FROM matches").fetchone()[0]) == ["anna", "carl"]
    assert db._conn.execute("SELECT player FROM achievements_earned").fetchone()[0] == "anna"
    row = db._conn.execute("SELECT color FROM players WHERE name = 'anna'").fetchone()
    assert row[0] == "#aabbcc"
    assert db._conn.execute("SELECT hidden FROM players WHERE name = 'carl'").fetchone()[0] == 1
    assert [f for f in os.listdir(tmp_path) if ".before-lowercase-" in f]


def test_players_that_differ_only_in_case_are_merged(tmp_path):
    path = tmp_path / "s.db"
    db = _old_db(path)
    _match(db, "m1", ["Ben", "Anna"], winner="Ben")
    _match(db, "m2", ["ben", "Carl"], winner="ben")
    db._conn.execute("INSERT INTO achievements_earned (player, achievement_id, tier, earned_at, match_id)"
                     " VALUES ('Ben', 'a', 0, '2026-02-01', 'm1'), ('ben', 'a', 0, '2026-03-01', 'm2')")
    db._conn.commit()
    db._conn.close()

    db = StatsDB(str(path))
    assert _stored_names(path)[0] == {"anna", "ben", "carl"}
    assert {r[0] for r in db._conn.execute("SELECT player FROM turns WHERE match_id IN ('m1', 'm2')")} == {"ben", "anna", "carl"}
    achievements = db._conn.execute("SELECT player, earned_at FROM achievements_earned").fetchall()
    assert [tuple(r) for r in achievements] == [("ben", "2026-02-01")]


def test_a_pair_that_played_in_the_same_match_is_left_alone(tmp_path, caplog):
    path = tmp_path / "s.db"
    db = _old_db(path)
    _match(db, "m1", ["Ben", "ben"])
    db._conn.close()
    with caplog.at_level("WARNING"):
        db = StatsDB(str(path))
    assert {r[0] for r in db._conn.execute("SELECT player FROM turns")} == {"Ben", "ben"}
    assert "same match" in caplog.text


def test_brackets_and_saved_matches_follow(tmp_path):
    path = tmp_path / "s.db"
    db = _old_db(path)
    db.save_tournament("t1", "finished", {"players": ["Anna", "Carl"]})
    db.save_running_match("X01", {"match_id": "m9", "players": ["Anna", "Carl"]})
    db._conn.close()
    db = StatsDB(str(path))
    assert json.loads(db._conn.execute("SELECT data FROM tournaments").fetchone()[0]) == {"players": ["anna", "carl"]}
    assert db.running_matches()["X01"]["data"]["players"] == ["anna", "carl"]


def test_a_database_in_lower_case_is_not_touched_again(tmp_path):
    path = tmp_path / "s.db"
    db = _old_db(path)
    db._conn.close()
    StatsDB(str(path))
    first = sorted(os.listdir(tmp_path))
    StatsDB(str(path))
    assert sorted(os.listdir(tmp_path)) == first


# ── the private voice-pack files ──────────────────────────────────────────────

OVERLAY = """# Private player names
[group.keys]
[group.keys.Anna]
variants = ["Anna", "Annie"]

[group.keys."Bär"]
variants = ["Bär"]

[group.keys.ben]
variants = ["Ben"]
"""


def test_the_keys_of_a_private_file_become_lower_case(tmp_path):
    file = tmp_path / "leni.toml"
    file.write_text(OVERLAY, encoding="utf-8")
    assert vo.lowercase_keys(file) == {"Anna": "anna", "Bär": "bär"}
    entries = vo.read_entries(file)
    assert set(entries) == {"anna", "bär", "ben"} and entries["anna"]["variants"] == ["Anna", "Annie"]
    assert file.read_text(encoding="utf-8").startswith("# Private player names")
    assert vo.lowercase_keys(file) == {}
    assert vo.lowercase_keys(tmp_path / "none.toml") == {}


def test_a_key_with_a_lower_case_twin_is_dropped(tmp_path):
    file = tmp_path / "leni.toml"
    file.write_text('[group.keys]\n[group.keys.Ben]\nvariants = ["Upper"]\n[group.keys.ben]\nvariants = ["Lower"]\n')
    assert vo.lowercase_keys(file) == {"Ben": "ben"}
    assert vo.read_entries(file) == {"ben": {"variants": ["Lower"]}}


def test_the_voice_files_of_renamed_keys_are_renamed(tmp_path):
    for name in ("Anna.mp3", "Anna+1.mp3", "Annabelle.mp3", "Ben.mp3", "ben.mp3"):
        (tmp_path / name).write_bytes(b"x")
    done = vo.rename_sound_files(tmp_path, {"Anna": "anna", "Ben": "ben"})
    assert sorted(done) == ["anna+1.mp3", "anna.mp3"]
    assert sorted(os.listdir(tmp_path)) == ["Annabelle.mp3", "Ben.mp3", "anna+1.mp3", "anna.mp3", "ben.mp3"]


def test_starting_the_server_changes_the_private_files_and_voice_files(tmp_path):
    (tmp_path / "voicepack").mkdir()
    (tmp_path / "voicepack" / "leni.toml").write_text(OVERLAY, encoding="utf-8")
    profile = tmp_path / "sounds" / "profiles" / "leni"
    profile.mkdir(parents=True)
    (profile / "Anna.mp3").write_bytes(b"x")
    config = tmp_path / "config.toml"
    config.write_text(f'[audio]\ndir = "{tmp_path / "sounds"}"\n')
    server.wire(None, None, config_path=str(config))
    try:
        assert set(vo.read_entries(tmp_path / "voicepack" / "leni.toml")) == {"anna", "bär", "ben"}
        assert os.listdir(profile) == ["anna.mp3"]
    finally:
        server.wire(None, None)
