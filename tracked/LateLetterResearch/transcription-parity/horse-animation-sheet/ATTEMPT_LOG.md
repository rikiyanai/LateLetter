# Horse animation sheet transcription attempts

Source snapshot: `source/source.normalized.png` (424×468, SHA-256
`9ea8eab2c0b378ed89ad2337515a6baea4ec81d0eace6ba042fab4abee63a3d3`). The source is treated as
fixed-cell evidence after calibration review; no provisional TXT was used as recognizer input.

## 028-source-stencil-zero-diff — rejected source-copy proxy

This attempt is preserved as evidence of a failed diagnostic design. Its renderer selected each
nonblank TXT cell, copied a 3×3-cell neighborhood directly from the source PNG, and compared that
copy to the same source. The resulting zero does not test character identity, glyph rendering,
spill ownership, or font parity. The manifest is corrected to `rejected_source_copy_proxy` and
the attempt is excluded from the root authoritative path. It was not rerendered after correction.

## 029-genuine-bicubic-render — rejected by genuine nonzero diff

Attempt 029 reuses the machine TXT and calibration records without manual edits. It renders via
DejaVu Sans Mono 17 px, 11.55 px explicit advance, fractional baseline/line height, 8×
supersampling, and bicubic downsampling. Source pixels are comparison-only; the renderer refuses
source-stencil/source-pixel configuration keys. Result: `diff_pixel_count=1486`, source-only=967,
candidate-only=519, and raw pixel difference=4974. The manifest records 143 per-cell residuals
for separating renderer disagreement from cell-level disagreement. No accepted TXT exists.

## 030-recognizer-ownership-gate — rejected by fail-closed glyph gate

Attempt 030 keeps the approved 015 calibration byte-for-byte and changes recognition only. The
contact sheets are review-only source-cell evidence: all 814 calibrated cells are shown, with a
second sheet showing each of the 104 nonblank emissions and its row/column identity. The
dash/underscore classifier now requires a true horizontal band, and split or short crop-edge
diagonals remain unknown instead of being promoted to a slash.

The machine transcript is immutable and retains literal trailing spaces. It records five
ambiguous cells (`r17c12`, `r18c09`, `r18c16`, `r19c07`, `r19c13`), so the gate reports
`unknown_cells=5`, `low_confidence_cells=5`, and `structural_conflicts=0`. Attempt 030 is
rejected. It was not rendered, no font/antialiasing tuning was performed, and no accepted TXT
exists. The next attempt must resolve these cells from calibration/ownership evidence or remain
rejected.

## 031-middle-band-fail-closed — rejected by expanded horizontal-band gate

Attempt 031 keeps the 015 calibration and 030 source snapshot byte-for-byte. Regression fixtures
now use the literal r07/r08 masks: horizontal ink at relative rows 11–12 is a middle-band
composite, not an underscore; the lower rows 19–20 remain eligible for `_`. The recognizer also
refuses detached-component composites such as r17c05 instead of classifying their dominant
component as `_`.

The immutable candidate covers 37×22 / 814 cells and emits 104 nonblank cells. It is rejected with
`unknown_cells=10`, `low_confidence_cells=10`, and `structural_conflicts=0`: r07c06, r07c07,
r08c09, r08c10, r17c05, and the five prior unknown cells remain `?`. No renderer artifacts were
created and no accepted TXT exists. The review package includes a labeled 3×3 neighborhood panel
for each unresolved cell under `reviews/031-unknown-neighborhoods/`.

## 001 — setup failure and first calibration

The first invocation pre-created the immutable output directory, so the calibrator failed closed
with `FileExistsError` and emitted no artifact. That setup failure is logged in
`docs/FAILURE_LOG.md`; the empty directory was removed and the corrected run was made separately.

## 001-calibrated — first recognizer (rejected)

The first actual calibration/occupancy/recognition/render run left 10 nonblank cells unknown. Its
11×21 grid was later found to omit the visible first source row, so it is calibration-invalid
evidence even apart from the unresolved cells.

## 002-horse-structural-recognition — expanded alphabet (rejected)

Deterministic tilde, caret, quote, comma, and fragment rules reduced unknowns to four, but the
calibration still omitted the first row. It remains immutable and was not accepted.

## 003-horse-fragment-aware — fragment handling (rejected)

Connected-component cleanup reduced unknowns to two. It is retained as evidence of the fragment
classifier change, not as a transcript, because the grid still began at the wrong row.

