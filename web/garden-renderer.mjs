/** Read-only renderer for canonical Garden scene projections. */

import { fixtureConnectedGroup, glyphForProjection } from './garden-atlas.mjs';
import { projectSkyPoints, resolveBrowserSky } from './garden-sky.mjs';

const DEPTH = Object.freeze({ stars: 0.02, distant: 0.20, far: 0.55, world: 1, foreground: 1.15 });

function clamp(value, low, high) { return Math.max(low, Math.min(high, value)); }

export function worldToScreen(point, camera, viewport, depth = DEPTH.world) {
  return [
    Math.round(viewport[0] / 2 + (point[0] - camera[0]) * depth),
    Math.round(viewport[1] / 2 + (point[1] - camera[1]) * depth),
  ];
}

export function screenToWorld(point, camera, viewport, depth = DEPTH.world) {
  if (depth === 0) throw new Error('fixed layers cannot be hit-tested');
  return [
    Math.round(camera[0] + (point[0] - viewport[0] / 2) / depth),
    Math.round(camera[1] + (point[1] - viewport[1] / 2) / depth),
  ];
}

export function connectedMasks(objects) {
  const groups = new Map();
  for (const object of objects) {
    if (object.kind !== 'fixture') continue;
    const group = fixtureConnectedGroup(object.semantic_state?.catalog_id);
    if (!group) continue;
    if (!groups.has(group)) groups.set(group, new Set());
    groups.get(group).add(`${object.position[0]},${object.position[1]}`);
  }
  const result = new Map();
  for (const object of objects) {
    if (object.kind === 'fixture' && Number.isInteger(object.semantic_state?.connected_mask)) {
      result.set(object.object_id, object.semantic_state.connected_mask & 15);
      continue;
    }
    const group = object.kind === 'fixture' ? fixtureConnectedGroup(object.semantic_state?.catalog_id) : null;
    if (!group) continue;
    const [x, y] = object.position, cells = groups.get(group);
    const mask = (cells.has(`${x},${y - 1}`) ? 1 : 0) |
      (cells.has(`${x + 1},${y}`) ? 2 : 0) |
      (cells.has(`${x},${y + 1}`) ? 4 : 0) |
      (cells.has(`${x - 1},${y}`) ? 8 : 0);
    result.set(object.object_id, mask);
  }
  return result;
}

export class CanonicalGardenRenderer {
  constructor(element, { onSelect = null, prefersReducedMotion = false, readerRegion = null } = {}) {
    this.element = element;
    this.onSelect = onSelect;
    this.prefersReducedMotion = Boolean(prefersReducedMotion);
    this.readerRegion = readerRegion;
    this.projection = null;
    this.rows = [];
    this.cellWidth = 8;
    this.cellHeight = 15;
    this.lastFrame = null;
    this.element.setAttribute('role', 'img');
    this.element.addEventListener('click', event => this._selectAt(event));
  }

  measure() {
    const width = Math.max(20, Math.floor(this.element.clientWidth / this.cellWidth));
    const height = Math.max(10, Math.floor(this.element.clientHeight / this.cellHeight));
    return [width, height];
  }

  render(projection) {
    if (!projection) return null;
    this.projection = projection;
    const viewport = this.measure();
    const cells = Array.from({ length: viewport[1] }, () => Array(viewport[0]).fill(' '));
    const masks = connectedMasks(projection.objects);
    const sky = resolveBrowserSky({ scene: projection.scene, readerRegion: this.readerRegion });
    for (const [x, y, glyph] of projectSkyPoints(sky, projection.effective_time, viewport)) {
      if (x >= 0 && x < viewport[0] && y >= 0 && y < viewport[1]) cells[y][x] = glyph;
    }
    const horizon = clamp(Math.floor(viewport[1] * 0.58), 1, viewport[1] - 2);
    for (let x = 0; x < viewport[0]; x += 1) cells[horizon][x] = '.';
    for (const object of projection.objects) {
      const [x, y] = worldToScreen(object.position, projection.camera, viewport);
      const visibleOrgans = object.kind === 'plant' && Array.isArray(object.semantic_state?.visible_organs)
        ? object.semantic_state.visible_organs : [];
      const symbols = visibleOrgans.length ? visibleOrgans.map(organ => ({
        dx: Number(organ.offset?.[0] ?? 0), dy: -Number(organ.offset?.[1] ?? 0),
        glyph: ({ root: '+', stem: '|', branch: '/', vine: '\\', leaf: '*', bloom: '@', fruit: 'o' })[organ.kind] ?? '*',
      })) : [{ dx: 0, dy: 0, glyph: glyphForProjection(object, { connectedMask: masks.get(object.object_id) ?? null }) }];
      for (const symbol of symbols) {
        const sx = x + symbol.dx, sy = y + symbol.dy;
        if (sx < 0 || sx >= viewport[0] || sy < 0 || sy >= viewport[1]) continue;
        let glyph = symbol.glyph;
        if (object.semantic_state?.choreography_locked) glyph = glyph.toUpperCase();
        cells[sy][sx] = glyph;
      }
    }
    const lines = cells.map(row => row.join(''));
    while (this.rows.length < lines.length) {
      const row = document.createElement('div');
      row.setAttribute('aria-hidden', 'true');
      this.element.appendChild(row); this.rows.push(row);
    }
    while (this.rows.length > lines.length) this.rows.pop().remove();
    const changedRows = [];
    lines.forEach((line, index) => {
      if (this.rows[index].textContent !== line) {
        this.rows[index].textContent = line; changedRows.push(index);
      }
    });
    this.element.setAttribute('aria-label', `${sky.label}. ${projection.objects.length} Garden objects.`);
    this.lastFrame = { viewport, lines, changedRows, sky, motionPaused: projection.motion_paused || this.prefersReducedMotion };
    return this.lastFrame;
  }

  _selectAt(event) {
    if (!this.projection || !this.onSelect) return;
    const rect = this.element.getBoundingClientRect();
    const screen = [Math.floor((event.clientX - rect.left) / this.cellWidth), Math.floor((event.clientY - rect.top) / this.cellHeight)];
    const [wx, wy] = screenToWorld(screen, this.projection.camera, this.measure());
    const candidates = this.projection.objects.filter(object => {
      const box = object.hotspot;
      return wx >= box.x && wx < box.x + box.width && wy >= box.y && wy < box.y + box.height;
    }).sort((left, right) => right.depth - left.depth || left.object_id.localeCompare(right.object_id));
    if (candidates[0]) this.onSelect(candidates[0], event);
  }

  onResize() { if (this.projection) this.render(this.projection); }
  setReaderRegion(region) { this.readerRegion = region; if (this.projection) this.render(this.projection); }
  setReducedMotion(value) {
    const next = Boolean(value);
    if (next === this.prefersReducedMotion) return;
    this.prefersReducedMotion = next;
    if (this.projection) this.render(this.projection);
  }
  start() { /* Canonical state changes, not presentation ticks, trigger render. */ }
  stop() {}
  setSeed() {}
  setPostComplete() {}
  setAnimalData() {}
  triggerAnimalFeedReaction() {}
  spawnAmbientBirdBurst() {}
  animalDebugState() { return 'canonical'; }
}
