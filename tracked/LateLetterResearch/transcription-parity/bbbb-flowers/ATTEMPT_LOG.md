# `bbbb-flowers` attempt log

All source material and every future conversion attempt are retained here. An attempt is
immutable once its render, overlay, and diff have been created.

## 001 — manual repair (rejected)

The initial pre-gate TXT was copied and manually edited while attempting to match the source.
It was rejected: row/glyph repairs were not a deterministic conversion and did not achieve visual
parity. `rejected-candidate.txt`, `rerender.png`, `overlay.png`, and `diff.png` preserve the final
state of that failed attempt.

Earlier intermediate edits to the same mutable files were overwritten before this attempt-log
policy existed; they cannot be reconstructed. `docs/FAILURE_LOG.md` records the known mutations.

The source snapshot is `source/source.normalized.png`, SHA-256
`f7d6f3d502cac705902885083219bed253a92cc0d5a5c058353c6781b04f7f3e`.

## 002 — Tesseract box mapping (machine candidate)

`002-grid-ocr/` records the measured 9 px × 19 px lattice, Tesseract `makebox` output, and a
fail-closed grid mapping. It is not accepted: line-level OCR merges punctuation and leaves cells
as `?` rather than inventing a glyph.

## 003 — per-cell Tesseract OCR (rejected)

`003-cell-ocr/` is retained with its generated candidate and per-cell evidence. It has 185 unknown
cells because off-canvas grid columns were incorrectly sliced with negative indexes.

## 004 — off-canvas guard (rejected metadata)

`004-cell-ocr-boundary-fixed/` fixes the slicing error but has a copied attempt identifier in its
manifest. It remains immutable evidence; no files are renamed or replaced.

## 005 — corrected metadata (rejected guide handling)

`005-cell-ocr-boundary-and-metadata-fixed/` labels itself correctly. Its broad guide suppression
removed the real central stem while failing to remove every dotted capture rail, so it is rejected.

## 006 — repeated-rail guide filter (candidate)

`006-cell-ocr-guide-fixed/` preserves the central stem and removes the rail sequence. Its two-pixel
cell-overlap still makes Tesseract read adjacent fragments as one glyph, leaving 101 unknown cells.

## 007 — exact 9 px cell bounds (candidate)

`007-cell-ocr-exact-boundaries/` removes horizontal overlap and lowers unresolved cells to 76. It
is still only a machine candidate: no unknown may be silently substituted, and it has not passed
source/re-render visual parity.

## 008 — geometric fallback (rejected)

`008-cell-ocr-geometric/` is retained as a failed experiment. The geometry fallback reduced the
reported unknown count to 18 by making speculative parenthesis, bracket, and stroke decisions;
the overlay showed false glyphs and wrong structure. Its manifest was not executable by the parity
renderer and its rows stripped trailing cells. It is rejected, not a conversion.

## 009 — calibration probe (rejected)

`009-calibrated-cell-ocr/` records the first calibration-only run. It missed a fourth dotted guide
rail partially covered by the flower stem, so the derived ink bounds and phase were contaminated.
The directory is retained immutable; it was not used as a transcription.

## 010 — rail-extension probe (rejected)

`010-calibrated-cell-ocr/` records the next calibration-only run. A naive 36 px extension treated
the central art stem as additional screenshot rails. That failure is retained; the rail detector
was changed to require a sparse isolated-dot signature before another attempt.

## 011 — calibration-derived cell OCR (superseded, not accepted)

`011-calibrated-cell-ocr/` derives the 9 px × 19 px lattice, origin, baseline, row/column extent,
and guide set from the source. It emits a source hash, calibration hash, recognizer/version/options,
normalization record, every cell's confidence, and a complete renderer manifest. The candidate
preserves all 35 columns, including trailing blank cells, and re-renders through the parity tool.
It has 22 unresolved cells and its overlay still disagrees with the source; verdict remains
`not_reviewed` / **OPEN**.

## 012 — calibration-derived cell OCR with complete artifact manifest (superseded, not accepted)

