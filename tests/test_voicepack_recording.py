import asyncio
import json

import pytest
from starlette.testclient import TestClient

import tools.generate_voicepack as gv
from breakfast import config as cfg_mod
from breakfast import sound_edit, voicepack
from breakfast import voicepack_editor as ve
from breakfast.audio_engine import AudioEngine
from breakfast.web import server

_PLAN = """\
voice = "de-CH-LeniNeural"

[[group]]
name = "Phrases"

[group.keys.busted]
variants = ["Busted", "Over"]

[group.keys.close]
variants = ["Close"]

[[group]]
name = "Numbers"

[group.range]
start = 1
end = 4
exclude = [2]
key_prefix = "require_"

[group.range.overrides.3]
variants = ["three"]
"""


@pytest.fixture
def pack(tmp_path, monkeypatch):
    plan = tmp_path / "plan.toml"
    plan.write_text(_PLAN, encoding="utf-8")
    monkeypatch.setattr(server, "_voicepack_plan_path", lambda pack=None: plan)
    audio_dir = tmp_path / "sounds"
    config = tmp_path / "config.toml"
    cfg_mod.write(str(config), {"audio": {"dir": str(audio_dir)}})
    out = audio_dir / "profiles" / "leni"
    out.mkdir(parents=True)
    engine = AudioEngine(str(out))
    sent = []
    engine._broadcast = sent.append
    server.wire(None, None, config_path=str(config), audio_engine=engine)
    # the editor is tested with a stand-in for ffmpeg: it returns the start and end it got
    monkeypatch.setattr(sound_edit, "render", lambda data, start, end, *a, **k: f"mp3:{start}-{end}".encode())
    try:
        yield {"out": out, "plan": plan, "client": TestClient(server.app), "engine": engine, "tmp": tmp_path}
    finally:
        server.wire(None, None)


def status(pack, group):
    body = pack["client"].get("/api/voicepack/recording", params={"group": group}).json()
    return {r["key"]: r["status"] for r in body["rows"]}, body["counts"]


def record(pack, name, body=b"raw", **extra):
    return pack["client"].post("/api/voicepack/recording/edit", params={"name": name, "end": 1.5, **extra}, content=body).json()


class TestRows:
    def test_every_key_is_listed_with_the_text_to_read(self, pack):
        body = pack["client"].get("/api/voicepack/recording", params={"group": "Numbers"}).json()
        assert [(r["key"], r["text"]) for r in body["rows"]] == [("require_1", "1"), ("require_3", "three"), ("require_4", "4")]

    def test_the_status_follows_the_files_and_the_marks(self, pack):
        out = pack["out"]
        (out / "busted.mp3").write_bytes(b"x")
        (out / "busted+1.mp3").write_bytes(b"x")
        (out / "close.mp3").write_bytes(b"x")
        voicepack.write_recorded(out, {"busted+1.mp3"})
        states, counts = status(pack, "Phrases")
        assert states == {"busted": "recorded", "close": "generated"}
        assert counts["total"] == 5 and counts["recorded"] == 1 and counts["generated"] == 1 and counts["missing"] == 3
        assert counts["groups"]["Phrases"] == {"total": 2, "recorded": 1, "generated": 1, "missing": 0}

    def test_a_gap_hides_the_files_behind_it(self, pack):
        (pack["out"] / "busted+2.mp3").write_bytes(b"x")
        assert status(pack, "Phrases")[0]["busted"] == "missing"

    def test_an_unknown_group_is_reported(self, pack):
        assert pack["client"].get("/api/voicepack/recording", params={"group": "Nope"}).json() == {"error": "unknown group"}


