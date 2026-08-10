import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import test from 'node:test';

import { canonicalJson, normalizeGardenInput } from '../../web/garden-input.mjs';
import {
  advanceGardenLive,
  canonicalWorldJson,
  compareCodePoints,
  deserializeWorldState,
  dispatchGardenCommand,
  generateInitialWorld,
  projectGardenScene,
  reconcileGardenOffline,
  serializeWorldState,
  stepGardenAnimals,
  EVENT_TRACE_LIMIT,
  FIXTURE_VERBS,
  MILESTONE_RECEIPT_LIMIT,
  PROCESSED_COMMAND_LIMIT,
  UNDO_STACK_LIMIT,
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

async function runAdvancedScenario() {
  let state = deserializeWorldState(scenario.initial_state);
  state.program_state.story_complete = true;
  const steps = [
    ['primary_interact', 'fixture:bench', { fixture_action: 'sit' }],
    ['tend', 'plant:rose', { care_action: 'prune' }],
    ['tend', 'plant:rose', { care_action: 'train' }],
    ['tend', 'plant:rose', { care_action: 'rest' }],
    ['tend', 'plant:rose', { care_action: 'transplant', x: 20, y: 20 }],
    ['undo', null, {}],
    ['place', null, { object_kind: 'plant', catalog_id: 'willow', object_id: 'plant:placed', x: 22, y: 20 }],
    ['move_fixture', 'plant:placed', { x: 23, y: 20 }],
    ['collect', 'collectible:feather', {}],
    ['inspect', 'collectible:feather', {}],
    ['open_journal', null, {}],
  ];
  const checkpoints = [];
  for (let index = 0; index < steps.length; index += 1) {
    const [kind, targetId, args] = steps[index];
    const command = await normalizeGardenInput({ modality: 'terminal', world_id: state.world_id,
      sequence: index + 1, command: kind, target_id: targetId, args, metadata: {} });
    const [updated, result] = await dispatchGardenCommand(state, command);
    assert.equal(result.accepted, true, result.reason);
    state = updated;
    checkpoints.push({ result, state: serializeWorldState(state) });
  }
  const offlineSource = deserializeWorldState(serializeWorldState(state));
  offlineSource.last_observed_wall_time = 100;
  const [offlineState, offlineReport] = await reconcileGardenOffline(offlineSource, 200);
  return { checkpoints, projection: await projectGardenScene(state), final_json: canonicalWorldJson(state),
    offline: { state: serializeWorldState(offlineState), report: offlineReport } };
}

async function runStressScenario() {
  let state = deserializeWorldState(scenario.initial_state);
  for (let sequence = 1; sequence <= 700; sequence += 1) {
    const value = await normalizeGardenInput({
      modality: 'terminal', world_id: state.world_id, sequence,
      command: 'move_fixture', target_id: 'fixture:bench',
      args: { x: sequence % 2 ? 7 : 8, y: 5 }, metadata: {},
    });
    const [updated, result] = await dispatchGardenCommand(state, value);
    assert.equal(result.accepted, true, result.reason);
    state = updated;
  }
  const restored = deserializeWorldState(canonicalWorldJson(state));
  return {
    final_json: canonicalWorldJson(state),
    restored_json: canonicalWorldJson(restored),
    processed_count: state.processed_commands.length,
    trace_count: state.event_trace.length,
    undo_count: state.undo_stack.length,
  };
}

async function runAnimalPlantConformanceVector(payload) {
  const plantState = deserializeWorldState(payload.plant_state);
  const stages = [];
  for (const effectiveTime of payload.stage_times) {
    plantState.effective_time = effectiveTime;
    const projection = await projectGardenScene(plantState);
    stages.push(projection.objects.find(item => item.object_id === payload.plant_id)
      .semantic_state.visible_organs.find(item => item.node_id === payload.organ_id));
  }
  const animalState = deserializeWorldState(payload.animal_state);
  await stepGardenAnimals(animalState);
  const projection = await projectGardenScene(animalState);
  const persisted = canonicalWorldJson(animalState);
  const interruptedAnimalState = deserializeWorldState(payload.interrupted_animal_state);
  const interruptedId = interruptedAnimalState.animals[0].animal_id;
  const interruptedCommand = await normalizeGardenInput({
    modality: 'browser_keyboard', world_id: interruptedAnimalState.world_id,
    sequence: interruptedAnimalState.command_sequence + 1, binding: 'inspect',
    target_id: interruptedId, args: {}, metadata: { source: 'conformance' },
  });
  const [interruptedUpdated, interruptedResult] = await dispatchGardenCommand(
    interruptedAnimalState, interruptedCommand,
  );
  assert.equal(interruptedResult.accepted, true);
  const interruptedProjection = await projectGardenScene(interruptedUpdated);
  const interruptedPersisted = canonicalWorldJson(interruptedUpdated);
  return {
    stages,
    animal_state: serializeWorldState(animalState),
    animal_projection: projection,
    restarted_projection: await projectGardenScene(deserializeWorldState(persisted)),
    interrupted_animal_state: serializeWorldState(interruptedUpdated),
    interrupted_animal_projection: interruptedProjection,
    interrupted_restarted_projection: await projectGardenScene(
      deserializeWorldState(interruptedPersisted),
    ),
  };
}

async function runFixtureScenario() {
  const output = {};
  for (const [catalogId, verbs] of Object.entries(FIXTURE_VERBS)) {
    for (const verb of verbs) {
      const state = deserializeWorldState(scenario.initial_state);
      state.fixtures = [{
        fixture_id: 'fixture:test', catalog_id: catalogId, position: [8, 5],
        rotation: 0, authored: false, interaction_count: 0,
        last_interaction: null,
        authored_state: verb === 'water' ? { water_level: 3 } : {},
      }];
      if (verb === 'arrange') {
        state.collectibles[0].collected = true;
        state.inventory = [state.collectibles[0].collectible_id];
      }
      const value = await normalizeGardenInput({
        modality: 'terminal', world_id: state.world_id, sequence: 1,
        command: 'primary_interact', target_id: 'fixture:test',
        args: { fixture_action: verb }, metadata: {},
      });
      const [updated, result] = await dispatchGardenCommand(state, value);
      assert.equal(result.accepted, true, `${catalogId}:${verb}:${result.reason}`);
      output[`${catalogId}:${verb}`] = canonicalWorldJson(updated);
    }
  }
  return output;
}

async function runLedgerStressScenario() {
  let state = deserializeWorldState(scenario.initial_state);
  state.last_observed_wall_time = 0;
  for (let day = 1; day <= 700; day += 1) {
    [state] = await reconcileGardenOffline(state, day * 86400);
  }
  const restored = deserializeWorldState(canonicalWorldJson(state));
  return {
    final_json: canonicalWorldJson(state),
    restored_json: canonicalWorldJson(restored),
    receipt_count: state.milestone_receipts.length,
    receipt_total: state.program_state.milestone_receipt_total,
    offline_total: state.program_state.offline_reconciliation_total,
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

/**
 * Emit the starter fixture roster this generator produces, for byte comparison
 * against the Python one.
 *
 * The anchors are canonical world data, so "identically in Python and JS" has
 * to mean identical POSITIONS, not merely two tables that look alike when read
 * side by side. Two tables can agree and still diverge if the scaling, the
 * margin or the collision nudge differ; comparing the generated output catches
 * that, and comparing the tables would not.
 */
async function runStarterCompositionScenario(seed = 'starter-seed') {
  const state = await generateInitialWorld('starter-composition', seed);
  return {
    world_width: state.world_width,
    world_height: state.world_height,
    camera: state.ui.camera,
    plants: state.plants.map(plant => ({
      species_id: plant.species_id,
      position: plant.position,
    })),
    fixtures: state.fixtures.map(fixture => ({
      catalog_id: fixture.catalog_id,
      position: fixture.position,
      rotation: fixture.rotation,
      visual_asset_id: fixture.authored_state.visual_asset_id,
      fixture_room_role: fixture.authored_state.fixture_room_role,
      side: fixture.authored_state.side ?? null,
      x_offset: fixture.authored_state.x_offset ?? null,
      y_anchor: fixture.authored_state.y_anchor ?? null,
    })),
  };
}

if (process.argv.includes('--emit')) {
  process.stdout.write(JSON.stringify(await runScenario()));
} else if (process.argv.includes('--starter-emit')) {
  const index = process.argv.indexOf('--starter-emit');
  process.stdout.write(JSON.stringify(await runStarterCompositionScenario(
    process.argv[index + 1] ?? 'starter-seed',
  )));
} else if (process.argv.includes('--projection-emit')) {
  process.stdout.write(JSON.stringify(await projectGardenScene(deserializeWorldState(scenario.initial_state))));
} else if (process.argv.includes('--advanced-emit')) {
  process.stdout.write(JSON.stringify(await runAdvancedScenario()));
} else if (process.argv.includes('--stress-emit')) {
  process.stdout.write(JSON.stringify(await runStressScenario()));
} else if (process.argv.includes('--fixture-emit')) {
  process.stdout.write(JSON.stringify(await runFixtureScenario()));
} else if (process.argv.includes('--ledger-stress-emit')) {
  process.stdout.write(JSON.stringify(await runLedgerStressScenario()));
} else if (process.argv.includes('--animal-plant-emit')) {
  let input = '';
  for await (const chunk of process.stdin) input += chunk;
  process.stdout.write(JSON.stringify(
    await runAnimalPlantConformanceVector(JSON.parse(input)),
  ));
} else {
  test('canonical semantic tie-breaks use Python-compatible Unicode scalar order', () => {
    assert.equal(compareCodePoints('a', 'b'), -1);
    assert.equal(compareCodePoints('\u{10000}', '\uE000'), 1);
    assert.equal(compareCodePoints('same', 'same'), 0);
  });

  test('live dwell is partition deterministic and canonical pause stops time', async () => {
    const base = deserializeWorldState(scenario.initial_state);
    base.last_observed_wall_time = 1000;
    const oneCall = await advanceGardenLive(base, 600);
    let partitioned = base;
    for (let index = 0; index < 120; index += 1) partitioned = await advanceGardenLive(partitioned, 5);
    assert.equal(canonicalWorldJson(oneCall), canonicalWorldJson(partitioned));
    assert.equal(oneCall.effective_time, base.effective_time + 600);
    assert.equal(oneCall.last_observed_wall_time, 1600);
    const [reopened, report] = await reconcileGardenOffline(oneCall, 1600);
    assert.equal(canonicalWorldJson(reopened), canonicalWorldJson(oneCall));
    assert.equal(report.elapsed_seconds, 0);
    assert.ok(oneCall.event_trace.some(entry => entry.kind === 'live_tick'));
    const bounded = await advanceGardenLive(base, 3600);
    assert.equal(bounded.event_trace.filter(entry => entry.kind === 'live_tick').length, 120);
    const paused = deserializeWorldState(canonicalWorldJson(base));
    paused.ui.motion_paused = true;
    const pausedAdvanced = await advanceGardenLive(paused, 600);
    assert.equal(pausedAdvanced.effective_time, paused.effective_time);
    assert.equal(pausedAdvanced.last_observed_wall_time, 1600);
    pausedAdvanced.ui.motion_paused = false;
    const [reopenedPaused, pausedReport] = await reconcileGardenOffline(pausedAdvanced, 1600);
    assert.equal(reopenedPaused.effective_time, paused.effective_time);
    assert.equal(reopenedPaused.last_observed_wall_time, 1600);
    assert.equal(pausedReport.elapsed_seconds, 0);
  });

  test('command idempotency trace and undo windows remain bounded after stress', async () => {
    let state = deserializeWorldState(scenario.initial_state);
    let recent = null;
    for (let sequence = 1; sequence <= 700; sequence += 1) {
      recent = await normalizeGardenInput({
        modality: 'terminal', world_id: state.world_id, sequence,
        command: 'move_fixture', target_id: 'fixture:bench',
        args: { x: sequence % 2 ? 7 : 8, y: 5 }, metadata: {},
      });
      const [updated, result] = await dispatchGardenCommand(state, recent);
      assert.equal(result.accepted, true, result.reason);
      state = updated;
    }
    assert.equal(state.processed_commands.length, PROCESSED_COMMAND_LIMIT);
    assert.equal(state.event_trace.length, EVENT_TRACE_LIMIT);
    assert.equal(state.undo_stack.length, UNDO_STACK_LIMIT);
    const restored = deserializeWorldState(canonicalWorldJson(state));
    assert.equal(canonicalWorldJson(restored), canonicalWorldJson(state));
    const [duplicate, result] = await dispatchGardenCommand(restored, recent);
    assert.equal(result.accepted, true);
    assert.equal(result.changed, false);
    assert.equal(canonicalWorldJson(duplicate), canonicalWorldJson(restored));
  });

  test('milestone receipt serialization keeps the newest bounded window', () => {
    const state = deserializeWorldState({
      ...scenario.initial_state,
      milestone_receipts: Array.from({ length: 700 }, (_, index) => `receipt:${index}`),
    });
    assert.equal(state.milestone_receipts.length, MILESTONE_RECEIPT_LIMIT);
    assert.equal(state.milestone_receipts[0], 'receipt:188');
    assert.equal(state.milestone_receipts.at(-1), 'receipt:699');
  });

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

  test('generation refuses unsupported and duplicated starter rosters', async () => {
    // The exact message strings are asserted, not just that something threw.
    // Python carries the identical assertions in
    // `tests/garden_world/test_generation_projection.py`, so if either
    // implementation changes what it refuses -- or merely how it says so --
    // one of the two suites goes red. That is what stops the two generators
    // drifting into accepting different rosters.
    await assert.rejects(
      () => generateInitialWorld('x', '1', { plant_species: ['nope'] }),
      { message: "unsupported plant species requested: 'nope' (supported: "
        + 'hydrangea, lavender, meadow_grass, oak, rose, sunflower, '
        + 'water_lily, willow)' },
    );
    // Duplicates matter because every object id is a pure function of the
    // species: asking twice used to yield two records sharing one id.
    await assert.rejects(
      () => generateInitialWorld('x', '1', { plant_species: ['oak', 'oak'] }),
      { message: "duplicate plant species requested: 'oak'" },
    );
    await assert.rejects(
      () => generateInitialWorld('x', '1', { animal_species: ['dragon'] }),
      { message: "unsupported animal species requested: 'dragon' "
        + '(supported: bird, cat, rabbit, turtle)' },
    );
    await assert.rejects(
      () => generateInitialWorld('x', '1', { collectibles: ['nope'] }),
      { message: "unsupported collectible requested: 'nope' "
        + '(supported: fallen_acorn, lavender_sprig, oak_leaf)' },
    );
    // The empty roster is NOT an error -- it is the current default, and means
    // 'deliberately none' rather than 'nothing was asked for'.
    const empty = await generateInitialWorld('x', '1', {
      plant_species: [], animal_species: [], collectibles: [],
    });
    assert.deepEqual([empty.plants, empty.animals, empty.collectibles], [[], [], []]);
  });

  test('point-and-click model declares primary actions and state-dependent opportunities', async () => {
    // BEHAVIOURAL, deliberately. The composition this runs on is under review
    // and not approved, so nothing here asserts a glyph, a colour or a
    // position -- only what the world OFFERS and what performing it does.
    const world = await generateInitialWorld('interaction:contract', 'slice', {
      animal_species: [], collectibles: [],
    });
    world.fixtures = [
      {
        fixture_id: 'fixture:bench', catalog_id: 'bench', position: [10, 10],
        rotation: 0, authored: false, interaction_count: 0,
        last_interaction: null, authored_state: {},
      },
      {
        fixture_id: 'fixture:lantern', catalog_id: 'lantern', position: [20, 10],
        rotation: 0, authored: false, interaction_count: 0,
        last_interaction: null, authored_state: {},
      },
    ];
    const scene = await projectGardenScene(world);
    const bench = scene.objects.find(item => item.semantic_name === 'Garden bench');
    const lantern = scene.objects.find(item => item.semantic_name === 'Lantern');
    const rose = scene.objects.find(item => item.kind === 'plant');

    assert.deepEqual(rose.primary_action, {
      command: 'tend', args: { care_action: 'water' }, label: 'water the rose',
    });
    assert.deepEqual(rose.opportunities, []);
    const [watered, waterResult] = await dispatchGardenCommand(world, {
      world_id: world.world_id, sequence: world.command_sequence + 1,
      kind: rose.primary_action.command, target_id: rose.object_id,
      args: rose.primary_action.args, command_id: 'command:water-rose',
    });
    assert.equal(waterResult.accepted, true);
    assert.equal(watered.plants[0].tended_count, world.plants[0].tended_count + 1);

    // 7.8.3.1: the world declares the act and its wording. A renderer reading
    // this cannot invent behaviour, because there is nothing left to infer.
    assert.deepEqual(bench.primary_action, {
      command: 'primary_interact',
      args: { fixture_action: 'sit' },
      label: 'Sit on the garden bench',
    });
    // The lantern's primary is the SAFE act. Lighting is state-dependent and
    // must not be the thing a plain click does.
    assert.equal(lantern.primary_action.args.fixture_action, 'observe');
    assert.deepEqual(bench.opportunities, []);

    // 7.8.3.2: exactly one side of the lit/unlit state is ever on offer.
    assert.equal(lantern.opportunities.length, 1);
    assert.equal(lantern.opportunities[0].label, 'Light the lantern');
    assert.equal(lantern.opportunities[0].command, 'primary_interact');
    assert.equal(lantern.opportunities[0].args.fixture_action, 'light');

    // Performing it goes through the ordinary dispatcher -- the opportunity
    // owns no state and adds no command of its own.
    const [lit, result] = await dispatchGardenCommand(world, {
      world_id: world.world_id, sequence: world.command_sequence + 1,
      kind: lantern.opportunities[0].command,
      target_id: lantern.object_id,
      args: lantern.opportunities[0].args,
      command_id: 'command:opportunity-light',
    });
    assert.equal(result.accepted, true);
    const litScene = await projectGardenScene(lit);
    const litLantern = litScene.objects.find(item => item.object_id === lantern.object_id);
    assert.equal(litLantern.semantic_state.authored_state.lit, true);
    // The offer flips rather than vanishing: still exactly one, now the
    // opposite act, under a DIFFERENT id so a renderer can tell it is new.
    assert.equal(litLantern.opportunities.length, 1);
    assert.equal(litLantern.opportunities[0].label, 'Put out the lantern');
    assert.notEqual(
      litLantern.opportunities[0].opportunity_id,
      lantern.opportunities[0].opportunity_id,
    );

    // Every projected object carries both fields, so a renderer never has to
    // test whether a key exists before reading it.
    for (const object of scene.objects) {
      assert.ok('primary_action' in object, object.object_id);
      assert.ok(Array.isArray(object.opportunities), object.object_id);
    }
  });

  test('browser world core has no DOM dependency', async () => {
    assert.equal('document' in globalThis, false);
    const output = await runScenario();
    assert.equal(JSON.parse(canonicalJson(output.final_state)).command_sequence, 15);
  });

  test('projection exposes canonical topology, connected masks, and semantic actions', async () => {
    const projection = await projectGardenScene(deserializeWorldState(scenario.initial_state));
    assert.equal(projection.observed_time, scenario.initial_state.last_observed_wall_time);
    const plant = projection.objects.find(item => item.kind === 'plant');
    assert.ok(Array.isArray(plant.semantic_state.visible_organs));
    assert.ok(plant.actions.includes('prune'));
    const fixture = projection.objects.find(item => item.kind === 'fixture');
    assert.ok(fixture.actions.includes('sit'));
    assert.equal(typeof fixture.semantic_state.connected_mask, 'number');
    assert.equal(fixture.semantic_state.render_cells.length,
      fixture.hotspot.width * fixture.hotspot.height);
    assert.ok(fixture.semantic_state.semantic_description.includes('at '));
    const animals = projection.objects.filter(item => item.kind === 'animal');
    assert.deepEqual(new Set(animals.map(item => item.semantic_state.presentation_variant.split('.')[0])),
      new Set(animals.map(item => item.semantic_state.species_id)));
    assert.ok(animals.every(item => item.semantic_state.semantic_description.includes('bond tier')));
  });
  test('advanced care, fixture, inventory, memorial, and placement scenario is accepted', async () => {
    const output = await runAdvancedScenario();
    assert.equal(output.checkpoints.length, 11);
    assert.equal(output.projection.scene.memorial.active, true);
  });
}
