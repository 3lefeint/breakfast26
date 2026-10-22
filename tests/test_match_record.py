import json

import pytest

from breakfast import achievements as ach
from breakfast.achievements import AchievementEngine
from breakfast.match_record import RECORD_VERSION, RecordError, deletion_record, export_record, import_record
from breakfast.stats import StatsDB

HOME = {"id": "loc-home", "name": "Home"}
POS = [{"x": 0.0, "y": 0.1, "entry": "board"}, {"x": 0.2, "y": 0.2, "entry": "board"}, None]


def _x01(db, match_id="m1", with_bot=True):
    """A finished X01 match: ana and ben, two legs, positions, a bot's turn."""
    db.open_match(match_id, "X01", 501)
    db.insert_turn(match_id, "ana", 1, 1, 501, 100, False, False, [("T20", 60, 441), ("S20", 20, 421), ("S20", 20, 401)],
                   positions=POS)
    db.insert_turn(match_id, "ben", 1, 1, 501, 26, False, False, [("S20", 20, 481), ("S5", 5, 476), ("S1", 1, 475)])
    db.insert_turn(match_id, "ana", 1, 2, 401, 401, False, True, [("T20", 60, 341), ("D20", 40, 301)])
    db.record_leg_win(match_id, 1, "ana")
    db.insert_turn(match_id, "ben", 2, 1, 501, 60, True, False, [("T20", 60, 441)])
    db.record_leg_win(match_id, 2, "ben", "bull_off")
    if with_bot:
        db.insert_bot_turn(match_id, "bot 3", 2, 1, 501, 41, False, False, [("S20", 20, 481), ("S20", 20, 461)],
                           positions=[{"x": 0.1, "y": 0.1}, None])
        db.mark_bot_match(match_id)
    db.set_winner(match_id, "ana")
    db.close_match(match_id)
    return match_id


def _elimination(db, match_id="e1"):
    db.open_match(match_id, "Elimination", 3)
    db.insert_elimination_turn(match_id, "ana", 3, score=60, target=0, freipass=True, passed=True, lives_before=3,
                               positions=[{"field": "T20", "x": 0.0, "y": 0.1, "entry": "board"}, None, None])
    db.insert_elimination_turn(match_id, "ben", 3, score=21, target=60, freipass=False, passed=False, lives_before=3,
                               positions=[{"field": "S20", "x": 0.2, "y": 0.0}])
    db.insert_elimination_turn(match_id, "ana", 3, score=100, target=21, freipass=False, passed=True, lives_before=3)
    db.record_elimination_result(match_id, [("ana", 1, 3), ("ben", 2, None)])
    db.set_winner(match_id, "ana")
    db.close_match(match_id)
    return match_id


def _rows(db, sql, *args):
    return [tuple(r) for r in db._conn.execute(sql, args)]


def test_the_revision_rises_with_every_close(db):
    db.open_match("m1", "X01", 501)
    assert db.match_row("m1")["match_id"] == "m1"
    assert _rows(db, "SELECT revision FROM matches")[0][0] == 0
    db.close_match("m1")
    assert _rows(db, "SELECT revision FROM matches")[0][0] == 1
    db.reopen_match("m1")
    db.close_match("m1")
    assert _rows(db, "SELECT revision FROM matches")[0][0] == 2


