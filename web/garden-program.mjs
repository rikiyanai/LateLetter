/** Authenticated Garden program parsing, migration, schedules, and evaluation. */

import { canonicalJson, sha256Hex } from './garden-input.mjs';
import { gardenCatalogHas } from './garden-world.mjs';

const FACTS = new Set([
  'time.utc', 'time.local', 'date.range', 'season.current', 'visit.total',
  'visit.nth', 'absence.days', 'session.duration_seconds', 'letter.due',
  'letter.read', 'gift.revealed', 'gift.examined', 'event.completed',
  'animal.arrived', 'animal.bond_tier', 'animal.interaction', 'animal.memory',
  'plant.growth_stage', 'plant.bloom', 'fixture.present', 'probability.seeded',
]);
const OPS = new Set(['==', '!=', '>', '>=', '<', '<=', 'contains',
  'not_contains', 'in', 'not_in', 'exists']);
const ACTIONS = new Set([
  'letter.present', 'entity.reveal', 'entity.place', 'entity.move',
  'entity.transform', 'entity.retire', 'animal.arrive', 'animal.depart',
  'animal.behave', 'animal.routine', 'animal.set_destination', 'animal.deliver',
  'animal.present_gift', 'plant.plant', 'plant.grow', 'plant.bloom',
  'plant.dormancy', 'plant.prune', 'plant.revive', 'scene.set',
  'narrative.show', 'variable.set', 'variable.increment', 'event.complete',
]);
const ID = /^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$/;
const clone = value => JSON.parse(canonicalJson(value));
const REQUIRED_PARAMS = Object.freeze({
  'letter.present': [['letter_id']],
  'entity.place': [['position']],
  'entity.move': [['position']],
  'animal.behave': [['behavior']],
  'animal.routine': [['routine']],
  'animal.set_destination': [['position'], ['fixture_id']],
  'animal.deliver': [['entity_id']],
  'animal.present_gift': [['gift_id']],
  'plant.plant': [['species_id']],
  'plant.grow': [['stage'], ['amount']],
  'plant.prune': [['node_ids']],
  'narrative.show': [['text']],
  'variable.set': [['name', 'value']],
});

