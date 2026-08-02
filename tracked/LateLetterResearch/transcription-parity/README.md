# Reference-transcription parity packages

One directory per reference image. A package keeps the source identity, a UTF-8 candidate or
accepted transcript, an explicit render-placement manifest, and same-pixel-dimension comparison
PNGs. Run:

```sh
python3 scripts/render_transcription_parity.py \
  tracked/LateLetterResearch/transcription-parity/<reference-id>/manifest.json
```

The renderer only creates `rerender.png`, `overlay.png`, and `diff.png`; it does not infer a
grid, alter a transcript, or set an acceptance verdict. When the source font is unknown, these
are readable structural review surfaces: a font-only pixel diff is diagnostic and does not reject
a structurally correct TXT. See SPEC §7.10.5 for the gate.

## Execution queue

This is the durable conversion order. A queued reference is intake only: its source path, hash,
and dimensions are recorded, but it receives no package or attempt directory until it becomes
active. Only one reference may be active at a time.

| Order | Reference ID | Source identity | Dimensions | State |
| --- | --- | --- | --- | --- |
| Complete | `bbbb-flowers` | `bbbb_flowers.normalized.png`; SHA-256 `f7d6f3d502cac705902885083219bed253a92cc0d5a5c058353c6781b04f7f3e` | 307×318 | Accepted TXT; blocked raster parity disclosed |
| Paused | `horse-animation-sheet` | tracked source SHA-256 `9ea8eab2c0b378ed89ad2337515a6baea4ec81d0eace6ba042fab4abee63a3d3` | 424×468 | Operator reprioritized the next queue item; attempt 064 remains rejected 17 unknown / 17 low-confidence / 0 structural / 0 forced-blank; 063 invalidated for working-copy mutation |
| Complete | `a8283c5cdb63b130` | `/Users/r/Downloads/STRUCTURAL ASCII ART EXAMPLES /a8283c5cdb63b130.png!cover_jpg.normalized.png`; SHA-256 `c50bcf5ded3a0499f762762f8bec75db6ac2c9176806061a86c2a6d8317bd8d8` | 271×619 | Attempt 015 approved; accepted TXT recorded; raster parity not run |
| 2 | `570f8131c83cdafded2c3b5be78d4df8` (`sitting-cat`) | `/Users/r/Downloads/STRUCTURAL ASCII ART EXAMPLES /570f8131c83cdafded2c3b5be78d4df8.normalized.png`; SHA-256 `e9b08e31960ffd6fe6e5e52e84107fd22ad80b645b6f1de2e21f4e9a20444275` | 236×236 | Attempt 002 rejected proposal-only; Japanese run recognition failed; no accepted TXT |
| 3 | `eb861dc84400fc36` | `/Users/r/Downloads/STRUCTURAL ASCII ART EXAMPLES /eb861dc84400fc36.png!cover_jpg.normalized.png`; SHA-256 `725949a5a44ce353100f56f6afc4494c3554a1da3505d02bfd1f33edc3ce25d1` | 394×192 | Queued; not started |

The operator-supplied `bbbb_flowers.normalized.png` hashes exactly to the existing accepted
`bbbb-flowers` source, so it is recorded as complete rather than duplicated in the pending queue.
Queued files remain outside the tracked evidence tree until activation; activation begins by
copying the selected source into its own immutable `source/` snapshot and verifying the recorded
hash. Do not use the provisional TXT files beside these downloads as recognizer input.

`a8283c5cdb63b130` was explicitly activated on 2026-08-02 and approved after operator review. Its source snapshot is tracked under
`a8283c5cdb63b130/source/`. Calibration attempts 001–005 are preserved range/legality evidence;
attempt 006 contains the machine occupancy and structural review for the join-aware 16×19 grid;
attempts 007, 009–014 are immutable rejected row-joint evidence; attempt 015 is the current
zero-count machine candidate bound to that calibration. It has 304/304 cells with zero unknown,
zero low-confidence, zero structural, and zero forced-blank conflicts. The operator approved it;
`accepted.txt` is a byte-for-byte copy with a durable `acceptance-receipt.json`. No parity renderer
was run. The calibration's 76 raw
boundary pixels are all recorded horizontal joins, not substantive diagonal cuts; the calibration
foreground is source-derived black rather than near-white antialiasing.

