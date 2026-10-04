import pytest
from starlette.testclient import TestClient

from breakfast import achievement_sounds as snd
from breakfast import config as cfg_mod
from breakfast.achievements import ACHIEVEMENTS, AchievementEngine
from breakfast.audio_engine import AudioEngine
from breakfast.stats import StatsDB
from breakfast.web import server

MP3 = b"ID3\x04\x00\x00\x00\x00\x00\x00" + b"\x00" * 64


@pytest.fixture
def sounds(tmp_path):
    """A sound directory with a general jingle and one for ton_up, and an engine over it."""
    base = tmp_path / "sounds"
    folder = base / "achievements"
    folder.mkdir(parents=True)
    for name in ("achievement.mp3", "achievement_ton_up.mp3", "fanfare.mp3", "party.mp3"):
        (folder / name).write_bytes(MP3)
    (base / "matchon.mp3").write_bytes(MP3)
    sent = []
    engine = AudioEngine([str(base), str(folder)], broadcast=sent.append)
    return engine, folder, base, sent


class TestAssignments:
    def test_a_file_name_or_a_list_is_read_as_a_list(self):
        cfg = {"achievements": {"sounds": {"a": "x.mp3", "b": ["y.mp3", "z.mp3"], "c": [], "d": [1]}}}
        assert snd.assignments(cfg) == {"a": ["x.mp3"], "b": ["y.mp3", "z.mp3"]}

    def test_no_section_is_no_assignment(self):
        assert snd.assignments({}) == {} and snd.assignments({"achievements": {}}) == {}


class TestFiles:
    def test_the_mp3_files_of_the_achievements_folder_are_listed(self, sounds):
        engine, folder, _, _ = sounds
        (folder / "notes.txt").write_text("x")
        assert snd.files(engine) == ["achievement.mp3", "achievement_ton_up.mp3", "fanfare.mp3", "party.mp3"]

    def test_a_file_that_a_folder_before_it_shadows_is_not_playable(self, sounds):
        engine, folder, base, _ = sounds
        (base / "fanfare.mp3").write_bytes(MP3)         # same name in the main folder, searched first
        assert snd.playable(engine, "party.mp3") and not snd.playable(engine, "fanfare.mp3")

    def test_a_file_that_is_not_there_is_not_playable(self, sounds):
        assert not snd.playable(sounds[0], "nope.mp3") and not snd.playable(sounds[0], "matchon.mp3")

    def test_without_a_sound_directory_there_is_nothing(self):
        engine = AudioEngine(["/nonexistent/sounds"])
        assert snd.sound_dir(engine) is None and snd.files(engine) == []


class TestPlaysNow:
    def test_an_assignment_wins(self, sounds):
        cfg = {"achievements": {"sounds": {"ton_up": ["fanfare.mp3", "party.mp3"]}}}
        assert snd.plays_now(sounds[0], cfg, "ton_up") == {"source": "assigned", "files": ["fanfare.mp3", "party.mp3"]}

    def test_the_file_name_convention_comes_next_then_the_general_sound(self, sounds):
        assert snd.plays_now(sounds[0], {}, "ton_up") == {"source": "id", "files": ["achievement_ton_up.mp3"]}
        assert snd.plays_now(sounds[0], {}, "bullseye") == {"source": "generic", "files": ["achievement.mp3"]}

    def test_without_any_file_nothing_plays(self, sounds):
        engine, folder, _, _ = sounds
        (folder / "achievement.mp3").unlink()
        engine.invalidate("achievement")
        assert snd.plays_now(engine, {}, "bullseye") == {"source": "none", "files": []}

    def test_an_assignment_to_a_missing_file_falls_back(self, sounds):
        cfg = {"achievements": {"sounds": {"ton_up": ["gone.mp3"]}}}
        assert snd.plays_now(sounds[0], cfg, "ton_up")["source"] == "id"
        data = snd.overview(sounds[0], cfg, ACHIEVEMENTS)
        entry = next(a for a in data["achievements"] if a["id"] == "ton_up")
        assert entry["assigned"] == ["gone.mp3"] and entry["missing"] == ["gone.mp3"]

    def test_the_overview_lists_every_achievement_with_its_files(self, sounds):
        data = snd.overview(sounds[0], {}, ACHIEVEMENTS)
        assert len(data["achievements"]) == len(ACHIEVEMENTS) and "fanfare.mp3" in data["files"]
        entry = next(a for a in data["achievements"] if a["id"] == "maximum_collector")
        assert entry["tiers"] == [10, 100, 1000] and entry["names"]["en"] == "Maximum Collector"


