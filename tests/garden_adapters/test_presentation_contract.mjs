/**
 * The SPEC 7.2.2 presentation contract, executed.
 * -----------------------------------------------
 *
 * The contract module defines what it means to compose a Garden picture
 * through the split GardenPresentation interface -- advance, compose, paint.
 * This file is where that definition is exercised: a reference implementation
 * is run and required to conform, then each clause is broken on purpose and
 * required to be caught, and finally the live renderer is measured against
 * the same contract without being changed.
 *
 * The order matters. A checker that has only ever refused things has not
 * been shown to be satisfiable, and a checker that accepts one good case has
 * not been shown to refuse anything. Both halves are here, for every clause.
 */

import test from 'node:test';
import assert from 'node:assert/strict';

import {
  contractViolations,
  frameViolations,
  composerViolations,
  assertConforms,
  MINIMUM_TARGET_PX,
} from '../../web/garden-presentation-contract.mjs';

import {
  REFERENCE_PRESENTATION,
  advanceReferenceState,
  composeReferenceFrame,
  REFERENCE_MANIFEST,
  REFERENCE_PROJECTION,
  REFERENCE_CONTEXT,
  REFERENCE_IDS,
} from '../garden_contract/fixtures/reference_composer.mjs';

/**
 * Build the contract input: projection, prior state, events, tick, context.
 *
 * @param {object} [overrides] - replace any input for a negative control
 * @returns {object} the input `contractViolations` takes
 */
function referenceInput(overrides = {}) {
  return {
    projection: REFERENCE_PROJECTION,
    previousState: null,
    presentationEvents: [],
    tick: { frame: 80, seconds: 1000 },
    context: REFERENCE_CONTEXT,
    ...overrides,
  };
}

/**
 * Advance and compose once, then damage the frame, so a clause can be tested
 * against a frame that is correct in every other respect.
 *
 * @param {(frame: object) => void} damage - mutates the composed frame
 * @returns {object} the damaged frame
 */
function damagedFrame(damage) {
  const input = referenceInput();
  const state = advanceReferenceState(input.previousState, input.presentationEvents, input.tick);
  const frame = composeReferenceFrame(input.projection, state, input.context);
  damage(frame);
  return frame;
}

/** The frame-check input shape: projection plus context. */
function frameInput() {
  return { projection: REFERENCE_PROJECTION, context: REFERENCE_CONTEXT };
}

// ---------------------------------------------------------------------------
// The positive control: the contract is satisfiable by code that runs.
// ---------------------------------------------------------------------------

test('the reference implementation satisfies every clause of the contract', () => {
  assertConforms(REFERENCE_PRESENTATION, referenceInput(), 'the reference implementation');
});

test('the reference implementation emits ink, so conformance is not vacuous', () => {
  const input = referenceInput();
  const state = advanceReferenceState(null, [], input.tick);
  const frame = composeReferenceFrame(input.projection, state, input.context);
  assert.ok(frame.visible_primitives.length > 10, 'the reference picture is not empty');
  assert.ok(frame.interaction_regions.length === 1, 'exactly the interactive object has a region');
  assert.ok(frame.attempted_primitives.length > frame.visible_primitives.length,
    'the attempted list demonstrably contains ink the visible list omits');
});

// ---------------------------------------------------------------------------
// Clause 1 — runtime emitted-primitive identity.
// ---------------------------------------------------------------------------

test('a nonblank primitive with no source id is refused', () => {
  const frame = damagedFrame(f => { f.attempted_primitives[0].source_id = null; });
  const problems = frameViolations(frame, frameInput());
  assert.ok(problems.some(p => p.clause === '1-identity' && /carries no source_id/.test(p.detail)));
});

test('a blank primitive needs no source id', () => {
  const frame = damagedFrame(f => {
    f.attempted_primitives.push({
      units: 'cell', profile: 'ascii-safe', painter_order: 999,
      x: 1, y: 0, glyph: ' ', color_role: 'sky', source_id: null, object_id: null,
    });
  });
  // The blank primitive is not visible, so exclude it from the subset check
  // by construction: it was attempted and hidden, which is legitimate.
  const problems = frameViolations(frame, frameInput());
  assert.deepEqual(problems, []);
});

