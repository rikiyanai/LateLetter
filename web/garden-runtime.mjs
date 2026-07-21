/** Sole browser owner for canonical Garden state, persistence, and commands. */

import { normalizeGardenInput } from './garden-input.mjs';
import {
  canonicalWorldJson,
  deserializeWorldState,
  dispatchGardenCommand,
  generateInitialWorld,
  materializeGardenProgramEffects,
  projectGardenScene,
  reconcileGardenOffline,
  seedGardenProgramState,
} from './garden-world.mjs';

export const WORLD_STORAGE_PREFIX = 'lateletter_garden_world_v1_';
export const PBKDF2_MIN_ITERATIONS = 600000;
export const PBKDF2_MAX_ITERATIONS = 2000000;

/** Reject attacker-controlled work factors before WebCrypto performs any work. */
export function validateBrowserPbkdf2Params(params, field = 'kdf_params') {
  if (!params || typeof params !== 'object' || Array.isArray(params)) {
    throw new Error(`${field} must be an object`);
  }
  const fields = Object.keys(params).sort();
  if (fields.join(',') !== 'hash,iterations,name') {
    throw new Error(`${field} must contain exactly hash, iterations, and name`);
  }
  if (params.name !== 'PBKDF2' || params.hash !== 'SHA-256') {
    throw new Error(`${field} uses an unsupported PBKDF2 profile`);
  }
  if (typeof params.iterations !== 'number' || !Number.isInteger(params.iterations)) {
    throw new Error(`${field}.iterations must be an integer, not a boolean`);
  }
  if (params.iterations < PBKDF2_MIN_ITERATIONS || params.iterations > PBKDF2_MAX_ITERATIONS) {
    throw new Error(`${field}.iterations is outside the supported range`);
  }
  return params;
}

/** Decode only canonical padded base64 and enforce the cryptographic field shape. */
export function decodeStrictBase64(value, { field = 'value', exact = null, minimum = null } = {}) {
  if (typeof value !== 'string' || value.length === 0 || value.length % 4 !== 0 ||
    !/^(?:[A-Za-z0-9+/]{4})*(?:[A-Za-z0-9+/]{2}==|[A-Za-z0-9+/]{3}=)?$/.test(value)) {
    throw new Error(`${field} must be valid padded base64`);
  }
  let binary;
  try { binary = globalThis.atob(value); } catch (_) {
    throw new Error(`${field} must be valid padded base64`);
  }
  const bytes = Uint8Array.from(binary, character => character.charCodeAt(0));
  if (exact !== null && bytes.length !== exact) {
    throw new Error(`${field} must decode to exactly ${exact} bytes`);
  }
  if (minimum !== null && bytes.length < minimum) {
    throw new Error(`${field} must decode to at least ${minimum} bytes`);
  }
  return bytes;
}

/** Resolve a semantic modality from the browser event which activated a control. */
export function inputModalityFromBrowserEvent(event) {
  if (String(event?.type ?? '').startsWith('key') || event?.detail === 0) {
    return 'browser_keyboard';
  }
  if (event?.pointerType === 'touch' || event?.sourceCapabilities?.firesTouchEvents === true) {
    return 'touch';
  }
  return 'mouse';
}

/** Reduced-motion preference overrides ambient animation, not saved pause state. */
export function effectiveAmbientMotion({ prefersReducedMotion = false, motionPaused = false } = {}) {
  return !prefersReducedMotion && !motionPaused;
}

export class GardenRuntime {
  constructor({ worldId, seed, load, save, now = () => Math.floor(Date.now() / 1000) }) {
    this.worldId = String(worldId);
    this.seed = String(seed);
    this.loadValue = load;
    this.saveValue = save;
    this.now = now;
    this.state = null;
    this.projection = null;
    this.lastResult = null;
    this.absenceReport = null;
    this.previousObservedWallTime = null;
    this.mutationTail = Promise.resolve();
  }

