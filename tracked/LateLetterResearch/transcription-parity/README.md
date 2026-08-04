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
| Active blocker | `570f8131c83cdafded2c3b5be78d4df8` (`sitting-cat`) | `/Users/r/Downloads/STRUCTURAL ASCII ART EXAMPLES /570f8131c83cdafded2c3b5be78d4df8.normalized.png`; SHA-256 `e9b08e31960ffd6fe6e5e52e84107fd22ad80b645b6f1de2e21f4e9a20444275` | 236×236 | Attempts 002–003 rejected; operator rejected the visibly wrong nine-row diagnostic replay; attempt 004 and every TXT remain blocked |
| Authored / complete | `eb861dc84400fc36` | operator-authored `accepted.txt`; SHA-256 `04bce501c712fc071523711a3ea1b67a8af302434a66f0e638c2bdc144b0baac`; prior PNG SHA-256 `725949a5a44ce353100f56f6afc4494c3554a1da3505d02bfd1f33edc3ce25d1` | 6 TXT rows; prior PNG 394×192 | Approved rose-bush art asset with trailing spaces excluded; pipeline not run and not claimed |

The operator-supplied `bbbb_flowers.normalized.png` hashes exactly to the existing accepted
`bbbb-flowers` source, so it is recorded as complete rather than duplicated in the pending queue.
Queued files remain outside the tracked evidence tree until activation; activation begins by
copying the selected source into its own immutable `source/` snapshot and verifying the recorded
hash. Do not use the provisional TXT files beside these downloads as recognizer input.

`eb861dc84400fc36` left the conversion queue by a different authority path on 2026-08-03: the
operator identified the six-line TXT as newly authored rose-bush art and approved it, then
corrected the intake to exclude trailing spaces. Its package records authorship and approval, not
recognition success. No candidate, attempt, geometry proof, raster-parity result, or pipeline claim
exists or is implied. Runtime integration is separately pending because the existing renderer-local
rose placeholder is different art and does not inherit this approval.

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

## General Unicode converter status and execution order

SPEC §7.10.7 is the authoritative end-to-end authority contract. Slices 1–5 established
canonical-IR, writer-boundary, corpus, raster-evidence, and component mechanics, but the
2026-08-04 architecture audit reopened the claim that geometry admission is single-owner. A local
source-only correction now returns coherent proved fixed-lattice decisions for both accepted
references and passes the focused raster-geometry tests. The identity-pinned external 26-source
replay is complete: 12 proved, 14 rejected/unresolved, zero timeouts, and zero harness errors. Its
inventory, implementation identity, and replay are recorded in
`geometry-replay/source-inventory-2026-08-04.json`,
`geometry-replay/implementation-identity-2026-08-04.json`, and
`geometry-replay/current-frozen-identity-2026-08-04.json`; because the source root is external and
the repository is dirty, this remains measurement-only, not a release gate. The class-eliminating
diagnostic criteria remain in the implementation. Recognition is independently blocked by its
32-entry structural vocabulary and biased ranking objective.

The pre-scorer release-fixture coverage/rank matrix is recorded in
`coverage-rank-matrix-2026-08-04-v4.json`. It is measurement-only and preserves adapter-level evidence without
using sitting-cat truth. Fixed ASCII has one present-but-losing row and one present-and-winning row; degraded
fixed art has one winning and one absent row; the remaining uncovered families are explicitly absent or unsupported
under the installed offline profiles.

`UnicodeTemplateRunAdapter` is now a proposal-only, source-run dynamic-programming adapter with hash-pinned font,
component ownership, residual, collision, and margin evidence. Its v5 coverage measurement is recorded in
`coverage-rank-matrix-2026-08-04-v5.json`; all ten positive targets remain outside reported top-k, so ranking and
candidate writing remain blocked. Arabic shaping and CJK repertoire assets are intentionally unsupported until their
profiles are pinned.

The subsequent pinned-cache replays are preserved as separate diagnostics: v6 exercised the verified Tesseract
cache but still lacked the run-level structural adapter; v7 added the Unicode template adapters but still lacked
that structural adapter in the harness. Both remained below coverage. v8 and v9 were interrupted at the ten-minute
runtime ceiling (Emoji atlas, then structural span expansion) and produced no benchmark report. The timeout receipt
is `tests/fixtures/transcription-v2/recognizer-benchmark-timeouts-2026-08-04.json`. The corrected ten-adapter v10
profile and receipt now complete independently, but four invocations exceed their pinned fixture budgets: Tesseract
on degraded fixed art, structural Unicode on degraded fixed and emoji-ZWJ art, and EmojiAtlas on emoji-ZWJ. This is
a runtime gate, not a complete coverage/rank matrix. It does already show broad failure: the other 96 completed
adapter/fixture records account for 96 `positive_missing` results, including all completed Latin, combining, and
Kana template records. Peak process RSS reached 2,420,146,176 bytes; the receipt repeats the process high-water mark,
so attribution remains open. No complete v10 coverage benchmark is authorized yet.

