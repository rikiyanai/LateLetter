/**
 * Conformance tests for the proportional presentation geometry module.
 *
 * WHAT THESE TESTS ARE GUARDING
 * -----------------------------
 * The Garden is moving from a monospace cell grid to proportional measured
 * layout. The danger in that move is subtle: it is very easy to write a
 * proportional renderer in which an object's position accumulates from the
 * widths of the text drawn before it. Such a renderer looks correct on the
 * first screenshot and is wrong forever after, because any change to any
 * artwork silently shifts unrelated objects sideways.
 *
 * The central test here is therefore `anchor is independent of other objects'
 * content`. If that test ever fails, world placement has stopped being a
 * property of the world.
 *
 * WHY THE MEASURER IS FAKE
 * ------------------------
 * Real text measurement needs a canvas. Under Node there is no canvas, and
 * PreText's `getMeasureContext()` throws outright rather than degrading. More
 * importantly, real font metrics vary by platform and font version, so tests
 * built on them could not assert exact pixel values.
 *
 * So these tests inject a deterministic synthetic measurer with a hand-written
 * width table. It is genuinely proportional -- 'i' is 3px, 'M' is 11px, a CJK
 * ideograph is 16px -- which is what makes the tests meaningful. A monospace
 * fake would pass even against a buggy grid-based implementation.
 *
 * The art used is synthetic two-row art, deliberately NOT the browser's existing
 * hard-coded art tables. Those tables are slated for deletion once art ownership
 * moves into the versioned atlas, and a test coupled to them would have to be
 * rewritten at exactly the moment it is most needed.
 */

import assert from 'node:assert/strict';
import test from 'node:test';

import {
  createGeometry,
  createPreTextMeasurer,
  toGraphemes,
  LATTICE_REFERENCE_TEXT,
  MINIMUM_TARGET_PX,
} from '../../web/garden-geometry.mjs';

/**
 * Per-code-point advance widths for the synthetic font.
 *
 * Chosen to be proportional and mutually distinct so that a wrong index shows up
 * as a wrong number rather than an accidental match. Combining marks are zero
 * width, exactly as they are in a real font -- they draw on top of the character
 * before them and advance the pen not at all.
 */
const SYNTHETIC_WIDTHS = new Map(Object.entries({
  i: 3,
  l: 3,
  ' ': 4,
  a: 7,
  e: 7,
  o: 7,
  n: 8,
  M: 11,
  W: 12,
  '_': 9,
  '=': 10,
  '/': 6,
  '\\': 6,
}));

/** Width of a single code point in the synthetic font. */
function codePointWidth(codePoint) {
  // Combining Diacritical Marks, U+0300..U+036F. Zero advance by definition.
  const value = codePoint.codePointAt(0);
  if (value >= 0x0300 && value <= 0x036f) return 0;
  // CJK Unified Ideographs and Hiragana/Katakana. Wide, as in any real font.
  if ((value >= 0x3040 && value <= 0x30ff) || (value >= 0x4e00 && value <= 0x9fff)) return 16;
  return SYNTHETIC_WIDTHS.get(codePoint) ?? 7;
}

/** Width of a whole string: the sum of its code points' advances. */
function syntheticAdvance(text) {
  let total = 0;
  for (const codePoint of text) total += codePointWidth(codePoint);
  return total;
}

/**
 * Build a synthetic measurer, optionally one that reports its font as unready.
 *
 * @param {object} [options]
 * @param {boolean} [options.ready=true] - What `ensureFont` reports.
 * @param {number} [options.fontSize=15]
 * @returns {object} A measurer plus a `calls` counter for cache assertions.
 */
function createSyntheticMeasurer(options = {}) {
  const { ready = true, fontSize = 15 } = options;
  const calls = { prefixWidths: 0, advance: 0, ensureFont: 0, clearCaches: 0 };

  return {
    calls,
    ensureFont(font) {
      calls.ensureFont += 1;
      return { ready, font };
    },
    advance(text) {
      calls.advance += 1;
      return syntheticAdvance(text);
    },
    prefixWidths(text) {
      calls.prefixWidths += 1;
      // Cumulative width through each grapheme -- the same contract the real
      // adapter normalises PreText's output into.
      const out = [];
      let running = 0;
      for (const grapheme of toGraphemes(text)) {
        running += syntheticAdvance(grapheme);
        out.push(running);
      }
      return out;
    },
    fontSize() {
      return fontSize;
    },
    clearCaches() {
      calls.clearCaches += 1;
    },
  };
}

