"""The sync of this installation with the circle of its friends (see relay/PROTOCOL.md, "Circle").

A background thread reports the local players, fetches the mappings of the admin, sends the records of finished
matches (an outbox with retry) and pulls the records meant for this site, which it imports (match_record.py). It runs
when it starts, every few minutes and after a match of its own ended or was deleted. The state (switch, cursor, outbox,
what was sent, last times and error) lives in `circle.json` next to `config.toml`.
"""

import json
import logging
import os
import threading
import time
from pathlib import Path

from breakfast import match_record
from breakfast.locations import LocationError

log = logging.getLogger(__name__)

INTERVAL_S = 300
FIRST_DELAY_S = 20
PAGE = 100
MAX_TRIES = 20
PERMANENT = {400, 403, 404, 409, 413, 422}     # the relay will not take this record, a retry does not help


class CircleSync:
    def __init__(self, db, locations, config_path, version, now=time.time, on_change=None):
        self._db, self._locations, self._version, self._now = db, locations, version, now
        self._on_change = on_change
        self.path = Path(config_path).parent / "circle.json"
        self._state_lock = threading.RLock()
        self._run_lock = threading.Lock()
        self._wake = threading.Event()
        self._stop = threading.Event()
        self._thread = None
        self._running = False
        self._approved = None

    # ── the file ──────────────────────────────────────────────────────────────

    def _load(self):
        try:
            state = json.loads(self.path.read_text())
        except (OSError, ValueError):
            state = {}
        state.setdefault("enabled", True)
        state.setdefault("cursor", 0)
        state.setdefault("outbox", {})
        state.setdefault("sent", {})
        return state

    def _save(self, state):
        tmp = self.path.with_suffix(".tmp")
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w") as f:
            json.dump(state, f)
        os.replace(tmp, self.path)

    def _update(self, **changes):
        with self._state_lock:
            state = self._load()
            state.update(changes)
            self._save(state)
            return state

    # ── what the app tells ────────────────────────────────────────────────────

    def status(self):
        state = self._load()
        registered = self._locations.status()["registered"]
        return {"enabled": state["enabled"], "registered": registered, "approved": self._approved if registered else None,
                "running": self._running, "pending": len(state["outbox"]),
                "last_push": state.get("last_push"), "last_pull": state.get("last_pull"), "last_sync": state.get("last_sync"),
                "pushed": state.get("pushed", 0), "pulled": state.get("pulled", 0), "error": state.get("error")}

    def set_enabled(self, enabled):
        self._update(enabled=bool(enabled))
        if enabled:
            self._wake.set()
        self._changed()

    def match_closed(self, match_id):
        """A match was finished (or closed again): it goes to the outbox, whatever the mode; the send decides."""
        self._queue(match_id, "push")

    def match_deleted(self, match_id):
        """A match was deleted: a deletion record follows when it was sent before."""
        with self._state_lock:
            state = self._load()
            if match_id in state["sent"]:
                state["outbox"][match_id] = {"op": "delete", "tries": 0}
            else:
                state["outbox"].pop(match_id, None)
            self._save(state)
        self._wake.set()

    def _queue(self, match_id, op):
        with self._state_lock:
            state = self._load()
            if not state["enabled"] or not self._locations.status()["registered"]:
                return
            state["outbox"][match_id] = {"op": op, "tries": 0}
            self._save(state)
        self._wake.set()

    def _changed(self):
        if self._on_change:
            try:
                self._on_change()
            except Exception:
                log.debug("CircleSync: on_change failed", exc_info=True)

    # ── the thread ────────────────────────────────────────────────────────────

    def start(self):
        if self._thread:
            return
        self._thread = threading.Thread(target=self._loop, name="circle-sync", daemon=True)
        self._thread.start()

    def stop(self):
        self._stop.set()
        self._wake.set()

    def _loop(self):
        self._stop.wait(FIRST_DELAY_S)
        while not self._stop.is_set():
            self.run_once()
            self._wake.wait(INTERVAL_S)
            self._wake.clear()
            self._stop.wait(2)                  # a match that just ended is stored before it is read

    def run_once(self):
        """One round: report, fetch the mappings, send the outbox, pull. Returns the status."""
        if not self._run_lock.acquire(blocking=False):
            return self.status()
        self._running = True
        self._changed()
        try:
            state = self._load()
            if state["enabled"] and self._locations.status()["registered"]:
                self._round()
        except LocationError as e:
            self._fail(e)
        except Exception as e:                  # a failing sync never reaches the games
            log.exception("CircleSync: the round failed")
            self._fail(e)
        finally:
            self._running = False
            self._run_lock.release()
            self._changed()
        return self.status()

    def _fail(self, error):
        log.warning("CircleSync: %s", error)
        self._update(error=str(error), error_at=self._now())

    # ── a round ───────────────────────────────────────────────────────────────

    def _round(self):
        origin = self._locations.status()
        reply = self._locations.call("PUT", "/circle/state", {
            "version": self._version, "players": self._db.list_players(),
            "state": {"outbox": len(self._load()["outbox"])}})
        self._approved = bool(reply.get("approved"))
        if not self._approved:
            self._update(error="waiting for the admin to approve this site", error_at=self._now())
            return
        config = self._locations.call("GET", "/circle/config")
        self._update(error=None)
        self._push(origin, config)
        self._pull(origin, config)
        self._update(last_sync=self._now())

    def _push(self, origin, config):
        origin_record = {"id": origin["id"], "name": origin["name"]}
        for match_id, entry in list(self._load()["outbox"].items()):
            try:
                body = self._outgoing(match_id, entry["op"], origin_record)
                if body is not None:
                    self._locations.call("PUT", f"/circle/records/{match_id}/{body['record']['revision']}", body)
                    self._sent(match_id, entry["op"], body)
            except match_record.RecordError as e:
                log.debug("CircleSync: match %s is not sent: %s", match_id, e)
            except LocationError as e:
                if e.status in PERMANENT:
                    log.info("CircleSync: match %s is not taken: %s", match_id, e)
                else:
                    self._retry(match_id, e)
                    raise
            self._forget(match_id)

    def _outgoing(self, match_id, op, origin):
        """The body of the PUT for an entry of the outbox, None when there is nothing to send."""
        state = self._load()
        if op == "delete":
            sent = state["sent"].get(match_id)
            if not sent:
                return None
            record = match_record.deletion_record(match_id, sent["game_mode"], origin, sent["revision"] + 1)
            return {"game_mode": sent["game_mode"], "deleted": True, "record": record, "participants": sent.get("participants", [])}
        record = match_record.export_record(self._db, match_id, origin)
        return {"game_mode": record["game_mode"], "deleted": False, "record": record,
                "participants": self._participants(record["match"].get("players") or [])}

    def _participants(self, players):
        """The players of a match as the relay wants them: a local player by name, a guest of another site with that
        site's name as `origin`."""
        with self._db.transaction() as c:
            guests = {r[0] for r in c.execute("SELECT name FROM players WHERE guest = 1")}
        out = []
        for name in players:
            if name in guests and "@" in name:
                local, _, site = name.rpartition("@")
                out.append({"name": local, "origin": site})
            else:
                out.append({"name": name})
        return out

    def _sent(self, match_id, op, body):
        with self._state_lock:
            state = self._load()
            if op == "delete":
                state["sent"].pop(match_id, None)
            else:
                state["sent"][match_id] = {"revision": body["record"]["revision"], "game_mode": body["game_mode"],
                                           "participants": body["participants"]}
            state["pushed"] = state.get("pushed", 0) + 1
            state["last_push"] = self._now()
            self._save(state)

    def _forget(self, match_id):
        with self._state_lock:
            state = self._load()
            state["outbox"].pop(match_id, None)
            self._save(state)

    def _retry(self, match_id, error):
        with self._state_lock:
            state = self._load()
            entry = state["outbox"].get(match_id)
            if entry is not None:
                entry["tries"] += 1
                if entry["tries"] >= MAX_TRIES:
                    state["outbox"].pop(match_id)
                    log.warning("CircleSync: match %s given up after %s tries: %s", match_id, MAX_TRIES, error)
                self._save(state)

    def _pull(self, origin, config):
        cursor = self._load()["cursor"]
        while True:
            page = self._locations.call("GET", f"/circle/records?since={cursor}&limit={PAGE}")
            for entry in page["records"]:
                self._import(entry, config, origin)
                cursor = entry["seq"]
                self._update(cursor=cursor)
            if len(page["records"]) < PAGE:
                break
        self._update(cursor=max(cursor, page.get("next", cursor)), last_pull=self._now())

    def _import(self, entry, config, origin):
        try:
            record = self._locations.call("GET", f"/circle/records/{entry['match_id']}")["record"]
            result = match_record.import_record(self._db, record, self._mapping(record, entry["origin"]["id"], config))
        except (match_record.RecordError, KeyError) as e:
            log.warning("CircleSync: record %s cannot be imported: %s", entry.get("match_id"), e)
            return
        except LocationError as e:
            if e.status in PERMANENT:
                log.warning("CircleSync: record %s cannot be fetched: %s", entry.get("match_id"), e)
                return
            raise
        if result["status"] in ("imported", "replaced", "deleted"):
            self._update(pulled=self._load().get("pulled", 0) + 1)
            log.info("CircleSync: match %s %s", result["match_id"], result["status"])

    @staticmethod
    def _mapping(record, origin_id, config):
        """{name in the record: local player} for the players of the record that are players of the circle: a plain name
        is a player of the origin site, `name@site` a guest of that site; the circle player behind it is the local
        player of this site when the admin mapped one."""
        circle = {(m["location_id"], m["local_name"]): m["player_id"] for m in config.get("site_mappings", [])}
        sites = {m["location_name"].lower(): m["location_id"] for m in config.get("site_mappings", [])}
        local = {m["player_id"]: m["local_name"] for m in config.get("mappings", [])}
        names = list((record.get("match") or {}).get("players") or [])
        if (record.get("match") or {}).get("winner"):
            names.append(record["match"]["winner"])
        mapping = {}
        for name in names:
            if "@" in name:
                player, _, site = name.rpartition("@")
                where = sites.get(site.lower())
            else:
                player, where = name, origin_id
            player_id = circle.get((where, player))
            if player_id in local:
                mapping[name] = local[player_id]
        return mapping
