"""Cut, fade and level a sound with ffmpeg: the part between two marks, a fade in and out, the loudness of the library.

Every sound of the library is brought to the same loudness, so a scene only has to set a volume when one sound should be
quieter or louder than the rest. The level is the mean of two measures: the loudness of the part (LUFS) and its highest
sample, taken back by what a pure tone peaks above its loudness. The sounds are short effects, and neither measure alone
says how loud one is: the loudness misses a sharp hit, the peak overrates a thin click. A pure tone ends up at
`TARGET_LUFS`. A peak limiter keeps the sound from clipping; a part shorter than 400 ms is set by its highest sample
(`SHORT_PEAK`).
"""

import re
import shutil
import subprocess
import tempfile
from pathlib import Path

TARGET_LUFS = -16
LIMIT = 0.841                 # -1.5 dBFS
WINDOW = 0.4                  # seconds the loudness measurement needs at least
PEAK_OFFSET = 3.7             # a pure tone peaks this far (dB) above its loudness in LUFS
TRIM_MAX = 6
CURVE_MIN, CURVE_MAX = 0.25, 4
SHORT_PEAK = -3.0
MIN_SECONDS = 0.05
MAX_SECONDS = 60
MAX_SOURCE_BYTES = 20 * 1024 * 1024
TIMEOUT = 60


def available() -> bool:
    return shutil.which("ffmpeg") is not None


def _run(args, timeout=TIMEOUT):
    return subprocess.run(["ffmpeg", "-hide_banner", "-nostdin", "-y", *args], capture_output=True, text=True,
                          timeout=timeout)


def _integrated(source: Path, cut: str) -> float | None:
    """The loudness in LUFS of the cut part (the quiet parts around a hit do not count), None when it is silent or shorter
    than the 400 ms the measurement needs."""
    done = _run(["-i", str(source), "-af", f"{cut},ebur128", "-f", "null", "-"])
    found = re.findall(r"\bI:\s+(-?[\d.]+) LUFS", done.stderr)
    return float(found[-1]) if done.returncode == 0 and found and float(found[-1]) > -70 else None


def _peak(source: Path, cut: str) -> float | None:
    """The highest sample of the cut part in dB."""
    done = _run(["-i", str(source), "-af", f"{cut},volumedetect", "-f", "null", "-"])
    found = re.search(r"max_volume: (-?[\d.]+) dB", done.stderr)
    return float(found.group(1)) if found and done.returncode == 0 else None


def _fades(length, fade_in, fade_out, curve_in, curve_out) -> str:
    """The filter of the two fades. A curve is the power the level follows along the fade: 1 is linear, above 1 starts
    quietly, below 1 starts loud. Each sample gets its own level, so a short fade has no steps."""
    if curve_in == 1 and curve_out == 1:
        parts = []
        if fade_in:
            parts.append(f"afade=t=in:st=0:d={fade_in:.3f}")
        if fade_out:
            parts.append(f"afade=t=out:st={length - fade_out:.3f}:d={fade_out:.3f}")
        return ",".join(parts)
    gain = []
    if fade_in:
        gain.append(f"if(lt(t,{fade_in:.3f}),pow(t/{fade_in:.3f},{curve_in:.3f}),1)")
    if fade_out:
        gain.append(f"if(gt(t,{length - fade_out:.3f}),pow(max(({length:.3f}-t)/{fade_out:.3f},0),{curve_out:.3f}),1)")
    return f"aeval='val(ch)*{'*'.join(gain)}':c=same"


def render(data: bytes, start: float, end: float, fade_in: float = 0, fade_out: float = 0, trim: float = 0,
           curve_in: float = 1, curve_out: float = 1):
    """The mp3 bytes of the part from *start* to *end* seconds, or the reason why not as a string.

    The fades lie inside the part and are applied after the loudness is set. *trim* (dB, at most TRIM_MAX either way)
    makes this one sound quieter or louder than the level of the library."""
    trim = max(-TRIM_MAX, min(TRIM_MAX, trim))
    curve_in, curve_out = (max(CURVE_MIN, min(CURVE_MAX, c)) for c in (curve_in, curve_out))
    if not available():
        return "ffmpeg is not installed"
    if not data:
        return "the file is empty"
    if len(data) > MAX_SOURCE_BYTES:
        return f"the file is larger than {MAX_SOURCE_BYTES // (1024 * 1024)} MB"
    length = end - start
    if start < 0 or length < MIN_SECONDS:
        return "the selection is too short"
    if length > MAX_SECONDS:
        return f"the selection is longer than {MAX_SECONDS} seconds"
    fade_in = max(0.0, min(fade_in, length))
    fade_out = max(0.0, min(fade_out, length - fade_in))
    cut = f"atrim=start={start:.3f}:end={end:.3f},asetpts=PTS-STARTPTS"
    with tempfile.TemporaryDirectory() as tmp:
        source, target = Path(tmp, "in"), Path(tmp, "out.mp3")
        source.write_bytes(data)
        try:
            chain = [cut]
            peak = _peak(source, cut)
            if peak is not None and peak > -70:
                average = _integrated(source, cut) if length >= WINDOW else None
                if average is None:                                   # too short to be measured by loudness
                    chain.append(f"volume={SHORT_PEAK - peak + trim:.2f}dB")
                else:
                    level = (average + peak - PEAK_OFFSET) / 2
                    chain.append(f"volume={TARGET_LUFS - level + trim:.2f}dB,"
                                 f"alimiter=limit={LIMIT:.3f}:attack=1:release=50:level=disabled")
            if fade_in or fade_out:
                chain.append(_fades(length, fade_in, fade_out, curve_in, curve_out))
            done = _run(["-i", str(source), "-af", ",".join(chain), "-ar", "44100", "-codec:a", "libmp3lame",
                         "-q:a", "2", str(target)])
        except subprocess.TimeoutExpired:
            return "the file took too long to process"
        if done.returncode or not target.is_file():
            return "this file could not be read as audio"
        return target.read_bytes()
