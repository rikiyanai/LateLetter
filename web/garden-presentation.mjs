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
 * `drawObject`, ...) remain in `web/garden-renderer.mjs` as module-level pure
 * functions -- they were extracted from the class in the preceding patch.
 * This module is their only orchestrator: it decides what is drawn, in what
 * order, under which authority, and what the resulting frame IS. The
 * renderer's class keeps measurement, event capture and the paint step, and
 * calls back into this module for everything visual. The import cycle this
 * creates (renderer -> presentation for the interface, presentation ->
 * renderer for the painters) is call-time only -- no module reads the other
 * during evaluation -- and it is the honest shape of the split: laws and
 * painters live beside the surface, decisions live here.
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
import {
  Raster,
  drawSky, drawSkyLife, drawGround, drawAmbient, drawPlantBeds,
  drawWeather, drawObject,
  gardenPresentationProfile, layoutGardenObjects, gardenDepthCohorts,
  timeOfDay, seasonOf, DAY, NIGHT, EVENING, paletteColor,
  objectBurstPattern, connectedMasks, objectPresentationArt,
  measuredAssetPlacement,
} from './garden-renderer.mjs';

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

/**
 * Advance the disposable presentation state.
 *
 * This is the only door through which pointer movement, pointer leave, click
 * feedback and focus changes enter the presentation layer. The state it
 * returns is disposable and unpersisted, but not derivable from the
 * projection alone: hover depends on where the pointer is, bursts depend on
 * prior clicks. Everything here used to be instance fields on the renderer
 * (`this.hoverCell`, `this.clickBursts`, `this.focusedObjectId`) mutated
 * from event handlers; making the advance explicit is what lets the composer
 * stay a pure function while the picture still responds.
 *
 * @param {object|null} previousState - the prior state, or null for the first frame
 * @param {Array<object>} presentationEvents - events gathered since the last advance:
 *   `{kind:'pointer-move', cell:[x,y]}`, `{kind:'pointer-leave'}`,
 *   `{kind:'focus-change', objectId}`, and
 *   `{kind:'burst', x, y, kind_, species, catalog, objectId}` for click feedback
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

  for (const event of presentationEvents ?? []) {
    if (event.kind === 'pointer-move') hoverCell = event.cell;
    else if (event.kind === 'pointer-leave') hoverCell = null;
    else if (event.kind === 'focus-change') focusedObjectId = event.objectId ?? null;
    else if (event.kind === 'burst') {
      clickBursts.push({
        x: event.x, y: event.y, frame,
        kind: event.objectKind, species: event.species,
        catalog: event.catalog, objectId: event.objectId,
      });
    }
  }
  return { visualFrame: frame, hoverCell, focusedObjectId, clickBursts };
}

/**
 * The set of ids the given manifest allows to paint, or null for "no
 * authority asserted".
 *
 * Null is a legitimate diagnostic state -- a Node adapter test or an
 * authoring tool composing without a manifest -- and it composes everything
 * WITH its identity, so nothing about provenance is lost by inspecting
 * without authority. What null never is: the release path. The viewer always
 * passes the build-derived manifest, so the product suppresses unaccepted
 * ink on every host equally.
 *
 * @param {object|null} manifest - the accepted-paint manifest, or null
 * @returns {Set<string>|null}
 */
