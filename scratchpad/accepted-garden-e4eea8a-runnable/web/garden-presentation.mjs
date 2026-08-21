/**
 * GardenPresentation -- the single owner of the composed Garden picture.
 * ---------------------------------------------------------------------
 *
 * WHAT THIS FILE IS
 *
 * The public presentation interface of SPEC 7.2.2, installed by the
 * ownership-transfer patch of the execution order:
 *
 *   advancePresentationState(previousState, presentationEvents, tick) -> presentationState
 *   composePresentationFrame(projection, presentationState, context)  -> PresentationFrame
 *   paintPresentationFrame(frame, surface)                            -> void
 *
 * Before this module, `CanonicalGardenRenderer.render` composed and painted
 * in one pass: what the Garden looked like was decided by a method on a DOM
 * object, gated by `allowUnacceptedArt` -- a boolean the caller minted from
 * the HOSTNAME. That is the arrangement this file ends. Composition is now a
 * pure function whose paint authority arrives as data (the build-derived
 * accepted-paint manifest), so accepted art composes on every host and
 * unreviewed ink composes on none, and nothing about the picture can be
 * changed by moving the page somewhere friendlier.
 *
 * WHERE THE DRAWING CODE LIVES
 *
 * The painters themselves (`drawSky`, `drawGround`, `drawWeather`,
 * `drawObject`, ...) live in `web/garden-painting.mjs` as pure functions.
 * This module is their only orchestrator: it decides what is drawn, in what
 * order, under which authority, and what the resulting frame IS -- including
 * the exact measured pixel placement of every atlas asset, resolved here at
 * composition from the geometry the context carries. The renderer's class
 * contributes measurement and event capture and consumes the interface; it
 * decides nothing visual. The earlier import cycle (renderer -> presentation
 * for the interface, presentation -> renderer for the painters) is gone: the
 * 2026-08-04 architecture review named it as the wrapper shape that kept the
 * renderer the real owner, and the painting layer now stands alone so this
 * module depends only on it.
 *
 * DETERMINISM
 *
 * `composePresentationFrame` reads its three parameters and nothing else. No
 * wall clock, no randomness, no hostname, no DOM, no module state. The same
 * projection, state and context always return the same frame, which is what
 * lets the contract in `web/garden-presentation-contract.mjs` judge it by
 * composing twice and comparing.
 */

import { resolveBrowserSky } from './garden-sky.mjs';
import { validatePaintAuthority } from './garden-paint-authority.mjs';
import {
  Raster,
  drawSky, drawSkyLife, drawPondButterflies, drawGround, drawGardenBillboards, drawAmbient,
  drawWeather, drawObject,
  gardenPresentationProfile, gardenTerrainFrame,
  layoutGardenObjects, gardenDepthCohorts,
  timeOfDay, seasonOf, DAY, NIGHT, EVENING, paletteColor,
  objectBurstPattern, connectedMasks, objectPresentationArt,
  measuredAssetPlacement, escapeHtml, stringHash,
  AMBIENT_BIRD_FRAMES, AMBIENT_BIRD_COMPACT_FRAMES,
} from './garden-painting.mjs';

/**
 * How long a click burst stays alive, in presentation frames.
 *
 * Carried over exactly from the renderer's previous inline filter; the value
 * is presentation cadence, not gameplay, so it lives with the state advance
 * that ages bursts.
 */
const BURST_LIFETIME_FRAMES = 12;

/**
 * The accessibility floor for an interaction region, in CSS pixels.
 *
 * SPEC 7.2.2 clause 3 permits the composer to ENLARGE a transformed region
 * to this size and permits nothing else to be done to one.
 */
const MINIMUM_TARGET_PX = 44;

// ---------------------------------------------------------------------------
// The presentation LIFECYCLE: the legacy engine's persistent actors, seeded.
//
// Reopened step 5 (2026-08-04 architecture route): ambient birds, weather
// particles and snow accumulation are STATEFUL in the deployed viewer --
// counters that persist across ticks, actors that age, depth maps that
// accumulate. The stateless per-frame recomputations that stood in for them
// here (`ambientBirdSpawns`, `weatherParticlePosition`) were the recorded
// CAUSE of non-exact ports, and are deleted in the same patch that adds
// this. The laws below are the frozen blob's
// (59dc49a820d07d1b6a1741e17aafe6d075f6c99d), ported line for line; the two
// recorded deviations are the entropy source (seeded streams instead of
// `Math.random()`/`Date.now()`, with every distribution kept verbatim,
// because the presentation contract forbids unseeded randomness) and the
// authored-scene weather override, which the legacy page did not have.
// ---------------------------------------------------------------------------

/**
 * The deployed viewer's RNG, ported verbatim (blob 59dc49a8 lines 593-612).
 *
 * State travels as a plain four-integer tuple so the advance can return a
 * NEW state without mutating the previous one -- advancing twice from one
 * state must produce one result. The legacy page kept SEPARATE streams per
 * layer (the particle layer owned an RNG; the creature layer drew from
 * `Math.random()`), and the port keeps that separation: bird draws and
 * particle draws never perturb each other's sequences.
 */
export class LifecycleRng {
  constructor(state) {
    if (Array.isArray(state)) {
      [this._a, this._b, this._c, this._d] = state;
      return;
    }
    const seed = state >>> 0;
    const h = x => { x ^= x >> 16; x = Math.imul(x, 0x45d9f3b) >>> 0; x ^= x >> 16; return x >>> 0; };
    this._a = h(seed); this._b = h(seed + 1); this._c = h(seed + 2); this._d = h(seed + 3);
    for (let i = 0; i < 20; i += 1) this.random();
  }
  random() {
    const a = this._a, b = this._b, c = this._c, d = this._d;
    const t = (a + b | 0) + d | 0;
    this._d = d + 1 | 0;
    this._a = b ^ (b >>> 9);
    this._b = (c + (c << 3)) | 0;
    this._c = (c << 21 | c >>> 11);
    this._c = this._c + t | 0;
    return (t >>> 0) / 4294967296;
  }
  randint(low, high) { return low + Math.floor(this.random() * (high - low + 1)); }
  choice(values) { return values[Math.floor(this.random() * values.length)]; }
  uniform(low, high) { return low + this.random() * (high - low); }
  state() { return [this._a, this._b, this._c, this._d]; }
}

