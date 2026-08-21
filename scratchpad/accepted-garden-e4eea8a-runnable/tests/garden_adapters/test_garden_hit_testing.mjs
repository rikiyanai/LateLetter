/**
 * Behavioural tests for pixel-space canonical hit testing.
 *
 * WHAT CHANGED, AND WHY IT NEEDED ITS OWN TESTS
 * ---------------------------------------------
 * Selection used to work in cell space: the pointer's pixel position was
 * divided by a fixed cell width, floored to a cell index, and tested against
 * hotspot rectangles measured in cells. The accessible 44px minimum target was
 * converted the same way, via `Math.ceil(44 / cellWidth)`.
 *
 * Both steps lost information. Flooring to a cell discards where inside the
 * cell the pointer actually was, which is precisely the sub-cell precision that
 * proportional presentation exists to provide. And rounding 44px up to a whole
 * number of cells over-expanded every target -- at an 8px cell it produced six
 * cells, or 48px -- while making an accessibility guarantee depend on the font.
 *
 * Selection now happens in pixels against the same canonical hotspots. Two
 * consequences are worth pinning down, because neither is visible in the
 * existing suite: expansion must never take a click from an object the player
 * genuinely touched, and the 44px floor must be exactly 44px.
 *
 * WHAT IS DELIBERATELY UNCHANGED
 * ------------------------------
 * Hit identity still comes from the projection's hotspots. This is a change of
 * units, not of authority. The tests below therefore assert on canonical object
 * ids, never on what was painted.
 */

import assert from 'node:assert/strict';
import test from 'node:test';
import { readFileSync } from 'node:fs';

import { CanonicalGardenRenderer } from '../../web/garden-renderer.mjs';
// Imported so provenance can be asserted, not just matching numbers: see the
// single-owner test at the end of this file.
import { createGeometry } from '../../web/garden-geometry.mjs';

// Reopened step 1 (2026-08-04 architecture review): the renderer refuses to
// construct without the accepted-paint manifest. Hit testing asserts on
// canonical ids, never painted cells, so the committed product manifest is
// simply the truthful constructor input here.
const COMMITTED_PAINT_AUTHORITY = JSON.parse(readFileSync(
  new URL('../../web/garden-accepted-paint.v1.json', import.meta.url), 'utf8'));

// Constructs a renderer under the committed authority.
function rendererUnderAuthority(element, options = {}) {
  return new CanonicalGardenRenderer(element,
    { paintAuthority: COMMITTED_PAINT_AUTHORITY, ...options });
}


/**
 * DOM stand-ins exposing only what the renderer touches.
 *
 * These mirror the shapes used by the existing renderer suite rather than
 * inventing new ones, so that a change to the renderer's DOM expectations
 * breaks both files together instead of leaving this one quietly stale.
 *
 * `getBoundingClientRect` returns the origin, so a test's `clientX`/`clientY`
 * are canvas-relative pixels directly and the arithmetic stays readable.
 */
class FakeRow {
  constructor() { this.textContent = ''; this.innerHTML = ''; this.attributes = {}; }
  setAttribute(key, value) { this.attributes[key] = value; }
  remove() {}
}

class FakeElement {
  constructor() {
    this.clientWidth = 320; this.clientHeight = 150;
    this.children = []; this.attributes = {}; this.style = {};
  }
  setAttribute(key, value) { this.attributes[key] = value; }
  addEventListener(kind, callback) { this.listener = kind === 'click' ? callback : this.listener; }
  appendChild(child) { this.children.push(child); }
  replaceChildren() { this.children = []; }
  getBoundingClientRect() { return { left: 0, top: 0 }; }
}

globalThis.document = { createElement: () => new FakeRow() };

/** A minimal projection holding exactly the objects a test cares about. */
function projectionOf(objects) {
  return {
    world_id: 'hit-test',
    effective_time: 10,
    camera: [10, 5],
    motion_paused: false,
    scene: { sky_mode: 'storybook_fallback' },
    objects,
  };
}

/** One selectable object occupying a single world cell. */
function cellObject(objectId, x, y, depth = 100) {
  return {
    object_id: objectId,
    kind: 'fixture',
    semantic_name: objectId,
    position: [x, y],
    depth,
    hotspot: { x, y, width: 1, height: 1 },
    // Every fixture must carry a projection-owned connected group and mask;
    // the renderer throws without them. These objects belong to no connected
    // family, which is expressed as a null group rather than an absent one.
    semantic_state: {
      catalog_id: 'sundial', connected_group: null, connected_mask: 0,
      render_cells: [{ dx: 0, dy: 0, connected_mask: 0 }],
    },
  };
}

/**
 * Build a renderer with a known cell size and a rendered frame.
 *
 * @param {object[]} objects - Projection objects to place.
 * @param {number} cellWidth - Pixels per column.
 * @param {number} cellHeight - Pixels per row.
 * @returns {{renderer: object, frame: object, selected: () => string|null}}
 */
