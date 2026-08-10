/**
 * Exact approved starter-flower pictures.
 *
 * Every non-operator entry is an exact standalone extraction from the two
 * hash-bound legacy flower text files recorded in
 * `docs/garden-asset-acceptance.json::starter_flower_pool`. Horizontal padding
 * used only to separate several examples on one source row is removed; no ink
 * glyph is changed, added, cropped, or substituted. The operator rose retains
 * its separately hash-bound source and authored accent roles.
 *
 * These species IDs are canonical world identity, not renderer variants. The
 * Python and JavaScript generators seed-select one of these IDs and conformance
 * tests compare the resulting world bytes. Painting therefore cannot silently
 * choose a different flower from the one persistence owns.
 */

const COLLECTED_SOURCE = Object.freeze({
  path: 'ascii-animations/flowers/collected-flowers.txt',
  sha256: '80f8d345c1d8d95166b0de3dbbd377d9fa4a7d538c9b660d3acddfe11e5e60d9',
});
const ANIMATION_SOURCE = Object.freeze({
  path: 'ascii-animations/flowers/flower-animations.txt',
  sha256: 'be4e5388056ba39d102e782c352b53b092ebd5cb92314d04e53f2f2bb4bc14c5',
});
const OPERATOR_ROSE_SOURCE = Object.freeze({
  path: 'tracked/LateLetterResearch/transcription-parity/eb861dc84400fc36/accepted.txt',
  sha256: '04bce501c712fc071523711a3ea1b67a8af302434a66f0e638c2bdc144b0baac',
});

const ROSE_LINES = Object.freeze([
  '              (@)(@)(@)',
  '               ,\\|,|,/,',
  '                _\\|/_',
  '               |_____|',
  '               |     |',
  '               |_____|',
]);

const ROSE_ACCENTS = Object.freeze(Object.fromEntries(
  ROSE_LINES.flatMap((line, row) => [...line].flatMap((glyph, column) =>
    glyph === ' ' ? [] : [[`${row},${column}`,
      row === 0 ? 'bloom' : row <= 2 ? 'stem' : 'vessel']]),
  ),
));

function flower(species, section, lines, source = COLLECTED_SOURCE, extra = {}) {
  return Object.freeze({
    species,
    identity: `plant.${species}`,
    section,
    source: source.path,
    sourceSha256: source.sha256,
    lines: Object.freeze(lines),
    sealed: true,
    ...extra,
  });
}