/** A geometry over the synthetic font, with sensible defaults for tests. */
function makeGeometry(overrides = {}) {
  return createGeometry({
    measurer: createSyntheticMeasurer(),
    font: '15px "Test Proportional"',
    ...overrides,
  });
}

// ---------------------------------------------------------------------------
// Case 4: font readiness before first measurement
// ---------------------------------------------------------------------------

test('geometry refuses to construct before the font is ready', () => {
  // Measuring against a fallback font and caching the result is an invisible
  // failure: the art still paints, just misaligned. Failing loudly is the whole
  // point of this gate.
  assert.throws(
    () => createGeometry({
      measurer: createSyntheticMeasurer({ ready: false }),
      font: '15px "Not Loaded Yet"',
    }),
    /font is not ready for measurement/,
  );
});

test('geometry derives its lattice from the reference probe, not from content', () => {
  const measurer = createSyntheticMeasurer();
  const geometry = createGeometry({ measurer, font: '15px "Test Proportional"' });

  // 'M' is 11px in the synthetic font, and the reference probe is 'M'.
  assert.equal(geometry.cellAdvance, syntheticAdvance(LATTICE_REFERENCE_TEXT));
  assert.equal(geometry.cellAdvance, 11);
  // Line height defaults to the font size at a 1.0 ratio, keeping box-drawing
  // rows in vertical contact.
  assert.equal(geometry.lineHeight, 15);
});

// ---------------------------------------------------------------------------
// Case 6: an object's anchor does not move when another object's text changes
// ---------------------------------------------------------------------------

test('anchor is independent of other objects content', () => {
  const geometry = makeGeometry();

  // Two objects on the same world row, one to the left of the other.
  const leftAnchor = geometry.worldToPixel(2, 3);
  const rightAnchorBefore = geometry.worldToPixel(9, 3);

  // The left object draws something extremely narrow.
  geometry.measureAsset(['i', 'l']);
  const rightAnchorAfterNarrow = geometry.worldToPixel(9, 3);

  // Now it draws something enormously wider -- wide CJK, many glyphs.
  geometry.measureAsset(['WWWWWWWWWWWW', '木木木木木']);
  const rightAnchorAfterWide = geometry.worldToPixel(9, 3);

  // THE INVARIANT. The right-hand object has not moved by a single pixel,
  // because its position is `originX + 9 * cellAdvance` and nothing about the
  // left object appears in that expression.
  assert.deepEqual(rightAnchorAfterNarrow, rightAnchorBefore);
  assert.deepEqual(rightAnchorAfterWide, rightAnchorBefore);
  // The left object has not moved either.
  assert.deepEqual(geometry.worldToPixel(2, 3), leftAnchor);
  // And the transform really is the affine one we claimed.
  assert.deepEqual(rightAnchorBefore, { x: 9 * 11, y: 3 * 15 });
});

test('world to pixel is affine and exactly invertible', () => {
  const geometry = makeGeometry({ originX: 40, originY: 12 });

  const pixel = geometry.worldToPixel(5, 4);
  assert.deepEqual(pixel, { x: 40 + 5 * 11, y: 12 + 4 * 15 });

  // Round-tripping returns the original integer coordinates.
  const world = geometry.pixelToWorld(pixel.x, pixel.y);
  assert.equal(world.x, 5);
  assert.equal(world.y, 4);
});

// ---------------------------------------------------------------------------
// Case 1: mixed narrow/wide Latin and CJK glyphs
// ---------------------------------------------------------------------------

test('measures mixed narrow, wide and CJK glyphs proportionally', () => {
  const geometry = makeGeometry();
  // 'i' 3, 'M' 11, ideograph 16, 'i' 3.
  const row = geometry.measureRow('iM木i');

  assert.deepEqual(row.graphemes, ['i', 'M', '木', 'i']);
  assert.deepEqual(row.prefix, [3, 14, 30, 33]);
  assert.equal(row.width, 33);

  // A grid-based implementation would report all four glyphs as equal width.
  // Asserting they differ is what makes this test catch that mistake.
  assert.notEqual(row.prefix[0], row.prefix[1] - row.prefix[0]);
});

// ---------------------------------------------------------------------------
// Case 2: combining / grapheme sequences
// ---------------------------------------------------------------------------

