import asyncio
from datetime import datetime, timezone

import pytest

from breakfast import config as cfg_mod
from breakfast import joke
from breakfast.web import server


@pytest.fixture(autouse=True)
def _fresh_joke_cache():
    joke.reset()
    yield
    joke.reset()


def _day(d):
    return datetime(2026, 10, d, 12, tzinfo=timezone.utc)


def test_joke_is_fetched_once_per_day():
    calls = []
    fetch = lambda: calls.append(1) or "A fetched joke"
    assert joke.joke_of_the_day(_day(1), fetch) == {"joke": "A fetched joke", "source": "icanhazdadjoke"}
    assert joke.joke_of_the_day(_day(1), fetch)["joke"] == "A fetched joke"
    assert len(calls) == 1
    joke.joke_of_the_day(_day(2), fetch)
    assert len(calls) == 2


def test_joke_falls_back_when_the_request_fails():
    def fail():
        raise OSError("no network")

    result = joke.joke_of_the_day(_day(1), fail)
    assert result["source"] == "builtin" and result["joke"] in joke.FALLBACK_JOKES


def test_a_failed_request_is_not_retried_right_away():
    calls = []

    def fail():
        calls.append(1)
        raise OSError("no network")

    joke.joke_of_the_day(_day(1), fail)
    joke.joke_of_the_day(_day(1), fail)
    assert len(calls) == 1


def test_builtin_joke_is_stable_within_a_day():
    fail = lambda: (_ for _ in ()).throw(OSError())
    assert joke.joke_of_the_day(_day(3), fail) == joke.joke_of_the_day(_day(3), fail)


def test_joke_endpoint_can_be_switched_off(tmp_path, monkeypatch):
    config_path = tmp_path / "config.toml"
    cfg_mod.write(str(config_path), {"web": {"joke_of_the_day": False}})
    monkeypatch.setattr(joke, "_fetch", lambda: pytest.fail("no outbound call expected"))
    server.wire(None, None, config_path=str(config_path))
    try:
        assert asyncio.run(server.get_joke()) == {"enabled": False, "joke": None, "source": None}
    finally:
        server.wire(None, None)


def test_joke_endpoint_defaults_to_on(tmp_path, monkeypatch):
    config_path = tmp_path / "config.toml"
    cfg_mod.write(str(config_path), {})
    monkeypatch.setattr(joke, "_fetch", lambda: "Fetched")
    server.wire(None, None, config_path=str(config_path))
    try:
        res = asyncio.run(server.get_joke())
        assert res["enabled"] is True and res["joke"] == "Fetched"
    finally:
        server.wire(None, None)


def test_changelog_endpoint_returns_the_versions():
    versions = asyncio.run(server.get_changelog())["versions"]
    assert versions and {"version", "date", "sections"} <= set(versions[0])


def test_changelog_endpoint_without_the_file(tmp_path, monkeypatch):
    monkeypatch.setattr(server, "_CHANGELOG_PATH", tmp_path / "missing.md")
    assert asyncio.run(server.get_changelog()) == {"versions": []}
