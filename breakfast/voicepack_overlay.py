"""The private player-name file of a voice pack.

The plans in `tools/` are tracked by git, so the names of the players do not belong there. They live
in `<data dir>/voicepack/<pack>.toml` instead (git ignores `data/`), in the format of the plan's
"Player names" group:

    [group.keys.anna]
    variants = ["Anna", "Annie"]

Whoever loads a plan merges these entries into its "Player names" group: the generator, the Voice Pack
tab and the preview. An entry here replaces an entry of the same key in the plan.
"""

import os
import re
import tomllib
from pathlib import Path

import tomlkit

from breakfast.names import normalize

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


def lowercase_keys(path: Path) -> dict[str, str]:
    """Change the keys of the private file at *path* to lower case, the form player names are stored in (names.py).
    A key whose lower-case twin exists is dropped, the twin stays. Returns {old key: new key} of what changed, `{}`
    for a file that is missing or has nothing to change; the comments of the file are kept."""
    path = Path(path)
    try:
        doc = tomlkit.parse(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {}
    except (OSError, UnicodeDecodeError, tomlkit.exceptions.TOMLKitError) as e:
        raise ValueError(f"{path.name}: {e}") from e
    group = doc.get("group")
    keys = group.get("keys") if group is not None else None
    if not keys:
        return {}
    changed = {}
    for key in [k for k in keys if normalize(k) != k]:
        low = normalize(key)
        entry = keys[key]
        del keys[key]
        if low not in keys:
            moved = tomlkit.table()
            for field, value in entry.items():
                moved[field] = value
            keys[low] = moved
        changed[key] = low
    if changed:
        path.write_text(tomlkit.dumps(doc), encoding="utf-8")
    return changed


def rename_sound_files(directory: Path, renames: dict[str, str]) -> list[str]:
    """Give the voice files of the renamed keys their new names (`Anna.mp3`, `Anna+1.mp3` become `anna.mp3`,
    `anna+1.mp3`). A file is left alone when one with the new name exists. Returns the new names."""
    directory = Path(directory)
    if not directory.is_dir():
        return []
    done = []
    for old, new in renames.items():
        pattern = re.compile(rf"^{re.escape(old)}(\+\d+)?\.mp3$")
        for entry in sorted(directory.iterdir()):
            match = pattern.match(entry.name)
            if not match:
                continue
            target = directory / f"{new}{match.group(1) or ''}.mp3"
            if os.path.lexists(target) and not os.path.samefile(entry, target):
                continue
            entry.rename(target)
            done.append(target.name)
    return done
