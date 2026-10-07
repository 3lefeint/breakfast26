#!/usr/bin/env python3
"""Generate a voice-pack profile from a TOML plan using edge-tts.

Reads a plan file (see tools/voicepack_leni.toml for the format: [[group]]
sections, each with a default rate/pitch/volume and either an explicit
`keys` table or a numeric `range`), synthesizes each entry with
`edge_tts.Communicate`, and writes `<key>.mp3` files into the target
profile directory (matching the layout `voicepack.py` already expects:
`<audio dir>/profiles/<name>/`).

A `keys.<key>` entry with a `variants` list (instead of `text`) generates
multiple *variants of the same key* — `<key>.mp3`, `<key>+1.mp3`,
`<key>+2.mp3`, ... — matching AudioEngine's existing random-pick-a-variant
convention. Use this for one person called by different nicknames (the
registered player name / lookup key stays the same; only which recording
gets played is randomized), not for different people.

Requires the `edge-tts` package (not a runtime dependency of Breakfast
itself — only needed to run this generator) and the `ffmpeg` binary (used
to trim the ~0.8-1s of silence edge-tts otherwise pads onto the end of
every clip — very noticeable as a gap when two calls play back to back,
e.g. "you_require" -> "require_140"):

    pip install edge-tts

Usage:
    python tools/generate_voicepack.py tools/voicepack_leni.toml
    python tools/generate_voicepack.py tools/voicepack_leni.toml --out sounds/profiles/leni
    python tools/generate_voicepack.py tools/voicepack_leni.toml --only "Score - achieved"
    python tools/generate_voicepack.py tools/voicepack_leni.toml --dry-run
    python tools/generate_voicepack.py tools/voicepack_leni.toml --force
    python tools/generate_voicepack.py tools/voicepack_leni.toml --no-trim
    python tools/generate_voicepack.py tools/voicepack_leni.toml --overlay data/voicepack/leni.toml

The names of the players are private: the plan's "Player names" group is extended by the entries of
`data/voicepack/<pack>.toml` (or the file given with --overlay), which git does not track.
"""

import argparse
import asyncio
import shutil
import sys
import tomllib
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))   # `breakfast` when run as a script
from breakfast import voicepack_overlay  # noqa: E402

try:
    import edge_tts
except ImportError:
    print("Missing dependency: pip install edge-tts", file=sys.stderr)
    sys.exit(1)

CONCURRENCY = 5

# Trims leading+trailing silence: forward pass removes the lead-in, then
# the same filter run on the reversed audio (and reversed back) removes
# the tail — edge-tts's default padding is otherwise ~0.8-1s per clip.
_TRIM_FILTER = (
    "silenceremove=start_periods=1:start_duration=0:start_threshold=-35dB:detection=peak,"
    "areverse,"
    "silenceremove=start_periods=1:start_duration=0:start_threshold=-35dB:detection=peak,"
    "areverse"
)


def resolve_value(key, value, default_text, g_rate, g_pitch, g_volume):
    """Expand one key's value (plain string / {text,...} / {variants,...})
    into (variant_key, text, rate, pitch, volume) tuples. A `variants` list
    produces <key>.mp3, <key>+1.mp3, <key>+2.mp3, ... (AudioEngine's
    existing random-pick-a-variant convention) — usable on any entry,
    including numeric range overrides, not just named keys."""
    if isinstance(value, dict) and "variants" in value:
        rate = value.get("rate", g_rate)
        pitch = value.get("pitch", g_pitch)
        volume = value.get("volume", g_volume)
        for i, text in enumerate(value["variants"]):
            variant_key = key if i == 0 else f"{key}+{i}"
            yield variant_key, text, rate, pitch, volume
        return
    if isinstance(value, dict):
        text = value.get("text", default_text)
        rate = value.get("rate", g_rate)
        pitch = value.get("pitch", g_pitch)
        volume = value.get("volume", g_volume)
    elif value is None:
        text, rate, pitch, volume = default_text, g_rate, g_pitch, g_volume
    else:
        text, rate, pitch, volume = value, g_rate, g_pitch, g_volume
    yield key, text, rate, pitch, volume


def resolve_entries(plan):
    """Yield (group_name, key, text, rate, pitch, volume) for every entry
    in the plan, in file order."""
    for group in plan["group"]:
        g_rate = group.get("rate", "+0%")
        g_pitch = group.get("pitch", "+0Hz")
        g_volume = group.get("volume", "+0%")
        name = group["name"]

        for key, value in group.get("keys", {}).items():
            for k, text, rate, pitch, volume in resolve_value(key, value, key, g_rate, g_pitch, g_volume):
                yield name, k, text, rate, pitch, volume

        rng = group.get("range")
        if rng:
            exclude = set(rng.get("exclude", []))
            prefix = rng.get("key_prefix", "")
            overrides = rng.get("overrides", {})
            for n in range(rng["start"], rng["end"] + 1):
                if n in exclude:
                    continue
                key = f"{prefix}{n}"
                override = overrides.get(str(n))
                for k, text, rate, pitch, volume in resolve_value(key, override, str(n), g_rate, g_pitch, g_volume):
                    yield name, k, text, rate, pitch, volume