test('a law may not be named as a primitive source', () => {
  const frame = damagedFrame(f => { f.attempted_primitives[0].source_id = REFERENCE_IDS.densityLaw; });
  const problems = frameViolations(frame, frameInput());
  assert.ok(problems.some(p => /names the law/.test(p.detail)),
    'a law is not a painter, and naming one as a source is anonymity with an id attached');
});

test('an id the release manifest does not accept is refused', () => {
  const frame = damagedFrame(f => { f.attempted_primitives[0].source_id = 'recipe.invented'; });
  const problems = frameViolations(frame, frameInput());
  assert.ok(problems.some(p => /does not accept/.test(p.detail)));
});

test('recipe-chain ink may not claim a canonical object', () => {
  const frame = damagedFrame(f => {
    const groundPrimitive = f.attempted_primitives.find(
      p => p.source_id === REFERENCE_IDS.groundRecipe,
    );
    groundPrimitive.object_id = 'plant-1';
  });
  const problems = frameViolations(frame, frameInput());
  assert.ok(problems.some(p => /recipe paint yet claims object/.test(p.detail)));
});

test('atlas ink may not claim an object the projection does not contain', () => {
  const frame = damagedFrame(f => {
    const plantPrimitive = f.attempted_primitives.find(
      p => p.source_id === REFERENCE_IDS.plantAsset,
    );
    plantPrimitive.object_id = 'object-nobody-projected';
  });
  const problems = frameViolations(frame, frameInput());
  assert.ok(problems.some(p => /absent from the projection/.test(p.detail)));
});

test('anonymous ink does not become acceptable by being occluded', () => {
  // Damage an attempted primitive that is NOT in the visible list: identity
  // is checked over attempts, so hiding anonymous ink must not excuse it.
  const frame = damagedFrame(f => {
    const hidden = f.attempted_primitives.find(
      p => !f.visible_primitives.includes(p),
    );
    hidden.source_id = null;
  });
  const problems = frameViolations(frame, frameInput());
  assert.ok(problems.some(p => p.clause === '1-identity'));
});

// ---------------------------------------------------------------------------
// Visibility — the visible picture is a subset of the attempted one.
// ---------------------------------------------------------------------------

test('a visible primitive that was never attempted is refused', () => {
  const frame = damagedFrame(f => {
    f.visible_primitives.push({
      units: 'cell', profile: 'ascii-safe', painter_order: 998,
      x: 2, y: 0, glyph: '!', color_role: 'ink',
      source_id: REFERENCE_IDS.snowRecipe, object_id: null,
    });
  });
  const problems = frameViolations(frame, frameInput());
  assert.ok(problems.some(p => p.clause === 'visibility' && /never attempted/.test(p.detail)),
    'a visible primitive outside the attempt list is a hidden second composer');
});

// ---------------------------------------------------------------------------
// Clause 3 — interaction regions are owned by the projection.
// ---------------------------------------------------------------------------

test('a region for an object the projection does not contain is refused', () => {
  const frame = damagedFrame(f => {
    f.interaction_regions.push({
      object_id: 'invented-target', asset_id: 'a', state_id: 's',
      units: 'pixel', x: 0, y: 0, width: 44, height: 44,
    });
  });
  const problems = frameViolations(frame, frameInput());
  assert.ok(problems.some(p => /the projection does not contain/.test(p.detail)));
});

test('visible interactive ink with no region is refused', () => {
  const frame = damagedFrame(f => { f.interaction_regions.length = 0; });
  const problems = frameViolations(frame, frameInput());
  assert.ok(problems.some(p => /painted visible ink and declares a primary action/.test(p.detail)),
    'the picture may not show something a person cannot touch');
});

test('a region that does not name its asset/state mask is refused', () => {
  const frame = damagedFrame(f => { f.interaction_regions[0].state_id = null; });
  const problems = frameViolations(frame, frameInput());
  assert.ok(problems.some(p => /does not name the asset\/state mask/.test(p.detail)),
    'a region that cannot say which mask it came from was recovered, not transformed');
});

test('a region under the 44px floor is refused', () => {
  const frame = damagedFrame(f => { f.interaction_regions[0].width = MINIMUM_TARGET_PX - 1; });
  const problems = frameViolations(frame, frameInput());
  assert.ok(problems.some(p => new RegExp(`under the ${MINIMUM_TARGET_PX}px floor`).test(p.detail)));
});