test('treats a base character plus combining mark as one grapheme', () => {
  const geometry = makeGeometry();
  // 'e' followed by U+0301 COMBINING ACUTE ACCENT: two code points, one
  // user-perceived character, drawn in one place.
  const row = geometry.measureRow('éa');

  assert.equal(row.graphemes.length, 2, 'combining mark must not be its own grapheme');
  assert.deepEqual(row.graphemes, ['é', 'a']);
  // The accent adds no advance, so the accented e is the same width as a bare e.
  assert.deepEqual(row.prefix, [7, 14]);

  // A click anywhere on the accented e selects the whole grapheme, never the
  // accent alone.
  assert.equal(geometry.graphemeAtOffset(row, 0), 0);
  assert.equal(geometry.graphemeAtOffset(row, 6.9), 0);
  assert.equal(geometry.graphemeAtOffset(row, 7), 1);
});

// ---------------------------------------------------------------------------
// Case 3: leading and internal spaces
// ---------------------------------------------------------------------------

test('preserves leading and internal spaces as measurable graphemes', () => {
  const geometry = makeGeometry();
  // Leading whitespace is load-bearing in ASCII art -- it is how a picture is
  // indented into position. Anything that trims it destroys the drawing.
  const row = geometry.measureRow('  i M');

  assert.deepEqual(row.graphemes, [' ', ' ', 'i', ' ', 'M']);
  assert.deepEqual(row.prefix, [4, 8, 11, 15, 26]);
  assert.equal(row.width, 26);
  // The first glyph of visible ink starts 8px in, not at zero.
  assert.equal(geometry.offsetOfGrapheme(row, 2), 8);
});

test('an empty row measures as zero width without crashing', () => {
  const geometry = makeGeometry();
  const row = geometry.measureRow('');
  assert.deepEqual(row.graphemes, []);
  assert.deepEqual(row.prefix, []);
  assert.equal(row.width, 0);
  // No grapheme can be under a pointer in an empty row.
  assert.equal(geometry.graphemeAtOffset(row, 0), -1);
});

// ---------------------------------------------------------------------------
// Case 7: forward and inverse asset-local measurements agree at boundaries
// ---------------------------------------------------------------------------

test('forward and inverse measurement agree at every grapheme boundary', () => {
  const geometry = makeGeometry();
  const row = geometry.measureRow(' iM木éW_');

  for (let index = 0; index < row.graphemes.length; index += 1) {
    const leftEdge = geometry.offsetOfGrapheme(row, index);
    // Landing exactly on a grapheme's left edge must select that grapheme, not
    // the one before it. Off-by-one here would make selection feel sticky.
    assert.equal(
      geometry.graphemeAtOffset(row, leftEdge), index,
      `left edge of grapheme ${index} must resolve back to ${index}`,
    );
    // One pixel short of the left edge belongs to the previous grapheme.
    if (index > 0) {
      assert.equal(geometry.graphemeAtOffset(row, leftEdge - 0.5), index - 1);
    }
  }

  // The position just past the last glyph is inside no grapheme at all.
  const end = geometry.offsetOfGrapheme(row, row.graphemes.length);
  assert.equal(end, row.width);
  assert.equal(geometry.graphemeAtOffset(row, end), -1);
  // So is anything to the left of the row.
  assert.equal(geometry.graphemeAtOffset(row, -1), -1);
});

test('binary search stays exact for a long row', () => {
  const geometry = makeGeometry();
  // Long enough that a linear scan and a binary search would visit different
  // elements, so an incorrect midpoint or bound shows up as a wrong answer.
  const row = geometry.measureRow('iMa 木Wl_iMa 木Wl_iMa 木Wl_');

  for (let index = 0; index < row.graphemes.length; index += 1) {
    const left = geometry.offsetOfGrapheme(row, index);
    const right = row.prefix[index];
    // Sample the middle of each glyph; it must resolve to that glyph.
    assert.equal(geometry.graphemeAtOffset(row, (left + right) / 2), index);
  }
});

// ---------------------------------------------------------------------------
// Asset measurement: rows are strings, and overhang is legal
// ---------------------------------------------------------------------------

test('measures a two-row asset and reports its widest row', () => {
  const geometry = makeGeometry();
  const asset = geometry.measureAsset([
    ' MM ',   // 4 + 11 + 11 + 4 = 30
    '======', // 6 * 10 = 60
  ]);

  assert.equal(asset.rows.length, 2);
  assert.equal(asset.rows[0].width, 30);
  assert.equal(asset.rows[1].width, 60);
  assert.equal(asset.width, 60, 'asset width is the widest row');
  assert.equal(asset.height, 2 * 15, 'rows stay discrete at uniform line height');
});

