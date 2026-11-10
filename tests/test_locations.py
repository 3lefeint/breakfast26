import base64
import hashlib
import json
from types import SimpleNamespace

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

from breakfast import locations
from breakfast.locations import LocationError, Locations, make_code, read_code


def _unb64(text):
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


class FakeRelay:
    """Answers like the relay and keeps the requests it got."""

    def __init__(self):
        self.calls = []
        self.status = 200
        self.answers = {}

    def __call__(self, url, **kw):
        self.calls.append({"url": url, **kw})
        path = "/" + url.split("//", 1)[1].split("/", 1)[1]
        status = self.status
        body = self.answers.get(path, {"id": "a" * 32, "token": "t" * 32, "link_id": "b" * 32,
                                       "peer": {"id": "c" * 32, "name": "Club"}, "links": []})
        return SimpleNamespace(status_code=status, json=lambda: body)


@pytest.fixture
def clock():
    state = {"t": 1_760_000_000.0}
    return state


@pytest.fixture
def relay():
    return FakeRelay()


@pytest.fixture
def loc(tmp_path, relay, clock):
    return Locations(tmp_path / "config.toml", post=relay, get=relay, delete=relay, patch=relay, now=lambda: clock["t"])


def test_register_signs_with_the_key_it_sends_and_stores_the_identity(loc, relay):
    status = loc.register("wss://relay.example", "Home", "1234")
    assert status["registered"] and status["name"] == "Home" and status["relay"] == "https://relay.example" and status["pin_set"]
    call = relay.calls[0]
    assert call["url"] == "https://relay.example/locations"
    body = json.loads(call["data"])
    message = f"POST\n/locations\n{call['headers']['x-timestamp']}\n{hashlib.sha256(call['data']).hexdigest()}".encode()
    Ed25519PublicKey.from_public_bytes(_unb64(body["public_key"])).verify(_unb64(call["headers"]["x-signature"]), message)
    assert (loc.path.stat().st_mode & 0o777) == 0o600


def test_register_refuses_twice_a_bad_name_a_bad_pin_and_no_relay(loc):
    with pytest.raises(LocationError, match="relay address"):
        loc.register("", "Home", "1234")
    with pytest.raises(LocationError, match="name"):
        loc.register("wss://r.example", "  ", "1234")
    with pytest.raises(LocationError, match="PIN"):
        loc.register("wss://r.example", "Home", "12")
    with pytest.raises(LocationError, match="PIN"):
        loc.register("wss://r.example", "Home", "12ab")
    assert not loc.status()["registered"]
    loc.register("wss://r.example", "Home", "1234")
    with pytest.raises(LocationError, match="already"):
        loc.register("wss://r.example", "Home", "1234")


def test_a_failed_register_leaves_nothing_behind(loc, relay):
    relay.status = 503
    relay.answers = {"/locations": {"error": "locations are not set up here"}}
    with pytest.raises(LocationError, match="not set up"):
        loc.register("wss://r.example", "Home", "1234")
    assert not loc.path.exists()


def test_signed_requests_carry_a_valid_signature(loc, relay):
    loc.register("wss://r.example", "Home", "1234")
    public = json.loads(relay.calls[0]["data"])["public_key"]
    code = loc.invite("1234")
    call = relay.calls[1]
    assert call["url"] == f"https://r.example/locations/{'a' * 32}/invitations"
    h = call["headers"]
    assert h["x-location"] == "a" * 32
    message = f"POST\n/locations/{'a' * 32}/invitations\n{h['x-timestamp']}\n{hashlib.sha256(call['data']).hexdigest()}".encode()
    Ed25519PublicKey.from_public_bytes(_unb64(public)).verify(_unb64(h["x-signature"]), message)
    assert read_code(code) == ("https://r.example", "t" * 32)


def test_the_qr_code_holds_the_invitation_text_and_scales_with_its_box(loc, relay):
    import segno
    loc.register("wss://r.example", "Home", "1234")
    code = loc.invite("1234")
    svg = locations.qr_svg(code)
    assert svg.startswith("<svg") and "viewBox" in svg and " width=" not in svg
    assert svg == segno.make(code, error="m").svg_inline(border=2, omitsize=True, dark="#000", light="#fff")
    assert svg != locations.qr_svg(make_code("https://r.example", "u" * 32))


