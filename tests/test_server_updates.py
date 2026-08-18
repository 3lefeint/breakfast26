import asyncio

from breakfast.web import server


def test_updates_check_returns_updater_response(monkeypatch):
    monkeypatch.setattr(
        server, "_updater_get",
        lambda path: {"current": "0.1.0", "latest": "0.2.0", "update_available": True},
    )
    res = asyncio.run(server.updates_check())
    assert res == {"current": "0.1.0", "latest": "0.2.0", "update_available": True}


def test_updates_check_reports_unreachable_updater(monkeypatch):
    def boom(path):
        raise ConnectionError("refused")
    monkeypatch.setattr(server, "_updater_get", boom)
    res = asyncio.run(server.updates_check())
    assert "error" in res
    assert "refused" in res["error"]


def test_updates_apply_returns_updater_response(monkeypatch):
    monkeypatch.setattr(server, "_updater_post", lambda path: {"ok": True})
    res = asyncio.run(server.updates_apply())
    assert res == {"ok": True}


def test_updates_apply_reports_unreachable_updater(monkeypatch):
    def boom(path):
        raise ConnectionError("refused")
    monkeypatch.setattr(server, "_updater_post", boom)
    res = asyncio.run(server.updates_apply())
    assert "error" in res


def test_updates_status_returns_updater_response(monkeypatch):
    monkeypatch.setattr(
        server, "_updater_get",
        lambda path: {"phase": "building", "detail": None, "started_at": 123.0},
    )
    res = asyncio.run(server.updates_status())
    assert res["phase"] == "building"


def test_updates_status_reports_unreachable_updater(monkeypatch):
    def boom(path):
        raise ConnectionError("refused")
    monkeypatch.setattr(server, "_updater_get", boom)
    res = asyncio.run(server.updates_status())
    assert "error" in res
