/** Versioned presentation atlas for the canonical browser Garden renderer. */

import ATLAS_MANIFEST from '../src/lateletter/garden/data/atlas.v1.json' with { type: 'json' };

export const ATLAS_VERSION = ATLAS_MANIFEST.id;
export { ATLAS_MANIFEST };
const TOKENS = ATLAS_MANIFEST.semantic_tokens;
const ASSETS = new Map(ATLAS_MANIFEST.assets.map(asset => [asset.id, asset]));
const FIXTURE_ASSETS = Object.freeze({
  bench: 'fixture.bench', fence: 'fixture.fence_gate', gate: 'fixture.fence_gate',
  fence_gate: 'fixture.fence_gate', sundial: 'fixture.sundial', trellis: 'fixture.trellis',
  birdbath: 'fixture.birdbath', lantern: 'fixture.lantern', pond: 'fixture.pond',
  mailbox: 'fixture.mailbox', memory_shrine: 'fixture.mailbox',
  stepping_stone: 'fixture.stepping_stones', stepping_stones: 'fixture.stepping_stones',
  bridge: 'fixture.bridge', planter: 'fixture.planter', table: 'fixture.table_chairs',
  chair: 'fixture.table_chairs', table_chairs: 'fixture.table_chairs', well: 'fixture.well',
  arbor: 'fixture.arbor', wind_chime: 'fixture.wind_chime', shed_edge: 'fixture.shed_edge',
  tool_rack: 'fixture.tool_rack', watering_can: 'fixture.watering_can',
  compost: 'fixture.compost', basket: 'fixture.basket', sign: 'fixture.sign',
  memorial_stone: 'fixture.memorial_stone',
});
// The single lattice glyph for a fixture whose drawing lives only in atlas v2.
//
// Why this map exists at all
// --------------------------
// `drawCanonicalObject` paints a fixture's art and THEN stamps one glyph per
// `render_cells` entry on top of it (web/garden-painting.mjs:2596-2600), with
// no guard on art already being present. That stamp is resolved by
// `glyphForProjection` below, which looks the catalog id up in `FIXTURE_ASSETS`
// and reads the first cell of the resulting v1 asset.
//
// The four operator-granted gift drawings of 2026-08-06 are v2-only, on
// purpose: v1 is the pre-artwork schema in which every asset is one glyph in a
// 1x1 box, and `tests/garden_contract/test_atlas_v2.py:91-107` enumerates these
// four by name as v2-only while `:331-340` pins `migrate(v1)` byte-for-byte
// against the committed v2 file. Writing a real drawing back into v1 would both
// describe v1 as something it never was and break that identity pin.
//
// So the stamp glyph is declared HERE instead — which is exactly the thing v1
// was for, one glyph per object, without mutating a pinned artifact.
//
// Why these particular characters
// -------------------------------
// Each is the glyph the asset's OWN art already places at its OWN declared
// anchor cell, verified against atlas.v2.json:
//   coffee_mug     anchor (3,1) of ':c[_]'  -> '_'
//   ice_cream_cone anchor (2,1) of '  V'    -> 'V'
//   mixtape        anchor (2,0) of '[o=o]'  -> '='
//   popsicle       anchor (1,2) of ' | '    -> '|'
// Because the stamped glyph equals the glyph already drawn there, the stamp
// lands invisibly and the granted art survives intact. This is deliberately
// better than the existing fixtures manage: `mailbox` stamps 'M' over its own
// '|' and `lantern` stamps 'o' over its own '_', so their anchor cell is
// genuinely replaced. That wider defect is recorded and left to the operator;
// it is NOT repaired here, because repairing it changes every reviewed fixture.
const V2_ONLY_FIXTURE_STAMP_GLYPHS = Object.freeze({
  coffee_mug: '_', ice_cream_cone: 'V', mixtape: '=', popsicle: '|',
});

const COLLECTIBLE_ASSETS = Object.freeze({
  'pressed-flower': 'collectible.pressed_flower', pressed_flower: 'collectible.pressed_flower',
  feather: 'collectible.feather', seed_packet: 'collectible.seed_packet',
  'seed-packet': 'collectible.seed_packet', smooth_stone: 'collectible.smooth_stone',
});

const CONNECTED = Object.freeze(Object.fromEntries(Object.entries(ATLAS_MANIFEST.connected_tiles)
  .map(([family, masks]) => [family, Array.from({ length: 16 }, (_, index) => masks[String(index)]).join('')])));

function assetGlyph(assetId, state = 'idle', fallback = '?') {
  const states = ASSETS.get(assetId)?.profiles?.['ascii-safe'];
  if (!states) return fallback;
  const frames = states[state] ?? states.idle ?? states[Object.keys(states).sort()[0]];
  return frames?.[0]?.cells?.[0]?.[0] ?? fallback;
}

export const LETTERBIRD_DELIVERY_FRAMES = TOKENS.delivery_frames.letterbird;
export const ANIMAL_DELIVERY_FRAMES = Object.freeze(Object.fromEntries(
  ['cat', 'bird', 'rabbit', 'turtle'].map(species => [species, TOKENS.delivery_frames[species]]),
));

export function deliveryFramesFor(speciesId, bondTier) {
  return Number(bondTier) >= 3 && Object.hasOwn(ANIMAL_DELIVERY_FRAMES, speciesId)
    ? ANIMAL_DELIVERY_FRAMES[speciesId] : LETTERBIRD_DELIVERY_FRAMES;
}

export function organGlyph(kind, glyphFamily = '') {
  if (String(glyphFamily).includes('bloom')) return '@';
  if (String(glyphFamily).includes('leaf') || ['needle', 'blade'].includes(glyphFamily)) return '*';
  return TOKENS.organ_kind_glyphs[kind] ?? '*';
}

export function connectedGlyph(mask, group = 'fence') {
  if (!Object.hasOwn(CONNECTED, group)) throw new Error(`unknown connected group ${group}`);
  const value = Number(mask);
  if (!Number.isInteger(value) || value < 0 || value > 15) {
    throw new Error(`invalid connected mask ${mask}`);
  }
  return CONNECTED[group][value];
}

export function glyphForProjection(object, { connectedMask = null } = {}) {
  const state = object?.semantic_state ?? {};
  if (object?.kind === 'fixture') {
    if (connectedMask !== null) return connectedGlyph(
      connectedMask, object.semantic_state?.connected_group,
    );
    // A v2-only fixture has no v1 asset to read a glyph from, so without this
    // the lookup misses and the literal 'F' fallback is stamped over the
    // drawing -- which is what made the granted coffee mug paint ':c[F]'
    // instead of ':c[_]'. Consulted before the atlas lookup because these ids
    // are deliberately absent from it.
    const v2OnlyGlyph = V2_ONLY_FIXTURE_STAMP_GLYPHS[state.catalog_id];
    if (v2OnlyGlyph !== undefined) return v2OnlyGlyph;
    return assetGlyph(FIXTURE_ASSETS[state.catalog_id], state.presentation_state, 'F');
  }
  if (object?.kind === 'plant') return TOKENS.plant_species_glyphs[state.species_id] ?? '*';
  if (object?.kind === 'animal') {
    const tiers = TOKENS.animal_tier_glyphs[state.species_id];
    const glyph = tiers?.[Math.max(0, Math.min(3, Number(state.bond_tier) || 0))]
      ?? 'a';
    return state.choreography_locked ? glyph.toUpperCase() : glyph;
  }
  if (object?.kind === 'collectible') return assetGlyph(COLLECTIBLE_ASSETS[state.family], 'idle', '$');
  return '?';
}