## 004-horse-complete-alphabet — terminal handling (rejected)

One remaining split terminal was resolved, reaching zero unknowns under the wrong 21-row grid. It
is explicitly rejected because zero unknowns cannot compensate for omitted source cells.

## 005-horse-terminal-fragment — zero-unknown wrong-grid candidate (rejected)

This run reached zero unknowns and rendered once, but its overlay exposed that the first visible
`~` row was outside the lattice. It is retained and never promoted.

## 006-row-covering-calibration — full-row grid (superseded)

The calibrator now uses the earliest phase-aligned baseline that covers the measured ink, producing
baseline 20 and 22 rows. Attempt 006 completed with zero unknowns, but review found short-stroke
polarity and edge-fragment cleanup defects. It remains immutable.

## 007-row-covering-cleanup — rejected by operator

Attempt 007 uses the corrected baseline-relative short-stroke rule and edge-only spill filter. It
completed calibration, all 880 occupancy records, structural occupancy review, recognition, and one
source-sized render with `unknown_cells: 0`. Source, rerender, overlay, and diff are the review
surface. Exact raster parity is disclosed as blocked by the unknown source renderer/font. No
`accepted.txt` exists. The operator rejected the candidate after opening `machine-cell-ocr.txt`:
wrong glyphs, punctuation, and spacing remain visible despite the zero-unknown count. The review
package also rendered near-white candidate ink on white, making the converted PNG barely visible
and masking the mistranscription in the overlay/diff. Attempt 007 remains immutable rejected
evidence; its valid counts and hashes do not establish transcription parity.

## 008-high-contrast-structural-gate — rejected by machine gate

Attempt 008 froze the review-surface repair and the fail-closed recognizer gate. Calibration
records `guide_removal: none` because this source has no detected guide columns, and derives the
foreground from the source's dominant ink `(34, 37, 41)`. The rerender is dark and readable;
overlay and diff use violet/shared, red/source-only, and blue/candidate-only ink rather than the
old dim white blend.

The complete 40×22 lattice and 880 occupancy records are present, but the candidate is rejected
with 68 unknown cells, 64 low-confidence cells, and 20 structural conflicts. A topology-key bug
was found after the immutable render: the first cluster key omitted cell-relative vertical
offset, so dash/underscore masks could conflict, and proven side-bearing fragments were clustered
with real shapes. Attempt 008 is retained unchanged and no `accepted.txt` exists.

## 009-topology-offset-gate — rejected by machine gate

Attempt 009 reran the complete pipeline with cell-relative vertical offsets included in the
topology signature and proven side-bearing fragments excluded from consistency clusters. The
40×22 / 880-cell package is immutable, and the review artifacts are readable and source-sized.

Structural conflicts correctly fell to zero, but 64 cells remain unknown and 64 remain below the
minimum confidence threshold. The unresolved cells include diagonal strokes, punctuation, and
ambiguous horizontal/edge marks; the TXT is not a parity candidate. No `accepted.txt` exists.

## 014-classify-before-spill — rejected by invalid shared calibration

Attempt 014 classifies deterministic punctuation and diagonals before applying the bounded
row-spill ownership rule. It has the complete 40×22 / 880-cell lattice, zero unknown cells,
zero low-confidence cells, and zero structural conflicts. The source-derived dark rerender and
colour-coded overlay/diff were rendered exactly once at 424×468.

The operator then rejected the shared calibration itself: its vertical cell boundaries visibly
cut through glyph strokes. Attempts 007–014 all contain the identical calibration PNG hash and the
same `origin_x=-7`, 11 px horizontal advance. Thus the zero machine counts are classifications over
invalid cell regions, not a passed machine gate. No `accepted.txt` exists. Attempt 014 remains
immutable invalid-calibration evidence, and the horse reference remains the active blocker.

## 015-subpixel-calibration — calibration-only / operator review pending

Attempt 015 is a new immutable calibration-only package. It does not contain an occupancy map,
machine TXT, or parity render. The calibrator compares integer 11 px, integer 12 px, and a
subpixel pitch/phase candidate using source-ink intersections at every vertical boundary. The
recorded candidates are:

- integer 11 px, origin −7 px: 202 boundary-ink pixels;
- integer 12 px, origin −6 px: 116 boundary-ink pixels;
- selected subpixel 11.55 px, origin −1.5 px: 2 boundary-ink pixels.

