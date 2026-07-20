import {
  canonicalWorldJson,
  generateInitialWorld,
  materializeGardenProgramEffects,
  projectGardenScene,
} from '../../web/garden-world.mjs';


if (process.argv.includes('--materialize')) {
  let input = '';
  for await (const chunk of process.stdin) input += chunk;
  const payload = JSON.parse(input);
  const [world, receipts] = await materializeGardenProgramEffects(
    payload.world, payload.program, payload.evaluation,
  );
  process.stdout.write(JSON.stringify({
    world: JSON.parse(canonicalWorldJson(world)),
    receipts,
  }));
  process.exit(0);
}

const results = [];
for (let seed = 0; seed < 100; seed += 1) {
  const world = await generateInitialWorld(`acceptance:${seed}`, seed, {
    world_width: 64,
    world_height: 40,
  });
  world.effective_time = 0;
  const early = await projectGardenScene(world);
  world.effective_time = 1_000_000;
  const late = await projectGardenScene(world);
  const earlyPlants = new Map(
    early.objects.filter(item => item.kind === 'plant')
      .map(item => [item.object_id, item.semantic_state.topology_hash]),
  );
  const latePlants = new Map(
    late.objects.filter(item => item.kind === 'plant')
      .map(item => [item.object_id, item.semantic_state.topology_hash]),
  );
  results.push({
    seed,
    plants: [...world.plants]
      .sort((left, right) => left.plant_id.localeCompare(right.plant_id))
      .map(plant => ({
        plant_id: plant.plant_id,
        node_ids: plant.topology.map(node => node.node_id).sort(),
        early_hash: earlyPlants.get(plant.plant_id),
        late_hash: latePlants.get(plant.plant_id),
      })),
  });
}

process.stdout.write(JSON.stringify(results));
