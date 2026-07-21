import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import test from 'node:test';

import { canonicalWorldJson, generateInitialWorld, projectGardenScene } from '../../web/garden-world.mjs';
import {
  GardenRuntime,
  decodeStrictBase64,
  effectiveAmbientMotion,
  inputModalityFromBrowserEvent,
  validateBrowserPbkdf2Params,
} from '../../web/garden-runtime.mjs';
import {
  evaluateGardenProgram,
  expandGardenSchedule,
  migrateAuthenticatedLegacyGifts,
  parseGardenProgram,
} from '../../web/garden-program.mjs';

const fixture = async name => JSON.parse(await readFile(
  new URL(`../garden_contract/fixtures/${name}`, import.meta.url), 'utf8',
));

test('initial generation and projection are viewport-independent', async () => {
  const left = await generateInitialWorld('garden:test', 'seed-1');
  const right = await generateInitialWorld('garden:test', 'seed-1');
  assert.equal(canonicalWorldJson(left), canonicalWorldJson(right));
  const before = canonicalWorldJson(left);
  const projection = await projectGardenScene(left);
  assert.equal(projection.objects.length, 47);
  assert.equal(canonicalWorldJson(left), before);
});

test('runtime persists exact canonical state and routes every action through reducer', async () => {
  const values = new Map();
  const runtime = await new GardenRuntime({
    worldId: 'standalone:test', seed: 'cozy', now: () => 100,
    load: async key => values.get(key) ?? null,
    save: async (key, value) => values.set(key, value),
  }).open();
  const plant = runtime.projection.objects.find(item => item.kind === 'plant');
  assert.equal((await runtime.dispatch('touch', 'move_focus', {
    args: { target_id: plant.object_id }, metadata: { pointerId: 99 },
  })).accepted, true);
  assert.equal((await runtime.dispatch('mouse', 'tend', {
    target_id: plant.object_id, args: { care_action: 'water' }, metadata: { x: 4 },
  })).accepted, true);
  assert.equal(values.get(runtime.storageKey), canonicalWorldJson(runtime.state));
  const restored = await new GardenRuntime({
    worldId: 'standalone:test', seed: 'ignored', now: () => 100,
    load: async key => values.get(key) ?? null,
    save: async (key, value) => values.set(key, value),
  }).open();
  assert.equal(canonicalWorldJson(restored.state), canonicalWorldJson(runtime.state));
});

test('runtime serializes concurrent accepted commands without losing either mutation', async () => {
  const values = new Map();
  const runtime = await new GardenRuntime({
    worldId: 'concurrent:test', seed: 'queue', now: () => 100,
    load: async key => values.get(key) ?? null,
    save: async (key, value) => {
      await new Promise(resolve => setTimeout(resolve, 2));
      values.set(key, value);
    },
  }).open();
  const animal = runtime.projection.objects.find(item => item.kind === 'animal');
  const before = runtime.state.command_sequence;
  const [feed, play] = await Promise.all([
    runtime.dispatch('mouse', 'feed', { target_id: animal.object_id }),
    runtime.dispatch('touch', 'play', { target_id: animal.object_id }),
  ]);
  assert.equal(feed.accepted, true);
  assert.equal(play.accepted, true);
  assert.equal(runtime.state.command_sequence, before + 2);
  const stored = JSON.parse(values.get(runtime.storageKey));
  assert.equal(stored.command_sequence, before + 2);
  const updated = runtime.state.animals.find(item => item.animal_id === animal.object_id);
  assert.equal(updated.interaction_counts.feed, 1);
  assert.equal(updated.interaction_counts.play, 1);
  assert.deepEqual(runtime.state.event_trace.slice(-2).map(row => row.kind), ['feed', 'play']);
});

test('browser event modality and reduced-motion policy reflect their real source', () => {
  assert.equal(inputModalityFromBrowserEvent({ type: 'click', detail: 1, pointerType: 'mouse' }),
    'mouse');
  assert.equal(inputModalityFromBrowserEvent({ type: 'click', detail: 1, pointerType: 'touch' }),
    'touch');
  assert.equal(inputModalityFromBrowserEvent({ type: 'click', detail: 0 }), 'browser_keyboard');
  assert.equal(inputModalityFromBrowserEvent({ type: 'keydown', detail: 1 }), 'browser_keyboard');
  assert.equal(effectiveAmbientMotion({ prefersReducedMotion: false, motionPaused: false }), true);
  assert.equal(effectiveAmbientMotion({ prefersReducedMotion: true, motionPaused: false }), false);
  assert.equal(effectiveAmbientMotion({ prefersReducedMotion: false, motionPaused: true }), false);
});

