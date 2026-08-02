/**
 * The presentation contract, executed.
 * ------------------------------------
 *
 * Route step 1 asked for the Garden's presentation contract to be DEFINED
 * rather than inferred from source text. This file is where that definition is
 * exercised: a reference composer is run and required to conform, then each
 * clause is broken on purpose and required to be caught, and finally the live
 * renderer is measured against the same contract without being changed.
 *
 * The order matters. A checker that has only ever refused things has not been
 * shown to be satisfiable, and a checker that accepts one good case has not
 * been shown to refuse anything. Both halves are here, for every clause.
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
  composeReferenceFrame,
  REFERENCE_MANIFEST,
  REFERENCE_PROJECTION,
  REFERENCE_VIEWPORT,
} from '../garden_contract/fixtures/reference_composer.mjs';

/**
 * Build the five contract inputs.
 *
 * @param {object} [overrides] - replace any input for a negative control
 * @returns {object} the input object a composer receives
 */
function referenceInput(overrides = {}) {
  return {
    projection: REFERENCE_PROJECTION,
    viewport: REFERENCE_VIEWPORT,
    presentationTime: { seconds: 1000, frame: 8 },
    presentationState: { snowDepth: 1 },
    acceptedManifest: REFERENCE_MANIFEST,
    ...overrides,
  };
}

/**
 * Compose a reference frame and then damage it, so a clause can be tested
 * against a frame that is correct in every other respect.
 *
 * @param {(frame: object) => void} damage - mutates the composed frame
 * @returns {object} the damaged frame
 */
function damagedFrame(damage) {
  const frame = composeReferenceFrame(referenceInput());
  damage(frame);
  return frame;
}

// ---------------------------------------------------------------------------
// The positive control: the contract is satisfiable by code that runs.
// ---------------------------------------------------------------------------

test('the reference composer satisfies every clause of the contract', () => {
  assertConforms(composeReferenceFrame, referenceInput(), 'the reference composer');
});

test('the reference composer emits ink, so conformance is not vacuous', () => {
  // A composer that returns no cells satisfies every per-cell clause by having
  // nothing to check. Requiring real ink is what keeps the positive control
  // from being empty.
  const frame = composeReferenceFrame(referenceInput());
  const ink = frame.cells.filter(cell => cell.glyph !== ' ' && cell.glyph !== '');
  assert.ok(ink.length > 10, `only ${ink.length} inked cells`);
  assert.ok(ink.some(cell => cell.objectId), 'no atlas-chain ink carrying an object id');
  assert.ok(ink.some(cell => !cell.objectId), 'no recipe-chain ink');
  assert.equal(frame.interactionRegions.length, 1, 'exactly the one interactive object gets a region');
  assert.equal(frame.interactionRegions[0].objectId, 'plant-1');
});

// ---------------------------------------------------------------------------
// Clause 1 — identity.
// ---------------------------------------------------------------------------

test('a nonblank cell with no source id is refused', () => {
  const frame = damagedFrame(f => { f.cells[0].sourceId = null; });
  const problems = frameViolations(frame, referenceInput());
  assert.ok(problems.some(p => p.clause === '1-identity' && /carries no sourceId/.test(p.detail)));
});

test('a blank cell needs no source id', () => {
  // The exemption is about INK, not about who wrote the cell. A composer that
  // clears a cell has not painted anything that could need review.
  const frame = damagedFrame(f => {
    f.cells.push({ x: 11, y: 0, glyph: ' ', color: null, animated: false, sourceId: null, objectId: null });
  });
  assert.deepEqual(frameViolations(frame, referenceInput()), []);
});

test('a law may not be named as a cell source', () => {
  const frame = damagedFrame(f => { f.cells[0].sourceId = 'law.reference.density'; });
  const problems = frameViolations(frame, referenceInput());
  assert.ok(problems.some(p => /names the law/.test(p.detail)),
    'a law id passed as a cell source: anonymity with a respectable id attached');
});

test('an id in neither register is refused', () => {
  const frame = damagedFrame(f => { f.cells[0].sourceId = 'recipe.invented.on.the.spot'; });
  const problems = frameViolations(frame, referenceInput());
  assert.ok(problems.some(p => /in neither register/.test(p.detail)));
});

test('recipe-chain ink may not claim a canonical object', () => {
  const frame = damagedFrame(f => {
    const ground = f.cells.find(cell => cell.sourceId === 'recipe.reference.ground');
    ground.objectId = 'plant-1';
  });
  const problems = frameViolations(frame, referenceInput());
  assert.ok(problems.some(p => /recipe paint yet claims object/.test(p.detail)));
});

test('atlas ink may not claim an object the projection does not contain', () => {
  const frame = damagedFrame(f => {
    const plant = f.cells.find(cell => cell.objectId === 'plant-1');
    plant.objectId = 'plant-99';
  });
  const problems = frameViolations(frame, referenceInput());
  assert.ok(problems.some(p => /absent from the projection/.test(p.detail)));
});

// ---------------------------------------------------------------------------
// Clause 2 — release paint authority.
// ---------------------------------------------------------------------------

test('ink from an unaccepted source is refused', () => {
  const input = referenceInput({
    acceptedManifest: {
      ...REFERENCE_MANIFEST,
      // The snow recipe is still a known recipe -- it is simply not accepted,
      // which is a different fact from being unknown and gets a different
      // sentence.
      acceptedIds: ['recipe.reference.ground', 'asset.reference.plant'],
    },
  });
  const frame = composeReferenceFrame(input);
  const problems = frameViolations(frame, input);
  assert.ok(problems.some(p => p.clause === '2-authority' && /not accepted/.test(p.detail)));
});

