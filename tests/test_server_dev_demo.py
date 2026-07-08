import asyncio

import pytest

from breakfast import config as cfg_mod
from breakfast.web import server


@pytest.fixture(autouse=True)
def reset_dev_unlocked():
    # _dev_unlocked is a plain module-level global, not reset by wire() —
    # guard against one test's unlock leaking into the next.
    server._dev_unlocked = False
    yield
    server._dev_unlocked = False


class FakeDemo:
    def __init__(self, start_result=(True, None)):
        self.start_result = start_result
        self.started_x01 = False
        self.started_elimination = False

    def start_x01(self):
        self.started_x01 = True
        return self.start_result

    def start_elimination(self):
        self.started_elimination = True
        return self.start_result

    def status(self):
        return {"running": False, "mode": None}


def _wire(tmp_path, dev_enabled, dev_demo):
    config_path = tmp_path / "config.toml"
    cfg_mod.write(str(config_path), {"dev": {"enabled": dev_enabled}})
    server.wire(None, None, config_path=str(config_path), dev_demo=dev_demo)


def test_x01_demo_refused_when_dev_disabled(tmp_path):
    demo = FakeDemo()
    _wire(tmp_path, False, demo)
    try:
        res = asyncio.run(server.dev_demo_x01())
        assert res == {"started": False, "error": "[dev] not enabled in config"}
        assert demo.started_x01 is False
    finally:
        server.wire(None, None)


def test_x01_demo_starts_when_dev_enabled(tmp_path):
    demo = FakeDemo()
    _wire(tmp_path, True, demo)
    try:
        res = asyncio.run(server.dev_demo_x01())
        assert res == {"started": True, "error": None}
        assert demo.started_x01 is True
    finally:
        server.wire(None, None)


def test_elimination_demo_refused_when_dev_disabled(tmp_path):
    demo = FakeDemo()
    _wire(tmp_path, False, demo)
    try:
        res = asyncio.run(server.dev_demo_elimination())
        assert res == {"started": False, "error": "[dev] not enabled in config"}
        assert demo.started_elimination is False
    finally:
        server.wire(None, None)


def test_elimination_demo_starts_when_dev_enabled(tmp_path):
    demo = FakeDemo()
    _wire(tmp_path, True, demo)
    try:
        res = asyncio.run(server.dev_demo_elimination())
        assert res == {"started": True, "error": None}
        assert demo.started_elimination is True
    finally:
        server.wire(None, None)


def test_demo_unavailable_when_not_wired(tmp_path):
    _wire(tmp_path, True, None)
    try:
        res = asyncio.run(server.dev_demo_x01())
        assert res == {"started": False, "error": "demo unavailable"}
    finally:
        server.wire(None, None)


def test_demo_start_failure_surfaces_error(tmp_path):
    demo = FakeDemo(start_result=(False, "A real match is already in progress"))
    _wire(tmp_path, True, demo)
    try:
        res = asyncio.run(server.dev_demo_x01())
        assert res == {"started": False, "error": "A real match is already in progress"}
    finally:
        server.wire(None, None)


class TestDevUnlock:
    def test_disabled_by_default(self, tmp_path):
        demo = FakeDemo()
        _wire(tmp_path, False, demo)
        try:
            assert server._dev_enabled() is False
        finally:
            server.wire(None, None)

    def test_unlock_enables_it_without_touching_config(self, tmp_path):
        demo = FakeDemo()
        _wire(tmp_path, False, demo)
        try:
            res = asyncio.run(server.dev_unlock())
            assert res == {"unlocked": True}
            assert server._dev_enabled() is True

            config_path = tmp_path / "config.toml"
            assert cfg_mod.load(str(config_path)).get("dev", {}).get("enabled") in (None, False)

            demo_res = asyncio.run(server.dev_demo_x01())
            assert demo_res == {"started": True, "error": None}
        finally:
            server.wire(None, None)
