import assert from 'node:assert/strict';
import { createHash } from 'node:crypto';
import { readFile } from 'node:fs/promises';
import test from 'node:test';

import {
  APPROVED_STARTER_FLOWER_SPECIES as ART_SPECIES,
  approvedStarterFlowerCatalog,
  approvedStarterFlowerPresentation,
} from '../../web/garden-approved-art.mjs';
import {
  APPROVED_STARTER_FLOWER_SPECIES as WORLD_SPECIES,
  STARTER_FLOWER_POOL,
  LEGACY_ACCEPTED_STARTER_FINGERPRINT,
  generateInitialWorld,
  projectGardenScene,
  upgradeUntouchedLegacyStarter,
} from '../../web/garden-world.mjs';
import {
  advancePresentationState,
  composePresentationFrame,
} from '../../web/garden-presentation.mjs';

const root = new URL('../../', import.meta.url);
const sha256 = value => createHash('sha256').update(value).digest('hex');

test('approved flower pool has one ordered canonical owner and hash-bound static art', async () => {
  const registry = JSON.parse(await readFile(
    new URL('docs/garden-asset-acceptance.json', root), 'utf8',
  ));
  const declared = registry.starter_flower_pool;
  const catalog = approvedStarterFlowerCatalog();
  assert.deepEqual(ART_SPECIES, WORLD_SPECIES);
  assert.deepEqual(ART_SPECIES, STARTER_FLOWER_POOL);
  assert.deepEqual(catalog.map(entry => entry.species), ART_SPECIES);
  assert.deepEqual(declared.entries.map(entry => entry.species_id), ART_SPECIES);
  assert.equal(new Set(ART_SPECIES).size, ART_SPECIES.length);

  for (const [path, expectedSha] of Object.entries(declared.source_files)) {
    const bytes = await readFile(new URL(path, root));
    assert.equal(sha256(bytes), expectedSha, path);
  }
  const registryBySpecies = new Map(
    declared.entries.map(entry => [entry.species_id, entry]),
  );
  for (const entry of catalog) {
    const registered = registryBySpecies.get(entry.species);
    const art = approvedStarterFlowerPresentation(entry.species);
    assert.ok(registered, entry.species);
    assert.equal(entry.identity, registered.asset_id);
    assert.equal(entry.source, registered.source);
    assert.equal(entry.section, registered.section);
    assert.equal(sha256(entry.lines.join('\n')), registered.art_sha256);
    assert.equal(Math.max(...entry.lines.map(line => [...line].length)), registered.width);
    assert.equal(entry.lines.length, registered.height);
    assert.equal(art.sealed, true);
    assert.equal(art.animated, false);
    assert.deepEqual(art.lines, entry.lines);
    assert.ok(registered.width <= 35 && registered.height <= 29, entry.species);
  }
});

test('seed selection is canonical, centered, viewport-free, and stable', async () => {
  const first = await generateInitialWorld('pool:test', 'seeded-flower');
  const second = await generateInitialWorld('pool:test', 'seeded-flower');
  assert.equal(first.plants.length, 1);
  assert.equal(first.fixtures.length, 6);
  assert.ok(STARTER_FLOWER_POOL.includes(first.plants[0].species_id));
  assert.deepEqual(first.plants[0].position, [60, 40]);
  assert.deepEqual(first.ui.camera, first.plants[0].position);
  assert.deepEqual(second, first);
});

test('only an untouched revision-five starter is upgraded', async () => {
  const legacy = await generateInitialWorld('pool:migrate', 'old-seed', {
    plant_species: ['rose'],
  });
  legacy.generator_version = 5;
  legacy.composition_version = 5;
  legacy.composition_fingerprint = LEGACY_ACCEPTED_STARTER_FINGERPRINT;
  legacy.ui.camera = [60, 51];
  const upgraded = await upgradeUntouchedLegacyStarter(legacy, 'old-seed');
  assert.equal(upgraded.generator_version, 6);
  assert.equal(upgraded.composition_version, 7);
  assert.deepEqual(upgraded.ui.camera, upgraded.plants[0].position);
  assert.equal(upgraded.fixtures.length, 6);

  const panned = structuredClone(legacy);
  panned.ui.camera = [59, 51];
  assert.equal(await upgradeUntouchedLegacyStarter(panned, 'old-seed'), panned);
});

test('every approved flower remains visible at desktop, mobile, and phone lattices', async () => {
  const authority = JSON.parse(await readFile(
    new URL('web/garden-accepted-paint.v1.json', root), 'utf8',
  ));
  for (const species of STARTER_FLOWER_POOL) {
    const world = await generateInitialWorld(`pool:viewport:${species}`, 'viewport-seed', {
      plant_species: [species],
    });
    const projection = await projectGardenScene(world);
    for (const viewport of [[160, 66], [49, 56], [40, 37]]) {
      const event = { kind: 'scene', projection, viewport };
      const state = advancePresentationState(null, [event], { frame: 0 });
      const frame = composePresentationFrame(projection, state, {
        viewport,
        profile: 'browser-proportional',
        presentationGeometry: { cellAdvance: 8, lineHeight: 15, affineOnly: false },
        acceptedManifest: authority,
        environment: { readerRegion: null, reducedMotion: true },
      });
      assert.ok(frame.layout.some(entry => entry.object.kind === 'plant'),
        `${species} was culled at ${viewport.join('x')}`);
      assert.ok(frame.visible_primitives.some(item =>
        item.object_id === world.plants[0].plant_id && item.glyph.trim()),
      `${species} had no visible ink at ${viewport.join('x')}`);
    }
  }
});
