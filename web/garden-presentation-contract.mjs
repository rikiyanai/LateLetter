/**
 * The Garden presentation contract of SPEC 7.2.2, written as something that RUNS.
 * -------------------------------------------------------------------------------
 *
 * WHAT THIS FILE IS
 *
 * The executable form of SPEC 7.2.2 "The GardenPresentation interface
 * contract": three functions and a `PresentationFrame`, checked by composing
 * frames and reading what comes back. It replaces the earlier draft in this
 * same file, which used the withdrawn single-function
 * `composePresentationFrame(input)` shape; that shape could not represent
 * pointer hover or click feedback without hidden state, so the contract is now
 * over the split interface:
 *
 *   advancePresentationState(previousState, presentationEvents, tick) -> presentationState
 *   composePresentationFrame(projection, presentationState, context)  -> PresentationFrame
 *   paintPresentationFrame(frame, surface)                            -> void
 *
 * Only the first two are judged here. `paintPresentationFrame` is REQUIRED to
 * decide nothing, and "decides nothing" is proved by the frame being complete
 * -- every check below is over the frame, so anything the painter could add
 * would be a violation visible before painting ever happens.
 *
 * WHY IT IS CODE AND NOT PROSE
 *
 * Eight rounds of audit tried to establish primitive identity by READING
 * renderer source, and every round found a new spelling of an invocation that
 * escaped the last round's rule. Whether a run of code puts an identity in a
 * cell is a property of EXECUTION, so it is settled here by executing. Nothing
 * in this file reads renderer source, and nothing in it should ever start.
 *
 * THE MANIFEST IS THE REAL ONE
 *
 * The paint authority these checks consult is the build-generated release
 * manifest (`garden-release-manifest.json`, built by
 * `scripts/prepare_pages_site.py`): `accepted_assets`, `accepted_recipes`
 * (paint recipes only) and `accepted_laws` (never paintable). The earlier
 * draft invented its own manifest vocabulary; a contract that checks against
 * a shape the build does not produce certifies nothing about a release.
 */

/**
 * The interaction-target floor in CSS pixels.
 *
 * A composer may ENLARGE a transformed region to this size so a fingertip can
 * hit it, and may do nothing else to it. The number is duplicated from
 * `web/garden-geometry.mjs` deliberately: importing it here would make the
 * contract depend on the geometry module it is meant to be able to judge.
 */
export const MINIMUM_TARGET_PX = 44;

/**
 * A blank primitive carries no identity requirement because it draws nothing.
 *
 * Only these two spellings count as blank. Content holding any other glyph is
 * ink, and ink must be able to say where it came from. A primitive whose
 * content is a RUN (a string of several glyphs) is blank only when every
 * character in it is a space.
 */
const BLANK = /^ *$/;

/** The unit systems a primitive may declare. */
const UNITS = new Set(['cell', 'pixel', 'both']);

/** The two presentation profiles of SPEC 7.9. */
const PROFILES = new Set(['browser-proportional', 'ascii-safe']);

/**
 * Describe one violation of the contract.
 *
 * Violations are returned as data rather than thrown, so a caller can collect
 * every problem in a frame at once. A check that stops at the first failure
 * teaches the reader one defect per run, which is how a long tail of defects
 * stays hidden.
 *
 * @param {string} clause - which numbered clause of SPEC 7.2.2 was broken
 * @param {string} detail - what specifically was wrong, in plain words
 * @returns {{clause: string, detail: string}}
 */
function violation(clause, detail) {
  return { clause, detail };
}

/**
 * The ink content of a primitive, whichever field it uses.
 *
 * A primitive may carry a single `glyph` or a measured `run`; both are ink.
 * Returning the string lets every identity check ask one question -- "is this
 * blank?" -- without caring which representation the composer chose.
 *
 * @param {object} primitive
 * @returns {string} the content, or '' when the primitive carries none
 */
function inkOf(primitive) {
  if (typeof primitive.glyph === 'string') return primitive.glyph;
  if (typeof primitive.run === 'string') return primitive.run;
  return '';
}