`012-calibrated-cell-ocr/` repeats the immutable run after the manifest review found one missing
reference: the calibration overlay itself was present but was not named under `artifacts`. The new
manifest now names `calibration.png` as well as the cell evidence, re-render, overlay, and diff.
The source hash, calibration hash, derived grid, recognizer metadata/options, normalization, and
all 560 cell records remain present. It has the same 22 unresolved cells and remains
`not_reviewed` / **OPEN**; 011 is retained as superseded evidence, not edited.

## 013 — calibration-derived cell OCR with corrected normalization receipt (superseded, not accepted)

`013-calibrated-cell-ocr/` repeats the run after a metadata-only inconsistency was found: the
normalization string still described the earlier three-rail, 5 px erase band even though the
calibrator now detects a partially covered fourth rail and erases exact columns. The candidate
and rendered artifacts are otherwise the same: 22 unresolved cells, 560 cell records, complete
parity manifest, and `not_reviewed` / **OPEN**. Attempts 011 and 012 remain immutable evidence.

## 014 — occupancy-gated OCR with fail-closed manifest (rejected)

`014-occupancy-gated-ocr/` executes the required phases separately: calibration, occupancy map,
structural occupancy review, recognition, and rendering. The occupancy phase emits no transcript;
the review phase validates all 560 unique cell records before recognition proceeds. The final
manifest correctly says `status: rejected` and `review.verdict: rejected` because 22 nonblank cells
remain unknown. The renderer refuses a second invocation once its three PNGs exist. This is the
process artifact, not a parity acceptance.

## 015 — first improved recognizer (rejected calibration)

`015-improved-recognition/` is retained after the first recognizer improvement. Its nearest-
baseline crop derivation misassigned the first pixels of each row and produced a 21px crop on a
19px lattice; 17 cells remained unresolved. It is immutable evidence, not a rerun target.

## 016 — row-gutter calibration (rejected candidate)

`016-row-gutter-calibrated/` records the clean repeated-boundary calibration (`-15..+4`, 19px
tile). It removes the cross-row composites, but leaves 14 genuine punctuation cells for the shape
recognizer. No manual substitutions were made.

## 017 — structural shape recognition (rejected candidate)

`017-structural-shape-recognition/` adds deterministic punctuation geometry for parentheses,
colons, brackets, and edge fragments. It reduces unknowns to six one-pixel side-bearing cells;
the classifier identifies them as blank, but the control branch still sent geometric blanks to
Tesseract, so the manifest remains rejected.

## 018 — geometric blank handling (rejected visual candidate)

`018-structural-shape-blank-fixed/` keeps geometric blanks as blanks and reaches zero unknowns.
The parity overlay still shows two classifier defects: a compact period was called `_`, and a
left bracket was called `/`. It is retained without edits.

## 019 — period and bracket correction (rejected visual candidate)

`019-period-bracket-fixed/` corrects the compact period and reaches zero unknowns, but the bracket
terminal test still inspected gutter rows and left `[` as `/`. It is retained immutable.

## 020 — bracket terminal correction (rejected candidate)

`020-bracket-terminals-fixed/` uses bbox-relative bracket terminals. It leaves one right bracket
unresolved because the terminal slice is still offset from the cell bbox. No output was edited.

## 021 — final structural recognizer (machine candidate, not accepted)

`021-final-structural-recognition/` completes calibration, all 560 occupancy records, structural
review, recognition, and one render. It has `unknown_cells: 0` and the source-sized comparison
PNGs. The operator then accepted layout parity and human visual parity. Exact raster parity remains
blocked by the unknown source font/renderer, disclosed rather than treated as a rejection. The
machine candidate was copied byte-for-byte to the package's `accepted.txt`; the durable receipt is
`acceptance-receipt.json`. Attempt 021 itself was not modified.

## Acceptance — verified reference transcription with blocked raster parity

The operator verdict is `approved`: layout parity and human visual parity are accepted, while exact
raster parity is `blocked_unknown_font`. `accepted.txt` has SHA-256
`6b33a6a36d98dac6e8e50094f3ca949b4ebcc55318a658e2b4535c18c8c20173`, identical to attempt 021's
machine candidate. The source, candidate, calibration, occupancy-review, rerender, overlay, and
diff hashes are recorded in `acceptance-receipt.json`; the root manifest is promoted to
`verified_reference_transcription_blocked_raster`. This is the first accepted transcript in the
package and does not claim pixel-exact raster reconstruction.