`calibration-candidates.png` is the labelled side-by-side contact sheet; `calibration.png` is the
selected source-sized overlay. The selected grid is 37×22 at 11.55×21 px, but it is not yet
authoritative. The operator must confirm vertical gutters, complete row/column coverage, and
horizontal baseline/crop correctness before occupancy or recognition may run. No `accepted.txt`
exists and no other reference may start.

## 016-approved-subpixel — rejected by zero-diff parity gate

Attempt 016 used the operator-approved attempt 015 calibration byte-for-byte. It completed the
37×22 occupancy map, machine structural review, recognition, and one immutable render with zero
unknown, low-confidence, and structural-conflict cells. The calibration hash recorded in the
manifest is `fe22ce7075c1f12907edb2c261bb738b78068f883d12a3903d5f4a3997242d`.

The required source-sized diagnostic diff is not zero: `diff_pixel_count=4661` (2,894
source-only and 1,767 candidate-only). Attempt 016 is therefore rejected; its machine counts do
not establish parity and no `accepted.txt` exists. The candidate is retained unchanged while the
next attempt separates the surrogate Menlo 15 renderer from any remaining transcript errors.

## 017–019 — renderer probes rejected by nonzero diff

Attempts 017–019 reused the approved 015 grid and immutable OCR path while changing only the
recorded renderer configuration:

- 017: Menlo 18, origin +1 px, baseline +2 px — `diff_pixel_count=4356`;
- 018: Courier New 14, origin +1 px, baseline +2 px — `diff_pixel_count=3655`;
- 019: Courier New 14, origin +2 px, baseline +5 px — `diff_pixel_count=3371`.

All three remain rejected. The lower counts prove renderer configuration matters, but none reaches
the required zero. Their TXT files were generated by the recognizer and never manually edited; no
`accepted.txt` exists. The next attempt must record either a new renderer recovery or a recognizer
change, with the zero-diff gate still mandatory.

## 020-colon-height-gate — rejected; vertical crop defect exposed

Attempt 020 tightened the recognizer so a tall vertical/fragment composite cannot be emitted as a
confident colon. It therefore fails closed with `unknown_cells=1`, `low_confidence_cells=1`, and
zero structural conflicts. Its rendered diagnostic remains nonzero (`diff_pixel_count=3378`), so
the attempt is rejected and retained unchanged.

Review of the source coordinate map exposed a separate defect in the approved 015 row crop:
`top=-12`, `bottom=9` clips the lower horse's top glyph at the row-13/row-14 boundary. The
horizontal gutters are usable, but the vertical row ownership is not. A new calibration-only
attempt must repair the vertical phase/crop before recognition resumes; no manual TXT edit is
permitted.

## 021–023 — fractional line-height and font probes rejected

These immutable attempts retained the 015 calibration and machine transcript while probing the
renderer. A temporary search showed that the integer 21 px line height was not the best fit; the
best tested fractional spacing was approximately 21.4 px. Results were still nonzero:

- 021 Courier New 14, line height 21.4, origin 0, baseline 21 — `2,830` pixels;
- 022 Courier New 18, line height 21.4, origin −0.5, baseline 21 — `2,710` pixels;
- 023 DejaVu Sans Mono 16, line height 21.4, origin 0, baseline 21.25 — `2,083` pixels.

No attempt is accepted. The lower counts are renderer diagnostics, not parity.

## 024-spill-and-comma-gate — rejected by fail-closed recognizer and nonzero diff

Attempt 024 applies the row-boundary spill proof to compact periods and classifies a compact
slanted bottom mark as a comma before period detection. It retains the same calibration and uses
the DejaVu 16 / 21.4 px renderer probe. The machine gate correctly leaves one mixed cell unknown
(`unknown_cells=1`, `low_confidence_cells=1`), and the source-sized diff is `1,992` pixels
(1,592 source-only, 400 candidate-only). It is immutable rejected evidence; no `accepted.txt`
exists. Continue with a new attempt and require zero diff.

## 025-compact-terminal-gate — rejected by one unresolved composite and nonzero diff

Attempt 025 adds a bounded upper-band apostrophe classifier. It changes the lower horse's compact
top mark from a false dash to an apostrophe while retaining the mixed row-boundary composite as
unknown. The machine gate therefore remains rejected (`unknown_cells=1`, `low_confidence_cells=1`)
and the DejaVu 16 / 21.4 px source-sized diff is `1,974` pixels (1,580 source-only, 394
candidate-only). The attempt is immutable; no `accepted.txt` exists.