/**
 * Check the SHAPE of a composed frame before checking anything about its
 * meaning.
 *
 * This exists so that a composer returning `undefined`, or an object missing
 * `interaction_regions`, produces a sentence a person can act on rather than
 * a `TypeError` thrown from inside a later check.
 *
 * The five fields are exactly SPEC 7.2.2's output table:
 * `attempted_primitives`, `visible_primitives`, `background`,
 * `interaction_regions`, `diagnostics`.
 *
 * @param {unknown} frame - whatever the composer returned
 * @returns {Array<{clause: string, detail: string}>} empty when the shape holds
 */
export function frameShapeViolations(frame) {
  const problems = [];
  if (!frame || typeof frame !== 'object') {
    return [violation('shape', `composer returned ${typeof frame}, not a frame object`)];
  }
  for (const field of ['attempted_primitives', 'visible_primitives', 'interaction_regions']) {
    if (!Array.isArray(frame[field])) {
      problems.push(violation('shape', `frame.${field} is not an array`));
    }
  }
  if (!frame.background || typeof frame.background !== 'object') {
    problems.push(violation('shape', 'frame.background is not an object'));
  }
  if (!frame.diagnostics || typeof frame.diagnostics !== 'object') {
    problems.push(violation('shape', 'frame.diagnostics is not an object'));
  }
  return problems;
}

/**
 * The per-primitive shape requirement of SPEC 7.2.2's output table.
 *
 * Every primitive states its unit system, content, position, painter order
 * and profile. Identity fields are judged separately by
 * `identityViolations`; this check is about a primitive being READABLE at
 * all, because a primitive missing its position cannot even be reported
 * usefully by the later checks.
 *
 * @param {{attempted_primitives: Array}} frame
 * @returns {Array<{clause: string, detail: string}>}
 */
export function primitiveShapeViolations(frame) {
  const problems = [];
  (frame.attempted_primitives ?? []).forEach((primitive, index) => {
    const at = `attempted[${index}]`;
    if (!UNITS.has(primitive.units)) {
      problems.push(violation('shape', `${at} declares units ${JSON.stringify(primitive.units)}`));
    }
    if (typeof primitive.glyph !== 'string' && typeof primitive.run !== 'string') {
      problems.push(violation('shape', `${at} carries neither glyph nor run`));
    }
    if (!Number.isFinite(primitive.x) || !Number.isFinite(primitive.y)) {
      problems.push(violation('shape', `${at} has no finite position`));
    }
    if (!Number.isFinite(primitive.painter_order)) {
      problems.push(violation('shape', `${at} has no painter_order`));
    }
    if (!PROFILES.has(primitive.profile)) {
      problems.push(violation('shape', `${at} declares profile ${JSON.stringify(primitive.profile)}`));
    }
  });
  return problems;
}

/**
 * Clause 1 -- runtime emitted-primitive identity, against the REAL manifest.
 *
 * Every nonblank primitive, attempted or visible, must say where it came
 * from:
 *
 *   - `source_id` is present and appears in the release manifest's
 *     `accepted_assets` or `accepted_recipes`;
 *   - `source_id` is never a law. A law decides what the painters are given
 *     (density, wind, cadence); it emits nothing itself, so naming one as a
 *     primitive's source is anonymity with a respectable id attached;
 *   - `object_id` appears only on the atlas chain (a `source_id` in
 *     `accepted_assets`) and only for an object the projection actually
 *     contains. A recipe-chain primitive carries none, because recipe paint
 *     is not a drawing OF a gameplay object.
 *
 * Checked over `attempted_primitives`, which by SPEC contains every draw
 * including the overwritten ones -- anonymous ink does not become acceptable
 * by being occluded.
 *
 * @param {{attempted_primitives: Array}} frame
 * @param {{projection: object, context: object}} input
 * @returns {Array<{clause: string, detail: string}>}
 */