export function parseGardenProgram(raw) {
  const errors = [];
  if (!raw || typeof raw !== 'object' || Array.isArray(raw)) {
    throw new Error('Invalid garden program: $: program must be an object');
  }
  const allowedTop = new Set(['version', 'evaluator_version', 'world_state_version',
    'atlas_version', 'astronomy_catalog_version', 'author_timezone', 'variables',
    'entities', 'animals', 'events']);
  for (const key of Object.keys(raw)) if (!allowedTop.has(key)) errors.push(`$: unknown fields ${key}`);
  if (raw.version !== 1) errors.push('$.version: expected 1');
  if ((raw.evaluator_version ?? 1) !== 1) errors.push('$.evaluator_version: expected 1');
  if ((raw.world_state_version ?? 1) !== 1) errors.push('$.world_state_version: expected 1');
  if (typeof raw.author_timezone !== 'string') errors.push('$.author_timezone: expected timezone');
  const objectIds = new Set();
  for (const [field, values] of [['entities', raw.entities], ['animals', raw.animals]]) {
    if (!Array.isArray(values)) { errors.push(`$.${field}: must be a list`); continue; }
    values.forEach((item, index) => {
      const path = `$.${field}[${index}]`;
      if (!item || typeof item !== 'object' || Array.isArray(item)) { errors.push(`${path}: must be an object`); return; }
      if (!ID.test(item.id ?? '')) errors.push(`${path}.id: invalid stable identifier`);
      else if (objectIds.has(item.id)) errors.push(`${path}.id: duplicate world identifier ${item.id}`);
      else objectIds.add(item.id);
      const catalog = item.species ?? item.catalog_id ?? item.asset_id;
      if (field === 'animals') {
        if (!gardenCatalogHas('animal', catalog)) errors.push(`${path}.species: unknown runtime animal species`);
        if (item.name != null && (typeof item.name !== 'string' || !item.name)) errors.push(`${path}.name: must be non-empty text`);
        if (item.personality != null && typeof item.personality !== 'string' &&
          (!item.personality || typeof item.personality !== 'object' || Array.isArray(item.personality))) errors.push(`${path}.personality: expected prose or a trait object`);
      } else if (item.kind === 'fixture' && !gardenCatalogHas('fixture', catalog)) errors.push(`${path}: unknown runtime fixture asset`);
      else if (item.kind === 'plant' && !gardenCatalogHas('plant', catalog)) errors.push(`${path}: unknown runtime plant asset`);
    });
  }
  const eventIds = new Set();
  const events = Array.isArray(raw.events) ? raw.events.map((event, index) => {
    const path = `$.events[${index}]`;
    if (!event || typeof event !== 'object' || !ID.test(event.id ?? '')) errors.push(`${path}.id: invalid stable identifier`);
    if (eventIds.has(event.id)) errors.push(`${path}.id: duplicate identifier ${event.id}`);
    eventIds.add(event.id);
    validateCondition(event.conditions, `${path}.conditions`, errors, 0);
    const actions = Array.isArray(event.actions) ? event.actions : [];
    for (let actionIndex = 0; actionIndex < actions.length; actionIndex += 1) {
      const action = actions[actionIndex];
      if (!ACTIONS.has(action?.type)) errors.push(`${path}.actions[${actionIndex}].type: unsupported action`);
      if (/^(entity|animal|plant)\./.test(action?.type ?? '') && !ID.test(action?.target ?? '')) {
        errors.push(`${path}.actions[${actionIndex}].target: required`);
      }
      if (/^(entity|animal|plant)\./.test(action?.type ?? '') &&
        ID.test(action?.target ?? '') && !objectIds.has(action.target)) {
        errors.push(`${path}.actions[${actionIndex}].target: unknown world object`);
      }
      const requiredChoices = REQUIRED_PARAMS[action?.type] ?? [];
      const params = action?.params ?? {};
      if (requiredChoices.length && !requiredChoices.some(choice => choice.every(key => Object.hasOwn(params, key)))) {
        errors.push(`${path}.actions[${actionIndex}].params: missing required parameters`);
      }
      if (action?.type === 'scene.set' && Object.keys(params).length === 0) errors.push(`${path}.actions[${actionIndex}].params: scene.set requires at least one scene field`);
      if (action?.type === 'plant.prune' && !Array.isArray(params.node_ids)) errors.push(`${path}.actions[${actionIndex}].params.node_ids: must be a list`);
      for (const key of ['letter_id', 'event_id', 'fixture_id', 'entity_id', 'gift_id']) {
        if (Object.hasOwn(params, key) && !ID.test(params[key] ?? '')) errors.push(`${path}.actions[${actionIndex}].params.${key}: invalid stable reference`);
      }
      for (const key of ['fixture_id', 'entity_id', 'gift_id']) {
        if (params[key] != null && !objectIds.has(params[key])) errors.push(`${path}.actions[${actionIndex}].params.${key}: unknown world object`);
      }
      rejectUnsafe(action?.params ?? {}, `${path}.actions[${actionIndex}].params`, errors);
    }
    if (!['once', 'recurring'].includes(event.occurrence ?? 'once')) errors.push(`${path}.occurrence: expected once or recurring`);
    if (event.schedule !== null && event.schedule !== undefined) {
      try { parseGardenSchedule(event.schedule); } catch (error) { errors.push(`${path}.schedule: ${error.message}`); }
    }
    if (event.cooldown != null) {
      if (!event.cooldown || typeof event.cooldown !== 'object' || Array.isArray(event.cooldown) || !Object.keys(event.cooldown).length) errors.push(`${path}.cooldown: expected a non-empty object`);
      else for (const [key, value] of Object.entries(event.cooldown)) {
        if (!['duration_seconds', 'visits'].includes(key)) errors.push(`${path}.cooldown: unknown field ${key}`);
        if (!Number.isInteger(value) || value < 1 || value > 31536000) errors.push(`${path}.cooldown.${key}: expected integer from 1 to 31536000`);
      }
    }
    return clone({ ...event, actions });
  }) : [];
  if (!Array.isArray(raw.events)) errors.push('$.events: must be a list');
  if (errors.length) throw new Error(`Invalid garden program: ${errors.join('; ')}`);
  return clone({
    version: 1, evaluator_version: raw.evaluator_version ?? 1,
    world_state_version: raw.world_state_version ?? 1,
    atlas_version: raw.atlas_version ?? 'garden-atlas-1',
    astronomy_catalog_version: raw.astronomy_catalog_version ?? 'bright-stars-1',
    author_timezone: raw.author_timezone, variables: raw.variables ?? {},
    entities: raw.entities ?? [], animals: raw.animals ?? [], events,
  });
}

