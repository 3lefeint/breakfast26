"""Thin wrapper over StatsDB's `players` table.

Player identity lives in stats.db, shared with online/local X01 and
Elimination — this module just exposes the players/win-count slice of it
under the same names the web server and Elimination controller already
call, so `db=None` (stats disabled) degrades to an empty list/no wins
instead of every call site needing its own guard.

Every known player shows up by default (`hidden` is the only opt-out —
see `StatsDB.upsert_player`/`list_players`); there's no separate roster
concept to add/remove from any more.
"""


def load(db):
    return db.list_players() if db else []


def add(name, db):
    if db:
        db.upsert_player(name)
    return load(db)


def load_wins(db):
    return db.win_counts() if db else {}


def load_x01_wins(db):
    return db.x01_win_counts() if db else {}
