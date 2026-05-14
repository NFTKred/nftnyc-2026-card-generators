#!/usr/bin/env python3
"""
Clone each rendered session card to a second filename keyed by the legacy
Speaker Voting Platform "original" ID, so URLs the old code constructs still
resolve.

The voting platform originally tracked sessions by a long UUID-style ID. We
migrated to Sessionize's shorter numeric Session Id, but some downstream code
still references the original IDs. For each row in the mapping CSV we copy
docs/nftnyc2026-speakertrack-<sessionId>.jpg
  -> docs/nftnyc2026-speakertrack-<originalId>.jpg

The copy is byte-for-byte (shutil.copyfile), not a re-render, so the two URLs
are guaranteed identical.

Each affected entry in docs/sessions.json gets an `originalId` field added.

Usage:
    python3 scripts/clone_legacy_id_aliases.py session_id_mapping.csv \
        [--docs docs] [--prefix nftnyc2026-speakertrack-]
"""

import argparse
import csv
import json
import shutil
import sys
from pathlib import Path

DEFAULT_PREFIX = "nftnyc2026-speakertrack-"


def main():
    ap = argparse.ArgumentParser(description="Clone session card JPGs under legacy original IDs.")
    ap.add_argument("mapping", help="CSV with columns: original_id, sessionize_session_id, ...")
    ap.add_argument("--docs", default="docs", help="Directory containing rendered JPGs + sessions.json")
    ap.add_argument("--prefix", default=DEFAULT_PREFIX, help="Filename prefix (default: %(default)s)")
    args = ap.parse_args()

    docs_dir = Path(args.docs).resolve()
    if not docs_dir.is_dir():
        print(f"docs dir not found: {docs_dir}", file=sys.stderr)
        sys.exit(1)

    manifest_path = docs_dir / "sessions.json"
    manifest = {}
    if manifest_path.exists():
        manifest = json.loads(manifest_path.read_text())

    with open(args.mapping, newline="", encoding="utf-8-sig") as f:
        rows = list(csv.DictReader(f))

    copied = 0
    skipped_missing = 0
    skipped_no_old = 0
    updated_manifest_entries = 0

    for row in rows:
        original_id = (row.get("original_id") or "").strip()
        session_id = (row.get("sessionize_session_id") or "").strip()
        if not session_id:
            continue
        if not original_id:
            skipped_no_old += 1
            continue

        src = docs_dir / f"{args.prefix}{session_id}.jpg"
        dst = docs_dir / f"{args.prefix}{original_id}.jpg"

        if not src.exists():
            print(f"  miss: source not found for session {session_id}", file=sys.stderr)
            skipped_missing += 1
            continue

        if dst.exists() and dst.stat().st_size == src.stat().st_size:
            # Already cloned and unchanged - leave it.
            pass
        else:
            shutil.copyfile(src, dst)
            copied += 1

        entry = manifest.get(session_id)
        if entry is not None and entry.get("originalId") != original_id:
            entry["originalId"] = original_id
            updated_manifest_entries += 1

    if manifest:
        manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n")

    print(
        f"\nDone. {copied} cloned, {skipped_missing} missing source, "
        f"{skipped_no_old} rows with no original_id, "
        f"{updated_manifest_entries} manifest entries updated."
    )


if __name__ == "__main__":
    main()
