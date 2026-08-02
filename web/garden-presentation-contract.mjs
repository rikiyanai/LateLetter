/**
 * The Garden presentation contract, written as something that RUNS.
 * ------------------------------------------------------------------
 *
 * WHAT THIS FILE IS
 *
 * It is the definition of what it means to compose a Garden picture, and the
 * conformance check for that definition. It is not a description of the
 * current renderer, and today the current renderer does not satisfy it; that
 * gap is the measured output of route step 1 rather than a thing to hide.
 *
 * WHY IT IS CODE AND NOT PROSE
 *
 * Eight rounds of audit tried to establish the same property by READING the
 * renderer's JavaScript — whether a drawing gives a cell a reviewable
 * identity. Each round shut one way of writing an invocation and the next
 * round found another: a receiver that is not named, an invoked subscript, an
 * optional invocation, a reflective `call`, an extracted reference. That was
 * the wrong medium for the question. Whether a run of code puts an identity in
 * a cell is a property of EXECUTION, so it is settled here by composing a
 * frame and looking at what comes back. Nothing in this file reads renderer
 * source, and nothing in it should ever start.
 *
 * THE SHAPE, exactly as the operator specified it on 2026-08-02:
 *
 *   projection + viewport + presentationTime + presentationState +
 *   acceptedManifest  ->  emitted cells + interaction regions +
 *                         next presentation state
 *
 * Five inputs, three outputs, and nothing else on either side. Two details in
 * that signature carry most of its weight:
 *
 *   - `presentationState` appears on BOTH sides. Presentation is a fold, not a
 *     pure function of the clock: snow accumulates, a burst ages, a hover
 *     settles. Making the state an explicit input and an explicit output is
 *     what lets the composer stay deterministic while still accumulating —
 *     the same five inputs always produce the same frame AND the same next
 *     state, so a test can compose twice and compare.
 *
 *   - `acceptedManifest` is an input. Paint authority is a value handed to the
 *     composer, not a decision it makes by looking at the hostname. That is
 *     what makes route step 4 a consequence of this contract rather than an
 *     argument to be had separately: accepted paint composes on every host,
 *     and unreviewed ink composes on none, because the composer is never told
 *     where it is running.
 */

/**
 * The interaction-target floor in CSS pixels.
 *
 * A composer may ENLARGE a projected hotspot to this size so a fingertip can
 * hit it, and may do nothing else to it. The number is duplicated from
 * `web/garden-geometry.mjs` deliberately: importing it here would make the
 * contract depend on the geometry module it is meant to be able to judge.
 */
export const MINIMUM_TARGET_PX = 44;

/**
 * A blank cell carries no identity requirement because it draws nothing.
 *
 * Only these two spellings count as blank. A cell holding any other glyph is
 * ink, and ink must be able to say where it came from.
 */
const BLANK_GLYPHS = new Set([' ', '']);

/**
 * Describe one violation of the contract.
 *
 * Violations are returned as data rather than thrown, so that a caller can
 * collect every problem in a frame at once. A check that stops at the first
 * failure teaches the reader one defect per run, which is how a long tail of
 * defects stays hidden.
 *
 * @param {string} clause - which numbered clause of the contract was broken
 * @param {string} detail - what specifically was wrong, in plain words
 * @returns {{clause: string, detail: string}}
 */
function violation(clause, detail) {
  return { clause, detail };
}

/**
 * Check the SHAPE of a composed frame before checking anything about its
 * meaning.
 *
 * This exists so that a composer returning `undefined`, or an object missing
 * `interactionRegions`, produces a sentence a person can act on rather than a
 * `TypeError` thrown from inside a later check.
 *
 * @param {unknown} frame - whatever the composer returned
 * @returns {Array<{clause: string, detail: string}>} empty when the shape holds
 */
export function frameShapeViolations(frame) {
  const problems = [];
  if (!frame || typeof frame !== 'object') {
    return [violation('shape', `composer returned ${typeof frame}, not a frame object`)];
  }
  if (!Array.isArray(frame.cells)) {
    problems.push(violation('shape', 'frame.cells is not an array'));
  }
  if (!Array.isArray(frame.interactionRegions)) {
    problems.push(violation('shape', 'frame.interactionRegions is not an array'));
  }
  // `nextPresentationState` may be any value including null — null is the
  // honest answer for a composer with nothing to remember — but the KEY must
  // be present, because an absent key and a null value are different claims
  // and only one of them is deliberate.
  if (!('nextPresentationState' in frame)) {
    problems.push(violation('shape', 'frame has no nextPresentationState key'));
  }
  return problems;
}

