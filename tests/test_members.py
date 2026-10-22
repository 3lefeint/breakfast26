import base64
import json
from types import SimpleNamespace

import pytest

from breakfast.locations import LocationError, Locations
from breakfast.members import CODE_PREFIX, Members, make_member_code, read_member_code
from breakfast.stats import StatsDB

MAILBOX = "e" * 32


class Relay:
    """Answers like the relay for the routes of the members and keeps the requests."""

    def __init__(self):
        self.calls = []
        self.status = 200
        self.token = "t" * 32
        self.mailbox = MAILBOX

    def __call__(self, url, **kw):
        self.calls.append({"url": url, "data": kw.get("data"), "headers": kw.get("headers", {})})
        path = "/" + url.split("//", 1)[1].split("/", 1)[1]
        body = {"id": "a" * 32}
        if path.endswith("/members"):
            body = {"mailbox_id": self.mailbox, "token": self.token, "expires_at": 1_760_000_000_000 + 7 * 86_400_000}
        elif path.endswith("/invitations"):
            body = {"mailbox_id": MAILBOX, "token": "n" * 32, "expires_at": 1_760_000_000_000 + 7 * 86_400_000}
        elif path == "/mailbox-invitations/redeem":
            body = {"mailbox_id": MAILBOX, "device_id": "d" * 32, "up": False, "location": {"id": "a" * 32, "name": "Home"}}
        elif path.startswith("/mailboxes/"):
            body = {"ok": True}
        if self.status >= 400:
            body = {"error": "the relay refused"}
        return SimpleNamespace(status_code=self.status, json=lambda: body)

    def paths(self):
        return [(c["url"].split("//", 1)[1].split("/", 1)[1]) for c in self.calls]


@pytest.fixture
def relay():
    return Relay()


@pytest.fixture
def home(tmp_path, relay):
    """A location with a PIN and a player ana, and its members."""
    folder = tmp_path / "home"
    folder.mkdir()
    db = StatsDB(str(folder / "stats.db"))
    db.upsert_player("ana")
    db.upsert_player("ben")
    loc = Locations(folder / "config.toml", post=relay, get=relay, delete=relay, patch=relay)
    loc.register("wss://relay.example", "Home", "1234")
    relay.calls.clear()
    return SimpleNamespace(loc=loc, db=db, members=Members(loc, db, folder / "config.toml", post=relay), path=folder / "sharing.json")


@pytest.fixture
def member_installation(tmp_path, relay):
    """Another installation with a player anna: it joins locations as a member."""
    folder = tmp_path / "member"
    folder.mkdir()
    db = StatsDB(str(folder / "stats.db"))
    db.upsert_player("anna")
    loc = Locations(folder / "config.toml", post=relay, get=relay, delete=relay, patch=relay)
    return SimpleNamespace(db=db, members=Members(loc, db, folder / "config.toml", post=relay), path=folder / "sharing.json")


def test_an_invitation_code_carries_everything_the_member_needs():
    key = bytes(range(32))
    code = make_member_code("https://relay.example", MAILBOX, "t" * 32, key, {"id": "a" * 32, "name": "Home"}, "ana")
    assert code.startswith(CODE_PREFIX)
    assert read_member_code(code) == {"relay": "https://relay.example", "mailbox": MAILBOX, "token": "t" * 32, "key": key,
                                      "location": {"id": "a" * 32, "name": "Home"}, "player": "ana"}


@pytest.mark.parametrize("code", ["", "BF1-abc", "BFM1-", "BFM1-bm90IGpzb24", CODE_PREFIX + "e30", None])
def test_a_text_that_is_no_member_invitation_is_refused(code):
    with pytest.raises(LocationError, match="not a member invitation"):
        read_member_code(code)


def test_the_first_invitation_needs_the_confirmation_of_the_admin(home, relay):
    with pytest.raises(LocationError, match="confirm"):
        home.members.invite_member("ana", "1234")
    assert relay.calls == []
    made = home.members.invite_member("ana", "1234", confirm=True)
    assert made["mailbox_id"] == MAILBOX and made["code"].startswith(CODE_PREFIX)
    assert home.members.status()["consent"] is True
    relay.mailbox = "f" * 32
    second = home.members.invite_member("ben", "1234")                       # the confirmation counts once
    assert second["mailbox_id"] == "f" * 32


def test_inviting_a_member_asks_the_relay_signed_and_stores_member_and_key(home, relay):
    made = home.members.invite_member("Ana", "1234", confirm=True)
    call = relay.calls[0]
    assert call["url"] == f"https://relay.example/locations/{home.loc.status()['id']}/members"
    assert call["headers"]["x-location"] == home.loc.status()["id"] and call["headers"]["x-signature"]
    assert [(m["mailbox_id"], m["player"]) for m in home.members.members()] == [(MAILBOX, "ana")]
    invitation = read_member_code(made["code"])
    stored = json.loads(home.path.read_text())["mailboxes"][MAILBOX]
    assert len(invitation["key"]) == 32 and stored["key"]
    assert (home.path.stat().st_mode & 0o777) == 0o600
    assert invitation["player"] == "ana" and invitation["token"] == "t" * 32 and invitation["location"]["name"] == "Home"