class TestStoring:
    def test_an_assignment_is_written_and_cleared(self, tmp_path):
        path = tmp_path / "config.toml"
        path.write_text('[web]\nport = 8080\n')
        assert snd.set_assignment(path, "ton_up", ["fanfare.mp3", "party.mp3"]) == ["fanfare.mp3", "party.mp3"]
        assert cfg_mod.load(path)["achievements"]["sounds"] == {"ton_up": ["fanfare.mp3", "party.mp3"]}
        assert cfg_mod.load(path)["web"]["port"] == 8080
        snd.set_assignment(path, "bullseye", ["party.mp3"])
        snd.set_assignment(path, "ton_up", [])
        assert cfg_mod.load(path)["achievements"]["sounds"] == {"bullseye": ["party.mp3"]}
        snd.set_assignment(path, "bullseye", [])
        assert "sounds" not in cfg_mod.load(path).get("achievements", {})


class TestUpload:
    @pytest.mark.parametrize("name, data, problem", [
        ("../x.mp3", MP3, "name"), ("x.wav", MP3, "name"), ("", MP3, "name"), (".mp3", MP3, "name"),
        ("x.mp3", b"", "empty"), ("x.mp3", b"hello world", "mp3"),
        ("x.mp3", MP3 + b"\x00" * (snd.MAX_UPLOAD_BYTES + 1), "larger"),
        ("fanfare.mp3", MP3, "exists"), ("matchon.mp3", MP3, "exists"),
    ])
    def test_what_is_refused(self, sounds, name, data, problem):
        assert problem in snd.check_upload(sounds[0], name, data)

    def test_an_mp3_is_saved_and_a_convention_name_is_found_at_once(self, sounds):
        engine, folder, _, _ = sounds
        assert snd.plays_now(engine, {}, "bullseye")["source"] == "generic"
        assert snd.save_upload(engine, "achievement_bullseye.mp3", MP3) is None
        assert (folder / "achievement_bullseye.mp3").exists()
        assert snd.plays_now(engine, {}, "bullseye")["source"] == "id"

    def test_a_frame_sync_header_without_tags_is_an_mp3_too(self, sounds):
        assert snd.check_upload(sounds[0], "raw.mp3", b"\xff\xfb\x90\x00" + b"\x00" * 32) is None


class TestManageFiles:
    @pytest.fixture
    def config(self, tmp_path):
        path = tmp_path / "config.toml"
        path.write_text('[achievements.sounds]\nton_up = ["fanfare.mp3", "party.mp3"]\nbullseye = ["fanfare.mp3"]\n')
        return path

    def test_a_file_can_be_renamed_and_the_assignments_follow(self, sounds, config):
        engine, folder, _, _ = sounds
        assert snd.rename_file(engine, config, "fanfare.mp3", "tada.mp3") is None
        assert (folder / "tada.mp3").exists() and not (folder / "fanfare.mp3").exists()
        assert snd.assignments(cfg_mod.load(config)) == {"ton_up": ["tada.mp3", "party.mp3"], "bullseye": ["tada.mp3"]}
        assert snd.playable(engine, "tada.mp3") and not snd.playable(engine, "fanfare.mp3")

    def test_a_rename_to_the_convention_name_is_found_at_once(self, sounds, config):
        engine = sounds[0]
        assert snd.plays_now(engine, {}, "bullseye")["source"] == "generic"
        assert snd.rename_file(engine, config, "party.mp3", "achievement_bullseye.mp3") is None
        assert snd.plays_now(engine, {}, "bullseye")["source"] == "id"

    @pytest.mark.parametrize("old, new, problem", [
        ("nope.mp3", "x.mp3", "not a sound"), ("matchon.mp3", "x.mp3", "not a sound"),
        ("fanfare.mp3", "party.mp3", "exists"), ("fanfare.mp3", "matchon.mp3", "exists"),
        ("fanfare.mp3", "fanfare.mp3", "same"), ("fanfare.mp3", "../x.mp3", "name"),
        ("fanfare.mp3", "x.wav", "name"), ("fanfare.mp3", "", "name"),
    ])
    def test_what_a_rename_refuses(self, sounds, config, old, new, problem):
        assert problem in snd.rename_file(sounds[0], config, old, new)
        assert snd.assignments(cfg_mod.load(config))["bullseye"] == ["fanfare.mp3"]

    def test_a_file_can_be_deleted_and_leaves_the_assignments(self, sounds, config):
        engine, folder, _, _ = sounds
        assert snd.delete_file(engine, config, "fanfare.mp3") is None
        assert not (folder / "fanfare.mp3").exists()
        assert snd.assignments(cfg_mod.load(config)) == {"ton_up": ["party.mp3"]}

    def test_deleting_the_last_file_of_the_last_assignment_removes_the_table(self, sounds, tmp_path):
        engine = sounds[0]
        path = tmp_path / "c.toml"
        path.write_text('[achievements.sounds]\nton_up = ["party.mp3"]\n')
        assert snd.delete_file(engine, path, "party.mp3") is None
        assert "sounds" not in cfg_mod.load(path).get("achievements", {})

    def test_what_a_delete_refuses(self, sounds, config):
        assert "not a sound" in snd.delete_file(sounds[0], config, "matchon.mp3")
        assert "not a sound" in snd.delete_file(sounds[0], config, "../config.toml")
        assert (sounds[2] / "matchon.mp3").exists()

    def test_the_overview_tells_where_a_file_is_used_and_how_big_it_is(self, sounds, config):
        data = snd.overview(sounds[0], cfg_mod.load(config), ACHIEVEMENTS)
        by = {f["name"]: f for f in data["file_details"]}
        assert [u["id"] for u in by["fanfare.mp3"]["used_by"]] == ["ton_up", "bullseye"]
        assert by["fanfare.mp3"]["used_by"][0]["names"]["en"] == "Ton Up"
        assert by["party.mp3"]["size"] == len(MP3)
        assert [u["id"] for u in by["party.mp3"]["used_by"]] == ["ton_up"]