/** Local clamp; the painting module keeps its own private copy. */
const clampValue = (value, low, high) => Math.max(low, Math.min(high, value));

/**
 * The wind law, verbatim (blob 59dc49a8 lines 1721-1725): the product of two
 * slow oscillators with a positive offset for a prevailing direction. Pure
 * in the tick, so it carries no state.
 */
export function lifecycleWindAt(tick) {
  const n0 = Math.sin(tick * 0.008) + 0.35 * Math.sin(tick * 0.0173 + 1.3);
  const n1 = Math.sin(tick * 0.0052 + 4.1) + 0.35 * Math.sin(tick * 0.0117 + 2.2);
  return clampValue(n0 * n1 * 0.45 + 0.08, -0.65, 0.65);
}

/**
 * The rain/snow/leaf surface maps, derived from the plant layout the same
 * way the legacy `buildCollision` derived them from its placed plants
 * (blob lines 785-803): every plant ink cell collides, the topmost ink row
 * per column is the landing surface, and foliage three or more rows above
 * the plant's base is canopy a leaf may detach from.
 */
function surfaceMapsOf(layout) {
  const collision = new Set();
  const top = {};
  const canopy = [];
  for (const entry of layout) {
    if (entry.object.kind !== 'plant') continue;
    const lines = entry.art?.lines ?? [];
    lines.forEach((line, rowIndex) => {
      const row = entry.rect.top + rowIndex;
      [...line].forEach((glyph, columnIndex) => {
        if (glyph === ' ' || glyph === '') return;
        const column = entry.rect.left + columnIndex;
        collision.add(`${row},${column}`);
        if (top[column] === undefined || row < top[column]) top[column] = row;
        if (entry.rect.bottom - row >= 3) canopy.push([row, column]);
      });
    });
  }
  return { collision, top, canopy };
}

/** A fresh lifecycle for one world: seeded streams, empty actor pools. */
function initialLifecycle(worldId) {
  return {
    worldId,
    // Distinct salts per stream, mirroring the legacy page's separate
    // entropy sources for creatures and particles.
    birdRng: new LifecycleRng(stringHash(`${worldId}:birds`) >>> 0).state(),
    particleRng: new LifecycleRng(stringHash(`${worldId}:particles`) >>> 0).state(),
    ambientRng: new LifecycleRng(stringHash(`${worldId}:ambient`) >>> 0).state(),
    tick: 0,
    lastFrame: null,
    birdT: 0,
    birds: [],
    ambientKey: null,
    ambient: [],
    particles: [],
    snowDepth: {},
    cols: 0,
    groundY: 0,
  };
}

function createAmbientActors(rng, season, mode, cols, groundY, pondCenter = null) {
  const actors = [];
  if ((season === 'spring' || season === 'summer') && cols >= 10 && groundY >= 12) {
    const count = pondCenter ? rng.randint(2, 3) : rng.randint(1, 2);
    for (let index = 0; index < count; index += 1) {
      const phase = rng.random() * 6.2832;
      const radiusX = 4 + rng.random() * 3;
      const radiusY = 1.2 + rng.random() * 1.3;
      actors.push({
        kind: 'butterfly', orbit: Boolean(pondCenter),
        centerX: pondCenter?.[0] ?? null, centerY: pondCenter?.[1] ?? null,
        angle: phase, angularVelocity: (index % 2 ? -1 : 1) * (0.035 + rng.random() * 0.02),
        radiusX, radiusY,
        x: pondCenter ? pondCenter[0] + Math.cos(phase) * radiusX : rng.randint(5, cols - 5),
        y: pondCenter ? pondCenter[1] + Math.sin(phase) * radiusY : rng.randint(3, groundY - 8),
        vx: rng.random() > 0.5 ? 0.3 : -0.3, phase,
        color: rng.choice(['bright_magenta', 'magenta', 'bright_cyan', 'cyan']),
      });
    }
  }
  if (season === 'summer' && mode === 'evening' && cols >= 8 && groundY >= 14) {
    const count = rng.randint(3, 5);
    for (let index = 0; index < count; index += 1) {
      actors.push({
        kind: 'firefly', x: rng.randint(3, cols - 3), y: rng.randint(groundY - 12, groundY - 3),
        vx: (index % 3 - 1) * 0.04, vy: index % 2 ? 0.02 : -0.02,
        phase: index * 0.7, on: 3 + index % 5, off: 10 + index % 15,
      });
    }
  }
  return actors;
}

/**
 * The ambient-bird spawn, verbatim (blob lines 1160-1180): random entry
 * side, 28% flocks of 3-5 trailing by 5 columns with the deployed vertical
 * offsets, base altitude within the upper sky clamped to 1..groundY-8,
 * 0.42 cells a tick, the compact frame pair below 60 columns.
 */
function spawnAmbientBirds(birds, rng, cols, groundY, count, forceFlock) {
  const compact = cols < 60;
  const frames = compact ? AMBIENT_BIRD_COMPACT_FRAMES : AMBIENT_BIRD_FRAMES;
  const width = Math.max(...frames.map(value => [...value].length));
  const fromLeft = rng.random() > 0.5;
  const flock = forceFlock ? count
    : (rng.random() < 0.28 ? 3 + Math.floor(rng.random() * 3) : 1);
  const baseY = Math.floor(rng.random() * Math.max(4, groundY - 12)) + 2;
  for (let i = 0; i < flock; i += 1) {
    const trail = i * 5;
    const offsetY = (i % 2 === 0 ? 0 : 1) + (i === 2 ? -1 : 0);
    birds.push({
      x: fromLeft ? -width - 2 - trail : cols + 2 + trail,
      y: clampValue(baseY + offsetY, 1, Math.max(2, groundY - 8)),
      vx: fromLeft ? 0.42 : -0.42,
      frameStep: 5 + (i % 3),
      compact,
      width,
    });
  }
}

/** One particle, with the legacy constructor's phase/amp/rotation draws. */
function newParticle(rng, kind, x, y, vx, vy, glyph, color, maxAge) {
  return {
    kind, x, y, vx, vy, glyph, color, age: 0, maxAge,
    phase: rng.random() * 6.28,
    amp: 0.3 + rng.random() * 0.7,
    rotPhase: Math.floor(rng.random() * 3),
  };
}

