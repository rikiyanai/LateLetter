/** Versioned presentation atlas for the canonical browser Garden renderer. */

export const ATLAS_VERSION = 'garden-atlas-1';

const FIXTURE_GLYPHS = Object.freeze({
  bench: '=', fence: '#', gate: '/', fence_gate: '+', sundial: '^',
  trellis: '#', birdbath: 'U', lantern: 'o', pond: '~', mailbox: 'M',
  memory_shrine: 'M', stepping_stone: '.', stepping_stones: '.', bridge: '-',
  planter: 'U', table: 'T', chair: 'T', table_chairs: 'T', well: 'O',
  arbor: 'n', wind_chime: '!', shed_edge: 'H', tool_rack: 'I',
  watering_can: 'W', compost: 'C', basket: 'U', sign: '?', memorial_stone: 'O',
});

const PLANT_GLYPHS = Object.freeze({
  oak: 'Y', pine: '^', willow: 'Y', cherry: 'Y', maple: 'Y',
  lavender: '*', rose: '@', daisy: '*', tulip: 'u', sunflower: 'O',
  fern: 'f', ivy: 'v', herb: ';', grass: "'", reed: '|', lotus: '*',
});

const ANIMAL_GLYPHS = Object.freeze({ cat: 'c', bird: 'v', rabbit: 'r', turtle: 't' });
const COLLECTIBLE_GLYPHS = Object.freeze({
  'pressed-flower': '*', pressed_flower: '*', feather: ',',
  seed_packet: '%', 'seed-packet': '%', smooth_stone: 'o',
});

const CONNECTED = Object.freeze({
  fence: '.|-+||++-+-+++++', hedge: '.###############',
  path: '.:=+::++=+=+++++', pond_edge: '.|~+||++~+~+++++',
  wall: '.|=+||++=+=+++++',
});

export function connectedGlyph(mask, group = 'fence') {
  return (CONNECTED[group] ?? CONNECTED.fence)[Number(mask) & 15];
}

export function glyphForProjection(object, { connectedMask = null } = {}) {
  const state = object?.semantic_state ?? {};
  if (object?.kind === 'fixture') {
    if (connectedMask !== null) return connectedGlyph(
      connectedMask, object.semantic_state?.connected_group ?? fixtureConnectedGroup(state.catalog_id),
    );
    return FIXTURE_GLYPHS[state.catalog_id] ?? 'F';
  }
  if (object?.kind === 'plant') return PLANT_GLYPHS[state.species_id] ?? '*';
  if (object?.kind === 'animal') return ANIMAL_GLYPHS[state.species_id] ?? 'a';
  if (object?.kind === 'collectible') return COLLECTIBLE_GLYPHS[state.family] ?? '$';
  return '?';
}

export function fixtureConnectedGroup(catalogId) {
  if (['fence', 'gate', 'fence_gate'].includes(catalogId)) return 'fence';
  if (['stepping_stone', 'stepping_stones'].includes(catalogId)) return 'path';
  if (catalogId === 'pond') return 'pond_edge';
  return null;
}
