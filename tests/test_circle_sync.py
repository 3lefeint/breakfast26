"""CircleSync with a stand-in for the relay: what happens when it is not reachable, refuses a record or has records that
cannot be read. The whole way of a match through the real relay is in test_circle_e2e.py."""

import pytest

from breakfast.circle_sync import MAX_TRIES, CircleSync
from breakfast.locations import LocationError
from breakfast.stats import StatsDB


class Relay:
    """A location as CircleSync sees it: the status and `call`, answered from a script."""

    def __init__(self):
        self.calls = []
        self.fail = None             # a LocationError to raise for PUT /circle/records
        self.records = []

    def status(self):
        return {"registered": True, "id": "loc-1", "name": "Home"}

    def call(self, method, path, body=None):
        self.calls.append((method, path.split("?")[0], body))
        if path == "/circle/state":
            return {"approved": True}
        if path == "/circle/config":
            return {"approved": True, "circle_players": [], "mappings": [], "site_mappings": []}
        if method == "PUT" and self.fail:
            raise self.fail
        if method == "PUT":
            return {}
        if path.startswith("/circle/records?"):
            return {"records": self.records, "next": self.records[-1]["seq"] if self.records else 0}
        raise AssertionError(path)


@pytest.fixture
def setup(tmp_path):
    db = StatsDB(str(tmp_path / "stats.db"))
    relay = Relay()
    sync = CircleSync(db, relay, tmp_path / "config.toml", "1.9.0")
    db.on_match_closed, db.on_match_deleted = sync.match_closed, sync.match_deleted
    return db, relay, sync


def _finish(db, match_id):
    db.open_match(match_id, "X01", 501)
    db.insert_turn(match_id, "anna", 1, 1, 501, 60, False, False, [("T20", 60, 441)])
    db.set_winner(match_id, "anna")
    db.close_match(match_id)


def _puts(relay):
    return [c for c in relay.calls if c[0] == "PUT" and c[1].startswith("/circle/records/")]


def test_an_unreachable_relay_keeps_the_match_in_the_outbox(setup):
    db, relay, sync = setup
    _finish(db, "m-1")
    relay.fail = LocationError("the relay is not reachable")
    status = sync.run_once()
    assert status["pending"] == 1 and "not reachable" in status["error"] and status["pushed"] == 0
    relay.fail = None
    status = sync.run_once()
    assert status["pending"] == 0 and status["pushed"] == 1 and status["error"] is None
    assert len(_puts(relay)) == 2 and _puts(relay)[1][1] == "/circle/records/m-1/1"


def test_a_match_the_relay_will_not_take_is_dropped(setup):
    db, relay, sync = setup
    _finish(db, "m-1")
    relay.fail = LocationError("no player of this match is in the circle", 422)
    status = sync.run_once()
    assert status["pending"] == 0 and status["pushed"] == 0 and status["error"] is None
    db.delete_match("m-1")
    assert sync.status()["pending"] == 0                   # it was never sent, so there is nothing to take away


def test_a_match_is_given_up_after_many_failed_tries(setup):
    db, relay, sync = setup
    _finish(db, "m-1")
    relay.fail = LocationError("the relay is not reachable")
    for _ in range(MAX_TRIES):
        sync.run_once()
    assert sync.status()["pending"] == 0


def test_a_mode_without_a_record_is_not_sent(setup):
    db, relay, sync = setup
    db.open_match("w-1", "Warm-up", 0)
    db.close_match("w-1")
    status = sync.run_once()
    assert status["pending"] == 0 and _puts(relay) == []


def test_a_record_that_cannot_be_read_does_not_block_the_next_ones(setup):
    db, relay, sync = setup
    good = {"record_version": 1, "game_mode": "X01", "match_id": "r-2", "revision": 1, "deleted": True, "origin": {"id": "o", "name": "Far"}}
    entries = [{"seq": 1, "match_id": "r-1", "origin": {"id": "o"}}, {"seq": 2, "match_id": "r-2", "origin": {"id": "o"}}]
    relay.records = entries
    answers = {"/circle/records/r-1": {"record": {"record_version": 99}}, "/circle/records/r-2": {"record": good}}
    original = relay.call
    relay.call = lambda m, p, b=None: answers[p] if p in answers else original(m, p, b)
    status = sync.run_once()
    assert status["error"] is None and sync._load()["cursor"] == 2


def test_an_installation_without_a_location_queues_nothing(tmp_path):
    from breakfast.locations import Locations
    db = StatsDB(str(tmp_path / "stats.db"))
    sync = CircleSync(db, Locations(tmp_path / "config.toml"), tmp_path / "config.toml", "1.9.0")
    db.on_match_closed = sync.match_closed
    _finish(db, "m-1")
    status = sync.status()
    assert status["registered"] is False and status["pending"] == 0
    assert sync.run_once()["pushed"] == 0


def test_the_api_shows_the_state_and_switches_the_sync(tmp_path):
    from starlette.testclient import TestClient
    from breakfast.stats import StatsTracker
    from breakfast.web import server
    server.wire(None, None, stats_tracker=StatsTracker(StatsDB(str(tmp_path / "stats.db"))), config_path=str(tmp_path / "config.toml"))
    try:
        client = TestClient(server.app)
        state = client.get("/api/circle").json()
        assert state["available"] is True and state["enabled"] is True and state["registered"] is False
        assert client.post("/api/circle/enabled", json={"enabled": False}).json()["enabled"] is False
        assert client.get("/api/circle").json()["enabled"] is False
        assert client.post("/api/circle/sync").json()["ok"] is True
    finally:
        server.wire(None, None)
