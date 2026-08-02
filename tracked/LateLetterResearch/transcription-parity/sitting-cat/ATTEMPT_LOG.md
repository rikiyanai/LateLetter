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
