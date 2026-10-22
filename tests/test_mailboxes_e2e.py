"""The mailboxes against the real relay: the Worker runs under `wrangler dev` (workerd, local D1 with the migrations
applied, local R2); a location signs with its identity, a member's device with a key of its own."""

import base64
import hashlib
import json
import shutil
import socket
import subprocess
import time
from pathlib import Path

import pytest
import requests
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from breakfast.locations import Locations

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


def _b64(data):
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


class Device:
    """A member's device: an Ed25519 key of its own."""

    def __init__(self, base):
        self.base, self.key, self.id = base, Ed25519PrivateKey.generate(), None
        self.public = _b64(self.key.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw))

    def request(self, method, path, body=None):
        raw = json.dumps(body, separators=(",", ":")) if body is not None else ""
        timestamp = str(int(time.time()))
        message = f"{method}\n{path.split('?')[0]}\n{timestamp}\n{hashlib.sha256(raw.encode()).hexdigest()}"
        headers = {"x-timestamp": timestamp, "x-signature": _b64(self.key.sign(message.encode())), "content-type": "application/json"}
        if self.id:
            headers["x-device"] = self.id
        return requests.request(method, self.base + path, data=raw.encode() if raw else None, headers=headers, timeout=20)


def _location_call(loc, relay_url, method, path, body=None):
    base = relay_url.replace("ws://", "http://")
    raw = json.dumps(body, separators=(",", ":")) if body is not None else ""
    headers = loc.signer_for(relay_url)(method, path.split("?")[0], raw)      # the signature covers the path, not the query
    headers["content-type"] = "application/json"
    return requests.request(method, base + path, data=raw.encode() if raw else None, headers=headers, timeout=20)


def test_a_member_and_a_location_exchange_records_through_a_mailbox(relay_url, tmp_path):
    base = relay_url.replace("ws://", "http://")
    folder = tmp_path / "home"
    folder.mkdir()
    home = Locations(folder / "config.toml")
    home.register(relay_url, "Home", "1234")
    location_id = home.status()["id"]

    made = _location_call(home, relay_url, "POST", f"/locations/{location_id}/members", {})
    assert made.status_code == 201, made.text
    mailbox, token = made.json()["mailbox_id"], made.json()["token"]

    device = Device(base)
    redeemed = device.request("POST", "/mailbox-invitations/redeem", {"token": token, "public_key": device.public})
    assert redeemed.status_code == 201, redeemed.text
    device.id = redeemed.json()["device_id"]
    assert redeemed.json()["location"] == {"id": location_id, "name": "Home"}
    assert device.request("POST", "/mailbox-invitations/redeem", {"token": token, "public_key": device.public}).status_code == 404

    record = {"envelope_version": 1, "game_mode": "X01", "deleted": False, "ciphertext": _b64(b"sealed match")}
    put = _location_call(home, relay_url, "PUT", f"/mailboxes/{mailbox}/down/m-1/1", record)
    assert put.status_code == 201, put.text
    listed = device.request("GET", f"/mailboxes/{mailbox}/down?since=0")
    assert [(r["match_id"], r["revision"]) for r in listed.json()["records"]] == [("m-1", 1)]
    fetched = device.request("GET", f"/mailboxes/{mailbox}/down/m-1/1").json()
    assert base64.urlsafe_b64decode(fetched["ciphertext"] + "==") == b"sealed match"

    assert _location_call(home, relay_url, "PATCH", f"/mailboxes/{mailbox}", {"up": True}).json()["up"] is True
    back = device.request("PUT", f"/mailboxes/{mailbox}/up/m-2/1", {**record, "game_mode": "Elimination", "ciphertext": _b64(b"from the member")})
    assert back.status_code == 201, back.text
    up = _location_call(home, relay_url, "GET", f"/mailboxes/{mailbox}/up?since=0").json()
    assert [r["match_id"] for r in up["records"]] == ["m-2"]

    assert _location_call(home, relay_url, "DELETE", f"/mailboxes/{mailbox}").json() == {"ok": True}
    assert device.request("GET", f"/mailboxes/{mailbox}/down").status_code == 401


def test_members_are_invited_join_and_are_removed_through_the_real_relay(relay_url, tmp_path):
    from breakfast.members import Members
    from breakfast.stats import StatsDB

    def installation(name, players):
        folder = tmp_path / name
        folder.mkdir()
        db = StatsDB(str(folder / "stats.db"))
        for player in players:
            db.upsert_player(player)
        return folder, db, Locations(folder / "config.toml")

    home_folder, home_db, home = installation("home-members", ["ana"])
    home.register(relay_url, "Home", "1234")
    admin = Members(home, home_db, home_folder / "config.toml")
    made = admin.invite_member("ana", "1234", confirm=True)

    member_folder, member_db, member_loc = installation("member", ["anna"])
    member = Members(member_loc, member_db, member_folder / "config.toml")
    assert member.preview(made["code"])["location"]["name"] == "Home"
    joined = member.join(made["code"], "anna", "both")
    assert joined["mailbox_id"] == made["mailbox_id"] and joined["location"]["name"] == "Home"
    assert [s["player"] for s in member.subscriptions()] == ["anna"]

    from breakfast.locations import LocationError
    second_folder, second_db, second_loc = installation("second", [])
    with pytest.raises(LocationError, match="invalid or expired"):
        Members(second_loc, second_db, second_folder / "config.toml").join(made["code"], "ben", "pull")   # the token was used

    again = admin.reinvite_member(made["mailbox_id"], "1234")
    assert again["code"] != made["code"]
    assert _location_call(home, relay_url, "GET", f"/mailboxes/{made['mailbox_id']}/up").json()["records"] == []     # nothing sent yet
    admin.remove_member(made["mailbox_id"], "1234")
    assert admin.members() == []
    assert _location_call(home, relay_url, "GET", f"/mailboxes/{made['mailbox_id']}/up").status_code == 404     # the mailbox is gone
