/** Sole browser owner for canonical Garden state, persistence, and commands. */

import { normalizeGardenInput } from './garden-input.mjs';
import {
  advanceGardenLive,
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
export const LIVE_PERSIST_SECONDS = 5;
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
    this.liveTimer = null;
    this.liveObserved = null;
    this.prefersReducedMotion = false;
    this.onLiveProjection = null;
    this.persistenceEnabled = true;
    this.liveDirty = false;
    this.lastPersistedEffectiveTime = null;
    this.invalidated = false;
    this.saveControllers = new Set();
  }

  get storageKey() { return `${WORLD_STORAGE_PREFIX}${this.worldId}`; }

  assertActive() {
    if (this.invalidated) throw new Error('Garden runtime was invalidated');
  }

  /**
   * Synchronously revoke a runtime and every queued mutation.
   *
   * Authenticated recipients call this before dropping their last reference
   * on pagehide or after a failed transaction.  Clearing state/projection here
   * prevents a suspended continuation from retaining or republishing authored
   * plaintext, while the active checks prevent a deferred force-commit.
   */
  invalidate() {
    if (this.invalidated) return;
    this.invalidated = true;
    this.persistenceEnabled = false;
    for (const controller of this.saveControllers) controller.abort();
    this.saveControllers.clear();
    this.stopLive({ flush: false });
    this.onLiveProjection = null;
    this.state = null;
    this.projection = null;
    this.absenceReport = null;
    this.previousObservedWallTime = null;
    this.liveDirty = false;
  }

  enqueueMutation(operation) {
    const guarded = () => {
      this.assertActive();
      return operation();
    };
    const pending = this.mutationTail.then(guarded, guarded);
    this.mutationTail = pending.then(() => undefined, () => undefined);
    return pending;
  }

  async open({ persist = true } = {}) {
    return this.enqueueMutation(async () => {
      this.assertActive();
      this.persistenceEnabled = Boolean(persist);
      const stored = await this.loadValue(this.storageKey);
      this.assertActive();
      let state;
      if (stored !== null && stored !== undefined && stored !== '') {
        state = deserializeWorldState(stored);
        if (state.world_id !== this.worldId) throw new Error('stored Garden world identity mismatch');
      } else {
        state = await generateInitialWorld(this.worldId, this.seed);
        this.assertActive();
      }
      this.previousObservedWallTime = state.last_observed_wall_time;
      const [reconciled, absenceReport] = await reconcileGardenOffline(state, this.now());
      this.assertActive();
      state = reconciled;
      this.absenceReport = absenceReport;
      this.state = state;
      await this.persist();
      this.assertActive();
      await this.refreshProjection();
      this.assertActive();
      return this;
    });
  }

  async persist({ force = false } = {}) {
    this.assertActive();
    if (!this.state) throw new Error('Garden runtime is not open');
    if (!this.persistenceEnabled && !force) return false;
    const state = this.state;
    const serialized = canonicalWorldJson(state);
    this.assertActive();
    const controller = new AbortController();
    this.saveControllers.add(controller);
    try {
      await this.saveValue(this.storageKey, serialized, { signal: controller.signal });
      this.assertActive();
      if (controller.signal.aborted) throw new Error('Garden persistence was aborted');
      if (this.state !== state) throw new Error('Garden runtime changed during persistence');
      this.lastPersistedEffectiveTime = state.effective_time;
      this.liveDirty = false;
      return true;
    } finally {
      this.saveControllers.delete(controller);
    }
  }

  /** Commit a transactionally opened runtime and enable normal persistence. */
  async commitPersistence({ enable = true } = {}) {
    return this.enqueueMutation(async () => {
      this.assertActive();
      if (!this.state) throw new Error('Garden runtime is not open');
      await this.persist({ force: true });
      this.assertActive();
      this.persistenceEnabled = Boolean(enable);
      return this;
    });
  }

  async flushLivePersistence() {
    return this.enqueueMutation(async () => {
      this.assertActive();
      if (!this.liveDirty) return false;
      return this.persist();
    });
  }

  async refreshProjection() {
    this.assertActive();
    const state = this.state;
    const projection = await projectGardenScene(state);
    this.assertActive();
    if (this.state !== state) throw new Error('Garden runtime changed during projection');
    this.projection = projection;
    return projection;
  }

  async tickLive(elapsedSeconds = null) {
    return this.enqueueMutation(async () => {
      this.assertActive();
      if (!this.state) throw new Error('Garden runtime is not open');
      const state = this.state;
      const observed = this.now();
      const elapsed = elapsedSeconds === null
        ? Math.max(0, observed - (this.liveObserved ?? observed))
        : Math.max(0, Number.parseInt(elapsedSeconds, 10) || 0);
      this.liveObserved = observed;
      const updated = await advanceGardenLive(state, elapsed);
      this.assertActive();
      if (this.state !== state) throw new Error('Garden runtime changed during live advance');
      if (canonicalWorldJson(updated) === canonicalWorldJson(state)) return false;
      this.state = updated;
      this.liveDirty = true;
      const explicitTick = elapsedSeconds !== null;
      const crossedPersistenceBoundary = this.lastPersistedEffectiveTime === null ||
        Math.floor(this.state.effective_time / LIVE_PERSIST_SECONDS) !==
          Math.floor(this.lastPersistedEffectiveTime / LIVE_PERSIST_SECONDS);
      if (explicitTick || crossedPersistenceBoundary) await this.persist();
      this.assertActive();
      await this.refreshProjection();
      this.assertActive();
      if (this.onLiveProjection) this.onLiveProjection(this.projection, {
        prefersReducedMotion: this.prefersReducedMotion,
      });
      return true;
    });
  }

  startLive({ intervalMs = 1000, prefersReducedMotion = false, onProjection = null } = {}) {
    this.assertActive();
    this.stopLive({ flush: false });
    this.prefersReducedMotion = Boolean(prefersReducedMotion);
    this.onLiveProjection = typeof onProjection === 'function' ? onProjection : null;
    this.liveObserved = this.now();
    const delay = Math.max(250, Number.parseInt(intervalMs, 10) || 1000);
    this.liveTimer = globalThis.setInterval(() => { this.tickLive().catch(() => {}); }, delay);
    return this;
  }

  stopLive({ flush = true } = {}) {
    if (this.liveTimer !== null) globalThis.clearInterval(this.liveTimer);
    this.liveTimer = null;
    this.liveObserved = null;
    if (flush && this.liveDirty) this.flushLivePersistence().catch(() => {});
  }

  async dispatch(modality, intent, { target_id = null, args = {}, metadata = {} } = {}) {
    return this.enqueueMutation(async () => {
      this.assertActive();
      if (!this.state) throw new Error('Garden runtime is not open');
      const state = this.state;
      const field = modality === 'browser_keyboard' ? 'binding'
        : modality === 'terminal' ? 'command' : 'control';
      const command = await normalizeGardenInput({
        modality, world_id: state.world_id,
        sequence: state.command_sequence + 1,
        [field]: intent, target_id, args, metadata,
      });
      this.assertActive();
      const [updated, result] = await dispatchGardenCommand(state, command);
      this.assertActive();
      if (this.state !== state) throw new Error('Garden runtime changed during dispatch');
      this.lastResult = result;
      if (result.accepted && result.changed) {
        // Resuming discards the wall interval spent under the canonical pause;
        // it must never return later as offline catch-up.
        if (intent === 'pause_motion' && updated.ui.motion_paused === false) {
          const observed = this.now();
          if (updated.last_observed_wall_time !== null) {
            updated.last_observed_wall_time = Math.max(
              updated.last_observed_wall_time, observed,
            );
          }
          this.liveObserved = observed;
        }
        this.state = updated;
        await this.persist();
        this.assertActive();
        await this.refreshProjection();
        this.assertActive();
      }
      return result;
    });
  }

  async materializeProgram(program, evaluation) {
    return this.enqueueMutation(async () => {
      this.assertActive();
      if (!this.state) throw new Error('Garden runtime is not open');
      const state = this.state;
      const [updated, receipts] = await materializeGardenProgramEffects(
        state, program, evaluation,
      );
      this.assertActive();
      if (this.state !== state) throw new Error('Garden runtime changed during materialization');
      this.state = updated;
      await this.persist();
      this.assertActive();
      await this.refreshProjection();
      this.assertActive();
      return receipts;
    });
  }

  async markStoryComplete(completedAt = null) {
    return this.enqueueMutation(async () => {
      this.assertActive();
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
      this.assertActive();
      await this.refreshProjection();
      this.assertActive();
      return true;
    });
  }

  prepareProgram(program) {
    this.assertActive();
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
    const scene = this.projection.scene ?? {};
    const absence = (scene.absence_summary ?? []).slice(0, 3);
    const missed = (scene.missed_event_summaries ?? []).slice(0, 3);
    const memorial = scene.memorial?.active
      ? ` Memorial lasting; ${(scene.memorial.examined_gifts ?? []).length} gifts remembered.` : '';
    const journal = (scene.journal_entries ?? []).slice(0, 3)
      .map(item => `${item.label}: ${item.description}`).join(' · ');
    const objectState = this.projection.objects.slice(0, 24).map(object =>
      object.semantic_state?.semantic_description ??
      `${object.semantic_name} at ${object.position[0]},${object.position[1]}.`).join(' ');
    return `Garden at ${this.projection.camera[0]},${this.projection.camera[1]}; ${contents || 'quiet'}. Inventory: ${this.state.inventory.join(', ') || 'empty'}. Journal: ${journal || 'waiting'}. ${focus ? `Focused ${focus.semantic_name}.` : 'No object focused.'} Motion ${this.projection.motion_paused ? 'paused' : 'enabled'}.${absence.length ? ` Welcome back: ${absence.join(' · ')}.` : ''}${missed.length ? ` While you were away: ${missed.join(' · ')}.` : ''}${memorial} ${objectState}`;
  }
}
