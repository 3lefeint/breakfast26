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
        self.mappings = [{"location_id": "loc-1", "location_name": "Home", "local_name": "anna", "player_id": "p-1"}]
        self.refetch = 0

    def status(self):
        return {"registered": True, "id": "loc-1", "name": "Home"}

    def call(self, method, path, body=None):
        self.calls.append((method, path.split("?")[0], body))
        if path == "/circle/state":
            return {"approved": True}
        if path == "/circle/config":
            return {"approved": True, "refetch": self.refetch, "circle_players": [], "mappings": [], "site_mappings": self.mappings}
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
        assert client.post("/api/circle/send-all").json()["queued"] == 0         # not registered: nothing to queue
    finally:
        server.wire(None, None)


def test_an_imported_match_earns_achievements_silently(tmp_path):
    from breakfast import achievements as ach
    from breakfast.match_record import export_record
    far = StatsDB(str(tmp_path / "far.db"))
    far.open_match("m-1", "X01", 501)
    far.insert_turn("m-1", "ana", 1, 1, 501, 120, False, False, [("S20", 20, 481), ("50", 50, 431), ("S1", 1, 430)])
    far.insert_turn("m-1", "bo", 1, 2, 501, 20, False, False, [("S20", 20, 481)])
    far.record_leg_win("m-1", 1, "ana")
    far.set_winner("m-1", "ana")
    far.close_match("m-1")
    record = export_record(far, "m-1", {"id": "far-id", "name": "Far"})

    home = StatsDB(str(tmp_path / "home.db"))
    home.set_achievements_start("2000-01-01T00:00:00+00:00")
    earned = []
    ach.AchievementEngine(home, definitions=(ach.BY_ID["bullseye"],), on_earned=earned.append).attach()
    relay = Relay()
    sync = CircleSync(home, relay, tmp_path / "config.toml", "1.9.0")
    config = {"site_mappings": [{"location_id": "far-id", "location_name": "Far", "local_name": "ana", "player_id": "p1"}],
              "mappings": [{"local_name": "anna", "player_id": "p1"}]}
    relay.call = lambda method, path, body=None: {"record": record}
    sync._import({"match_id": "m-1", "origin": {"id": "far-id"}}, config, {})
    assert {(r["player"], r["achievement_id"]) for r in home._conn.execute("SELECT player, achievement_id FROM achievements_earned")} == {("anna", "bullseye")}
    assert earned == []                                       # nothing is announced
    assert home._conn.execute("SELECT COUNT(*) FROM achievements_earned WHERE player = 'bo@far'").fetchone()[0] == 0


def test_an_imported_match_counts_before_the_achievements_start_and_stays_after_a_local_match(tmp_path):
    from breakfast import achievements as ach
    from breakfast.match_record import export_record
    far = StatsDB(str(tmp_path / "far.db"))
    far.open_match("m-1", "X01", 501)
    far.insert_turn("m-1", "ana", 1, 1, 501, 120, False, False, [("S20", 20, 481), ("50", 50, 431), ("S1", 1, 430)])
    far.record_leg_win("m-1", 1, "ana")
    far.set_winner("m-1", "ana")
    far.close_match("m-1")
    record = export_record(far, "m-1", {"id": "far-id", "name": "Far"})

    home = StatsDB(str(tmp_path / "home.db"))
    home.set_achievements_start("2999-01-01T00:00:00+00:00")    # the match started long before
    engine = ach.AchievementEngine(home, definitions=(ach.BY_ID["bullseye"],)).attach()
    relay = Relay()
    sync = CircleSync(home, relay, tmp_path / "config.toml", "1.9.0")
    config = {"site_mappings": [{"location_id": "far-id", "location_name": "Far", "local_name": "ana", "player_id": "p1"}],
              "mappings": [{"local_name": "anna", "player_id": "p1"}]}
    relay.call = lambda method, path, body=None: {"record": record}
    sync._import({"match_id": "m-1", "origin": {"id": "far-id"}}, config, {})
    earned = lambda: {(r["player"], r["achievement_id"]) for r in home._conn.execute("SELECT player, achievement_id FROM achievements_earned")}
    assert earned() == {("anna", "bullseye")}
    home.open_match("local", "X01", 501)
    home.insert_turn("local", "anna", 1, 1, 501, 3, False, False, [("S1", 1, 500), ("S1", 1, 499), ("S1", 1, 498)])
    home.close_match("local")
    engine.evaluate_match("local")
    assert earned() == {("anna", "bullseye")}                   # a local match does not take it back