## Monospace recovery plan

1. Calibrate source ink, cell advance, row pitch, phase, and baselines. Save calibration JSON and
   a grid overlay.
2. Segment all cells, including blank cells; retain absolute row/column indices.
3. Decode complete rows jointly: use overlapping windows, complete-image component ownership,
   neighbouring-row spill proofs, leave-one-out templates, and exact repeated silhouettes. Never
   infer a glyph from an isolated crop when ownership is unresolved; never edit TXT manually.
4. Write a new immutable machine candidate with one hash-bound record for every cell. Trailing
   spaces and row widths are validated against the transcript hash before rendering. Unknown,
   low-confidence, or structural-conflict cells block acceptance.
5. Re-render only a hash-bound candidate with a genuine glyph renderer. The renderer must reject
   missing/mismatched transcript hashes, use no source pixels, and compare source/re-render/overlay/
   diff at matching pixel dimensions. With an unknown source face, the result is structural
   diagnostics rather than a pixel-exact parity claim.
6. Copy only an operator-accepted machine candidate to `accepted.txt`; a nonzero diff caused only
   by an unknown font/renderer is disclosed as blocked and does not reject a structurally correct
   TXT. Wrong rows, spaces, glyphs, ownership, or structural strokes still reject.

`bbbb-flowers`'s current machine candidate is
`attempts/021-final-structural-recognition/`. The derived lattice is 9 px × 19 px with a
source-sized `calibration.png`; occupancy, recognition, and rendering all complete, and the
candidate contains zero unknown cells. Operator review accepted layout and human visual parity;
exact raster parity remains **blocked_unknown_font** because the source font/renderer is unknown.
The byte-for-byte accepted copy is `bbbb-flowers/accepted.txt`, with its durable receipt in
`bbbb-flowers/acceptance-receipt.json`. The root manifest now records a verified reference
transcription with that raster disclosure. The root `candidate.txt` and attempts 001–020 remain
retained immutable failure evidence; no TXT was edited by hand. Attempts 014–020 document the crop
and shape-recognition defects corrected before 021.

The canonical command sequence creates calibration, reviews occupancy in a separate phase, then
recognizes. It consumes calibration rather than accepting origin, baseline, or advance guesses:

```sh
python3 scripts/calibrate_monospace_grid.py \
  tracked/LateLetterResearch/transcription-parity/bbbb-flowers/source/source.normalized.png \
  tracked/LateLetterResearch/transcription-parity/bbbb-flowers/attempts/<new-attempt>
python3 scripts/ocr_monospace_cells.py \
  tracked/LateLetterResearch/transcription-parity/bbbb-flowers/source/source.normalized.png \
  tracked/LateLetterResearch/transcription-parity/bbbb-flowers/attempts/<new-attempt> \
  --calibration tracked/LateLetterResearch/transcription-parity/bbbb-flowers/attempts/<new-attempt>/calibration.json \
  --phase occupancy
python3 scripts/ocr_monospace_cells.py \
  tracked/LateLetterResearch/transcription-parity/bbbb-flowers/source/source.normalized.png \
  tracked/LateLetterResearch/transcription-parity/bbbb-flowers/attempts/<new-attempt> \
  --calibration tracked/LateLetterResearch/transcription-parity/bbbb-flowers/attempts/<new-attempt>/calibration.json \
  --phase review
python3 scripts/ocr_monospace_cells.py \
  tracked/LateLetterResearch/transcription-parity/bbbb-flowers/source/source.normalized.png \
  tracked/LateLetterResearch/transcription-parity/bbbb-flowers/attempts/<new-attempt> \
  --calibration tracked/LateLetterResearch/transcription-parity/bbbb-flowers/attempts/<new-attempt>/calibration.json \
  --phase recognize
python3 scripts/render_transcription_parity.py \
  tracked/LateLetterResearch/transcription-parity/bbbb-flowers/attempts/<new-attempt>/manifest.json
```

