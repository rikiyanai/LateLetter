# Row-joint fixed-cell decoder

The horse sheet exposed a system defect in the original conversion path: it classified each
cropped cell in isolation. A crop cannot tell whether a short mark is a glyph, a side-bearing
fragment, or ink owned by the row above/below. It also cannot distinguish a dash from an
underscore when the crop is vertically misregistered. The replacement path is deterministic and
fail-closed, but it does not claim exact font/raster recovery.

## Contract

1. Calibration supplies the lattice. The decoder does not choose a new origin, pitch, baseline,
   or crop while recognizing.
2. Every declared cell is retained, including blanks and trailing spaces.
3. High-confidence geometry comes from the canonical structural classifier. A low-confidence or
   ambiguous geometry result is unresolved; it is never promoted by a generic OCR guess.
4. Each cell carries an overlapping horizontal evidence window (the cell plus one neighbour on
   each side). The window is evidence only; it cannot alter world coordinates or become artwork.
5. Connected components are computed across each complete row. A component crossing a lattice
   edge receives one shared ownership ID so the sequence decoder can keep both sides visible.
6. Tiny edge marks are blanked only when the canonical neighbouring-cell or row-spill proof
   establishes their owner. Otherwise they remain ink and can become `?`. When component cleanup
   removes proven preceding-row spill, it recomputes the retained mask's topology and component
   IDs; retained ink can never remain `forced_blank`.
7. Repeated source shapes form a screenshot-local template bank. A cell is never scored against a
   template learned from itself (leave-one-out). Repeated masks must therefore resolve
   consistently or remain unresolved. Compact punctuation additionally requires an independent,
   unshared component plus a row/window continuity proof; shape plus baseline or component
   isolation alone cannot turn a slash fragment into an apostrophe/backtick.
8. Parenthesis geometry is valid only for one independently owned component with no crop-edge
   contact. A compound or edge-contact crop is never promoted to `(` or `)`; it is decomposed by
   ownership or remains `?`. This specifically protects the horse `r17c04` diagonal fixture.
9. A complete row is decoded by deterministic beam search. Unary shape/template evidence is
   combined with component continuity and neighbour transitions. A low local margin emits `?`.
   A low row margin may reject unresolved cells, but cannot erase a proven geometry anchor.
10. Output is an immutable machine candidate. No renderer is run until unknown, low-confidence,
   structural-conflict, and forced-blank-conflict gates are all zero and an operator has reviewed
   the contact sheet.
11. Raster parity remains a separate diagnostic. The decoder never copies source pixels into a
    rerender, and an unknown source font cannot reject a structurally correct TXT.

## Current evidence

Attempts 032–036 are retained failures during the migration from the independent-cell path.
Attempt 046 (`attempts/046-recognition-topology-consensus/`) reached the structural counts but is
now rejected as an evidence-binding failure: its row/cell evidence says the first row is 37
columns beginning with three blanks, while its TXT has an extra leading `S` and 39 columns. It is
frozen and cannot be repaired in place.

Attempt 052 (`attempts/052-row-joint-bound-output/`) was the fresh candidate after the binding gate:
814 cells, 22 rows of exactly 37 columns, matching transcript hashes, and 0/0/0 machine counts.
The subsequent exact-shape audit found two coarse-topology aliases in that candidate, so 052 is
superseded for recognition even though it remains immutable evidence.

Attempt 054 (`attempts/054-row-joint-exact-shape-consensus/`) used exact normalized binary
silhouettes for screenshot-local consensus and correctly failed closed at 2 unknown, 2
low-confidence, 0 structural conflicts. Attempts 057 and 059 preserve the ownership repair and
the fail-closed ambiguous-fragment gate. Attempt 060 proves the component-state repair. Attempt
061 is frozen rejected evidence: its forced-blank precedence emitted periods, its
component-isolated punctuation emitted false apostrophes, and its compound `r17c04` mask emitted
`(`. The next attempt must use the ownership/context guards and record non-ASCII scope metadata;
no accepted TXT exists. Non-ASCII references are deferred to the Unicode run-decoder boundary
described in `unicode-run-decoder-design.md`, not handled by adding ASCII classifier branches.

Attempts 048–051 are separate genuine renderer probes, but they consumed the now-rejected 046 TXT
and therefore cannot validate 052, 054, 055, or 061. Attempt 056 consumes 055 with the transcript
hash/grid gate and reaches 1,392 mask-diff pixels without source pixels, so it remains a renderer
comparison diagnostic, not a TXT-contract rejection. Attempt 061 proves that the current row-joint
manifest enters the renderer and records its 4,240-pixel surrogate-face residual as pending
structural review. Exact font/renderer recovery is optional forensic work and is not an acceptance
blocker.

The next improvement must be a general scoring/ownership change tested on literal source masks,
not a rule keyed to horse row numbers or a hand-edited transcript. A new attempt must remain
immutable and must publish its unknown/low-confidence/conflict/forced-blank counts before any
comparison-renderer probe.