test('a composition with no manifest asserts no authority at all', () => {
  // Diagnostic and authoring compositions legitimately paint unreviewed art.
  // The clause is skipped rather than failed, and the RELEASE check is the
  // caller that always supplies the manifest.
  const input = referenceInput({
    acceptedManifest: { ...REFERENCE_MANIFEST, acceptedIds: undefined },
  });
  const frame = composeReferenceFrame(input);
  assert.ok(!frameViolations(frame, input).some(p => p.clause === '2-authority'));
});

// ---------------------------------------------------------------------------
// Clause 3 — interaction regions owned by the projection.
// ---------------------------------------------------------------------------

test('a region for an object the projection does not contain is refused', () => {
  const frame = damagedFrame(f => {
    f.interactionRegions.push({ objectId: 'ghost-1', x: 0, y: 0, width: 44, height: 44, primary: null });
  });
  const problems = frameViolations(frame, referenceInput());
  assert.ok(problems.some(p => /the projection does not contain/.test(p.detail)));
});

test('visible interactive ink with no region is refused', () => {
  const frame = damagedFrame(f => { f.interactionRegions.length = 0; });
  const problems = frameViolations(frame, referenceInput());
  assert.ok(problems.some(p => /painted visible ink and declares a primary action/.test(p.detail)),
    'the picture showed something a person cannot touch');
});

test('a region under the 44px floor is refused', () => {
  const frame = damagedFrame(f => { f.interactionRegions[0].height = 20; });
  const problems = frameViolations(frame, referenceInput());
  assert.ok(problems.some(p => p.detail.includes(`${MINIMUM_TARGET_PX}px floor`)));
});

test('a non-interactive projected object gets no region and that is not a defect', () => {
  // `stone-1` is projected and declares no primary action. The clause must not
  // demand a target for it, or every scenery object becomes a click surface.
  const frame = composeReferenceFrame(referenceInput());
  assert.ok(!frame.interactionRegions.some(region => region.objectId === 'stone-1'));
  assert.deepEqual(frameViolations(frame, referenceInput()), []);
});

// ---------------------------------------------------------------------------
// Clause 4 — the composer is a function of its five inputs and nothing else.
// ---------------------------------------------------------------------------

test('presentation state accumulates through the signature, not behind it', () => {
  // Frame 8 is divisible by four, so depth grows by one. The growth appears in
  // the RETURNED state; the composer keeps nothing of its own between calls,
  // which is what makes composing twice from one input reproducible.
  const first = composeReferenceFrame(referenceInput());
  assert.equal(first.nextPresentationState.snowDepth, 2);
  const second = composeReferenceFrame(referenceInput({ presentationState: first.nextPresentationState }));
  assert.equal(second.nextPresentationState.snowDepth, 3);
  assert.ok(second.cells.length > first.cells.length, 'deeper snow paints more cells');
});

test('a composer that keeps state of its own is refused', () => {
  let hidden = 0;
  const drifting = input => {
    hidden += 1;                       // the state that is not in the signature
    const frame = composeReferenceFrame(input);
    frame.cells.push({
      x: hidden, y: 0, glyph: '*', color: '#fff', animated: false,
      sourceId: 'recipe.reference.snow', objectId: null,
    });
    return frame;
  };
  const problems = composerViolations(drifting, referenceInput());
  assert.ok(problems.some(p => p.clause === '4-determinism'));
});

test('a composer that reads the hostname is refused', () => {
  // This is the mechanism that makes `allowUnacceptedArt` impossible to
  // reintroduce rather than merely forbidden: paint authority is an input, so
  // a composer that consults where it is running composes a different picture
  // when the ground is moved underneath it, and the clause catches that.
  const hostSniffing = input => {
    const frame = composeReferenceFrame(input);
    if (globalThis.location?.hostname !== 'localhost') {
      frame.cells = frame.cells.filter(cell => cell.sourceId !== 'recipe.reference.snow');
    }
    return frame;
  };
  const problems = composerViolations(hostSniffing, referenceInput());
  assert.ok(problems.some(p => /hostname changed/.test(p.detail)),
    'a composer decided what to paint from where it was running');
});

test('a broken frame shape is reported as a sentence, not a TypeError', () => {
  assert.deepEqual(contractViolations(() => undefined, referenceInput()),
    [{ clause: 'shape', detail: 'composer returned undefined, not a frame object' }]);
  const noRegions = contractViolations(() => ({ cells: [], nextPresentationState: null }), referenceInput());
  assert.ok(noRegions.some(p => /interactionRegions is not an array/.test(p.detail)));
});

// ---------------------------------------------------------------------------
// The live renderer, measured against the contract without being changed.
// ---------------------------------------------------------------------------

test('the live renderer does not yet expose a composer, and that is the step 1 finding', async () => {
  // Route step 1 changes no rendering. What it produces is a contract and an
  // honest measurement against it. `CanonicalGardenRenderer.render(projection)`
  // composes and paints in one pass and returns nothing, so there is no frame
  // to apply the contract to -- which is precisely the gap step 4 closes by
  // splitting composition from painting.
  const module = await import('../../web/garden-renderer.mjs');
  const renderer = module.CanonicalGardenRenderer;
  assert.ok(typeof renderer === 'function', 'the renderer class is exported');
  assert.equal(typeof module.composePresentationFrame, 'undefined',
    'a composer appeared without the contract test being re-derived');
  assert.ok(!Object.getOwnPropertyNames(renderer.prototype).includes('composeFrame'),
    'a composer method appeared without the contract test being re-derived');
});
