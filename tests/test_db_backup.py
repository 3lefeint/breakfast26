import sqlite3
from datetime import datetime, timezone

from breakfast import db_backup
from breakfast.stats import StatsDB


def make_db(path):
    db = StatsDB(str(path))
    db.upsert_player("ana")
    return db


def at(second):
    return datetime(2026, 10, 19, 4, 0, second, tzinfo=timezone.utc)


def test_the_copy_holds_what_the_database_holds(tmp_path):
    path = tmp_path / "stats.db"
    make_db(path)
    copy = db_backup.backup(path, "1.5.0", now=at(0))
    assert copy == tmp_path / "backups" / "stats-v1.5.0-20261019-040000.db"
    assert sqlite3.connect(copy).execute("SELECT name FROM players").fetchall() == [("ana",)]


def test_only_the_last_three_are_kept(tmp_path):
    path = tmp_path / "stats.db"
    make_db(path)
    for second in range(5):
        db_backup.backup(path, "1.5.0", now=at(second))
    names = [p.name for p in db_backup.backups(path)]
    assert names == [f"stats-v1.5.0-2026101{9}-04000{s}.db" for s in (4, 3, 2)]


def test_other_files_in_the_folder_are_left_alone(tmp_path):
    path = tmp_path / "stats.db"
    make_db(path)
    (tmp_path / "backups").mkdir()
    (tmp_path / "backups" / "notes.txt").write_text("mine")
    for second in range(5):
        db_backup.backup(path, "1.5.0", now=at(second))
    assert (tmp_path / "backups" / "notes.txt").read_text() == "mine"


def test_there_is_nothing_to_copy_without_a_database_file(tmp_path):
    assert db_backup.backup(tmp_path / "missing.db", "1.5.0") is None
    assert db_backup.backup(":memory:", "1.5.0") is None
    assert db_backup.latest(tmp_path / "missing.db") is None


def test_latest_tells_version_and_time(tmp_path):
    path = tmp_path / "stats.db"
    make_db(path)
    db_backup.backup(path, "1.4.0", now=at(1))
    db_backup.backup(path, "1.5.0", now=at(2))
    latest = db_backup.latest(path)
    assert latest["file"] == "stats-v1.5.0-20261019-040002.db" and latest["version"] == "1.5.0" and latest["at"]