function rejectUnsafe(value, path, errors, depth = 0) {
  if (depth > 20) { errors.push(`${path}: nesting is too deep`); return; }
  if (typeof value === 'string') {
    if (/[\x00-\x08\x0b\x0c\x0e-\x1f\x1b]/.test(value)) errors.push(`${path}: control characters are forbidden`);
    if (/(?:https?|ftp|data|javascript):/i.test(value)) errors.push(`${path}: remote or executable URLs are forbidden`);
  } else if (typeof value === 'number' && !Number.isFinite(value)) errors.push(`${path}: non-finite numbers are forbidden`);
  else if (Array.isArray(value)) value.forEach((item, index) => rejectUnsafe(item, `${path}[${index}]`, errors, depth + 1));
  else if (value && typeof value === 'object') Object.entries(value).forEach(([key, item]) => rejectUnsafe(item, `${path}.${key}`, errors, depth + 1));
}

function validateCondition(value, path, errors, depth) {
  if (depth > 16) { errors.push(`${path}: condition depth exceeds 16`); return; }
  if (!value || typeof value !== 'object' || Array.isArray(value)) { errors.push(`${path}: condition must be an object`); return; }
  const logical = ['all', 'any', 'not'].filter(key => key in value);
  if (logical.length) {
    if (logical.length !== 1 || Object.keys(value).length !== 1) errors.push(`${path}: use exactly one of all, any, or not`);
    const kind = logical[0];
    const children = kind === 'not' ? [value[kind]] : value[kind];
    if (!Array.isArray(children) || (!children.length && kind !== 'not')) { errors.push(`${path}.${kind}: must be a non-empty list`); return; }
    children.forEach((child, index) => validateCondition(child, `${path}.${kind}[${index}]`, errors, depth + 1));
    return;
  }
  if (!FACTS.has(value.fact)) errors.push(`${path}.fact: unsupported fact`);
  if (!OPS.has(value.op)) errors.push(`${path}.op: unsupported operator`);
  if (value.op !== 'exists' && !('value' in value) && !('ref' in value)) errors.push(`${path}: comparison needs value or ref`);
}

function lookup(mapping, dotted) {
  if (Object.hasOwn(mapping, dotted)) return [true, mapping[dotted]];
  let current = mapping;
  for (const part of dotted.split('.')) {
    if (!current || typeof current !== 'object' || !Object.hasOwn(current, part)) return [false, null];
    current = current[part];
  }
  return [true, current];
}

function compare(observed, op, expected, exists) {
  if (op === 'exists') return expected === undefined || expected === null ? exists : exists === Boolean(expected);
  if (!exists) return false;
  if (op === '==') return canonicalJson(observed) === canonicalJson(expected);
  if (op === '!=') return canonicalJson(observed) !== canonicalJson(expected);
  if (['>', '>=', '<', '<='].includes(op)) {
    if (typeof observed !== typeof expected || !['number', 'string'].includes(typeof observed)) return false;
    return ({ '>': observed > expected, '>=': observed >= expected, '<': observed < expected, '<=': observed <= expected })[op];
  }
  let includes = false;
  if (typeof observed === 'string' || Array.isArray(observed)) includes = observed.includes(expected);
  else if (observed && typeof observed === 'object') includes = Object.hasOwn(observed, expected);
  if (op === 'contains') return includes;
  if (op === 'not_contains') return !includes;
  const inside = typeof expected === 'string' || Array.isArray(expected)
    ? expected.includes(observed) : Boolean(expected && typeof expected === 'object' && Object.hasOwn(expected, observed));
  return op === 'in' ? inside : op === 'not_in' ? !inside : false;
}

async function probability(seed, eventId, occurrenceId) {
  const material = `garden-probability-v1\0${seed}\0${eventId}\0${occurrenceId}`;
  const digest = await sha256Hex(material);
  return Number(BigInt(`0x${digest.slice(0, 16)}`)) / 2 ** 64;
}

