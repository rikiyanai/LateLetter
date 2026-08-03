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
// The live renderer, measured against the contract without being changed.
// ---------------------------------------------------------------------------

test('the live renderer does not yet expose the split interface; the transfer step owns that', async () => {
  // The ownership-transfer step of the execution order moves composition into
  // a public GardenPresentation module and holds the LIVE product to this
  // contract. Until that patch lands, `CanonicalGardenRenderer.render`
  // composes and paints in one pass and returns no frame, so there is
  // nothing to apply the contract to -- and this test pins that gap so the
  // transfer cannot half-land: the moment a composer appears in the renderer
  // module, this file must be re-derived to hold it to the contract.
  const module = await import('../../web/garden-renderer.mjs');
  const renderer = module.CanonicalGardenRenderer;
  assert.ok(typeof renderer === 'function', 'the renderer class is exported');
  assert.equal(typeof module.composePresentationFrame, 'undefined',
    'a composer appeared without the contract test being re-derived');
  assert.ok(!Object.getOwnPropertyNames(renderer.prototype).includes('composeFrame'),
    'a composer method appeared without the contract test being re-derived');
});
