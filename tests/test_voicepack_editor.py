import pytest

from breakfast import voicepack_editor as ve

_PLAN = """\
# top banner comment
voice = "de-CH-LeniNeural"

[[group]]
name = "Phrases"
rate = "+15%"
pitch = "+0Hz"
volume = "+0%"

[group.keys.busted]
# why busted has 3 takes
variants = ["a", "b", "c"]

[group.keys.close]
variants = ["knapp"]
rate = "+20%"

[[group]]
name = "Numbers"
rate = "+10%"

[group.range]
start = 0
end = 5
key_prefix = "require_"

[group.range.overrides.3]
variants = ["3", "drü"]
"""


@pytest.fixture
def plan_path(tmp_path):
    p = tmp_path / "plan.toml"
    p.write_text(_PLAN, encoding="utf-8")
    return p


@pytest.fixture
def doc(plan_path):
    return ve.load_plan(plan_path)


class TestLoadSaveRoundtrip:
    def test_preserves_comments(self, doc, plan_path):
        ve.save_plan(plan_path, doc)
        out = plan_path.read_text(encoding="utf-8")
        assert "# top banner comment" in out
        assert "# why busted has 3 takes" in out

    def test_edit_survives_roundtrip(self, doc, plan_path):
        ve.upsert_entry(doc, "Phrases", "busted", ["x", "y"])
        ve.save_plan(plan_path, doc)
        reloaded = ve.load_plan(plan_path)
        assert list(reloaded["group"][0]["keys"]["busted"]["variants"]) == ["x", "y"]


class TestListGroups:
    def test_reports_name_and_range_flag(self, doc):
        assert ve.list_groups(doc) == [
            {"name": "Phrases", "is_range": False},
            {"name": "Numbers", "is_range": True},
        ]


class TestListEntries:
    def test_unknown_group_returns_none(self, doc, tmp_path):
        assert ve.list_entries(doc, "Nope", tmp_path) is None

    def test_keys_group_reports_variants_and_file_existence(self, doc, tmp_path):
        (tmp_path / "busted.mp3").write_bytes(b"")
        (tmp_path / "busted+1.mp3").write_bytes(b"")
        # busted+2.mp3 deliberately not written

        entries = ve.list_entries(doc, "Phrases", tmp_path)
        busted = next(e for e in entries if e["key"] == "busted")
        assert [v["has_file"] for v in busted["variants"]] == [True, True, False]
        assert [v["filename"] for v in busted["variants"]] == [
            "busted.mp3", "busted+1.mp3", "busted+2.mp3",
        ]

    def test_range_group_applies_key_prefix_to_filenames(self, doc, tmp_path):
        entries = ve.list_entries(doc, "Numbers", tmp_path)
        assert entries == [{
            "key": "3",
            "variants": [
                {"index": 0, "text": "3", "filename": "require_3.mp3", "has_file": False},
                {"index": 1, "text": "drü", "filename": "require_3+1.mp3", "has_file": False},
            ],
        }]


class TestEntryProsody:
    def test_falls_back_to_group_defaults(self, doc):
        assert ve.entry_prosody(doc, "Phrases", "busted") == {
            "rate": "+15%", "pitch": "+0Hz", "volume": "+0%",
        }

    def test_uses_per_key_override_when_present(self, doc):
        assert ve.entry_prosody(doc, "Phrases", "close")["rate"] == "+20%"

    def test_unknown_group_returns_none(self, doc):
        assert ve.entry_prosody(doc, "Nope", "busted") is None


