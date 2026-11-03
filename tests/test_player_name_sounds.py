import pytest
from starlette.testclient import TestClient

from breakfast.audio_engine import AudioEngine
from breakfast.stats import StatsDB, StatsTracker
from breakfast.web import server

MP3 = b"ID3" + b"\x00" * 64


@pytest.fixture
def db(tmp_path):
    db = StatsDB(str(tmp_path / "s.db"))
    for name in ("ana", "ben"):
        db.upsert_player(name)
    return db


@pytest.fixture
def engine(tmp_path, db):
    pack = tmp_path / "pack"
    library = pack / "scenes"
    library.mkdir(parents=True)
    (pack / "ana.mp3").write_bytes(b"")
    for name in ("ana-1.mp3", "ana-2.mp3", "ben-1.mp3"):
        (library / name).write_bytes(MP3)
    sent = []
    eng = AudioEngine(str(pack), broadcast=sent.append, library_dirs=[str(library)])
    eng.player_sounds = lambda name: db.player_sounds().get(name, [])
    eng.sent = sent
    return eng


class TestStored:
    def test_a_player_has_no_sounds_until_some_are_set(self, db):
        assert db.player_sounds() == {}

    def test_the_sounds_are_replaced_and_keep_their_order(self, db):
        assert db.set_player_sounds("ana", ["b.mp3", "a.mp3"]) is True
        assert db.player_sounds() == {"ana": ["b.mp3", "a.mp3"]}
        assert db.set_player_sounds("ana", ["c.mp3"]) is True
        assert db.player_sounds() == {"ana": ["c.mp3"]}
        assert db.set_player_sounds("ana", []) is True
        assert db.player_sounds() == {}

    def test_an_unknown_player_is_reported(self, db):
        assert db.set_player_sounds("nobody", ["a.mp3"]) is False
        assert db.player_sounds() == {}

    def test_a_renamed_library_file_is_followed(self, db):
        db.set_player_sounds("ana", ["a.mp3", "b.mp3"])
        db.set_player_sounds("ben", ["a.mp3"])
        db.rename_player_sound_file("a.mp3", "z.mp3")
        assert db.player_sounds() == {"ana": ["z.mp3", "b.mp3"], "ben": ["z.mp3"]}

    def test_renaming_onto_a_file_the_player_has_keeps_it_once(self, db):
        db.set_player_sounds("ana", ["a.mp3", "z.mp3"])
        db.rename_player_sound_file("a.mp3", "z.mp3")
        assert db.player_sounds() == {"ana": ["z.mp3"]}

    def test_deleting_a_player_removes_the_sounds(self, db):
        db.set_player_sounds("ana", ["a.mp3"])
        db.set_player_sounds("ben", ["b.mp3"])
        db.delete_player("ana")
        assert db.player_sounds() == {"ben": ["b.mp3"]}

    def test_merging_moves_the_sounds_and_keeps_one_of_a_shared_file(self, db):
        db.set_player_sounds("ana", ["a.mp3", "shared.mp3"])
        db.set_player_sounds("ben", ["shared.mp3", "b.mp3"])
        assert "error" not in db.merge_players("ana", "ben")
        assert sorted(db.player_sounds()["ben"]) == ["a.mp3", "b.mp3", "shared.mp3"]
        assert list(db.player_sounds()) == ["ben"]


