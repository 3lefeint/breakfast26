import json
import time

import pytest

from breakfast import dev_demo
from breakfast.dev_demo import DemoRunner
from breakfast.elimination import EliminationController
from breakfast.mqtt_output import NullMqttPublisher
from breakfast.state import GameState


@pytest.fixture(autouse=True)
def no_real_sleep(monkeypatch):
    monkeypatch.setattr(dev_demo.time, "sleep", lambda *_: None)


@pytest.fixture
def x01_fixture(tmp_path, monkeypatch):
    lines = [
        {"ts": "2026-01-01T10:00:00", "payload": {"event": "match-started"}},
        {"ts": "2026-01-01T10:00:01", "payload": {"event": "dart1-thrown", "game": {"dartValue": "20"}}},
    ]
    p = tmp_path / "demo.jsonl"
    p.write_text("\n".join(json.dumps(l) for l in lines) + "\n")
    monkeypatch.setattr(dev_demo, "_X01_DEMO_FILE", str(p))
    return lines


def _wait_until_idle(runner, timeout=2.0):
    deadline = time.time() + timeout
    while runner.status()["running"] and time.time() < deadline:
        time.sleep(0.01)


class TestX01Demo:
    def test_replays_every_line_through_callback(self, x01_fixture):
        received = []
        runner = DemoRunner(on_x01_event=received.append)
        runner._run_x01()
        assert received == [l["payload"] for l in x01_fixture]
        assert runner.status() == {"running": False, "mode": None}

    def test_stops_after_first_match_won_even_if_file_continues(self, tmp_path, monkeypatch):
        # The bundled fixture is a real recording of two full matches back to
        # back (a second match-started fires right after the first
        # match-won) — the demo must stop at the first match-won rather than
        # silently rolling into the second match.
        lines = [
            {"ts": "2026-01-01T10:00:00", "payload": {"event": "match-started"}},
            {"ts": "2026-01-01T10:00:01", "payload": {"event": "dart1-thrown"}},
            {"ts": "2026-01-01T10:00:02", "payload": {"event": "match-won"}},
            {"ts": "2026-01-01T10:00:03", "payload": {"event": "match-started"}},  # second match — must never be reached
            {"ts": "2026-01-01T10:00:04", "payload": {"event": "dart1-thrown"}},
        ]
        p = tmp_path / "demo.jsonl"
        p.write_text("\n".join(json.dumps(l) for l in lines) + "\n")
        monkeypatch.setattr(dev_demo, "_X01_DEMO_FILE", str(p))

        received = []
        runner = DemoRunner(on_x01_event=received.append)
        runner._run_x01()
        assert received == [l["payload"] for l in lines[:3]]

    def test_synthesizes_match_started_when_fixture_starts_mid_match(self, tmp_path, monkeypatch):
        # Real recordings can start a moment after the actual match-started
        # fired (recording turned on slightly late) — state.py only sets
        # game_mode/points_start/match_started from an actual match-started
        # event, so without one /tv would never leave "waiting for match".
        lines = [
            {"ts": "2026-01-01T10:00:00", "payload": {"event": "game-started", "game": {"mode": "X01", "pointsStart": "121"}}},
            {"ts": "2026-01-01T10:00:01", "payload": {"event": "dart1-thrown"}},
            {"ts": "2026-01-01T10:00:02", "payload": {"event": "match-won"}},
        ]
        p = tmp_path / "demo.jsonl"
        p.write_text("\n".join(json.dumps(l) for l in lines) + "\n")
        monkeypatch.setattr(dev_demo, "_X01_DEMO_FILE", str(p))

        received = []
        runner = DemoRunner(on_x01_event=received.append)
        runner._run_x01()
        assert received[0] == {"event": "match-started", "game": {"mode": "X01", "pointsStart": "121"}}
        assert received[1:] == [l["payload"] for l in lines]

    def test_no_synthetic_event_when_fixture_already_starts_with_match_started(self, x01_fixture):
        received = []
        runner = DemoRunner(on_x01_event=received.append)
        runner._run_x01()
        assert received == [l["payload"] for l in x01_fixture]

    def test_delay_derived_from_real_ts_deltas_and_clamped(self, tmp_path, monkeypatch):
        sleeps = []
        monkeypatch.setattr(dev_demo.time, "sleep", lambda d: sleeps.append(d))
        lines = [
            {"ts": "2026-01-01T10:00:00", "payload": {"event": "match-started"}},
            {"ts": "2026-01-01T10:00:01", "payload": {"event": "dart1-thrown"}},       # 1s real gap
            {"ts": "2026-01-01T10:00:01.050000", "payload": {"event": "dart2-thrown"}},  # 0.05s -> floored
            {"ts": "2026-01-01T10:05:00", "payload": {"event": "match-won"}},          # huge gap -> ceiled
        ]
        p = tmp_path / "demo.jsonl"
        p.write_text("\n".join(json.dumps(l) for l in lines) + "\n")
        monkeypatch.setattr(dev_demo, "_X01_DEMO_FILE", str(p))

        runner = DemoRunner(on_x01_event=lambda e: None)
        runner._run_x01()

        # Fixture already starts with match-started, so no synthetic-event
        # pause — sleeps correspond 1:1 to the 3 gaps between the 4 lines.
        assert sleeps[0] == pytest.approx(1.0, abs=0.01)
        assert sleeps[1] == dev_demo._X01_DEMO_MIN_DELAY_S
        assert sleeps[2] == dev_demo._X01_DEMO_MAX_DELAY_S

    def test_refuses_without_event_pipeline(self):
        runner = DemoRunner()
        started, error = runner.start_x01()
        assert started is False
        assert "unavailable" in error

    def test_refuses_while_real_match_in_progress(self, x01_fixture):
        state = GameState()
        state.match_started = True
        runner = DemoRunner(on_x01_event=lambda e: None, game_state=state)
        started, error = runner.start_x01()
        assert started is False
        assert "already in progress" in error

    def test_refuses_while_already_running(self, x01_fixture):
        runner = DemoRunner(on_x01_event=lambda e: None)
        assert runner._claim("x01") is True
        started, error = runner.start_x01()
        assert started is False
        assert "already running" in error

    def test_start_runs_in_background_and_releases(self, x01_fixture):
        runner = DemoRunner(on_x01_event=lambda e: None)
        started, error = runner.start_x01()
        assert started is True
        assert error is None
        _wait_until_idle(runner)
        assert runner.status() == {"running": False, "mode": None}