async def synthesize(voice, text, rate, pitch, volume, dest, trim):
    communicate = edge_tts.Communicate(text, voice, rate=rate, pitch=pitch, volume=volume)
    await communicate.save(str(dest))
    if trim:
        await trim_silence(dest)


async def trim_silence(path):
    """Re-encode *path* in place with leading/trailing silence stripped."""
    tmp = path.with_suffix(".trim.mp3")
    proc = await asyncio.create_subprocess_exec(
        "ffmpeg", "-y", "-loglevel", "error",
        "-i", str(path), "-af", _TRIM_FILTER, str(tmp),
    )
    await proc.wait()
    if proc.returncode == 0 and tmp.exists():
        shutil.move(str(tmp), str(path))
    else:
        tmp.unlink(missing_ok=True)
        print(f"Warning: silence trim failed for {path}, keeping untrimmed file", file=sys.stderr)


async def run(plan, out_dir, only, force, dry_run, trim, on_progress=None):
    out_dir.mkdir(parents=True, exist_ok=True)
    entries = list(resolve_entries(plan))
    if only:
        entries = [e for e in entries if only.lower() in e[0].lower()]

    sem = asyncio.Semaphore(CONCURRENCY)
    total = len(entries)
    done = skipped = 0
    current_group = None

    async def worker(group_name, key, text, rate, pitch, volume):
        nonlocal done, skipped, current_group
        dest = out_dir / f"{key}.mp3"
        if dest.exists() and not force:
            skipped += 1
            if on_progress:
                on_progress(done, skipped, total)
            return
        if dry_run:
            print(f"[{group_name}] {key}: {text!r} (rate={rate} pitch={pitch} volume={volume})")
            return
        async with sem:
            await synthesize(plan["voice"], text, rate, pitch, volume, dest, trim)
        done += 1
        print(f"[{group_name}] {key} -> {dest}")
        if on_progress:
            on_progress(done, skipped, total)

    if dry_run:
        for group_name, key, text, rate, pitch, volume in entries:
            await worker(group_name, key, text, rate, pitch, volume)
        print(f"\n{len(entries)} entries planned (dry run, nothing written).")
        return

    await asyncio.gather(*(worker(*e) for e in entries))
    print(f"\nDone: {done} generated, {skipped} skipped (already existed).")
    if skipped and not force:
        print("Use --force to regenerate existing files.")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("plan", help="Path to a voicepack plan TOML file")
    ap.add_argument("--out", help="Output profile directory (default: sounds/profiles/<voice-name>)")
    ap.add_argument("--only", help="Only process groups whose name contains this substring")
    ap.add_argument("--force", action="store_true", help="Regenerate files that already exist")
    ap.add_argument("--dry-run", action="store_true", help="Print the resolved plan, generate nothing")
    ap.add_argument("--overlay", help="Private player-name file to merge into the plan "
                     "(default: data/voicepack/<voice-name>.toml if it exists)")
    ap.add_argument("--no-trim", action="store_true",
                     help="Skip the ffmpeg silence-trim pass (requires ffmpeg on PATH otherwise)")
    args = ap.parse_args()

    if not args.no_trim and not args.dry_run and not shutil.which("ffmpeg"):
        print("ffmpeg not found on PATH — install it, or pass --no-trim to keep "
              "edge-tts's ~0.8-1s of padding per clip.", file=sys.stderr)
        sys.exit(1)

    with open(args.plan, "rb") as f:
        plan = tomllib.load(f)

    # "de-CH-LeniNeural" -> "leni"
    short_name = plan["voice"].split("-")[-1].removesuffix("Neural").lower()
    out_dir = Path(args.out) if args.out else Path("sounds/profiles") / short_name

    overlay = Path(args.overlay) if args.overlay else voicepack_overlay.overlay_path("data", short_name)
    if args.overlay or overlay.is_file():
        try:
            voicepack_overlay.merge_into_plan(plan, voicepack_overlay.read_entries(overlay))
        except ValueError as e:
            print(f"Cannot read the player-name file: {e}", file=sys.stderr)
            sys.exit(1)

    asyncio.run(run(plan, out_dir, args.only, args.force, args.dry_run, not args.no_trim))


if __name__ == "__main__":
    main()
