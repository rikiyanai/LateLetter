/**
 * Composition versioning in the browser world.
 * --------------------------------------------
 *
 * This is the side where the defect actually happened. A persisted browser
 * world of 13 plants / 22 fixtures / 4 animals / 8 collectibles was opened in a
 * localhost review and read as the current starter. Nothing in the document
 * was false; there was no field able to
 * say "an older generator made me", and nothing in the runtime knew the world
 * had come out of storage at all.
 *
 * These mirror `tests/garden_world/test_composition_versioning.py`, because a
 * review of the browser Garden and a review of the terminal Garden have to mean
 * the same thing by the word "fresh". Several of them exist because a first
 * attempt certified an EMPTY world as an approved fresh composition.
 */

import test from 'node:test';
import assert from 'node:assert/strict';

import {
  COMPOSITION_VERSION,
  GENERATOR_VERSION,
  LOAD_GENERATED,
  LOAD_STORED,
  WORLD_SCHEMA_VERSION,
  characterizeGardenWorld,
  compositionFingerprint,
  deserializeWorldState,
  gardenWorldCensus,
  generateInitialWorld,
  loadMigratedGardenWorld,
  migrateGardenWorldDocument,
  newGardenWorld,
  requireFreshComposition,
  serializeWorldState,
} from '../../web/garden-world.mjs';

import { GardenRuntime } from '../../web/garden-runtime.mjs';

/** The REAL starter, through the real generator -- not `newGardenWorld`. */
function generated() {
  return generateInitialWorld('world-1', 'seed-1');
}

// ---------------------------------------------------------------------------
// What the stamps mean, and what they do not.
// ---------------------------------------------------------------------------

test('a generated world carries all three stamps and a fingerprint', async () => {
  const world = await generated();
  assert.equal(world.schema_version, WORLD_SCHEMA_VERSION);
  assert.equal(world.generator_version, GENERATOR_VERSION);
  assert.equal(world.composition_version, COMPOSITION_VERSION);
  assert.equal(world.composition_fingerprint, compositionFingerprint(world));
});

test('an empty world is not a composition', async () => {
  // `newGardenWorld` returns nothing planted. Stamping there declared 0/0/0/0
  // to be a whole composition, and the characterization then agreed with it.
  const empty = await newGardenWorld('world-1', 'seed-1');
  assert.deepEqual(gardenWorldCensus(empty), {
    plants: 0, fixtures: 0, animals: 0, collectibles: 0,
  });
  assert.equal(empty.generator_version, null);
  assert.equal(empty.composition_version, null);
  assert.equal(empty.composition_fingerprint, null);
  assert.equal(characterizeGardenWorld(empty).is_fresh, false);
});

test('the stamp describes the roster the generator actually produced', async () => {
  // Measured, not quoted. An
  // earlier report of this work quoted a historical 8/10/4/3 instead of
  // measuring, which is the same mistake as trusting a version number.
  const world = await generated();
  assert.deepEqual(gardenWorldCensus(world), {
    plants: 1, fixtures: 6, animals: 0, collectibles: 0,
  });
  // Species AND the authored anchor each was placed against. Names alone were
  // not enough: moving every anchor produces a visibly different garden out of
  // an identical species list.
  assert.ok(world.composition_fingerprint.includes('plants=rose@70,820'));
});

test('the browser and python fingerprints are the same string', async () => {
  // Byte-identical, or a world generated in one language reads as tampered in
  // the other. The expected value is duplicated from the Python test on
  // purpose: two independent literals disagree loudly, where one shared helper
  // would let both drift together.
  const world = await generated();
  assert.equal(
    world.composition_fingerprint,
    'plants=rose@70,820'
    + '|fixtures=bench@400,300,lantern@480,200,mailbox@700,700,planter@850,820,'
    + 'pond@400,900,stepping_stones@300,900'
    + '|animals=|collectibles=',
  );
});

// ---------------------------------------------------------------------------
// The fingerprint: turning an assertion into evidence.
// ---------------------------------------------------------------------------

test('a current stamp over a changed population is caught', async () => {
  // Without this, a world could carry every current stamp over an arbitrary
  // roster and characterize as fresh.
  const world = await generated();
  const tampered = { ...world, fixtures: world.fixtures.slice(0, -1) };
  const origin = characterizeGardenWorld(tampered);
  assert.equal(origin.is_fresh, false);
  assert.ok(origin.reasons.some(r => r.includes('no longer match the stamped composition')));
  assert.notEqual(origin.composition_fingerprint, origin.observed_fingerprint);
});