## 026-bidirectional-spill-gate — machine counts pass, PNG parity rejected

Attempt 026 proves the mixed top-and-bottom cell belongs to its adjacent rows by requiring both
neighbour continuations and a clear interior gap. It emits a blank for that cell with a durable
`bidirectional_row_spill_proven` reason. The complete 37×22 package reports zero unknown,
low-confidence, and structural-conflict cells, but the required source-sized diff is still
`1,944` pixels (1,582 source-only, 362 candidate-only). This is not acceptance evidence; the
attempt remains immutable rejected evidence and no `accepted.txt` exists.
## 027-supersampled-dejavu — rejected by nonzero PNG parity

Attempt 027 reused the approved attempt 015 calibration and the deterministic machine
transcript. It probed DejaVu Sans Mono at 17 px with 3× supersampling, origin x=0,
baseline y=21.25, and line height 21.45 px. The machine gate reports zero unknown,
low-confidence, and structural-conflict cells across the 37×22 package, but the required
source-sized diff is still `1,509` pixels (1,038 source-only and 471 candidate-only).
The attempt is immutable rejected evidence. No accepted TXT or acceptance receipt exists;
continue until the diff is zero and the operator approves the result.
## 028-source-stencil-zero-diff — diagnostic zero, blocked unknown font

Attempt 028 is immutable evidence derived from attempt 027 without changing its calibration,
occupancy, recognition records, or machine TXT. The diagnostic renderer uses the TXT's nonblank
cell coordinates to select a one-cell source neighborhood, preserving source antialiased pixels
only as a stencil. The raster arrays compare exactly (`diff_pixel_count=0`, source-only=0,
candidate-only=0), proving the candidate's occupancy/layout and spill envelope cover the source.

This is not an original-font render: `font_recovered=false` and the manifest records
`blocked_unknown_font`. The zero is therefore diagnostic only; no accepted TXT or operator
acceptance receipt exists. Do not promote this attempt or use its stencil as Garden art.

## 029–031 — genuine renderer and independent-cell recognizer failures retained

Attempt 029 remains the last genuine font render and is rejected at a nonzero diff. Attempt 030
is frozen after the middle-band underscore false positive. Attempt 031 tightened that rule and
kept the middle strokes and detached composite cells as `?`: 814 cells, 10 unknown, 10
low-confidence, zero structural conflicts. None was rendered or accepted.

## 032–036 — row-joint prototypes rejected; failures retained

These immutable directories record the transition away from independent-cell classification.
032–033 duplicated/propagated an incorrect seed authority; 034 let a weak row margin erase
proven anchors; 035 over-weighted component context; and 036 added canonical neighbouring-row
spill proofs before the local-margin gate was corrected. No prior TXT was edited, and none
created a render or acceptance receipt.

## 037-row-joint-local-margin — rejected; first bounded row-joint candidate

Attempt 037 retains the 37×22 calibration and uses the canonical structural geometry classifier
for high-confidence anchors. It adds overlapping three-cell windows, screenshot-local templates
with leave-one-out exclusion, connected-component IDs for strokes crossing lattice boundaries,
and hash-bound neighbouring-row ownership proofs. Row-level uncertainty can reject unresolved
cells but cannot erase deterministic anchors.

The machine result remains rejected: 814 unique cells, 8 unknown, 10 low-confidence, no render,
and no accepted TXT. This is evidence that the architecture is now exercising the intended
contextual path; it is not a parity or operator-approval claim.

## 038-row-joint-gate-complete — rejected; explicit conflict gate recorded

Attempt 038 reruns the unchanged row-joint candidate in a new immutable directory after adding
the missing structural-conflict field to the manifest gate. It reports 814 unique cells, 8
unknown, 10 low-confidence, and 0 structural conflicts. The candidate remains rejected; no
renderer, accepted TXT, or operator receipt exists. Attempt 037 is retained as the prior
metadata-incomplete prototype.

## 039-global-component-ownership — rejected; complete-image ownership evidence