export async function evaluateGardenCondition(condition, facts, options = {}) {
  const kind = ['all', 'any', 'not'].find(key => key in condition);
  if (kind) {
    const children = kind === 'not' ? [condition.not] : condition[kind];
    const evaluated = [];
    for (const child of children) evaluated.push(await evaluateGardenCondition(child, facts, options));
    const values = evaluated.map(item => item[0]);
    const result = kind === 'all' ? values.every(Boolean) : kind === 'any' ? values.some(Boolean) : !values[0];
    return [result, { kind, result, children: evaluated.map(item => item[1]) }];
  }
  let exists; let observed;
  if (condition.fact === 'probability.seeded') {
    exists = true;
    observed = await probability(options.seed ?? 0, options.event_id ?? '', options.occurrence_id ?? '');
  } else [exists, observed] = lookup(facts, condition.fact ?? '');
  const expected = condition.ref ?? condition.value;
  const result = compare(observed, condition.op ?? '', expected, exists);
  return [result, { kind: 'leaf', fact: condition.fact, op: condition.op,
    expected: clone(expected ?? null), observed: clone(observed ?? null), exists, result }];
}

function applyAction(action, state, eventId, effects) {
  const params = clone(action.params ?? {});
  const effect = { type: action.type, event_id: eventId };
  if (action.target !== null && action.target !== undefined) effect.target = action.target;
  if (Object.keys(params).length) effect.params = params;
  if (action.type === 'variable.set') (state.variables ??= {})[params.name] = clone(params.value ?? null);
  else if (action.type === 'variable.increment') {
    const variables = state.variables ??= {};
    variables[params.name] = (variables[params.name] ?? 0) + (params.amount ?? 1);
  } else if (action.type === 'event.complete') {
    const completed = state.completed_events ??= [];
    const id = params.event_id ?? eventId;
    if (!completed.includes(id)) completed.push(id);
    completed.sort();
  } else if (/^(entity|animal|plant)\./.test(action.type)) {
    const entity = (state.entities ??= {})[action.target] ??= { id: action.target };
    if (action.type.endsWith('.reveal')) entity.revealed = true;
    else if (action.type.endsWith('.retire')) entity.retired = true;
    else if (action.type.endsWith('.place') || action.type.endsWith('.move')) entity.position = clone(params.position);
    else if (action.type === 'animal.arrive') Object.assign(entity, { present: true }, params);
    else if (action.type === 'animal.depart') entity.present = false;
    else if (action.type === 'plant.plant') Object.assign(entity, params, { planted: true });
    else if (action.type === 'plant.grow') Object.assign(entity, params);
    else if (action.type === 'plant.bloom') Object.assign(entity, params, { blooming: true });
    else if (action.type === 'plant.dormancy') entity.dormant = Boolean(params.dormant ?? true);
    else if (action.type === 'plant.prune') entity.pruned_node_ids = clone(params.node_ids ?? []);
    else if (action.type === 'plant.revive') Object.assign(entity, { dormant: false, revived: true });
    else entity.directive = { type: action.type, ...params };
  }
  effects.push(effect);
}

