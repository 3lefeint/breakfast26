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
