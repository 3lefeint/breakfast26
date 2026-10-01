from breakfast.changelog import parse_changelog

SAMPLE = """# Changelog

## [Unreleased]

## [0.6.0] - 2026-10-02

### Added
- First thing (#14).
- Second thing that is
  wrapped over two lines.

### Fixed
- A fix.

## [0.1.0] - 2026-07-08
- Start of a clean tracked history.
"""


def test_parses_versions_in_file_order():
    versions = parse_changelog(SAMPLE)
    assert [v["version"] for v in versions] == ["0.6.0", "0.1.0"]
    assert versions[0]["date"] == "2026-10-02"


def test_sections_and_entries():
    added, fixed = parse_changelog(SAMPLE)[0]["sections"]
    assert added["name"] == "Added"
    assert added["entries"] == ["First thing (#14).", "Second thing that is wrapped over two lines."]
    assert fixed == {"name": "Fixed", "entries": ["A fix."]}


def test_entries_directly_under_a_version_have_no_section_name():
    oldest = parse_changelog(SAMPLE)[1]
    assert oldest["sections"] == [{"name": None, "entries": ["Start of a clean tracked history."]}]


def test_unreleased_is_kept_only_with_entries():
    with_entries = SAMPLE.replace("## [Unreleased]\n", "## [Unreleased]\n\n### Added\n- Coming soon.\n")
    versions = parse_changelog(with_entries)
    assert versions[0]["version"] == "Unreleased" and versions[0]["date"] is None
    assert [v["version"] for v in parse_changelog(SAMPLE)] == ["0.6.0", "0.1.0"]


def test_real_changelog_parses():
    from pathlib import Path
    text = (Path(__file__).resolve().parents[1] / "CHANGELOG.md").read_text(encoding="utf-8")
    versions = parse_changelog(text)
    assert versions and all(s["entries"] for v in versions for s in v["sections"])
