import assert from 'node:assert/strict';
import test from 'node:test';
import { existsSync, readFileSync } from 'node:fs';

import {
  LEGACY_ANIMAL_SPECIES, LEGACY_ART_PROVENANCE, LEGACY_PLANT_SPECIES,
  legacyAnimalFrameSet, legacyPlantFrameSet,
} from '../../web/garden-legacy-art.mjs';

import {
  CanonicalGardenRenderer, ambientEntityPosition,
  AMBIENT_BIRD_FRAMES, AMBIENT_BIRD_COMPACT_FRAMES, ambientBirdSpawns, drawSkyLife,
  Raster, DAY,
  animalPoseFamily, connectedMasks, gardenGroundY, gardenPresentationProfile,
  layoutGardenObjects, measuredAssetPlacement,
  objectBurstPattern, skyCloudPresentation,
  weatherParticlePosition, worldToGardenScreen,
} from '../../web/garden-renderer.mjs';
import { createGeometry } from '../../web/garden-geometry.mjs';
import {
  ANIMAL_DELIVERY_FRAMES,
  ATLAS_MANIFEST,
  LETTERBIRD_DELIVERY_FRAMES,
  connectedGlyph,
  deliveryFramesFor,
  glyphForProjection,
} from '../../web/garden-atlas.mjs';
import {
  BRIGHT_STAR_CATALOG, altAz, greenwichApparentSiderealTime, quantizeRoughLocation,
  projectSkyPoints, requestRoughSkyLocation,
} from '../../web/garden-sky.mjs';
import {
  REVIEW_PENDING_ANIMAL_SPECIES,
  REVIEW_PENDING_COLLECTIBLES,
  REVIEW_PENDING_PLANT_SPECIES,
  generateInitialWorld,
  projectGardenScene,
} from '../../web/garden-world.mjs';

// Reopened step 1 (2026-08-04 architecture review): paint authority is
// MANDATORY -- the renderer refuses to construct without the accepted-paint
// manifest, exactly as the product refuses when its manifest fetch fails.
// Every test renderer therefore composes under the committed product
// manifest, the same file the viewer fetches, so what these tests see is
// what a recipient sees. Inspecting unaccepted ink is still possible one
// level down, with a bare Raster and the painters; what no longer exists is
// a composed frame outside the registers' authority.
const COMMITTED_PAINT_AUTHORITY = JSON.parse(readFileSync(
  new URL('../../web/garden-accepted-paint.v1.json', import.meta.url), 'utf8'));

// Constructs a renderer under the committed authority; an explicit
// `paintAuthority` in `options` (the empty-authority test) still wins.
function rendererUnderAuthority(element, options = {}) {
  return new CanonicalGardenRenderer(element,
    { paintAuthority: COMMITTED_PAINT_AUTHORITY, ...options });
}

/**
 * The attempted ink recorded for one object, as [x, y, glyph, suppressed].
 *
 * Reopened step 1 made paint authority mandatory, so a machinery test can no
 * longer read unaccepted ink off the visible lines -- and should not:
 * visibility belongs to the registers, while these tests pin the MACHINERY.
 * The raster's attempted log records every write with its glyph, identity
 * and suppression verdict, so asserting on it proves the painters did their
 * exact work independently of what the manifest let through -- and lets the
 * same test pin that unaccepted ink was in fact suppressed.
 */
function attemptedInkOf(frame, objectId) {
  return frame.attempted_primitives
    .filter(item => item.object_id === objectId && item.glyph.trim() !== '')
    .map(item => [item.x, item.y, item.glyph, item.suppressed]);
}

class FakeRow {
  constructor() { this.textContent = ''; this.innerHTML = ''; this.attributes = {}; }
  setAttribute(key, value) { this.attributes[key] = value; }
  remove() {}
}

class FakeElement {
  constructor() { this.clientWidth = 320; this.clientHeight = 150; this.children = []; this.attributes = {}; this.style = {}; }
  setAttribute(key, value) { this.attributes[key] = value; }
  addEventListener(kind, callback) { this.listener = kind === 'click' ? callback : this.listener; }
  appendChild(child) { this.children.push(child); }
  replaceChildren() { this.children = []; }
  getBoundingClientRect() { return { left: 0, top: 0 }; }
}

test('renderer places atlas rows from measured prefixes, never column pitch', () => {
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
  const placed = measuredAssetPlacement(geometry, {
    objectId: 'fixture:probe', anchor: [10, 4], artAnchor: [0, 0],
    lines: ['iM', 'Mi'], color: '#111', accents: { '1,1': '#c00' },
  });

  assert.equal(geometry.cellAdvance, 11);
  assert.deepEqual(placed.glyphs.map(glyph => [glyph.glyph, glyph.x, glyph.y]), [
    ['i', 110, 60], ['M', 113, 60],
    ['M', 110, 75], ['i', 121, 75],
  ]);
  assert.equal(placed.glyphs[3].color, '#c00');
  assert.deepEqual(
    { left: placed.left, top: placed.top, width: placed.width, height: placed.height },
    { left: 110, top: 60, width: 14, height: 30 },
  );
  assert.notEqual(placed.glyphs[1].x, 110 + geometry.cellAdvance,
    'a fixed column pitch would put M at 121px instead of the measured 113px prefix');
});

globalThis.document = { createElement: () => new FakeRow() };

function projection() {
  return {
    world_id: 'proof', effective_time: 10, camera: [10, 5], motion_paused: false,
    scene: { sky_mode: 'storybook_fallback' },
    objects: [
      { object_id: 'plant:a', kind: 'plant', semantic_name: 'rose', position: [10, 5],
        depth: 100, hotspot: { x: 10, y: 5, width: 1, height: 1 },
        semantic_state: { species_id: 'rose', visible_organs: [
          { node_id: 'root', parent_id: null, kind: 'root', offset: [0, 0] },
          { node_id: 'bloom', parent_id: 'root', kind: 'bloom', offset: [0, 1] },
        ] } },
      { object_id: 'fence:a', kind: 'fixture', semantic_name: 'fence', position: [11, 5],
        depth: 100, hotspot: { x: 11, y: 5, width: 1, height: 1 },
        semantic_state: { catalog_id: 'fence', connected_group: 'fence',
          connected_mask: 2, render_cells: [{ dx: 0, dy: 0, connected_mask: 2 }] } },
      { object_id: 'fence:b', kind: 'fixture', semantic_name: 'fence', position: [12, 5],
        depth: 100, hotspot: { x: 12, y: 5, width: 1, height: 1 },
        semantic_state: { catalog_id: 'fence', connected_group: 'fence',
          connected_mask: 8, render_cells: [{ dx: 0, dy: 0, connected_mask: 8 }] } },
    ],
  };
}

function projectionCenteredOn(objectId, { isolate = false } = {}) {
  const data = projection();
  const target = data.objects.find(object => object.object_id === objectId);
  assert.ok(target, `missing projection fixture ${objectId}`);
  data.camera = [...target.position];
  if (isolate) data.objects = [target];
  return data;
}

function expectedSharedFeature(left, right) {
  const fixture = object => object.kind === 'fixture'
    ? String(object.semantic_state?.catalog_id ?? '') : '';
  const plant = object => object.kind === 'plant'
    ? String(object.semantic_state?.species_id ?? '') : '';
  const fixturePair = new Set([fixture(left), fixture(right)]);
  if (fixturePair.size === 2 && fixturePair.has('pond') && fixturePair.has('bridge')) return true;
  return (fixture(left) === 'pond' && plant(right) === 'water_lily') ||
    (fixture(right) === 'pond' && plant(left) === 'water_lily');
}

test('ambient presentation follows stable adjacent-frame trajectories', () => {
  const width = 120, horizon = 60, span = width + 4;
  for (let index = 0; index < 18; index += 1) {
    for (let frame = 0; frame < 96; frame += 1) {
      const before = ambientEntityPosition('motion-proof', index, frame, width, horizon);
      const after = ambientEntityPosition('motion-proof', index, frame + 1, width, horizon);
      const dx = Math.abs(after[0] - before[0]);
      assert.ok(Math.min(dx, span - dx) <= 1, `ambient x jumped at ${index}:${frame}`);
      assert.ok(Math.abs(after[1] - before[1]) <= 1, `ambient y jumped at ${index}:${frame}`);
    }
  }
});

test('weather moves continuously until a particle exits and respawns', () => {
  const width = 120, horizon = 60;
  for (const kind of ['rain', 'snow', 'leaves']) {
    for (let index = 0; index < 20; index += 1) {
      for (let frame = 0; frame < 120; frame += 1) {
        const before = weatherParticlePosition('weather-proof', index, frame, width, horizon, kind);
        const after = weatherParticlePosition('weather-proof', index, frame + 1, width, horizon, kind);
        if (after[1] !== 0) assert.ok(Math.abs(after[0] - before[0]) <= 1,
          `${kind} x jumped mid-flight at ${index}:${frame}`);
        const dy = Math.abs(after[1] - before[1]);
        assert.ok(Math.min(dy, horizon - dy) <= 1, `${kind} y jumped at ${index}:${frame}`);
      }
    }
  }
});

// REWRITTEN 2026-07-31, from three tests that required the receding ground
// plane the operator rejected.
//
// They asserted that world depth spread objects over at least eight rows, that
// layout spread them over at least twelve, and that a camera moved far in
// depth culled everything. All three were true of the old plane and all three
// are false of a single surface -- not because the surface is broken, but
// because those numbers WERE the rejected composition, written down as a pass
// condition. Left in place they would have blocked the change the operator
// asked for while reporting a green suite.
//
// What survives is what is still true regardless of composition: layout does
// not mutate the projection it reads, depth scaling has no magic constant, and
// horizontal culling still removes what the camera cannot see. Nothing here
// asserts a row count, because the right row count is exactly the open
// question. A depth assertion belongs here again once a composition is
// accepted.

test('projection is pure and free of hidden depth constants', () => {
  const data = projection(), objects = [];
  for (let index = 0; index < 5; index += 1) {
    const object = structuredClone(data.objects[0]);
    object.object_id = `plant:${index}`;
    object.position = [10 + index * 8, index * 20];
    object.hotspot = { x: object.position[0], y: object.position[1], width: 1, height: 1 };
    objects.push(object);
  }
  data.camera = [26, 40]; data.objects = objects;
  const before = structuredClone(data);
  layoutGardenObjects(data, [160, 48]);
  assert.deepEqual(data, before);
  assert.doesNotMatch(readFileSync(new URL('../../web/garden-renderer.mjs', import.meta.url), 'utf8'),
    /GROUND_DEPTH_SCALE/);
});

test('every object stands on the single painted soil line', () => {
  // The defect this exists to catch: paint one row, place feet on another, and
  // the scene renders fixtures standing on nothing. Tying both to
  // `groundFront` in one assertion means they cannot drift apart again.
  const viewport = [160, 48];
  const profile = gardenPresentationProfile(viewport);
  assert.equal(profile.groundBack, profile.groundFront);
  assert.equal(profile.groundSpan, 0);
  assert.equal(profile.yScale, 0);
  const data = projection(), objects = [];
  for (let index = 0; index < 5; index += 1) {
    const object = structuredClone(data.objects[0]);
    object.object_id = `plant:${index}`;
    object.position = [10 + index * 8, index * 20];
    object.hotspot = { x: object.position[0], y: object.position[1], width: 1, height: 1 };
    objects.push(object);
  }
  data.camera = [26, 40]; data.objects = objects;
  const layout = layoutGardenObjects(data, viewport);
  assert.equal(layout.length, objects.length);          // depth culls nothing now
  for (const entry of layout) assert.equal(entry.groundRow, profile.groundFront);
  // World depth no longer moves anything vertically, at any depth multiplier.
  assert.equal(
    worldToGardenScreen([40, 0], [40, 40], viewport)[1],
    worldToGardenScreen([40, 60], [40, 40], viewport)[1],
  );
});

test('compositor still culls objects the camera cannot see horizontally', () => {
  const data = projection();
  data.objects = [data.objects[0]];
  assert.equal(layoutGardenObjects(data, [80, 40]).length, 1);
  // Vertical culling is inactive while the plane is one line -- every object
  // is on it. Horizontal culling is the live one and must keep working.
  data.camera = [4_000, 40];
  assert.deepEqual(layoutGardenObjects(data, [80, 40]), []);
});

