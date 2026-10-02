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
    for s in sites.values():
        assert s.ctrl.game.state == "finished" and s.ctrl.game.winner == "ben"
        result = s.session.status()["result"]
        assert result["reason"] == "finished"
        assert [(p["player"], p["placement"]) for p in result["placements"]] == [("ben", 1), ("anna", 2), ("carl", 3)]
        rows = s.db._conn.execute("SELECT player, placement FROM elimination_results ORDER BY placement").fetchall()
        assert [(r["player"], r["placement"]) for r in rows] == [("ben", 1), ("anna", 2), ("carl", 3)]
        turns = s.db._conn.execute("SELECT player FROM elimination_turns ORDER BY id").fetchall()
        assert [t["player"] for t in turns] == ["anna", "carl", "ben", "anna"]
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