function permittedSources(manifest) {
  if (!manifest) return null;
  return new Set([
    ...(manifest.accepted_assets ?? []),
    ...(manifest.accepted_recipes ?? []),
    ...(manifest.accepted_legacy_art ?? []),
  ]);
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
  const environment = context.environment ?? {};
  const authority = permittedSources(context.acceptedManifest ?? null);

  const raster = new Raster(viewport[0], viewport[1], { authority });
  connectedMasks(projection.objects);
  const sky = resolveBrowserSky({
    scene: projection.scene, readerRegion: environment.readerRegion ?? null,
  });
  const mode = timeOfDay(projection);
  const season = seasonOf(projection);
  const palette = mode === 'night' ? NIGHT : mode === 'evening' ? EVENING : DAY;
  const profile = gardenPresentationProfile(viewport);
  const horizon = profile.horizon;
  const layout = layoutGardenObjects(projection, viewport, state.visualFrame);
  const depthCohorts = gardenDepthCohorts(layout, profile);

  drawSky(raster, projection, sky, palette, profile, mode);
  // Sky life is drawn straight after the stars so that ground, planting and
  // objects all paint over it: clouds and distant birds are the backdrop.
  drawSkyLife(raster, projection, palette, season, profile, mode);
  drawGround(raster, palette, season, profile);
  drawAmbient(raster, projection, palette, season, horizon, profile);
  // Far, middle and near are painter's cohorts derived from the canonical
  // ground rows. Plant beds are interleaved with their own cohort so the
  // foreground can overlap the middle distance without moving any object.
  const view = {
    visualFrame: state.visualFrame,
    hoverCell: state.hoverCell,
    focusedObjectId: state.focusedObjectId,
  };
  for (const entries of [depthCohorts.far, depthCohorts.middle, depthCohorts.near]) {
    drawPlantBeds(raster, projection, entries, palette, season, profile);
    entries.forEach(entry => drawObject(raster, entry, projection, palette, season, view));
  }
  const weatherReactions = drawWeather(
    raster, projection, palette, season, horizon, layout, state.visualFrame,
  );
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

  // The painted rows, exactly as the painter must emit them. Text and
  // lattice HTML are both decided here; the paint step copies them into the
  // DOM and decides nothing.
  const lines = Array.from({ length: viewport[1] }, (_, row) => raster.line(row));
  const htmlLines = Array.from({ length: viewport[1] }, (_, row) =>
    raster.latticeHtml(row, cellWidth, !geometry.affineOnly));

  // The background: the accepted sky-to-ground gradient, always. This
  // replaces the deleted hostname-conditioned branch -- there is one
  // background and it does not depend on where the page is served.
  const groundPct = (profile.groundBack / viewport[1] * 100).toFixed(2);
  const nearPct = ((horizon + 1) / viewport[1] * 100).toFixed(2);
  const background = {
    kind: 'gradient',
    bands: [
      { to_percent: Number(groundPct), color_role: 'sky', color: palette.sky },
      { to_percent: Number(nearPct), color_role: 'soil', color: palette.soil },
      { to_percent: 100, color_role: 'ground', color: palette.ground },
    ],
    css: `linear-gradient(to bottom,${palette.sky} 0%,${palette.sky} ${groundPct}%,` +
      `${palette.ground} ${groundPct}%,${palette.soil} ${nearPct}%,${palette.ground} 100%)`,
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
    },
    // ---- painter payload and adapter-compat surface ----------------------
    // Everything below is decided data the paint step and the existing
    // consumers of `renderer.lastFrame` read. It is part of the frame, not a
    // side channel: the paint step copies `rows`; adapter consumers read the
    // named fields the class has always exposed.
    rows: { lines, html: htmlLines },
    measured_assets: raster.measuredAssets,
    aria_label: ariaLabel,
    theme: { mode, palette },
    viewport, lines, sky, palette, season, timeOfDay: mode,
    horizon, profile, layout, depthCohorts, weatherReactions,
    motionPaused: motionSuppressed,
  };
}

/**
 * Copy a decided frame onto a renderer surface.
 *
 * This function MAY NOT decide anything. If a change here can alter which
 * cells are visible, what colour anything is, where a region sits or what
 * the label says, the frame was incomplete and the defect is in
 * `composePresentationFrame`. Everything below is transport: DOM row
 * management, style assignment from frame data, and the measured-asset
 * pixel layer.
 *
 * @param {object} frame - the composed PresentationFrame
 * @param {object} surface - the `CanonicalGardenRenderer` instance acting as
 *   the DOM adapter; it owns `element`, `rows`, `rowHtml` and the measured
 *   layer machinery
 */
export function paintPresentationFrame(frame, surface) {
  const element = surface.element;
  if (element.style) {
    element.style.background = frame.background.css;
    element.style.color = frame.background.text_color;
  }
  const lines = frame.rows.lines;
  const htmlLines = frame.rows.html;
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
    const html = htmlLines[index];
    if (surface.rows[index].textContent !== line || surface.rowHtml[index] !== html) {
      surface.rows[index].textContent = line;
      if (Object.hasOwn(surface.rows[index], 'innerHTML') ||
        (typeof globalThis.HTMLElement !== 'undefined' &&
          surface.rows[index] instanceof globalThis.HTMLElement)) {
        surface.rows[index].innerHTML = html;
      }
      surface.rowHtml[index] = html;
      changedRows.push(index);
    }
  });
  surface._renderMeasuredAssets(frame.measured_assets);
  element.setAttribute('aria-label', frame.aria_label);
  return changedRows;
}
