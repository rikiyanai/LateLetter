/**
 * Operator-authored Garden pictures accepted as exact text assets.
 *
 * This is deliberately separate from the legacy archive and from the
 * renderer's placeholder tables: these bytes were authored and approved by
 * the operator on 2026-08-03.  Leading spaces are part of the composition;
 * trailing spaces are not.  The source receipt is
 * tracked/LateLetterResearch/transcription-parity/eb861dc84400fc36/.
 */

const OPERATOR_PLANT_ART = Object.freeze({
  rose: Object.freeze({
    identity: 'plant.rose',
    sha256: '04bce501c712fc071523711a3ea1b67a8af302434a66f0e638c2bdc144b0baac',
    lines: Object.freeze([
      '              (@)(@)(@)',
      '               ,\\|,|,/,',
      '                _\\|/_',
      '               |_____|',
      '               |     |',
      '               |_____|',
    ]),
  }),
});

export function operatorPlantPresentation(species) {
  const entry = OPERATOR_PLANT_ART[String(species ?? '')];
  if (!entry) return null;
  return {
    lines: [...entry.lines],
    identity: entry.identity,
    sourceSha256: entry.sha256,
  };
}