def test_an_x01_match_goes_through_a_record_unchanged(db, tmp_path):
    _x01(db)
    record = export_record(db, "m1", HOME)
    assert record["record_version"] == RECORD_VERSION and record["game_mode"] == "X01" and record["revision"] == 1
    assert record["origin"] == HOME and record["deleted"] is False
    json.dumps(record)                                       # a plain JSON document
    other = StatsDB(":memory:")
    assert import_record(other, record, mapping={"ana": "anna", "ben": "bernd"}) == {
        "status": "imported", "match_id": "m1", "revision": 1}
    mapped = {"ana": "anna", "ben": "bernd"}

    def renamed(summary):
        text = json.dumps(summary)
        for old, new in mapped.items():
            text = text.replace(f'"{old}"', f'"{new}"')
        return json.loads(text)
    assert other.x01_match_summary("m1") == renamed(db.x01_match_summary("m1"))
    assert other.session_stats("m1") == {mapped[k]: v for k, v in db.session_stats("m1").items()}
    assert _rows(other, "SELECT winner, has_bot, revision, origin_id, origin_name, tournament_id FROM matches") == [
        ("anna", 1, 1, "loc-home", "Home", None)]
    assert _rows(other, "SELECT leg, winner, decided FROM legs ORDER BY leg") == [(1, "anna", None), (2, "bernd", "bull_off")]
    assert _rows(other, "SELECT player, leg, turn, dart_number, x, y FROM dart_positions ORDER BY id") == [
        ("anna", 1, 1, 1, 0.0, 0.1), ("anna", 1, 1, 2, 0.2, 0.2)]
    assert _rows(other, "SELECT player, positions FROM bot_turns")[0][0] == "bot 3"


def test_an_elimination_match_goes_through_a_record_unchanged(db):
    _elimination(db)
    record = export_record(db, "e1", HOME)
    other = StatsDB(":memory:")
    assert import_record(other, record, mapping={"ana": "ana", "ben": "ben"})["status"] == "imported"
    assert other.match_stats("e1") == db.match_stats("e1")
    assert _rows(other, "SELECT player, score, target, freipass, passed, lives_before FROM elimination_turns ORDER BY id") == \
        _rows(db, "SELECT player, score, target, freipass, passed, lives_before FROM elimination_turns ORDER BY id")
    assert _rows(other, "SELECT player, turn, dart_number, field, x, y FROM dart_positions ORDER BY id") == \
        _rows(db, "SELECT player, turn, dart_number, field, x, y FROM dart_positions ORDER BY id")
    assert _rows(other, "SELECT player, placement, lives_left FROM elimination_results ORDER BY placement") == \
        [("ana", 1, 3), ("ben", 2, None)]


def test_players_without_a_mapping_become_guests_and_a_mapped_one_counts(db):
    _x01(db, with_bot=False)
    record = export_record(db, "m1", HOME)
    other = StatsDB(":memory:")
    import_record(other, record, mapping={"ana": "anna"})
    names = {r[0] for r in _rows(other, "SELECT player FROM turns")}
    assert names == {"anna", "ben@home"}
    assert _rows(other, "SELECT hidden, guest FROM players WHERE name = 'ben@home'") == [(1, 1)]
    assert _rows(other, "SELECT hidden, guest FROM players WHERE name = 'anna'") == [(0, 0)]
    assert [r["player"] for r in other.all_players_stats()] == ["anna"]
    assert json.loads(_rows(other, "SELECT players FROM matches")[0][0]) == ["anna", "ben@home"]


def test_a_record_of_the_same_or_an_older_revision_is_skipped_and_a_newer_one_replaces(db):
    _x01(db)
    record = export_record(db, "m1", HOME)
    other = StatsDB(":memory:")
    import_record(other, record)
    assert import_record(other, record)["status"] == "skipped"
    db.reopen_match("m1")
    db.insert_turn("m1", "ana", 3, 1, 501, 180, False, False, [("T20", 60, 441), ("T20", 60, 381), ("T20", 60, 321)])
    db.close_match("m1")
    newer = export_record(db, "m1", HOME)
    assert newer["revision"] == 2
    assert import_record(other, newer) == {"status": "replaced", "match_id": "m1", "revision": 2}
    assert _rows(other, "SELECT COUNT(*) FROM turns") == _rows(db, "SELECT COUNT(*) FROM turns")
    assert import_record(other, record)["status"] == "skipped"        # the old one does not bring the match back
    assert _rows(other, "SELECT revision FROM matches") == [(2,)]


