"""Copies of the statistics database taken before an update.

An update replaces the program, and a rollback only brings the old program back, so a migration the new
version made to `stats.db` would stay. A copy is taken first with SQLite's backup API (consistent while the
app runs) into `backups/` next to the database; the last few are kept. The Docker `updater` service has its own
small copy of this, see updater/app.py.
"""

import re
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

KEEP = 3


def backup_dir(db_path):
    return Path(db_path).parent / "backups"


def _pattern(db_path):
    return re.compile(rf"^{re.escape(Path(db_path).stem)}-v[\w.]+-\d{{8}}-\d{{6}}\.db$")


def backups(db_path):
    """The copies of this database, newest first."""
    directory = backup_dir(db_path)
    if not directory.is_dir():
        return []
    pattern = _pattern(db_path)
    return sorted((p for p in directory.iterdir() if pattern.match(p.name)), key=lambda p: p.name, reverse=True)


def backup(db_path, version, keep=KEEP, now=None):
    """Copy the database before the update from *version*. Returns the copy, None when there is no database file to
    copy (statistics switched off). Older copies beyond *keep* are deleted."""
    source = Path(db_path)
    if str(db_path) in ("", ":memory:") or not source.is_file():
        return None
    directory = backup_dir(db_path)
    directory.mkdir(exist_ok=True)
    stamp = (now or datetime.now(timezone.utc)).strftime("%Y%m%d-%H%M%S")
    target = directory / f"{source.stem}-v{version}-{stamp}.db"
    src = sqlite3.connect(f"file:{source}?mode=ro", uri=True)
    try:
        dst = sqlite3.connect(target)
        try:
            src.backup(dst)
        finally:
            dst.close()
    finally:
        src.close()
    for old in backups(db_path)[keep:]:
        old.unlink(missing_ok=True)
    return target


def latest(db_path):
    """{"file", "version", "at"} of the newest copy, None when there is none. `at` is the time the file was written."""
    found = backups(db_path)
    if not found:
        return None
    path = found[0]
    version = re.search(r"-v([\w.]+)-\d{8}-\d{6}\.db$", path.name).group(1)
    return {"file": path.name, "version": version,
            "at": datetime.fromtimestamp(path.stat().st_mtime, timezone.utc).isoformat(timespec="seconds")}
