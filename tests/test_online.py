import json
import queue
import threading
import time
from pathlib import Path
from types import SimpleNamespace

import pytest
import websocket

from breakfast import online
from breakfast.elimination import EliminationController
from breakfast.mqtt_output import NullMqttPublisher
from breakfast.online import OnlineSession, RelayError, throw_from_wire, throw_to_wire
from breakfast.stats import StatsDB

EXAMPLES = json.loads((Path(__file__).resolve().parents[1] / "relay/protocol-tests/messages.json").read_text())


# ── the frames shared with the relay ─────────────────────────────────────────────────

@pytest.mark.parametrize("case", EXAMPLES["client"], ids=lambda c: json.dumps(c["frame"])[:60])
def test_client_frames_match_the_shared_examples(case):
    assert (online.validate_client_frame(case["frame"]) is None) is case["valid"]


@pytest.mark.parametrize("case", EXAMPLES["server"], ids=lambda c: json.dumps(c["frame"])[:60])
def test_server_frames_match_the_shared_examples(case):
    assert (online.validate_server_frame(case["frame"]) is None) is case["valid"]


def test_a_throw_survives_the_wire():
    throw = {"segment": {"name": "T20", "number": 20, "multiplier": 3, "bed": "triple"},
             "coords": {"x": 0.01, "y": 0.6}, "entry": "detected"}
    wire = throw_to_wire(throw)
    assert wire == {"number": 20, "multiplier": 3, "name": "T20", "x": 0.01, "y": 0.6, "entry": "detected"}
    assert online.validate_client_frame({"type": "dart", "seq": 1, "player": "a", "throws": [wire]}) is None
    back = throw_from_wire(wire)
    assert back["segment"] == {"number": 20, "multiplier": 3, "name": "T20"} and back["coords"] == {"x": 0.01, "y": 0.6}


def test_a_bare_segment_has_no_position_on_the_wire():
    assert throw_to_wire({"segment": {"number": 5, "multiplier": 1}}) == {"number": 5, "multiplier": 1}


# ── a scripted connection ───────────────────────────────────────────────────────────

class FakeConn:
    def __init__(self):
        self.sent = []
        self.inbox = queue.Queue()
        self.closed = False
        self.pings = 0

    def send(self, text):
        self.sent.append(json.loads(text))

    def recv(self):
        item = self.inbox.get(timeout=5)
        if isinstance(item, Exception):
            raise item
        return item

    def ping(self):
        self.pings += 1

    def close(self):
        self.closed = True
        self.inbox.put(None)

    def push(self, frame):
        self.inbox.put(json.dumps(frame))

    def sent_types(self):
        return [f["type"] for f in self.sent]


def _wait(cond, timeout=3):
    end = time.time() + timeout
    while time.time() < end:
        if cond():
            return True
        time.sleep(0.01)
    return False


WELCOME = {"type": "welcome", "code": "K7M2QX", "site": "Home", "token": "tok", "host": True, "state": "lobby"}


class Harness:
    def __init__(self):
        self.db = StatsDB(":memory:")
        self.ctrl = EliminationController(NullMqttPublisher(), "autodarts", stats_db=self.db)
        self.conns = []
        self.posts = []
        self.sleeps = []
        self.session = OnlineSession(self.ctrl, connect=self._connect, post=self._post, sleep=self.sleeps.append)
        self.next_frames = [WELCOME]

    def _post(self, url, body):
        self.posts.append((url, body))
        return SimpleNamespace(status_code=200, json=lambda: {"code": "K7M2QX", "expires_in_s": 600})

    def _connect(self, url):
        conn = FakeConn()
        conn.url = url
        self.conns.append(conn)
        for frame in self.next_frames:
            conn.push(frame)
        self.next_frames = []
        return conn


@pytest.fixture
def h():
    harness = Harness()
    yield harness
    harness.session.leave()


# ── session ──────────────────────────────────────────────────────────────────────────

