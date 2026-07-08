import asyncio

import pytest

from tools import generate_voicepack as gv


def _plan(n=3):
    return {
        "voice": "de-CH-LeniNeural",
        "group": [
            {
                "name": "Test",
                "keys": {f"key{i}": f"text {i}" for i in range(n)},
            }
        ],
    }


@pytest.fixture(autouse=True)
def _fake_synthesize(monkeypatch):
    # Never hit the real edge-tts/ffmpeg — just create the destination file
    # so the existence-based skip logic still works across test scenarios.
    async def fake(voice, text, rate, pitch, volume, dest, trim):
        dest.write_bytes(b"fake mp3")
    monkeypatch.setattr(gv, "synthesize", fake)


class TestOnProgress:
    def test_callback_fires_once_per_entry_with_cumulative_counts(self, tmp_path):
        calls = []
        asyncio.run(gv.run(
            _plan(3), tmp_path, only=None, force=False, dry_run=False, trim=True,
            on_progress=lambda done, skipped, total: calls.append((done, skipped, total)),
        ))
        assert len(calls) == 3
        assert all(total == 3 for _, _, total in calls)
        assert {done for done, _, _ in calls} == {1, 2, 3}
        assert {skipped for _, skipped, _ in calls} == {0}

    def test_skipped_entries_trigger_callback_too(self, tmp_path):
        for i in range(3):
            (tmp_path / f"key{i}.mp3").write_bytes(b"already exists")

        calls = []
        asyncio.run(gv.run(
            _plan(3), tmp_path, only=None, force=False, dry_run=False, trim=True,
            on_progress=lambda done, skipped, total: calls.append((done, skipped, total)),
        ))
        assert len(calls) == 3
        assert {done for done, _, _ in calls} == {0}
        assert {skipped for _, skipped, _ in calls} == {1, 2, 3}

    def test_force_regenerates_existing_files(self, tmp_path):
        for i in range(3):
            (tmp_path / f"key{i}.mp3").write_bytes(b"stale content")

        calls = []
        asyncio.run(gv.run(
            _plan(3), tmp_path, only=None, force=True, dry_run=False, trim=True,
            on_progress=lambda done, skipped, total: calls.append((done, skipped, total)),
        ))
        assert {done for done, _, _ in calls} == {1, 2, 3}
        assert {skipped for _, skipped, _ in calls} == {0}

    def test_no_callback_does_not_raise(self, tmp_path):
        asyncio.run(gv.run(_plan(2), tmp_path, only=None, force=False, dry_run=False, trim=True))
        assert (tmp_path / "key0.mp3").exists()
        assert (tmp_path / "key1.mp3").exists()
