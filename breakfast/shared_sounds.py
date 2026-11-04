"""Scenes and achievement sounds shared in the circle (see relay/PROTOCOL.md, "Circle").

The relay stores a sound file once per hash (sha256 of the bytes); a shared scene or achievement entry names its files
by `{file, hash}`. This module is the local half: it describes what this site publishes, and stores what the other sites
published: scenes as read-only copies (`scenes.source`), achievement sounds in `shared_achievement_sounds.json` next to
`config.toml`, used only for an achievement that has no sound of its own.
"""

import hashlib
import json
import logging
import os
import re
import threading
from pathlib import Path

from . import achievement_sounds as ach_sounds
from . import scene_sounds, scenes

log = logging.getLogger(__name__)

MAX_SHARE_BYTES = 2 * 1024 * 1024      # a larger file is not shared (the relay refuses it)
STORE = "shared_achievement_sounds.json"
_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._+-]{0,63}\.mp3$")


class SoundUnavailable(Exception):
    """The relay will not hand out a sound (unknown, refused): a retry does not help."""


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _stem(name: str) -> str:
    return name[:-4] if name.lower().endswith(".mp3") else name


class SharedSounds:
    def __init__(self, db, config_path, engine=None, audio=None):
        """*engine*, *audio*: functions that return the scene engine and the audio engine (they are set after this object)."""
        self._db = db
        self._engine = engine or (lambda: None)
        self._audio = audio or (lambda: None)
        self.config_path = Path(config_path)
        self._store_path = self.config_path.parent / STORE
        self._lock = threading.RLock()
        self._hashes = {}               # path -> (mtime_ns, size, hash)

    # ── what this site publishes ──────────────────────────────────────────────

    def _hash_of(self, path: Path):
        """(hash, size) of a file, None when it is missing or too large to share. Hashed again only when the file changed."""
        try:
            stat = path.stat()
        except OSError:
            return None
        if stat.st_size == 0 or stat.st_size > MAX_SHARE_BYTES:
            return None
        key = str(path)
        cached = self._hashes.get(key)
        if cached and cached[:2] == (stat.st_mtime_ns, stat.st_size):
            return cached[2], stat.st_size
        try:
            value = digest(path.read_bytes())
        except OSError:
            return None
        self._hashes[key] = (stat.st_mtime_ns, stat.st_size, value)
        return value, stat.st_size

    def _listed(self, folder, names):
        """[{file, hash}] and {hash: path} of the files that exist in the folder and can be shared."""
        entries, blobs = [], {}
        for name in names:
            found = self._hash_of(folder / name) if folder else None
            if found:
                entries.append({"file": name, "hash": found[0]})
                blobs[found[0]] = folder / name
        return entries, blobs

    def scene_payloads(self):
        """({share id: {name, graph, sounds}}, {hash: path}) of the scenes of the user that are shared. A sound that is
        missing here or too large is left out of the list; the copies mark the step."""
        audio = self._audio()
        folder = scene_sounds.folder(audio) if audio else None
        payloads, blobs = {}, {}
        for row in self._db.list_scenes():
            if not row.get("shared") or row.get("slug") or row.get("source") or not row.get("share_id"):
                continue
            graph = scenes.upgrade_graph(row["graph"])
            entries, found = self._listed(folder, scenes.sound_files(graph))
            payloads[row["share_id"]] = {"name": row["name"], "graph": graph, "sounds": entries}
            blobs.update(found)
        return payloads, blobs

    def achievement_payloads(self):
        """({achievement id: [{file, hash}]}, {hash: path}) of the sounds assigned to achievements."""
        audio = self._audio()
        if not audio:
            return {}, {}
        from . import config as cfg_mod
        folder = ach_sounds.sound_dir(audio)
        payloads, blobs = {}, {}
        for achievement, names in ach_sounds.assignments(cfg_mod.load(self.config_path)).items():
            entries, found = self._listed(folder, [n for n in names if ach_sounds.playable(audio, n)])
            if entries:
                payloads[achievement] = entries
                blobs.update(found)
        return payloads, blobs

    def problems(self, graph) -> dict:
        """{node id: code} for the steps of a graph that cannot run here: `sound` (a file that is not in the library),
        `call` (a voice key the voice pack has no sound for), `player` (a name that is no player here). Plain keys only: a key
        with a placeholder, a fallback or a combination is not checked."""
        audio = self._audio()
        library = set(scene_sounds.files(audio)) if audio else set()
        players = set(self._db.list_players()) if hasattr(self._db, "list_players") else set()
        found = {}
        for node in (graph or {}).get("nodes", []):
            kind = node.get("kind")
            if kind == "sound" and any(e["file"] not in library for e in scenes.sound_entries(node)):
                found[node["id"]] = "sound"
            elif kind == "call" and audio and re.fullmatch(r"[a-z0-9_]+", node.get("key") or "") and not audio.variants(node["key"]):
                found[node["id"]] = "call"
            elif kind == "player" and any(n.lower() not in players for n in node.get("names") or []):
                found[node["id"]] = "player"
        return found

    def can_take_scenes(self) -> bool:
        """Whether there is a sound library to put the sounds of a copy in (no sound directory: no audio engine)."""
        audio = self._audio()
        return bool(audio) and scene_sounds.folder(audio) is not None

    def can_take_achievements(self) -> bool:
        audio = self._audio()
        return bool(audio) and ach_sounds.sound_dir(audio) is not None

    # ── what the other sites published ────────────────────────────────────────

    def _place(self, folder: Path, name: str, wanted: str, fetch, save):
        """The name under which the library holds the file with this hash: its own name when that is free or holds the same
        bytes, else `<name>-<hash>.mp3`. Fetches and saves the file when it is not here. None when it cannot be had."""
        for candidate in (name, f"{_stem(name)}-{wanted[:8]}.mp3"):
            found = self._hash_of(folder / candidate)
            if found and found[0] == wanted:
                return candidate
            if (folder / candidate).exists():
                continue
            if not _NAME.match(candidate):
                return None
            try:
                data = fetch(wanted)
            except SoundUnavailable as e:         # any other error (the relay is not reachable) ends the round, it is tried again
                log.warning("SharedSounds: the sound %s could not be fetched: %s", name, e)
                return None
            if digest(data) != wanted:
                log.warning("SharedSounds: the sound %s does not match its hash", name)
                return None
            problem = save(candidate, data)
            if problem:
                log.warning("SharedSounds: the sound %s is not stored: %s", name, problem)
                return None
            return candidate
        return None

    def take_scene(self, entry, fetch):
        """Store (or update, or remove) the copy of a scene of another site. *fetch(hash)* returns the bytes of a sound."""
        engine, audio = self._engine(), self._audio()
        origin = entry["origin"]
        if entry.get("deleted"):
            removed = self._db.delete_scene_copy(origin["id"], entry["scene_id"])
            if removed and engine:
                engine.changed()
            return removed
        folder = scene_sounds.folder(audio) if audio else None
        names = {}
        for sound in entry.get("sounds") or []:
            if folder is None or not _NAME.match(sound.get("file", "")):
                continue
            placed = self._place(folder, sound["file"], sound["hash"], fetch,
                                 lambda name, data: scene_sounds.save_upload(audio, name, data))
            if placed:
                names[sound["file"]] = placed
            else:
                log.warning("SharedSounds: the sound %s of the scene %s is missing here", sound["file"], entry.get("name"))
        graph = scenes.clean_scene({"name": entry["name"], "graph": self._renamed(entry["graph"], names)})["graph"]
        self._db.upsert_scene_copy(origin["id"], entry["scene_id"], origin["name"], scenes.clean_scene({"name": entry["name"]})["name"], graph)
        if engine:
            engine.changed()
        return True

    @staticmethod
    def _renamed(graph, names):
        """The graph with the sound files under the names the library holds them by."""
        nodes = []
        for node in (graph or {}).get("nodes", []):
            if isinstance(node, dict) and node.get("kind") == "sound":
                node = {**node, "files": [{**e, "file": names.get(e.get("file"), e.get("file"))}
                                          for e in scenes.sound_entries(node)]}
                node.pop("file", None)
            nodes.append(node)
        return {**(graph or {}), "nodes": nodes}

    # achievement sounds of the other sites: {achievement: {origin id: {name, seq, files}}}

    def _read(self):
        try:
            data = json.loads(self._store_path.read_text())
            return data if isinstance(data, dict) else {}
        except (OSError, ValueError):
            return {}

    def _write(self, data):
        tmp = self._store_path.with_suffix(".tmp")
        tmp.write_text(json.dumps(data))
        os.replace(tmp, self._store_path)

    def take_achievement(self, entry, fetch):
        audio = self._audio()
        origin = entry["origin"]
        with self._lock:
            data = self._read()
            by_origin = data.setdefault(entry["achievement"], {})
            if entry.get("deleted"):
                by_origin.pop(origin["id"], None)
            else:
                folder = ach_sounds.sound_dir(audio) if audio else None
                names = []
                for sound in entry.get("files") or []:
                    if folder is None or not _NAME.match(sound.get("file", "")):
                        continue
                    placed = self._place(folder, sound["file"], sound["hash"], fetch,
                                         lambda name, blob: ach_sounds.save_upload(audio, name, blob))
                    if placed:
                        names.append(placed)
                    else:
                        log.warning("SharedSounds: the sound %s of %s is missing here", sound["file"], entry["achievement"])
                if names:
                    by_origin[origin["id"]] = {"name": origin["name"], "seq": entry.get("seq", 0), "files": names}
                else:
                    by_origin.pop(origin["id"], None)
            if not by_origin:
                data.pop(entry["achievement"], None)
            self._write(data)

    def forget_achievements(self):
        with self._lock:
            if self._store_path.exists():
                self._store_path.unlink()

    def achievement_shared(self, achievement_id):
        """{origin, files} of the newest shared sound of an achievement (files that are in the folder), None when there is none."""
        audio = self._audio()
        with self._lock:
            by_origin = self._read().get(achievement_id) or {}
        for item in sorted(by_origin.values(), key=lambda i: i.get("seq", 0), reverse=True):
            files = [f for f in item.get("files", []) if audio and ach_sounds.playable(audio, f)]
            if files:
                return {"origin": item.get("name"), "files": files}
        return None

    def achievement_files(self, achievement_id):
        """The files of a shared sound that plays for an achievement, []."""
        found = self.achievement_shared(achievement_id)
        return found["files"] if found else []
