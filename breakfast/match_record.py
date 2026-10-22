"""The record of a finished match: a self-contained document that can be stored again on another installation.

`export_record()` turns a finished X01 or Elimination match into a JSON document (a dict), `import_record()` stores
such a document as a match of this installation. The content has a format of its own per game mode, independent of
the database tables, so a record stays readable when the tables change. Nothing here compresses, encrypts or sends:
that is the job of whatever carries the record (see docu/SHARING-CONCEPT.md).

    {"record_version": 1, "game_mode": "X01", "match_id": "...", "origin": {"id": "...", "name": "..."},
     "revision": 2, "deleted": false, "match": {...}, "x01": {...}}        (Elimination: "elimination")

* `origin` is the location the match was played at, `revision` rises with every close of the match: a record
  replaces an imported match of a lower revision and is skipped for the same or a higher one.
* The players of an imported match are guests `name@origin` (StatsDB.guest_name) unless `import_record()` is given a
  mapping to local players; a mapped player has the match in his statistics.
* An imported match is never exported again. A record with `deleted` set (see `deletion_record()`) deletes an
  imported match. Imported matches do not go through the achievement engine.
"""

import json
from datetime import datetime, timezone

RECORD_VERSION = 1
MODES = ("X01", "Elimination")


class RecordError(ValueError):
    """A match cannot be exported, or a record cannot be imported: the text says why."""


# ── export ────────────────────────────────────────────────────────────────────

def export_record(db, match_id: str, origin: dict) -> dict:
    """The record of a finished match played here. `origin` is {"id": ..., "name": ...}, this installation as a location.
    RecordError for an unknown or unfinished match, for one that was imported, and for a game mode without a record."""
    if not isinstance(origin, dict) or not origin.get("id"):
        raise RecordError("the origin needs an id")
    with db.transaction() as c:
        match = c.execute("SELECT * FROM matches WHERE match_id = ?", (match_id,)).fetchone()
        if match is None:
            raise RecordError("unknown match")
        if match["origin_id"]:
            raise RecordError("an imported match is not exported again")
        if match["ended_at"] is None:
            raise RecordError("the match is not finished")
        if match["game_mode"] not in MODES:
            raise RecordError(f"no record for {match['game_mode']}")
        mode = match["game_mode"]
        record = {
            "record_version": RECORD_VERSION, "game_mode": mode, "match_id": match_id,
            "origin": {"id": origin["id"], "name": origin.get("name")},
            "revision": max(1, match["revision"]), "deleted": False,
            "match": {"started_at": match["started_at"], "ended_at": match["ended_at"], "winner": match["winner"],
                      "players": json.loads(match["players"] or "[]"), "has_bot": bool(match["has_bot"])},
        }
        if mode == "X01":
            record["x01"] = _export_x01(c, match)
        else:
            record["elimination"] = _export_elimination(c, match)
    return record


def deletion_record(match_id: str, game_mode: str, origin: dict, revision: int) -> dict:
    """The record that takes a match away again at the places that imported it."""
    return {"record_version": RECORD_VERSION, "game_mode": game_mode, "match_id": match_id,
            "origin": {"id": origin["id"], "name": origin.get("name")}, "revision": revision, "deleted": True}


def _positions(c, match_id, mode):
    """The stored dart positions of a match: {(player, leg, turn): {dart number: position}}."""
    found = {}
    for r in c.execute("SELECT player, leg, turn, dart_number, field, x, y, entry, corrected, misread"
                       " FROM dart_positions WHERE match_id = ? AND game_mode = ? ORDER BY id", (match_id, mode)):
        found.setdefault((r["player"], r["leg"], r["turn"]), {})[r["dart_number"]] = {
            "field": r["field"], "x": r["x"], "y": r["y"], "entry": r["entry"],
            "corrected": r["corrected"], "misread": r["misread"]}
    return found


