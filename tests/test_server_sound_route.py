import asyncio

from breakfast.audio_engine import AudioEngine
from breakfast.web import server


def test_get_sound_sets_long_lived_cache_control(tmp_path):
    (tmp_path / "busted.mp3").write_bytes(b"x")
    engine = AudioEngine(str(tmp_path))
    server.wire(None, None, audio_engine=engine)
    try:
        resp = asyncio.run(server.get_sound("busted.mp3", v=engine.version))
        assert resp.headers["cache-control"] == "public, max-age=31536000, immutable"
    finally:
        server.wire(None, None)


def test_get_sound_v_param_is_optional(tmp_path):
    (tmp_path / "busted.mp3").write_bytes(b"x")
    engine = AudioEngine(str(tmp_path))
    server.wire(None, None, audio_engine=engine)
    try:
        resp = asyncio.run(server.get_sound("busted.mp3"))
        assert resp.headers["cache-control"] == "public, max-age=31536000, immutable"
    finally:
        server.wire(None, None)