function scene(objects, cellWidth = 8, cellHeight = 15) {
  let selected = null;
  const renderer = rendererUnderAuthority(new FakeElement(), {
    onSelect: (object) => { selected = object.object_id; },
  });
  renderer.setCellGeometry(cellWidth, cellHeight);
  const frame = renderer.render(projectionOf(objects));
  return { renderer, frame, selected: () => selected };
}

/**
 * Build a renderer whose layout is supplied directly.
 *
 * Hit testing reads `lastFrame.layout`, so the layout is assigned rather than
 * produced by `render()`. That is deliberate: the packer relocates and clips
 * objects to fit the viewport, which is its job, but it means a rendered
 * `hitRect` is not the rectangle the test asked for. Supplying the layout keeps
 * each test about the thing it names -- which rectangle wins a pointer -- with
 * no dependence on packing decisions made elsewhere.
 *
 * @param {Array<{id: string, rect: object, depth?: number}>} entries
 * @param {number} cellWidth
 * @param {number} cellHeight
 */
function hitScene(entries, cellWidth = 8, cellHeight = 15) {
  let selected = null;
  const renderer = rendererUnderAuthority(new FakeElement(), {
    onSelect: (object) => { selected = object.object_id; },
  });
  renderer.setCellGeometry(cellWidth, cellHeight);
  // A projection must be present for selection to run at all; its contents are
  // irrelevant because the layout below is what hit testing consults.
  renderer.projection = projectionOf([]);
  renderer.lastFrame = {
    layout: entries.map(({ id, rect, depth = 100 }) => ({
      object: { object_id: id, kind: 'fixture', depth, semantic_state: {} },
      hitRect: rect,
    })),
  };
  return {
    renderer,
    selected: () => selected,
    /** The pixel rectangle the renderer derives for one entry, as edges. */
    pixels: (id) => edgesOf(renderer._hitRectPixels(
      renderer.lastFrame.layout.find((entry) => entry.object.object_id === id),
    )),
  };
}

/** An inclusive one-cell rectangle at a world position. */
function cellRect(x, y) {
  return { left: x, right: x, top: y, bottom: y };
}

/**
 * Restate a geometry rectangle as edges.
 *
 * `garden-geometry.mjs` speaks in origin-and-extent (`x, y, width, height`),
 * which is the right shape for an affine transform: the origin is what the
 * transform produces and the extent is what it scales. The assertions below
 * reason about BOUNDARIES -- "22px either side of the centre, and no further"
 * -- so they read far better in edges.
 *
 * Converting in one named place keeps the tests asserting on behaviour rather
 * than on a struct layout, so a future change of vocabulary in the geometry
 * module touches this function and nothing else. Right and bottom stay
 * EXCLUSIVE, matching the half-open containment rule they are compared against.
 *
 * @param {{x: number, y: number, width: number, height: number}} rect
 * @returns {{left: number, top: number, right: number, bottom: number}}
 */
function edgesOf(rect) {
  return {
    left: rect.x,
    top: rect.y,
    right: rect.x + rect.width,
    bottom: rect.y + rect.height,
  };
}

// ---------------------------------------------------------------------------
// Expansion must not steal a click
// ---------------------------------------------------------------------------

test('an exact hotspot hit outranks a nearer objects expanded target', () => {
  // The case that makes exact-first necessary is objects of DIFFERENT SIZES.
  // A wide object's centre can be far from a pointer that is nonetheless well
  // inside it, while a small neighbour's centre sits close by. Ranking on
  // distance alone would then hand the click to the neighbour -- even though
  // the player is physically touching the wide object.
  //
  // Here: a sixteen-cell pond spanning px 80..208 (centre 144), and a one-cell
  // sundial at px 208..216 (centre 212). The pointer at px 206 is inside the
  // pond, 62px from its centre but only 6px from the sundial's.
  const { renderer, selected, pixels } = hitScene([
    { id: 'fixture:pond', rect: { left: 10, right: 25, top: 8, bottom: 8 } },
    { id: 'fixture:sundial', rect: cellRect(26, 8) },
  ]);

  const pond = pixels('fixture:pond');
  const sundial = pixels('fixture:sundial');
  const pointX = 206;
  const pointY = (pond.top + pond.bottom) / 2;

  // Establish that this really is the adversarial arrangement, so the test
  // cannot quietly stop testing anything if the geometry changes.
  assert.ok(pointX >= pond.left && pointX < pond.right, 'pointer is inside the pond');
  assert.ok(pointX < sundial.left, 'pointer is outside the sundials own hotspot');
  const pondDistance = Math.abs(pointX - (pond.left + pond.right) / 2);
  const sundialDistance = Math.abs(pointX - (sundial.left + sundial.right) / 2);
  assert.ok(sundialDistance < pondDistance, 'the sundials centre is nearer');
  assert.ok(
    pointX >= sundial.left - 22,
    'the sundials 44px expanded target reaches the pointer',
  );

  renderer._selectAt({ clientX: pointX, clientY: pointY });
  assert.equal(
    selected(), 'fixture:pond',
    'accessibility expansion must not take a click from an object actually touched',
  );
});

