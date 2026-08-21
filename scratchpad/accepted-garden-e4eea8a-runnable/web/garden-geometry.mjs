/**
 * Proportional presentation geometry for the Garden.
 *
 * WHAT THIS FILE IS FOR
 * ---------------------
 * The Garden's world model places every object on an integer lattice: an object
 * sits at world cell (3, 7), occupies a 2x1 footprint, and owns a hotspot
 * rectangle measured in those same integer cells. That is the canonical truth,
 * and nothing in this file changes it.
 *
 * What this file does is convert that integer truth into device pixels so a
 * browser can paint it with a PROPORTIONAL font -- a font where 'i' is narrow
 * and 'M' is wide -- instead of the monospace grid the renderer currently
 * assumes. Proportional fonts are required because the ASCII/Shift_JIS art
 * tradition the Garden draws from aligns strokes at sub-character precision,
 * which a uniform-width grid physically cannot express.
 *
 * THE ONE INVARIANT THAT MATTERS MOST
 * -----------------------------------
 * An object's position on screen is computed from its world coordinates and the
 * font's lattice constants, and from NOTHING ELSE. In particular it is never
 * computed by adding up the widths of glyphs drawn before it.
 *
 * Why this matters: if position accumulated from measured text, then widening a
 * single glyph inside one object -- say a plant grows a wider leaf -- would
 * shove every object to its right sideways. Placement would stop being a
 * property of the world and start being a side effect of drawing. Objects would
 * drift, collision would disagree with what the player sees, and the same seed
 * would produce different-looking gardens on different fonts.
 *
 * So the transform here is AFFINE: pixel_x = originX + worldX * cellAdvance.
 * That is a multiply and an add. It cannot depend on content because content
 * does not appear in the formula.
 *
 * Proportional measurement is used only INSIDE an asset, to lay out that
 * asset's own rows of text relative to that asset's own anchor. It is
 * "asset-local". One asset's glyphs can never move another asset.
 *
 * WHO OWNS A CLICK
 * ----------------
 * Canonical hotspot rectangles own hit identity. When the player taps the
 * screen, this module converts each object's integer hotspot into a pixel
 * rectangle and asks which rectangle was hit. It does NOT ask which glyph was
 * under the finger.
 *
 * The distinction is not pedantic. Art is allowed to overhang its declared
 * footprint -- a tree's canopy may visually spill past the cells it occupies.
 * If visible ink decided what you clicked, then redrawing a picture would
 * silently change the game's affordances, and an artist could invent an action
 * target by accident. Measured glyph extents are therefore used only for
 * painting, hover highlighting, and diagnostics.
 *
 * WHAT THIS FILE DELIBERATELY DOES NOT DO
 * ---------------------------------------
 * It does not import PreText's measurement module. That module calls
 * `getMeasureContext()`, which throws outright when there is no OffscreenCanvas
 * and no DOM -- which is to say, under Node, which is where the tests run. A
 * direct import would make this logic untestable. Instead the measurement
 * capability is INJECTED as a `measurer` object. The browser injects a PreText
 * adapter; tests inject a deterministic synthetic one. The geometry itself is
 * pure and provable either way.
 */

/**
 * The minimum size, in CSS pixels, of anything a person is expected to tap.
 *
 * This is WCAG 2.2 Success Criterion 2.5.8 ("Target Size (Minimum)"). A single
 * world cell rendered at a readable font size is roughly 8px wide, which is far
 * below what a fingertip can reliably hit, so small targets are grown to this
 * size before hit testing. Growing a target changes only how forgiving it is;
 * it never changes which object the target belongs to.
 */
export const MINIMUM_TARGET_PX = 44;

/**
 * The fixed probe string used to derive lattice spacing from a font.
 *
 * A capital M is the traditional choice because in most fonts it is the widest
 * ordinary Latin letter, so a lattice built from it leaves room for typical
 * text. The specific character barely matters. What matters is that it is a
 * CONSTANT: the lattice must be a property of the font alone, so that every
 * object is spaced identically regardless of what any object happens to draw.
 * Measuring the lattice from real content would reintroduce exactly the
 * content-dependent drift this module exists to prevent.
 */
