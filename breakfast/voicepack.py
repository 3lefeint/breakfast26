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

import logging
import os

log = logging.getLogger(__name__)

PROFILES_SUBDIR = "profiles"
# Jingles for earned achievements: not spoken, not part of a voice, so they live apart from
# the calls. Searched last; see achievements.AchievementEngine.announce().
ACHIEVEMENTS_SUBDIR = "achievements"


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