export async function evaluateGardenProgram(programInput, stateInput, contextInput) {
  const program = parseGardenProgram(programInput);
  const state = clone(stateInput); const context = clone(contextInput);
  const ledger = state.applied_occurrences ??= [];
  const applied = new Set(ledger);
  const claims = state.exclusive_claims ??= {};
  const cooldowns = state.event_cooldowns ??= {};
  const effects = []; const trace = [];
  const events = [...program.events].sort((left, right) =>
    (right.priority ?? 0) - (left.priority ?? 0) || left.id.localeCompare(right.id));
  for (const event of events) {
    let occurrenceId = event.schedule == null
      ? event.occurrence === 'recurring'
        ? Number.isInteger(context.facts?.['visit.total'])
          ? `${event.id}:visit:${context.facts['visit.total']}`
          : `${event.id}:time:${context.facts?.['time.utc'] ?? 'unknown'}`
        : `${event.id}:once`
      : context.eligible_occurrences?.[event.id];
    if (occurrenceId === true) occurrenceId = `${event.id}:scheduled`;
    const row = { event_id: event.id, priority: event.priority ?? 0,
      exclusive_group: event.exclusive_group ?? null, occurrence_id: occurrenceId ?? null };
    if (!occurrenceId) { trace.push({ ...row, status: 'blocked', reason: 'schedule_not_eligible' }); continue; }
    const ledgerId = `${event.id}@${occurrenceId}`;
    if (applied.has(ledgerId)) { trace.push({ ...row, status: 'skipped', reason: 'already_applied' }); continue; }
    if (event.exclusive_group && Object.hasOwn(claims, event.exclusive_group)) { trace.push({ ...row, status: 'blocked', reason: 'exclusive_group_claimed' }); continue; }
    const priorCooldown = cooldowns[event.id];
    if (event.cooldown && priorCooldown) {
      const nowMs = Date.parse(context.facts?.['time.utc'] ?? '');
      const visit = context.facts?.['visit.total'];
      const blockedByTime = Number.isFinite(nowMs) && Number.isInteger(priorCooldown.time_utc_seconds) &&
        event.cooldown.duration_seconds != null && Math.floor(nowMs / 1000) - priorCooldown.time_utc_seconds < event.cooldown.duration_seconds;
      const blockedByVisit = Number.isInteger(visit) && Number.isInteger(priorCooldown.visit_total) &&
        event.cooldown.visits != null && visit - priorCooldown.visit_total < event.cooldown.visits;
      if (blockedByTime || blockedByVisit) { trace.push({ ...row, status: 'blocked', reason: 'cooldown_active' }); continue; }
    }
    const [eligible, conditions] = await evaluateGardenCondition(event.conditions, context.facts ?? {}, {
      seed: context.seed ?? 0, event_id: event.id, occurrence_id: occurrenceId,
    });
    if (!eligible) { trace.push({ ...row, conditions, status: 'blocked', reason: 'conditions_false' }); continue; }
    for (const action of event.actions) applyAction(action, state, event.id, effects);
    applied.add(ledgerId); ledger.push(ledgerId); ledger.sort();
    if (event.exclusive_group) claims[event.exclusive_group] = ledgerId;
    if (event.cooldown) {
      const nowMs = Date.parse(context.facts?.['time.utc'] ?? '');
      const visit = context.facts?.['visit.total'];
      cooldowns[event.id] = {
        ...(Number.isFinite(nowMs) ? { time_utc_seconds: Math.floor(nowMs / 1000) } : {}),
        ...(Number.isInteger(visit) ? { visit_total: visit } : {}),
      };
    }
    trace.push({ ...row, conditions, status: 'applied', effect_count: event.actions.length });
  }
  return { state, effects, trace };
}

const LEGACY_CATALOG_ALIASES = Object.freeze({
  plant: Object.freeze({ rosebush: 'rose', sapling: 'oak' }),
});

function legacyCatalogId(type, value) {
  const leaf = String(value ?? '').split('.').at(-1);
  return LEGACY_CATALOG_ALIASES[type]?.[leaf] ?? leaf;
}

export function migrateAuthenticatedLegacyGifts(gifts, options = {}) {
  if (!options.authenticated) throw new Error('legacy gifts cannot influence world state before bundle authentication');
  const messageIds = [...new Set(options.message_ids ?? [])].sort();
  const completion = messageIds.length ? { all: messageIds.map(ref => ({ fact: 'letter.read', op: 'contains', ref })) } : null;
  const entities = []; const animals = []; const events = [];
  for (const [index, gift] of gifts.entries()) {
    if (!gift?.id) throw new Error(`legacy gift ${index} has no stable id`);
    const eventId = `legacy.${gift.id}`; const target = `legacy-entity.${gift.id}`;
    const catalogId = legacyCatalogId(gift.type, gift.catalog_id);
    let original;
    if (gift.trigger?.type === 'date') original = { fact: 'time.local', op: '>=', value: `${gift.trigger.value}T00:00:00` };
    else if (gift.trigger?.type === 'cumulative_visits') original = { fact: 'visit.total', op: '>=', value: Number.parseInt(gift.trigger.value, 10) };
    else if (gift.trigger?.type === 'post_letter') original = { fact: 'letter.read', op: 'contains', ref: String(gift.trigger.value) };
    else throw new Error(`unsupported legacy trigger ${gift.trigger?.type}`);
    const actions = [];
    if (gift.type === 'animal') {
      animals.push({ id: target, species: catalogId, catalog_id: catalogId,
        name: gift.animal_name || catalogId, initial_state: { present: false } });
      actions.push({ type: 'animal.arrive', target, params: { position: gift.placement_hint || 'random' } });
    } else if (gift.type === 'plant') {
      entities.push({ id: target, kind: 'plant', catalog_id: catalogId,
        initial_state: { planted: false }, placement: gift.placement_hint || 'random' });
      actions.push({ type: 'plant.plant', target, params: { species_id: catalogId, position: gift.placement_hint || 'random' } });
    } else {
      entities.push({ id: target, kind: gift.type, catalog_id: catalogId,
        initial_state: { revealed: false }, placement: gift.placement_hint || 'random' });
      actions.push({ type: 'entity.reveal', target, params: { position: gift.placement_hint || 'random' } });
    }
    const sentiment = options.decrypted_sentiments?.[gift.id] ?? '';
    if (sentiment) actions.push({ type: 'narrative.show', target: null,
      params: { kind: 'memory', text: sentiment, label: gift.animal_name || catalogId } });
    actions.push({ type: 'event.complete', target: null, params: { event_id: eventId } });
    events.push({ id: eventId, conditions: completion ? { any: [original, completion] } : original,
      schedule: null, occurrence: 'once', priority: 0, exclusive_group: null,
      cooldown: null, actions });
  }
  return parseGardenProgram({ version: 1, evaluator_version: 1, world_state_version: 1,
    atlas_version: options.atlas_version ?? 'garden-atlas-1',
    astronomy_catalog_version: options.astronomy_catalog_version ?? 'bright-stars-1',
    author_timezone: options.author_timezone ?? 'UTC', variables: {}, entities, animals, events });
}