class TestPlayName:
    def test_assigned_sounds_and_the_voice_pack_file_share_one_pool(self, db, engine):
        db.set_player_sounds("ana", ["ana-1.mp3", "ana-2.mp3"])
        for _ in range(120):
            engine.play_name("ana")
        files = [m["file"] for m in engine.sent]
        assert set(files) == {"ana.mp3", "ana-1.mp3", "ana-2.mp3"}
        assert all(20 <= files.count(f) for f in set(files))      # each about a third

    def test_only_an_assigned_sound_plays_when_the_voice_pack_has_no_file(self, db, engine):
        db.set_player_sounds("ben", ["ben-1.mp3"])
        assert engine.play_name("ben") is True
        assert [m["file"] for m in engine.sent] == ["ben-1.mp3"]

    def test_without_an_assignment_the_voice_pack_file_plays(self, engine):
        assert engine.play_name("ana") is True
        assert [m["file"] for m in engine.sent] == ["ana.mp3"]

    def test_a_missing_library_file_is_left_out(self, db, engine):
        db.set_player_sounds("ana", ["gone.mp3"])
        assert engine.play_name("ana") is True
        assert [m["file"] for m in engine.sent] == ["ana.mp3"]

    def test_a_name_with_nothing_returns_false(self, engine):
        assert engine.play_name("carl") is False
        assert engine.sent == []

    def test_the_channel_and_volume_are_passed_on(self, db, engine):
        db.set_player_sounds("ana", ["ana-1.mp3"])
        engine.play_name("ana", channel="ambient", volume=0.5)
        assert engine.sent[0]["channel"] == "ambient" and engine.sent[0]["volume"] == 0.5

    def test_has_name_audio_counts_an_assignment(self, db, engine):
        assert engine.has_name_audio("ben") is False
        db.set_player_sounds("ben", ["ben-1.mp3"])
        assert engine.has_name_audio("ben") is True
        assert engine.has_name_audio("ana") is True      # the voice-pack file

    def test_without_a_provider_nothing_is_assigned(self, tmp_path):
        eng = AudioEngine(str(tmp_path))
        assert eng.name_files("ana") == []


class TestEndpoints:
    @pytest.fixture
    def client(self, db, engine):
        server.wire(None, None, stats_tracker=StatsTracker(db), audio_engine=engine)
        yield TestClient(server.app)
        server.wire(None, None)

    def test_the_sounds_and_the_library_are_listed(self, client, db):
        db.set_player_sounds("ana", ["ana-1.mp3"])
        body = client.get("/api/players/sounds").json()
        assert body["sounds"] == {"ana": ["ana-1.mp3"]}
        assert body["files"] == ["ana-1.mp3", "ana-2.mp3", "ben-1.mp3"]

    def test_the_sounds_of_a_player_are_set(self, client, db):
        res = client.put("/api/players/ana/sounds", json={"files": ["ana-2.mp3", "ana-1.mp3", "ana-2.mp3"]}).json()
        assert res == {"ok": True, "files": ["ana-2.mp3", "ana-1.mp3"]}
        assert db.player_sounds() == {"ana": ["ana-2.mp3", "ana-1.mp3"]}

    def test_a_file_that_is_not_in_the_library_is_refused(self, client, db):
        assert client.put("/api/players/ana/sounds", json={"files": ["nope.mp3"]}).json() == {"error": "not a sound of the library"}
        assert db.player_sounds() == {}

    def test_an_unknown_player_is_refused(self, client):
        assert "error" in client.put("/api/players/nobody/sounds", json={"files": ["ana-1.mp3"]}).json()

    def test_the_name_is_taken_in_lower_case(self, client, db):
        client.put("/api/players/ANA/sounds", json={"files": ["ana-1.mp3"]})
        assert db.player_sounds() == {"ana": ["ana-1.mp3"]}

    def test_renaming_a_library_file_moves_the_assignment(self, client, db):
        db.set_player_sounds("ana", ["ana-1.mp3"])
        assert client.post("/api/scenes/sounds/ana-1.mp3/rename", json={"name": "ana-first.mp3"}).json()["ok"]
        assert db.player_sounds() == {"ana": ["ana-first.mp3"]}

    def test_a_player_with_a_sound_is_not_reported_as_missing_audio(self, client, db, engine):
        db.set_player_sounds("ben", ["ben-1.mp3"])
        state = client.get("/api/state").json()
        assert "ben" not in state["players_missing_audio"]


class TestScenes:
    def test_the_player_of_a_call_step_picks_from_the_voice_pack_and_the_assigned_sounds(self, db, engine):
        from breakfast.scenes import SceneEngine
        db.set_player_sounds("ana", ["ana-2.mp3"])
        scenes = SceneEngine(None, audio=engine)
        for _ in range(40):
            assert scenes._call("{player}", {"player": "ANA"}) is True
        assert {m["file"] for m in engine.sent} == {"ana.mp3", "ana-2.mp3"}

    def test_a_player_without_anything_plays_unknown_player(self, engine, tmp_path):
        from breakfast.scenes import SceneEngine
        (tmp_path / "pack" / "unknown_player.mp3").write_bytes(b"")
        assert SceneEngine(None, audio=engine)._call("{player}", {"player": "carl"}) is True
        assert [m["file"] for m in engine.sent] == ["unknown_player.mp3"]