def _export_x01(c, match):
    positions = _positions(c, match["match_id"], "X01")
    legs = [{"leg": r["leg"], "winner": r["winner"], "decided": r["decided"]}
            for r in c.execute("SELECT leg, winner, decided FROM legs WHERE match_id = ? ORDER BY id", (match["match_id"],))]
    turns = []
    for table, bot in (("turns", False), ("bot_turns", True)):
        for r in c.execute(f"SELECT * FROM {table} WHERE match_id = ? ORDER BY id", (match["match_id"],)):
            bot_positions = json.loads(r["positions"] or "[]") if bot else []
            darts = []
            for i in (1, 2, 3):
                if r[f"dart{i}"] is None:
                    continue
                dart = {"field": r[f"dart{i}"], "value": r[f"dart{i}_val"], "remaining": r[f"dart{i}_rem"]}
                if bot:
                    spot = bot_positions[i - 1] if i - 1 < len(bot_positions) else None
                    if spot:
                        dart.update(x=spot["x"], y=spot["y"])
                else:
                    spot = positions.get((r["player"], r["leg"], r["turn"]), {}).get(i)
                    if spot:
                        dart.update(spot)
                darts.append(dart)
            turns.append({"player": r["player"], "bot": bot, "leg": r["leg"], "turn": r["turn"],
                          "remaining_before": r["remaining_before"], "score": r["score"], "bust": bool(r["is_bust"]),
                          "checkout": bool(r["is_checkout"]), "at": r["created_at"], "darts": darts})
    turns.sort(key=lambda t: t["at"] or "")           # stable: the order of a table is kept
    return {"start": match["points_start"], "legs": legs, "turns": turns}


def _export_elimination(c, match):
    positions = _positions(c, match["match_id"], "Elimination")
    counts = {}
    turns = []
    for r in c.execute("SELECT * FROM elimination_turns WHERE match_id = ? ORDER BY id", (match["match_id"],)):
        counts[r["player"]] = n = counts.get(r["player"], 0) + 1
        turn = {"player": r["player"], "darts_count": r["darts_count"], "score": r["score"], "target": r["target"],
                "freipass": None if r["freipass"] is None else bool(r["freipass"]),
                "passed": None if r["passed"] is None else bool(r["passed"]),
                "lives_before": r["lives_before"], "at": r["created_at"], "darts": []}
        for number, spot in sorted(positions.get((r["player"], 1, n), {}).items()):
            turn["darts"].append({"dart": number, **spot})
        turns.append(turn)
    results = [{"player": r["player"], "placement": r["placement"], "lives_left": r["lives_left"]}
               for r in c.execute("SELECT player, placement, lives_left FROM elimination_results WHERE match_id = ?"
                                  " ORDER BY placement, id", (match["match_id"],))]
    return {"lives": match["points_start"], "turns": turns, "results": results}


# ── import ────────────────────────────────────────────────────────────────────

def import_record(db, record: dict, mapping: dict | None = None) -> dict:
    """Store a record as a match of this installation. `mapping` maps names in the record to local players; the other
    players become guests. Returns {"status", "match_id", "revision"} with the status
    `imported`, `replaced` (an older revision was there), `skipped` (the same or a newer revision is there),
    `deleted` (a deletion record took the match away) or `ignored` (a deletion record for a match that is not
    imported here, or a record of a match played here). RecordError for a record that cannot be read."""
    mode, match_id, revision, deleted = _check(record)
    origin = record["origin"]
    with db.transaction() as c:
        existing = c.execute("SELECT origin_id, revision FROM matches WHERE match_id = ?", (match_id,)).fetchone()
        result = {"match_id": match_id, "revision": revision}
        if existing is not None and not existing["origin_id"]:
            return {**result, "status": "ignored"}              # a match played here is never touched
        if deleted:
            if existing is None or existing["revision"] > revision:
                return {**result, "status": "ignored"}
            db.delete_match_rows(match_id)
            return {**result, "status": "deleted"}
        if existing is not None and existing["revision"] >= revision:
            return {**result, "status": "skipped"}
        if existing is not None:
            db.delete_match_rows(match_id)
        label = origin.get("name") or origin["id"]
        names = _Names(db, c, label, mapping or {})
        c.execute("INSERT INTO matches (match_id, started_at, ended_at, game_mode, points_start, players, winner, has_bot,"
                  " revision, origin_id, origin_name) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                  (match_id, record["match"]["started_at"], record["match"]["ended_at"], mode,
                   record[mode.lower()].get("start", record[mode.lower()].get("lives")),
                   json.dumps(list(dict.fromkeys(names(p) for p in record["match"].get("players") or []))),
                   names(record["match"].get("winner")), int(bool(record["match"].get("has_bot"))),
                   revision, origin["id"], origin.get("name")))
        if mode == "X01":
            _import_x01(c, match_id, record["x01"], names)
        else:
            _import_elimination(c, match_id, record["elimination"], names)
        return {**result, "status": "replaced" if existing is not None else "imported"}


