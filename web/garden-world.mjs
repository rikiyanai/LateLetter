/** Canonical, renderer-neutral Garden world model and reducer for browsers. */

import {
  canonicalJson,
  sha256Hex,
  stableId,
  validateGardenCommand,
} from './garden-input.mjs';


export const WORLD_SCHEMA_VERSION = 1;
export const ENGINE_VERSION = 'garden-world-internal-v1';

const PERSONALITY_FIELDS = Object.freeze([
  'boldness', 'sociability', 'curiosity', 'playfulness', 'patience',
  'routine_strength', 'food_motivation', 'day_preference',
]);

const FIXTURE_CATALOG = Object.freeze({
  bench: { name: 'Garden bench', footprint: [2, 1], blocks_movement: true, affordances: ['sit', 'animal-rest', 'author-socket'], actions: ['inspect', 'primary_interact'] },
  fence: { name: 'Fence', footprint: [1, 1], blocks_movement: true, affordances: ['boundary', 'perch', 'vine-support'], actions: ['inspect'] },
  gate: { name: 'Garden gate', footprint: [1, 1], blocks_movement: false, affordances: ['open-close', 'route'], actions: ['inspect', 'primary_interact'] },
  sundial: { name: 'Sundial', footprint: [1, 1], blocks_movement: true, affordances: ['garden-time', 'authored-beat'], actions: ['inspect'] },
  trellis: { name: 'Trellis', footprint: [2, 1], blocks_movement: true, affordances: ['train-plant', 'animal-hide'], actions: ['inspect', 'tend'] },
  birdbath: { name: 'Birdbath', footprint: [1, 1], blocks_movement: true, affordances: ['refill', 'drink', 'bathe'], actions: ['inspect', 'tend'] },
  lantern: { name: 'Lantern', footprint: [1, 1], blocks_movement: true, affordances: ['light', 'moth-visit'], actions: ['inspect', 'primary_interact'] },
  pond: { name: 'Pond', footprint: [3, 2], blocks_movement: true, affordances: ['ripples', 'aquatic-plant', 'water-visitor'], actions: ['inspect', 'tend'] },
  memory_shrine: { name: 'Memory shrine', footprint: [2, 1], blocks_movement: true, affordances: ['keepsake', 'inscription', 'memory-discovery'], actions: ['inspect', 'open_journal'] },
  stepping_stone: { name: 'Stepping stone', footprint: [1, 1], blocks_movement: false, affordances: ['path'], actions: ['inspect'] },
  bridge: { name: 'Bridge', footprint: [3, 1], blocks_movement: false, affordances: ['cross-water', 'animal-route'], actions: ['inspect', 'primary_interact'] },
  planter: { name: 'Planter', footprint: [2, 1], blocks_movement: true, affordances: ['plant-container', 'transplant'], actions: ['inspect', 'tend'] },
  table: { name: 'Garden table', footprint: [2, 2], blocks_movement: true, affordances: ['place-keepsake', 'animal-sniff'], actions: ['inspect', 'primary_interact'] },
  chair: { name: 'Garden chair', footprint: [1, 1], blocks_movement: true, affordances: ['sit', 'observe'], actions: ['inspect', 'primary_interact'] },
});

export const MINIMUM_WORLD_WIDTH = 64;
export const MINIMUM_WORLD_HEIGHT = 40;

const SPECIES_CATALOG = Object.freeze({
  oak: ['tree', 18, 30, 86400, ['trunk', 'branch', 'broadleaf']],
  pine: ['tree', 16, 26, 86400, ['trunk', 'conifer', 'needle']],
  willow: ['tree', 20, 32, 86400, ['trunk', 'branch', 'drooping-leaf']],
  rose: ['shrub', 10, 18, 64800, ['stem', 'thorn', 'rose-bloom']],
  hydrangea: ['shrub', 12, 20, 64800, ['stem', 'broadleaf', 'cluster-bloom']],
  ivy: ['vine', 12, 24, 43200, ['vine', 'ivy-leaf']],
  wisteria: ['vine', 14, 26, 43200, ['vine', 'drooping-bloom']],
  meadow_grass: ['grass', 8, 16, 21600, ['blade', 'seed-head']],
  lavender: ['herb', 9, 17, 32400, ['stem', 'narrow-leaf', 'lavender-bloom']],
  rosemary: ['herb', 9, 17, 32400, ['stem', 'needle-leaf', 'herb-bloom']],
  tulip: ['flower', 6, 10, 21600, ['stem', 'tulip-leaf', 'tulip-bloom']],
  sunflower: ['flower', 7, 12, 32400, ['stem', 'broadleaf', 'sunflower-bloom']],
  water_lily: ['aquatic', 7, 13, 43200, ['rhizome', 'lily-pad', 'water-bloom']],
});

const ANIMAL_SPECIES = Object.freeze({
  bird: { affinities: ['fence', 'birdbath', 'trellis'] },
  cat: { affinities: ['bench', 'table', 'memory_shrine'] },
  rabbit: { affinities: ['trellis', 'planter', 'bench'] },
  turtle: { affinities: ['pond', 'bridge', 'stepping_stone'] },
});

const COLLECTIBLE_CATALOG = Object.freeze({
  oak_leaf: ['plant_species', 'recipient-grown', 'Oak leaf', "A leaf showing the oak's branching veins."],
  lavender_sprig: ['plant_species', 'recipient-grown', 'Lavender sprig', 'A fragrant sprig from a tended lavender plant.'],
  first_snowflake: ['seasonal_natural_find', 'procedural', 'First snowflake', "A remembered trace of the season's first snow."],
  fallen_acorn: ['seasonal_natural_find', 'procedural', 'Fallen acorn', 'A small autumn find beneath the trees.'],
  rabbit_track: ['animal_trace', 'animal-given', 'Rabbit track', 'A soft print where a rabbit paused.'],
  bird_feather: ['animal_trace', 'animal-given', 'Bird feather', 'A feather left near a favorite perch.'],
  pressed_flower: ['authored_keepsake', 'author-authored', 'Pressed flower', 'A flower preserved with an authored memory.'],
  small_key: ['authored_keepsake', 'author-authored', 'Small key', 'A keepsake key waiting without expiry.'],
});

const clone = value => globalThis.structuredClone
  ? globalThis.structuredClone(value)
  : JSON.parse(JSON.stringify(value));
const integer = (value, fallback = 0) => {
  const parsed = Number(value ?? fallback);
  return Number.isFinite(parsed) ? Math.trunc(parsed) : Math.trunc(fallback);
};
const clamp = (value, low, high) => Math.max(low, Math.min(high, integer(value)));
const rotation = value => ((integer(value) % 360) + 360) % 360;
const optionalString = value => value ? String(value) : null;
const vec2 = (value = [0, 0]) => [integer(value[0]), integer(value[1])];
const uniqueSorted = values => [...new Set(values.map(String))].sort();
const sortBy = (values, field) => [...values].sort((left, right) =>
  String(left[field]).localeCompare(String(right[field])));

function normalizeOrgan(data) {
  return {
    node_id: String(data.node_id),
    parent_id: optionalString(data.parent_id),
    kind: String(data.kind),
    birth_time: integer(data.birth_time),
    maturity_time: integer(data.maturity_time),
    final_direction: vec2(data.final_direction),
    final_length: integer(data.final_length),
    glyph_family: String(data.glyph_family),
    bloom_state: optionalString(data.bloom_state),
  };
}

function normalizePlant(data) {
  return {
    plant_id: String(data.plant_id),
    species_id: String(data.species_id),
    position: vec2(data.position),
    topology: (data.topology ?? []).map(normalizeOrgan),
    growth_points: integer(data.growth_points, 0),
    tended_count: integer(data.tended_count, 0),
    last_tended_at: data.last_tended_at === null || data.last_tended_at === undefined
      ? null : integer(data.last_tended_at),
    growth_period_seconds: Math.max(1, integer(data.growth_period_seconds, 86400)),
  };
}

