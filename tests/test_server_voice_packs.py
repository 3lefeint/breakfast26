import asyncio

from breakfast import config as cfg_mod
from breakfast.web import server


def test_no_config_path_returns_empty_list():
    server.wire(None, None)
    try:
        res = asyncio.run(server.get_voice_packs())
        assert res == {"profiles": []}
    finally:
        server.wire(None, None)


def test_no_audio_dir_configured_returns_empty_list(tmp_path):
    config_path = tmp_path / "config.toml"
    cfg_mod.write(str(config_path), {})
    server.wire(None, None, config_path=str(config_path))
    try:
        res = asyncio.run(server.get_voice_packs())
        assert res == {"profiles": []}
    finally:
        server.wire(None, None)


def test_lists_installed_profiles_sorted(tmp_path):
    audio_dir = tmp_path / "sounds"
    profiles_dir = audio_dir / "profiles"
    (profiles_dir / "en-US-Joey-Male").mkdir(parents=True)
    (profiles_dir / "de-CH-LeniNeural").mkdir(parents=True)
    (profiles_dir / "not_a_profile.txt").write_text("x")  # a file, not a dir — must be ignored

    config_path = tmp_path / "config.toml"
    cfg_mod.write(str(config_path), {"audio": {"dir": str(audio_dir)}})
    server.wire(None, None, config_path=str(config_path))
    try:
        res = asyncio.run(server.get_voice_packs())
        assert res == {"profiles": ["de-CH-LeniNeural", "en-US-Joey-Male"]}
    finally:
        server.wire(None, None)