/**
 * The seasonal spawn law, verbatim (blob lines 1040-1075), with the one
 * recorded addition the canonical product needs: an AUTHORED scene weather
 * takes precedence over the season, because authored weather is canonical
 * state the legacy page never had. An empty authored weather falls through
 * to the deployed season law exactly.
 */
function spawnParticles(particles, rng, facts) {
  const { season, weather, cols, wind, canopy } = facts;
  const authoredRain = weather.includes('rain') || weather.includes('storm');
  const authoredSnow = weather.includes('snow');
  const seasonal = weather === '' || weather.includes('weather');
  const rainGlyph = wind > 0.2 ? '\\' : wind < -0.2 ? '/' : '|';
  const rainCount = particles.filter(p => p.kind === 'rain').length;
  if ((authoredRain || (seasonal && season === 'spring')) &&
      rainCount < 60 && rng.random() < 0.35) {
    particles.push(newParticle(rng, 'rain', rng.random() * cols, 0,
      wind * 0.3, rng.uniform(0.5, 1.0), rainGlyph, 'rain', 60));
  }
  if (seasonal && season === 'autumn' && rainCount < 120) {
    const n = rng.randint(2, 5);
    for (let i = 0; i < n; i += 1) {
      particles.push(newParticle(rng, 'rain', rng.random() * cols, 0,
        wind * 0.3, rng.uniform(0.7, 1.4), rainGlyph, 'rain', 35));
    }
  }
  if ((authoredSnow || (seasonal && season === 'winter')) &&
      particles.filter(p => p.kind === 'snow').length < 80) {
    particles.push(newParticle(rng, 'snow', rng.random() * cols, 0,
      0, rng.uniform(0.08, 0.25), rng.choice(['.', '*']), 'bright_white', 300));
  }
  if (seasonal && season === 'autumn' && canopy.length) {
    const leafCap = Math.max(0, Math.min(60, Math.floor(canopy.length / 3)));
    const leafCount = particles.filter(p => p.kind === 'leaf' || p.kind === 'leaf-rest').length;
    if (leafCount < leafCap) {
      let x, y, vx, vy;
      if (rng.random() < 0.3) {
        x = rng.random() * cols; y = rng.randint(0, 2);
        vx = rng.uniform(-0.3, 0.3); vy = rng.uniform(0.1, 0.25);
      } else {
        const [row, column] = canopy[Math.floor(rng.random() * canopy.length)];
        x = column; y = row;
        vx = rng.uniform(-0.2, 0.2); vy = rng.uniform(0.05, 0.2);
      }
      particles.push(newParticle(rng, 'leaf', x, y, vx, vy,
        rng.choice([',', "'", '~', '*']), 'autumn', 150));
    }
  }
}

/** Plant-hit fragments, verbatim (blob lines 1025-1030). */
function spawnFragments(particles, rng, cx, cy, wind) {
  const n = rng.randint(2, 4);
  for (let i = 0; i < n; i += 1) {
    particles.push(newParticle(rng, 'frag', cx, cy,
      (wind > 0 ? -1 : 1) * rng.uniform(0.1, 0.4), rng.uniform(-0.3, 0),
      "'", 'rain', rng.randint(3, 8)));
  }
}

/** Ground splashes, verbatim (blob lines 1032-1037). */
function spawnSplashes(particles, rng, cx, groundY) {
  const n = rng.randint(3, 5);
  for (let i = 0; i < n; i += 1) {
    particles.push(newParticle(rng, 'splash',
      cx + rng.randint(-1, 1), groundY, rng.uniform(-0.35, 0.35), 0,
      "'", 'white', rng.randint(3, 8)));
  }
}

/**
 * One tick of particle physics, verbatim from the legacy `update` loop
 * (blob lines 960-1023): rain gains gravity and splashes or fragments on
 * impact; snow sways by its own phase and accumulates per-column depth up
 * to 3 on the landing surface; leaves drift on the wind, tumble through
 * their three-glyph rotation, and rest on the ground for 41 ticks; spray
 * ages through the ' . · sequence.
 */
function stepParticles(particles, rng, snowDepth, facts) {
  const { cols, groundY, wind, collision, top } = facts;
  const alive = [];
  for (const p of particles) {
    p.age += 1;
    if (p.kind === 'rain') {
      p.vy = Math.min(p.vy + 0.08, 2.2);
      p.x += p.vx + wind * 0.3;
      p.y += p.vy;
      const row = p.y | 0, column = p.x | 0;
      if (collision.has(`${row},${column}`)) {
        spawnFragments(alive, rng, column, row, wind);
      } else if (row >= groundY) {
        spawnSplashes(alive, rng, column, groundY);
      } else if (p.age <= p.maxAge && p.x >= 0 && p.x < cols) {
        alive.push(p);
      }
      continue;
    }
    if (p.kind === 'snow') {
      p.x += p.amp * Math.sin(p.phase + p.age * 0.04) * 0.25;
      p.y += p.vy;
      const column = Math.round(p.x);
      const surface = top[column] !== undefined ? top[column] : groundY;
      const depth = snowDepth[column] || 0;
      if ((p.y | 0) >= surface - depth) {
        if (depth < 3) snowDepth[column] = depth + 1;
        continue;
      }
      if (p.age <= p.maxAge && p.x >= 0 && p.x < cols && p.y >= 0) alive.push(p);
      continue;
    }
    if (p.kind === 'leaf') {
      p.vx += wind * 0.04;
      p.vx = Math.max(-0.8, Math.min(0.8, p.vx));
      p.vy = Math.min(p.vy + 0.04, 1.5);
      p.x += p.vx;
      p.y += p.vy * 0.4;
      if (p.age % 8 === 0) p.rotPhase = (p.rotPhase + 1) % 3;
      p.glyph = ['\\', '-', '/'][p.rotPhase];
      if ((p.y | 0) >= groundY) {
        p.kind = 'leaf-rest'; p.vx = 0; p.vy = 0; p.glyph = '-';
        p.age = 0; p.maxAge = 41;
        alive.push(p);
      } else if (p.age <= p.maxAge && p.x >= 0 && p.x < cols) {
        alive.push(p);
      }
      continue;
    }
    if (p.kind === 'leaf-rest') {
      if (p.age < p.maxAge) alive.push(p);
      continue;
    }
    if (p.kind === 'frag' || p.kind === 'splash') {
      const f = p.age / p.maxAge;
      p.glyph = f < 0.4 ? "'" : f < 0.75 ? '.' : '·';
      if (p.kind === 'frag') { p.vx *= 0.82; p.vy += 0.05; }
      else { p.vx *= 0.88; }
      p.x += p.vx;
      p.y += p.vy;
      if (p.age < p.maxAge && p.x >= 0 && p.x < cols && p.y < groundY + 2) alive.push(p);
      continue;
    }
  }
  return alive;
}