test('connected fixtures keep their canonical relative anchors', () => {
  const data = projection();
  const fixtures = data.objects.filter(object => object.kind === 'fixture');
  const obstacle = structuredClone(fixtures[0]);
  obstacle.object_id = 'aaa-obstacle';
  obstacle.semantic_name = 'garden sign';
  obstacle.position = [...fixtures[0].position];
  obstacle.hotspot = { ...fixtures[0].hotspot };
  obstacle.semantic_state = {
    ...obstacle.semantic_state, catalog_id: 'sign', connected_group: null,
  };
  data.objects = [obstacle, ...fixtures];
  const layout = layoutGardenObjects(data, [160, 48]);
  assert.equal(layout.length, 3);
  const connected = layout.filter(entry => entry.object.semantic_state?.connected_group === 'fence');
  assert.equal(connected.length, 2);
  assert.notDeepEqual(connected[0].anchor, connected[0].baseAnchor,
    'the obstacle must force a shared connected-group packing shift');
  assert.deepEqual(
    [connected[1].anchor[0] - connected[0].anchor[0],
      connected[1].anchor[1] - connected[0].anchor[1]],
    [connected[1].baseAnchor[0] - connected[0].baseAnchor[0],
      connected[1].baseAnchor[1] - connected[0].baseAnchor[1]],
  );
});

test('responsive compositor selects bounded visual detail by viewport', () => {
  assert.equal(gardenPresentationProfile([40, 20]).lod, 'compact');
  assert.equal(gardenPresentationProfile([72, 32]).lod, 'medium');
  assert.equal(gardenPresentationProfile([120, 48]).lod, 'full');
  const compact = layoutGardenObjects(projection(), [40, 20]);
  // Budget raised from 2/3 lines. A three-line cap forced every plant and
  // animal into a stub at narrow widths, which is what made a phone read as a
  // heap of punctuation; a body still has to survive reduction to stay
  // species-specific. Collectibles are exempt because they carry their own
  // purpose-drawn compact picture rather than a trimmed one.
  assert.ok(compact.every(entry => entry.object.kind === 'collectible' ||
    entry.art.lines.length <= (entry.object.kind === 'fixture' ? 3 : 6)));
  // Reduction must still actually reduce: a mature oak is taller than this.
  const tall = projection();
  tall.objects = [{
    object_id: 'plant:oak', kind: 'plant', semantic_name: 'oak', position: [10, 5],
    depth: 100, hotspot: { x: 10, y: 5, width: 1, height: 1 },
    semantic_state: { species_id: 'oak', visible_organ_count: 20 },
  }];
  const reduced = layoutGardenObjects(tall, [40, 20])[0];
  const full = layoutGardenObjects(tall, [120, 48])[0];
  assert.ok(reduced.art.lines.length < full.art.lines.length,
    'compact density did not reduce a mature tree at all');
});

test('starter compositor crops canonically and only shares intentional water-garden art', async () => {
  const intersects = (left, right) =>
    Math.max(0, Math.min(left.right, right.right) - Math.max(left.left, right.left) + 1) *
    Math.max(0, Math.min(left.bottom, right.bottom) - Math.max(left.top, right.top) + 1);
  for (let seed = 0; seed < 50; seed += 1) {
    // A populated world, because this test is about CROPPING: with only the
    // ten fixtures the narrow viewport has nothing to drop and the assertion
    // that it must crop cannot mean anything. The default starter content is
    // empty while its art awaits per-asset approval, so it is requested here.
    const state = await generateInitialWorld(`packing-${seed}`, `packing-seed-${seed}`, {
      plant_species: REVIEW_PENDING_PLANT_SPECIES,
      animal_species: REVIEW_PENDING_ANIMAL_SPECIES,
      collectibles: REVIEW_PENDING_COLLECTIBLES,
    });
    const data = await projectGardenScene(state);
    for (const [viewport, maximumXShift, maximumYShift, mustCrop] of [
      [[128, 48], 8, 3, false],
      [[49, 64], 2, 1, true],
    ]) {
      const layout = layoutGardenObjects(data, viewport);
      assert.ok(layout.length > 0, `${seed}:${viewport} lost the canonical camera slice`);
      if (mustCrop) assert.ok(layout.length < data.objects.length,
        `${seed}:${viewport} crushed the whole world into a narrow viewport`);
      for (const entry of layout) {
        assert.ok(Math.abs(entry.anchor[0] - entry.baseAnchor[0]) <= maximumXShift,
          `${seed}:${viewport} relocated ${entry.object.object_id} across the viewport`);
        assert.ok(Math.abs(entry.anchor[1] - entry.baseAnchor[1]) <= maximumYShift,
          `${seed}:${viewport} changed ${entry.object.object_id}'s canonical depth`);
      }
      for (let left = 0; left < layout.length; left += 1) {
        for (let right = left + 1; right < layout.length; right += 1) {
          const leftGroup = layout[left].object.semantic_state?.connected_group;
          const rightGroup = layout[right].object.semantic_state?.connected_group;
          if (leftGroup && leftGroup === rightGroup) continue;
          const overlap = intersects(layout[left].rect, layout[right].rect);
          if (overlap > 0) assert.equal(
            expectedSharedFeature(layout[left].object, layout[right].object), true,
            `${seed}:${viewport} ${layout[left].object.object_id} overlaps ` +
            `${layout[right].object.object_id} without a canonical shared feature`,
          );
        }
      }
    }
  }
});

test('plant wind uses stable per-cell phases instead of one global flip', () => {
  // `plant:a` is a rose. The archive draws no rose, so this plant is still on
  // the renderer's own glyph-substitution animation, and this test still
  // describes it: the outline is fixed and only interior characters change.
  // The species the archive DOES draw animate differently on purpose -- see
  // 'a legacy plant sways by whole archived frames, never by loose glyphs'.
  const before = layoutGardenObjects(projection(), [120, 48], 0)
    .find(entry => entry.object.object_id === 'plant:a').art.lines;
  const after = layoutGardenObjects(projection(), [120, 48], 18)
    .find(entry => entry.object.object_id === 'plant:a').art.lines;
  assert.notDeepEqual(after, before);
  assert.equal(after.map(line => [...line].length).join(','),
    before.map(line => [...line].length).join(','));
});

// ── The legacy art port ────────────────────────────────────────────────────
// The operator granted the archive a standing visual approval on 2026-08-01
// and ordered it to replace the unapproved placeholders, art AND behaviour.
// These tests hold the port to that: every picture a ported species can show
// must be an archived picture, and the motion must be the archive's whole-frame
// sway rather than the renderer's glyph shimmer.

/** One plant object of `species`, mature enough to reach its largest drawing. */
const legacyPlantScene = (species, organs = 20) => {
  const data = projection();
  data.objects = [{
    object_id: `plant:${species}`, kind: 'plant', semantic_name: species,
    position: [10, 5], depth: 100, hotspot: { x: 10, y: 5, width: 1, height: 1 },
    semantic_state: { species_id: species, visible_organ_count: organs, visible_organs: [] },
  }];
  data.camera = [10, 5];
  return data;
};

test('every picture a ported plant can show comes from the legacy archive', () => {
  // The point of the grant is that what reaches the screen is the drawing the
  // operator looked at. A renderer that starts from an archived frame and then
  // substitutes glyphs into it is showing something nobody approved, so this
  // sweeps a long frame range and requires an exact match every time.
  for (const species of LEGACY_PLANT_SPECIES) {
    const archived = new Set(legacyPlantFrameSet(species));
    assert.ok(archived.size > 0, `${species} claims a port but has no frames`);
    for (const viewport of [[120, 48], [72, 32], [40, 20]]) {
      for (let frame = 0; frame < 64; frame += 1) {
        const entry = layoutGardenObjects(legacyPlantScene(species), viewport, frame)[0];
        assert.ok(entry, `${species} was not laid out at ${viewport} frame ${frame}`);
        const drawn = entry.art.lines.join('\n');
        // At full density the picture must be an archived frame exactly. At a
        // reduced density it must be an archived frame with whole rows removed
        // and nothing else -- `presentationLod` keeps the first row and a run
        // of trailing rows. That reduction is a viewport policy that predates
        // this port and applies to every plant, but it may only ever DELETE
        // from an archived drawing; substituting a glyph into one would be
        // showing a picture the operator never saw.
        const isArchivedOrReduction = archived.has(drawn) || [...archived].some(source => {
          const rows = source.split('\n'), shown = drawn.split('\n');
          return shown.length < rows.length && shown[0] === rows[0] &&
            shown.slice(1).join('\n') === rows.slice(-(shown.length - 1)).join('\n');
        });
        assert.ok(isArchivedOrReduction,
          `${species} drew a picture the archive does not contain at ${viewport} frame ${frame}:\n` +
          drawn);
      }
    }
  }
});

test('a legacy plant sways by whole archived frames, never by loose glyphs', () => {
  // The archive's own words, flowers/flower-animations.txt:
  //   "3 frames, loop: 1->2->3->2->1 ... ~400ms per frame (gentle breeze)"
  // Two things follow that the glyph-substitution animation cannot produce, and
  // both are asserted: the picture changes as a unit, and it returns to where
  // it started rather than wandering forever through fresh combinations.
  // Sampled one archived frame apart, not one presentation frame apart. The
  // archive holds each picture for ~400ms and the Garden ticks at the
  // accepted 50ms cadence (recipe.motion.frame_cadence), so EIGHT
  // consecutive presentation frames show the SAME picture by design;
  // sampling every frame would only measure the hold.
  const seen = [];
  for (let step = 0; step < 20; step += 1) {
    seen.push(layoutGardenObjects(legacyPlantScene('willow'), [120, 48], step * 8)[0]
      .art.lines.join('\n'));
  }
  const distinct = new Set(seen);
  assert.ok(distinct.size > 1, 'a swaying willow never changed picture');
  // A three-frame archived sequence can only ever show three pictures. Glyph
  // substitution over 80 frames would show far more.
  assert.ok(distinct.size <= 4,
    `willow showed ${distinct.size} distinct pictures; the archive draws 3`);
  // Ping-pong, not wrap-around: the sequence returns through its middle frame.
  const order = seen.map(picture => [...distinct].indexOf(picture));
  assert.ok(order.some((value, index) => index >= 2 &&
    value === order[index - 2] && value !== order[index - 1]),
  'the sway never reversed, so it is wrapping rather than swinging back');
});

test('two plants of one species do not sway in unison', () => {
  // The property worth keeping from the animation the port replaced. Whole-
  // frame sway makes lockstep much more visible than glyph shimmer did, so this
  // is more load-bearing now, not less.
  const data = legacyPlantScene('willow');
  const right = structuredClone(data.objects[0]);
  right.object_id = 'plant:willow-right';
  right.position = [40, 5];
  right.hotspot = { x: 40, y: 5, width: 1, height: 1 };
  data.objects = [data.objects[0], right];
  data.camera = [25, 5];
  const pictures = frame => layoutGardenObjects(data, [160, 48], frame)
    .map(entry => entry.art.lines.join('\n'));
  const differed = [];
  for (let frame = 0; frame < 40; frame += 1) {
    const [left, second] = pictures(frame);
    differed.push(left !== second);
  }
  assert.ok(differed.some(Boolean),
    'two willows showed the identical archived frame on every frame of the loop');
});

test('a ported plant keeps one bounding box while its ink moves', () => {
  // The archive draws each sway frame at its own natural width. Swapped in
  // place that would resize the object every few frames, which moves its
  // hotspot, its occlusion rectangle and anything anchored beside it. The port
  // pads the frames to a common box; this is the assertion that says so.
  for (const species of LEGACY_PLANT_SPECIES) {
    const boxes = new Set();
    for (let frame = 0; frame < 48; frame += 1) {
      const lines = layoutGardenObjects(legacyPlantScene(species), [120, 48], frame)[0].art.lines;
      boxes.add(`${lines.length}x${Math.max(...lines.map(line => [...line].length))}`);
    }
    assert.equal(boxes.size, 1,
      `${species} changed size while swaying: ${[...boxes].join(', ')}`);
  }
});

