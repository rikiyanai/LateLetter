/**
 * A GardenPresentation implementation that satisfies SPEC 7.2.2, and runs.
 * ------------------------------------------------------------------------
 *
 * WHY THIS EXISTS
 *
 * A conformance check that has only ever REFUSED things proves nothing about
 * whether it can be satisfied at all. An earlier round of this work learned
 * that the hard way: its "satisfiable" positive control was a string of
 * JavaScript that could not execute, and it was the sole evidence that the
 * gate was reachable. So this one is a module: it is imported and executed,
 * it advances real state and composes a real frame, and the contract is
 * applied to its output. If the contract ever becomes unsatisfiable, this
 * file stops conforming and says so.
 *
 * WHAT IT IS NOT
 *
 * It is not the Garden and it is not a proposal for the Garden's art. It
 * draws the smallest picture that exercises every clause: recipe-chain
 * ground, atlas-chain object ink carrying an object id, an interaction
 * region transformed from an atlas mask and bound to a projected object, an
 * occluded primitive that stays in the attempted list, and presentation-only
 * state (hover and snow depth) that accumulates through the public advance.
 */

/** Ids the reference picture paints from, matching the fixture manifest below. */
export const REFERENCE_IDS = Object.freeze({
  groundRecipe: 'recipe.reference.ground',
  snowRecipe: 'recipe.reference.snow',
  densityLaw: 'law.reference.density',
  plantAsset: 'asset.reference.plant',
});

/**
 * The accepted-paint manifest the reference implementation is given.
 *
 * The SHAPE is the real one -- the build-generated release manifest of
 * `scripts/prepare_pages_site.py`: `accepted_assets`, `accepted_recipes`
 * (paint recipes only) and `accepted_laws` (accepted, but never paintable).
 * In the product these lists are compiled at build time from the two verdict
 * registers; here they are literals, because the contract's job is to check
 * a composer against whatever manifest it was handed, not to read files.
 */
export const REFERENCE_MANIFEST = Object.freeze({
  accepted_assets: [REFERENCE_IDS.plantAsset],
  accepted_recipes: [REFERENCE_IDS.groundRecipe, REFERENCE_IDS.snowRecipe],
  accepted_laws: [REFERENCE_IDS.densityLaw],
});

/**
 * A projection holding one interactive object, in the shape
 * `projectGardenScene` produces: an `object_id`, a `hotspot` in cells, and a
 * `primary_action` that is non-null exactly when the object is interactive.
 * `asset_id`/`state_id` are the atlas selection the projection owns; the
 * composer binds each interaction region to them, which is how "the region
 * came from the atlas mask" stays checkable on the frame.
 */
export const REFERENCE_PROJECTION = Object.freeze({
  objects: [
    {
      object_id: 'plant-1',
      kind: 'plant',
      asset_id: 'asset.reference.plant',
      state_id: 'state.default',
      position: [4, 2],
      hotspot: { x: 4, y: 2, width: 1, height: 2 },
      primary_action: { verb: 'water', target: 'plant-1' },
    },
    {
      // Present, projected, and deliberately NOT interactive: it must not get
      // a region, which is how the contract's "only declared-interactive
      // objects" half is exercised rather than assumed.
      object_id: 'stone-1',
      kind: 'fixture',
      asset_id: 'asset.reference.plant',
      state_id: 'state.default',
      position: [8, 3],
      hotspot: { x: 8, y: 3, width: 1, height: 1 },
      primary_action: null,
    },
  ],
});

/** A viewport of 12x5 cells, each 10x20 CSS pixels. */
export const REFERENCE_VIEWPORT = Object.freeze({
  cellsWide: 12,
  cellsHigh: 5,
  cellWidth: 10,
  cellHeight: 20,
});

/**
 * The full composition context of SPEC 7.2.2's input table.
 *
 * `presentationGeometry` carries the measurement facts a real composer needs
 * for Contract P; the reference picture is lattice-only, so its table is
 * trivial, but the FIELD is present because the contract's input shape is
 * part of what this fixture demonstrates to be satisfiable.
 */
export const REFERENCE_CONTEXT = Object.freeze({
  viewport: REFERENCE_VIEWPORT,
  profile: 'ascii-safe',
  presentationGeometry: Object.freeze({
    fontIdentity: 'reference-font-v1',
    cellAdvance: REFERENCE_VIEWPORT.cellWidth,
    lineHeight: REFERENCE_VIEWPORT.cellHeight,
  }),
  acceptedManifest: REFERENCE_MANIFEST,
  environment: Object.freeze({ reducedMotion: false, theme: 'day' }),
});