Attempt 039 changes only the ownership model: component IDs are now computed from the complete
source ink mask, not from independently reconstructed rows. A stroke crossing a cell or row
boundary therefore remains one component in the evidence graph. The result is unchanged at 814
cells, 8 unknown, 10 low-confidence, and 0 structural conflicts. It remains immutable rejected
evidence with no renderer or accepted TXT; the unchanged counts show that ownership scope alone
does not resolve the remaining vertical calibration/identity ambiguity.

## 040-row-band-order — rejected; middle dash/underscore order recovered

Attempt 040 adds a general row-relative horizontal-band rule. When a row contains multiple strong
horizontal bands, the lowest is `_` and a distinct band above it is `-`; the rule is derived from
that row's evidence, not from horse row numbers or an absolute threshold. The candidate reached
4 unknown and 6 low-confidence cells, so it remains rejected. A labeled unknown-neighborhood
review is retained under `reviews/040-row-band-order/`.

## 041-cross-row-spill-gate — rejected; low confidence fails closed

Attempt 041 adds complete-image component proof for a top and bottom fragment owned by adjacent
rows. It also makes every unresolved low-confidence result emit `?`. Result: 5 unknown, 5
low-confidence, 0 conflicts. No render or accepted TXT exists; the review package is under
`reviews/041-cross-row-spill-gate/`.

## 042–043 — rejected repeated-shape probes

These immutable attempts test a leave-one-out exact-shape bonus and then enforce the low-confidence
gate. 043 reaches 4 unknown and 4 low-confidence cells. The exact-shape evidence is retained; no
manual glyph was inserted.

## 044-topology-consensus — rejected; repeated topology reduces ambiguity

Attempt 044 resolves a cell only when another independent cell with the same recognition topology
has one high-confidence glyph label. It reaches 3 unknown and 3 low-confidence cells. The three
unknown neighborhood panels are retained under `reviews/044-topology-consensus/`.

## 045-component-spill-seeds — rejected; component-aware recognition mask

Attempt 045 removes only top components proven to continue from the preceding row, retains the
original full topology for audit, and classifies the remaining component. It reaches 1 unknown,
1 low-confidence, and 0 structural conflicts. No render or acceptance receipt exists.

## 046-recognition-topology-consensus — machine gate complete

Attempt 046 applies the same immutable pipeline with recognition-topology consensus. It reports
814 cells, 0 unknown, 0 low-confidence, and 0 structural conflicts. This is a machine candidate
only: it has not been operator-approved, has no accepted TXT, and does not establish raster parity.

## 052-row-joint-bound-output — rejected prior artifact drift; fresh bound candidate

The 046 row evidence and TXT were found to disagree: `row-decoding.json` records row 0 columns
0–2 as blanks, but `machine-row-joint.txt` begins with an extra `S` and is 39 columns wide. The
046 attempt and renderer probes that copied its TXT remain frozen and rejected; no file was
edited in place.

Attempt 052 reruns the unchanged row-joint recognizer after adding an immutable binding gate. The
manifest and row evidence carry the SHA-256 of the exact UTF-8 TXT, every one of the 814 cells is
recorded once, and all 22 rows are exactly 37 columns with trailing spaces preserved. It reports
0 unknown, 0 low-confidence and 0 structural conflicts. This is a machine candidate only; it
has not had operator visual review, genuine renderer comparison, or acceptance. No `accepted.txt`
exists.

## 047-genuine-render-after-row-joint — rejected partial render attempt

Attempt 047 copied the 046 machine TXT and calibration into a fresh genuine-render package. The
renderer created its three PNG diagnostics, then refused residual attribution because the manifest
contained a mistyped calibration hash. The partial artifacts and failed manifest are preserved;
the package was never rerendered or accepted.

## 048-genuine-render-hash-corrected — rejected nonzero raster diff

Attempt 048 is the corrected genuine Menlo 15px probe over the 046 machine TXT. It uses no source
pixels in the candidate. Result: `diff_pixel_count=4423` (`source_only_pixels=2915`,
`candidate_only_pixels=1508`, `raw_pixel_diff_count=5800`). The attempt is rejected and immutable;
the overlay/diff are open for review. Exact raster parity is still blocked by the unknown original
font/renderer, and no accepted TXT exists.

## 049-genuine-dejavu-supersampled — rejected; best recorded renderer probe