function normalizeFixture(data) {
  return {
    fixture_id: String(data.fixture_id),
    catalog_id: String(data.catalog_id),
    position: vec2(data.position),
    rotation: rotation(data.rotation ?? 0),
    authored: Boolean(data.authored ?? false),
  };
}

function normalizePersonality(data = {}) {
  return Object.fromEntries(PERSONALITY_FIELDS.map(field => [
    field, clamp(data[field] ?? 50, 0, 100),
  ]));
}

function normalizeMemory(data) {
  return {
    memory_id: String(data.memory_id),
    kind: String(data.kind),
    target_id: optionalString(data.target_id),
    timestamp: integer(data.timestamp),
    valence: integer(data.valence, 0),
    salience: integer(data.salience, 0),
  };
}

function normalizeAnimal(data) {
  const counts = data.interaction_counts ?? {};
  const cooldowns = data.cooldowns ?? {};
  return {
    animal_id: String(data.animal_id),
    species_id: String(data.species_id),
    position: vec2(data.position),
    high_level_state: String(data.high_level_state ?? 'awake'),
    bond_points: Math.max(0, integer(data.bond_points, 0)),
    bond_tier: clamp(data.bond_tier ?? 0, 0, 3),
    interaction_counts: Object.fromEntries(
      Object.keys(counts).sort().map(key => [String(key), integer(counts[key])]),
    ),
    session_interactions: (data.session_interactions ?? []).map(String),
    recent_memories: (data.recent_memories ?? []).map(normalizeMemory),
    personality: normalizePersonality(data.personality),
    energy: clamp(data.energy ?? 60, 0, 100),
    social_appetite: clamp(data.social_appetite ?? 50, 0, 100),
    play_appetite: clamp(data.play_appetite ?? 50, 0, 100),
    rest_appetite: clamp(data.rest_appetite ?? 40, 0, 100),
    choreography_lock: optionalString(data.choreography_lock),
    current_intent: String(data.current_intent ?? 'idle'),
    intent_started_at: Math.max(0, integer(data.intent_started_at, 0)),
    minimum_dwell_until: Math.max(0, integer(data.minimum_dwell_until, 0)),
    decision_index: Math.max(0, integer(data.decision_index, 0)),
    cooldowns: Object.fromEntries(
      Object.keys(cooldowns).sort().map(key => [String(key), integer(cooldowns[key])]),
    ),
    favorite_fixture_ids: uniqueSorted(data.favorite_fixture_ids ?? []),
    authored_preferences: uniqueSorted(data.authored_preferences ?? []),
    authored_prohibitions: uniqueSorted(data.authored_prohibitions ?? []),
  };
}

function normalizeCollectible(data) {
  return {
    collectible_id: String(data.collectible_id),
    family: String(data.family),
    provenance: String(data.provenance),
    label: String(data.label),
    description: String(data.description),
    position: vec2(data.position),
    collected: Boolean(data.collected ?? false),
    authored: Boolean(data.authored ?? false),
  };
}

function normalizeJournal(data) {
  return {
    entry_id: String(data.entry_id),
    object_id: String(data.object_id),
    status: String(data.status),
    label: String(data.label),
    description: String(data.description),
    discovered_at: integer(data.discovered_at),
  };
}

function normalizeUi(data = {}) {
  return {
    focus_id: optionalString(data.focus_id),
    camera: vec2(data.camera ?? [0, 0]),
    actions_open_for: optionalString(data.actions_open_for),
    journal_open: Boolean(data.journal_open ?? false),
    motion_paused: Boolean(data.motion_paused ?? false),
  };
}

function normalizeUndo(data) {
  return {
    kind: String(data.kind),
    object_id: String(data.object_id),
    previous_position: data.previous_position ? vec2(data.previous_position) : null,
    previous_rotation: data.previous_rotation === null || data.previous_rotation === undefined
      ? null : integer(data.previous_rotation),
    created: Boolean(data.created ?? false),
  };
}

function normalizeTrace(data) {
  return {
    trace_id: String(data.trace_id),
    sequence: integer(data.sequence),
    kind: String(data.kind),
    target_id: optionalString(data.target_id),
    effective_time: integer(data.effective_time),
    summary: String(data.summary),
  };
}

export function deserializeWorldState(raw) {
  const data = typeof raw === 'string' ? JSON.parse(raw) : raw;
  const schemaVersion = integer(data.schema_version, 0);
  if (schemaVersion !== WORLD_SCHEMA_VERSION) {
    throw new Error(`unsupported Garden world schema ${schemaVersion}`);
  }
  return {
    schema_version: schemaVersion,
    engine_version: String(data.engine_version ?? ENGINE_VERSION),
    world_id: String(data.world_id),
    seed: String(data.seed),
    world_width: Math.max(1, integer(data.world_width, 120)),
    world_height: Math.max(1, integer(data.world_height, 80)),
    effective_time: Math.max(0, integer(data.effective_time, 0)),
    last_observed_wall_time:
      data.last_observed_wall_time === null || data.last_observed_wall_time === undefined
        ? null : integer(data.last_observed_wall_time),
    command_sequence: Math.max(0, integer(data.command_sequence, 0)),
    plants: (data.plants ?? []).map(normalizePlant),
    fixtures: (data.fixtures ?? []).map(normalizeFixture),
    animals: (data.animals ?? []).map(normalizeAnimal),
    collectibles: (data.collectibles ?? []).map(normalizeCollectible),
    inventory: (data.inventory ?? []).map(String),
    journal: (data.journal ?? []).map(normalizeJournal),
    ui: normalizeUi(data.ui),
    undo_stack: (data.undo_stack ?? []).map(normalizeUndo),
    milestone_receipts: (data.milestone_receipts ?? []).map(String),
    program_state: clone(data.program_state ?? {}),
    processed_commands: (data.processed_commands ?? []).map(String),
    event_trace: (data.event_trace ?? []).map(normalizeTrace),
  };
}

export function serializeWorldState(state) {
  return {
    schema_version: integer(state.schema_version),
    engine_version: String(state.engine_version),
    world_id: String(state.world_id),
    seed: String(state.seed),
    world_width: integer(state.world_width),
    world_height: integer(state.world_height),
    effective_time: integer(state.effective_time),
    last_observed_wall_time: state.last_observed_wall_time === null
      ? null : integer(state.last_observed_wall_time),
    command_sequence: integer(state.command_sequence),
    plants: sortBy(state.plants.map(normalizePlant), 'plant_id').map(plant => ({
      ...plant,
      topology: sortBy(plant.topology, 'node_id'),
    })),
    fixtures: sortBy(state.fixtures.map(normalizeFixture), 'fixture_id'),
    animals: sortBy(state.animals.map(normalizeAnimal), 'animal_id'),
    collectibles: sortBy(state.collectibles.map(normalizeCollectible), 'collectible_id'),
    inventory: uniqueSorted(state.inventory),
    journal: sortBy(state.journal.map(normalizeJournal), 'entry_id'),
    ui: normalizeUi(state.ui),
    undo_stack: state.undo_stack.map(normalizeUndo),
    milestone_receipts: uniqueSorted(state.milestone_receipts),
    program_state: clone(state.program_state ?? {}),
    processed_commands: state.processed_commands.map(String),
    event_trace: state.event_trace.map(normalizeTrace),
  };
}

export function canonicalWorldJson(state) {
  return canonicalJson(serializeWorldState(state));
}

export function worldStateBytes(state) {
  return new TextEncoder().encode(canonicalWorldJson(state));
}

export async function newGardenWorld(
  worldId,
  seed,
  { world_width = 120, world_height = 80 } = {},
) {
  const seedDigest = await sha256Hex(canonicalJson(['world-seed', String(seed)]));
  return deserializeWorldState({
    schema_version: WORLD_SCHEMA_VERSION,
    engine_version: ENGINE_VERSION,
    world_id: String(worldId),
    seed: seedDigest,
    world_width: Math.max(1, integer(world_width)),
    world_height: Math.max(1, integer(world_height)),
  });
}

const ZERO_REPLACEMENT = 0x6d2b79f5;

