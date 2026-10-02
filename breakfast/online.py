"""Online Elimination: this site's side of the relay protocol (see relay/PROTOCOL.md).

An OnlineSession connects to the relay, takes part in the lobby and, once the host starts
the match, drives the local EliminationGame: the turns of remote players arrive as frames and
are replayed through the same code a local turn runs through, this site's own turns go out as
frames. The rules run here, in elimination.py; the relay only orders the turns and decides
the result.
"""

import json
import logging
import threading
import time

import requests
import websocket

log = logging.getLogger(__name__)

PROTOCOL_VERSION = 1
NAME_LENGTH = 24
MAX_LIVES = 10
REJOIN_WINDOW_S = 180
CONNECT_TIMEOUT_S = 10
PING_INTERVAL_S = 20

# Close codes of the relay (relay/PROTOCOL.md); after these there is nothing to rejoin.
_FINAL_CLOSES = {4400, 4401, 4404, 4409, 4410, 4426, 4429}


# ── frame validation, mirrored from relay/src/protocol.ts ─────────────────────────────

def _is_int(v, lo, hi):
    return isinstance(v, int) and not isinstance(v, bool) and lo <= v <= hi


def _is_name(v):
    return isinstance(v, str) and v == v.strip() and 0 < len(v) <= NAME_LENGTH


def _is_text(v, limit=200):
    return isinstance(v, str) and 0 < len(v) <= limit


def _names(v, minimum=0):
    return isinstance(v, list) and len(v) >= minimum and all(_is_name(n) for n in v) and len(set(v)) == len(v)


def _throw_error(t):
    if not isinstance(t, dict):
        return "throw must be an object"
    n = t.get("number")
    if not (_is_int(n, 0, 20) or n == 25 and isinstance(n, int)):
        return "throw.number must be 0 to 20 or 25"
    if not _is_int(t.get("multiplier"), 0, 3):
        return "throw.multiplier out of range"
    for k in ("x", "y"):
        if k in t and (not isinstance(t[k], (int, float)) or isinstance(t[k], bool)):
            return f"throw.{k} must be a number"
    for k in ("name", "entry"):
        if k in t and not isinstance(t[k], str):
            return f"throw.{k} must be a string"
    return None


def _throws_error(v):
    if not isinstance(v, list) or len(v) > 3:
        return "throws must be a list of at most 3"
    for t in v:
        e = _throw_error(t)
        if e:
            return e
    return None


def validate_client_frame(m):
    """None if `m` is a valid frame for the relay, else why not."""
    if not isinstance(m, dict) or not isinstance(m.get("type"), str):
        return "frame must be an object with a type"
    t = m["type"]
    if t == "hello":
        if not _is_int(m.get("protocol_version"), 0, 1_000_000):
            return "protocol_version must be an integer"
        if m.get("mode") not in ("create", "join", "rejoin"):
            return "mode must be create, join or rejoin"
        if not _is_name(m.get("site")):
            return "site must be a name of up to 24 characters"
        if not _is_text(m.get("password"), 128):
            return "password is required"
        if m["mode"] == "rejoin":
            if not _is_text(m.get("token"), 128):
                return "token is required to rejoin"
            if not _is_int(m.get("last_seq"), 0, 1_000_000):
                return "last_seq must be an integer"
        return None
    if t == "lobby_set_players":
        return None if _names(m.get("players")) else "players must be a list of unique names"
    if t == "lobby_start":
        if not _is_int(m.get("lives"), 1, MAX_LIVES):
            return "lives must be 1 to 10"
        return None if _names(m.get("order"), 2) else "order must list the players once"
    if t == "dart":
        if not _is_int(m.get("seq"), 1, 1_000_000) or not _is_name(m.get("player")):
            return "dart needs seq and player"
        return _throws_error(m.get("throws"))
    if t == "turn":
        if not _is_int(m.get("seq"), 1, 1_000_000) or not _is_name(m.get("player")):
            return "turn needs seq and player"
        e = _throws_error(m.get("throws"))
        if e:
            return e
        if m.get("next_player") is not None and not _is_name(m.get("next_player")):
            return "next_player must be a name or null"
        if "next_player" not in m or "winner" not in m:
            return "next_player and winner are required"
        if not isinstance(m.get("eliminated"), list) or not all(_is_name(n) for n in m["eliminated"]):
            return "eliminated must be a list of names"
        if m.get("winner") is not None and not _is_name(m.get("winner")):
            return "winner must be a name or null"
        return None
    if t == "ack":
        if not _is_int(m.get("seq"), 1, 1_000_000):
            return "seq must be a positive integer"
        return None if _is_text(m.get("hash")) else "hash is required"
    if t == "decision":
        return None if m.get("choice") in ("continue", "abort") else "choice must be continue or abort"
    if t in ("rematch", "leave"):
        return None
    return f"unknown frame type {t}"