test('a custom roster does not inherit the starter stamp', async () => {
  const custom = await generateInitialWorld('world-1', 'seed-1', { plant_species: ['oak'] });
  const starter = await generated();
  assert.notEqual(custom.composition_fingerprint, starter.composition_fingerprint);
  assert.equal(custom.composition_version, null, 'a custom roster claimed the named revision');
});

// ---------------------------------------------------------------------------
// Absent stamps, which is the actual historical world.
// ---------------------------------------------------------------------------

test('a world stored before versioning does not claim todays stamps', async () => {
  const document = serializeWorldState(await generated());
  delete document.generator_version;
  delete document.composition_version;
  delete document.composition_fingerprint;

  const restored = deserializeWorldState(document);
  assert.equal(restored.generator_version, null);
  assert.equal(restored.composition_version, null);
  assert.equal(restored.composition_fingerprint, null);

  const origin = characterizeGardenWorld(restored);
  assert.equal(origin.is_fresh, false);
  assert.equal(origin.label, 'restored');
  assert.ok(origin.reasons.some(r => r.includes('predates version stamping')));
  assert.ok(origin.reasons.some(r => r.includes('roster was never recorded')));
});

test('an explicit null stamp is absent, not the integer zero', async () => {
  const document = serializeWorldState(await generated());
  document.generator_version = null;
  assert.equal(deserializeWorldState(document).generator_version, null);
});

// ---------------------------------------------------------------------------
// Migration: a real transform, or a refusal.
// ---------------------------------------------------------------------------

test('an unregistered older schema is refused, not renumbered', async () => {
  // Schema 1 is the only shape this project has written, so there is no
  // transform to run and nothing honest to do with a document claiming an
  // older one.
  const document = serializeWorldState(await generated());
  document.schema_version = WORLD_SCHEMA_VERSION - 1;
  assert.throws(() => migrateGardenWorldDocument(document), /no migration is registered/);
});

test('a document from a newer build is refused rather than downgraded', async () => {
  const document = serializeWorldState(await generated());
  document.schema_version = WORLD_SCHEMA_VERSION + 1;
  assert.throws(() => migrateGardenWorldDocument(document), /newer build/);
});

test('a current document loads and reports that it was loaded', async () => {
  const document = serializeWorldState(await generated());
  const { state, loadOrigin } = loadMigratedGardenWorld(document);
  assert.equal(loadOrigin, LOAD_STORED);
  assert.equal(characterizeGardenWorld(state).is_fresh, true, 'its LINEAGE is fresh');
});

// ---------------------------------------------------------------------------
// The runtime path is NOT tested here.
//
// It is tested in tests/garden_adapters/test_review_refuses_restored_world.mjs,
// which enters through `GardenRuntime.open` exactly as viewer-bnw.html does and
// asserts on the side effects -- nothing saved, nothing projected, no state
// adopted. Duplicating a weaker version of that here would give the two places
// to disagree, and the weaker one would be the one that kept holding.
// ---------------------------------------------------------------------------

test('requireFreshComposition demands an explicit, known load origin', async () => {
  // The permissive answer must never be the one you get by forgetting. An
  // earlier version defaulted this to 'generated', so a caller who omitted it
  // certified a loaded world as newly generated.
  const world = await generated();
  assert.throws(() => requireFreshComposition(world), /unknown load origin/);
  assert.throws(() => requireFreshComposition(world, 'probably'), /unknown load origin/);
  assert.equal(requireFreshComposition(world, LOAD_GENERATED).is_fresh, true);
  assert.throws(() => requireFreshComposition(world, LOAD_STORED), /not generated/);
});

test('a custom roster is not the named composition and cannot be reviewed', async () => {
  // A number every roster receives identifies nothing. An earlier version
  // stamped the same revision on every successful generation, so a one-oak
  // roster read as the current composition.
  const custom = await generateInitialWorld('world-1', 'seed-1', { plant_species: ['oak'] });
  assert.equal(custom.composition_version, null);
  const origin = characterizeGardenWorld(custom);
  assert.equal(origin.is_fresh, false, 'a non-starter population was certified as fresh');
  assert.throws(() => requireFreshComposition(custom, LOAD_GENERATED), /no composition_version/);
});
