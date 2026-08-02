import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import test from 'node:test';

import {
  REVIEW_PENDING_ANIMAL_SPECIES,
  REVIEW_PENDING_COLLECTIBLES,
  REVIEW_PENDING_PLANT_SPECIES,
  STARTER_ANIMAL_SPECIES,
  STARTER_COLLECTIBLES,
  STARTER_FIXTURES,
  STARTER_PLANT_SPECIES,
  canonicalWorldJson,
  generateInitialWorld,
  projectGardenScene,
} from '../../web/garden-world.mjs';
import {
  GardenRuntime,
  WORLD_STORAGE_PREFIX,
  decodeStrictBase64,
  effectiveAmbientMotion,
  inputModalityFromBrowserEvent,
  validateBrowserPbkdf2Params,
} from '../../web/garden-runtime.mjs';
import {
  compareCodePoints,
  EXCLUSIVE_LEDGER_LIMIT,
  evaluateGardenProgram,
  expandGardenSchedule,
  migrateAuthenticatedLegacyGifts,
  parseGardenProgram,
  OCCURRENCE_LEDGER_LIMIT,
  validateBundleIdentityShape,
} from '../../web/garden-program.mjs';

test('multi-year recurring and exclusive ledgers retain bounded recent idempotency plus totals', async () => {
  const program = parseGardenProgram({
    version: 1, evaluator_version: 1, world_state_version: 1,
    atlas_version: 'garden-atlas-1', astronomy_catalog_version: 'bright-stars-1',
    author_timezone: 'UTC', variables: { returns: 0 }, entities: [], animals: [],
    events: [{ id: 'event.recurring',
      conditions: { fact: 'visit.total', op: '>=', value: 1 }, schedule: null,
      occurrence: 'recurring', priority: 1, exclusive_group: 'return', cooldown: null,
      actions: [{ type: 'variable.increment', target: null,
        params: { name: 'returns', amount: 1 } }],
    }],
  });
  let state = {};
  for (let visit = 1; visit <= 700; visit += 1) {
    ({ state } = await evaluateGardenProgram(program, state, {
      facts: { 'visit.total': visit },
    }));
  }
  assert.equal(state.applied_occurrences.length, OCCURRENCE_LEDGER_LIMIT);
  assert.equal(state.exclusive_occurrences.length, EXCLUSIVE_LEDGER_LIMIT);
  assert.equal(state.applied_occurrence_total, 700);
  assert.equal(state.exclusive_occurrence_total, 700);
  assert.equal(state.variables.returns, 700);
  assert.match(state.applied_occurrences[0], /:visit:189$/);
  assert.match(state.applied_occurrences.at(-1), /:visit:700$/);
  assert.equal(state.exclusive_occurrences[0], 'return@visit:189');
  assert.equal(state.exclusive_occurrences.at(-1), 'return@visit:700');
});

test('bundle identity validation rejects traversal and duplicate IDs before persistence', () => {
  const block = 'MDEyMzQ1Njc4OWFiY2RlZg==';
  assert.doesNotThrow(() => validateBundleIdentityShape({
    version: 1,
    bundle_id: 'bundle-under_test.2',
    messages: [{ id: 'letter.one', date: '2030-01-01', ciphertext: block,
      salt: block, nonce: 'MDEyMzQ1Njc4OWFi', kdf_params: null }],
    garden_gifts: [{ id: 'gift.one', type: 'item', catalog_id: 'plate_of_food',
      trigger: { type: 'post_letter', value: 'letter.one' } }],
  }));
  assert.throws(
    () => validateBundleIdentityShape({ bundle_id: '../escape' }),
    /path-safe identifier/,
  );
  assert.throws(
    () => validateBundleIdentityShape({
      bundle_id: 'bundle', messages: [{ id: 'letter.one' }, { id: 'letter.one' }],
    }),
    /duplicates/,
  );
  assert.throws(
    () => validateBundleIdentityShape({
      bundle_id: 'bundle', garden_gifts: [{ id: 'gift.one' }, { id: 'gift.one' }],
    }),
    /duplicates/,
  );
});

