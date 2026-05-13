#!/usr/bin/env python3
"""
NFTNYC2026_Session_Track_Card — renders one track card PER SESSION (not per speaker).

Filename pattern: nftnyc2026-speakertrack-<sessionId>.jpg
Manifest:         sessions.json (sessionId -> {imageUrl, speakerName, track, photoUrl})

Source: NFT.NYC 2026 flattened sessions export (XLSX or CSV). In a multi-speaker
session, the row whose Track column is filled is the session owner / primary
speaker row (the export populates Track only on the first/primary row for the
session). We render that row.

Reuses render_card and helpers from NFTNYC2026_Track_Card_template.py.

Usage:
    python3 scripts/NFTNYC2026_Session_Track_Card.py path/to/sessions.xlsx \
        --out docs --base-url https://nftkred.github.io/nftnyc-2026-card-generators
"""

import argparse
import csv
import json
import sys
from pathlib import Path

import openpyxl

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))

from NFTNYC2026_Track_Card_template import (  # noqa: E402
    EXCLUDED_SPEAKER_IDS,
    PHOTO_Y_OFFSETS,
    fetch_to_cache,
    is_url,
    lookup_photo_override,
    pick_column,
    render_card,
    resolve_name,
    resolve_track,
)

FILENAME_PREFIX = "nftnyc2026-speakertrack-"


def _read_xlsx_rows(path: Path) -> list[dict]:
    """Read an XLSX into a list of dicts. The flattened sessions export has duplicate
    headers (Track at col 8 AND col 74, Day at col 30 AND col 73, Announced col 31/75,
    OneHub col 36/79, Highlighted col 34/78); the rightmost duplicates are unpopulated.
    Keep the first occurrence of each header so the populated column wins.
    """
    wb = openpyxl.load_workbook(path, read_only=True, data_only=True)
    ws = wb.active
    it = ws.iter_rows(values_only=True)
    raw_headers = [str(h).strip() if h is not None else "" for h in next(it)]
    seen: set[str] = set()
    keep_indices: list[tuple[int, str]] = []
    for i, h in enumerate(raw_headers):
        if not h or h in seen:
            continue
        seen.add(h)
        keep_indices.append((i, h))
    rows: list[dict] = []
    for r in it:
        if r is None:
            continue
        row = {}
        for i, h in keep_indices:
            v = r[i] if i < len(r) else None
            row[h] = "" if v is None else (str(v).strip() if not isinstance(v, str) else v.strip())
        if any(row.values()):
            rows.append(row)
    return rows


def _read_csv_rows(path: Path) -> list[dict]:
    with open(path, newline="", encoding="utf-8-sig") as f:
        return [
            {k: (v.strip() if isinstance(v, str) else v) for k, v in row.items() if k}
            for row in csv.DictReader(f)
        ]


def load_rows(path: Path) -> list[dict]:
    suffix = path.suffix.lower()
    if suffix in (".xlsx", ".xlsm"):
        return _read_xlsx_rows(path)
    if suffix == ".csv":
        return _read_csv_rows(path)
    raise SystemExit(f"Unsupported input format: {suffix} (use .xlsx or .csv)")


def main():
    ap = argparse.ArgumentParser(description="Render NFT.NYC 2026 per-session track cards.")
    ap.add_argument("source", help="XLSX or CSV with flattened sessions+speakers")
    ap.add_argument("--out", default=None, help="Output directory (default: ./docs next to source)")
    ap.add_argument("--cache", default=None, help="Photo cache directory")
    ap.add_argument(
        "--base-url",
        default="https://nftkred.github.io/nftnyc-2026-card-generators",
        help="Public base URL used to construct imageUrl in sessions.json",
    )
    ap.add_argument("--limit", type=int, help="Only render the first N sessions (debugging)")
    ap.add_argument(
        "--only-session",
        help="Render only this Session Id (debugging). Can be passed multiple times comma-separated.",
    )
    args = ap.parse_args()

    src_path = Path(args.source).resolve()
    if not src_path.exists():
        print(f"Source not found: {src_path}", file=sys.stderr)
        sys.exit(1)

    src_dir = src_path.parent
    out_dir = Path(args.out).resolve() if args.out else (src_dir / "docs")
    cache_dir = Path(args.cache).resolve() if args.cache else (src_dir / "photo-cache")
    only_sessions = {s.strip() for s in args.only_session.split(",")} if args.only_session else None

    rows = load_rows(src_path)

    manifest: dict = {}
    successes = 0
    failures = 0
    skipped_no_track = 0
    skipped_excluded = 0
    skipped_no_photo = 0

    base_url = args.base_url.rstrip("/")

    for i, row in enumerate(rows, 1):
        session_id = pick_column(row, "Session Id", "session_id")
        if not session_id:
            continue
        # Primary-speaker row filter: Track is only populated on the row where the
        # session's owner/primary speaker lives. Co-speaker rows have an empty Track.
        track_raw = pick_column(row, "Track")
        if not track_raw:
            skipped_no_track += 1
            continue
        if only_sessions and session_id not in only_sessions:
            continue

        speaker_id = pick_column(row, "Speaker Id", "speaker_id")
        if speaker_id and speaker_id in EXCLUDED_SPEAKER_IDS:
            skipped_excluded += 1
            continue

        photo = pick_column(row, "Profile Picture", "image_path", "photo", "url")
        if not photo:
            skipped_no_photo += 1
            continue

        name = resolve_name(row)
        track = resolve_track(track_raw)

        try:
            override = lookup_photo_override(speaker_id) if speaker_id else None
            if override:
                photo_path = override
            elif is_url(photo):
                photo_path = fetch_to_cache(photo, cache_dir)
            else:
                photo_path = Path(photo)
                if not photo_path.is_absolute():
                    photo_path = (src_dir / photo_path).resolve()
                if not photo_path.exists():
                    raise FileNotFoundError(f"photo not found: {photo_path}")
        except Exception as e:
            print(f"[{i}] FAIL fetch session={session_id} {name}: {e}", file=sys.stderr)
            failures += 1
            continue

        filename = f"{FILENAME_PREFIX}{session_id}.jpg"
        out_path = out_dir / filename

        try:
            y_offset = PHOTO_Y_OFFSETS.get(speaker_id, 0) if speaker_id else 0
            render_card(photo_path, name, track, out_path, y_offset=y_offset, image_format="JPEG")
        except Exception as e:
            print(f"[{i}] FAIL render session={session_id} {name}: {e}", file=sys.stderr)
            failures += 1
            continue

        manifest[str(session_id)] = {
            "imageUrl": f"{base_url}/{filename}",
            "speakerName": name,
            "track": track,
            "photoSource": photo,
            "speakerId": speaker_id or "",
        }
        successes += 1
        print(f"[{i}] {session_id}  {name}  [{track}]  -> {out_path}")

        if args.limit and successes >= args.limit:
            break

    manifest_path = out_dir / "sessions.json"
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    with open(manifest_path, "w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=2, sort_keys=True)
        f.write("\n")

    print(
        f"\nDone. {successes} rendered, {failures} failed, "
        f"{skipped_no_track} co-speaker rows skipped (no track), "
        f"{skipped_excluded} excluded, {skipped_no_photo} skipped (no photo)."
    )
    print(f"Manifest: {manifest_path}")
    sys.exit(0 if failures == 0 else 2)


if __name__ == "__main__":
    main()
