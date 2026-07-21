/** Read-only renderer for canonical Garden scene projections. */

import { glyphForProjection, organGlyph } from './garden-atlas.mjs';
import { projectSkyPoints, resolveBrowserSky } from './garden-sky.mjs';
import { compareCodePoints } from './garden-world.mjs';

const DEPTH = Object.freeze({ stars: 0.02, distant: 0.20, far: 0.55, world: 1, foreground: 1.15 });

function clamp(value, low, high) { return Math.max(low, Math.min(high, value)); }
function roundHalfAway(value) {
  return Math.sign(value) * Math.floor(Math.abs(value) + 0.5);
}

export function worldToScreen(point, camera, viewport, depth = DEPTH.world) {
  return [
    Math.floor(viewport[0] / 2) + roundHalfAway((point[0] - camera[0]) * depth),
    Math.floor(viewport[1] / 2) + roundHalfAway((point[1] - camera[1]) * depth),
  ];
}

export function screenToWorld(point, camera, viewport, depth = DEPTH.world) {
  if (depth === 0) throw new Error('fixed layers cannot be hit-tested');
  return [
    camera[0] + roundHalfAway((point[0] - Math.floor(viewport[0] / 2)) / depth),
    camera[1] + roundHalfAway((point[1] - Math.floor(viewport[1] / 2)) / depth),
  ];
}

