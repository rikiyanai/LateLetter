/**
 * The browser surface: `CanonicalGardenRenderer`, the DOM adapter.
 * ----------------------------------------------------------------
 *
 * This module is an ADAPTER, not an owner. The painters and art tables live
 * in `web/garden-painting.mjs`; what is composed is decided by
 * `web/garden-presentation.mjs`; this class contributes measurements
 * (Contract-P cell geometry), captures input events, and hands the composed
 * frame to `paintPresentationFrame`, which copies it onto the generic
 * surface fields (`element`, `rows`, `rowHtml`, `measuredLayer`,
 * `measuredAssetRects`). No method of this class participates in painting:
 * the paint-time `_renderMeasuredAssets`, which re-derived measured pixel
 * placement from renderer-private geometry AFTER composition, was removed by
 * the reopened frame-ownership transfer -- placement now arrives inside the
 * frame, resolved at composition.
 *
 * The import cycle that used to run renderer -> presentation -> renderer is
 * gone (reopened step 4): presentation imports the painting layer directly,
 * and this module imports both. The `export *` below preserves the module
 * surface importers have always used -- `Raster`, the painters and the
 * layout helpers still resolve from './garden-renderer.mjs'.
 */

import {
  advancePresentationState, composePresentationFrame, paintPresentationFrame,
} from './garden-presentation.mjs';
import { isValidPaintAuthority } from './garden-paint-authority.mjs';
// Presentation geometry: the affine world-to-pixel transform, the accessible
// target floor, and the containment rule. This module used to carry its own
// copies of all three. They agreed at the time and would not have stayed
// agreeing -- an off-by-one in one containment test and not the other is the
// kind of divergence that only shows up as an occasional unselectable object.
import { createGeometry } from './garden-geometry.mjs';
import { compareCodePoints } from './garden-world.mjs';
import { DAY, hitRectToHotspot } from './garden-painting.mjs';

export * from './garden-painting.mjs';

export class CanonicalGardenRenderer {
  constructor(element, {
    onSelect = null, onTheme = null, prefersReducedMotion = false, readerRegion = null,
    measurer = null, font = null,
    // The build-derived accepted-paint manifest (web/garden-accepted-paint.
    // v1.json in the product; the release artifact embeds the same lists in
    // garden-release-manifest.json). REQUIRED. An earlier version defaulted
    // this to null as a "diagnostic mode" that painted everything -- the
    // fail-open seam the 2026-08-04 architecture review rejected: a viewer
    // constructed before its manifest fetch resolved, or after it failed,
    // painted unaccepted ink permanently. The constructor now refuses
    // instead; diagnosing unaccepted ink is done one level down, with a
    // bare Raster and the painters. This replaces `allowUnacceptedArt`,
    // which was a boolean the viewer minted from the hostname: authority is
    // data bound to the registers, identical on every host, and never
    // optional.
    paintAuthority,
  } = {}) {
    // One validator owns the manifest's shape (web/garden-paint-authority.
    // mjs, mirroring the generator); this adds only the construction-time
    // framing so the error names the fix.
    if (!isValidPaintAuthority(paintAuthority)) {
      throw new Error('CanonicalGardenRenderer requires paintAuthority: the ' +
        'accepted-paint manifest must be loaded BEFORE the renderer is ' +
        'constructed, and a missing or invalid manifest refuses garden ' +
        'painting entirely.');
    }
    this.element = element; this.onSelect = onSelect; this.onTheme = onTheme;
    this.measurer = measurer; this.font = font;
    this.paintAuthority = paintAuthority;
    this.prefersReducedMotion = Boolean(prefersReducedMotion); this.readerRegion = readerRegion;
    this.projection = null; this.rows = []; this.rowHtml = [];
    this.measuredLayer = null; this.measuredAssetRects = new Map();
    this.cellWidth = 8; this.cellHeight = 15; this.cellGeometryMeasured = false;
    // Built immediately from the default lattice so `this.geometry` is never
    // absent. A pointer event can arrive before any layout has been measured --
    // a click during the first frame -- and an undefined transform would fail
    // there rather than simply resolving against the default cell size.
    this.geometry = null; this.setCellGeometry(this.cellWidth, this.cellHeight);
    this.cellGeometryMeasured = false;
    this.lastFrame = null; this.visualFrame = 0; this.hoverCell = null;
    // Input events gathered between frames, consumed by the state advance at
    // the top of render(). The renderer never interprets them itself.
    this.pendingEvents = []; this.presentationState = null;
    this.presentationTimer = null; this.presentationLast = 0;
    this.presentationWanted = false; this.presentationActive = false; this.themeMode = null;
    this.focusedObjectId = null;
    this.element.setAttribute('role', 'img');
    this.element.addEventListener('click', event => { this._burstAt(event); this._selectAt(event); });
    this.element.addEventListener('mousemove', event => this._hoverAt(event));
    this.element.addEventListener('mouseleave', () => {
      this.hoverCell = null;
      this.pendingEvents.push({ kind: 'pointer-leave' });
      if (this.element.style) this.element.style.cursor = 'default';
      if (this.projection && !this.prefersReducedMotion) this.render(this.projection);
    });
  }