test('shared unknown bundle-field vectors reject at every authenticated boundary', async () => {
  const vectors = JSON.parse(await readFile(
    new URL('../fixtures/bundle_unknown_field_vectors.json', import.meta.url),
    'utf8',
  ));
  const pbkdf2 = { name: 'PBKDF2', hash: 'SHA-256', iterations: 600000 };
  for (const vector of vectors) {
    const raw = {
      version: vector.version,
      bundle_id: 'bundle-under-test',
      author_name: 'Demo', passphrase_hint: null,
      bundle_auth_salt: 'MDEyMzQ1Njc4OWFiY2RlZg==', garden_seed: 7,
      messages: [{
        id: 'letter.one', date: '2030-01-01', ciphertext: 'eA==',
        salt: 'MDEyMzQ1Njc4OWFiY2RlZg==', nonce: 'MDEyMzQ1Njc4OWFi',
        kdf_params: { ...pbkdf2 },
      }],
      garden_gifts: [{
        id: 'gift.one', type: 'item', catalog_id: 'plate_of_food',
        sentiment_ciphertext: '', salt: '', nonce: '',
        trigger: { type: 'post_letter', value: 'letter.one' },
        placement_hint: 'random', animal_name: null, animal_collar_color: null,
      }],
      notification: { email: null, method: null }, checksum: '', hmac: '',
    };
    if (vector.version === 2) {
      raw.bundle_auth_kdf_params = { ...pbkdf2 };
      raw.garden_gifts = [];
      raw.garden_program = {
        version: 1, ciphertext: 'eA==', salt: raw.bundle_auth_salt,
        nonce: 'MDEyMzQ1Njc4OWFi', kdf_params: { ...pbkdf2 },
      };
    }
    let target = raw;
    for (const part of vector.path) target = target[part];
    target.future_extension = true;
    assert.throws(
      () => validateBundleIdentityShape(raw),
      /unknown fields/,
      vector.name,
    );
  }
});

test('shared bundle schema vectors reject every Python-invalid version structure', async () => {
  const vectors = JSON.parse(await readFile(
    new URL('../fixtures/bundle_schema_rejection_vectors.json', import.meta.url),
    'utf8',
  ));
  const kdf = { name: 'PBKDF2', hash: 'SHA-256', iterations: 600000 };
  const block = 'MDEyMzQ1Njc4OWFiY2RlZg==';
  const nonce = 'MDEyMzQ1Njc4OWFi';
  const message = () => ({ id: 'letter.one', date: '2030-01-01', ciphertext: block,
    salt: block, nonce, kdf_params: { ...kdf } });
  const gift = () => ({ id: 'gift.one', type: 'item', catalog_id: 'plate_of_food',
    sentiment_ciphertext: '', salt: '', nonce: '',
    trigger: { type: 'post_letter', value: 'letter.one' }, placement_hint: 'random',
    animal_name: null, animal_collar_color: null });
  for (const vector of vectors) {
    const raw = { version: vector.version, bundle_id: 'bundle-under-test', author_name: 'Demo',
      passphrase_hint: null, bundle_auth_salt: block, garden_seed: 7,
      messages: [message()], garden_gifts: vector.version === 2 ? [] : [gift()],
      notification: null, checksum: '', hmac: '00' };
    if (vector.version === 2) {
      raw.bundle_auth_kdf_params = { ...kdf };
      raw.garden_program = { version: 1, ciphertext: block, salt: block, nonce,
        kdf_params: { ...kdf } };
    }
    if (vector.mutation === 'add_legacy_gift') raw.garden_gifts = [gift()];
    else if (vector.mutation === 'boolean_seed') raw.garden_seed = true;
    else if (vector.mutation === 'remove_message_kdf') delete raw.messages[0].kdf_params;
    else if (vector.mutation === 'remove_message_date') delete raw.messages[0].date;
    else if (vector.mutation === 'remove_auth_kdf') delete raw.bundle_auth_kdf_params;
    else if (vector.mutation === 'remove_program') delete raw.garden_program;
    else if (vector.mutation === 'notification_array') raw.notification = [];
    else if (vector.mutation === 'unsupported_version') raw.version = 99;
    assert.throws(() => validateBundleIdentityShape(raw), /Invalid bundle identity/, vector.name);
  }
});