/**
 * Advance the lifecycle by the elapsed presentation ticks.
 *
 * Aging is measured in TICK DELTAS, not advance calls: a hover repaint
 * arrives within the same tick and steps nothing, so pointer traffic can
 * never speed the garden up. The step cap bounds the cost of a resumed
 * suspended tab; the legacy page's rAF loop simply stopped counting while
 * hidden, and so does this.
 *
 * Winter gates bird SPAWNS only, exactly as deployed: an active bird keeps
 * crossing (the previous stateless port made mid-flight birds vanish at the
 * season boundary -- a recorded divergence this repair removes), the timer
 * keeps counting and keeps drawing its per-tick threshold, so the first
 * non-winter tick with an over-threshold counter spawns immediately.
 */
function advanceLifecycle(previous, scene, frame) {
  const projection = scene.projection ?? {};
  const worldId = String(projection.world_id ?? 'garden');
  const state = previous && previous.worldId === worldId
    ? previous : initialLifecycle(worldId);
  const steps = state.lastFrame === null
    ? 1 : Math.max(0, Math.min(240, frame - state.lastFrame));

  const viewport = scene.viewport;
  const cols = Number(viewport?.[0]) || state.cols || 80;
  const profile = gardenPresentationProfile(viewport ?? [cols, 24]);
  const terrain = gardenTerrainFrame(projection, viewport ?? [cols, 24], profile);
  const groundY = terrain.groundFront;
  const season = seasonOf(projection);
  const mode = timeOfDay(projection);
  const weather = String(projection.scene?.weather ?? '').toLowerCase();
  const layout = layoutGardenObjects(projection, viewport ?? [cols, 24], frame, terrain);
  const pond = layout.find(entry =>
    entry.object.kind === 'fixture' && entry.object.semantic_state?.catalog_id === 'pond');
  const pondCenter = pond
    ? [Math.round((pond.rect.left + pond.rect.right) / 2), pond.rect.top - 1]
    : null;
  const ambientRng = new LifecycleRng(state.ambientRng);
  const ambientKey = `${season}:${mode}:${cols}:${groundY}:${pondCenter?.join(',') ?? 'no-pond'}`;
  let ambient = state.ambientKey === ambientKey
    ? state.ambient.map(actor => ({ ...actor }))
    : createAmbientActors(ambientRng, season, mode, cols, groundY, pondCenter);
  for (const actor of ambient) {
    if (actor.kind === 'butterfly' && actor.orbit && pondCenter) {
      actor.centerX = pondCenter[0]; actor.centerY = pondCenter[1];
    }
  }
  if (steps === 0) {
    return {
      ...state,
      ambientRng: ambientRng.state(), ambientKey, ambient,
      lastFrame: frame, cols, groundY,
    };
  }

  const surfaces = surfaceMapsOf(layout);
  const birdRng = new LifecycleRng(state.birdRng);
  const particleRng = new LifecycleRng(state.particleRng);
  let birds = state.birds.map(bird => ({ ...bird }));
  let particles = state.particles.map(particle => ({ ...particle }));
  const snowDepth = { ...state.snowDepth };
  let birdT = state.birdT;
  let tick = state.tick;

  for (let step = 0; step < steps; step += 1) {
    tick += 1;
    const wind = lifecycleWindAt(tick);

    // Butterflies and fireflies keep their deployed actor identity and move
    // continuously.  Repainting after a pointer event therefore cannot
    // regenerate or teleport them; only elapsed presentation ticks advance
    // their positions.
    for (const actor of ambient) {
      if (actor.kind === 'butterfly') {
        if (actor.orbit && Number.isFinite(actor.centerX) && Number.isFinite(actor.centerY)) {
          actor.angle += actor.angularVelocity;
          actor.x = actor.centerX + Math.cos(actor.angle) * actor.radiusX;
          actor.y = actor.centerY + Math.sin(actor.angle) * actor.radiusY;
        } else {
          actor.x += actor.vx;
          actor.y += 0.15 * Math.sin(tick * 0.05 + actor.phase);
          if (actor.x < 1) { actor.x = 1; actor.vx = Math.abs(actor.vx); }
          if (actor.x > cols - 3) { actor.x = cols - 3; actor.vx = -Math.abs(actor.vx); }
          actor.y = clampValue(actor.y, 2, Math.max(2, groundY - 5));
        }
      } else if (actor.kind === 'firefly') {
        actor.x += actor.vx;
        actor.y += actor.vy + 0.05 * Math.sin(tick * 0.02 + actor.phase);
        actor.y = clampValue(actor.y, 1, Math.max(1, groundY - 2));
      }
    }

    // Birds: step, deactivate beyond the deployed bounds, then the per-tick
    // resampled respawn threshold (blob lines 1476-1489). The draw happens
    // every tick INCLUDING winter, exactly as the deployed condition
    // evaluated Math.random() before testing the season.
    for (const bird of birds) bird.x += bird.vx;
    birds = birds.filter(bird =>
      bird.x >= -bird.width - 2 && bird.x <= cols + bird.width + 2);
    birdT += 1;
    const threshold = 250 + Math.floor(birdRng.random() * 350);
    if (birdT > threshold && season !== 'winter') {
      birdT = 0;
      spawnAmbientBirds(birds, birdRng, cols, groundY, 1, false);
    }

    // Particles: the deployed layer spawned every second tick and stepped
    // every tick (blob lines 960-964).
    if (tick % 2 === 0) {
      spawnParticles(particles, particleRng, {
        season, weather, cols, wind, canopy: surfaces.canopy,
      });
    }
    particles = stepParticles(particles, particleRng, snowDepth, {
      cols, groundY, wind,
      collision: surfaces.collision, top: surfaces.top,
    });
  }

  return {
    worldId,
    birdRng: birdRng.state(),
    particleRng: particleRng.state(),
    ambientRng: ambientRng.state(), ambientKey, ambient,
    tick, lastFrame: frame, birdT, birds, particles, snowDepth, cols, groundY,
  };
}