The occupancy phase writes only `occupancy-map.json`; it cannot emit a transcript. The review phase
validates one unique record per cell and writes `occupancy-review.json`; only the later recognize
phase may emit text. This structural review is not operator visual acceptance. The command
sequence is immutable-attempt work: calibrate into a new directory first, then add the occupancy,
candidate, and parity artifacts there. Existing attempt files and rendered PNGs are never
overwritten; a second render fails closed.

The next reference is `horse-animation-sheet`. Its tracked source is 424×468. Attempts 007–014
reuse an invalid 40×22, 11×21 px grid whose vertical boundaries cut through glyph strokes; they
remain immutable rejected evidence, and attempt 014's zero counts do not constitute a machine-gate
pass. Attempt 015 records the approved subpixel calibration used by later work: 11.55×21 px,
origin −1.5 px, 37×22, with only two boundary-ink pixels. Attempts 016–031 remain immutable
rejected renderer/recognizer probes; their nonzero PNG diffs and recognizer defects are recorded
in the horse attempt log. Attempt 028 is retained but explicitly rejected as a source-copy proxy
and excluded from the authoritative parity path. Attempt 029 is frozen as the last genuine
renderer comparison: 8× DejaVu Sans Mono with bicubic downsampling, `diff_pixel_count=1486`, and
per-cell residuals. Its residual attribution is historical; future renders use the hash-bound
calibration cell boundaries rather than experimental renderer placement.

Attempt 046 reached the machine counts but is rejected because its TXT was later found to diverge
from its row evidence (an extra leading `S` and a 39-column row). Attempts 048–053 that consumed
that TXT remain frozen evidence. Attempt 054 then correctly reopened two coarse-shape aliases;
attempts 055 and 058 are preserved machine-gate runs; 057 and 059 are preserved fail-closed
recognition runs. Attempt 060 proves the component-state repair; attempt 061 is frozen rejected
evidence because it emitted spill periods, false apostrophes, and a compound-parenthesis
substitution. Attempt 062 records the forced-blank/punctuation-context correction with 13 unknown
and 13 low-confidence cells. Attempt 063 is the current immutable candidate: compound/edge-contact
parenthesis crops remain `?`, unproven punctuation cannot be relabelled by topology consensus, and
the machine gate records 17 unknown, 17 low-confidence, 0 structural, and 0 forced-blank
conflicts. A later working-copy mutation invalidated 063; fresh attempt 064 has verified transcript
hash `8d6b27d77024d10a220f4841610b215065abeb6e7b173c25b1963aef18c0c2e2`. No comparison renderer or `accepted.txt` exists. Non-ASCII references are deferred to
the Unicode run-decoder boundary; do not add per-glyph ASCII branches for Japanese/Kanji partials,
Arabic joining/bidi, combining marks, fullwidth/halfwidth, emoji, or other grapheme clusters.

For a fixed-cell reference whose calibration has passed the visual grid gate, run the row-joint
stage into a new immutable directory (never over an earlier attempt):

```sh
python3 scripts/decode_monospace_rows.py \
  <reference>/source/source.normalized.png \
  <reference>/attempts/<new-attempt>/calibration.json \
  <reference>/attempts/<new-attempt>
```

This emits `machine-row-joint.txt`, `row-decoding.json`, `template-bank.json`, and a manifest with
the transcript hash. It refuses an existing output directory and refuses a transcript whose rows,
trailing spaces, or cell records disagree. Run the comparison renderer only when all machine
counts—including forced-blank conflicts—are zero and the operator has reviewed the emitted rows;
it requires the transcript hash and refuses source-pixel inputs. A font-only pixel residual is
diagnostic, not a TXT rejection.

Do not start another reference, tune the renderer, or create `accepted.txt` until a
contact-sheet-reviewed transcript reaches zero unknown, low-confidence, structural-conflict,
and forced-blank-conflict cells and the operator accepts its font-independent visual structure.