class TestEliminationDemo:
    def _controller(self):
        return EliminationController(NullMqttPublisher(), "autodarts")

    def test_scripted_match_reaches_a_winner(self):
        ctrl = self._controller()
        runner = DemoRunner(elim_ctrl=ctrl)
        runner._run_elimination()
        assert ctrl.game.state == "finished"
        assert ctrl.game.winner in dev_demo._ELIM_DEMO_PLAYERS
        assert runner.status() == {"running": False, "mode": None}

    def test_refuses_while_real_match_in_progress(self):
        ctrl = self._controller()
        ctrl.start(["real one", "real two"], 3)
        runner = DemoRunner(elim_ctrl=ctrl)
        started, error = runner.start_elimination()
        assert started is False
        assert "already in progress" in error

    def test_refuses_without_elim_ctrl(self):
        runner = DemoRunner()
        started, error = runner.start_elimination()
        assert started is False
        assert "unavailable" in error

    def test_start_runs_in_background_and_releases(self):
        ctrl = self._controller()
        runner = DemoRunner(elim_ctrl=ctrl)
        started, error = runner.start_elimination()
        assert started is True
        assert error is None
        _wait_until_idle(runner)
        assert runner.status() == {"running": False, "mode": None}
        assert ctrl.game.state == "finished"
