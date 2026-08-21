/**
 * Guards that the versioned atlas is the SINGLE owner of any art it carries.
 *
 * THE FAILURE THIS EXISTS TO PREVENT
 * ----------------------------------
 * Before the migration, `fixture.bench` was drawn by two different tables in
 * `garden-renderer.mjs`: `FIXTURE_DECOR.bench` and `STARTER_FIXTURE_ART.bench`.
 * They contained different pictures. `fixtureArt()` consulted the starter table
 * first, so one drawing rendered and the other sat there looking authoritative
 * while having no effect at all.
 *
 * That is the quiet version of the problem. The loud version is what happens
 * during a migration: an asset moves into the atlas, the old table is left
 * behind "just in case", and from then on nobody can tell which drawing is
 * live. The change either has one owner or it has none.
 *
 * So this file asserts the invariant mechanically rather than trusting a
 * reviewer to notice. It reads the renderer's source text, because the tables
 * are module-private and there is nothing to import -- and because the check
 * needs to fail on the mere PRESENCE of a re-introduced entry, not on its
 * behaviour.
 */

import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import test from 'node:test';

import {
  ATLAS_PROPORTIONAL_ART,
  ATLAS_PROPORTIONAL_FONT,
  canonicalProportionalArt,
} from '../../web/garden-atlas-art.mjs';

// The painting layer was split out of the renderer by the reopened
// frame-ownership transfer (step 4): the local art tables and `fixtureArt`
// now live in web/garden-painting.mjs, and web/garden-renderer.mjs is the
// adapter class that re-exports it. The single-owner invariant is over the
// pair, so both sources are scanned -- a table reappearing in EITHER file is
// the two-owner defect this file exists to prevent.
const rendererSource = [
  await readFile(new URL('../../web/garden-renderer.mjs', import.meta.url), 'utf8'),
  await readFile(new URL('../../web/garden-painting.mjs', import.meta.url), 'utf8'),
].join('\n');

/**
 * Extract the top-level keys of a `const NAME = Object.freeze({ ... })` table.
 *
 * Parses by brace balance rather than by regular expression, because the tables
 * contain nested `Object.freeze({...})` values and artwork full of braces and
 * slashes that a naive pattern would terminate on early.
 *
 * @param {string} source - The renderer's full source text.
 * @param {string} name - The table's identifier.
 * @returns {string[]} The table's own keys, in source order.
 */
function tableKeys(source, name) {
  const start = source.indexOf(`const ${name} = Object.freeze({`);
  assert.notEqual(start, -1, `renderer no longer declares ${name}`);

  const open = source.indexOf('{', source.indexOf('Object.freeze(', start));
  let depth = 0;
  let end = open;
  for (let index = open; index < source.length; index += 1) {
    const char = source[index];
    if (char === '{') depth += 1;
    else if (char === '}') {
      depth -= 1;
      if (depth === 0) { end = index; break; }
    }
  }

  const body = source.slice(open + 1, end);
  const keys = [];
  let depthInBody = 0;
  for (const line of body.split('\n')) {
    // Only lines at nesting depth zero declare keys of THIS table; deeper lines
    // belong to a nested value such as a per-LOD object.
    const trimmed = line.trim();
    if (depthInBody === 0) {
      const match = /^([A-Za-z_$][\w$]*)\s*:/.exec(trimmed);
      if (match) keys.push(match[1]);
    }
    for (const char of line) {
      if (char === '{') depthInBody += 1;
      else if (char === '}') depthInBody -= 1;
    }
  }
  return keys;
}

/** Catalog ids the atlas owns, derived from its canonical `fixture.<id>` keys. */
function atlasOwnedFixtureCatalogIds() {
  return Object.keys(ATLAS_PROPORTIONAL_ART)
    .filter((id) => id.startsWith('fixture.'))
    .map((id) => id.slice('fixture.'.length));
}

test('no atlas-owned fixture reappears in a renderer-local art table', () => {
  const owned = atlasOwnedFixtureCatalogIds();
  assert.ok(owned.length > 0, 'the atlas should own at least the bench canary');

  for (const table of ['FIXTURE_DECOR', 'STARTER_FIXTURE_ART']) {
    const keys = tableKeys(rendererSource, table);
    for (const catalog of owned) {
      assert.ok(
        !keys.includes(catalog),
        `${table} re-declares '${catalog}', which the atlas owns. ` +
        'Delete the local entry: two owners means nobody can tell which drawing is live.',
      );
    }
  }
});

