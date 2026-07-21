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