def test_links_keep_the_source_the_relay_reports(loc, relay):
    loc.register("wss://r.example", "Home", "1234")
    link = {"link_id": "b" * 32, "kind": "play", "source": "admin", "peer": {"id": "c" * 32, "name": "Club"}}
    relay.answers = {f"/locations/{'a' * 32}/links": {"links": [link]}}
    assert loc.links() == [link]


def test_forget_deletes_the_identity_without_a_call_to_the_relay(loc, relay):
    loc.register("wss://r.example", "Home", "1234")
    calls = len(relay.calls)
    loc.forget()
    assert not loc.path.exists() and not loc.status()["registered"]
    assert len(relay.calls) == calls
    loc.forget()                                                     # nothing to forget is no error


def test_an_error_of_the_relay_carries_its_code(loc, relay):
    loc.register("wss://r.example", "Home", "1234")
    relay.status = 401
    relay.answers = {f"/locations/{'a' * 32}/links": {"error": "unknown location", "code": "unknown_location"}}
    with pytest.raises(LocationError) as caught:
        loc.links()
    assert (caught.value.status, caught.value.code) == (401, "unknown_location")


def test_join_checks_the_relay_of_the_code(loc, relay):
    loc.register("wss://r.example", "Home", "1234")
    with pytest.raises(LocationError, match="another relay"):
        loc.join(make_code("https://other.example", "t" * 32), "1234")
    link = loc.join(make_code("https://r.example", "t" * 32), "1234")
    assert link == {"link_id": "b" * 32, "peer": {"id": "c" * 32, "name": "Club"}}
    assert relay.calls[-1]["url"] == "https://r.example/invitations/redeem"
    assert json.loads(relay.calls[-1]["data"]) == {"token": "t" * 32}


@pytest.mark.parametrize("code", ["", "hello", "BF1-", "BF1-!!!", "BF1-" + base64.urlsafe_b64encode(b'{"r":1,"t":2}').decode()])
def test_a_bad_code_is_refused(code):
    with pytest.raises(LocationError, match="invitation"):
        read_code(code)


def test_relay_errors_reach_the_caller(loc, relay):
    loc.register("wss://r.example", "Home", "1234")
    relay.status = 404
    relay.answers = {"/invitations/redeem": {"error": "invalid or expired invitation"}}
    with pytest.raises(LocationError, match="expired"):
        loc.join(make_code("https://r.example", "t" * 32), "1234")


def test_unlink_refuses_an_id_that_is_not_a_link_id(loc, relay):
    loc.register("wss://r.example", "Home", "1234")
    for bad in ("../x", "", "A" * 32, None):
        with pytest.raises(LocationError, match="unknown link"):
            loc.unlink(bad, "1234")
    loc.unlink("b" * 32, "1234")
    assert relay.calls[-1]["url"] == f"https://r.example/links/{'b' * 32}"


def test_the_commands_need_the_registration_and_the_pin(loc, relay):
    with pytest.raises(LocationError, match="register"):
        loc.invite("1234")
    loc.register("wss://r.example", "Home", "1234")
    calls = len(relay.calls)
    with pytest.raises(LocationError, match="wrong PIN"):
        loc.invite("9999")
    with pytest.raises(LocationError, match="wrong PIN"):
        loc.unlink("b" * 32, "")
    assert len(relay.calls) == calls


def test_the_pin_locks_after_three_wrong_tries_then_after_two_each_time(loc, clock):
    loc.register("wss://r.example", "Home", "1234")
    for _ in range(3):
        with pytest.raises(LocationError, match="wrong PIN"):
            loc.invite("0000")
    with pytest.raises(LocationError, match="try again in"):
        loc.invite("1234")                      # locked: even the right PIN waits
    clock["t"] += 61
    loc.invite("1234")                          # a right PIN resets the count
    for _ in range(3):
        with pytest.raises(LocationError, match="wrong PIN"):
            loc.invite("0000")
    clock["t"] += 61
    for _ in range(2):
        with pytest.raises(LocationError, match="wrong PIN"):
            loc.invite("0000")
    with pytest.raises(LocationError, match="try again in"):
        loc.invite("1234")
    clock["t"] += 301
    with pytest.raises(LocationError, match="wrong PIN"):
        loc.invite("0000")
    with pytest.raises(LocationError, match="wrong PIN"):
        loc.invite("0000")
    with pytest.raises(LocationError, match="try again in"):
        loc.invite("1234")                      # the 2 tries and 5 minutes repeat
    clock["t"] += 301
    loc.invite("1234")


