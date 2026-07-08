"""Browser-based audio engine.

Breakfast never touches OS audio directly. This engine resolves a sound key
to a concrete file (picking a random variant from name.mp3, name+1.mp3, ...)
and broadcasts a play instruction to the web clients connected with
role=audio (see the /audio page). The browser fetches the file via
GET /api/sound/{filename} and plays it.

Playback semantics implemented by the browser player:
- channel "voice": sequential queue — each sound waits for the previous one
  (the old darts-caller wait_for_last as default behavior).
  break_last=True stops the current voice sound and clears the queue first.
- channel "ambient": separate parallel channel, never interrupts voice.
  Keys starting with "ambient_" go there automatically.

A `with engine.batch():` block groups several play() calls into a single
`sound_batch` message (an ordered list of items) instead of one `sound`
message per call, so the browser can fetch a whole known sequence in
parallel instead of one phrase at a time — see AudioEngine.batch().
"""

import contextlib
import hashlib
import logging
import os
import random
import threading

log = logging.getLogger(__name__)


class AudioEngine:
    def __init__(self, dirs, broadcast=None):
        """*dirs*: one directory or an ordered search path (first match per
        key wins — see voicepack.search_dirs())."""
        self.dirs = [dirs] if isinstance(dirs, str) else list(dirs)
        self._broadcast = broadcast
        self._cache = {}
        self._batch_local = threading.local()
        # Deterministic hash of the resolved dir search path, which already
        # encodes the active audio profile (voicepack.search_dirs() puts the
        # profile dir first) — used as a browser cache-busting key for
        # GET /api/sound/{filename}. Not a random per-process token: a plain
        # restart with no profile/config change should not bust the cache,
        # and the profile can't change without a restart anyway (it's not in
        # config.py's RUNTIME_FIELDS).
        self.version = hashlib.sha1("|".join(self.dirs).encode()).hexdigest()[:10]
        log.info("Audio engine started (browser playback), dirs=%s", self.dirs)

    def play(self, name, prob=1.0, volume=1.0, channel=None, break_last=False):
        """Send one sound to the audio clients. Returns True if a file for
        *name* exists and an instruction was sent — callers use this for
        fallback chains (try key A, else key B). If called inside a
        `with self.batch():` block, the instruction is buffered and sent as
        part of that batch's single `sound_batch` message instead of its own
        `sound` message — the True/False return is unaffected either way, so
        fallback-chain decisions never depend on whether batching is active."""
        if prob < 1.0 and random.random() >= prob:
            return False
        files = self._variants(name)
        if not files:
            return False
        filename = random.choice(files)
        channel = channel or self._default_channel(name)
        items = getattr(self._batch_local, "items", None)
        if items is not None:
            items.append({"file": filename, "channel": channel,
                          "volume": volume, "break_last": break_last})
        else:
            self._send(filename, channel, volume, break_last)
        return True

    def play_sequence(self, *names):
        """Send multiple sounds to play in order (voice queue preserves order)."""
        for name in names:
            self.play(name)

    @contextlib.contextmanager
    def batch(self):
        """Buffer every play() call made inside this block and flush them as
        one ordered `sound_batch` broadcast on exit, instead of one `sound`
        broadcast per call — lets the browser fetch a whole known sequence
        (e.g. a turn-end call) in parallel instead of one phrase at a time.

        Re-entrant: a nested `with audio.batch():` (e.g. elimination.py's
        _finish_match() opening its own batch while already called from
        inside _publish_turn_preview()'s batch) just keeps appending to the
        already-open outer batch — only the outermost block flushes, so
        nested sequences still collapse into a single wire message.

        Thread-local rather than a plain attribute: elimination.py's
        _play_start_calls() fires via its own threading.Timer, a different
        thread than the one processing board/MQTT events, so two unrelated
        batches must never interleave."""
        local = self._batch_local
        if getattr(local, "items", None) is not None:
            yield  # already batching — outer block owns the flush
            return
        local.items = []
        try:
            yield
        finally:
            items, local.items = local.items, None
            if items:
                self._send_batch(items)

    def resolve(self, filename):
        """Map a filename from a play instruction back to a real path for the
        HTTP sound route. Searches the same directory order used for lookup,
        so profile files shadow own-set files of the same name. Returns None
        for unknown or unsafe names."""
        if "/" in filename or "\\" in filename or ".." in filename:
            return None
        for d in self.dirs:
            path = os.path.join(d, filename)
            if os.path.isfile(path):
                return path
        return None

    @staticmethod
    def _default_channel(name):
        return "ambient" if name.startswith("ambient_") else "voice"

    def has_audio(self, name: str) -> bool:
        """True if at least one variant file exists for *name*, without
        playing it — e.g. to flag a player name with no recording in the UI."""
        return bool(self._variants(name))

    def _variants(self, name):
        """All variant filenames for *name* from the first directory that has
        the key at all — variants of one key are never mixed across dirs."""
        if name in self._cache:
            return self._cache[name]
        files = []
        for d in self.dirs:
            if os.path.isfile(os.path.join(d, f"{name}.mp3")):
                files.append(f"{name}.mp3")
            i = 1
            while True:
                fn = f"{name}+{i}.mp3"
                if os.path.isfile(os.path.join(d, fn)):
                    files.append(fn)
                    i += 1
                else:
                    break
            if files:
                break
        self._cache[name] = files
        if not files:
            log.debug("No audio file for: %s", name)
        return files

    def _send(self, filename, channel, volume, break_last):
        if not self._broadcast:
            log.debug("No audio broadcast wired; dropping %s", filename)
            return
        self._broadcast({
            "type": "sound",
            "file": filename,
            "channel": channel,
            "volume": volume,
            "break_last": break_last,
            "v": self.version,
        })

    def _send_batch(self, items):
        if not self._broadcast:
            log.debug("No audio broadcast wired; dropping batch of %d", len(items))
            return
        self._broadcast({"type": "sound_batch", "v": self.version, "items": items})
