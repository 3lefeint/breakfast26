"""Read/write/synthesize support for the Settings "Voice Pack" editor.

Complements tools/generate_voicepack.py's bulk generator with per-key
operations (add/edit one entry, delete one variant) driven by the Web UI.
Uses tomlkit instead of tomllib for the plan file specifically because
this module writes it back — tomllib+tomli_w (the pattern breakfast/
config.py already uses for config.toml) parses into plain dicts with no
comment/formatting metadata, so writing back would silently strip every
comment in the plan (section banners, per-key rationale notes) on the
first save. tools/generate_voicepack.py's own bulk-generate path is
untouched by this module and keeps using tomllib (read-only, so no risk).
"""

import re
from pathlib import Path

import tomlkit

from breakfast import voicepack
from breakfast import voicepack_overlay as vo


def load_plan(path: Path):
    return tomlkit.parse(path.read_text(encoding="utf-8"))


def save_plan(path: Path, doc):
    path.write_text(tomlkit.dumps(doc), encoding="utf-8")


_OVERLAY_TEMPLATE = """\
# Private player names for this voice pack (git ignores this folder). Same format as the "Player names"
# group of the plan; an entry here replaces the entry of the same key in the plan.

[group.keys]
"""


def merge_overlay(doc, entries: dict):
    """A copy of the plan *doc* with the private player *entries* merged into its "Player names"
    group. Never save this copy as the plan, it holds the names that must stay out of git."""
    merged = tomlkit.parse(tomlkit.dumps(doc))
    group = _find_group(merged, vo.PLAYER_GROUP)
    if group is None:
        return merged
    table = group.setdefault("keys", tomlkit.table())
    for key, value in entries.items():
        entry = tomlkit.table()
        for field, v in value.items():
            entry[field] = v
        table[key] = entry
    return merged


def _plain(value):
    return value.unwrap() if hasattr(value, "unwrap") else value


def overlay_changes(plan_doc, merged_doc) -> dict[str, dict]:
    """The entries of the "Player names" group of *merged_doc* that the plain *plan_doc* does not have
    as they are: what belongs into the private file. ValueError if an entry of the plan is gone,
    because the file cannot take an entry away from the plan."""
    plan_group, merged_group = _find_group(plan_doc, vo.PLAYER_GROUP), _find_group(merged_doc, vo.PLAYER_GROUP)
    plan_keys = {k: _plain(v) for k, v in (plan_group.get("keys", {}) if plan_group is not None else {}).items()}
    merged_keys = {k: _plain(v) for k, v in (merged_group.get("keys", {}) if merged_group is not None else {}).items()}
    gone = sorted(set(plan_keys) - set(merged_keys))
    if gone:
        raise ValueError(f"{gone[0]} is part of the plan and cannot be removed here")
    return {k: v for k, v in merged_keys.items() if plan_keys.get(k) != v}


def write_overlay(path: Path, changes: dict[str, dict]):
    """Write *changes* as the entries of the private file at *path*, creating the file and its folder
    on the first call and keeping the comments of an existing file."""
    path = Path(path)
    doc = tomlkit.parse(path.read_text(encoding="utf-8") if path.is_file() else _OVERLAY_TEMPLATE)
    group = doc.setdefault("group", tomlkit.table())
    keys = group.setdefault("keys", tomlkit.table())
    for key in [k for k in keys if k not in changes]:
        del keys[key]
    for key, value in changes.items():
        entry = tomlkit.table()
        for field, v in value.items():
            entry[field] = v
        keys[key] = entry
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(tomlkit.dumps(doc), encoding="utf-8")


def profile_dir_name(doc) -> str:
    """"de-CH-LeniNeural" -> "leni" — same derivation server.py's bulk
    generate endpoint and generate_voicepack.py's main() both use (`voicepack.profile_name`)."""
    return voicepack.profile_name(doc)


def list_groups(doc) -> list[dict]:
    return [{"name": g["name"], "is_range": "range" in g} for g in doc["group"]]


def variant_filename(stem: str, index: int) -> str:
    return f"{stem}.mp3" if index == 0 else f"{stem}+{index}.mp3"


def _find_group(doc, group_name):
    for g in doc["group"]:
        if g["name"] == group_name:
            return g
    return None


def _filename_stem(group, key: str) -> str:
    """The actual on-disk key (no .mp3/+N suffix) for *key* in *group* —
    range groups prefix it (e.g. key_prefix="require_" -> stem "require_21"
    for key "21"), matching generate_voicepack.py's resolve_entries()."""
    if "range" in group:
        return f"{group['range'].get('key_prefix', '')}{key}"
    return key


def _entries_table(group):
    """The tomlkit table holding this group's keyed entries — range
    overrides for a range group, `keys` otherwise."""
    if "range" in group:
        return group["range"].setdefault("overrides", tomlkit.table())
    return group.setdefault("keys", tomlkit.table())


