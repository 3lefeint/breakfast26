#!/usr/bin/env python3
"""Generate achievement badge motifs with an image API.

Reads a plan file (see tools/badges.toml: `[modes.*]` accent colours and
`[[badge]]` entries with an id, a mode, a difficulty, an optional label and a
motif subject) and one style description per file in tools/badge_styles/.
A badge is drawn in the style of its mode (`style` in `[modes.*]`), else in
`[defaults] style`; --style draws every badge in the given styles instead.
For every badge and its style it asks the image API for a single motif
(one object, transparent background, no text, no border) and writes
`<out>/<style>/<id>_<YYYYMMDD-HHMMSS>.png`. The rim, the accent colour, the label and the
progress are drawn by the frontend, not by the image.

A motif is skipped when a file for it exists and the prompt, model, quality and
size are unchanged since it was generated (kept in `<out>/state.json`). A
changed prompt or style regenerates only the affected motifs. A regenerated
motif gets a new file name with a new timestamp, the old file stays; the newest
file of an id is the one that counts. To discard a motif, move its file out of
the style folder (then it counts as not generated).

The image API limits requests per minute by usage tier (5 on tier 1, 20 on tier 2).
--per-minute says how many the account may make (5 by default); the script spaces the
starts of the requests evenly under that limit and works out how many have to be in flight at the
same time, from how long an image takes (measured, see below). --delay and --jobs override the
two values. A 429 answer is retried after the pause the API asks for.

Before a run it says what the run will cost, and after every image it logs the tokens the API
reports and what they cost in tools/badge_work/cost_log.jsonl; the average of that log prices the
next run. tools/image_costs.toml holds the token prices and the start values (see there).

Needs no extra package, only the standard library. The API key is read from
the OPENAI_API_KEY environment variable and only when something has to be
generated.

Usage:
    python tools/generate_badges.py --dry-run
    python tools/generate_badges.py --style flat --only bullseye ton_up
    python tools/generate_badges.py
    python tools/generate_badges.py --force
    python tools/generate_badges.py --delay 0     # no pause, for a higher rate limit
    python tools/generate_badges.py --check
    python tools/generate_badges.py --preview
    python tools/generate_badges.py --export

--export scales the newest motif of every id of one style down to --export-size
px (256 by default) and writes it to frontend/src/lib/assets/badges/<id>.png
(the timestamp is dropped from the name), where the frontend picks it up. The transparent
margin is cut off and every motif is fitted into the same share of the canvas, so motifs the model
drew at different sizes come out equally large. It needs ImageMagick (magick or convert) and
skips motifs whose export is already newer than the original; --force exports all again.
--no-fit keeps the picture as the model drew it (margin and position) and only scales it.
"""

import argparse
import base64
import hashlib
import html
import json
import math
import os
import re
import shutil
import subprocess
import sys
import threading
import time
import tomllib
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

TOOLS_DIR = Path(__file__).resolve().parent
DEFAULT_PLAN = TOOLS_DIR / "badges.toml"
DEFAULT_STYLES = TOOLS_DIR / "badge_styles"
DEFAULT_OUT = TOOLS_DIR / "badge_work"
DEFAULT_EXPORT = TOOLS_DIR.parent / "frontend" / "src" / "lib" / "assets" / "badges"
COSTS_FILE = TOOLS_DIR / "image_costs.toml"
COST_LOG = DEFAULT_OUT / "cost_log.jsonl"

API_URL = "https://api.openai.com/v1/images/generations"
MODEL = "gpt-image-2.5-flare"
QUALITY = "medium"
SIZE = "1024x1024"
MAX_JOBS = 16
CONFIRM_ABOVE = 20
# Images per minute the account may request: the image API limits it by usage tier (5 on tier 1,
# 20 on tier 2). The requests start evenly spread, a little under that.
DEFAULT_PER_MINUTE = 5
DELAY_MARGIN = 1.08
# How long one image takes when nothing has been measured yet, to work out how many requests have
# to be in flight at the same time (rate times duration).
ASSUMED_SECONDS = 30.0
RATE_LIMIT_RETRIES = 5
EXPORT_SIZE = 256
EXPORT_FILL = 0.8      # how much of the canvas the longer side of a motif fills in the export

