"""Statistics: SQLite persistence + in-memory session stats.

Only X01 / Random Checkout turns are tracked (per-dart data requires the
dart1/2/3-thrown events that only X01 emits).
"""

import json
import logging
import sqlite3
import threading
from datetime import datetime, timezone

log = logging.getLogger(__name__)

_SCHEMA = """
CREATE TABLE IF NOT EXISTS matches (
    match_id   TEXT PRIMARY KEY,
    started_at TEXT NOT NULL,
    ended_at   TEXT,
    game_mode  TEXT,
    points_start INTEGER,
    players    TEXT
);
CREATE TABLE IF NOT EXISTS turns (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    match_id         TEXT    NOT NULL,
    player           TEXT    NOT NULL,
    leg              INTEGER NOT NULL DEFAULT 1,
    turn             INTEGER NOT NULL,
    remaining_before INTEGER NOT NULL,
    score            INTEGER NOT NULL DEFAULT 0,
    is_bust          INTEGER NOT NULL DEFAULT 0,
    is_checkout      INTEGER NOT NULL DEFAULT 0,
    darts_count      INTEGER NOT NULL DEFAULT 0,
    dart1     TEXT, dart1_val INTEGER, dart1_rem INTEGER,
    dart2     TEXT, dart2_val INTEGER, dart2_rem INTEGER,
    dart3     TEXT, dart3_val INTEGER, dart3_rem INTEGER,
    FOREIGN KEY (match_id) REFERENCES matches(match_id)
);
CREATE TABLE IF NOT EXISTS legs (
    id       INTEGER PRIMARY KEY AUTOINCREMENT,
    match_id TEXT NOT NULL,
    leg      INTEGER NOT NULL,
    winner   TEXT
);
CREATE TABLE IF NOT EXISTS players (
    name       TEXT PRIMARY KEY,
    created_at TEXT NOT NULL,
    hidden     INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS elimination_results (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    match_id   TEXT NOT NULL,
    player     TEXT NOT NULL,
    placement  INTEGER NOT NULL,
    lives_left INTEGER,
    UNIQUE(match_id, player)
);
CREATE TABLE IF NOT EXISTS elimination_turns (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    match_id    TEXT NOT NULL,
    player      TEXT NOT NULL,
    darts_count INTEGER NOT NULL,
    score       INTEGER,
    target      INTEGER,
    freipass    INTEGER,
    passed      INTEGER,
    lives_before INTEGER
);
CREATE INDEX IF NOT EXISTS idx_turns_player ON turns (player);
CREATE INDEX IF NOT EXISTS idx_turns_match  ON turns (match_id);
CREATE INDEX IF NOT EXISTS idx_legs_match   ON legs  (match_id);
CREATE INDEX IF NOT EXISTS idx_elim_results_match ON elimination_results (match_id);
CREATE INDEX IF NOT EXISTS idx_elim_turns_match   ON elimination_turns   (match_id);
"""


# Which per-turn tables feed a stat for each mode: "all" is both game modes
# together, "x01" and "elimination" are one each.
_TURN_TABLES = {"all": ("turns", "elimination_turns"), "x01": ("turns",), "elimination": ("elimination_turns",)}


# A match counts as "solo" (practice, no opponent) when exactly one distinct
# player ever appears in its `turns` rows — Elimination is excluded here
# since EliminationController.start() already refuses fewer than 2 players,
# so this predicate only ever matches X01. Shared by every query that must
# not let solo sessions inflate competitive win/loss stats.
_SOLO_X01_SQL = (
    "m.game_mode != 'Elimination' AND "
    "(SELECT COUNT(DISTINCT player) FROM turns WHERE turns.match_id = m.match_id) <= 1"
)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _safe_name(raw) -> str | None:
    if isinstance(raw, str):
        return raw
    if isinstance(raw, dict):
        return raw.get("name") or str(raw)
    return str(raw) if raw is not None else None


# ── Database ──────────────────────────────────────────────────────────────────