def test_only_a_local_player_and_only_once_and_only_with_the_pin(home, relay):
    with pytest.raises(LocationError, match="player of this installation"):
        home.members.invite_member("nobody", "1234", confirm=True)
    with pytest.raises(LocationError, match="wrong PIN"):
        home.members.invite_member("ana", "0000", confirm=True)
    assert home.members.members() == [] and not home.path.exists()
    home.members.invite_member("ana", "1234", confirm=True)
    with pytest.raises(LocationError, match="member already"):
        home.members.invite_member("ana", "1234")
    guest = home.db.guest_name("carl", "club")
    with pytest.raises(LocationError, match="player of this installation"):
        home.members.invite_member(guest, "1234")


def test_a_refusal_of_the_relay_leaves_nothing_behind(home, relay):
    relay.status = 503
    with pytest.raises(LocationError, match="refused"):
        home.members.invite_member("ana", "1234", confirm=True)
    assert home.members.members() == [] and not home.path.exists()
    assert home.members.status()["consent"] is False


def test_a_lost_invitation_is_replaced_by_a_new_one_with_the_same_key(home, relay):
    first = home.members.invite_member("ana", "1234", confirm=True)
    again = home.members.reinvite_member(MAILBOX, "1234")
    assert relay.paths()[-1] == f"mailboxes/{MAILBOX}/invitations"
    assert read_member_code(again["code"])["key"] == read_member_code(first["code"])["key"]
    assert read_member_code(again["code"])["token"] == "n" * 32
    with pytest.raises(LocationError, match="unknown member"):
        home.members.reinvite_member("f" * 32, "1234")


def test_removing_a_member_deletes_his_mailbox_at_the_relay_first(home, relay):
    home.members.invite_member("ana", "1234", confirm=True)
    relay.status = 503
    with pytest.raises(LocationError):
        home.members.remove_member(MAILBOX, "1234")
    assert len(home.members.members()) == 1 and MAILBOX in json.loads(home.path.read_text())["mailboxes"]
    relay.status = 200
    home.members.remove_member(MAILBOX, "1234")
    assert relay.calls[-1]["url"] == f"https://relay.example/mailboxes/{MAILBOX}"
    assert home.members.members() == [] and json.loads(home.path.read_text())["mailboxes"] == {}
    with pytest.raises(LocationError, match="wrong PIN"):
        home.members.invite_member("ben", "0000")


def test_a_member_installation_previews_and_joins_with_a_key_of_its_own(home, member_installation, relay):
    code = home.members.invite_member("ana", "1234", confirm=True)["code"]
    relay.calls.clear()
    m = member_installation.members
    assert m.preview(code) == {"location": {"id": home.loc.status()["id"], "name": "Home"}, "member": "ana",
                               "suggested": None, "known": False}
    assert relay.calls == []                                                 # a preview asks nobody
    joined = m.join(code, "Anna", "both")
    assert joined == {"mailbox_id": MAILBOX, "location": {"id": "a" * 32, "name": "Home"}, "direction": "both", "player": "anna"}
    call = relay.calls[0]
    assert call["url"] == "https://relay.example/mailbox-invitations/redeem"
    body = json.loads(call["data"])
    assert body["token"] == "t" * 32 and len(body["public_key"]) == 43
    assert "x-device" not in call["headers"] and "x-location" not in call["headers"]
    assert [(s["mailbox_id"], s["player"], s["direction"], s["location_name"]) for s in m.subscriptions()] == [(MAILBOX, "anna", "both", "Home")]
    secrets_ = json.loads(member_installation.path.read_text())["devices"][MAILBOX]
    assert read_member_code(code)["key"] == base64.urlsafe_b64decode(secrets_["key"] + "=") and secrets_["device_key"]
    assert (member_installation.path.stat().st_mode & 0o777) == 0o600


def test_the_preview_suggests_the_player_of_the_same_name_and_the_user_confirms(home, member_installation):
    member_installation.db.upsert_player("ana")
    code = home.members.invite_member("ana", "1234", confirm=True)["code"]
    assert member_installation.members.preview(code)["suggested"] == "ana"
    joined = member_installation.members.join(code, "anna", "pull")             # another player is picked
    assert joined["player"] == "anna"


def test_joining_creates_the_player_when_there_is_none_of_that_name(home, member_installation):
    code = home.members.invite_member("ana", "1234", confirm=True)["code"]
    member_installation.members.join(code, "Neuer", "pull")
    assert "neuer" in member_installation.db.list_players()


