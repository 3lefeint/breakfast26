"""Generate the Stream Deck key icons with an image API: one transparent PNG per action, all from the same style text (glyph parts with a green to teal gradient, real objects such as the board and the dart rendered realistically).

    python tools/generate_streamdeck_icons_api.py --dry-run            # print the prompts, no request
    python tools/generate_streamdeck_icons_api.py --only undo --variants 3
    python tools/generate_streamdeck_icons_api.py                      # every icon, one variant each

The variants are written to `data/streamdeck-icons-generated/<name>_v<N>.png` (never over an older one). The ones that are kept go
into a folder (`selection`) and are put into the package with `--install`, which centers each icon, scales it to 256 pixels and
writes `breakfast/streamdeck_icons/icon_<name>.png`:

    python tools/generate_streamdeck_icons_api.py --install data/streamdeck-icons-generated/selection
 Needs no package; the key comes from `--key-file` or the environment
variable `OPENAI_API_KEY` and is never printed.
"""

import argparse
import base64
import json
import os
import re
import sys
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "data" / "streamdeck-icons-generated"
MODEL = "gpt-image-2.5-sunburst"
SIZE = "1024x1024"
URL = "https://api.openai.com/v1/images/generations"

STYLE = (
    "A single icon for a small control key, modern app style, made of two kinds of parts that look like one set. GLYPH parts "
    "(arrows, check marks, flags, notes, sound waves, any abstract symbol) are solid, simplified shapes with thick rounded forms and "
    "soft rounded corners, not outlines and not thin line drawings. REALISTIC parts (only where the motif says realistic) are "
    "detailed, softly lit, semi-realistic renderings of a real object, with natural materials and gentle shading, but in a restrained "
    "palette: dark charcoal and cream with green accents, never red, so they sit well next to the green glyph. Realistic parts have "
    "no glow. Color of the glyph parts: a smooth gradient inside the shape "
    "from fresh green #8bc34a through mint to teal #22d3ee, the same gradient direction (top left to bottom right) in every icon. "
    "A thin light inner edge on the upper left of a glyph and a very faint soft green glow close around the glyph, no other "
    "effects. Glyphs are flat with only slight depth from the gradient: no hard shadow, no border, no frame, no container shape. "
    "Parts that must stay readable are separated by small gaps instead of lines. No text, no "
    "letters, no numbers. Transparent background, nothing behind the icon. The icon is centered with a margin of at least 15 percent "
    "on every side and fills about 70 percent of the canvas. Square canvas. The same drawing style, shape language, gradient and "
    "level of detail in every icon of the set; simple enough to read at 72 pixels."
)

MOTIFS = {
    "reset_board": "A broom sweeping: handle at the upper right, wide bristle head at the lower left.",
    "start_board": "A solid circle with a play triangle cut out of it.",
    "undo": "A curved arrow turning back counter-clockwise.",
    "next_player": "Head and shoulders of a person with a small arrow pointing right next to it.",
    "next_game": "A realistic dartboard seen from the front (black and cream segments, wire rings, bullseye, with the green accent instead of red) on the left, and a bold glyph arrow pointing right next to it.",
    "cancel_game": "A bold X with rounded ends.",
    "fun_mode": "A party hat (cone) with a pompom and two stripes.",
    "detect_bouncer": "A realistic dartboard edge-on as a vertical slab on the left; a realistic dart flies at it from the upper right and a bold "
                      "glyph curved arrow falls away from the hit point down to the right.",
    "detect_mark": "A flag on a pole.",
    "random_sound": "A solid loudspeaker with two sound waves and a small die (three pips) at the upper right.",
    "sound": "An eighth note.",
    "confirm_dart": "A realistic steel-tip dart pointing down and to the left (metal barrel, shaft, flights) with a bold glyph check mark next to it.",
    "correct_dart": "A realistic dartboard seen from the front (black and cream segments, wire rings, bullseye, with the green accent instead of red) with a glyph pencil pointing at its edge from the upper right.",
    "folder": "A solid folder with a tab.",
    "back": "An arrow that goes up and turns left (one level up).",
    "page_next": "A chevron pointing right.",
    "page_prev": "A chevron pointing left.",
}


