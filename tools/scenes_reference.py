"""Keeps the tables of SCENES.md in step with the code.

SCENES.md is written by hand, except the blocks between `<!-- generated:NAME -->` and `<!-- /generated:NAME -->`: the triggers
with their facts, the limits and the standard scenes are read from `breakfast/scenes.py` and `breakfast/scenes_default.py`.

    python tools/scenes_reference.py           rewrite the generated blocks of SCENES.md
    python tools/scenes_reference.py --check   exit with 1 when a block is out of date (a test does the same)
"""

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from breakfast import scenes, scenes_default  # noqa: E402

DOC = ROOT / "SCENES.md"


def events() -> str:
    """Every trigger with the facts a condition can look at."""
    lines = []
    for event_id, spec in scenes.EVENTS.items():
        lines.append(f"### `{event_id}`: {spec['label']} ({spec['game']})")
        lines.append("")
        if spec["fields"]:
            lines.extend(f"- `{name}`: {label}" for name, label in spec["fields"].items())
        else:
            lines.append("No facts of its own besides `player` and `fun`.")
        lines.append("")
    return "\n".join(lines).rstrip()


def limits() -> str:
    rows = [
        ("Nodes in a scene", scenes.MAX_NODES),
        ("Edges in a scene", scenes.MAX_NODES * 4),
        ("Characters of a scene name", scenes.MAX_NAME),
        ("Characters of an overlay text", scenes.MAX_TEXT),
        ("Seconds of a `delay`", scenes.MAX_DELAY_S),
        ("Seconds of an `overlay`", scenes.MAX_OVERLAY_S),
        ("Files in one `sound` step", scenes.MAX_SOUND_FILES),
        ("Highest `weight` of a file or an edge", scenes.MAX_WEIGHT),
        ("Highest `volume` of a `sound` (1 is the level of the library)", scenes.MAX_VOLUME),
        ("Outputs of a `switch` besides `else`", scenes.MAX_SWITCH_OUTPUTS),
        ("Values on one output of a `switch`", scenes.MAX_SWITCH_VALUES),
        ("Checks in a `combine`", scenes.MAX_CHECKS),
    ]
    out = ["| Limit | Value |", "|---|---|"]
    out.extend(f"| {name} | {value} |" for name, value in rows)
    return "\n".join(out)


def standard() -> str:
    out = ["| Id (the `ref` of the routes) | Moment | Game |", "|---|---|---|"]
    out.extend(f"| `{d['slug']}` | {d['name']} | {d['game']} |" for d in scenes_default.DEFAULTS)
    return "\n".join(out)


BLOCKS = {"events": events, "limits": limits, "standard": standard}


def render(text: str) -> str:
    """The document with every generated block rewritten."""
    for name, build in BLOCKS.items():
        pattern = re.compile(rf"(<!-- generated:{name} -->)\n(?:.*?\n)?(<!-- /generated:{name} -->)", re.S)
        if not pattern.search(text):
            raise SystemExit(f"SCENES.md has no block `{name}`")
        text = pattern.sub(lambda m: m.group(1) + "\n" + build() + "\n" + m.group(2), text)
    return text


def main(argv) -> int:
    text = DOC.read_text()
    fresh = render(text)
    if "--check" in argv:
        if fresh != text:
            print("SCENES.md is out of date: run `python tools/scenes_reference.py`")
            return 1
        return 0
    if fresh != text:
        DOC.write_text(fresh)
        print("SCENES.md updated")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