The canonical production `transcribe()`/`accept()` owners now exist in
`src/lateletter/transcription/pipeline.py` and the `lateletter transcribe` / `lateletter accept`
CLI paths. They currently stop at a failed geometry or open-repertoire recognition gate and write
no candidate TXT; synthetic receipt tests cover promotion only. Proposal capture remains diagnostic.

The current sitting-cat replay proves only these facts: the source has nine recoverable row strips;
all nine diagnostic strings can be placed on their measured runs; the first `___` row visually
matches; and the remaining eight selected strings do not. The operator explicitly rejected the
side-by-side replay for wrong head/face glyphs and broken middle/lower structure. `aligned` is
width/placement evidence, not glyph-identity evidence. No replay may create attempt 004 until exact
proposal coverage and the machine authority gates pass. Its public geometry result remains
`rejected/unresolved` with all proof flags false, while the non-authoritative evidence seam now
produces 16 deterministic proposal-only hypotheses. Run-level candidates preserve source component
IDs. Neither fact authorizes TXT.

Completed prerequisites: sitting-cat evaluation truth is unavailable to runtime; the second
geometry selector has been removed; unresolved proposal evidence is typed and non-authoritative;
run-level component IDs survive into proposals; and fail-closed production `transcribe()`/`accept()`
owners exist. None of those prerequisites proves conversion accuracy.

Current continuation order:

1. attribute each of the four v10 budget failures to its internal source-only cost owner, recording
   stage timings and run/span/glyph/atlas/subprocess/state/cache counts against paired passing controls;
2. make Tesseract's degraded path complete or explicitly refuse within 12 seconds using capability-
   derived scheduling or bounded execution, not a larger ceiling or truth-derived pruning;
3. bound structural Unicode expansion for degraded-fixed and emoji-ZWJ inputs below 90 seconds using
   admissible topology/dominance/state-merging rules or a typed capability refusal;
4. index the Unicode 17 emoji atlas so full VS/ZWJ cluster matching, collisions, residuals, and margins
   complete below 30 seconds without partial-cluster matching;
5. rerun the complete ten-adapter profile in fresh processes and require zero budget failures,
   deterministic hashes, terminal records for every adapter/fixture, and bounded peak resources;
6. only then run the full v10 coverage benchmark and source-hash-bound matrix; classify every miss as
   absent, unsupported, collision, or present-but-losing while keeping sitting-cat truth unavailable;
7. in the co-equal geometry child, classify all 14 live-corpus rejections by expected profile,
   implement only generic source-derived admission evidence for supported classes, and rerun the
   identity-pinned 26-source receipt; sitting-cat must prove geometry before attempt 004;
8. add pinned recognizer/repertoire coverage only for the remaining absent/unsupported families,
   including Arabic, Kanji/CJK, width mixtures, and mixed scripts; do not grow the finite structural
   glyph table into a claimed Unicode recognizer;
9. regenerate the coverage matrix, then rebuild ranking only for present-but-losing cases: remove
   cost floors, whitelist bonuses, duplicate rescoring, and codepoint tie-breaks in favor of one
   evidence-calibrated, identity-sensitive objective;
10. complete exactly-once component ownership, unexplained-ink, collision, and winner-margin gates;
11. complete/revalidate logical grapheme, shaping/bidi, and width evidence while preserving logical
   TXT order separately from visual comparison order;
12. harden and extend the implemented `pipeline.py` `transcribe()`/`accept()` owners as the first
   production users of the canonical IR and candidate writer; keep the recognizer gate fail-closed
   until open-repertoire coverage is proven;
13. re-pin tests at public interfaces and accepted-corpus outcomes, while retaining expected-fail
   fixtures and immutability/ownership invariants;
14. generate the next immutable release/holdout benchmark and require exact top-k coverage, no
   false-unique negative resolution, deterministic hashes, and bounded resources;
15. run a source-only sitting-cat replay; create attempt 004 only after all nine rows are visually
   correct and every machine gate passes, then await operator accept/reject; and
16. rerun horse as fresh attempt 065 without importing attempt-064 text, then resume the queue.

`eb861dc84400fc36` stays outside recognizer execution because it is operator-authored approved art;
its separate Garden integration must use the delete-first canonical asset boundary.

Spent lanes that must not be repeated are: isolated-cell OCR for connected art, choosing the first
legal grid, treating zero unknowns as correctness, font/renderer parameter searches before TXT
review, source-stencil zero-diff proxies, larger undifferentiated beams, transcript-specific glyph
rules, provisional/evaluation TXT as runtime input, and hand repair of immutable candidates.

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
