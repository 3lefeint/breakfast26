import pytest

from breakfast import voicepack_editor as ve
from breakfast import voicepack_overlay as vo
from tools import generate_voicepack as gv

_PLAN = """\
voice = "en-GB-RyanNeural"

[[group]]
name = "Phrases"

[group.keys.matchon]
variants = ["Game on"]

[[group]]
name = "Player names"
rate = "+10%"

[group.keys]

[group.keys.unknown_player]
variants = ["dude"]
"""


def test_overlay_path_is_next_to_the_data_dir(tmp_path):
    assert vo.overlay_path(tmp_path, "ryan") == tmp_path / "voicepack" / "ryan.toml"


def test_read_entries_without_a_file_is_empty(tmp_path):
    assert vo.read_entries(tmp_path / "none.toml") == {}


def test_read_entries_reads_the_player_entries(tmp_path):
    f = tmp_path / "ryan.toml"
    f.write_text('[group.keys.anna]\nvariants = ["Anna", "Annie"]\n', encoding="utf-8")
    assert vo.read_entries(f) == {"anna": {"variants": ["Anna", "Annie"]}}


def test_read_entries_refuses_a_broken_file(tmp_path):
    f = tmp_path / "ryan.toml"
    f.write_text("not [ valid", encoding="utf-8")
    with pytest.raises(ValueError):
        vo.read_entries(f)


def test_merge_into_plan_extends_and_replaces_player_entries():
    import tomllib
    plan = tomllib.loads(_PLAN)
    vo.merge_into_plan(plan, {"anna": {"variants": ["Anna"]}, "unknown_player": {"variants": ["x"]}})
    keys = plan["group"][1]["keys"]
    assert keys["anna"] == {"variants": ["Anna"]}
    assert keys["unknown_player"] == {"variants": ["x"]}
    assert "anna" not in plan["group"][0].get("keys", {})


def test_the_generator_makes_files_for_the_private_names():
    import tomllib
    plan = tomllib.loads(_PLAN)
    vo.merge_into_plan(plan, {"anna": {"variants": ["Anna", "Annie"]}})
    made = {k: text for _, k, text, *_ in gv.resolve_entries(plan)}
    assert made["anna"] == "Anna" and made["anna+1"] == "Annie"


def test_overlay_changes_lists_only_what_differs_from_the_plan():
    plan = ve.tomlkit.parse(_PLAN)
    merged = ve.merge_overlay(plan, {})
    assert ve.overlay_changes(plan, merged) == {}
    ve.upsert_entry(merged, "Player names", "anna", ["Anna"])
    ve.upsert_entry(merged, "Player names", "unknown_player", ["x"])
    assert ve.overlay_changes(plan, merged) == {
        "anna": {"variants": ["Anna"]}, "unknown_player": {"variants": ["x"]}}


def test_overlay_changes_refuses_to_drop_a_plan_entry():
    plan = ve.tomlkit.parse(_PLAN)
    merged = ve.merge_overlay(plan, {})
    ve.remove_variant(merged, "Player names", "unknown_player", 0)
    with pytest.raises(ValueError):
        ve.overlay_changes(plan, merged)


def test_the_merged_copy_leaves_the_plan_alone():
    plan = ve.tomlkit.parse(_PLAN)
    ve.merge_overlay(plan, {"anna": {"variants": ["Anna"]}})
    assert "anna" not in ve.tomlkit.dumps(plan)


def test_write_overlay_creates_the_folder_and_keeps_comments(tmp_path):
    f = tmp_path / "voicepack" / "ryan.toml"
    ve.write_overlay(f, {"anna": {"variants": ["Anna"]}})
    assert vo.read_entries(f) == {"anna": {"variants": ["Anna"]}}
    text = f.read_text(encoding="utf-8")
    f.write_text("# my note\n" + text, encoding="utf-8")
    ve.write_overlay(f, {"anna": {"variants": ["Anna", "Annie"]}, "ben": {"variants": ["Ben"]}})
    assert f.read_text(encoding="utf-8").startswith("# my note")
    assert set(vo.read_entries(f)) == {"anna", "ben"}
    ve.write_overlay(f, {"ben": {"variants": ["Ben"]}})
    assert set(vo.read_entries(f)) == {"ben"}
