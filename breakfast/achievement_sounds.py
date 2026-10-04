"""Which sound an earned achievement plays.

The sounds live in the `achievements/` folder of the sound directory. An achievement plays, in this
order: the files assigned to it in `[achievements.sounds]` of `config.toml` (a random one of them),
else `achievement_<id>` (with its `+N` variants), else the general `achievement`, else nothing.

This module holds the parts the web page and the player share: reading the assignments, listing and
checking the files, and describing what plays now.
"""

import os
import re
from pathlib import Path

from . import config as cfg_mod
from .voicepack import ACHIEVEMENTS_SUBDIR

SECTION = "achievements"
KEY = "sounds"
MAX_UPLOAD_BYTES = 3 * 1024 * 1024
_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._+-]{0,63}\.mp3$")


def assignments(cfg: dict) -> dict:
    """{achievement id: [file names]} from a loaded config, a single file name counts as a list."""
    raw = (cfg.get(SECTION) or {}).get(KEY) or {}
    result = {}
    for key, value in raw.items():
        files = [value] if isinstance(value, str) else [v for v in value if isinstance(v, str)]
        if files:
            result[key] = files
    return result


def sound_dir(audio) -> Path | None:
    """The `achievements/` folder the audio engine searches, None without an audio engine."""
    for d in getattr(audio, "dirs", []):
        if os.path.basename(os.path.normpath(d)) == ACHIEVEMENTS_SUBDIR:
            return Path(d)
    return None


def files(audio) -> list:
    """The mp3 files in the achievements folder, sorted."""
    folder = sound_dir(audio)
    if not folder or not folder.is_dir():
        return []
    return sorted(p.name for p in folder.iterdir() if p.is_file() and p.suffix.lower() == ".mp3")


def playable(audio, filename: str) -> bool:
    """Is this a file of the achievements folder that the audio engine would really play: not
    shadowed by a file of the same name in another folder of the search path."""
    folder = sound_dir(audio)
    if not folder or filename not in files(audio):
        return False
    resolved = audio.resolve(filename)
    return bool(resolved) and Path(resolved).resolve() == (folder / filename).resolve()


def files_for(audio, cfg: dict, achievement_id: str) -> list:
    """The assigned files of an achievement that exist, in the order they were assigned."""
    return [f for f in assignments(cfg).get(achievement_id, []) if playable(audio, f)]


def plays_now(audio, cfg: dict, achievement_id: str) -> dict:
    """What would play for an achievement: `source` is "assigned", "id" (the file name convention),
    "generic" or "none", with the files."""
    assigned = files_for(audio, cfg, achievement_id)
    if assigned:
        return {"source": "assigned", "files": assigned}
    for source, key in (("id", f"achievement_{achievement_id}"), ("generic", "achievement")):
        found = audio.variants(key) if audio else []
        if found:
            return {"source": source, "files": found}
    return {"source": "none", "files": []}


def overview(audio, cfg: dict, definitions) -> dict:
    """Everything the page needs: the achievements with their assignment and what plays now, and
    the files that can be picked."""
    mine = assignments(cfg)
    folder = sound_dir(audio)
    names = {d.id: d.names for d in definitions}
    return {
        "files": files(audio),
        "file_details": [{
            "name": f, "size": (folder / f).stat().st_size,
            "used_by": [{"id": i, "names": names.get(i)} for i in used_by(cfg, f)],
        } for f in files(audio)],
        "achievements": [{
            "id": a.id, "names": a.names, "mode": a.mode, "difficulty": a.difficulty,
            "hidden": a.hidden, "tiers": list(a.tiers) if a.tiers else None,
            "assigned": mine.get(a.id, []),
            "missing": [f for f in mine.get(a.id, []) if not playable(audio, f)],
            "plays_now": plays_now(audio, cfg, a.id),
        } for a in definitions],
    }


def _write(config_path, mine: dict):
    """Write the whole `sounds` table back; an empty table removes it."""
    cfg_mod.write(config_path, {SECTION: {KEY: mine or None}})


def set_assignment(config_path, achievement_id: str, chosen: list) -> list:
    """Store the files of one achievement in `config.toml`; an empty list clears it. Returns what
    is stored. The whole `sounds` table is written back, so a cleared last entry removes it."""
    mine = assignments(cfg_mod.load(config_path))
    if chosen:
        mine[achievement_id] = list(chosen)
    else:
        mine.pop(achievement_id, None)
    _write(config_path, mine)
    return mine.get(achievement_id, [])


def used_by(cfg: dict, filename: str) -> list:
    """The ids of the achievements a file is assigned to."""
    return [i for i, fs in assignments(cfg).items() if filename in fs]


def _forget(audio, filename: str):
    """Drop a file name from the audio engine's cache of variants (`x+1.mp3` is a variant of `x`)."""
    audio.invalidate(re.sub(r"(\+\d+)?\.mp3$", "", filename))


def rename_file(audio, config_path, old: str, new: str):
    """Rename a file of the achievements folder, and in every assignment that uses it. Returns None
    when done, else why not."""
    if not playable(audio, old):
        return "not a sound of the achievements folder"
    if not _NAME.match(new or ""):
        return "the name must be letters, digits and . _ + - and end in .mp3"
    if new == old:
        return "the name is the same"
    folder = sound_dir(audio)
    if audio.resolve(new) or (folder / new).exists():
        return "a sound with this name exists already"
    (folder / old).rename(folder / new)
    mine = assignments(cfg_mod.load(config_path))
    if any(old in fs for fs in mine.values()):
        _write(config_path, {i: [new if f == old else f for f in fs] for i, fs in mine.items()})
    _forget(audio, old)
    _forget(audio, new)
    return None


def delete_file(audio, config_path, name: str):
    """Delete a file of the achievements folder and take it out of every assignment. Returns None
    when done, else why not."""
    if not playable(audio, name):
        return "not a sound of the achievements folder"
    (sound_dir(audio) / name).unlink()
    mine = assignments(cfg_mod.load(config_path))
    if any(name in fs for fs in mine.values()):
        _write(config_path, {i: [f for f in fs if f != name] for i, fs in mine.items() if any(f != name for f in fs)})
    _forget(audio, name)
    return None


def check_upload(audio, name: str, data: bytes):
    """None if the upload is fine, else why it is not."""
    if not _NAME.match(name or ""):
        return "the name must be letters, digits and . _ + - and end in .mp3"
    if not data:
        return "the file is empty"
    if len(data) > MAX_UPLOAD_BYTES:
        return f"the file is larger than {MAX_UPLOAD_BYTES // (1024 * 1024)} MB"
    if not (data[:3] == b"ID3" or (data[0] == 0xFF and data[1] & 0xE0 == 0xE0)):
        return "this does not look like an mp3 file"
    if sound_dir(audio) is None:
        return "no sound directory is configured"
    if audio.resolve(name):
        return "a sound with this name exists already"
    return None


def save_upload(audio, name: str, data: bytes):
    """Write an uploaded mp3 into the achievements folder. Returns None when saved, else why not."""
    problem = check_upload(audio, name, data)
    if problem:
        return problem
    folder = sound_dir(audio)
    folder.mkdir(parents=True, exist_ok=True)
    (folder / name).write_bytes(data)
    _forget(audio, name)
    return None
