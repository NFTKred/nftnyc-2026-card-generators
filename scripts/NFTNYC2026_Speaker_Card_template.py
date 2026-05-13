#!/usr/bin/env python3
"""
NFTNYC2026_Speaker_Card_template — locked design, 2026-05-07.

Canonical batch renderer for the NFT.NYC 2026 speaker cards.
Design approved on 2026-05-07; do not change layout/typography without explicit sign-off.

Design lock-in:
    Canvas         : 800 x 800 PNG
    Background     : speaker photo, scaled-to-cover, heavy gaussian blur,
                     lifted toward warm white (28%) and slightly desaturated (18%)
    Watermark "26" : Monument Extended Black, 560pt, white @ ~45/255 alpha,
                     vertically nudged -40px so digits bleed off canvas edges
    Portrait       : center 440px circular crop with soft drop shadow (radius 24, alpha 70).
                     Center at (400, 360)
    Speaker name   : Space Grotesk Bold, auto-fits 58pt -> 32pt, white,
                     baseline ~y=625, max width 680px, balanced two-line wrap if needed
                     (Brand rule: Monument is uppercase-only, so mixed-case names use
                     Space Grotesk Bold instead.)
    Logo           : official NFT.NYC white PNG, 200px wide, baseline y=730

Required fonts (must be installed at these paths):
    ~/Library/Fonts/MonumentExtended-Black.otf
    ~/Library/Fonts/SpaceGrotesk-Bold.ttf
    /System/Library/Fonts/Avenir Next.ttc, Avenir.ttc

Usage:
    python3 NFTNYC2026_Speaker_Card_template.py path/to/speakers.csv [--out DIR] [--limit N]

Recognised CSV columns (case- and punctuation-insensitive; first match wins):
    photo source : Profile Picture | image_path | image | photo | file | url
    name         : ScreenName | (FirstName + LastName) | name | speaker | display_name
    speaker key  : Speaker Id | speaker_id  -- used to de-dupe (one card per speaker)
    overrides    : output_path, output_dir

Photo URLs are downloaded into ./photo-cache/ next to the CSV and reused.
Default output dir: ./rendered-cards/ next to the CSV.
"""

import argparse
import colorsys
import csv
import hashlib
import os
import re
import sys
import urllib.request
from collections import Counter
from pathlib import Path
from typing import Optional, Tuple

from PIL import Image, ImageDraw, ImageFilter, ImageFont

CANVAS = 800
PORTRAIT_CENTER = (400, 360)
PORTRAIT_DIAMETER = 440
NAME_BASELINE_Y = 625
NAME_MAX_WIDTH = 680
LOGO_BASELINE_Y = 730
LOGO_TARGET_WIDTH = 200
LOGO_PATH = "/Users/lucasjohnson/Documents/NYC Logos/NFT.NYC.logo.whitepng.png"

# Speaker Ids to permanently exclude from rendering (test rows, withdrawn speakers, etc.).
EXCLUDED_SPEAKER_IDS = {
    "23df8697-d798-4379-9c82-1a87e3f53d8a",  # Relay The Rat (test row, do not include)
}

# Per-speaker image overrides — replaces the CSV's Profile Picture URL when a file
# named <speaker_id>.<ext> exists in scripts/assets/photo-overrides/.
PHOTO_OVERRIDE_DIR = Path(__file__).parent / "assets" / "photo-overrides"


def lookup_photo_override(speaker_id: str):
    if not speaker_id or not PHOTO_OVERRIDE_DIR.exists():
        return None
    for ext in (".jpg", ".jpeg", ".png", ".webp"):
        candidate = PHOTO_OVERRIDE_DIR / f"{speaker_id}{ext}"
        if candidate.exists():
            return candidate
    return None
WATERMARK_TEXT = "26"
WATERMARK_FONT_SIZE = 560  # Monument Extended Black is a wide face; this is wide-canvas size

# macOS TTC face indexes (probed at runtime, see top of file).
# Each weight maps to (path, ttc_index).
HOME = os.path.expanduser("~")
FONT_FACES = {
    "monument-black": (f"{HOME}/Library/Fonts/MonumentExtended-Black.otf", 0),
    "monument-bold":  (f"{HOME}/Library/Fonts/MonumentExtended-Bold.otf", 0),
    "space-grotesk-bold":   (f"{HOME}/Library/Fonts/SpaceGrotesk-Bold.ttf", 0),
    "space-grotesk-medium": (f"{HOME}/Library/Fonts/SpaceGrotesk-Medium.ttf", 0),
    "space-grotesk":        (f"{HOME}/Library/Fonts/SpaceGrotesk-Regular.ttf", 0),
    "ultralight":     ("/System/Library/Fonts/Avenir Next.ttc", 10),
    "light":          ("/System/Library/Fonts/Avenir.ttc", 6),
    "regular":        ("/System/Library/Fonts/Avenir Next.ttc", 7),
    "medium":         ("/System/Library/Fonts/Avenir Next.ttc", 5),
    "bold":           ("/System/Library/Fonts/Avenir Next.ttc", 0),
}
FALLBACK_TTF = "/System/Library/Fonts/HelveticaNeue.ttc"