def _sites_ok(v):
    return isinstance(v, list) and all(isinstance(s, dict) and _is_name(s.get("site")) and _names(s.get("players")) for s in v)


def validate_server_frame(m):
    """None if `m` is a valid frame from the relay, else why not."""
    if not isinstance(m, dict) or not isinstance(m.get("type"), str):
        return "frame must be an object with a type"
    t = m["type"]
    if t == "welcome":
        if not (_is_text(m.get("code"), 12) and _is_name(m.get("site")) and _is_text(m.get("token"), 128)):
            return "welcome needs code, site and token"
        if not isinstance(m.get("host"), bool):
            return "host must be a boolean"
        return None if _is_text(m.get("state"), 20) else "state is required"
    if t == "lobby":
        if not _is_name(m.get("host")):
            return "host must be a name"
        sites = m.get("sites")
        if not isinstance(sites, list) or not all(
                isinstance(s, dict) and _is_name(s.get("site")) and _names(s.get("players")) and isinstance(s.get("connected"), bool)
                for s in sites):
            return "sites must list {site, players, connected}"
        return None if _is_int(m.get("lives"), 0, MAX_LIVES) else "lives must be 0 to 10"
    if t == "rematch":
        return None
    if t == "started":
        if not (_is_text(m.get("match_id"), 64) and _is_int(m.get("lives"), 1, MAX_LIVES) and _names(m.get("order"), 2)):
            return "started needs match_id, lives and order"
        return None if isinstance(m.get("owners"), dict) else "owners must be an object"
    if t in ("dart", "turn"):
        return validate_client_frame({**m, "type": t}) or (None if _is_name(m.get("site")) else "site must be a name")
    if t == "turn_ok":
        return None if _is_int(m.get("seq"), 1, 1_000_000) else "seq must be a positive integer"
    if t == "turn_rejected":
        return None if _is_int(m.get("seq"), 0, 1_000_000) and _is_text(m.get("reason")) else "turn_rejected needs seq and reason"
    if t == "rejected":
        return None if _is_text(m.get("for")) and _is_text(m.get("reason")) else "rejected needs for and reason"
    if t == "paused":
        ok = _is_name(m.get("site")) and isinstance(m.get("rejoin_until"), (int, float)) and _is_text(m.get("reason"))
        return None if ok else "paused needs reason, site and rejoin_until"
    if t == "resumed":
        return None if _is_name(m.get("site")) else "site must be a name"
    if t == "decision_needed":
        return None if _sites_ok(m.get("sites")) else "sites must list {site, players}"
    if t == "site_dropped":
        if not _sites_ok(m.get("sites")):
            return "sites must list {site, players}"
        return None if m.get("next_player") is None or _is_name(m.get("next_player")) else "next_player must be a name or null"
    if t == "desync":
        return None if _is_int(m.get("seq"), 1, 1_000_000) and isinstance(m.get("hashes"), dict) else "desync needs seq and hashes"
    if t == "ended":
        if m.get("reason") not in ("finished", "aborted", "desync"):
            return "reason must be finished, aborted or desync"
        p = m.get("placements")
        ok = isinstance(p, list) and all(isinstance(x, dict) and _is_name(x.get("player")) and _is_int(x.get("placement"), 1, 12) for x in p)
        return None if ok else "placements must list {player, placement}"
    if t == "error":
        return None if _is_int(m.get("code"), 4000, 4999) and _is_text(m.get("message"), 300) else "error needs code and message"
    return f"unknown frame type {t}"


# ── throws on the wire ────────────────────────────────────────────────────────────────

def throw_to_wire(throw):
    """An Autodarts throw ({segment, coords, entry}) as the relay's {number, multiplier, ...}."""
    seg = throw.get("segment") or {}
    wire = {"number": int(seg.get("number") or 0), "multiplier": int(seg.get("multiplier") or 0)}
    if seg.get("name"):
        wire["name"] = str(seg["name"])
    coords = throw.get("coords")
    if isinstance(coords, dict) and "x" in coords and "y" in coords:
        wire["x"], wire["y"] = float(coords["x"]), float(coords["y"])
    if throw.get("entry"):
        wire["entry"] = str(throw["entry"])
    return wire