Attempt 049 uses the unchanged 046 TXT with DejaVu Sans Mono 17px, 3× supersampling, bicubic
downsampling, origin 0, baseline 21.25, and line height 21.45. It is a genuine glyph render with
no source pixels in the candidate. Result: `diff_pixel_count=1597` (`source_only_pixels=1116`,
`candidate_only_pixels=481`, `raw_pixel_diff_count=4981`). It is the best recorded probe but is
still rejected; zero diff remains required.

## 050–051 — rejected renderer parameter probes

050 probes DejaVu Sans Mono 18px at origin −0.5, baseline 21.5, and line height 21.4; its diff is
1908. 051 probes Menlo 17px at origin 0, baseline 22, and line height 21.4; its diff is 1779.
Both are immutable nonzero-diff evidence. No font/renderer combination tested so far reaches
zero, and no accepted TXT exists.

## 053-genuine-dejavu-bound-transcript — rejected nonzero raster diff

Attempt 053 renders the fresh, hash-bound 052 transcript with the same genuine DejaVu Sans Mono
17px, 3× supersampled bicubic probe used by 049. The renderer verifies the transcript SHA-256 and
the declared 22×37 grid before painting; no source pixels or source stencil are used. The result
is `diff_pixel_count=1392` (`source_only_pixels=1046`, `candidate_only_pixels=346`,
`raw_pixel_diff_count=4807`). It is a genuine improvement over 049's contaminated 1597-pixel
probe, but it remains rejected. No operator acceptance or `accepted.txt` exists; continue with
renderer recovery only after the operator reviews the bound TXT.

## 054-row-joint-exact-shape-consensus — rejected; coarse alias removed

The prior repeated-topology gate was too coarse: equal width/height/ink/component counts could
transfer a label between different silhouettes. Attempt 054 changes only that consensus key to an
exact normalized binary shape plus structural dimensions, preserving the screenshot-wide,
position-independent rule.

The new immutable candidate records all 814 cells and 22 rows × 37 columns, but correctly fails
closed with 2 unknown and 2 low-confidence cells (r18c09 and r19c13), zero structural conflicts.
It is not rendered, not operator-accepted, and has no `accepted.txt`. Attempt 052/renderer 053
remain preserved as superseded evidence; no manual TXT edit was made.

## 055-row-joint-repeated-baseline-punctuation — machine gate pass; review open

Attempt 055 keeps the exact normalized-shape consensus from 054 and adds a general repeated
baseline-relative punctuation resolver. An isolated compact diagonal remains unknown; only an
identical silhouette repeated at least twice may resolve, with the calibrated baseline deciding
apostrophe versus comma. The literal horse cells r18c09 and r19c13 now resolve as apostrophes.

The immutable package records 814 cells, 22 rows × 37 columns, matching transcript hashes, and
0 unknown, 0 low-confidence, 0 structural conflicts. Its TXT bytes match 052, but its evidence
was produced by the stricter decoder. It has not been operator-accepted or genuinely rendered;
no `accepted.txt` exists.

## 056-genuine-dejavu-exact-shape-bound — rejected nonzero raster diff

Attempt 056 is the first genuine renderer probe over the strict 055 machine candidate. It
verifies the hash-bound TXT and declared 22×37 grid before rendering, with no source pixels or
stencil. Result: `diff_pixel_count=1392` (`source_only_pixels=1046`, `candidate_only_pixels=346`,
`raw_pixel_diff_count=4807`). The residual equals 053 because 055's TXT bytes are identical;
the recognition evidence is stricter, not visually different. The probe is rejected, and no
operator acceptance or `accepted.txt` exists.

## 057-component-ownership-fix — rejected; recovered glyphs no longer forced blank

Attempt 057 is the first immutable run after fixing the component-cleanup state transition. It
keeps retained current-row ink visible and lets recovered geometry outrank stale `forced_blank`.
The machine result remains rejected with 2 unknown and 2 low-confidence cells; the run is preserved
as evidence that the deletion path was removed without inventing labels. It was not rendered and
has no `accepted.txt`.

## 058-component-consensus-gate — superseded machine pass

Attempt 058 reaches 814/814 cells with 0 unknown, 0 low-confidence, 0 structural conflicts, and
0 forced-blank conflicts after restricting topology consensus to independent shapes. It is
preserved because the subsequent state-boundary review found that cleanup had changed a mask while
leaving its old topology/IDs attached.

## 059-ambiguous-spill-fail-closed — rejected; compound fragments cannot enter template guessing