class TestStoring:
    def test_a_recording_becomes_the_file_of_the_key_and_is_marked(self, pack):
        assert record(pack, "close.mp3", start=0.1) == {"ok": True, "file": "close.mp3"}
        assert (pack["out"] / "close.mp3").read_bytes() == b"mp3:0.1-1.5"
        assert voicepack.read_recorded(pack["out"]) == {"close.mp3"}
        assert status(pack, "Phrases")[0]["close"] == "recorded"

    def test_the_next_recording_is_the_next_variant(self, pack):
        record(pack, "close.mp3")
        record(pack, "close+1.mp3")
        assert sorted(p.name for p in pack["out"].glob("close*.mp3")) == ["close+1.mp3", "close.mp3"]

    def test_a_variant_cannot_skip_an_index(self, pack):
        assert "error" in record(pack, "close+1.mp3")
        assert "error" in record(pack, "close+3.mp3")
        assert not list(pack["out"].glob("close*"))

    def test_a_name_that_is_not_a_key_of_the_plan_is_refused(self, pack):
        assert record(pack, "nothing.mp3") == {"error": "not a key of this pack"}
        assert "error" in record(pack, "../close.mp3")
        assert "error" in record(pack, "close+0.mp3")
        assert "error" in record(pack, "close.wav")

    def test_recording_again_replaces_the_variant(self, pack):
        record(pack, "close.mp3", start=0)
        record(pack, "close.mp3", start=0.5)
        assert (pack["out"] / "close.mp3").read_bytes() == b"mp3:0.5-1.5"

    def test_a_generated_variant_can_be_replaced_next_to_a_recorded_one(self, pack):
        (pack["out"] / "busted.mp3").write_bytes(b"generated")
        record(pack, "busted+1.mp3")
        assert (pack["out"] / "busted.mp3").read_bytes() == b"generated"
        assert voicepack.read_recorded(pack["out"]) == {"busted+1.mp3"}

    def test_a_file_of_the_pack_can_be_adjusted(self, pack):
        record(pack, "close.mp3")
        res = pack["client"].post("/api/voicepack/recording/edit", params={"name": "close.mp3", "source": "close.mp3", "end": 2}).json()
        assert res["ok"] is True
        assert (pack["out"] / "close.mp3").read_bytes() == b"mp3:0.0-2.0"

    def test_a_source_outside_the_pack_is_refused(self, pack):
        res = pack["client"].post("/api/voicepack/recording/edit", params={"name": "close.mp3", "source": "../plan.toml", "end": 2}).json()
        assert res == {"error": "not a file of this pack"}

    def test_a_failed_render_stores_nothing(self, pack, monkeypatch):
        monkeypatch.setattr(sound_edit, "render", lambda *a, **k: "the selection is too short")
        assert record(pack, "close.mp3") == {"error": "the selection is too short"}
        assert not (pack["out"] / "close.mp3").exists() and voicepack.read_recorded(pack["out"]) == set()

    def test_the_caller_finds_the_new_file(self, pack):
        assert pack["engine"].has_audio("close") is False
        record(pack, "close.mp3")
        assert pack["engine"].has_audio("close") is True

    def test_the_preview_stores_nothing(self, pack, monkeypatch):
        monkeypatch.setattr(sound_edit, "preview", lambda *a, **k: b"preview")
        res = pack["client"].post("/api/voicepack/recording/preview", params={"end": 1}, content=b"raw")
        assert res.content == b"preview"
        assert not list(pack["out"].iterdir())


class TestDeleting:
    def test_the_higher_variants_move_down_with_their_marks(self, pack):
        record(pack, "close.mp3", start=0)
        record(pack, "close+1.mp3", start=1)
        (pack["out"] / "close+2.mp3").write_bytes(b"generated")
        assert pack["client"].delete("/api/voicepack/recording", params={"filename": "close.mp3"}).json() == {"ok": True}
        assert sorted(p.name for p in pack["out"].glob("close*.mp3")) == ["close+1.mp3", "close.mp3"]
        assert (pack["out"] / "close.mp3").read_bytes() == b"mp3:1.0-1.5"
        assert voicepack.read_recorded(pack["out"]) == {"close.mp3"}

    def test_a_missing_file_is_reported(self, pack):
        assert "error" in pack["client"].delete("/api/voicepack/recording", params={"filename": "close.mp3"}).json()