test('a non-interactive projected object gets no region and that is not a defect', () => {
  const input = referenceInput();
  const state = advanceReferenceState(null, [], input.tick);
  const frame = composeReferenceFrame(input.projection, state, input.context);
  assert.ok(!frame.interaction_regions.some(region => region.object_id === 'stone-1'));
  assert.deepEqual(frameViolations(frame, frameInput()), []);
});

// ---------------------------------------------------------------------------
// Paint payload — the frame carries every final visible primitive, including
// exact measured pixel placement (reopened step 2).
// ---------------------------------------------------------------------------

test('a frame without the measured-placement payload is refused', () => {
  const frame = damagedFrame(f => { delete f.measured_asset_placements; });
  const problems = frameViolations(frame, frameInput());
  assert.ok(problems.some(p => p.clause === 'paint-payload' &&
    /measured_asset_placements is not an array/.test(p.detail)),
    'a frame that leaves placement to the painter re-opens the second visual owner');
});

test('a frame without painted rows, background strings or a label is refused', () => {
  for (const [damage, expect] of [
    [f => { delete f.rows; }, /rows must carry lines/],
    [f => { f.background = { kind: 'bands' }; }, /background must carry css and text_color/],
    [f => { f.aria_label = ''; }, /aria_label is not a nonempty string/],
  ]) {
    const frame = damagedFrame(damage);
    const problems = frameViolations(frame, frameInput());
    assert.ok(problems.some(p => p.clause === 'paint-payload' && expect.test(p.detail)),
      `expected ${expect} from ${damage}`);
  }
});

test('a measured placement that is not finished pixels is refused', () => {
  for (const [placement, expect] of [
    [{ object_id: 'o', source_id: REFERENCE_IDS.plantAsset, units: 'cell',
      left: 0, top: 0, width: 1, height: 1, glyphs: [] }, /must declare pixel units/],
    [{ object_id: 'o', source_id: null, units: 'pixel',
      left: 0, top: 0, width: 1, height: 1, glyphs: [] }, /carries no source_id/],
    [{ object_id: 'o', source_id: 'asset.invented', units: 'pixel',
      left: 0, top: 0, width: 1, height: 1, glyphs: [] }, /asset lists do not accept/],
    [{ object_id: 'o', source_id: REFERENCE_IDS.plantAsset, units: 'pixel',
      left: Number.NaN, top: 0, width: 1, height: 1, glyphs: [] }, /no finite pixel position/],
    [{ object_id: 'o', source_id: REFERENCE_IDS.plantAsset, units: 'pixel',
      left: 0, top: 0, width: 1, height: 1,
      glyphs: [{ glyph: 'x', x: 4, y: 'seven' }] }, /finite pixel position/],
  ]) {
    const frame = damagedFrame(f => { f.measured_asset_placements.push(placement); });
    const problems = frameViolations(frame, frameInput());
    assert.ok(problems.some(p => p.clause === 'paint-payload' && expect.test(p.detail)),
      `expected ${expect} for ${JSON.stringify(placement)}`);
  }
});

// ---------------------------------------------------------------------------
// The interface test (reopened step 3): ANY conforming frame can be painted
// with no renderer-private knowledge — a bare surface, and the frame alone.
// ---------------------------------------------------------------------------

/** A DOM-node stand-in with exactly what a painted element must support. */
function bareNode() {
  return {
    style: {}, attributes: {}, children: [],
    className: '', textContent: '', innerHTML: '',
    setAttribute(key, value) { this.attributes[key] = value; },
    appendChild(child) { this.children.push(child); child.parentNode = this; },
    remove() {},
  };
}

/** Run a callback with `document.createElement` stubbed to bare nodes. */
function withBareDocument(callback) {
  const saved = globalThis.document;
  globalThis.document = { createElement: () => bareNode() };
  try { return callback(); } finally {
    if (saved === undefined) delete globalThis.document;
    else globalThis.document = saved;
  }
}