class StatsDB:
    def __init__(self, path: str):
        self._conn = sqlite3.connect(path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._lock = threading.Lock()
        with self._lock:
            self._conn.executescript(_SCHEMA)
            self._migrate_matches_winner()
            self._migrate_elimination_turn_details()
            self._migrate_backfill_x01_winner()
            self._migrate_drop_in_roster()
            self._conn.commit()
        log.info("Stats DB: %s", path)

    def _migrate_matches_winner(self):
        """CREATE TABLE IF NOT EXISTS matches doesn't add columns to an
        already-existing DB file, so `winner` needs an explicit migration."""
        cols = {r["name"] for r in self._conn.execute("PRAGMA table_info(matches)")}
        if "winner" not in cols:
            self._conn.execute("ALTER TABLE matches ADD COLUMN winner TEXT")

    def _migrate_elimination_turn_details(self):
        """Turns recorded before the per-turn details existed keep NULL in the new
        columns; only the darts count is known for them."""
        cols = {r["name"] for r in self._conn.execute("PRAGMA table_info(elimination_turns)")}
        for name in ("score", "target", "freipass", "passed", "lives_before"):
            if name not in cols:
                self._conn.execute(f"ALTER TABLE elimination_turns ADD COLUMN {name} INTEGER")

    def _migrate_backfill_x01_winner(self):
        """`matches.winner` was only ever written by elimination.py — X01
        matches never got one at all until StatsTracker.process()'s
        "match-won" handler started calling set_winner() too. Backfill
        existing X01 matches from `legs` (the winner of a match's last
        leg is its match winner, since a match ends exactly when someone
        reaches the required leg count) so pre-existing history isn't
        silently missing from x01_win_counts()."""
        rows = self._conn.execute(
            "SELECT match_id FROM matches WHERE winner IS NULL AND game_mode != 'Elimination'"
        ).fetchall()
        for r in rows:
            last_leg = self._conn.execute(
                "SELECT winner FROM legs WHERE match_id = ? AND winner IS NOT NULL"
                " ORDER BY leg DESC LIMIT 1",
                (r["match_id"],),
            ).fetchone()
            if last_leg:
                self._conn.execute(
                    "UPDATE matches SET winner = ? WHERE match_id = ?",
                    (last_leg["winner"], r["match_id"]),
                )

    def _migrate_drop_in_roster(self):
        """Old on-disk DBs (from before a schema cleanup) still physically carry
        the now-unused `in_roster` column. DROP COLUMN needs SQLite >= 3.35.0
        (2021) — guard on version and swallow any failure so an old SQLite
        build just leaves the column in place instead of crashing __init__."""
        cols = {r["name"] for r in self._conn.execute("PRAGMA table_info(players)")}
        if "in_roster" not in cols:
            return
        if sqlite3.sqlite_version_info < (3, 35, 0):
            log.info("Stats DB: sqlite %s < 3.35.0, leaving dead in_roster column in place",
                      sqlite3.sqlite_version)
            return
        try:
            self._conn.execute("ALTER TABLE players DROP COLUMN in_roster")
        except sqlite3.OperationalError:
            log.info("Stats DB: DROP COLUMN in_roster failed despite sqlite %s, leaving it in place",
                      sqlite3.sqlite_version)

    def open_match(self, match_id: str, game_mode: str, points_start: int):
        log.debug("DB write: open_match match_id=%s game_mode=%s points_start=%s",
                  match_id, game_mode, points_start)
        with self._lock:
            self._conn.execute(
                "INSERT OR IGNORE INTO matches (match_id, started_at, game_mode, points_start)"
                " VALUES (?, ?, ?, ?)",
                (match_id, _now_iso(), game_mode, points_start),
            )
            self._conn.commit()

    def close_match(self, match_id: str):
        with self._lock:
            players = [
                r[0] for r in self._conn.execute(
                    "SELECT DISTINCT player FROM turns WHERE match_id = ?"
                    " UNION SELECT DISTINCT player FROM elimination_turns WHERE match_id = ?",
                    (match_id, match_id),
                ).fetchall()
            ]
            log.debug("DB write: close_match match_id=%s players=%s", match_id, players)
            self._conn.execute(
                "UPDATE matches SET ended_at = ?, players = ? WHERE match_id = ?",
                (_now_iso(), json.dumps(players), match_id),
            )
            self._conn.commit()

    def set_winner(self, match_id: str, winner: str | None):
        log.debug("DB write: set_winner match_id=%s winner=%s", match_id, winner)
        with self._lock:
            self._conn.execute(
                "UPDATE matches SET winner = ? WHERE match_id = ?", (winner, match_id)
            )
            self._conn.commit()

    # ── Players ───────────────────────────────────────────────────────────────

    def upsert_player(self, name: str, hidden: bool | None = None):
        log.debug("DB write: upsert_player name=%s hidden=%s", name, hidden)
        with self._lock:
            self._ensure_player(name)
            if hidden is not None:
                self._conn.execute(
                    "UPDATE players SET hidden = ? WHERE name = ?", (int(hidden), name)
                )
            self._conn.commit()

    def list_players(self) -> list:
        """Every known player, shown by default in the Players tab /
        Elimination picker — `hidden` is the only opt-out mechanism.
        Always alphabetical — insertion order was confusing and
        there's no manual-ordering feature anywhere in the app to preserve."""
        with self._lock:
            rows = self._conn.execute(
                "SELECT name FROM players WHERE hidden = 0 ORDER BY name COLLATE NOCASE"
            ).fetchall()
        return [r["name"] for r in rows]

    def hidden_players(self) -> list:
        """Names excluded from leaderboard()/all_players_stats() — the
        "Unhide" list, since a hidden name by definition no longer
        shows up in those views itself."""
        with self._lock:
            rows = self._conn.execute(
                "SELECT name FROM players WHERE hidden = 1 ORDER BY name"
            ).fetchall()
        return [r["name"] for r in rows]

    def win_counts(self) -> dict:
        with self._lock:
            rows = self._conn.execute(
                "SELECT player, COUNT(*) as n FROM elimination_results"
                " WHERE placement = 1 GROUP BY player"
            ).fetchall()
        return {r["player"]: r["n"] for r in rows}

    def x01_win_counts(self) -> dict:
        """Excludes solo (single-player/practice) X01 matches — see
        `_is_solo_x01()`: a session with no opponent isn't a
        competitive win and shouldn't feed the leaderboard/win badges."""
        with self._lock:
            rows = self._conn.execute(
                "SELECT winner as player, COUNT(*) as n FROM matches m"
                " WHERE winner IS NOT NULL AND game_mode != 'Elimination'"
                f" AND NOT ({_SOLO_X01_SQL})"
                " GROUP BY winner"
            ).fetchall()
        return {r["player"]: r["n"] for r in rows}

    # ── Elimination ───────────────────────────────────────────────────────────

    def record_elimination_result(self, match_id: str, results: list):
        """results: list of (player, placement, lives_left) — lives_left is
        None for eliminated players, the winner's remaining lives otherwise."""
        log.debug("DB write: record_elimination_result match_id=%s results=%s",
                  match_id, results)
        with self._lock:
            for player, placement, lives_left in results:
                self._ensure_player(player)
                self._conn.execute(
                    "INSERT OR IGNORE INTO elimination_results"
                    " (match_id, player, placement, lives_left) VALUES (?, ?, ?, ?)",
                    (match_id, player, placement, lives_left),
                )
            self._conn.commit()

    def delete_elimination_results(self, match_id: str):
        """Un-record everything record_elimination_result() wrote for a
        match — used when undoing a match finish so a later
        re-finish doesn't silently no-op against the old rows'
        UNIQUE(match_id, player) constraint."""
        log.debug("DB write: delete_elimination_results match_id=%s", match_id)
        with self._lock:
            self._conn.execute(
                "DELETE FROM elimination_results WHERE match_id = ?", (match_id,)
            )
            self._conn.commit()

    def delete_last_elimination_turn(self, match_id: str, player: str):
        """Remove the most recently inserted elimination_turns row for one
        player in one match — undoes insert_elimination_turn()'s write for
        the turn being walked back."""
        log.debug("DB write: delete_last_elimination_turn match_id=%s player=%s",
                  match_id, player)
        with self._lock:
            row = self._conn.execute(
                "SELECT id FROM elimination_turns WHERE match_id = ? AND player = ?"
                " ORDER BY id DESC LIMIT 1",
                (match_id, player),
            ).fetchone()
            if row:
                self._conn.execute(
                    "DELETE FROM elimination_turns WHERE id = ?", (row["id"],)
                )
                self._conn.commit()

    def reopen_match(self, match_id: str):
        """Clear `ended_at` — undoing a match finish walks the
        match back to `state == "playing"`, so it shouldn't still look
        closed."""
        log.debug("DB write: reopen_match match_id=%s", match_id)
        with self._lock:
            self._conn.execute(
                "UPDATE matches SET ended_at = NULL WHERE match_id = ?", (match_id,)
            )
            self._conn.commit()

    def insert_elimination_turn(self, match_id: str, player: str, darts_count: int,
                                score: int | None = None, target: int | None = None,
                                freipass: bool | None = None, passed: bool | None = None,
                                lives_before: int | None = None):
        """`target` is the score this turn had to beat (0 on a freipass), `passed`
        whether it did, `lives_before` the player's lives going into the turn."""
        log.debug("DB write: insert_elimination_turn match_id=%s player=%s darts_count=%s "
                  "score=%s target=%s freipass=%s passed=%s lives_before=%s",
                  match_id, player, darts_count, score, target, freipass, passed, lives_before)
        with self._lock:
            self._ensure_player(player)
            self._conn.execute(
                "INSERT INTO elimination_turns"
                " (match_id, player, darts_count, score, target, freipass, passed, lives_before)"
                " VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (match_id, player, darts_count, score, target,
                 None if freipass is None else int(freipass),
                 None if passed is None else int(passed), lives_before),
            )
            self._conn.commit()

    def correct_last_elimination_turn(self, match_id: str, player: str, score: int, passed: bool):
        """A finished turn's total was corrected: rewrite the score and whether it
        passed on the player's most recent recorded turn."""
        log.debug("DB write: correct_last_elimination_turn match_id=%s player=%s score=%s passed=%s",
                  match_id, player, score, passed)
        with self._lock:
            self._conn.execute(
                "UPDATE elimination_turns SET score = ?, passed = ? WHERE id = ("
                " SELECT id FROM elimination_turns WHERE match_id = ? AND player = ?"
                " ORDER BY id DESC LIMIT 1)",
                (score, int(passed), match_id, player),
            )
            self._conn.commit()

    def _ensure_player(self, name):
        """Auto-link a name into the `players` identity table. Must be called
        from within a block that already holds `self._lock` — this method
        does not acquire it itself (the lock isn't reentrant)."""
        log.debug("DB write: ensure_player name=%s", name)
        self._conn.execute(
            "INSERT OR IGNORE INTO players (name, created_at) VALUES (?, ?)",
            (name, _now_iso()),
        )

    def insert_turn(self, match_id, player, leg, turn, remaining_before,
                    score, is_bust, is_checkout, darts):
        """darts: list of (field_str, value_int, remaining_after_int), up to 3 entries."""
        d = [darts[i] if i < len(darts) else (None, None, None) for i in range(3)]
        log.debug(
            "DB write: insert_turn match_id=%s player=%s leg=%s turn=%s "
            "remaining_before=%s score=%s is_bust=%s is_checkout=%s darts=%s",
            match_id, player, leg, turn, remaining_before, score, is_bust, is_checkout, darts,
        )
        with self._lock:
            self._ensure_player(player)
            self._conn.execute(
                "INSERT INTO turns "
                "(match_id, player, leg, turn, remaining_before, score,"
                " is_bust, is_checkout, darts_count,"
                " dart1, dart1_val, dart1_rem,"
                " dart2, dart2_val, dart2_rem,"
                " dart3, dart3_val, dart3_rem)"
                " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (match_id, player, leg, turn, remaining_before, score,
                 int(is_bust), int(is_checkout), len(darts),
                 d[0][0], d[0][1], d[0][2],
                 d[1][0], d[1][1], d[1][2],
                 d[2][0], d[2][1], d[2][2]),
            )
            self._conn.commit()

    # ── Queries ───────────────────────────────────────────────────────────────

    def session_stats(self, match_id: str) -> dict:
        """Per-player stats dict for one match (queried from DB)."""
        with self._lock:
            rows = self._conn.execute("""
                SELECT player,
                    COUNT(*) as turns,
                    SUM(score) as total_score,
                    SUM(darts_count) as total_darts,
                    SUM(CASE WHEN score = 180 THEN 1 ELSE 0 END) as s180,
                    SUM(CASE WHEN score >= 140 AND score < 180 THEN 1 ELSE 0 END) as s140,
                    SUM(CASE WHEN score >= 100 AND score < 140 THEN 1 ELSE 0 END) as s100,
                    SUM(CASE WHEN remaining_before <= 170 THEN 1 ELSE 0 END) as co_attempts,
                    SUM(is_checkout) as co_hits
                FROM turns WHERE match_id = ?
                GROUP BY player
            """, (match_id,)).fetchall()
        return {r["player"]: _row_stats(r) for r in rows}

    def all_players_stats(self) -> list:
        """Lifetime stats for every player that has ever played, excluding
        players flagged `hidden` (comparison/leaderboard views only — a
        direct player_stats() lookup still works for a hidden player)."""
        with self._lock:
            rows = self._conn.execute("""
                SELECT t.player as player,
                    COUNT(DISTINCT t.match_id) as sessions,
                    COUNT(*) as turns,
                    SUM(t.score) as total_score,
                    SUM(t.darts_count) as total_darts,
                    SUM(CASE WHEN t.score = 180 THEN 1 ELSE 0 END) as s180,
                    SUM(CASE WHEN t.score >= 140 AND t.score < 180 THEN 1 ELSE 0 END) as s140,
                    SUM(CASE WHEN t.score >= 100 AND t.score < 140 THEN 1 ELSE 0 END) as s100,
                    SUM(CASE WHEN t.remaining_before <= 170 THEN 1 ELSE 0 END) as co_attempts,
                    SUM(t.is_checkout) as co_hits,
                    -- Double attempts: darts actually thrown when remaining ≤ 40 or = 50 (bull)
                    SUM(
                        CASE WHEN t.darts_count >= 1
                              AND (t.remaining_before <= 40 OR t.remaining_before = 50) THEN 1 ELSE 0 END
                      + CASE WHEN t.darts_count >= 2 AND t.dart1_rem IS NOT NULL
                              AND (t.dart1_rem <= 40 OR t.dart1_rem = 50) THEN 1 ELSE 0 END
                      + CASE WHEN t.darts_count >= 3 AND t.dart2_rem IS NOT NULL
                              AND (t.dart2_rem <= 40 OR t.dart2_rem = 50) THEN 1 ELSE 0 END
                    ) as dbl_attempts,
                    -- Double hits: checkout where the finishing dart was thrown at a double
                    SUM(CASE WHEN t.is_checkout = 1 AND (
                        (t.darts_count >= 1 AND (t.remaining_before  <= 40 OR t.remaining_before  = 50))
                     OR (t.darts_count >= 2 AND t.dart1_rem IS NOT NULL
                         AND (t.dart1_rem <= 40 OR t.dart1_rem = 50))
                     OR (t.darts_count >= 3 AND t.dart2_rem IS NOT NULL
                         AND (t.dart2_rem <= 40 OR t.dart2_rem = 50))
                    ) THEN 1 ELSE 0 END) as dbl_hits
                FROM turns t
                LEFT JOIN players p ON p.name = t.player
                WHERE COALESCE(p.hidden, 0) = 0
                GROUP BY t.player
                ORDER BY sessions DESC, total_score DESC
            """).fetchall()
        return [{"player": r["player"], **_row_stats_full(r)} for r in rows]

    def leaderboard(self, metric: str, limit: int = 10) -> list:
        """Top-N players sorted by *metric* (desc). Valid metrics: avg3, s180, co_pct, dbl_pct, total_score."""
        valid = {"avg3", "s180", "co_pct", "dbl_pct", "total_score"}
        if metric not in valid:
            raise ValueError(f"Invalid leaderboard metric: {metric!r}")
        rows = self.all_players_stats()
        rows.sort(key=lambda r: r.get(metric) or 0, reverse=True)
        return rows[:limit]

    def player_stats(self, player: str) -> dict | None:
        """Lifetime stats for a single player."""
        with self._lock:
            row = self._conn.execute("""
                SELECT COUNT(DISTINCT match_id) as sessions,
                    COUNT(*) as turns,
                    SUM(score) as total_score,
                    SUM(darts_count) as total_darts,
                    SUM(CASE WHEN score = 180 THEN 1 ELSE 0 END) as s180,
                    SUM(CASE WHEN score >= 140 AND score < 180 THEN 1 ELSE 0 END) as s140,
                    SUM(CASE WHEN score >= 100 AND score < 140 THEN 1 ELSE 0 END) as s100,
                    SUM(CASE WHEN remaining_before <= 170 THEN 1 ELSE 0 END) as co_attempts,
                    SUM(is_checkout) as co_hits,
                    SUM(
                        CASE WHEN remaining_before <= 40 OR remaining_before = 50 THEN 1 ELSE 0 END
                      + CASE WHEN dart1_rem IS NOT NULL
                              AND (dart1_rem <= 40 OR dart1_rem = 50) THEN 1 ELSE 0 END
                      + CASE WHEN dart2_rem IS NOT NULL
                              AND (dart2_rem <= 40 OR dart2_rem = 50) THEN 1 ELSE 0 END
                    ) as dbl_attempts,
                    SUM(CASE WHEN is_checkout = 1 AND (
                        (darts_count >= 1 AND (remaining_before  <= 40 OR remaining_before  = 50))
                     OR (darts_count >= 2 AND dart1_rem IS NOT NULL
                         AND (dart1_rem <= 40 OR dart1_rem = 50))
                     OR (darts_count >= 3 AND dart2_rem IS NOT NULL
                         AND (dart2_rem <= 40 OR dart2_rem = 50))
                    ) THEN 1 ELSE 0 END) as dbl_hits
                FROM turns WHERE player = ?
            """, (player,)).fetchone()
        if not row or not row["turns"]:
            return None
        return _row_stats_full(row)

    def record_leg_win(self, match_id: str, leg: int, winner: str | None):
        """Record which player won a leg (winner=None if unknown/abandoned)."""
        log.debug("DB write: record_leg_win match_id=%s leg=%s winner=%s",
                  match_id, leg, winner)
        with self._lock:
            self._conn.execute(
                "INSERT INTO legs (match_id, leg, winner) VALUES (?, ?, ?)",
                (match_id, leg, winner),
            )
            self._conn.commit()

    def legs_won_by_player(self, match_id: str) -> dict:
        """Return {player_name: legs_won_count} for a match."""
        with self._lock:
            rows = self._conn.execute(
                "SELECT winner, COUNT(*) as n FROM legs WHERE match_id=?"
                " AND winner IS NOT NULL GROUP BY winner",
                (match_id,),
            ).fetchall()
        return {r["winner"]: r["n"] for r in rows}

    def delete_player(self, player: str):
        """Delete all data for a player, including their identity row
        (irreversible) — unlike upsert_player(hidden=True), which only
        hides them from the Players tab/leaderboard without touching
        history."""
        log.debug("DB write: delete_player player=%s (turns, elimination_turns, "
                  "elimination_results, players)", player)
        with self._lock:
            self._conn.execute("DELETE FROM turns WHERE player = ?", (player,))
            self._conn.execute("DELETE FROM elimination_turns WHERE player = ?", (player,))
            self._conn.execute("DELETE FROM elimination_results WHERE player = ?", (player,))
            self._conn.execute("DELETE FROM players WHERE name = ?", (player,))
            self._conn.commit()
        log.info("Deleted all stats for player: %s", player)

    def recent_matches(self, limit: int = 20, mode: str | None = None) -> list:
        """Newest first. `mode` ("x01" or "elimination") restricts which game mode
        counts toward the limit; None returns both."""
        mode_sql = {
            "x01": " AND COALESCE(game_mode, '') != 'Elimination'",
            "elimination": " AND game_mode = 'Elimination'",
        }.get(mode, "")
        with self._lock:
            rows = self._conn.execute(
                "SELECT match_id, started_at, ended_at, game_mode, points_start, players"
                " FROM matches"
                " WHERE (EXISTS (SELECT 1 FROM turns WHERE turns.match_id = matches.match_id)"
                "    OR EXISTS (SELECT 1 FROM elimination_turns WHERE elimination_turns.match_id = matches.match_id))"
                + mode_sql +
                " ORDER BY started_at DESC LIMIT ?",
                (limit,),
            ).fetchall()
        result = []
        for r in rows:
            mid = r["match_id"]
            with self._lock:
                leg_rows = self._conn.execute(
                    "SELECT winner, COUNT(*) as n FROM legs"
                    " WHERE match_id=? AND winner IS NOT NULL GROUP BY winner",
                    (mid,),
                ).fetchall()
                total_row = self._conn.execute(
                    "SELECT COUNT(*) as n FROM legs WHERE match_id=?", (mid,)
                ).fetchone()
            result.append({
                "match_id":    mid,
                "started_at":  r["started_at"],
                "ended_at":    r["ended_at"],
                "game_mode":   r["game_mode"],
                "points_start": r["points_start"],
                "players":     json.loads(r["players"] or "[]"),
                "legs_won":    {row["winner"]: row["n"] for row in leg_rows},
                "legs_total":  total_row["n"] if total_row else 0,
            })
        return result

    def match_elimination_stats(self, match_id: str) -> dict:
        """Per-player result of one Elimination match, best placement first:
        `placement`/`lives_left` are None for a match that never finished."""
        with self._lock:
            results = self._conn.execute(
                "SELECT player, placement, lives_left FROM elimination_results"
                " WHERE match_id = ?", (match_id,)
            ).fetchall()
            turns = self._conn.execute(
                "SELECT player, COUNT(*) as turns, AVG(darts_count) as avg_darts"
                " FROM elimination_turns WHERE match_id = ? GROUP BY player", (match_id,)
            ).fetchall()
        by_player = {
            r["player"]: {"placement": r["placement"], "lives_left": r["lives_left"],
                          "turns": 0, "avg_darts_per_turn": None}
            for r in results
        }
        for r in turns:
            entry = by_player.setdefault(
                r["player"],
                {"placement": None, "lives_left": None, "turns": 0, "avg_darts_per_turn": None},
            )
            entry["turns"] = r["turns"]
            entry["avg_darts_per_turn"] = round(r["avg_darts"], 2)
        ordered = sorted(
            by_player.items(),
            key=lambda kv: (kv[1]["placement"] is None, kv[1]["placement"] or 0, kv[0]),
        )
        return dict(ordered)

    def match_stats(self, match_id: str) -> dict:
        """Per-player stats dict for one specific match (for the Stats tab).
        Elimination matches return their own shape, see
        `match_elimination_stats()`."""
        with self._lock:
            mode_row = self._conn.execute(
                "SELECT game_mode FROM matches WHERE match_id = ?", (match_id,)
            ).fetchone()
        if mode_row and mode_row["game_mode"] == "Elimination":
            return self.match_elimination_stats(match_id)
        with self._lock:
            rows = self._conn.execute("""
                SELECT player,
                    COUNT(*) as turns,
                    SUM(score) as total_score,
                    SUM(darts_count) as total_darts,
                    SUM(CASE WHEN score = 180 THEN 1 ELSE 0 END) as s180,
                    SUM(CASE WHEN score >= 140 AND score < 180 THEN 1 ELSE 0 END) as s140,
                    SUM(CASE WHEN score >= 100 AND score < 140 THEN 1 ELSE 0 END) as s100,
                    SUM(CASE WHEN remaining_before <= 170 THEN 1 ELSE 0 END) as co_attempts,
                    SUM(is_checkout) as co_hits,
                    SUM(
                        CASE WHEN remaining_before <= 40 OR remaining_before = 50 THEN 1 ELSE 0 END
                      + CASE WHEN dart1_rem IS NOT NULL
                              AND (dart1_rem <= 40 OR dart1_rem = 50) THEN 1 ELSE 0 END
                      + CASE WHEN dart2_rem IS NOT NULL
                              AND (dart2_rem <= 40 OR dart2_rem = 50) THEN 1 ELSE 0 END
                    ) as dbl_attempts,
                    SUM(CASE WHEN is_checkout = 1 AND (
                        (darts_count >= 1 AND (remaining_before  <= 40 OR remaining_before  = 50))
                     OR (darts_count >= 2 AND dart1_rem IS NOT NULL
                         AND (dart1_rem <= 40 OR dart1_rem = 50))
                     OR (darts_count >= 3 AND dart2_rem IS NOT NULL
                         AND (dart2_rem <= 40 OR dart2_rem = 50))
                    ) THEN 1 ELSE 0 END) as dbl_hits
                FROM turns WHERE match_id = ?
                GROUP BY player
            """, (match_id,)).fetchall()
        return {r["player"]: _row_stats_full(r) for r in rows}

    # ── Advanced per-player dashboard ────────────────────────────────────────

    def player_activity(self, player: str, mode: str = "all") -> dict:
        """Total darts/games/playtime/walking-distance for one game mode, or
        X01 + Elimination together."""
        tables = _TURN_TABLES[mode]
        darts = " + ".join(f"COALESCE((SELECT SUM(darts_count) FROM {t} WHERE player = ?), 0)" for t in tables)
        walks = " + ".join(f"COALESCE((SELECT COUNT(*) FROM {t} WHERE player = ?), 0)" for t in tables)
        match_ids = " UNION ".join(f"SELECT match_id FROM {t} WHERE player = ?" for t in tables)
        with self._lock:
            row = self._conn.execute(f"""
                SELECT
                    ({darts}) as total_darts,
                    ({walks}) as total_walks,
                    (SELECT COUNT(DISTINCT match_id) FROM ({match_ids})) as total_games,
                    (SELECT COALESCE(SUM((julianday(ended_at) - julianday(started_at)) * 24), 0)
                     FROM matches
                     WHERE ended_at IS NOT NULL AND match_id IN ({match_ids})) as total_playtime_hours
            """, (player,) * (4 * len(tables))).fetchone()
        walks = row["total_walks"] or 0
        return {
            "total_darts": row["total_darts"] or 0,
            "total_games": row["total_games"] or 0,
            "total_playtime_hours": round(row["total_playtime_hours"] or 0.0, 2),
            "total_distance_km": round(walks * 4.74 / 1000, 2),
        }

    def player_activity_by_date(self, player: str, mode: str = "all") -> list:
        """[{date, darts, minutes}, ...] — one calendar day per match's start date."""
        tables = _TURN_TABLES[mode]
        darts_union = " UNION ALL ".join(f"SELECT match_id, darts_count as darts FROM {t} WHERE player = ?" for t in tables)
        match_ids = " UNION ".join(f"SELECT match_id FROM {t} WHERE player = ?" for t in tables)
        with self._lock:
            darts_rows = self._conn.execute(f"""
                SELECT DATE(m.started_at) as date, SUM(darts) as darts FROM (
                    {darts_union}
                ) x JOIN matches m ON m.match_id = x.match_id
                GROUP BY DATE(m.started_at)
            """, (player,) * len(tables)).fetchall()
            minutes_rows = self._conn.execute(f"""
                SELECT DATE(m.started_at) as date,
                       SUM((julianday(m.ended_at) - julianday(m.started_at)) * 1440) as minutes
                FROM matches m
                WHERE m.ended_at IS NOT NULL AND m.match_id IN ({match_ids})
                GROUP BY DATE(m.started_at)
            """, (player,) * len(tables)).fetchall()
        by_date = {}
        for r in darts_rows:
            by_date.setdefault(r["date"], {"date": r["date"], "darts": 0, "minutes": 0.0})
            by_date[r["date"]]["darts"] = r["darts"] or 0
        for r in minutes_rows:
            by_date.setdefault(r["date"], {"date": r["date"], "darts": 0, "minutes": 0.0})
            by_date[r["date"]]["minutes"] = round(r["minutes"] or 0.0, 1)
        return [by_date[d] for d in sorted(by_date)]

    def player_performance_summary(self, player: str) -> dict:
        """Best 3-dart average (per match), fewest-darts leg won, best checkout,
        total 180s — X01 only (Elimination has no 3-dart-average/leg concept)."""
        with self._lock:
            match_rows = self._conn.execute("""
                SELECT SUM(score) as total_score, SUM(darts_count) as total_darts
                FROM turns WHERE player = ? GROUP BY match_id
                HAVING total_darts > 0
            """, (player,)).fetchall()
            leg_row = self._conn.execute("""
                SELECT MIN(darts) as darts FROM (
                    SELECT SUM(t.darts_count) as darts
                    FROM turns t JOIN legs l ON l.match_id = t.match_id AND l.leg = t.leg
                    WHERE l.winner = ? AND t.player = ?
                    GROUP BY t.match_id, t.leg
                )
            """, (player, player)).fetchone()
            co_row = self._conn.execute(
                "SELECT MAX(score) as best FROM turns WHERE player = ? AND is_checkout = 1",
                (player,),
            ).fetchone()
            s180_row = self._conn.execute(
                "SELECT SUM(CASE WHEN score = 180 THEN 1 ELSE 0 END) as n FROM turns WHERE player = ?",
                (player,),
            ).fetchone()
        best_avg3 = 0.0
        for r in match_rows:
            td = r["total_darts"] or 0
            if td:
                best_avg3 = max(best_avg3, (r["total_score"] or 0) / td * 3)
        return {
            "best_avg3": round(best_avg3, 1),
            "best_leg_darts": leg_row["darts"] if leg_row and leg_row["darts"] is not None else None,
            "best_checkout": co_row["best"] if co_row and co_row["best"] is not None else None,
            "total_180s": s180_row["n"] or 0 if s180_row else 0,
        }

    def player_scoring_buckets(self, player: str) -> dict:
        with self._lock:
            row = self._conn.execute("""
                SELECT
                    SUM(CASE WHEN score < 60 THEN 1 ELSE 0 END) as under_60,
                    SUM(CASE WHEN score >= 60 AND score < 100 THEN 1 ELSE 0 END) as s60,
                    SUM(CASE WHEN score >= 100 AND score < 140 THEN 1 ELSE 0 END) as s100,
                    SUM(CASE WHEN score >= 140 AND score < 170 THEN 1 ELSE 0 END) as s140,
                    SUM(CASE WHEN score >= 170 THEN 1 ELSE 0 END) as s170
                FROM turns WHERE player = ?
            """, (player,)).fetchone()
        return {
            "under_60": row["under_60"] or 0,
            "60_99":    row["s60"] or 0,
            "100_139":  row["s100"] or 0,
            "140_169":  row["s140"] or 0,
            "170_plus": row["s170"] or 0,
        }

    def player_avg_by_date(self, player: str) -> list:
        with self._lock:
            rows = self._conn.execute("""
                SELECT DATE(m.started_at) as date,
                       SUM(t.score) as total_score, SUM(t.darts_count) as total_darts
                FROM turns t JOIN matches m ON m.match_id = t.match_id
                WHERE t.player = ?
                GROUP BY DATE(m.started_at)
                ORDER BY date
            """, (player,)).fetchall()
        return [
            {"date": r["date"],
             "avg3": round((r["total_score"] or 0) / r["total_darts"] * 3, 1) if r["total_darts"] else 0.0}
            for r in rows
        ]

    def player_checkout_pct_by_date(self, player: str) -> list:
        with self._lock:
            rows = self._conn.execute("""
                SELECT DATE(m.started_at) as date,
                       SUM(CASE WHEN t.remaining_before <= 170 THEN 1 ELSE 0 END) as co_attempts,
                       SUM(t.is_checkout) as co_hits
                FROM turns t JOIN matches m ON m.match_id = t.match_id
                WHERE t.player = ?
                GROUP BY DATE(m.started_at)
                ORDER BY date
            """, (player,)).fetchall()
        return [
            {"date": r["date"],
             "co_pct": round(r["co_hits"] / r["co_attempts"] * 100, 1) if r["co_attempts"] else 0.0}
            for r in rows
        ]

    def player_win_loss(self, player: str, mode: str = "all") -> dict:
        """Wins vs losses among decided (winner set) matches this player was
        in — excludes solo X01 matches, same as x01_win_counts()."""
        tables = _TURN_TABLES[mode]
        match_ids = " UNION ".join(f"SELECT match_id FROM {t} WHERE player = ?" for t in tables)
        with self._lock:
            rows = self._conn.execute(f"""
                SELECT winner FROM matches m
                WHERE winner IS NOT NULL AND match_id IN ({match_ids})
                AND NOT ({_SOLO_X01_SQL})
            """, (player,) * len(tables)).fetchall()
        wins = sum(1 for r in rows if r["winner"] == player)
        return {"wins": wins, "losses": len(rows) - wins}

    def player_game_type_ratio(self, player: str) -> dict:
        with self._lock:
            x01 = self._conn.execute(
                "SELECT COUNT(DISTINCT match_id) as n FROM turns WHERE player = ?", (player,)
            ).fetchone()["n"]
            elim = self._conn.execute(
                "SELECT COUNT(DISTINCT match_id) as n FROM elimination_turns WHERE player = ?", (player,)
            ).fetchone()["n"]
        return {"x01": x01 or 0, "elimination": elim or 0}

    def player_elimination_stats(self, player: str) -> dict:
        """Elimination-only numbers: finished games, how they placed, and the
        average darts per recorded turn. `games` counts games with a recorded
        result, so a match that was abandoned before finishing isn't included."""
        with self._lock:
            rows = self._conn.execute(
                "SELECT placement, COUNT(*) as n FROM elimination_results"
                " WHERE player = ? GROUP BY placement", (player,)
            ).fetchall()
            avg_row = self._conn.execute(
                "SELECT AVG(darts_count) as avg_darts FROM elimination_turns WHERE player = ?",
                (player,),
            ).fetchone()
        return _elimination_summary({r["placement"]: r["n"] for r in rows}, avg_row["avg_darts"])

    def all_elimination_stats(self) -> list:
        """Lifetime Elimination numbers per player, same fields as
        player_elimination_stats plus the name. Players flagged `hidden` are left
        out, and so are players without a recorded result."""
        with self._lock:
            place_rows = self._conn.execute("""
                SELECT r.player as player, r.placement as placement, COUNT(*) as n
                FROM elimination_results r
                LEFT JOIN players p ON p.name = r.player
                WHERE COALESCE(p.hidden, 0) = 0
                GROUP BY r.player, r.placement
            """).fetchall()
            avg_rows = self._conn.execute(
                "SELECT player, AVG(darts_count) as avg_darts FROM elimination_turns GROUP BY player"
            ).fetchall()
        by_player = {}
        for r in place_rows:
            by_player.setdefault(r["player"], {})[r["placement"]] = r["n"]
        avg = {r["player"]: r["avg_darts"] for r in avg_rows}
        result = [
            {"player": name, **_elimination_summary(by_place, avg.get(name))}
            for name, by_place in by_player.items()
        ]
        result.sort(key=lambda r: (-r["games"], -r["wins"], r["player"]))
        return result

    def player_doubles_by_number(self, player: str) -> list:
        """Attempts/hits per double target (D1-D20 + bullseye-as-25), inferred from
        the remaining score before each dart — same approximation the existing
        aggregate dbl_attempts/dbl_hits use, just broken out per number instead of
        summed. Not a recorded "intended target", just the remaining that made a
        double-out mathematically possible at that point."""
        with self._lock:
            rows = self._conn.execute("""
                SELECT target, COUNT(*) as attempts, SUM(hit) as hits FROM (
                    SELECT
                        CASE WHEN remaining_before = 50 THEN 25 ELSE remaining_before / 2 END as target,
                        CASE WHEN darts_count = 1 AND is_checkout = 1 THEN 1 ELSE 0 END as hit
                    FROM turns
                    WHERE player = ? AND darts_count >= 1
                      AND (remaining_before = 50 OR (remaining_before > 0 AND remaining_before <= 40
                           AND remaining_before % 2 = 0))
                    UNION ALL
                    SELECT
                        CASE WHEN dart1_rem = 50 THEN 25 ELSE dart1_rem / 2 END as target,
                        CASE WHEN darts_count = 2 AND is_checkout = 1 THEN 1 ELSE 0 END as hit
                    FROM turns
                    WHERE player = ? AND darts_count >= 2 AND dart1_rem IS NOT NULL
                      AND (dart1_rem = 50 OR (dart1_rem > 0 AND dart1_rem <= 40 AND dart1_rem % 2 = 0))
                    UNION ALL
                    SELECT
                        CASE WHEN dart2_rem = 50 THEN 25 ELSE dart2_rem / 2 END as target,
                        CASE WHEN darts_count = 3 AND is_checkout = 1 THEN 1 ELSE 0 END as hit
                    FROM turns
                    WHERE player = ? AND darts_count >= 3 AND dart2_rem IS NOT NULL
                      AND (dart2_rem = 50 OR (dart2_rem > 0 AND dart2_rem <= 40 AND dart2_rem % 2 = 0))
                ) GROUP BY target ORDER BY target
            """, (player, player, player)).fetchall()
        return [
            {"target": r["target"], "attempts": r["attempts"], "hits": r["hits"] or 0,
             "pct": round((r["hits"] or 0) / r["attempts"] * 100, 1) if r["attempts"] else 0.0}
            for r in rows
        ]

    def x01_points_start_values(self) -> list:
        """Distinct `points_start` values ever played in an X01 match,
        ascending — the fewest-darts-per-leg ranking only makes sense
        within a single starting score (a 701 leg can never beat a 301
        leg on darts alone), so this backs the Top 10 Legs mode tabs."""
        with self._lock:
            rows = self._conn.execute(
                "SELECT DISTINCT points_start FROM matches"
                " WHERE game_mode != 'Elimination' AND points_start IS NOT NULL"
                " ORDER BY points_start"
            ).fetchall()
        return [r["points_start"] for r in rows]

    def top_legs(self, player: str, limit: int = 10, points_start: int | None = None) -> list:
        """Fewest-darts legs won by this player, optionally scoped to one
        `points_start` value (see x01_points_start_values)."""
        query = """
            SELECT t.match_id, t.leg, SUM(t.darts_count) as darts,
                   SUM(t.score) as total_score, m.started_at, m.game_mode, m.points_start
            FROM turns t
            JOIN legs l ON l.match_id = t.match_id AND l.leg = t.leg
            JOIN matches m ON m.match_id = t.match_id
            WHERE l.winner = ? AND t.player = ?
        """
        params = [player, player]
        if points_start is not None:
            query += " AND m.points_start = ?"
            params.append(points_start)
        query += " GROUP BY t.match_id, t.leg ORDER BY darts ASC LIMIT ?"
        params.append(limit)
        with self._lock:
            rows = self._conn.execute(query, params).fetchall()
        return [
            {
                "match_id": r["match_id"], "leg": r["leg"], "darts": r["darts"],
                "avg3": round(r["total_score"] / r["darts"] * 3, 1) if r["darts"] else 0.0,
                "started_at": r["started_at"], "game_mode": r["game_mode"],
                "points_start": r["points_start"],
            }
            for r in rows
        ]

    def top_checkouts(self, player: str, limit: int = 10) -> list:
        """Highest-scoring checkouts, with the finishing darts as the "targets"."""
        with self._lock:
            rows = self._conn.execute("""
                SELECT t.score, t.dart1, t.dart2, t.dart3, t.match_id, t.leg,
                       m.started_at, m.game_mode, m.points_start
                FROM turns t JOIN matches m ON m.match_id = t.match_id
                WHERE t.player = ? AND t.is_checkout = 1
                ORDER BY t.score DESC
                LIMIT ?
            """, (player, limit)).fetchall()
        return [
            {
                "score": r["score"],
                "targets": [d for d in (r["dart1"], r["dart2"], r["dart3"]) if d],
                "match_id": r["match_id"], "leg": r["leg"],
                "points_start": r["points_start"],
                "started_at": r["started_at"], "game_mode": r["game_mode"],
            }
            for r in rows
        ]

    def player_dashboard(self, player: str, points_start: int | None = None, mode: str = "all") -> dict:
        """Bundle every player_*/top_* method above into one payload — one fetch
        for the whole advanced-stats view instead of ~10 round trips.

        `points_start` picks the Top 10 Legs mode tab; when not given
        (first load), default to 501 if it's ever been played, else the
        lowest available mode — resolved here so the frontend never has
        to guess before its first paint.

        `mode` ("x01" or "elimination") limits the activity and win/loss
        numbers to one game mode; the other sections are per-mode already."""
        leg_modes = self.x01_points_start_values()
        if points_start is None:
            points_start = 501 if 501 in leg_modes else (leg_modes[0] if leg_modes else None)
        return {
            "activity": self.player_activity(player, mode),
            "activity_by_date": self.player_activity_by_date(player, mode),
            "performance": self.player_performance_summary(player),
            "scoring_buckets": self.player_scoring_buckets(player),
            "avg_by_date": self.player_avg_by_date(player),
            "checkout_pct_by_date": self.player_checkout_pct_by_date(player),
            "win_loss": self.player_win_loss(player, mode),
            "game_type_ratio": self.player_game_type_ratio(player),
            "elimination": self.player_elimination_stats(player),
            "doubles": self.player_doubles_by_number(player),
            "top_legs": self.top_legs(player, points_start=points_start),
            "leg_modes": leg_modes,
            "selected_points_start": points_start,
            "top_checkouts": self.top_checkouts(player),
        }