test('the bench canary is owned by the atlas and nowhere else', () => {
  // Named explicitly, so that if the bench is ever the only migrated asset and
  // someone removes it from the atlas, this fails rather than passing vacuously
  // on an empty owned-set.
  assert.ok(ATLAS_PROPORTIONAL_ART['fixture.bench'], 'atlas must own fixture.bench');
  assert.ok(!tableKeys(rendererSource, 'FIXTURE_DECOR').includes('bench'));
  assert.ok(!tableKeys(rendererSource, 'STARTER_FIXTURE_ART').includes('bench'));
});

test('the renderer consults canonical art before its local tables', () => {
  // Ordering is the mechanism that makes migration a one-step change. If the
  // local tables were checked first, moving an asset into the atlas would have
  // no effect until someone also remembered to delete the local entry.
  const body = rendererSource.slice(
    rendererSource.indexOf('function fixtureArt('),
    rendererSource.indexOf('function fixtureArt(') + 1400,
  );
  const canonicalAt = body.indexOf('canonicalProportionalArt');
  const starterAt = body.indexOf('STARTER_FIXTURE_ART[');
  const decorAt = body.indexOf('FIXTURE_DECOR[');

  assert.ok(canonicalAt !== -1, 'fixtureArt must consult the atlas');
  assert.ok(canonicalAt < starterAt, 'atlas must be consulted before STARTER_FIXTURE_ART');
  assert.ok(canonicalAt < decorAt, 'atlas must be consulted before FIXTURE_DECOR');
});

test('canonical bench art stands on its last row and is not the discarded drawing', () => {
  const bench = canonicalProportionalArt('fixture.bench');

  // Row counts change between drawing rounds, so the assertion is the contract:
  // fixtures stand on the ground, so the anchor row is the final one.
  assert.ok(bench.rows.length > 1);
  assert.equal(bench.anchor[1], bench.rows.length - 1);
  // Neither discarded browser drawing may reappear. Both had a fourteen- or
  // eighteen-underscore top row; asserting their absence keeps a revert visible.
  assert.ok(!bench.rows.includes('  __________  '));
  assert.ok(!bench.rows.includes('  ______________  '));
});

test('every starter fixture the atlas owns has real art, not a single glyph', () => {
  const starter = [
    'pond', 'bridge', 'birdbath', 'trellis', 'arbor',
    'lantern', 'bench', 'mailbox', 'stepping_stones', 'planter',
  ];
  for (const catalog of starter) {
    const art = canonicalProportionalArt(`fixture.${catalog}`);
    assert.ok(art, `atlas must own fixture.${catalog}`);
    assert.ok(art.rows.length > 1, `fixture.${catalog} is still one row tall`);
    assert.ok(
      art.rows.some((row) => row.trim().length > 1),
      `fixture.${catalog} has no drawn content`,
    );
  }
});

test('an asset the atlas does not own returns null rather than empty art', () => {
  // The distinction matters: null means "not migrated, fall through to the
  // local table", whereas empty art would mean "migrated, draws nothing" and
  // would silently blank the object.
  // Undrawn fixtures and every plant still fall through to the local tables.
  assert.equal(canonicalProportionalArt('fixture.sundial'), null);
  assert.equal(canonicalProportionalArt('plant.oak'), null);
});

test('the atlas declares the font its row strings were measured in', () => {
  // Row strings have no intrinsic width. Measuring them against a different
  // font than they were drawn for misaligns every stroke, so the font travels
  // with the art rather than being assumed by the renderer.
  assert.ok(ATLAS_PROPORTIONAL_FONT.family);
  assert.ok(ATLAS_PROPORTIONAL_FONT.size_px > 0);
});

/*
 * THE FONT THE ART DECLARES vs THE FONT THE PRODUCT PAINTS IN
 * -----------------------------------------------------------
 * The test above only checks that the atlas SAYS something about its font. A
 * declaration nothing honours is worth nothing, and that is exactly the state
 * this pair of tests was written to end: the atlas declared 15px IBM Plex Mono
 * while the Garden canvas painted in 13px/15px Courier New, and no code path
 * anywhere compared the two.
 *
 * The cost of that gap is not theoretical. Courier New is missing six of the
 * twelve non-ASCII characters the accepted art uses. A character its font
 * lacks is not skipped -- the browser silently draws it from some OTHER font,
 * per glyph, and that substitute's advance width has no relationship to the
 * advance width of the font around it. The columns shear. That is the same
 * defect that got two rounds of art rejected, arriving by a route no drawing
 * change can address.
 *
 * Four rounds of operator review could not catch it because the review
 * worksheet styles the art in a different stack than the product does, and on
 * the reviewing machine that stack resolved to a font with full coverage. The
 * art was signed off in one font and shipped in another.
 *
 * So the invariant is mechanical, not editorial: whatever the atlas declares
 * it was measured in must be what the canvas paints in. Either side may
 * change -- that is an operator's visual decision -- but they may not disagree
 * silently.
 */