async function deriveSeed(rootSeed, ...domain) {
  const digest = await sha256Hex(canonicalJson([
    'lateletter-garden-rng-v1', String(rootSeed), ...domain,
  ]));
  const value = Number.parseInt(digest.slice(0, 8), 16) >>> 0;
  return value || ZERO_REPLACEMENT;
}

class DeterministicRng {
  constructor(seed) { this.state = (Number(seed) >>> 0) || ZERO_REPLACEMENT; }
  nextU32() {
    let value = this.state >>> 0;
    value = (value ^ ((value << 13) >>> 0)) >>> 0;
    value = (value ^ (value >>> 17)) >>> 0;
    value = (value ^ ((value << 5) >>> 0)) >>> 0;
    this.state = value >>> 0;
    return this.state;
  }
  randbelow(stop) {
    if (!Number.isInteger(stop) || stop <= 0) throw new Error('stop must be positive');
    const limit = 0x100000000 - (0x100000000 % stop);
    for (;;) {
      const value = this.nextU32();
      if (value < limit) return value % stop;
    }
  }
  randint(start, stop) {
    if (stop < start) throw new Error('stop must be >= start');
    return start + this.randbelow(stop - start + 1);
  }
  choice(values) {
    if (!values.length) throw new Error('cannot choose from an empty sequence');
    return values[this.randbelow(values.length)];
  }
}

async function shuffled(values, rng) {
  const output = [...values];
  for (let index = output.length - 1; index > 0; index -= 1) {
    const swap = rng.randbelow(index + 1);
    [output[index], output[swap]] = [output[swap], output[index]];
  }
  return output;
}

function organKind(definition, index, total) {
  const [category, , , , glyphs] = definition;
  const progress = index / Math.max(1, total - 1);
  if (category === 'tree' || category === 'shrub') {
    if (progress < 0.28) return 'stem';
    if (progress < 0.68) return 'branch';
    return glyphs.at(-1).includes('bloom') ? 'bloom' : 'leaf';
  }
  if (category === 'vine') return index % 3 ? 'vine' : 'leaf';
  if (category === 'aquatic') return progress > 0.8 ? 'bloom' : 'leaf';
  if (progress < 0.45) return 'stem';
  return progress > 0.82 ? 'bloom' : 'leaf';
}

async function generateTopology(worldSeed, plantId, speciesId, plantedAt = 0) {
  const definition = SPECIES_CATALOG[speciesId];
  const structure = new DeterministicRng(await deriveSeed(
    worldSeed, 'plant', plantId, 'topology', 'structure',
  ));
  const timing = new DeterministicRng(await deriveSeed(
    worldSeed, 'plant', plantId, 'topology', 'timing',
  ));
  const styling = new DeterministicRng(await deriveSeed(
    worldSeed, 'plant', plantId, 'topology', 'style',
  ));
  const [, minimum, maximum, , glyphs] = definition;
  const total = structure.randint(minimum, maximum);
  const rootId = await stableId('organ', plantId, 'root');
  const nodes = [normalizeOrgan({
    node_id: rootId, parent_id: null, kind: 'root', birth_time: plantedAt,
    maturity_time: plantedAt, final_direction: [0, -1], final_length: 1,
    glyph_family: 'root', bloom_state: null,
  })];
  for (let index = 1; index < total; index += 1) {
    const kind = organKind(definition, index, total);
    const parentIndex = definition[0] === 'vine' || index < 4
      ? index - 1 : structure.randbelow(index);
    const parent = nodes[parentIndex];
    let direction = [structure.randint(-1, 1), -structure.randint(0, 1)];
    if (direction[0] === 0 && direction[1] === 0) direction = [0, -1];
    const birth = plantedAt + index * timing.randint(2700, 7200);
    const maturity = birth + timing.randint(3600, 14400);
    nodes.push(normalizeOrgan({
      node_id: await stableId('organ', plantId, index, kind, parent.node_id),
      parent_id: parent.node_id, kind, birth_time: birth, maturity_time: maturity,
      final_direction: direction, final_length: structure.randint(1, 4),
      glyph_family: styling.choice(glyphs),
      bloom_state: kind === 'bloom' ? 'bud' : null,
    }));
  }
  return nodes;
}

async function freePosition(state, domain, occupied, margin = 2) {
  const rng = new DeterministicRng(await deriveSeed(state.seed, 'layout', ...domain));
  for (let attempt = 0; attempt < 512; attempt += 1) {
    const candidate = [
      rng.randint(margin, state.world_width - margin - 1),
      rng.randint(margin, state.world_height - margin - 1),
    ];
    if (!occupied.has(cellKey(candidate))) {
      occupied.add(cellKey(candidate));
      return candidate;
    }
  }
  throw new Error(`could not place ${canonicalJson(domain)} safely`);
}

/** Generate the same canonical initial state as Python; viewport is never input. */
export async function generateInitialWorld(
  worldId, seed, { world_width = 120, world_height = 80 } = {},
) {
  if (world_width < MINIMUM_WORLD_WIDTH || world_height < MINIMUM_WORLD_HEIGHT) {
    throw new Error(`canonical world must be at least ${MINIMUM_WORLD_WIDTH}x${MINIMUM_WORLD_HEIGHT}`);
  }
  const state = await newGardenWorld(worldId, seed, { world_width, world_height });
  const fixtureRng = new DeterministicRng(await deriveSeed(
    state.seed, 'layout', 'fixtures',
  ));
  const fixtureIds = await shuffled(Object.keys(FIXTURE_CATALOG), fixtureRng);
  const columns = 5;
  const spacingX = Math.max(8, Math.floor((state.world_width - 8) / columns));
  const startY = state.world_height - 18;
  state.fixtures = [];
  for (let index = 0; index < fixtureIds.length; index += 1) {
    const catalogId = fixtureIds[index];
    state.fixtures.push(normalizeFixture({
      fixture_id: await stableId('fixture', state.world_id, catalogId),
      catalog_id: catalogId,
      position: [4 + (index % columns) * spacingX, startY + Math.floor(index / columns) * 5],
      rotation: fixtureRng.randbelow(4) * 90,
      authored: false,
    }));
  }
  const occupied = new Set(state.fixtures.flatMap(fixtureCells).map(cellKey));
  for (const speciesId of Object.keys(SPECIES_CATALOG).sort()) {
    const plantId = await stableId('plant', state.world_id, speciesId);
    const position = await freePosition(state, ['plant', speciesId], occupied, 3);
    state.plants.push(normalizePlant({
      plant_id: plantId, species_id: speciesId, position,
      topology: await generateTopology(state.seed, plantId, speciesId),
      growth_period_seconds: SPECIES_CATALOG[speciesId][3],
    }));
  }
  const blocked = new Set([...occupied, ...state.plants.map(item => cellKey(item.position))]);
  for (const speciesId of Object.keys(ANIMAL_SPECIES).sort()) {
    const animalId = await stableId('animal', state.world_id, speciesId);
    const position = await freePosition(state, ['animal', speciesId], blocked, 2);
    const personalityRng = new DeterministicRng(await deriveSeed(
      state.seed, 'animal', animalId, 'personality',
    ));
    state.animals.push(normalizeAnimal({
      animal_id: animalId, species_id: speciesId, position,
      personality: Object.fromEntries(PERSONALITY_FIELDS.map(field => [
        field, personalityRng.randint(20, 80),
      ])),
    }));
  }
  for (const catalogId of Object.keys(COLLECTIBLE_CATALOG).sort()) {
    const collectibleId = await stableId('collectible', state.world_id, catalogId);
    const position = await freePosition(state, ['collectible', catalogId], blocked, 2);
    const [family, provenance, label, description] = COLLECTIBLE_CATALOG[catalogId];
    state.collectibles.push(normalizeCollectible({
      collectible_id: collectibleId, family, provenance, label, description,
      position, authored: family === 'authored_keepsake',
    }));
  }
  if (!layoutIsSafe(state)) throw new Error('generated Garden layout failed safety validation');
  return deserializeWorldState(serializeWorldState(state));
}