test('browser rejects weak, excessive, and malformed cryptographic inputs before derivation', () => {
  const params = iterations => ({ name: 'PBKDF2', hash: 'SHA-256', iterations });
  assert.equal(validateBrowserPbkdf2Params(params(600000)).iterations, 600000);
  assert.equal(validateBrowserPbkdf2Params(params(2000000)).iterations, 2000000);
  for (const iterations of [true, '600000', 599999, 2000001, 10 ** 12]) {
    assert.throws(() => validateBrowserPbkdf2Params(params(iterations)), /iterations/);
  }
  assert.throws(() => validateBrowserPbkdf2Params({ ...params(600000), extra: true }),
    /exactly/);
  assert.throws(() => validateBrowserPbkdf2Params({ ...params(600000), hash: 'sha256' }),
    /unsupported/);
  assert.equal(decodeStrictBase64('AAAAAAAAAAAAAAAAAAAAAA==', { exact: 16 }).length, 16);
  assert.throws(() => decodeStrictBase64('not base64!', { exact: 16 }), /padded base64/);
  assert.throws(() => decodeStrictBase64('AAAAAAAAAAAAAAAA', { exact: 16 }), /exactly 16/);
  assert.throws(() => decodeStrictBase64('AAAAAAAAAAAAAAAA', { minimum: 16 }), /at least 16/);
});

test('program evaluator and authenticated v1 migration match fixtures', async () => {
  const programFixture = await fixture('program_evaluation.v1.json');
  const result = await evaluateGardenProgram(
    parseGardenProgram(programFixture.program), programFixture.state, programFixture.context,
  );
  assert.equal(result.state.variables.visits_rewarded, 1);
  assert.equal(result.trace.find(row => row.event_id === 'event.fallback-return').reason,
    'exclusive_group_claimed');

  const legacy = await fixture('legacy_migration.v1.json');
  assert.throws(() => migrateAuthenticatedLegacyGifts(legacy.gifts, { authenticated: false }),
    /before bundle authentication/);
  const migrated = migrateAuthenticatedLegacyGifts(legacy.gifts, {
    authenticated: true, decrypted_sentiments: legacy.sentiments,
    message_ids: ['letter.first', 'letter.last'],
  });
  const migratedResult = await evaluateGardenProgram(migrated, { applied_occurrences: [] }, {
    seed: 7, facts: { 'visit.total': 3, 'letter.read': ['letter.first'],
      'time.local': '2027-01-01T00:00:00' },
  });
  assert.deepEqual(migratedResult.trace.filter(row => row.status === 'applied')
    .map(row => row.event_id).sort(), ['legacy.gift.flower', 'legacy.gift.rabbit']);
  const values = new Map();
  const runtime = await new GardenRuntime({
    worldId: 'bundle:legacy', seed: '7', now: () => 100,
    load: async key => values.get(key) ?? null,
    save: async (key, value) => values.set(key, value),
  }).open();
  const commandSequence = runtime.state.command_sequence;
  const processedCommands = [...runtime.state.processed_commands];
  const receipts = await runtime.materializeProgram(migrated, migratedResult);
  assert.ok(receipts.length > 0);
  assert.ok(runtime.state.animals.some(item => item.animal_id === 'legacy-entity.gift.rabbit'));
  assert.ok(runtime.state.collectibles.some(item =>
    item.collectible_id === 'legacy-entity.gift.flower'));
  assert.ok(runtime.state.journal.some(item => item.label === 'Clover'));
  assert.equal(runtime.state.command_sequence, commandSequence);
  assert.deepEqual(runtime.state.processed_commands, processedCommands);
  assert.ok(receipts.every(receipt => runtime.state.milestone_receipts.includes(receipt)));
  assert.deepEqual(await runtime.materializeProgram(migrated, migratedResult), []);
  assert.equal(values.get(runtime.storageKey), canonicalWorldJson(runtime.state));

  const parallelValues = new Map();
  const parallel = await new GardenRuntime({
    worldId: 'bundle:parallel-program', seed: '7', now: () => 100,
    load: async key => parallelValues.get(key) ?? null,
    save: async (key, value) => {
      await new Promise(resolve => setTimeout(resolve, 2));
      parallelValues.set(key, value);
    },
  }).open();
  const baseAnimal = parallel.projection.objects.find(item => item.kind === 'animal');
  const [parallelReceipts, parallelPlay] = await Promise.all([
    parallel.materializeProgram(migrated, migratedResult),
    parallel.dispatch('mouse', 'play', { target_id: baseAnimal.object_id }),
  ]);
  assert.ok(parallelReceipts.length > 0);
  assert.equal(parallelPlay.accepted, true);
  assert.ok(parallel.state.journal.some(item => item.label === 'Clover'));
  assert.equal(parallel.state.animals.find(item => item.animal_id === baseAnimal.object_id)
    .interaction_counts.play, 1);
  assert.equal(parallelValues.get(parallel.storageKey), canonicalWorldJson(parallel.state));
});