  get storageKey() { return `${WORLD_STORAGE_PREFIX}${this.worldId}`; }

  enqueueMutation(operation) {
    const pending = this.mutationTail.then(operation, operation);
    this.mutationTail = pending.then(() => undefined, () => undefined);
    return pending;
  }

  async open() {
    return this.enqueueMutation(async () => {
      const stored = await this.loadValue(this.storageKey);
      let state;
      if (stored !== null && stored !== undefined && stored !== '') {
        state = deserializeWorldState(stored);
        if (state.world_id !== this.worldId) throw new Error('stored Garden world identity mismatch');
      } else state = await generateInitialWorld(this.worldId, this.seed);
      this.previousObservedWallTime = state.last_observed_wall_time;
      [state, this.absenceReport] = await reconcileGardenOffline(state, this.now());
      this.state = state;
      await this.persist();
      await this.refreshProjection();
      return this;
    });
  }

  async persist() {
    if (!this.state) throw new Error('Garden runtime is not open');
    await this.saveValue(this.storageKey, canonicalWorldJson(this.state));
  }

  async refreshProjection() {
    this.projection = await projectGardenScene(this.state);
    return this.projection;
  }

  async dispatch(modality, intent, { target_id = null, args = {}, metadata = {} } = {}) {
    return this.enqueueMutation(async () => {
      if (!this.state) throw new Error('Garden runtime is not open');
      const field = modality === 'browser_keyboard' ? 'binding'
        : modality === 'terminal' ? 'command' : 'control';
      const command = await normalizeGardenInput({
        modality, world_id: this.state.world_id,
        sequence: this.state.command_sequence + 1,
        [field]: intent, target_id, args, metadata,
      });
      const [updated, result] = await dispatchGardenCommand(this.state, command);
      this.lastResult = result;
      if (result.accepted && result.changed) {
        this.state = updated;
        await this.persist();
        await this.refreshProjection();
      }
      return result;
    });
  }

  async materializeProgram(program, evaluation) {
    return this.enqueueMutation(async () => {
      if (!this.state) throw new Error('Garden runtime is not open');
      const [updated, receipts] = await materializeGardenProgramEffects(
        this.state, program, evaluation,
      );
      this.state = updated;
      await this.persist();
      await this.refreshProjection();
      return receipts;
    });
  }

  async markStoryComplete(completedAt = null) {
    return this.enqueueMutation(async () => {
      if (!this.state) throw new Error('Garden runtime is not open');
      if (this.state.program_state.story_complete === true) return false;
      this.state.program_state.story_complete = true;
      this.state.program_state.memorial = {
        active: true,
        completed_at: Number.isInteger(completedAt) ? completedAt : this.state.effective_time,
        examined_gifts: this.state.journal.filter(item => item.status === 'examined')
          .map(item => item.object_id).sort(),
        lasting: true,
      };
      await this.persist();
      await this.refreshProjection();
      return true;
    });
  }

  prepareProgram(program) {
    if (!this.state) throw new Error('Garden runtime is not open');
    return seedGardenProgramState(this.state, program).program_state;
  }

  focusedObject() {
    return this.projection?.objects.find(item => item.object_id === this.state?.ui.focus_id) ?? null;
  }

  sceneSummary() {
    if (!this.projection) return 'Garden unavailable.';
    const counts = {};
    for (const object of this.projection.objects) counts[object.kind] = (counts[object.kind] ?? 0) + 1;
    const contents = Object.keys(counts).sort().map(kind =>
      `${counts[kind]} ${kind}${counts[kind] === 1 ? '' : 's'}`).join(', ');
    const focus = this.focusedObject();
    return `Garden at ${this.projection.camera[0]},${this.projection.camera[1]}; ${contents}. ${this.state.inventory.length} in inventory. ${focus ? `Focused ${focus.semantic_name}.` : 'No object focused.'} Motion ${this.projection.motion_paused ? 'paused' : 'enabled'}.`;
  }
}
