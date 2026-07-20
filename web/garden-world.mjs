/**
 * Dormant browser implementation of the canonical Garden world schema.
 *
 * This module has no DOM access and is not wired into the live viewer.  It
 * mirrors the Python ``lateletter.garden.world`` schema and reducer so browser
 * adapters can prove state/trace parity before an ownership cutover.
 */

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
  bench: { footprint: [2, 1], blocks_movement: true },
  fence: { footprint: [1, 1], blocks_movement: true },
  gate: { footprint: [1, 1], blocks_movement: false },
  sundial: { footprint: [1, 1], blocks_movement: true },
  trellis: { footprint: [2, 1], blocks_movement: true },
  birdbath: { footprint: [1, 1], blocks_movement: true },
  lantern: { footprint: [1, 1], blocks_movement: true },
  pond: { footprint: [3, 2], blocks_movement: true },
  memory_shrine: { footprint: [2, 1], blocks_movement: true },
  stepping_stone: { footprint: [1, 1], blocks_movement: false },
  bridge: { footprint: [3, 1], blocks_movement: false },
  planter: { footprint: [2, 1], blocks_movement: true },
  table: { footprint: [2, 2], blocks_movement: true },
  chair: { footprint: [1, 1], blocks_movement: true },
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
