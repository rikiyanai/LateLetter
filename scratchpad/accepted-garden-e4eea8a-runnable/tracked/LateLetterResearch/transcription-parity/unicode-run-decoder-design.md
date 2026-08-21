# Unicode run decoder boundary

The fixed-cell horse decoder is an ASCII reference path. It is not the authority for
non-ASCII art. Adding one classifier branch per glyph would repeat the failure seen at horse
`r17c04`: a cropped diagonal is not a character identity, and a code point is not necessarily a
terminal cell.

## Pipeline

1. **Geometry only.** Recover row bands, baselines, visual-column anchors, reading direction,
   and connected ink components. This stage never names a character or emits text.
2. **Run and grapheme recognition.** Decode a complete horizontal/vertical run against candidate
   grapheme clusters. A grapheme is the unit of evidence, not a Python code point or a fixed cell.
   Candidate records retain code points, NFC form, source span, alternatives, and confidence.
3. **Script-aware shaping.** For Arabic and other joining scripts, shape candidate runs with the
   recorded font/shaper profile and apply bidi ordering before comparing ink. For Japanese and
   Kanji, allow fullwidth, halfwidth, kana, combining marks, and partial/cropped glyph evidence;
   a partial Kanji component is not promoted to a complete ideograph without a run-level match.
   Emoji, variation selectors, ZWJ sequences, and combining sequences stay intact as one
   extended grapheme cluster.
4. **Ownership.** Assign every source component to exactly one recognized run or leave it
   unresolved. A disconnected fragment, edge contact, or cross-row continuation cannot become a
   period, quote, parenthesis, or ideograph by shape alone.
5. **Display width.** Record measured advance and declared terminal width per grapheme. Width is
   profile-specific: East Asian Wide/Fullwidth is normally two columns, halfwidth one, and
   ambiguous width requires an explicit profile. Browser proportional placement uses measured
   prefix widths; terminal placement uses the validated cell-width profile.
6. **Acceptance.** NFC, UAX #29 grapheme segmentation, UAX #9 bidi, UAX #11 width, UTS #51
   emoji data, shaper/font versions, and normalization options are hash-bound metadata. If two
   Unicode sequences remain visually indistinguishable, the candidate is `?`/rejected; the
   operator never chooses a code-point spelling from appearance alone.

## Output contract

The UTF-8 transcript preserves literal rows, leading/trailing spaces, grapheme clusters, and
line endings. Its sidecar stores, for each grapheme run:

```json
{
  "row": 3,
  "visual_start": 12.5,
  "visual_end": 28.5,
  "text": "漢字",
  "nfc": "漢字",
  "graphemes": ["漢", "字"],
  "display_width": 4,
  "direction": "ltr",
  "components": [91, 92],
  "alternatives": [],
  "confidence": 0.94,
  "status": "candidate"
}
```

The ASCII fixed-cell decoder may feed geometry and regression fixtures into this path, but it
must fail closed when a source contains non-ASCII graphemes, joining scripts, bidi controls,
combining marks, or width-ambiguous clusters. No source image is copied into a candidate
rerender, and no font residual can promote a transcript.
