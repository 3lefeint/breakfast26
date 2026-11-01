import contextlib

import pytest
from breakfast.stats import StatsDB, StatsTracker


class FakeAudio:
    """Records play() calls; play succeeds only for keys in *available*."""

    def __init__(self, available):
        self.available = set(available)
        self.calls = []

    def play(self, name, prob=1.0, volume=1.0, channel=None, break_last=False):
        self.calls.append(name)
        return name in self.available

    def has_audio(self, name):
        return name in self.available

    def played(self):
        return [c for c in self.calls if c in self.available]

    def batch(self):
        # No-op: this double records every play() call in real time
        # regardless of batching, so callers using `with audio.batch():`
        # need no special handling here.
        return contextlib.nullcontext()


def drive(caller, evt, snapshot):
    """An event of the X01 stream the way the program handles it: the caller, then the scenes (the standard scenes make the
    calls of the lifecycle)."""
    from breakfast.scenes import SceneEngine, run_x01
    engine = getattr(caller, "_test_scenes", None)
    if engine is None:
        engine = caller._test_scenes = SceneEngine(None, audio=caller.audio)
        engine.ambient_volume = caller.ambient_volume
    run_x01(engine, caller, evt, snapshot)


@pytest.fixture
def db():
    return StatsDB(":memory:")


@pytest.fixture
def tracker(db):
    return StatsTracker(db)