/**
 * Clause 1 — runtime emitted-primitive identity.
 *
 * Every nonblank cell in the frame must say where it came from:
 *
 *   - `sourceId` is present and names a record in one of the two registers.
 *   - `sourceId` is never a law id. A law decides what the painters are given
 *     (density, wind, cadence); it emits nothing itself, so naming one as a
 *     cell's source is anonymity with a respectable id attached.
 *   - `objectId` appears only on the atlas chain, and only for an object the
 *     projection actually contains. A recipe-chain cell carries none, because
 *     recipe paint is not a drawing OF a gameplay object.
 *
 * @param {{cells: Array}} frame - the composed frame
 * @param {{acceptedManifest: object, projection: object}} input - what it was composed from
 * @returns {Array<{clause: string, detail: string}>}
 */
export function identityViolations(frame, input) {
  const problems = [];
  const manifest = input.acceptedManifest ?? {};
  const assetIds = new Set(manifest.assetIds ?? []);
  const recipeIds = new Set(manifest.recipeIds ?? []);
  const lawIds = new Set(manifest.lawIds ?? []);
  const projectedIds = new Set((input.projection?.objects ?? []).map(o => o.object_id));

  for (const cell of frame.cells ?? []) {
    // A cell that draws nothing needs no provenance; this is the only
    // exemption in the clause, and it is about ink rather than about who wrote
    // the cell, which is what the withdrawn static rule kept getting wrong.
    if (BLANK_GLYPHS.has(cell.glyph)) continue;

    const at = `(${cell.x},${cell.y}) ${JSON.stringify(cell.glyph)}`;
    if (cell.sourceId === null || cell.sourceId === undefined || cell.sourceId === '') {
      problems.push(violation('1-identity', `${at} carries no sourceId`));
      continue;
    }
    if (lawIds.has(cell.sourceId)) {
      problems.push(violation('1-identity', `${at} names the law ${cell.sourceId} as its source`));
      continue;
    }
    const isAsset = assetIds.has(cell.sourceId);
    const isRecipe = recipeIds.has(cell.sourceId);
    if (!isAsset && !isRecipe) {
      problems.push(violation('1-identity', `${at} names ${cell.sourceId}, which is in neither register`));
      continue;
    }
    if (cell.objectId !== null && cell.objectId !== undefined) {
      if (isRecipe) {
        problems.push(violation('1-identity', `${at} is recipe paint yet claims object ${cell.objectId}`));
      } else if (!projectedIds.has(cell.objectId)) {
        problems.push(violation('1-identity', `${at} claims object ${cell.objectId}, absent from the projection`));
      }
    }
  }
  return problems;
}

/**
 * Clause 2 — release paint authority.
 *
 * Ink may only come from a source the operator has accepted. The composer is
 * told which ids those are; it is never told the hostname, so the same code
 * composes the same accepted picture everywhere and cannot be talked into
 * painting unreviewed art by being run somewhere friendlier.
 *
 * `acceptedIds` absent means the caller is not asserting authority at all —
 * a diagnostic or authoring composition. That is a legitimate use, so it is
 * skipped rather than failed; the RELEASE check always passes the manifest.
 *
 * @param {{cells: Array}} frame
 * @param {{acceptedManifest: object}} input
 * @returns {Array<{clause: string, detail: string}>}
 */
export function authorityViolations(frame, input) {
  const accepted = input.acceptedManifest?.acceptedIds;
  if (!accepted) return [];
  const allowed = new Set(accepted);
  const problems = [];
  for (const cell of frame.cells ?? []) {
    if (BLANK_GLYPHS.has(cell.glyph)) continue;
    if (cell.sourceId && !allowed.has(cell.sourceId)) {
      problems.push(violation(
        '2-authority',
        `(${cell.x},${cell.y}) painted from ${cell.sourceId}, which is not accepted`,
      ));
    }
  }
  return problems;
}

/**
 * Clause 3 — interaction regions are owned by the projection, not recovered
 * from the picture.
 *
 * Three separate failures live here, and they are different mistakes:
 *
 *   - a region for an object the projection does not contain: the composer
 *     invented a target;
 *   - a declared-interactive object that emitted ink but has no region: the
 *     picture shows something a person cannot touch;
 *   - a region smaller than the 44px floor: it is present but not reachable by
 *     a fingertip.
 *
 * @param {{cells: Array, interactionRegions: Array}} frame
 * @param {{projection: object, viewport: object}} input
 * @returns {Array<{clause: string, detail: string}>}
 */