test('art may overhang its declared footprint without changing its hotspot', () => {
  const geometry = makeGeometry();

  // A one-cell object whose picture is far wider than one cell: 11px of
  // footprint, 60px of ink. This is legal and common -- a canopy spills past
  // the trunk's cell.
  const hotspot = { x: 4, y: 2, width: 1, height: 1 };
  const rect = geometry.hotspotToRect(hotspot);
  const asset = geometry.measureAsset(['==========']);

  assert.equal(rect.width, 11, 'hotspot follows the declared cell footprint');
  assert.ok(asset.width > rect.width, 'the picture genuinely overhangs');
  // The hotspot is unchanged by the presence of wide art, because
  // `hotspotToRect` performs no measurement at all.
  assert.deepEqual(geometry.hotspotToRect(hotspot), rect);
});

// ---------------------------------------------------------------------------
// Case 8: expanded targets still dispatch the exact canonical object id
// ---------------------------------------------------------------------------

test('expands a small target to the accessible minimum about its own centre', () => {
  const geometry = makeGeometry();
  const rect = geometry.hotspotToRect({ x: 0, y: 0, width: 1, height: 1 });
  const target = geometry.expandTarget(rect);

  assert.equal(target.width, MINIMUM_TARGET_PX);
  assert.equal(target.height, MINIMUM_TARGET_PX);
  // Centres coincide: the target grew, it did not slide.
  assert.equal(target.x + target.width / 2, rect.x + rect.width / 2);
  assert.equal(target.y + target.height / 2, rect.y + rect.height / 2);
});

test('a target already large enough is left alone', () => {
  const geometry = makeGeometry();
  // 6 cells wide (66px) and 4 rows tall (60px), both over the 44px floor.
  const rect = geometry.hotspotToRect({ x: 1, y: 1, width: 6, height: 4 });
  assert.deepEqual(geometry.expandTarget(rect), rect);
});

test('a tap inside the expanded target dispatches the exact canonical id', () => {
  const geometry = makeGeometry();
  const objects = [
    { object_id: 'plant.oak.01', hotspot: { x: 10, y: 10, width: 1, height: 1 } },
  ];

  const rect = geometry.hotspotToRect(objects[0].hotspot);
  const centreX = rect.x + rect.width / 2;
  const centreY = rect.y + rect.height / 2;

  // Dead centre obviously hits.
  assert.equal(geometry.hitTest(objects, centreX, centreY), 'plant.oak.01');

  // 20px to the left: outside the 11px-wide hotspot, inside the 44px target.
  // A fingertip that missed by this much still opens the right object.
  const nearMiss = centreX - 20;
  assert.ok(nearMiss < rect.x, 'the sample point is genuinely outside the hotspot');
  assert.equal(geometry.hitTest(objects, nearMiss, centreY), 'plant.oak.01');

  // 40px away is outside even the expanded target, and must hit nothing.
  assert.equal(geometry.hitTest(objects, centreX - 40, centreY), null);
});

test('an exact hotspot hit always beats a neighbours expanded target', () => {
  const geometry = makeGeometry();
  // Two adjacent one-cell objects, 11px apart. Their 44px expanded targets
  // overlap heavily, so this is the case where expansion could steal a click.
  const objects = [
    { object_id: 'fixture.bench', hotspot: { x: 5, y: 5, width: 1, height: 1 } },
    { object_id: 'fixture.lantern', hotspot: { x: 6, y: 5, width: 1, height: 1 } },
  ];

  const lantern = geometry.hotspotToRect(objects[1].hotspot);
  // A point genuinely inside the lantern's real hotspot.
  const insideLantern = lantern.x + 1;
  const midRow = lantern.y + lantern.height / 2;

  // The bench's expanded target also covers this point, but the lantern owns it
  // outright because the unexpanded hotspot contains it.
  const benchTarget = geometry.expandTarget(geometry.hotspotToRect(objects[0].hotspot));
  assert.ok(
    insideLantern >= benchTarget.x && insideLantern < benchTarget.x + benchTarget.width,
    'the bench target really does overlap this point',
  );
  assert.equal(geometry.hitTest(objects, insideLantern, midRow), 'fixture.lantern');
});