def test_the_lock_survives_a_restart(tmp_path, relay, clock):
    mk = lambda: Locations(tmp_path / "config.toml", post=relay, get=relay, delete=relay, patch=relay, now=lambda: clock["t"])
    a = mk()
    a.register("wss://r.example", "Home", "1234")
    for _ in range(3):
        with pytest.raises(LocationError):
            a.invite("0000")
    with pytest.raises(LocationError, match="try again in"):
        mk().invite("1234")


def test_removing_the_pin_from_the_file_resets_it(loc):
    loc.register("wss://r.example", "Home", "1234")
    state = json.loads(loc.path.read_text())
    del state["pin"]
    loc.path.write_text(json.dumps(state))
    assert loc.status()["pin_set"] is False
    with pytest.raises(LocationError, match="no PIN"):
        loc.invite("1234")
    loc.set_pin("5678")
    assert loc.status()["pin_set"] is True
    loc.invite("5678")
    with pytest.raises(LocationError, match="already"):
        loc.set_pin("1111")


def test_rename_changes_the_name_at_the_relay_and_here(loc, relay):
    loc.register("wss://r.example", "Home", "1234")
    assert loc.rename("  Garage ", "1234")["name"] == "Garage"
    call = relay.calls[-1]
    assert call["url"] == f"https://r.example/locations/{'a' * 32}" and json.loads(call["data"]) == {"name": "Garage"}
    assert loc.status()["name"] == "Garage"
    for bad in ("", "  ", "x" * 25):
        with pytest.raises(LocationError, match="name"):
            loc.rename(bad, "1234")
    with pytest.raises(LocationError, match="wrong PIN"):
        loc.rename("Other", "0000")
    assert loc.status()["name"] == "Garage"


def test_a_failed_rename_keeps_the_old_name(loc, relay):
    loc.register("wss://r.example", "Home", "1234")
    relay.status = 503
    relay.answers = {f"/locations/{'a' * 32}": {"error": "locations are not set up here"}}
    with pytest.raises(LocationError):
        loc.rename("Garage", "1234")
    assert loc.status()["name"] == "Home"


def test_unregister_deletes_at_the_relay_then_forgets_the_identity(loc, relay):
    loc.register("wss://r.example", "Home", "1234")
    with pytest.raises(LocationError, match="wrong PIN"):
        loc.unregister("0000")
    assert loc.status()["registered"]
    loc.unregister("1234")
    assert relay.calls[-1]["url"] == f"https://r.example/locations/{'a' * 32}"
    assert not loc.path.exists() and not loc.status()["registered"]
    loc.register("wss://r.example", "Garage", "5678")      # a new registration is possible
    assert loc.status()["name"] == "Garage"


def test_unregister_keeps_the_identity_while_the_relay_is_not_reached(loc, relay):
    loc.register("wss://r.example", "Home", "1234")
    relay.status = 503
    relay.answers = {f"/locations/{'a' * 32}": {"error": "the relay is down"}}
    with pytest.raises(LocationError, match="down"):
        loc.unregister("1234")
    assert loc.status()["registered"]


def test_change_pin_needs_the_current_pin_and_a_valid_new_one(loc):
    loc.register("wss://r.example", "Home", "1234")
    with pytest.raises(LocationError, match="wrong PIN"):
        loc.change_pin("0000", "5678")
    with pytest.raises(LocationError, match="PIN is"):
        loc.change_pin("1234", "12")
    loc.change_pin("1234", "5678")
    with pytest.raises(LocationError, match="wrong PIN"):
        loc.invite("1234")
    loc.invite("5678")


def test_the_relay_answers_are_logged_without_secrets(loc, relay, caplog):
    loc.register("wss://r.example", "Home", "1234")
    relay.status = 404
    relay.answers = {"/invitations/redeem": {"error": "invalid or expired invitation"}}
    with caplog.at_level("INFO", logger="breakfast.locations"):
        with pytest.raises(LocationError):
            loc.join(make_code("https://r.example", "t" * 32), "1234")
    text = caplog.text
    assert "/invitations/redeem answered 404: invalid or expired invitation" in text
    assert "1234" not in text and "t" * 32 not in text


def test_verify_pin_passes_without_a_pin_and_checks_it_once_set(loc):
    assert not loc.pin_required()
    loc.verify_pin(None)
    loc.register("wss://r.example", "Home", "1234")
    assert loc.pin_required()
    loc.verify_pin("1234")
    with pytest.raises(LocationError, match="wrong PIN"):
        loc.verify_pin("0000")
    with pytest.raises(LocationError, match="wrong PIN"):
        loc.verify_pin(None)