/** The stylesheet block that paints the Garden, read as source text. */
const viewerUrl = new URL('../../viewer-bnw.html', import.meta.url);
const viewerSource = await readFile(viewerUrl, 'utf8');

/**
 * Pull the CSS `font:` shorthand out of a rule in the viewer's stylesheet.
 *
 * Parsed from source text rather than from a live stylesheet because there is
 * no DOM here, and because the check must fail on the mere PRESENCE of a
 * disagreeing declaration -- not on some rendered consequence of it that only
 * shows up on a machine missing the right fonts.
 *
 * @param {string} selector - The rule to read, e.g. `#g`.
 * @returns {string} The shorthand value, e.g. `13px/15px 'Courier New', monospace`.
 */
function cssFontShorthand(selector) {
  // Find the rule body: everything between the selector and its closing brace.
  // `[^}]*` is safe because CSS rules do not nest here.
  const rule = new RegExp(`${selector}\\s*\\{([^}]*)\\}`).exec(viewerSource);
  assert.ok(rule, `viewer-bnw.html no longer declares a \`${selector}\` rule`);

  // The `font:` shorthand, not `font-size:`/`font-family:`. Anchored to a line
  // start so that `font-size:` and `text-shadow: ... font` cannot match.
  const shorthand = /(?:^|\s)font:\s*([^;]+);/.exec(rule[1]);
  assert.ok(shorthand, `\`${selector}\` no longer sets the \`font\` shorthand`);
  return shorthand[1].trim();
}

/**
 * Split a CSS font shorthand into the two parts this invariant cares about.
 *
 * The shorthand may carry a line height (`13px/15px`), which is a separate
 * concern from the size the glyphs are drawn at -- conflating the two is how
 * the atlas came to declare 15 for a face painted at 13.
 *
 * @param {string} shorthand - e.g. `13px/15px 'Courier New', Courier, monospace`.
 * @returns {{sizePx: number, families: string[]}} Size in px, and the family
 *   list lowercased and stripped of quotes so `'Courier New'` and
 *   `"courier new"` compare equal.
 */
function parseFontShorthand(shorthand) {
  // Group 1: the font size in px. Group 2 (optional, discarded): the line
  // height after the slash. Group 3: everything left, which is the family list.
  const parsed = /^(?:.*\s)?(\d+(?:\.\d+)?)px(?:\s*\/\s*[\d.]+(?:px)?)?\s+(.+)$/
    .exec(shorthand);
  assert.ok(parsed, `cannot read a size and family list out of: ${shorthand}`);

  return {
    sizePx: Number.parseFloat(parsed[1]),
    families: parsed[2]
      .split(',')
      .map((name) => name.trim().replace(/^['"]|['"]$/g, '').toLowerCase())
      .filter((name) => name.length > 0),
  };
}

test('the canvas that paints the atlas art uses the family the atlas declares', () => {
  const painted = parseFontShorthand(cssFontShorthand('#g'));
  const declared = parseFontShorthand(
    `${ATLAS_PROPORTIONAL_FONT.size_px}px ${ATLAS_PROPORTIONAL_FONT.family}`,
  );

  assert.deepEqual(
    painted.families,
    declared.families,
    'The Garden canvas paints the atlas art in a different family than the ' +
    'atlas says it was measured in. Any character missing from the painted ' +
    'family is substituted per glyph from another font, whose advance width ' +
    'is unrelated -- the art shears mid-row. Bring one side to the other: ' +
    'either widen the `#g` stack in viewer-bnw.html to the declared family, ' +
    'or re-declare ATLAS_PROPORTIONAL_FONT in scripts/migrate_atlas_v2.py to ' +
    'the family actually painted (and redraw against it). Both are visual ' +
    `decisions. painted=[${painted.families}] declared=[${declared.families}]`,
  );
});

test('the canvas that paints the atlas art uses the size the atlas declares', () => {
  // Checked separately from the family because the two disagree for different
  // reasons and a single assertion would report only whichever failed first.
  const painted = parseFontShorthand(cssFontShorthand('#g'));

  assert.equal(
    painted.sizePx,
    ATLAS_PROPORTIONAL_FONT.size_px,
    'The Garden paints the atlas art at a different size than the atlas says ' +
    'it was measured at. Row strings are measured, not counted, so a size the ' +
    'measurement did not use produces widths for art that is not on screen. ' +
    'Note that the `#g` shorthand carries a line height too -- the size is the ' +
    'number BEFORE the slash. ' +
    `painted=${painted.sizePx}px declared=${ATLAS_PROPORTIONAL_FONT.size_px}px`,
  );
});
