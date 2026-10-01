"""Parses CHANGELOG.md (Keep a Changelog layout) for the About page."""

import re

_VERSION = re.compile(r"^## \[([^\]]+)\](?:\s*-\s*(\S+))?\s*$")
_SECTION = re.compile(r"^### (.+?)\s*$")


def parse_changelog(text: str) -> list[dict]:
    """Versions, newest first as written: {version, date, sections}. A section is
    {name, entries}; entries listed directly under a version have name None.
    `[Unreleased]` is kept only if it has entries."""
    versions: list[dict] = []
    current = None
    section = None
    for line in text.splitlines():
        m = _VERSION.match(line)
        if m:
            current = {"version": m.group(1), "date": m.group(2), "sections": []}
            versions.append(current)
            section = None
            continue
        if current is None:
            continue
        m = _SECTION.match(line)
        if m:
            section = {"name": m.group(1), "entries": []}
            current["sections"].append(section)
            continue
        if line.startswith("- "):
            if section is None:
                section = {"name": None, "entries": []}
                current["sections"].append(section)
            section["entries"].append(line[2:].strip())
        elif line.startswith("  ") and line.strip() and section and section["entries"]:
            section["entries"][-1] += " " + line.strip()
    return [v for v in versions
            if v["version"].lower() != "unreleased" or any(s["entries"] for s in v["sections"])]