class TestGenerationKeepsRecordings:
    def test_a_forced_run_skips_the_recorded_files(self):
        written = []

        async def fake(voice, text, rate, pitch, volume, dest, trim):
            written.append(dest.name)
            dest.write_bytes(b"generated")

        import tempfile
        from pathlib import Path
        plan = {"voice": "x-Y-ZNeural", "group": [{"name": "g", "keys": {"a": "A", "b": "B"}}]}
        orig = gv.synthesize
        gv.synthesize = fake
        try:
            with tempfile.TemporaryDirectory() as tmp:
                out = Path(tmp)
                (out / "a.mp3").write_bytes(b"mine")
                asyncio.run(gv.run(plan, out, None, True, False, False, keep={"a.mp3"}))
                assert written == ["b.mp3"] and (out / "a.mp3").read_bytes() == b"mine"
        finally:
            gv.synthesize = orig

    def test_saving_an_entry_keeps_a_recorded_variant(self, pack, monkeypatch):
        async def fake(voice, text, rate, pitch, volume, dest, trim):
            dest.write_bytes(b"generated")
        monkeypatch.setattr(gv, "synthesize", fake)
        (pack["out"] / "busted.mp3").write_bytes(b"generated")
        record(pack, "busted+1.mp3", start=0.25)
        res = pack["client"].post("/api/voicepack/entries", json={"group": "Phrases", "key": "busted", "variants": ["Busted"]}).json()
        assert res == {"ok": True}
        assert (pack["out"] / "busted+1.mp3").read_bytes() == b"mp3:0.25-1.5"      # not pruned
        assert voicepack.read_recorded(pack["out"]) == {"busted+1.mp3"}

    def test_deleting_a_plan_variant_moves_the_marks(self, pack):
        (pack["out"] / "busted.mp3").write_bytes(b"generated")
        record(pack, "busted+1.mp3", start=0.25)
        res = pack["client"].request("DELETE", "/api/voicepack/entries", json={"group": "Phrases", "key": "busted", "variant_index": 0}).json()
        assert res == {"ok": True}
        assert voicepack.read_recorded(pack["out"]) == {"busted.mp3"}
        assert (pack["out"] / "busted.mp3").read_bytes() == b"mp3:0.25-1.5"


class TestCopyingAPlan:
    def test_a_copy_is_a_pack_of_its_own(self, pack, monkeypatch):
        monkeypatch.undo()
        plan = pack["tmp"] / "tools" / "voicepack_leni.toml"
        plan.parent.mkdir()
        plan.write_text(_PLAN, encoding="utf-8")
        monkeypatch.setattr(server, "_TOOLS_DIR", plan.parent)
        res = pack["client"].post("/api/voicepack/packs/copy", json={"source": "leni", "name": "Mine"}).json()
        assert res == {"ok": True, "name": "mine"}
        packs = {p["name"]: p for p in pack["client"].get("/api/voicepack/packs").json()["packs"]}
        assert set(packs) == {"leni", "mine"} and packs["mine"]["own"] is True and packs["leni"]["own"] is False
        assert pack["client"].get("/api/voicepack/groups", params={"pack": "mine"}).json()["groups"][0]["name"] == "Phrases"
        # its files go to their own folder
        monkeypatch.setattr(sound_edit, "render", lambda *a, **k: b"mp3")
        assert pack["client"].post("/api/voicepack/recording/edit", params={"pack": "mine", "name": "close.mp3", "end": 1}, content=b"r").json()["ok"]
        assert (pack["tmp"] / "sounds" / "profiles" / "mine" / "close.mp3").is_file()
        assert not (pack["tmp"] / "sounds" / "profiles" / "leni" / "close.mp3").exists()

    def test_a_bad_or_taken_name_is_refused(self, pack, monkeypatch):
        plan = pack["tmp"] / "tools" / "voicepack_leni.toml"
        plan.parent.mkdir()
        plan.write_text(_PLAN, encoding="utf-8")
        monkeypatch.setattr(server, "_TOOLS_DIR", plan.parent)
        for name in ("a", "9abc", "with space", "leni"):
            assert "error" in pack["client"].post("/api/voicepack/packs/copy", json={"source": "leni", "name": name}).json()

    def test_the_profile_name_of_a_plan(self):
        assert voicepack.profile_name({"voice": "de-CH-LeniNeural"}) == "leni"
        assert voicepack.profile_name({"voice": "de-CH-LeniNeural", "profile": " mine "}) == "mine"
        assert ve.profile_dir_name({"voice": "en-GB-RyanNeural"}) == "ryan"