def _check(record):
    """(game mode, match id, revision, deleted) of a record that can be read, else RecordError."""
    if not isinstance(record, dict):
        raise RecordError("a record is a JSON object")
    version = record.get("record_version")
    if not isinstance(version, int):
        raise RecordError("no record version")
    if version > RECORD_VERSION:
        raise RecordError("this record needs a newer version of the app")
    mode = record.get("game_mode")
    if mode not in MODES:
        raise RecordError(f"no record for {mode}")
    match_id, revision = record.get("match_id"), record.get("revision")
    origin = record.get("origin")
    if not (isinstance(match_id, str) and match_id and isinstance(revision, int) and not isinstance(revision, bool)):
        raise RecordError("a record needs a match id and a revision")
    if not (isinstance(origin, dict) and isinstance(origin.get("id"), str) and origin["id"]):
        raise RecordError("a record needs an origin with an id")
    deleted = bool(record.get("deleted"))
    if not deleted and not (isinstance(record.get("match"), dict) and isinstance(record.get(mode.lower()), dict)):
        raise RecordError("the record has no content")
    return mode, match_id, revision, deleted


class _Names:
    """The name a player of the record is stored under here: the mapped local player, else a guest of the origin."""

    def __init__(self, db, conn, label, mapping):
        self._db, self._conn, self._label, self._mapping = db, conn, label, mapping
        self._cache = {}

    def __call__(self, name, bot=False):
        if name is None or bot:
            return name
        if name not in self._cache:
            if name in self._mapping:
                local = self._mapping[name]
                self._conn.execute("INSERT OR IGNORE INTO players (name, created_at) VALUES (?, ?)",
                                   (local, datetime.now(timezone.utc).isoformat()))
                self._cache[name] = local
            else:
                self._cache[name] = self._db.guest_name_in(self._conn, name, self._label)
        return self._cache[name]


def _insert_positions(c, match_id, mode, player, leg, turn, darts):
    for number, dart in darts:
        if dart.get("x") is None or dart.get("y") is None:
            continue
        c.execute("INSERT INTO dart_positions (match_id, game_mode, player, leg, turn, dart_number, field, x, y, entry,"
                  " corrected, misread) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                  (match_id, mode, player, leg, turn, number, dart.get("field"), dart["x"], dart["y"], dart.get("entry"),
                   int(dart.get("corrected") or 0), int(dart.get("misread") or 0)))


def _import_x01(c, match_id, content, names):
    for leg in content.get("legs") or []:
        c.execute("INSERT INTO legs (match_id, leg, winner, decided) VALUES (?,?,?,?)",
                  (match_id, leg["leg"], names(leg.get("winner")), leg.get("decided")))
    for t in content.get("turns") or []:
        bot = bool(t.get("bot"))
        player = names(t["player"], bot=bot)
        darts = (t.get("darts") or [])[:3]
        cells = []
        for i in range(3):
            d = darts[i] if i < len(darts) else {}
            cells += [d.get("field"), d.get("value"), d.get("remaining")]
        columns = ("match_id, player, leg, turn, remaining_before, score, is_bust, is_checkout, darts_count,"
                   " dart1, dart1_val, dart1_rem, dart2, dart2_val, dart2_rem, dart3, dart3_val, dart3_rem")
        values = [match_id, player, t["leg"], t["turn"], t["remaining_before"], t["score"], int(bool(t.get("bust"))),
                  int(bool(t.get("checkout"))), len(darts)] + cells
        if bot:
            spots = [{"x": d["x"], "y": d["y"]} if d.get("x") is not None and d.get("y") is not None else None
                     for d in darts]
            c.execute(f"INSERT INTO bot_turns ({columns}, positions, created_at) VALUES ({','.join('?' * 20)})",
                      values + [json.dumps(spots), t.get("at")])
        else:
            c.execute(f"INSERT INTO turns ({columns}, created_at) VALUES ({','.join('?' * 19)})", values + [t.get("at")])
            _insert_positions(c, match_id, "X01", player, t["leg"], t["turn"], list(enumerate(darts, start=1)))


def _import_elimination(c, match_id, content, names):
    counts = {}
    for t in content.get("turns") or []:
        player = names(t["player"])
        counts[player] = n = counts.get(player, 0) + 1
        c.execute("INSERT INTO elimination_turns (match_id, player, darts_count, score, target, freipass, passed,"
                  " lives_before, created_at) VALUES (?,?,?,?,?,?,?,?,?)",
                  (match_id, player, t["darts_count"], t.get("score"), t.get("target"),
                   None if t.get("freipass") is None else int(t["freipass"]),
                   None if t.get("passed") is None else int(t["passed"]), t.get("lives_before"), t.get("at")))
        _insert_positions(c, match_id, "Elimination", player, 1, n, [(d["dart"], d) for d in t.get("darts") or []])
    for r in content.get("results") or []:
        c.execute("INSERT INTO elimination_results (match_id, player, placement, lives_left) VALUES (?,?,?,?)",
                  (match_id, names(r["player"]), r["placement"], r.get("lives_left")))
