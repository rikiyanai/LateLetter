/**
 * EXECUTED proof of what a raster does with a visual source id.
 *
 * WHY THIS FILE EXISTS
 * --------------------
 * `scripts/validate_presentation_identity.py` decides, by reading the source
 * text, whether a raster can give an emitted cell a `visual_source_id` as
 * `docs/SPEC.md` §7.2.1 requires. Reading text is the only thing a static gate
 * can do, and it has been wrong twice in the same way: it accepted a MENTION of
 * the identity as proof that the identity was kept.
 *
 *   this.sources[y][x] = source ? null : null;   // named it, stored null
 *
 * and it credited a reference raster that could never have run at all, because
 * that raster declared `this.glyphs = []` and then indexed `this.glyphs[y][x]`.
 * Both cleared the gate. Neither would have put one identified cell on a screen.
 *
 * The static gate is now tighter, but tightening it is not the answer to the
 * class of problem, because the next discarding expression nobody thought of is
 * still out there. The answer is that the claim "the cell carries the id" is
 * settled by RUNNING the code and looking at the cell. That is this file.
 *
 * It measures the same two rasters the Python contract measures statically, so
 * a lie in either direction shows up:
 *
 *   * the REFERENCE raster (`tests/garden_contract/fixtures/identity_reference_raster.mjs`)
 *     is credited by the static gate, so it must actually deliver the exact id
 *     to the exact cell -- otherwise the gate's "satisfiable" claim is empty;
 *   * the LIVE renderer's `Raster` is refused by the static gate, so it must
 *     actually retain nothing -- otherwise the gate is refusing a raster that
 *     works, and the two would have to be reconciled before anything is trusted.
 *
 * The live arm therefore FAILS the day the renderer starts recording identity,
 * which is deliberate: route step 5 has to update both the code and the gate
 * together, and cannot quietly do one without the other.
 */

import assert from 'node:assert/strict';
import test from 'node:test';
import { readFileSync } from 'node:fs';
import { fileURLToPath, pathToFileURL } from 'node:url';
import { dirname, resolve } from 'node:path';

import { Raster as ReferenceRaster }
  from '../garden_contract/fixtures/identity_reference_raster.mjs';

const HERE = dirname(fileURLToPath(import.meta.url));
const WEB = resolve(HERE, '..', '..', 'web');
const RENDERER = resolve(WEB, 'garden-renderer.mjs');

/** The id used throughout, distinctive enough that a substring scan is sound. */
const TEST_SOURCE = 'recipe.identity_contract.probe';

/**
 * Load the live renderer's `Raster`, which the module does not export.
 *
 * The class is internal, and this file must not change the renderer to reach it
 * -- the operator route's step 1 changes no rendering, and adding an export for
 * a test's convenience is still an edit to the file under examination. So the
 * module's own text is read, its relative import specifiers are rewritten to
 * absolute `file://` URLs (a `data:` module has no directory of its own to
 * resolve `./garden-atlas.mjs` against), an export of the class is appended, and
 * the result is imported.
 *
 * What executes is the renderer's real source, byte for byte, apart from the
 * specifier rewrite and the appended export line.
 *
 * @returns The `Raster` class as the live renderer actually defines it.
 */
async function loadLiveRaster() {
  const source = readFileSync(RENDERER, 'utf8');
  const rebased = source.replace(
    /(\bfrom\s*['"])\.\/([^'"]+)(['"])/g,
    (_match, before, file, after) => `${before}${pathToFileURL(resolve(WEB, file)).href}${after}`,
  );
  const withExport = `${rebased}\nexport { Raster };\n`;
  const url = `data:text/javascript;base64,${Buffer.from(withExport, 'utf8').toString('base64')}`;
  return (await import(url)).Raster;
}

/**
 * Every per-cell plane a raster keeps, as flat arrays of cell values.
 *
 * Used to ask "is this id anywhere in this raster at all", which is a stronger
 * question than "is it in the plane I expected". A renderer that stashed the id
 * somewhere unexpected would still be recording it, and the live-arm assertion
 * below should not pass on a technicality.
 *
 * @param raster Any raster instance.
 * @returns One flat array per own property that looks like a grid of rows.
 */
function cellPlanes(raster) {
  return Object.entries(raster)
    .filter(([, value]) => Array.isArray(value) && value.every(row => Array.isArray(row)))
    .map(([name, rows]) => [name, rows.flat()]);
}

test('the reference raster records the exact source id on the cell put wrote', () => {
  const raster = new ReferenceRaster(10, 4);
  raster.put(3, 1, 'A', '#fff', false, null, { source: TEST_SOURCE });
  assert.equal(raster.glyphs[1][3], 'A');
  // The id, not a truthy stand-in for it: an implementation that stored `true`
  // or the string 'source' would satisfy "the cell carries something".
  assert.equal(raster.sources[1][3], TEST_SOURCE);
  // Its neighbours were not written, so they must claim nothing.
  assert.equal(raster.sources[1][2], null);
  assert.equal(raster.sources[1][4], null);
});

