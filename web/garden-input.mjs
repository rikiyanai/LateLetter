/** Neutral browser-side normalization for canonical Garden commands. */

export const ACTIONS = Object.freeze([
  'move_focus',
  'pan',
  'inspect',
  'primary_interact',
  'open_actions',
  'tend',
  'feed',
  'play',
  'collect',
  'place',
  'move_fixture',
  'undo',
  'open_journal',
  'pause_motion',
  'back',
]);

export const MODALITIES = Object.freeze([
  'touch',
  'mouse',
  'browser_keyboard',
  'terminal',
]);

const INTENT_FIELDS = Object.freeze({
  touch: 'control',
  mouse: 'control',
  browser_keyboard: 'binding',
  terminal: 'command',
});

/** Python-compatible Unicode scalar ordering for canonical JSON keys. */
export function compareUnicodeScalars(leftValue, rightValue) {
  const left = Array.from(String(leftValue), character => character.codePointAt(0));
  const right = Array.from(String(rightValue), character => character.codePointAt(0));
  const count = Math.min(left.length, right.length);
  for (let index = 0; index < count; index += 1) {
    if (left[index] !== right[index]) return left[index] < right[index] ? -1 : 1;
  }
  return left.length === right.length ? 0 : left.length < right.length ? -1 : 1;
}

function canonicalValue(value) {
  if (Array.isArray(value)) return value.map(canonicalValue);
  if (value !== null && typeof value === 'object') {
    return Object.fromEntries(
      Object.keys(value).sort(compareUnicodeScalars)
        .map(key => [key, canonicalValue(value[key])]),
    );
  }
  return value;
}

export function canonicalJson(value) {
  return JSON.stringify(canonicalValue(value));
}

export async function sha256Hex(text) {
  if (!globalThis.crypto?.subtle) {
    throw new Error('WebCrypto SHA-256 is required for Garden command IDs');
  }
  const digest = await globalThis.crypto.subtle.digest(
    'SHA-256', new TextEncoder().encode(text),
  );
  return Array.from(new Uint8Array(digest), byte =>
    byte.toString(16).padStart(2, '0')).join('');
}

export async function stableId(namespace, ...parts) {
  const digest = await sha256Hex(canonicalJson([namespace, ...parts]));
  return `${namespace}:${digest.slice(0, 24)}`;
}

export function validateGardenCommand(value) {
  const errors = [];
  if (!Number.isInteger(value.sequence) || value.sequence < 1) {
    errors.push('sequence must be positive');
  }
  const targetRequired = new Set([
    'inspect', 'tend', 'feed', 'play', 'collect', 'move_fixture',
  ]);
  if (targetRequired.has(value.kind) && !value.target_id) {
    errors.push(`${value.kind} requires target_id`);
  }
  if (value.kind === 'pan' && !('dx' in value.args || 'dy' in value.args)) {
    errors.push('pan requires dx and/or dy');
  }
  if (value.kind === 'place') {
    if (!['fixture', 'plant'].includes(value.args.object_kind ?? 'fixture')) {
      errors.push('place object_kind must be fixture or plant');
    }
    if (!('catalog_id' in value.args)) errors.push('place requires catalog_id');
    if (!('x' in value.args) || !('y' in value.args)) {
      errors.push('place requires x and y');
    }
  }
  if (value.kind === 'move_fixture' &&
      (!('x' in value.args) || !('y' in value.args))) {
    errors.push('move_fixture requires x and y');
  }
  return errors;
}

/**
 * Convert one modality-specific resolved intent into the canonical command.
 * Device metadata is accepted for diagnostics but never enters command bytes.
 */
export async function normalizeGardenInput(envelope) {
  const modality = String(envelope.modality ?? '');
  if (!MODALITIES.includes(modality)) {
    throw new Error(`unsupported input modality: ${modality}`);
  }
  const intentField = INTENT_FIELDS[modality];
  const kind = envelope[intentField];
  if (kind === undefined || kind === null) {
    throw new Error(`${modality} intent requires ${intentField}`);
  }
  if (!ACTIONS.includes(String(kind))) {
    throw new Error(`unknown garden action: ${kind}`);
  }
  const args = envelope.args ?? {};
  if (args === null || Array.isArray(args) || typeof args !== 'object') {
    throw new Error('args must be a mapping');
  }
  const targetId = envelope.target_id === undefined || envelope.target_id === null
    ? null : String(envelope.target_id);
  const sequence = Number(envelope.sequence);
  const normalized = {
    command_id: await stableId(
      'command',
      String(envelope.world_id),
      sequence,
      String(kind),
      targetId,
      args,
    ),
    sequence,
    kind: String(kind),
    target_id: targetId,
    args: canonicalValue(args),
  };
  const errors = validateGardenCommand(normalized);
  if (errors.length) throw new Error(errors.join('; '));
  return normalized;
}

export function semanticBytes(command) {
  return new TextEncoder().encode(canonicalJson(command));
}