def test_the_voice_channels_of_a_site_are_asked_with_a_signed_request(loc, relay):
    loc.register("wss://r.example", "Home", "1234")
    relay.answers = {"/circle/voice": {"channels": [{"id": "d" * 32, "name": "Kitchen"}]}}
    assert loc.voice_channels() == [{"id": "d" * 32, "name": "Kitchen"}]
    call = relay.calls[-1]
    assert call["url"] == "https://r.example/circle/voice" and call["headers"]["x-location"] == "a" * 32


def test_the_address_of_a_voice_channel_carries_the_ticket_after_the_hash(loc, relay):
    loc.register("wss://r.example", "Home", "1234")
    channel = "d" * 32
    relay.answers = {f"/circle/voice/{channel}/ticket": {"ticket": "t" * 32, "site": "Home", "channel": {"id": channel, "name": "Front room"}}}
    url = loc.voice_channel_url(channel, "de")
    assert url == f"https://r.example/voice#channel={channel}&name=Front+room&site=Home&ticket={'t' * 32}&lang=de"
    assert relay.calls[-1]["url"] == f"https://r.example/circle/voice/{channel}/ticket"


def test_a_voice_channel_needs_a_plain_id_and_a_registered_location(loc, relay):
    with pytest.raises(LocationError, match="register"):
        loc.voice_channels()
    loc.register("wss://r.example", "Home", "1234")
    for bad in ("", "../x", "D" * 32, "d" * 31):
        with pytest.raises(LocationError, match="unknown channel"):
            loc.voice_channel_url(bad)
    relay.status = 404
    relay.answers = {f"/circle/voice/{'d' * 32}/ticket": {"error": "unknown channel"}}
    with pytest.raises(LocationError, match="unknown channel"):
        loc.voice_channel_url("d" * 32)


# ── a server that serves its routes below a prefix, pairing and the switch to it ──────────────────────────────

def _verify(public, call, method, path):
    h = call["headers"]
    body = call.get("data") or b""
    message = f"{method}\n{path}\n{h['x-timestamp']}\n{hashlib.sha256(body).hexdigest()}".encode()
    Ed25519PublicKey.from_public_bytes(_unb64(public)).verify(_unb64(h["x-signature"]), message)


def test_requests_to_an_address_with_a_prefix_are_signed_over_the_whole_path(loc, relay):
    loc.register("wss://cloud.example/api/v1", "Home", "1234")
    assert loc.status()["relay"] == "https://cloud.example/api/v1"
    public = json.loads(relay.calls[0]["data"])["public_key"]
    assert relay.calls[0]["url"] == "https://cloud.example/api/v1/locations"
    _verify(public, relay.calls[0], "POST", "/api/v1/locations")
    loc.invite("1234")
    assert relay.calls[1]["url"] == f"https://cloud.example/api/v1/locations/{'a' * 32}/invitations"
    _verify(public, relay.calls[1], "POST", f"/api/v1/locations/{'a' * 32}/invitations")
    loc.call("GET", "/circle/records?since=3&limit=10")
    _verify(public, relay.calls[2], "GET", "/api/v1/circle/records")
    sign = loc.signer_for("wss://cloud.example/api/v1")
    headers = sign("POST", "/api/matches", "{}")
    _verify(public, {"headers": headers, "data": b"{}"}, "POST", "/api/v1/api/matches")


@pytest.mark.parametrize("typed, base", [
    ("cloud.example", "https://cloud.example/api/v1"),
    (" https://cloud.example/ ", "https://cloud.example/api/v1"),
    ("wss://cloud.example", "https://cloud.example/api/v1"),
    ("http://127.0.0.1:8080", "http://127.0.0.1:8080/api/v1"),
    ("https://cloud.example/api/v1/", "https://cloud.example/api/v1"),
    ("https://cloud.example/other", "https://cloud.example/other"),
])
def test_the_address_of_a_cloud_server_gets_the_prefix_unless_it_has_a_path(typed, base):
    assert locations.cloud_base(typed) == base


@pytest.mark.parametrize("typed", ["", "  ", "ftp://cloud.example", "https://", "https://cloud.example?x=1", "cloud example"])
def test_a_bad_cloud_address_is_refused(typed):
    with pytest.raises(LocationError):
        locations.cloud_base(typed)