export const LATTICE_REFERENCE_TEXT = 'M';

/**
 * Vertical spacing as a multiple of the font's size in pixels.
 *
 * ASCII art assumes uniform leading -- every row is the same height, because
 * the art was drawn on a terminal where that was guaranteed. So rows stay
 * discrete even though columns become continuous. 1.0 means one line of art
 * occupies exactly the font's nominal size with no extra gap, which keeps
 * box-drawing characters in vertically adjacent rows visually connected.
 */
export const DEFAULT_LINE_HEIGHT_RATIO = 1.0;

/**
 * Split a string into user-perceived characters ("graphemes").
 *
 * A grapheme is what a reader would call "one character", which is not the same
 * as one code unit or even one code point. The letter e followed by a combining
 * acute accent is two code points but one grapheme -- and crucially, it is drawn
 * in one position and should be selected as one unit. Naive indexing by code
 * unit would let a click land "between" a letter and its own accent.
 *
 * `Intl.Segmenter` implements the Unicode text-segmentation rules for this and
 * is available in every browser the Garden supports, as well as in Node.
 *
 * @param {string} text - Any string, possibly empty.
 * @returns {string[]} The graphemes in order; empty array for empty input.
 */
export function toGraphemes(text) {
  // A fresh Segmenter per call would be wasteful, but a module-level one is
  // created lazily below and reused; see `graphemeSegmenter`.
  const segmenter = getGraphemeSegmenter();
  const out = [];
  for (const piece of segmenter.segment(text)) out.push(piece.segment);
  return out;
}

// Lazily constructed because building a Segmenter loads ICU segmentation data,
// which is measurable work we should not do at import time in case a caller
// only ever needs the affine transform.
let graphemeSegmenter = null;
function getGraphemeSegmenter() {
  if (graphemeSegmenter === null) {
    graphemeSegmenter = new Intl.Segmenter(undefined, { granularity: 'grapheme' });
  }
  return graphemeSegmenter;
}

/**
 * Wrap PreText's measurement module as an injectable measurer.
 *
 * This is the ONLY place that knows PreText exists, and it is only ever called
 * in a browser. It is written as a factory taking the already-imported PreText
 * namespace rather than importing it itself, so that importing this file under
 * Node -- where PreText's canvas lookup would throw -- stays safe.
 *
 * Usage in the browser:
 *     import * as pretext from './vendor/pretext/measurement.js';
 *     const measurer = createPreTextMeasurer(pretext);
 *
 * @param {object} pretext - The module namespace from `vendor/pretext/measurement.js`.
 * @param {object} [options]
 * @param {() => boolean} [options.isFontReady] - Returns true when the requested
 *   font has actually loaded. Defaults to consulting `document.fonts`. See
 *   `ensureFont` below for why this matters so much.
 * @returns {object} A measurer satisfying the interface `createGeometry` expects.
 */