def test_a_match_without_a_player_of_the_circle_is_not_sent(setup):
    db, relay, sync = setup
    relay.mappings = []
    _finish(db, "m-1")
    status = sync.run_once()
    assert status["pending"] == 0 and _puts(relay) == []


def test_send_all_queues_the_history_once_and_a_mapping_made_later_gets_it_sent(setup):
    db, relay, sync = setup
    relay.mappings = []
    for n in range(3):
        _finish(db, f"m-{n}")
    db.open_match("open", "X01", 501)                     # not finished: not queued
    sync.run_once()
    assert sync.status()["pending"] == 0
    relay.mappings = [{"location_id": "loc-1", "location_name": "Home", "local_name": "anna", "player_id": "p-1"}]
    assert sync.send_all() == 3
    assert sync.send_all() == 0                           # already in the outbox
    status = sync.run_once()
    assert status["pending"] == 0 and status["pushed"] == 3
    assert sync.send_all() == 0                           # sent, nothing newer


def test_a_limit_of_the_relay_pauses_the_outbox_without_losing_anything(setup):
    db, relay, sync = setup
    clock = {"t": 1000.0}
    sync._now = lambda: clock["t"]
    for n in range(3):
        _finish(db, f"m-{n}")
    relay.fail = LocationError("too many records today", 429)
    status = sync.run_once()
    assert status["pending"] == 3 and status["error"] is None and status["paused_until"] == 1000 + 3600
    assert len(_puts(relay)) == 1                         # one try, then it waits
    sync.run_once()
    assert len(_puts(relay)) == 1                         # still waiting
    relay.fail = None
    clock["t"] += 3601
    status = sync.run_once()
    assert status["pending"] == 0 and status["pushed"] == 3 and status["paused_until"] is None


def test_a_large_outbox_goes_out_in_rounds(setup, monkeypatch):
    import breakfast.circle_sync as module
    monkeypatch.setattr(module, "PUSH_ROUND", 2)
    db, relay, sync = setup
    for n in range(5):
        _finish(db, f"m-{n}")
    assert sync.run_once()["pending"] == 3 and sync._more is True
    assert sync.run_once()["pending"] == 1
    assert sync.run_once()["pending"] == 0 and sync._more is False


def test_the_admin_can_make_a_site_fetch_everything_again(setup):
    db, relay, sync = setup
    relay.records = [{"seq": 1, "match_id": "r-1", "revision": 1, "deleted": True, "origin": {"id": "o"}}]
    sync.run_once()
    assert sync._load()["cursor"] == 1
    relay.calls.clear()
    sync.run_once()
    assert [c for c in relay.calls if c[1] == "/circle/records"][0][1:] == ("/circle/records", None)
    relay.refetch = 1
    sync._update(cursor=7)
    sync.run_once()
    assert sync._load()["refetch_seen"] == 1 and sync._load()["cursor"] == 1      # started at 0 again, read the list again
    paths = [c[1] for c in relay.calls]
    assert paths.count("/circle/records") >= 2


def test_a_record_already_here_is_not_fetched_again(setup):
    db, relay, sync = setup
    _finish(db, "m-1")
    revision = db._conn.execute("SELECT revision FROM matches WHERE match_id = 'm-1'").fetchone()[0]
    relay.records = [{"seq": 1, "match_id": "m-1", "revision": revision, "deleted": False, "origin": {"id": "o"}},
                     {"seq": 2, "match_id": "gone", "revision": 1, "deleted": True, "origin": {"id": "o"}}]
    sync.run_once()
    assert not [c for c in relay.calls if c[0] == "GET" and c[1].startswith("/circle/records/")]


def test_a_limit_while_fetching_pauses_the_fetch(setup):
    db, relay, sync = setup
    sync._now = lambda: 5000.0
    relay.records = [{"seq": 1, "match_id": "r-1", "revision": 1, "deleted": False, "origin": {"id": "o"}}]
    original = relay.call

    def call(method, path, body=None):
        if path.startswith("/circle/records/"):
            raise LocationError("too many requests", 429)
        return original(method, path, body)
    relay.call = call
    status = sync.run_once()
    assert status["paused_until"] == 5000 + 3600 and status["error"] is None and sync._load()["cursor"] == 0