function objectIds(state) {
  return [
    ...state.plants.map(item => item.plant_id),
    ...state.fixtures.map(item => item.fixture_id),
    ...state.animals.map(item => item.animal_id),
    ...state.collectibles.filter(item => !item.collected).map(item => item.collectible_id),
  ].sort();
}

function objectKind(state, objectId) {
  if (state.plants.some(item => item.plant_id === objectId)) return 'plant';
  if (state.fixtures.some(item => item.fixture_id === objectId)) return 'fixture';
  if (state.animals.some(item => item.animal_id === objectId)) return 'animal';
  if (state.collectibles.some(item =>
    item.collectible_id === objectId && !item.collected)) return 'collectible';
  return null;
}

function availableActions(state, objectId) {
  return {
    plant: ['inspect', 'tend'],
    fixture: ['inspect', 'move_fixture'],
    animal: ['inspect', 'feed', 'play'],
    collectible: ['inspect', 'collect'],
  }[objectKind(state, objectId)] ?? [];
}

function reject(reason) {
  return {
    accepted: false,
    changed: false,
    reason,
    summary: '',
    available_actions: [],
    details: null,
  };
}

async function finish(prior, updated, command, summary, {
  actions = [], details = null,
} = {}) {
  const final = clone(updated);
  final.command_sequence = command.sequence;
  final.processed_commands.push(command.command_id);
  final.event_trace.push({
    trace_id: await stableId('trace', prior.world_id, command.command_id),
    sequence: command.sequence,
    kind: command.kind,
    target_id: command.target_id,
    effective_time: prior.effective_time,
    summary,
  });
  return [final, {
    accepted: true,
    changed: true,
    reason: '',
    summary,
    available_actions: [...actions],
    details: details === null ? null : clone(details),
  }];
}

async function journalEntry(state, objectId, status, label, description) {
  const entry = {
    entry_id: await stableId('journal', state.world_id, objectId),
    object_id: objectId,
    status,
    label,
    description,
    discovered_at: state.effective_time,
  };
  return [
    ...state.journal.filter(item => item.object_id !== objectId),
    entry,
  ];
}

function animalTier(points, counts) {
  const diversity = Object.values(counts).filter(value => value > 0).length;
  if (points >= 40 && diversity >= 3) return 3;
  if (points >= 20 && diversity >= 2) return 2;
  if (points >= 8) return 1;
  return 0;
}

async function animalInteraction(state, source, kind) {
  const animal = clone(source);
  const sessionCount = animal.session_interactions.filter(item => item === kind).length;
  const base = { observe: 1, feed: 3, play: 4 }[kind];
  const gain = Math.max(0, base - sessionCount);
  animal.interaction_counts[kind] = (animal.interaction_counts[kind] ?? 0) + 1;
  animal.bond_points += gain;
  animal.bond_tier = animalTier(animal.bond_points, animal.interaction_counts);
  const memory = {
    memory_id: await stableId(
      'memory', state.world_id, animal.animal_id, kind,
      state.command_sequence + 1,
    ),
    kind,
    target_id: null,
    timestamp: state.effective_time,
    valence: 1,
    salience: Math.max(1, gain),
  };
  animal.session_interactions.push(kind);
  animal.recent_memories = [...animal.recent_memories, memory].slice(-16);
  if (kind === 'feed') animal.energy = Math.min(100, animal.energy + 8);
  else if (kind === 'play') {
    animal.energy = Math.max(0, animal.energy - 5);
    animal.play_appetite = Math.max(0, animal.play_appetite - 15);
  } else animal.social_appetite = Math.max(0, animal.social_appetite - 5);
  return animal;
}

async function inspect(state, targetId) {
  const updated = clone(state);
  const plant = updated.plants.find(item => item.plant_id === targetId);
  if (plant) {
    updated.journal = await journalEntry(
      state, targetId, 'observed', plant.species_id,
      'A living plant in the garden.',
    );
    return [updated, `Inspected ${plant.species_id}.`, normalizePlant(plant)];
  }
  const fixture = updated.fixtures.find(item => item.fixture_id === targetId);
  if (fixture) {
    updated.journal = await journalEntry(
      state, targetId, 'observed', fixture.catalog_id,
      'A fixture that can shape garden routines.',
    );
    return [updated, `Inspected ${fixture.catalog_id}.`, normalizeFixture(fixture)];
  }
  const animalIndex = updated.animals.findIndex(item => item.animal_id === targetId);
  if (animalIndex >= 0) {
    const animal = await animalInteraction(state, updated.animals[animalIndex], 'observe');
    updated.animals[animalIndex] = animal;
    updated.journal = await journalEntry(
      state, targetId, 'observed', animal.species_id,
      `A ${animal.species_id} sharing the garden.`,
    );
    return [updated, `Observed ${animal.species_id}.`, normalizeAnimal(animal)];
  }
  const collectible = updated.collectibles.find(item =>
    item.collectible_id === targetId && !item.collected);
  if (collectible) {
    updated.journal = await journalEntry(
      state, targetId, 'observed', collectible.label, collectible.description,
    );
    return [updated, `Observed ${collectible.label}.`, normalizeCollectible(collectible)];
  }
  return null;
}

async function collect(state, targetId) {
  const updated = clone(state);
  const item = updated.collectibles.find(candidate =>
    candidate.collectible_id === targetId);
  if (!item || item.collected) return null;
  item.collected = true;
  updated.inventory = uniqueSorted([...updated.inventory, targetId]);
  updated.journal = await journalEntry(
    state, targetId, 'collected', item.label, item.description,
  );
  return [updated, `Collected ${item.label}.`, normalizeCollectible(item)];
}

function insideWorld(state, position) {
  return position[0] >= 0 && position[0] < state.world_width &&
    position[1] >= 0 && position[1] < state.world_height;
}

function occupied(state, position, exceptId = null) {
  return [
    ...state.plants.map(item => [item.plant_id, item.position]),
    ...state.fixtures.map(item => [item.fixture_id, item.position]),
  ].some(([objectId, current]) => objectId !== exceptId &&
    current[0] === position[0] && current[1] === position[1]);
}

const cellKey = position => `${position[0]},${position[1]}`;

function fixtureCells(fixture) {
  const definition = FIXTURE_CATALOG[fixture.catalog_id];
  const cells = [];
  for (let dy = 0; dy < definition.footprint[1]; dy += 1) {
    for (let dx = 0; dx < definition.footprint[0]; dx += 1) {
      cells.push([fixture.position[0] + dx, fixture.position[1] + dy]);
    }
  }
  return cells;
}

function allFixtureCells(state, exceptId = null) {
  return new Set(state.fixtures
    .filter(item => item.fixture_id !== exceptId)
    .flatMap(fixtureCells)
    .map(cellKey));
}

function blockedCells(state) {
  const blocked = new Set(state.plants.map(item => cellKey(item.position)));
  for (const fixture of state.fixtures) {
    if (FIXTURE_CATALOG[fixture.catalog_id].blocks_movement) {
      for (const cell of fixtureCells(fixture)) blocked.add(cellKey(cell));
    }
  }
  return blocked;
}

function layoutIsSafe(state) {
  const occupiedCells = new Set();
  for (const fixture of state.fixtures) {
    if (!(fixture.catalog_id in FIXTURE_CATALOG)) return false;
    for (const cell of fixtureCells(fixture)) {
      if (!insideWorld(state, cell) || occupiedCells.has(cellKey(cell))) return false;
      occupiedCells.add(cellKey(cell));
    }
  }
  const blocked = blockedCells(state);
  const goals = [
    ...state.animals.map(item => item.position),
    ...state.collectibles.filter(item => !item.collected).map(item => item.position),
  ];
  if (goals.some(goal => blocked.has(cellKey(goal)))) return false;
  let start = null;
  for (let y = 0; y < state.world_height && start === null; y += 1) {
    for (let x = 0; x < state.world_width; x += 1) {
      if (!blocked.has(cellKey([x, y]))) {
        start = [x, y];
        break;
      }
    }
  }
  if (start === null) return goals.length === 0;
  const queue = [start];
  const reached = new Set([cellKey(start)]);
  for (let index = 0; index < queue.length; index += 1) {
    const current = queue[index];
    for (const [dx, dy] of [[1, 0], [-1, 0], [0, 1], [0, -1]]) {
      const next = [current[0] + dx, current[1] + dy];
      const key = cellKey(next);
      if (!insideWorld(state, next) || blocked.has(key) || reached.has(key)) continue;
      reached.add(key);
      queue.push(next);
    }
  }
  return goals.every(goal => reached.has(cellKey(goal)));
}