export function createPreTextMeasurer(pretext, options = {}) {
  // Per-font measurement state handed back by PreText: a segment cache, the
  // parsed pixel size, and an emoji width correction factor.
  let state = null;
  let activeFont = null;

  const isFontReady =
    options.isFontReady ??
    ((font) => {
      // `document.fonts.check` answers "can you render this font right now
      // without substituting". If there is no font-loading API at all we cannot
      // verify, so we optimistically say yes rather than deadlock.
      if (typeof document === 'undefined' || !document.fonts) return true;
      try {
        return document.fonts.check(font);
      } catch {
        // `check` throws on a font string it cannot parse. An unparseable font
        // is a caller error, not a readiness question, so let measurement
        // proceed and fail loudly later if it is genuinely broken.
        return true;
      }
    });

  return {
    ensureFont(font) {
      if (!isFontReady(font)) return { ready: false, font };
      if (font !== activeFont) {
        // `getFontMeasurementState` also assigns `ctx.font`, which is what makes
        // every later `measureText` call use this font. Skipping it would
        // silently measure against whatever font was set last.
        state = pretext.getFontMeasurementState(font, true);
        activeFont = font;
      }
      return { ready: true, font };
    },

    advance(text) {
      if (state === null) throw new Error('geometry: ensureFont() must succeed before advance()');
      const metrics = pretext.getSegmentMetrics(text, state.cache);
      return pretext.getCorrectedSegmentWidth(text, metrics, state.emojiCorrection);
    },

    prefixWidths(text) {
      if (state === null) throw new Error('geometry: ensureFont() must succeed before prefixWidths()');
      const metrics = pretext.getSegmentMetrics(text, state.cache);
      const widths = pretext.getSegmentGraphemePrefixWidths(
        text, metrics, state.cache, state.emojiCorrection,
      );
      // CRITICAL NORMALISATION. PreText returns `null` -- not an array -- when a
      // segment contains one grapheme or fewer, as an allocation optimisation
      // for its line-breaking hot path (measurement.js:161). Single-character
      // rows are extremely common in ASCII art, so a caller that trusted the
      // return type would crash on the very first such row. We restore the
      // uniform contract: always an array, one cumulative width per grapheme.
      if (widths !== null) return widths;
      if (text.length === 0) return [];
      return [pretext.getCorrectedSegmentWidth(text, metrics, state.emojiCorrection)];
    },

    fontSize() {
      if (state === null) throw new Error('geometry: ensureFont() must succeed before fontSize()');
      return state.fontSize;
    },

    clearCaches() {
      pretext.clearMeasurementCaches();
      state = null;
      activeFont = null;
    },
  };
}

/**
 * A measured row of an asset: the text, and where each grapheme boundary falls.
 *
 * @typedef {object} MeasuredRow
 * @property {string} text - The original row string, unmodified.
 * @property {string[]} graphemes - The row split into user-perceived characters.
 * @property {number[]} prefix - Cumulative widths in pixels. `prefix[i]` is the
 *   distance from the row's start to the RIGHT edge of grapheme `i`. Therefore
 *   the LEFT edge of grapheme `i` is `prefix[i - 1]`, or 0 when `i` is 0. This
 *   representation is chosen because it makes both directions of lookup a
 *   single array read or one binary search, with no running totals to drift.
 * @property {number} width - Total advance width of the row in pixels.
 */

/**
 * A fully measured asset frame, ready to paint.
 *
 * @typedef {object} MeasuredAsset
 * @property {MeasuredRow[]} rows
 * @property {number} width - Widest row, in pixels. May EXCEED the pixel width
 *   of the declared cell footprint; overhang is legal and does not affect
 *   occupancy or hit identity.
 * @property {number} height - Row count multiplied by line height, in pixels.
 */

/**
 * Build a geometry transform bound to one font, one lattice, and one scale.
 *
 * AFFINE-ONLY CONSTRUCTION
 * ------------------------
 * Supplying BOTH `cellAdvance` and `lineHeight` explicitly makes `measurer` and
 * `font` optional. This is not a convenience shortcut; it follows from what the
 * affine transform is. `worldToPixel` is a multiply and an add over the lattice
 * constants, so once those constants are known there is nothing left for a
 * measurer to contribute, and demanding one would be asking a caller to supply
 * a dependency that provably cannot affect the answer.
 *
 * The renderer's hit testing is exactly this case: it already knows its cell
 * size, and hit identity comes from canonical hotspot rectangles, which are
 * integers converted by units alone. In affine-only mode every function that
 * would need to measure text throws rather than guessing, so the restriction is
 * enforced instead of merely documented.
 *
 * @param {object} config
 * @param {object} [config.measurer] - Injected measurement capability. Must
 *   provide `ensureFont(font)`, `advance(text)`, `prefixWidths(text)`,
 *   `fontSize()` and `clearCaches()`. See `createPreTextMeasurer`. Optional
 *   only in affine-only mode, described above.
 * @param {string} [config.font] - A CSS font shorthand string, e.g.
 *   `'15px "IBM Plex Mono", monospace'`. Optional only in affine-only mode.
 * @param {number} [config.scale=1] - Zoom factor. Browser zoom and pinch-zoom
 *   both change how many device pixels a CSS pixel occupies; multiplying the
 *   lattice by this keeps world spacing proportional to text size rather than
 *   drifting away from it.
 * @param {number} [config.originX=0] - Pixel x of world column 0.
 * @param {number} [config.originY=0] - Pixel y of world row 0.
 * @param {number} [config.cellAdvance] - Pixels per world column. Defaults to
 *   the measured width of `LATTICE_REFERENCE_TEXT`, i.e. derived from the font
 *   and nothing else.
 * @param {number} [config.lineHeight] - Pixels per world row. Defaults to the
 *   font size times `DEFAULT_LINE_HEIGHT_RATIO`.
 * @param {number} [config.minimumTargetPx=MINIMUM_TARGET_PX] - Accessibility
 *   floor for tap targets.
 * @returns {object} The geometry API.
 */