def _elimination_summary(by_place: dict, avg_darts) -> dict:
    games = sum(by_place.values())
    wins = by_place.get(1, 0)
    return {
        "games": games,
        "wins": wins,
        "win_pct": round(wins / games * 100, 1) if games else 0.0,
        "placements": {
            "first": wins,
            "second": by_place.get(2, 0),
            "third": by_place.get(3, 0),
            "other": sum(n for place, n in by_place.items() if place > 3),
        },
        "avg_darts_per_turn": round(avg_darts, 2) if avg_darts is not None else None,
    }


def _row_stats(r) -> dict:
    td  = r["total_darts"] or 0
    ts  = r["total_score"] or 0
    coa = r["co_attempts"] or 0
    coh = r["co_hits"] or 0
    return {
        "turns":       r["turns"] or 0,
        "total_score": ts,
        "avg3":        round(ts / td * 3, 1) if td else 0.0,
        "s180":        r["s180"] or 0,
        "s140":        r["s140"] or 0,
        "s100":        r["s100"] or 0,
        "co_attempts": coa,
        "co_hits":     coh,
        "co_pct":      round(coh / coa * 100, 1) if coa else 0.0,
    }


def _row_stats_full(r) -> dict:
    base = _row_stats(r)
    da = r["dbl_attempts"] or 0 if "dbl_attempts" in r.keys() else 0
    dh = r["dbl_hits"] or 0 if "dbl_hits" in r.keys() else 0
    return {
        **base,
        "sessions":    r["sessions"] or 0 if "sessions" in r.keys() else None,
        "dbl_attempts": da,
        "dbl_hits":     dh,
        "dbl_pct":      round(dh / da * 100, 1) if da else 0.0,
    }