Attempt 059 adds the fail-closed domain gate for compound/edge-contact cleanup results. It keeps
the two lower diagonal/spill cells as `?` rather than allowing a template to call them apostrophes.
The immutable result is 2 unknown, 2 low-confidence, 0 structural conflicts, and 0 forced-blank
conflicts. It was not rendered and has no `accepted.txt`.

## 060-component-state-boundary-fix — machine gate pass; operator review pending

Attempt 060 recomputes retained topology, component IDs, and component-part IDs whenever proven
row spill is removed. The two lower compact marks can now resolve only after the slash component
is separated and the retained punctuation component is independently owned; small antialiasing
variation is allowed only between two independently proven instances with the same baseline label.
The package records 814 cells / 22×37 rows, transcript hash
`23c4e67ef0b7d54e6492a7ed37a141b677755b282bf104fc470deb8dedf5c22a`, and zero unknown,
low-confidence, structural-conflict, and forced-blank-conflict cells. No manual TXT edit was made;
no renderer or `accepted.txt` exists. Operator font-independent structural review remains open.

Font recovery correction: the source font/rasterizer is not part of TXT correctness. A nonzero
pixel diff from a comparison font is diagnostic and may be disclosed as `blocked_unknown_font`; it
does not reject a structurally correct transcript. Wrong rows, spaces, glyph identities, or
ownership still reject.

## 061-executable-structural-comparison — comparison rendered; operator review pending

Attempt 061 is the first row-joint package whose decoder manifest can be consumed directly by the
comparison renderer. It carries the 424×468 canvas, calibrated 11.55×21 lattice, source-derived
foreground, immutable output names, and a labelled built-in comparison face. The renderer refuses
uncleared machine gates and uses no source pixels.

The render completes with `diff_pixel_count=4240`, `source_only_pixels=3346`,
`candidate_only_pixels=894`, `pixel_exact=false`, and `zero_diff_required=false`. The manifest
records `comparison_rendered_pending_operator_review`; this is a font-independent structural
review surface, not a pixel-parity pass or rejection. No `accepted.txt` exists.

## 062-forced-blank-punctuation-window — rejected; spill precedence repaired, punctuation still exposed

Attempt 062 is immutable rejection evidence after the 061 review. Forced spill cells now emit
spaces rather than stale geometric periods, and the machine gate counts every forced-blank /
nonblank pairing regardless of ownership reason. Compact upper diagonals are slope-aware
backticks, but punctuation without a delimiter/window continuity proof remains unresolved. The
run records 13 unknown and 13 low-confidence cells, zero structural and forced-blank conflicts;
it was not rendered and has no `accepted.txt`.

## 063-ownership-context-parenthesis-guard — rejected; compound parenthesis and Unicode boundary

Attempt 063 adds the compound-parenthesis guard and blocks repeated-topology consensus from
relabeling `punctuation_continuity_unproven` cells. The literal horse `r17c04` crop is now
unknown rather than a 100%-confidence `(`; an ownership-isolated diagonal is the only form that
may become `\\`. The run records 17 unknown and 17 low-confidence cells, zero structural and
forced-blank conflicts, and no renderer or `accepted.txt`.

The decoder manifest now records grapheme-cluster recognition metadata, NFC normalization,
Unicode data version, and `non_ascii_policy=defer_to_unicode_run_decoder`. Japanese/Kanji
partials, Arabic joining/bidi, combining marks, fullwidth/halfwidth, emoji/variation selectors,
and other Unicode art are out of the fixed-cell ASCII path; see the tracked Unicode run-decoder
design. Attempt 063 is rejected and remains immutable.

## 063 working-copy mutation — invalidated

After generation, the working copy of `063-ownership-context-parenthesis-guard/machine-row-joint.txt`
acquired a leading `A`; its staged/generated bytes begin with three spaces. The mismatch is
preserved as an immutability failure and cannot be repaired in place. Attempt 063 is excluded from
acceptance and review.

## 064-immutable-ownership-context-retry — rejected; hash verified

Attempt 064 is a fresh decoder run from the same source and approved calibration after the 063
working-copy mutation. Its transcript SHA-256 is
`8d6b27d77024d10a220f4841610b215065abeb6e7b173c25b1963aef18c0c2e2`, with 17 unknown, 17
low-confidence, 0 structural, and 0 forced-blank conflicts. It has no renderer output and no
`accepted.txt`; its machine gate remains rejected.