def prompt(name: str) -> str:
    return f"{STYLE}\n\nMotif: {MOTIFS[name]}"


def next_number(name: str) -> int:
    found = [int(m.group(1)) for p in OUT.glob(f"{name}_v*.png") if (m := re.fullmatch(rf"{re.escape(name)}_v(\d+)\.png", p.name))]
    return max(found, default=0) + 1


ICONS = ROOT / "breakfast" / "streamdeck_icons"
ICON_SIZE = 256


def install(folder: Path) -> int:
    """Put the chosen files (`<name>_v<N>.png`) into the package: centered on what is drawn, 256 pixels, as `icon_<name>.png`."""
    from PIL import Image

    ICONS.mkdir(parents=True, exist_ok=True)
    count = 0
    for path in sorted(folder.glob("*.png")):
        found = re.fullmatch(r"(\w+?)_v\d+\.png", path.name)
        if not found or found.group(1) not in MOTIFS:
            print(f"skipped {path.name}", file=sys.stderr)
            continue
        with Image.open(path) as opened:
            image = opened.convert("RGBA")
        box = image.getchannel("A").point(lambda v: 255 if v > 60 else 0).getbbox()
        if box:
            dx, dy = image.width // 2 - (box[0] + box[2]) // 2, image.height // 2 - (box[1] + box[3]) // 2
            shifted = Image.new("RGBA", image.size, (0, 0, 0, 0))
            shifted.paste(image, (dx, dy))
            image = shifted
        image.resize((ICON_SIZE, ICON_SIZE), Image.LANCZOS).save(ICONS / f"icon_{found.group(1)}.png", optimize=True)
        count += 1
    print(f"{count} icons installed in {ICONS.relative_to(ROOT)}")
    return 0


def read_key(key_file: str | None) -> str:
    if key_file:
        return Path(key_file).expanduser().read_text().strip()
    return os.environ.get("OPENAI_API_KEY", "")


def request(key: str, model: str, name: str, count: int) -> list:
    """The base64 images the API returns for one icon."""
    body = {"model": model, "prompt": prompt(name), "size": SIZE, "quality": "high", "background": "transparent",
            "output_format": "png", "n": count}
    req = urllib.request.Request(URL, json.dumps(body).encode(), {"Authorization": f"Bearer {key}", "Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=300) as response:
        return [item["b64_json"] for item in json.load(response)["data"]]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--only", nargs="+", choices=sorted(MOTIFS), help="only these icons (default: all)")
    parser.add_argument("--variants", type=int, default=1, help="variants per icon (default 1)")
    parser.add_argument("--model", default=MODEL)
    parser.add_argument("--key-file", help="file with the API key (default: the environment variable OPENAI_API_KEY)")
    parser.add_argument("--install", type=Path, metavar="DIR", help="put the chosen files of DIR into the package and stop")
    parser.add_argument("--dry-run", action="store_true", help="print the prompts and send nothing")
    args = parser.parse_args()
    if args.install:
        return install(args.install)
    names = args.only or list(MOTIFS)
    if args.dry_run:
        for name in names:
            print(f"--- {name} ({args.variants} variant(s), {args.model}, {SIZE}, transparent)\n{prompt(name)}\n")
        return 0
    key = read_key(args.key_file)
    if not key:
        print("no API key: pass --key-file or set OPENAI_API_KEY", file=sys.stderr)
        return 1
    OUT.mkdir(parents=True, exist_ok=True)
    for name in names:
        try:
            images = request(key, args.model, name, args.variants)
        except urllib.error.HTTPError as exc:
            print(f"{name}: the image API answered {exc.code}: {exc.read().decode(errors='replace')[:500].replace(key, '***')}", file=sys.stderr)
            return 1
        except (urllib.error.URLError, OSError, KeyError, ValueError) as exc:
            print(f"{name}: the image API failed: {str(exc).replace(key, '***')}", file=sys.stderr)
            return 1
        first = next_number(name)
        for number, data in enumerate(images, start=first):
            path = OUT / f"{name}_v{number}.png"
            path.write_bytes(base64.b64decode(data))
            print(f"wrote {path.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