class TestLobby:
    def test_create_reserves_a_code_and_says_hello(self, h):
        code = h.session.create("ws://127.0.0.1:8787", "Home", "pw")
        assert code == "K7M2QX"
        assert h.posts == [("http://127.0.0.1:8787/api/matches", {"protocol_version": 1})]
        assert h.conns[0].url == "ws://127.0.0.1:8787/ws/K7M2QX"
        assert h.conns[0].sent[0] == {"type": "hello", "protocol_version": 1, "mode": "create", "site": "Home", "password": "pw"}
        assert h.session.status()["phase"] == "lobby" and h.session.status()["host"] is True

    def test_secure_relay_urls_use_https_for_the_reservation(self, h):
        h.session.create("wss://relay.example.workers.dev/", "Home", "pw")
        assert h.posts[0][0] == "https://relay.example.workers.dev/api/matches"
        assert h.conns[0].url == "wss://relay.example.workers.dev/ws/K7M2QX"

    def test_join_uppercases_the_code(self, h):
        h.next_frames = [{**WELCOME, "site": "Club", "host": False}]
        h.session.join("ws://relay", "k7m2qx", "Club", "pw")
        assert h.conns[0].url.endswith("/ws/K7M2QX")
        assert h.conns[0].sent[0]["mode"] == "join"
        assert h.session.status()["host"] is False

    def test_a_refusal_is_reported_and_leaves_nothing_open(self, h):
        h.next_frames = [{"type": "error", "code": 4401, "message": "wrong password"}]
        with pytest.raises(RelayError, match="wrong password"):
            h.session.join("ws://relay", "K7M2QX", "Club", "nope")
        assert h.session.status()["phase"] == "idle" and h.session.status()["message"] == "wrong password"

    def test_an_unreachable_relay_is_reported(self, h):
        def refuse(url):
            raise OSError("connection refused")
        h.session._connect = refuse
        with pytest.raises(RelayError, match="not reachable"):
            h.session.create("ws://relay", "Home", "pw")
        assert h.session.status()["phase"] == "idle"

    def test_a_quiet_connection_is_pinged_and_kept(self, h):
        h.session.create("ws://127.0.0.1:8787", "Home", "pw")
        h.conns[0].inbox.put(websocket.WebSocketTimeoutException("Connection timed out"))
        assert _wait(lambda: h.conns[0].pings == 1)
        assert h.session.status()["phase"] == "lobby" and h.session.connected

    def test_the_lobby_is_kept(self, h):
        h.session.create("ws://relay", "Home", "pw")
        h.conns[0].push({"type": "lobby", "host": "Home", "sites": [{"site": "Home", "players": ["anna"], "connected": True}], "lives": 0, "order": []})
        assert _wait(lambda: h.session.status()["lobby"]["sites"])
        assert h.session.status()["lobby"]["sites"][0]["players"] == ["anna"]

    def test_players_and_start_go_to_the_relay(self, h):
        h.session.create("ws://relay", "Home", "pw")
        h.session.set_players(["anna", "ben"])
        h.session.start(3, ["ben", "anna"])
        assert h.conns[0].sent[1:] == [
            {"type": "lobby_set_players", "players": ["anna", "ben"]},
            {"type": "lobby_start", "lives": 3, "order": ["ben", "anna"]}]

    def test_an_invalid_frame_is_not_sent(self, h):
        h.session.create("ws://relay", "Home", "pw")
        h.session.start(99, ["a", "b"])
        assert h.conns[0].sent_types() == ["hello"]

    def test_a_second_match_cannot_be_opened(self, h):
        h.session.create("ws://relay", "Home", "pw")
        with pytest.raises(RelayError, match="already open"):
            h.session.create("ws://relay", "Home", "pw")

    def test_leave_closes_and_resets(self, h):
        h.session.create("ws://relay", "Home", "pw")
        h.session.leave()
        assert h.conns[0].sent[-1] == {"type": "leave"} and h.conns[0].closed
        assert h.session.status()["phase"] == "idle"


STARTED = {"type": "started", "match_id": "m-online", "lives": 2, "order": ["anna", "carl"],
           "owners": {"anna": "Home", "carl": "Club"}}


def _t(number, multiplier, name=None):
    seg = {"number": number, "multiplier": multiplier}
    if name:
        seg["name"] = name
    return {"segment": seg}


def _w(number, multiplier):
    return {"number": number, "multiplier": multiplier}


