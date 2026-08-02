# `a8283c5cdb63b130` attempt log

Source snapshot: `source/source.normalized.png`  
Source SHA-256: `c50bcf5ded3a0499f762762f8bec75db6ac2c9176806061a86c2a6d8317bd8d8`

## Attempt 001 — `calibration-candidate`

- Rejected before OCR. The default calibrator searched too narrowly and selected 13.5×18,
  which visibly cut through source strokes.
- No occupancy map or TXT was emitted.

## Attempt 002 — `expanded-calibration`

- Searched x=14–22 and y=28–40 and found approximately 17.95×33, but the raw legality rule
  rejected 76 boundary pixels. Later review showed all 76 were horizontal dash/underscore joins.
- Calibration-only; no OCR or TXT.

## Attempts 003–004 — `horizontal-join-aware-calibration`

- Completed duplicate join-aware calibrations after the widened search; both reproduce the
  17.95×33, zero-non-horizontal-crossing candidate. They are retained as immutable duplicate
  evidence rather than treated as separate discoveries.

## Attempt 005 — `horizontal-join-aware-calibration`

- Completed after precomputing the horizontal-join mask. The 16×19, 17.95×33 grid had zero
  non-horizontal boundary crossings and was machine-legal.
- Superseded because foreground selection recorded near-white `[254,254,254]` for black-on-white
  source ink.

## Attempt 006 — `row-joint-candidate`

- Fresh calibration plus occupancy and structural review using the attempt-005 grid.
- The occupancy map contains one unique record for every 304 cells; no transcript was emitted.

## Attempt 007 — `row-joint-decode`

- Fresh immutable decode bound to attempt 006 calibration.
- Rejected: 33 unknown, 33 low-confidence, 3 structural conflicts, 0 forced-blank conflicts.
- Transcript SHA-256: `9de7f705870aa7c64b38210871ebe020ef29906b25367fa81ea564b8eb550be0`.

## Attempt 008 — `dark-foreground-calibration`

- Fresh calibration after fixing foreground selection to prefer maximum distance from the dominant
  background. Foreground is `[0,0,0]`; grid remains 16×19 at 17.95×33.
- Occupancy and structural review completed; no transcript in this directory.

## Attempt 009 — `row-joint-decode`

- Fresh immutable decode bound to attempt 008 calibration; transcript bytes match attempt 007.
- Rejected: 33 unknown, 33 low-confidence, 3 structural conflicts, 0 forced-blank conflicts.
- No parity render and no `accepted.txt`. The candidate is pending operator visual review; it must
  not be manually edited.

## Attempt 010 — `four-row-horizontal-decode`

- Added the general four-row/full-width horizontal-band classifier to a fresh decode.
- Rejected: 7 unknown, 7 low-confidence, 3 structural conflicts, 0 forced-blank conflicts.

## Attempt 011 — `same-row-horizontal-ownership`

- Added same-row ownership logic for joined horizontal components, but the helper still excluded
  four-row bands from its ownership proof.
- Rejected: 7 unknown, 7 low-confidence, 3 structural conflicts, 0 forced-blank conflicts.

## Attempt 012 — `same-row-horizontal-ownership`

- Four-row ownership proof enabled. Rejected: 2 unknown, 2 low-confidence, 3 structural
  conflicts, 0 forced-blank conflicts.

## Attempt 013 — `clipped-component-ownership`

- Corrected global component IDs for cells clipped at negative image coordinates. Rejected:
  0 unknown, 0 low-confidence, 3 structural conflicts, 0 forced-blank conflicts.

## Attempt 014 — `exact-silhouette-conflict-gate`

- Replaced coarse width/height/ink conflict grouping with exact normalized silhouettes. Rejected:
  0 unknown, 0 low-confidence, 1 structural conflict, 0 forced-blank conflicts.

## Attempt 015 — `final-structural-candidate`

- Dash/underscore conflicts are separated by baseline-relative band while exact silhouette
  consensus remains position-independent for other glyphs.
- Machine gate: **zero unknown, zero low-confidence, zero structural, zero forced-blank** across
  304 cells (16×19). Transcript SHA-256:
  `bcbf1901d86a9bd55a4861f8ff973b1315f3d7ae28f58e43536c7d0e005e4012`.
- Operator then approved the source/TXT structure. `accepted.txt` was copied byte-for-byte and
  `acceptance-receipt.json` records the source, candidate, calibration, occupancy-review hashes,
  and zero-count gate.
- Status: **VERIFIED REFERENCE TRANSCRIPTION**. Raster parity was not run and is disclosed as
  not run; the generated attempt remains immutable.