export function parseGardenSchedule(raw) {
  const errors = [];
  if (!raw || typeof raw !== 'object' || Array.isArray(raw)) throw new Error('Invalid garden schedule: $: schedule must be an object');
  const allowed = new Set(['start', 'timezone', 'recurrence', 'exceptions', 'missed']);
  for (const key of Object.keys(raw)) if (!allowed.has(key)) errors.push(`$: unknown fields ${key}`);
  const start = parseLocal(raw.start);
  if (!start) errors.push('$.start: invalid ISO date/time');
  try { new Intl.DateTimeFormat('en-US', { timeZone: raw.timezone }).format(0); }
  catch { errors.push(`$.timezone: unknown IANA timezone ${raw.timezone}`); }
  if (!['skip', 'deliver_on_next_visit', 'summarize_then_current'].includes(raw.missed)) errors.push('$.missed: unsupported missed-event policy');
  if (!Array.isArray(raw.exceptions) || raw.exceptions.some(value => typeof value !== 'string' || !parseException(value))) {
    errors.push('$.exceptions: expected valid ISO local dates or date/times');
  }
  const recurrence = raw.recurrence == null ? null : { interval: 1, ...clone(raw.recurrence) };
  if (recurrence) {
    const recurrenceAllowed = new Set(['frequency', 'interval', 'count', 'until', 'by_weekday',
      'intentional_unbounded', 'dst_gap', 'dst_fold']);
    for (const key of Object.keys(recurrence)) if (!recurrenceAllowed.has(key)) errors.push(`$.recurrence: unknown fields ${key}`);
    if (!['daily', 'weekly', 'monthly', 'yearly'].includes(recurrence.frequency)) errors.push('$.recurrence.frequency: unsupported frequency');
    if (!Number.isInteger(recurrence.interval) || recurrence.interval < 1 || recurrence.interval > 10000) errors.push('$.recurrence.interval: expected integer from 1 to 10000');
    if (recurrence.count != null && (!Number.isInteger(recurrence.count) || recurrence.count < 1 || recurrence.count > 1000000)) errors.push('$.recurrence.count: expected positive bounded integer');
    if (recurrence.until != null && !parseLocal(recurrence.until)) errors.push('$.recurrence.until: invalid ISO date/time');
    if (recurrence.count == null && recurrence.until == null && recurrence.intentional_unbounded !== true) errors.push('$.recurrence: count, until, or intentional_unbounded is required');
    if (recurrence.intentional_unbounded != null && typeof recurrence.intentional_unbounded !== 'boolean') errors.push('$.recurrence.intentional_unbounded: expected boolean');
    const weekdays = recurrence.by_weekday ?? [];
    if (!Array.isArray(weekdays) || weekdays.some(day => !['MO', 'TU', 'WE', 'TH', 'FR', 'SA', 'SU'].includes(day))) errors.push('$.recurrence.by_weekday: use MO through SU');
    if (weekdays.length && recurrence.frequency !== 'weekly') errors.push('$.recurrence.by_weekday: only valid for weekly recurrence');
    if (!['shift_forward', 'skip'].includes(recurrence.dst_gap ?? 'shift_forward')) errors.push('$.recurrence.dst_gap: expected shift_forward or skip');
    if (!['first', 'second'].includes(recurrence.dst_fold ?? 'first')) errors.push('$.recurrence.dst_fold: expected first or second');
  }
  if (errors.length) throw new Error(`Invalid garden schedule: ${errors.join('; ')}`);
  return { start, timezone: raw.timezone, recurrence: recurrence ? {
    ...recurrence,
    interval: recurrence.interval ?? 1,
    by_weekday: [...new Set(recurrence.by_weekday ?? [])].sort(),
    intentional_unbounded: recurrence.intentional_unbounded ?? false,
    dst_gap: recurrence.dst_gap ?? 'shift_forward',
    dst_fold: recurrence.dst_fold ?? 'first',
  } : null, exceptions: raw.exceptions ?? [], missed: raw.missed };
}

