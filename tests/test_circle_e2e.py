"""The circle against the real relay: the Worker runs under `wrangler dev` (workerd, local D1 with the migrations applied, local R2,
the admin secrets as variables). Three sites register, the admin approves them and sets players and rules, a match of one site
travels to the sites in the rule of a player in it and is imported there."""

import hashlib
import json
import shutil
import socket
import subprocess
import time
from pathlib import Path

import pytest
import requests

from breakfast.locations import Locations
from breakfast.match_record import export_record, import_record
from breakfast.stats import StatsDB

RELAY = Path(__file__).resolve().parents[1] / "relay"
WRANGLER = RELAY / "node_modules" / ".bin" / "wrangler"
PASSWORD = "a long password from the password manager"
SALT = "ab" * 16
PASSWORD_HASH = f"sha256${SALT}${hashlib.sha256(f'{SALT}:{PASSWORD}'.encode()).hexdigest()}"

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
        [str(WRANGLER), "dev", "--port", str(port), "--ip", "127.0.0.1", "--persist-to", str(state),
         "--var", f"ADMIN_PASSWORD_HASH:{PASSWORD_HASH}", "--var", f"ADMIN_TOKEN_KEY:{'k' * 64}"],
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


def _site(tmp_path, name, relay_url):
    folder = tmp_path / name.replace(" ", "-").replace("'", "")
    folder.mkdir()
    loc = Locations(folder / "config.toml")
    loc.register(relay_url, name, "1234")
    db = StatsDB(str(folder / "stats.db"))
    return loc, db


def _call(loc, relay_url, method, path, body=None):
    base = relay_url.replace("ws://", "http://")
    raw = json.dumps(body, separators=(",", ":")) if body is not None else ""
    headers = loc.signer_for(relay_url)(method, path.split("?")[0], raw)
    headers["content-type"] = "application/json"
    return requests.request(method, base + path, data=raw.encode() if raw else None, headers=headers, timeout=20)


class Admin:
    def __init__(self, relay_url):
        self.base = relay_url.replace("ws://", "http://")
        self.token = None

    def login(self, password=PASSWORD):
        res = requests.post(self.base + "/admin/login", json={"password": password}, timeout=20)
        if res.status_code == 200:
            self.token = res.json()["token"]
        return res

    def __call__(self, method, path, body=None):
        return requests.request(method, self.base + path, json=body, headers={"authorization": f"Bearer {self.token}"}, timeout=20)


def _match(db, match_id, players, winner):
    db.open_match(match_id, "X01", 501)
    for i, player in enumerate(players, 1):
        db.insert_turn(match_id, player, 1, i, 501, 60, False, False, [("T20", 60, 441)])
    db.record_leg_win(match_id, 1, winner)
    db.set_winner(match_id, winner)
    db.close_match(match_id)


def test_a_match_travels_to_the_sites_in_the_rule_of_a_player_in_it(relay_url, tmp_path):
    ashitaka, ashitaka_db = _site(tmp_path, "Ashitaka's Board", relay_url)
    meierhof, meierhof_db = _site(tmp_path, "Meierhof", relay_url)
    crealine, crealine_db = _site(tmp_path, "Crealine", relay_url)
    sites = {"ashitaka": ashitaka, "meierhof": meierhof, "crealine": crealine}
    ids = {name: loc.status()["id"] for name, loc in sites.items()}

    admin = Admin(relay_url)
    assert admin.login("wrong password").status_code == 401
    assert admin.login().status_code == 200
    assert requests.options(admin.base + "/admin/sites", timeout=20).headers["access-control-allow-origin"] == "*"
    assert requests.get(admin.base + "/admin/sites", timeout=20).status_code == 401

    # the sites report themselves, the admin sees them and approves them
    for name, loc in sites.items():
        assert _call(loc, relay_url, "PUT", "/circle/state", {"version": "1.9.0", "players": ["ashi" if name == "ashitaka" else "peter"]}).json() == {"approved": False}
        assert _call(loc, relay_url, "GET", "/circle/config").status_code == 403
    listed = admin("GET", "/admin/sites").json()["sites"]
    assert sorted(s["name"] for s in listed) == ["Ashitaka's Board", "Crealine", "Meierhof"]
    assert all(not s["approved"] for s in listed)
    for site_id in ids.values():
        assert admin("POST", f"/admin/sites/{site_id}/approve", {}).json()["approved"] is True

    # circle players, mappings and rules: Ashi's matches go to his board and Meierhof, not to Crealine
    ashi = admin("POST", "/admin/players", {"name": "Ashi"}).json()["id"]
    peter = admin("POST", "/admin/players", {"name": "Peter"}).json()["id"]
    for site, local, player in (("ashitaka", "ashi", ashi), ("meierhof", "peter", peter), ("meierhof", "ashi", ashi)):
        assert admin("PUT", "/admin/mappings", {"location_id": ids[site], "local_name": local, "player_id": player}).status_code == 200
    assert admin("PUT", "/admin/rules", {"player_id": ashi, "location_ids": [ids["ashitaka"], ids["meierhof"]]}).status_code == 200
    assert admin("PUT", "/admin/rules", {"player_id": peter, "location_ids": [ids["meierhof"]]}).status_code == 200
    config = _call(meierhof, relay_url, "GET", "/circle/config").json()
    assert [p["name"] for p in config["circle_players"]] == ["Ashi", "Peter"]
    assert [m["local_name"] for m in config["mappings"]] == ["ashi", "peter"]

    # Meierhof plays a match of Peter and Ashi and sends its record
    _match(meierhof_db, "m-1", ["peter", "ashi"], "peter")
    origin = {"id": ids["meierhof"], "name": "Meierhof"}
    record = export_record(meierhof_db, "m-1", origin)
    put = _call(meierhof, relay_url, "PUT", "/circle/records/m-1/1",
                {"game_mode": "X01", "deleted": False, "participants": [{"name": "peter"}, {"name": "ashi"}], "record": record})
    assert put.status_code == 201, put.text

    # Ashitaka's Board gets it (Ashi's rule), Crealine does not, Meierhof does not get its own back
    listed = _call(ashitaka, relay_url, "GET", "/circle/records?since=0").json()
    assert [(r["match_id"], r["origin"]["name"]) for r in listed["records"]] == [("m-1", "Meierhof")]
    assert _call(crealine, relay_url, "GET", "/circle/records?since=0").json()["records"] == []
    assert _call(meierhof, relay_url, "GET", "/circle/records?since=0").json()["records"] == []
    fetched = _call(ashitaka, relay_url, "GET", "/circle/records/m-1").json()
    assert import_record(ashitaka_db, fetched["record"], mapping={"ashi": "ashi"}) == {"status": "imported", "match_id": "m-1", "revision": 1}
    assert {r[0] for r in ashitaka_db._conn.execute("SELECT player FROM turns")} == {"ashi", "peter@meierhof"}

    # the admin sees the state without the content
    sync = admin("GET", "/admin/sync").json()
    assert sync["totals"]["n"] == 1
    records = admin("GET", "/admin/records").json()["records"]
    assert sorted(records[0]["players"]) == ["Ashi", "Peter"] and records[0]["origin"]["name"] == "Meierhof"
    assert "turns" not in json.dumps(records)
    assert admin("GET", "/admin/reports").status_code == 200