class TestMatch:
    def _start(self, h):
        h.session.create("ws://relay", "Home", "pw")
        h.conns[0].push(STARTED)
        assert _wait(lambda: h.ctrl.game is not None)
        return h.conns[0]

    def test_started_creates_the_game_with_the_relays_match_id(self, h):
        self._start(h)
        game = h.ctrl.game
        assert game.match_id == "m-online" and game.order == ["anna", "carl"] and game.lives == {"anna": 2, "carl": 2}
        assert game.local_players == {"anna"}
        assert h.session.status()["phase"] == "playing" and h.session.status()["local_players"] == ["anna"]

    def test_a_local_turn_goes_to_the_relay_with_its_hash(self, h):
        conn = self._start(h)
        for n in (1, 2, 3):                                    # anna: 180, dart by dart
            h.ctrl.on_board_state(n, [_t(20, 3, "T20")] * n)
        h.ctrl.on_board_state(0, [])
        types = conn.sent_types()
        assert types.count("dart") == 3
        turn = next(f for f in conn.sent if f["type"] == "turn")
        assert turn["seq"] == 1 and turn["player"] == "anna" and turn["next_player"] == "carl"
        assert turn["eliminated"] == [] and turn["winner"] is None and len(turn["throws"]) == 3
        ack = conn.sent[-1]
        assert ack == {"type": "ack", "seq": 1, "hash": h.ctrl.game.state_hash()}

    def test_the_board_of_a_remote_players_turn_is_ignored(self, h):
        conn = self._start(h)
        h.ctrl.on_board_state(3, [_t(20, 3)] * 3)
        h.ctrl.on_board_state(0, [])                           # carl is up now
        sent = len(conn.sent)
        h.ctrl.on_board_state(1, [_t(1, 1)])
        h.ctrl.on_board_state(0, [])
        assert len(conn.sent) == sent and h.ctrl.game.current_player == "carl"

    def test_remote_darts_show_live_and_the_turn_is_applied(self, h):
        conn = self._start(h)
        h.ctrl.on_board_state(3, [_t(20, 3)] * 3)
        h.ctrl.on_board_state(0, [])
        conn.push({"type": "dart", "seq": 2, "player": "carl", "throws": [_w(1, 1)], "site": "Club"})
        assert _wait(lambda: h.ctrl.game.snapshot()["current_darts"] == [1])
        conn.push({"type": "turn", "seq": 2, "player": "carl", "throws": [_w(1, 1), _w(1, 1), _w(1, 1)],
                   "next_player": "anna", "eliminated": [], "winner": None, "site": "Club"})
        assert _wait(lambda: h.ctrl.game.turn_seq == 2)
        game = h.ctrl.game
        assert game.lives == {"anna": 2, "carl": 1} and game.current_player == "anna"
        rows = h.db._conn.execute("SELECT player, score FROM elimination_turns ORDER BY id").fetchall()
        assert [(r["player"], r["score"]) for r in rows] == [("anna", 180), ("carl", 3)]
        assert conn.sent[-1]["type"] == "ack" and conn.sent[-1]["seq"] == 2

    def test_a_replayed_turn_is_applied_once(self, h):
        conn = self._start(h)
        h.ctrl.on_board_state(3, [_t(20, 3)] * 3)
        h.ctrl.on_board_state(0, [])
        turn = {"type": "turn", "seq": 2, "player": "carl", "throws": [_w(1, 1)] * 3,
                "next_player": "anna", "eliminated": [], "winner": None, "site": "Club"}
        conn.push(turn)
        assert _wait(lambda: h.ctrl.game.turn_seq == 2)
        conn.push(turn)
        conn.push({**turn, "seq": 1})
        time.sleep(0.1)
        assert h.ctrl.game.turn_seq == 2 and h.ctrl.game.lives["carl"] == 1

    def test_the_match_ends_with_the_relays_placements(self, h):
        conn = self._start(h)
        h.ctrl.on_board_state(3, [_t(20, 3)] * 3)
        h.ctrl.on_board_state(0, [])
        conn.push({"type": "turn", "seq": 2, "player": "carl", "throws": [_w(1, 1)] * 3,
                   "next_player": "anna", "eliminated": [], "winner": None, "site": "Club"})
        assert _wait(lambda: h.ctrl.game.turn_seq == 2)
        h.ctrl.on_board_state(3, [_t(20, 3)] * 3)
        h.ctrl.on_board_state(0, [])
        conn.push({"type": "turn", "seq": 4, "player": "carl", "throws": [_w(1, 1)] * 3,
                   "next_player": None, "eliminated": ["carl"], "winner": "anna", "site": "Club"})
        assert _wait(lambda: h.ctrl.game.state == "finished")
        conn.push({"type": "ended", "reason": "finished", "placements": [{"player": "anna", "placement": 1}, {"player": "carl", "placement": 2}]})
        assert _wait(lambda: h.session.status()["phase"] == "ended")
        rows = h.db._conn.execute("SELECT player, placement FROM elimination_results WHERE match_id = 'm-online' ORDER BY placement").fetchall()
        assert [(r["player"], r["placement"]) for r in rows] == [("anna", 1), ("carl", 2)]

    def _finish(self, h):
        conn = self._start(h)
        conn.push({"type": "ended", "reason": "finished", "placements": [{"player": "anna", "placement": 1}, {"player": "carl", "placement": 2}]})
        assert _wait(lambda: h.session.status()["phase"] == "ended")
        return conn

    def test_a_rematch_goes_back_to_the_lobby_on_the_same_connection(self, h):
        conn = self._finish(h)
        h.session.rematch()
        assert conn.sent[-1] == {"type": "rematch"}
        conn.push({"type": "rematch"})
        conn.push({"type": "lobby", "host": "Home", "lives": 2, "order": ["carl", "anna"],
                   "sites": [{"site": "Home", "players": ["anna"], "connected": True}, {"site": "Club", "players": ["carl"], "connected": True}]})
        assert _wait(lambda: h.session.status()["phase"] == "lobby")
        status = h.session.status()
        assert status["result"] is None and status["match"] is None and status["lobby"]["order"] == ["carl", "anna"]
        assert h.ctrl.game is None and not conn.closed and status["connected"]
        assert status["local_players"] == ["anna"]

    def test_a_rematch_starts_a_new_game(self, h):
        conn = self._finish(h)
        conn.push({"type": "rematch"})
        assert _wait(lambda: h.session.status()["phase"] == "lobby")
        conn.push({**STARTED, "match_id": "m-second", "order": ["carl", "anna"]})
        assert _wait(lambda: h.ctrl.game is not None and h.ctrl.game.match_id == "m-second")
        assert h.ctrl.game.order == ["carl", "anna"] and h.session.status()["phase"] == "playing"

    def test_a_rematch_needs_a_finished_match_and_the_host(self, h):
        conn = self._start(h)
        with pytest.raises(RelayError):
            h.session.rematch()                                 # still playing
        conn.push({"type": "ended", "reason": "aborted", "placements": []})
        assert _wait(lambda: h.session.status()["phase"] == "ended")
        with pytest.raises(RelayError):
            h.session.rematch()                                 # aborted, nothing to repeat

    def test_a_guest_cannot_ask_for_a_rematch(self, h):
        h.next_frames = [{**WELCOME, "site": "Club", "host": False}]
        h.session.join("ws://relay", "k7m2qx", "Club", "pw")
        h.conns[0].push({**STARTED, "owners": {"anna": "Home", "carl": "Club"}})
        assert _wait(lambda: h.ctrl.game is not None)
        h.conns[0].push({"type": "ended", "reason": "finished", "placements": [{"player": "anna", "placement": 1}, {"player": "carl", "placement": 2}]})
        assert _wait(lambda: h.session.status()["phase"] == "ended")
        with pytest.raises(RelayError):
            h.session.rematch()

    def test_playing_on_without_a_dropped_site(self, h):
        conn = self._start(h)
        conn.push({"type": "site_dropped", "sites": [{"site": "Club", "players": ["carl"]}], "next_player": None})
        assert _wait(lambda: h.ctrl.game.state == "finished")
        assert h.ctrl.game.winner == "anna"

    def test_an_aborted_match_stops_the_game(self, h):
        conn = self._start(h)
        conn.push({"type": "ended", "reason": "aborted", "placements": []})
        assert _wait(lambda: h.ctrl.game is None)
        assert h.session.status()["result"]["reason"] == "aborted"

    def test_pause_and_decision_are_kept(self, h):
        conn = self._start(h)
        conn.push({"type": "paused", "reason": "disconnect", "site": "Club", "rejoin_until": 1})
        assert _wait(lambda: h.session.status()["phase"] == "paused")
        assert not h.session.can_play()
        conn.push({"type": "decision_needed", "sites": [{"site": "Club", "players": ["carl"]}]})
        assert _wait(lambda: h.session.status()["decision"])
        conn.push({"type": "resumed", "site": "Club"})
        assert _wait(lambda: h.session.status()["phase"] == "playing" and h.session.status()["decision"] is None)

    def test_undo_and_corrections_are_not_available_online(self, h):
        self._start(h)
        h.ctrl.on_board_state(3, [_t(20, 3)] * 3)
        h.ctrl.on_board_state(0, [])
        assert h.ctrl.game.undo() is False
        h.ctrl.game.correct_turn(10)
        assert h.ctrl.game.turn_seq == 1 and h.ctrl.game.lives["anna"] == 2

    def test_a_dropped_connection_is_rejoined_with_the_token(self, h):
        conn = self._start(h)
        h.next_frames = [{**WELCOME, "state": "playing"}]
        conn.inbox.put(None)                                    # the relay hangs up
        assert _wait(lambda: len(h.conns) == 2)
        rejoin = h.conns[1].sent[0]
        assert rejoin["mode"] == "rejoin" and rejoin["token"] == "tok" and rejoin["last_seq"] == 0
        assert _wait(lambda: h.session.status()["connected"])

    def test_a_refusal_is_final(self, h):
        conn = self._start(h)
        conn.push({"type": "error", "code": 4410, "message": "this match is over"})
        conn.inbox.put(None)
        assert _wait(lambda: h.session.status()["phase"] == "ended")
        assert len(h.conns) == 1