function parseLocal(value) {
  const match = /^(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2})(?::(\d{2}))?$/.exec(value ?? '');
  if (!match) return null;
  const parts = match.slice(1).map(Number);
  const date = new Date(Date.UTC(parts[0], parts[1] - 1, parts[2], parts[3], parts[4], parts[5] ?? 0));
  return localStamp([date.getUTCFullYear(), date.getUTCMonth() + 1, date.getUTCDate(),
    date.getUTCHours(), date.getUTCMinutes(), date.getUTCSeconds()]) === localStamp(parts)
    ? parts : null;
}

function parseException(value) {
  if (/^\d{4}-\d{2}-\d{2}$/.test(value)) return parseLocal(`${value}T00:00:00`) !== null;
  return parseLocal(value) !== null;
}

function localStamp(parts) {
  const [year, month, day, hour, minute, second] = parts;
  return `${String(year).padStart(4, '0')}-${String(month).padStart(2, '0')}-${String(day).padStart(2, '0')}T${String(hour).padStart(2, '0')}:${String(minute).padStart(2, '0')}:${String(second ?? 0).padStart(2, '0')}`;
}

function formattedParts(ms, timeZone) {
  const values = Object.fromEntries(new Intl.DateTimeFormat('en-CA', {
    timeZone, year: 'numeric', month: '2-digit', day: '2-digit', hour: '2-digit',
    minute: '2-digit', second: '2-digit', hourCycle: 'h23',
  }).formatToParts(new Date(ms)).filter(item => item.type !== 'literal').map(item => [item.type, Number(item.value)]));
  return [values.year, values.month, values.day, values.hour, values.minute, values.second];
}

function resolveLocal(parts, timeZone, gap, fold) {
  const target = localStamp(parts);
  const naiveMs = Date.UTC(parts[0], parts[1] - 1, parts[2], parts[3], parts[4], parts[5] ?? 0);
  const matches = [];
  for (let delta = -14 * 60; delta <= 14 * 60; delta += 1) {
    const candidate = naiveMs + delta * 60000;
    if (localStamp(formattedParts(candidate, timeZone)) === target) matches.push(candidate);
  }
  if (matches.length) return fold === 'second' ? matches.at(-1) : matches[0];
  if (gap === 'skip') return null;
  for (let shift = 1; shift <= 180; shift += 1) {
    const shifted = new Date(naiveMs + shift * 60000);
    const next = [shifted.getUTCFullYear(), shifted.getUTCMonth() + 1, shifted.getUTCDate(),
      shifted.getUTCHours(), shifted.getUTCMinutes(), shifted.getUTCSeconds()];
    const resolved = resolveLocal(next, timeZone, 'skip', fold);
    if (resolved !== null) return resolved;
  }
  throw new Error('DST gap exceeded three-hour safety bound');
}

function addDays(parts, days) {
  const date = new Date(Date.UTC(parts[0], parts[1] - 1, parts[2] + days, parts[3], parts[4], parts[5] ?? 0));
  return [date.getUTCFullYear(), date.getUTCMonth() + 1, date.getUTCDate(), date.getUTCHours(), date.getUTCMinutes(), date.getUTCSeconds()];
}

function daysBetween(start, candidate) {
  return Math.floor((Date.UTC(candidate[0], candidate[1] - 1, candidate[2]) -
    Date.UTC(start[0], start[1] - 1, start[2])) / 86400000);
}

