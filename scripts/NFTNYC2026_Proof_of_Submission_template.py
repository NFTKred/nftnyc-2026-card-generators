#!/usr/bin/env python3
"""
NFTNYC2026_Proof_of_Submission_template — locked design, 2026-05-07.

Canonical batch renderer for the NFT.NYC 2026 "Proof of Submission" speaker cards.
Design approved on 2026-05-07; do not change layout/typography/foil palette without
explicit sign-off.

Design lock-in:
    Canvas         : 1080 x 1080 PNG, black background
    Left strip     : 100px wide, full height, blue/purple metallic-foil gradient
                     (alternating periwinkle / lavender / indigo / pale lilac stops with
                     diagonal shine bands and fine grain to read as reflective foil)
                     "PROOF OF SUBMISSION 2026" text rotated -90 deg, dark navy ink,
                     Monument Extended Black 30pt with 2px tracking
                     Starburst icon (12-point, dark navy) near bottom of strip
    Photo area     : 980 wide x 880 tall, starts at x=100, y=0
                     Speaker photo center-cropped to fill rectangle (no blur, full opacity)
    Bottom bar     : 980 wide x 200 tall, starts at (x=100, y=880), solid black
                     (does NOT extend across the foil sidebar)
                     "SPEAKER" label : Monument Extended Black 22pt, 2px tracking, white
                     Speaker name    : Space Grotesk Bold, auto-fits 68pt single-line ->
                                       52pt two-line wrap -> 34pt fallback, white
                                       (Brand rule: Monument is uppercase-only, so mixed-case
                                       names use Space Grotesk Bold instead.)
                     NFT.NYC official white logo (180px wide) at right edge
    Logo PNG       : /Users/lucasjohnson/Documents/NYC Logos/NFT.NYC.logo.whitepng.png

Required fonts:
    ~/Library/Fonts/MonumentExtended-Black.otf
    ~/Library/Fonts/SpaceGrotesk-Bold.ttf

Usage:
    python3 NFTNYC2026_Proof_of_Submission_template.py path/to/speakers.csv [--out DIR] [--limit N]

CSV column resolution and URL caching are identical to the speaker-card template.
"""

import argparse
import csv
import hashlib
import math
import os
import random
import re
import sys
import urllib.request
from pathlib import Path
from typing import Optional, Tuple

from PIL import Image, ImageChops, ImageDraw, ImageFilter, ImageFont, ImageOps

CANVAS_W = 1080
CANVAS_H = 1080
SIDEBAR_W = 100
BOTTOM_BAR_H = 200
PHOTO_X = SIDEBAR_W
PHOTO_Y = 0
PHOTO_W = CANVAS_W - SIDEBAR_W
PHOTO_H = CANVAS_H - BOTTOM_BAR_H

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
LOGO_TARGET_WIDTH = 180

# Blue/purple metallic-foil palette. Alternating bright highlights and dark
# reflections build the reflective curved-surface look; hues shift between
# violet, indigo, periwinkle, and pale lilac. Top -> bottom.
SIDEBAR_STOPS = [
    (0.00, (215, 220, 245)),  # pale periwinkle highlight
    (0.08, (140, 148, 200)),  # mid lavender-blue
    (0.18, (52,  46,  104)),  # deep indigo
    (0.28, (130, 116, 180)),  # warm violet
    (0.40, (228, 222, 248)),  # near-white lilac highlight
    (0.50, (170, 158, 210)),  # soft purple
    (0.60, (40,  44,  100)),  # deep navy-purple
    (0.72, (148, 152, 204)),  # periwinkle
    (0.84, (220, 218, 245)),  # pale lavender highlight
    (0.92, (90,  86,  152)),  # darker violet
    (1.00, (180, 180, 220)),  # lavender silver
]

