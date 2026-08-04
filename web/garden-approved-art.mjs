/**
 * Operator-authored Garden pictures accepted as exact text assets.
 *
 * This is deliberately separate from the legacy archive and from the
 * renderer's placeholder tables: these bytes were authored and approved by
 * the operator on 2026-08-03.  Leading spaces are part of the composition;
 * trailing spaces are not.  The source receipt is
 * tracked/LateLetterResearch/transcription-parity/eb861dc84400fc36/.
 */

const ROSE_LINES = Object.freeze([
  '              (@)(@)(@)',
  '               ,\\|,|,/,',
  '                _\\|/_',
  '               |_____|',
  '               |     |',
  '               |_____|',
]);

// Part roles are authored beside the exact text, not inferred by the painter.
// The bytes remain the approved asset; these roles state how its three visible
// materials participate in the current palette.
const ROSE_ACCENTS = Object.freeze(Object.fromEntries(
  ROSE_LINES.flatMap((line, row) => [...line].flatMap((glyph, column) =>
    glyph === ' ' ? [] : [[`${row},${column}`,
      row === 0 ? 'bloom' : row <= 2 ? 'stem' : 'vessel']]),
  ),
));

const OPERATOR_PLANT_ART = Object.freeze({
  rose: Object.freeze({
    identity: 'plant.rose',
    sha256: '04bce501c712fc071523711a3ea1b67a8af302434a66f0e638c2bdc144b0baac',
    lines: ROSE_LINES,
    accents: ROSE_ACCENTS,
    sealed: true,
  }),
});

export function operatorPlantPresentation(species) {
  const entry = OPERATOR_PLANT_ART[String(species ?? '')];
  if (!entry) return null;
  return {
    lines: [...entry.lines],
    accents: { ...entry.accents },
    sealed: Boolean(entry.sealed),
    identity: entry.identity,
    sourceSha256: entry.sha256,
  };
}