def load_font(size: int, weight: str = "regular") -> ImageFont.FreeTypeFont:
    path, idx = FONT_FACES.get(weight, FONT_FACES["regular"])
    if os.path.exists(path):
        try:
            return ImageFont.truetype(path, size, index=idx)
        except (OSError, ValueError):
            pass
    if os.path.exists(FALLBACK_TTF):
        try:
            return ImageFont.truetype(FALLBACK_TTF, size, index=0)
        except (OSError, ValueError):
            pass
    return ImageFont.load_default()


def slugify(name: str) -> str:
    s = re.sub(r"[^A-Za-z0-9]+", "-", name).strip("-").lower()
    return s or "speaker"


def build_blur_background(photo: Image.Image, size: int) -> Image.Image:
    """Heavily blurred + softly lifted version of the photo, used as the card background.

    Pulls all the photo's hues into a soft pastel wash (matching the Robin Arzón reference).
    """
    # cover-fit and oversize so heavy blur doesn't reveal edges
    src = photo.convert("RGB")
    w, h = src.size
    scale = max(size / w, size / h) * 1.25
    new_w, new_h = int(w * scale), int(h * scale)
    base = src.resize((new_w, new_h), Image.LANCZOS)

    left = (new_w - size) // 2
    top = (new_h - size) // 2
    base = base.crop((left, top, left + size, top + size))

    # heavy blur to abstract into color regions
    blurred = base.filter(ImageFilter.GaussianBlur(radius=size // 6))

    # lift toward pastel: blend with a near-white wash, then slight desaturation
    wash = Image.new("RGB", (size, size), (245, 240, 245))
    lifted = Image.blend(blurred, wash, 0.28)

    # mild desaturate so colors feel ambient, not loud
    grey = lifted.convert("L").convert("RGB")
    lifted = Image.blend(lifted, grey, 0.18)

    # soft second blur pass for that creamy look
    lifted = lifted.filter(ImageFilter.GaussianBlur(radius=size // 28))
    return lifted


def draw_watermark(canvas: Image.Image, alpha: int = 45):
    """'26' watermark in Monument Extended Black, white at low opacity, edges bleed off canvas."""
    layer = Image.new("RGBA", canvas.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(layer)
    font = load_font(WATERMARK_FONT_SIZE, weight="monument-black")
    bbox = draw.textbbox((0, 0), WATERMARK_TEXT, font=font)
    tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
    x = (canvas.width - tw) // 2 - bbox[0]
    y = (canvas.height - th) // 2 - bbox[1] - 40
    draw.text((x, y), WATERMARK_TEXT, font=font, fill=(255, 255, 255, alpha))
    canvas.alpha_composite(layer)


def circular_portrait(photo: Image.Image, diameter: int) -> Image.Image:
    w, h = photo.size
    side = min(w, h)
    left = (w - side) // 2
    top = max(0, (h - side) // 3)
    if top + side > h:
        top = h - side
    cropped = photo.crop((left, top, left + side, top + side)).resize(
        (diameter, diameter), Image.LANCZOS
    )

    mask = Image.new("L", (diameter * 4, diameter * 4), 0)
    ImageDraw.Draw(mask).ellipse((0, 0, diameter * 4, diameter * 4), fill=255)
    mask = mask.resize((diameter, diameter), Image.LANCZOS)

    out = Image.new("RGBA", (diameter, diameter), (0, 0, 0, 0))
    out.paste(cropped.convert("RGBA"), (0, 0), mask)
    return out


def draw_portrait_shadow(canvas: Image.Image, center, diameter):
    """Soft drop shadow under the portrait for separation from the background."""
    pad = 60
    shadow = Image.new("RGBA", (diameter + pad * 2, diameter + pad * 2), (0, 0, 0, 0))
    d = ImageDraw.Draw(shadow)
    d.ellipse((pad, pad, pad + diameter, pad + diameter), fill=(0, 0, 0, 70))
    shadow = shadow.filter(ImageFilter.GaussianBlur(radius=24))
    sx = center[0] - shadow.width // 2
    sy = center[1] - shadow.height // 2 + 8  # nudge down slightly
    canvas.alpha_composite(shadow, (sx, sy))


def fit_name_text(draw, name, max_width, base_size=58) -> Tuple[ImageFont.FreeTypeFont, list]:
    """Sized for Space Grotesk Bold (narrower than Monument)."""
    size = base_size
    while size >= 32:
        font = load_font(size, weight="space-grotesk-bold")
        words = name.split()
        if len(words) <= 1:
            tw = draw.textbbox((0, 0), name, font=font)[2]
            if tw <= max_width:
                return font, [name]
            size -= 2
            continue

        if draw.textbbox((0, 0), name, font=font)[2] <= max_width:
            return font, [name]

        best = None
        for i in range(1, len(words)):
            line1 = " ".join(words[:i])
            line2 = " ".join(words[i:])
            w1 = draw.textbbox((0, 0), line1, font=font)[2]
            w2 = draw.textbbox((0, 0), line2, font=font)[2]
            if w1 <= max_width and w2 <= max_width:
                score = abs(w1 - w2)
                if best is None or score < best[0]:
                    best = (score, [line1, line2])
        if best:
            return font, best[1]
        size -= 2

    return load_font(32, weight="space-grotesk-bold"), [name]


def draw_name(canvas: Image.Image, name: str):
    layer = Image.new("RGBA", canvas.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(layer)
    font, lines = fit_name_text(draw, name, NAME_MAX_WIDTH)
    line_h = font.size + 6
    total_h = line_h * len(lines)
    y = NAME_BASELINE_Y - total_h // 2
    for line in lines:
        bbox = draw.textbbox((0, 0), line, font=font)
        tw = bbox[2] - bbox[0]
        x = (canvas.width - tw) // 2 - bbox[0]
        draw.text((x, y), line, font=font, fill=(255, 255, 255, 255))
        y += line_h
    canvas.alpha_composite(layer)


_LOGO_CACHE = {}


def _load_logo(target_width: int) -> Image.Image:
    key = (LOGO_PATH, target_width)
    if key in _LOGO_CACHE:
        return _LOGO_CACHE[key]
    src = Image.open(LOGO_PATH).convert("RGBA")
    ratio = src.height / src.width
    sized = src.resize((target_width, max(1, int(target_width * ratio))), Image.LANCZOS)
    _LOGO_CACHE[key] = sized
    return sized


def draw_nft_nyc_logo(canvas: Image.Image, baseline_y: int, target_width: int):
    """Composite the official NFT.NYC white logo, centered horizontally."""
    logo = _load_logo(target_width)
    paste_x = (canvas.width - logo.width) // 2
    paste_y = baseline_y - logo.height // 2
    canvas.alpha_composite(logo, (paste_x, paste_y))


def render_card(photo_path: Path, name: str, out_path: Path) -> None:
    photo = Image.open(photo_path).convert("RGB")

    canvas = Image.new("RGBA", (CANVAS, CANVAS), (255, 255, 255, 255))
    bg = build_blur_background(photo, CANVAS).convert("RGBA")
    canvas.alpha_composite(bg)

    draw_watermark(canvas, alpha=70)

    draw_portrait_shadow(canvas, PORTRAIT_CENTER, PORTRAIT_DIAMETER)
    portrait = circular_portrait(photo, PORTRAIT_DIAMETER)
    px = PORTRAIT_CENTER[0] - PORTRAIT_DIAMETER // 2
    py = PORTRAIT_CENTER[1] - PORTRAIT_DIAMETER // 2
    canvas.alpha_composite(portrait, (px, py))

    if name:
        draw_name(canvas, name)
    draw_nft_nyc_logo(canvas, LOGO_BASELINE_Y, LOGO_TARGET_WIDTH)

    out_path.parent.mkdir(parents=True, exist_ok=True)
    canvas.convert("RGB").save(out_path, "PNG", optimize=True)


def normalize_header(h: str) -> str:
    return re.sub(r"[^a-z0-9]", "", h.lower())


def pick_column(row: dict, *aliases: str) -> Optional[str]:
    norm = {normalize_header(k): v for k, v in row.items() if k}
    for alias in aliases:
        v = norm.get(normalize_header(alias))
        if v is not None and str(v).strip():
            return str(v).strip()
    return None


def is_url(s: str) -> bool:
    return s.startswith("http://") or s.startswith("https://")


def fetch_to_cache(url: str, cache_dir: Path) -> Path:
    cache_dir.mkdir(parents=True, exist_ok=True)
    digest = hashlib.sha1(url.encode("utf-8")).hexdigest()[:16]
    ext_match = re.search(r"\.(jpe?g|png|webp|gif)(\?|$)", url, re.IGNORECASE)
    ext = ("." + ext_match.group(1).lower()) if ext_match else ".img"
    target = cache_dir / f"{digest}{ext}"
    if target.exists() and target.stat().st_size > 0:
        return target
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 NFTNYC-card-renderer"})
    with urllib.request.urlopen(req, timeout=30) as r, open(target, "wb") as f:
        f.write(r.read())
    return target


NAME_OVERRIDES = {
    "8c30c323-743a-47d1-bfa3-9c40b83ae209": "YuZapata",  # CSV Pseudonym="He" is a typo
}


def _clean_name_part(s):
    if not s:
        return ""
    s = s.strip()
    if s.lower() in ("n/a", "na", "-", "none"):
        return ""
    return s


def resolve_name(row: dict) -> str:
    """NFT.NYC display-name rule: Pseudonym > FirstName + LastName.

    Brand rule: every card uses a pseudonym. CSV `Pseudonym` wins; if blank,
    fall back to FirstName + LastName (columns AP and AQ). 'N/A' values in
    either name part are treated as empty.
    """
    spid = pick_column(row, "Speaker Id", "speaker_id")
    if spid and spid in NAME_OVERRIDES:
        return NAME_OVERRIDES[spid]
    pseudo = pick_column(row, "Pseudonym")
    if pseudo:
        return pseudo
    first = _clean_name_part(pick_column(row, "FirstName", "first_name"))
    last = _clean_name_part(pick_column(row, "LastName", "last_name"))
    combined = (first + " " + last).strip()
    if combined:
        return combined
    return pick_column(row, "name", "speaker", "display_name", "speaker_name") or ""


def main():
    ap = argparse.ArgumentParser(description="Render NFT.NYC 2026 speaker cards.")
    ap.add_argument("csv", help="CSV file with speaker rows")
    ap.add_argument("--out", help="Override output directory")
    ap.add_argument("--cache", help="Override photo cache directory")
    ap.add_argument("--limit", type=int, help="Process only the first N unique speakers")
    args = ap.parse_args()

    csv_path = Path(args.csv).resolve()
    if not csv_path.exists():
        print(f"CSV not found: {csv_path}", file=sys.stderr)
        sys.exit(1)
    csv_dir = csv_path.parent
    default_out = Path(args.out).resolve() if args.out else (csv_dir / "rendered-cards")
    cache_dir = Path(args.cache).resolve() if args.cache else (csv_dir / "photo-cache")

    with open(csv_path, newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        rows = list(reader)

    if not rows:
        print("CSV has no rows.", file=sys.stderr)
        sys.exit(1)

    seen_keys = set()
    successes, failures, skipped_dup, skipped_excluded = 0, 0, 0, 0

    for i, row in enumerate(rows, 1):
        image = pick_column(
            row, "Profile Picture", "image_path", "image", "photo", "file", "filename", "url"
        )
        name = resolve_name(row)
        speaker_key = pick_column(row, "Speaker Id", "speaker_id") or (image or name)

        if not image:
            continue
        if speaker_key in EXCLUDED_SPEAKER_IDS:
            skipped_excluded += 1
            continue
        if speaker_key in seen_keys:
            skipped_dup += 1
            continue
        seen_keys.add(speaker_key)

        if args.limit and len(seen_keys) > args.limit:
            break

        try:
            override = lookup_photo_override(speaker_key)
            if override:
                photo_path = override
            elif is_url(image):
                photo_path = fetch_to_cache(image, cache_dir)
            else:
                photo_path = Path(image)
                if not photo_path.is_absolute():
                    photo_path = (csv_dir / photo_path).resolve()
                if not photo_path.exists():
                    raise FileNotFoundError(f"photo not found: {photo_path}")
        except Exception as e:
            print(f"[{i}] FAIL fetch {name or speaker_key}: {e}", file=sys.stderr)
            failures += 1
            continue

        explicit_out = pick_column(row, "output_path")
        row_out_dir = pick_column(row, "output_dir")
        if explicit_out:
            out_path = Path(explicit_out)
            if not out_path.is_absolute():
                out_path = (csv_dir / out_path).resolve()
        else:
            out_dir = Path(row_out_dir).resolve() if row_out_dir else default_out
            stem = slugify(name) if name else (photo_path.stem or "speaker")
            out_path = out_dir / f"{stem}.png"

        try:
            render_card(photo_path, name, out_path)
            print(f"[{i}] {name or '(no name)'} -> {out_path}")
            successes += 1
        except Exception as e:
            print(f"[{i}] FAIL render {name or speaker_key}: {e}", file=sys.stderr)
            failures += 1

    print(f"Done. {successes} rendered, {failures} failed, {skipped_dup} duplicate rows skipped, {skipped_excluded} excluded.")
    sys.exit(0 if failures == 0 else 2)


if __name__ == "__main__":
    main()