test('the port claims the archive grant only where the archive actually draws', () => {
  // The grant covers the archive, so a drawing may claim it only by being one.
  // Every ported entry must name the file and section it came from, and that
  // file must exist with that section in it. This is what stops a plausible
  // new drawing being filed under an approval it was never shown for.
  const entries = Object.entries(LEGACY_ART_PROVENANCE);
  assert.ok(entries.length > 0, 'the port records no provenance at all');
  for (const [assetId, source] of entries) {
    const [path, ...sections] = source.split(' :: ');
    for (const clause of path.split(' + ')) {
      const file = new URL(
        `../../archive/legacy-repo-7b9389d/ascii-animations/${clause.trim()}`, import.meta.url);
      assert.ok(existsSync(file), `${assetId} cites a missing archive file: ${clause}`);
    }
    assert.ok(sections.length > 0, `${assetId} cites a file but no section within it`);
  }
});

test('species the archive never drew are not dressed up as approved', () => {
  // "WHEN POSSIBLE" was the operator's own qualifier. The archive names oak,
  // willow, pine, sunflower and lily; it names no rose, tulip, hydrangea,
  // wisteria, lavender, rosemary, ivy or meadow grass. Those must stay on their
  // unapproved placeholders and must NOT appear in the provenance record,
  // because appearing there is what claims the grant.
  const unported = ['rose', 'tulip', 'hydrangea', 'wisteria', 'lavender',
    'rosemary', 'ivy', 'meadow_grass'];
  for (const species of unported) {
    assert.ok(!LEGACY_PLANT_SPECIES.includes(species),
      `${species} claims a legacy port, but the archive does not draw it`);
    assert.ok(!Object.keys(LEGACY_ART_PROVENANCE).some(key => key.startsWith(`plant.${species}.`)),
      `${species} claims archive provenance it cannot have`);
  }
  // Same for the two animals the archive never drew.
  for (const species of ['rabbit', 'turtle']) {
    assert.ok(!LEGACY_ANIMAL_SPECIES.includes(species),
      `${species} claims a legacy port, but the archive does not draw it`);
  }
});

test('a sleeping animal is not faked from a still one', () => {
  // The archive contains no sleeping anything. A cat at rest therefore falls
  // through to the renderer's own placeholder rather than borrowing the
  // peeking-cat's held face, which is a cat holding still, not a cat asleep.
  const data = projection();
  data.objects = [{
    object_id: 'animal:cat', kind: 'animal', semantic_name: 'cat', position: [10, 5],
    depth: 110, hotspot: { x: 10, y: 5, width: 1, height: 1 },
    semantic_state: { species_id: 'cat', bond_tier: 0, intent: 'rest' },
  }];
  data.camera = [10, 5];
  const picture = layoutGardenObjects(data, [120, 48], 0)[0].art.lines.join('\n');
  assert.ok(picture.includes('z'), 'a resting cat lost its readable sleeping pose');
  assert.ok(!legacyAnimalFrameSet('cat').some(frame => frame === picture),
    'the sleeping pose was sourced from the archive, which draws no sleep');
});

test('restoring the ported plants leaves the authoritative fixture row alone', async () => {
  // The five fixture anchors are authoritative canonical data. Plants returning
  // to the default scene must arrange themselves AROUND that row, never move
  // it. Anchored between the fixtures they did move it -- measured, the bench
  // and lantern shifted 7 columns each and then fell out of the phone crop
  // altogether. This is the assertion that keeps them outside it.
  const fixturesOnly = async () => {
    const state = await generateInitialWorld('anchor-check', 'anchor-seed', { plant_species: [] });
    return projectGardenScene(state);
  };
  const withPlants = async () => {
    const state = await generateInitialWorld('anchor-check', 'anchor-seed');
    return projectGardenScene(state);
  };
  const columnsOf = (data, viewport) => {
    const element = new FakeElement();
    [element.clientWidth, element.clientHeight] = viewport;
    const frame = rendererUnderAuthority(element).render(data);
    return new Map(frame.layout
      .filter(entry => entry.object.kind === 'fixture')
      .map(entry => [entry.object.semantic_state?.catalog_id,
        `${entry.rect.left}-${entry.rect.right}`]));
  };
  const bare = columnsOf(await fixturesOnly(), [1600, 1000]);
  const planted = columnsOf(await withPlants(), [1600, 1000]);
  for (const [catalog, span] of bare) {
    assert.equal(planted.get(catalog), span,
      `${catalog} moved from ${span} to ${planted.get(catalog)} when the plants returned`);
  }
  // And the operator's own phone-crop requirement, restated where it can fail.
  const phone = columnsOf(await withPlants(), [390, 844]);
  for (const catalog of ['bench', 'mailbox', 'lantern']) {
    assert.ok(phone.has(catalog),
      `the 390x844 crop lost ${catalog}; it holds ${[...phone.keys()].join(', ')}`);
  }
});

test('the default scene plants only species whose art came from the archive', async () => {
  // The whole point of the removal was that the default scene stopped shipping
  // drawings nobody approved. Plants are back, so the rule needs restating
  // where a future addition will trip over it: a species may stand in the
  // default scene only if the archive draws it.
  const state = await generateInitialWorld('roster-check', 'roster-seed');
  const data = await projectGardenScene(state);
  for (const object of data.objects) {
    const species = object.semantic_state?.species_id;
    if (object.kind === 'plant') {
      assert.ok(LEGACY_PLANT_SPECIES.includes(species),
        `the default scene plants ${species}, which the archive does not draw`);
    }
    if (object.kind === 'animal') {
      assert.ok(LEGACY_ANIMAL_SPECIES.includes(species),
        `the default scene places ${species}, which the archive does not draw`);
    }
  }
});

test('every picture a ported animal can show in an archived routine is archived', () => {
  // Intents, not family names: `animalPoseFamily` maps "greet" onto the
  // `approach` family, so asking for the `greet` family means passing an intent
  // it does not recognise and letting it fall to its default.
  for (const [species, family, intent] of [
    ['cat', 'approach', 'approach'], ['cat', 'forage', 'forage'],
    ['bird', 'play', 'play'], ['bird', 'rest', 'perch'],
    ['bird', 'greet', 'idle'],
  ]) {
    const archived = new Set(legacyAnimalFrameSet(species));
    const data = projection();
    data.objects = [{
      object_id: `animal:${species}`, kind: 'animal', semantic_name: species,
      position: [10, 5], depth: 110, hotspot: { x: 10, y: 5, width: 1, height: 1 },
      semantic_state: { species_id: species, bond_tier: 0, intent },
    }];
    data.camera = [10, 5];
    for (let frame = 0; frame < 48; frame += 1) {
      const entry = layoutGardenObjects(data, [120, 48], frame)[0];
      assert.equal(entry.art.poseFamily, family,
        `${species} intent ${intent} did not resolve to ${family}`);
      assert.ok(archived.has(entry.art.lines.join('\n')),
        `${species}/${family} drew an unarchived picture at frame ${frame}:\n` +
        entry.art.lines.join('\n'));
    }
  }
});

test('focused plant rustles independently from an equal-species neighbor', () => {
  const data = projection();
  const left = structuredClone(data.objects[0]);
  // Keep the two now-recognisable oak silhouettes far enough apart that the
  // packing/culling contract is not what this animation test exercises.
  left.object_id = 'plant:rustle-left'; left.position = [0, 5];
  left.hotspot = { x: 0, y: 5, width: 1, height: 1 };
  left.semantic_state = { species_id: 'oak', visible_organ_count: 8, visible_organs: [] };
  const right = structuredClone(left);
  right.object_id = 'plant:rustle-right'; right.position = [30, 5];
  right.hotspot = { x: 30, y: 5, width: 1, height: 1 };
  data.objects = [left, right]; data.camera = [15, 5];

  const sequence = focusedObjectId => {
    const element = new FakeElement();
    element.clientWidth = 960; element.clientHeight = 720;
    const renderer = rendererUnderAuthority(element);
    renderer.setFocusedObject(focusedObjectId);
    const pictures = [];
    for (let frame = 0; frame < 32; frame += 1) {
      renderer.visualFrame = frame;
      const rendered = renderer.render(data);
      const capture = objectId => {
        const entry = rendered.layout.find(item => item.object.object_id === objectId);
        assert.ok(entry, `${objectId} was not laid out at frame ${frame}`);
        return rendered.lines.slice(entry.rect.top, entry.rect.bottom + 1).map(line =>
          [...line].slice(entry.rect.left, entry.rect.right + 1).join('')).join('\n');
      };
      pictures.push([capture(left.object_id), capture(right.object_id)]);
    }
    return pictures;
  };
  const unfocused = sequence(null), focused = sequence(left.object_id);
  assert.notDeepEqual(unfocused.map(picture => picture[0]), unfocused.map(picture => picture[1]),
    'equal-species plants followed one synchronized presentation sequence');
  assert.notDeepEqual(focused.map(picture => picture[0]), unfocused.map(picture => picture[0]),
    'focused plant retained its unfocused presentation sequence');
  assert.deepEqual(focused.map(picture => picture[1]), unfocused.map(picture => picture[1]),
    'focusing one plant changed its equal-species neighbor');
  assert.ok(focused.some((picture, index) => index > 0 &&
    picture[0] !== focused[index - 1][0] && picture[1] === focused[index - 1][1]),
  'focused plant never changed on an adjacent frame while its neighbor remained still');
});

test('every canonical plant species has a distinct established silhouette', () => {
  const speciesIds = [
    'oak', 'pine', 'willow', 'rose', 'hydrangea', 'ivy', 'wisteria',
    'meadow_grass', 'lavender', 'rosemary', 'tulip', 'sunflower', 'water_lily',
  ];
  for (const viewport of [[120, 48], [72, 32], [40, 20]]) {
    const pictures = new Map();
    for (const species of speciesIds) {
      const data = projection();
      data.objects = [{
        object_id: `plant:${species}`, kind: 'plant', semantic_name: species,
        position: [10, 5], depth: 100, hotspot: { x: 10, y: 5, width: 1, height: 1 },
        semantic_state: { species_id: species, visible_organ_count: 8, visible_organs: [] },
      }];
      const entry = layoutGardenObjects(data, viewport, 0)[0];
      assert.ok(entry, `${species} was not laid out at ${viewport}`);
      pictures.set(species, entry.art.lines.join('\n'));
    }
    assert.equal(new Set(pictures.values()).size, speciesIds.length,
      `${viewport} plant silhouettes collapsed: ${JSON.stringify(Object.fromEntries(pictures))}`);
  }
});

// REPLACES 'every canonical collectible keeps its semantic glyph at every
// density', which asserted an exact one-character picture for all eight
// identities. That assertion guaranteed uniqueness but forbade recognisability:
// a single arbitrary mark depicts nothing, and it blocked purpose-drawn art.
// The uniqueness guarantee it did carry is preserved and strengthened below —
// pictures must now be distinct at every density AND large enough to read.
test('every canonical collectible has recognisable unique art at every density', () => {
  const collectibles = [
    ['oak_leaf', 'Oak leaf', 'plant_species'],
    ['lavender_sprig', 'Lavender sprig', 'plant_species'],
    ['first_snowflake', 'First snowflake', 'seasonal_natural_find'],
    ['fallen_acorn', 'Fallen acorn', 'seasonal_natural_find'],
    ['rabbit_track', 'Rabbit track', 'animal_trace'],
    ['bird_feather', 'Bird feather', 'animal_trace'],
    ['pressed_flower', 'Pressed flower', 'authored_keepsake'],
    ['small_key', 'Small key', 'authored_keepsake'],
  ];
  for (const viewport of [[205, 66], [120, 48], [72, 32], [40, 20]]) {
    const pictures = new Map();
    for (const [catalogId, label, family] of collectibles) {
      const data = projection();
      data.objects = [{
        object_id: `collectible:${catalogId}`, kind: 'collectible', semantic_name: label,
        position: [10, 5], depth: 100, hotspot: { x: 10, y: 5, width: 1, height: 1 },
        semantic_state: { catalog_id: catalogId, family },
      }];
      const entry = layoutGardenObjects(data, viewport, 0)[0];
      assert.ok(entry, `${catalogId} was not laid out at ${viewport}`);
      const picture = entry.art.lines.join('\n');
      assert.doesNotMatch(picture, /\$/, `${catalogId} fell back to a placeholder`);
      // Never a bare mark: a collectible must be drawn, at every density.
      assert.ok(entry.art.lines.length >= 2,
        `${catalogId} collapsed to a single line at ${viewport}`);
      assert.ok(picture.replace(/\s/g, '').length >= 4,
        `${catalogId} is too small to recognise at ${viewport}`);
      assert.ok(!pictures.has(picture),
        `${catalogId} is identical to ${pictures.get(picture)} at ${viewport}`);
      pictures.set(picture, catalogId);
    }
    assert.equal(pictures.size, collectibles.length,
      `${viewport} collectible identities collapsed`);
  }
});