function validateFixturePlacement(
  state, catalogId, position, { fixtureId = 'candidate', exceptId = null } = {},
) {
  if (!(catalogId in FIXTURE_CATALOG)) return ['unknown fixture catalog ID'];
  const candidate = normalizeFixture({
    fixture_id: fixtureId,
    catalog_id: catalogId,
    position,
  });
  const cells = fixtureCells(candidate);
  const errors = [];
  if (cells.some(cell => !insideWorld(state, cell))) {
    errors.push('fixture footprint is outside the world');
  }
  const fixtureOccupancy = allFixtureCells(state, exceptId);
  if (cells.some(cell => fixtureOccupancy.has(cellKey(cell)))) {
    errors.push('fixture footprint overlaps another fixture');
  }
  const plantOccupancy = new Set(state.plants.map(item => cellKey(item.position)));
  if (cells.some(cell => plantOccupancy.has(cellKey(cell)))) {
    errors.push('fixture footprint overlaps a plant');
  }
  if (errors.length) return errors;
  const candidateState = clone(state);
  candidateState.fixtures = [
    ...candidateState.fixtures.filter(item => item.fixture_id !== exceptId),
    candidate,
  ];
  if (!layoutIsSafe(candidateState)) {
    errors.push('fixture placement makes the world unsafe or unreachable');
  }
  return errors;
}

/** Apply one canonical command without touching rendering or persistence APIs. */
export async function dispatchGardenCommand(sourceState, command) {
  const state = clone(sourceState);
  if (state.processed_commands.includes(command.command_id)) {
    return [state, {
      accepted: true,
      changed: false,
      reason: 'already applied',
      summary: 'Command was already applied.',
      available_actions: [],
      details: null,
    }];
  }
  const errors = validateGardenCommand(command);
  if (errors.length) return [state, reject(errors.join('; '))];
  if (command.sequence !== state.command_sequence + 1) {
    return [state, reject(`expected sequence ${state.command_sequence + 1}`)];
  }

  const kind = command.kind;
  const target = command.target_id;

  if (kind === 'move_focus') {
    const ids = objectIds(state);
    if (!ids.length) return [state, reject('world has no focusable objects')];
    const requested = command.args.target_id || target;
    let focus;
    if (requested !== null && requested !== undefined) {
      if (!ids.includes(requested)) return [state, reject('focus target does not exist')];
      focus = String(requested);
    } else {
      const current = ids.includes(state.ui.focus_id) ? ids.indexOf(state.ui.focus_id) : -1;
      const direction = String(command.args.direction ?? 'next');
      const delta = ['previous', 'left', 'up'].includes(direction) ? -1 : 1;
      focus = ids[(current + delta + ids.length) % ids.length];
    }
    const updated = clone(state);
    updated.ui.focus_id = focus;
    updated.ui.actions_open_for = null;
    return finish(state, updated, command, `Focused ${focus}.`, {
      actions: availableActions(state, focus),
    });
  }

  if (kind === 'pan') {
    const updated = clone(state);
    updated.ui.camera = [
      clamp(state.ui.camera[0] + integer(command.args.dx, 0), 0, state.world_width - 1),
      clamp(state.ui.camera[1] + integer(command.args.dy, 0), 0, state.world_height - 1),
    ];
    return finish(
      state, updated, command,
      `Panned to ${updated.ui.camera[0]},${updated.ui.camera[1]}.`,
    );
  }

  if (kind === 'inspect' || kind === 'primary_interact') {
    const chosen = target || state.ui.focus_id;
    if (!chosen) return [state, reject('no interaction target')];
    const outcome = kind === 'primary_interact' && objectKind(state, chosen) === 'collectible'
      ? await collect(state, chosen) : await inspect(state, chosen);
    if (!outcome) return [state, reject('target is not available')];
    const [updated, summary, details] = outcome;
    return finish(state, updated, command, summary, {
      actions: availableActions(updated, chosen), details,
    });
  }

  if (kind === 'open_actions') {
    const chosen = target || state.ui.focus_id;
    if (!chosen || !objectKind(state, chosen)) return [state, reject('no action target')];
    const updated = clone(state);
    updated.ui.focus_id = chosen;
    updated.ui.actions_open_for = chosen;
    updated.ui.journal_open = false;
    const actions = availableActions(state, chosen);
    return finish(state, updated, command, `Opened actions for ${chosen}.`, { actions });
  }

  if (kind === 'tend') {
    const updated = clone(state);
    const plant = updated.plants.find(item => item.plant_id === target);
    if (!plant) return [state, reject('tend target is not a plant')];
    const care = String(command.args.care_action ?? 'water');
    const gains = { observe: 0, water: 2, prune: 1, train: 2, transplant: 1 };
    if (!(care in gains)) return [state, reject('unsupported care action')];
    plant.growth_points += gains[care];
    plant.tended_count += 1;
    plant.last_tended_at = state.effective_time;
    updated.journal = await journalEntry(
      state, plant.plant_id, 'observed', plant.species_id,
      `A ${plant.species_id} tended with care.`,
    );
    return finish(state, updated, command, `Used ${care} on ${plant.species_id}.`, {
      details: normalizePlant(plant),
    });
  }

  if (kind === 'feed' || kind === 'play') {
    const updated = clone(state);
    const index = updated.animals.findIndex(item => item.animal_id === target);
    if (index < 0) return [state, reject(`${kind} target is not an animal`)];
    const animal = await animalInteraction(state, updated.animals[index], kind);
    updated.animals[index] = animal;
    return finish(state, updated, command, `Shared ${kind} with ${animal.species_id}.`, {
      details: normalizeAnimal(animal),
    });
  }

  if (kind === 'collect') {
    const outcome = await collect(state, String(target));
    if (!outcome) return [state, reject('collectible is unavailable')];
    const [updated, summary, details] = outcome;
    return finish(state, updated, command, summary, { details });
  }

  if (kind === 'place') {
    const position = [integer(command.args.x), integer(command.args.y)];
    if (!insideWorld(state, position)) return [state, reject('placement is outside the world')];
    const objectKindValue = String(command.args.object_kind ?? 'fixture');
    const catalog = String(command.args.catalog_id);
    const objectId = String(command.args.object_id ?? await stableId(
      objectKindValue, state.world_id, command.command_id,
    ));
    if (objectIds(state).includes(objectId)) return [state, reject('object ID already exists')];
    const updated = clone(state);
    updated.undo_stack.push({
      kind: objectKindValue,
      object_id: objectId,
      previous_position: null,
      previous_rotation: null,
      created: true,
    });
    let details;
    if (objectKindValue === 'fixture') {
      const placementErrors = validateFixturePlacement(
        state, catalog, position, { fixtureId: objectId },
      );
      if (placementErrors.length) return [state, reject(placementErrors.join('; '))];
      details = normalizeFixture({
        fixture_id: objectId,
        catalog_id: catalog,
        position,
        rotation: command.args.rotation ?? 0,
      });
      updated.fixtures.push(details);
    } else {
      if (occupied(state, position)) return [state, reject('placement cell is occupied')];
      const root = normalizeOrgan({
        node_id: await stableId('organ', objectId, 'root'),
        parent_id: null,
        kind: 'root',
        birth_time: state.effective_time,
        maturity_time: state.effective_time,
        final_direction: [0, -1],
        final_length: 1,
        glyph_family: 'root',
      });
      details = normalizePlant({
        plant_id: objectId,
        species_id: catalog,
        position,
        topology: [root],
      });
      updated.plants.push(details);
    }
    return finish(
      state, updated, command,
      `Placed ${catalog} at ${position[0]},${position[1]}.`, { details },
    );
  }

  if (kind === 'move_fixture') {
    const updated = clone(state);
    const fixture = updated.fixtures.find(item => item.fixture_id === target);
    if (!fixture) return [state, reject('move target is not a fixture')];
    const position = [integer(command.args.x), integer(command.args.y)];
    if (!insideWorld(state, position)) return [state, reject('move is outside the world')];
    const placementErrors = validateFixturePlacement(
      state,
      fixture.catalog_id,
      position,
      { fixtureId: fixture.fixture_id, exceptId: fixture.fixture_id },
    );
    if (placementErrors.length) return [state, reject(placementErrors.join('; '))];
    updated.undo_stack.push({
      kind: 'fixture',
      object_id: fixture.fixture_id,
      previous_position: [...fixture.position],
      previous_rotation: fixture.rotation,
      created: false,
    });
    fixture.position = position;
    fixture.rotation = rotation(command.args.rotation ?? fixture.rotation);
    return finish(
      state, updated, command,
      `Moved ${fixture.catalog_id} to ${position[0]},${position[1]}.`,
      { details: normalizeFixture(fixture) },
    );
  }

  if (kind === 'undo') {
    if (!state.undo_stack.length) return [state, reject('nothing to undo')];
    const updated = clone(state);
    const undo = updated.undo_stack.at(-1);
    if (undo.created) {
      if (undo.kind === 'fixture') {
        updated.fixtures = updated.fixtures.filter(item => item.fixture_id !== undo.object_id);
      } else {
        updated.plants = updated.plants.filter(item => item.plant_id !== undo.object_id);
      }
    } else if (undo.kind === 'fixture' && undo.previous_position !== null) {
      const fixture = updated.fixtures.find(item => item.fixture_id === undo.object_id);
      if (fixture) {
        fixture.position = [...undo.previous_position];
        fixture.rotation = undo.previous_rotation || 0;
      }
    } else return [state, reject('undo record is invalid')];
    updated.undo_stack.pop();
    return finish(
      state, updated, command,
      `Undid ${undo.kind} change for ${undo.object_id}.`,
    );
  }

  if (kind === 'open_journal') {
    const updated = clone(state);
    updated.ui.journal_open = true;
    updated.ui.actions_open_for = null;
    return finish(
      state, updated, command,
      `Opened journal with ${state.journal.length} entries.`,
      { details: { entries: state.journal.map(normalizeJournal) } },
    );
  }

  if (kind === 'pause_motion') {
    const updated = clone(state);
    updated.ui.motion_paused = Boolean(
      command.args.paused ?? !state.ui.motion_paused,
    );
    return finish(
      state, updated, command,
      updated.ui.motion_paused ? 'Motion paused.' : 'Motion resumed.',
    );
  }

  if (kind === 'back') {
    const updated = clone(state);
    let summary;
    if (updated.ui.actions_open_for !== null) {
      updated.ui.actions_open_for = null;
      summary = 'Closed actions.';
    } else if (updated.ui.journal_open) {
      updated.ui.journal_open = false;
      summary = 'Closed journal.';
    } else if (updated.ui.focus_id !== null) {
      updated.ui.focus_id = null;
      summary = 'Cleared focus.';
    } else summary = 'Already at the garden.';
    return finish(state, updated, command, summary);
  }

  return [state, reject('unsupported command')];
}