test('selection is identical whichever order the layout lists objects', () => {
  // Determinism matters more than which object wins: the same tap on the same
  // scene has to do the same thing on every machine.
  const entries = [
    { id: 'fixture:aaa', rect: cellRect(30, 6) },
    { id: 'fixture:bbb', rect: cellRect(31, 6) },
  ];
  // Equidistant from both centres, so the tie-break decides and nothing else.
  const point = { clientX: 31 * 8, clientY: 6 * 15 + 7 };

  const forward = hitScene(entries);
  forward.renderer._selectAt(point);

  const reversed = hitScene([...entries].reverse());
  reversed.renderer._selectAt(point);

  assert.equal(forward.selected(), reversed.selected());
  assert.ok(forward.selected(), 'the tap must select something');
});

// ---------------------------------------------------------------------------
// The 44px floor is 44px
// ---------------------------------------------------------------------------

test('the accessible minimum target is exactly 44px, not a rounded cell count', () => {
  // At an 8px cell the old code computed ceil(44/8) = 6 cells = 48px, so a tap
  // 23px from the centre still landed. In pixels the target is 44px wide: it
  // reaches 22px either side of a one-cell object's centre and no further.
  const near = hitScene([{ id: 'fixture:only', rect: cellRect(25, 9) }]);
  const rect = near.pixels('fixture:only');
  const centreX = (rect.left + rect.right) / 2;
  const centreY = (rect.top + rect.bottom) / 2;

  near.renderer._selectAt({ clientX: centreX - 21, clientY: centreY });
  assert.equal(near.selected(), 'fixture:only', '21px out is inside the 44px target');

  const beyond = hitScene([{ id: 'fixture:only', rect: cellRect(25, 9) }]);
  beyond.renderer._selectAt({ clientX: centreX - 23, clientY: centreY });
  assert.equal(beyond.selected(), null, '23px out is beyond 44px, and beyond the old 48px');
});

test('a target already larger than the minimum is not expanded at all', () => {
  // An eight-cell object is 64px across; expanding it would only blur its edges
  // into a neighbour's territory.
  const wide = { id: 'fixture:wide', rect: { left: 10, right: 17, top: 4, bottom: 4 } };

  const outside = hitScene([wide]);
  const rect = outside.pixels('fixture:wide');
  assert.equal(rect.right - rect.left, 64);
  outside.renderer._selectAt({ clientX: rect.left - 1, clientY: (rect.top + rect.bottom) / 2 });
  assert.equal(outside.selected(), null, 'nothing to expand, so just outside must miss');

  const inside = hitScene([wide]);
  inside.renderer._selectAt({ clientX: rect.left + 1, clientY: (rect.top + rect.bottom) / 2 });
  assert.equal(inside.selected(), 'fixture:wide');
});

test('a tall target is measured against the same 44px floor vertically', () => {
  // Rows are 15px, so a one-row object is well under the floor on the vertical
  // axis too -- the guarantee is about fingertips, not about line height.
  const one = hitScene([{ id: 'fixture:only', rect: cellRect(12, 3) }]);
  const rect = one.pixels('fixture:only');
  const centreX = (rect.left + rect.right) / 2;
  const centreY = (rect.top + rect.bottom) / 2;

  one.renderer._selectAt({ clientX: centreX, clientY: centreY - 21 });
  assert.equal(one.selected(), 'fixture:only');

  const beyond = hitScene([{ id: 'fixture:only', rect: cellRect(12, 3) }]);
  beyond.renderer._selectAt({ clientX: centreX, clientY: centreY - 23 });
  assert.equal(beyond.selected(), null);
});

// ---------------------------------------------------------------------------
// Sub-cell precision, which cell-flooring could not express
// ---------------------------------------------------------------------------

test('hit testing distinguishes positions inside a single cell', () => {
  // Under the old code both points floored to the same cell index and were
  // indistinguishable. In pixel space they are different points, and the 44px
  // target boundary can fall between them.
  const probe = hitScene([{ id: 'fixture:only', rect: cellRect(25, 9) }]);
  const rect = probe.pixels('fixture:only');
  const centreY = (rect.top + rect.bottom) / 2;
  const boundary = (rect.left + rect.right) / 2 - 22;

  const inside = hitScene([{ id: 'fixture:only', rect: cellRect(25, 9) }]);
  inside.renderer._selectAt({ clientX: boundary + 0.25, clientY: centreY });
  assert.equal(inside.selected(), 'fixture:only');

  const outside = hitScene([{ id: 'fixture:only', rect: cellRect(25, 9) }]);
  outside.renderer._selectAt({ clientX: boundary - 0.25, clientY: centreY });
  assert.equal(outside.selected(), null);
});