test('animal intent presentation distinguishes routines and choreography', () => {
  assert.equal(animalPoseFamily('startle_retreat'), 'retreat');
  assert.equal(animalPoseFamily('pause_approach'), 'approach');
  assert.equal(animalPoseFamily('settled_knead'), 'groom');
  assert.equal(animalPoseFamily('forage_nearby'), 'forage');
  assert.equal(animalPoseFamily('initiate_hop_play'), 'play');
  assert.equal(animalPoseFamily('rest_near'), 'rest');
  assert.equal(animalPoseFamily('anything', true), 'perform');
});

test('every species and bond tier retains the complete pose-family presentation', () => {
  const intents = {
    play: 'initiate_hop_play', greet: 'idle', rest: 'rest_near',
    approach: 'pause_approach', retreat: 'startle_retreat', groom: 'settled_knead',
    forage: 'forage_nearby', perform: 'greet',
  };
  for (const species of ['bird', 'cat', 'rabbit', 'turtle']) {
    const tierPicturesByFamily = new Map(Object.keys(intents).map(family => [family, new Set()]));
    for (const tier of [0, 1, 2, 3]) {
      const pictures = new Set();
      for (const [family, intent] of Object.entries(intents)) {
        const data = projection();
        data.objects = [{
          object_id: `animal:${species}:${family}`, kind: 'animal',
          semantic_name: species, position: [10, 5], depth: 110,
          hotspot: { x: 10, y: 5, width: 1, height: 1 },
          semantic_state: { species_id: species, bond_tier: tier, intent,
            choreography_locked: family === 'perform' },
        }];
        const entry = layoutGardenObjects(data, [120, 48], 0)[0];
        assert.ok(entry, `${species}:${tier}:${family} was not laid out`);
        assert.equal(entry.art.poseFamily, family, `${species}:${tier}:${family} chose the wrong pose family`);
        const picture = entry.art.lines.join('\n');
        pictures.add(picture);
        tierPicturesByFamily.get(family).add(picture);
      }
      assert.ok(pictures.size >= 6, `${species}:tier${tier} visually collapsed pose families`);
    }
    for (const [family, pictures] of tierPicturesByFamily)
      assert.equal(pictures.size, 4, `${species}:${family} visually collapsed bond tiers`);
  }
});

test('interaction particles are object-aware rather than a shared four-cell burst', () => {
  const pine = objectBurstPattern({ kind: 'plant', species: 'pine' }, 0);
  const flower = objectBurstPattern({ kind: 'plant', species: 'rose' }, 0);
  const pond = objectBurstPattern({ kind: 'fixture', catalog: 'pond' }, 0);
  const animal = objectBurstPattern({ kind: 'animal', species: 'rabbit' }, 0);
  assert.ok(pine.length > 4);
  assert.notDeepEqual(pine, flower);
  assert.ok(pond.every(item => item[2] === '~' && item[3] === 'water'));
  assert.ok(animal.some(item => item[3] === 'flower'));
});

test('real hover and click paths retain the exact semantic object', () => {
  const element = new FakeElement();
  const renderer = rendererUnderAuthority(element);
  renderer.setCellGeometry(8, 15);
  const data = projectionCenteredOn('plant:a', { isolate: true });
  const before = JSON.stringify(attemptedInkOf(renderer.render(data), 'plant:a'));
  const plant = renderer.lastFrame.layout.find(entry => entry.object.object_id === 'plant:a');
  const event = {
    clientX: plant.hitRect.left * renderer.cellWidth + 1,
    clientY: plant.hitRect.top * renderer.cellHeight + 1,
  };
  renderer._hoverAt(event);
  // The rose carries no accepted identity, so its ink is recorded and
  // suppressed rather than shown; hover must still reshape the ATTEMPT.
  // Identity retention is a machinery fact, not a visibility one.
  const after = JSON.stringify(attemptedInkOf(renderer.lastFrame, 'plant:a'));
  assert.equal(element.style.cursor, 'pointer');
  assert.notEqual(after, before);
  renderer._burstAt(event);
  // The click no longer mutates renderer state directly: it queues a burst
  // EVENT, and the state advance at the next render turns it into a live
  // burst. The identity facts are unchanged -- exact object, exact cell.
  renderer.render(data);
  assert.deepEqual(renderer.presentationState.clickBursts.at(-1), {
    x: plant.hitRect.left, y: plant.hitRect.top, frame: renderer.visualFrame,
    kind: 'plant', species: 'rose', catalog: undefined, objectId: 'plant:a',
  });
});

test('connected masks are consumed only from canonical projection fields', () => {
  const masks = connectedMasks(projection().objects);
  assert.equal(masks.get('fence:a'), 2);
  assert.equal(masks.get('fence:b'), 8);
  assert.equal(new Set(Array.from({ length: 16 }, (_, mask) => connectedGlyph(mask))).has(undefined), false);
  const missing = projection();
  delete missing.objects.find(item => item.object_id === 'fence:a').semantic_state.connected_mask;
  assert.throws(() => connectedMasks(missing.objects), /projection-owned connected mask/);
  const missingGroup = projection();
  delete missingGroup.objects.find(item => item.object_id === 'fence:a').semantic_state.connected_group;
  assert.throws(() => connectedMasks(missingGroup.objects), /projection-owned connected group/);
});

test('canonical atlas owns delivery choreography and species fallbacks', () => {
  assert.equal(deliveryFramesFor('cat', 3), ANIMAL_DELIVERY_FRAMES.cat);
  assert.equal(deliveryFramesFor('unknown', 3), LETTERBIRD_DELIVERY_FRAMES);
  assert.equal(deliveryFramesFor('cat', 2), LETTERBIRD_DELIVERY_FRAMES);
  assert.match(LETTERBIRD_DELIVERY_FRAMES.flat().join('\n'), /✉/);
});

test('resize changes presentation only and partial repaint becomes empty', () => {
  const data = projection(), before = structuredClone(data), element = new FakeElement();
  const renderer = rendererUnderAuthority(element, { prefersReducedMotion: true });
  const first = renderer.render(data);
  assert.ok(first.changedRows.length > 0);
  assert.equal(first.motionPaused, true);
  const second = renderer.render(data);
  assert.deepEqual(second.changedRows, []);
  element.clientWidth = 400;
  renderer.onResize();
  assert.deepEqual(data, before);
  // The rose and fences carry no accepted identity: their ink is recorded
  // and suppressed, not shown. Resize must still re-attempt the scene's
  // objects at the new width -- that is the machinery being pinned.
  assert.match(renderer.lastFrame.attempted_primitives
    .map(item => item.glyph).join(''), /[@+\-]/);
});