TIMESTAMP_FORMAT = "%Y%m%d-%H%M%S"
TIMESTAMP_RE = r"\d{8}-\d{6}"

STATE_FILE = "state.json"
PREVIEW_FILE = "preview.html"

REQUIREMENTS = """Requirements, identical for every badge motif:
- show only what the subject describes, add no extra objects or decoration
- one object or a small group, centered, with a simple, clear silhouette
- transparent background
- no text, no letters, no numbers
- no border, no surrounding circle, no frame, no badge shape
- generous empty padding around the object
- must stay readable when scaled down to 48 x 48 pixels"""


def load_plan(path):
    with open(path, "rb") as f:
        plan = tomllib.load(f)
    modes = plan.get("modes", {})
    badges = plan.get("badge", [])
    seen = set()
    for badge in badges:
        for key in ("id", "mode", "difficulty", "subject"):
            if not badge.get(key):
                raise ValueError(f"badge {badge.get('id', '?')!r}: missing {key!r}")
        if badge["id"] in seen:
            raise ValueError(f"duplicate badge id {badge['id']!r}")
        seen.add(badge["id"])
        if badge["mode"] not in modes:
            raise ValueError(f"badge {badge['id']!r}: unknown mode {badge['mode']!r}")
        if badge.get("colour", "accent") not in ("accent", "natural"):
            raise ValueError(f"badge {badge['id']!r}: colour must be 'accent' or 'natural'")
    return modes, badges


def load_default_style(path):
    """The style of every mode without its own `style`: `[defaults] style` of the plan."""
    with open(path, "rb") as f:
        return tomllib.load(f).get("defaults", {}).get("style")


def assign_styles(modes, badges, default_style):
    """{badge id: style name}: the style of the badge's mode, else the plan's default."""
    return {b["id"]: modes[b["mode"]].get("style") or default_style for b in badges}


def load_styles(styles_dir):
    return {p.stem: p.read_text().strip() for p in sorted(Path(styles_dir).glob("*.txt"))}


def build_prompt(style_text, badge, mode):
    accent = f"{mode['name']} ({mode['hex']})"
    if badge.get("colour") == "natural":
        colour = (f"Colour: draw the object in its natural colours. Use {accent} only as an accent "
                  "on one small detail.")
    else:
        colour = f"Colour: use {accent} as the dominant colour of the motif."
    return (
        f"Subject, draw exactly this:\n{badge['subject']}\n\n"
        f"{colour}\n\n"
        f"{style_text}\n\n"
        f"{REQUIREMENTS}"
    )


def timestamp():
    return time.strftime(TIMESTAMP_FORMAT)


def motif_files(out, style, badge_id):
    """The files of one motif, oldest first: `<id>_<timestamp>.png`, and the
    older plain `<id>.png` (which sorts first)."""
    pattern = re.compile(rf"^{re.escape(badge_id)}(?:_({TIMESTAMP_RE}))?\.png$")
    found = []
    style_dir = Path(out) / style
    if style_dir.is_dir():
        for path in style_dir.iterdir():
            match = pattern.match(path.name)
            if match:
                found.append((match.group(1) or "", path))
    return [path for _, path in sorted(found)]


def latest_motif(out, style, badge_id):
    files = motif_files(out, style, badge_id)
    return files[-1] if files else None


def motif_id(file_name):
    """The badge id a motif file belongs to: its name without `.png` and timestamp."""
    return re.sub(rf"(?:_{TIMESTAMP_RE})?\.png$", "", file_name)


def prompt_hash(prompt, model, quality, size):
    payload = json.dumps([prompt, model, quality, size])
    return hashlib.sha256(payload.encode()).hexdigest()


def load_state(out):
    path = Path(out) / STATE_FILE
    if path.exists():
        return json.loads(path.read_text())
    return {}