/**
 * Advance the disposable presentation state.
 *
 * This is the only door through which pointer movement, pointer leave, click
 * feedback, focus changes and the per-frame scene facts enter the
 * presentation layer. The state it returns is disposable and unpersisted,
 * but not derivable from the projection alone: hover depends on where the
 * pointer is, bursts depend on prior clicks, and the lifecycle -- birds,
 * weather particles, snow depth -- depends on every tick since the world
 * opened. Everything here used to be instance fields on the renderer
 * (`this.hoverCell`, `this.clickBursts`, `this.focusedObjectId`) mutated
 * from event handlers; making the advance explicit is what lets the composer
 * stay a pure function while the picture still responds.
 *
 * @param {object|null} previousState - the prior state, or null for the first frame
 * @param {Array<object>} presentationEvents - events gathered since the last advance:
 *   `{kind:'pointer-move', cell:[x,y]}`, `{kind:'pointer-leave'}`,
 *   `{kind:'focus-change', objectId}`,
 *   `{kind:'burst', x, y, kind_, species, catalog, objectId}` for click
 *   feedback, and `{kind:'scene', projection, viewport}` -- the adapter's
 *   per-frame scene facts, which drive the lifecycle. Without a scene event
 *   the lifecycle stands still: nothing spawns and nothing ages.
 * @param {{frame: number}} tick - the presentation frame counter; the ONLY
 *   time source. The advance never reads a clock.
 * @returns {object} the next presentation state
 */
export function advancePresentationState(previousState, presentationEvents, tick) {
  const frame = Number(tick?.frame ?? 0);
  let hoverCell = previousState?.hoverCell ?? null;
  let focusedObjectId = previousState?.focusedObjectId ?? null;
  // Bursts age out after their lifetime; the filter ran inline in render()
  // before, and moving it here is what makes composing twice from one state
  // return one picture -- the composer no longer mutates the list it reads.
  const clickBursts = (previousState?.clickBursts ?? [])
    .filter(burst => frame - burst.frame < BURST_LIFETIME_FRAMES);

  let scene = null;
  for (const event of presentationEvents ?? []) {
    if (event.kind === 'pointer-move') hoverCell = event.cell;
    else if (event.kind === 'pointer-leave') hoverCell = null;
    else if (event.kind === 'focus-change') focusedObjectId = event.objectId ?? null;
    else if (event.kind === 'scene') scene = event;
    else if (event.kind === 'burst') {
      clickBursts.push({
        x: event.x, y: event.y, frame,
        kind: event.objectKind, species: event.species,
        catalog: event.catalog, objectId: event.objectId,
      });
    }
  }
  const lifecycle = scene
    ? advanceLifecycle(previousState?.lifecycle ?? null, scene, frame)
    : previousState?.lifecycle ?? null;
  return { visualFrame: frame, hoverCell, focusedObjectId, clickBursts, lifecycle };
}

/**
 * The set of ids the given manifest allows to paint.
 *
 * Authority is MANDATORY. An earlier version of this function returned null
 * for a missing manifest, meaning "no restriction" -- so a slow manifest
 * fetch briefly painted everything and a failed one painted everything
 * permanently, while the E2E never noticed because its static server always
 * served the file. The 2026-08-04 architecture review named that fail-open
 * seam directly: missing or invalid authority must refuse composition, not
 * widen it. Diagnostic inspection of unaccepted ink still exists, one level
 * down: construct a `Raster` without authority and call painters directly.
 * What no longer exists is a COMPOSED FRAME that was not composed under the
 * registers.
 *
 * Validation itself lives in ONE place -- `validatePaintAuthority` in
 * web/garden-paint-authority.mjs, mirroring the generator's full shape --
 * because the first version of this refusal re-declared a three-list schema
 * of its own and accepted a partial manifest (claim verification,
 * 2026-08-04). Laws are validated as present but are NEVER paint sources,
 * so the permitted set is built from the other three lists only.
 *
 * @param {object} manifest - the build-derived accepted-paint manifest
 * @returns {Set<string>} every id the manifest allows to paint
 * @throws {Error} when the manifest is absent or not the generator's shape
 */
function permittedSources(manifest) {
  validatePaintAuthority(manifest);
  return new Set(
    [
      'accepted_assets', 'review_candidate_assets',
      'accepted_recipes', 'accepted_legacy_art',
    ]
      .flatMap(name => manifest[name]),
  );
}

/**
 * The atlas identity and state an interaction region is transformed from.
 *
 * Projection owns the object and its declared action; the atlas owns the
 * mask. The region must NAME the asset/state it came from so the frame can
 * prove it was transformed rather than recovered from whatever happened to
 * be painted. Objects whose art has no accepted identity (placeholders) get
 * no region from the frame -- their ink is suppressed under authority, and
 * a target over suppressed ink would be a target over nothing.
 *
 * @param {object} object - the projected object
 * @param {object} entry - its layout entry (for the level of detail)
 * @param {number} frame - presentation frame, for art-state resolution
 * @returns {{assetId: string, stateId: string}|null}
 */
function regionMaskIdentity(object, entry, frame) {
  const art = objectPresentationArt(object, frame, entry.lod, false);
  const assetId = art.assetId ?? art.identity ?? null;
  if (!assetId) return null;
  const stateId = String(object.semantic_state?.presentation_state ?? 'default');
  return { assetId, stateId };
}

/**
 * Compose one PresentationFrame.
 *
 * The orchestration here is exactly what `render()` used to do between
 * measuring the viewport and touching the DOM, with two deliberate changes:
 *
 *   1. The `allowUnacceptedArt` gate is GONE. Every painter always runs; the
 *      raster's authority (from `context.acceptedManifest`) suppresses any
 *      write whose source the manifest does not accept, recording it as an
 *      attempted-but-suppressed primitive. Unreviewed ink no longer depends
 *      on where the code runs -- it composes nowhere.
 *   2. The hostname-dependent background branch is GONE. The background is
 *      the accepted sky-to-ground gradient always, described as data.
 *
 * @param {object} projection - the canonical projection, read-only
 * @param {object} state - what `advancePresentationState` returned
 * @param {object} context - `{viewport, profile, presentationGeometry,
 *   acceptedManifest, environment}` per SPEC 7.2.2's input table
 * @returns {object} the PresentationFrame
 */
