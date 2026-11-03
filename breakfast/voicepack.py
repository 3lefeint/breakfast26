"""Voice-pack selection: which sound directories are active.

Layout (single mount point, container-friendly):

    sounds/                     # [audio] dir — your own set, always the fallback
      matchon.mp3
      freipass.mp3
      achievements/             # jingles for earned achievements, searched last
        achievement.mp3
        achievement_ton_up.mp3
      profiles/                 # voice packs, one subdirectory each (tools/generate_voicepack.py)
        ryan/
          matchon.mp3
          ...

With `[audio] profile` set, the profile directory is searched first and your
own set covers any key the profile doesn't have (e.g. elimination-only
vocabulary). Fallback is per key, decided in AudioEngine: a key found in the
profile uses only the profile's variants — variants of one key are never
mixed across voices.
"""

import json
import logging
import os

log = logging.getLogger(__name__)

PROFILES_SUBDIR = "profiles"
# Jingles for earned achievements: not spoken, not part of a voice, so they live apart from
# the calls. Searched last; see achievements.AchievementEngine.announce().
ACHIEVEMENTS_SUBDIR = "achievements"
# The sound library of the scenes: files that are played by name from a scene, not the sound of a key.
SCENES_SUBDIR = "scenes"
# The files of a profile folder that were recorded by a person: a list of file names. Generating a pack never overwrites them.
RECORDED_FILE = "recorded.json"


def profile_name(plan) -> str:
    """The folder name of the profile a plan generates: its own `profile` entry (a plan copied for recordings), else the short
    name of its voice ("de-CH-LeniNeural" -> "leni")."""
    own = plan.get("profile")
    if isinstance(own, str) and own.strip():
        return own.strip()
    return plan["voice"].split("-")[-1].removesuffix("Neural").lower()


def read_recorded(out_dir) -> set:
    """The file names marked as recorded in a profile folder, empty when there are none or the list cannot be read."""
    try:
        with open(os.path.join(out_dir, RECORDED_FILE), encoding="utf-8") as f:
            names = json.load(f)
    except (OSError, ValueError):
        return set()
    return {n for n in names if isinstance(n, str)} if isinstance(names, list) else set()


def write_recorded(out_dir, names) -> None:
    if not names and not os.path.exists(os.path.join(out_dir, RECORDED_FILE)):
        return
    os.makedirs(out_dir, exist_ok=True)
    with open(os.path.join(out_dir, RECORDED_FILE), "w", encoding="utf-8") as f:
        json.dump(sorted(names), f)


def search_dirs(audio_dir, profile=None):
    """Ordered list of directories to look up sound files in."""
    dirs = []
    if profile:
        p = os.path.join(audio_dir, PROFILES_SUBDIR, profile)
        if os.path.isdir(p):
            dirs.append(p)
        else:
            log.warning("Audio profile '%s' not found under %s — using own set only",
                        profile, os.path.join(audio_dir, PROFILES_SUBDIR))
    dirs.append(audio_dir)
    dirs.append(os.path.join(audio_dir, ACHIEVEMENTS_SUBDIR))
    return dirs


def list_profiles(audio_dir):
    """Names of installed voice-pack profiles (sorted)."""
    base = os.path.join(audio_dir, PROFILES_SUBDIR)
    if not os.path.isdir(base):
        return []
    return sorted(d for d in os.listdir(base)
                  if os.path.isdir(os.path.join(base, d)))
