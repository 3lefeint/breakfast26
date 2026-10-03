import asyncio

from starlette.testclient import TestClient

from breakfast.stats import StatsDB, StatsTracker
from breakfast.web import server


def _wire(tmp_path):
    db = StatsDB(str(tmp_path / "s.db"))
    server.wire(None, None, stats_tracker=StatsTracker(db))
    return db


def _first_ws_payload():
    with TestClient(server.app).websocket_connect("/ws") as ws:
        return ws.receive_json()


def test_new_ws_client_gets_players_added_after_the_last_push(tmp_path):
    db = _wire(tmp_path)
    try:
        server.push()
        db.upsert_player("Neu")
        assert _first_ws_payload()["known_players"] == ["Neu"]
    finally:
        server.wire(None, None)


def _count_pushes(monkeypatch):
    calls = []
    monkeypatch.setattr(server, "push", lambda: calls.append(1))
    return calls


def test_add_player_pushes(tmp_path, monkeypatch):
    _wire(tmp_path)
    calls = _count_pushes(monkeypatch)
    try:
        asyncio.run(server.add_player(server.PlayerBody(name="Neu")))
        assert calls == [1]
    finally:
        server.wire(None, None)


def test_hiding_and_unhiding_a_player_pushes(tmp_path, monkeypatch):
    _wire(tmp_path)
    calls = _count_pushes(monkeypatch)
    try:
        asyncio.run(server.add_player(server.PlayerBody(name="Neu")))
        asyncio.run(server.set_player_hidden("Neu", server.HiddenBody(hidden=True)))
        asyncio.run(server.set_player_hidden("Neu", server.HiddenBody(hidden=False)))
        assert calls == [1, 1, 1]
    finally:
        server.wire(None, None)


def test_deleting_a_player_pushes(tmp_path, monkeypatch):
    _wire(tmp_path)
    calls = _count_pushes(monkeypatch)
    try:
        asyncio.run(server.add_player(server.PlayerBody(name="Neu")))
        asyncio.run(server.stats_delete_player("Neu"))
        assert calls == [1, 1]
    finally:
        server.wire(None, None)