def test_joining_refuses_a_bad_direction_a_second_time_and_a_refused_invitation(home, member_installation, relay):
    code = home.members.invite_member("ana", "1234", confirm=True)["code"]
    m = member_installation.members
    with pytest.raises(LocationError, match="pull, push or both"):
        m.join(code, "anna", "sideways")
    with pytest.raises(LocationError, match="choose the player"):
        m.join(code, "  ", "pull")
    relay.status = 404
    with pytest.raises(LocationError, match="refused"):
        m.join(code, "anna", "pull")
    assert m.subscriptions() == [] and not member_installation.path.exists()
    relay.status = 200
    m.join(code, "anna", "pull")
    assert m.preview(code)["known"] is True
    with pytest.raises(LocationError, match="already"):
        m.join(code, "anna", "pull")


def test_leaving_forgets_the_membership_and_its_keys_here(home, member_installation):
    code = home.members.invite_member("ana", "1234", confirm=True)["code"]
    m = member_installation.members
    m.join(code, "anna", "pull")
    m.leave(MAILBOX)
    assert m.subscriptions() == [] and json.loads(member_installation.path.read_text())["devices"] == {}
    with pytest.raises(LocationError, match="unknown membership"):
        m.leave(MAILBOX)
    with pytest.raises(LocationError, match="unknown membership"):
        m.leave("not an id")


# ── the routes ────────────────────────────────────────────────────────────────

from starlette.testclient import TestClient

from breakfast.stats import StatsTracker
from breakfast.web import server


@pytest.fixture
def api(home, member_installation, relay):
    """The web server with this location as the location and a second installation joining through its own Members."""
    server.wire(None, None, stats_tracker=StatsTracker(home.db))
    server._locations, server._members = home.loc, home.members
    yield TestClient(server.app), home, member_installation
    server.wire(None, None)


def test_the_status_lists_members_and_memberships(api):
    http, home, _ = api
    assert http.get("/api/sharing").json() == {"available": True, "consent": False, "members": [], "subscriptions": []}
    http.post("/api/sharing/members", json={"player": "ana", "pin": "1234", "confirm": True})
    body = http.get("/api/sharing").json()
    assert body["consent"] is True and [m["player"] for m in body["members"]] == ["ana"]


def test_the_routes_invite_reinvite_and_remove(api):
    http, home, _ = api
    refused = http.post("/api/sharing/members", json={"player": "ana", "pin": "1234"}).json()
    assert "confirm" in refused["error"]
    made = http.post("/api/sharing/members", json={"player": "Ana", "pin": "1234", "confirm": True}).json()
    assert made["code"].startswith(CODE_PREFIX) and made["mailbox_id"] == MAILBOX
    assert http.post("/api/sharing/members", json={"player": "ben", "pin": "0000"}).json() == {"error": "wrong PIN"}
    again = http.post("/api/sharing/members/invitation", json={"pin": "1234", "mailbox_id": MAILBOX}).json()
    assert again["code"].startswith(CODE_PREFIX)
    assert http.post("/api/sharing/members/remove", json={"pin": "1234", "mailbox_id": MAILBOX}).json() == {"ok": True}
    assert http.get("/api/sharing").json()["members"] == []
    assert "unknown" in http.post("/api/sharing/members/remove", json={"pin": "1234", "mailbox_id": MAILBOX}).json()["error"]


def test_the_routes_preview_join_and_leave(api):
    http, home, member = api
    code = http.post("/api/sharing/members", json={"player": "ana", "pin": "1234", "confirm": True}).json()["code"]
    server._members = member.members                                      # now this installation is the member
    server._locations = member.members._locations
    preview = http.post("/api/sharing/preview", json={"code": code}).json()
    assert preview["member"] == "ana" and preview["location"]["name"] == "Home" and preview["known"] is False
    assert "error" in http.post("/api/sharing/preview", json={"code": "nonsense"}).json()
    joined = http.post("/api/sharing/join", json={"code": code, "player": "Anna", "direction": "pull"}).json()
    assert joined["player"] == "anna" and joined["direction"] == "pull"
    assert [s["player"] for s in http.get("/api/sharing").json()["subscriptions"]] == ["anna"]
    assert http.post("/api/sharing/leave", json={"mailbox_id": MAILBOX}).json() == {"ok": True}
    assert http.get("/api/sharing").json()["subscriptions"] == []


def test_the_routes_say_when_there_is_nothing(tmp_path):
    server.wire(None, None)
    try:
        assert TestClient(server.app).get("/api/sharing").json() == {"available": False}
        assert TestClient(server.app).post("/api/sharing/preview", json={"code": "x"}).json() == {"error": "members are not available"}
    finally:
        server.wire(None, None)