test('overlapping expanded targets resolve to the nearest centre, deterministically', () => {
  const geometry = makeGeometry();
  const objects = [
    { object_id: 'a.near', hotspot: { x: 10, y: 4, width: 1, height: 1 } },
    { object_id: 'b.far', hotspot: { x: 13, y: 4, width: 1, height: 1 } },
  ];

  const near = geometry.hotspotToRect(objects[0].hotspot);
  // Sit just outside `a.near` on the side away from `b.far`, so both expanded
  // targets may reach but `a.near`'s centre is closer.
  const px = near.x - 6;
  const py = near.y + near.height / 2;

  const winner = geometry.hitTest(objects, px, py);
  assert.equal(winner, 'a.near');
  // Order of the projection list must not change the answer.
  assert.equal(geometry.hitTest([...objects].reverse(), px, py), winner);
});

test('hit testing rejects malformed projection objects loudly', () => {
  const geometry = makeGeometry();
  assert.throws(
    () => geometry.hitTest([{ hotspot: { x: 0, y: 0, width: 1, height: 1 } }], 0, 0),
    /lacks a string object_id/,
  );
  assert.throws(
    () => geometry.hitTest([{ object_id: 'x', hotspot: { x: 0, y: 0 } }], 0, 0),
    /hotspot must have finite/,
  );
});

// ---------------------------------------------------------------------------
// Case 5: cache behaviour across font load, resize and zoom
// ---------------------------------------------------------------------------

test('row measurement is memoised within one geometry', () => {
  const measurer = createSyntheticMeasurer();
  const geometry = createGeometry({ measurer, font: '15px "Test Proportional"' });

  geometry.measureRow('iMa');
  const afterFirst = measurer.calls.prefixWidths;
  geometry.measureRow('iMa');
  geometry.measureAsset(['iMa', 'iMa']);

  assert.equal(measurer.calls.prefixWidths, afterFirst, 'repeat rows must not re-measure');
  assert.equal(geometry.cachedRowCount(), 1);
});

test('zoom produces a new geometry with its own scaled measurements', () => {
  const measurer = createSyntheticMeasurer();
  const base = createGeometry({ measurer, font: '15px "Test Proportional"' });
  const zoomed = createGeometry({ measurer, font: '15px "Test Proportional"', scale: 2 });

  // Lattice and measured art scale together. If only one of them scaled, art
  // would drift out of alignment with placement as the player zoomed.
  assert.equal(zoomed.cellAdvance, base.cellAdvance * 2);
  assert.equal(zoomed.lineHeight, base.lineHeight * 2);
  assert.equal(zoomed.measureRow('iM').width, base.measureRow('iM').width * 2);

  // Caches cannot leak between them, because each geometry owns its own.
  assert.equal(zoomed.worldToPixel(3, 1).x, base.worldToPixel(3, 1).x * 2);
});

test('a resize or font swap is expressed as a fresh geometry, not a mutated one', () => {
  const measurer = createSyntheticMeasurer();
  const before = createGeometry({ measurer, font: '15px "Test Proportional"' });
  before.measureRow('iMa');
  assert.equal(before.cachedRowCount(), 1);

  // The font changed. Construct anew rather than invalidating in place: a
  // geometry's cache is only valid under the font and scale it was built with,
  // so tying their lifetimes together removes a whole class of stale-cache bug.
  const after = createGeometry({
    measurer,
    font: '30px "Test Proportional"',
    cellAdvance: 22,
    lineHeight: 30,
  });
  assert.equal(after.cachedRowCount(), 0, 'a new geometry starts with an empty cache');
  assert.equal(after.cellAdvance, 22);
  assert.equal(before.cellAdvance, 11, 'the old geometry is untouched');
});

test('lattice spacing must be positive', () => {
  assert.throws(
    () => makeGeometry({ cellAdvance: 0 }),
    /lattice spacing must be positive/,
  );
  assert.throws(
    () => makeGeometry({ lineHeight: Number.NaN }),
    /lattice spacing must be positive/,
  );
});

// ---------------------------------------------------------------------------
// The PreText adapter's null normalisation
// ---------------------------------------------------------------------------

