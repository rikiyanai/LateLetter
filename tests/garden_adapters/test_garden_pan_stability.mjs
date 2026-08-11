import assert from 'node:assert/strict';
import test from 'node:test';

import { worldToGardenScreen } from '../../web/garden-renderer.mjs';
import { advancePresentationState } from '../../web/garden-presentation.mjs';
import { generateInitialWorld, projectGardenScene } from '../../web/garden-world.mjs';

// Operator complaint (2026-08-11): dragging the camera makes plants and the
// flies above the pond jump around. These tests pin the two mechanisms so the
// repair is falsifiable and a regression cannot ship silently.

const VIEWPORT = [120, 40];

async function summerNoonPondProjection() {
  const state = await generateInitialWorld('fixture-review-room', 'fixture-review-seed', {
    plant_species: [], animal_species: [], collectibles: [],
  });
  const data = await projectGardenScene(state);
  data.scene = { ...data.scene, season: 'summer' };
  data.observed_time = Date.UTC(2026, 6, 22, 12) / 1000;
  return data;
}

function ambientIdentities(lifecycle) {
  return (lifecycle.ambient ?? []).map(actor => actor.kind === 'butterfly'
    ? ['butterfly', actor.angularVelocity, actor.radiusX, actor.radiusY]
    : [actor.kind, actor.on ?? null, actor.off ?? null, actor.phase ?? null])
    .map(identity => identity.join('|')).sort();
}

// A pan is a camera move, not a season change: the ambient actors that existed
// before the step must be the SAME actors afterwards, each within ordinary
// per-tick travel of where it was. Before the repair the lifecycle keyed its
// actor cache on the pond's PROJECTED screen centre and the projected ground
// row, so every one-cell pan re-rolled every butterfly and firefly from the
// RNG — which is exactly the "flies above the pond jump around while
// dragging" defect the operator reported.
test('pond flies survive a one-cell camera pan as the same actors', async () => {
  const data = await summerNoonPondProjection();
  let state = null;
  for (let frame = 0; frame < 30; frame += 1) {
    state = advancePresentationState(state, [
      { kind: 'scene', projection: data, viewport: VIEWPORT },
    ], { frame });
  }
  const before = state.lifecycle;
  assert.ok(before.ambient.length >= 2, 'scenario must actually spawn pond flies');
  const beforeIdentities = ambientIdentities(before);
  const beforePositions = before.ambient.map(actor => [actor.x, actor.y]);

  const panned = { ...data, camera: [data.camera[0] + 1, data.camera[1]] };
  state = advancePresentationState(state, [
    { kind: 'scene', projection: panned, viewport: VIEWPORT },
  ], { frame: 30 });
  const after = state.lifecycle;

  assert.deepEqual(ambientIdentities(after), beforeIdentities,
    'a camera pan regenerated the ambient actors');
  after.ambient.forEach((actor, index) => {
    const [x, y] = beforePositions[index];
    const travel = Math.max(Math.abs(actor.x - x), Math.abs(actor.y - y));
    assert.ok(travel <= 4,
      `actor ${index} teleported ${travel.toFixed(1)} cells across one pan step`);
  });
});

// Two points in the SAME depth layer must keep their projected spacing under
// every camera position: a pan may move the layer, never stretch it. Before
// the repair the projection rounded (point - camera) as one term, so each
// object crossed cell boundaries on its own fractional phase and neighbours
// visibly wobbled ±1 cell against each other during a drag — the "plants jump
// around" defect the operator reported.
test('same-depth points keep their projected spacing under every camera', () => {
  const spacings = new Set();
  const steps = new Set();
  for (let cameraX = 40; cameraX <= 80; cameraX += 1) {
    const camera = [cameraX, 51];
    const left = worldToGardenScreen([50, 70], camera, VIEWPORT, 1);
    const right = worldToGardenScreen([56, 70], camera, VIEWPORT, 1);
    spacings.add(right[0] - left[0]);
    const nextCamera = [cameraX + 1, 51];
    const leftStep = worldToGardenScreen([50, 70], nextCamera, VIEWPORT, 1)[0] - left[0];
    const rightStep = worldToGardenScreen([56, 70], nextCamera, VIEWPORT, 1)[0] - right[0];
    steps.add(`${leftStep}:${rightStep}`);
    assert.equal(leftStep, rightStep,
      `camera ${cameraX}→${cameraX + 1} moved same-depth points by different amounts`);
  }
  assert.equal(spacings.size, 1,
    `projected spacing wobbled across cameras: ${[...spacings].join(', ')}`);
});

// The vertical axis obeys the same law.
test('same-depth points keep their projected row spacing under vertical pan', () => {
  const spacings = new Set();
  for (let cameraY = 40; cameraY <= 62; cameraY += 1) {
    const camera = [60, cameraY];
    const back = worldToGardenScreen([60, 66], camera, VIEWPORT, 1);
    const front = worldToGardenScreen([60, 71], camera, VIEWPORT, 1);
    spacings.add(front[1] - back[1]);
  }
  assert.equal(spacings.size, 1,
    `projected row spacing wobbled across cameras: ${[...spacings].join(', ')}`);
});