HOME = os.path.expanduser("~")
FONT_FACES = {
    "monument-black": (f"{HOME}/Library/Fonts/MonumentExtended-Black.otf", 0),
    "monument-bold":  (f"{HOME}/Library/Fonts/MonumentExtended-Bold.otf", 0),
    "space-grotesk-bold":   (f"{HOME}/Library/Fonts/SpaceGrotesk-Bold.ttf", 0),
    "space-grotesk-medium": (f"{HOME}/Library/Fonts/SpaceGrotesk-Medium.ttf", 0),
    "space-grotesk":        (f"{HOME}/Library/Fonts/SpaceGrotesk-Regular.ttf", 0),
    "ultralight":     ("/System/Library/Fonts/Avenir Next.ttc", 10),
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
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 NFTNYC-pos-renderer"})
    with urllib.request.urlopen(req, timeout=30) as r, open(target, "wb") as f:
        f.write(r.read())
    return target


def normalize_header(h: str) -> str:
    return re.sub(r"[^a-z0-9]", "", h.lower())


def pick_column(row: dict, *aliases: str) -> Optional[str]:
    norm = {normalize_header(k): v for k, v in row.items() if k}
    for alias in aliases:
        v = norm.get(normalize_header(alias))
        if v is not None and str(v).strip():
            return str(v).strip()
    return None


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


def flatten_alpha_to_white(img: Image.Image, background=(255, 255, 255)) -> Image.Image:
    """Composite alpha onto white before converting to RGB so subject cutouts
    (transparent PNGs) don't end up with their transparent areas turned to black."""
    if img.mode == "RGBA":
        bg = Image.new("RGB", img.size, background)
        bg.paste(img, mask=img.split()[-1])
        return bg
    if img.mode == "LA":
        return Image.merge("RGB", (img.convert("L"),) * 3)
    if img.mode == "P" and "transparency" in img.info:
        return flatten_alpha_to_white(img.convert("RGBA"), background)
    return img.convert("RGB")


def trim_uniform_borders(img: Image.Image,
                         variance_max: int = 14,
                         light_thresh: int = 240,
                         dark_thresh: int = 18,
                         margin: int = 6) -> Image.Image:
    """Crop away true letterbox bars / hard padding. Requires both narrow
    brightness variance AND extreme value, so bright studio backgrounds (which
    are content) don't get trimmed."""
    g = img.convert("L")
    w, h = g.size
    px = g.load()

    def _row_is_padding(y):
        mn, mx = 255, 0
        for x in range(w):
            v = px[x, y]
            if v < mn: mn = v
            if v > mx: mx = v
            if mx - mn > variance_max:
                return False
        return mx <= dark_thresh  # only trim dark letterbox bars; keep light backdrops

    def _col_is_padding(x):
        mn, mx = 255, 0
        for y in range(h):
            v = px[x, y]
            if v < mn: mn = v
            if v > mx: mx = v
            if mx - mn > variance_max:
                return False
        return mx <= dark_thresh  # only trim dark letterbox bars; keep light backdrops

    def _row_active(y):
        return not _row_is_padding(y)

    def _col_active(x):
        return not _col_is_padding(x)

    top = 0
    while top < h and not _row_active(top): top += 1
    bot = h - 1
    while bot > top and not _row_active(bot): bot -= 1
    left = 0
    while left < w and not _col_active(left): left += 1
    right = w - 1
    while right > left and not _col_active(right): right -= 1
    if top >= bot or left >= right:
        return img
    top = max(0, top - margin)
    bot = min(h - 1, bot + margin)
    left = max(0, left - margin)
    right = min(w - 1, right + margin)
    new_w = right - left + 1
    new_h = bot - top + 1
    if new_w * new_h > w * h * 0.93: return img
    if new_w < w * 0.5 or new_h < h * 0.5: return img
    return img.crop((left, top, right + 1, bot + 1))


def detect_empty_top_rows(photo: Image.Image, sensitivity: int = 10,
                          max_inspect_frac: float = 0.25) -> int:
    """Number of empty/low-variance rows at the top of the source (head detection)."""
    g = photo.convert("L")
    w, h = g.size
    px = g.load()
    max_check = max(1, int(h * max_inspect_frac))
    for y in range(max_check):
        mn, mx = 255, 0
        for x in range(w):
            v = px[x, y]
            if v < mn: mn = v
            if v > mx: mx = v
            if mx - mn > sensitivity:
                return y
    return max_check


def cover_crop(photo: Image.Image, w: int, h: int) -> Image.Image:
    src_w, src_h = photo.size
    scale = max(w / src_w, h / src_h)
    new_w, new_h = int(src_w * scale + 0.5), int(src_h * scale + 0.5)
    scaled = photo.resize((new_w, new_h), Image.LANCZOS)

    left = (new_w - w) // 2
    excess_h = new_h - h
    if excess_h <= 0:
        top = 0
    else:
        empty_src = detect_empty_top_rows(photo)
        empty_scaled = int(empty_src * scale)
        headroom_px = int(h * 0.04)
        max_safe_top = max(0, empty_scaled - headroom_px)
        top = min(max_safe_top, excess_h)
    if top + h > new_h:
        top = new_h - h
    return scaled.crop((left, top, left + w, top + h))


def interp_rgb(c1, c2, t):
    return tuple(int(c1[i] + (c2[i] - c1[i]) * t) for i in range(3))


def _vertical_gradient(width: int, height: int, stops) -> Image.Image:
    grad = Image.new("RGB", (width, height), (0, 0, 0))
    px = grad.load()
    for y in range(height):
        t = y / max(height - 1, 1)
        for i in range(len(stops) - 1):
            t0, c0 = stops[i]
            t1, c1 = stops[i + 1]
            if t0 <= t <= t1:
                local = (t - t0) / max(t1 - t0, 1e-6)
                color = interp_rgb(c0, c1, local)
                break
        else:
            color = stops[-1][1]
        for x in range(width):
            px[x, y] = color
    return grad


def _diagonal_shine(width: int, height: int) -> Image.Image:
    """Soft diagonal highlight bands that mimic foil reflection."""
    over_w = int(math.hypot(width, height)) + 32
    over_h = over_w
    shine = Image.new("L", (over_w, over_h), 0)
    sd = ImageDraw.Draw(shine)
    band_specs = [
        (0.18, 90, 200),
        (0.42, 60, 110),
        (0.62, 80, 160),
        (0.82, 50, 90),
    ]
    for pos, thickness, intensity in band_specs:
        cy = int(over_h * pos)
        sd.rectangle((0, cy - thickness // 2, over_w, cy + thickness // 2), fill=intensity)
    shine = shine.filter(ImageFilter.GaussianBlur(radius=24))
    rotated = shine.rotate(-22, resample=Image.BICUBIC, expand=False)
    left = (rotated.width - width) // 2
    top = (rotated.height - height) // 2
    return rotated.crop((left, top, left + width, top + height))


def _grain(width: int, height: int, strength: int = 8) -> Image.Image:
    rng = random.Random(0xF011)
    noise = Image.new("L", (width, height), 0)
    px = noise.load()
    for y in range(height):
        for x in range(width):
            px[x, y] = rng.randint(-strength, strength) + 128
    return noise


def build_sidebar(width: int, height: int) -> Image.Image:
    base = _vertical_gradient(width, height, SIDEBAR_STOPS)

    # 1) Add a horizontal sheen so the strip looks rounded/reflective
    sheen = Image.new("L", (width, height), 0)
    sd = ImageDraw.Draw(sheen)
    cx = width // 2
    for x in range(width):
        # bell curve: brightest in the middle, dimmer at edges
        t = abs(x - cx) / max(cx, 1)
        sd.rectangle((x, 0, x + 1, height), fill=int(60 * (1 - t * t)))
    sheen_layer = Image.merge("RGB", (sheen, sheen, sheen))
    lit = ImageChops.add(base, sheen_layer)

    # 2) Diagonal foil bands (soft white highlights)
    shine = _diagonal_shine(width, height)
    shine_rgb = Image.merge("RGB", (shine, shine, shine))
    lit = ImageChops.screen(lit, shine_rgb)

    # 3) Subtle grain for the metallic micro-texture
    grain = _grain(width, height, strength=6)
    grain_rgb = Image.merge("RGB", (grain, grain, grain))
    lit = ImageChops.overlay(lit, grain_rgb)

    return lit


def draw_sidebar_text(canvas: Image.Image):
    """Draw 'PROOF OF SUBMISSION' rotated -90deg on the sidebar (reads bottom-up)."""
    text = "PROOF OF SUBMISSION 2026"
    font_size = 30
    tracking = 2  # Monument Extended is already wide; minimal extra tracking

    font = load_font(font_size, weight="monument-black")
    # Render each letter individually so we can apply tracking
    glyph_widths = []
    glyph_heights = []
    for ch in text:
        bbox = font.getbbox(ch)
        glyph_widths.append(bbox[2] - bbox[0])
        glyph_heights.append(bbox[3] - bbox[1])
    total_w = sum(glyph_widths) + tracking * (len(text) - 1)
    line_h = max(glyph_heights) + 8

    horiz = Image.new("RGBA", (total_w + 4, line_h + 4), (0, 0, 0, 0))
    hd = ImageDraw.Draw(horiz)
    cx = 2
    # Dark ink for legibility on the pastel metallic foil
    ink = (24, 22, 36, 255)
    for i, ch in enumerate(text):
        hd.text((cx, 2), ch, font=font, fill=ink)
        cx += glyph_widths[i] + tracking

    # Rotate 90 deg counter-clockwise so text reads upward
    rotated = horiz.rotate(90, expand=True, resample=Image.BICUBIC)

    # Position centered vertically on the sidebar
    sx = (SIDEBAR_W - rotated.width) // 2
    sy = (CANVAS_H - rotated.height) // 2
    canvas.alpha_composite(rotated, (sx, sy))


def draw_starburst(canvas: Image.Image, center, outer_r: int, inner_r: int, points: int = 12,
                   color=(24, 22, 36, 255)):
    """A starburst spark icon — alternating long/short rays."""
    layer = Image.new("RGBA", canvas.size, (0, 0, 0, 0))
    d = ImageDraw.Draw(layer)
    pts = []
    cx, cy = center
    for i in range(points * 2):
        r = outer_r if i % 2 == 0 else inner_r
        angle = (math.pi / points) * i - math.pi / 2
        pts.append((cx + r * math.cos(angle), cy + r * math.sin(angle)))
    d.polygon(pts, fill=color)
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


def fit_name(draw, name, max_width, base_size=68):
    """Fit speaker name in the bottom bar without overlapping the logo.

    Sized for Space Grotesk Bold (narrower than Monument), so a 1-line max of 68pt
    still reads bold; falls back to 2 balanced lines at <=52pt before final fallback.
    Returns (font, lines).
    """
    # Pass 1 — single line.
    for size in range(base_size, 50, -2):
        font = load_font(size, weight="space-grotesk-bold")
        if draw.textbbox((0, 0), name, font=font)[2] <= max_width:
            return font, [name]

    # Pass 2 — two-line balanced wrap (>=2 words).
    words = name.split()
    if len(words) >= 2:
        for size in range(52, 32, -2):
            font = load_font(size, weight="space-grotesk-bold")
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

    # Pass 3 — fallback: smallest single line.
    return load_font(34, weight="space-grotesk-bold"), [name]


def draw_bottom_bar(canvas: Image.Image, name: str):
    bar_top = CANVAS_H - BOTTOM_BAR_H
    layer = Image.new("RGBA", canvas.size, (0, 0, 0, 0))
    d = ImageDraw.Draw(layer)
    # Bottom bar only covers the main photo area, leaving the sidebar gradient untouched.
    d.rectangle((SIDEBAR_W, bar_top, CANVAS_W, CANVAS_H), fill=(0, 0, 0, 255))
    canvas.alpha_composite(layer)

    text_layer = Image.new("RGBA", canvas.size, (0, 0, 0, 0))
    td = ImageDraw.Draw(text_layer)

    # Logo at right
    logo = _load_logo(LOGO_TARGET_WIDTH)
    logo_x = CANVAS_W - logo.width - 60
    logo_y = bar_top + (BOTTOM_BAR_H - logo.height) // 2
    canvas.alpha_composite(logo, (logo_x, logo_y))

    # SPEAKER label (Monument Extended Black)
    label_font = load_font(22, weight="monument-black")
    label_text = "SPEAKER"
    tracking = 2
    label_x = SIDEBAR_W + 60
    label_y = bar_top + 50
    cur_x = label_x
    for ch in label_text:
        td.text((cur_x, label_y), ch, font=label_font, fill=(255, 255, 255, 255))
        cur_x += label_font.getbbox(ch)[2] - label_font.getbbox(ch)[0] + tracking

    # Speaker name (Monument Extended Bold) — wraps to 2 balanced lines if too wide.
    max_name_w = logo_x - label_x - 30
    name_font, name_lines = fit_name(td, name, max_name_w, base_size=68)
    line_h = name_font.size + 6
    block_h = line_h * len(name_lines)
    # Anchor block so it sits neatly under the SPEAKER label and inside the bottom bar.
    name_y = bar_top + (BOTTOM_BAR_H - block_h) // 2 + 18
    for line in name_lines:
        td.text((label_x, name_y), line, font=name_font, fill=(255, 255, 255, 255))
        name_y += line_h

    canvas.alpha_composite(text_layer)


def render_card(photo_path: Path, name: str, out_path: Path) -> None:
    photo = Image.open(photo_path)
    photo = ImageOps.exif_transpose(photo)
    photo = flatten_alpha_to_white(photo)
    photo = trim_uniform_borders(photo)

    canvas = Image.new("RGBA", (CANVAS_W, CANVAS_H), (0, 0, 0, 255))

    # Photo
    cropped = cover_crop(photo, PHOTO_W, PHOTO_H).convert("RGBA")
    canvas.alpha_composite(cropped, (PHOTO_X, PHOTO_Y))

    # Sidebar gradient
    sidebar = build_sidebar(SIDEBAR_W, CANVAS_H).convert("RGBA")
    canvas.alpha_composite(sidebar, (0, 0))

    # Sidebar text
    draw_sidebar_text(canvas)

    # Bottom bar with name + logo (drawn before the starburst so the burst stays on top of the sidebar)
    draw_bottom_bar(canvas, name)

    # Starburst inside the sidebar, near the bottom
    draw_starburst(
        canvas,
        center=(SIDEBAR_W // 2, CANVAS_H - 50),
        outer_r=22,
        inner_r=10,
        points=12,
    )

    out_path.parent.mkdir(parents=True, exist_ok=True)
    canvas.convert("RGB").save(out_path, "PNG", optimize=True)


def main():
    ap = argparse.ArgumentParser(description="Render NFT.NYC 2026 proof-of-submission cards.")
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
    default_out = Path(args.out).resolve() if args.out else (csv_dir / "rendered-pos-cards")
    cache_dir = Path(args.cache).resolve() if args.cache else (csv_dir / "photo-cache")

    with open(csv_path, newline="", encoding="utf-8-sig") as f:
        rows = list(csv.DictReader(f))

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