class TestPlayFile:
    def test_a_file_is_sent_by_name(self, sounds):
        engine, _, _, sent = sounds
        assert engine.play_file("fanfare.mp3") is True
        assert sent[0]["type"] == "sound" and sent[0]["file"] == "fanfare.mp3"

    def test_an_unknown_file_is_not_sent(self, sounds):
        engine, _, _, sent = sounds
        assert engine.play_file("nope.mp3") is False and sent == []

    def test_inside_a_batch_it_joins_the_batch(self, sounds):
        engine, _, _, sent = sounds
        with engine.batch():
            engine.play_file("fanfare.mp3")
            engine.play("matchon")
        assert len(sent) == 1 and sent[0]["type"] == "sound_batch"
        assert [i["file"] for i in sent[0]["items"]] == ["fanfare.mp3", "matchon.mp3"]


class TestUnlockSound:
    def _earn(self, sounds, assigned):
        engine = sounds[0]
        pushed = []
        db = StatsDB(":memory:")
        ach = AchievementEngine(db).announce(pushed.append, engine, sounds=(lambda a: assigned.get(a, [])) if assigned is not None else None)
        ach.on_earned({"player": "ana", "achievement": "ton_up", "tier": 1})
        return pushed

    def test_an_assigned_file_plays_instead_of_the_file_name_convention(self, sounds):
        self._earn(sounds, {"ton_up": ["fanfare.mp3"]})
        assert [m["file"] for m in sounds[3]] == ["fanfare.mp3"]

    def test_one_of_several_assigned_files_plays(self, sounds):
        self._earn(sounds, {"ton_up": ["fanfare.mp3", "party.mp3"]})
        assert len(sounds[3]) == 1 and sounds[3][0]["file"] in ("fanfare.mp3", "party.mp3")

    def test_without_an_assignment_the_convention_still_works(self, sounds):
        self._earn(sounds, {})
        assert [m["file"] for m in sounds[3]] == ["achievement_ton_up.mp3"]
        sounds[3].clear()
        self._earn(sounds, None)
        assert [m["file"] for m in sounds[3]] == ["achievement_ton_up.mp3"]

    def test_an_assigned_file_that_cannot_play_falls_back(self, sounds):
        self._earn(sounds, {"ton_up": ["gone.mp3"]})
        assert [m["file"] for m in sounds[3]] == ["achievement_ton_up.mp3"]


@pytest.fixture
def client(sounds, tmp_path):
    engine = sounds[0]
    config = tmp_path / "config.toml"
    config.write_text("[web]\nport = 8080\n")
    server.wire(None, None, audio_engine=engine, config_path=str(config))
    server._dev_unlocked = False
    yield TestClient(server.app), engine, config
    server._dev_unlocked = False
    server.wire(None, None)


URL = "/api/admin/achievement-sounds"