/**
 * Advance the disposable presentation state.
 *
 * The reference state holds the two kinds of thing SPEC names: an input echo
 * (hover cell, from pointer events) and an accumulation (snow depth, which
 * deepens by one band every 40 ticks up to a cap). Both live HERE and
 * nowhere else: the composer below keeps nothing of its own between calls.
 *
 * @param {object|null} previousState - prior state, or null for the first frame
 * @param {Array<object>} presentationEvents - pointer/focus/reduced-motion events
 * @param {{frame: number, seconds: number}} tick - presentation time
 * @returns {object} the next disposable state
 */
export function advanceReferenceState(previousState, presentationEvents, tick) {
  // Hover follows the last pointer event, and a pointer leave clears it.
  let hoverCell = previousState?.hoverCell ?? null;
  for (const event of presentationEvents ?? []) {
    if (event.kind === 'pointer-move') hoverCell = { x: event.cell.x, y: event.cell.y };
    if (event.kind === 'pointer-leave') hoverCell = null;
  }
  // Accumulation is a fold over the PREVIOUS state, not a function of the
  // clock: a composer that could only see the frame number would have to
  // recompute accumulation from the beginning of time, or fake it. Capped at
  // two bands so it can never bury the reference plant and make the
  // interaction checks vacuous.
  const previousDepth = previousState?.snowDepth ?? 0;
  const snowDepth = Math.min(
    previousDepth + ((tick?.frame ?? 0) % 4 === 0 ? 1 : 0), 2,
  );
  return { hoverCell, snowDepth };
}

/**
 * Compose one PresentationFrame from projection, state and context.
 *
 * Pure by construction: it reads its three parameters and nothing else -- no
 * clock, no randomness, no hostname, no module variable. Determinism is not
 * an aspiration here; there is simply nothing nondeterministic in scope.
 *
 * @param {object} projection - canonical projection, read-only
 * @param {object} state - what `advanceReferenceState` returned
 * @param {object} context - viewport, profile, geometry, manifest, environment
 * @returns {object} a PresentationFrame per SPEC 7.2.2
 */
