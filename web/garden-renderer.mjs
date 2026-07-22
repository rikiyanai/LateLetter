/**
 * Rich, read-only presentation for canonical Garden scene projections.
 *
 * World state, topology, positions, hit targets, actions, animal intent, and
 * time remain owned by garden-world.mjs/GardenRuntime.  This module owns only
 * disposable pixels: palette, multi-cell silhouettes, wind frames, particles,
 * and hover/click feedback.  Nothing here is persisted or fed back to gameplay.
 */

import { glyphForProjection, organGlyph } from './garden-atlas.mjs';
import { projectSkyPoints, resolveBrowserSky } from './garden-sky.mjs';
import { compareCodePoints } from './garden-world.mjs';

const DEPTH = Object.freeze({ stars: 0.02, distant: 0.20, far: 0.55, world: 1, foreground: 1.15 });
const DAY = Object.freeze({
  sky: '#f9f8f5', ground: '#ddd8ce', soil: '#c8c2b6', dim: '#aaa397',
  green: '#4a7030', brightGreen: '#62923e', deepGreen: '#33511e', brown: '#7a5830',
  flower: '#a03888', flower2: '#b85038', gold: '#c09428', water: '#4a6888',
  creature: '#6e5135', stone: '#777770', star: '#8a8878', moon: '#b1aa91', text: '#55514b',
});
const NIGHT = Object.freeze({
  sky: '#0b0e16', ground: '#13181e', soil: '#28302a', dim: '#606058',
  green: '#5a9858', brightGreen: '#78b870', deepGreen: '#41703e', brown: '#a08868',
  flower: '#d068b8', flower2: '#e87868', gold: '#e0b848', water: '#7898b8',
  creature: '#c0a078', stone: '#a0a098', star: '#b8b8a8', moon: '#e8e4d0', text: '#d0ccc0',
});
const EVENING = Object.freeze({ ...DAY, sky: '#ecd6b6', ground: '#d8bea2', star: '#766979' });
const MOON_ART = Object.freeze([
  [], ['  _', ' ) ', ' ‾ '], [' _ ', '|) ', ' ‾ '], [' __ ', '(O) ', ' ‾‾ '],
  [' __ ', '(  )', ' ‾‾ '], [' __ ', ' (O)', ' ‾‾ '], [' _ ', ' (|', ' ‾ '], [' _ ', ' ( ', ' ‾ '],
]);
const ANIMAL_ART = Object.freeze({
  cat: [
    ['/\\_ ', 'o.  '], ['/\\_/\\', '(o.o)', ' >^< '],
    ['/\\_/\\', '(-.-)', ' ~~^ '], ['/\\_/\\', '(zzz)', ' ~_~ '],
  ],
  bird: [['>-'], ['>o<', ' | '], ['\\o/', ' | '], ['(o)', '/|\\']],
  rabbit: [['(\\ '], ['(\\ /)', '.    '], ['(\\ /)', ' . . '], ['(\\./)', '  z  ']],
  turtle: [[' (~) '], [' (~)_', '{__} '], ['(~o~)', '{__}'], ['(~-~)', '{__}']],
});
const FIXTURE_DECOR = Object.freeze({
  bench: [' __|__ ', '|_____|'], arbor: [' /^^\\ ', '/|  |\\'], sundial: [' \\|/ ', '--o--'],
  trellis: ['#\\/#', '#/\\#'], birdbath: [' \\_/', '  | '], lantern: [' .-.', '(*)', ' | '],
  pond: [' ~~~ ', '~~~~~'], mailbox: [' __', '[__]', ' | '], memory_shrine: [' .*. ', '[___]'],
  bridge: ['_/===\\_'], fence: ['-|-'], gate: ['-| |-'], fence_gate: ['-| |-'],
  stepping_stone: ['(·)'], stepping_stones: ['(·) (·)'],
  planter: ['\\___/', ' \\_/ '], table: ['o=T=o', '  |  '], chair: [' _ ', '|_|'],
  table_chairs: ['o=T=o', '  |  '], well: [' /\\ ', '(==)', ' || '],
  wind_chime: [' \\|/', '  * ', ' /|\\'], shed_edge: [' /\\ ', '/__\\', '|[]|'],
  tool_rack: ['|-Y-'], watering_can: [' __o', '(__)'], compost: ['{%%%}'], basket: ['\\___/'],
  sign: ['[ garden ]', '    |    '], memorial_stone: [' .-.', '(   )'],
});