async function topologyVisibilityHash(plant, effectiveTime) {
  // Persistence intentionally sorts topology by stable node ID, so the
  // semantic visibility hash is explicitly graph-order independent too.
  const visible = plant.topology
    .filter(node => node.birth_time <= effectiveTime)
    .sort((left, right) => left.node_id.localeCompare(right.node_id))
    .map(node => {
      const duration = Math.max(1, node.maturity_time - node.birth_time);
      const maturity = Math.max(0, Math.min(
        1000, Math.floor(((effectiveTime - node.birth_time) * 1000) / duration),
      ));
      return [node.node_id, maturity, node.bloom_state];
    });
  return sha256Hex(canonicalJson(visible));
}

/** Build a read-only semantic projection; renderers may not mutate this state. */
export async function projectGardenScene(sourceState) {
  const state = deserializeWorldState(serializeWorldState(sourceState));
  const objects = [];
  for (const plant of state.plants) {
    const visible = plant.topology.filter(node => node.birth_time <= state.effective_time);
    objects.push({
      object_id: plant.plant_id, kind: 'plant',
      semantic_name: plant.species_id.replaceAll('_', ' '),
      position: [...plant.position], depth: 100, collision: true, occlusion: true,
      affordances: ['observe', 'water', 'prune', 'train', 'transplant'],
      actions: ['inspect', 'tend'],
      hotspot: { x: plant.position[0], y: plant.position[1], width: 1, height: 1 },
      semantic_state: {
        species_id: plant.species_id, visible_organ_count: visible.length,
        topology_hash: await topologyVisibilityHash(plant, state.effective_time),
        growth_points: plant.growth_points,
      },
    });
  }
  for (const fixture of state.fixtures) {
    const definition = FIXTURE_CATALOG[fixture.catalog_id];
    objects.push({
      object_id: fixture.fixture_id, kind: 'fixture', semantic_name: definition.name,
      position: [...fixture.position], depth: 100,
      collision: definition.blocks_movement, occlusion: definition.blocks_movement,
      affordances: [...definition.affordances], actions: [...definition.actions],
      hotspot: {
        x: fixture.position[0], y: fixture.position[1],
        width: definition.footprint[0], height: definition.footprint[1],
      },
      semantic_state: { catalog_id: fixture.catalog_id, rotation: fixture.rotation },
    });
  }
  for (const animal of state.animals) {
    objects.push({
      object_id: animal.animal_id, kind: 'animal', semantic_name: animal.species_id,
      position: [...animal.position], depth: 110, collision: false, occlusion: true,
      affordances: [...ANIMAL_SPECIES[animal.species_id].affinities],
      actions: ['inspect', 'feed', 'play'],
      hotspot: { x: animal.position[0], y: animal.position[1], width: 1, height: 1 },
      semantic_state: {
        species_id: animal.species_id, high_level_state: animal.high_level_state,
        intent: animal.current_intent, bond_tier: animal.bond_tier,
        choreography_locked: animal.choreography_lock !== null,
      },
    });
  }
  for (const item of state.collectibles.filter(candidate => !candidate.collected)) {
    objects.push({
      object_id: item.collectible_id, kind: 'collectible', semantic_name: item.label,
      position: [...item.position], depth: 120, collision: false, occlusion: false,
      affordances: ['discover', 'journal'], actions: ['inspect', 'collect'],
      hotspot: { x: item.position[0], y: item.position[1], width: 1, height: 1 },
      semantic_state: {
        family: item.family, provenance: item.provenance, authored: item.authored,
      },
    });
  }
  objects.sort((left, right) => left.depth - right.depth ||
    left.object_id.localeCompare(right.object_id));
  return {
    world_id: state.world_id, effective_time: state.effective_time,
    camera: [...state.ui.camera], motion_paused: state.ui.motion_paused, objects,
  };
}