def test_a_match_played_here_is_never_touched_by_an_import(db):
    _x01(db)
    record = export_record(db, "m1", HOME)
    record = {**record, "revision": 9}
    assert import_record(db, record)["status"] == "ignored"
    assert import_record(db, deletion_record("m1", "X01", HOME, 9))["status"] == "ignored"
    assert _rows(db, "SELECT revision, origin_id FROM matches") == [(1, None)]


def test_an_imported_match_is_not_exported_again(db):
    _x01(db)
    other = StatsDB(":memory:")
    import_record(other, export_record(db, "m1", HOME))
    with pytest.raises(RecordError, match="imported"):
        export_record(other, "m1", {"id": "loc-b"})


def test_a_deletion_record_deletes_an_imported_match(db):
    _x01(db)
    other = StatsDB(":memory:")
    import_record(other, export_record(db, "m1", HOME))
    assert import_record(other, deletion_record("m1", "X01", HOME, 1))["status"] == "deleted"
    assert _rows(other, "SELECT COUNT(*) FROM matches") == [(0,)] and _rows(other, "SELECT COUNT(*) FROM turns") == [(0,)]
    assert import_record(other, deletion_record("m1", "X01", HOME, 1))["status"] == "ignored"
    assert import_record(other, export_record(db, "m1", HOME))["status"] == "imported"     # it can come again


def test_an_unfinished_unknown_or_unsupported_match_cannot_be_exported(db):
    db.open_match("open", "X01", 501)
    db.open_match("kill", "Killer", 3)
    db.close_match("kill")
    for match_id, text in (("open", "not finished"), ("nope", "unknown"), ("kill", "Killer")):
        with pytest.raises(RecordError, match=text):
            export_record(db, match_id, HOME)
    with pytest.raises(RecordError, match="origin"):
        export_record(db, "open", {})


@pytest.mark.parametrize("change, text", [
    ({"record_version": RECORD_VERSION + 1}, "newer version"),
    ({"record_version": None}, "version"),
    ({"game_mode": "Cricket"}, "Cricket"),
    ({"match_id": ""}, "match id"),
    ({"revision": "1"}, "revision"),
    ({"origin": {}}, "origin"),
    ({"match": None}, "content"),
])
def test_a_record_that_cannot_be_read_is_refused(db, change, text):
    _x01(db)
    record = {**export_record(db, "m1", HOME), **change}
    with pytest.raises(RecordError, match=text):
        import_record(StatsDB(":memory:"), record)
    with pytest.raises(RecordError):
        import_record(StatsDB(":memory:"), "not a record")


def test_an_imported_match_does_not_earn_achievements(db):
    other = StatsDB(":memory:")
    engine = AchievementEngine(other, definitions=tuple(ach.BY_ID[i] for i in ("ton_up",))).attach()
    db.open_match("m1", "X01", 501)
    db.insert_turn("m1", "ana", 1, 1, 501, 180, False, False, [("T20", 60, 441), ("T20", 60, 381), ("T20", 60, 321)])
    db.close_match("m1")
    import_record(other, export_record(db, "m1", HOME), mapping={"ana": "anna"})
    assert other.earned_for_player("anna") == [] and engine is not None


def test_a_database_without_the_record_columns_gets_them(tmp_path):
    import sqlite3
    path = tmp_path / "old.db"
    conn = sqlite3.connect(path)
    conn.execute("CREATE TABLE matches (match_id TEXT PRIMARY KEY, started_at TEXT NOT NULL, ended_at TEXT, game_mode TEXT,"
                 " points_start INTEGER, players TEXT)")
    conn.execute("INSERT INTO matches (match_id, started_at, ended_at, game_mode) VALUES ('a', 'x', 'y', 'X01'), ('b', 'x', NULL, 'X01')")
    conn.commit()
    conn.close()
    db = StatsDB(str(path))
    assert _rows(db, "SELECT match_id, revision, origin_id FROM matches ORDER BY match_id") == [("a", 1, None), ("b", 0, None)]
