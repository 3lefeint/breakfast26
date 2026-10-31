"""Two Breakfast sites play a whole Elimination match against the real relay: the Worker
runs under `wrangler dev` (workerd, local Durable Objects), the sites are two
OnlineSessions with their own EliminationController and stats database."""

import shutil
import socket
import subprocess
import time
from pathlib import Path
from types import SimpleNamespace

import pytest
import requests

from breakfast.elimination import EliminationController
from breakfast.mqtt_output import NullMqttPublisher
from breakfast.online import OnlineSession, RelayError
from breakfast.stats import StatsDB

RELAY = Path(__file__).resolve().parents[1] / "relay"
WRANGLER = RELAY / "node_modules" / ".bin" / "wrangler"

pytestmark = pytest.mark.skipif(
    not WRANGLER.exists() or not shutil.which("node"),
    reason="needs `npm install` in relay/ and node")


def _free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture(scope="module")
def relay_url(tmp_path_factory):
    port = _free_port()
    state = tmp_path_factory.mktemp("wrangler-state")
    proc = subprocess.Popen(
        [str(WRANGLER), "dev", "--port", str(port), "--ip", "127.0.0.1", "--persist-to", str(state)],
        cwd=RELAY, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    url = f"http://127.0.0.1:{port}"
    try:
        for _ in range(120):
            try:
                if requests.get(url + "/", timeout=1).status_code == 200:
                    break
            except requests.RequestException:
                pass
            time.sleep(0.5)
        else:
            pytest.fail("wrangler dev did not come up")
        yield f"ws://127.0.0.1:{port}"
    finally:
        proc.terminate()
        try:
            proc.wait(10)
        except subprocess.TimeoutExpired:
            proc.kill()


def _site(players):
    db = StatsDB(":memory:")
    ctrl = EliminationController(NullMqttPublisher(), "autodarts", stats_db=db)
    return SimpleNamespace(db=db, ctrl=ctrl, session=OnlineSession(ctrl), players=players)


def _wait(cond, timeout=15):
    end = time.time() + timeout
    while time.time() < end:
        if cond():
            return True
        time.sleep(0.05)
    return False


def _throws(number, multiplier, n=3):
    return [{"segment": {"number": number, "multiplier": multiplier, "name": f"{'SDT'[multiplier - 1]}{number}"},
             "coords": {"x": 0.0, "y": 0.6}, "entry": "detected"}] * n


def test_a_wrong_protocol_version_is_refused_at_the_door(relay_url):
    res = requests.post(relay_url.replace("ws://", "http://") + "/api/matches", json={"protocol_version": 99})
    assert res.status_code == 426 and "upgrade" in res.json()["error"]


def test_the_wrong_password_does_not_get_in(relay_url):
    host, guest = _site(["anna"]), _site(["carl"])
    code = host.session.create(relay_url, "Home", "right")
    with pytest.raises(RelayError, match="password"):
        guest.session.join(relay_url, code, "Club", "wrong")
    host.session.leave()


def test_two_sites_play_a_whole_match(relay_url):
    home, club = _site(["anna", "ben"]), _site(["carl"])
    sites = {"Home": home, "Club": club}
    code = home.session.create(relay_url, "Home", "pw")
    club.session.join(relay_url, code, "Club", "pw")
    home.session.set_players(home.players)
    club.session.set_players(club.players)
    assert _wait(lambda: len(home.session.status()["lobby"]["sites"]) == 2
                 and sum(len(s["players"]) for s in home.session.status()["lobby"]["sites"]) == 3)
    home.session.start(1, ["anna", "carl", "ben"])
    assert _wait(lambda: home.ctrl.game and club.ctrl.game)
    assert home.ctrl.game.match_id == club.ctrl.game.match_id

    def throw(site, number, multiplier):
        ctrl = sites[site].ctrl
        for n in (1, 2, 3):
            ctrl.on_board_state(n, _throws(number, multiplier, n))
        ctrl.on_board_state(0, [])

    def settle(seq):
        assert _wait(lambda: home.ctrl.game.turn_seq == seq and club.ctrl.game.turn_seq == seq)

    throw("Home", 20, 3)        # anna 180
    settle(1)
    throw("Club", 1, 1)         # carl 3 against 180: his only life
    settle(2)
    assert club.ctrl.game.current_player == "ben"
    throw("Home", 1, 1)         # ben: a freipass after an elimination, 3 passes
    settle(3)
    throw("Home", 1, 1)         # anna 3 against 3 is not enough: out, ben wins
    assert _wait(lambda: home.session.status()["phase"] == "ended" and club.session.status()["phase"] == "ended")
    settle(4)
    # each site stores the players of the other site as guests, name@site
    stored = {"Home": {"ben": "ben", "anna": "anna", "carl": "carl@club"},
              "Club": {"ben": "ben@home", "anna": "anna@home", "carl": "carl"}}
    for name, s in sites.items():
        assert s.ctrl.game.state == "finished" and s.ctrl.game.winner == "ben"
        result = s.session.status()["result"]
        assert result["reason"] == "finished"
        assert [(p["player"], p["placement"]) for p in result["placements"]] == [("ben", 1), ("anna", 2), ("carl", 3)]
        rows = s.db._conn.execute("SELECT player, placement FROM elimination_results ORDER BY placement").fetchall()
        assert [(r["player"], r["placement"]) for r in rows] == [(stored[name][p], n) for p, n in (("ben", 1), ("anna", 2), ("carl", 3))]
        turns = s.db._conn.execute("SELECT player FROM elimination_turns ORDER BY id").fetchall()
        assert [t["player"] for t in turns] == [stored[name][p] for p in ("anna", "carl", "ben", "anna")]
    assert home.ctrl.game.state_hash() == club.ctrl.game.state_hash()


def test_a_site_that_drops_rejoins_and_the_match_goes_on(relay_url):
    home, club = _site(["anna"]), _site(["carl"])
    code = home.session.create(relay_url, "Home", "pw")
    club.session.join(relay_url, code, "Club", "pw")
    home.session.set_players(home.players)
    club.session.set_players(club.players)
    assert _wait(lambda: sum(len(s["players"]) for s in home.session.status()["lobby"]["sites"]) == 2)
    home.session.start(2, ["anna", "carl"])
    assert _wait(lambda: home.ctrl.game and club.ctrl.game)

    club.session._conn.close()                                   # the connection of the club breaks
    assert _wait(lambda: home.session.status()["phase"] == "paused" or club.session.status()["connected"])
    assert _wait(lambda: home.session.status()["phase"] == "playing" and club.session.status()["connected"])

    ctrl = home.ctrl
    for n in (1, 2, 3):
        ctrl.on_board_state(n, _throws(20, 3, n))
    ctrl.on_board_state(0, [])
    assert _wait(lambda: club.ctrl.game.turn_seq == 1 and club.ctrl.game.current_player == "carl")
    home.session.leave()
    club.session.leave()


def test_a_rematch_plays_a_second_match_in_the_same_room(relay_url):
    home, club = _site(["anna", "ben"]), _site(["carl"])
    sites = {"Home": home, "Club": club}
    code = home.session.create(relay_url, "Home", "pw")
    club.session.join(relay_url, code, "Club", "pw")
    home.session.set_players(home.players)
    club.session.set_players(club.players)
    assert _wait(lambda: sum(len(s["players"]) for s in home.session.status()["lobby"]["sites"]) == 3)
    home.session.start(1, ["anna", "carl", "ben"])
    assert _wait(lambda: home.ctrl.game and club.ctrl.game)
    first_match = home.ctrl.game.match_id

    def throw(site, number, multiplier):
        ctrl = sites[site].ctrl
        for n in (1, 2, 3):
            ctrl.on_board_state(n, _throws(number, multiplier, n))
        ctrl.on_board_state(0, [])

    def settle(seq):
        assert _wait(lambda: home.ctrl.game.turn_seq == seq and club.ctrl.game.turn_seq == seq)

    for seq, (site, number, multiplier) in enumerate([("Home", 20, 3), ("Club", 1, 1), ("Home", 1, 1), ("Home", 1, 1)], 1):
        throw(site, number, multiplier)
        settle(seq)
    assert _wait(lambda: home.session.status()["phase"] == "ended" and club.session.status()["phase"] == "ended")

    with pytest.raises(RelayError):
        club.session.rematch()                                    # only the host asks
    home.session.rematch()
    assert _wait(lambda: all(s.session.status()["phase"] == "lobby" for s in sites.values()))
    for s in sites.values():
        status = s.session.status()
        assert status["result"] is None and status["match"] is None and s.ctrl.game is None
        assert status["lobby"]["order"] == ["carl", "anna", "ben"]      # like a local rematch: the winner is last
        assert status["connected"]

    club.session.set_players(["carl", "tom"])                   # the players can change
    assert _wait(lambda: sum(len(s["players"]) for s in home.session.status()["lobby"]["sites"]) == 4)
    home.session.start(1, ["carl", "anna", "ben", "tom"])
    assert _wait(lambda: home.ctrl.game and club.ctrl.game)
    assert home.ctrl.game.match_id == club.ctrl.game.match_id != first_match

    plan = [("Club", 20, 3), ("Home", 1, 1), ("Home", 1, 1), ("Club", 1, 1), ("Club", 20, 3), ("Home", 1, 1)]
    for seq, (site, number, multiplier) in enumerate(plan, 1):
        throw(site, number, multiplier)
        settle(seq)
    assert _wait(lambda: home.session.status()["phase"] == "ended" and club.session.status()["phase"] == "ended")
    for s in sites.values():
        assert s.ctrl.game.state == "finished" and s.ctrl.game.winner == "carl"
        matches = s.db._conn.execute("SELECT DISTINCT match_id FROM elimination_results").fetchall()
        assert len(matches) == 2
    assert home.ctrl.game.state_hash() == club.ctrl.game.state_hash()
    home.session.leave()
    club.session.leave()


def test_a_turn_and_the_turn_that_ended_the_match_are_taken_back_on_both_sites(relay_url):
    home, club = _site(["anna", "ben"]), _site(["carl"])
    sites = {"Home": home, "Club": club}
    code = home.session.create(relay_url, "Home", "pw")
    club.session.join(relay_url, code, "Club", "pw")
    home.session.set_players(home.players)
    club.session.set_players(club.players)
    assert _wait(lambda: sum(len(s["players"]) for s in home.session.status()["lobby"]["sites"]) == 3)
    home.session.start(1, ["anna", "carl", "ben"])
    assert _wait(lambda: home.ctrl.game and club.ctrl.game)

    def throw(site, number, multiplier):
        ctrl = sites[site].ctrl
        for n in (1, 2, 3):
            ctrl.on_board_state(n, _throws(number, multiplier, n))
        ctrl.on_board_state(0, [])

    def settle(seq):
        assert _wait(lambda: home.ctrl.game.turn_seq == seq and club.ctrl.game.turn_seq == seq)

    throw("Home", 20, 3)        # anna 180
    settle(1)
    throw("Club", 1, 1)         # carl 3: his only life
    settle(2)
    club.session.undo()         # carl takes his turn back: he is up again at both sites
    assert _wait(lambda: home.ctrl.game.turn_seq == 1 and club.ctrl.game.turn_seq == 1)
    for s in sites.values():
        assert s.ctrl.game.current_player == "carl" and s.ctrl.game.lives == {"anna": 1, "carl": 1, "ben": 1}
    home.session.undo()         # Home takes anna's turn back as well: anna is up again
    assert _wait(lambda: home.ctrl.game.turn_seq == 0 and club.ctrl.game.turn_seq == 0)
    assert home.ctrl.game.current_player == "anna" and club.ctrl.game.current_player == "anna"
    throw("Home", 20, 3)        # the match is played again: anna 180, carl 3 is out, ben passes, anna is out
    settle(1)
    throw("Club", 1, 1)
    settle(2)
    throw("Home", 1, 1)
    settle(3)
    throw("Home", 1, 1)
    assert _wait(lambda: home.session.status()["phase"] == "ended" and club.session.status()["phase"] == "ended")
    settle(4)
    winner = home.ctrl.game.winner
    club.session.undo()         # the last turn was Home's: the relay refuses a take-back from Club
    assert _wait(lambda: "site that threw" in (club.session.status()["message"] or ""))
    assert home.session.status()["phase"] == "ended"
    home.session.undo()         # Home takes back the turn that ended the match
    assert _wait(lambda: home.session.status()["phase"] == "playing" and club.session.status()["phase"] == "playing")
    for s in sites.values():
        assert s.ctrl.game.state == "playing" and s.ctrl.game.winner is None and winner is not None
        assert s.db._conn.execute("SELECT COUNT(*) FROM elimination_results").fetchone()[0] == 0
    assert home.ctrl.game.state_hash() == club.ctrl.game.state_hash()
    for s in sites.values():
        s.session.leave()


def test_a_dart_and_a_total_are_corrected_on_both_sites(relay_url):
    home, club = _site(["anna", "ben"]), _site(["carl"])
    sites = {"Home": home, "Club": club}
    code = home.session.create(relay_url, "Home", "pw")
    club.session.join(relay_url, code, "Club", "pw")
    home.session.set_players(home.players)
    club.session.set_players(club.players)
    assert _wait(lambda: sum(len(s["players"]) for s in home.session.status()["lobby"]["sites"]) == 3)
    home.session.start(2, ["anna", "carl", "ben"])
    assert _wait(lambda: home.ctrl.game and club.ctrl.game)

    def throw(site, number, multiplier):
        ctrl = sites[site].ctrl
        for n in (1, 2, 3):
            ctrl.on_board_state(n, _throws(number, multiplier, n))
        ctrl.on_board_state(0, [])

    def settle(seq):
        assert _wait(lambda: home.ctrl.game.turn_seq == seq and club.ctrl.game.turn_seq == seq)

    def scores(site, player):
        rows = sites[site].db._conn.execute("SELECT score FROM elimination_turns WHERE player = ? ORDER BY id", (player,)).fetchall()
        return [r["score"] for r in rows]

    throw("Home", 20, 3)                      # anna 180
    settle(1)
    assert home.ctrl.game.correct_last_dart(0, "S1") is True      # the first dart was a single 1: 1 + 60 + 60
    assert _wait(lambda: scores("Club", "anna@home") == [121])
    assert scores("Home", "anna") == [121]
    settle(1)
    assert home.ctrl.game.state_hash() == club.ctrl.game.state_hash()
    throw("Club", 1, 1)                       # carl 3 against 121: a life lost
    settle(2)
    assert club.ctrl.game.lives["carl"] == 1
    club.ctrl.game.correct_turn(150)          # carl's total was 150: he passes
    assert _wait(lambda: home.ctrl.game.lives["carl"] == 2)
    for s in sites.values():
        assert s.ctrl.game.lives["carl"] == 2 and s.ctrl.game.current_player == "ben"
    assert scores("Club", "carl") == [150] and scores("Home", "carl@club") == [150]
    assert _wait(lambda: home.ctrl.game.state_hash() == club.ctrl.game.state_hash())
    for s in sites.values():
        s.session.leave()


# ── X01 ───────────────────────────────────────────────────────────────────────

def _x01_site(players):
    """A site that can play X01: the controller feeds a statistics tracker like the server does."""
    from breakfast.state import GameState
    from breakfast.stats import StatsTracker
    from breakfast.x01_game import X01Controller
    db = StatsDB(":memory:")
    tracker = StatsTracker(db)
    state = GameState()

    def emit(data):
        state.update(data)
        tracker.process(data)

    elim = EliminationController(NullMqttPublisher(), "autodarts", stats_db=db)
    x01 = X01Controller(emit, stats_db=db)
    x01.tracker = tracker
    return SimpleNamespace(db=db, ctrl=x01, session=OnlineSession(elim, x01=x01), players=players)


def _dart(number, multiplier, x, y):
    return {"segment": {"number": number, "multiplier": multiplier, "name": f"{'SDT'[multiplier - 1]}{number}"},
            "coords": {"x": x, "y": y}, "entry": "detected"}


X01_RULES = {"start": 40, "in_mode": "straight", "out_mode": "double", "legs": 1, "bull_off": True, "max_rounds": None}


def test_two_sites_play_an_x01_match_from_the_bull_off_to_the_checkout(relay_url):
    home, club = _x01_site(["anna"]), _x01_site(["carl"])
    sites = {"Home": home, "Club": club}
    code = home.session.create(relay_url, "Home", "pw")
    club.session.join(relay_url, code, "Club", "pw")
    home.session.set_players(home.players)
    club.session.set_players(club.players)
    assert _wait(lambda: sum(len(s["players"]) for s in home.session.status()["lobby"]["sites"]) == 2)
    home.session.set_rules("x01", 3, X01_RULES)
    assert _wait(lambda: club.session.status()["lobby"]["rules"] == X01_RULES)       # the other site sees the rules
    home.session.start(3, ["anna", "carl"], "x01", X01_RULES)
    assert _wait(lambda: home.ctrl.game and club.ctrl.game)
    assert home.ctrl.game.match_id == club.ctrl.game.match_id
    assert home.ctrl.game.phase == "bull_off" and home.ctrl.game.current == "anna"

    def settle(seq):
        assert _wait(lambda: home.ctrl.game.turn_seq == seq and club.ctrl.game.turn_seq == seq)

    def bull_off(site, x, y):
        ctrl = sites[site].ctrl
        ctrl.on_board_state(1, [_dart(25, 1, x, y)])
        ctrl.on_board_state(0, [])

    bull_off("Home", 0.4, 0.0)            # anna is far from the bull
    settle(1)
    assert club.ctrl.game.current == "carl"
    bull_off("Club", 0.02, 0.0)           # carl is closer: he throws first
    settle(2)
    for s in sites.values():
        game = s.ctrl.game
        assert game.phase == "playing" and game.order == ["carl", "anna"] and game.current == "carl"

    ctrl = club.ctrl
    ctrl.on_board_state(1, [_dart(20, 2, 0.0, 0.6)])         # D20 checks out 40
    settle(3)
    assert _wait(lambda: home.session.status()["phase"] == "ended" and club.session.status()["phase"] == "ended")
    for s in sites.values():
        assert s.ctrl.game.state == "finished" and s.ctrl.game.winner == "carl"
    assert home.ctrl.game.state_hash() == club.ctrl.game.state_hash()
    # each site stores the player of the other site as a guest, name@site
    winner = lambda s: s.db._conn.execute("SELECT winner FROM matches WHERE match_id = ?", (s.ctrl.game.match_id,)).fetchone()[0]
    assert winner(home) == "carl@club" and winner(club) == "carl"
    turned = lambda s: [r[0] for r in s.db._conn.execute("SELECT player FROM turns ORDER BY id")]
    assert turned(home) == ["carl@club"] and turned(club) == ["carl"]
    # the screens find the average of a player of the other site under his plain name
    assert set(home.ctrl.tracker.computed_session_stats()) == set(club.ctrl.tracker.computed_session_stats()) == {"carl"}
    home.session.leave()
    club.session.leave()


def test_an_x01_turn_can_be_taken_back_and_corrected_at_the_site_that_threw_it(relay_url):
    rules = {**X01_RULES, "start": 100, "bull_off": False}
    home, club = _x01_site(["anna"]), _x01_site(["carl"])
    sites = {"Home": home, "Club": club}
    code = home.session.create(relay_url, "Home", "pw")
    club.session.join(relay_url, code, "Club", "pw")
    home.session.set_players(home.players)
    club.session.set_players(club.players)
    assert _wait(lambda: sum(len(s["players"]) for s in home.session.status()["lobby"]["sites"]) == 2)
    home.session.start(3, ["anna", "carl"], "x01", rules)
    assert _wait(lambda: home.ctrl.game and club.ctrl.game)
    assert home.ctrl.game.phase == "playing" and home.ctrl.game.order == ["anna", "carl"]

    def settle(seq):
        assert _wait(lambda: home.ctrl.game.turn_seq == seq and club.ctrl.game.turn_seq == seq)

    def turn(site, *darts):
        ctrl = sites[site].ctrl
        for n in range(1, len(darts) + 1):
            ctrl.on_board_state(n, list(darts[:n]))
        ctrl.on_board_state(0, [])

    def scores(s):
        return {p["name"]: p["remaining"] for p in s.ctrl.game.snapshot()["players"]}

    turn("Home", *_throws(20, 1, 3))                       # anna 60, 40 left
    settle(1)
    turn("Club", *_throws(1, 1, 3))                        # carl 3, 97 left
    settle(2)
    assert scores(home) == scores(club) == {"anna": 40, "carl": 97}

    club.session.undo()                                    # carl's site takes its turn back
    assert _wait(lambda: home.ctrl.game.turn_seq == 1 and club.ctrl.game.turn_seq == 1)
    assert scores(home) == scores(club) == {"anna": 40, "carl": 100}
    assert home.ctrl.game.current == club.ctrl.game.current == "carl"
    turn("Club", *_throws(5, 1, 3))                        # carl 15, 85 left
    settle(2)
    assert club.ctrl.game.correct_last_dart(2, "S20")      # the third dart was a 20, not a 5
    assert _wait(lambda: scores(home) == scores(club) == {"anna": 40, "carl": 70})
    settle(2)
    assert home.ctrl.game.state_hash() == club.ctrl.game.state_hash()

    turn("Home", _dart(20, 2, 0.0, 0.6))                   # anna checks out 40
    settle(3)
    assert _wait(lambda: home.session.status()["phase"] == "ended" and club.session.status()["phase"] == "ended")
    assert home.ctrl.game.winner == club.ctrl.game.winner == "anna"
    home.session.leave()
    club.session.leave()


def test_the_darts_of_a_turn_in_progress_reach_the_other_site_also_when_set_by_hand(relay_url):
    rules = {**X01_RULES, "start": 301, "bull_off": True}
    home, club = _x01_site(["anna"]), _x01_site(["carl"])
    shown = {"Home": [], "Club": []}
    for name, s in (("Home", home), ("Club", club)):
        s.ctrl.on_remote_darts = shown[name].append
    code = home.session.create(relay_url, "Home", "pw")
    club.session.join(relay_url, code, "Club", "pw")
    home.session.set_players(home.players)
    club.session.set_players(club.players)
    assert _wait(lambda: sum(len(s["players"]) for s in home.session.status()["lobby"]["sites"]) == 2)
    home.session.start(3, ["anna", "carl"], "x01", rules)
    assert _wait(lambda: home.ctrl.game and club.ctrl.game)

    # the bull-off: anna sets her dart by hand, carl's site sees it before anna's darts are pulled
    home.ctrl.game.correct_current_dart(0, "25")
    assert _wait(lambda: any(len(d) == 1 for d in shown["Club"])), shown
    home.ctrl.game.next_turn()
    assert _wait(lambda: club.ctrl.game.turn_seq == 1)
    club.ctrl.game.correct_current_dart(0, "D25")
    assert _wait(lambda: club.ctrl.game.turn_seq == 1 and any(len(d) == 1 for d in shown["Home"])), shown
    club.ctrl.game.next_turn()
    assert _wait(lambda: home.ctrl.game.phase == "playing" and club.ctrl.game.phase == "playing")

    # in the match the darts set by hand arrive one by one
    thrower = home if home.ctrl.game.current == "anna" else club
    other = "Club" if thrower is home else "Home"
    thrower.ctrl.game.correct_current_dart(0, "T20")
    thrower.ctrl.game.correct_current_dart(1, "S5")
    assert _wait(lambda: [len(d) for d in shown[other]][-2:] == [1, 2]), shown
    other_site = club if thrower is home else home
    assert _wait(lambda: other_site.ctrl.game.snapshot()["current_darts"] == [60, 5]), other_site.ctrl.game.snapshot()["current_darts"]
    home.session.leave()
    club.session.leave()


def test_when_the_host_ends_the_match_every_site_is_back_at_the_start_at_once(relay_url):
    home, club = _x01_site(["anna"]), _x01_site(["carl"])
    code = home.session.create(relay_url, "Home", "pw")
    club.session.join(relay_url, code, "Club", "pw")
    home.session.set_players(home.players)
    club.session.set_players(club.players)
    assert _wait(lambda: sum(len(s["players"]) for s in home.session.status()["lobby"]["sites"]) == 2)
    home.session.start(3, ["anna", "carl"], "x01", {**X01_RULES, "bull_off": False})
    assert _wait(lambda: home.ctrl.game and club.ctrl.game)
    home.session.leave()                                     # the host ends the match
    assert _wait(lambda: not club.session.active and club.ctrl.game is None)
    assert club.session.status()["message"] is None