test('program cooldown state survives visits and blocks until every bound clears', async () => {
  const program = {
    version: 1, evaluator_version: 1, world_state_version: 1,
    atlas_version: 'garden-atlas-1', astronomy_catalog_version: 'bright-stars-1',
    author_timezone: 'UTC', variables: {}, entities: [], animals: [],
    events: [{ id: 'return.memory',
      conditions: { fact: 'visit.total', op: '>=', value: 1 }, schedule: null,
      occurrence: 'recurring', priority: 0, exclusive_group: null,
      cooldown: { duration_seconds: 3600, visits: 2 },
      actions: [{ type: 'narrative.show', target: null,
        params: { text: 'Welcome back.' } }],
    }],
  };
  const first = await evaluateGardenProgram(program, {}, { facts: {
    'visit.total': 1, 'time.utc': '2026-07-21T00:00:00Z',
  } });
  assert.equal(first.trace[0].status, 'applied');
  const tooSoon = await evaluateGardenProgram(program, first.state, { facts: {
    'visit.total': 2, 'time.utc': '2026-07-21T02:00:00Z',
  } });
  assert.equal(tooSoon.trace[0].reason, 'cooldown_active');
  const ready = await evaluateGardenProgram(program, tooSoon.state, { facts: {
    'visit.total': 3, 'time.utc': '2026-07-21T02:00:00Z',
  } });
  assert.equal(ready.trace[0].status, 'applied');
});

test('browser schedule resolves DST gap and fold vectors', async () => {
  const schedule = await fixture('schedule_conformance.v1.json');
  for (const vector of schedule.vectors) {
    const result = expandGardenSchedule(vector.schedule, {
      event_id: 'event.dst', last_seen_utc: vector.last_seen_utc,
      now_utc: vector.now_utc,
    });
    assert.equal(new Date(result.occurrences[0].scheduled_utc).getTime(),
      new Date(vector.expected_occurrence_utc).getTime(), vector.name);
  }
});

test('scheduled program occurrence materializes through canonical runtime once', async () => {
  const program = parseGardenProgram({
    version: 1, evaluator_version: 1, world_state_version: 1,
    atlas_version: 'garden-atlas-1', astronomy_catalog_version: 'bright-stars-1',
    author_timezone: 'UTC', variables: {}, entities: [], animals: [],
    events: [{
      id: 'scheduled.memory', conditions: { fact: 'visit.total', op: '>=', value: 1 },
      schedule: { start: '2026-01-01T09:00:00', timezone: 'UTC', recurrence: null,
        exceptions: [], missed: 'deliver_on_next_visit' },
      occurrence: 'once', priority: 0, exclusive_group: null, cooldown: null,
      actions: [{ type: 'narrative.show', target: null,
        params: { kind: 'memory', label: 'Scheduled memory', text: 'Still here.' } }],
    }],
  });
  const values = new Map();
  const runtime = await new GardenRuntime({
    worldId: 'scheduled:test', seed: 'schedule', now: () => 1_767_297_700,
    load: async key => values.get(key) ?? null,
    save: async (key, value) => values.set(key, value),
  }).open();
  const expanded = expandGardenSchedule(program.events[0].schedule, {
    event_id: 'scheduled.memory', last_seen_utc: '2025-12-31T00:00:00Z',
    now_utc: '2026-01-02T09:01:40Z',
  });
  const programState = runtime.prepareProgram(program);
  const evaluation = await evaluateGardenProgram(program, programState, {
    seed: runtime.state.seed, facts: { 'visit.total': 1 },
    eligible_occurrences: { 'scheduled.memory': expanded.occurrences[0].id },
  });
  const receipts = await runtime.materializeProgram(program, evaluation);
  assert.equal(runtime.state.journal.at(-1).label, 'Scheduled memory');
  assert.ok(receipts.length > 0);
  assert.deepEqual(await runtime.materializeProgram(program, evaluation), []);
});

test('an accepted interaction can unlock and persist an in-session authored event', async () => {
  const program = parseGardenProgram({
    version: 1, evaluator_version: 1, world_state_version: 1,
    atlas_version: 'garden-atlas-1', astronomy_catalog_version: 'bright-stars-1',
    author_timezone: 'UTC', variables: {}, entities: [], animals: [],
    events: [{
      id: 'after.feed',
      conditions: { fact: 'animal.interaction', op: 'contains', value: 'feed' },
      schedule: null, occurrence: 'once', priority: 0, exclusive_group: null,
      cooldown: null, actions: [{ type: 'narrative.show', target: null,
        params: { kind: 'memory', label: 'Shared snack', text: 'A new memory.' } }],
    }],
  });
  const values = new Map();
  const runtime = await new GardenRuntime({
    worldId: 'interaction:test', seed: 'bond', now: () => 100,
    load: async key => values.get(key) ?? null,
    save: async (key, value) => values.set(key, value),
  }).open();
  const animal = runtime.projection.objects.find(item => item.kind === 'animal');
  assert.equal((await runtime.dispatch('touch', 'feed', {
    target_id: animal.object_id, metadata: { control: 'action-sheet' },
  })).changed, true);
  const interactions = [...new Set(runtime.state.animals.flatMap(item =>
    Object.keys(item.interaction_counts)))].sort();
  const evaluation = await evaluateGardenProgram(program, runtime.prepareProgram(program), {
    seed: runtime.state.seed, facts: { 'animal.interaction': interactions },
  });
  await runtime.materializeProgram(program, evaluation);
  assert.ok(runtime.state.journal.some(item => item.label === 'Shared snack'));
  assert.equal(values.get(runtime.storageKey), canonicalWorldJson(runtime.state));
});