def plan_jobs(modes, badges, styles, out, selected_styles, only, force, model, quality, size, assigned=None):
    """One job per (style, badge): action is 'generate' (new), 'update' (prompt
    changed or forced) or 'skip' (file exists and the prompt is unchanged).
    With `assigned` ({badge id: style}) a badge only gets the job of its own style."""
    state = load_state(out)
    jobs = []
    for style in selected_styles:
        for badge in badges:
            if only and badge["id"] not in only:
                continue
            if assigned and assigned.get(badge["id"]) != style:
                continue
            prompt = build_prompt(styles[style], badge, modes[badge["mode"]])
            digest = prompt_hash(prompt, model, quality, size)
            key = f"{style}/{badge['id']}"
            if latest_motif(out, style, badge["id"]) is None:
                action = "generate"
            elif force or state.get(key, {}).get("hash") != digest:
                action = "update"
            else:
                action = "skip"
            jobs.append({"style": style, "id": badge["id"], "key": key,
                         "prompt": prompt, "hash": digest, "action": action})
    return jobs


class RateLimited(RuntimeError):
    """HTTP 429. `wait` is the pause in seconds the API asked for."""

    def __init__(self, message, wait):
        super().__init__(message)
        self.wait = wait


class Pacer:
    """Spaces the start of requests at least `delay` seconds apart, across threads."""

    def __init__(self, delay):
        self.delay = delay
        self._lock = threading.Lock()
        self._next = 0.0

    def wait(self):
        if self.delay <= 0:
            return
        with self._lock:
            now = time.monotonic()
            start = max(now, self._next)
            self._next = start + self.delay
        if start > now:
            time.sleep(start - now)


def parse_retry_wait(message, default=15.0):
    """Seconds from an API message like 'Please try again in 12s.' or '350ms'."""
    match = re.search(r"try again in ([\d.]+)(ms|s)\b", message)
    if not match:
        return default
    value = float(match.group(1))
    return value / 1000 if match.group(2) == "ms" else value