export function composePresentationFrame(projection, state, context) {
  const viewport = context.viewport;
  const geometry = context.presentationGeometry ?? {};
  const cellWidth = Number(geometry.cellAdvance ?? 8);
  const cellHeight = Number(geometry.lineHeight ?? 15);
  // Whether the context's geometry can actually measure text. The adapter
  // passes its whole geometry object; a context built from bare cell numbers
  // has no `measureAsset`, and measured atlas placement is then composed as
  // absent rather than guessed from a column pitch. This flag decides BOTH
  // the pixel placements below and whether the lattice HTML omits
  // measured-owned cells -- one decision, so an asset is painted by exactly
  // one layer.
  const canMeasure = !geometry.affineOnly && typeof geometry.measureAsset === 'function';
  const environment = context.environment ?? {};
  // Throws when context carries no valid manifest: composition is refused
  // outright rather than proceeding unrestricted (reopened step 1).
  const authority = permittedSources(context.acceptedManifest);

  const raster = new Raster(viewport[0], viewport[1], { authority });
  connectedMasks(projection.objects);
  const sky = resolveBrowserSky({
    scene: projection.scene, readerRegion: environment.readerRegion ?? null,
  });
  const mode = timeOfDay(projection);
  const season = seasonOf(projection);
  const palette = mode === 'night' ? NIGHT : mode === 'evening' ? EVENING : DAY;
  const profile = gardenPresentationProfile(viewport);
  const terrain = gardenTerrainFrame(projection, viewport, profile);
  const horizon = profile.horizon;
  const layout = layoutGardenObjects(projection, viewport, state.visualFrame, terrain);
  const depthCohorts = gardenDepthCohorts(layout, profile, terrain);

  drawSky(raster, projection, sky, palette, profile, mode);
  // Sky life is drawn straight after the stars so that ground, planting and
  // objects all paint over it. The birds are the LIFECYCLE's actors --
  // spawned and stepped by the state advance, painted here from state alone.
  // (Recorded painter-order divergence, unchanged by the lifecycle port: the
  // deployed page painted creatures after plants; this backdrop position
  // predates the port and moves, if it moves, with the painter-order law.)
  drawSkyLife(raster, state.lifecycle, palette);
  drawGround(raster, palette, season, terrain);
  drawAmbient(raster, projection, palette, season, horizon, profile);
  const view = {
    visualFrame: state.visualFrame,
    hoverCell: state.hoverCell,
    focusedObjectId: state.focusedObjectId,
  };
  // One billboard queue owns occlusion.  The old two-phase owner painted all
  // presentation-native plants first and every canonical fixture afterwards,
  // so a farther pond or stepping-stone card could cut a nearer plant in half.
  // Backdrop plants and canonical objects now share one baseline/depth sort.
  drawGardenBillboards(
    raster, projection, palette, season, profile, terrain, state.visualFrame,
    state.hoverCell, lifecycleWindAt(state.lifecycle?.tick ?? state.visualFrame),
    layout, view,
  );
  drawPondButterflies(raster, state.lifecycle, palette);
  const weatherReactions = drawWeather(raster, state.lifecycle, palette);
  if (projection.scene?.memorial?.active) {
    const center = Math.floor(viewport[0] / 2);
    raster.art(center, horizon - 1, ['  @  ', ' @@@ ', '  |  '], palette.flower,
      { source: 'recipe.special.post_complete_marker' });
  }

  const motionSuppressed = Boolean(projection.motion_paused || environment.reducedMotion);
  if (!motionSuppressed) {
    for (const burst of state.clickBursts ?? []) {
      const age = state.visualFrame - burst.frame;
      for (const [dx, dy, glyph, color] of objectBurstPattern(burst, age)) {
        raster.put(burst.x + dx, burst.y + dy, glyph,
          paletteColor(palette, color, season), true,
          null, { source: 'recipe.feedback.click_leaf_burst' });
      }
    }
  }

  // ---- frame assembly ----------------------------------------------------
  const attempted = raster.attempted.map(entry => ({
    units: 'cell', profile: context.profile ?? 'browser-proportional', ...entry,
  }));
  // A primitive is visible when it survived: it was not suppressed by
  // authority and its cell still points at it after every later write. This
  // derivation is the raster's own occlusion outcome -- no second policy.
  const visibleIndexes = new Set();
  for (const row of raster.cellAttempt) {
    for (const index of row) if (index !== null) visibleIndexes.add(index);
  }
  const visible = attempted.filter((entry, index) =>
    !entry.suppressed && visibleIndexes.has(index));

  // Interaction regions: the canonical hit rectangle, transformed through
  // the same cell geometry the art uses, bound to the projected object and
  // named after its atlas mask, then enlarged -- only enlarged -- to the
  // accessibility floor, centred so growing never moves the target off its
  // ink.
  const interactionRegions = [];
  for (const entry of layout) {
    const mask = regionMaskIdentity(entry.object, entry, state.visualFrame);
    if (!mask) continue;
    const rect = entry.hitRect;
    const rawWidth = (rect.right - rect.left + 1) * cellWidth;
    const rawHeight = (rect.bottom - rect.top + 1) * cellHeight;
    const width = Math.max(rawWidth, MINIMUM_TARGET_PX);
    const height = Math.max(rawHeight, MINIMUM_TARGET_PX);
    interactionRegions.push({
      object_id: entry.object.object_id,
      asset_id: mask.assetId,
      state_id: mask.stateId,
      units: 'pixel',
      x: rect.left * cellWidth - (width - rawWidth) / 2,
      y: rect.top * cellHeight - (height - rawHeight) / 2,
      width, height,
    });
  }

  // ---- measured pixel placement, resolved AT COMPOSITION -----------------
  // Reopened step 2: the frame contains every final visible primitive,
  // including the exact measured pixel placement of atlas assets. Before
  // this, the frame carried the raw asset descriptors (lines, anchors) and
  // the SURFACE resolved their pixels at paint time with its private
  // geometry -- a second visual owner deciding placement after composition.
  // The raster's measured plan is already authority-gated, so everything
  // resolved here is accepted ink with its source identity attached.
  const resolvedMeasuredAssets = canMeasure
    ? raster.measuredAssets.map(asset => {
      const placed = measuredAssetPlacement(geometry, asset);
      return {
        object_id: placed.objectId,
        source_id: asset.source ?? null,
        units: 'pixel',
        left: placed.left, top: placed.top,
        width: placed.width, height: placed.height,
        // Final platform primitives only: glyph, pixel position, colour.
        // The logical row/column each glyph came from is diagnostic
        // provenance, not paint data, and lives in `diagnostics` below.
        glyphs: placed.glyphs.map(glyph => ({
          glyph: glyph.glyph, x: glyph.x, y: glyph.y, color: glyph.color ?? null,
          row: glyph.row, column: glyph.column,
        })),
        owner: asset.owner,
        world_anchor: [...asset.anchor],
        art_anchor: [...asset.artAnchor],
      };
    })
    : [];

  // Exact-font mode paints ONE ordered platform plane. The former split put
  // every measured atlas asset in an overlay above every lattice-painted
  // plant, so no baseline sort could make a nearer plant occlude a pond. The
  // raster has already settled final cell ownership and painter order; this
  // projection merely gives those final glyphs their finished pixel
  // positions. Affine/degraded mode keeps its existing row transport.
  const platformGlyphs = canMeasure ? [] : null;
  if (canMeasure) {
    for (const placement of resolvedMeasuredAssets) {
      for (const glyph of placement.glyphs) {
        const worldX = placement.world_anchor[0] - placement.art_anchor[0] + glyph.column;
        const worldY = placement.world_anchor[1] - placement.art_anchor[1] + glyph.row;
        if (worldX < 0 || worldX >= raster.width || worldY < 0 || worldY >= raster.height)
          continue;
        if (raster.owners[worldY][worldX] !== placement.owner) continue;
        platformGlyphs.push({
          glyph: glyph.glyph, x: glyph.x, y: glyph.y, color: glyph.color,
          painter_order: raster.cellAttempt[worldY][worldX] ?? 0,
          source_id: raster.sources[worldY][worldX],
        });
      }
    }
    for (let row = 0; row < raster.height; row += 1) {
      for (let column = 0; column < raster.width; column += 1) {
        const glyph = raster.glyphs[row][column];
        if (glyph === ' ' || glyph === '' || raster.owners[row][column] !== null) continue;
        platformGlyphs.push({
          glyph, x: column * cellWidth, y: row * cellHeight,
          color: raster.colors[row][column],
          painter_order: raster.cellAttempt[row][column] ?? 0,
          source_id: raster.sources[row][column],
        });
      }
    }
    platformGlyphs.sort((left, right) => left.painter_order - right.painter_order);
  }
  const measuredAssetPlacements = resolvedMeasuredAssets.map(placement => ({
    object_id: placement.object_id,
    source_id: placement.source_id,
    units: placement.units,
    left: placement.left, top: placement.top,
    width: placement.width, height: placement.height,
    glyphs: placement.glyphs.map(glyph => ({
      glyph: glyph.glyph, x: glyph.x, y: glyph.y, color: glyph.color,
    })),
  }));

  // The painted rows, exactly as the painter must emit them. Text and
  // lattice HTML are both decided here; the paint step copies them into the
  // DOM and decides nothing.
  const lines = Array.from({ length: viewport[1] }, (_, row) => raster.line(row));
  const htmlLines = canMeasure
    ? Array.from({ length: viewport[1] }, () => '')
    : Array.from({ length: viewport[1] }, (_, row) =>
      raster.latticeHtml(row, cellWidth, false));

  // The background: the accepted sky-to-ground gradient, always. This
  // replaces the deleted hostname-conditioned branch -- there is one
  // background and it does not depend on where the page is served.
  // The coloured terrain begins at the far grass edge. The canonical fixture
  // surface is nearer the bottom and lives inside this band; using it as the
  // gradient boundary erased the depth between background and foreground.
  const groundPct = (terrain.farGroundY / viewport[1] * 100).toFixed(2);
  const background = {
    kind: 'gradient',
    bands: [
      { to_percent: Number(groundPct), color_role: 'sky', color: palette.sky },
      { to_percent: 100, color_role: 'ground', color: palette.dimGreen },
    ],
    css: `linear-gradient(to bottom,${palette.sky} ${groundPct}%,` +
      `${palette.dimGreen} ${groundPct}%)`,
    text_color: palette.text,
  };

  // The accessible label, decided at composition like everything else the
  // reader perceives.
  const sceneLabel = [projection.scene?.weather, projection.scene?.palette,
    projection.scene?.story_time, projection.scene?.ambience].filter(Boolean).join(' · ');
  const absence = (projection.scene?.absence_summary ?? []).slice(0, 3);
  const missed = (projection.scene?.missed_event_summaries ?? []).slice(0, 3);
  const memorial = projection.scene?.memorial?.active
    ? ` Memorial lasting; ${(projection.scene.memorial.examined_gifts ?? []).length} gifts remembered.`
    : '';
  const inventory = projection.scene?.inventory ?? [];
  const inventoryPreview = inventory.slice(0, 5);
  const inventoryRemainder = Math.max(0, inventory.length - inventoryPreview.length);
  const inventoryLabel = inventoryPreview.length
    ? `${inventoryPreview.join(', ')}${inventoryRemainder ? `; and ${inventoryRemainder} more` : ''}`
    : 'empty';
  const counts = Object.fromEntries(['plant', 'fixture', 'animal', 'collectible'].map(kind => [kind,
    projection.objects.filter(object => object.kind === kind).length]));
  const contents = [
    counts.plant ? `${counts.plant} plants` : '', counts.fixture ? `${counts.fixture} fixtures` : '',
    counts.animal ? `${counts.animal} relationship ${counts.animal === 1 ? 'animal' : 'animals'}` : '',
    counts.collectible ? `${counts.collectible} collectibles` : '',
  ].filter(Boolean).join(', ') || 'quiet ground';
  const ariaLabel = `${sky.label}. ${sceneLabel || `${season} ${mode}`}. Garden with ${contents}. ` +
    `Inventory: ${inventoryLabel}.` +
    `${absence.length ? ` Welcome back: ${absence.join(' ')}` : ''}` +
    `${missed.length ? ` While you were away: ${missed.join(' ')}` : ''}${memorial}`;

  return {
    attempted_primitives: attempted,
    visible_primitives: visible,
    background,
    interaction_regions: interactionRegions,
    diagnostics: {
      attempted: attempted.length,
      visible: visible.length,
      suppressed: attempted.filter(entry => entry.suppressed).length,
      authority_asserted: authority !== null,
      // The LOGICAL grapheme runs of measured assets (row strings, anchors,
      // accents), kept for inspection only. The paint payload is the
      // pixel-resolved `measured_asset_placements` above; a painter reading
      // these runs would be re-deciding placement, which the interface test
      // in tests/garden_adapters/test_presentation_contract.mjs forbids by
      // proving a frame paints with `diagnostics` never touched.
      measured_asset_runs: raster.measuredAssets,
    },
    // ---- painter payload and adapter-compat surface ----------------------
    // Everything below is decided data the paint step and the existing
    // consumers of `renderer.lastFrame` read. It is part of the frame, not a
    // side channel: the paint step copies `rows`; adapter consumers read the
    // named fields the class has always exposed.
    rows: {
      lines, html: htmlLines, line_height_px: cellHeight,
      paint_mode: canMeasure ? 'platform' : 'rows',
    },
    measured_asset_placements: measuredAssetPlacements,
    platform_glyphs: platformGlyphs,
    aria_label: ariaLabel,
    theme: { mode, palette },
    viewport, lines, sky, palette, season, timeOfDay: mode,
    horizon, profile, terrain, layout, depthCohorts, weatherReactions,
    motionPaused: motionSuppressed,
  };
}

