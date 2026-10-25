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
from breakfast import voicepack_editor as ve
from breakfast import voicepack_overlay as vo
from breakfast.locations import LocationError

log = logging.getLogger(__name__)

INTERVAL_S = 300
FIRST_DELAY_S = 20
PAGE = 100
MAX_TRIES = 20
PUSH_ROUND = 200          # records sent in one round, a larger outbox goes on in the next one
PULL_ROUND = 300          # records fetched in one round
FAST_S = 10               # the wait before the next round while there is more to do
PAUSE_S = 3600            # the wait after the relay said "too many" (rate limit, records of the day)
PERMANENT = {400, 403, 404, 409, 413, 422}     # the relay will not take this record, a retry does not help


class CircleSync:
    def __init__(self, db, locations, config_path, version, now=time.time, on_change=None, voice_packs=None, on_voice=None):
        """*voice_packs*: returns the names of the voice packs this installation has a plan for. *on_voice*: called with
        (pack, player) after the voice entry of a player was changed here, so that the voice files can follow."""
        self._db, self._locations, self._version, self._now = db, locations, version, now
        self._on_change = on_change
        self._voice_packs = voice_packs or (lambda: [])
        self._on_voice = on_voice
        self.path = Path(config_path).parent / "circle.json"
        self._state_lock = threading.RLock()
        self._run_lock = threading.Lock()
        self._wake = threading.Event()
        self._stop = threading.Event()
        self._thread = None
        self._running = False
        self._approved = None
        self._more = False                      # the last round left work that can go on at once

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
        state.setdefault("foreign", {})
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
                "paused_until": max([u for u in (state.get("push_until"), state.get("pull_until")) if u and u > self._now()], default=None),
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
            state["foreign"].pop(match_id, None)
            if match_id in state["sent"]:
                state["outbox"][match_id] = {"op": "delete", "tries": 0}
            else:
                state["outbox"].pop(match_id, None)
            self._save(state)
        self._wake.set()

    def send_all(self):
        """Queue every finished match played here that the circle does not have yet (or has in an older revision): the catch-up
        for the history, for matches whose players were mapped later and for a changed rule. Returns how many were queued."""
        with self._db.transaction() as c:
            rows = c.execute("SELECT match_id, revision FROM matches WHERE ended_at IS NOT NULL AND origin_id IS NULL"
                             " AND game_mode IN (?, ?) ORDER BY ended_at", match_record.MODES).fetchall()
        with self._state_lock:
            state = self._load()
            if not state["enabled"] or not self._locations.status()["registered"]:
                return 0
            queued = 0
            for match_id, revision in rows:
                sent = state["sent"].get(match_id)
                if match_id in state["outbox"] or match_id in state["foreign"] or (sent and sent["revision"] >= revision):
                    continue
                state["outbox"][match_id] = {"op": "push", "tries": 0}
                queued += 1
            self._save(state)
        if queued:
            self._wake.set()
        return queued

    def _queue(self, match_id, op):
        with self._state_lock:
            state = self._load()
            if not state["enabled"] or not self._locations.status()["registered"]:
                return
            if op == "push" and match_id in state["foreign"]:
                return                  # the relay holds it from the other site that played it
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
            self._wake.wait(FAST_S if self._more else INTERVAL_S)
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
        refetch = config.get("refetch", 0)
        if refetch != self._load().get("refetch_seen", 0):
            log.info("CircleSync: the admin asked to fetch everything again")
            self._update(cursor=0, refetch_seen=refetch, pull_until=None)
        self._more = False
        self._backfill_achievements()
        self._sync_profiles(config)
        self._adopt_guests(config)
        self._push(origin, config)
        self._pull(origin, config)
        self._update(last_sync=self._now())

    def _adopt_guests(self, config):
        """A guest of another site (`ben@site`, stored by an online match) that the admin mapped to a local player is
        that player: everything stored under the guest name moves to him, as a merge in the Players tab does it. Not
        while a match runs, its game still holds the guest name."""
        guests = self._db.guest_names()
        if not guests or self._db.running_matches():
            return
        engine = getattr(self._db, "achievement_engine", None)
        for guest, local in self._mapping({"match": {"players": guests}}, None, config).items():
            matches = self._db.finished_matches_of(guest)
            result = self._db.merge_players(guest, local)
            if "error" in result:
                log.info("CircleSync: the guest %s stays a guest of its own: %s", guest, result["error"])
                continue
            log.info("CircleSync: the guest %s is %s here: %s matches", guest, local, result["matches"])
            for match_id in matches:            # as a guest he earned nothing: the matches count for him now, silently
                try:
                    engine and engine.evaluate_imported(match_id)
                except Exception:
                    log.exception("CircleSync: the achievements of match %s could not be evaluated", match_id)

    def _backfill_achievements(self):
        """Once per installation: the achievements of the matches that were imported before they counted whatever their start."""
        engine = getattr(self._db, "achievement_engine", None)
        if not engine:
            return
        try:
            done = engine.backfill_imported()
            if done:
                log.info("CircleSync: the achievements of %s imported matches were evaluated", done)
        except Exception:
            log.exception("CircleSync: the achievements of the imported matches could not be evaluated")

    # ── the profiles of the circle players (color, voice entries) ─────────────

    def _local_profiles(self, mappings, packs):
        """{(circle player, field): (local name, value)} for the players of this site the admin mapped: `color` is #rrggbb or
        None, `voice:<pack>` the private entry of the player in that pack ({"variants": [...]}) or None."""
        colors = self._db.player_colors()
        entries = {}
        for pack in packs:
            try:
                entries[pack] = vo.read_entries(vo.overlay_path(self.path.parent, pack))
            except ValueError as e:
                log.warning("CircleSync: the private voice file of %s is not read: %s", pack, e)
        local = {}
        for m in mappings:
            name, player = m["local_name"], m["player_id"]
            local[(player, "color")] = (name, colors.get(name))
            for pack, found in entries.items():
                entry = found.get(name)
                variants = entry.get("variants") if entry else None
                local[(player, f"voice:{pack}")] = (name, {"variants": list(variants)} if variants else None)
        return local

    def _sync_profiles(self, config):
        """Make the color and the voice entries of the mapped players the same on every site; the latest change wins. What
        changed here since the last round (against `profile_base`, what both sides had then) is sent, what changed at the
        relay and not here is taken over. A failure here never stops the sync of the matches."""
        try:
            packs = list(self._voice_packs())
            local = self._local_profiles(config.get("mappings", []), packs)
            remote = {(f["player_id"], f["field"]): f.get("value") for f in config.get("profiles", [])}
            base = dict(self._load().get("profile_base", {}))
            outgoing, sent = {}, {}
            for (player, field), (name, value) in local.items():
                key = f"{player}|{field}"
                if value != base.get(key):                      # changed here: send it
                    outgoing.setdefault(name, {})[field] = value
                    sent[key] = value
                elif remote.get((player, field)) != base.get(key) and self._take(name, field, remote.get((player, field)), packs):
                    base[key] = remote.get((player, field))     # changed at the relay: take it over
            if outgoing:
                self._locations.call("PUT", "/circle/profile", {"players": self._profile_body(outgoing)})
                base.update(sent)
            self._update(profile_base=base)
        except LocationError as e:
            if e.status == 404:                                 # a relay without profiles
                log.debug("CircleSync: the relay has no profiles: %s", e)
            else:
                log.warning("CircleSync: the profiles are not synced: %s", e)
        except Exception:
            log.exception("CircleSync: the profiles are not synced")

    @staticmethod
    def _profile_body(outgoing):
        players = []
        for name, fields in outgoing.items():
            entry = {"name": name}
            for field, value in fields.items():
                if field == "color":
                    entry["color"] = value
                else:
                    entry.setdefault("voice", {})[field.split(":", 1)[1]] = value
            players.append(entry)
        return players

    def _take(self, name, field, value, packs):
        """Apply a value from the relay to the local player. Returns False when it could not be applied here (a pack this
        installation has no plan for, a value that is not valid), so that the round does not count it as taken."""
        if field == "color":
            try:
                self._db.set_player_color(name, value)
            except ValueError:
                return False
            return True
        pack = field.split(":", 1)[1]
        if pack not in packs:
            return False
        path = vo.overlay_path(self.path.parent, pack)
        try:
            entries = vo.read_entries(path)
            if value is None:
                entries.pop(name, None)
            else:
                entries[name] = {"variants": list(value["variants"])}
            ve.write_overlay(path, entries)
        except (ValueError, KeyError, TypeError, OSError) as e:
            log.warning("CircleSync: the voice entry of %s in %s is not stored: %s", name, pack, e)
            return False
        if self._on_voice:
            try:
                self._on_voice(pack, name)
            except Exception:
                log.exception("CircleSync: the voice files of %s could not follow", name)
        return True

    def _push(self, origin, config):
        state = self._load()
        if (state.get("push_until") or 0) > self._now():
            return
        origin_record = {"id": origin["id"], "name": origin["name"]}
        taken = 0
        for match_id, entry in list(state["outbox"].items()):
            if taken >= PUSH_ROUND:
                self._more = True
                return
            try:
                body = self._outgoing(match_id, entry["op"], origin_record, config)
                if body is not None:
                    taken += 1
                    self._locations.call("PUT", f"/circle/records/{match_id}/{body['record']['revision']}", body)
                    self._sent(match_id, entry["op"], body)
            except match_record.RecordError as e:
                log.debug("CircleSync: match %s is not sent: %s", match_id, e)
            except LocationError as e:
                if e.status == 429:                 # a limit of the relay: the outbox waits, nothing is lost
                    log.info("CircleSync: the relay is not taking more records for now: %s", e)
                    self._update(push_until=self._now() + PAUSE_S)
                    return
                if e.status in PERMANENT:
                    log.info("CircleSync: match %s is not taken: %s", match_id, e)
                    if e.status == 403 and "another site" in str(e):
                        self._mark_foreign(match_id)
                else:
                    self._retry(match_id, e)
                    raise
            self._forget(match_id)

    def _outgoing(self, match_id, op, origin, config):
        """The body of the PUT for an entry of the outbox, None when there is nothing to send (a match in which no player is
        a player of the circle as far as the mappings say, the relay would refuse it)."""
        state = self._load()
        if op == "delete":
            sent = state["sent"].get(match_id)
            if not sent:
                return None
            record = match_record.deletion_record(match_id, sent["game_mode"], origin, sent["revision"] + 1)
            return {"game_mode": sent["game_mode"], "deleted": True, "record": record, "participants": sent.get("participants", [])}
        record = match_record.export_record(self._db, match_id, origin)
        participants = self._participants(record["match"].get("players") or [])
        if not self._in_circle(participants, origin["id"], config):
            return None
        return {"game_mode": record["game_mode"], "deleted": False, "record": record, "participants": participants}

    @staticmethod
    def _in_circle(participants, origin_id, config):
        """Whether one of the participants is a player of the circle: a local player the admin mapped, a guest of another site
        through the mapping of that site."""
        mapped = {(m["location_id"], m["local_name"]) for m in config.get("site_mappings", [])}
        sites = {m["location_name"].lower(): m["location_id"] for m in config.get("site_mappings", [])}
        for p in participants:
            where = sites.get(p["origin"].lower()) if p.get("origin") else origin_id
            if (where, p["name"].lower()) in mapped:
                return True
        return False

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

    def _mark_foreign(self, match_id):
        """The relay holds the match from another site (both sites played it online): it counts as delivered, a later
        "send all" or a second close of the match does not queue it again."""
        with self._state_lock:
            state = self._load()
            state["foreign"][match_id] = 1
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
        state = self._load()
        if (state.get("pull_until") or 0) > self._now():
            return
        cursor, taken = state["cursor"], 0
        try:
            while True:
                page = self._locations.call("GET", f"/circle/records?since={cursor}&limit={PAGE}")
                for entry in page["records"]:
                    taken += self._import(entry, config, origin)
                    cursor = entry["seq"]
                    self._update(cursor=cursor)
                    if taken >= PULL_ROUND:
                        self._more = True
                        self._update(last_pull=self._now())
                        return
                if len(page["records"]) < PAGE:
                    break
        except LocationError as e:
            if e.status != 429:
                raise
            log.info("CircleSync: the relay is not giving more records for now: %s", e)
            self._update(pull_until=self._now() + PAUSE_S)
            return
        self._update(cursor=max(cursor, page.get("next", cursor)), last_pull=self._now())

    def _have(self, entry):
        """Whether this installation has the match in that revision (or a newer one) already: nothing to fetch."""
        with self._db.transaction() as c:
            row = c.execute("SELECT revision FROM matches WHERE match_id = ?", (entry.get("match_id"),)).fetchone()
        if entry.get("deleted"):
            return row is None
        return row is not None and isinstance(entry.get("revision"), int) and row[0] >= entry["revision"]

    def _import(self, entry, config, origin):
        """Fetch and import one record; returns 1 when the record was fetched, 0 when it was already here."""
        if self._have(entry):
            return 0
        try:
            record = self._locations.call("GET", f"/circle/records/{entry['match_id']}")["record"]
            result = match_record.import_record(self._db, record, self._mapping(record, entry["origin"]["id"], config))
        except (match_record.RecordError, KeyError) as e:
            log.warning("CircleSync: record %s cannot be imported: %s", entry.get("match_id"), e)
            return 1
        except LocationError as e:
            if e.status in PERMANENT:
                log.warning("CircleSync: record %s cannot be fetched: %s", entry.get("match_id"), e)
                return 1
            raise
        if result["status"] in ("imported", "replaced", "deleted"):
            self._update(pulled=self._load().get("pulled", 0) + 1)
            log.info("CircleSync: match %s %s", result["match_id"], result["status"])
        if result["status"] in ("imported", "replaced") and getattr(self._db, "achievement_engine", None):
            try:
                self._db.achievement_engine.evaluate_imported(result["match_id"])
            except Exception:
                log.exception("CircleSync: the achievements of match %s could not be evaluated", result["match_id"])
        return 1

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