function clamp(value, low, high) { return Math.max(low, Math.min(high, value)); }
function roundHalfAway(value) { return Math.sign(value) * Math.floor(Math.abs(value) + 0.5); }
function escapeHtml(value) {
  return value.replaceAll('&', '&amp;').replaceAll('<', '&lt;').replaceAll('>', '&gt;');
}
function stringHash(value) {
  let hash = 2166136261;
  for (const glyph of String(value)) { hash ^= glyph.codePointAt(0); hash = Math.imul(hash, 16777619); }
  return hash >>> 0;
}
function noise(seed) {
  let value = seed >>> 0;
  value ^= value >>> 16; value = Math.imul(value, 0x7feb352d);
  value ^= value >>> 15; value = Math.imul(value, 0x846ca68b); value ^= value >>> 16;
  return (value >>> 0) / 4294967296;
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
    const mask = state.connected_mask;
    if (!Number.isInteger(mask) || mask < 0 || mask > 15) {
      throw new Error(`fixture ${object.object_id} lacks a projection-owned connected mask`);
    }
    const renderCells = state.render_cells;
    if (!Array.isArray(renderCells) || renderCells.some(cell =>
      !Number.isInteger(cell?.connected_mask) || cell.connected_mask < 0 || cell.connected_mask > 15)) {
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

class Raster {
  constructor(width, height) {
    this.width = width; this.height = height;
    this.glyphs = Array.from({ length: height }, () => Array(width).fill(' '));
    this.colors = Array.from({ length: height }, () => Array(width).fill(null));
    this.animated = Array.from({ length: height }, () => Array(width).fill(false));
  }
  put(x, y, glyph, color = null, animated = false) {
    if (x < 0 || x >= this.width || y < 0 || y >= this.height || !glyph) return;
    this.glyphs[y][x] = [...String(glyph)][0]; this.colors[y][x] = color; this.animated[y][x] = animated;
  }
  text(x, y, value, color = null, animated = false) {
    [...String(value)].forEach((glyph, index) => this.put(x + index, y, glyph, color, animated));
  }
  art(anchorX, anchorY, lines, color, { baseline = true, animated = false } = {}) {
    const width = Math.max(0, ...lines.map(line => [...line].length));
    const top = baseline ? anchorY - lines.length + 1 : anchorY;
    lines.forEach((line, row) => this.text(anchorX - Math.floor(width / 2), top + row, line, color, animated));
  }
  line(row) { return this.glyphs[row].join(''); }
  html(row) {
    let output = '', color = null, run = '';
    const flush = () => {
      if (!run) return;
      output += color ? `<span style="color:${color}">${escapeHtml(run)}</span>` : escapeHtml(run);
      run = '';
    };
    for (let column = 0; column < this.width; column += 1) {
      const next = this.colors[row][column];
      if (next !== color) { flush(); color = next; }
      run += this.glyphs[row][column];
    }
    flush(); return output;
  }
}

function timeOfDay(projection) {
  const authored = String(projection.scene?.story_time ?? projection.scene?.palette ?? '').toLowerCase();
  if (authored.includes('night')) return 'night';
  if (authored.includes('evening') || authored.includes('sunset') || authored.includes('dusk')) return 'evening';
  if (authored.includes('day') || authored.includes('morning')) return 'day';
  const hour = new Date(Math.max(0, Number(projection.effective_time) || 0) * 1000).getUTCHours();
  return hour >= 21 || hour < 5 ? 'night' : hour >= 18 ? 'evening' : 'day';
}
function seasonOf(projection) {
  const authored = String(projection.scene?.season ?? projection.scene?.palette ?? '').toLowerCase();
  for (const season of ['spring', 'summer', 'autumn', 'winter']) if (authored.includes(season)) return season;
  const month = new Date(Math.max(0, Number(projection.effective_time) || 0) * 1000).getUTCMonth() + 1;
  return month >= 3 && month <= 5 ? 'spring' : month <= 8 ? 'summer' : month <= 11 ? 'autumn' : 'winter';
}
function lunarPhase(effectiveTime) {
  const days = ((Number(effectiveTime) * 1000 - Date.UTC(2000, 0, 6, 18, 14)) / 86400000);
  return Math.floor((((days % 29.53) + 29.53) % 29.53) / 29.53 * 8);
}

function plantArt(object, frame) {
  const state = object.semantic_state ?? {};
  const species = String(state.species_id ?? object.semantic_name ?? 'plant');
  const visible = Math.max(1, Number(state.visible_organ_count ?? state.visible_organs?.length ?? 1));
  const stage = clamp(Math.floor(Math.log2(visible + 1)), 1, 4);
  const sway = frame % 24 < 12 ? '/' : '\\';
  if (['oak', 'maple', 'cherry', 'willow'].includes(species)) {
    const crown = species === 'willow' ? 'vVvYvVv' : species === 'cherry' ? '@o@Y@o@' : '*o*Y*o*';
    const lines = stage >= 3 ? [`  ${crown[3]}  `, ` ${crown.slice(1, 6)} `, crown, '  /|\\  ', '   |   '] : ['  *  ', ' *Y* ', '  |  '];
    return { lines, color: 'green' };
  }
  if (species === 'pine') {
    const lines = stage >= 3 ? ['   ^   ', '  /|\\  ', ' //|\\\\ ', '///|\\\\\\', '   |   '] : [' ^ ', '/|\\', ' | '];
    return { lines, color: 'deepGreen' };
  }
  if (['rose', 'daisy', 'tulip', 'sunflower', 'lavender', 'hydrangea', 'wisteria', 'lotus', 'water_lily'].includes(species)) {
    const bloom = species === 'sunflower' ? 'O' : species === 'tulip' ? 'u' : species === 'rose' ? '@' : '*';
    return { lines: stage >= 2 ? [` ${bloom} ${bloom} `, `${sway}| |${sway === '/' ? '\\' : '/'}`, ` |${bloom}| `, '  |  '] : [bloom, '|'], color: 'flower' };
  }
  if (['grass', 'meadow_grass', 'reed'].includes(species)) {
    return { lines: [`${sway}|${sway === '/' ? '\\' : '/'}'`, '|||'], color: 'brightGreen' };
  }
  if (['fern', 'ivy'].includes(species)) return { lines: [' * * ', `${sway}| |${sway === '/' ? '\\' : '/'}`, '  |  '], color: 'green' };
  return { lines: [' ;;; ', '; | ;', '  |  '], color: 'green' };
}

function animalArt(object, frame) {
  const state = object.semantic_state ?? {};
  const species = String(state.species_id ?? 'bird');
  const tier = clamp(Number(state.bond_tier) || 0, 0, 3);
  const options = ANIMAL_ART[species] ?? ANIMAL_ART.bird;
  let lines = options[tier];
  const intent = String(state.intent ?? 'idle');
  if (intent === 'feed' && species === 'cat') lines = ['/\\_/\\', '(o.o)', ' [_] '];
  if (state.choreography_locked && frame % 12 < 6) lines = lines.map(line => line.replace('o', 'O'));
  return lines;
}

function paletteColor(palette, key, season) {
  if (season === 'autumn' && ['green', 'brightGreen'].includes(key)) return key === 'green' ? '#a66d25' : '#c18a2f';
  if (season === 'winter' && key === 'brightGreen') return palette.stone;
  return palette[key] ?? palette.text;
}

export class CanonicalGardenRenderer {
  constructor(element, { onSelect = null, prefersReducedMotion = false, readerRegion = null } = {}) {
    this.element = element; this.onSelect = onSelect;
    this.prefersReducedMotion = Boolean(prefersReducedMotion); this.readerRegion = readerRegion;
    this.projection = null; this.rows = []; this.cellWidth = 8; this.cellHeight = 15;
    this.lastFrame = null; this.visualFrame = 0; this.hoverCell = null; this.clickBursts = [];
    this.presentationTimer = null;
    this.element.setAttribute('role', 'img');
    this.element.addEventListener('click', event => { this._burstAt(event); this._selectAt(event); });
    this.element.addEventListener('mousemove', event => this._hoverAt(event));
    this.element.addEventListener('mouseleave', () => { this.hoverCell = null; });
  }

  setCellGeometry(width, height) {
    if (Number.isFinite(width) && width > 0) this.cellWidth = width;
    if (Number.isFinite(height) && height > 0) this.cellHeight = height;
    return [this.cellWidth, this.cellHeight];
  }
  refreshCellGeometry() {
    if (!globalThis.document?.createElement || !this.element?.appendChild || typeof globalThis.getComputedStyle !== 'function') return [this.cellWidth, this.cellHeight];
    const probe = document.createElement('span');
    if (!probe.style || typeof probe.getBoundingClientRect !== 'function') return [this.cellWidth, this.cellHeight];
    probe.textContent = '0000000000';
    probe.style.cssText = 'position:absolute;visibility:hidden;white-space:pre;font:inherit;line-height:inherit;padding:0;margin:0;border:0;';
    this.element.appendChild(probe);
    const rect = probe.getBoundingClientRect(), style = getComputedStyle(this.element);
    const lineHeight = Number.parseFloat(style.lineHeight); probe.remove();
    return this.setCellGeometry(rect.width / 10, Number.isFinite(lineHeight) ? lineHeight : rect.height);
  }
  measure() {
    this.refreshCellGeometry();
    return [Math.max(20, Math.floor(this.element.clientWidth / this.cellWidth)), Math.max(10, Math.floor(this.element.clientHeight / this.cellHeight))];
  }

  _drawSky(raster, projection, sky, palette, mode) {
    for (const [x, y, glyph] of projectSkyPoints(sky, projection.effective_time, [raster.width, raster.height])) raster.put(x, y, glyph, palette.star);
    if (mode === 'night') {
      const art = MOON_ART[lunarPhase(projection.effective_time)];
      art.forEach((line, row) => raster.text(Math.max(1, Math.floor(raster.width * 0.78)), 1 + row, line, palette.moon));
    }
  }

  _drawGround(raster, palette, season, horizon) {
    const texture = season === 'winter' ? '.,*..,.*' : season === 'autumn' ? ',~.^`.,~' : ',~.^,.,~';
    for (let x = 0; x < raster.width; x += 1) {
      raster.put(x, horizon, texture[x % texture.length], palette.soil);
      if ((x + 2) % 5 !== 0) raster.put(x, horizon + 1, texture[(x + 3) % texture.length], palette.ground);
    }
  }

  _drawAmbient(raster, projection, palette, season, horizon) {
    const seed = stringHash(`${projection.world_id}:${Math.floor((Number(projection.effective_time) + this.visualFrame) / 8)}`);
    if (season !== 'winter') {
      for (let index = 0; index < 4; index += 1) {
        const x = Math.floor(noise(seed + index * 17) * raster.width);
        const y = clamp(Math.floor(noise(seed + index * 29) * Math.max(2, horizon - 3)), 1, horizon - 2);
        raster.text(x, y, index % 2 ? '{}': '><', paletteColor(palette, index % 2 ? 'flower' : 'gold', season), true);
      }
    }
    if (timeOfDay(projection) === 'night') {
      for (let index = 0; index < 8; index += 1) {
        const x = Math.floor(noise(seed + index * 41) * raster.width), y = Math.floor(noise(seed + index * 53) * horizon);
        if ((this.visualFrame + index) % 4 !== 0) raster.put(x, y, '.', palette.gold, true);
      }
    } else if (this.visualFrame % 180 < 70) {
      const birdX = (Math.floor(this.visualFrame / 3) + (seed % raster.width)) % (raster.width + 8) - 4;
      raster.text(birdX, clamp(Math.floor(horizon * 0.22), 1, horizon - 3), this.visualFrame % 12 < 6 ? '\\v/' : '_v_', palette.stone, true);
    }
  }

  _drawWeather(raster, projection, palette, season, horizon) {
    const weather = String(projection.scene?.weather ?? '').toLowerCase();
    const rain = weather.includes('rain') || weather.includes('storm');
    const snow = weather.includes('snow') || (season === 'winter' && weather.includes('weather'));
    const leaves = season === 'autumn' && !snow;
    const count = rain ? 70 : snow ? 45 : leaves ? 16 : 0;
    const seed = stringHash(`${projection.world_id}:weather:${Math.floor(this.visualFrame / 2)}`);
    for (let index = 0; index < count; index += 1) {
      const x = Math.floor(noise(seed + index * 101) * raster.width);
      const y = Math.floor(noise(seed + index * 211) * Math.max(1, horizon));
        raster.put(x, y, rain ? (index % 3 ? '|' : '/') : snow ? (index % 4 ? '.' : '*') : (index % 2 ? '`' : ','),
        rain ? palette.water : snow ? palette.moon : palette.gold, true);
    }
    if (snow) {
      for (let x = 0; x < raster.width; x += 3) {
        if (noise(seed + x * 307) > 0.35) raster.put(x, horizon - 1, x % 2 ? '.' : '*', palette.moon, true);
      }
    }
  }

  _drawObject(raster, object, projection, masks, palette, season) {
    const depth = Number(object.depth ?? 100) / 100;
    const [x, y] = worldToScreen(object.position, projection.camera, [raster.width, raster.height], depth);
    const state = object.semantic_state ?? {};
    const hovered = this.hoverCell && Math.abs(this.hoverCell[0] - x) <= 4 && Math.abs(this.hoverCell[1] - y) <= 3;
    if (object.kind === 'plant') {
      const art = plantArt(object, this.visualFrame + (hovered ? 5 : 0));
      raster.art(x, y, art.lines, paletteColor(palette, art.color, season), { animated: hovered });
      for (const organ of state.visible_organs ?? []) {
        raster.put(x + Number(organ.offset?.[0] ?? 0), y - Number(organ.offset?.[1] ?? 0),
          organGlyph(organ.kind, organ.glyph_family), paletteColor(palette, organ.kind === 'bloom' ? 'flower' : 'brightGreen', season));
      }
      // Preserve the canonical root/anchor as the hit-testable visual origin.
      raster.put(x, y, glyphForProjection(object), paletteColor(palette, 'brightGreen', season));
      return;
    }
    if (object.kind === 'animal') {
      raster.art(x, y, animalArt(object, this.visualFrame), palette.creature, { animated: true });
      raster.put(x, y, glyphForProjection(object), palette.creature, true);
      const memories = Number(state.recent_memories?.length ?? 0);
      if (memories > 0) raster.put(x + 3, y - 2, memories > 2 ? '*' : '.', palette.flower, true);
      if (Number(state.bond_tier) > 0 && (projection.scene?.absence_summary ?? []).length) {
        raster.text(x - 1, y + 1, state.species_id === 'bird' ? 'v v' : state.species_id === 'turtle' ? '---' : '. .', palette.dim, true);
      }
      return;
    }
    if (object.kind === 'fixture') {
      const catalog = String(state.catalog_id ?? 'fixture');
      const decor = FIXTURE_DECOR[catalog];
      if (decor) raster.art(x, y, decor, catalog === 'pond' ? palette.water : palette.stone);
      const renderCells = Array.isArray(state.render_cells) ? state.render_cells : [];
      for (const cell of renderCells) raster.put(x + Number(cell.dx ?? 0), y + Number(cell.dy ?? 0), glyphForProjection(object, {
        connectedMask: state.connected_group && state.presentation_state !== 'open' ? Number(cell.connected_mask ?? 0) : null,
      }), state.presentation_state === 'on' ? palette.gold : palette.stone);
      return;
    }
    raster.put(x, y, glyphForProjection(object), state.family === 'feather' ? palette.creature : palette.gold);
  }

  render(projection) {
    if (!projection) return null;
    this.projection = projection;
    const viewport = this.measure(), raster = new Raster(viewport[0], viewport[1]);
    const masks = connectedMasks(projection.objects), sky = resolveBrowserSky({ scene: projection.scene, readerRegion: this.readerRegion });
    const mode = timeOfDay(projection), season = seasonOf(projection), palette = mode === 'night' ? NIGHT : mode === 'evening' ? EVENING : DAY;
    // The accepted Garden used a near-bottom ground plane.  The 58% dotted
    // horizon belonged to the sparse replacement and visually cut the world
    // in half, leaving fixtures stranded below an arbitrary divider.
    const horizon = clamp(viewport[1] - 4, 1, viewport[1] - 2);
    this._drawSky(raster, projection, sky, palette, mode);
    this._drawGround(raster, palette, season, horizon);
    this._drawAmbient(raster, projection, palette, season, horizon);
    [...projection.objects].sort((left, right) => Number(left.depth ?? 100) - Number(right.depth ?? 100) || compareCodePoints(left.object_id, right.object_id))
      .forEach(object => this._drawObject(raster, object, projection, masks, palette, season));
    this._drawWeather(raster, projection, palette, season, horizon);
    if (projection.scene?.memorial?.active) {
      const center = Math.floor(viewport[0] / 2);
      raster.art(center, horizon - 1, ['  @  ', ' @@@ ', '  |  '], palette.flower);
      raster.text(center + 6, horizon - 7, 'v', palette.moon);
    }
    this.clickBursts = this.clickBursts.filter(burst => this.visualFrame - burst.frame < 12);
    for (const burst of this.clickBursts) {
      const glyph = this.visualFrame - burst.frame < 5 ?
        (burst.kind === 'plant' ? (burst.species === 'pine' ? "'" : '*') : burst.kind === 'fixture' ? '+' : '.') : '.';
      [[0, -1], [-1, 0], [1, 0], [0, 1]].forEach(([dx, dy]) => raster.put(burst.x + dx, burst.y + dy, glyph, palette.gold, true));
    }

    if (this.element.style) {
      const pct = ((horizon + 1) / viewport[1] * 100).toFixed(2);
      this.element.style.background = `linear-gradient(to bottom,${palette.sky} ${pct}%,${palette.ground} ${pct}%)`;
      this.element.style.color = palette.text;
    }
    const lines = Array.from({ length: viewport[1] }, (_, row) => raster.line(row));
    while (this.rows.length < lines.length) {
      const row = document.createElement('div'); row.setAttribute('aria-hidden', 'true');
      this.element.appendChild(row); this.rows.push(row);
    }
    while (this.rows.length > lines.length) this.rows.pop().remove();
    const changedRows = [];
    lines.forEach((line, index) => {
      if (this.rows[index].textContent !== line) {
        this.rows[index].textContent = line;
        if (Object.hasOwn(this.rows[index], 'innerHTML') ||
          (typeof globalThis.HTMLElement !== 'undefined' && this.rows[index] instanceof globalThis.HTMLElement)) {
          this.rows[index].innerHTML = raster.html(index);
        }
        changedRows.push(index);
      }
    });
    const sceneLabel = [projection.scene?.weather, projection.scene?.palette, projection.scene?.story_time, projection.scene?.ambience].filter(Boolean).join(' · ');
    const absence = (projection.scene?.absence_summary ?? []).slice(0, 3), missed = (projection.scene?.missed_event_summaries ?? []).slice(0, 3);
    const memorial = projection.scene?.memorial?.active ? ` Memorial lasting; ${(projection.scene.memorial.examined_gifts ?? []).length} gifts remembered.` : '';
    const inventory = projection.scene?.inventory ?? [];
    const descriptions = projection.objects.slice(0, 24).map(object => object.semantic_state?.semantic_description ?? `${object.semantic_name} at ${object.position[0]},${object.position[1]}.`).join(' ');
    this.element.setAttribute('aria-label', `${sky.label}. ${sceneLabel || `${season} ${mode}`}. ${projection.objects.length} Garden objects. Inventory: ${inventory.join(', ') || 'empty'}.${absence.length ? ` Welcome back: ${absence.join(' ')}` : ''}${missed.length ? ` While you were away: ${missed.join(' ')}` : ''}${memorial} ${descriptions}`);
    this.lastFrame = { viewport, lines, changedRows, sky, palette, season, timeOfDay: mode,
      horizon, motionPaused: projection.motion_paused || this.prefersReducedMotion };
    return this.lastFrame;
  }

  startPresentation() {
    if (this.presentationTimer || typeof globalThis.requestAnimationFrame !== 'function') return;
    let last = 0;
    const tick = now => {
      this.presentationTimer = requestAnimationFrame(tick);
      if (now - last < 100 || !this.projection || this.projection.motion_paused || this.prefersReducedMotion) return;
      last = now; this.visualFrame += 1; this.render(this.projection);
    };
    this.presentationTimer = requestAnimationFrame(tick);
  }
  stopPresentation() {
    if (this.presentationTimer && typeof globalThis.cancelAnimationFrame === 'function') cancelAnimationFrame(this.presentationTimer);
    this.presentationTimer = null;
  }
  clear() {
    this.projection = null; this.lastFrame = null; this.rows = []; this.clickBursts = [];
    this.element.replaceChildren(); this.element.setAttribute('aria-label', 'Generic Garden preview.');
  }
  _eventCell(event) {
    const rect = this.element.getBoundingClientRect(), [cellWidth, cellHeight] = this.refreshCellGeometry();
    return [Math.floor((event.clientX - rect.left) / cellWidth), Math.floor((event.clientY - rect.top) / cellHeight)];
  }
  _hoverAt(event) { this.hoverCell = this._eventCell(event); if (this.projection && !this.prefersReducedMotion) this.render(this.projection); }
  _burstAt(event) {
    const [x, y] = this._eventCell(event);
    let selected = null;
    if (this.projection) {
      selected = this.projection.objects.find(object => {
        const depth = Number(object.depth ?? 100) / 100;
        const [wx, wy] = screenToWorld([x, y], this.projection.camera, this.measure(), depth), box = object.hotspot;
        return wx >= box.x && wx < box.x + box.width && wy >= box.y && wy < box.y + box.height;
      });
    }
    this.clickBursts.push({ x, y, frame: this.visualFrame, kind: selected?.kind,
      species: selected?.semantic_state?.species_id });
  }
  _selectAt(event) {
    if (!this.projection || !this.onSelect) return;
    const screen = this._eventCell(event);
    const candidates = this.projection.objects.filter(object => {
      const depth = Number(object.depth ?? 100) / 100;
      const [wx, wy] = screenToWorld(screen, this.projection.camera, this.measure(), depth), box = object.hotspot;
      return wx >= box.x && wx < box.x + box.width && wy >= box.y && wy < box.y + box.height;
    }).sort((left, right) => right.depth - left.depth || compareCodePoints(left.object_id, right.object_id));
    if (candidates[0]) this.onSelect(candidates[0], event);
  }
  onResize() { if (this.projection) this.render(this.projection); }
  setReaderRegion(region) { this.readerRegion = region; if (this.projection) this.render(this.projection); }
  setReducedMotion(value) {
    const next = Boolean(value); if (next === this.prefersReducedMotion) return;
    this.prefersReducedMotion = next; if (this.projection) this.render(this.projection);
  }
  start(runtime = null, options = {}) {
    this.startPresentation();
    if (runtime?.startLive) runtime.startLive({ ...options, prefersReducedMotion: this.prefersReducedMotion, onProjection: projection => this.render(projection) });
  }
  stop(runtime = null) { this.stopPresentation(); if (runtime?.stopLive) runtime.stopLive(); }
  setSeed() {}
  setPostComplete() {}
  setAnimalData() {}
  triggerAnimalFeedReaction(data = {}) {
    const animal = this.projection?.objects.find(object => object.kind === 'animal' && (!data.type || object.semantic_state?.species_id === data.type));
    if (!animal || !this.lastFrame) return;
    const [x, y] = worldToScreen(animal.position, this.projection.camera, this.lastFrame.viewport, Number(animal.depth ?? 100) / 100);
    this.clickBursts.push({ x, y, frame: this.visualFrame });
  }
  spawnAmbientBirdBurst() { this.visualFrame = Math.max(this.visualFrame, 1); if (this.projection) this.render(this.projection); }
  animalDebugState() { return 'canonical-rich-projection'; }
}