test('the reference raster records the source id on every cell text wrote', () => {
  const raster = new ReferenceRaster(10, 4);
  raster.text(2, 2, 'abc', null, false, null, { source: TEST_SOURCE });
  assert.equal(raster.line(2).trim(), 'abc');
  for (const column of [2, 3, 4]) assert.equal(raster.sources[2][column], TEST_SOURCE);
  assert.equal(raster.sources[2][5], null);
});

test('the reference raster records the source id on both of art\'s branches', () => {
  // Plain branch: whole rows delegated to `text`.
  const plain = new ReferenceRaster(12, 6);
  plain.art(5, 3, ['ab', 'cd'], null, { baseline: false, source: TEST_SOURCE });
  const plainWritten = plain.sources.flat().filter(id => id === TEST_SOURCE);
  assert.equal(plainWritten.length, 4, 'all four glyphs of the drawing are identified');

  // Accent branch: cell by cell through `put`, so one glyph can be recoloured.
  // This is the branch a checker that only followed the common path missed.
  const accented = new ReferenceRaster(12, 6);
  accented.art(5, 3, ['ab', 'cd'], null, {
    baseline: false, accents: { '0,1': '#f00' }, source: TEST_SOURCE,
  });
  const accentWritten = accented.sources.flat().filter(id => id === TEST_SOURCE);
  assert.equal(accentWritten.length, 4, 'the accent branch identifies its cells too');
  // The drawing is 2 wide and centred on x=5, so it occupies columns 4 and 5,
  // and the accent named as art cell "row 0, column 1" is the one at x=5.
  assert.equal(accented.colors[3][4], null);
  assert.equal(accented.colors[3][5], '#f00', 'the accent still recoloured its cell');
});

test('the reference raster records the source id on measuredArt\'s cells', () => {
  const raster = new ReferenceRaster(12, 6);
  raster.measuredArt('fixture.bench', 5, 3, ['xy'], [0, 0], null, { source: TEST_SOURCE });
  const written = raster.sources.flat().filter(id => id === TEST_SOURCE);
  assert.equal(written.length, 2);
  // The gameplay owner and the presentation identity are different facts and
  // are kept in different planes; collapsing them would lose one of them.
  assert.equal(raster.owners[3][5], 'asset:fixture.bench');
  assert.equal(raster.sources[3][5], TEST_SOURCE);
});

test('a later write replaces the source id, and an anonymous write clears it', () => {
  const raster = new ReferenceRaster(10, 4);
  raster.put(1, 1, 'A', null, false, null, { source: TEST_SOURCE });
  // Overwrite: the cell now shows the second drawing, so it must say so. A
  // stale id would attribute a visible glyph to a recipe that did not draw it.
  raster.put(1, 1, 'B', null, false, null, { source: 'recipe.identity_contract.second' });
  assert.equal(raster.glyphs[1][1], 'B');
  assert.equal(raster.sources[1][1], 'recipe.identity_contract.second');
  // Clear: an anonymous write leaves an anonymous cell, rather than inheriting
  // the previous claim. Anonymous paint has to stay visible to the gate.
  raster.put(1, 1, 'C');
  assert.equal(raster.glyphs[1][1], 'C');
  assert.equal(raster.sources[1][1], null);
});

test('the live renderer retains no visual source, matching its static verdict', async () => {
  const LiveRaster = await loadLiveRaster();
  const raster = new LiveRaster(12, 6);

  // Every writer, each handed the id in the most generous form available: the
  // options object where one exists, a surplus trailing argument where it does
  // not. This is exactly the shape route step 5 might be tempted to add first.
  raster.put(1, 1, 'A', null, false, null, { source: TEST_SOURCE });
  raster.text(1, 2, 'bc', null, false, null, { source: TEST_SOURCE });
  raster.art(5, 3, ['de'], null, { baseline: false, source: TEST_SOURCE });
  raster.measuredArt('fixture.bench', 5, 4, ['fg'], [0, 0], null, { source: TEST_SOURCE });

  // The glyphs did land, so this is not a test that simply failed to paint.
  assert.equal(raster.glyphs[1][1], 'A');
  assert.ok(raster.glyphs.flat().includes('d'));

  // And not one cell, in any plane, kept the id.
  for (const [name, cells] of cellPlanes(raster)) {
    assert.ok(
      !cells.includes(TEST_SOURCE),
      `plane '${name}' unexpectedly retained a visual source id -- the renderer `
      + 'has gained identity, so the static gate in '
      + 'scripts/validate_presentation_identity.py must be re-derived against it',
    );
  }
  // Stated separately from the scan, because the absent plane IS the defect:
  // there is nowhere for a cell to keep provenance, which is what the blocker
  // `writers_that_cannot_record_identity` reports without running anything.
  assert.equal(raster.sources, undefined, 'the live raster has no per-cell source plane');
});