test('browser program safe-JSON validation rejects non-JSON runtime values', () => {
  const raw = value => ({
      version: 1, evaluator_version: 1, world_state_version: 1,
      atlas_version: 'garden-atlas-1',
      astronomy_catalog_version: 'bright-stars-1', author_timezone: 'UTC',
      variables: { memory: value }, entities: [], animals: [], events: [],
  });
  for (const value of [1n, new Map([['key', 'value']]), undefined]) {
    assert.throws(() => parseGardenProgram(raw(value)), /unsupported JSON value type/);
  }
});

test('program parser binds final references and rejects nested ethics and bad positions', async () => {
  const raw = (await fixture('program_evaluation.v1.json')).program;
  assert.doesNotThrow(() => parseGardenProgram(
    structuredClone(raw), { knownLetterIds: ['letter.future'] },
  ));
  raw.entities[0].placement = 'somewhere-ish';
  raw.events[0].actions[1].params = {
    state: { journal: ["Act now or I'll be disappointed"] },
  };
  assert.throws(
    () => parseGardenProgram(raw, { knownLetterIds: ['letter.present'] }),
    error => error.message.includes('unsupported placement hint') &&
      error.message.includes('prohibited guilt') &&
      error.message.includes('unknown bundle letter'),
  );
});

test('program ordering uses Unicode code points without locale collation', async () => {
  assert.equal(compareCodePoints('Z.event', 'a.event') < 0, true);
  const raw = (await fixture('program_evaluation.v1.json')).program;
  raw.events = raw.events.slice(0, 1).map(event => ({
    ...event, id: 'a.event', priority: 0, exclusive_group: null,
  }));
  raw.events.push({ ...structuredClone(raw.events[0]), id: 'Z.event' });
  const result = await evaluateGardenProgram(raw, {}, {
    seed: 1, facts: { 'visit.total': 3, 'season.current': 'spring', 'letter.read': [] },
  });
  assert.deepEqual(result.trace.map(row => row.event_id), ['Z.event', 'a.event']);
});

const fixture = async name => JSON.parse(await readFile(
  new URL(`../garden_contract/fixtures/${name}`, import.meta.url), 'utf8',
));

/**
 * Return a fresh key/value store that already holds a populated world.
 *
 * Many runtime tests below tend a plant, feed an animal or pick something up,
 * so they need a world that actually contains those records -- and the default
 * starter content is empty while its art waits for per-asset visual approval.
 *
 * The world is built here and written into the store, then the runtime opens
 * it. That is the ordinary restore path rather than a test-only door:
 * `GardenRuntime` opens whatever `load` hands back and only generates when
 * there is nothing stored, so putting a world in the store is how any caller
 * supplies a specific one. The runtime constructor itself takes no content
 * arguments, which keeps a test's staging needs off the product surface.
 *
 * @param worldId Identity the runtime under test will open. The storage key is
 *   derived from it exactly as the runtime derives its own, so a mismatch here
 *   would surface as the runtime generating an empty world instead of silently
 *   reading someone else's.
 * @param seed Generation seed. Pass the same value the runtime is constructed
 *   with, so the stored world is the one that runtime would have made itself.
 * @returns A `Map` suitable for the `load`/`save` closures used throughout.
 */
async function populatedStore(worldId, seed) {
  const values = new Map();
  const world = await generateInitialWorld(worldId, seed, {
    plant_species: REVIEW_PENDING_PLANT_SPECIES,
    animal_species: REVIEW_PENDING_ANIMAL_SPECIES,
    collectibles: REVIEW_PENDING_COLLECTIBLES,
  });
  values.set(`${WORLD_STORAGE_PREFIX}${worldId}`, canonicalWorldJson(world));
  return values;
}

test('initial generation and projection are viewport-independent', async () => {
  const left = await generateInitialWorld('garden:test', 'seed-1');
  const right = await generateInitialWorld('garden:test', 'seed-1');
  assert.equal(canonicalWorldJson(left), canonicalWorldJson(right));
  const before = canonicalWorldJson(left);
  const projection = await projectGardenScene(left);
  assert.equal(projection.objects.length,
    STARTER_FIXTURES.length + STARTER_PLANT_SPECIES.length +
    STARTER_COLLECTIBLES.length + STARTER_ANIMAL_SPECIES.length);
  for (const plant of left.plants) {
    const visibleCount = plant.topology.filter(node => node.birth_time <= 0).length;
    assert.ok(visibleCount >= 4 && visibleCount < plant.topology.length);
  }
  assert.equal(canonicalWorldJson(left), before);
});

