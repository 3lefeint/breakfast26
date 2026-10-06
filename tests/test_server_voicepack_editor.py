import asyncio

import pytest

import tools.generate_voicepack as gv
from breakfast import config as cfg_mod
from breakfast.audio_engine import AudioEngine
from breakfast.web import server

_PLAN = """\
voice = "de-CH-LeniNeural"

[[group]]
name = "Phrases"
rate = "+15%"

[group.keys.busted]
variants = ["a", "b", "c"]

[[group]]
name = "Numbers"

[group.range]
start = 0
end = 5
key_prefix = "require_"

[group.range.overrides.3]
variants = ["3", "drü"]
"""


async def _fake_synthesize(voice, text, rate, pitch, volume, dest, trim):
    dest.write_bytes(b"fake-mp3")


@pytest.fixture(autouse=True)
def fake_tts(monkeypatch):
    """Every test here goes through server.py's lazily-imported
    `synthesize()` — patch the real function so no network/ffmpeg call
    ever happens in the test suite."""
    monkeypatch.setattr(gv, "synthesize", _fake_synthesize)


@pytest.fixture
def wired(tmp_path, monkeypatch):
    plan_path = tmp_path / "plan.toml"
    plan_path.write_text(_PLAN, encoding="utf-8")
    monkeypatch.setattr(server, "_voicepack_plan_path", lambda pack=None: plan_path)

    audio_dir = tmp_path / "sounds"
    config_path = tmp_path / "config.toml"
    cfg_mod.write(str(config_path), {"audio": {"dir": str(audio_dir)}})

    # Points directly at where the "leni" profile's files actually land
    # (audio_dir/profiles/leni), matching what voicepack.search_dirs()
    # would resolve for a real [audio] profile = "leni" config.
    engine = AudioEngine(str(audio_dir / "profiles" / "leni"))
    server.wire(None, None, config_path=str(config_path), audio_engine=engine)
    try:
        yield {"plan_path": plan_path, "audio_dir": audio_dir, "engine": engine}
    finally:
        server.wire(None, None)


def test_groups_lists_names_and_range_flag(wired):
    res = asyncio.run(server.voicepack_groups())
    assert res == {"groups": [
        {"name": "Phrases", "is_range": False},
        {"name": "Numbers", "is_range": True},
    ]}


def test_entries_unknown_group_returns_error(wired):
    res = asyncio.run(server.voicepack_entries(group="Nope"))
    assert res == {"error": "unknown group"}


def test_entries_reports_disk_state_for_existing_key(wired):
    out_dir = wired["audio_dir"] / "profiles" / "leni"
    out_dir.mkdir(parents=True)
    (out_dir / "busted.mp3").write_bytes(b"x")

    res = asyncio.run(server.voicepack_entries(group="Phrases"))
    busted = next(e for e in res["entries"] if e["key"] == "busted")
    assert [v["has_file"] for v in busted["variants"]] == [True, False, False]


def test_save_entry_new_key_writes_files_and_plan(wired):
    body = server.VoicepackEntryBody(group="Phrases", key="newkey", variants=["hi", "there"])
    res = asyncio.run(server.voicepack_save_entry(body))
    assert res == {"ok": True}

    out_dir = wired["audio_dir"] / "profiles" / "leni"
    assert (out_dir / "newkey.mp3").read_bytes() == b"fake-mp3"
    assert (out_dir / "newkey+1.mp3").read_bytes() == b"fake-mp3"

    saved = wired["plan_path"].read_text(encoding="utf-8")
    assert 'variants = ["hi", "there"]' in saved.replace("'", '"')


def test_save_entry_shrinking_variants_prunes_stale_files(wired):
    out_dir = wired["audio_dir"] / "profiles" / "leni"
    out_dir.mkdir(parents=True)
    for name in ("busted.mp3", "busted+1.mp3", "busted+2.mp3"):
        (out_dir / name).write_bytes(b"old")

    body = server.VoicepackEntryBody(group="Phrases", key="busted", variants=["only one"])
    res = asyncio.run(server.voicepack_save_entry(body))
    assert res == {"ok": True}

    assert (out_dir / "busted.mp3").read_bytes() == b"fake-mp3"
    assert not (out_dir / "busted+1.mp3").is_file()
    assert not (out_dir / "busted+2.mp3").is_file()


def test_save_entry_invalidates_the_running_audio_engine_cache(wired):
    engine = wired["engine"]
    assert engine.has_audio("busted") is False  # nothing on disk yet -> cached as missing

    body = server.VoicepackEntryBody(group="Phrases", key="busted", variants=["a"])
    asyncio.run(server.voicepack_save_entry(body))

    assert engine.has_audio("busted") is True, "stale cache must be invalidated after save"


def test_save_entry_range_group_applies_key_prefix(wired):
    body = server.VoicepackEntryBody(group="Numbers", key="4", variants=["4", "vier"])
    res = asyncio.run(server.voicepack_save_entry(body))
    assert res == {"ok": True}

    out_dir = wired["audio_dir"] / "profiles" / "leni"
    assert (out_dir / "require_4.mp3").is_file()
    assert (out_dir / "require_4+1.mp3").is_file()


def test_save_entry_rejects_non_numeric_key_for_range_group(wired):
    body = server.VoicepackEntryBody(group="Numbers", key="not-a-number", variants=["x"])
    res = asyncio.run(server.voicepack_save_entry(body))
    assert res == {"error": "key must be a whole number for this group"}


def test_save_entry_rejects_empty_variants(wired):
    body = server.VoicepackEntryBody(group="Phrases", key="k", variants=["  ", ""])
    res = asyncio.run(server.voicepack_save_entry(body))
    assert res == {"error": "at least one variant is required"}


