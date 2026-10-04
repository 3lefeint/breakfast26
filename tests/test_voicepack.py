import os
import zipfile

import pytest

from breakfast.voicepack import install_profile, list_profiles, search_dirs


def build_pack(path):
    """Synthetic pack in the darts-caller format: outer zip containing a
    nested sounds zip + a ;-separated CSV template (with BOM, like the real
    ones). Sorted sound order: a.mp3, b.mp3, c.mp3, d.mp3."""
    inner = str(path) + ".inner.zip"
    with zipfile.ZipFile(inner, "w") as z:
        z.writestr("sounds/a.mp3", b"sound-a")   # row 1: plain "0" -> key 0
        z.writestr("sounds/b.mp3", b"sound-b")   # row 2: gameon AND matchon
        z.writestr("sounds/c.mp3", b"sound-c")   # row 3: gameon again -> gameon+1
        z.writestr("sounds/d.mp3", b"sound-d")   # row 4: busted
    csv_text = "﻿0;;\nLet's play!;gameon;matchon;\nGame on!;gameon;\nBusted!;busted;\n"
    with zipfile.ZipFile(path, "w") as z:
        z.write(inner, "en-US-test.zip")
        z.writestr("en-US-v1.csv", csv_text.encode("utf-8"))
    os.remove(inner)


class TestSearchDirs:
    def test_no_profile_is_own_dir_and_the_achievement_sounds(self, tmp_path):
        assert search_dirs(str(tmp_path)) == [str(tmp_path), str(tmp_path / "achievements")]

    def test_profile_searched_first(self, tmp_path):
        prof = tmp_path / "profiles" / "en-US-Joey-Male"
        prof.mkdir(parents=True)
        assert search_dirs(str(tmp_path), "en-US-Joey-Male") == \
            [str(prof), str(tmp_path), str(tmp_path / "achievements")]

    def test_missing_profile_falls_back_to_own_dir(self, tmp_path):
        assert search_dirs(str(tmp_path), "nope") == [str(tmp_path), str(tmp_path / "achievements")]


class TestInstallProfile:
    @pytest.fixture
    def pack(self, tmp_path):
        p = tmp_path / "pack.zip"
        build_pack(str(p))
        return str(p)

    @pytest.fixture
    def audio_dir(self, tmp_path):
        d = tmp_path / "sounds"
        d.mkdir()
        return str(d)

    def test_install_maps_rows_to_sorted_sounds(self, audio_dir, pack):
        dest = install_profile(audio_dir, "test-voice", url=pack)
        files = sorted(os.listdir(dest))
        assert files == ["0.mp3", "busted.mp3", "gameon+1.mp3", "gameon.mp3",
                         "matchon.mp3"]
        # multi-key row: same sound copied to both keys
        with open(os.path.join(dest, "gameon.mp3"), "rb") as f:
            assert f.read() == b"sound-b"
        with open(os.path.join(dest, "matchon.mp3"), "rb") as f:
            assert f.read() == b"sound-b"
        # duplicate key becomes a +1 variant
        with open(os.path.join(dest, "gameon+1.mp3"), "rb") as f:
            assert f.read() == b"sound-c"

    def test_installed_pack_found_by_search_dirs(self, audio_dir, pack):
        dest = install_profile(audio_dir, "test-voice", url=pack)
        assert search_dirs(audio_dir, "test-voice") == [dest, audio_dir, os.path.join(audio_dir, "achievements")]
        assert list_profiles(audio_dir) == ["test-voice"]

    def test_already_installed_skips(self, audio_dir, pack):
        dest = install_profile(audio_dir, "test-voice", url=pack)
        marker = os.path.join(dest, "marker")
        open(marker, "w").close()
        install_profile(audio_dir, "test-voice", url=pack)   # no-op
        assert os.path.exists(marker)

    def test_force_reinstalls(self, audio_dir, pack):
        dest = install_profile(audio_dir, "test-voice", url=pack)
        marker = os.path.join(dest, "marker")
        open(marker, "w").close()
        install_profile(audio_dir, "test-voice", url=pack, force=True)
        assert not os.path.exists(marker)

    def test_unknown_name_without_url_raises(self, audio_dir):
        with pytest.raises(ValueError):
            install_profile(audio_dir, "not-in-catalog")

    def test_empty_pack_raises(self, audio_dir, tmp_path):
        empty = tmp_path / "empty.zip"
        with zipfile.ZipFile(empty, "w") as z:
            z.writestr("nothing.txt", b"")
        with pytest.raises(RuntimeError):
            install_profile(audio_dir, "test-voice", url=str(empty))


class TestListProfiles:
    def test_empty_without_profiles_dir(self, tmp_path):
        assert list_profiles(str(tmp_path)) == []

    def test_lists_sorted_directories_only(self, tmp_path):
        base = tmp_path / "profiles"
        (base / "b-voice").mkdir(parents=True)
        (base / "a-voice").mkdir()
        (base / "stray.mp3").write_bytes(b"")
        assert list_profiles(str(tmp_path)) == ["a-voice", "b-voice"]
