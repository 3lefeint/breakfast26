"""Two locations against the real relay: the Worker runs under `wrangler dev` (workerd, local D1 with
the migrations applied); the locations are two `Locations` with their own identity files."""

import shutil
import socket
import subprocess
import time
from pathlib import Path

import pytest
import requests

from breakfast.locations import LocationError, Locations

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


def _site(tmp_path, name, relay_url, pin="1234", now=time.time):
    folder = tmp_path / name
    folder.mkdir()
    loc = Locations(folder / "config.toml", now=now)
    loc.register(relay_url, name, pin)
    return loc


def test_two_locations_link_and_unlink(relay_url, tmp_path):
    home = _site(tmp_path, "Home", relay_url)
    club = _site(tmp_path, "Club", relay_url)
    assert home.links() == [] and club.links() == []

    code = home.invite("1234")
    link = club.join(code, "1234")
    assert link["peer"] == {"id": home.status()["id"], "name": "Home"}

    (home_link,) = home.links()
    (club_link,) = club.links()
    assert home_link["link_id"] == club_link["link_id"] == link["link_id"]
    assert home_link["peer"]["name"] == "Club" and club_link["peer"]["name"] == "Home"

    with pytest.raises(LocationError, match="invalid or expired"):
        club.join(code, "1234")                      # the invitation is single use

    club.unlink(link["link_id"], "1234")
    assert home.links() == [] and club.links() == []


def test_an_own_invitation_and_a_stranger_are_refused(relay_url, tmp_path):
    home = _site(tmp_path, "Home", relay_url)
    third = _site(tmp_path, "Third", relay_url)
    with pytest.raises(LocationError, match="own invitation"):
        home.join(home.invite("1234"), "1234")
    link = third.join(home.invite("1234"), "1234")
    stranger = _site(tmp_path, "Stranger", relay_url)
    with pytest.raises(LocationError, match="unknown link"):
        stranger.unlink(link["link_id"], "1234")     # not a side of that link
    assert len(home.links()) == 1


def test_a_stale_or_forged_request_is_refused(relay_url, tmp_path):
    offset = {"s": 0}
    late = _site(tmp_path, "Late", relay_url, now=lambda: time.time() - offset["s"])
    offset["s"] = 3600                               # the clock of this site runs an hour behind
    with pytest.raises(LocationError, match="not signed correctly"):
        late.invite("1234")                          # timestamp an hour old
    home = _site(tmp_path, "Home", relay_url)
    res = requests.post(f"http://{relay_url[5:]}/locations/{home.status()['id']}/invitations", data=b"{}",
                        headers={"x-location": home.status()["id"], "x-timestamp": str(int(time.time())), "x-signature": "A" * 86})
    assert res.status_code == 401
    other = _site(tmp_path, "Other", relay_url)
    res = requests.get(f"http://{relay_url[5:]}/locations/{home.status()['id']}/links", headers={"x-location": other.status()["id"], "x-timestamp": str(int(time.time())), "x-signature": "A" * 86})
    assert res.status_code == 401


def test_rename_and_unregister(relay_url, tmp_path):
    home = _site(tmp_path, "Home", relay_url)
    club = _site(tmp_path, "Club", relay_url)
    link = club.join(home.invite("1234"), "1234")
    home.rename("Garage", "1234")
    assert club.links()[0]["peer"]["name"] == "Garage"
    home.unregister("1234")
    assert club.links() == []                         # the links went with the location
    assert not home.status()["registered"]
    with pytest.raises(LocationError, match="unknown link"):
        club.unlink(link["link_id"], "1234")          # nothing left of that link
    home.register(relay_url, "Home2", "4321")
    assert home.status()["name"] == "Home2"
