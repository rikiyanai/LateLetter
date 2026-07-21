import assert from 'node:assert/strict';
import test from 'node:test';
import { readFileSync } from 'node:fs';

import {
  CanonicalGardenRenderer, connectedMasks, screenToWorld, worldToScreen,
} from '../../web/garden-renderer.mjs';
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
  requestRoughSkyLocation,
} from '../../web/garden-sky.mjs';

class FakeRow {
  constructor() { this.textContent = ''; this.attributes = {}; }
  setAttribute(key, value) { this.attributes[key] = value; }
  remove() {}
}

class FakeElement {
  constructor() { this.clientWidth = 320; this.clientHeight = 150; this.children = []; this.attributes = {}; }
  setAttribute(key, value) { this.attributes[key] = value; }
  addEventListener(kind, callback) { this.listener = kind === 'click' ? callback : this.listener; }
  appendChild(child) { this.children.push(child); }
  replaceChildren() { this.children = []; }
  getBoundingClientRect() { return { left: 0, top: 0 }; }
}

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

test('camera transform and inverse share the same canonical coordinates', () => {
  const viewport = [40, 10], camera = [10, 5], world = [13, 7];
  assert.deepEqual(screenToWorld(worldToScreen(world, camera, viewport), camera, viewport), world);
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
  const renderer = new CanonicalGardenRenderer(element, { prefersReducedMotion: true });
  const first = renderer.render(data);
  assert.ok(first.changedRows.length > 0);
  assert.equal(first.motionPaused, true);
  const second = renderer.render(data);
  assert.deepEqual(second.changedRows, []);
  element.clientWidth = 400;
  renderer.onResize();
  assert.deepEqual(data, before);
  assert.match(renderer.lastFrame.lines.join('\n'), /[@+\-]/);
});

test('browser renderer paints every canonical fixture footprint cell', () => {
  const data = projection();
  data.objects.push({
    object_id: 'fixture:table', kind: 'fixture', semantic_name: 'table', position: [10, 5],
    depth: 120, hotspot: { x: 10, y: 5, width: 2, height: 2 },
    semantic_state: { catalog_id: 'table_chairs', presentation_state: 'idle',
      connected_group: null, connected_mask: 0, render_cells: [
        { dx: 0, dy: 0, connected_mask: 0 }, { dx: 1, dy: 0, connected_mask: 0 },
        { dx: 0, dy: 1, connected_mask: 0 }, { dx: 1, dy: 1, connected_mask: 0 },
      ] },
  });
  const frame = new CanonicalGardenRenderer(new FakeElement()).render(data);
  const [x, y] = worldToScreen([10, 5], [10, 5], frame.viewport);
  assert.equal(frame.lines[y].slice(x, x + 2), 'TT');
  assert.equal(frame.lines[y + 1].slice(x, x + 2), 'TT');
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
      const frame = new CanonicalGardenRenderer(new FakeElement()).render(data);
      assert.equal(frame.lines[Math.floor(frame.viewport[1] / 2)][Math.floor(frame.viewport[0] / 2)],
        connectedGlyph(mask, group));
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
      const frame = new CanonicalGardenRenderer(new FakeElement()).render(data);
      const expected = ATLAS_MANIFEST.semantic_tokens.animal_tier_glyphs[speciesId][tier];
      assert.equal(glyphForProjection(object), expected);
      assert.equal(frame.lines[Math.floor(frame.viewport[1] / 2)][Math.floor(frame.viewport[0] / 2)], expected);
      assert.match(object.semantic_state.semantic_description, new RegExp(`bond tier ${tier}`));
      assert.match(object.semantic_state.semantic_description, /greet; personality playfulness; 1 memories/);
    }
  }
});

test('browser renderer uses per-object parallax depth and inverse hit testing', () => {
  let selected = null;
  const data = { ...projection(), camera: [0, 0], objects: [{
    object_id: 'collectible:foreground', kind: 'collectible', semantic_name: 'foreground',
    position: [5, 0], depth: 110, hotspot: { x: 5, y: 0, width: 1, height: 1 },
    semantic_state: { family: 'feather' },
  }] };
  const element = new FakeElement();
  const renderer = new CanonicalGardenRenderer(element, {
    onSelect: object => { selected = object.object_id; },
  });
  const frame = renderer.render(data);
  const [x, y] = worldToScreen([5, 0], [0, 0], frame.viewport, 1.1);
  assert.equal(x, Math.floor(frame.viewport[0] / 2) + 6);
  assert.equal(frame.lines[y][x], glyphForProjection(data.objects[0]));
  renderer._selectAt({ clientX: x * renderer.cellWidth + 1, clientY: y * renderer.cellHeight + 1 });
  assert.equal(selected, 'collectible:foreground');
});

test('browser accessible summary exposes bounded missed-event summaries', () => {
  const data = projection();
  data.scene.missed_event_summaries = ['one waited', 'two waited', 'three waited'];
  const element = new FakeElement();
  new CanonicalGardenRenderer(element).render(data);
  assert.match(element.attributes['aria-label'], /While you were away: one waited two waited three waited/);
});

test('renderer clear purges authored rows projection and accessible prose', () => {
  const element = new FakeElement();
  const renderer = new CanonicalGardenRenderer(element);
  renderer.render(projection());
  assert.ok(renderer.rows.length > 0);
  assert.match(element.attributes['aria-label'], /Garden objects/);
  renderer.clear();
  assert.equal(renderer.projection, null);
  assert.equal(renderer.lastFrame, null);
  assert.deepEqual(renderer.rows, []);
  assert.deepEqual(element.children, []);
  assert.equal(element.attributes['aria-label'], 'Generic Garden preview.');
});

test('raster hit testing inverts the same camera and selects canonical object', () => {
  let selected = null;
  const element = new FakeElement();
  element.clientWidth = 330; element.clientHeight = 156;
  const renderer = new CanonicalGardenRenderer(element, { onSelect: object => { selected = object.object_id; } });
  renderer.render(projection());
  const [x, y] = worldToScreen([10, 5], [10, 5], renderer.measure());
  renderer._selectAt({ clientX: x * renderer.cellWidth + 1, clientY: y * renderer.cellHeight + 1 });
  assert.equal(selected, 'plant:a');
});

test('measured cell geometry API drives responsive hit testing', () => {
  let selected = null;
  const element = new FakeElement();
  const renderer = new CanonicalGardenRenderer(element, { onSelect: object => { selected = object.object_id; } });
  renderer.setCellGeometry(11, 13);
  renderer.render(projection());
  const [x, y] = worldToScreen([10, 5], [10, 5], renderer.measure());
  renderer._selectAt({ clientX: x * 11 + 1, clientY: y * 13 + 1 });
  assert.equal(selected, 'plant:a');
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
  const renderer = new CanonicalGardenRenderer(element);
  const data = projection();
  renderer.render(data);
  for (let second = 1; second <= 600; second += 1) {
    const frame = renderer.render({ ...data, camera: [10 + second, 5] });
    assert.equal(frame.lines[Math.floor(frame.viewport[1] * 0.58)].includes('.'), true);
    assert.ok(frame.changedRows.length < frame.viewport[1]);
  }
});
