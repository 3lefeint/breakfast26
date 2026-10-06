from breakfast.voicepack import list_profiles, search_dirs


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


class TestListProfiles:
    def test_empty_without_profiles_dir(self, tmp_path):
        assert list_profiles(str(tmp_path)) == []

    def test_lists_sorted_directories_only(self, tmp_path):
        base = tmp_path / "profiles"
        (base / "b-voice").mkdir(parents=True)
        (base / "a-voice").mkdir()
        (base / "stray.mp3").write_bytes(b"")
        assert list_profiles(str(tmp_path)) == ["a-voice", "b-voice"]