  setCellGeometry(width, height) {
    if (Number.isFinite(width) && width > 0) this.cellWidth = width;
    if (Number.isFinite(height) && height > 0) this.cellHeight = height;
    this.cellGeometryMeasured = true;
    // The transform is rebuilt rather than mutated, because a geometry is
    // immutable per (font, scale) by design: its caches and lattice constants
    // are only valid under the assumptions it was constructed with, so a
    // changed cell size means a new object, never an edited one.
    //
    // Affine-only: hit identity comes from canonical hotspot rectangles, which
    // are integers converted by units alone. No text is measured to decide what
    // was clicked, and passing a measurer here would imply otherwise.
    this.geometry = createGeometry({
      ...(this.measurer && this.font ? { measurer: this.measurer, font: this.font } : {}),
      cellAdvance: this.cellWidth,
      lineHeight: this.cellHeight,
      // Pointer positions arrive relative to the canvas element's own top-left
      // corner (see `_eventPixel`), so world (0, 0) is that corner.
      originX: 0,
      originY: 0,
    });
    return [this.cellWidth, this.cellHeight];
  }
  refreshCellGeometry() {
    // Both early exits go through `setCellGeometry` with the values already
    // held, rather than only flipping the measured flag. Without that, a
    // headless or non-layout host would mark itself measured while leaving the
    // transform unbuilt, and the very first pointer event would fail on an
    // absent geometry. One construction site, always reached.
    if (!globalThis.document?.createElement || !this.element?.appendChild || typeof globalThis.getComputedStyle !== 'function') {
      return this.setCellGeometry(this.cellWidth, this.cellHeight);
    }
    const probe = document.createElement('span');
    if (!probe.style || typeof probe.getBoundingClientRect !== 'function') {
      return this.setCellGeometry(this.cellWidth, this.cellHeight);
    }
    probe.textContent = '0000000000';
    probe.style.cssText = 'position:absolute;visibility:hidden;white-space:pre;font:inherit;line-height:inherit;padding:0;margin:0;border:0;';
    this.element.appendChild(probe);
    const rect = probe.getBoundingClientRect(), style = getComputedStyle(this.element);
    const lineHeight = Number.parseFloat(style.lineHeight); probe.remove();

    const resolvedLineHeight = Number.isFinite(lineHeight) ? lineHeight : rect.height;
    if (this.measurer && this.font) {
      // Contract P: the world lattice comes from the fixed reference probe;
      // object-local rows use this same geometry's cumulative prefix widths.
      // No glyph repertoire or asset content participates in the lattice.
      this.geometry = createGeometry({
        measurer: this.measurer, font: this.font,
        lineHeight: resolvedLineHeight, originX: 0, originY: 0,
      });
      this.cellWidth = this.geometry.cellAdvance;
      this.cellHeight = this.geometry.lineHeight;
      this.cellGeometryMeasured = true;
      return [this.cellWidth, this.cellHeight];
    }

    // Explicit degraded/headless boundary. No measurement capability means the
    // browser cannot claim Contract P; the whole Garden uses the probe lattice.
    return this.setCellGeometry(rect.width / 10, resolvedLineHeight);
  }

  measure() {
    if (!this.cellGeometryMeasured) this.refreshCellGeometry();
    return [Math.max(20, Math.floor(this.element.clientWidth / this.cellWidth)), Math.max(10, Math.floor(this.element.clientHeight / this.cellHeight))];
  }


