import asyncio
import threading
import time

from starlette.testclient import TestClient

from breakfast.achievements import AchievementEngine
from breakfast.stats import StatsDB, StatsTracker
from breakfast.web import server


def _get(name):
    return TestClient(server.app).get(f"/api/achievements/{name}").json()


def test_without_a_stats_database_the_list_is_empty():
    server.wire(None, None)
    assert _get("ana") == {"player": "ana", "achievements": []}


def test_without_an_engine_the_list_is_empty(tmp_path):
    server.wire(None, None, stats_tracker=StatsTracker(StatsDB(str(tmp_path / "s.db"))))
    try:
        assert _get("ana")["achievements"] == []
    finally:
        server.wire(None, None)


def test_lists_the_achievements_of_a_player(tmp_path):
    db = StatsDB(str(tmp_path / "s.db"))
    AchievementEngine(db).attach()
    server.wire(None, None, stats_tracker=StatsTracker(db))
    try:
        db.open_match("m1", "X01", 501)
        db.insert_turn("m1", "ana", 1, 1, 501, 50, False, False, [("BULL", 50, 451)])
        db.insert_turn("m1", "bo", 1, 1, 501, 20, False, False, [("S20", 20, 481)])
        db.close_match("m1")
        body = _get("ana")
        assert body["player"] == "ana"
        by_id = {a["id"]: a for a in body["achievements"]}
        assert by_id["bullseye"]["tier"] == 1
        assert by_id["beast_mode"]["names"] is None
    finally:
        server.wire(None, None)


def test_an_achievement_message_is_sent_to_every_websocket_client(monkeypatch):
    # The server runs its own event loop (server.start()); give it one here and two fake clients.
    loop = asyncio.new_event_loop()
    threading.Thread(target=loop.run_forever, daemon=True).start()
    received = []

    class FakeClient:
        async def send_json(self, data):
            received.append(data)

    monkeypatch.setattr(server, "_loop", loop)
    monkeypatch.setattr(server, "_clients", {FakeClient(), FakeClient()})
    try:
        message = {"type": "achievement", "player": "ana", "id": "bullseye"}
        server.push_achievement(message)
        deadline = time.time() + 2
        while len(received) < 2 and time.time() < deadline:
            time.sleep(0.01)
        assert received == [message, message]
    finally:
        loop.call_soon_threadsafe(loop.stop)


def test_nothing_is_sent_while_the_server_is_not_running(monkeypatch):
    monkeypatch.setattr(server, "_loop", None)
    server.push_achievement({"type": "achievement"})      # must not raise