def request_image(api_key, prompt, model, quality, size):
    """Ask the image API for one transparent PNG and return its bytes and the usage it reports
    (tokens used, None if it reports none)."""
    body = json.dumps({
        "model": model, "quality": quality, "size": size,
        "background": "transparent", "output_format": "png", "prompt": prompt,
    }).encode()
    req = urllib.request.Request(API_URL, data=body, headers={
        "Authorization": f"Bearer {api_key}", "Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=300) as resp:
            data = json.load(resp)
    except urllib.error.HTTPError as e:
        try:
            message = json.load(e).get("error", {}).get("message", "")
        except ValueError:
            message = ""
        if e.code == 429:
            raise RateLimited(f"HTTP 429 {message}".strip(), parse_retry_wait(message)) from None
        raise RuntimeError(f"HTTP {e.code} {message}".strip()) from None
    return base64.b64decode(data["data"][0]["b64_json"]), data.get("usage")


def request_with_retry(pacer, api_key, job, model, quality, size, label):
    """One paced request; on a rate limit wait as long as the API asks and retry. Returns the
    image, the usage and the timing: `seconds` the successful request took, `retries` rate
    limit answers before it, `waited` the seconds between the call and the start of that request."""
    called = time.monotonic()
    retries = 0
    for attempt in range(RATE_LIMIT_RETRIES + 1):
        pacer.wait()
        started = time.monotonic()
        try:
            png, usage = request_image(api_key, job["prompt"], model, quality, size)
        except RateLimited as e:
            if attempt == RATE_LIMIT_RETRIES:
                raise
            retries += 1
            pause = e.wait + 1
            print(f"  … {label}: rate limited, retry in {pause:.0f}s", file=sys.stderr)
            time.sleep(pause)
            continue
        timing = {"seconds": round(time.monotonic() - started, 2), "retries": retries,
                  "waited": round(started - called, 2)}
        return png, usage, timing


def run_jobs(jobs, out, api_key, model, quality, size, max_jobs=MAX_JOBS, delay=0.0,
             prices=None, cost_log=None, costs=None):
    """Generate every job that is not a skip. Returns the list of failed keys. With `prices`
    (see load_prices) what every image cost is worked out from the tokens the API reports;
    it is appended to `costs` and written to the log file `cost_log`."""
    state_lock = threading.Lock()
    state = load_state(out)
    failed = []
    pacer = Pacer(delay)

    def work(job):
        try:
            png, usage, timing = request_with_retry(pacer, api_key, job, model, quality, size, job["key"])
            cost = usage_cost(prices, model, usage) if prices else None
            dest = Path(out) / job["style"] / f"{job['id']}_{timestamp()}.png"
            dest.parent.mkdir(parents=True, exist_ok=True)
            tmp = dest.with_suffix(".png.tmp")
            tmp.write_bytes(png)
            tmp.replace(dest)
            with state_lock:
                state[job["key"]] = {"hash": job["hash"], "model": model,
                                     "quality": quality, "size": size, "seconds": timing["seconds"]}
                if cost is not None:
                    state[job["key"]]["cost"] = round(cost, 5)
                    if costs is not None:
                        costs.append(cost)
                if cost_log:
                    log_cost(cost_log, {"time": time.strftime("%Y-%m-%dT%H:%M:%S"), "key": job["key"],
                                        "model": model, "quality": quality, "size": size,
                                        "usage": usage, "cost": None if cost is None else round(cost, 5),
                                        **timing})
                (Path(out) / STATE_FILE).write_text(json.dumps(state, indent=2, sort_keys=True))
            note = ", ".join(([f"${cost:.4f}"] if cost is not None else []) + [f"{timing['seconds']:.1f} s"])
            print(f"  ✓ {job['key']} ({note})")
        except Exception as e:  # keep going, report at the end
            with state_lock:
                failed.append(job["key"])
            print(f"  ✗ {job['key']}: {e}", file=sys.stderr)

    todo = [j for j in jobs if j["action"] != "skip"]
    Path(out).mkdir(parents=True, exist_ok=True)
    with ThreadPoolExecutor(max_workers=max_jobs) as pool:
        list(pool.map(work, todo))
    return failed


def check(out, badges, styles, selected_styles, model, quality, size, modes, assigned=None):
    """Return a list of problems: missing, outdated or orphan motif files."""
    problems = []
    state = load_state(out)
    ids = {b["id"] for b in badges}
    for style in selected_styles:
        for badge in badges:
            if assigned and assigned.get(badge["id"]) != style:
                continue
            key = f"{style}/{badge['id']}"
            if latest_motif(out, style, badge["id"]) is None:
                problems.append(f"missing: {key}")
                continue
            prompt = build_prompt(styles[style], badge, modes[badge["mode"]])
            if state.get(key, {}).get("hash") != prompt_hash(prompt, model, quality, size):
                problems.append(f"outdated: {key}")
        style_dir = Path(out) / style
        if style_dir.is_dir():
            for png in sorted(style_dir.glob("*.png")):
                if motif_id(png.name) not in ids:
                    problems.append(f"orphan: {style}/{png.name}")
    return problems


def write_preview(out, badges, selected_styles, assigned=None):
    """A static page that shows every generated motif at 48, 96 and 192 px on a
    dark and a light background, one row per style."""
    rows = []
    for style in selected_styles:
        cards = []
        for badge in badges:
            if assigned and assigned.get(badge["id"]) != style:
                continue
            latest = latest_motif(out, style, badge["id"])
            if latest is None:
                continue
            rel = f"{style}/{latest.name}"
            sizes = "".join(
                f'<img src="{html.escape(rel)}" width="{s}" height="{s}" alt="">' for s in (48, 96, 192))
            cards.append(f'<figure><div class="dark">{sizes}</div><div class="light">{sizes}</div>'
                         f'<figcaption>{html.escape(badge["id"])}</figcaption></figure>')
        rows.append(f"<h2>{html.escape(style)}</h2><div class='row'>{''.join(cards)}</div>")
    page = ("<!doctype html><meta charset='utf-8'><title>Badge motifs</title>"
            "<style>body{font:14px sans-serif;margin:1rem;background:#222;color:#eee}"
            ".row{display:flex;flex-wrap:wrap;gap:1rem}figure{margin:0}"
            ".dark,.light{display:flex;align-items:center;gap:.5rem;padding:.5rem}"
            ".dark{background:#121212}.light{background:#f4f4f4}</style>"
            + "".join(rows))
    path = Path(out) / PREVIEW_FILE
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(page)
    return path


def find_imagemagick():
    return shutil.which("magick") or shutil.which("convert")


def fit_motif(tool, src, target, size, fill=EXPORT_FILL, fit=True):
    """Write `src` to `target` as a `size` x `size` PNG. Without `fit` the picture is only
    scaled, with its margin and the position the model drew. With `fit`: the transparent margin is cut off
    (faint pixels such as a soft shadow do not count as the motif), the motif is scaled so its
    longer side is `fill` of the canvas and centered. Motifs the model drew at different
    sizes come out equally large."""
    if not fit:
        subprocess.run([tool, str(src), "-resize", f"{size}x{size}", "-strip",
                        "-define", "png:compression-level=9", str(target)],
                       check=True, capture_output=True)
        return
    box = subprocess.run([tool, str(src), "-alpha", "extract", "-threshold", "5%", "-format", "%@", "info:"],
                         check=True, capture_output=True, text=True).stdout.strip()
    inner = max(1, round(size * fill))
    subprocess.run([tool, str(src), "-crop", box, "+repage", "-resize", f"{inner}x{inner}",
                    "-background", "none", "-gravity", "center", "-extent", f"{size}x{size}",
                    "-strip", "-define", "png:compression-level=9", str(target)],
                   check=True, capture_output=True)


def export_motifs(out, badges, style, dest, size, only=None, force=False, assigned=None, fit=True):
    """Fit the newest motif of every id of one style (or, with `assigned`, of the
    style of each badge) into the frontend size (see
    fit_motif) and write it to `dest/<id>.png`, without the timestamp. Returns
    (exported, skipped, missing) id lists; a motif is skipped when its export is
    already newer than the original, unless `force`."""
    tool = find_imagemagick()
    if not tool:
        raise RuntimeError("ImageMagick (magick or convert) is needed for --export")
    exported, skipped, missing = [], [], []
    dest = Path(dest)
    for badge in badges:
        if only and badge["id"] not in only:
            continue
        src = latest_motif(out, (assigned or {}).get(badge["id"], style), badge["id"])
        target = dest / f"{badge['id']}.png"
        if src is None:
            missing.append(badge["id"])
        elif not force and target.exists() and target.stat().st_mtime >= src.stat().st_mtime:
            skipped.append(badge["id"])
        else:
            dest.mkdir(parents=True, exist_ok=True)
            fit_motif(tool, src, target, size, fit=fit)
            exported.append(badge["id"])
    return exported, skipped, missing


def load_costs(path=COSTS_FILE):
    """{model: {quality: dollars per image of 1024 x 1024}} from tools/image_costs.toml."""
    try:
        with open(path, "rb") as f:
            return tomllib.load(f).get("costs", {})
    except FileNotFoundError:
        return {}


def load_prices(path=COSTS_FILE):
    """{model: {text_input, image_input, image_output}}, dollars per million tokens."""
    try:
        with open(path, "rb") as f:
            return tomllib.load(f).get("tokens", {})
    except FileNotFoundError:
        return {}


def usage_cost(prices, model, usage):
    """What one image cost, in dollars, from the tokens the API reported; None if the price of the
    model or the usage is not known."""
    price = prices.get(model)
    if not price or not usage:
        return None
    details = usage.get("input_tokens_details") or {}
    if details:
        text_in, image_in = details.get("text_tokens", 0), details.get("image_tokens", 0)
    else:
        text_in, image_in = usage.get("input_tokens", 0), 0
    out = usage.get("output_tokens", 0)
    return (text_in * price["text_input"] + image_in * price["image_input"] + out * price["image_output"]) / 1e6


def log_cost(path, entry):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a") as f:
        f.write(json.dumps(entry) + "\n")


def _log_averages(path, field):
    """{(model, quality, size): (average of `field`, number of images)} over the lines of the log
    that have the field; broken lines and lines without it are skipped."""
    try:
        lines = Path(path).read_text().splitlines()
    except FileNotFoundError:
        return {}
    sums = {}
    for line in lines:
        try:
            e = json.loads(line)
            key = (e["model"], e["quality"], e["size"])
            value = float(e[field])
        except (ValueError, KeyError, TypeError):
            continue
        total, n = sums.get(key, (0.0, 0))
        sums[key] = (total + value, n + 1)
    return {key: (total / n, n) for key, (total, n) in sums.items()}


def measured_costs(path=COST_LOG):
    """{(model, quality, size): (average cost, number of images)} from the cost log."""
    return _log_averages(path, "cost")


def measured_times(path=COST_LOG):
    """{(model, quality, size): (average seconds one image took, number of images)}."""
    return _log_averages(path, "seconds")


def pacing(per_minute, avg_seconds=None, delay=None, jobs=None):
    """(seconds between two request starts, requests in flight at the same time). The delay spaces
    the starts evenly a little under the rate limit; the requests in flight follow from the rate
    and how long an image takes (rate times duration, plus one), at most MAX_JOBS. `delay` and
    `jobs` override the two values."""
    if per_minute <= 0:
        raise ValueError("--per-minute has to be more than 0")
    spaced = 60.0 / per_minute * DELAY_MARGIN if delay is None else delay
    seconds = avg_seconds or ASSUMED_SECONDS
    parallel = jobs if jobs is not None else min(MAX_JOBS, max(1, math.ceil(per_minute * seconds / 60) + 1))
    return spaced, parallel


def estimate_time(images, delay, jobs, avg_seconds=None):
    """A sentence about how long `images` images take: limited by the spacing of the starts or by
    how many can be in flight, whichever is slower."""
    if images == 0:
        return None
    seconds = avg_seconds or ASSUMED_SECONDS
    total = max((images - 1) * delay + seconds, math.ceil(images / jobs) * seconds)
    basis = "measured" if avg_seconds else "assumed"
    amount = f"{total:.0f} s" if total < 90 else f"{total / 60:.1f} min"
    return f"estimated time: about {amount} (one request every {delay:.1f} s, up to {jobs} at once, {seconds:.0f} s per image {basis})"


def estimate_cost(costs, model, quality, size, images, measured=None):
    """A sentence about what `images` images will cost, or why that is not known. The average of
    the images already made with the same model, quality and size is preferred; the table `costs`
    (measured by hand, 1024x1024 only) is the fallback."""
    if images == 0:
        return None
    each, basis = None, ""
    known = (measured or {}).get((model, quality, size))
    if known:
        each, basis = known[0], f", average of {known[1]} made"
    elif size != "1024x1024":
        return f"cost unknown for size {size}, the table in tools/image_costs.toml is for 1024x1024"
    else:
        each = costs.get(model, {}).get(quality)
    if each is None:
        return (f"cost unknown for {model} at {quality}, add a measured value to tools/image_costs.toml")
    total = each * images
    amount = f"${total:.3f}" if total < 1 else f"${total:.2f}"
    return f"estimated cost: about {amount} for {images} {'image' if images == 1 else 'images'} (${each:.3f} each{basis})"


def summarize(jobs):
    counts = {"generate": 0, "update": 0, "skip": 0}
    for job in jobs:
        counts[job["action"]] += 1
    return counts


def main(argv=None):
    parser = argparse.ArgumentParser(description="Generate achievement badge motifs.")
    parser.add_argument("--plan", default=str(DEFAULT_PLAN), help="badge plan (TOML)")
    parser.add_argument("--styles-dir", default=str(DEFAULT_STYLES), help="folder with one <style>.txt per style")
    parser.add_argument("--out", default=str(DEFAULT_OUT), help="output folder (not committed)")
    parser.add_argument("--style", nargs="+",
                        help="every badge in these styles (default: each badge in the style of its mode)")
    parser.add_argument("--only", nargs="+", help="only these badge ids")
    parser.add_argument("--force", action="store_true", help="regenerate even if unchanged, or with --export export every motif again")
    parser.add_argument("--dry-run", action="store_true", help="show what would be generated, no API call")
    parser.add_argument("--check", action="store_true", help="report missing, outdated and orphan motifs, exit 1 on problems")
    parser.add_argument("--preview", action="store_true", help="write a preview page of the generated motifs")
    parser.add_argument("--export", action="store_true", help="scale the motifs of one style down for the frontend")
    parser.add_argument("--no-fit", action="store_true",
                        help="with --export: only scale the motifs, keep their margin and position")
    parser.add_argument("--export-dir", default=str(DEFAULT_EXPORT), help="folder for --export")
    parser.add_argument("--export-size", type=int, default=EXPORT_SIZE, help="edge length in px for --export")
    parser.add_argument("--yes", action="store_true", help=f"do not ask before generating more than {CONFIRM_ABOVE} motifs")
    parser.add_argument("--per-minute", type=float, default=DEFAULT_PER_MINUTE,
                        help="images per minute the account may request, by usage tier (default: %(default)s)")
    parser.add_argument("--jobs", type=int, default=None,
                        help="requests in flight at the same time (default: worked out from --per-minute)")
    parser.add_argument("--delay", type=float, default=None,
                        help="seconds between two request starts, 0 for none (default: worked out from --per-minute)")
    parser.add_argument("--model", default=MODEL)
    parser.add_argument("--quality", default=QUALITY)
    parser.add_argument("--size", default=SIZE)
    args = parser.parse_args(argv)

    modes, badges = load_plan(args.plan)
    styles = load_styles(args.styles_dir)
    if not styles:
        print(f"No styles found in {args.styles_dir}", file=sys.stderr)
        return 1
    default_style = load_default_style(args.plan)
    assigned = None if args.style else assign_styles(modes, badges, default_style)
    if assigned is not None and None in assigned.values():
        print("A mode has no style: set [defaults] style in the plan or use --style", file=sys.stderr)
        return 1
    selected_styles = args.style or list(dict.fromkeys(assigned.values()))
    for name in selected_styles:
        if name not in styles:
            print(f"Unknown style {name!r}, available: {', '.join(styles)}", file=sys.stderr)
            return 1
    if args.only:
        unknown = set(args.only) - {b["id"] for b in badges}
        if unknown:
            print(f"Unknown badge id(s): {', '.join(sorted(unknown))}", file=sys.stderr)
            return 1

    if args.check:
        problems = check(args.out, badges, styles, selected_styles, args.model, args.quality, args.size, modes, assigned)
        for problem in problems:
            print(problem)
        print(f"{len(problems)} problem(s)")
        return 1 if problems else 0

    if args.export:
        if args.style and len(args.style) != 1:
            print("--export takes one style with --style, or none for the style of each mode", file=sys.stderr)
            return 1
        try:
            exported, skipped, missing = export_motifs(args.out, badges, selected_styles[0],
                                                       args.export_dir, args.export_size, args.only, args.force,
                                                       assigned, fit=not args.no_fit)
        except RuntimeError as e:
            print(e, file=sys.stderr)
            return 1
        print(f"{len(exported)} exported, {len(skipped)} up to date, {len(missing)} not generated yet")
        for badge_id in missing:
            print(f"  missing: {(assigned or {}).get(badge_id, selected_styles[0])}/{badge_id}")
        return 1 if missing else 0

    if args.preview:
        print(write_preview(args.out, badges, selected_styles, assigned))
        return 0

    jobs = plan_jobs(modes, badges, styles, args.out, selected_styles, args.only, args.force,
                     args.model, args.quality, args.size, assigned)
    counts = summarize(jobs)
    todo = counts["generate"] + counts["update"]
    print(f"{counts['generate']} new, {counts['update']} changed, {counts['skip']} unchanged")
    cost_line = estimate_cost(load_costs(), args.model, args.quality, args.size, todo, measured_costs())
    if cost_line:
        print(cost_line)
    seconds = measured_times().get((args.model, args.quality, args.size), (None, 0))[0]
    try:
        delay, jobs_in_flight = pacing(args.per_minute, seconds, args.delay, args.jobs)
    except ValueError as e:
        print(e, file=sys.stderr)
        return 1
    time_line = estimate_time(todo, delay, jobs_in_flight, seconds)
    if time_line:
        print(time_line)
    if args.dry_run:
        for job in jobs:
            print(f"  {job['action']:8} {job['key']}")
        return 0
    if todo == 0:
        return 0

    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        print("OPENAI_API_KEY is not set.", file=sys.stderr)
        return 1
    if todo > CONFIRM_ABOVE and not args.yes:
        if input(f"Generate {todo} motifs? [y/N] ").strip().lower() != "y":
            print("Aborted.")
            return 1

    spent = []
    failed = run_jobs(jobs, args.out, api_key, args.model, args.quality, args.size, jobs_in_flight, delay,
                      prices=load_prices(), cost_log=COST_LOG, costs=spent)
    if spent:
        print(f"cost of this run: ${sum(spent):.3f} for {len(spent)} {'image' if len(spent) == 1 else 'images'}"
              f" (logged in {COST_LOG.relative_to(TOOLS_DIR.parent)})")
    if failed:
        print(f"{len(failed)} failed: {', '.join(failed)}", file=sys.stderr)
        return 1
    print("Done.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
