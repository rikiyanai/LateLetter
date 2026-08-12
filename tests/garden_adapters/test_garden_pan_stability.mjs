import assert from 'node:assert/strict';
import test from 'node:test';

import {
  gardenPresentationProfile, layoutGardenObjects, worldToGardenScreen,
} from '../../web/garden-renderer.mjs';
import { advancePresentationState } from '../../web/garden-presentation.mjs';
import { generateInitialWorld, projectGardenScene } from '../../web/garden-world.mjs';

// Operator complaint (2026-08-11): dragging the camera makes plants and the
// flies above the pond jump around. These tests pin the two mechanisms so the
// repair is falsifiable and a regression cannot ship silently.

const VIEWPORT = [120, 40];
const LIVE_DESKTOP_VIEWPORT = [153, 64];

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

// The raw-spacing checks above are necessary but not sufficient. The operator
// reproduced a one-cell pointer drag at camera 46,40 that advanced canonical
// state to 47,40 while the visible Garden outran the pointer. This exercises
// the complete compositor-owned layout path at the same desktop viewport.
//
// The accepted contract (batch operator decision item 8) does NOT promise
// that every camera step paints exactly one column: the viewport fit
// (`xScale`) is part of the accepted composition, so at some widths a step
// legitimately paints one or two columns. What it DOES promise, and what
// this pins: every world-depth object moves by the SAME amount on the same
// step (no relative jumping), the packer's disposable nudge never flips
// during a pan, each step is bounded by the viewport fit, and over a longer
// pan the painted displacement tracks the canonical displacement one-to-one
// within a single cell. One-to-one FEEL under the pointer is owned by the
// viewer's smooth gesture presentation, which settles to canonical cells.
test('full compositor pans world-depth objects rigidly, bounded and one-to-one in aggregate', async () => {
  const state = await generateInitialWorld(
    'recipient-preview', 'lateletter-recipient-preview-v1',
  );
  const projection = await projectGardenScene(state);
  const profile = gardenPresentationProfile(LIVE_DESKTOP_VIEWPORT);
  const stepBound = Math.ceil(profile.xScale);
  const SPAN = 12;
  const layouts = [];
  for (let cameraX = 46; cameraX <= 46 + SPAN; cameraX += 1) {
    layouts.push(layoutGardenObjects(
      { ...projection, camera: [cameraX, 40] }, LIVE_DESKTOP_VIEWPORT,
    ));
  }
  assert.ok(layouts[0].length >= 3, 'scenario must include the accepted composed Garden');

  const worldDepth = entry => Number(entry.object.depth ?? 100) === 100;
  for (let step = 1; step < layouts.length; step += 1) {
    const afterById = new Map(layouts[step].map(entry => [entry.object.object_id, entry]));
    const deltas = new Set();
    for (const left of layouts[step - 1].filter(worldDepth)) {
      const right = afterById.get(left.object.object_id);
      assert.ok(right, `${left.object.object_id} disappeared across one camera step`);
      const beforeNudge = [
        left.anchor[0] - left.baseAnchor[0], left.anchor[1] - left.baseAnchor[1],
      ];
      const afterNudge = [
        right.anchor[0] - right.baseAnchor[0], right.anchor[1] - right.baseAnchor[1],
      ];
      assert.deepEqual(afterNudge, beforeNudge,
        `${left.object.object_id} was repacked during the pan`);
      const delta = right.anchor[0] - left.anchor[0];
      assert.ok(delta <= -1 && delta >= -stepBound,
        `${left.object.object_id} moved ${delta} columns on one step (bound ${stepBound})`);
      deltas.add(delta);
    }
    assert.ok(deltas.size <= 1,
      `world-depth objects moved by different amounts on one step: ${[...deltas].join(', ')}`);
  }

  // Aggregate one-to-one: across the whole pan, painted displacement equals
  // the viewport-fit-scaled canonical displacement within one cell.
  const firstById = new Map(layouts[0].map(entry => [entry.object.object_id, entry]));
  for (const last of layouts[layouts.length - 1].filter(worldDepth)) {
    const first = firstById.get(last.object.object_id);
    if (!first) continue;
    const painted = first.anchor[0] - last.anchor[0];
    assert.ok(Math.abs(painted - SPAN * profile.xScale) <= 1,
      `${last.object.object_id} drifted from one-to-one: ${painted} painted columns over ${SPAN} cells`);
  }
});