def list_entries(doc, group_name: str, out_dir: Path) -> list[dict] | None:
    """Every key currently defined in *group_name*'s TOML plan, with each
    variant's text and whether its .mp3 has actually been generated yet.
    None if *group_name* doesn't exist."""
    group = _find_group(doc, group_name)
    if group is None:
        return None
    table = group["range"].get("overrides", {}) if "range" in group else group.get("keys", {})
    entries = [_entry(group, key, value, out_dir) for key, value in table.items()]
    entries.sort(key=lambda e: e["key"])
    return entries


def _entry(group, key, value, out_dir: Path) -> dict:
    variants = value.get("variants", []) if isinstance(value, dict) else []
    stem = _filename_stem(group, key)
    files = [
        {
            "index": i,
            "text": text,
            "filename": variant_filename(stem, i),
            "has_file": (out_dir / variant_filename(stem, i)).is_file(),
        }
        for i, text in enumerate(variants)
    ]
    return {"key": key, "variants": files}


def entry_prosody(doc, group_name: str, key: str) -> dict | None:
    """Effective (rate, pitch, volume) for *key* — its own override if it
    has one, else the group's default — same fallback resolve_value() uses.
    None if the group doesn't exist."""
    group = _find_group(doc, group_name)
    if group is None:
        return None
    table = group["range"].get("overrides", {}) if "range" in group else group.get("keys", {})
    entry = table.get(key)
    existing = entry if isinstance(entry, dict) else {}
    return {
        "rate": existing.get("rate", group.get("rate", "+0%")),
        "pitch": existing.get("pitch", group.get("pitch", "+0Hz")),
        "volume": existing.get("volume", group.get("volume", "+0%")),
    }


def upsert_entry(doc, group_name: str, key: str, variants: list[str]) -> dict | None:
    """Set *key*'s variants list to exactly *variants*, replacing whatever
    was there before but keeping any existing per-key rate/pitch/volume
    override untouched. Returns {"stem", "old_count"} — *old_count* is how
    many variant files existed before this save, so the caller knows how
    many trailing files to prune if the new list is shorter. None if
    *group_name* doesn't exist."""
    group = _find_group(doc, group_name)
    if group is None:
        return None
    table = _entries_table(group)
    existing = table.get(key)
    old_count = len(existing.get("variants", [])) if isinstance(existing, dict) else 0
    entry = existing if isinstance(existing, dict) else tomlkit.table()
    entry["variants"] = variants
    table[key] = entry
    return {"stem": _filename_stem(group, key), "old_count": old_count}


def remove_variant(doc, group_name: str, key: str, index: int) -> dict | None:
    """Remove the variant at *index* from *key*'s list (deletes the whole
    key from the plan if that was its last variant). Returns
    {"stem", "new_count"} — *new_count* is how many variants remain, i.e.
    the caller must delete/renumber on-disk files so exactly indices
    0..new_count-1 exist afterward (AudioEngine._variants() stops scanning
    at the first gap, so a stray leftover file beyond new_count would be
    silently unreachable dead weight otherwise). None if not found."""
    group = _find_group(doc, group_name)
    if group is None:
        return None
    table = group["range"].get("overrides", {}) if "range" in group else group.get("keys", {})
    entry = table.get(key)
    if not isinstance(entry, dict) or "variants" not in entry:
        return None
    variants = list(entry["variants"])
    if not (0 <= index < len(variants)):
        return None
    del variants[index]
    if variants:
        entry["variants"] = variants
    else:
        del table[key]
    return {"stem": _filename_stem(group, key), "new_count": len(variants)}


def prune_extra_variant_files(out_dir: Path, stem: str, keep_count: int, recorded=()):
    """Delete <stem>+N.mp3 files at or beyond *keep_count* — used after a
    save shrinks a key's variant list, so no file survives past what the
    plan (and AudioEngine's gap-stops-the-scan convention) says exists.
    The first recorded file and the ones after it stay: a recording is never deleted by a plan."""
    i = keep_count
    while True:
        p = out_dir / variant_filename(stem, i)
        if not p.is_file() or p.name in recorded:
            break
        p.unlink()
        i += 1


def renumber_after_delete(out_dir: Path, stem: str, deleted_index: int, new_count: int, recorded=None):
    """After removing the variant at *deleted_index*, delete its file and
    shift every higher-indexed file down by one so the remaining files stay
    contiguous from index 0. *recorded*, a set of file names, follows the files."""
    (out_dir / variant_filename(stem, deleted_index)).unlink(missing_ok=True)
    if recorded is not None:
        recorded.discard(variant_filename(stem, deleted_index))
    i = deleted_index + 1
    while (out_dir / variant_filename(stem, i)).is_file():
        src, dest = variant_filename(stem, i), variant_filename(stem, i - 1)
        (out_dir / src).rename(out_dir / dest)
        if recorded is not None and src in recorded:
            recorded.discard(src)
            recorded.add(dest)
        i += 1


