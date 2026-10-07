"""The private player-name file of a voice pack.

The plans in `tools/` are tracked by git, so the names of the players do not belong there. They live
in `<data dir>/voicepack/<pack>.toml` instead (git ignores `data/`), in the format of the plan's
"Player names" group:

    [group.keys.anna]
    variants = ["Anna", "Annie"]

Whoever loads a plan merges these entries into its "Player names" group: the generator, the Voice Pack
tab and the preview. An entry here replaces an entry of the same key in the plan.
"""

import tomllib
from pathlib import Path

PLAYER_GROUP = "Player names"


def overlay_path(data_dir, pack: str) -> Path:
    return Path(data_dir) / "voicepack" / f"{pack}.toml"


def read_entries(path: Path) -> dict[str, dict]:
    """The player entries of the file at *path*, `{}` if there is none. ValueError if the file is
    broken, so that nobody overwrites a file they could not read."""
    try:
        text = Path(path).read_text(encoding="utf-8")
    except FileNotFoundError:
        return {}
    except (OSError, UnicodeDecodeError) as e:
        raise ValueError(f"{Path(path).name}: {e}") from e
    try:
        data = tomllib.loads(text)
    except tomllib.TOMLDecodeError as e:
        raise ValueError(f"{Path(path).name}: {e}") from e
    keys = data.get("group", {}).get("keys", {}) if isinstance(data.get("group"), dict) else {}
    return {key: value for key, value in keys.items() if isinstance(value, dict)}


def merge_into_plan(plan: dict, entries: dict[str, dict]) -> None:
    """Put *entries* into the "Player names" group of a plan loaded with tomllib."""
    for group in plan.get("group", []):
        if group.get("name") == PLAYER_GROUP:
            group.setdefault("keys", {}).update(entries)
            return