test('runtime persists exact canonical state and routes every action through reducer', async () => {
  const values = await populatedStore('standalone:test', 'cozy');
  const runtime = await new GardenRuntime({
    worldId: 'standalone:test', seed: 'cozy', now: () => 100,
    load: async key => values.get(key) ?? null,
    save: async (key, value) => values.set(key, value),
  }).open({ composition: 'accept_restored' });
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
  }).open({ composition: 'accept_restored' });
  assert.equal(canonicalWorldJson(restored.state), canonicalWorldJson(runtime.state));
});

test('runtime serializes concurrent accepted commands without losing either mutation', async () => {
  const values = await populatedStore('concurrent:test', 'queue');
  const runtime = await new GardenRuntime({
    worldId: 'concurrent:test', seed: 'queue', now: () => 100,
    load: async key => values.get(key) ?? null,
    save: async (key, value) => {
      await new Promise(resolve => setTimeout(resolve, 2));
      values.set(key, value);
    },
  }).open({ composition: 'accept_restored' });
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
  const values = await populatedStore('bundle:legacy', '7');
  const runtime = await new GardenRuntime({
    worldId: 'bundle:legacy', seed: '7', now: () => 100,
    load: async key => values.get(key) ?? null,
    save: async (key, value) => values.set(key, value),
  }).open({ composition: 'accept_restored' });
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
  }).open({ composition: 'accept_restored' });
  const authoredAnimalId = 'legacy-entity.gift.rabbit';
  const [parallelReceipts, parallelPlay] = await Promise.all([
    parallel.materializeProgram(migrated, migratedResult),
    parallel.dispatch('mouse', 'play', { target_id: authoredAnimalId }),
  ]);
  assert.ok(parallelReceipts.length > 0);
  assert.equal(parallelPlay.accepted, true);
  assert.ok(parallel.state.journal.some(item => item.label === 'Clover'));
  assert.equal(parallel.state.animals.find(item => item.animal_id === authoredAnimalId)
    .interaction_counts.play, 1);
  assert.equal(parallelValues.get(parallel.storageKey), canonicalWorldJson(parallel.state));
});

