"""The sound library of the scenes: the mp3 files in the `scenes/` folder of the sound directory.

A scene plays a file by its name. The folder is a library folder of the audio engine, so its files are never taken
for the sound of a key (a file called `nice.mp3` here is not the `nice` call).
"""

import logging
import os
import re
import tempfile
from pathlib import Path

from . import scenes, sound_edit

log = logging.getLogger(__name__)

MAX_UPLOAD_BYTES = 3 * 1024 * 1024
MAX_SPEECH_CHARS = 200
SPEECH_RATE = (-50, 100)       # percent, relative to the voice
SPEECH_PITCH = (-50, 50)       # Hz, relative to the voice
_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._+-]{0,63}\.mp3$")


def folder(audio) -> Path | None:
    """The library folder, None without an audio engine or a sound directory."""
    dirs = getattr(audio, "library_dirs", None)
    return Path(dirs[0]) if dirs else None


def files(audio) -> list:
    path = folder(audio)
    if not path or not path.is_dir():
        return []
    return sorted(p.name for p in path.iterdir() if p.is_file() and p.suffix.lower() == ".mp3")


def used_by(scene_list: list, filename: str) -> list:
    """The names of the scenes that play a file."""
    return [s["name"] for s in scene_list if filename in scenes.sound_files(s["graph"])]


def overview(audio, scene_list: list) -> list:
    path = folder(audio)
    return [{"name": f, "size": (path / f).stat().st_size, "used_by": used_by(scene_list, f)} for f in files(audio)]


def check_upload(audio, name: str, data: bytes, overwrite: bool = False):
    """None if the upload is fine, else why it is not."""
    if not _NAME.match(name or ""):
        return "the name must be letters, digits and . _ + - and end in .mp3"
    if not data:
        return "the file is empty"
    if len(data) > MAX_UPLOAD_BYTES:
        return f"the file is larger than {MAX_UPLOAD_BYTES // (1024 * 1024)} MB"
    if not (data[:3] == b"ID3" or (data[0] == 0xFF and data[1] & 0xE0 == 0xE0)):
        return "this does not look like an mp3 file"
    if folder(audio) is None:
        return "no sound directory is configured"
    if name in files(audio) and not overwrite:
        return "a sound with this name exists already"
    return None


def save_upload(audio, name: str, data: bytes, overwrite: bool = False):
    """Write an uploaded mp3 into the library. Returns None when saved, else why not."""
    problem = check_upload(audio, name, data, overwrite)
    if problem:
        return problem
    path = folder(audio)
    path.mkdir(parents=True, exist_ok=True)
    (path / name).write_bytes(data)
    audio.files_changed()
    return None


def name_problem(audio, name: str, overwrite: bool = False):
    """None if a file of this name can be written to the library, else why not."""
    if not _NAME.match(name or ""):
        return "the name must be letters, digits and . _ + - and end in .mp3"
    if folder(audio) is None:
        return "no sound directory is configured"
    if name in files(audio) and not overwrite:
        return "a sound with this name exists already"
    return None


def speech_problem(text: str, rate: int, pitch: int):
    """None if this text and these settings can be spoken, else why not."""
    if not (text or "").strip():
        return "the text is empty"
    if len(text) > MAX_SPEECH_CHARS:
        return f"the text is longer than {MAX_SPEECH_CHARS} characters"
    if not SPEECH_RATE[0] <= rate <= SPEECH_RATE[1]:
        return f"the speed must be between {SPEECH_RATE[0]} and {SPEECH_RATE[1]} %"
    if not SPEECH_PITCH[0] <= pitch <= SPEECH_PITCH[1]:
        return f"the pitch must be between {SPEECH_PITCH[0]} and {SPEECH_PITCH[1]} Hz"
    return None


async def speak(voice: str, text: str, rate: int, pitch: int):
    """The mp3 of *text* spoken by *voice* (a voice of the voice-pack plans), silence at both ends trimmed as for the voice
    packs. Returns the bytes, or a string saying why not. The text goes to the speech service, so this needs the internet."""
    try:
        from tools.generate_voicepack import synthesize
    except ImportError:
        return "speech is not available here"
    fd, tmp = tempfile.mkstemp(suffix=".mp3", prefix="scene-speech-")
    os.close(fd)
    dest = Path(tmp)
    try:
        await synthesize(voice, text.strip(), f"{rate:+d}%", f"{pitch:+d}Hz", "+0%", dest, trim=sound_edit.available())
        return dest.read_bytes()
    except Exception as e:
        log.warning("Scene speech failed: %s", e)
        return f"the speech could not be created: {e}"
    finally:
        dest.unlink(missing_ok=True)


def delete_file(audio, name: str):
    """Delete a file of the library. Returns None when done, else why not. A scene that plays it stays as it is and
    plays nothing for that node."""
    if name not in files(audio):
        return "not a sound of the library"
    (folder(audio) / name).unlink()
    audio.files_changed()
    return None


def save_edit(audio, name: str, data: bytes, start: float, end: float, fade_in: float, fade_out: float,
              overwrite: bool = False, trim: float = 0, curve_in: float = 1, curve_out: float = 1,
              low_cut: bool = False, noise: str = "", compress: str = ""):
    """Cut, fade and level the sound in *data* and store the result under *name*. Returns None when saved, else why not."""
    if not _NAME.match(name or ""):
        return "the name must be letters, digits and . _ + - and end in .mp3"
    if folder(audio) is None:
        return "no sound directory is configured"
    if name in files(audio) and not overwrite:
        return "a sound with this name exists already"
    result = sound_edit.render(data, start, end, fade_in, fade_out, trim, curve_in, curve_out, low_cut, noise, compress)
    if isinstance(result, str):
        return result
    return save_upload(audio, name, result, overwrite)


def rename_file(audio, engine, old: str, new: str):
    """Rename a file of the library and the sound steps of the scenes that play it. Returns None when done, else why not."""
    if old not in files(audio):
        return "not a sound of the library"
    if not _NAME.match(new or ""):
        return "the name must be letters, digits and . _ + - and end in .mp3"
    if new in files(audio):
        return "a sound with this name exists already"
    (folder(audio) / old).rename(folder(audio) / new)
    audio.files_changed()
    for scene in engine.store.list_scenes() if engine else []:
        graph = scenes.upgrade_graph(scene["graph"])
        hits = [n for n in graph.get("nodes", []) if n.get("kind") == "sound" and any(e["file"] == old for e in n["files"])]
        for node in hits:
            node["files"] = scenes.sound_entries({"files": [{**e, "file": new if e["file"] == old else e["file"]} for e in node["files"]]})
        if hits:
            engine.store.save_scene(scene["id"], {**scene, "graph": graph}, slug=scene.get("slug"))
    if engine:
        engine.changed()
    return None