test('palette-only transitions repaint rows whose glyphs are unchanged', () => {
  const data = projection(), element = new FakeElement();
  data.scene.story_time = 'day';
  const renderer = rendererUnderAuthority(element, { prefersReducedMotion: true });
  const day = renderer.render(data), dayGround = element.children[day.horizon].innerHTML;
  data.scene.story_time = 'night';
  const night = renderer.render(data), nightGround = element.children[night.horizon].innerHTML;
  assert.equal(day.lines[day.horizon], night.lines[night.horizon]);
  assert.notEqual(dayGround, nightGround);
  assert.ok(night.changedRows.includes(night.horizon));
  assert.match(nightGround, /#28302a/);
});

test('cell geometry is cached until resize invalidates it', () => {
  const originalDocument = globalThis.document;
  const originalGetComputedStyle = globalThis.getComputedStyle;
  let created = 0;
  globalThis.document = { createElement: () => { created += 1; return new FakeRow(); } };
  globalThis.getComputedStyle = () => ({ lineHeight: '15' });
  try {
    const renderer = rendererUnderAuthority(new FakeElement(), { prefersReducedMotion: true });
    renderer.render(projection());
    const afterFirst = created;
    renderer.render(projection());
    assert.equal(created, afterFirst);
    renderer.onResize();
    assert.equal(created, afterFirst + 1);
  } finally {
    globalThis.document = originalDocument;
    globalThis.getComputedStyle = originalGetComputedStyle;
  }
});

test('presentation loop sleeps without a visible moving Garden', () => {
  const originalRequest = globalThis.requestAnimationFrame;
  const originalCancel = globalThis.cancelAnimationFrame;
  let scheduled = 0, cancelled = 0;
  globalThis.requestAnimationFrame = () => { scheduled += 1; return scheduled; };
  globalThis.cancelAnimationFrame = () => { cancelled += 1; };
  try {
    const renderer = rendererUnderAuthority(new FakeElement());
    renderer.startPresentation();
    assert.equal(scheduled, 0);
    renderer.setPresentationActive(true);
    assert.equal(scheduled, 0);
    renderer.render(projection());
    assert.equal(scheduled, 1);
    renderer.setPresentationActive(false);
    assert.equal(cancelled, 1);
    renderer.setPresentationActive(true);
    assert.equal(scheduled, 2);
    renderer.render({ ...projection(), motion_paused: true });
    assert.equal(cancelled, 2);
    assert.equal(renderer.presentationTimer, null);
    renderer.setReducedMotion(true);
    renderer.render(projection());
    assert.equal(scheduled, 2);
  } finally {
    globalThis.requestAnimationFrame = originalRequest;
    globalThis.cancelAnimationFrame = originalCancel;
  }
});

test('click and feed bursts are suppressed or cleared when motion is suppressed', () => {
  const element = new FakeElement();
  const renderer = rendererUnderAuthority(element);
  let data = projectionCenteredOn('plant:a', { isolate: true });
  renderer.render(data);
  const plant = renderer.lastFrame.layout.find(entry => entry.object.object_id === 'plant:a');
  const event = { clientX: plant.anchor[0] * renderer.cellWidth + 1,
    clientY: plant.anchor[1] * renderer.cellHeight + 1 };
  renderer._burstAt(event);
  renderer.render(data);
  assert.equal(renderer.presentationState.clickBursts.length, 1);
  const burstInk = frame => frame.visible_primitives
    .filter(item => item.source_id === 'recipe.feedback.click_leaf_burst');
  // While motion runs, the burst paints. When motion is suppressed the
  // observable guarantees are: no burst INK reaches the picture, and no new
  // burst EVENT is even recorded. (The state list itself now merely ages
  // out; what the old cleared-list assertion protected was the ink.)
  assert.ok(burstInk(renderer.lastFrame).length > 0);
  data = { ...data, motion_paused: true };
  assert.deepEqual(burstInk(renderer.render(data)), []);
  renderer._burstAt(event);
  assert.equal(renderer.pendingEvents.length, 0, 'a paused Garden records no burst');
  renderer.setReducedMotion(true);
  assert.deepEqual(burstInk(renderer.render({ ...data, motion_paused: false })), []);
  renderer._burstAt(event);
  assert.equal(renderer.pendingEvents.length, 0, 'reduced motion records no burst');
});

test('browser renderer paints every canonical fixture footprint cell', () => {
  const data = projection();
  const table = {
    object_id: 'fixture:table', kind: 'fixture', semantic_name: 'table', position: [10, 5],
    depth: 120, hotspot: { x: 10, y: 5, width: 2, height: 2 },
    semantic_state: { catalog_id: 'table_chairs', presentation_state: 'idle',
      connected_group: null, connected_mask: 0, render_cells: [
        { dx: 0, dy: 0, connected_mask: 0 }, { dx: 1, dy: 0, connected_mask: 0 },
        { dx: 0, dy: 1, connected_mask: 0 }, { dx: 1, dy: 1, connected_mask: 0 },
      ] },
  };
  data.objects = [table];
  data.camera = [...table.position];
  const frame = rendererUnderAuthority(new FakeElement()).render(data);
  const [x, y] = frame.layout.find(entry => entry.object.object_id === 'fixture:table').anchor;
  // table_chairs has no accepted identity, so its footprint is recorded and
  // suppressed rather than shown. Every render cell must still have been
  // attempted with the table glyph at its exact offset, and none of that
  // unaccepted ink may escape suppression.
  const ink = attemptedInkOf(frame, 'fixture:table');
  for (const [cellX, cellY] of [[x, y], [x + 1, y], [x, y + 1], [x + 1, y + 1]]) {
    assert.ok(ink.some(([atX, atY, glyph]) => atX === cellX && atY === cellY && glyph === 'T'),
      `no table ink attempted at footprint cell ${cellX},${cellY}`);
  }
  assert.ok(ink.every(item => item[3]), 'unaccepted footprint ink escaped suppression');
});

test('browser renderer covers all connected masks and animal species tiers', () => {
  for (const group of Object.keys(ATLAS_MANIFEST.connected_tiles)) {
    for (let mask = 0; mask < 16; mask += 1) {
      const data = projection();
      data.camera = [0, 0];
      data.objects = [{
        object_id: `fixture:${group}:${mask}`, kind: 'fixture', semantic_name: group,
        position: [0, 0], depth: 100, hotspot: { x: 0, y: 0, width: 1, height: 1 },
        semantic_state: { catalog_id: 'fence', presentation_state: 'closed',
          connected_group: group, connected_mask: mask,
          render_cells: [{ dx: 0, dy: 0, connected_mask: mask }] },
      }];
      const frame = rendererUnderAuthority(new FakeElement()).render(data);
      const [x, y] = frame.layout[0].anchor;
      // Connected-fixture ink is anonymous (no accepted identity), so the
      // mask coverage is proven on the attempted log, not the visible lines.
      const ink = attemptedInkOf(frame, `fixture:${group}:${mask}`);
      assert.ok(ink.some(([atX, atY, glyph]) =>
        atX === x && atY === y && glyph === connectedGlyph(mask, group)),
      `mask ${mask} of ${group} was not attempted with its connected glyph`);
    }
  }
  for (const speciesId of ['bird', 'cat', 'rabbit', 'turtle']) {
    for (let tier = 0; tier < 4; tier += 1) {
      const performing = tier % 2 === 1;
      const object = { object_id: `animal:${speciesId}:${tier}`, kind: 'animal',
        semantic_name: speciesId, position: [0, 0], depth: 110,
        hotspot: { x: 0, y: 0, width: 1, height: 1 },
        semantic_state: { species_id: speciesId, bond_tier: tier,
          choreography_locked: performing, intent: 'greet', personality_emphasis: 'playfulness',
          recent_memories: [{ kind: 'feed' }],
          presentation_variant: `${speciesId}.tier${tier}.greet.${performing ? 'perform' : 'routine'}`,
          semantic_description: `${speciesId}, bond tier ${tier}; greet; personality playfulness; 1 memories.` },
      };
      const data = { ...projection(), camera: [0, 0], objects: [object] };
      const frame = rendererUnderAuthority(new FakeElement()).render(data);
      const expected = ATLAS_MANIFEST.semantic_tokens.animal_tier_glyphs[speciesId][tier];
      const [x, y] = frame.layout[0].anchor;
      assert.equal(glyphForProjection(object), expected);
      // bird and cat carry accepted identities; rabbit and turtle do not,
      // so tier coverage is proven on the attempted log for all four alike.
      const ink = attemptedInkOf(frame, `animal:${speciesId}:${tier}`);
      assert.ok(ink.some(([atX, atY, glyph]) => atX === x && atY === y && glyph === expected),
        `${speciesId} tier ${tier} was not attempted with its tier glyph`);
      assert.match(object.semantic_state.semantic_description, new RegExp(`bond tier ${tier}`));
      assert.match(object.semantic_state.semantic_description, /greet; personality playfulness; 1 memories/);
    }
  }
});

test('rich projection restores layered plant animal palette and weather presentation', () => {
  const data = projection();
  data.effective_time = Date.UTC(2026, 9, 22, 12) / 1000;
  data.scene = { sky_mode: 'storybook_fallback', palette: 'autumn', weather: 'rain' };
  const cat = {
    object_id: 'animal:cat', kind: 'animal', semantic_name: 'cat', position: [30, 5],
    depth: 110, hotspot: { x: 30, y: 5, width: 1, height: 1 },
    semantic_state: { species_id: 'cat', bond_tier: 3, intent: 'rest',
      recent_memories: [{ kind: 'feed' }], choreography_locked: false },
  };
  data.objects = [data.objects.find(object => object.object_id === 'plant:a'), cat];
  data.camera = [20, 5];
  const element = new FakeElement();
  element.clientWidth = 960;
  element.clientHeight = 720;
  const frame = rendererUnderAuthority(element, { prefersReducedMotion: true }).render(data);
  const picture = frame.lines.join('\n');
  assert.equal(frame.season, 'autumn');
  assert.equal(frame.timeOfDay, 'day');
  assert.equal(picture.includes('|'), true);
  const catEntry = frame.layout.find(entry => entry.object.object_id === cat.object_id);
  assert.ok(catEntry, 'canonical camera crop lost the separated animal target');
  assert.equal(catEntry.art.poseFamily, 'rest');
  assert.ok(catEntry.art.lines.length >= 4);
  assert.ok(catEntry.art.lines.some(line => line.includes('z')),
    'resting cat has no readable sleeping pose');
  assert.equal(picture.includes('/'), true);
  // Asserts that palette colour reaches the DOM, without pinning the order of
  // declarations inside the style attribute. Each span now also carries the
  // `left` that places it on the cell lattice, so `style="color:` alone no
  // longer matches even though the colouring behaviour is unchanged.
  assert.match(
    element.children.map(row => row.innerHTML).join(''),
    /<span style="[^"]*color:#[0-9a-f]{3,8}/i,
  );
  assert.match(element.style.background, /linear-gradient/);
});

test('an empty paint authority suppresses every attempted primitive', () => {
  // This replaces the `allowUnacceptedArt: false` test: release blocking is
  // no longer a boolean the caller mints from the hostname but a manifest of
  // accepted ids. An authority that accepts NOTHING is the strictest case --
  // every attempted primitive is suppressed, no ink reaches the lattice on
  // any host -- while each suppressed attempt keeps its identity, so the
  // frame can still say what WOULD have painted and under which id.
  const element = new FakeElement();
  // Structurally VALID (the single validator demands the generator's full
  // shape) while accepting nothing: the register records are present but
  // vouch for nothing, which the runtime never re-derives anyway -- digest
  // truth is the build-time drift test's job.
  const nothingAccepted = {
    schema: 1,
    purpose: 'test authority accepting nothing',
    registers: {
      asset_register: { path: 'docs/garden-asset-acceptance.json', sha256: '' },
      recipe_register: { path: 'docs/garden-presentation-recipes.json', sha256: '' },
    },
    accepted_assets: [], accepted_recipes: [], accepted_laws: [],
    accepted_legacy_art: [],
  };
  const frame = rendererUnderAuthority(element, {
    paintAuthority: nothingAccepted,
    prefersReducedMotion: true,
  }).render(projection());
  assert.ok(frame.lines.every(line => line.trim() === ''));
  assert.equal(frame.visible_primitives.filter(item => item.glyph.trim()).length, 0);
  assert.ok(frame.diagnostics.suppressed > 0, 'the attempts were recorded, not skipped');
  assert.equal(frame.diagnostics.authority_asserted, true);
  // The same projection with no authority paints: suppression came from the
  // manifest, not from where the code ran.
  const diagnostic = rendererUnderAuthority(new FakeElement(), {
    prefersReducedMotion: true,
  }).render(projection());
  assert.ok(diagnostic.lines.some(line => line.trim() !== ''));
});

test('civil presentation uses canonical observed time, never elapsed simulation time', () => {
  const data = projection();
  data.effective_time = 0;
  data.observed_time = Date.UTC(2026, 9, 22, 12) / 1000;
  data.scene = { sky_mode: 'storybook_fallback' };
  const frame = rendererUnderAuthority(
    new FakeElement(), { prefersReducedMotion: true },
  ).render(data);
  assert.equal(frame.timeOfDay, 'day');
  assert.equal(frame.season, 'autumn');
});

test('weather reacts at object surfaces with splashes caps and settled leaves', () => {
  const rainy = projectionCenteredOn('plant:a', { isolate: true });
  rainy.scene = { sky_mode: 'storybook_fallback', season: 'summer', weather: 'rain' };
  const rainRenderer = rendererUnderAuthority(new FakeElement(), { prefersReducedMotion: true });
  rainRenderer.visualFrame = 40;
  const rain = rainRenderer.render(rainy);
  assert.ok(rain.weatherReactions.splashes > 0);

  const snowy = projectionCenteredOn('plant:a', { isolate: true });
  snowy.scene = { sky_mode: 'storybook_fallback', season: 'winter', weather: 'snow' };
  const snowRenderer = rendererUnderAuthority(new FakeElement(), { prefersReducedMotion: true });
  snowRenderer.visualFrame = 90;
  const snow = snowRenderer.render(snowy);
  assert.ok(snow.weatherReactions.snowCaps > 0);
  for (const entry of snow.layout) {
    const [x, y] = entry.anchor;
    assert.notEqual(snow.lines[y][x], '.');
    assert.notEqual(snow.lines[y][x], '*');
  }

  const autumn = projectionCenteredOn('plant:a', { isolate: true });
  autumn.scene = { sky_mode: 'storybook_fallback', season: 'autumn' };
  const leafRenderer = rendererUnderAuthority(new FakeElement(), { prefersReducedMotion: true });
  leafRenderer.visualFrame = 150;
  assert.ok(leafRenderer.render(autumn).weatherReactions.settledLeaves > 0);
});

test('weather reaction counters require semantic object surfaces and plant canopies', () => {
  const empty = projection();
  empty.objects = [];
  empty.scene = { sky_mode: 'storybook_fallback', season: 'summer', weather: 'rain' };
  const rainRenderer = rendererUnderAuthority(new FakeElement(), { prefersReducedMotion: true });
  rainRenderer.visualFrame = 40;
  const rain = rainRenderer.render(empty).weatherReactions;
  assert.equal(rain.splashes, 0);
  assert.ok(rain.groundSplashes > 0);

  empty.scene = { sky_mode: 'storybook_fallback', season: 'winter', weather: 'snow' };
  const snowRenderer = rendererUnderAuthority(new FakeElement(), { prefersReducedMotion: true });
  snowRenderer.visualFrame = 90;
  const snow = snowRenderer.render(empty).weatherReactions;
  assert.equal(snow.snowCaps, 0);
  assert.ok(snow.groundSnow > 0);

  empty.scene = { sky_mode: 'storybook_fallback', season: 'autumn' };
  const leafRenderer = rendererUnderAuthority(new FakeElement(), { prefersReducedMotion: true });
  leafRenderer.visualFrame = 150;
  assert.equal(leafRenderer.render(empty).weatherReactions.settledLeaves, 0);
});

test('semantic focus visibly marks the same canonical object', () => {
  const renderer = rendererUnderAuthority(new FakeElement(), { prefersReducedMotion: true });
  renderer.setFocusedObject('plant:a');
  const frame = renderer.render(projectionCenteredOn('plant:a', { isolate: true }));
  const plant = frame.layout.find(entry => entry.object.object_id === 'plant:a');
  // The caret is renderer-authored ink with no accepted identity, so under
  // the mandatory authority it is recorded and suppressed -- in the product
  // too, which means focus currently has NO visible mark (Failure Log
  // 2026-08-04; giving the mark an accepted identity is register work the
  // operator decides, not renderer work). The machinery fact pinned here:
  // focus places the caret attempt at the marked object's anchor column,
  // one row above its picture, and that anonymous ink never escapes.
  const caretRow = Math.max(0, plant.rect.top - 1);
  const caret = frame.attempted_primitives.filter(item =>
    item.glyph === '⌄' && item.x === plant.anchor[0] && item.y === caretRow);
  assert.equal(caret.length, 1, 'the focus caret was not attempted at the focused object');
  assert.equal(caret[0].suppressed, true, 'anonymous caret ink escaped suppression');
});

