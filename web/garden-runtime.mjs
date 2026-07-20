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
  }

  get storageKey() { return `${WORLD_STORAGE_PREFIX}${this.worldId}`; }

  async open() {
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
  }

  async materializeProgram(program, evaluation) {
    if (!this.state) throw new Error('Garden runtime is not open');
    const [updated, receipts] = await materializeGardenProgramEffects(
      this.state, program, evaluation,
    );
    this.state = updated;
    await this.persist();
    await this.refreshProjection();
    return receipts;
  }

  prepareProgram(program) {
    if (!this.state) throw new Error('Garden runtime is not open');
    this.state = seedGardenProgramState(this.state, program);
    return this.state.program_state;
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