test('a conforming frame paints on a bare surface, and diagnostics stay unread', async () => {
  const live = await import('../../web/garden-presentation.mjs');
  // A hand-authored frame carrying the complete paint payload -- built from
  // the field set alone, with no composer and no renderer anywhere. If the
  // painter needs anything this object does not carry, the frame was not
  // the complete picture and this test fails.
  let diagnosticsRead = 0;
  const frame = {
    attempted_primitives: [], visible_primitives: [], interaction_regions: [],
    background: { css: 'linear-gradient(red, blue)', text_color: '#123456' },
    rows: { lines: ['ab', 'cd'], html: ['<span>ab</span>', '<span>cd</span>'] },
    measured_asset_placements: [{
      object_id: 'fixture:probe', source_id: 'fixture.bench', units: 'pixel',
      left: 10, top: 20, width: 30, height: 15,
      glyphs: [
        { glyph: '&', x: 10, y: 20, color: '#c00' },
        { glyph: 'M', x: 17.5, y: 20, color: null },
      ],
    }],
    aria_label: 'A bare-surface garden.',
    // The painter is FORBIDDEN from the diagnostics (that is where the
    // logical grapheme runs live). A proxy records any read.
    diagnostics: new Proxy({}, { get() { diagnosticsRead += 1; return undefined; } }),
  };
  const surface = { element: bareNode(), rows: [], rowHtml: [] };
  const changed = withBareDocument(() => live.paintPresentationFrame(frame, surface));

  assert.deepEqual(changed, [0, 1], 'both rows were painted and reported changed');
  assert.deepEqual(surface.rows.map(row => row.textContent), ['ab', 'cd']);
  assert.equal(surface.element.style.background, frame.background.css);
  assert.equal(surface.element.style.color, '#123456');
  assert.equal(surface.element.attributes['aria-label'], 'A bare-surface garden.');
  assert.ok(surface.measuredLayer, 'the painter created the measured overlay itself');
  assert.ok(surface.measuredLayer.innerHTML.includes('left:10.00px;top:20.00px;color:#c00'));
  assert.ok(surface.measuredLayer.innerHTML.includes('left:17.50px;top:20.00px'));
  assert.ok(surface.measuredLayer.innerHTML.includes('&amp;'),
    'overlay glyphs are escaped from frame data, not trusted as markup');
  assert.deepEqual(surface.measuredAssetRects.get('fixture:probe'),
    { x: 10, y: 20, width: 30, height: 15 });
  assert.equal(diagnosticsRead, 0,
    'the painter read the diagnostics: placement is being re-decided at paint time');
});

test('the live composer resolves measured pixel placement, and its frame paints bare', async () => {
  const live = await import('../../web/garden-presentation.mjs');
  const { readFileSync } = await import('node:fs');
  const { createGeometry } = await import('../../web/garden-geometry.mjs');
  const authority = JSON.parse(readFileSync(
    new URL('../../web/garden-accepted-paint.v1.json', import.meta.url), 'utf8',
  ));
  // A REAL measuring geometry (the same construction the browser uses), fed
  // by a deterministic measurer, handed to composition through the public
  // context -- the knowledge that used to be renderer-private.
  const widths = new Map([['i', 3], ['M', 11]]);
  const measurer = {
    ensureFont: font => ({ ready: true, font }),
    advance: text => [...text].reduce((sum, glyph) => sum + (widths.get(glyph) ?? 7), 0),
    prefixWidths(text) {
      let sum = 0;
      return [...text].map(glyph => (sum += widths.get(glyph) ?? 7));
    },
    fontSize: () => 15,
    clearCaches() {},
  };
  const geometry = createGeometry({
    measurer, font: "400 15px 'LateLetter Garden'", lineHeight: 15,
  });
  const projection = {
    world_id: 'placement-proof',
    observed_time: 1750000000,
    scene: { sky_mode: 'storybook_fallback', season: 'summer', story_time: 'day' },
    camera: [0, 0],
    objects: [{
      object_id: 'fixture:bench', kind: 'fixture', semantic_name: 'bench',
      position: [20, 30], depth: 100, hotspot: { x: 20, y: 30, width: 5, height: 2 },
      primary_action: { verb: 'sit', target: 'fixture:bench' },
      semantic_state: { catalog_id: 'bench', presentation_state: 'idle',
        connected_group: null, connected_mask: 0, render_cells: [] },
    }],
  };
  const context = {
    viewport: [90, 34],
    profile: 'browser-proportional',
    presentationGeometry: geometry,
    acceptedManifest: authority,
    environment: { readerRegion: null, reducedMotion: false },
  };
  const state = live.advancePresentationState(null, [], { frame: 24 });
  const frame = live.composePresentationFrame(projection, state, context);

  // The frame owns the placement: pixel-resolved glyphs with identity.
  const placements = frame.measured_asset_placements;
  assert.equal(placements.length, 1, 'the bench resolved to exactly one placement');
  const bench = placements[0];
  assert.equal(bench.object_id, 'fixture:bench');
  assert.equal(bench.source_id, 'fixture.bench');
  assert.equal(bench.units, 'pixel');
  assert.ok(bench.glyphs.length > 5, 'the bench drawing is real, not a token');
  for (const glyph of bench.glyphs) {
    assert.ok(Number.isFinite(glyph.x) && Number.isFinite(glyph.y),
      'every overlay glyph carries its finished pixel position');
  }
  // And the extended contract holds over this measured frame.
  assert.deepEqual(frameViolations(frame, { projection, context }), []);

  // Painting it needs the frame and a bare surface -- nothing else. The spans
  // painted are exactly the placement's glyph count.
  const surface = { element: bareNode(), rows: [], rowHtml: [] };
  withBareDocument(() => live.paintPresentationFrame(frame, surface));
  const spanCount = (surface.measuredLayer.innerHTML.match(/<span /g) ?? []).length;
  assert.equal(spanCount, bench.glyphs.length);
  assert.deepEqual(surface.measuredAssetRects.get('fixture:bench'),
    { x: bench.left, y: bench.top, width: bench.width, height: bench.height });
});

