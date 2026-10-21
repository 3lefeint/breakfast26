"""Linked locations against the real relay (`wrangler dev`, local D1 with the migrations applied): a match is
announced to the linked location, which lists it and joins with a ticket instead of the password."""

import shutil
import socket
import subprocess
import time
from pathlib import Path
from types import SimpleNamespace

import pytest
import requests

from breakfast.elimination import EliminationController
from breakfast.locations import Locations, LocationError
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
    subprocess.run([str(WRANGLER), "d1", "migrations", "apply", "breakfast-telemetry", "--local", "--persist-to", str(state)],
                   cwd=RELAY, check=True, capture_output=True)
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


def _wait(cond, timeout=15):
    end = time.time() + timeout
    while time.time() < end:
        if cond():
            return True
        time.sleep(0.05)
    return False


def _location(tmp_path, name, relay_url):
    folder = tmp_path / name
    folder.mkdir()
    loc = Locations(folder / "config.toml")
    loc.register(relay_url, name, "1234")
    return loc


def _session():
    ctrl = EliminationController(NullMqttPublisher(), "autodarts", stats_db=StatsDB(":memory:"))
    return OnlineSession(ctrl)


def _linked(tmp_path, relay_url):
    home = _location(tmp_path, "Home", relay_url)
    club = _location(tmp_path, "Club", relay_url)
    club.join(home.invite("1234"), "1234")
    return home, club


def test_a_linked_location_lists_the_match_and_joins_without_the_password(relay_url, tmp_path):
    home, club = _linked(tmp_path, relay_url)
    host, guest = _session(), _session()
    try:
        code = host.create(relay_url, "Home", "", home.signer_for(relay_url))
        (match,) = club.open_matches()
        assert match["code"] == code and match["location"]["name"] == "Home" and match["site"] == "Home"
        assert home.open_matches() == []                       # nobody else is linked to it

        guest.join(relay_url, code, "Club", ticket=club.join_ticket(code))
        assert _wait(lambda: len(host.status()["lobby"]["sites"]) == 2)
        assert [s["ready"] for s in host.status()["lobby"]["sites"]] == [True, False]

        guest.set_players(["carl"])
        guest.set_ready(True)
        assert _wait(lambda: [s["ready"] for s in host.status()["lobby"]["sites"]] == [True, True])
        guest.set_players(["carl", "dora"])                    # a change takes the ready back
        assert _wait(lambda: [s["ready"] for s in host.status()["lobby"]["sites"]] == [True, False])
    finally:
        host.leave(); guest.leave()


def test_the_list_and_a_ticket_only_serve_linked_locations(relay_url, tmp_path):
    home, club = _linked(tmp_path, relay_url)
    stranger = _location(tmp_path, "Stranger", relay_url)
    host, other = _session(), _session()
    try:
        code = host.create(relay_url, "Home", "", home.signer_for(relay_url))
        assert stranger.open_matches() == []
        with pytest.raises(LocationError, match="not open for you"):
            stranger.join_ticket(code)
        with pytest.raises(RelayError, match="wrong password"):
            other.join(relay_url, code, "Stranger", "guess")   # the password of a linked-only match is random
        ticket = club.join_ticket(code)
        guest = _session()
        guest.join(relay_url, code, "Club", ticket=ticket)
        with pytest.raises(RelayError, match="ticket"):
            other.join(relay_url, code, "Other", ticket=ticket)  # a ticket works once
        guest.leave()
    finally:
        host.leave(); other.leave()


def test_a_name_that_is_taken_is_reported_and_a_started_match_is_not_listed(relay_url, tmp_path):
    home, club = _linked(tmp_path, relay_url)
    host, guest = _session(), _session()
    try:
        code = host.create(relay_url, "Home", "", home.signer_for(relay_url))
        with pytest.raises(RelayError, match="already taken"):
            guest.join(relay_url, code, "Home", ticket=club.join_ticket(code))
        guest.join(relay_url, code, "Club", ticket=club.join_ticket(code))   # the ticket was not used up
        host.set_players(["anna"])
        guest.set_players(["carl"])
        assert _wait(lambda: host.status()["lobby"]["sites"] and len(host.status()["lobby"]["sites"]) == 2)
        host.start(3, ["anna", "carl"])
        assert _wait(lambda: host.status()["phase"] == "playing")
        assert club.open_matches() == []
    finally:
        host.leave(); guest.leave()