/** Aggregate humane absence progress without replaying elapsed ticks. */
export async function reconcileGardenOffline(sourceState, observedWallTime, maxSummaries = 3) {
  const state = deserializeWorldState(serializeWorldState(sourceState));
  const observed = Math.max(0, integer(observedWallTime));
  const previous = state.last_observed_wall_time;
  if (previous === null) {
    state.last_observed_wall_time = observed;
    return [state, { elapsed_seconds: 0, rollback_clamped: false, summaries: [], receipt_ids: [] }];
  }
  if (observed <= previous) {
    return [state, {
      elapsed_seconds: 0, rollback_clamped: observed < previous,
      summaries: [], receipt_ids: [],
    }];
  }
  const elapsed = observed - previous;
  const start = state.effective_time;
  const end = start + elapsed;
  const changes = [];
  const receipts = [];
  for (const plant of state.plants) {
    const milestones = Math.max(0,
      Math.floor(end / Math.max(1, plant.growth_period_seconds)) -
      Math.floor(start / Math.max(1, plant.growth_period_seconds)));
    if (milestones) {
      plant.growth_points += milestones;
      changes.push([plant.plant_id, milestones]);
      receipts.push(await stableId(
        'milestone', state.world_id, 'plant-growth', plant.plant_id, start, end,
      ));
    }
  }
  for (const animal of state.animals) {
    animal.session_interactions = [];
    animal.energy = Math.max(50, animal.energy);
    animal.social_appetite = 50;
    animal.play_appetite = 50;
    animal.rest_appetite = 40;
  }
  if (state.animals.length) {
    receipts.push(await stableId('milestone', state.world_id, 'animal-return', start, end));
  }
  const available = state.collectibles.filter(item => !item.collected);
  if (available.length) {
    receipts.push(await stableId('milestone', state.world_id, 'finds-waiting', start, end));
  }
  const candidates = [
    ...changes.map(([id, count]) => [10, id,
      `A plant changed while you were away (${count} growth milestone${count === 1 ? '' : 's'}).`]),
    ...state.animals.map(animal => [20, animal.animal_id,
      `Your ${animal.species_id} is glad to see you.`]),
  ];
  if (available.length) candidates.push([30, available[0].collectible_id,
    `${available.length} garden find${available.length === 1 ? ' is' : 's are'} waiting to be noticed.`]);
  candidates.sort((left, right) => left[0] - right[0] || String(left[1]).localeCompare(String(right[1])));
  const summaries = candidates.slice(0, Math.max(0, maxSummaries)).map(item => item[2]);
  state.effective_time = end;
  state.last_observed_wall_time = observed;
  state.milestone_receipts = uniqueSorted([...state.milestone_receipts, ...receipts]);
  state.event_trace.push({
    trace_id: await stableId('trace', state.world_id, 'offline', start, end),
    sequence: state.command_sequence, kind: 'offline_reconcile', target_id: null,
    effective_time: end, summary: `Reconciled ${elapsed} seconds in aggregate.`,
  });
  return [state, {
    elapsed_seconds: elapsed, rollback_clamped: false, summaries,
    receipt_ids: receipts,
  }];
}

async function authoredPosition(state, target, kind, catalogId, requested) {
  let candidate = null;
  if (Array.isArray(requested) && requested.length === 2) candidate = requested;
  else if (requested && typeof requested === 'object' &&
    Object.hasOwn(requested, 'x') && Object.hasOwn(requested, 'y')) {
    candidate = [requested.x, requested.y];
  }
  if (candidate) {
    candidate = [
      clamp(candidate[0], 1, state.world_width - 2),
      clamp(candidate[1], 1, state.world_height - 2),
    ];
    if (kind !== 'fixture' || !validateFixturePlacement(
      state, catalogId, candidate, { fixtureId: target, exceptId: target },
    ).length) return candidate;
  }
  const occupiedCells = new Set([
    ...state.plants, ...state.fixtures, ...state.animals, ...state.collectibles,
  ].map(item => cellKey(item.position)));
  const rng = new DeterministicRng(await deriveSeed(
    state.seed, 'program', target, kind, 'position',
  ));
  for (let attempt = 0; attempt < 512; attempt += 1) {
    const value = [
      rng.randint(2, state.world_width - 3),
      rng.randint(2, state.world_height - 3),
    ];
    if (occupiedCells.has(cellKey(value))) continue;
    if (kind === 'fixture' && validateFixturePlacement(
      state, catalogId, value, { fixtureId: target, exceptId: target },
    ).length) continue;
    return value;
  }
  throw new Error(`could not place authored Garden object ${target}`);
}

function programDefinition(program, target) {
  return program.animals?.find(item => item.id === target)
    ?? program.entities?.find(item => item.id === target) ?? {};
}

function programDefinitions(program) {
  return [...(program.entities ?? []), ...(program.animals ?? [])]
    .filter(item => typeof item?.id === 'string')
    .sort((left, right) => String(left.id).localeCompare(String(right.id)));
}

const catalogLeaf = value => {
  const leaf = String(value ?? '').split('.').at(-1);
  return ({ rosebush: 'rose', sapling: 'oak' })[leaf] ?? leaf;
};

function programKind(definition) {
  const catalogId = catalogLeaf(
    definition.catalog_id ?? definition.asset_id ?? definition.species,
  );
  const rawKind = String(definition.kind ?? '');
  if (definition.species || Object.hasOwn(ANIMAL_SPECIES, catalogId)) return ['animal', catalogId];
  if (rawKind === 'plant' || Object.hasOwn(SPECIES_CATALOG, catalogId)) return ['plant', catalogId];
  if (rawKind === 'fixture' || Object.hasOwn(FIXTURE_CATALOG, catalogId)) return ['fixture', catalogId];
  return ['collectible', catalogId || 'authored_keepsake'];
}

export function seedGardenProgramState(sourceState, program) {
  const state = deserializeWorldState(serializeWorldState(sourceState));
  const programState = clone(state.program_state ?? {});
  const variables = programState.variables ??= {};
  for (const [name, value] of Object.entries(program.variables ?? {})) {
    if (!Object.hasOwn(variables, name)) variables[name] = clone(value);
  }
  const entities = programState.entities ??= {};
  for (const definition of programDefinitions(program)) {
    const target = String(definition.id);
    const slot = entities[target] ??= { id: target };
    const initial = definition.initial_state;
    if (initial && typeof initial === 'object' && !Array.isArray(initial)) {
      for (const [name, value] of Object.entries(initial)) {
        if (!Object.hasOwn(slot, name)) slot[name] = clone(value);
      }
    }
  }
  programState.applied_occurrences ??= [];
  programState.exclusive_claims ??= {};
  state.program_state = programState;
  return state;
}

function initialProgramEffects(program) {
  const effects = [];
  for (const definition of programDefinitions(program)) {
    const initial = definition.initial_state;
    if (!initial || typeof initial !== 'object' || Array.isArray(initial)) continue;
    const [kind, catalogId] = programKind(definition);
    const params = {};
    const requested = definition.position ?? definition.placement;
    if (requested !== undefined) params.position = clone(requested);
    let type = null;
    if (kind === 'animal' && initial.present === true) {
      type = 'animal.arrive';
      if (definition.routine !== undefined) params.routine = clone(definition.routine);
    } else if (kind === 'plant' && initial.planted === true) {
      type = 'plant.plant'; params.species_id = catalogId;
    } else if (['fixture', 'collectible'].includes(kind) && initial.revealed === true) {
      type = 'entity.reveal';
    }
    if (type) {
      const effect = { type, event_id: 'program.initial', target: String(definition.id) };
      if (Object.keys(params).length) effect.params = params;
      effects.push(effect);
    }
  }
  return effects;
}

function animalWithAuthoredData(animal, definition, routine = undefined) {
  const output = clone(animal);
  if (definition.personality && typeof definition.personality === 'object' &&
    !Array.isArray(definition.personality)) output.personality = normalizePersonality(definition.personality);
  output.favorite_fixture_ids = uniqueSorted(definition.favorite_places ?? []);
  output.authored_prohibitions = uniqueSorted(definition.prohibited_behaviors ?? []);
  const value = routine !== undefined ? routine : definition.routine;
  output.authored_preferences = uniqueSorted(
    Array.isArray(value) ? value : value ? [value] : [],
  );
  return output;
}

async function programJournal(state, receipt, objectId, label, description, status = 'discovered') {
  const entryId = await stableId('journal', state.world_id, receipt);
  if (!state.journal.some(item => item.entry_id === entryId)) state.journal.push(normalizeJournal({
    entry_id: entryId, object_id: objectId, status, label, description,
    discovered_at: state.effective_time,
  }));
}

function pythonJson(value) {
  if (Array.isArray(value)) return `[${value.map(pythonJson).join(', ')}]`;
  if (value && typeof value === 'object') return `{${Object.keys(value).sort().map(key =>
    `${JSON.stringify(key)}: ${pythonJson(value[key])}`).join(', ')}}`;
  return JSON.stringify(value);
}

