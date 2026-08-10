#!/usr/bin/env node
/**
 * The public runtime-frame check of SPEC 7.2.2 clause 4.
 * ------------------------------------------------------
 *
 * WHAT THIS IS
 *
 * The release gate's answer to "does the product's picture carry identity and
 * paint only accepted art", answered the only way that question can be
 * answered: by COMPOSING AN ACTUAL FRAME through the public
 * GardenPresentation interface and reading the primitives back. It replaces
 * the static writer-graph analysis that used to live in
 * `scripts/validate_presentation_identity.py` -- eight audit rounds of
 * reading renderer source text, each defeated by a spelling of an invocation
 * the previous round had not imagined. Identity is a property of EXECUTION;
 * this file executes.
 *
 * WHAT IT CHECKS
 *
 *   1. The starter world -- the exact composition a recipient's Garden opens
 *      with -- is generated, projected and composed under the committed
 *      accepted-paint authority.
 *   2. Every clause of the executable presentation contract holds on the
 *      result: primitive identity, authority, visibility subset, region
 *      ownership, determinism, hostname independence.
 *   3. No attempted primitive was suppressed: a release frame that needed
 *      suppression tried to paint something unaccepted, and "the gate hid it
 *      for you" is not a release condition.
 *   4. Divergence: any source id whose register record claims a deployed
 *      verdict (`accepted_as_deployed`) while its implementation is not an
 *      exact reproduction (`candidate_status` != "exact") is reported. A
 *      citation of legacy line numbers is provenance, not approval.
 *
 * OUTPUT
 *
 * One JSON object on stdout: `{violations: [...], divergent: [...], stats}`.
 * The Python release gate consumes it verbatim as the
 * `runtime_frame_violations` blocker. Exit code 0 means "ran and reported",
 * not "clean" -- emptiness is judged by the consumer, so a crash cannot be
 * confused with a clean report.
 */

import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { dirname, resolve } from 'node:path';

import { generateInitialWorld, projectGardenScene } from '../web/garden-world.mjs';
import {
  advancePresentationState, composePresentationFrame,
} from '../web/garden-presentation.mjs';
import {
  frameViolations, composerViolations,
} from '../web/garden-presentation-contract.mjs';

const HERE = dirname(fileURLToPath(import.meta.url));
const ROOT = resolve(HERE, '..');

/** The committed runtime paint authority; the same lists the release
 * manifest embeds. Reading it here (rather than accepting one on argv) is
 * deliberate: the gate judges the release configuration, and a caller who
 * could pass a friendlier manifest would be judging something else. */
const AUTHORITY = JSON.parse(
  readFileSync(resolve(ROOT, 'web/garden-accepted-paint.v1.json'), 'utf8'),
);

/** The recipe register, for the divergence report. */
const RECIPES = JSON.parse(
  readFileSync(resolve(ROOT, 'docs/garden-presentation-recipes.json'), 'utf8'),
);

/** Verdicts that claim to reproduce the deployed presentation. Kept in
 * lockstep with PROVENANCE_CLAIMING_VERDICTS in the Python gate. */
const PROVENANCE_CLAIMING_VERDICTS = new Set(['accepted_as_deployed']);

/**
 * A fixed identity for the checked world. Fixed so the check is
 * deterministic: the gate must fail because the product changed, never
 * because the dice rolled differently.
 */
const WORLD_ID = 'release-gate-starter';
const SEED = 'release-gate-seed-1';

/** The viewport the frame is composed at: a desktop-shaped lattice. The gate
 * checks identity and authority, which do not vary by size; the E2E suite
 * owns per-size behaviour. */
const VIEWPORT = [120, 40];

const world = await generateInitialWorld(WORLD_ID, SEED);
const projection = await projectGardenScene(world);

const context = {
  viewport: VIEWPORT,
  profile: 'browser-proportional',
  presentationGeometry: { cellAdvance: 8, lineHeight: 15, affineOnly: false },
  acceptedManifest: AUTHORITY,
  environment: { readerRegion: null, reducedMotion: false },
};
// The accepted recipient Garden is static. Advance exactly one deterministic
// frame so this gate proves the composer without manufacturing ambient life.
const sceneEvent = { kind: 'scene', projection, viewport: VIEWPORT };
const initialState = advancePresentationState(null, [sceneEvent], { frame: 0 });

const input = {
  projection,
  previousState: initialState,
  presentationEvents: [sceneEvent],
  tick: { frame: 0, seconds: 0 },
  context,
};

const state = advancePresentationState(input.previousState, input.presentationEvents, input.tick);
const frame = composePresentationFrame(projection, state, context);

const violations = [
  ...frameViolations(frame, { projection, context }),
  ...composerViolations(advancePresentationState, composePresentationFrame, input),
];

// Suppression in a release frame means something unaccepted tried to paint.
const suppressed = frame.attempted_primitives.filter(item => item.suppressed);
for (const item of suppressed) {
  violations.push({
    clause: 'release-suppression',
    detail: `(${item.x},${item.y}) ${JSON.stringify(item.glyph)} attempted from ` +
      `${item.source_id ?? 'no source at all'}, which the release authority does not accept`,
  });
}

// Divergence: painted ids claiming deployed provenance without an exact
// implementation. Grant-backed legacy identities and per-asset verdicts have
// no candidate_status machinery and are skipped -- their exactness is owned
// by the provenance tests over LEGACY_ART_PROVENANCE and the atlas.
const paintedSources = new Set(
  frame.attempted_primitives
    .filter(item => item.source_id && item.glyph.trim())
    .map(item => item.source_id),
);
const divergent = [];
for (const source of [...paintedSources].sort()) {
  const record = RECIPES.records[source];
  if (!record) continue;
  if (PROVENANCE_CLAIMING_VERDICTS.has(record.verdict) &&
      record.candidate_status !== 'exact') {
    divergent.push(
      `${source} paints while candidate_status is ` +
      `${JSON.stringify(record.candidate_status ?? null)}, so it may not claim ` +
      `verdict ${JSON.stringify(record.verdict)}`,
    );
  }
}

process.stdout.write(JSON.stringify({
  violations,
  divergent,
  stats: {
    attempted: frame.attempted_primitives.length,
    visible: frame.visible_primitives.length,
    suppressed: suppressed.length,
    regions: frame.interaction_regions.length,
    painted_sources: [...paintedSources].sort(),
  },
}, null, 2) + '\n');