export function identityViolations(frame, input) {
  const problems = [];
  const manifest = input.context?.acceptedManifest ?? {};
  // Grant-backed legacy art identities are atlas-chain exactly like
  // per-verdict assets: they are drawings OF gameplay objects, so their
  // primitives may inherit an object_id from the projection. The manifest
  // keeps the two lists separate because their acceptance MECHANISMS differ
  // (verdict row versus recorded grant plus provenance); the chain they
  // paint on is the same.
  const assetIds = new Set([
    ...(manifest.accepted_assets ?? []),
    ...(manifest.accepted_legacy_art ?? []),
  ]);
  const recipeIds = new Set(manifest.accepted_recipes ?? []);
  const lawIds = new Set(manifest.accepted_laws ?? []);
  const projectedIds = new Set((input.projection?.objects ?? []).map(o => o.object_id));

  (frame.attempted_primitives ?? []).forEach((primitive, index) => {
    // A primitive that draws nothing needs no provenance; this is the only
    // exemption in the clause, and it is about ink rather than about who
    // wrote the primitive.
    if (BLANK.test(inkOf(primitive))) return;

    const at = `attempted[${index}] (${primitive.x},${primitive.y}) ${JSON.stringify(inkOf(primitive))}`;
    const source = primitive.source_id;
    if (source === null || source === undefined || source === '') {
      problems.push(violation('1-identity', `${at} carries no source_id`));
      return;
    }
    if (lawIds.has(source)) {
      problems.push(violation('1-identity', `${at} names the law ${source} as its source`));
      return;
    }
    const isAsset = assetIds.has(source);
    const isRecipe = recipeIds.has(source);
    if (!isAsset && !isRecipe) {
      problems.push(violation('1-identity', `${at} names ${source}, which the release manifest does not accept`));
      return;
    }
    if (primitive.object_id !== null && primitive.object_id !== undefined) {
      if (isRecipe) {
        problems.push(violation('1-identity', `${at} is recipe paint yet claims object ${primitive.object_id}`));
      } else if (!projectedIds.has(primitive.object_id)) {
        problems.push(violation('1-identity', `${at} claims object ${primitive.object_id}, absent from the projection`));
      }
    }
  });
  return problems;
}

/**
 * Deep structural equality, used to compare frames and states.
 *
 * Written here rather than imported so the contract has no dependency that
 * could itself be wrong. It compares by value, ignoring key order, because a
 * frame is data and two frames that describe the same picture are the same
 * frame regardless of the order the composer happened to build them in.
 *
 * @param {unknown} left
 * @param {unknown} right
 * @returns {boolean}
 */
function deepEqual(left, right) {
  if (left === right) return true;
  if (typeof left !== typeof right) return false;
  if (left === null || right === null) return false;
  if (typeof left !== 'object') return false;
  if (Array.isArray(left) !== Array.isArray(right)) return false;
  if (Array.isArray(left)) {
    if (left.length !== right.length) return false;
    return left.every((item, index) => deepEqual(item, right[index]));
  }
  const leftKeys = Object.keys(left).sort();
  const rightKeys = Object.keys(right).sort();
  if (leftKeys.length !== rightKeys.length) return false;
  if (!leftKeys.every((key, index) => key === rightKeys[index])) return false;
  return leftKeys.every(key => deepEqual(left[key], right[key]));
}

/**
 * The visible picture is a subset of the attempted one.
 *
 * SPEC 7.2.2: "A primitive that is attempted and then hidden remains in
 * `attempted_primitives`; only `visible_primitives` drive the final painted
 * picture." A visible primitive that was never attempted is a decision made
 * OUTSIDE the attempt list -- exactly the hidden second composer the split
 * exists to make impossible.
 *
 * @param {{attempted_primitives: Array, visible_primitives: Array}} frame
 * @returns {Array<{clause: string, detail: string}>}
 */
export function visibilityViolations(frame) {
  const problems = [];
  const attempted = frame.attempted_primitives ?? [];
  (frame.visible_primitives ?? []).forEach((primitive, index) => {
    if (!attempted.some(candidate => deepEqual(candidate, primitive))) {
      problems.push(violation(
        'visibility',
        `visible[${index}] at (${primitive.x},${primitive.y}) was never attempted`,
      ));
    }
  });
  return problems;
}