export function composeReferenceFrame(projection, state, context) {
  const manifest = context.acceptedManifest ?? {};
  const viewport = context.viewport;
  const attempted = [];
  let order = 0;

  /**
   * Record one attempted primitive. Everything the painter could ever need
   * is decided HERE -- content, position, colour role, identity, order --
   * which is what makes the paint step a copy.
   */
  const attempt = (fields) => {
    const primitive = {
      units: 'cell',
      profile: context.profile,
      painter_order: order += 1,
      object_id: null,
      ...fields,
    };
    attempted.push(primitive);
    return primitive;
  };

  const ground = viewport.cellsHigh - 1;   // soil occupies the bottom row

  // --- recipe chain: the ground ------------------------------------------
  // Every ground primitive names the recipe that draws ground. None carries
  // an object id, because ground is not a drawing OF a gameplay object --
  // that is the whole distinction between the two identity chains.
  for (let x = 0; x < viewport.cellsWide; x += 1) {
    attempt({
      x, y: ground, glyph: '_', color_role: 'soil',
      source_id: manifest.accepted_recipes?.includes(REFERENCE_IDS.groundRecipe)
        ? REFERENCE_IDS.groundRecipe
        : null,
    });
  }

  // --- recipe chain: accumulated snow -------------------------------------
  // Painted FROM STATE: the depth the advance computed is the only thing
  // consulted, which is what "presentation-only state travels through the
  // public state advance" means in practice.
  for (let depth = 0; depth < (state?.snowDepth ?? 0); depth += 1) {
    for (let x = 0; x < viewport.cellsWide; x += 2) {
      attempt({
        x, y: ground - 1 - depth, glyph: '.', color_role: 'snow',
        source_id: REFERENCE_IDS.snowRecipe,
      });
    }
  }

  // --- atlas chain: object ink -------------------------------------------
  // Each object's ink carries the ASSET id as its source and the object id
  // inherited from the projection. The object id is copied, never invented:
  // the composer has no way to name an object the projection did not give
  // it. The hovered object renders with an emphasis colour role only, so
  // hover changes the picture and nothing else.
  for (const object of projection.objects ?? []) {
    const hovered = Boolean(state?.hoverCell) &&
      state.hoverCell.x === object.hotspot.x && state.hoverCell.y === object.hotspot.y;
    for (let row = 0; row < object.hotspot.height; row += 1) {
      attempt({
        x: object.hotspot.x,
        y: object.hotspot.y + row,
        glyph: row === 0 ? (object.kind === 'plant' ? '♣' : 'o') : '|',
        color_role: hovered ? 'emphasis' : 'ink',
        source_id: manifest.accepted_assets?.includes(object.asset_id)
          ? object.asset_id
          : null,
        object_id: object.object_id,
      });
    }
  }

  // --- an occluded attempt ------------------------------------------------
  // One deliberate overdraw: a snow flake attempted on the soil row and then
  // NOT shown, so `attempted_primitives` demonstrably contains ink the
  // visible list omits -- SPEC's "a primitive that is attempted and then
  // hidden remains in attempted_primitives", exercised rather than asserted.
  const occluded = attempt({
    x: 0, y: ground, glyph: '.', color_role: 'snow',
    source_id: REFERENCE_IDS.snowRecipe,
  });

  // Visibility: everything except the deliberate occlusion. The contract
  // checks that visible is a SUBSET of attempted; which occlusion policy a
  // composer uses is its own business, so the reference keeps the simplest
  // one that exercises the subset relation.
  const visible = attempted.filter(primitive => primitive !== occluded);

  // --- interaction regions -------------------------------------------------
  // Transformed from the projected hotspot (the atlas-mask stand-in in this
  // fixture) through the same cell-to-pixel transform the art uses, bound to
  // the projected object, named after the asset/state mask it came from, and
  // enlarged -- only enlarged -- to the 44px accessibility floor, centred so
  // growing never moves the target off the ink it belongs to.
  const regions = [];
  for (const object of projection.objects ?? []) {
    if (!object.primary_action) continue;    // not declared interactive
    const rawWidth = object.hotspot.width * viewport.cellWidth;
    const rawHeight = object.hotspot.height * viewport.cellHeight;
    const width = Math.max(rawWidth, 44);
    const height = Math.max(rawHeight, 44);
    regions.push({
      object_id: object.object_id,
      asset_id: object.asset_id,
      state_id: object.state_id,
      units: 'pixel',
      x: object.hotspot.x * viewport.cellWidth - (width - rawWidth) / 2,
      y: object.hotspot.y * viewport.cellHeight - (height - rawHeight) / 2,
      width,
      height,
    });
  }

  // --- the paint payload ---------------------------------------------------
  // Reopened step 2 (frame ownership): the frame carries everything the
  // painter emits, as finished platform primitives. The reference derives
  // its painted rows from the visible primitives -- one string per row --
  // and, having no measured atlas art, declares the measured overlay
  // explicitly EMPTY rather than absent: an empty overlay is a decision the
  // composer made; a missing field would be a hole a painter had to fill.
  const rowGlyphs = Array.from({ length: viewport.cellsHigh },
    () => Array(viewport.cellsWide).fill(' '));
  for (const primitive of visible) {
    if (primitive.y >= 0 && primitive.y < viewport.cellsHigh &&
        primitive.x >= 0 && primitive.x < viewport.cellsWide) {
      rowGlyphs[primitive.y][primitive.x] = primitive.glyph;
    }
  }
  const lines = rowGlyphs.map(row => row.join(''));

  return {
    attempted_primitives: attempted,
    visible_primitives: visible,
    background: {
      kind: 'bands',
      bands: [
        { from_row: 0, to_row: ground - 1, color_role: 'sky' },
        { from_row: ground, to_row: ground, color_role: 'soil' },
      ],
      source_id: REFERENCE_IDS.groundRecipe,
      // The finished platform form of the two bands above; roles are for
      // inspection, these strings are what a painter assigns.
      css: 'linear-gradient(to bottom, #bfe3ff 0%, #bfe3ff 90%, #b58a5f 90%, #b58a5f 100%)',
      text_color: '#243329',
    },
    interaction_regions: regions,
    rows: { lines, html: lines.map(() => '') },
    measured_asset_placements: [],
    aria_label: `Reference garden with ${(projection.objects ?? []).length} objects.`,
    diagnostics: {
      attempted: attempted.length,
      visible: visible.length,
      regions: regions.length,
    },
  };
}

/** The pair under contract, packaged the way `contractViolations` takes it. */
export const REFERENCE_PRESENTATION = Object.freeze({
  advance: advanceReferenceState,
  compose: composeReferenceFrame,
});