const APPROVED_STARTER_FLOWERS = Object.freeze({
  rose: flower('rose', 'operator-authored rose bush', ROSE_LINES, OPERATOR_ROSE_SOURCE, {
    accents: ROSE_ACCENTS,
  }),
  legacy_rose: flower('legacy_rose', 'ROSE (Unknown artist)', [
    '        .     .',
    "    ...  :``..':",
    "     : ````.'   :''::'",
    "   ..:..  :     .'' :",
    "``.    `:    .'     :",
    '    :    :   :        :',
    '     :   :   :         :',
    '     :    :   :        :',
    "      :    :   :..''''``::.",
    "       : ...:..'     .''",
    "       .'   .'  .::::'",
    "      :..'''``:::::::",
    "      '         `::::",
    '                  `::.',
    '                   `::',
    '                    :::.',
    "         ..:```.:'`. ::'`.",
    "       ..'      `:.: ::",
    '      .:        .:``:::',
    "      .:    ..''     :::",
    "       : .''         .::",
    "        :          .'`::",
    '                       ::',
    '                       ::',
    '                        :',
    '                        :',
    '                        :',
    '                        :',
    '                        .',
  ]),
  legacy_sunflower_sunglasses: flower(
    'legacy_sunflower_sunglasses', 'SUNFLOWER w/ SUNGLASSES (Laura Brown)', [
      '          .',
      '    _/ \\ / \\ / \\_',
      "  _\\ \\ .'- -'. / /_",
      ' \\_ \\,___   ___,/ _/',
      '< _ ( \\__)-(__/ ) _ >',
      ' /_  -  .___.  -  _\\',
      '  /_ / -.. ..- \\ _\\',
      '     \\ / \\ / \\ /',
      "         |'|_.---._,",
      " ,_.---._| |- --- /",
      "  \\ --- -| | '---'",
      "   '---'_|_|___",
      '     [_________]',
      '      \\___ldb_/',
    ],
  ),
  legacy_sunflower: flower('legacy_sunflower', 'SUNFLOWER (Hayley Jane Wakenshaw / Flump)', [
    '           /:.   ,:\\',
    '     .~=-./::: u  ::\\,-~=.',
    '  ___|::  \\    |    /  ::|___',
    " \\::  `.   \\   |   /   .' :::/",
    "  \\:    `.  \\  |  /  .'    :/",
    ".-: `-._  `.;;;;;;.'   _.-' :-.",
    "\\::     `-;;;;;;;;;;;-'     ::/",
    ' >~------~;;;;;;;;;;;~------~<',
    '/::    _.-;;;;;;;;;;;-._    ::\\',
    "`-:_.-'   .`;;;;;;;'.   `-._:-'",
    "   /    .'  /  |  \\  `.   :\\",
    "  /::_.'   /   |   \\   `._::\\",
    '      |:: /    |    \\  ::|',
    "      `=-'\\:::.n.:::/`-=-'      hjw",
    "           \\:'   `:/",
  ]),
  legacy_tulip: flower('legacy_tulip', 'TULIP (Sebastian Stöcker)', [
    "          ,'|/\\",
    '         /  | )\\',
    '        /   |/  :',
    '       :    ;   |',
    '       :   /    ;',
    "        \\,'   ,'",
    '         `,,-\'',
    '         //',
    '  _     // ____',
    " /|`.  /;''/  ,`.",
    ":.:/ \\/,`-',-'. ,'",
    ": `\\,// `-.\\_\\.'",
    ' `._//',
    '   // SSt',
  ]),
  legacy_small_flower: flower('legacy_small_flower', 'SMALL FLOWER (Joan Stark)', [
    '       _ _',
    '      (_\\_)',
    '     (__<_{}',
    '      (_/_)',
    '     |\\ |',
    '    _| \\|  _',
    '   / |     \\',
    '  |  |      |',
    '   \\_|  .. /',
    '     |__|_/   jgs',
  ]),
  legacy_daisy_round: flower('legacy_daisy_round', 'Tiny Daisy :: (*)', [
    '(*)', ' | ', '/|\\',
  ]),
  legacy_daisy_at: flower('legacy_daisy_at', 'Tiny Daisy :: (@)', [
    '(@)', ' | ', '/|\\',
  ]),
  legacy_daisy_brace: flower('legacy_daisy_brace', 'Tiny Daisy :: {*}', [
    '{*}', ' | ', '/|\\',
  ]),
  legacy_small_rose_short: flower('legacy_small_rose_short', 'Small Rose :: short', [
    '@>->--',
  ]),
  legacy_small_rose_long: flower('legacy_small_rose_long', 'Small Rose :: long', [
    '@>--->--',
  ]),
  legacy_medium_flower_round: flower('legacy_medium_flower_round', 'Medium Flower :: round', [
    ".-'-.", '( o o )', " `-.-'", '   |', '  /|\\',
  ]),
  legacy_medium_flower_plain: flower('legacy_medium_flower_plain', 'Medium Flower :: plain', [
    ',-=-,', "( ' ' )", " `-.-'", '   |', '  /|\\',
  ]),
  legacy_medium_flower_at: flower('legacy_medium_flower_at', 'Medium Flower :: at', [
    '.~=~.', '( @ @ )', " `-.-'", '   |', '  /|\\',
  ]),
  legacy_tall_sunflower: flower('legacy_tall_sunflower', 'Tall Sunflower', [
    ' \\|/', '--@--', ' /|\\', '  |', '  |', ' /|\\',
  ]),
  legacy_lily_double: flower('legacy_lily_double', 'Lily :: double', [
    '\\\\ //', ' )|(', '  |', ' /|\\',
  ]),
  legacy_lily_round: flower('legacy_lily_round', 'Lily :: round', [
    '() ()', ' \\|/', '  |', ' /|\\',
  ]),
  legacy_lily_bud: flower('legacy_lily_bud', 'Lily :: bud', [
    '>\\/<', ' )|(', '  |', ' /|\\',
  ]),
  legacy_bloom_full: flower(
    'legacy_bloom_full', 'BLOOM ANIMATION: Flower Opening :: Frame 6 (full)', [
      '.-===-.', '( @   @ )', " `-._.-'", '    |', '   /|\\',
    ], ANIMATION_SOURCE,
  ),
});

export const APPROVED_STARTER_FLOWER_SPECIES = Object.freeze(
  Object.keys(APPROVED_STARTER_FLOWERS),
);

export function approvedStarterFlowerPresentation(species) {
  const entry = APPROVED_STARTER_FLOWERS[String(species ?? '')];
  if (!entry) return null;
  return {
    lines: [...entry.lines],
    accents: entry.accents ? { ...entry.accents } : null,
    sealed: true,
    animated: false,
    identity: entry.identity,
    source: entry.source,
    sourceSection: entry.section,
    sourceSha256: entry.sourceSha256,
  };
}

export function approvedStarterFlowerCatalog() {
  return Object.values(APPROVED_STARTER_FLOWERS).map(entry => ({
    species: entry.species,
    identity: entry.identity,
    section: entry.section,
    source: entry.source,
    source_sha256: entry.sourceSha256,
    lines: [...entry.lines],
  }));
}
