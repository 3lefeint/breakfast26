"""Integration: recorded session -> GameState -> Caller -> AudioEngine.

Uses the real recorded session and the real sound inventory when present
(both are gitignored, so these tests skip on checkouts without them).
"""

import json
import os

import pytest

from breakfast.audio_engine import AudioEngine
from breakfast.caller import from_config
from breakfast.state import GameState

SESSION = os.path.join(os.path.dirname(__file__), "..", "sessions", "test.jsonl")
SOUNDS = os.path.join(os.path.dirname(__file__), "..", "sounds")

pytestmark = pytest.mark.skipif(
    not (os.path.isfile(SESSION) and os.path.isdir(SOUNDS)),
    reason="recorded session or sound inventory not present",
)


@pytest.fixture
def played():
    instructions = []
    engine = AudioEngine(SOUNDS, broadcast=instructions.append)
    caller = from_config(engine)
    state = GameState()
    with open(SESSION) as f:
        for line in f:
            data = json.loads(line)["payload"]
            evt = state.update(data)
            caller.on_event(evt, state.snapshot())
    return [i["file"] for i in instructions]


class TestRecordedSession:
    def test_produces_calls(self, played):
        assert len(played) > 20

    def test_lifecycle_calls_present(self, played):
        assert any(p.startswith("matchon") for p in played)
        assert any(p.startswith("matchshot") for p in played)
        assert any(p.startswith("busted") for p in played)

    def test_checkout_calls_present(self, played):
        assert any(p.startswith("you_require") for p in played)

    def test_require_namespace_never_leaks_plain_numbers(self, played):
        # With no require_* files installed, a you_require call must not be
        # followed by anything in the same instruction batch — the number is
        # skipped, never replaced by the achieved-score file. Verified at
        # unit level too (test_caller_x01); here we just assert no
        # require_* file was invented from the plain-number namespace.
        assert not any(p.startswith("require_") for p in played)

    def test_per_dart_and_totals_present(self, played):
        # singles are announced via plain numbers; misses via m-fields
        assert any(p.split("+")[0].rstrip(".mp3").isdigit() for p in played)
        assert any(p.startswith("m") and p[1].isdigit() for p in played)