// ---------------------------------------------------------------------------
// Clause 2 — state travels through the public advance; the pair is a
// function of its declared inputs and nothing else.
// ---------------------------------------------------------------------------

test('presentation state accumulates through the signature, not behind it', () => {
  // Tick 80 is divisible by four, so depth grows by one from null state. The
  // growth appears in the RETURNED state; the composer keeps nothing of its
  // own between calls, which is what makes running twice reproducible.
  const tick = { frame: 80, seconds: 1000 };
  const first = advanceReferenceState(null, [], tick);
  assert.equal(first.snowDepth, 1);
  const second = advanceReferenceState(first, [], tick);
  assert.equal(second.snowDepth, 2);
  const shallow = composeReferenceFrame(REFERENCE_PROJECTION, first, REFERENCE_CONTEXT);
  const deep = composeReferenceFrame(REFERENCE_PROJECTION, second, REFERENCE_CONTEXT);
  assert.ok(deep.visible_primitives.length > shallow.visible_primitives.length,
    'deeper snow paints more primitives');
});

test('hover enters through presentation events and changes the picture only', () => {
  const tick = { frame: 1, seconds: 10 };
  const away = advanceReferenceState(null, [], tick);
  const over = advanceReferenceState(null, [
    { kind: 'pointer-move', cell: { x: 4, y: 2 } },
  ], tick);
  const awayFrame = composeReferenceFrame(REFERENCE_PROJECTION, away, REFERENCE_CONTEXT);
  const overFrame = composeReferenceFrame(REFERENCE_PROJECTION, over, REFERENCE_CONTEXT);
  const emphasis = frame => frame.visible_primitives.filter(p => p.color_role === 'emphasis');
  assert.equal(emphasis(awayFrame).length, 0);
  assert.ok(emphasis(overFrame).length > 0, 'hovering the plant emphasized its ink');
  // The regions do not move under hover: hover changes the picture, not the
  // targets, and certainly not the world.
  assert.deepEqual(awayFrame.interaction_regions, overFrame.interaction_regions);
});

test('an implementation that keeps state of its own is refused', () => {
  let hidden = 0;
  const drifting = (projection, state, context) => {
    hidden += 1;                       // the state that is not in the signature
    const frame = composeReferenceFrame(projection, state, context);
    frame.attempted_primitives = [...frame.attempted_primitives, {
      units: 'cell', profile: 'ascii-safe', painter_order: 900 + hidden,
      x: hidden, y: 0, glyph: '*', color_role: 'snow',
      source_id: REFERENCE_IDS.snowRecipe, object_id: null,
    }];
    return frame;
  };
  const problems = composerViolations(advanceReferenceState, drifting, referenceInput());
  assert.ok(problems.some(p => p.clause === '2-determinism'));
});