# ── two sites through a tiny in-process relay ───────────────────────────────────────

class Hub:
    """Just enough relay for two sites: it assigns the match, forwards darts and turns."""

    def __init__(self):
        self.sites = {}
        self.lobby = {}
        self.log = []

    def connect_for(self, session_name):
        def connect(url):
            conn = FakeConn()
            hub = self

            def send(text, conn=conn):
                frame = json.loads(text)
                hub.on_frame(conn, frame)
            conn.send = send
            conn.name = session_name
            return conn
        return connect

    def on_frame(self, conn, f):
        t = f["type"]
        if t == "hello":
            self.sites[f["site"]] = conn
            conn.site = f["site"]
            conn.push({"type": "welcome", "code": "K7M2QX", "site": f["site"], "token": "t-" + f["site"],
                       "host": f["mode"] == "create", "state": "lobby"})
        elif t == "lobby_set_players":
            self.lobby[conn.site] = f["players"]
        elif t == "lobby_start":
            owners = {p: s for s, ps in self.lobby.items() for p in ps}
            for c in self.sites.values():
                c.push({"type": "started", "match_id": "m-hub", "lives": f["lives"], "order": f["order"], "owners": owners})
        elif t in ("dart", "turn"):
            for site, c in self.sites.items():
                if site != conn.site:
                    c.push({**f, "site": conn.site})
            if t == "turn":
                conn.push({"type": "turn_ok", "seq": f["seq"]})
            self.log.append(f)