  render(projection) {
    if (!projection) return null;
    this.projection = projection;
    if (projection.motion_paused || this.prefersReducedMotion) this._cancelPresentationFrame();
    const viewport = this.measure();

    // ---- advance: gathered input events become presentation state. -------
    // Events accumulated since the previous frame (pointer moves and leaves,
    // click feedback, focus changes) are consumed exactly once, and the
    // adapter contributes one scene-facts event so the LIFECYCLE (birds,
    // weather particles, snow depth -- reopened step 5) can age by elapsed
    // ticks. The composer never sees an event, only the state the advance
    // derived from it, which is what keeps composition a pure function of
    // its three inputs.
    this.presentationState = advancePresentationState(
      this.presentationState,
      [...this.pendingEvents.splice(0, this.pendingEvents.length),
        { kind: 'scene', projection, viewport }],
      { frame: this.visualFrame },
    );

    // ---- compose: the picture is decided, entirely outside this class. ---
    // This class contributes measurements and environment facts; it makes no
    // choice about cells, colours, order, regions or labels. Paint authority
    // is the build-derived accepted manifest the caller handed the
    // constructor -- not the hostname, which is no longer consulted anywhere.
    const frame = composePresentationFrame(projection, this.presentationState, {
      viewport,
      profile: 'browser-proportional',
      // The geometry OBJECT, not a summary of it. Composition resolves the
      // measured pixel placement of every atlas asset itself (reopened step
      // 2), so it needs the same measurement capability the hit path uses --
      // `measureAsset`, `worldToPixel`, `offsetOfGrapheme` -- not merely the
      // cell numbers. The paint step receives finished pixels and measures
      // nothing.
      presentationGeometry: this.geometry,
      acceptedManifest: this.paintAuthority,
      environment: {
        readerRegion: this.readerRegion,
        reducedMotion: this.prefersReducedMotion,
      },
    });

    if (frame.theme.mode !== this.themeMode) {
      this.themeMode = frame.theme.mode;
      this.onTheme?.({ mode: frame.theme.mode, palette: { ...frame.theme.palette } });
    }

    // ---- paint: the decided frame is copied to the DOM. ------------------
    frame.changedRows = paintPresentationFrame(frame, this);
    this.lastFrame = frame;
    this._ensurePresentationLoop();
    return this.lastFrame;
  }

