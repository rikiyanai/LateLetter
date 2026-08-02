/**
 * Composition versioning in the browser world.
 * --------------------------------------------
 *
 * This is the side where the defect actually happened. A persisted browser
 * world of 13 plants / 22 fixtures / 4 animals / 8 collectibles was opened in a
 * localhost review and read as the current starter, which generates 2 plants
 * and 5 fixtures. Nothing in the document was false; there was no field able to
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
  // Measured, not quoted. The starter is two plants and five fixtures; an
  // earlier report of this work quoted a historical 8/10/4/3 instead of
  // measuring, which is the same mistake as trusting a version number.
  const world = await generated();
  assert.deepEqual(gardenWorldCensus(world), {
    plants: 2, fixtures: 5, animals: 0, collectibles: 0,
  });
  assert.ok(world.composition_fingerprint.includes('plants=oak,sunflower'));
});

test('the browser and python fingerprints have the same form', async () => {
  // Both languages must produce byte-identical fingerprints, or a world
  // generated in one would read as tampered in the other.
  const world = await generated();
  assert.equal(
    world.composition_fingerprint,
    'plants=oak,sunflower|fixtures=bench,lantern,mailbox,planter,stepping_stones'
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
  const tampered = { ...world, plants: world.plants.slice(0, 1) };
  const origin = characterizeGardenWorld(tampered);
  assert.equal(origin.is_fresh, false);
  assert.ok(origin.reasons.some(r => r.includes('no longer match the stamped composition')));
  assert.notEqual(origin.composition_fingerprint, origin.observed_fingerprint);
});

test('a custom roster does not inherit the starter stamp', async () => {
  const custom = await generateInitialWorld('world-1', 'seed-1', { plant_species: ['oak'] });
  const starter = await generated();
  assert.notEqual(custom.composition_fingerprint, starter.composition_fingerprint);
  assert.equal(characterizeGardenWorld(custom).is_fresh, true, 'fresh, just not the starter');
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
// The runtime: the path where the defect actually happened.
// ---------------------------------------------------------------------------

/**
 * Build a runtime over an in-memory store.
 *
 * @param {string|null} stored - a serialized world to open, or null to generate
 * @returns {GardenRuntime}
 */
function runtimeOver(stored) {
  let value = stored;
  return new GardenRuntime({
    worldId: 'world-1',
    seed: 'seed-1',
    load: async () => value,
    save: async next => { value = next; },
    now: () => 1000,
  });
}

test('opening a stored world records that it was loaded', async () => {
  const world = await generated();
  const runtime = runtimeOver(JSON.stringify(serializeWorldState(world)));
  await runtime.open();
  assert.equal(runtime.loadOrigin, LOAD_STORED);
  assert.equal(runtime.worldOrigin.is_fresh, true, 'lineage is fresh');
});

test('opening with nothing stored records that it was generated', async () => {
  const runtime = runtimeOver(null);
  await runtime.open();
  assert.equal(runtime.loadOrigin, LOAD_GENERATED);
  assert.equal(runtime.worldOrigin.is_fresh, true);
  assert.deepEqual(runtime.worldOrigin.census, {
    plants: 2, fixtures: 5, animals: 0, collectibles: 0,
  });
});

test('a review refuses a loaded world even when its lineage is fresh', async () => {
  // The case a version-stamp check can never catch, and the one a visual review
  // most needs: a perfectly current world that is nonetheless not what the code
  // just produced.
  const world = await generated();
  const runtime = runtimeOver(JSON.stringify(serializeWorldState(world)));
  await runtime.open();
  assert.throws(
    () => runtime.requireFreshCompositionForReview(),
    /not generated in this process/,
  );
});

test('a review accepts a freshly generated world', async () => {
  // The positive control: a refusal-only check proves nothing about whether
  // anything can satisfy it.
  const runtime = runtimeOver(null);
  await runtime.open();
  assert.equal(runtime.requireFreshCompositionForReview().is_fresh, true);
});

test('a review refuses a stored world with no stamps, which is the real defect', async () => {
  // The 13/22/4/8 condition: a current-shape document with nothing recorded
  // about where its contents came from. Before this it rendered silently.
  const document = serializeWorldState(await generated());
  delete document.generator_version;
  delete document.composition_version;
  delete document.composition_fingerprint;
  const runtime = runtimeOver(JSON.stringify(document));
  await runtime.open();
  assert.equal(runtime.worldOrigin.label, 'restored');
  assert.throws(() => runtime.requireFreshCompositionForReview(), /predates version stamping/);
});

test('requireFreshComposition defaults to the strict reading', async () => {
  // A caller that omits the load origin is asserting it generated the world
  // itself. The lenient answer must never be the one you get by forgetting.
  const world = await generated();
  assert.equal(requireFreshComposition(world).is_fresh, true);
  assert.throws(() => requireFreshComposition(world, LOAD_STORED), /not generated/);
});