/**
 * Materialize evaluator effects into the authoritative WorldState.
 * The evaluator owns only occurrence/variable bookkeeping; it never becomes
 * a renderer-local gameplay state. Receipts make recurring/replayed results
 * idempotent and every change is visible in canonical persistence/projection.
 */
export async function materializeGardenProgramEffects(
  sourceState, program, evaluation,
) {
  const state = seedGardenProgramState(sourceState, program);
  state.program_state = clone(evaluation.state ?? {});
  const occurrences = { 'program.initial': 'definition', ...Object.fromEntries(evaluation.trace
    .filter(row => row.status === 'applied' && row.occurrence_id)
    .map(row => [String(row.event_id), String(row.occurrence_id)])) };
  const actionIndexes = {};
  const materialized = [];
  for (const effect of [...initialProgramEffects(program), ...evaluation.effects]) {
    const eventId = String(effect.event_id);
    const index = actionIndexes[eventId] ?? 0;
    actionIndexes[eventId] = index + 1;
    const receiptId = await stableId(
      'program-receipt', state.world_id, eventId,
      occurrences[eventId] ?? 'unscheduled', index, effect,
    );
    if (state.milestone_receipts.includes(receiptId)) continue;
    const target = effect.target === undefined || effect.target === null
      ? null : String(effect.target);
    const params = clone(effect.params ?? {});
    const definition = programDefinition(program, target);
    const [kind, catalogId] = programKind(definition);
    const requested = params.position ?? definition.position ?? definition.placement;

    if (effect.type === 'animal.arrive') {
      const species = catalogLeaf(definition.species ?? definition.catalog_id ?? catalogId);
      if (Object.hasOwn(ANIMAL_SPECIES, species)) {
        const position = await authoredPosition(state, target, 'animal', species, requested);
        const personalityRng = new DeterministicRng(await deriveSeed(
          state.seed, 'animal', target, 'personality',
        ));
        let animal = normalizeAnimal({
          animal_id: target, species_id: species, position,
          personality: Object.fromEntries(PERSONALITY_FIELDS.map(field => [
            field, personalityRng.randint(20, 80),
          ])),
        });
        animal = animalWithAuthoredData(animal, definition, params.routine);
        state.animals = [...state.animals.filter(item => item.animal_id !== target), animal];
      }
    } else if (effect.type === 'animal.depart') {
      state.animals = state.animals.filter(item => item.animal_id !== target);
    } else if (effect.type.startsWith('animal.')) {
      const animal = state.animals.find(item => item.animal_id === target);
      if (animal && effect.type === 'animal.behave') {
        animal.current_intent = String(params.behavior ?? 'idle');
        animal.intent_started_at = state.effective_time;
        animal.minimum_dwell_until = state.effective_time + Math.max(0, integer(params.duration_ticks));
      } else if (animal && effect.type === 'animal.routine') {
        Object.assign(animal, animalWithAuthoredData(animal, definition, params.routine));
      } else if (animal && effect.type === 'animal.set_destination') {
        let destination = null;
        if (Array.isArray(params.position) && params.position.length === 2) destination = vec2(params.position);
        else if (params.position && typeof params.position === 'object') destination = [integer(params.position.x), integer(params.position.y)];
        if (!destination && params.fixture_id) destination = state.fixtures.find(item =>
          item.fixture_id === params.fixture_id)?.position ?? null;
        if (destination) animal.position = [...destination];
      } else if (animal && ['animal.deliver', 'animal.present_gift'].includes(effect.type)) {
        animal.choreography_lock = effect.type;
      }
      if (['animal.deliver', 'animal.present_gift'].includes(effect.type)) {
        await programJournal(state, receiptId, target, 'Authored animal moment', pythonJson(params));
      }
    } else if (effect.type === 'plant.plant') {
      const species = catalogLeaf(params.species_id ?? catalogId);
      if (Object.hasOwn(SPECIES_CATALOG, species)) {
        const position = await authoredPosition(state, target, 'plant', species, requested);
        const plant = normalizePlant({
          plant_id: target, species_id: species, position,
          topology: await generateTopology(state.seed, target, species, state.effective_time),
          growth_period_seconds: SPECIES_CATALOG[species][3],
        });
        state.plants = [...state.plants.filter(item => item.plant_id !== target), plant];
      }
    } else if (effect.type.startsWith('plant.')) {
      const plant = state.plants.find(item => item.plant_id === target);
      if (plant && effect.type === 'plant.grow') {
        const value = params.amount ?? params.stage ?? 1;
        const amount = typeof value === 'number' && !Number.isNaN(value) ? integer(value) : 1;
        plant.growth_points = Math.max(0, plant.growth_points + amount);
      } else if (plant && effect.type === 'plant.bloom') {
        plant.topology = plant.topology.map(node =>
          node.kind === 'bloom' ? { ...node, bloom_state: 'bloom' } : node);
      } else if (plant && effect.type === 'plant.prune') {
        const removed = new Set((params.node_ids ?? []).map(String));
        let changed = true;
        while (changed) {
          const before = removed.size;
          for (const node of plant.topology) if (removed.has(node.parent_id)) removed.add(node.node_id);
          changed = removed.size !== before;
        }
        plant.topology = plant.topology.filter(node => !removed.has(node.node_id));
      }
    } else if (effect.type.startsWith('entity.')) {
      if (effect.type === 'entity.retire') {
        state.fixtures = state.fixtures.filter(item => item.fixture_id !== target);
        state.plants = state.plants.filter(item => item.plant_id !== target);
        state.collectibles = state.collectibles.filter(item => item.collectible_id !== target);
      } else if (kind === 'fixture' && Object.hasOwn(FIXTURE_CATALOG, catalogId)) {
        const position = await authoredPosition(state, target, kind, catalogId, requested);
        state.fixtures = [...state.fixtures.filter(item => item.fixture_id !== target),
          normalizeFixture({ fixture_id: target, catalog_id: catalogId, position, authored: true })];
      } else if (kind === 'plant' && Object.hasOwn(SPECIES_CATALOG, catalogId)) {
        const position = await authoredPosition(state, target, kind, catalogId, requested);
        state.plants = [...state.plants.filter(item => item.plant_id !== target), normalizePlant({
          plant_id: target, species_id: catalogId, position,
          topology: await generateTopology(state.seed, target, catalogId, state.effective_time),
          growth_period_seconds: SPECIES_CATALOG[catalogId][3],
        })];
      } else {
        const position = await authoredPosition(state, target, 'collectible', catalogId, requested);
        const properties = definition.properties && typeof definition.properties === 'object'
          ? definition.properties : {};
        const label = String(properties.label ?? target);
        const rawDescription = params.state ?? properties.description ?? 'An authored garden keepsake.';
        const description = typeof rawDescription === 'string' ? rawDescription : String(rawDescription);
        state.collectibles = [...state.collectibles.filter(item => item.collectible_id !== target),
          normalizeCollectible({ collectible_id: target, family: 'authored_keepsake',
            provenance: 'author-authored', label, description, position, authored: true })];
      }
    } else if (['narrative.show', 'scene.set', 'letter.present'].includes(effect.type)) {
      const labels = { 'scene.set': 'The Garden changed', 'letter.present': 'A letter is ready' };
      const label = String(params.label ?? labels[effect.type] ?? 'Garden memory');
      const description = String(params.text ?? pythonJson(params));
      await programJournal(state, receiptId, target ?? effect.type, label, description);
    }
    state.milestone_receipts = uniqueSorted([...state.milestone_receipts, receiptId]);
    state.event_trace.push(normalizeTrace({
      trace_id: await stableId('trace', state.world_id, 'program', receiptId),
      sequence: state.command_sequence, kind: `program:${effect.type}`,
      target_id: target, effective_time: state.effective_time,
      summary: `Applied authored Garden event ${eventId}.`,
    }));
    materialized.push(receiptId);
  }
  return [deserializeWorldState(serializeWorldState(state)), materialized];
}