# ── Tracker ───────────────────────────────────────────────────────────────────

class StatsTracker:
    """Subscribes to game events and writes turns to StatsDB.

    Also maintains in-memory session_stats for zero-latency live display.
    Only X01 / Random Checkout games are tracked.
    """

    def __init__(self, db: StatsDB):
        self._db = db
        self._match_id: str | None = None
        self._game_mode: str = ""
        self._leg = 1
        self._turn_per_player: dict[str, int] = {}
        self._buf: dict | None = None
        self._session_stats: dict[str, dict] = {}

    @property
    def session_stats(self) -> dict:
        """In-memory per-player stats for the current match."""
        return dict(self._session_stats)

    def process(self, event_data: dict):
        ev     = event_data.get("event")
        player = _safe_name(event_data.get("player"))
        game   = event_data.get("game", {})

        if ev == "match-started":
            self._match_id  = event_data.get("id")
            self._game_mode = game.get("mode", "")
            pts_start       = int(game.get("pointsStart") or 0)
            self._leg       = 1
            self._turn_per_player = {}
            self._buf       = None
            self._session_stats = {}
            if self._match_id:
                self._db.open_match(self._match_id, self._game_mode, pts_start)

        elif ev == "dart1-thrown" and self._is_x01():
            dv  = int(game.get("dartValue") or 0)
            rem = int(game.get("pointsLeft") or 0)
            rem_before = rem + dv
            field = (game.get("fieldName") or "").upper()
            self._buf = {
                "player": player,
                "leg": self._leg,
                "remaining_before": rem_before,
                "is_bust": False,
                "darts": [(field, dv, rem)],
            }

        elif ev == "dart2-thrown":
            if self._buf and self._buf["player"] == player:
                dv   = int(game.get("dartValue") or 0)
                field = (game.get("fieldName") or "").upper()
                prev_rem = self._buf["darts"][-1][2]
                self._buf["darts"].append((field, dv, prev_rem - dv))

        elif ev == "dart3-thrown":
            if self._buf and self._buf["player"] == player:
                dv   = int(game.get("dartValue") or 0)
                field = (game.get("fieldName") or "").upper()
                prev_rem = self._buf["darts"][-1][2]
                self._buf["darts"].append((field, dv, prev_rem - dv))

        elif ev == "busted":
            if self._buf:
                self._buf["is_bust"] = True

        elif ev == "darts-pulled":
            self._flush_turn()

        elif ev == "game-won":
            # autodarts_client.py's _emit_dart_thrown() already emits the
            # checkout dart itself before game-won/match-won, so self._buf
            # is complete by this point — but the matching darts-pulled
            # that would normally trigger _flush_turn() only fires on the
            # *next* board-state poll, racing against a following
            # match-started (e.g. an immediate rematch), whose handler
            # wipes self._buf unconditionally. That race silently drops
            # exactly the one turn per leg with is_checkout=True, pinning
            # co_pct/dbl_pct at 0% regardless of how much is played.
            # Flushing here removes the dependency on that later event
            # entirely; harmless no-op if darts-pulled already did fire.
            self._flush_turn()
            winner = game.get("winner")
            if self._match_id:
                self._db.record_leg_win(self._match_id, self._leg, winner)
            self._leg += 1
            self._turn_per_player = {}

        elif ev == "match-won":
            self._flush_turn()
            winner = game.get("winner")
            if self._match_id:
                self._db.record_leg_win(self._match_id, self._leg, winner)
                self._db.set_winner(self._match_id, winner)
                self._db.close_match(self._match_id)

    # ── internal ─────────────────────────────────────────────────────────────

    def _is_x01(self) -> bool:
        return "01" in self._game_mode or self._game_mode == "Random Checkout"

    def _flush_turn(self):
        if not self._buf or not self._match_id:
            self._buf = None
            return
        buf, self._buf = self._buf, None

        player = buf["player"]
        if not player:
            return

        darts       = buf["darts"]
        is_bust     = buf["is_bust"]
        total       = sum(v for _, v, _ in darts)
        score       = 0 if is_bust else total
        is_checkout = (not is_bust) and buf["remaining_before"] == total

        turn_n = self._turn_per_player.get(player, 0) + 1
        self._turn_per_player[player] = turn_n

        self._db.insert_turn(
            match_id=self._match_id,
            player=player,
            leg=buf["leg"],
            turn=turn_n,
            remaining_before=buf["remaining_before"],
            score=score,
            is_bust=is_bust,
            is_checkout=is_checkout,
            darts=darts,
        )

        s = self._session_stats.setdefault(player, {
            "turns": 0, "total_score": 0, "total_darts": 0,
            "s180": 0, "s140": 0, "s100": 0,
            "co_attempts": 0, "co_hits": 0,
        })
        s["turns"]       += 1
        s["total_darts"] += len(darts)
        s["total_score"] += score
        if score == 180:
            s["s180"] += 1
        elif score >= 140:
            s["s140"] += 1
        elif score >= 100:
            s["s100"] += 1
        if buf["remaining_before"] <= 170:
            s["co_attempts"] += 1
        if is_checkout:
            s["co_hits"] += 1

    def computed_session_stats(self) -> dict:
        """Derive avg3, co_pct etc. from raw accumulators."""
        result = {}
        for player, s in self._session_stats.items():
            td  = s["total_darts"] or 0
            ts  = s["total_score"] or 0
            coa = s["co_attempts"] or 0
            coh = s["co_hits"] or 0
            result[player] = {
                "turns":       s["turns"],
                "avg3":        round(ts / td * 3, 1) if td else 0.0,
                "s180":        s["s180"],
                "s140":        s["s140"],
                "s100":        s["s100"],
                "co_attempts": coa,
                "co_hits":     coh,
                "co_pct":      round(coh / coa * 100, 1) if coa else 0.0,
            }
        return result