def test_pairing_asks_for_a_code_and_shows_it_as_a_qr_code(loc, relay):
    loc.register("wss://cloud.example/api/v1", "Home", "1234")
    relay.answers = {"/api/v1/pairings": {"code": "K7M2-QX4R", "url": "https://cloud.example/#/pair/K7M2-QX4R", "expires_in_s": 600, "interval_s": 5}}
    with pytest.raises(LocationError, match="wrong PIN"):
        loc.pair("0000")
    res = loc.pair("1234")
    assert res["code"] == "K7M2-QX4R" and res["url"].endswith("/#/pair/K7M2-QX4R") and res["expires_in_s"] == 600 and res["interval_s"] == 5
    assert res["qr"].lstrip().startswith("<svg")
    assert relay.calls[-1]["url"] == "https://cloud.example/api/v1/pairings"


def test_the_account_is_reported_and_a_relay_without_accounts_has_none(loc, relay):
    loc.register("wss://cloud.example/api/v1", "Home", "1234")
    relay.answers = {"/api/v1/account": {"paired": True, "email": "anna@example.org", "paired_at": 5}}
    assert loc.account() == {"available": True, "paired": True, "email": "anna@example.org", "paired_at": 5}
    loc.unpair("1234")
    assert relay.calls[-1]["url"] == "https://cloud.example/api/v1/account"
    relay.status = 404
    relay.answers = {}
    assert loc.account() == {"available": False}
    relay.status = 503
    with pytest.raises(LocationError):
        loc.account()


class MovingRelay(FakeRelay):
    """Two servers: answers per full address, and the greeting of a Breakfast server as text."""

    def __init__(self):
        super().__init__()
        self.pages = {}

    def __call__(self, url, **kw):
        self.calls.append({"url": url, **kw})
        if url in self.pages:
            status, text, body = self.pages[url]
            return SimpleNamespace(status_code=status, text=text, json=lambda: body)
        return SimpleNamespace(status_code=200, text="", json=lambda: {"id": "a" * 32, "links": []})


def test_moving_to_another_server_keeps_the_identity_and_changes_the_address(tmp_path, clock):
    relay = MovingRelay()
    loc = Locations(tmp_path / "config.toml", post=relay, get=relay, delete=relay, patch=relay, now=lambda: clock["t"])
    loc.register("wss://relay.example", "Home", "1234")
    public = json.loads(relay.calls[0]["data"])["public_key"]
    before = json.loads(loc.path.read_text())
    relay.pages["https://cloud.example/api/v1/"] = (200, "breakfast relay, protocol 4\n", {})
    with pytest.raises(LocationError, match="wrong PIN"):
        loc.move_to("cloud.example", "0000")
    assert loc.move_to("cloud.example", "1234") == "https://cloud.example/api/v1"
    after = json.loads(loc.path.read_text())
    assert after["relay"] == "https://cloud.example/api/v1"
    assert (after["id"], after["key"], after["name"], after["pin"]) == (before["id"], before["key"], before["name"], before["pin"])
    check = relay.calls[-1]
    assert check["url"] == f"https://cloud.example/api/v1/locations/{'a' * 32}/links"
    _verify(public, check, "GET", f"/api/v1/locations/{'a' * 32}/links")
    with pytest.raises(LocationError, match="already"):
        loc.move_to("https://cloud.example", "1234")


def test_a_move_changes_nothing_when_the_new_server_is_not_one_or_does_not_know_the_location(tmp_path, clock):
    relay = MovingRelay()
    loc = Locations(tmp_path / "config.toml", post=relay, get=relay, delete=relay, patch=relay, now=lambda: clock["t"])
    loc.register("wss://relay.example", "Home", "1234")
    relay.pages["https://other.example/api/v1/"] = (200, "<html>a web page</html>", {})
    with pytest.raises(LocationError, match="no Breakfast server"):
        loc.move_to("other.example", "1234")
    relay.pages["https://down.example/api/v1/"] = (502, "", {})
    with pytest.raises(LocationError, match="no Breakfast server"):
        loc.move_to("down.example", "1234")
    relay.pages["https://cloud.example/api/v1/"] = (200, "breakfast relay, protocol 4\n", {})
    relay.pages[f"https://cloud.example/api/v1/locations/{'a' * 32}/links"] = (401, "", {"error": "unknown location", "code": "unknown_location"})
    with pytest.raises(LocationError, match="has not been moved"):
        loc.move_to("cloud.example", "1234")
    assert loc.status()["relay"] == "https://relay.example"
