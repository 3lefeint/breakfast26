import pytest

from breakfast.audio_engine import AudioEngine


@pytest.fixture
def audio_dir(tmp_path):
    for name in ("matchon.mp3", "matchon+1.mp3", "matchon+2.mp3",
                 "ambient_gameon.mp3", "busted.mp3"):
        (tmp_path / name).write_bytes(b"")
    return tmp_path


@pytest.fixture
def engine(audio_dir):
    sent = []
    eng = AudioEngine(str(audio_dir), broadcast=sent.append)
    eng.sent = sent
    return eng


class TestPlay:
    def test_sends_instruction_for_existing_key(self, engine):
        assert engine.play("busted") is True
        assert len(engine.sent) == 1
        inst = engine.sent[0]
        assert inst["type"] == "sound"
        assert inst["file"] == "busted.mp3"
        assert inst["channel"] == "voice"
        assert inst["volume"] == 1.0
        assert inst["break_last"] is False

    def test_picks_random_variant(self, engine):
        engine.play("matchon")
        assert engine.sent[0]["file"] in ("matchon.mp3", "matchon+1.mp3", "matchon+2.mp3")

    def test_missing_key_returns_false(self, engine):
        assert engine.play("does_not_exist") is False
        assert engine.sent == []

    def test_prob_zero_never_plays(self, engine):
        assert engine.play("busted", prob=0.0) is False
        assert engine.sent == []

    def test_ambient_prefix_selects_ambient_channel(self, engine):
        engine.play("ambient_gameon")
        assert engine.sent[0]["channel"] == "ambient"

    def test_explicit_channel_overrides_prefix(self, engine):
        engine.play("ambient_gameon", channel="voice")
        assert engine.sent[0]["channel"] == "voice"

    def test_volume_and_break_last_passed_through(self, engine):
        engine.play("busted", volume=0.4, break_last=True)
        inst = engine.sent[0]
        assert inst["volume"] == 0.4
        assert inst["break_last"] is True

    def test_no_broadcast_wired_is_silent(self, audio_dir):
        eng = AudioEngine(str(audio_dir))
        assert eng.play("busted") is True   # file exists, just nowhere to send


class TestHasAudio:
    def test_true_for_existing_key(self, engine):
        assert engine.has_audio("busted") is True

    def test_false_for_unknown_key(self, engine):
        assert engine.has_audio("does_not_exist") is False

    def test_does_not_send_anything(self, engine):
        engine.has_audio("busted")
        assert engine.sent == []


class TestPlaySequence:
    def test_order_preserved(self, engine):
        engine.play_sequence("busted", "ambient_gameon")
        assert [i["file"] for i in engine.sent] == ["busted.mp3", "ambient_gameon.mp3"]

    def test_missing_keys_skipped(self, engine):
        engine.play_sequence("busted", "nope", "ambient_gameon")
        assert [i["file"] for i in engine.sent] == ["busted.mp3", "ambient_gameon.mp3"]


class TestSearchPath:
    """Multi-directory lookup: profile dir first, own set as per-key fallback."""

    @pytest.fixture
    def dirs(self, tmp_path):
        prof = tmp_path / "profile"
        own = tmp_path / "own"
        prof.mkdir()
        own.mkdir()
        # both have matchon (own also has a variant); only own has freipass
        (prof / "matchon.mp3").write_bytes(b"profile-matchon")
        (own / "matchon.mp3").write_bytes(b"own-matchon")
        (own / "matchon+1.mp3").write_bytes(b"own-matchon-1")
        (own / "freipass.mp3").write_bytes(b"own-freipass")
        return prof, own

    @pytest.fixture
    def multi(self, dirs):
        sent = []
        eng = AudioEngine([str(dirs[0]), str(dirs[1])], broadcast=sent.append)
        eng.sent = sent
        return eng

    def test_profile_key_shadows_own_set_completely(self, multi):
        # own set's matchon+1 variant must never be picked once the
        # profile has the key — no voice mixing within a key
        for _ in range(20):
            multi.play("matchon")
        assert all(i["file"] == "matchon.mp3" for i in multi.sent)

    def test_missing_key_falls_back_to_own_set(self, multi):
        assert multi.play("freipass") is True
        assert multi.sent[0]["file"] == "freipass.mp3"

    def test_resolve_prefers_profile_for_shadowed_name(self, multi, dirs):
        prof, own = dirs
        assert multi.resolve("matchon.mp3") == str(prof / "matchon.mp3")

    def test_resolve_falls_back_for_own_only_names(self, multi, dirs):
        prof, own = dirs
        assert multi.resolve("freipass.mp3") == str(own / "freipass.mp3")
        assert multi.resolve("matchon+1.mp3") == str(own / "matchon+1.mp3")

    def test_single_string_still_accepted(self, dirs):
        eng = AudioEngine(str(dirs[1]))
        assert eng.dirs == [str(dirs[1])]


class TestBatch:
    def test_batches_into_single_message(self, engine):
        with engine.batch():
            engine.play("busted")
            engine.play("ambient_gameon")
        assert len(engine.sent) == 1
        inst = engine.sent[0]
        assert inst["type"] == "sound_batch"
        assert [i["file"] for i in inst["items"]] == ["busted.mp3", "ambient_gameon.mp3"]
        assert all({"file", "channel", "volume", "break_last"} <= set(i) for i in inst["items"])

    def test_play_return_value_unaffected_by_batch(self, engine):
        with engine.batch():
            assert engine.play("busted") is True
            assert engine.play("does_not_exist") is False

    def test_empty_batch_sends_nothing(self, engine):
        with engine.batch():
            engine.play("does_not_exist")
        assert engine.sent == []

    def test_reentrant_batch_flushes_once(self, engine):
        with engine.batch():
            engine.play("busted")
            with engine.batch():
                engine.play("ambient_gameon")
            engine.play("busted")
        assert len(engine.sent) == 1
        assert [i["file"] for i in engine.sent[0]["items"]] == \
            ["busted.mp3", "ambient_gameon.mp3", "busted.mp3"]

    def test_batch_message_carries_version(self, engine):
        with engine.batch():
            engine.play("busted")
        assert engine.sent[0]["v"] == engine.version

    def test_non_batched_message_also_carries_version(self, engine):
        engine.play("busted")
        assert engine.sent[0]["v"] == engine.version


class TestVersion:
    def test_same_dir_same_version(self, audio_dir):
        assert AudioEngine(str(audio_dir)).version == AudioEngine(str(audio_dir)).version

    def test_different_dir_different_version(self, audio_dir, tmp_path):
        other = tmp_path / "other"
        other.mkdir()
        assert AudioEngine(str(audio_dir)).version != AudioEngine(str(other)).version


class TestResolve:
    def test_known_file(self, engine, audio_dir):
        assert engine.resolve("busted.mp3") == str(audio_dir / "busted.mp3")

    def test_variant_file(self, engine, audio_dir):
        assert engine.resolve("matchon+2.mp3") == str(audio_dir / "matchon+2.mp3")

    def test_unknown_file(self, engine):
        assert engine.resolve("nope.mp3") is None

    def test_path_traversal_rejected(self, engine):
        assert engine.resolve("../secrets.mp3") is None
        assert engine.resolve("..") is None
        assert engine.resolve("sub/file.mp3") is None
        assert engine.resolve("sub\\file.mp3") is None

    def test_directory_rejected(self, engine, audio_dir):
        (audio_dir / "adir.mp3").mkdir()
        assert engine.resolve("adir.mp3") is None