test('night rendering publishes page theme and has no animal-like ambient glyphs', () => {
  const data = projection();
  data.effective_time = Date.UTC(2026, 9, 22, 2) / 1000;
  data.objects = [];
  const themes = [];
  const renderer = rendererUnderAuthority(new FakeElement(), {
    onTheme: theme => themes.push(theme.mode),
  });
  const frame = renderer.render(data);
  assert.deepEqual(themes, ['night']);
  assert.doesNotMatch(frame.lines.join('\n'), />\<|\{\}/);
  renderer.clear();
  assert.deepEqual(themes, ['night', 'day']);
});

test('storybook night sky is dense deterministic and stable within a civil day', () => {
  const sky = { mode: 'storybook_fallback', astronomical: false, region: null };
  const first = projectSkyPoints(sky, Date.UTC(2026, 6, 22, 1) / 1000, [128, 48]);
  const later = projectSkyPoints(sky, Date.UTC(2026, 6, 22, 23) / 1000, [128, 48]);
  const tomorrow = projectSkyPoints(sky, Date.UTC(2026, 6, 23, 1) / 1000, [128, 48]);
  assert.ok(first.length >= 30);
  assert.deepEqual(first, later);
  assert.notDeepEqual(first, tomorrow);
  assert.ok(new Set(first.map(([x, y]) => `${x},${y}`)).size >= first.length * 0.9);

  const data = projection();
  data.objects = [];
  data.observed_time = Date.UTC(2026, 6, 22, 22) / 1000;
  const element = new FakeElement();
  element.clientWidth = 1024; element.clientHeight = 720;
  const night = rendererUnderAuthority(element, {
    prefersReducedMotion: true,
  }).render(data);
  const skyGlyphs = night.lines.slice(0, night.profile.bandTop).join('');
  assert.ok((skyGlyphs.match(/[.*·✦]/g) ?? []).length >= 20);
});

// REPLACED 2026-08-01: 'day sky birds stay presentation-only and never enter
// canonical layout' REQUIRED the archived `\v/ _v_ /v\` flap glyphs to appear
// in a daytime frame.
//
// The operator identified those birds in a live product frame as content they
// had never individually accepted. A test that requires unapproved decoration
// is not coverage; it is the decoration's guarantee of survival. This is the
// sixth time in four days a test has been found protecting an unreviewed
// visual, and the third to be handled by replacing it with its own inverse.
//
// What survives is the half that was always a real contract: whatever the sky
// draws, it must never acquire canonical identity. That property is worth
// keeping regardless of which drawings the sky ends up holding.
test('nothing the sky draws ever enters canonical layout', () => {
  const data = projection();
  data.effective_time = Date.UTC(2026, 9, 22, 12) / 1000;
  data.objects = [];
  const frame = rendererUnderAuthority(new FakeElement()).render(data);
  assert.deepEqual(frame.layout, []);
  // And, for now, the sky draws nothing at all: no unaccepted asset may ship.
  assert.doesNotMatch(frame.lines.join('\n'), /\\v\/|_v_|\/v\\/,
    'unaccepted distant-bird art is being drawn again');
});

test('memorial presentation remains visible without inventing a perch bird', () => {
  const data = projection();
  data.objects = [];
  data.observed_time = Date.UTC(2026, 6, 22, 12) / 1000;
  data.scene = { sky_mode: 'storybook_fallback', season: 'summer', memorial: { active: true } };
  const frame = rendererUnderAuthority(
    new FakeElement(), { prefersReducedMotion: true },
  ).render(data);
  const picture = frame.lines.join('\n');
  assert.match(picture, /@@@/);
  assert.deepEqual(frame.layout, []);
});

// REMOVED 2026-07-31: 'ground cover forms a continuous full-width garden bed'.
//
// It required at least 60% of columns to carry ground cover and required the
// two rows at the horizon to be entirely non-blank. `_drawGroundCover`
// satisfied it by repeating a `__/\___` unit across the whole width, and the
// operator rejected exactly that band on sight.
//
// The test is deleted rather than loosened because there is currently no
// approved answer for what the ground should look like. The composition is
// being rebuilt around the "one band / one surface" rule, and writing a
// replacement assertion now would once again pin a decision nobody has made --
// which is precisely how a suite came to report 140/140 while protecting a
// rejected visual. A new test belongs here once a ground composition has been
// approved, and not before.

// REPLACED 2026-07-31: 'ambient life is differentiated across day night and
// winter' required at least three `⋈` butterflies in daylight and at least
// five `·`/`✦` fireflies at night.
//
// That art was never submitted for per-asset acceptance, and in the live
// capture the butterflies were precisely what the operator had already
// rejected: scattered multicolour marks, sitting in the ground region rather
// than the sky. A test that REQUIRES unapproved decoration is not coverage --
// it is the decoration's guarantee of survival.
//
// It is replaced rather than deleted, by its own inverse: the default scene
// must contain none of it. That keeps the suite honest about what ships and
// makes an accidental reintroduction fail. When a population is drawn and
// accepted, this becomes an assertion about that population instead.
test('no unapproved ambient fauna is drawn in the default scene', () => {
  const data = projection();
  data.objects = [];
  data.scene = { sky_mode: 'storybook_fallback', season: 'summer' };
  const renderer = rendererUnderAuthority(new FakeElement());
  renderer.visualFrame = 1;
  for (const [hour, season] of [[12, 'summer'], [23, 'summer'], [23, 'winter']]) {
    data.scene.season = season;
    data.observed_time = Date.UTC(2026, 6, 22, hour) / 1000;
    const frame = renderer.render(data).lines.join('');
    assert.doesNotMatch(frame, /[⋈⋊✦]/, `${season} at ${hour}h`);
  }
});

test('browser renderer uses per-object parallax and projection-hotspot hit testing', () => {
  let selected = null;
  const data = { ...projection(), camera: [0, 0], objects: [{
    object_id: 'collectible:foreground', kind: 'collectible', semantic_name: 'foreground',
    position: [5, 0], depth: 110, hotspot: { x: 5, y: 0, width: 1, height: 1 },
    semantic_state: { family: 'feather' },
  }] };
  const element = new FakeElement();
  const renderer = rendererUnderAuthority(element, {
    onSelect: object => { selected = object.object_id; },
  });
  const frame = renderer.render(data);
  const entry = frame.layout[0], [x, y] = entry.anchor;
  assert.ok(entry.baseAnchor[0] > Math.floor(frame.viewport[0] / 2));
  // The feather is drawn, not marked. Previously this asserted the single
  // legacy character `⌇`; a collectible now paints its own picture, so the
  // check is that the picture's own last line lands on the anchor row.
  const bottom = entry.art.lines[entry.art.lines.length - 1];
  assert.ok(entry.art.lines.length >= 2, 'collectible art must not be a bare mark');
  // Collectible ink stays anonymous until atlas ownership arrives, so under
  // the mandatory authority it is recorded and suppressed -- the product
  // shows no feather. The machinery fact: the picture's last line was
  // attempted on the anchor row, centred on the anchor column, and none of
  // that anonymous ink escaped suppression.
  const ink = attemptedInkOf(frame, 'collectible:foreground');
  const anchorStart = x - Math.floor([...bottom].length / 2);
  [...bottom].forEach((glyph, index) => {
    if (glyph === ' ') return;
    assert.ok(ink.some(([atX, atY, attempted]) =>
      atX === anchorStart + index && atY === y && attempted === glyph),
    `feather glyph ${JSON.stringify(glyph)} was not attempted at its anchor cell`);
  });
  assert.ok(ink.every(item => item[3]), 'anonymous collectible ink escaped suppression');
  assert.deepEqual(entry.hitRect, {
    left: entry.baseAnchor[0] + entry.anchor[0] - entry.baseAnchor[0],
    right: entry.baseAnchor[0] + entry.anchor[0] - entry.baseAnchor[0],
    top: entry.baseAnchor[1] + entry.anchor[1] - entry.baseAnchor[1],
    bottom: entry.baseAnchor[1] + entry.anchor[1] - entry.baseAnchor[1],
  });
  renderer._selectAt({ clientX: entry.hitRect.left * renderer.cellWidth + 1,
    clientY: entry.hitRect.top * renderer.cellHeight + 1 });
  assert.equal(selected, 'collectible:foreground');
});

test('browser renderer rejects a missing projection-owned hotspot', () => {
  const data = projection();
  delete data.objects[0].hotspot;
  assert.throws(() => rendererUnderAuthority(new FakeElement()).render(data),
    /projection-owned hotspot/);
});

test('browser accessible summary exposes bounded missed-event summaries', () => {
  const data = projection();
  data.scene.missed_event_summaries = ['one waited', 'two waited', 'three waited'];
  const element = new FakeElement();
  rendererUnderAuthority(element).render(data);
  assert.match(element.attributes['aria-label'], /While you were away: one waited two waited three waited/);
});

test('browser accessible summary bounds large inventory announcements', () => {
  const data = projection();
  data.scene.inventory = ['acorn', 'feather', 'flower', 'key', 'leaf', 'snowflake', 'sprig'];
  const element = new FakeElement();
  rendererUnderAuthority(element).render(data);
  assert.match(element.attributes['aria-label'], /Inventory: acorn, feather, flower, key, leaf; and 2 more\./);
  assert.doesNotMatch(element.attributes['aria-label'], /snowflake|sprig/);
});

test('renderer clear purges authored rows projection and accessible prose', () => {
  const element = new FakeElement();
  const renderer = rendererUnderAuthority(element);
  renderer.render(projection());
  assert.ok(renderer.rows.length > 0);
  assert.match(element.attributes['aria-label'], /Garden with 1 plants, 2 fixtures/);
  renderer.clear();
  assert.equal(renderer.projection, null);
  assert.equal(renderer.lastFrame, null);
  assert.deepEqual(renderer.rows, []);
  assert.deepEqual(element.children, []);
  assert.equal(element.attributes['aria-label'], 'Generic Garden preview.');
});

test('raster hit testing consumes the packed canonical hotspot', () => {
  let selected = null;
  const element = new FakeElement();
  element.clientWidth = 330; element.clientHeight = 156;
  const renderer = rendererUnderAuthority(element, { onSelect: object => { selected = object.object_id; } });
  const frame = renderer.render(projectionCenteredOn('plant:a', { isolate: true }));
  const target = frame.layout.find(entry => entry.object.object_id === 'plant:a').hitRect;
  renderer._selectAt({ clientX: target.left * renderer.cellWidth + 1,
    clientY: target.top * renderer.cellHeight + 1 });
  assert.equal(selected, 'plant:a');
});

test('measured cell geometry API drives canonical-hotspot hit testing', () => {
  let selected = null;
  const element = new FakeElement();
  const renderer = rendererUnderAuthority(element, { onSelect: object => { selected = object.object_id; } });
  renderer.setCellGeometry(11, 13);
  const frame = renderer.render(projectionCenteredOn('plant:a', { isolate: true }));
  const target = frame.layout.find(entry => entry.object.object_id === 'plant:a').hitRect;
  renderer._selectAt({ clientX: target.left * 11 + 1, clientY: target.top * 13 + 1 });
  assert.equal(selected, 'plant:a');
});

test('normal raster selection gives one-cell objects a 44px minimum target', () => {
  let selected = null;
  const element = new FakeElement();
  const renderer = rendererUnderAuthority(element, { onSelect: object => { selected = object.object_id; } });
  renderer.setCellGeometry(8, 15);
  const frame = renderer.render(projectionCenteredOn('plant:a', { isolate: true }));
  const plant = frame.layout.find(entry => entry.object.object_id === 'plant:a');
  renderer._selectAt({ clientX: (plant.hitRect.left - 1) * 8 + 1,
    clientY: plant.hitRect.top * 15 + 1 });
  assert.equal(selected, 'plant:a');
});