/**
 * Copy a decided frame onto a surface.
 *
 * This function MAY NOT decide anything. If a change here can alter which
 * cells are visible, what colour anything is, where a region sits or what
 * the label says, the frame was incomplete and the defect is in
 * `composePresentationFrame`. Everything below is transport: DOM row
 * management, style assignment from frame data, and copying the
 * pixel-resolved measured placements into the overlay layer.
 *
 * The surface is GENERIC: any object carrying `element` (a DOM node),
 * `rows` (array) and `rowHtml` (array) can be painted -- it does not have to
 * be a `CanonicalGardenRenderer`, and no method of the surface is called.
 * The painter reads only the frame's paint payload; `diagnostics` (where the
 * logical grapheme runs live) is out of bounds, and the interface test
 * proves a frame paints with diagnostics never touched. The earlier version
 * called back into `surface._renderMeasuredAssets`, which re-measured the
 * assets with the renderer's private geometry at paint time -- placement
 * decided after composition, on knowledge only the renderer had. That
 * method is gone; placement arrives inside the frame.
 *
 * @param {object} frame - the composed PresentationFrame
 * @param {object} surface - `{element, rows, rowHtml}` plus the painter-owned
 *   `measuredLayer` and `measuredAssetRects` it maintains across paints
 */
export function paintPresentationFrame(frame, surface) {
  const element = surface.element;
  if (element.style) {
    element.style.background = frame.background.css;
    element.style.color = frame.background.text_color;
  }
  const lines = frame.rows.lines;
  const htmlLines = frame.rows.html;
  const platformMode = frame.rows.paint_mode === 'platform';
  while (surface.rows.length < lines.length) {
    const row = document.createElement('div');
    row.className = 'garden-lattice-row';
    row.setAttribute('aria-hidden', 'true');
    element.appendChild(row); surface.rows.push(row);
  }
  while (surface.rows.length > lines.length) surface.rows.pop().remove();
  surface.rowHtml.length = lines.length;
  const changedRows = [];
  lines.forEach((line, index) => {
    // Row extent is part of the composed lattice. Leaving CSS's historical
    // 17px height in charge while geometry measured a 15px line box overflowed
    // 59 rows by 118px and clipped every object's feet off the viewport.
    if (surface.rows[index].style) {
      surface.rows[index].style.height = `${frame.rows.line_height_px}px`;
      surface.rows[index].style.lineHeight = `${frame.rows.line_height_px}px`;
    }
    const html = htmlLines[index];
    const paintedLine = platformMode ? '' : line;
    if (surface.rows[index].textContent !== paintedLine || surface.rowHtml[index] !== html) {
      surface.rows[index].textContent = paintedLine;
      if (Object.hasOwn(surface.rows[index], 'innerHTML') ||
        (typeof globalThis.HTMLElement !== 'undefined' &&
          surface.rows[index] instanceof globalThis.HTMLElement)) {
        surface.rows[index].innerHTML = html;
      }
      surface.rowHtml[index] = html;
      changedRows.push(index);
    }
  });
  // ---- measured overlay: finished pixels in, spans out -------------------
  // Every number here was decided at composition. The rects map is kept for
  // the adapter's `objectArtRectPixels`, which reports where a drawing IS --
  // a fact of the frame, recorded as it is painted.
  const placements = frame.measured_asset_placements;
  const platformGlyphs = platformMode ? frame.platform_glyphs : null;
  surface.measuredAssetRects = new Map();
  if (!placements.length && !platformGlyphs?.length) {
    if (surface.measuredLayer) surface.measuredLayer.innerHTML = '';
  } else {
    if (!surface.measuredLayer) {
      surface.measuredLayer = document.createElement('div');
      surface.measuredLayer.className = 'garden-measured-layer';
      surface.measuredLayer.setAttribute('aria-hidden', 'true');
      element.appendChild(surface.measuredLayer);
    } else if (surface.measuredLayer.parentNode === element) {
      // Keep the overlay after the lattice rows when a resize adds rows.
      element.appendChild(surface.measuredLayer);
    }
    for (const placement of placements) {
      surface.measuredAssetRects.set(placement.object_id, {
        x: placement.left, y: placement.top,
        width: placement.width, height: placement.height,
      });
    }
    const glyphs = platformGlyphs ?? placements.flatMap(placement => placement.glyphs);
    const spans = glyphs.map(glyph =>
      `<span style="left:${glyph.x.toFixed(2)}px;top:${glyph.y.toFixed(2)}px` +
        (glyph.color ? `;color:${glyph.color}` : '') +
        `">${escapeHtml(glyph.glyph)}</span>`);
    surface.measuredLayer.innerHTML = spans.join('');
  }
  element.setAttribute('aria-label', frame.aria_label);
  return changedRows;
}