test('the PreText adapter normalises the null prefix-width return', () => {
  // PreText returns `null` rather than an array whenever a segment holds one
  // grapheme or fewer (measurement.js:161). Single-glyph rows are everywhere in
  // ASCII art, so an un-normalised caller would crash immediately. This fakes
  // the PreText namespace to reproduce that exact return and proves the adapter
  // converts it to the uniform array contract.
  const fakePreText = {
    getFontMeasurementState: () => ({ cache: new Map(), fontSize: 15, emojiCorrection: 0 }),
    getSegmentMetrics: (segment) => ({ width: syntheticAdvance(segment) }),
    getCorrectedSegmentWidth: (segment, metrics) => metrics.width,
    getSegmentGraphemePrefixWidths: (segment) => {
      const graphemes = toGraphemes(segment);
      if (graphemes.length <= 1) return null; // PreText's optimisation
      let running = 0;
      return graphemes.map((grapheme) => (running += syntheticAdvance(grapheme)));
    },
    clearMeasurementCaches: () => {},
  };

  const measurer = createPreTextMeasurer(fakePreText, { isFontReady: () => true });
  measurer.ensureFont('15px "Test Proportional"');

  // The case that would otherwise return null.
  assert.deepEqual(measurer.prefixWidths('M'), [11]);
  // Empty input is an empty array, not null and not [0].
  assert.deepEqual(measurer.prefixWidths(''), []);
  // Multi-grapheme input passes through unchanged.
  assert.deepEqual(measurer.prefixWidths('iM'), [3, 14]);

  // And the whole geometry works end to end on top of it, including the
  // single-glyph row that would have crashed.
  const geometry = createGeometry({ measurer, font: '15px "Test Proportional"' });
  const asset = geometry.measureAsset(['M', 'iM']);
  assert.equal(asset.rows[0].width, 11);
  assert.equal(asset.rows[1].width, 14);
});

test('the PreText adapter refuses to measure before its font is ready', () => {
  const measurer = createPreTextMeasurer({}, { isFontReady: () => false });
  const state = measurer.ensureFont('15px "Never Loads"');
  assert.equal(state.ready, false);
  // Measuring anyway is a programming error, not a silent fallback.
  assert.throws(() => measurer.advance('M'), /ensureFont\(\) must succeed/);
  assert.throws(() => measurer.prefixWidths('M'), /ensureFont\(\) must succeed/);
});

// ---------------------------------------------------------------------------
// Affine-only construction
// ---------------------------------------------------------------------------
//
// The renderer's hit testing needs the world-to-pixel transform and nothing
// else: hit identity comes from canonical hotspot rectangles, which are
// integers converted by units alone. Requiring a measurer there would ask a
// caller to supply a dependency that provably cannot affect the answer -- and
// under Node, where PreText's canvas lookup throws, it could not supply a real
// one at all.

test('supplying both lattice constants makes the measurer unnecessary', () => {
  const geometry = createGeometry({ cellAdvance: 8, lineHeight: 15 });

  assert.equal(geometry.affineOnly, true);
  assert.equal(geometry.cellAdvance, 8);
  assert.equal(geometry.lineHeight, 15);

  // The affine half is fully functional, which is the entire point.
  assert.deepEqual(geometry.worldToPixel(3, 2), { x: 24, y: 30 });
  assert.deepEqual(
    geometry.hotspotToRect({ x: 3, y: 2, width: 2, height: 1 }),
    { x: 24, y: 30, width: 16, height: 15 },
  );
  assert.equal(geometry.expandTarget({ x: 24, y: 30, width: 16, height: 15 }).width, 44);
});

test('an affine-only geometry refuses to measure rather than guessing', () => {
  const geometry = createGeometry({ cellAdvance: 8, lineHeight: 15 });

  // A plausible fallback would be worse than a throw. Almost-right glyph
  // placement is the hardest rendering fault to notice or attribute, which is
  // the same reason the font readiness gate is a hard precondition.
  assert.throws(() => geometry.measureRow('M'), /needs a measurer/);
  assert.throws(() => geometry.measureAsset(['M']), /needs a measurer/);
});

test('a geometry built with a measurer is not affine-only', () => {
  const geometry = createGeometry({
    measurer: createSyntheticMeasurer(), font: '15px "Test Proportional"',
  });
  assert.equal(geometry.affineOnly, false);
  // And it still measures, so the flag is not merely cosmetic.
  assert.equal(geometry.measureRow('M').width, 11);
});

test('a missing measurer is only forgiven when both constants are given', () => {
  // One constant is not enough: the other would have to be measured, and there
  // is nothing to measure it with.
  assert.throws(() => createGeometry({ cellAdvance: 8 }), /must be injected/);
  assert.throws(() => createGeometry({ lineHeight: 15 }), /must be injected/);
  assert.throws(() => createGeometry({}), /must be injected/);
  // A non-positive constant is not a constant.
  assert.throws(() => createGeometry({ cellAdvance: 0, lineHeight: 15 }), /must be injected/);
});