export function interactionViolations(frame, input) {
  const problems = [];
  const objects = input.projection?.objects ?? [];
  const byId = new Map(objects.map(o => [o.object_id, o]));
  const regionsById = new Map();

  for (const region of frame.interactionRegions ?? []) {
    if (!byId.has(region.objectId)) {
      problems.push(violation(
        '3-interaction',
        `region for ${region.objectId}, which the projection does not contain`,
      ));
      continue;
    }
    regionsById.set(region.objectId, region);
    if (region.width < MINIMUM_TARGET_PX || region.height < MINIMUM_TARGET_PX) {
      problems.push(violation(
        '3-interaction',
        `region for ${region.objectId} is ${region.width}x${region.height}px, under the ${MINIMUM_TARGET_PX}px floor`,
      ));
    }
  }

  // Which objects actually put ink on the screen this frame. An object that
  // drew nothing needs no region -- it is off-screen or occluded, and a target
  // over empty space would be a target nobody can see to aim at.
  const inked = new Set();
  for (const cell of frame.cells ?? []) {
    if (!BLANK_GLYPHS.has(cell.glyph) && cell.objectId) inked.add(cell.objectId);
  }
  for (const object of objects) {
    if (!object.primary_action) continue;      // not declared interactive
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
 * Determinism (clause 4) is deliberately not here: it is a statement about two
 * compositions, so it needs the composer rather than a frame, and lives in
 * `composerViolations` below.
 *
 * @param {object} frame - the composed frame
 * @param {object} input - the five inputs it was composed from
 * @returns {Array<{clause: string, detail: string}>} empty when the frame conforms
 */
export function frameViolations(frame, input) {
  const shape = frameShapeViolations(frame);
  if (shape.length) return shape;   // later clauses would only throw on a broken shape
  return [
    ...identityViolations(frame, input),
    ...authorityViolations(frame, input),
    ...interactionViolations(frame, input),
  ];
}

/**
 * Deep structural equality, used to compare two composed frames.
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
 * Clause 4 — the composer is a function of its five inputs and nothing else.
 *
 * This is checked by composing twice from one input and comparing both the
 * frame and the next state. It is the practical form of "presentation-only
 * state is derived, never discovered": a composer that reads the wall clock,
 * unseeded randomness, storage, or the hostname will differ between the two
 * runs, or will differ once the environment underneath it is moved.
 *
 * The second half moves the environment on purpose. `globalThis.location` is
 * replaced between the two compositions, so a composer that consults the
 * hostname to decide what it may paint is caught here — which is the whole
 * mechanism by which `allowUnacceptedArt` becomes impossible to reintroduce
 * rather than merely forbidden.
 *
 * @param {(input: object) => object} compose - the composer under test
 * @param {object} input - the five inputs
 * @returns {Array<{clause: string, detail: string}>}
 */
export function composerViolations(compose, input) {
  const problems = [];
  const first = compose(input);
  const second = compose(input);
  if (!deepEqual(first.cells, second.cells)) {
    problems.push(violation('4-determinism', 'composing twice from one input produced different cells'));
  }
  if (!deepEqual(first.interactionRegions, second.interactionRegions)) {
    problems.push(violation('4-determinism', 'composing twice from one input produced different regions'));
  }
  if (!deepEqual(first.nextPresentationState, second.nextPresentationState)) {
    problems.push(violation('4-determinism', 'composing twice from one input produced different next state'));
  }

  // Move the ground under the composer and require the picture not to move.
  //
  // Both compositions run under a STUBBED hostname rather than one being the
  // ambient environment. Under Node there is no `location` at all, so a
  // composer asking `location?.hostname === 'localhost'` would take the same
  // branch in the ambient run and in a single stubbed run, and the difference
  // this clause exists to find would never appear. Two named hosts, compared
  // against each other, is the form that actually detects the dependence.
  const savedLocation = globalThis.location;
  const withHostname = (hostname) => {
    // `configurable: true` so the property can be restored afterwards; a check
    // that permanently rewrites the global environment corrupts everything
    // that runs after it.
    Object.defineProperty(globalThis, 'location', {
      value: { hostname, href: `https://${hostname}/` },
      configurable: true,
      writable: true,
    });
    return compose(input);
  };
  try {
    const here = withHostname('localhost');
    const elsewhere = withHostname('an-entirely-different-host.example');
    if (!deepEqual(here.cells, elsewhere.cells)) {
      problems.push(violation('4-determinism', 'the composed picture changed when the hostname changed'));
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
 * The whole contract, applied to a composer.
 *
 * @param {(input: object) => object} compose - the composer under test
 * @param {object} input - projection, viewport, presentationTime,
 *                         presentationState, acceptedManifest
 * @returns {Array<{clause: string, detail: string}>} empty when it conforms
 */
export function contractViolations(compose, input) {
  const frame = compose(input);
  const shape = frameShapeViolations(frame);
  if (shape.length) return shape;
  return [...frameViolations(frame, input), ...composerViolations(compose, input)];
}

/**
 * Throw unless the composer conforms, with every violation in the message.
 *
 * Provided for tests that want an assertion rather than a list. The message
 * names each broken clause so a failure reads as a defect report instead of a
 * boolean.
 *
 * @param {(input: object) => object} compose
 * @param {object} input
 * @param {string} [label] - what is under test, for the failure message
 */
export function assertConforms(compose, input, label = 'composer') {
  const problems = contractViolations(compose, input);
  if (problems.length) {
    const lines = problems.map(p => `  [${p.clause}] ${p.detail}`).join('\n');
    throw new Error(`${label} does not satisfy the presentation contract:\n${lines}`);
  }
}
