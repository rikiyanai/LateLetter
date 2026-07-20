import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import test from 'node:test';

import { canonicalJson, normalizeGardenInput } from '../../web/garden-input.mjs';
import {
  canonicalWorldJson,
  deserializeWorldState,
  dispatchGardenCommand,
  serializeWorldState,
} from '../../web/garden-world.mjs';


const scenarioUrl = new URL('../fixtures/garden_world_golden_scenario.json', import.meta.url);
const scenario = JSON.parse(await readFile(scenarioUrl, 'utf8'));

function sourceField(modality) {
  if (modality === 'browser_keyboard') return 'binding';
  if (modality === 'terminal') return 'command';
  return 'control';
}

async function scenarioCommand(step) {
  return normalizeGardenInput({
    modality: step.modality,
    world_id: scenario.initial_state.world_id,
    sequence: step.sequence,
    [sourceField(step.modality)]: step.kind,
    target_id: step.target_id,
    args: step.args,
    metadata: step.metadata,
  });
}

async function runScenario() {
  let state = deserializeWorldState(scenario.initial_state);
  const checkpoints = [];
  let lastCommand = null;
  for (const step of scenario.commands) {
    const command = await scenarioCommand(step);
    const [updated, result] = await dispatchGardenCommand(state, command);
    assert.equal(result.accepted, true, `${step.sequence}:${step.kind} ${result.reason}`);
    state = updated;
    lastCommand = command;
    checkpoints.push({
      command,
      result,
      state: serializeWorldState(state),
    });
  }

  const [duplicateState, duplicateResult] = await dispatchGardenCommand(state, lastCommand);
  const gapCommand = await normalizeGardenInput({
    modality: 'terminal',
    world_id: state.world_id,
    sequence: state.command_sequence + 2,
    command: 'back',
    target_id: null,
    args: {},
    metadata: { token: 'back' },
  });
  const [gapState, gapResult] = await dispatchGardenCommand(state, gapCommand);
  const persisted = canonicalWorldJson(state);
  const restored = deserializeWorldState(persisted);

  return {
    checkpoints,
    final_state: serializeWorldState(state),
    final_json: persisted,
    duplicate: {
      result: duplicateResult,
      state: serializeWorldState(duplicateState),
    },
    sequence_gap: {
      result: gapResult,
      state: serializeWorldState(gapState),
    },
    persistence_round_trip_json: canonicalWorldJson(restored),
  };
}

function assertFinalExpectations(state) {
  const expected = scenario.final_expectations;
  const plant = state.plants.find(item => item.plant_id === 'plant:rose');
  const animal = state.animals.find(item => item.animal_id === 'animal:rabbit');
  const fixture = state.fixtures.find(item => item.fixture_id === 'fixture:lantern-golden');
  assert.equal(state.command_sequence, expected.command_sequence);
  assert.deepEqual(state.ui.camera, expected.camera);
  assert.equal(plant.growth_points, expected.plant_growth_points);
  assert.equal(plant.tended_count, expected.plant_tended_count);
  assert.equal(animal.bond_points, expected.animal_bond_points);
  assert.equal(animal.bond_tier, expected.animal_bond_tier);
  assert.deepEqual(animal.interaction_counts, expected.animal_interaction_counts);
  assert.deepEqual(state.inventory, expected.inventory);
  assert.deepEqual(fixture.position, expected.placed_fixture_position);
  assert.equal(fixture.rotation, expected.placed_fixture_rotation);
  assert.equal(state.ui.journal_open, expected.journal_open);
  assert.equal(state.ui.motion_paused, expected.motion_paused);
  assert.equal(state.event_trace.length, expected.trace_count);
  assert.equal(state.undo_stack.length, expected.undo_depth);
}

if (process.argv.includes('--emit')) {
  process.stdout.write(JSON.stringify(await runScenario()));
} else {
  test('golden scenario applies every canonical command', async () => {
    assert.equal(new Set(scenario.commands.map(item => item.kind)).size, 15);
    const output = await runScenario();
    assertFinalExpectations(output.final_state);
  });

  test('command sequence is the world revision and duplicate IDs are idempotent', async () => {
    const output = await runScenario();
    assert.equal(output.duplicate.result.accepted, true);
    assert.equal(output.duplicate.result.changed, false);
    assert.equal(output.duplicate.result.reason, 'already applied');
    assert.deepEqual(output.duplicate.state, output.final_state);
    assert.equal(output.sequence_gap.result.accepted, false);
    assert.equal(output.sequence_gap.result.reason, 'expected sequence 16');
    assert.deepEqual(output.sequence_gap.state, output.final_state);
  });

  test('canonical persistence round trip is byte identical', async () => {
    const output = await runScenario();
    assert.equal(output.persistence_round_trip_json, output.final_json);
    assert.throws(
      () => deserializeWorldState({ ...scenario.initial_state, schema_version: 999 }),
      /unsupported Garden world schema 999/,
    );
  });

  test('browser world core has no DOM dependency', async () => {
    assert.equal('document' in globalThis, false);
    const output = await runScenario();
    assert.equal(JSON.parse(canonicalJson(output.final_state)).command_sequence, 15);
  });
}