/**
 * Clause 3 -- canonical-object interaction-region ownership.
 *
 * The split is exact: projection owns `object_id` and the declared action,
 * the atlas owns the asset-state-local mask, the composer transforms the mask
 * and binds the region. So on the composed frame:
 *
 *   - every region is keyed by an `object_id` that exists in the projection;
 *   - every declared-interactive object that emitted VISIBLE ink has a
 *     region -- the picture may not show something a person cannot touch;
 *   - every region names the `asset_id`/`state_id` mask it came from, which
 *     is what proves it was transformed from atlas ownership rather than
 *     recovered from whatever happened to be painted;
 *   - a region may be enlarged to the 44px accessibility floor and may not
 *     end up under it.
 *
 * @param {{visible_primitives: Array, interaction_regions: Array}} frame
 * @param {{projection: object}} input
 * @returns {Array<{clause: string, detail: string}>}
 */
export function interactionViolations(frame, input) {
  const problems = [];
  const objects = input.projection?.objects ?? [];
  const byId = new Map(objects.map(o => [o.object_id, o]));
  const regionsById = new Map();

  for (const region of frame.interaction_regions ?? []) {
    if (!byId.has(region.object_id)) {
      problems.push(violation(
        '3-interaction',
        `region for ${region.object_id}, which the projection does not contain`,
      ));
      continue;
    }
    regionsById.set(region.object_id, region);
    if (!region.asset_id || !region.state_id) {
      problems.push(violation(
        '3-interaction',
        `region for ${region.object_id} does not name the asset/state mask it came from`,
      ));
    }
    if (region.width < MINIMUM_TARGET_PX || region.height < MINIMUM_TARGET_PX) {
      problems.push(violation(
        '3-interaction',
        `region for ${region.object_id} is ${region.width}x${region.height}px, under the ${MINIMUM_TARGET_PX}px floor`,
      ));
    }
  }

  // Which objects actually put VISIBLE ink on the screen this frame. An
  // object that drew nothing needs no region -- it is off-screen or fully
  // occluded, and a target over empty space is a target nobody can see to
  // aim at.
  const inked = new Set();
  for (const primitive of frame.visible_primitives ?? []) {
    if (!BLANK.test(inkOf(primitive)) && primitive.object_id) inked.add(primitive.object_id);
  }
  for (const object of objects) {
    if (!object.primary_action) continue;       // not declared interactive
    if (!inked.has(object.object_id)) continue; // drew nothing this frame
    if (!regionsById.has(object.object_id)) {
      problems.push(violation(
        '3-interaction',
        `${object.object_id} painted visible ink and declares a primary action, but has no region`,
      ));
    }
  }
  return problems;
}

/**
 * Every clause that can be judged from ONE composed frame.
 *
 * Determinism (clause 2) is deliberately not here: it is a statement about
 * two advance+compose runs, so it needs the functions rather than a frame,
 * and lives in `composerViolations` below.
 *
 * @param {object} frame - the composed frame
 * @param {{projection: object, presentationState: object, context: object}} input
 * @returns {Array<{clause: string, detail: string}>} empty when the frame conforms
 */
export function frameViolations(frame, input) {
  const shape = frameShapeViolations(frame);
  if (shape.length) return shape;   // later clauses would only throw on a broken shape
  return [
    ...primitiveShapeViolations(frame),
    ...identityViolations(frame, input),
    ...visibilityViolations(frame),
    ...interactionViolations(frame, input),
  ];
}

