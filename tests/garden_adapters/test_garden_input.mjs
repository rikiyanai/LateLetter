import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import test from 'node:test';

import {
  ACTIONS,
  MODALITIES,
  canonicalJson,
  normalizeGardenInput,
} from '../../web/garden-input.mjs';


const fixtureUrl = new URL('../fixtures/garden_adapter_vectors.json', import.meta.url);
const fixture = JSON.parse(await readFile(fixtureUrl, 'utf8'));

async function normalize(vector, modality, metadataOverride = undefined) {
  const input = vector.inputs[modality];
  const intentField = modality === 'browser_keyboard'
    ? 'binding' : modality === 'terminal' ? 'command' : 'control';
  return normalizeGardenInput({
    modality,
    world_id: fixture.world_id,
    sequence: vector.sequence,
    [intentField]: input[intentField],
    target_id: vector.target_id,
    args: vector.args,
    metadata: metadataOverride ?? input.metadata,
  });
}

async function emittedPayloads() {
  const payloads = [];
  for (const vector of fixture.vectors) {
    payloads.push(canonicalJson(await normalize(vector, 'touch')));
  }
  return payloads;
}

if (process.argv.includes('--emit')) {
  process.stdout.write(JSON.stringify(await emittedPayloads()));
} else {
  test('fixture covers all canonical actions', () => {
    assert.deepEqual(
      [...new Set(fixture.vectors.map(vector => vector.action))].sort(),
      [...ACTIONS].sort(),
    );
    assert.equal(ACTIONS.length, 15);
  });

  test('all modalities emit byte-identical canonical commands', async () => {
    for (const vector of fixture.vectors) {
      const payloads = await Promise.all(
        MODALITIES.map(async modality => canonicalJson(await normalize(vector, modality))),
      );
      assert.equal(new Set(payloads).size, 1, vector.action);
    }
  });

  test('modality metadata does not affect semantic bytes', async () => {
    const vector = fixture.vectors.find(item => item.action === 'place');
    const baseline = canonicalJson(await normalize(
      vector, 'mouse', { button: 0, client_x: 20 },
    ));
    const changed = canonicalJson(await normalize(
      vector, 'mouse', { button: 2, client_x: 9000, device: 'diagnostic only' },
    ));
    assert.equal(baseline, changed);
  });
}