class TestRoutes:
    def test_everything_is_locked_until_the_dev_tab_is_unlocked(self, client):
        c, *_ = client
        assert "locked" in c.get(URL).json()["error"]
        assert "locked" in c.put(f"{URL}/ton_up", json={"files": ["fanfare.mp3"]}).json()["error"]
        assert "locked" in c.post(f"{URL}/upload?name=x.mp3", content=MP3).json()["error"]

    def test_the_unlock_opens_it(self, client):
        c, *_ = client
        c.post("/api/dev/unlock")
        data = c.get(URL).json()
        assert len(data["achievements"]) == len(ACHIEVEMENTS) and "party.mp3" in data["files"]

    def test_dev_enabled_in_the_config_opens_it_too(self, client):
        c, _, config = client
        cfg_mod.write(config, {"dev": {"enabled": True}})
        assert "achievements" in c.get(URL).json()

    def test_an_assignment_is_stored_applied_and_cleared(self, client):
        c, engine, config = client
        c.post("/api/dev/unlock")
        assert c.put(f"{URL}/ton_up", json={"files": ["fanfare.mp3", "party.mp3"]}).json() == {
            "ok": True, "assigned": ["fanfare.mp3", "party.mp3"]}
        assert cfg_mod.load(config)["achievements"]["sounds"]["ton_up"] == ["fanfare.mp3", "party.mp3"]
        assert server.assigned_achievement_sounds("ton_up") == ["fanfare.mp3", "party.mp3"]
        entry = next(a for a in c.get(URL).json()["achievements"] if a["id"] == "ton_up")
        assert entry["plays_now"]["source"] == "assigned"
        assert c.put(f"{URL}/ton_up", json={"files": []}).json() == {"ok": True, "assigned": []}
        assert server.assigned_achievement_sounds("ton_up") == []

    def test_a_file_that_is_listed_twice_is_stored_once(self, client):
        c, *_ = client
        c.post("/api/dev/unlock")
        assert c.put(f"{URL}/ton_up", json={"files": ["party.mp3", "party.mp3"]}).json()["assigned"] == ["party.mp3"]

    def test_an_unknown_achievement_or_file_is_refused(self, client):
        c, *_ = client
        c.post("/api/dev/unlock")
        assert "unknown achievement" in c.put(f"{URL}/nope", json={"files": []}).json()["error"]
        assert "not a sound" in c.put(f"{URL}/ton_up", json={"files": ["matchon.mp3"]}).json()["error"]
        assert "not a sound" in c.put(f"{URL}/ton_up", json={"files": ["../x.mp3"]}).json()["error"]

    def test_an_upload_is_saved_and_can_be_assigned(self, client):
        c, engine, _ = client
        c.post("/api/dev/unlock")
        assert c.post(f"{URL}/upload?name=new.mp3", content=MP3).json() == {"ok": True, "file": "new.mp3"}
        assert "new.mp3" in c.get(URL).json()["files"]
        assert c.put(f"{URL}/ton_up", json={"files": ["new.mp3"]}).json()["ok"] is True
        assert c.get("/api/sound/new.mp3").status_code == 200

    def test_a_bad_upload_comes_back_as_an_error(self, client):
        c, *_ = client
        c.post("/api/dev/unlock")
        assert "mp3" in c.post(f"{URL}/upload?name=x.mp3", content=b"hello").json()["error"]
        assert "exists" in c.post(f"{URL}/upload?name=party.mp3", content=MP3).json()["error"]

    def test_a_file_can_be_renamed_and_deleted_through_the_routes(self, client):
        c, engine, config = client
        c.post("/api/dev/unlock")
        c.put(f"{URL}/ton_up", json={"files": ["fanfare.mp3"]})
        assert c.patch(f"{URL}/files/fanfare.mp3", json={"name": "tada.mp3"}).json() == {"ok": True, "file": "tada.mp3"}
        assert cfg_mod.load(config)["achievements"]["sounds"]["ton_up"] == ["tada.mp3"]
        assert "exists" in c.patch(f"{URL}/files/tada.mp3", json={"name": "party.mp3"}).json()["error"]
        assert c.delete(f"{URL}/files/tada.mp3").json() == {"ok": True}
        assert "sounds" not in cfg_mod.load(config).get("achievements", {})
        assert "not a sound" in c.delete(f"{URL}/files/tada.mp3").json()["error"]
        assert "tada.mp3" not in c.get(URL).json()["files"]

    def test_renaming_and_deleting_are_locked_too(self, client):
        c, *_ = client
        assert "locked" in c.patch(f"{URL}/files/fanfare.mp3", json={"name": "x.mp3"}).json()["error"]
        assert "locked" in c.delete(f"{URL}/files/fanfare.mp3").json()["error"]

    def test_without_an_audio_engine_there_is_nothing_to_list(self, tmp_path):
        config = tmp_path / "config.toml"
        config.write_text("")
        server.wire(None, None, config_path=str(config))
        server._dev_unlocked = True
        try:
            assert "no config file or sound directory" in TestClient(server.app).get(URL).json()["error"]
            assert server.assigned_achievement_sounds("ton_up") == []
        finally:
            server._dev_unlocked = False
            server.wire(None, None)