test('feed presentation retains exact canonical animal target identity', () => {
  const data = projection();
  data.objects = [{
    object_id: 'animal:rabbit:first', kind: 'animal', semantic_name: 'first rabbit',
    position: [8, 5], depth: 110, hotspot: { x: 8, y: 5, width: 1, height: 1 },
    semantic_state: { species_id: 'rabbit', bond_tier: 1, intent: 'rest' },
  }, {
    object_id: 'animal:rabbit:second', kind: 'animal', semantic_name: 'second rabbit',
    position: [14, 5], depth: 110, hotspot: { x: 14, y: 5, width: 1, height: 1 },
    semantic_state: { species_id: 'rabbit', bond_tier: 1, intent: 'rest' },
  }];
  const renderer = rendererUnderAuthority(new FakeElement());
  renderer.render(data);
  renderer.triggerAnimalFeedReaction({ objectId: 'animal:rabbit:second' });
  renderer.render(data);
  assert.equal(renderer.presentationState.clickBursts.at(-1)?.objectId, 'animal:rabbit:second');
  const count = renderer.presentationState.clickBursts.length;
  renderer.triggerAnimalFeedReaction({ objectId: 'animal:rabbit:missing' });
  renderer.render(data);
  assert.equal(renderer.presentationState.clickBursts.length, count);
});

test('rough sky location is immediately quantized and raw coordinates are discarded', async () => {
  const raw = { latitude: 35.681236, longitude: 139.767125 };
  const geolocation = { getCurrentPosition: callback => callback({ coords: raw }) };
  const coarse = await requestRoughSkyLocation({ geolocation });
  assert.deepEqual(coarse, { latitude_cell: 36, longitude_cell: 140, grid_degrees: 1 });
  assert.deepEqual(quantizeRoughLocation(-33.86, 151.21), {
    latitude_cell: -34, longitude_cell: 151, grid_degrees: 1,
  });
  assert.equal(JSON.stringify(coarse).includes('35.681236'), false);
});

test('browser sky agrees with all twelve trusted USNO vectors', () => {
  const payload = JSON.parse(readFileSync(
    new URL('../garden_contract/fixtures/astronomy_vectors.v1.json', import.meta.url), 'utf8',
  ));
  assert.equal(payload.vectors.length, 12);
  for (const vector of payload.vectors) {
    const seconds = Date.parse(vector.timestamp) / 1000;
    const gast = greenwichApparentSiderealTime(seconds);
    const [altitude, azimuth] = altAz({ gastHours: gast, raHours: vector.ra_hours,
      decDegrees: vector.dec_degrees, latitude: vector.latitude, longitude: vector.longitude });
    assert.ok(Math.abs(gast - vector.gast_hours) < 0.25);
    assert.ok(Math.abs(altitude - vector.altitude_degrees) < 0.25);
    assert.ok(Math.abs(azimuth - vector.azimuth_degrees) < 0.25);
  }
});

test('browser sky uses the complete canonical 24-star catalog', () => {
  const canonical = JSON.parse(readFileSync(
    new URL('../../src/lateletter/garden/data/bright-stars.v1.json', import.meta.url), 'utf8',
  ));
  const skySource = readFileSync(
    new URL('../../web/garden-sky.mjs', import.meta.url), 'utf8',
  );
  assert.equal(BRIGHT_STAR_CATALOG.length, 24);
  assert.match(skySource, /import BRIGHT_STAR_DATA from .*bright-stars\.v1\.json/);
  assert.doesNotMatch(skySource, /6\.75247222/);
  assert.deepEqual(BRIGHT_STAR_CATALOG.map(item => item[0]),
    canonical.stars.map(item => item.id));
  assert.deepEqual(BRIGHT_STAR_CATALOG.map(item => item[1]),
    canonical.stars.map(item => item.ra_hours));
  assert.deepEqual(BRIGHT_STAR_CATALOG.map(item => item[2]),
    canonical.stars.map(item => item.dec_degrees));
});

test('ten-minute pan simulation keeps initialized scenery and partial row diffs', () => {
  const element = new FakeElement();
  const renderer = rendererUnderAuthority(element);
  const data = projection();
  renderer.render(data);
  for (let second = 1; second <= 600; second += 1) {
    const frame = renderer.render({ ...data, camera: [10 + second, 5] });
    assert.equal(frame.lines[frame.horizon].includes('.'), true);
    assert.ok(frame.changedRows.length < frame.viewport[1]);
  }
});

// ─── Ground contract, identity and continuity ────────────────────────────────
// These cover the three properties the Garden lost when the five-layer browser
// presentation was replaced: things stood on nothing, objects could not be told
// apart, and the sky was reserved but empty.

// REWRITTEN 2026-08-01. The previous version of this test carried the word
// "painted" in its name and never rendered anything. It read the LAYOUT and
// checked that each object's foot row fell inside `[groundBack, groundFront]`,
// which is a statement about arithmetic, not about pixels. That is why it
// stayed green through the exact defect it is named for: the compositor put
// feet on `groundFront` while `_drawGround` painted `horizon` and `horizon + 1`,
// so every fixture in the live capture stood on empty air and the suite
// reported nothing wrong.
//
// A test about paint has to look at paint. This one renders a real frame from
// the real starter world and reads the characters back out of it.
const SOIL_GLYPHS = new Set(['.', ',', '*', '`']);

test('every ground-dwelling object rests on a painted soil line', async () => {
  // Desktop and phone. The soil line is placed as a fraction of frame height,
  // so the two sizes exercise genuinely different rows.
  for (const [pixelWidth, pixelHeight] of [[1600, 1000], [390, 844]]) {
    const element = new FakeElement();
    element.clientWidth = pixelWidth;
    element.clientHeight = pixelHeight;
    const renderer = rendererUnderAuthority(element);
    const state = await generateInitialWorld('ground-paint', 'ground-paint-seed');
    const data = await projectGardenScene(state);
    // Clear weather, so the only thing that can put a glyph on the ground row
    // is the ground itself or an object standing on it. A rain streak landing
    // on the soil line would otherwise make this test fail for a reason that
    // has nothing to do with the contract it is guarding.
    data.scene = { ...data.scene, weather: 'clear' };
    const frame = renderer.render(data);

    // One answer to "where is the ground", read the way the rest of the
    // program reads it.
    const groundY = gardenGroundY(frame.viewport);
    assert.equal(frame.profile.groundFront, groundY,
      `gardenGroundY disagrees with the profile at ${pixelWidth}x${pixelHeight}`);
    assert.ok(frame.layout.length > 0,
      `nothing was laid out at ${pixelWidth}x${pixelHeight}`);

    const line = [...frame.lines[groundY]];
    // Columns an object's own drawing occupies. Art paints over the soil, so
    // these are the cells where a soil glyph is legitimately absent.
    const covered = new Set();
    for (const entry of frame.layout) {
      assert.equal(entry.lift, 0,
        `${entry.object.object_id} is a ground-dwelling kind and must not be lifted`);
      assert.equal(entry.rect.bottom, groundY,
        `${entry.object.object_id}'s feet are on row ${entry.rect.bottom}, ` +
        `but the ground is row ${groundY}`);
      for (let column = entry.rect.left; column <= entry.rect.right; column += 1) {
        covered.add(column);
      }
    }

    // THE ASSERTION THAT MATTERS. Every cell of the foot row that no object is
    // standing on must hold soil. Move the paint back to `horizon` and this
    // fails on the first uncovered column, because the row is then blank
    // between the fixtures -- which is exactly what the capture showed.
    for (let column = 0; column < frame.viewport[0]; column += 1) {
      if (covered.has(column)) continue;
      assert.ok(SOIL_GLYPHS.has(line[column]),
        `at ${pixelWidth}x${pixelHeight} the ground row ${groundY} holds ` +
        `${JSON.stringify(line[column])} at column ${column}, not soil — ` +
        'the objects are standing on nothing');
    }
  }
});

// The five starter fixtures, in the order the canonical anchors place them
// left to right. Named here so a failure says which fixture went missing.
const STARTER_ROW = ['stepping_stones', 'bench', 'mailbox', 'lantern', 'planter'];

test('the authoritative starter row is whole, separate and stable', async () => {
  const state = await generateInitialWorld('starter-row', 'starter-row-seed');
  const data = await projectGardenScene(state);
  const catalogOf = entry => String(entry.object.semantic_state?.catalog_id ?? '');

  // The world declares five. Anything the picture loses from here on is the
  // presentation losing it, not the world never having had it -- a distinction
  // the first single-surface capture could not make, which is why "three
  // fixtures visible" took a live screenshot to notice.
  // Filtered to fixtures. The default scene also plants an oak and a sunflower
  // since the legacy art port, and this test is about the FIXTURE row: the
  // claim it defends is that all five fixtures survive from world to picture,
  // which is unchanged by there being other objects in the world. The plants
  // are held to their own contract in 'restoring the ported plants leaves the
  // authoritative fixture row alone'.
  const fixtures = data.objects.filter(object => object.kind === 'fixture');
  assert.deepEqual(
    fixtures.map(object => String(object.semantic_state?.catalog_id ?? '')).sort(),
    [...STARTER_ROW].sort(),
  );

  // ── Desktop, 1600x1000 ──────────────────────────────────────────────────
  // At eight pixels per cell and fifteen per row, that is a 200x66 grid.
  const desktop = [200, 66];
  const layout = layoutGardenObjects(data, desktop, 0)
    .filter(entry => entry.object.kind === 'fixture');
  assert.deepEqual(layout.map(catalogOf).sort(), [...STARTER_ROW].sort(),
    'a starter fixture is missing from the desktop composition');

  // Non-overlapping, pairwise. This is the assertion that would have caught
  // the collision: the planter and the stepping stones were still in the
  // layout, they were simply drawn underneath the mailbox, so a count of five
  // proved nothing.
  const sorted = [...layout].sort((left, right) => left.rect.left - right.rect.left);
  for (let index = 1; index < sorted.length; index += 1) {
    assert.ok(sorted[index].rect.left > sorted[index - 1].rect.right,
      `${catalogOf(sorted[index - 1])} and ${catalogOf(sorted[index])} overlap: ` +
      `columns ${sorted[index - 1].rect.left}-${sorted[index - 1].rect.right} ` +
      `and ${sorted[index].rect.left}-${sorted[index].rect.right}`);
  }
  assert.deepEqual(sorted.map(catalogOf), STARTER_ROW,
    'the canonical left-to-right order of the starter row changed');

  // ── Phone, 390x844 → a 48x56 grid ───────────────────────────────────────
  // Cropping is expected and correct: a phone is a camera into the same world,
  // not a request to crush it. What the crop must NOT do is lose the two
  // fixtures the interaction slice is built on. The outer two are deliberately
  // not asserted either way -- whether they survive the crop is a camera
  // question, and pinning it here would freeze a composition decision.
  const phone = layoutGardenObjects(data, [48, 56], 0).map(catalogOf);
  for (const catalogId of ['bench', 'mailbox', 'lantern']) {
    assert.ok(phone.includes(catalogId),
      `the phone crop lost the ${catalogId}; it kept ${JSON.stringify(phone)}`);
  }

  // ── Stability ───────────────────────────────────────────────────────────
  // Art animates; placement does not. Neither an advancing frame nor a focus
  // highlight may move a fixture the reader was not touching.
  const signature = entries => entries
    .map(entry => `${catalogOf(entry)}@${entry.anchor.join(',')}`).sort().join('|');
  const base = signature(layout);
  for (const frame of [1, 7, 23, 96, 501]) {
    assert.equal(signature(layoutGardenObjects(data, desktop, frame)
      .filter(entry => entry.object.kind === 'fixture')), base,
    `frame ${frame} moved a fixture`);
  }
  const element = new FakeElement();
  element.clientWidth = 1600; element.clientHeight = 1000;
  const renderer = rendererUnderAuthority(element);
  const before = renderer.render(data);
  renderer.setFocusedObject(before.layout[0].object.object_id);
  assert.equal(signature(renderer.render(data).layout), signature(before.layout),
    'focusing one fixture moved another');
});

