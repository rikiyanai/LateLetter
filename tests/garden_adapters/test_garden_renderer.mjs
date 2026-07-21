import assert from 'node:assert/strict';
import test from 'node:test';
import { readFileSync } from 'node:fs';

import {
  CanonicalGardenRenderer, connectedMasks, screenToWorld, worldToScreen,
} from '../../web/garden-renderer.mjs';
import { connectedGlyph } from '../../web/garden-atlas.mjs';
import {
  altAz, greenwichApparentSiderealTime, quantizeRoughLocation,
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
        depth: 100, hotspot: { x: 11, y: 5, width: 1, height: 1 }, semantic_state: { catalog_id: 'fence' } },
      { object_id: 'fence:b', kind: 'fixture', semantic_name: 'fence', position: [12, 5],
        depth: 100, hotspot: { x: 12, y: 5, width: 1, height: 1 }, semantic_state: { catalog_id: 'fence' } },
    ],
  };
}

test('camera transform and inverse share the same canonical coordinates', () => {
  const viewport = [40, 10], camera = [10, 5], world = [13, 7];
  assert.deepEqual(screenToWorld(worldToScreen(world, camera, viewport), camera, viewport), world);
});

test('connected masks are derived only from canonical fixture positions', () => {
  const masks = connectedMasks(projection().objects);
  assert.equal(masks.get('fence:a'), 2);
  assert.equal(masks.get('fence:b'), 8);
  assert.equal(new Set(Array.from({ length: 16 }, (_, mask) => connectedGlyph(mask))).has(undefined), false);
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

test('raster hit testing inverts the same camera and selects canonical object', () => {
  let selected = null;
  const element = new FakeElement();
  const renderer = new CanonicalGardenRenderer(element, { onSelect: object => { selected = object.object_id; } });
  renderer.render(projection());
  const [x, y] = worldToScreen([10, 5], [10, 5], renderer.measure());
  renderer._selectAt({ clientX: x * renderer.cellWidth + 1, clientY: y * renderer.cellHeight + 1 });
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