export function createGeometry(config) {
  const {
    measurer,
    font,
    scale = 1,
    originX = 0,
    originY = 0,
    minimumTargetPx = MINIMUM_TARGET_PX,
  } = config;

  // AFFINE-ONLY MODE. Both lattice constants supplied means the transform is
  // fully determined and no text has to be measured to build it. See the note
  // above `createGeometry` for why that makes the measurer genuinely redundant
  // rather than merely optional.
  const affineOnly =
    Number.isFinite(config.cellAdvance) && config.cellAdvance > 0 &&
    Number.isFinite(config.lineHeight) && config.lineHeight > 0 &&
    !measurer;

  if (!affineOnly) {
    if (!measurer) {
      throw new Error(
        'geometry: a measurer must be injected, or both cellAdvance and ' +
        'lineHeight supplied for affine-only use',
      );
    }
    if (typeof font !== 'string' || font.length === 0) {
      throw new Error('geometry: a CSS font string is required');
    }

    // FONT READINESS GATE.
    //
    // Measuring before the real font has loaded produces widths for a fallback
    // font -- usually a substantially different one. Those wrong widths would
    // be cached, and every glyph placed from them would sit in the wrong place
    // until something happened to invalidate the cache. Worse, the error is
    // invisible: the art still draws, it is just subtly misaligned, which is
    // precisely the failure mode that is hardest to notice and hardest to
    // attribute.
    //
    // So readiness is a hard precondition, checked once, up front.
    const readiness = measurer.ensureFont(font);
    if (!readiness || readiness.ready !== true) {
      throw new Error(
        `geometry: font is not ready for measurement: ${font}. ` +
        'Await document.fonts.ready before constructing geometry.',
      );
    }
  }

  // LATTICE CONSTANTS.
  //
  // Computed once, from the font and the fixed reference probe -- or supplied
  // outright in affine-only mode. These two numbers are the entire
  // content-independent basis of world positioning.
  const cellAdvance =
    (config.cellAdvance ?? measurer.advance(LATTICE_REFERENCE_TEXT)) * scale;
  const lineHeight =
    (config.lineHeight ?? measurer.fontSize() * DEFAULT_LINE_HEIGHT_RATIO) * scale;

  if (!(cellAdvance > 0) || !(lineHeight > 0)) {
    throw new Error('geometry: lattice spacing must be positive and finite');
  }

  /**
   * Refuse a measurement request that has no measurer behind it.
   *
   * Throwing beats returning a plausible-looking fallback. A fallback would put
   * glyphs at almost-right positions, and almost-right placement is the single
   * hardest rendering fault to notice or attribute -- which is the same reason
   * the font readiness gate above is a hard precondition rather than a warning.
   *
   * @param {string} what - The function the caller reached for.
   */
  function requireMeasurer(what) {
    if (!affineOnly) return;
    throw new Error(
      `geometry: ${what}() needs a measurer; this geometry was built ` +
      'affine-only from explicit lattice constants',
    );
  }

  // Measured-asset cache. Keyed by row text alone, because the font and scale
  // are fixed for the lifetime of this geometry object -- a font change or zoom
  // change means constructing a new geometry, which starts with an empty cache.
  // That is why there is no invalidation bug lurking here: the cache cannot
  // outlive the assumptions it was built under.
  const rowCache = new Map();

  /**
   * Convert an integer world coordinate to a pixel position.
   *
   * This is the affine transform. Note what does not appear in it: any asset,
   * any glyph, any measured text, any other object. Two objects at the same
   * world coordinate always land on the same pixel, forever, no matter what
   * either of them draws.
   *
   * @param {number} worldX - Integer world column.
   * @param {number} worldY - Integer world row.
   * @returns {{x: number, y: number}} Position in CSS pixels.
   */
  function worldToPixel(worldX, worldY) {
    return {
      x: originX + worldX * cellAdvance,
      y: originY + worldY * lineHeight,
    };
  }

  /**
   * Convert a pixel position back to fractional world coordinates.
   *
   * Fractional, not integer, because the caller usually wants to know where
   * within a cell the point fell. Callers that need a cell index should floor
   * the result themselves, and should be aware that this is a coarse spatial
   * query -- it is NOT how a click is resolved to an object. See `hitTest`.
   *
   * @param {number} px
   * @param {number} py
   * @returns {{x: number, y: number}} Fractional world coordinates.
   */
  function pixelToWorld(px, py) {
    return {
      x: (px - originX) / cellAdvance,
      y: (py - originY) / lineHeight,
    };
  }

  /**
   * Measure one row string, with caching.
   *
   * @param {string} text
   * @returns {MeasuredRow}
   */
  function measureRow(text) {
    requireMeasurer('measureRow');
    const cached = rowCache.get(text);
    if (cached !== undefined) return cached;

    const graphemes = toGraphemes(text);
    // `prefixWidths` returns unscaled pixel widths from the measurer; the zoom
    // scale is applied here so that measured art and lattice spacing zoom
    // together. Applying it in one place avoids the two drifting apart.
    const raw = graphemes.length === 0 ? [] : measurer.prefixWidths(text);

    const prefix = new Array(raw.length);
    for (let i = 0; i < raw.length; i += 1) prefix[i] = raw[i] * scale;

    const row = {
      text,
      graphemes,
      prefix,
      // Total width is the last cumulative value; an empty row has zero width.
      width: prefix.length === 0 ? 0 : prefix[prefix.length - 1],
    };
    rowCache.set(text, row);
    return row;
  }

  /**
   * Measure a whole asset frame: a list of row strings.
   *
   * Rows are stored and measured as STRINGS, never as character matrices,
   * because with a proportional font a "column count" is not a meaningful
   * quantity -- ten narrow glyphs and ten wide ones occupy different widths.
   * Any validation that counts columns is measuring the wrong thing.
   *
   * @param {string[]} rows - The asset's row strings, top to bottom.
   * @returns {MeasuredAsset}
   */
  function measureAsset(rows) {
    if (!Array.isArray(rows)) throw new TypeError('geometry: asset rows must be an array');
    const measured = rows.map(measureRow);
    let width = 0;
    for (const row of measured) {
      if (row.width > width) width = row.width;
    }
    return { rows: measured, width, height: measured.length * lineHeight };
  }

  /**
   * Find which grapheme of a row sits under a horizontal offset.
   *
   * ASSET-LOCAL AND ADVISORY. `offsetPx` is measured from the row's own left
   * edge, not from the screen. The answer is used for hover highlighting and
   * for diagnostics such as "which glyph is the player pointing at" -- never to
   * decide which object was clicked. That decision belongs to `hitTest`.
   *
   * Implemented as a binary search over the cumulative prefix array: we want the
   * first grapheme whose RIGHT edge lies strictly beyond the offset, because
   * that is the grapheme the offset falls inside. Binary search is exact and
   * O(log n); the alternative it replaces -- dividing by a fixed cell width --
   * is only correct when every glyph is the same width, which is the assumption
   * this whole module exists to remove.
   *
   * @param {MeasuredRow} row
   * @param {number} offsetPx - Distance from the row's left edge, in pixels.
   * @returns {number} Grapheme index, or -1 if the offset is outside the row.
   */
  function graphemeAtOffset(row, offsetPx) {
    const { prefix } = row;
    if (prefix.length === 0) return -1;
    // Anything left of the row's start, or at or beyond its end, is a miss.
    // `>= width` rather than `> width` because the far edge belongs to no
    // grapheme -- it is the boundary after the last one.
    if (offsetPx < 0 || offsetPx >= row.width) return -1;

    let low = 0;
    let high = prefix.length - 1;
    while (low < high) {
      // Bit shift is an integer divide by two. Written this way because the
      // midpoint must be an integer index; a fractional index would be a silent
      // bug when used to read the array.
      const mid = (low + high) >> 1;
      if (prefix[mid] > offsetPx) {
        // Grapheme `mid` ends beyond the offset, so the answer is `mid` or
        // earlier. Keep `mid` inside the search window.
        high = mid;
      } else {
        // Grapheme `mid` ends at or before the offset, so the offset lies in a
        // later grapheme.
        low = mid + 1;
      }
    }
    return low;
  }

  /**
   * The left edge of a grapheme, in pixels from the row's start.
   *
   * The exact inverse of `graphemeAtOffset` at grapheme boundaries: feeding this
   * function's output back into that one returns the same index. That round-trip
   * property is what makes selection and caret positioning stable, and it is
   * asserted directly in the conformance tests.
   *
   * @param {MeasuredRow} row
   * @param {number} index - Grapheme index; may equal the grapheme count, which
   *   yields the row's total width (the position just past the last glyph).
   * @returns {number} Offset in pixels.
   */
  function offsetOfGrapheme(row, index) {
    if (index <= 0) return 0;
    if (index >= row.prefix.length) return row.width;
    // The left edge of grapheme `index` is the right edge of the one before it.
    return row.prefix[index - 1];
  }

  /**
   * Convert a canonical integer hotspot into a pixel rectangle.
   *
   * The hotspot comes from the projection layer, which is the authority on hit
   * identity (see `garden-world.mjs` and `projection.py`). This function only
   * changes its units. It performs no measurement whatsoever -- which is the
   * entire point, because it means an object's clickable area is immune to
   * changes in its own or anyone else's artwork.
   *
   * @param {{x: number, y: number, width: number, height: number}} hotspot -
   *   Integer world cells.
   * @returns {{x: number, y: number, width: number, height: number}} CSS pixels.
   */
  function hotspotToRect(hotspot) {
    const values = [hotspot?.x, hotspot?.y, hotspot?.width, hotspot?.height].map(Number);
    if (values.some((value) => !Number.isFinite(value))) {
      throw new Error('geometry: hotspot must have finite x, y, width and height');
    }
    const [hx, hy, hw, hh] = values;
    const topLeft = worldToPixel(hx, hy);
    return {
      x: topLeft.x,
      y: topLeft.y,
      width: hw * cellAdvance,
      height: hh * lineHeight,
    };
  }

  /**
   * Grow a rectangle to the minimum accessible tap size, centred in place.
   *
   * Growth is symmetric about the rectangle's own centre, so the target still
   * points at the same thing it did before -- it just becomes easier to hit. A
   * rectangle already large enough is returned unchanged.
   *
   * @param {{x: number, y: number, width: number, height: number}} rect
   * @returns {{x: number, y: number, width: number, height: number}}
   */
  function expandTarget(rect) {
    const width = Math.max(rect.width, minimumTargetPx);
    const height = Math.max(rect.height, minimumTargetPx);
    return {
      // Half the growth comes off each side, which is what keeps the centre
      // fixed. If we grew only rightwards the target would creep away from the
      // object it represents.
      x: rect.x - (width - rect.width) / 2,
      y: rect.y - (height - rect.height) / 2,
      width,
      height,
    };
  }

  /** Is a point inside a rectangle? Left/top edges inclusive, right/bottom exclusive. */
  function containsPoint(rect, px, py) {
    return (
      px >= rect.x && px < rect.x + rect.width &&
      py >= rect.y && py < rect.y + rect.height
    );
  }

  /**
   * Resolve a pointer position to exactly one canonical object id.
   *
   * RESOLUTION ORDER, and why it is this order:
   *
   *   1. Any object whose UNEXPANDED hotspot contains the point wins outright.
   *      Accessibility expansion must never steal a click from an object the
   *      player actually touched. If two unexpanded hotspots both contain the
   *      point the world model has overlapping hotspots, which is a world bug;
   *      we resolve it deterministically rather than arbitrarily.
   *   2. Otherwise, among objects whose EXPANDED target contains the point, the
   *      one whose centre is nearest wins. Nearest-centre is the least
   *      surprising rule when several forgiving targets overlap.
   *   3. Ties break on object id, compared by code point. Determinism matters
   *      more than which particular object wins: the same tap on the same scene
   *      must always do the same thing, including across machines.
   *
   * @param {Array<{object_id: string, hotspot: object}>} objects - Projection
   *   objects. Every one must carry a hotspot; the renderer already throws when
   *   one does not, and so does this.
   * @param {number} px - Pointer x in CSS pixels, relative to the same origin.
   * @param {number} py - Pointer y in CSS pixels.
   * @returns {string|null} The winning object id, or null if nothing was hit.
   */
  function hitTest(objects, px, py) {
    let exact = null;
    let nearest = null;
    let nearestDistanceSquared = Infinity;

    for (const object of objects) {
      const id = object?.object_id;
      if (typeof id !== 'string') {
        throw new Error('geometry: projection object lacks a string object_id');
      }
      const rect = hotspotToRect(object.hotspot);

      if (containsPoint(rect, px, py)) {
        // Rule 1. Among exact hits, lowest id wins, for determinism.
        if (exact === null || id < exact) exact = id;
        continue;
      }
      // An exact hit already found makes expanded candidates irrelevant, but we
      // keep looping rather than breaking so that rule 1's tie-break sees every
      // exact hit, not just the first one encountered.
      if (exact !== null) continue;

      const target = expandTarget(rect);
      if (!containsPoint(target, px, py)) continue;

      // Distance from the pointer to the rectangle's centre. Squared distance is
      // compared instead of the real distance because the square root is
      // monotonic -- it would not change any ordering, only cost time.
      const centreX = rect.x + rect.width / 2;
      const centreY = rect.y + rect.height / 2;
      const dx = px - centreX;
      const dy = py - centreY;
      const distanceSquared = dx * dx + dy * dy;

      if (
        distanceSquared < nearestDistanceSquared ||
        (distanceSquared === nearestDistanceSquared && nearest !== null && id < nearest)
      ) {
        nearestDistanceSquared = distanceSquared;
        nearest = id;
      }
    }

    return exact ?? nearest;
  }

  return {
    // Lattice constants, exposed so callers and tests can assert on them.
    cellAdvance,
    lineHeight,
    originX,
    originY,
    scale,
    font,

    /**
     * True when this geometry carries no measurer and can only do the affine
     * half. Exposed so a caller can branch instead of catching, and so a test
     * can assert which half it is exercising.
     */
    affineOnly,

    worldToPixel,
    pixelToWorld,
    measureRow,
    measureAsset,
    graphemeAtOffset,
    offsetOfGrapheme,
    hotspotToRect,
    expandTarget,
    // Exported because callers that do their own RANKING -- the renderer ranks
    // by exactness, then distance, then depth, then id -- still need the one
    // canonical containment rule. Two implementations of "is this point inside
    // this rectangle" is exactly how an edge case ends up half-open on one side
    // and closed on the other.
    containsPoint,
    hitTest,

    /** Number of rows currently memoised. Diagnostics and cache tests only. */
    cachedRowCount() {
      return rowCache.size;
    },
  };
}