class TestUpsertEntry:
    def test_new_key_reports_zero_old_count(self, doc):
        result = ve.upsert_entry(doc, "Phrases", "brandnew", ["hi"])
        assert result == {"stem": "brandnew", "old_count": 0}
        assert list(doc["group"][0]["keys"]["brandnew"]["variants"]) == ["hi"]

    def test_editing_existing_key_reports_previous_count(self, doc):
        result = ve.upsert_entry(doc, "Phrases", "busted", ["only one now"])
        assert result == {"stem": "busted", "old_count": 3}
        assert list(doc["group"][0]["keys"]["busted"]["variants"]) == ["only one now"]

    def test_preserves_existing_rate_override_on_edit(self, doc):
        ve.upsert_entry(doc, "Phrases", "close", ["neu"])
        assert doc["group"][0]["keys"]["close"]["rate"] == "+20%"

    def test_range_group_writes_under_overrides_with_plain_numeric_key(self, doc):
        result = ve.upsert_entry(doc, "Numbers", "4", ["4", "vier"])
        assert result == {"stem": "require_4", "old_count": 0}
        assert list(doc["group"][1]["range"]["overrides"]["4"]["variants"]) == ["4", "vier"]

    def test_unknown_group_returns_none(self, doc):
        assert ve.upsert_entry(doc, "Nope", "x", ["a"]) is None


class TestRemoveVariant:
    def test_removes_one_variant_keeps_the_rest(self, doc):
        result = ve.remove_variant(doc, "Phrases", "busted", 1)
        assert result == {"stem": "busted", "new_count": 2}
        assert list(doc["group"][0]["keys"]["busted"]["variants"]) == ["a", "c"]

    def test_removing_last_variant_deletes_the_whole_key(self, doc):
        result = ve.remove_variant(doc, "Phrases", "close", 0)
        assert result == {"stem": "close", "new_count": 0}
        assert "close" not in doc["group"][0]["keys"]

    def test_out_of_range_index_returns_none(self, doc):
        assert ve.remove_variant(doc, "Phrases", "busted", 99) is None

    def test_unknown_key_returns_none(self, doc):
        assert ve.remove_variant(doc, "Phrases", "nope", 0) is None

    def test_range_group(self, doc):
        result = ve.remove_variant(doc, "Numbers", "3", 1)
        assert result == {"stem": "require_3", "new_count": 1}
        assert list(doc["group"][1]["range"]["overrides"]["3"]["variants"]) == ["3"]


class TestPruneExtraVariantFiles:
    def test_deletes_from_keep_count_onward_stopping_at_first_gap(self, tmp_path):
        for name in ("k.mp3", "k+1.mp3", "k+2.mp3", "k+4.mp3"):  # k+3 missing (gap)
            (tmp_path / name).write_bytes(b"")

        ve.prune_extra_variant_files(tmp_path, "k", keep_count=1)

        assert (tmp_path / "k.mp3").is_file()
        assert not (tmp_path / "k+1.mp3").is_file()
        assert not (tmp_path / "k+2.mp3").is_file()
        assert (tmp_path / "k+4.mp3").is_file(), "unreachable past the gap, left alone"


class TestRenumberAfterDelete:
    def test_shifts_higher_indexed_files_down(self, tmp_path):
        for name in ("k.mp3", "k+1.mp3", "k+2.mp3", "k+3.mp3"):
            (tmp_path / name).write_text(name)

        # deleting index 1 (k+1.mp3) leaves 3 variants (indices 0,1,2) —
        # k+2 -> k+1, k+3 -> k+2
        ve.renumber_after_delete(tmp_path, "k", deleted_index=1, new_count=3)

        assert (tmp_path / "k.mp3").read_text() == "k.mp3"  # untouched (index 0 kept)
        assert (tmp_path / "k+1.mp3").read_text() == "k+2.mp3"
        assert (tmp_path / "k+2.mp3").read_text() == "k+3.mp3"
        assert not (tmp_path / "k+3.mp3").is_file()

    def test_deleting_index_zero_promotes_variant_one(self, tmp_path):
        (tmp_path / "k.mp3").write_text("original base")
        (tmp_path / "k+1.mp3").write_text("was variant 1")

        ve.renumber_after_delete(tmp_path, "k", deleted_index=0, new_count=1)

        assert (tmp_path / "k.mp3").read_text() == "was variant 1"
        assert not (tmp_path / "k+1.mp3").is_file()

    def test_missing_source_file_is_not_an_error(self, tmp_path):
        (tmp_path / "k.mp3").write_bytes(b"")
        ve.renumber_after_delete(tmp_path, "k", deleted_index=0, new_count=0)  # nothing to shift
        assert not (tmp_path / "k.mp3").is_file()