test('an implementation that reads the hostname is refused', () => {
  // This is the mechanism that makes `allowUnacceptedArt` impossible to
  // reintroduce rather than merely forbidden: paint authority is an input,
  // so a composer that consults where it is running composes a different
  // picture when the ground is moved underneath it, and the clause catches
  // that.
  const hostSniffing = (projection, state, context) => {
    const frame = composeReferenceFrame(projection, state, context);
    if (globalThis.location?.hostname !== 'localhost') {
      const keep = p => p.source_id !== REFERENCE_IDS.snowRecipe;
      frame.attempted_primitives = frame.attempted_primitives.filter(keep);
      frame.visible_primitives = frame.visible_primitives.filter(keep);
    }
    return frame;
  };
  const problems = composerViolations(advanceReferenceState, hostSniffing, referenceInput());
  assert.ok(problems.some(p => /hostname changed/.test(p.detail)),
    'a composer decided what to paint from where it was running');
});

test('a broken frame shape is reported as a sentence, not a TypeError', () => {
  const broken = { advance: () => null, compose: () => undefined };
  assert.deepEqual(contractViolations(broken, referenceInput()),
    [{ clause: 'shape', detail: 'composer returned undefined, not a frame object' }]);
  const noRegions = contractViolations(
    { advance: () => null, compose: () => ({ attempted_primitives: [], visible_primitives: [] }) },
    referenceInput(),
  );
  assert.ok(noRegions.some(p => /interaction_regions is not an array/.test(p.detail)));
});

// ---------------------------------------------------------------------------
// The LIVE owner, held to the same contract as the reference implementation.
// ---------------------------------------------------------------------------

test('the live GardenPresentation owner conforms, composing real accepted art', async () => {
  // The tripwire that used to stand here asserted that the renderer exposed
  // no composer, pinning the pre-transfer gap. The ownership patch landed:
  // web/garden-presentation.mjs is the public owner, so the honest test is
  // now conformance of the REAL functions composing a REAL scene under the
  // REAL committed paint authority -- not a fixture standing in for them.
  const { readFileSync } = await import('node:fs');
  const live = await import('../../web/garden-presentation.mjs');
  const authority = JSON.parse(readFileSync(
    new URL('../../web/garden-accepted-paint.v1.json', import.meta.url), 'utf8',
  ));

  // A small scene made ENTIRELY of accepted identities: two atlas fixtures
  // and one grant-backed legacy plant. Anything unaccepted here would be a
  // contract violation, which is the point -- the live product's default
  // scene is built from exactly these families.
  const projection = {
    world_id: 'contract-live',
    observed_time: 1750000000,
    scene: { sky_mode: 'storybook_fallback', season: 'summer', story_time: 'day' },
    camera: [0, 0],
    objects: [
      {
        object_id: 'fixture:bench', kind: 'fixture', semantic_name: 'bench',
        position: [20, 40], depth: 100, hotspot: { x: 20, y: 40, width: 5, height: 2 },
        primary_action: { verb: 'sit', target: 'fixture:bench' },
        semantic_state: { catalog_id: 'bench', presentation_state: 'idle',
          connected_group: null, connected_mask: 0,
          render_cells: [{ dx: 0, dy: 0, connected_mask: 0 }] },
      },
      {
        object_id: 'plant:oak', kind: 'plant', semantic_name: 'oak',
        position: [50, 40], depth: 100, hotspot: { x: 50, y: 40, width: 3, height: 3 },
        primary_action: null,
        semantic_state: { species_id: 'oak', visible_organ_count: 12,
          connected_group: null, connected_mask: 0 },
      },
    ],
  };
  const context = {
    viewport: [90, 34],
    profile: 'browser-proportional',
    presentationGeometry: { cellAdvance: 8, lineHeight: 15, affineOnly: false },
    acceptedManifest: authority,
    environment: { readerRegion: null, reducedMotion: false },
  };
  const input = {
    projection,
    previousState: null,
    presentationEvents: [],
    tick: { frame: 24, seconds: 360 },
    context,
  };
  assertConforms(
    { advance: live.advancePresentationState, compose: live.composePresentationFrame },
    input,
    'the live GardenPresentation owner',
  );

  // And not vacuously: the frame carries real ink from both identity chains
  // and a region for the declared-interactive bench.
  const state = live.advancePresentationState(null, [], input.tick);
  const frame = live.composePresentationFrame(projection, state, context);
  const inked = frame.visible_primitives.filter(item => item.glyph.trim());
  assert.ok(inked.length > 50, 'the live frame is not empty');
  assert.ok(inked.some(item => item.source_id === 'fixture.bench'));
  assert.ok(inked.some(item => String(item.source_id).startsWith('plant.oak.')));
  assert.ok(inked.some(item => item.source_id === 'recipe.scene.ground_line'));
  assert.ok(frame.interaction_regions.some(region => region.object_id === 'fixture:bench'));
  assert.equal(frame.diagnostics.suppressed, 0,
    'a scene of accepted art suppresses nothing');
});