async def synthesize_entry(voice, rate, pitch, volume, out_dir: Path, stem: str,
                            texts: list[str], trim: bool = True, keep=()):
    """(Re)generate every variant file for one key, overwriting any that
    already exist — matches editing the TOML by hand and re-running the
    CLI generator with --force for just that one key.

    Imports `synthesize()` lazily (not at module load time) so merely
    importing this module doesn't require edge-tts to be installed — same
    discipline tools/generate_voicepack.py's own callers already follow."""
    from tools.generate_voicepack import synthesize

    out_dir.mkdir(parents=True, exist_ok=True)
    for i, text in enumerate(texts):
        dest = out_dir / variant_filename(stem, i)
        if dest.name in keep:                    # a recording stays
            continue
        await synthesize(voice, text, rate, pitch, volume, dest, trim)


# ── Recording a pack with your own voice ──────────────────────────────────────

_FILE = re.compile(r"^(.+?)(?:\+(\d+))?\.mp3$")


def _first_text(value, default: str) -> str:
    """The text to read for an entry of a plan: its first variant, its text, the plain string, else *default*."""
    if isinstance(value, dict):
        variants = value.get("variants")
        if variants:
            return str(variants[0])
        return str(value.get("text", default))
    return str(value) if value is not None else default


def group_keys(group) -> list[dict]:
    """Every key of a group as {"key": the file stem, "text": what to read}, whether or not it has a file yet."""
    rows = []
    if "range" in group:
        rng = group["range"]
        prefix = rng.get("key_prefix", "")
        exclude = set(rng.get("exclude", []))
        overrides = rng.get("overrides", {})
        for n in range(rng["start"], rng["end"] + 1):
            if n not in exclude:
                rows.append({"key": f"{prefix}{n}", "text": _first_text(overrides.get(str(n)), str(n))})
    else:
        for key, value in group.get("keys", {}).items():
            rows.append({"key": str(key), "text": _first_text(value, str(key))})
    return rows


def _files_of(present: set, stem: str) -> list[str]:
    """The contiguous variant files of a key, the way AudioEngine finds them."""
    files, i = [], 0
    while variant_filename(stem, i) in present:
        files.append(variant_filename(stem, i))
        i += 1
    return files


def _present(out_dir: Path) -> set:
    return {p.name for p in out_dir.iterdir() if p.is_file()} if out_dir.is_dir() else set()


def _status(files: list, recorded) -> str:
    if not files:
        return "missing"
    return "recorded" if any(f in recorded for f in files) else "generated"


def recording_rows(doc, group_name: str, out_dir: Path, recorded) -> list[dict] | None:
    """The keys of a group for the recording view: key, text, status (recorded, generated, missing) and the variant files
    with a flag for the recorded ones. None if the group does not exist."""
    group = _find_group(doc, group_name)
    if group is None:
        return None
    present = _present(out_dir)
    rows = []
    for item in group_keys(group):
        files = _files_of(present, item["key"])
        rows.append({**item, "status": _status(files, recorded),
                     "variants": [{"index": i, "filename": f, "recorded": f in recorded} for i, f in enumerate(files)]})
    return rows


def recording_counts(doc, out_dir: Path, recorded) -> dict:
    """{"total", "recorded", "generated", "missing"} over the keys of every group, and the same for each group."""
    present = _present(out_dir)
    total = {"total": 0, "recorded": 0, "generated": 0, "missing": 0}
    groups = {}
    for group in doc["group"]:
        counts = {"total": 0, "recorded": 0, "generated": 0, "missing": 0}
        for item in group_keys(group):
            status = _status(_files_of(present, item["key"]), recorded)
            counts["total"] += 1
            counts[status] += 1
        groups[group["name"]] = counts
        for k, v in counts.items():
            total[k] += v
    return {**total, "groups": groups}


def recording_target(doc, filename: str, out_dir: Path):
    """(stem, index) for a file name a recording may be stored under: a key of the plan, and the index of an existing variant
    (replaced) or the next one (added). Else the reason why not as a string."""
    m = _FILE.match(filename or "")
    if not m:
        return "not a voice-pack file name"
    stem, index = m.group(1), int(m.group(2) or 0)
    if m.group(2) is not None and (index < 1 or str(index) != m.group(2)):
        return "not a voice-pack file name"
    if stem not in {item["key"] for group in doc["group"] for item in group_keys(group)}:
        return "not a key of this pack"
    if index > len(_files_of(_present(out_dir), stem)):
        return "the variants of a key follow each other without a gap"
    return stem, index