def test_delete_variant_renumbers_and_updates_plan(wired):
    out_dir = wired["audio_dir"] / "profiles" / "leni"
    out_dir.mkdir(parents=True)
    for name in ("busted.mp3", "busted+1.mp3", "busted+2.mp3"):
        (out_dir / name).write_text(name)

    body = server.VoicepackDeleteVariantBody(group="Phrases", key="busted", variant_index=1)
    res = asyncio.run(server.voicepack_delete_variant(body))
    assert res == {"ok": True}

    assert (out_dir / "busted+1.mp3").read_text() == "busted+2.mp3"
    assert not (out_dir / "busted+2.mp3").is_file()

    entries = asyncio.run(server.voicepack_entries(group="Phrases"))
    busted = next(e for e in entries["entries"] if e["key"] == "busted")
    assert [v["text"] for v in busted["variants"]] == ["a", "c"]


def test_delete_variant_unknown_entry_returns_error(wired):
    body = server.VoicepackDeleteVariantBody(group="Phrases", key="nope", variant_index=0)
    res = asyncio.run(server.voicepack_delete_variant(body))
    assert res == {"error": "entry not found"}


def test_preview_unknown_group_returns_error(wired):
    body = server.VoicepackPreviewBody(group="Nope", text="hallo")
    res = asyncio.run(server.voicepack_preview(body))
    assert res == {"error": "unknown group"}


def test_preview_empty_text_returns_error(wired):
    body = server.VoicepackPreviewBody(group="Phrases", text="   ")
    res = asyncio.run(server.voicepack_preview(body))
    assert res == {"error": "text is required"}


def test_preview_returns_a_file_response_without_touching_the_plan(wired):
    original_plan = wired["plan_path"].read_text(encoding="utf-8")
    body = server.VoicepackPreviewBody(group="Phrases", text="hallo welt")
    res = asyncio.run(server.voicepack_preview(body))

    assert res.media_type == "audio/mpeg"
    assert res.headers["cache-control"] == "no-store"
    assert wired["plan_path"].read_text(encoding="utf-8") == original_plan


# ── several packs ────────────────────────────────────────────────────────────

_PLAN_RYAN = """\
voice = "en-GB-RyanNeural"

[[group]]
name = "Lifecycle"

[group.keys.matchon]
variants = ["Game on"]
"""


@pytest.fixture
def two_packs(tmp_path, monkeypatch):
    tools = tmp_path / "tools"
    tools.mkdir()
    (tools / "voicepack_leni.toml").write_text(_PLAN, encoding="utf-8")
    (tools / "voicepack_ryan.toml").write_text(_PLAN_RYAN, encoding="utf-8")
    (tools / "voicepack_broken.toml").write_text("not a plan", encoding="utf-8")
    monkeypatch.setattr(server, "_TOOLS_DIR", tools)
    audio_dir = tmp_path / "sounds"
    config_path = tmp_path / "config.toml"

    def configure(profile=None):
        audio = {"dir": str(audio_dir)}
        if profile:
            audio["profile"] = profile
        cfg_mod.write(str(config_path), {"audio": audio})
        server.wire(None, None, config_path=str(config_path))

    configure()
    try:
        yield {"configure": configure, "audio_dir": audio_dir}
    finally:
        server.wire(None, None)


def test_packs_lists_every_plan_and_skips_a_broken_one(two_packs):
    res = asyncio.run(server.voicepack_packs())
    assert [p["name"] for p in res["packs"]] == ["leni", "ryan"]
    assert res["packs"][1] == {"name": "ryan", "voice": "en-GB-RyanNeural", "plan": "voicepack_ryan.toml"}


def test_packs_starts_on_the_active_profile(two_packs):
    two_packs["configure"]("ryan")
    assert asyncio.run(server.voicepack_packs())["default"] == "ryan"


def test_packs_starts_on_the_first_plan_when_the_active_profile_has_none(two_packs):
    two_packs["configure"]("en-US-coral-FEMALE")
    assert asyncio.run(server.voicepack_packs())["default"] == "leni"


def test_groups_follow_the_chosen_pack(two_packs):
    assert asyncio.run(server.voicepack_groups(pack="ryan")) == {"groups": [{"name": "Lifecycle", "is_range": False}]}
    assert [g["name"] for g in asyncio.run(server.voicepack_groups(pack="leni"))["groups"]] == ["Phrases", "Numbers"]


def test_groups_without_a_pack_use_the_active_one(two_packs):
    two_packs["configure"]("ryan")
    assert [g["name"] for g in asyncio.run(server.voicepack_groups())["groups"]] == ["Lifecycle"]


def test_an_unknown_pack_is_refused(two_packs):
    assert asyncio.run(server.voicepack_groups(pack="nope")) == {"error": "unknown voice pack"}
    assert asyncio.run(server.voicepack_entries(group="Lifecycle", pack="nope")) == {"error": "unknown voice pack"}


def test_saving_an_entry_writes_into_the_chosen_pack(two_packs):
    res = asyncio.run(server.voicepack_save_entry(
        server.VoicepackEntryBody(group="Lifecycle", key="gameon", variants=["Next leg"], pack="ryan")))
    assert res == {"ok": True}
    assert (two_packs["audio_dir"] / "profiles" / "ryan" / "gameon.mp3").is_file()
    assert "gameon" in (server._TOOLS_DIR / "voicepack_ryan.toml").read_text(encoding="utf-8")
    assert "gameon" not in (server._TOOLS_DIR / "voicepack_leni.toml").read_text(encoding="utf-8")
