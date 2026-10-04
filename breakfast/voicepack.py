"""Voice-pack selection: which sound directories are active.

Layout (single mount point, container-friendly):

    sounds/                     # [audio] dir — your own set, always the fallback
      matchon.mp3
      freipass.mp3
      achievements/             # jingles for earned achievements, searched last
        achievement.mp3
        achievement_ton_up.mp3
      profiles/                 # installed voice packs, one subdirectory each
        en-US-Joey-Male/
          matchon.mp3
          ...

With `[audio] profile` set, the profile directory is searched first and your
own set covers any key the profile doesn't have (e.g. elimination-only
vocabulary). Fallback is per key, decided in AudioEngine: a key found in the
profile uses only the profile's variants — variants of one key are never
mixed across voices.
"""

import csv
import logging
import os
import shutil
import tempfile
import zipfile

log = logging.getLogger(__name__)

PROFILES_SUBDIR = "profiles"
# Jingles for earned achievements: not spoken, not part of a voice, so they live apart from
# the calls. Searched last; see achievements.AchievementEngine.announce().
ACHIEVEMENTS_SUBDIR = "achievements"

_CDN = "https://darts-downloads.peschi.org/soundfiles"

# Downloadable voice packs (from the darts-caller project's catalog).
# NOTE: this is a third-party CDN run by the darts-caller successor's
# maintainer — no license is published for these files. Using them is a
# deliberate user choice; nothing is downloaded unless explicitly requested
# via `main.py voicepack --install`.
AVAILABLE_PROFILES = {
    # Amazon Polly
    "nl-NL-Laura-Female":    f"{_CDN}/amazon/nl-NL-Laura-Female.zip",
    "fr-FR-Remi-Male":       f"{_CDN}/amazon/fr-FR-Remi-Male.zip",
    "fr-FR-Lea-Female":      f"{_CDN}/amazon/fr-FR-Lea-Female.zip",
    "es-ES-Lucia-Female":    f"{_CDN}/amazon/es-ES-Lucia-Female.zip",
    "es-ES-Sergio-Male":     f"{_CDN}/amazon/es-ES-Sergio-Male.zip",
    "de-AT-Hannah-Female":   f"{_CDN}/amazon/de-AT-Hannah-Female.zip",
    "de-DE-Vicki-Female":    f"{_CDN}/amazon/de-DE-Vicki-Female.zip",
    "de-DE-Daniel-Male":     f"{_CDN}/amazon/de-DE-Daniel-Male.zip",
    "en-US-Ivy-Female":      f"{_CDN}/amazon/en-US-Ivy-Female.zip",
    "en-US-Joey-Male":       f"{_CDN}/amazon/en-US-Joey-Male.zip",
    "en-US-Joanna-Female":   f"{_CDN}/amazon/en-US-Joanna-Female.zip",
    "en-US-Matthew-Male":    f"{_CDN}/amazon/en-US-Matthew-Male.zip",
    "en-US-Danielle-Female": f"{_CDN}/amazon/en-US-Danielle-Female.zip",
    "en-US-Kimberly-Female": f"{_CDN}/amazon/en-US-Kimberly-Female.zip",
    "en-US-Ruth-Female":     f"{_CDN}/amazon/en-US-Ruth-Female.zip",
    "en-US-Salli-Female":    f"{_CDN}/amazon/en-US-Salli-Female.zip",
    "en-US-Kevin-Male":      f"{_CDN}/amazon/en-US-Kevin-Male.zip",
    "en-US-Justin-Male":     f"{_CDN}/amazon/en-US-Justin-Male.zip",
    "en-US-Stephen-Male":    f"{_CDN}/amazon/en-US-Stephen-Male.zip",
    "en-US-Kendra-Female":   f"{_CDN}/amazon/en-US-Kendra-Female.zip",
    "en-US-Gregory-Male":    f"{_CDN}/amazon/en-US-Gregory-Male.zip",
    "en-GB-Amy-Female":      f"{_CDN}/amazon/en-GB-Amy-Female.zip",
    "en-GB-Arthur-Male":     f"{_CDN}/amazon/en-GB-Arthur-Male.zip",
    "en-GB-Brian-Male":      f"{_CDN}/amazon/en-GB-Brian-Male.zip",
    "en-GB-Emma-Female":     f"{_CDN}/amazon/en-GB-Emma-Female.zip",
    # Google
    "de-DE-Chirp3-HD-Achird-MALE":    f"{_CDN}/google/de-DE-Chirp3-HD-Achird-MALE.zip",
    "de-DE-Chirp3-HD-Algenib-MALE":   f"{_CDN}/google/de-DE-Chirp3-HD-Algenib-MALE.zip",
    "de-DE-Chirp3-HD-Alnilam-MALE":   f"{_CDN}/google/de-DE-Chirp3-HD-Alnilam-MALE.zip",
    "de-DE-Chirp3-HD-Aoede-FEMALE":   f"{_CDN}/google/de-DE-Chirp3-HD-Aoede-FEMALE.zip",
    "de-DE-Chirp3-HD-Enceladus-MALE": f"{_CDN}/google/de-DE-Chirp3-HD-Enceladus-MALE.zip",
    "de-DE-Chirp3-HD-Puck-MALE":      f"{_CDN}/google/de-DE-Chirp3-HD-Puck-MALE.zip",
    "de-DE-Chirp3-HD-Schedar-MALE":   f"{_CDN}/google/de-DE-Chirp3-HD-Schedar-MALE.zip",
    "en-GB-Chirp3-HD-Achird-MALE":    f"{_CDN}/google/en-GB-Chirp3-HD-Achird-MALE.zip",
    "en-GB-Chirp3-HD-Enceladus-MALE": f"{_CDN}/google/en-GB-Chirp3-HD-Enceladus-MALE.zip",
    "en-GB-Chirp3-HD-Puck-MALE":      f"{_CDN}/google/en-GB-Chirp3-HD-Puck-MALE.zip",
    "en-US-Chirp3-HD-Achird-MALE":    f"{_CDN}/google/en-US-Chirp3-HD-Achird-MALE.zip",
    "en-US-Chirp3-HD-Enceladus-MALE": f"{_CDN}/google/en-US-Chirp3-HD-Enceladus-MALE.zip",
    "en-US-Chirp3-HD-Puck-MALE":      f"{_CDN}/google/en-US-Chirp3-HD-Puck-MALE.zip",
    # OpenAI
    "de-DE-ash-MALE":      f"{_CDN}/openai/de-DE-ash-MALE.zip",
    "de-DE-ballad-MALE":   f"{_CDN}/openai/de-DE-ballad-MALE.zip",
    "de-DE-coral-FEMALE":  f"{_CDN}/openai/de-DE-coral-FEMALE.zip",
    "de-DE-onyx-MALE":     f"{_CDN}/openai/de-DE-onyx-MALE.zip",
    "de-DE-sage-FEMALE":   f"{_CDN}/openai/de-DE-sage-FEMALE.zip",
    "en-GB-ash-MALE":      f"{_CDN}/openai/en-GB-ash-MALE-v2.zip",
    "en-GB-ballad-MALE":   f"{_CDN}/openai/en-GB-ballad-MALE-v2.zip",
    "en-GB-coral-FEMALE":  f"{_CDN}/openai/en-GB-coral-FEMALE.zip",
    "en-GB-onyx-MALE":     f"{_CDN}/openai/en-GB-onyx-MALE-v2.zip",
    "en-GB-sage-FEMALE":   f"{_CDN}/openai/en-GB-sage-FEMALE.zip",
    "en-GB-verse-MALE":    f"{_CDN}/openai/en-GB-verse-MALE.zip",
    "en-US-ash-MALE":      f"{_CDN}/openai/en-US-ash-MALE-v2.zip",
    "en-US-ballad-MALE":   f"{_CDN}/openai/en-US-ballad-MALE-v2.zip",
    "en-US-coral-FEMALE":  f"{_CDN}/openai/en-US-coral-FEMALE.zip",
    "en-US-onyx-MALE":     f"{_CDN}/openai/en-US-onyx-MALE-v2.zip",
    "en-US-sage-FEMALE":   f"{_CDN}/openai/en-US-sage-FEMALE.zip",
}