  _cancelPresentationFrame() {
    if (this.presentationTimer && typeof globalThis.cancelAnimationFrame === 'function')
      cancelAnimationFrame(this.presentationTimer);
    this.presentationTimer = null;
  }
  _ensurePresentationLoop() {
    if (this.presentationTimer || !this.presentationWanted || !this.presentationActive ||
      !this.projection || this.projection.motion_paused || this.prefersReducedMotion ||
      typeof globalThis.requestAnimationFrame !== 'function') return;
    const tick = now => {
      this.presentationTimer = null;
      if (!this.presentationWanted || !this.presentationActive || !this.projection ||
        this.projection.motion_paused || this.prefersReducedMotion) return;
      // The 50ms floor is the ACCEPTED cadence law (recipe.motion.
      // frame_cadence): requestAnimationFrame with an explicit 50ms floor,
      // ~20 ticks a second regardless of display refresh. Every archived
      // animation constant -- the 0.42-cell bird step, the 250-600 tick
      // respawn interval, the sway cadences -- is calibrated against this
      // tick, so the earlier 100ms floor silently halved every speed the
      // operator accepted. Changing this number changes every motion in the
      // Garden; it moves only with that register record.
      if (now - this.presentationLast >= 50) {
        this.presentationLast = now; this.visualFrame += 1; this.render(this.projection);
      }
      this._ensurePresentationLoop();
    };
    this.presentationTimer = requestAnimationFrame(tick);
  }
  startPresentation() {
    this.presentationWanted = true;
    this._ensurePresentationLoop();
  }
  stopPresentation() {
    this.presentationWanted = false;
    this._cancelPresentationFrame();
  }
  setPresentationActive(value) {
    this.presentationActive = Boolean(value);
    if (this.presentationActive) this._ensurePresentationLoop();
    else this._cancelPresentationFrame();
  }
  clear() {
    this._cancelPresentationFrame();
    this.projection = null; this.lastFrame = null; this.rows = []; this.rowHtml = [];
    this.pendingEvents = []; this.presentationState = null;
    this.measuredLayer = null; this.measuredAssetRects = new Map();
    this.focusedObjectId = null;
    this.themeMode = 'day'; this.onTheme?.({ mode: 'day', palette: { ...DAY } });
    this.element.replaceChildren(); this.element.setAttribute('aria-label', 'Generic Garden preview.');
  }
  _eventCell(event) {
    if (!this.cellGeometryMeasured) this.refreshCellGeometry();
    const rect = this.element.getBoundingClientRect(), { cellWidth, cellHeight } = this;
    return [Math.floor((event.clientX - rect.left) / cellWidth), Math.floor((event.clientY - rect.top) / cellHeight)];
  }
  /**
   * The pointer position in CSS pixels, relative to the canvas element.
   *
   * Hit identity is decided in pixel space, not cell space. A cell index is a
   * lossy summary of where a pointer actually was, and rounding to it before
   * testing containment discards the sub-cell precision that proportional
   * presentation exists to provide. `_eventCell` survives only for the paint
   * effects below, which genuinely want a cell.
   */
  _eventPixel(event) {
    if (!this.cellGeometryMeasured) this.refreshCellGeometry();
    const rect = this.element.getBoundingClientRect();
    return [Number(event.clientX) - rect.left, Number(event.clientY) - rect.top];
  }
  /**
   * An entry's canonical hotspot, converted from cells into pixels.
   *
   * The conversion is `garden-geometry.mjs`'s, not this module's. That matters
   * beyond tidiness: the accessible 44px floor, the centred expansion, and the
   * half-open containment rule are one implementation used by both the hit path
   * and anything else that positions world coordinates, so they cannot drift
   * into disagreeing about an edge.
   */
  _hitRectPixels(entry) {
    if (!this.cellGeometryMeasured) this.refreshCellGeometry();
    return this.geometry.hotspotToRect(hitRectToHotspot(entry.hitRect));
  }
  _layoutCandidatesAt(pixel) {
    const geometry = this.geometry;
    return [...(this.lastFrame?.layout ?? [])].filter(entry =>
      geometry.containsPoint(
        geometry.expandTarget(this._hitRectPixels(entry)), pixel[0], pixel[1],
      ));
  }
  /**
   * Order the objects under a pointer, most-selected first.
   *
   * Hit identity comes from the projection's canonical hotspot rectangles and
   * from nothing else. Painted artwork is deliberately not consulted: art is
   * allowed to overhang its declared footprint, so if visible ink decided what
   * was clicked, redrawing a picture would silently change the garden's
   * affordances.
   *
   * Ordering, and the reason for each step:
   *
   *   1. An object whose UNEXPANDED hotspot contains the pointer outranks every
   *      merely-nearby one. Accessibility expansion must never take a click
   *      from an object the player actually touched.
   *   2. Then nearest centre, which is the least surprising rule when several
   *      forgiving targets overlap.
   *   3. Then depth, so a foreground object wins over one behind it.
   *   4. Then object id by code point, so the result is identical on every
   *      machine. Determinism matters more here than which object wins: the
   *      same tap on the same scene has to do the same thing every time.
   */
  _rankedLayoutCandidatesAt(pixel) {
    const geometry = this.geometry;
    return this._layoutCandidatesAt(pixel).map(entry => {
      const rect = this._hitRectPixels(entry);
      return {
        entry,
        exact: geometry.containsPoint(rect, pixel[0], pixel[1]),
        distance: Math.hypot(
          pixel[0] - (rect.x + rect.width / 2),
          pixel[1] - (rect.y + rect.height / 2),
        ),
      };
    }).sort((left, right) =>
      Number(right.exact) - Number(left.exact) ||
      left.distance - right.distance ||
      Number(right.entry.object.depth ?? 100) - Number(left.entry.object.depth ?? 100) ||
      compareCodePoints(left.entry.object.object_id, right.entry.object.object_id),
    ).map(candidate => candidate.entry);
  }
  /**
   * Where an object currently sits on screen, in pixels relative to the grid.
   *
   * Exposed so a caller can position a control BESIDE an object -- the spawned
   * opportunity of SPEC 7.8.3.2 -- without re-deriving cell geometry and
   * risking a control that drifts away from the thing it belongs to. It
   * returns the same accessibility-expanded rectangle the hit test uses, so
   * "where it looks" and "where it is clickable" cannot disagree.
   *
   * @param objectId Canonical object id from the projection.
   * @returns `{x, y, width, height}` in CSS pixels, or `null` when the object
   *   is not in the last painted frame (off-camera, or nothing painted yet).
   */
  objectRectPixels(objectId) {
    const entry = (this.lastFrame?.layout ?? []).find(
      item => item.object.object_id === String(objectId),
    );
    return entry ? this._hitRectPixels(entry) : null;
  }
  /**
   * Where an object's DRAWING is, in pixels.
   *
   * Distinct from `objectRectPixels`, which reports the canonical HOTSPOT --
   * the thing that decides what a click selects. The two differ a lot: a
   * lantern's hotspot is one world cell, about eight pixels wide, while its
   * picture is a post and a lamp head some four times that.
   *
   * A caller placing a control "beside the lantern" needs this one. Using the
   * hotspot put the beside-object control on top of the lantern's own post, and
   * made a neighbouring fixture look clear when the control was in fact sitting
   * across its drawing -- occlusion is a fact about ink, and the hotspot does
   * not know where the ink is.
   *
   * Hit testing deliberately keeps using the hotspot: art may overhang its
   * declared footprint, and if visible ink decided what was clickable, redrawing
   * a picture would silently change the Garden's affordances.
   *
   * @param objectId Canonical object id.
   * @returns `{x, y, width, height}` in CSS pixels, or null when the object is
   *   not in the last painted frame.
   */
  objectArtRectPixels(objectId) {
    const entry = (this.lastFrame?.layout ?? []).find(
      item => item.object.object_id === String(objectId),
    );
    if (!entry) return null;
    if (!this.cellGeometryMeasured) this.refreshCellGeometry();
    const measured = this.measuredAssetRects.get(String(objectId));
    if (measured) return { ...measured };
    return this.geometry.hotspotToRect(hitRectToHotspot(entry.rect));
  }
  _hoverAt(event) {
    // Approved picture-owned hover: the hover cell drives rustle/emphasis and
    // the cursor follows the same pixel hit test that selection uses. Hover
    // does not call back into the viewer: the removed callback existed only to
    // build the rejected textual invitation/card surface.
    this.hoverCell = this._eventCell(event);
    this.pendingEvents.push({ kind: 'pointer-move', cell: this.hoverCell });
    const candidates = this._layoutCandidatesAt(this._eventPixel(event));
    if (this.element.style) this.element.style.cursor = candidates.length ? 'pointer' : 'default';
    if (this.projection && !this.prefersReducedMotion) this.render(this.projection);
  }
  _burstAt(event) {
    if (!this.projection || this.projection.motion_paused || this.prefersReducedMotion) return;
    // The burst is painted at a cell; the object it reports is chosen in pixels.
    const [x, y] = this._eventCell(event);
    const selected = this._rankedLayoutCandidatesAt(this._eventPixel(event))[0]?.object ?? null;
    this.pendingEvents.push({ kind: 'burst', x, y,
      objectKind: selected?.kind,
      species: selected?.semantic_state?.species_id,
      catalog: selected?.semantic_state?.catalog_id,
      objectId: selected?.object_id });
  }
  _selectAt(event) {
    if (!this.projection || !this.onSelect) return;
    const candidates = this._rankedLayoutCandidatesAt(this._eventPixel(event));
    if (candidates[0]) this.onSelect(candidates[0].object, event);
  }
  onResize() {
    this.measurer?.clearCaches?.();
    this.cellGeometryMeasured = false;
    if (this.projection) this.render(this.projection);
  }
  setFocusedObject(objectId) {
    this.focusedObjectId = objectId ? String(objectId) : null;
    this.pendingEvents.push({ kind: 'focus-change', objectId: this.focusedObjectId });
  }
  setReaderRegion(region) { this.readerRegion = region; if (this.projection) this.render(this.projection); }
  setReducedMotion(value) {
    const next = Boolean(value); if (next === this.prefersReducedMotion) return;
    this.prefersReducedMotion = next;
    if (next) this._cancelPresentationFrame();
    if (this.projection) this.render(this.projection);
  }
  start(runtime = null, options = {}) {
    this.startPresentation();
    if (runtime?.startLive) runtime.startLive({ ...options, prefersReducedMotion: this.prefersReducedMotion, onProjection: projection => this.render(projection) });
  }
  stop(runtime = null) { this.stopPresentation(); if (runtime?.stopLive) runtime.stopLive(); }
  triggerAnimalFeedReaction(data = {}) {
    if (!this.projection || this.projection.motion_paused || this.prefersReducedMotion) return;
    const objectId = String(data.objectId ?? '');
    if (!objectId) return;
    const animal = this.projection?.objects.find(object =>
      object.kind === 'animal' && object.object_id === objectId);
    if (!animal || !this.lastFrame) return;
    const entry = this.lastFrame.layout.find(item => item.object.object_id === animal.object_id);
    if (!entry) return;
    const [x, y] = entry.anchor;
    this.pendingEvents.push({ kind: 'burst', x, y, objectKind: 'animal',
      species: animal.semantic_state?.species_id, objectId: animal.object_id });
  }
  animalDebugState() { return 'canonical-rich-projection'; }
}