function addMonthsExact(parts, months) {
  const monthIndex = parts[0] * 12 + parts[1] - 1 + months;
  const year = Math.floor(monthIndex / 12); const month = monthIndex % 12 + 1;
  const candidate = [year, month, parts[2], parts[3], parts[4], parts[5] ?? 0];
  return parseLocal(localStamp(candidate)) ? candidate : null;
}

function addYearsExact(parts, years) {
  const candidate = [parts[0] + years, parts[1], parts[2], parts[3], parts[4], parts[5] ?? 0];
  return parseLocal(localStamp(candidate)) ? candidate : null;
}

function occurrenceId(eventId, ms) { return `${eventId}@${new Date(ms).toISOString().replace('.000Z', 'Z')}`; }

export function expandGardenSchedule(ruleInput, options) {
  const rule = ruleInput.start && Array.isArray(ruleInput.start) ? ruleInput : parseGardenSchedule(ruleInput);
  const last = new Date(options.last_seen_utc).getTime(); const now = new Date(options.now_utc).getTime();
  if (now < last) return { occurrences: [], summarized_missed: 0, skipped_missed: 0, catch_up_truncated: false, rollback_detected: true };
  const catchupStart = Math.max(last, now - 366 * 86400000);
  let truncated = last < catchupStart;
  const recurrence = rule.recurrence;
  const candidates = []; let emitted = 0;
  const weekdayNumbers = new Set((recurrence?.by_weekday ?? []).map(day =>
    ({ MO: 1, TU: 2, WE: 3, TH: 4, FR: 5, SA: 6, SU: 0 })[day]));
  for (let index = 0; index < 200000; index += 1) {
    let local; let matches = true;
    if (!recurrence) local = rule.start;
    else if (['daily', 'weekly'].includes(recurrence.frequency)) {
      local = addDays(rule.start, index);
      const days = daysBetween(rule.start, local);
      matches = recurrence.frequency === 'daily'
        ? days % recurrence.interval === 0
        : weekdayNumbers.size
          ? Math.floor(days / 7) % recurrence.interval === 0 &&
            weekdayNumbers.has(new Date(Date.UTC(local[0], local[1] - 1, local[2])).getUTCDay())
          : days % (7 * recurrence.interval) === 0;
    } else if (recurrence.frequency === 'monthly') {
      local = addMonthsExact(rule.start, index * recurrence.interval);
    } else local = addYearsExact(rule.start, index * recurrence.interval);
    if (!matches || local === null) continue;
    if (recurrence?.until && localStamp(local) > `${recurrence.until}${recurrence.until.length === 16 ? ':00' : ''}`) break;
    emitted += 1;
    const localDate = localStamp(local); const dateOnly = localDate.slice(0, 10);
    const exception = rule.exceptions.some(value => value === dateOnly ||
      (value.length === 16 ? `${value}:00` : value) === localDate);
    if (exception) {
      if (recurrence?.count != null && emitted >= recurrence.count) break;
      continue;
    }
    const scheduled = resolveLocal(local, rule.timezone, recurrence?.dst_gap ?? 'shift_forward', recurrence?.dst_fold ?? 'first');
    if (scheduled === null) {
      if (recurrence?.count != null && emitted >= recurrence.count) break;
      continue;
    }
    if (scheduled > now) break;
    if (scheduled > catchupStart) {
      candidates.push({ id: occurrenceId(options.event_id, scheduled),
        scheduled_utc: new Date(scheduled).toISOString(), scheduled_local: localDate });
      if (candidates.length > 400) { candidates.splice(0, candidates.length - 400); truncated = true; }
    }
    if (!recurrence) break;
    if (recurrence.count != null && emitted >= recurrence.count) break;
  }
  const base = { summarized_missed: 0, skipped_missed: 0,
    catch_up_truncated: truncated, rollback_detected: false };
  if (!candidates.length) return { occurrences: [], ...base };
  if (rule.missed === 'skip') {
    const current = candidates.filter(item => now - new Date(item.scheduled_utc).getTime() <= (options.current_window_seconds ?? 60) * 1000);
    return { occurrences: current, ...base, skipped_missed: candidates.length - current.length };
  }
  const latest = candidates.at(-1);
  return rule.missed === 'deliver_on_next_visit'
    ? { occurrences: [latest], ...base, skipped_missed: Math.max(0, candidates.length - 1) }
    : { occurrences: [latest], ...base, summarized_missed: Math.max(0, candidates.length - 1) };
}
