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
import html
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


INDEX_HTML_TEMPLATE = """<!doctype html>
<html lang="en"><head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>NFT.NYC 2026 - Speaker Track Cards ({count} sessions)</title>
<style>
  html,body{{margin:0;padding:0;background:#0a0a0a;color:#eee;font-family:-apple-system,BlinkMacSystemFont,"Helvetica Neue",Helvetica,Arial,sans-serif}}
  header{{padding:36px 40px 8px;position:sticky;top:0;background:linear-gradient(#0a0a0a,#0a0a0acc 70%,transparent);z-index:10;backdrop-filter:blur(6px)}}
  header h1{{font-weight:300;letter-spacing:-.01em;margin:0 0 6px;font-size:30px}}
  header p{{margin:0 0 14px;opacity:.6;font-size:13px}}
  .controls{{display:flex;gap:10px;flex-wrap:wrap;align-items:center}}
  .controls input[type=search]{{flex:0 0 280px;padding:8px 12px;border-radius:10px;border:1px solid #2a2a2a;background:#141414;color:#eee;font:inherit}}
  .controls select{{padding:8px 12px;border-radius:10px;border:1px solid #2a2a2a;background:#141414;color:#eee;font:inherit}}
  .controls .count{{margin-left:auto;opacity:.55;font-size:13px}}
  .grid{{display:grid;gap:18px;padding:18px 40px 60px;grid-template-columns:repeat(auto-fill,minmax(220px,1fr))}}
  .card{{background:#141414;border-radius:14px;overflow:hidden;text-decoration:none;color:#ddd;transition:transform .15s ease;display:flex;flex-direction:column}}
  .card:hover{{transform:translateY(-2px)}}
  .card img{{width:100%;display:block;aspect-ratio:1/1;object-fit:cover;background:#000}}
  .meta{{padding:10px 12px;border-top:1px solid rgba(255,255,255,.06);font-size:12px;display:flex;flex-direction:column;gap:3px}}
  .meta .name{{font-size:14px;color:#fff}}
  .meta .track{{opacity:.65}}
  .meta .sid{{opacity:.4;font-family:ui-monospace,SFMono-Regular,Menlo,monospace;font-size:11px}}
  .hidden{{display:none !important}}
</style>
</head><body>
<header>
  <h1>NFT.NYC 2026 - Speaker Track Cards</h1>
  <p>{count} sessions . 1080x1080 . click any card to open the full JPG (the same URL the voting feed embeds)</p>
  <div class="controls">
    <input id="q" type="search" placeholder="Filter by speaker, track, or session ID">
    <select id="track">
      <option value="">All tracks</option>
      {track_options}
    </select>
    <span class="count" id="count"></span>
  </div>
</header>
<div class="grid" id="grid">
{cards}
</div>
<script>
  const q = document.getElementById('q');
  const tsel = document.getElementById('track');
  const grid = document.getElementById('grid');
  const cards = Array.from(grid.children);
  const count = document.getElementById('count');
  function apply() {{
    const term = q.value.trim().toLowerCase();
    const t = tsel.value;
    let shown = 0;
    for (const c of cards) {{
      const hay = c.dataset.search;
      const trk = c.dataset.track;
      const ok = (!term || hay.includes(term)) && (!t || trk === t);
      c.classList.toggle('hidden', !ok);
      if (ok) shown++;
    }}
    count.textContent = shown + ' shown';
  }}
  q.addEventListener('input', apply);
  tsel.addEventListener('change', apply);
  apply();
</script>
</body></html>
"""


def write_index_html(path: Path, manifest: dict) -> None:
    items = sorted(
        manifest.items(),
        key=lambda kv: (kv[1].get("track", ""), kv[1].get("speakerName", "").lower()),
    )
    tracks = sorted({v.get("track", "") for v in manifest.values() if v.get("track")})
    track_options = "\n      ".join(
        f'<option value="{html.escape(t)}">{html.escape(t)}</option>' for t in tracks
    )
    card_html_parts = []
    for sid, info in items:
        name = info.get("speakerName", "")
        track = info.get("track", "")
        filename = info["imageUrl"].rsplit("/", 1)[-1]
        search_blob = " ".join([sid, name, track]).lower()
        card_html_parts.append(
            f'<a class="card" href="{html.escape(filename)}" target="_blank" '
            f'data-search="{html.escape(search_blob)}" data-track="{html.escape(track)}">'
            f'<img loading="lazy" src="{html.escape(filename)}" alt="{html.escape(name)}">'
            f'<div class="meta">'
            f'<span class="name">{html.escape(name)}</span>'
            f'<span class="track">{html.escape(track)}</span>'
            f'<span class="sid">{html.escape(sid)}</span>'
            f'</div></a>'
        )
    page = INDEX_HTML_TEMPLATE.format(
        count=len(items),
        track_options=track_options,
        cards="\n".join(card_html_parts),
    )
    path.write_text(page, encoding="utf-8")


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

    index_path = out_dir / "index.html"
    write_index_html(index_path, manifest)

    print(
        f"\nDone. {successes} rendered, {failures} failed, "
        f"{skipped_no_track} co-speaker rows skipped (no track), "
        f"{skipped_excluded} excluded, {skipped_no_photo} skipped (no photo)."
    )
    print(f"Manifest: {manifest_path}")
    print(f"Index:    {index_path}")
    sys.exit(0 if failures == 0 else 2)


if __name__ == "__main__":
    main()