test('authenticated v1 plant aliases canonicalize without weakening authored programs', () => {
  const migrated = migrateAuthenticatedLegacyGifts([{
    id: 'gift.rose', type: 'plant', catalog_id: 'rosebush',
    placement_hint: 'random', trigger: { type: 'cumulative_visits', value: '1' },
  }], { authenticated: true });
  assert.equal(migrated.entities[0].catalog_id, 'rose');
  assert.equal(migrated.events[0].actions[0].params.species_id, 'rose');
  assert.throws(() => parseGardenProgram({
    version: 1, evaluator_version: 1, world_state_version: 1,
    atlas_version: 'garden-atlas-1', astronomy_catalog_version: 'bright-stars-1',
    author_timezone: 'UTC', variables: {}, animals: [], events: [],
    entities: [{ id: 'authored.rose', kind: 'plant', catalog_id: 'rosebush',
      initial_state: { planted: false } }],
  }), /unknown runtime plant asset/);
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

test('letter presentation and missed summaries persist canonically only after apply', async () => {
  const program = parseGardenProgram({
    version: 1, evaluator_version: 1, world_state_version: 1,
    atlas_version: 'garden-atlas-1', astronomy_catalog_version: 'bright-stars-1',
    author_timezone: 'UTC', variables: {}, entities: [], animals: [],
    events: [{ id: 'present.future', conditions: { fact: 'visit.total', op: '>=', value: 2 },
      schedule: null, occurrence: 'once', priority: 0, exclusive_group: null, cooldown: null,
      actions: [{ type: 'letter.present', target: null, params: { letter_id: 'letter.future' } }],
    }],
  });
  const summary = [{ event_id: 'present.future', occurrence_id: 'present.future:once',
    missed_count: 999, catch_up_truncated: true }];
  const blocked = await evaluateGardenProgram(program, {}, {
    facts: { 'visit.total': 1 }, missed_event_summaries: summary,
  });
  assert.deepEqual(blocked.state.presented_letters, undefined);
  assert.deepEqual(blocked.state.missed_event_summaries, undefined);
  const applied = await evaluateGardenProgram(program, blocked.state, {
    facts: { 'visit.total': 2 }, missed_event_summaries: summary,
  });
  assert.deepEqual(applied.state.presented_letters, undefined);
  const values = await populatedStore('letter-present:test', 'future');
  const runtime = await new GardenRuntime({
    worldId: 'letter-present:test', seed: 'future', now: () => 100,
    load: async key => values.get(key) ?? null,
    save: async (key, value) => values.set(key, value),
  }).open({ composition: 'accept_restored' });
  await runtime.materializeProgram(program, applied);
  assert.deepEqual(runtime.state.program_state.presented_letters, ['letter.future']);
  assert.ok(runtime.state.journal.some(entry => entry.object_id === 'letter.future'));
  assert.deepEqual(runtime.state.program_state.missed_event_summaries, [{
    event_id: 'present.future', occurrence_id: 'present.future:once',
    missed_count: 400, catch_up_truncated: true,
  }]);
  assert.match(runtime.sceneSummary(), /While you were away: present\.future: 400 missed occurrences; catch-up truncated\./);
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
  const values = await populatedStore('scheduled:test', 'schedule');
  const runtime = await new GardenRuntime({
    worldId: 'scheduled:test', seed: 'schedule', now: () => 1_767_297_700,
    load: async key => values.get(key) ?? null,
    save: async (key, value) => values.set(key, value),
  }).open({ composition: 'accept_restored' });
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

test('authenticated program roster replaces sandbox animals before absence reconciliation', async () => {
  const program = parseGardenProgram({
    version: 1, evaluator_version: 1, world_state_version: 1,
    atlas_version: 'garden-atlas-1', astronomy_catalog_version: 'bright-stars-1',
    author_timezone: 'UTC', variables: {}, entities: [], animals: [], events: [],
  });
  // Seeded with animals on purpose: this test is about an authenticated
  // program REPLACING a sandbox roster, so an empty world would let it pass
  // without ever replacing anything.
  const values = await populatedStore('roster:test', 'sandbox');
  const sandbox = await new GardenRuntime({
    worldId: 'roster:test', seed: 'sandbox', now: () => 100,
    load: async key => values.get(key) ?? null,
    save: async (key, value) => values.set(key, value),
  }).open({ composition: 'accept_restored' });
  assert.ok(sandbox.state.animals.length > 0);
  const authenticated = await new GardenRuntime({
    worldId: 'roster:test', seed: 'sandbox', program, now: () => 200,
    load: async key => values.get(key) ?? null,
    save: async (key, value) => values.set(key, value),
  }).open({ composition: 'accept_restored' });
  assert.deepEqual(authenticated.state.animals, []);
  assert.equal((authenticated.state.program_state.absence_summary ?? [])
    .some(summary => summary.startsWith('Your ')), false);
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
  const values = await populatedStore('interaction:test', 'bond');
  const runtime = await new GardenRuntime({
    worldId: 'interaction:test', seed: 'bond', now: () => 100,
    load: async key => values.get(key) ?? null,
    save: async (key, value) => values.set(key, value),
  }).open({ composition: 'accept_restored' });
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

test('runtime live tick persists projection changes and honors canonical pause', async () => {
  const values = await populatedStore('live:test', 'dwell');
  const runtime = await new GardenRuntime({
    worldId: 'live:test', seed: 'dwell', now: () => 100,
    load: async key => values.get(key) ?? null,
    save: async (key, value) => values.set(key, value),
  }).open({ composition: 'accept_restored' });
  const before = runtime.state.effective_time;
  assert.equal(await runtime.tickLive(30), true);
  assert.equal(runtime.state.effective_time, before + 30);
  assert.ok(runtime.state.event_trace.some(entry => entry.kind === 'live_tick'));
  assert.equal(values.get(runtime.storageKey), canonicalWorldJson(runtime.state));
  runtime.state.ui.motion_paused = true;
  const pausedWatermark = runtime.state.last_observed_wall_time;
  assert.equal(await runtime.tickLive(30), true);
  assert.equal(runtime.state.effective_time, before + 30);
  assert.equal(runtime.state.last_observed_wall_time, pausedWatermark + 30);
});

test('resuming canonical pause discards its wall interval instead of replaying it', async () => {
  let now = 100;
  const runtime = await new GardenRuntime({
    worldId: 'live:pause-resume', seed: 'pause', now: () => now,
    load: async () => null, save: async () => {},
  }).open({ composition: 'accept_restored' });
  const before = runtime.state.effective_time;
  await runtime.dispatch('browser_keyboard', 'pause_motion', { args: { paused: true } });
  now = 700;
  await runtime.dispatch('browser_keyboard', 'pause_motion', { args: { paused: false } });
  assert.equal(runtime.state.effective_time, before);
  assert.equal(runtime.state.last_observed_wall_time, 700);
});

test('live runtime coalesces ambient writes and supports one-write authenticated commit', async () => {
  const values = new Map();
  const saves = [];
  let now = 100;
  const runtime = await new GardenRuntime({
    worldId: 'live:coalesced', seed: 'dwell', now: () => now,
    load: async key => values.get(key) ?? null,
    save: async (key, value) => { values.set(key, value); saves.push(value); },
  }).open({ composition: 'accept_restored' });
  assert.equal(saves.length, 1);
  runtime.liveObserved = 100;
  for (now = 101; now <= 104; now += 1) assert.equal(await runtime.tickLive(), true);
  assert.equal(saves.length, 1);
  now = 105;
  assert.equal(await runtime.tickLive(), true);
  assert.equal(saves.length, 2);
  assert.equal(values.get(runtime.storageKey), canonicalWorldJson(runtime.state));

  const transactionalSaves = [];
  const transactional = await new GardenRuntime({
    worldId: 'live:transaction', seed: 'auth', now: () => 100,
    load: async () => null,
    save: async (_key, value) => transactionalSaves.push(value),
  }).open({ persist: false, composition: 'accept_restored' });
  assert.equal(transactionalSaves.length, 0);
  await assert.rejects(transactional.materializeProgram({
    version: 1, evaluator_version: 1, world_state_version: 1,
    atlas_version: 'garden-atlas-1', astronomy_catalog_version: 'bright-stars-1',
    author_timezone: 'UTC', variables: {}, animals: [], events: [],
    entities: [{ id: 'fixture:unsafe', kind: 'fixture', catalog_id: 'bench',
      position: [9999, 9999], initial_state: { revealed: true } }],
  }, { state: {}, trace: [], effects: [] }), /unsafe authored position/);
  assert.equal(transactionalSaves.length, 0);
  assert.equal(await transactional.tickLive(30), true);
  assert.equal(transactionalSaves.length, 0);
  await transactional.commitPersistence();
  assert.equal(transactionalSaves.length, 1);
  assert.equal(transactionalSaves[0], canonicalWorldJson(transactional.state));
});

test('runtime invalidation cancels an in-flight open and every deferred force commit', async () => {
  let releaseLoad;
  const saves = [];
  const runtime = new GardenRuntime({
    worldId: 'auth:cancelled', seed: 'secret', now: () => 100,
    load: async () => new Promise(resolve => { releaseLoad = resolve; }),
    save: async (_key, value) => saves.push(value),
  });
  const opening = runtime.open({ persist: false, composition: 'accept_restored' });
  await Promise.resolve();
  assert.equal(typeof releaseLoad, 'function');
  runtime.invalidate();
  releaseLoad(null);
  await assert.rejects(opening, /invalidated/);
  assert.equal(runtime.state, null);
  assert.equal(runtime.projection, null);
  assert.equal(saves.length, 0);
  await assert.rejects(runtime.commitPersistence(), /invalidated/);
  assert.equal(saves.length, 0);
});

test('runtime invalidation aborts an already-started authenticated save before commit', async () => {
  let saveStarted;
  const started = new Promise(resolve => { saveStarted = resolve; });
  const committed = [];
  const runtime = await new GardenRuntime({
    worldId: 'auth:save-cancelled', seed: 'secret', now: () => 100,
    load: async () => null,
    save: async (_key, value, { signal } = {}) => {
      saveStarted();
      await new Promise((resolve, reject) => {
        if (signal?.aborted) { reject(signal.reason); return; }
        signal?.addEventListener('abort', () => reject(signal.reason), { once: true });
      });
      committed.push(value);
    },
  }).open({ persist: false, composition: 'accept_restored' });
  const commit = runtime.commitPersistence();
  await started;
  runtime.invalidate();
  await assert.rejects(commit);
  assert.equal(committed.length, 0);
  assert.equal(runtime.state, null);
});