SOUND_EXTENSIONS = (".mp3", ".wav")


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


def install_profile(audio_dir, name, url=None, force=False):
    """Download and install a voice pack into <audio_dir>/profiles/<name>/.

    *url* may also be a path to a local pack zip (offline install / tests).
    Pack format (darts-caller convention): a zip containing a nested zip of
    sound files plus a `;`-separated CSV template — row i names the call
    key(s) for the i-th sound file in sorted order; rows without a key
    column use the lowercased spoken text as the key. Duplicate keys become
    `key+1`, `key+2`, ... variants.

    Returns the profile directory. Skips the download if already installed
    (unless *force*).
    """
    url = url or AVAILABLE_PROFILES.get(name)
    if not url:
        raise ValueError(f"Unknown voice pack '{name}' and no --url given "
                         f"(see AVAILABLE_PROFILES)")
    dest = os.path.join(audio_dir, PROFILES_SUBDIR, name)
    if os.path.isdir(dest) and not force:
        log.info("Voice pack '%s' already installed at %s", name, dest)
        return dest

    with tempfile.TemporaryDirectory(prefix="voicepack-") as tmp:
        pack = os.path.join(tmp, "pack.zip")
        if os.path.isfile(url):
            shutil.copyfile(url, pack)
        else:
            import requests
            log.info("Downloading voice pack '%s' ...", name)
            with requests.get(url, stream=True, timeout=60) as r:
                r.raise_for_status()
                with open(pack, "wb") as f:
                    shutil.copyfileobj(r.raw, f)

        extract = os.path.join(tmp, "extract")
        os.mkdir(extract)
        with zipfile.ZipFile(pack) as z:
            z.extractall(extract)
        # The outer zip nests the actual sound archive as another zip.
        for root, _dirs, files in os.walk(extract):
            for f in files:
                if f.endswith(".zip"):
                    inner = os.path.join(root, f)
                    with zipfile.ZipFile(inner) as z:
                        z.extractall(extract)
                    os.remove(inner)

        keys_per_row = _parse_template(extract)
        sounds = _collect_sounds(extract)
        if not keys_per_row or not sounds:
            raise RuntimeError(f"Voice pack '{name}': no template CSV or no "
                               f"sound files found in the archive")
        if len(keys_per_row) != len(sounds):
            log.warning("Voice pack '%s': %d template rows vs %d sound files "
                        "— mapping the overlapping range",
                        name, len(keys_per_row), len(sounds))

        staging = os.path.join(tmp, "staging")
        os.mkdir(staging)
        for keys, sound in zip(keys_per_row, sounds):
            ext = os.path.splitext(sound)[1].lower()
            for key in keys:
                target = os.path.join(staging, key + ext)
                n = 0
                while os.path.exists(target):
                    n += 1
                    target = os.path.join(staging, f"{key}+{n}{ext}")
                shutil.copyfile(sound, target)

        if os.path.isdir(dest):
            shutil.rmtree(dest)
        os.makedirs(os.path.dirname(dest), exist_ok=True)
        shutil.move(staging, dest)

    log.info("Voice pack '%s' installed: %s", name, dest)
    return dest


def _parse_template(root):
    """Rows of call keys from the first CSV template found."""
    for r, _dirs, files in sorted(os.walk(root)):
        for f in sorted(files):
            if f.endswith(".csv"):
                with open(os.path.join(r, f), encoding="utf-8-sig") as fh:
                    rows = []
                    for row in csv.reader(fh, delimiter=";"):
                        cells = [c.strip() for c in row if c.strip()]
                        if not cells:
                            continue
                        keys = cells[1:] if len(cells) > 1 else [cells[0].lower()]
                        rows.append(keys)
                    return rows
    return []


def _collect_sounds(root):
    """All sound files under *root*, in the deterministic order the
    darts-caller pack format maps template rows to (sorted walk)."""
    sounds = []
    for r, dirs, files in sorted(os.walk(root)):
        dirs.sort()
        for f in sorted(files):
            if f.lower().endswith(SOUND_EXTENSIONS):
                sounds.append(os.path.join(r, f))
    return sounds
