"""Statistics: SQLite persistence + in-memory session stats.

Only X01 / Random Checkout turns are tracked (per-dart data requires the
dart1/2/3-thrown events that only X01 emits).
"""

import json
import logging
import re
import sqlite3
import threading
from datetime import datetime, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from breakfast.dartboard import field_centers
from breakfast.target_battle_scoring import SCORING

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
    created_at TEXT,
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
    hidden     INTEGER NOT NULL DEFAULT 0,
    color      TEXT
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
    lives_before INTEGER,
    created_at  TEXT
);
CREATE TABLE IF NOT EXISTS target_battle_turns (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    match_id    TEXT NOT NULL,
    player      TEXT NOT NULL,
    round_no    INTEGER NOT NULL,
    target      INTEGER NOT NULL,
    tiebreak    INTEGER NOT NULL DEFAULT 0,
    darts_count INTEGER NOT NULL,
    score       INTEGER NOT NULL,
    created_at  TEXT
);
CREATE TABLE IF NOT EXISTS target_battle_results (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    match_id   TEXT NOT NULL,
    player     TEXT NOT NULL,
    placement  INTEGER NOT NULL,
    score      INTEGER NOT NULL,
    UNIQUE(match_id, player)
);
CREATE TABLE IF NOT EXISTS target_battle_games (
    match_id      TEXT PRIMARY KEY,
    scoring       TEXT NOT NULL,
    rounds        INTEGER NOT NULL,
    tiebreak      INTEGER NOT NULL DEFAULT 0,
    fixed_targets INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS killer_games (
    match_id TEXT PRIMARY KEY,
    own_goal INTEGER NOT NULL DEFAULT 0,
    singles  INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS killer_turns (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    match_id    TEXT NOT NULL,
    player      TEXT NOT NULL,
    darts_count INTEGER NOT NULL,
    created_at  TEXT
);
CREATE TABLE IF NOT EXISTS killer_events (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    turn_id    INTEGER NOT NULL,
    match_id   TEXT NOT NULL,
    player     TEXT NOT NULL,
    kind       TEXT NOT NULL,
    victim     TEXT,
    dart_no    INTEGER NOT NULL,
    number     INTEGER,
    lives_after INTEGER
);
CREATE TABLE IF NOT EXISTS killer_results (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    match_id   TEXT NOT NULL,
    player     TEXT NOT NULL,
    placement  INTEGER NOT NULL,
    lives_left INTEGER,
    number     INTEGER NOT NULL,
    UNIQUE(match_id, player)
);
CREATE INDEX IF NOT EXISTS idx_killer_turns_match  ON killer_turns  (match_id);
CREATE INDEX IF NOT EXISTS idx_killer_events_match ON killer_events (match_id);
CREATE TABLE IF NOT EXISTS dart_positions (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    match_id    TEXT    NOT NULL,
    game_mode   TEXT    NOT NULL,
    player      TEXT    NOT NULL,
    leg         INTEGER NOT NULL DEFAULT 1,
    turn        INTEGER NOT NULL,
    dart_number INTEGER NOT NULL,
    field       TEXT,
    x           REAL    NOT NULL,
    y           REAL    NOT NULL,
    entry       TEXT,
    corrected   INTEGER NOT NULL DEFAULT 0,
    misread     INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS achievements_earned (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    player         TEXT    NOT NULL,
    achievement_id TEXT    NOT NULL,
    tier           INTEGER NOT NULL DEFAULT 0,
    earned_at      TEXT    NOT NULL,
    match_id       TEXT,
    UNIQUE(player, achievement_id, tier)
);
CREATE TABLE IF NOT EXISTS achievements_meta (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_turns_player ON turns (player);
CREATE INDEX IF NOT EXISTS idx_dart_positions_player ON dart_positions (player);
CREATE INDEX IF NOT EXISTS idx_dart_positions_match  ON dart_positions (match_id);
CREATE INDEX IF NOT EXISTS idx_turns_match  ON turns (match_id);
CREATE INDEX IF NOT EXISTS idx_legs_match   ON legs  (match_id);
CREATE INDEX IF NOT EXISTS idx_elim_results_match ON elimination_results (match_id);
CREATE INDEX IF NOT EXISTS idx_elim_turns_match   ON elimination_turns   (match_id);
"""


# Which per-turn tables feed a stat for each mode: "all" is both game modes
# together, "x01" and "elimination" are one each.
_TURN_TABLES = {"all": ("turns", "elimination_turns"), "x01": ("turns",), "elimination": ("elimination_turns",)}


# The games that are not X01. Everything else in `matches` is an X01 variant.
_OTHER_MODES_SQL = "('Elimination', 'Target Battle', 'Killer')"

# A match counts as "solo" (practice, no opponent) when exactly one distinct
# player ever appears in its `turns` rows — Elimination is excluded here
# since EliminationController.start() already refuses fewer than 2 players,
# so this predicate only ever matches X01. Shared by every query that must
# not let solo sessions inflate competitive win/loss stats.
_SOLO_X01_SQL = (
    f"m.game_mode NOT IN {_OTHER_MODES_SQL} AND "
    "(SELECT COUNT(DISTINCT player) FROM turns WHERE turns.match_id = m.match_id) <= 1"
)


_FIELD_CENTERS = field_centers()


def _is_corrected(field, x, y, entry) -> bool:
    """A dart sits on the exact center of its field, or Autodarts says it was not
    detected, when it was set by a correction — its position is not where the dart landed."""
    if entry not in (None, "", "detected"):
        return True
    key = {"BULL": "50"}.get((field or "").upper(), (field or "").upper())
    center = _FIELD_CENTERS.get(key)
    return bool(center) and abs(center["x"] - x) < 1e-6 and abs(center["y"] - y) < 1e-6


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def load_timezone(name: str | None) -> ZoneInfo:
    """The zone for `[stats] timezone` (an IANA name); an unknown name falls back to UTC."""
    try:
        return ZoneInfo(name or "UTC")
    except (ZoneInfoNotFoundError, ValueError):
        log.warning("Unknown timezone %r in [stats], using UTC", name)
        return ZoneInfo("UTC")


def _position(game: dict):
    """{x, y, entry} from a dart event's coords, or None if it carries none."""
    coords = game.get("coords")
    if isinstance(coords, dict):
        try:
            return {"x": float(coords["x"]), "y": float(coords["y"]), "entry": game.get("entry")}
        except (KeyError, TypeError, ValueError):
            pass
    return None


def _safe_name(raw) -> str | None:
    if isinstance(raw, str):
        return raw
    if isinstance(raw, dict):
        return raw.get("name") or str(raw)
    return str(raw) if raw is not None else None


# ── Database ──────────────────────────────────────────────────────────────────

class StatsDB:
    def __init__(self, path: str, tz: str | None = "UTC"):
        self.tz = load_timezone(tz)
        self._conn = sqlite3.connect(path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._lock = threading.Lock()
        # Called with a match id after a change that can decide achievements (a match
        # closed or reopened, a turn undone or corrected). See achievements.py.
        self.on_match_changed = None
        self.achievement_engine = None      # set by AchievementEngine.attach()
        with self._lock:
            self._conn.executescript(_SCHEMA)
            self._conn.execute(
                "INSERT OR IGNORE INTO achievements_meta (key, value) VALUES ('start', ?)",
                (_now_iso(),))
            self._migrate_matches_winner()
            self._migrate_elimination_turn_details()
            self._migrate_turn_times()
            self._migrate_misread()
            self._migrate_player_color()
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

    def _migrate_turn_times(self):
        """Turns recorded before the time was stored keep NULL in `created_at`."""
        for table in ("turns", "elimination_turns"):
            cols = {r["name"] for r in self._conn.execute(f"PRAGMA table_info({table})")}
            if "created_at" not in cols:
                self._conn.execute(f"ALTER TABLE {table} ADD COLUMN created_at TEXT")

    def _migrate_misread(self):
        """`misread` separates darts whose field is unknown (the total of their turn was
        corrected) from darts set by a correction, whose field is known. Before it existed
        `corrected` meant both, so every corrected Elimination dart stays untrusted."""
        cols = {r["name"] for r in self._conn.execute("PRAGMA table_info(dart_positions)")}
        if "misread" not in cols:
            self._conn.execute("ALTER TABLE dart_positions ADD COLUMN misread INTEGER NOT NULL DEFAULT 0")
            self._conn.execute("UPDATE dart_positions SET misread = corrected WHERE game_mode = 'Elimination'")

    def _migrate_player_color(self):
        cols = {r["name"] for r in self._conn.execute("PRAGMA table_info(players)")}
        if "color" not in cols:
            self._conn.execute("ALTER TABLE players ADD COLUMN color TEXT")

    def local_time(self, iso: str) -> datetime:
        """A stored UTC time as a datetime in the configured timezone."""
        return datetime.fromisoformat(iso).astimezone(self.tz)

    def _migrate_backfill_x01_winner(self):
        """`matches.winner` was only ever written by elimination.py — X01
        matches never got one at all until StatsTracker.process()'s
        "match-won" handler started calling set_winner() too. Backfill
        existing X01 matches from `legs` (the winner of a match's last
        leg is its match winner, since a match ends exactly when someone
        reaches the required leg count) so pre-existing history isn't
        silently missing from x01_win_counts()."""
        rows = self._conn.execute(
            f"SELECT match_id FROM matches WHERE winner IS NULL AND game_mode NOT IN {_OTHER_MODES_SQL}"
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

    def _match_changed(self, match_id: str):
        """Tell the listener a match changed. A failing listener must never reach the
        game, so its errors are only logged."""
        if self.on_match_changed is None:
            return
        try:
            self.on_match_changed(match_id)
        except Exception:
            log.exception("Match listener failed for %s", match_id)

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
                    " UNION SELECT DISTINCT player FROM elimination_turns WHERE match_id = ?"
                    " UNION SELECT DISTINCT player FROM target_battle_turns WHERE match_id = ?"
                    " UNION SELECT DISTINCT player FROM killer_turns WHERE match_id = ?",
                    (match_id, match_id, match_id, match_id),
                ).fetchall()
            ]
            log.debug("DB write: close_match match_id=%s players=%s", match_id, players)
            self._conn.execute(
                "UPDATE matches SET ended_at = ?, players = ? WHERE match_id = ?",
                (_now_iso(), json.dumps(players), match_id),
            )
            self._conn.commit()
        self._match_changed(match_id)

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

    def set_player_color(self, name: str, color: str | None) -> bool:
        """Set a player's color (`#rrggbb`, stored lowercase) or clear it with None. Returns
        False when there is no such player; an invalid value raises ValueError."""
        if color is not None:
            if not re.fullmatch(r"#[0-9a-fA-F]{6}", color):
                raise ValueError("color must look like #rrggbb")
            color = color.lower()
        log.debug("DB write: set_player_color name=%s color=%s", name, color)
        with self._lock:
            cur = self._conn.execute("UPDATE players SET color = ? WHERE name = ?", (color, name))
            self._conn.commit()
        return cur.rowcount > 0

    def player_colors(self) -> dict:
        """Name -> color of every player that has one."""
        with self._lock:
            rows = self._conn.execute("SELECT name, color FROM players WHERE color IS NOT NULL").fetchall()
        return {r["name"]: r["color"] for r in rows}

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
                f" WHERE winner IS NOT NULL AND game_mode NOT IN {_OTHER_MODES_SQL}"
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

    def replace_elimination_results(self, match_id: str, results: list):
        """Like record_elimination_result(), but replaces what is stored for the match: an
        online match stores the placements the relay decided."""
        with self._lock:
            self._conn.execute("DELETE FROM elimination_results WHERE match_id = ?", (match_id,))
        self.record_elimination_result(match_id, results)

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
                turn = self._conn.execute(
                    "SELECT COUNT(*) FROM elimination_turns WHERE match_id = ? AND player = ?",
                    (match_id, player)).fetchone()[0]
                self._conn.execute(
                    "DELETE FROM dart_positions WHERE match_id = ? AND game_mode = 'Elimination'"
                    " AND player = ? AND turn = ?", (match_id, player, turn))
                self._conn.execute(
                    "DELETE FROM elimination_turns WHERE id = ?", (row["id"],)
                )
                self._conn.commit()
        self._match_changed(match_id)

    # ── Target Battle ─────────────────────────────────────────────────────────

    def insert_target_battle_turn(self, match_id, player, round_no, target, tiebreak, score,
                                  darts_count, positions=None):
        """One finished turn: the round it belonged to, the target of that round and what the
        darts scored. positions: one {"field", "x", "y"} (or None) per dart."""
        log.debug("DB write: insert_target_battle_turn match_id=%s player=%s round=%s target=%s "
                  "tiebreak=%s score=%s darts_count=%s",
                  match_id, player, round_no, target, tiebreak, score, darts_count)
        with self._lock:
            self._ensure_player(player)
            self._conn.execute(
                "INSERT INTO target_battle_turns"
                " (match_id, player, round_no, target, tiebreak, darts_count, score, created_at)"
                " VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (match_id, player, round_no, target, int(tiebreak), darts_count, score, _now_iso()))
            turn = self._conn.execute(
                "SELECT COUNT(*) FROM target_battle_turns WHERE match_id = ? AND player = ?",
                (match_id, player)).fetchone()[0]
            self._insert_positions(match_id, "Target Battle", player, 1, turn,
                                   [((p or {}).get("field"), p) for p in positions or []])
            self._conn.commit()

    def correct_last_target_battle_turn(self, match_id: str, player: str, score: int):
        """The total of a finished turn was corrected: rewrite the score of the player's most
        recent turn. Its darts were misread, so neither their fields nor positions are trusted."""
        log.debug("DB write: correct_last_target_battle_turn match_id=%s player=%s score=%s",
                  match_id, player, score)
        with self._lock:
            self._conn.execute(
                "UPDATE target_battle_turns SET score = ? WHERE id = ("
                " SELECT id FROM target_battle_turns WHERE match_id = ? AND player = ?"
                " ORDER BY id DESC LIMIT 1)", (score, match_id, player))
            self._conn.execute(
                "UPDATE dart_positions SET corrected = 1, misread = 1"
                " WHERE match_id = ? AND game_mode = 'Target Battle' AND player = ? AND turn = ("
                " SELECT COUNT(*) FROM target_battle_turns WHERE match_id = ? AND player = ?)",
                (match_id, player, match_id, player))
            self._conn.commit()
        self._match_changed(match_id)

    def delete_last_target_battle_turn(self, match_id: str, player: str):
        """Undo insert_target_battle_turn() for the player's most recent turn."""
        log.debug("DB write: delete_last_target_battle_turn match_id=%s player=%s", match_id, player)
        with self._lock:
            row = self._conn.execute(
                "SELECT id FROM target_battle_turns WHERE match_id = ? AND player = ?"
                " ORDER BY id DESC LIMIT 1", (match_id, player)).fetchone()
            if row:
                turn = self._conn.execute(
                    "SELECT COUNT(*) FROM target_battle_turns WHERE match_id = ? AND player = ?",
                    (match_id, player)).fetchone()[0]
                self._conn.execute(
                    "DELETE FROM dart_positions WHERE match_id = ? AND game_mode = 'Target Battle'"
                    " AND player = ? AND turn = ?", (match_id, player, turn))
                self._conn.execute("DELETE FROM target_battle_turns WHERE id = ?", (row["id"],))
                self._conn.commit()
        self._match_changed(match_id)

    def record_target_battle_results(self, match_id: str, results: list):
        """results: (player, placement, score) per player. Players who tie share a placement."""
        log.debug("DB write: record_target_battle_results match_id=%s results=%s", match_id, results)
        with self._lock:
            for player, placement, score in results:
                self._ensure_player(player)
                self._conn.execute(
                    "INSERT OR REPLACE INTO target_battle_results (match_id, player, placement, score)"
                    " VALUES (?, ?, ?, ?)", (match_id, player, placement, score))
            self._conn.commit()

    def delete_target_battle_results(self, match_id: str):
        """Un-record the results of a match, used when undoing the turn that finished it."""
        log.debug("DB write: delete_target_battle_results match_id=%s", match_id)
        with self._lock:
            self._conn.execute("DELETE FROM target_battle_results WHERE match_id = ?", (match_id,))
            self._conn.commit()

    def record_target_battle_setup(self, match_id: str, scoring: str, rounds: int, tiebreak: bool,
                                   fixed_targets: bool):
        """The rules a game was played under, so the statistics can keep the scoring profiles
        apart."""
        with self._lock:
            self._conn.execute(
                "INSERT OR REPLACE INTO target_battle_games (match_id, scoring, rounds, tiebreak, fixed_targets)"
                " VALUES (?, ?, ?, ?, ?)", (match_id, scoring, rounds, int(tiebreak), int(fixed_targets)))
            self._conn.commit()

    def match_target_battle_stats(self, match_id: str) -> dict:
        """One Target Battle game: its rules, the players by placement with their totals, and every
        round with its target and what each player scored."""
        with self._lock:
            setup = self._conn.execute(
                "SELECT scoring, rounds FROM target_battle_games WHERE match_id = ?", (match_id,)).fetchone()
            results = self._conn.execute(
                "SELECT player, placement, score FROM target_battle_results WHERE match_id = ?"
                " ORDER BY placement, score DESC, player", (match_id,)).fetchall()
            turns = self._conn.execute(
                "SELECT round_no, target, tiebreak, player, score FROM target_battle_turns"
                " WHERE match_id = ? ORDER BY id", (match_id,)).fetchall()
        history = {}
        for t in turns:
            row = history.setdefault((bool(t["tiebreak"]), t["round_no"]), {
                "round": t["round_no"], "tiebreak": bool(t["tiebreak"]), "target": t["target"], "scores": {}})
            row["scores"][t["player"]] = t["score"]
        return {
            "scoring": setup["scoring"] if setup else "standard",
            "rounds": setup["rounds"] if setup else None,
            "players": [{"player": r["player"], "placement": r["placement"], "score": r["score"]} for r in results],
            "history": list(history.values()),
        }

    def target_battle_overview(self, scoring: str = "standard") -> dict:
        """The Target Battle statistics of one scoring profile (older games count as standard).

        Wins, placements, form and head to head come from games with at least two players, the
        numbers about the throwing from every finished game, played alone or not. Players flagged
        `hidden` are left out. Tiebreak turns are not part of the throwing numbers. A dart is a hit
        when it lands on the target number, in any ring; darts of a turn whose total was corrected
        are not counted."""
        scope = ("m.game_mode = 'Target Battle' AND COALESCE(g.scoring, 'standard') = ?"
                 " AND EXISTS (SELECT 1 FROM target_battle_results x WHERE x.match_id = m.match_id)")
        joins = "JOIN matches m ON m.match_id = {t}.match_id LEFT JOIN target_battle_games g ON g.match_id = m.match_id"
        with self._lock:
            matches = self._conn.execute(
                "SELECT m.match_id, m.started_at, m.ended_at, m.points_start AS rounds FROM matches m"
                " LEFT JOIN target_battle_games g ON g.match_id = m.match_id WHERE " + scope +
                " ORDER BY m.started_at", (scoring,)).fetchall()
            results = self._conn.execute(
                "SELECT r.match_id, r.player, r.placement, r.score, COALESCE(p.hidden, 0) AS hidden"
                " FROM target_battle_results r " + joins.format(t="r") +
                " LEFT JOIN players p ON p.name = r.player WHERE " + scope + " ORDER BY r.id", (scoring,)).fetchall()
            turns = self._conn.execute(
                "SELECT t.match_id, t.player, t.target, t.tiebreak, t.darts_count, t.score"
                " FROM target_battle_turns t " + joins.format(t="t") + " WHERE " + scope + " ORDER BY t.id",
                (scoring,)).fetchall()
            darts = self._conn.execute(
                "SELECT d.match_id, d.player, d.turn, d.field FROM dart_positions d " + joins.format(t="d") +
                " WHERE d.game_mode = 'Target Battle' AND d.misread = 0 AND " + scope, (scoring,)).fetchall()
        started = {m["match_id"]: m["started_at"][:10] for m in matches}
        rounds_of = {m["match_id"]: m["rounds"] for m in matches}
        minutes = [(datetime.fromisoformat(m["ended_at"]) - datetime.fromisoformat(m["started_at"])).total_seconds() / 60
                   for m in matches if m["ended_at"]]
        summary = {
            "games": len(matches),
            "total_minutes": round(sum(minutes), 1),
            "avg_minutes": round(sum(minutes) / len(minutes), 1) if minutes else None,
            "longest_minutes": round(max(minutes), 1) if minutes else None,
        }

        in_match = {}
        for r in results:
            in_match.setdefault(r["match_id"], []).append(r)
        stats = {}

        def player(name):
            return stats.setdefault(name, {
                "player": name, "placed": {}, "expected": 0.0, "form": [], "solo_games": 0,
                "turns": 0, "points": 0, "darts": 0, "hits": 0, "perfect_turns": 0, "best_turn": None,
                "by_target": {}})

        pairs = {}
        best_dart = max(SCORING.get(scoring, {1: 1}).values())
        for match_id in (m["match_id"] for m in matches):
            rows = in_match.get(match_id, [])
            size = len(rows)
            visible = [r for r in rows if not r["hidden"]]
            if size < 2:
                for r in visible:
                    player(r["player"])["solo_games"] += 1
                continue
            for r in visible:
                s = player(r["player"])
                s["placed"][r["placement"]] = s["placed"].get(r["placement"], 0) + 1
                s["expected"] += 1.0 / size
                s["form"].append({
                    "match_id": match_id, "date": started[match_id], "placement": r["placement"], "size": size,
                    "opponents": sorted(o["player"] for o in rows if o["player"] != r["player"])})
            for i, r1 in enumerate(visible):
                for r2 in visible[i + 1:]:
                    (a, pa), (b, pb) = sorted([(r1["player"], r1["placement"]), (r2["player"], r2["placement"])])
                    entry = pairs.setdefault((a, b), {"a": a, "b": b, "a_ahead": 0, "b_ahead": 0, "games": 0})
                    entry["games"] += 1
                    if pa != pb:
                        entry["a_ahead" if pa < pb else "b_ahead"] += 1

        # The throwing: the n-th turn of a player in a game is the one its darts are stored under.
        hidden = {r["player"] for r in results if r["hidden"]}
        ordinal, target_of = {}, {}
        for t in turns:
            key = (t["match_id"], t["player"])
            ordinal[key] = ordinal.get(key, 0) + 1
            target_of[key + (ordinal[key],)] = (t["target"], t["tiebreak"])
            if t["tiebreak"] or t["player"] in hidden:
                continue
            s = player(t["player"])
            s["turns"] += 1
            s["points"] += t["score"]
            if t["darts_count"] == 3 and t["score"] == 3 * best_dart:
                s["perfect_turns"] += 1
            if s["best_turn"] is None or t["score"] > s["best_turn"]["score"]:
                s["best_turn"] = {"score": t["score"], "date": started[t["match_id"]], "match_id": t["match_id"]}
        for d in darts:
            target = target_of.get((d["match_id"], d["player"], d["turn"]))
            if target is None or target[1] or d["player"] in hidden:
                continue
            s = player(d["player"])
            field = re.fullmatch(r"[SDT](\d{1,2})", (d["field"] or "").upper())
            hit = bool(field and int(field.group(1)) == target[0])
            s["darts"] += 1
            s["hits"] += hit
            by = s["by_target"].setdefault(target[0], {"target": target[0], "darts": 0, "hits": 0})
            by["darts"] += 1
            by["hits"] += hit

        players = []
        for name, s in stats.items():
            games = sum(s["placed"].values())
            wins = s["placed"].get(1, 0)
            best, run = 0, 0
            for g in s["form"]:
                run = run + 1 if g["placement"] == 1 else 0
                best = max(best, run)
            players.append({
                "player": name,
                "games": games, "wins": wins, "win_pct": round(wins / games * 100, 1) if games else 0.0,
                "placements": {"first": wins, "second": s["placed"].get(2, 0), "third": s["placed"].get(3, 0),
                               "other": sum(n for place, n in s["placed"].items() if place > 3)},
                "expected_wins": round(s["expected"], 2),
                "form": {"games": s["form"][-15:], "current_streak": run, "best_streak": best},
                "solo_games": s["solo_games"],
                "turns": s["turns"],
                "avg_points_per_round": round(s["points"] / s["turns"], 2) if s["turns"] else None,
                "darts": s["darts"], "hits": s["hits"],
                "hit_pct": round(s["hits"] / s["darts"] * 100, 1) if s["darts"] else None,
                "perfect_turns": s["perfect_turns"], "best_turn": s["best_turn"],
                "by_target": sorted(s["by_target"].values(), key=lambda b: b["target"]),
            })
        players.sort(key=lambda p: (-p["games"], -p["wins"], -p["turns"], p["player"]))

        best_game = None
        for r in results:
            if not r["hidden"] and (best_game is None or r["score"] > best_game["score"]):
                best_game = {"score": r["score"], "rounds": rounds_of[r["match_id"]], "player": r["player"],
                             "date": started[r["match_id"]], "match_id": r["match_id"]}
        best_turn = None
        for p in players:
            if p["best_turn"] and (best_turn is None or p["best_turn"]["score"] > best_turn["score"]):
                best_turn = {"score": p["best_turn"]["score"], "player": p["player"], "date": p["best_turn"]["date"]}
        return {
            "scoring": scoring,
            "summary": summary,
            "records": {"best_game": best_game, "best_turn": best_turn},
            "players": players,
            "head_to_head": sorted(pairs.values(), key=lambda e: (-e["games"], e["a"], e["b"])),
        }

    # ── Killer ────────────────────────────────────────────────────────────────

    def record_killer_setup(self, match_id: str, own_goal: bool, singles: bool):
        log.debug("DB write: record_killer_setup match_id=%s own_goal=%s singles=%s",
                  match_id, own_goal, singles)
        with self._lock:
            self._conn.execute(
                "INSERT OR REPLACE INTO killer_games (match_id, own_goal, singles) VALUES (?, ?, ?)",
                (match_id, int(own_goal), int(singles)))
            self._conn.commit()

    def insert_killer_turn(self, match_id, player, darts_count, events, positions=None):
        """One finished turn with what its darts did. events: dicts with kind, dart, victim, number
        and lives (the victim's lives afterwards). positions: one {"field", "x", "y"} (or None) per dart."""
        log.debug("DB write: insert_killer_turn match_id=%s player=%s darts_count=%s events=%s",
                  match_id, player, darts_count, events)
        with self._lock:
            self._ensure_player(player)
            cur = self._conn.execute(
                "INSERT INTO killer_turns (match_id, player, darts_count, created_at) VALUES (?, ?, ?, ?)",
                (match_id, player, darts_count, _now_iso()))
            turn_id = cur.lastrowid
            for e in events:
                self._conn.execute(
                    "INSERT INTO killer_events (turn_id, match_id, player, kind, victim, dart_no, number,"
                    " lives_after) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                    (turn_id, match_id, e["player"], e["kind"], e.get("victim"), e["dart"],
                     e.get("number"), e.get("lives")))
            turn = self._conn.execute(
                "SELECT COUNT(*) FROM killer_turns WHERE match_id = ? AND player = ?",
                (match_id, player)).fetchone()[0]
            self._insert_positions(match_id, "Killer", player, 1, turn,
                                   [((p or {}).get("field"), p) for p in positions or []])
            self._conn.commit()

    def delete_last_killer_turn(self, match_id: str, player: str):
        """Undo insert_killer_turn() for the player's most recent turn."""
        log.debug("DB write: delete_last_killer_turn match_id=%s player=%s", match_id, player)
        with self._lock:
            row = self._conn.execute(
                "SELECT id FROM killer_turns WHERE match_id = ? AND player = ? ORDER BY id DESC LIMIT 1",
                (match_id, player)).fetchone()
            if row:
                turn = self._conn.execute(
                    "SELECT COUNT(*) FROM killer_turns WHERE match_id = ? AND player = ?",
                    (match_id, player)).fetchone()[0]
                self._conn.execute(
                    "DELETE FROM dart_positions WHERE match_id = ? AND game_mode = 'Killer'"
                    " AND player = ? AND turn = ?", (match_id, player, turn))
                self._conn.execute("DELETE FROM killer_events WHERE turn_id = ?", (row["id"],))
                self._conn.execute("DELETE FROM killer_turns WHERE id = ?", (row["id"],))
                self._conn.commit()
        self._match_changed(match_id)

    def record_killer_results(self, match_id: str, results: list):
        """results: (player, placement, lives_left, number) per player, lives_left only for the winner."""
        log.debug("DB write: record_killer_results match_id=%s results=%s", match_id, results)
        with self._lock:
            for player, placement, lives_left, number in results:
                self._ensure_player(player)
                self._conn.execute(
                    "INSERT OR REPLACE INTO killer_results (match_id, player, placement, lives_left, number)"
                    " VALUES (?, ?, ?, ?, ?)", (match_id, player, placement, lives_left, number))
            self._conn.commit()

    def delete_killer_results(self, match_id: str):
        log.debug("DB write: delete_killer_results match_id=%s", match_id)
        with self._lock:
            self._conn.execute("DELETE FROM killer_results WHERE match_id = ?", (match_id,))
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
        self._match_changed(match_id)

    def insert_elimination_turn(self, match_id: str, player: str, darts_count: int,
                                score: int | None = None, target: int | None = None,
                                freipass: bool | None = None, passed: bool | None = None,
                                lives_before: int | None = None, positions=None):
        """`target` is the score this turn had to beat (0 on a freipass), `passed`
        whether it did, `lives_before` the player's lives going into the turn.
        positions: one {"field", "x", "y"} (or None) per dart."""
        log.debug("DB write: insert_elimination_turn match_id=%s player=%s darts_count=%s "
                  "score=%s target=%s freipass=%s passed=%s lives_before=%s",
                  match_id, player, darts_count, score, target, freipass, passed, lives_before)
        with self._lock:
            self._ensure_player(player)
            self._conn.execute(
                "INSERT INTO elimination_turns"
                " (match_id, player, darts_count, score, target, freipass, passed, lives_before,"
                " created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (match_id, player, darts_count, score, target,
                 None if freipass is None else int(freipass),
                 None if passed is None else int(passed), lives_before, _now_iso()),
            )
            turn = self._conn.execute(
                "SELECT COUNT(*) FROM elimination_turns WHERE match_id = ? AND player = ?",
                (match_id, player)).fetchone()[0]
            self._insert_positions(match_id, "Elimination", player, 1, turn,
                                   [((p or {}).get("field"), p) for p in positions or []])
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
            # The darts of a turn whose total was corrected were misread: neither their
            # fields nor their positions tell what was hit.
            self._conn.execute(
                "UPDATE dart_positions SET corrected = 1, misread = 1"
                " WHERE match_id = ? AND game_mode = 'Elimination' AND player = ? AND turn = ("
                " SELECT COUNT(*) FROM elimination_turns WHERE match_id = ? AND player = ?)",
                (match_id, player, match_id, player),
            )
            self._conn.commit()
        self._match_changed(match_id)

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
                    score, is_bust, is_checkout, darts, positions=None):
        """darts: list of (field_str, value_int, remaining_after_int), up to 3 entries.
        positions: one entry per dart, {"x", "y", "entry"} or None if the position is unknown."""
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
                " dart3, dart3_val, dart3_rem, created_at)"
                " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (match_id, player, leg, turn, remaining_before, score,
                 int(is_bust), int(is_checkout), len(darts),
                 d[0][0], d[0][1], d[0][2],
                 d[1][0], d[1][1], d[1][2],
                 d[2][0], d[2][1], d[2][2], _now_iso()),
            )
            self._insert_positions(match_id, "X01", player, leg, turn,
                                   [(f, p) for (f, _, _), p in zip(darts, positions or [])])
            self._conn.commit()

    def _insert_positions(self, match_id, game_mode, player, leg, turn, fields_positions):
        """Caller holds the lock and commits. fields_positions: (field, position) per
        dart, in dart order; darts without a position are skipped."""
        for number, (field, pos) in enumerate(fields_positions, start=1):
            if not pos:
                continue
            self._conn.execute(
                "INSERT INTO dart_positions"
                " (match_id, game_mode, player, leg, turn, dart_number, field, x, y, entry, corrected)"
                " VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                (match_id, game_mode, player, leg, turn, number, field, pos["x"], pos["y"],
                 pos.get("entry"), int(_is_corrected(field, pos["x"], pos["y"], pos.get("entry")))))

    # ── Queries ───────────────────────────────────────────────────────────────

    def session_stats(self, match_id: str) -> dict:
        """Per-player stats dict for one match (queried from DB)."""
        with self._lock:
            rows = self._conn.execute(f"""
                SELECT player,
                    COUNT(*) as turns,
                    SUM(score) as total_score,
                    SUM(darts_count) as total_darts,
                    SUM(CASE WHEN score = 180 THEN 1 ELSE 0 END) as s180,
                    SUM(CASE WHEN score >= 140 AND score < 180 THEN 1 ELSE 0 END) as s140,
                    SUM(CASE WHEN score >= 100 AND score < 140 THEN 1 ELSE 0 END) as s100,
                    {_checkout_columns()}
                FROM turns WHERE match_id = ?
                GROUP BY player
            """, (match_id,)).fetchall()
        return {r["player"]: _row_stats(r) for r in rows}

    def all_players_stats(self) -> list:
        """Lifetime stats for every player that has ever played, excluding
        players flagged `hidden` (comparison/leaderboard views only — a
        direct player_stats() lookup still works for a hidden player)."""
        with self._lock:
            rows = self._conn.execute(f"""
                SELECT t.player as player,
                    COUNT(DISTINCT t.match_id) as sessions,
                    COUNT(*) as turns,
                    SUM(t.score) as total_score,
                    SUM(t.darts_count) as total_darts,
                    SUM(CASE WHEN t.score = 180 THEN 1 ELSE 0 END) as s180,
                    SUM(CASE WHEN t.score >= 140 AND t.score < 180 THEN 1 ELSE 0 END) as s140,
                    SUM(CASE WHEN t.score >= 100 AND t.score < 140 THEN 1 ELSE 0 END) as s100,
                    {_checkout_columns('t.')}
                FROM turns t
                LEFT JOIN players p ON p.name = t.player
                WHERE COALESCE(p.hidden, 0) = 0
                GROUP BY t.player
                ORDER BY sessions DESC, total_score DESC
            """).fetchall()
        return [{"player": r["player"], **_row_stats_full(r)} for r in rows]

    def leaderboard(self, metric: str, limit: int = 10) -> list:
        """Top-N players sorted by *metric* (desc). Valid metrics: avg3, s180, co_pct, total_score."""
        valid = {"avg3", "s180", "co_pct", "total_score"}
        if metric not in valid:
            raise ValueError(f"Invalid leaderboard metric: {metric!r}")
        rows = self.all_players_stats()
        rows.sort(key=lambda r: r.get(metric) or 0, reverse=True)
        return rows[:limit]

    def player_stats(self, player: str) -> dict | None:
        """Lifetime stats for a single player."""
        with self._lock:
            row = self._conn.execute(f"""
                SELECT COUNT(DISTINCT match_id) as sessions,
                    COUNT(*) as turns,
                    SUM(score) as total_score,
                    SUM(darts_count) as total_darts,
                    SUM(CASE WHEN score = 180 THEN 1 ELSE 0 END) as s180,
                    SUM(CASE WHEN score >= 140 AND score < 180 THEN 1 ELSE 0 END) as s140,
                    SUM(CASE WHEN score >= 100 AND score < 140 THEN 1 ELSE 0 END) as s100,
                    {_checkout_columns()}
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
            self._conn.execute("DELETE FROM target_battle_turns WHERE player = ?", (player,))
            self._conn.execute("DELETE FROM target_battle_results WHERE player = ?", (player,))
            self._conn.execute("DELETE FROM dart_positions WHERE player = ? AND game_mode = 'Target Battle'", (player,))
            self._conn.execute("DELETE FROM killer_events WHERE player = ? OR victim = ?", (player, player))
            self._conn.execute("DELETE FROM killer_turns WHERE player = ?", (player,))
            self._conn.execute("DELETE FROM killer_results WHERE player = ?", (player,))
            self._conn.execute("DELETE FROM dart_positions WHERE player = ? AND game_mode = 'Killer'", (player,))
            self._conn.execute("DELETE FROM achievements_earned WHERE player = ?", (player,))
            self._conn.execute("DELETE FROM players WHERE name = ?", (player,))
            self._conn.commit()
        log.info("Deleted all stats for player: %s", player)

    # ── Achievements ──────────────────────────────────────────────────────────

    def achievements_start(self) -> str:
        """Only matches that started at or after this time count for achievements."""
        with self._lock:
            return self._conn.execute(
                "SELECT value FROM achievements_meta WHERE key = 'start'").fetchone()[0]

    def set_achievements_start(self, iso: str):
        with self._lock:
            self._conn.execute(
                "INSERT OR REPLACE INTO achievements_meta (key, value) VALUES ('start', ?)", (iso,))
            self._conn.commit()

    def match_row(self, match_id: str) -> dict | None:
        with self._lock:
            row = self._conn.execute(
                "SELECT m.match_id, m.game_mode, m.points_start, m.winner, m.started_at, m.ended_at,"
                " COALESCE(g.scoring, 'standard') AS scoring FROM matches m"
                " LEFT JOIN target_battle_games g ON g.match_id = m.match_id"
                " WHERE m.match_id = ?", (match_id,)).fetchone()
        return dict(row) if row else None

    def match_participants(self, match_id: str) -> list:
        with self._lock:
            rows = self._conn.execute(
                "SELECT player FROM turns WHERE match_id = ?"
                " UNION SELECT player FROM elimination_turns WHERE match_id = ?"
                " UNION SELECT player FROM elimination_results WHERE match_id = ?"
                " UNION SELECT player FROM target_battle_turns WHERE match_id = ?"
                " UNION SELECT player FROM target_battle_results WHERE match_id = ?"
                " UNION SELECT player FROM killer_turns WHERE match_id = ?"
                " UNION SELECT player FROM killer_results WHERE match_id = ?",
                (match_id,) * 7).fetchall()
        return sorted(r[0] for r in rows)

    def player_final_matches(self, player: str, since: str) -> list:
        """Closed matches the player took part in that started at or after `since`,
        oldest first."""
        with self._lock:
            rows = self._conn.execute(
                "SELECT m.match_id, m.game_mode, m.points_start, m.winner, m.started_at, m.ended_at,"
                " COALESCE(g.scoring, 'standard') AS scoring FROM matches m"
                " LEFT JOIN target_battle_games g ON g.match_id = m.match_id"
                " WHERE m.ended_at IS NOT NULL AND m.started_at >= ? AND ("
                " EXISTS (SELECT 1 FROM turns t WHERE t.match_id = m.match_id AND t.player = ?)"
                " OR EXISTS (SELECT 1 FROM elimination_turns e WHERE e.match_id = m.match_id AND e.player = ?)"
                " OR EXISTS (SELECT 1 FROM elimination_results r WHERE r.match_id = m.match_id AND r.player = ?)"
                " OR EXISTS (SELECT 1 FROM target_battle_turns b WHERE b.match_id = m.match_id AND b.player = ?)"
                " OR EXISTS (SELECT 1 FROM target_battle_results c WHERE c.match_id = m.match_id AND c.player = ?)"
                " OR EXISTS (SELECT 1 FROM killer_turns k WHERE k.match_id = m.match_id AND k.player = ?)"
                " OR EXISTS (SELECT 1 FROM killer_results l WHERE l.match_id = m.match_id AND l.player = ?))"
                " ORDER BY m.started_at, m.match_id", (since,) + (player,) * 7).fetchall()
        return [dict(r) for r in rows]

    def turns_for_achievements(self, match_id: str, player: str, game_mode: str) -> list:
        """The player's turns of a match as {number, score, is_bust, darts}. `darts` are the
        field names that can be trusted: all stored X01 darts, and for Elimination and Target
        Battle the stored darts except those of a turn whose total was corrected (a dart set
        by a correction counts, its field is known). A Target Battle turn also has its target,
        its round and whether it belongs to a tiebreak."""
        with self._lock:
            if game_mode == "Target Battle":
                turn_rows = self._conn.execute(
                    "SELECT round_no, target, tiebreak, score FROM target_battle_turns"
                    " WHERE match_id = ? AND player = ? ORDER BY id", (match_id, player)).fetchall()
                dart_rows = self._conn.execute(
                    "SELECT turn, field FROM dart_positions WHERE match_id = ? AND player = ?"
                    " AND game_mode = 'Target Battle' AND misread = 0 ORDER BY turn, dart_number",
                    (match_id, player)).fetchall()
                fields = {}
                for r in dart_rows:
                    fields.setdefault(r["turn"], []).append((r["field"] or "").upper())
                return [{"number": n, "score": r["score"], "is_bust": False, "darts": tuple(fields.get(n, ())),
                         "target": r["target"], "round_no": r["round_no"], "tiebreak": bool(r["tiebreak"])}
                        for n, r in enumerate(turn_rows, start=1)]
            if game_mode == "Elimination":
                rows = self._conn.execute(
                    "SELECT turn, field FROM dart_positions WHERE match_id = ? AND player = ?"
                    " AND game_mode = ? AND misread = 0 ORDER BY turn, dart_number",
                    (match_id, player, game_mode)).fetchall()
                turns = {}
                for r in rows:
                    turns.setdefault(r["turn"], []).append((r["field"] or "").upper())
                return [{"number": n, "score": None, "is_bust": False, "darts": tuple(d)}
                        for n, d in sorted(turns.items())]
            rows = self._conn.execute(
                "SELECT turn, leg, score, is_bust, is_checkout, remaining_before, dart1, dart2, dart3,"
                " created_at FROM turns WHERE match_id = ? AND player = ? ORDER BY id",
                (match_id, player)).fetchall()
        return [{"number": r["turn"], "score": r["score"], "is_bust": bool(r["is_bust"]),
                 "darts": tuple(d.upper() for d in (r["dart1"], r["dart2"], r["dart3"]) if d),
                 "is_checkout": bool(r["is_checkout"]), "remaining_before": r["remaining_before"],
                 "leg": r["leg"], "at": r["created_at"]}
                for r in rows]

    def x01_turn_rows(self, match_id: str) -> list:
        """Every turn of every player of an X01 match, in the order played."""
        with self._lock:
            rows = self._conn.execute(
                "SELECT player, leg, remaining_before, score, is_bust, is_checkout FROM turns"
                " WHERE match_id = ? ORDER BY id", (match_id,)).fetchall()
        return [{"player": r["player"], "leg": r["leg"], "remaining_before": r["remaining_before"],
                 "score": r["score"], "is_bust": bool(r["is_bust"]), "is_checkout": bool(r["is_checkout"])}
                for r in rows]

    def elimination_turn_rows(self, match_id: str) -> list:
        """Every turn of an Elimination match, in the order played: player, score, `to_beat`
        (what the turn had to beat, 0 with a freipass), freipass, passed and lives_before."""
        with self._lock:
            rows = self._conn.execute(
                "SELECT player, score, target, freipass, passed, lives_before FROM elimination_turns"
                " WHERE match_id = ? ORDER BY id", (match_id,)).fetchall()
        return [{"player": r["player"], "score": r["score"], "to_beat": r["target"] or 0,
                 "freipass": bool(r["freipass"]), "passed": bool(r["passed"]),
                 "lives_before": r["lives_before"]} for r in rows]

    def elimination_results(self, match_id: str) -> list:
        """The result of an Elimination match: player, placement and, for the winner, the lives left."""
        with self._lock:
            rows = self._conn.execute(
                "SELECT player, placement, lives_left FROM elimination_results WHERE match_id = ?"
                " ORDER BY placement, player", (match_id,)).fetchall()
        return [dict(r) for r in rows]

    def target_battle_results(self, match_id: str) -> list:
        """The result of a Target Battle game: player, placement and total of everybody."""
        with self._lock:
            rows = self._conn.execute(
                "SELECT player, placement, score FROM target_battle_results WHERE match_id = ?"
                " ORDER BY placement, player", (match_id,)).fetchall()
        return [dict(r) for r in rows]

    def target_battle_turn_rows(self, match_id: str) -> list:
        """Every turn of a Target Battle game, of every player, in the order they were played."""
        with self._lock:
            rows = self._conn.execute(
                "SELECT player, round_no, tiebreak, score FROM target_battle_turns"
                " WHERE match_id = ? ORDER BY id", (match_id,)).fetchall()
        return [{"player": r["player"], "round_no": r["round_no"], "tiebreak": bool(r["tiebreak"]),
                 "score": r["score"]} for r in rows]

    def achievement_distribution(self, since: str) -> tuple:
        """(number of players, {(achievement_id, tier): number who earned it}). The players
        are the visible ones with a closed match that started at or after `since`."""
        with self._lock:
            players = self._conn.execute(
                "SELECT COUNT(DISTINCT p.player) FROM ("
                " SELECT player, match_id FROM turns"
                " UNION SELECT player, match_id FROM elimination_turns"
                " UNION SELECT player, match_id FROM elimination_results"
                " UNION SELECT player, match_id FROM target_battle_turns"
                " UNION SELECT player, match_id FROM target_battle_results"
                " UNION SELECT player, match_id FROM killer_turns"
                " UNION SELECT player, match_id FROM killer_results) p"
                " JOIN matches m ON m.match_id = p.match_id"
                " WHERE m.ended_at IS NOT NULL AND m.started_at >= ?"
                " AND p.player NOT IN (SELECT name FROM players WHERE hidden = 1)",
                (since,)).fetchone()[0]
            rows = self._conn.execute(
                "SELECT achievement_id, tier, COUNT(*) FROM achievements_earned"
                " WHERE player NOT IN (SELECT name FROM players WHERE hidden = 1)"
                " GROUP BY achievement_id, tier").fetchall()
        return players, {(r[0], r[1]): r[2] for r in rows}

    def earned_rows(self, player: str, achievement_id: str) -> list:
        with self._lock:
            rows = self._conn.execute(
                "SELECT id, tier, earned_at, match_id FROM achievements_earned"
                " WHERE player = ? AND achievement_id = ? ORDER BY tier",
                (player, achievement_id)).fetchall()
        return [dict(r) for r in rows]

    def earned_for_player(self, player: str) -> list:
        with self._lock:
            rows = self._conn.execute(
                "SELECT achievement_id, tier, earned_at, match_id FROM achievements_earned"
                " WHERE player = ? ORDER BY earned_at, id", (player,)).fetchall()
        return [dict(r) for r in rows]

    def add_earned(self, player: str, achievement_id: str, tier: int, match_id: str | None):
        log.debug("DB write: add_earned player=%s achievement=%s tier=%s match_id=%s",
                  player, achievement_id, tier, match_id)
        with self._lock:
            self._ensure_player(player)
            self._conn.execute(
                "INSERT OR IGNORE INTO achievements_earned"
                " (player, achievement_id, tier, earned_at, match_id) VALUES (?, ?, ?, ?, ?)",
                (player, achievement_id, tier, _now_iso(), match_id))
            self._conn.commit()

    def set_earned_match(self, row_id: int, match_id: str):
        with self._lock:
            self._conn.execute(
                "UPDATE achievements_earned SET match_id = ? WHERE id = ?", (match_id, row_id))
            self._conn.commit()

    def delete_earned(self, row_id: int):
        log.debug("DB write: delete_earned id=%s", row_id)
        with self._lock:
            self._conn.execute("DELETE FROM achievements_earned WHERE id = ?", (row_id,))
            self._conn.commit()

    def recent_matches(self, limit: int = 20, mode: str | None = None) -> list:
        """Newest first. `mode` ("x01" or "elimination") restricts which game mode
        counts toward the limit; None returns both."""
        mode_sql = {
            "x01": f" AND COALESCE(game_mode, '') NOT IN {_OTHER_MODES_SQL}",
            "elimination": " AND game_mode = 'Elimination'",
            "target_battle": " AND game_mode = 'Target Battle'",
            "killer": " AND game_mode = 'Killer'",
        }.get(mode, "")
        with self._lock:
            rows = self._conn.execute(
                "SELECT match_id, started_at, ended_at, game_mode, points_start, players"
                " FROM matches"
                " WHERE (EXISTS (SELECT 1 FROM turns WHERE turns.match_id = matches.match_id)"
                "    OR EXISTS (SELECT 1 FROM elimination_turns WHERE elimination_turns.match_id = matches.match_id)"
                "    OR EXISTS (SELECT 1 FROM target_battle_turns WHERE target_battle_turns.match_id = matches.match_id)"
                "    OR EXISTS (SELECT 1 FROM killer_turns WHERE killer_turns.match_id = matches.match_id))"
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
            scoring = None
            if r["game_mode"] == "Target Battle":
                with self._lock:
                    setup = self._conn.execute(
                        "SELECT scoring FROM target_battle_games WHERE match_id = ?", (mid,)).fetchone()
                scoring = setup["scoring"] if setup else "standard"
            result.append({
                "match_id":    mid,
                "scoring":     scoring,
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
        if mode_row and mode_row["game_mode"] == "Target Battle":
            return self.match_target_battle_stats(match_id)
        with self._lock:
            rows = self._conn.execute(f"""
                SELECT player,
                    COUNT(*) as turns,
                    SUM(score) as total_score,
                    SUM(darts_count) as total_darts,
                    SUM(CASE WHEN score = 180 THEN 1 ELSE 0 END) as s180,
                    SUM(CASE WHEN score >= 140 AND score < 180 THEN 1 ELSE 0 END) as s140,
                    SUM(CASE WHEN score >= 100 AND score < 140 THEN 1 ELSE 0 END) as s100,
                    {_checkout_columns()}
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
            leg_501_row = self._conn.execute("""
                SELECT MIN(darts) as darts FROM (
                    SELECT SUM(t.darts_count) as darts
                    FROM turns t
                    JOIN legs l ON l.match_id = t.match_id AND l.leg = t.leg
                    JOIN matches m ON m.match_id = t.match_id
                    WHERE l.winner = ? AND t.player = ? AND m.points_start = 501
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
            "best_leg_501_darts": leg_501_row["darts"] if leg_501_row and leg_501_row["darts"] is not None else None,
            "best_checkout": co_row["best"] if co_row and co_row["best"] is not None else None,
            "total_180s": s180_row["n"] or 0 if s180_row else 0,
        }

    def player_score_histogram(self, player: str) -> dict:
        """How often each turn score came up, in bins of ten points (0-9, 10-19, ...,
        170-179, 180), with the 3-dart average. Busts count as the turns they are."""
        with self._lock:
            rows = self._conn.execute(
                "SELECT score / 10 as bin, COUNT(*) as n FROM turns WHERE player = ? GROUP BY bin",
                (player,),
            ).fetchall()
            total = self._conn.execute(
                "SELECT COUNT(*) as turns, SUM(score) as score, SUM(darts_count) as darts"
                " FROM turns WHERE player = ?", (player,),
            ).fetchone()
        bins = [0] * 19
        for r in rows:
            bins[min(r["bin"], 18)] += r["n"]
        return {
            "bins": bins,
            "turns": total["turns"] or 0,
            "avg3": round(total["score"] * 3.0 / total["darts"], 1) if total["darts"] else None,
        }

    # Starting scores of a turn, grouped to see where busts happen (the labels are shown as they are).
    _BUST_BANDS = (("≤ 10", 0, 10), ("11–20", 11, 20), ("21–30", 21, 30), ("31–40", 31, 40),
                   ("41–60", 41, 60), ("61–100", 61, 100), ("101–170", 101, 170), ("> 170", 171, None))

    def player_bust_by_remaining(self, player: str) -> dict:
        """Turns and busts by the score a turn started on, in fixed bands, plus the totals."""
        with self._lock:
            rows = self._conn.execute(
                "SELECT remaining_before as remaining, is_bust FROM turns WHERE player = ?", (player,)
            ).fetchall()
        bands = [{"label": label, "turns": 0, "busts": 0} for label, _, _ in self._BUST_BANDS]
        for r in rows:
            for band, (_, low, high) in zip(bands, self._BUST_BANDS):
                if r["remaining"] >= low and (high is None or r["remaining"] <= high):
                    band["turns"] += 1
                    band["busts"] += 1 if r["is_bust"] else 0
                    break
        return {"bands": bands, "turns": len(rows), "busts": sum(b["busts"] for b in bands)}

    def player_dart_hits(self, player: str) -> dict:
        """Where this player's darts went, from the recorded dart fields: hits per
        field on the board (`S20`, `D16`, `T19`, `25`, `BULL`), misses per sector (the
        darts that landed outside the scoring area next to that number, `M11`), and the
        misses without any sector."""
        fields, misses, no_sector, darts = {}, {}, 0, 0
        with self._lock:
            rows = self._conn.execute(
                "SELECT dart1, dart2, dart3 FROM turns WHERE player = ?", (player,)).fetchall()
        for row in rows:
            for raw in row:
                if not raw:
                    continue
                darts += 1
                field = raw.upper()
                miss = re.fullmatch(r"M(\d{1,2})", field)
                if miss:
                    misses[miss.group(1)] = misses.get(miss.group(1), 0) + 1
                elif field == "MISS":
                    no_sector += 1
                else:
                    fields[field] = fields.get(field, 0) + 1
        return {"darts": darts, "fields": fields, "misses": misses, "no_sector_misses": no_sector}

    def player_dart_positions(self, player: str, mode: str = "x01", limit: int = 3000) -> dict:
        """Where this player's darts landed, newest `limit` darts: `darts` as {x, y, field},
        unit = outer edge of the double ring, y up. Darts set by a correction are not
        listed, they only count in `corrected`. `total` is everything recorded."""
        where = "game_mode = 'Elimination'" if mode == "elimination" else f"game_mode NOT IN {_OTHER_MODES_SQL}"
        with self._lock:
            rows = self._conn.execute(
                f"SELECT x, y, field, corrected FROM dart_positions WHERE player = ? AND {where}"
                " ORDER BY id DESC LIMIT ?", (player, limit)).fetchall()
            total = self._conn.execute(
                f"SELECT COUNT(*) FROM dart_positions WHERE player = ? AND {where}", (player,)).fetchone()[0]
        return {
            "darts": [{"x": round(r["x"], 4), "y": round(r["y"], 4), "field": r["field"]}
                      for r in rows if not r["corrected"]],
            "corrected": sum(1 for r in rows if r["corrected"]),
            "total": total,
        }

    def player_avg_by_match(self, player: str) -> list:
        """The 3-dart average of each match the player threw darts in, oldest first."""
        with self._lock:
            rows = self._conn.execute("""
                SELECT t.match_id as match_id, m.started_at as started_at, m.points_start as points_start,
                       SUM(t.score) as score, SUM(t.darts_count) as darts
                FROM turns t JOIN matches m ON m.match_id = t.match_id
                WHERE t.player = ?
                GROUP BY t.match_id HAVING SUM(t.darts_count) > 0
                ORDER BY m.started_at
            """, (player,)).fetchall()
        return [
            {"match_id": r["match_id"], "started_at": r["started_at"], "points_start": r["points_start"],
             "darts": r["darts"], "avg3": round(r["score"] * 3.0 / r["darts"], 1)}
            for r in rows
        ]

    def player_checkout_by_match(self, player: str) -> list:
        """Checkout % of each match, oldest first: hits over the darts thrown at a score a
        double can finish. Matches without such a dart are left out."""
        with self._lock:
            rows = self._conn.execute(f"""
                SELECT t.match_id as match_id, m.started_at as started_at,
                       SUM({_checkout_exprs('t.')[0]}) as attempts,
                       SUM({_checkout_exprs('t.')[1]}) as hits
                FROM turns t JOIN matches m ON m.match_id = t.match_id
                WHERE t.player = ?
                GROUP BY t.match_id HAVING attempts > 0
                ORDER BY m.started_at
            """, (player,)).fetchall()
        return [
            {"match_id": r["match_id"], "started_at": r["started_at"], "attempts": r["attempts"],
             "hits": r["hits"], "co_pct": round(r["hits"] / r["attempts"] * 100, 1)}
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
        player_elimination_stats plus the name and `expected_wins`: the wins a
        player would have by chance, i.e. 1/players summed over their games (a win
        against one opponent is worth less than against two). Players flagged
        `hidden` are left out, and so are players without a recorded result."""
        with self._lock:
            place_rows = self._conn.execute("""
                SELECT r.player as player, r.placement as placement, COUNT(*) as n,
                       SUM(1.0 / f.size) as expected
                FROM elimination_results r
                JOIN (SELECT match_id, COUNT(*) as size FROM elimination_results GROUP BY match_id) f
                  ON f.match_id = r.match_id
                LEFT JOIN players p ON p.name = r.player
                WHERE COALESCE(p.hidden, 0) = 0
                GROUP BY r.player, r.placement
            """).fetchall()
            avg_rows = self._conn.execute(
                "SELECT player, AVG(darts_count) as avg_darts FROM elimination_turns GROUP BY player"
            ).fetchall()
        by_player, expected = {}, {}
        for r in place_rows:
            by_player.setdefault(r["player"], {})[r["placement"]] = r["n"]
            expected[r["player"]] = expected.get(r["player"], 0.0) + r["expected"]
        avg = {r["player"]: r["avg_darts"] for r in avg_rows}
        result = [
            {"player": name, **_elimination_summary(by_place, avg.get(name)),
             "expected_wins": round(expected[name], 2)}
            for name, by_place in by_player.items()
        ]
        result.sort(key=lambda r: (-r["games"], -r["wins"], r["player"]))
        return result

    def elimination_form(self, limit: int = 15) -> dict:
        """Per player (hidden players left out): their last `limit` finished
        Elimination games, oldest first, each with the date, placement, number of
        players and opponents, plus the current and best win streak over all their
        games."""
        with self._lock:
            rows = self._conn.execute("""
                SELECT r.player as player, r.placement as placement, r.match_id as match_id,
                       m.started_at as started_at
                FROM elimination_results r
                JOIN matches m ON m.match_id = r.match_id
                LEFT JOIN players p ON p.name = r.player
                WHERE m.game_mode = 'Elimination' AND COALESCE(p.hidden, 0) = 0
                ORDER BY m.started_at, r.id
            """).fetchall()
            everyone = self._conn.execute(
                "SELECT match_id, player FROM elimination_results"
            ).fetchall()
        in_match = {}
        for r in everyone:
            in_match.setdefault(r["match_id"], []).append(r["player"])
        games = {}
        for r in rows:
            players = in_match[r["match_id"]]
            games.setdefault(r["player"], []).append({
                "match_id": r["match_id"],
                "date": r["started_at"][:10],
                "placement": r["placement"],
                "size": len(players),
                "opponents": sorted(p for p in players if p != r["player"]),
            })
        result = {}
        for name, played in games.items():
            best = run = 0
            for g in played:
                run = run + 1 if g["placement"] == 1 else 0
                best = max(best, run)
            result[name] = {"games": played[-limit:], "current_streak": run, "best_streak": best}
        return result

    def elimination_head_to_head(self) -> list:
        """For every pair of players that finished games together: how often each
        finished ahead of the other (a lower placement is ahead, so in a
        three-player game all three pairs are counted). Players flagged `hidden`
        are left out. The pair is ordered by name; most shared games first."""
        with self._lock:
            rows = self._conn.execute("""
                SELECT r.match_id as match_id, r.player as player, r.placement as placement
                FROM elimination_results r
                LEFT JOIN players p ON p.name = r.player
                WHERE COALESCE(p.hidden, 0) = 0
            """).fetchall()
        by_match = {}
        for r in rows:
            by_match.setdefault(r["match_id"], []).append((r["player"], r["placement"]))
        pairs = {}
        for finishers in by_match.values():
            for i, (p1, place1) in enumerate(finishers):
                for p2, place2 in finishers[i + 1:]:
                    (a, place_a), (b, place_b) = sorted([(p1, place1), (p2, place2)])
                    entry = pairs.setdefault((a, b), {"a": a, "b": b, "a_ahead": 0, "b_ahead": 0, "games": 0})
                    entry["games"] += 1
                    entry["a_ahead" if place_a < place_b else "b_ahead"] += 1
        return sorted(pairs.values(), key=lambda e: (-e["games"], e["a"], e["b"]))

    def elimination_game_lengths(self) -> list:
        """Every finished Elimination game that has an end time, oldest first: its
        lives setting, length in minutes, number of players and winner."""
        with self._lock:
            rows = self._conn.execute("""
                SELECT m.match_id as match_id, m.started_at as started_at, m.points_start as lives,
                       m.winner as winner,
                       (julianday(m.ended_at) - julianday(m.started_at)) * 1440 as minutes,
                       (SELECT COUNT(*) FROM elimination_results r WHERE r.match_id = m.match_id) as size
                FROM matches m
                WHERE m.game_mode = 'Elimination' AND m.ended_at IS NOT NULL AND m.points_start IS NOT NULL
                  AND EXISTS (SELECT 1 FROM elimination_results r WHERE r.match_id = m.match_id)
                ORDER BY m.started_at
            """).fetchall()
        return [
            {"match_id": r["match_id"], "date": r["started_at"][:10], "lives": r["lives"],
             "minutes": round(r["minutes"], 1), "size": r["size"], "winner": r["winner"]}
            for r in rows
        ]

    def elimination_records(self, player: str | None = None) -> dict:
        """The highest score thrown in an Elimination turn, and the highest score
        that still lost a life (it did not beat the score before it, `target`).
        Each is None, or {score, target, player, date}, the first time it was
        reached. Only turns recorded with a score count, so both stay None for
        games played before scores were stored. Over everyone (hidden players left
        out), or for one `player` (a direct lookup, hidden or not)."""
        who, params = ("AND t.player = ?", (player,)) if player else ("AND COALESCE(p.hidden, 0) = 0", ())

        def best(extra=""):
            with self._lock:
                row = self._conn.execute(f"""
                    SELECT t.score as score, t.target as target, t.player as player,
                           m.started_at as started_at
                    FROM elimination_turns t
                    JOIN matches m ON m.match_id = t.match_id
                    LEFT JOIN players p ON p.name = t.player
                    WHERE t.score IS NOT NULL {who} {extra}
                    ORDER BY t.score DESC, m.started_at, t.id
                    LIMIT 1
                """, params).fetchone()
            if not row:
                return None
            return {"score": row["score"], "target": row["target"],
                    "player": row["player"], "date": row["started_at"][:10]}
        return {"highest_score": best(), "highest_lost_score": best("AND t.passed = 0")}

    def elimination_summary(self) -> dict:
        """Finished Elimination matches (those with a recorded result): how many,
        and how long they took. Minutes are None until a match has an end time."""
        with self._lock:
            rows = self._conn.execute("""
                SELECT (julianday(m.ended_at) - julianday(m.started_at)) * 1440 as minutes
                FROM matches m
                WHERE m.game_mode = 'Elimination'
                  AND EXISTS (SELECT 1 FROM elimination_results r WHERE r.match_id = m.match_id)
            """).fetchall()
        minutes = [r["minutes"] for r in rows if r["minutes"] is not None]
        return {
            "games": len(rows),
            "total_minutes": round(sum(minutes), 1),
            "avg_minutes": round(sum(minutes) / len(minutes), 1) if minutes else None,
            "longest_minutes": round(max(minutes), 1) if minutes else None,
        }

    def player_doubles_by_number(self, player: str) -> list:
        """Attempts/hits per double target (D1-D20 + bullseye-as-25), inferred from
        the remaining score before each dart — same approximation the
        checkout % uses, just broken out per number instead of summed. Not a recorded "intended target", just the remaining that made a
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
                f" WHERE game_mode NOT IN {_OTHER_MODES_SQL} AND points_start IS NOT NULL"
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

    def x01_overview(self) -> dict:
        """What the X01 view opens with: totals over every X01 match, and records.
        The totals count everything played; the records leave out players flagged
        `hidden`, like the leaderboards. Each record is None or a dict with the
        player and the date (`started_at`, date part only)."""
        with self._lock:
            totals = self._conn.execute("""
                SELECT COUNT(DISTINCT match_id) as matches, COALESCE(SUM(darts_count), 0) as darts
                FROM turns
            """).fetchone()
            legs = self._conn.execute("""
                SELECT COUNT(*) as n FROM legs
                WHERE winner IS NOT NULL AND match_id IN (SELECT match_id FROM turns)
            """).fetchone()["n"]
            hours = self._conn.execute("""
                SELECT COALESCE(SUM((julianday(ended_at) - julianday(started_at)) * 24), 0) as h
                FROM matches
                WHERE ended_at IS NOT NULL AND match_id IN (SELECT match_id FROM turns)
            """).fetchone()["h"]

            def one(sql, params=()):
                return self._conn.execute(sql, params).fetchone()

            visible = "COALESCE(p.hidden, 0) = 0"
            turn = one(f"""
                SELECT t.score, t.player, m.started_at FROM turns t
                JOIN matches m ON m.match_id = t.match_id
                LEFT JOIN players p ON p.name = t.player
                WHERE {visible} ORDER BY t.score DESC, m.started_at LIMIT 1
            """)
            checkout = one(f"""
                SELECT t.score, t.player, t.dart1, t.dart2, t.dart3, m.started_at FROM turns t
                JOIN matches m ON m.match_id = t.match_id
                LEFT JOIN players p ON p.name = t.player
                WHERE t.is_checkout = 1 AND {visible} ORDER BY t.score DESC, m.started_at LIMIT 1
            """)
            # Legs are only comparable within one starting score: take the most played one.
            common = one("""
                SELECT m.points_start as points_start FROM legs l
                JOIN matches m ON m.match_id = l.match_id
                WHERE l.winner IS NOT NULL AND m.points_start IS NOT NULL
                GROUP BY m.points_start ORDER BY COUNT(*) DESC, m.points_start DESC LIMIT 1
            """)
            leg = one(f"""
                SELECT t.player, SUM(t.darts_count) as darts, m.points_start, m.started_at
                FROM turns t
                JOIN legs l ON l.match_id = t.match_id AND l.leg = t.leg AND l.winner = t.player
                JOIN matches m ON m.match_id = t.match_id
                LEFT JOIN players p ON p.name = t.player
                WHERE m.points_start = ? AND {visible}
                GROUP BY t.match_id, t.leg, t.player ORDER BY darts, m.started_at LIMIT 1
            """, (common["points_start"],)) if common else None
            # A match average needs a few turns behind it to mean anything.
            average = one(f"""
                SELECT t.player, SUM(t.score) * 3.0 / SUM(t.darts_count) as avg3,
                       m.points_start, m.started_at
                FROM turns t
                JOIN matches m ON m.match_id = t.match_id
                LEFT JOIN players p ON p.name = t.player
                WHERE {visible}
                GROUP BY t.match_id, t.player HAVING SUM(t.darts_count) >= 18
                ORDER BY avg3 DESC, m.started_at LIMIT 1
            """)

        def day(row):
            return row["started_at"][:10]

        return {
            "summary": {
                "matches": totals["matches"], "legs": legs, "darts": totals["darts"],
                "playtime_hours": round(hours, 2),
            },
            "records": {
                "highest_turn": {"score": turn["score"], "player": turn["player"], "date": day(turn)} if turn else None,
                "highest_checkout": {
                    "score": checkout["score"], "player": checkout["player"], "date": day(checkout),
                    "targets": [d for d in (checkout["dart1"], checkout["dart2"], checkout["dart3"]) if d],
                } if checkout else None,
                "best_leg": {
                    "darts": leg["darts"], "player": leg["player"], "date": day(leg),
                    "points_start": leg["points_start"],
                } if leg else None,
                "best_average": {
                    "avg3": round(average["avg3"], 1), "player": average["player"], "date": day(average),
                    "points_start": average["points_start"],
                } if average else None,
            },
        }

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
            "score_histogram": self.player_score_histogram(player),
            "avg_by_match": self.player_avg_by_match(player),
            "dart_hits": self.player_dart_hits(player),
            "dart_positions": self.player_dart_positions(player, mode if mode in ("x01", "elimination") else "x01"),
            "bust_by_remaining": self.player_bust_by_remaining(player),
            "checkout_by_match": self.player_checkout_by_match(player),
            "win_loss": self.player_win_loss(player, mode),
            "elimination_records": self.elimination_records(player),
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


def _is_double_rem(rem) -> bool:
    """True when a dart thrown at this remaining score can finish a double-out leg:
    an even score up to 40, or 50 (the bull)."""
    return rem is not None and (rem == 50 or (0 < rem <= 40 and rem % 2 == 0))


def _checkout_exprs(p: str = "") -> tuple:
    """SQL expressions for checkout darts and checkout hits of a `turns` row, `p` being
    a table alias prefix such as "t.". Like Autodarts, a checkout is counted per dart
    thrown at a score a double can finish, not per turn that started in checkout range.
    The remaining before each dart is remaining_before, dart1_rem and dart2_rem; a hit
    is the finishing dart of a turn that checked out."""
    def d(col):
        c = f"{p}{col}"
        return f"({c} = 50 OR ({c} > 0 AND {c} <= 40 AND {c} % 2 = 0))"
    attempts = (
        f"(CASE WHEN {p}darts_count >= 1 AND {d('remaining_before')} THEN 1 ELSE 0 END"
        f" + CASE WHEN {p}darts_count >= 2 AND {d('dart1_rem')} THEN 1 ELSE 0 END"
        f" + CASE WHEN {p}darts_count >= 3 AND {d('dart2_rem')} THEN 1 ELSE 0 END)"
    )
    hits = (
        f"(CASE WHEN {p}is_checkout = 1 AND ("
        f"({p}darts_count = 1 AND {d('remaining_before')})"
        f" OR ({p}darts_count = 2 AND {d('dart1_rem')})"
        f" OR ({p}darts_count = 3 AND {d('dart2_rem')})"
        f") THEN 1 ELSE 0 END)"
    )
    return attempts, hits


def _checkout_columns(p: str = "") -> str:
    """SELECT columns co_attempts and co_hits."""
    attempts, hits = _checkout_exprs(p)
    return f"SUM({attempts}) as co_attempts, SUM({hits}) as co_hits"


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
    return {
        **_row_stats(r),
        "sessions":    r["sessions"] or 0 if "sessions" in r.keys() else None,
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
                "positions": [_position(game)],
            }

        elif ev == "dart2-thrown":
            if self._buf and self._buf["player"] == player:
                dv   = int(game.get("dartValue") or 0)
                field = (game.get("fieldName") or "").upper()
                prev_rem = self._buf["darts"][-1][2]
                self._buf["darts"].append((field, dv, prev_rem - dv))
                self._buf["positions"].append(_position(game))

        elif ev == "dart3-thrown":
            if self._buf and self._buf["player"] == player:
                dv   = int(game.get("dartValue") or 0)
                field = (game.get("fieldName") or "").upper()
                prev_rem = self._buf["darts"][-1][2]
                self._buf["darts"].append((field, dv, prev_rem - dv))
                self._buf["positions"].append(_position(game))

        elif ev == "busted" and self._is_x01():
            self._on_bust(player, game)

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
            # co_pct at 0% regardless of how much is played.
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

    def _on_bust(self, player, game):
        """Marks the turn as a bust and stores the dart that busted. That dart has
        no dart{n}-thrown event; the busted event carries it. A bust on the first
        dart starts the turn, since no buffer exists yet. The same event can
        arrive more than once, a dart already stored is not added again."""
        if self._buf and player and self._buf["player"] != player:
            self._flush_turn()
        field = (game.get("fieldName") or game.get("field_name") or "").upper()
        try:
            number = int(game.get("dartNumber"))
            value = int(game.get("dartValue"))
        except (TypeError, ValueError):
            number = value = None          # an older recording: only the bust flag is known
        if self._buf is None and number == 1 and player:
            try:
                before = int(game.get("pointsBeforeTurn"))
            except (TypeError, ValueError):
                before = None
            if before is not None:
                self._buf = {"player": player, "leg": self._leg, "remaining_before": before,
                             "is_bust": True, "darts": [(field, value, before - value)],
                             "positions": [_position(game)]}
                return
        if not self._buf:
            return
        self._buf["is_bust"] = True
        darts = self._buf["darts"]
        if number == len(darts) + 1:
            darts.append((field, value, darts[-1][2] - value))
            self._buf["positions"].append(_position(game))

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
            positions=buf.get("positions"),
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
        before = buf["remaining_before"]
        for i, (_, _, after) in enumerate(darts):
            if _is_double_rem(before):
                s["co_attempts"] += 1
                if is_checkout and i == len(darts) - 1:
                    s["co_hits"] += 1
            before = after

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
