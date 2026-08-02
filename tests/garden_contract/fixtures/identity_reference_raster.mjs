/**
 * A raster that actually threads a visual source id through to the emitted cell.
 *
 * WHY THIS FILE EXISTS
 * --------------------
 * `docs/SPEC.md` §7.2.1 requires that every emitted nonblank cell CARRIES a
 * `visual_source_id`. The release gate in `scripts/validate_presentation_identity.py`
 * has to answer two questions about that requirement, and they are different
 * questions:
 *
 *   1. Does the live renderer meet it?  (Today: no. Its raster keeps four
 *      per-cell planes -- glyphs, colors, animated, owners -- and none of them
 *      holds a visual source, so no call to any writer can identify a cell.)
 *   2. Is the gate SATISFIABLE at all -- could any raster clear it?  A gate that
 *      nothing can pass is a permanent refusal wearing a rule's clothes, and it
 *      would be indistinguishable from a broken checker.
 *
 * This file is the answer to question 2, and it is a real module rather than a
 * string inside a test because the previous version of it was a string that
 * would have thrown `TypeError` on its first write: it declared `this.glyphs = []`
 * and then indexed `this.glyphs[y][x]`, so no row array ever existed. It parsed,
 * the static gate credited it, and it could not have painted a single cell. A
 * positive control that cannot run proves nothing about what running code does.
 *
 * So this module is used TWICE, by two different checks, and that is the point:
 *
 *   * `tests/garden_contract/test_asset_acceptance.py` reads its TEXT and hands
 *     it to the static gate, which must report every writer as able to record an
 *     identity;
 *   * `tests/garden_adapters/test_raster_identity_contract.mjs` IMPORTS it and
 *     executes it, asserting the exact source id lands on the exact cell.
 *
 * Static credit and executed behaviour are therefore measured on one artifact.
 * Faking either one alone breaks the other.
 *
 * WHAT "THREADING IDENTITY" MEANS STRUCTURALLY
 * -------------------------------------------
 * Three things, all of which must hold:
 *   (a) each writer's options parameter can express a read of `source`;
 *   (b) each delegating writer hands that value into the identity argument of
 *       the writer it delegates to, under the property name `source`;
 *   (c) the terminal writer `put` -- the one every other writer funnels into --
 *       assigns it into a per-cell plane that the constructor allocated.
 * Break any one and the id never reaches a cell, however faithfully the other
 * two are written.
 */

/**
 * The reference raster.
 *
 * Deliberately a near-copy of the live renderer's `Raster` in shape -- same
 * method names, same parameter order, same delegation chain -- so that the
 * difference between "passes" and "fails" is only the identity thread and not
 * some unrelated divergence in structure.
 */
export class Raster {
  /**
   * @param width  Number of cells across. Writes outside it are dropped.
   * @param height Number of cell rows. Writes outside it are dropped.
   */
  constructor(width, height) {
    this.width = width;
    this.height = height;
    // Every plane is a real height x width grid. The live renderer allocates
    // its planes the same way; the earlier string fixture did not, which is how
    // it managed to look correct while being unrunnable.
    this.glyphs = Array.from({ length: height }, () => Array(width).fill(' '));
    this.colors = Array.from({ length: height }, () => Array(width).fill(null));
    this.animated = Array.from({ length: height }, () => Array(width).fill(false));
    this.owners = Array.from({ length: height }, () => Array(width).fill(null));
    // The plane the live renderer does not have. One slot per cell, holding the
    // id of the visual source that most recently wrote that cell.
    this.sources = Array.from({ length: height }, () => Array(width).fill(null));
    this.measuredAssets = [];
  }

  /**
   * Write one cell -- the terminal writer, and the only place identity can be
   * stored, because it is the only method that assigns into the per-cell planes.
   *
   * @param source The visual source id, read out of the options object. It is
   *   assigned UNCONDITIONALLY, so a later write with no source CLEARS the
   *   previous one rather than leaving a stale id behind. That matters: a cell
   *   painted by the ground band and then overwritten by a fixture must report
   *   the fixture, and a cell overwritten by an anonymous paint must report
   *   nothing rather than continuing to claim the ground band drew it.
   */
  put(x, y, glyph, color = null, animated = false, owner = null, { source = null } = {}) {
    if (x < 0 || x >= this.width || y < 0 || y >= this.height || !glyph) return;
    this.glyphs[y][x] = [...String(glyph)][0];
    this.colors[y][x] = color;
    this.animated[y][x] = animated;
    this.owners[y][x] = owner;
    this.sources[y][x] = source;
  }

  /** Write a string left-to-right from (x, y), handing the id to every cell. */
  text(x, y, value, color = null, animated = false, owner = null, { source = null } = {}) {
    [...String(value)].forEach((glyph, index) =>
      this.put(x + index, y, glyph, color, animated, owner, { source }));
  }

  /**
   * Draw a picture, in either of the two branches the live renderer has.
   *
   * The plain branch delegates a whole row to `text`; the accent branch writes
   * cell by cell through `put` so one glyph can take a different colour. BOTH
   * must carry the identity: a writer that identifies its common path and drops
   * the id on its rarer one produces cells whose provenance depends on whether
   * the drawing happened to have an accent, which is not provenance at all.
   */
  art(anchorX, anchorY, lines, color, {
    baseline = true, animated = false, accents = null, owner = null, source = null,
  } = {}) {
    const width = Math.max(0, ...lines.map(line => [...line].length));
    const top = baseline ? anchorY - lines.length + 1 : anchorY;
    const left = anchorX - Math.floor(width / 2);
    lines.forEach((line, row) => {
      if (!accents) {
        this.text(left, top + row, line, color, animated, owner, { source });
        return;
      }
      [...line].forEach((glyph, column) => {
        this.put(left + column, top + row, glyph,
          accents[`${row},${column}`] ?? color, animated, owner, { source });
      });
    });
  }

  /**
   * Record one atlas-owned picture and paint its cells.
   *
   * Its options parameter is a plain named object rather than a destructuring
   * pattern, so the identity read is spelled `options.source`. Both spellings
   * have to work, because the live renderer uses both.
   */
  measuredArt(objectId, anchorX, anchorY, lines, artAnchor, color, options = {}) {
    const owner = `asset:${objectId}`;
    const anchor = Array.isArray(artAnchor) && artAnchor.length === 2
      ? [Number(artAnchor[0]), Number(artAnchor[1])]
      : [Math.floor(Math.max(0, ...lines.map(line => [...line].length)) / 2), lines.length - 1];
    const top = anchorY - anchor[1], left = anchorX - anchor[0];
    this.measuredAssets.push({
      objectId: String(objectId), anchor: [anchorX, anchorY], artAnchor: anchor,
      lines: [...lines], color, accents: options.accents ?? null,
    });
    lines.forEach((line, row) => [...line].forEach((glyph, column) => {
      this.put(left + column, top + row, glyph,
        options.accents?.[`${row},${column}`] ?? color,
        Boolean(options.animated), owner, { source: options.source });
    }));
  }

  /** Read one row back as a string. A reader, so it names no source. */
  line(row) {
    return this.glyphs[row].join('');
  }
}
