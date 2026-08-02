/**
 * A composer that satisfies the presentation contract, and actually runs.
 * ----------------------------------------------------------------------
 *
 * WHY THIS EXISTS
 *
 * A conformance check that has only ever REFUSED things proves nothing about
 * whether it can be satisfied at all. The previous round of this work learned
 * that the hard way: its "satisfiable" positive control was a string of
 * JavaScript that could not execute — it allocated no row arrays and would
 * have thrown on its first write — and it was the sole evidence for the claim
 * that the gate was reachable. A control that cannot run proves nothing about
 * running code.
 *
 * So this one is a module. It is imported and executed, it composes a real
 * frame from real inputs, and the contract is applied to its output. If the
 * contract ever becomes unsatisfiable, this file stops conforming and says so.
 *
 * WHAT IT IS NOT
 *
 * It is not the Garden and it is not a proposal for the Garden's art. It draws
 * the smallest picture that exercises every clause: recipe-chain ground,
 * atlas-chain object ink carrying an object id, an interaction region
 * transported from a projected hotspot, and one piece of presentation-only
 * state that accumulates across frames.
 */

/** Ids the reference picture paints from, matching the fixture manifest below. */
export const REFERENCE_IDS = Object.freeze({
  groundRecipe: 'recipe.reference.ground',
  snowRecipe: 'recipe.reference.snow',
  densityLaw: 'law.reference.density',
  plantAsset: 'asset.reference.plant',
});

/**
 * The accepted-paint manifest the reference composer is meant to be given.
 *
 * In the product this is compiled at build time from the two registers. Here
 * it is a literal, because the contract's job is to check the composer against
 * whatever manifest it was handed, not to go and read files.
 */
export const REFERENCE_MANIFEST = Object.freeze({
  assetIds: [REFERENCE_IDS.plantAsset],
  recipeIds: [REFERENCE_IDS.groundRecipe, REFERENCE_IDS.snowRecipe],
  lawIds: [REFERENCE_IDS.densityLaw],
  acceptedIds: [REFERENCE_IDS.groundRecipe, REFERENCE_IDS.snowRecipe, REFERENCE_IDS.plantAsset],
});

/**
 * A projection holding one interactive object, in the shape
 * `projectGardenScene` produces: an `object_id`, a `hotspot` in cells, and a
 * `primary_action` that is non-null exactly when the object is interactive.
 */
export const REFERENCE_PROJECTION = Object.freeze({
  objects: [
    {
      object_id: 'plant-1',
      kind: 'plant',
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
 * Compose one frame.
 *
 * @param {object} input                     the five contract inputs
 * @param {object} input.projection          canonical projection, read-only
 * @param {object} input.viewport            cell counts and pixel cell size
 * @param {{seconds: number, frame: number}} input.presentationTime the only time source
 * @param {object|null} input.presentationState  what the previous compose returned
 * @param {object} input.acceptedManifest    which ids may be painted
 * @returns {{cells: Array, interactionRegions: Array, nextPresentationState: object}}
 */
export function composeReferenceFrame({
  projection,
  viewport,
  presentationTime,
  presentationState,
  acceptedManifest,
}) {
  const cells = [];
  const ground = viewport.cellsHigh - 1;   // soil occupies the bottom row

  // --- recipe chain: the ground ------------------------------------------
  // Every ground cell names the recipe that draws ground. None of them carries
  // an object id, because ground is not a drawing OF a gameplay object -- that
  // is the whole distinction between the two identity chains.
  for (let x = 0; x < viewport.cellsWide; x += 1) {
    cells.push({
      x,
      y: ground,
      glyph: '_',
      color: '#6b5b3e',
      animated: false,
      sourceId: acceptedManifest.recipeIds.includes('recipe.reference.ground')
        ? 'recipe.reference.ground'
        : null,
      objectId: null,
    });
  }

  // --- presentation-only state that accumulates --------------------------
  // Snow depth grows by one cell every four frames and stops at the row above
  // the soil. It is read from the incoming state and written to the outgoing
  // state; nothing about it is persisted or handed back to the world. This is
  // why `presentationState` is on both sides of the signature: a composer that
  // could only see the frame number would have to recompute accumulation from
  // the beginning of time, or fake it.
  const previousDepth = presentationState?.snowDepth ?? 0;
  const snowDepth = Math.min(previousDepth + (presentationTime.frame % 4 === 0 ? 1 : 0), ground);
  for (let depth = 0; depth < snowDepth; depth += 1) {
    for (let x = 0; x < viewport.cellsWide; x += 2) {
      cells.push({
        x,
        y: ground - 1 - depth,
        glyph: '.',
        color: '#e8eef5',
        animated: false,
        sourceId: 'recipe.reference.snow',
        objectId: null,
      });
    }
  }

  // --- atlas chain: object ink -------------------------------------------
  // The plant's two cells carry the ASSET id as their source and the object id
  // inherited from the projection. The object id is copied, never invented:
  // the composer has no way to name an object the projection did not give it.
  const plant = projection.objects.find(object => object.kind === 'plant');
  if (plant) {
    for (let row = 0; row < plant.hotspot.height; row += 1) {
      cells.push({
        x: plant.hotspot.x,
        y: plant.hotspot.y + row,
        glyph: row === 0 ? '♣' : '|',
        color: '#3f7d43',
        animated: false,
        sourceId: 'asset.reference.plant',
        objectId: plant.object_id,
      });
    }
  }

  // --- interaction regions ------------------------------------------------
  // Transported from the projected hotspot through the same cell-to-pixel
  // transform the art uses, then enlarged -- only enlarged -- to the 44px
  // accessibility floor. The region is centred on the hotspot when it grows,
  // so enlarging never moves the target off the ink it belongs to.
  const interactionRegions = [];
  for (const object of projection.objects) {
    if (!object.primary_action) continue;    // not declared interactive
    const rawWidth = object.hotspot.width * viewport.cellWidth;
    const rawHeight = object.hotspot.height * viewport.cellHeight;
    const width = Math.max(rawWidth, 44);
    const height = Math.max(rawHeight, 44);
    interactionRegions.push({
      objectId: object.object_id,
      x: object.hotspot.x * viewport.cellWidth - (width - rawWidth) / 2,
      y: object.hotspot.y * viewport.cellHeight - (height - rawHeight) / 2,
      width,
      height,
      primary: object.primary_action,
    });
  }

  return { cells, interactionRegions, nextPresentationState: { snowDepth } };
}