def _throws(*specs):
    return [_t(n, m, f"{'SDT'[m - 1]}{n}") for n, m in specs]


def test_two_sites_play_a_match_and_agree():
    hub = Hub()
    sites = {}
    for name, players in (("Home", ["anna", "ben"]), ("Club", ["carl"])):
        db = StatsDB(":memory:")
        ctrl = EliminationController(NullMqttPublisher(), "autodarts", stats_db=db)
        session = OnlineSession(ctrl, connect=hub.connect_for(name), post=lambda url, body: SimpleNamespace(status_code=200, json=lambda: {"code": "K7M2QX"}))
        sites[name] = SimpleNamespace(db=db, ctrl=ctrl, session=session, players=players)
    sites["Home"].session.create("ws://hub", "Home", "pw")
    sites["Club"].session.join("ws://hub", "K7M2QX", "Club", "pw")
    for s in sites.values():
        s.session.set_players(s.players)
    sites["Home"].session.start(2, ["anna", "carl", "ben"])
    assert _wait(lambda: all(s.ctrl.game for s in sites.values()))

    def turn(site, throws):
        ctrl = sites[site].ctrl
        ctrl.on_board_state(len(throws), throws)
        ctrl.on_board_state(0, [])

    def settle(seq):
        assert _wait(lambda: all(s.ctrl.game.turn_seq == seq for s in sites.values()))

    turn("Home", _throws((20, 3), (20, 3), (20, 3)))      # anna 180
    settle(1)
    turn("Club", _throws((1, 1), (1, 1), (1, 1)))         # carl 3: loses a life
    settle(2)
    turn("Home", _throws((5, 1), (5, 1), (5, 1)))         # ben 15 against 3: passes
    settle(3)
    for s in sites.values():
        game = s.ctrl.game
        assert game.current_player == "anna" and game.lives == {"anna": 2, "carl": 1, "ben": 2}
        assert game.match_id == "m-hub"
    assert sites["Home"].ctrl.game.state_hash() == sites["Club"].ctrl.game.state_hash()
    # everything of everyone is in both databases, remote players are ordinary players
    for s in sites.values():
        rows = s.db._conn.execute("SELECT player, score FROM elimination_turns ORDER BY id").fetchall()
        assert [(r["player"], r["score"]) for r in rows] == [("anna", 180), ("carl", 3), ("ben", 15)]
        assert {p["name"] for p in s.db._conn.execute("SELECT name FROM players").fetchall()} >= {"anna", "carl", "ben"}
    for s in sites.values():
        s.session.leave()
