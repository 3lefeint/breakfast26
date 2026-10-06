"""Print the CHANGELOG section of one version (the body of a GitHub release).

    python windows/release_notes.py 1.1.0
"""
import re
import sys
from pathlib import Path

version = sys.argv[1].lstrip("v")
text = (Path(__file__).resolve().parents[1] / "CHANGELOG.md").read_text(encoding="utf-8")
m = re.search(rf"^## \[{re.escape(version)}\][^\n]*\n(.*?)(?=^## \[|\Z)", text, re.S | re.M)
if not m:
    sys.exit(f"no CHANGELOG section for {version}")
print(m.group(1).strip())
