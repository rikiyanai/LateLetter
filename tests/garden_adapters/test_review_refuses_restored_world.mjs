/**
 * The invariant, executed on the product path. Nothing else in this file.
 * ----------------------------------------------------------------------
 *
 * > A visual-review entry point must prove it generated the exact current
 * > starter composition in this process, before persistence or projection, and
 * > must refuse everything else.
 *
 * Every earlier attempt at this failed the same way: a mechanism was built, a
 * unit test was written against the mechanism, and the report said the product
 * path enforced it. It did not. The refusal existed as a method nobody called,
 * so a restored world still reconciled, still persisted and still projected --
 * and only a later manual call to the guard threw, long after the picture had
 * been produced.
 *
 * So these tests do not call the guard. They seed storage with a world a review
 * must not see, enter through `GardenRuntime.open` exactly as `viewer-bnw.html`
 * does, and then assert on the SIDE EFFECTS: that nothing was written, that no
 * projection exists, that no state was adopted. A guard that runs one line too
 * late fails here even though every unit test still holds.
 */

import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { dirname, resolve } from 'node:path';

import {
  generateInitialWorld,
  serializeWorldState,
} from '../../web/garden-world.mjs';
import { GardenRuntime } from '../../web/garden-runtime.mjs';

const ROOT = resolve(dirname(fileURLToPath(import.meta.url)), '..', '..');

/**
 * A runtime over an in-memory store that RECORDS every write.
 *
 * The saves array is the evidence. Asserting that it is empty is what proves
 * the refusal happened before persistence -- a claim no amount of reading the
 * source could establish, since the whole failure mode is code that looks
 * right and runs in the wrong order.
 *
 * @param {string|null} stored - the serialized world already in storage
 * @returns {{runtime: GardenRuntime, saves: string[]}}
 */
function runtimeOverStorage(stored) {
  const saves = [];
  let value = stored;
  const runtime = new GardenRuntime({
    worldId: 'world-1',
    seed: 'seed-1',
    load: async () => value,
    save: async next => { saves.push(next); value = next; },
    now: () => 1000,
  });
  return { runtime, saves };
}

/** A stored world in the condition the browser one was found in: no stamps. */
async function restoredWorldWithoutStamps() {
  const document = serializeWorldState(await generateInitialWorld('world-1', 'seed-1'));
  delete document.generator_version;
  delete document.composition_version;
  delete document.composition_fingerprint;
  return JSON.stringify(document);
}

// ---------------------------------------------------------------------------
// The invariant.
// ---------------------------------------------------------------------------

test('a review aborts on a restored world BEFORE saving or projecting', async () => {
  const { runtime, saves } = runtimeOverStorage(await restoredWorldWithoutStamps());

  await assert.rejects(
    () => runtime.open({ composition: 'require_fresh' }),
    /not a fresh composition/,
  );

  // The three side effects the guard exists to prevent. Each is asserted
  // separately, because a guard placed between two of them would satisfy one
  // and not the others, and a single combined assertion would hide which.
  assert.deepEqual(saves, [], 'the restored world was written to storage');
  assert.equal(runtime.projection, null, 'a projection was produced from it');
  assert.equal(runtime.state, null, 'the restored world was adopted as runtime state');
});

test('a review aborts on a stored world that is current but was not generated here', async () => {
  // The subtler half. This world has every stamp current -- its LINEAGE is
  // fresh -- and it still must not be reviewed, because it came out of storage
  // rather than out of this build. No version stamp can record that; only the
  // load origin can.
  const world = await generateInitialWorld('world-1', 'seed-1');
  const { runtime, saves } = runtimeOverStorage(JSON.stringify(serializeWorldState(world)));

  await assert.rejects(
    () => runtime.open({ composition: 'require_fresh' }),
    /not generated in this process/,
  );
  assert.deepEqual(saves, []);
  assert.equal(runtime.projection, null);
});

test('a review opens a world it generated itself, and it is the exact starter', async () => {
  // The positive control. A guard that only ever refuses has not been shown to
  // be satisfiable, and a review that can never run is not a review.
  const { runtime } = runtimeOverStorage(null);
  await runtime.open({ composition: 'require_fresh', persist: false });

  assert.equal(runtime.loadOrigin, 'generated');
  assert.equal(runtime.worldOrigin.is_fresh, true);
  assert.deepEqual(runtime.worldOrigin.census, {
    plants: 2, fixtures: 5, animals: 0, collectibles: 0,
  });
  assert.ok(runtime.projection.objects.length > 0, 'the fresh world projected nothing');
});

test('the product opens a restored world rather than destroying it', async () => {
  // The other direction, and it matters as much. A guard that refused
  // everywhere would delete a recipient's garden -- which is why the policy is
  // stated per call site instead of being one global rule.
  const { runtime, saves } = runtimeOverStorage(await restoredWorldWithoutStamps());
  await runtime.open({ composition: 'accept_restored' });

  assert.equal(runtime.worldOrigin.label, 'restored');
  assert.equal(runtime.worldOrigin.is_fresh, false);
  assert.ok(runtime.projection.objects.length > 0);
  assert.ok(saves.length > 0, 'the recipient world was opened but never written back');
});

// ---------------------------------------------------------------------------
// The policy cannot be omitted, and the viewer states it.
// ---------------------------------------------------------------------------

test('open refuses to run at all without an explicit composition policy', async () => {
  // No default. Whichever one were chosen would be silently wrong for the other
  // caller: a lenient default reviews a restored world, a strict default
  // deletes a recipient's garden.
  const { runtime, saves } = runtimeOverStorage(await restoredWorldWithoutStamps());
  await assert.rejects(() => runtime.open({}), /requires composition/);
  await assert.rejects(() => runtime.open({ composition: 'yes' }), /requires composition/);
  assert.deepEqual(saves, [], 'a rejected policy still reached storage');
});

test('the real viewer states a policy at its open call site', () => {
  // The failure this whole file exists for is a mechanism with no product
  // caller. `viewer-bnw.html` is the product caller; if it stops passing the
  // policy, `open` now throws -- but this asserts the review branch is present
  // rather than both branches having quietly become 'accept_restored'.
  const viewer = readFileSync(resolve(ROOT, 'viewer-bnw.html'), 'utf-8');
  const call = viewer.match(/runtime\.open\(\{[\s\S]{0,240}?\}\)/);
  assert.ok(call, 'viewer-bnw.html no longer calls runtime.open with options');
  assert.ok(call[0].includes('require_fresh'), 'the review branch is gone');
  assert.ok(call[0].includes('accept_restored'), 'the product branch is gone');
});