def throw_from_wire(wire):
    throw = {"segment": {"number": wire["number"], "multiplier": wire["multiplier"]}}
    if wire.get("name"):
        throw["segment"]["name"] = wire["name"]
    if "x" in wire and "y" in wire:
        throw["coords"] = {"x": wire["x"], "y": wire["y"]}
    if wire.get("entry"):
        throw["entry"] = wire["entry"]
    return throw


# ── the session ───────────────────────────────────────────────────────────────────────

class RelayError(Exception):
    """Something the user has to be told: no relay, wrong password, ..."""


def _http_base(relay_url):
    url = relay_url.rstrip("/")
    for ws, http in (("wss://", "https://"), ("ws://", "http://")):
        if url.startswith(ws):
            return http + url[len(ws):]
    return url


def _ws_base(relay_url):
    url = relay_url.rstrip("/")
    for http, ws in (("https://", "wss://"), ("http://", "ws://")):
        if url.startswith(http):
            return ws + url[len(http):]
    return url


def _open_socket(url):
    conn = websocket.create_connection(url, timeout=CONNECT_TIMEOUT_S)
    conn.settimeout(PING_INTERVAL_S)  # a quiet lobby must not end the connection; the reader pings instead
    return conn


class OnlineSession:
    """One online match, from the lobby to the result. `controller` is the
    EliminationController that runs the local game."""

    def __init__(self, controller, on_change=None, connect=None, post=None, sleep=time.sleep):
        self.controller = controller
        self._on_change = on_change
        self._connect = connect or _open_socket
        self._post = post or (lambda url, body: requests.post(url, json=body, timeout=CONNECT_TIMEOUT_S))
        self._sleep = sleep
        self._lock = threading.RLock()
        self._send_lock = threading.Lock()
        self._conn = None
        self._reader = None
        self._ready = threading.Event()
        self._closing = False
        self._fatal = False        # the relay refused us for good, nothing to rejoin
        self._reset()

    def _reset(self):
        self.phase = "idle"        # idle | connecting | lobby | playing | paused | ended
        self.relay_url = None
        self.code = None
        self.site = None
        self.password = None
        self.token = None
        self.host = False
        self.lobby = {"host": None, "sites": [], "lives": 0, "order": []}
        self.local_players = []
        self.match = None          # {match_id, lives, order, owners} once started
        self.paused = None         # {site, rejoin_until}
        self.decision = None       # [{site, players}] while the host has to decide
        self.result = None         # {reason, placements}
        self.message = None        # the last thing the user should know
        self.connected = False

    # ── what the rest of Breakfast asks ──────────────────────────────────────────

    @property
    def active(self):
        return self.phase != "idle"

    def can_play(self):
        """Local darts count only while connected to a running match."""
        return self.connected and self.phase == "playing"

    def status(self):
        with self._lock:
            return {
                "phase": self.phase, "code": self.code, "site": self.site, "host": self.host,
                "lobby": self.lobby, "local_players": list(self.local_players), "match": self.match,
                "paused": self.paused, "decision": self.decision, "result": self.result,
                "message": self.message, "connected": self.connected,
            }

    # ── commands ─────────────────────────────────────────────────────────────────

    def create(self, relay_url, site, password):
        """Reserve a code, open the lobby as its host. Returns the code."""
        self._begin(relay_url, site, password)
        try:
            res = self._post(f"{_http_base(relay_url)}/api/matches", {"protocol_version": PROTOCOL_VERSION})
        except requests.RequestException as e:
            self._fail(f"The relay is not reachable: {e}")
        if res.status_code != 200:
            self._fail(self._http_error(res))
        self.code = res.json()["code"]
        self._open("create")
        return self.code

    def join(self, relay_url, code, site, password):
        self._begin(relay_url, site, password)
        self.code = code.strip().upper()
        self._open("join")

    def set_players(self, players):
        with self._lock:
            self.local_players = list(players)
        self._send({"type": "lobby_set_players", "players": list(players)})

    def start(self, lives, order):
        self._send({"type": "lobby_start", "lives": int(lives), "order": list(order)})

    def rematch(self):
        """Host only, after a finished match: back to the lobby with the same sites and players."""
        with self._lock:
            ready = self.phase == "ended" and self.host and (self.result or {}).get("reason") == "finished"
        if not ready:
            raise RelayError("A rematch needs a finished match and the host")
        self._send({"type": "rematch"})

    def decide(self, choice):
        self._send({"type": "decision", "choice": choice})

    def leave(self):
        with self._lock:
            conn, self._closing = self._conn, True
        if conn is not None:
            self._send({"type": "leave"})
            try:
                conn.close()
            except Exception:
                pass
        with self._lock:
            self._conn = None
            self._reset()
            self._closing = False
        self._changed()

    # ── what the engine reports ──────────────────────────────────────────────────

    def send_dart(self, seq, player, throws):
        self._send({"type": "dart", "seq": seq, "player": player, "throws": [throw_to_wire(t) for t in throws]})

    def send_turn(self, seq, player, throws, next_player, eliminated, winner):
        self._send({"type": "turn", "seq": seq, "player": player, "throws": [throw_to_wire(t) for t in throws],
                    "next_player": next_player, "eliminated": eliminated, "winner": winner})

    def send_ack(self, seq, state_hash):
        self._send({"type": "ack", "seq": seq, "hash": state_hash})

    # ── connection ───────────────────────────────────────────────────────────────

    def _begin(self, relay_url, site, password):
        with self._lock:
            if self.phase not in ("idle", "ended"):
                raise RelayError("An online match is already open")
            self._reset()
            self.phase, self.relay_url, self.site, self.password = "connecting", relay_url, site, password
        self._changed()

    def _fail(self, message):
        with self._lock:
            self._reset()
            self.message = message
        self._changed()
        raise RelayError(message)

    @staticmethod
    def _http_error(res):
        try:
            return res.json().get("error") or f"The relay answered {res.status_code}"
        except ValueError:
            return f"The relay answered {res.status_code}"

    def _open(self, mode):
        url = f"{_ws_base(self.relay_url)}/ws/{self.code}"
        try:
            conn = self._connect(url)
        except Exception as e:
            if mode == "rejoin":
                raise RelayError(f"The relay is not reachable: {e}")
            self._fail(f"The relay is not reachable: {e}")
        self._ready.clear()
        with self._lock:
            self._conn = conn
            self._closing = False
            self._fatal = False
        hello = {"type": "hello", "protocol_version": PROTOCOL_VERSION, "mode": mode, "site": self.site,
                 "password": self.password}
        if mode == "rejoin":
            hello.update(token=self.token, last_seq=self._last_seq())
        self._send(hello)
        self._reader = threading.Thread(target=self._read, args=(conn,), daemon=True, name="relay-reader")
        self._reader.start()
        if mode != "rejoin":
            if not self._ready.wait(CONNECT_TIMEOUT_S) or not self.token:
                message = self.message or "The relay did not answer"
                self._fail(message)

    def _last_seq(self):
        game = self.controller.game
        return game.turn_seq if game is not None else 0

    def _send(self, frame):
        with self._lock:
            conn = self._conn
        if conn is None:
            return
        problem = validate_client_frame(frame)
        if problem:
            log.error("Not sending an invalid %s frame: %s", frame.get("type"), problem)
            return
        try:
            with self._send_lock:
                conn.send(json.dumps(frame, ensure_ascii=False))
        except Exception as e:
            log.warning("Sending to the relay failed: %s", e)

    def _read(self, conn):
        try:
            while True:
                try:
                    raw = conn.recv()
                except websocket.WebSocketTimeoutException:
                    with self._send_lock:
                        conn.ping()  # raises when the connection is gone
                    continue
                if raw is None or raw == "":
                    break
                try:
                    frame = json.loads(raw)
                except ValueError:
                    log.warning("The relay sent something that is not JSON")
                    continue
                problem = validate_server_frame(frame)
                if problem:
                    log.warning("Ignoring an invalid frame from the relay: %s", problem)
                    continue
                self._on_frame(frame)
        except Exception as e:
            log.info("Relay connection ended: %s", e)
        self._on_closed(conn)

    def _on_closed(self, conn):
        with self._lock:
            if conn is not self._conn:
                return
            self._conn = None
            self.connected = False
            closing, phase, final = self._closing, self.phase, self._fatal
        self._ready.set()
        if closing or phase in ("idle", "ended"):
            return
        if phase in ("playing", "paused") and not final and self.token:
            threading.Thread(target=self._reconnect, daemon=True, name="relay-reconnect").start()
            self._changed()
            return
        with self._lock:
            if phase != "ended":
                self.message = self.message or "The connection to the relay was lost"
                self.phase = "ended"
        self._changed()

    def _reconnect(self):
        deadline = time.monotonic() + REJOIN_WINDOW_S
        while time.monotonic() < deadline:
            with self._lock:
                if self._closing or self.phase in ("idle", "ended"):
                    return
            try:
                self._open("rejoin")
                return
            except RelayError:
                pass
            self._sleep(3)
        with self._lock:
            if self.phase not in ("idle", "ended"):
                self.message = "The connection to the relay was lost"
                self.phase = "ended"
        self._changed()

    def _changed(self):
        if self._on_change:
            try:
                self._on_change()
            except Exception:
                log.exception("on_change failed")

    # ── frames from the relay ────────────────────────────────────────────────────

    def _on_frame(self, f):
        handler = getattr(self, f"_on_{f['type']}", None)
        if handler:
            handler(f)
            self._changed()

    def _on_welcome(self, f):
        with self._lock:
            self.token, self.host, self.connected = f["token"], f["host"], True
            if f["state"] in ("playing", "paused"):
                self.phase = f["state"]
            elif self.phase == "connecting":
                self.phase = "lobby"
        self._ready.set()

    def _on_lobby(self, f):
        with self._lock:
            self.lobby = {"host": f["host"], "sites": f["sites"], "lives": f["lives"], "order": f["order"]}

    def _on_rematch(self, f):
        with self._lock:
            self.phase, self.result, self.match = "lobby", None, None
            self.paused = self.decision = self.message = None
        self.controller.stop()

    def _on_started(self, f):
        with self._lock:
            game = self.controller.game
            if game is not None and game.match_id == f["match_id"]:
                self.phase = "playing"
                return
            self.match = {"match_id": f["match_id"], "lives": f["lives"], "order": f["order"], "owners": f["owners"]}
            self.local_players = [p for p in f["order"] if f["owners"].get(p) == self.site]
            self.phase = "playing"
        self.controller.start_online(f["order"], f["lives"], f["match_id"], self.local_players, self)

    def _on_dart(self, f):
        self.controller.remote_dart(f["player"], [throw_from_wire(t) for t in f["throws"]])

    def _on_turn(self, f):
        game = self.controller.game
        if game is not None and f["seq"] <= game.turn_seq:
            return          # a turn we already applied, replayed after a rejoin
        self.controller.remote_turn(f["player"], [throw_from_wire(t) for t in f["throws"]])
        game = self.controller.game
        if game is not None and game.state == "playing" and f.get("next_player") != game.current_player:
            log.warning("Turn %s: the relay expects %s up next, this site has %s", f["seq"], f.get("next_player"), game.current_player)

    def _on_turn_rejected(self, f):
        with self._lock:
            self.message = f"The relay did not accept a turn: {f['reason']}"
        log.warning("Turn %s rejected: %s", f["seq"], f["reason"])

    def _on_rejected(self, f):
        with self._lock:
            self.message = f["reason"]

    def _on_paused(self, f):
        with self._lock:
            self.phase, self.paused = "paused", {"site": f["site"], "rejoin_until": f["rejoin_until"]}

    def _on_resumed(self, f):
        with self._lock:
            self.phase, self.paused, self.decision = "playing", None, None

    def _on_decision_needed(self, f):
        with self._lock:
            self.decision = f["sites"]

    def _on_site_dropped(self, f):
        with self._lock:
            self.decision, self.paused, self.phase = None, None, "playing"
        self.controller.drop_players([p for s in f["sites"] for p in s["players"]], f["next_player"])

    def _on_desync(self, f):
        with self._lock:
            self.message = "The sites no longer agree about the game, the match was stopped"

    def _on_ended(self, f):
        with self._lock:
            self.phase, self.result, self.paused, self.decision = "ended", {"reason": f["reason"], "placements": f["placements"]}, None, None
        if f["reason"] == "finished":
            self.controller.apply_placements(f["placements"])
        else:
            self.controller.stop()

    def _on_error(self, f):
        with self._lock:
            self.message = f["message"]
            self._fatal = f["code"] in _FINAL_CLOSES
