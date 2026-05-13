# NFT.NYC 2026 Speaker Card Generators

Three Python tools that render the NFT.NYC 2026 speaker-card image set from a
Sessionize CSV export. Layout, typography, and palette are design-locked
(2026-05-07) — do not change without explicit sign-off.

## Tools

| Script | Output | Use |
|---|---|---|
| `scripts/NFTNYC2026_Speaker_Card_template.py` | 800×800 PNG, blurred-photo background with circular portrait + "26" watermark | Hero speaker card |
| `scripts/NFTNYC2026_Track_Card_template.py` | 1080×1080 PNG, sidebar tinted by track brand colour | Track-specific announcement card |
| `scripts/NFTNYC2026_Proof_of_Submission_template.py` | 1080×1080 PNG, "PROOF OF SUBMISSION 2026" sidebar | Confirmation card for accepted speakers |

## Sample output

- `proof-of-submission-output/` — 91 rendered Proof-of-Submission cards + an `index.html` grid view
- `track-card-output/` — 91 rendered Track cards + an `index.html` grid view

Open either `index.html` in a browser to browse the rendered set.

## Requirements

- Python 3.10+
- `pip install pillow`
- Fonts installed locally:
  - `~/Library/Fonts/MonumentExtended-Black.otf` (uppercase headings only — brand rule)
  - `~/Library/Fonts/SpaceGrotesk-Bold.ttf`, `SpaceGrotesk-Medium.ttf`, `SpaceGrotesk-Regular.ttf` (used for any mixed-case text, e.g. speaker names)
- NFT.NYC white logo PNG referenced by the scripts (path is at the top of each script — adjust for your environment).

## Usage

```bash
python3 scripts/NFTNYC2026_Speaker_Card_template.py path/to/speakers.csv --out rendered/
python3 scripts/NFTNYC2026_Track_Card_template.py path/to/speakers.csv --out track-cards/
python3 scripts/NFTNYC2026_Proof_of_Submission_template.py path/to/speakers.csv --out pos/
```

The CSV is the Sessionize speakers export. Each script auto-detects the
relevant columns (photo URL, screen name, speaker id). Photos are cached in
`./photo-cache/` next to the CSV and reused on re-runs.

### Photo overrides

Drop a replacement headshot into `scripts/assets/photo-overrides/<speaker-id>.{jpg,png}`
to override the Sessionize photo for that speaker.

## Brand rules baked into the renderers

- **Monument Extended is uppercase-only.** Any mixed-case text (speaker names,
  pseudonyms with internal capitals) uses Space Grotesk Bold instead.
- **Pseudonyms display first**, with a FirstName-only fallback. Never
  "FirstName LastName" combined.
- Track-card sidebar colour is derived from the speaker's primary session
  track via the shared `TRACK_BASE_COLORS` palette in the Track Card script.
