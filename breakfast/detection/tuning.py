"""The settings of the tracker that can be changed from the Board page while it runs, and the clean-up of old sessions.

Only settings that make sense to an operator are listed, each with its range: a value outside it is refused, so a typo cannot switch the
detection off. The values are kept in `tracker_settings.json` in the detection folder and win over `config.toml`; resetting removes the
file. Which cameras and devices are used needs a restart and stays in
`config.toml`; the exposure and the white balance of the cameras are here."""
import json
import shutil
from dataclasses import fields
from pathlib import Path

# name -> (kind, lowest, highest); the texts of the page are in the frontend
TUNABLE = {
    "settle_s": ("float", 0.1, 2.0),
    "motion_fraction": ("float", 0.0005, 0.02),
    "uncertain_margin_mm": ("float", 0.0, 6.0),
    "uncertain_sigma": ("float", 0.5, 5.0),
    "recount": ("bool", None, None),
    "recount_looks": ("int", 1, 5),
    "exposure": ("int", 1, 2000),
    "white_balance": ("int", 2800, 6500),
}
AUTOMATIC = {"exposure", "white_balance"}              # 0 is allowed besides the range: the camera's automatic


def describe(settings):
    """What the page shows: every tunable setting with its value, range and texts."""
    return [{"key": k, "kind": kind, "min": lo, "max": hi, "value": getattr(settings, k),
             "default": _default(k)} for k, (kind, lo, hi) in TUNABLE.items()]


def _default(key):
    from breakfast.detection.tracker import Settings
    return next(f.default for f in fields(Settings) if f.name == key)


def coerce(key, value):
    """The value as the setting's type, or ValueError with the reason."""
    if key not in TUNABLE:
        raise ValueError(f"{key} cannot be changed here")
    kind, lo, hi = TUNABLE[key]
    if kind == "bool":
        if not isinstance(value, bool):
            raise ValueError(f"{key} must be true or false")
        return value
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{key} must be a number")
    value = int(value) if kind == "int" and float(value).is_integer() else float(value)
    if kind == "int" and not isinstance(value, int):
        raise ValueError(f"{key} must be a whole number")
    if key in AUTOMATIC and value == 0:
        return 0
    if not lo <= value <= hi:
        raise ValueError(f"{key} must be between {lo} and {hi}")
    return value


def apply(settings, changes):
    """Set what is valid on `settings`. Returns (values applied, {key: reason} of those refused)."""
    done, refused = {}, {}
    for key, value in changes.items():
        try:
            done[key] = coerce(key, value)
        except ValueError as e:
            refused[key] = str(e)
    for key, value in done.items():
        setattr(settings, key, value)
    return done, refused


def load(path):
    try:
        data = json.loads(Path(path).read_text())
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def save(path, values):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(values, indent=1))


def clean_sessions(folder, keep=10, max_gb=2.0, current=None):
    """Remove the oldest session folders of the event pictures: keep the newest `keep` and stay under `max_gb` together. The session in
    use is never removed. Returns the names removed."""
    folder = Path(folder)
    if not folder.is_dir():
        return []
    sessions = sorted((p for p in folder.iterdir() if p.is_dir()), key=lambda p: p.name)

    def size(p):
        return sum(f.stat().st_size for f in p.rglob("*") if f.is_file())

    sizes = {p: size(p) for p in sessions}
    removed = []
    for p in sessions:                                  # oldest first
        too_many = len(sessions) - len(removed) > keep
        too_big = sum(sizes[q] for q in sessions if q.name not in removed) > max_gb * 1024 ** 3
        if (too_many or too_big) and p.name != getattr(current, "name", current):
            shutil.rmtree(p, ignore_errors=True)
            removed.append(p.name)
    return removed