test('composition refuses when the paint authority is absent or malformed', async () => {
  // Reopened step 1 (2026-08-04 architecture review): a missing manifest
  // used to mean "no restriction", so a slow or failed fetch painted
  // everything. The rule now is refusal -- no frame exists that was not
  // composed under the registers. This pins the refusal for every way the
  // authority can be wrong: absent, null, and present-but-missing-lists.
  const live = await import('../../web/garden-presentation.mjs');
  const projection = {
    world_id: 'refusal-proof',
    observed_time: 1750000000,
    scene: { sky_mode: 'storybook_fallback', season: 'summer', story_time: 'day' },
    camera: [0, 0],
    objects: [],
  };
  const state = live.advancePresentationState(null, [], { frame: 1, seconds: 1 });
  const contextWith = manifest => ({
    viewport: [60, 20],
    profile: 'browser-proportional',
    presentationGeometry: { cellAdvance: 8, lineHeight: 15, affineOnly: false },
    acceptedManifest: manifest,
    environment: { readerRegion: null, reducedMotion: false },
  });
  // Every way the authority can be wrong, including the PARTIAL object the
  // first version of this refusal accepted: three lists with no schema, no
  // registers, no accepted_laws (claim verification, 2026-08-04). The
  // validator is the single owner in web/garden-paint-authority.mjs and
  // mirrors the generator's full shape.
  const broken = [
    undefined,
    null,
    {},
    { accepted_assets: [], accepted_recipes: [] },       // lists missing
    { accepted_assets: [], accepted_recipes: [],         // the old partial
      accepted_legacy_art: [] },                         // three-list shape
    { schema: 2,                                         // wrong schema
      registers: { asset_register: { path: '', sha256: '' },
        recipe_register: { path: '', sha256: '' } },
      accepted_assets: [], accepted_recipes: [],
      accepted_laws: [], accepted_legacy_art: [] },
    { schema: 1,                                         // registers absent
      accepted_assets: [], accepted_recipes: [],
      accepted_laws: [], accepted_legacy_art: [] },
    { schema: 1,                                         // list is not a list
      registers: { asset_register: { path: '', sha256: '' },
        recipe_register: { path: '', sha256: '' } },
      accepted_assets: 'fixture.bench', accepted_recipes: [],
      accepted_laws: [], accepted_legacy_art: [] },
  ];
  for (const manifest of broken) {
    assert.throws(
      () => live.composePresentationFrame(projection, state, contextWith(manifest)),
      /composition refused/,
      `composition proceeded under a broken authority: ${JSON.stringify(manifest)}`,
    );
  }
});

test('the renderer refuses construction without a valid paint authority', async () => {
  // Same rule at the adapter boundary: the viewer must have AWAITED its
  // manifest before a renderer can exist, so a construction with nothing to
  // paint under fails at once instead of composing an ungoverned frame on
  // its first render.
  const { CanonicalGardenRenderer } = await import('../../web/garden-renderer.mjs');
  const element = {
    clientWidth: 320, clientHeight: 150, children: [], attributes: {}, style: {},
    setAttribute() {}, addEventListener() {}, appendChild() {},
    replaceChildren() {}, getBoundingClientRect() { return { left: 0, top: 0 }; },
  };
  for (const paintAuthority of [undefined, null, {}, { accepted_assets: [] }]) {
    assert.throws(
      () => new CanonicalGardenRenderer(element, { paintAuthority }),
      /requires paintAuthority/,
      `a renderer was constructed under ${JSON.stringify(paintAuthority)}`,
    );
  }
});
