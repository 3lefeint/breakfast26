"""The voice chat against the real relay (`wrangler dev`): the page, the voice ticket of a site and the signaling room
(who is in it, offers and candidates passed on). The audio itself is WebRTC between browsers and is not tested here."""

import json
import shutil
import socket
import subprocess
import time
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import pytest
import requests
import websocket

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
def relay(tmp_path_factory):
    port = _free_port()
    state = tmp_path_factory.mktemp("wrangler-state")
    proc = subprocess.Popen(
        [str(WRANGLER), "dev", "--port", str(port), "--ip", "127.0.0.1", "--persist-to", str(state)],
        cwd=RELAY, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    url = f"127.0.0.1:{port}"
    try:
        for _ in range(120):
            try:
                if requests.get(f"http://{url}/", timeout=1).status_code == 200:
                    break
            except requests.RequestException:
                pass
            time.sleep(0.5)
        else:
            pytest.fail("wrangler dev did not come up")
        yield url
    finally:
        proc.terminate()
        try:
            proc.wait(10)
        except subprocess.TimeoutExpired:
            proc.kill()


def _session():
    ctrl = EliminationController(NullMqttPublisher(), "autodarts", stats_db=StatsDB(":memory:"))
    return OnlineSession(ctrl)


@pytest.fixture
def match(relay):
    host, guest = _session(), _session()
    code = host.create(f"ws://{relay}", "Home", "pw")
    guest.join(f"ws://{relay}", code, "Club", "pw")
    yield SimpleNamespace(relay=relay, code=code, host=host, guest=guest)
    host.leave(); guest.leave()


class SimpleNamespace:
    def __init__(self, **kw):
        self.__dict__.update(kw)


def _ticket(session):
    fragment = parse_qs(urlparse(session.voice_url("en")).fragment)
    return fragment["ticket"][0]


def _room(relay, code):
    ws = websocket.create_connection(f"ws://{relay}/voice/{code}", timeout=5)
    return ws


def _recv(ws):
    return json.loads(ws.recv())


def _join(relay, code, site, ticket):
    ws = _room(relay, code)
    ws.send(json.dumps({"type": "join", "site": site, "ticket": ticket}))
    return ws, _recv(ws)


def test_the_page_is_served_with_a_strict_policy(relay):
    page = requests.get(f"http://{relay}/voice")
    assert page.status_code == 200 and "text/html" in page.headers["content-type"]
    assert "script-src 'self'" in page.headers["content-security-policy"] and "<script src=\"/voice.js\">" in page.text
    script = requests.get(f"http://{relay}/voice.js")
    assert script.status_code == 200 and "javascript" in script.headers["content-type"] and "getUserMedia" in script.text


def test_the_ticket_needs_the_token_of_a_site_of_the_match(match):
    url = match.host.voice_url("de")
    fragment = parse_qs(urlparse(url).fragment)
    assert url.startswith(f"http://{match.relay}/voice#") and fragment["code"] == [match.code] and fragment["site"] == ["Home"] and fragment["lang"] == ["de"]
    res = requests.post(f"http://{match.relay}/api/matches/{match.code}/voice-ticket", json={"site": "Home", "token": "wrong"})
    assert res.status_code == 401
    res = requests.post(f"http://{match.relay}/api/matches/{match.code}/voice-ticket", json={"site": "Stranger", "token": "x"})
    assert res.status_code == 401


def test_two_sites_meet_in_the_room_and_pass_signals_on(match):
    a, joined_a = _join(match.relay, match.code, "Home", _ticket(match.host))
    try:
        assert joined_a["type"] == "joined" and joined_a["peers"] == [] and joined_a["ice"][0]["urls"] == ["stun:stun.cloudflare.com:3478"]
        b, joined_b = _join(match.relay, match.code, "Club", _ticket(match.guest))
        try:
            assert [p["site"] for p in joined_b["peers"]] == ["Home"] and joined_b["peers"][0]["peer"] == joined_a["peer"]
            assert _recv(a) == {"type": "peer-joined", "peer": joined_b["peer"], "site": "Club"}

            b.send(json.dumps({"type": "signal", "to": joined_a["peer"], "data": {"description": {"type": "offer", "sdp": "v=0"}}}))
            assert _recv(a) == {"type": "signal", "from": joined_b["peer"], "data": {"description": {"type": "offer", "sdp": "v=0"}}}
            a.send(json.dumps({"type": "signal", "to": joined_b["peer"], "data": {"candidate": {"candidate": "candidate:1"}}}))
            assert _recv(b)["data"] == {"candidate": {"candidate": "candidate:1"}}

            b.send(json.dumps({"type": "mute", "muted": True}))
            assert _recv(a) == {"type": "mute", "peer": joined_b["peer"], "muted": True}
            c, joined_c = _join(match.relay, match.code, "Home", _ticket(match.host))     # the host again, from a second tab
            try:
                assert [p["site"] for p in joined_c["peers"]] == ["Club"] and joined_c["peers"][0]["muted"] is True
                assert _recv(a)["type"] == "error"                                         # the first tab is replaced
            finally:
                c.close()
        finally:
            b.close()
    finally:
        a.close()


def test_leaving_is_announced_and_the_room_refuses_strangers_and_wrong_tickets(match):
    a, joined_a = _join(match.relay, match.code, "Home", _ticket(match.host))
    try:
        b, joined_b = _join(match.relay, match.code, "Club", _ticket(match.guest))
        _recv(a)                                                                           # peer-joined
        b.close()
        assert _recv(a) == {"type": "peer-left", "peer": joined_b["peer"]}

        refused, answer = _join(match.relay, match.code, "Club", "f" * 32)
        assert answer["type"] == "error" and answer["code"] == 4401
        refused.close()
        other, answer = _join(match.relay, match.code, "Home", _ticket(match.guest))        # the ticket of another site
        assert answer["type"] == "error" and answer["code"] == 4401
        other.close()
        first = _room(match.relay, match.code)
        first.send(json.dumps({"type": "signal", "to": "0" * 16, "data": {"candidate": {}}}))   # before joining
        assert _recv(first)["type"] == "error"
        first.close()
    finally:
        a.close()


def test_no_ticket_after_the_site_left_the_match(match):
    ticket = _ticket(match.host)
    match.host.leave()
    ws, answer = _join(match.relay, match.code, "Home", ticket)
    assert answer["type"] == "error" and answer["code"] == 4401
    ws.close()
    with pytest.raises(RelayError, match="no online match"):
        match.host.voice_url()