export function connectedMasks(objects) {
  const result = new Map();
  for (const object of objects) {
    if (object.kind !== 'fixture') continue;
    const state = object.semantic_state ?? {};
    if (!Object.hasOwn(state, 'connected_group')) {
      throw new Error(`fixture ${object.object_id} lacks a projection-owned connected group`);
    }
    const group = state.connected_group;
    const mask = object.semantic_state?.connected_mask;
    if (!Number.isInteger(mask) || mask < 0 || mask > 15) {
      throw new Error(`fixture ${object.object_id} lacks a projection-owned connected mask`);
    }
    const renderCells = object.semantic_state?.render_cells;
    if (!Array.isArray(renderCells) || renderCells.some(cell =>
      !Number.isInteger(cell?.connected_mask) || cell.connected_mask < 0 ||
      cell.connected_mask > 15)) {
      throw new Error(`fixture ${object.object_id} lacks projection-owned connected cells`);
    }
    if (group === null) {
      if (mask !== 0) throw new Error(`fixture ${object.object_id} has a mask without a connected group`);
      continue;
    }
    if (typeof group !== 'string' || group.length === 0) {
      throw new Error(`fixture ${object.object_id} has an invalid connected group`);
    }
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

  setCellGeometry(width, height) {
    if (Number.isFinite(width) && width > 0) this.cellWidth = width;
    if (Number.isFinite(height) && height > 0) this.cellHeight = height;
    return [this.cellWidth, this.cellHeight];
  }

  refreshCellGeometry() {
    if (!globalThis.document?.createElement || !this.element?.appendChild ||
      typeof globalThis.getComputedStyle !== 'function') return [this.cellWidth, this.cellHeight];
    const probe = document.createElement('span');
    if (!probe.style || typeof probe.getBoundingClientRect !== 'function') return [this.cellWidth, this.cellHeight];
    probe.textContent = '0000000000';
    probe.style.cssText = 'position:absolute;visibility:hidden;white-space:pre;font:inherit;line-height:inherit;padding:0;margin:0;border:0;';
    this.element.appendChild(probe);
    const rect = probe.getBoundingClientRect();
    const style = getComputedStyle(this.element);
    const lineHeight = Number.parseFloat(style.lineHeight);
    probe.remove();
    return this.setCellGeometry(rect.width / 10, Number.isFinite(lineHeight) ? lineHeight : rect.height);
  }

  measure() {
    this.refreshCellGeometry();
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
      const depth = Number(object.depth ?? 100) / 100;
      const [x, y] = worldToScreen(object.position, projection.camera, viewport, depth);
      const visibleOrgans = object.kind === 'plant' && Array.isArray(object.semantic_state?.visible_organs)
        ? object.semantic_state.visible_organs : [];
      let symbols = visibleOrgans.length ? visibleOrgans.map(organ => ({
        dx: Number(organ.offset?.[0] ?? 0), dy: -Number(organ.offset?.[1] ?? 0),
        glyph: organGlyph(organ.kind, organ.glyph_family),
      })) : [{ dx: 0, dy: 0, glyph: glyphForProjection(object, { connectedMask: masks.get(object.object_id) ?? null }) }];
      if (object.kind === 'fixture' && Array.isArray(object.semantic_state?.render_cells)) {
        symbols = object.semantic_state.render_cells.map(cell => ({
          dx: Number(cell.dx ?? 0), dy: Number(cell.dy ?? 0),
          glyph: glyphForProjection(object, {
            connectedMask: object.semantic_state?.connected_group &&
              object.semantic_state?.presentation_state !== 'open'
              ? Number(cell.connected_mask ?? 0) : null,
          }),
        }));
      }
      for (const symbol of symbols) {
        const sx = x + symbol.dx, sy = y + symbol.dy;
        if (sx < 0 || sx >= viewport[0] || sy < 0 || sy >= viewport[1]) continue;
        let glyph = symbol.glyph;
        if (object.semantic_state?.choreography_locked) glyph = glyph.toUpperCase();
        cells[sy][sx] = glyph;
      }
    }
    const sceneLabel = [projection.scene?.weather, projection.scene?.palette,
      projection.scene?.story_time, projection.scene?.ambience].filter(Boolean).join(' · ');
    if (sceneLabel) {
      [...sceneLabel].slice(0, viewport[0]).forEach((glyph, index) => { cells[0][index] = glyph; });
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
    const absence = (projection.scene?.absence_summary ?? []).slice(0, 3);
    const missed = (projection.scene?.missed_event_summaries ?? []).slice(0, 3);
    const memorial = projection.scene?.memorial?.active
      ? ` Memorial lasting; ${(projection.scene.memorial.examined_gifts ?? []).length} gifts remembered.` : '';
    const inventory = projection.scene?.inventory ?? [];
    const descriptions = projection.objects.slice(0, 24).map(object =>
      object.semantic_state?.semantic_description ??
      `${object.semantic_name} at ${object.position[0]},${object.position[1]}.`).join(' ');
    this.element.setAttribute('aria-label', `${sky.label}. ${sceneLabel || 'calm natural scene'}. ${projection.objects.length} Garden objects. Inventory: ${inventory.join(', ') || 'empty'}.${absence.length ? ` Welcome back: ${absence.join(' ')}` : ''}${missed.length ? ` While you were away: ${missed.join(' ')}` : ''}${memorial} ${descriptions}`);
    this.lastFrame = { viewport, lines, changedRows, sky, motionPaused: projection.motion_paused || this.prefersReducedMotion };
    return this.lastFrame;
  }

  clear() {
    this.projection = null;
    this.lastFrame = null;
    this.rows = [];
    this.element.replaceChildren();
    this.element.setAttribute('aria-label', 'Generic Garden preview.');
  }

  _selectAt(event) {
    if (!this.projection || !this.onSelect) return;
    const rect = this.element.getBoundingClientRect();
    const [cellWidth, cellHeight] = this.refreshCellGeometry();
    const screen = [Math.floor((event.clientX - rect.left) / cellWidth), Math.floor((event.clientY - rect.top) / cellHeight)];
    const candidates = this.projection.objects.filter(object => {
      const depth = Number(object.depth ?? 100) / 100;
      const [wx, wy] = screenToWorld(screen, this.projection.camera, this.measure(), depth);
      const box = object.hotspot;
      return wx >= box.x && wx < box.x + box.width && wy >= box.y && wy < box.y + box.height;
    }).sort((left, right) => right.depth - left.depth || compareCodePoints(left.object_id, right.object_id));
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
  start(runtime = null, options = {}) {
    if (runtime?.startLive) runtime.startLive({ ...options, prefersReducedMotion: this.prefersReducedMotion,
      onProjection: projection => this.render(projection) });
  }
  stop(runtime = null) { if (runtime?.stopLive) runtime.stopLive(); }
  setSeed() {}
  setPostComplete() {}
  setAnimalData() {}
  triggerAnimalFeedReaction() {}
  spawnAmbientBirdBurst() {}
  animalDebugState() { return 'canonical'; }
}