test('an object reports its drawing and its hotspot separately', async () => {
  // These two rectangles are NOT interchangeable, and treating them as one is a
  // defect with a visible symptom. `objectRectPixels` is the canonical hotspot:
  // one world cell for a lantern, a few pixels wide, and the only thing allowed
  // to decide what a click selects. `objectArtRectPixels` is where the ink is:
  // a post and a lamp head, several times wider.
  //
  // Presentation diagnostics may inspect the second, while selection must use
  // the first. Redrawing visible ink must never silently redefine the target.
  const element = new FakeElement();
  element.clientWidth = 1600; element.clientHeight = 1000;
  const renderer = rendererUnderAuthority(element);
  const state = await generateInitialWorld('art-rect', 'art-rect-seed');
  const frame = renderer.render(await projectGardenScene(state));

  let wider = 0;
  for (const entry of frame.layout) {
    const id = entry.object.object_id;
    const hotspot = renderer.objectRectPixels(id);
    const art = renderer.objectArtRectPixels(id);
    assert.ok(hotspot && art, `${id} reported no rectangles`);
    // The drawing never reports narrower than the footprint it stands on.
    assert.ok(art.width >= hotspot.width - 0.001, `${id}: art ${art.width} < hotspot ${hotspot.width}`);
    if (art.width > hotspot.width + 0.001) wider += 1;
  }
  assert.ok(wider > 0,
    'no fixture drew wider than its hotspot, so the two rectangles were never ' +
    'actually distinguished by this test');
  assert.equal(renderer.objectArtRectPixels('nothing:here'), null);
});

test('only a bird in flight leaves the ground, and never beyond a bounded height', () => {
  const viewport = [120, 48];
  const profile = gardenPresentationProfile(viewport);
  const build = (species, intent) => {
    const data = projection();
    data.objects = [{
      object_id: `animal:${species}`, kind: 'animal', semantic_name: species,
      position: [10, 5], depth: 100, hotspot: { x: 10, y: 5, width: 1, height: 1 },
      semantic_state: { species_id: species, intent },
    }];
    return layoutGardenObjects(data, viewport, 0)[0];
  };
  for (const species of ['cat', 'rabbit', 'turtle']) {
    assert.equal(build(species, 'greet').lift, 0, `${species} must stay on the ground`);
  }
  // A resting bird is on the ground exactly like every other animal.
  assert.equal(build('bird', 'rest').lift, 0);
  const flying = build('bird', 'play');
  assert.ok(flying.lift > 0, 'an active bird should leave the ground');
  assert.ok(flying.lift <= 6, 'flight height must stay bounded');
  assert.ok(flying.rect.bottom >= profile.groundBack - 6);
  // Hit testing follows the picture up, so a bird can be clicked where it flies.
  assert.equal(flying.hitRect.bottom, flying.baseHitRect.bottom + (flying.anchor[1] - flying.baseAnchor[1]));
});

test('layout does not repack when the frame advances or an object is focused', () => {
  const viewport = [160, 52];
  const data = projection();
  const signature = layout => layout
    .map(entry => `${entry.object.object_id}@${entry.anchor.join(',')}`).sort().join('|');
  const base = signature(layoutGardenObjects(data, viewport, 0));
  assert.ok(base.length > 0);
  // Animation must not move anything: art changes, placement does not.
  for (const frame of [1, 7, 23, 96, 501]) {
    assert.equal(signature(layoutGardenObjects(data, viewport, frame)), base,
      `frame ${frame} repacked the scene`);
  }
  // Nor may a focus highlight, which is why the renderer keeps focus out of the
  // geometry it packs from.
  const renderer = rendererUnderAuthority(new FakeElement());
  const before = renderer.render(data);
  renderer.focusedObjectId = 'plant:a';
  const after = renderer.render(data);
  assert.equal(signature(after.layout), signature(before.layout),
    'focusing an object rearranged the Garden');
});

test('every fixture picture is recognisable and unique at every density', () => {
  const catalogIds = [
    'bench', 'arbor', 'sundial', 'trellis', 'birdbath', 'lantern', 'pond', 'mailbox',
    'memory_shrine', 'bridge', 'fence', 'gate', 'fence_gate', 'stepping_stone',
    'stepping_stones', 'planter', 'table', 'chair', 'table_chairs', 'well',
    'wind_chime', 'shed_edge', 'tool_rack', 'watering_can', 'compost', 'basket',
    'sign', 'memorial_stone',
  ];
  for (const viewport of [[205, 66], [120, 48], [40, 20]]) {
    const pictures = new Map(), firstLines = new Map();
    for (const catalogId of catalogIds) {
      const data = projection();
      data.objects = [{
        object_id: `fixture:${catalogId}`, kind: 'fixture', semantic_name: catalogId,
        position: [10, 5], depth: 100, hotspot: { x: 10, y: 5, width: 1, height: 1 },
        semantic_state: { catalog_id: catalogId },
      }];
      const entry = layoutGardenObjects(data, viewport, 0)[0];
      assert.ok(entry, `${catalogId} was not laid out at ${viewport}`);
      const picture = entry.art.lines.join('\n');
      assert.doesNotMatch(picture, /\$/, `${catalogId} fell back to a placeholder`);
      // A single character cannot depict a bench or a well.
      assert.ok(picture.replace(/\s/g, '').length >= 3,
        `${catalogId} is too small to recognise at ${viewport}`);
      assert.ok(!pictures.has(picture),
        `${catalogId} is identical to ${pictures.get(picture)} at ${viewport}`);
      pictures.set(picture, catalogId);
      // The first line is all that survives aggressive reduction, so it has to
      // carry identity on its own.
      const head = entry.art.lines[0];
      assert.ok(!firstLines.has(head),
        `${catalogId} shares its top line with ${firstLines.get(head)} at ${viewport}`);
      firstLines.set(head, catalogId);
    }
  }
});

test('sky life travels continuously and never impersonates a relationship animal', () => {
  const width = 120, skyTop = 1, skyBottom = 18;
  // Clouds remain a kept trajectory with no paint permission; their motion
  // contract is unchanged.
  const cloudPictures = new Set();
  for (let index = 0; index < 8; index += 1) {
    for (let frame = 0; frame < 120; frame += 1) {
      const before = skyCloudPresentation('sky-proof', index, frame, width, skyTop, skyBottom, 8);
      const after = skyCloudPresentation('sky-proof', index, frame + 1, width, skyTop, skyBottom, 8);
      cloudPictures.add(after.lines.join('\n'));
      const span = Math.max(8, width + Math.max(...before.lines.map(l => [...l].length)) + 4);
      const dx = Math.abs(after.x - before.x);
      assert.ok(Math.min(dx, span - dx) <= 1, `cloud ${index} jumped at frame ${frame}`);
      assert.equal(after.y, before.y, `cloud ${index} changed altitude at frame ${frame}`);
    }
  }
  assert.ok(cloudPictures.size >= 3, 'cloud catalogue collapsed to repeated bowls');
});

/**
 * Paint one sky frame through the real painter and return the bird cells.
 *
 * The traversal is judged on what actually lands in a raster, because that
 * is what a viewer sees; the spawn schedule alone cannot show a clamp or an
 * edge bound misfiring.
 */
function birdCellsAt(frame, cols, season = 'summer') {
  const raster = new Raster(cols, 40);
  const profile = gardenPresentationProfile([cols, 40]);
  drawSkyLife(raster, { world_id: 'sky-proof' }, DAY, season, profile, 'day', frame);
  return raster.attempted.filter(item =>
    item.source_id === 'recipe.ambient.bird_traversal' && item.glyph.trim());
}

test('the ambient bird traversal is the deployed recipe, edge to edge', () => {
  const cols = 120;
  const spawns = ambientBirdSpawns('sky-proof', 20000);
  assert.ok(spawns.length > 5, 'a long session produced almost no bird spawns');
  // The deployed interval: 250 plus up to 350 ticks, spawning the tick after
  // the threshold -- so consecutive spawn gaps sit in [251, 601].
  for (let i = 1; i < spawns.length; i += 1) {
    const gap = spawns[i].time - spawns[i - 1].time;
    assert.ok(gap >= 251 && gap <= 601, `respawn gap ${gap} is outside the deployed interval`);
  }
  // Determinism: the schedule is a pure function of (worldId, frame).
  assert.deepEqual(ambientBirdSpawns('sky-proof', 20000), spawns);

  // Follow the first spawn across the sky, frame by frame.
  const spawn = spawns[0];
  let previousXs = null;
  let firstSeen = null, lastSeen = null;
  let minX = Infinity, maxX = -Infinity;
  const frameGlyphs = new Set();
  for (let frame = spawn.time; frame < spawn.time + Math.ceil((cols + 20) / 0.42); frame += 1) {
    const cells = birdCellsAt(frame, cols);
    if (!cells.length) { previousXs = null; continue; }
    const xs = cells.map(cell => cell.x);
    if (firstSeen === null) firstSeen = { frame, x: Math.min(...xs) };
    lastSeen = { frame, xs };
    minX = Math.min(minX, ...xs);
    maxX = Math.max(maxX, ...xs);
    cells.forEach(cell => frameGlyphs.add(cell.glyph));
    // Continuous travel: at 0.42 cells a tick, no painted column moves more
    // than one cell between consecutive frames.
    if (previousXs !== null) {
      const step = Math.abs(Math.min(...xs) - Math.min(...previousXs));
      assert.ok(step <= 1, `the bird jumped ${step} cells in one tick at frame ${frame}`);
    }
    previousXs = xs;
  }
  assert.ok(firstSeen, 'the first spawn never painted at all');
  // The crossing reaches from one edge region to the other: painting begins
  // within a few cells of an edge and the swept range covers the full width.
  assert.ok(minX <= 2, `the bird first appeared at ${minX}, not at an edge`);
  assert.ok(maxX >= cols - 3, `the bird disappeared at ${maxX}, before the far edge`);
  // Only the archived flap glyphs ever paint at desktop width.
  const archived = new Set(AMBIENT_BIRD_FRAMES.flatMap(value => [...value]));
  for (const glyph of frameGlyphs) {
    assert.ok(archived.has(glyph), `unarchived bird glyph ${JSON.stringify(glyph)}`);
  }
});

test('below sixty columns the deployed compact frames paint, and winter is empty', () => {
  // Find any frame where a phone-width bird is on screen.
  let compactSeen = new Set();
  for (let frame = 0; frame < 4000; frame += 1) {
    for (const cell of birdCellsAt(frame, 49)) compactSeen.add(cell.glyph);
    if (compactSeen.size) break;
  }
  assert.ok(compactSeen.size > 0, 'no phone-width bird painted in 4000 ticks');
  const compact = new Set(AMBIENT_BIRD_COMPACT_FRAMES.flatMap(value => [...value]));
  for (const glyph of compactSeen) {
    assert.ok(compact.has(glyph),
      `phone bird painted ${JSON.stringify(glyph)}, not the deployed compact pair`);
  }
  // Winter: the deployed viewer stops spawning; this port paints nothing.
  for (let frame = 0; frame < 4000; frame += 200) {
    assert.equal(birdCellsAt(frame, 120, 'winter').length, 0,
      'a bird painted in winter');
  }
});

// REPLACED 2026-08-01: 'daylight inhabits the sky it reserves' required at
// least four inked sky lines, a cloud body matching /\(___/, and the archived
// distant-bird glyphs.
//
// Every one of those was a requirement that specific unaccepted drawings be
// present. The sky is now deliberately empty, and this test would have blocked
// emptying it while reporting a healthy suite -- the same failure mode as the
// ground-cover band and the butterflies.
//
// The one assertion that was never about a drawing is kept: the sky must not
// eat the frame. That is a proportion contract, and it holds whether the sky is
// full or empty.
test('the reserved sky never dwarfs the Garden, and holds no unaccepted art', () => {
  const data = projection();
  data.objects = [];
  data.observed_time = Date.UTC(2026, 6, 22, 12) / 1000;
  data.scene = { sky_mode: 'storybook_fallback', season: 'summer' };
  const element = new FakeElement();
  element.clientWidth = 1600; element.clientHeight = 1000;
  const renderer = rendererUnderAuthority(element);
  renderer.visualFrame = 5;
  const frame = renderer.render(data);
  assert.ok(frame.profile.bandTop < frame.viewport[1] * 0.5,
    'more than half the frame is still reserved for sky');
  const sky = frame.lines.slice(0, frame.profile.bandTop).join('\n');
  assert.doesNotMatch(sky, /\(___/, 'unaccepted cloud art is being drawn again');
  assert.doesNotMatch(sky, /\\v\/|_v_|\/v\\/,
    'unaccepted distant-bird art is being drawn again');
});