// ---------------------------------------------------------------------------
// Authority: hotspots decide, artwork does not
// ---------------------------------------------------------------------------

test('overhanging art never widens what a click can reach', () => {
  // The bench draws eighteen columns of picture from a one-cell hotspot. If ink
  // decided hit identity, a click far to the side of its cell would select it.
  // Only the hotspot -- expanded to the accessible minimum -- may.
  const { renderer, selected, pixels } = hitScene([
    { id: 'fixture:bench', rect: cellRect(30, 10) },
  ]);
  const rect = pixels('fixture:bench');
  const centreX = (rect.left + rect.right) / 2;

  // The drawing spans roughly 144px, so 60px from centre is under the picture
  // but well outside the hotspot's 44px target.
  renderer._selectAt({ clientX: centreX + 60, clientY: (rect.top + rect.bottom) / 2 });
  assert.equal(selected(), null, 'overhanging art must not become an action target');
});

test('hit identity comes from the hotspot rectangle, not the object position', () => {
  // A bird in flight is painted away from the cell it belongs to. Its hotspot
  // is what the projection says it is, and that is what a pointer must find.
  const displaced = { id: 'animal:bird', rect: cellRect(40, 2) };
  const { renderer, selected, pixels } = hitScene([displaced]);
  const rect = pixels('animal:bird');

  renderer._selectAt({
    clientX: (rect.left + rect.right) / 2,
    clientY: (rect.top + rect.bottom) / 2,
  });
  assert.equal(selected(), 'animal:bird');
});

// ---------------------------------------------------------------------------
// One owner for the pixel rules
// ---------------------------------------------------------------------------

test('the renderer derives hit rectangles from garden-geometry, not its own copy', () => {
  // The tests above pin BEHAVIOUR, which a second private implementation could
  // satisfy just as well -- and did, until this module started importing the
  // geometry. That is the failure worth guarding: two copies of the 44px floor
  // and the half-open containment rule that agree today and quietly diverge
  // later, showing up only as an occasional object that will not select.
  //
  // So this asserts PROVENANCE. An independently constructed geometry, built
  // from the same lattice constants and nothing else, must produce exactly the
  // rectangles the renderer produces -- for the origin, the extent, and the
  // expansion. A renderer that reintroduced its own arithmetic would have to
  // reproduce all of it bit for bit to keep passing.
  const cellWidth = 8;
  const cellHeight = 15;
  const rect = { left: 10, right: 25, top: 8, bottom: 8 };
  const { renderer } = hitScene([{ id: 'fixture:pond', rect }], cellWidth, cellHeight);

  const geometry = createGeometry({ cellAdvance: cellWidth, lineHeight: cellHeight });
  const expected = geometry.hotspotToRect({
    x: rect.left,
    y: rect.top,
    // Inclusive cell edges, so the extent is one more than the difference: a
    // span from column 10 to column 25 covers sixteen columns, not fifteen.
    width: rect.right - rect.left + 1,
    height: rect.bottom - rect.top + 1,
  });

  const actual = renderer._hitRectPixels(renderer.lastFrame.layout[0]);
  assert.deepEqual(actual, expected);
  assert.deepEqual(geometry.expandTarget(actual), geometry.expandTarget(expected));

  // And the inclusive-to-extent conversion is load-bearing: sixteen columns at
  // 8px is 128px. An off-by-one here would make every object one cell smaller
  // than it looks, silently.
  assert.equal(actual.width, 128);
  assert.equal(actual.height, 15);
});

test('a pointer event before any layout is measured still resolves', () => {
  // A click can arrive during the first frame, before `refreshCellGeometry` has
  // run. The transform must already exist at that moment -- an absent one would
  // throw rather than simply resolving against the default cell size.
  let selected = null;
  const renderer = rendererUnderAuthority(new FakeElement(), {
    onSelect: (object) => { selected = object.object_id; },
  });
  assert.ok(renderer.geometry, 'a geometry exists from construction');
  assert.equal(renderer.cellGeometryMeasured, false, 'and it is still unmeasured');

  renderer.projection = projectionOf([]);
  renderer.lastFrame = {
    layout: [{
      object: { object_id: 'fixture:only', kind: 'fixture', depth: 100, semantic_state: {} },
      hitRect: cellRect(2, 2),
    }],
  };
  renderer._selectAt({ clientX: 2 * 8 + 4, clientY: 2 * 15 + 7 });
  assert.equal(selected, 'fixture:only');
});