/**
 * Clause 2 -- presentation-only state travels through the public advance,
 * and the pair (advance, compose) is a function of its declared inputs.
 *
 * The checkable consequence SPEC states is exact: advancing state and
 * composing twice from the same prior state, events, tick, projection and
 * context returns the same primitives, the same regions and the same next
 * state -- and the composed picture does not change when the hostname
 * underneath it changes.
 *
 * The hostname half moves the ground on purpose. Both compositions run under
 * a STUBBED hostname rather than one being the ambient environment: under
 * Node there is no `location` at all, so a composer asking
 * `location?.hostname === 'localhost'` would take the same branch in the
 * ambient run and a single stubbed run, and the dependence this clause
 * exists to find would never appear. Two named hosts, compared against each
 * other, is the form that actually detects it -- which is the mechanism by
 * which `allowUnacceptedArt` stays impossible to reintroduce rather than
 * merely forbidden.
 *
 * @param {(prev: object|null, events: Array, tick: object) => object} advance
 * @param {(projection: object, state: object, context: object) => object} compose
 * @param {{projection: object, previousState: object|null, presentationEvents: Array,
 *          tick: object, context: object}} input
 * @returns {Array<{clause: string, detail: string}>}
 */
export function composerViolations(advance, compose, input) {
  const problems = [];
  const { projection, previousState = null, presentationEvents = [], tick, context } = input;

  const run = () => {
    const state = advance(previousState, presentationEvents, tick);
    return { state, frame: compose(projection, state, context) };
  };
  const first = run();
  const second = run();
  if (!deepEqual(first.state, second.state)) {
    problems.push(violation('2-determinism', 'advancing twice from one input produced different states'));
  }
  if (!deepEqual(first.frame.attempted_primitives, second.frame.attempted_primitives) ||
      !deepEqual(first.frame.visible_primitives, second.frame.visible_primitives)) {
    problems.push(violation('2-determinism', 'composing twice from one input produced different primitives'));
  }
  if (!deepEqual(first.frame.interaction_regions, second.frame.interaction_regions)) {
    problems.push(violation('2-determinism', 'composing twice from one input produced different regions'));
  }

  const savedLocation = globalThis.location;
  const withHostname = (hostname) => {
    // `configurable: true` so the property can be restored afterwards; a
    // check that permanently rewrites the global environment corrupts
    // everything that runs after it.
    Object.defineProperty(globalThis, 'location', {
      value: { hostname, href: `https://${hostname}/` },
      configurable: true,
      writable: true,
    });
    return run();
  };
  try {
    const here = withHostname('localhost');
    const elsewhere = withHostname('an-entirely-different-host.example');
    if (!deepEqual(here.frame.attempted_primitives, elsewhere.frame.attempted_primitives) ||
        !deepEqual(here.frame.visible_primitives, elsewhere.frame.visible_primitives)) {
      problems.push(violation('2-determinism', 'the composed picture changed when the hostname changed'));
    }
  } finally {
    if (savedLocation === undefined) {
      delete globalThis.location;
    } else {
      Object.defineProperty(globalThis, 'location', {
        value: savedLocation,
        configurable: true,
        writable: true,
      });
    }
  }
  return problems;
}

/**
 * The whole contract, applied to a GardenPresentation implementation.
 *
 * @param {{advance: Function, compose: Function}} presentation - the pair under test
 * @param {{projection: object, previousState: object|null, presentationEvents: Array,
 *          tick: object, context: object}} input
 * @returns {Array<{clause: string, detail: string}>} empty when it conforms
 */
export function contractViolations(presentation, input) {
  const { advance, compose } = presentation;
  const state = advance(input.previousState ?? null, input.presentationEvents ?? [], input.tick);
  const frame = compose(input.projection, state, input.context);
  const shape = frameShapeViolations(frame);
  if (shape.length) return shape;
  return [
    ...frameViolations(frame, { projection: input.projection, context: input.context }),
    ...composerViolations(advance, compose, input),
  ];
}

/**
 * Throw unless the implementation conforms, with every violation in the
 * message.
 *
 * Provided for tests that want an assertion rather than a list. The message
 * names each broken clause so a failure reads as a defect report instead of
 * a boolean.
 *
 * @param {{advance: Function, compose: Function}} presentation
 * @param {object} input
 * @param {string} [label] - what is under test, for the failure message
 */
export function assertConforms(presentation, input, label = 'presentation') {
  const problems = contractViolations(presentation, input);
  if (problems.length) {
    const lines = problems.map(p => `  [${p.clause}] ${p.detail}`).join('\n');
    throw new Error(`${label} does not satisfy the presentation contract:\n${lines}`);
  }
}
