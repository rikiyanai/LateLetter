# sitting-cat attempt log

Source: `source/source.normalized.png`
Source SHA-256: `e9b08e31960ffd6fe6e5e52e84107fd22ad80b645b6f1de2e21f4e9a20444275`
Reference: queued Japanese/cat reference; no provisional TXT was used.

## 001-calibrate — rejected calibration evidence

The inherited 13.55px calibration is preserved unchanged. Its manifest records 39 boundary-ink
pixels and `rejected_boundary_crossings`; the overlay visibly cuts the Japanese and cat strokes.
It is not an input to later attempts.

## 002-current-raster-japanese — rejected invalid-geometry/proposal attempt

The raster geometry owner falsely promoted four blank-gap groups to a fixed lattice. The largest
group spans 109 source pixels and contains multiple substantive drawing rows; periodic baselines
were not recovered. Geometry therefore failed before recognition, even though the invalid
candidate produced recognition-input hash
`a4e907b307fb116a0f60bbe414fa8b14b764353fd0c322d3ecb8fa80ffd62893`. Tesseract received all
four strips through separate `psm7-eng`, `psm13-eng`, `psm7-jpn-cjk`, and `psm7-ara` profiles.
The Japanese profile produced the machine candidate in `candidate.txt`:

```text
本
リッ ブラ
未 二
六 - ニ
```

This is visibly not a transcription of the cat drawing. The attempt is rejected with
`exact_nfc_target_unavailable`, `recognizer_coverage_not_proven`, and `operator_review_pending`.
No renderer, accepted TXT, or operator acceptance was created. The candidate is retained only as
machine proposal evidence and is not evidence that geometry or recognition succeeded.

## 003-fail-closed-proposal-only — rejected cleanly

Attempt 002 exposed a writer-contract defect: the proposal-only helper copied the first Japanese
Tesseract proposal into `candidate.txt`. That file is frozen as rejected evidence; it is not an
accepted or reviewed transcript.

Attempt 003 reran the same flawed geometry evidence and proposal ensemble in a fresh, immutable
directory. It records `proposal-report.json`, but deliberately emits **no** `candidate.txt`,
renderer artifacts, or `accepted.txt`. The manifest is `rejected_proposal_only`; it must not be
read as a geometry pass. The reference remains blocked by `row_baselines_undersegmented` before
the Japanese whole-run recognizer can be trusted.

## Read-only successor diagnostics after 003 — no attempt created

Later source-only geometry work recovered nine row strips and retained the 23px row pitch with a
13.65px mixed-width display basis. The live structural proposal owner was replaced with a
one-to-many-unit run-level span lattice, and its leading logical blanks are now bound to measured
source columns. A bounded replay can therefore align all nine generated strings to the recovered
runs.

That is not transcription success. Only row 0 (`___`) visually matches the screenshot. The other
selected strings contain wrong ASCII/Japanese glyph identities, punctuation, and compound lower-row
structures. At least one complete lower-row witness (`ミ＿xノ`) is now present in proposal evidence
but loses ranking; exact complete-row proposal coverage for the other failed rows has not been
proved. The current failure is therefore split explicitly into:

- **proposal coverage:** whether the correct complete logical row exists in any adapter's output;
- **proposal ranking:** whether a present correct row loses to a source-incompatible alternative;
- **authority:** geometry remains proposal-alignment-only until pitch, phase, ownership, and winner
  margin proofs all pass.

No read-only replay wrote a manifest, candidate, renderer artifact, or acceptance receipt. Attempt
004 remains uncreated. The hand-tuned evaluation candidates under `evaluation/` are runtime-ineligible
and rejected benchmark-label evidence; sitting-cat evaluation truth is unavailable until an
authoritative original TXT or renderer-generated labeled fixture exists.

### Operator verdict on the bounded replay — rejected

The operator performed direct side-by-side source/generated review and explicitly rejected the
machine replay. The disagreement is structural, not font-only: the head/face glyph identities are
wrong, the middle rows lose or substitute bars, diagonals, horizontals, and spaces, and the lower
body contains unrelated bracket/bar/kana/punctuation sequences. All nine rows fitting measured run
widths does not establish visual parity.

This rejects the replay only. It does not create or mutate attempt 004, and it does not decide the
separate evaluation transcript candidate. Machine candidate emission remains blocked at proposal
coverage and ranking.
