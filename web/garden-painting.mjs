/**
 * The Garden painting layer: palettes, art tables, layout, and the painters.
 * --------------------------------------------------------------------------
 *
 * Everything in this module is PURE: functions and frozen tables with no DOM,
 * no clock source of its own, no hostname and no surface class. It exists as
 * its own module because of the reopened architecture route (2026-08-04,
 * step 4): while the painters lived beside `CanonicalGardenRenderer`, the
 * presentation owner had to import the renderer to reach them, and the
 * renderer imported the presentation interface back -- a circular import
 * that made the "owner" a wrapper over the surface it was meant to command.
 * Now the graph is a line: this module imports no Garden presentation or
 * surface code; `garden-presentation.mjs` imports the painters from here to
 * decide the frame; `garden-renderer.mjs` imports both to be the DOM
 * adapter, and re-exports this module whole so existing importers keep the
 * surface they always had.
 *
 * World state, topology, positions, hit targets, actions, animal intent, and
 * time remain owned by garden-world.mjs/GardenRuntime.  This module owns only
 * disposable pixels: palette, multi-cell silhouettes, wind frames, particles,
 * and hover/click feedback.  Nothing here is persisted or fed back to gameplay.
 */

import { glyphForProjection, organGlyph } from './garden-atlas.mjs';
import { canonicalProportionalArt } from './garden-atlas-art.mjs';
import { projectSkyPoints } from './garden-sky.mjs';
// Plant and animal drawings transcribed from the legacy archive, together with
// the whole-frame sway the archive animates them with. These are the only
// plant/animal pictures the operator has approved (grant of 2026-08-01,
// "PLANTS ANIMATIONS IN LEGACY ARE APPROVED VISUALLY"); everything this module
// still draws for the species the archive does not cover is an unapproved
// placeholder, kept only so an authored program that places one is not blank.
import {
  legacyAnimalPresentation, legacyPlantPresentation,
} from './garden-legacy-art.mjs';
import { approvedStarterFlowerPresentation } from './garden-approved-art.mjs';
import { compareCodePoints } from './garden-world.mjs';

const DEPTH = Object.freeze({ stars: 0.02, distant: 0.20, far: 0.55, world: 1, foreground: 1.15 });
export const DAY = Object.freeze({
  sky: '#f9f8f5', ground: '#c8c2b6', soil: '#ddd8ce', dimGreen: '#ddd8ce', dim: '#b0a898',
  green: '#4a7030', brightGreen: '#62923e', deepGreen: '#33511e', brown: '#7a5830',
  flower: '#a03888', flower2: '#b85038', gold: '#c09428', water: '#4a6888',
  // Semantic accent, not decoration: the one colour the garden is allowed to
  // spend on "something has arrived". Reserved for the `signal` accent role.
  flag: '#b3241c',
  creature: '#68472d', stone: '#6f695f', star: '#817b6b', moon: '#aaa184', text: '#443d35',
});
export const NIGHT = Object.freeze({
  sky: '#0b0e16', ground: '#28302a', soil: '#13181e', dimGreen: '#13181e', dim: '#606058',
  green: '#5a9858', brightGreen: '#78b870', deepGreen: '#41703e', brown: '#a08868',
  flower: '#d068b8', flower2: '#e87868', gold: '#e0b848', water: '#7898b8',
  flag: '#e2564a',
  creature: '#c0a078', stone: '#a0a098', star: '#b8b8a8', moon: '#e8e4d0', text: '#d0ccc0',
});
export const EVENING = Object.freeze({ ...DAY, sky: '#ecd6b6', ground: '#d8bea2', star: '#766979' });
const MOON_ART = Object.freeze([
  [], ['  _', ' ) ', ' ‾ '], [' _ ', '|) ', ' ‾ '], [' __ ', '(O) ', ' ‾‾ '],
  [' __ ', '(  )', ' ‾‾ '], [' __ ', ' (O)', ' ‾‾ '], [' _ ', ' (|', ' ‾ '], [' _ ', ' ( ', ' ‾ '],
]);
const ANIMAL_POSES = Object.freeze({
  cat: Object.freeze({
    play: [[" /\\_/\\", ' (o.o)', '  >o< '], [" /\\_/\\", ' (O.o)', '  /o/ ']],
    greet: [[" /\\_/\\", ' (o.o)', '  /|  '], [" /\\_/\\", ' (o.O)', '  |\\  ']],
    rest: [[" /\\_/\\", ' (-.-)', '  ~~~ '], [" /\\_/\\", ' (zzz)', '  ~~~ ']],
    approach: [[" /\\_/\\", ' (o.o)', ' __/  '], [" /\\_/\\", ' (o.o)', '  /__ ']],
    retreat: [[" /\\_/\\", ' (o.o)', '  \\__ '], [" /\\_/\\", ' (o.o)', ' __/  ']],
    groom: [[" /\\_/\\", ' (o.-)', '  /)  '], [" /\\_/\\", ' (-.o)', '  (\\  ']],
    forage: [[" /\\_/\\", ' (..o)', ' _/   '], [" /\\_/\\", ' (o..)', '   \\_']],
    perform: [[" /\\_/\\", ' (O.O)', ' \\ | /'], [" /\\_/\\", ' (o.o)', ' / | \\']],
  }),
  bird: Object.freeze({
    play: [['  \\o/ ', ' --|--'], ['  >o< ', ' --|--']],
    greet: [['  >o< ', '  /|  '], ['  \\o/ ', '   |  ']],
    rest: [['  (o) ', ' --|--'], ['  (-) ', ' --|--']],
    approach: [['   >o<', '  /|  '], [' >o<  ', '   |  ']],
    retreat: [['<o<   ', '  |\\  '], ['  <o< ', '  |   ']],
    groom: [['  (o) ', '  /|  '], ['  (o) ', '  |\\  ']],
    forage: [['  (.) ', ' --|--'], ['  (o) ', ' --|--']],
    perform: [[' \\ o /', '-- | --'], ['  >o< ', ' --|--']],
  }),
  rabbit: Object.freeze({
    play: [['  (\\ /)', '  (o.o)', '  /   \\'], ['  (\\ /)', '  (o.o)', '   /\\ ']],
    greet: [['  (\\ /)', '  (o.o)', '  /|  '], ['  (\\ /)', '  (o.o)', '   |\\ ']],
    rest: [['  (\\./)', '  (-.-)', '  ~~~ '], ['  (\\./)', '  (zzz)', '  ~~~ ']],
    approach: [['  (\\ /)', '  (o.o)', ' __/  '], ['  (\\ /)', '  (o.o)', '  /__ ']],
    retreat: [[' (\\ /) ', ' (o.o) ', '  \\__  '], ['(\\ /)  ', '(o.o)  ', ' __/   ']],
    groom: [['  (\\./)', '  (o.-)', '  /)  '], ['  (\\./)', '  (-.o)', '  (\\  ']],
    forage: [['  (\\ /)', '  (..o)', '  . . '], ['  (\\ /)', '  (o..)', ' . .  ']],
    perform: [[' \\(\\ /)/', '  (O.O)', '  /   \\'], ['  (\\ /)', ' \\(o.o)/', '   /\\ ']],
  }),
  turtle: Object.freeze({
    play: [['  __  ', ' /o \\_', '{____}'], ['   __ ', ' _/ o\\', '{____}']],
    greet: [['  __  ', ' /o \\_', '{____}'], ['  __  ', '_/ o\\ ', '{____}']],
    rest: [['  ___ ', ' / - \\', '{_____}'], ['  ___ ', ' / z \\', '{_____}']],
    approach: [['   __ ', ' _/ o\\', '{____}'], ['  __  ', ' /o \\_', '{____}']],
    retreat: [[' __   ', '/o \\_ ', '{____}'], ['  __  ', ' _/o \\', '{____}']],
    groom: [['  __  ', ' /o-\\ ', '{____}'], ['  __  ', ' /-o\\ ', '{____}']],
    forage: [['  __  ', ' /._\\ ', '{____}'], ['  __  ', ' /_.\\ ', '{____}']],
    perform: [['  ___ ', '_/O O\\', '{_____}'], ['  ___ ', ' /o o\\', '{_____}']],
  }),
});

// The starter cat is a resident character, not a three-line face token. These
// full poses preserve ears, muzzle, body, paws and tail in every routine. The
// existing smaller pose family remains the independently authored compact set.
const STARTER_CAT_FULL_POSES = Object.freeze({
  play: [
    ['   /\\____/\\      ', '  (  =..=  )     ', '   \\   --  /  __ ', '  /|______|\\_/  )', ' (_/      \\____/ '],
    ['      /\\____/\\   ', '     (  =..=  )  ', '  __  \\  --   /   ', ' (  \\_/|_____|\\  ', '  \\____/     \\_) '],
  ],
  greet: [
    ['    /\\____/\\    ', '   (  =..=  )   ', '    \\   --  /    ', '    /|____|\\___ ', '   (_/    \\___/ '],
    ['    /\\____/\\    ', '   (  =.-=  )   ', '    \\   --  /    ', ' ___/|____|\\    ', ' \\___/    \\_)   '],
  ],
  rest: [
    ['    /\\____/\\      ', '   (  =--=  )     ', '  /  `------`  \\   ', ' (______________)~~'],
    ['    /\\____/\\      ', '   (   z  z   )     ', '  /  `------`  \\   ', ' (______________)~~'],
  ],
  approach: [
    ['   /\\____/\\       ', '  (  =..=  )      ', ' __\\   --  /       ', '/   |____|\\____~~ ', '\\___/    \\_/     '],
    ['      /\\____/\\    ', '     (  =..=  )   ', '    /\\   --  /__  ', '~~_/  |____|   \\  ', '      \\_/  \\___/  '],
  ],
  retreat: [
    ['       /\\____/\\   ', '      (  =..=  )  ', '   __  \\  --   /   ', '~~/   /|_____|\\   ', '  \\___/    \\_/    '],
    ['  /\\____/\\        ', ' (  =..=  )       ', '  \\   --  /\\      ', '   /|____|  \\_~~ ', '  (_/  \\___/      '],
  ],
  groom: [
    ['    /\\____/\\    ', '   (  =.-=  )   ', '    \\   --  /    ', '    /|___/)/~~  ', '   (_/   \\_)    '],
    ['    /\\____/\\    ', '   (  -.=  )   ', '    \\   --  /    ', '  ~~(\\___|\\    ', '    (_/   \\_)   '],
  ],
  forage: [
    ['       /\\____/\\ ', '  ____/  =..=  ) ', ' /       __..__/  ', '(_______/  \\_)~~ '],
    [' /\\____/\\       ', '(  =..=  \\____  ', ' \\__..__       \\ ', '~~(_/  \\_______) '],
  ],
  perform: [
    ['     /\\____/\\     ', '    (  =OO=  )    ', '   __\\   --  /__   ', '  /   |____|   \\  ', ' (_   /    \\   _) '],
    ['   \\ /\\____/\\ /   ', '    (  =..=  )    ', '     \\  --  /     ', '    /|____|\\     ', '   (_/    \\_)    '],
  ],
});
/**
 * Collectible pictures.
 *
 * Each identity carries two purpose-drawn pictures rather than one picture that
 * gets trimmed. A single arbitrary character — `⌁` for an oak leaf, `;` for a
 * lavender sprig, `♢` for an acorn — is unique but tells the reader nothing:
 * it depicts nothing, and three of them sitting in open ground read as stray
 * marks rather than as things worth picking up. Reduction that deletes interior
 * lines only makes a small picture smaller, so the compact form is drawn on
 * purpose to stay recognisable at its own size.
 *
 * `full` is used at full density, `compact` at medium and compact. Both are
 * required to be unique within the collectible set, at every density, by test.
 */
const COLLECTIBLE_ART = Object.freeze({
  // A lobed leaf hanging from its stem.
  oak_leaf: { full: [' (%%) ', '(%%%%)', '  \\|  '], compact: ['(%%)', ' \\| '] },
  // A flowering spike: buds up the stalk.
  lavender_sprig: { full: [' :  : ', ' ;::; ', '  ||  '], compact: [';::;', ' || '] },
  // Six arms.
  first_snowflake: { full: [' \\ | / ', '--- ---', ' / | \\ '], compact: ['\\|/', '/|\\'] },
  // A nut sitting in its cup.
  fallen_acorn: { full: ['  __  ', ' /oo\\ ', ' \\__/ '], compact: ['/oo\\', '\\__/'] },
  // Two prints in soft ground.
  rabbit_track: { full: [' ..  ..', ' ::  ::', '       '], compact: ['.. ..', ':: ::'] },
  // A quill: vane along one side of a shaft.
  bird_feather: { full: ['   /)) ', '  //// ', ' |     '], compact: ['/))', '// '] },
  // A pressed bloom, flattened and kept.
  pressed_flower: { full: [' *@@* ', ' @@@@ ', '  ||  '], compact: ['*@@*', ' || '] },
  // Bow, shaft and ward.
  small_key: { full: [' o==. ', ' o== | ', '      '], compact: ['o==.', 'o==|'] },
  // Family fallbacks, for a collectible whose catalogue identity is unknown to
  // this renderer. Still pictures, never bare marks.
  plant_species: { full: [' (..) ', '(....)', '  \\|  '], compact: ['(..)', ' \\| '] },
  seasonal_natural_find: { full: ['  ..  ', ' .**. ', '  ..  '], compact: ['.**.', ' .. '] },
  animal_trace: { full: [' ..   ', ' ::   ', '      '], compact: ['..', '::'] },
  authored_keepsake: { full: ['  /\\  ', ' <  > ', '  \\/  '], compact: ['/\\', '\\/'] },
  feather: { full: ['   ))) ', '  //// ', ' |     '], compact: [')))', '///'] },
});
/**
 * Fixture pictures.
 *
 * Two rules, both learned from the pictures these replace:
 *
 * 1. A picture must be big enough to be recognised. One or two lines of three
 *    characters is a hint, not a silhouette, and a reader looking at the Garden
 *    could not name a single object on screen.
 * 2. A picture must be unique. `gate` and `fence_gate` were byte-identical, as
 *    were `table` and `table_chairs`, and five further pairs shared their first
 *    line — which is all a reader sees once level-of-detail reduction trims the
 *    rest. Two catalogue entries that look the same are two objects the reader
 *    cannot tell apart.
 *
 * Uniqueness is enforced by test at every density rather than by inspection
 * here, because reduction can make two distinct pictures collide.
 *
 * Deliberately avoided throughout: `v`, `>o<` and `{}`, which belong to the
 * creature vocabulary. A fixture must never read as an animal.
 */
const FIXTURE_DECOR = Object.freeze({
  // arbor, birdbath, bridge, lantern, mailbox, planter, pond, stepping_stones, trellis were here. Each is now drawn in the
  // versioned atlas (atlas.v2.json) and reaches this module through
  // garden-atlas-art.mjs. They were deleted in the same change that made
  // the atlas their owner: leaving them as a fallback would preserve the
  // split ownership the migration exists to end.
  // `bench` was here. It now lives in the versioned atlas
  // (`fixture.bench`, atlas.v2.json) and reaches this module through
  // `garden-atlas-art.mjs`. It was deleted in the same change that made the
  // atlas its owner -- leaving it as a fallback would have preserved exactly
  // the split ownership the migration exists to end.
  sundial: ['   \\|/   ', '  --O--  ', '   /|\\   '],
  memory_shrine: ['  /\\_/\\ ', ' | *** | ', ' |_____| '],
  fence: ['-+-+-+-', ' | | | '],
  gate: ['-+   +-', ' |   | '],
  fence_gate: ['-+ | +-', ' | | | '],
  stepping_stone: ['(o)'],
  table: [' .====. ', '   ||   '],
  chair: [' |=| ', ' |_| '],
  table_chairs: ['o.====.o', '   ||   '],
  well: ['  /^\\  ', ' |[o]| ', ' |___| '],
  wind_chime: ['  ===  ', ' | | | ', ' o o o '],
  shed_edge: [' /|\\    ', '|_[]___|'],
  tool_rack: ['|=====|', '| /|\\ |'],
  watering_can: ['  __o  ', ' |__|> '],
  compost: [' .~~~. ', '(%%%%%)'],
  basket: [' \\uuu/ ', '  \\_/  '],
  sign: ['+------+', '|GARDEN|', '   ||   '],
  memorial_stone: ['  .-.  ', ' | + | ', ' |___| '],
});

/**
 * Purpose-drawn pictures for the visible starter tableau.
 *
 * These are illustrations, not catalog tokens enlarged with padding. Full and
 * compact are independently authored so a phone never receives a desktop
 * picture with its identifying middle cut out.
 */
const STARTER_FIXTURE_ART = Object.freeze({
  // lantern, mailbox, planter, stepping_stones were here. Each is now drawn in the
  // versioned atlas (atlas.v2.json) and reaches this module through
  // garden-atlas-art.mjs. They were deleted in the same change that made
  // the atlas their owner: leaving them as a fallback would preserve the
  // split ownership the migration exists to end.
  // `bench` was here, and this was the drawing that actually rendered -- this
  // table is consulted before FIXTURE_DECOR, which held a second, different
  // bench. Both were deleted when `fixture.bench` moved into the versioned
  // atlas, which now carries this exact picture along with its authored compact
  // variant. See `scripts/migrate_atlas_v2.py`.
});

const STARTER_PLANT_ART = Object.freeze({
  oak: Object.freeze({
    full: [
      '    &&&  &&      ',
      '  &&&&&&&&&&     ',
      ' &&&&&&&&&&&&    ',
      '   && \\|/ &&     ',
      '      ||         ',
      '      ||         ',
      '    __||__       ',
    ],
    compact: [
      '    &&&&&&&    ',
      '  &&&&&&&&&&&  ',
      ' &&&&&&&&&&&&& ',
      '   && \\|/ &&   ',
      '      ||       ',
      '    __||__     ',
    ],
  }),
  hydrangea: Object.freeze({
    full: [
      ' .@@@.   .@@@.  ',
      '(@@@@@) (@@@@@) ',
      ' `@@@`\\ /`@@@`  ',
      '   /\\  V  /\\    ',
      '__/  \\___/  \\__ ',
    ],
    compact: ['  .@@@. .@@@.  ', ' (@@@@@)(@@@@@) ', '  `@@/\\/\\@@`  ', ' __/      \\__ '],
  }),
  meadow_grass: Object.freeze({
    full: [
      " \\ | /\\ | /   ",
      "  \\|/  \\|/    ",
      "__/|\\__/|\\__  ",
    ],
    compact: [" \\\\ | // \\\\|// ", "  \\\\|//   \\|/  ", '__/|\\____/|\\__'],
  }),
  lavender: Object.freeze({
    full: [
      ' :::  :::  ::: ',
      ' ;;;  ;;;  ;;; ',
      ' \\|/  \\|/  \\|/ ',
      '__|____|____|__',
    ],
    compact: ['  :::  :::  ', '  ;;;  ;;;  ', '  \\|/  \\|/  ', '__/|____|\\__'],
  }),
  sunflower: Object.freeze({
    full: [
      ' \\ | / ',
      '--(@)--',
      '  /|\\  ',
      '   |   ',
      ' \\_|_/ ',
      ' __|__ ',
    ],
    compact: ['  \\|/  ', '--(@)--', '   |   ', ' \\_|_/ ', ' __|__ '],
  }),
});

const STARTER_COLLECTIBLE_ART = Object.freeze({
  fallen_acorn: Object.freeze({
    full: [
      '   ,   ',
      ' _###_ ',
      '/_____\\',
      ' \\   / ',
      '  \\_/  ',
    ],
    compact: ['   ,   ', ' _###_ ', '/_____\\', ' \\___/ '],
  }),
});

function clamp(value, low, high) { return Math.max(low, Math.min(high, value)); }
function roundHalfAway(value) { return Math.sign(value) * Math.floor(Math.abs(value) + 0.5); }
export function escapeHtml(value) {
  return value.replaceAll('&', '&amp;').replaceAll('<', '&lt;').replaceAll('>', '&gt;');
}
export function stringHash(value) {
  let hash = 2166136261;
  for (const glyph of String(value)) { hash ^= glyph.codePointAt(0); hash = Math.imul(hash, 16777619); }
  return hash >>> 0;
}
function noise(seed) {
  let value = seed >>> 0;
  value ^= value >>> 16; value = Math.imul(value, 0x7feb352d);
  value ^= value >>> 15; value = Math.imul(value, 0x846ca68b); value ^= value >>> 16;
  return (value >>> 0) / 4294967296;
}
function wrap(value, size) { return ((value % size) + size) % size; }

/**
 * Continuous position for one small ambient traveller.
 *
 * worldId  seeds the whole arrangement so a Garden looks the same on reload
 * index    which traveller; also picks its speed and direction
 * frame    presentation frame counter
 * width    raster width in cells
 * horizon  soil line, the hard lower bound for anything in the air
 * band     optional [top, bottom] rows to confine the traveller to
 *
 * `band` exists because "anywhere between the top of the frame and the soil" is
 * not a plausible place for every kind of ambient life. A butterfly belongs
 * among the planting; drawing it by a uniform draw over the full height strands
 * it alone in empty sky, which reads as a rendering fault rather than as a
 * butterfly. Callers pass the band that suits the creature.
 *
 * Returns [column, row]. Successive frames move at most one cell in each axis,
 * which is what makes this a trajectory rather than a teleport.
 */
export function ambientEntityPosition(worldId, index, frame, width, horizon, band = null) {
  const seed = stringHash(`${worldId}:ambient:${index}`);
  const span = Math.max(5, width + 4), cadence = 6 + (index % 3) * 2;
  const direction = index % 2 ? 1 : -1;
  const travel = Math.floor(Math.max(0, frame) / cadence) * direction;
  const x = wrap(Math.floor(noise(seed) * span) + travel, span) - 2;
  // Default band is the whole airspace, preserving the original behaviour for
  // callers that do not care where their traveller sits.
  const low = clamp(band ? Math.min(band[0], band[1]) : 1, 1, Math.max(1, horizon - 2));
  const high = clamp(band ? Math.max(band[0], band[1]) : horizon - 2, low, Math.max(1, horizon - 2));
  const baseY = clamp(
    low + Math.floor(noise(seed + 29) * Math.max(1, high - low + 1)), low, high,
  );
  const bobCycle = [0, 0, 1, 1, 0, 0, -1, -1];
  const bob = bobCycle[Math.floor((Math.max(0, frame) + (seed % 11)) / 4) % bobCycle.length];
  return [x, clamp(baseY + bob, low, high)];
}

/**
 * Cloud pictures, smallest first. Clouds vary in size as well as in speed and
 * altitude, because a sky of identically sized shapes reads as wallpaper.
 * Deliberately built from `.`, `-`, `~`, `(` and `)` only: none of those are
 * part of any creature vocabulary, so a cloud can never be misread as an
 * animal, and none collides with the glyphs the ambient-life tests police.
 */
const CLOUD_SHAPES = Object.freeze([
  ['      _..--.._      ', '  _.-`        `-._  ', '(___..________..___)'],
  ['   .-~~-.  ', '.-(      )-.', ' `-.___.-` '],
  ['        __        ', '  _..--`  `--.._  ', '(___          ___)'],
  ['  .--.       ', '.(    )__.   ', ' `--`    `--.'],
]);

/**
 * Where cloud `index` sits this frame.
 *
 * Clouds drift slowly and steadily; each has its own speed, altitude and
 * shape, all seeded from the world so the sky is stable across reloads.
 *
 * skyTop / skyBottom bound the region the sky owns — above the tallest thing
 * that grows out of the ground, so a cloud never collides with a canopy.
 *
 * Returns {x, y, lines}: `lines` is the picture, `y` is its TOP row.
 */
export function skyCloudPresentation(
  worldId, index, frame, width, skyTop, skyBottom, count = 4,
) {
  const seed = stringHash(`${worldId}:cloud:${index}`);
  const shape = CLOUD_SHAPES[seed % CLOUD_SHAPES.length];
  const shapeWidth = Math.max(...shape.map(line => [...line].length));
  // Travel across the full width plus the picture, so a cloud leaves the frame
  // completely before reappearing on the other side.
  const span = Math.max(8, width + shapeWidth + 4);
  // Higher clouds drift more slowly, which is the ordinary read on depth.
  const cadence = 10 + (seed % 14);
  const direction = index % 2 ? 1 : -1;
  const travel = Math.floor(Math.max(0, frame) / cadence) * direction;
  // Stratified start: each cloud owns one slice of the width and is jittered
  // inside it. A purely random draw clumps two or three clouds into the same
  // corner and leaves the rest of a wide sky bare, which is what an unassisted
  // seed did here.
  const slice = span / Math.max(1, count);
  const start = Math.floor(slice * index + noise(seed + 5) * slice);
  const x = wrap(start + travel, span) - shapeWidth - 2;
  // Altitude is stratified the same way, so clouds occupy different heights
  // instead of stacking along one line.
  const low = Math.max(0, skyTop);
  const high = Math.max(low, skyBottom - shape.length);
  const lanes = Math.max(1, high - low + 1);
  // One altitude lane per cloud, jittered within the lane. Spacing them evenly
  // down the sky is what stops every cloud from stacking against the top edge
  // and leaving the middle of a tall frame bare.
  const laneHeight = lanes / Math.max(1, count);
  const y = low + Math.floor(laneHeight * index + noise(seed + 61) * laneHeight);
  return { x, y: Math.min(y, high), lines: shape };
}



// `weatherParticlePosition` stood here: a stateless hash of (worldId, kind,
// index, frame) standing in for the deployed particle system. Deleted by
// reopened step 5 -- weather particles are lifecycle actors owned by the
// presentation state advance, and a per-frame recomputation cannot be a
// port of an engine that accumulates.

/**
 * Responsive, disposable browser presentation profile. Canonical coordinates
 * and camera remain the source values; this profile only decides how much of
 * the fixed-size world can be read at the current character-cell viewport.
 */
export function gardenPresentationProfile(viewport, worldSize = [120, 80]) {
  const width = Math.max(20, Number(viewport?.[0]) || 20);
  const height = Math.max(10, Number(viewport?.[1]) || 10);
  const worldWidth = Math.max(1, Number(worldSize?.[0]) || 120);
  const worldHeight = Math.max(1, Number(worldSize?.[1]) || 80);
  const horizon = clamp(height - 3, 4, height - 2);
  // How much of the frame the Garden itself occupies. The remainder is sky.
  //
  // A fixed 22-line cap meant that the taller the display, the larger the share
  // of it that was reserved for sky and then left empty — two thirds of a
  // desktop frame held nothing but three characters in daylight. Scaling with
  // the frame keeps the reserved sky proportionate to what there is to put in
  // it, while the absolute cap still stops an enormous display from turning the
  // Garden into a wall.
  const bandRows = Math.min(
    48,
    Math.max(4, Math.floor(height * 0.72)),
    Math.max(4, horizon - 2),
  );
  const bandTop = Math.max(1, horizon - bandRows);
  const lod = width < 60 || bandRows < 8 ? 'compact' :
    width < 80 || bandRows < 14 ? 'medium' : 'full';

  // ── The ground plane ────────────────────────────────────────────────────
  // This Garden is drawn side-on, so a world coordinate's second component is
  // DEPTH INTO THE SCENE, not height above it. Something standing further back
  // is drawn a little higher up the screen and a little smaller, but its feet
  // still rest on soil. Treating that component as altitude — which is what
  // happens when the whole object band is used as vertical spread — leaves
  // benches, bridges, ponds and rabbits hanging in mid-air with nothing
  // underneath them.
  //
  // `groundRows` is how many character lines the walkable plane recedes over.
  // Everything that lives on the ground gets its FEET placed on one of these
  // lines; the object band above them exists for the parts of a thing that
  // rise into the air (a tree's canopy, a bird in flight), not for its base.
  //
  // The plane takes most of the band. A shallow plane would collapse the whole
  // Garden onto a strip along the bottom edge, losing every sense of one thing
  // standing behind another; a plane that filled the band would leave no room
  // above it for the parts of things that genuinely rise into the air. Three
  // quarters keeps real recession while reserving headroom for canopies.
  // The 16-line ceiling that used to sit here was binding on any large display:
  // the plane stopped well short of the band, objects bunched along the bottom,
  // and the rows between the treetops and the clouds were left as a void. The
  // plane is allowed to be genuinely deep so the Garden occupies its frame.
  // ONE RECEDING TERRAIN PLANE. Canonical world y selects a stable band on
  // this plane; painters never repack an object onto a different band.
  //
  // The receding plane described above is switched off, and the reason is the
  // defect that produced it. Painting only two soil rows while leaving the
  // plane deep put the painted band BELOW `groundFront`, so every object stood
  // on a line that was no longer drawn: the fixtures did not float above the
  // band, the band sat under their feet with unpainted air between. Deleting
  // paint could never have corrected that, because the geometry is what
  // decides where feet land.
  //
  // The later visual review restored a real near/far plane. The two boundary
  // rows are now explicit owners: the sky transition is `farGroundY`; the
  // closest walkable contour is `groundFront`. World depth may project between
  // them, but may never derive a third boundary.
  const farGroundY = clamp(Math.round(height * 0.64), 5, horizon - 6);
  const groundRows = Math.max(1, horizon - farGroundY + 1);
  // Two rows answer two different questions and must not be collapsed again:
  // `farGroundY` is the continuous grass edge behind the playable scene;
  // `groundFront` is the canonical surface where fixture feet land.  The
  // failed 2026-08-04 pass moved `groundFront` to the reference contour and
  // consequently made background trunks, fixtures and foreground cover all
  // compete for one row.  The reference instead has an elevated far edge with
  // a foreground plane continuing down toward the viewer.
  const groundFront = horizon;
  const groundBack = farGroundY;
  const groundSpan = groundFront - groundBack;

  return {
    width, height, horizon, bandTop, bandRows, lod,
    groundRows, farGroundY, groundBack, groundFront, groundSpan,
    // A phone is a camera into the same Garden, not a request to crush the
    // entire 120-cell world into forty columns. Cropping preserves silhouettes
    // and spatial relationships; canonical pan/focus reveals the rest.
    xScale: clamp((width - 10) / (worldWidth * DEPTH.foreground), 0.80, 1.35),
    // The authored plane is visible again, so canonical world depth maps into
    // the bounded interval between its far and near contours.
    yScale: groundSpan === 0 ? 0 : clamp(groundSpan / worldHeight, 0.01, 0.44),
    centerX: Math.floor(width / 2),
    // The camera's authored y sits slightly behind the middle of the terrain,
    // leaving room for a foreground pond while still letting a low world-y
    // lantern reach the far band.
    centerY: groundBack + Math.round(groundSpan * 0.45),
  };
}

// The authored starter camera is the neutral view of the 120 x 80 world.
// Terrain is part of that world-facing composition, not a CSS stripe glued to
// the viewport.  Keeping the neutral camera beside the projection law makes
// the vertical pan transform explicit and prevents a second screen-space
// owner from appearing in the viewer or painter.
const GARDEN_HOME_CAMERA_Y = 40;
const FAR_TERRAIN_DEPTH = 0.52;
const NEAR_TERRAIN_DEPTH = 1.0;

/**
 * Camera-projected terrain contours for one composed frame.
 *
 * `gardenPresentationProfile` owns the neutral shape of the viewport.  This
 * function applies the same vertical camera delta used by world projection at
 * the depth of each contour.  Every consumer of the visible terrain band --
 * ink, CSS colour transition, culling, planting and weather -- receives this
 * value.  No consumer is allowed to re-derive a fixed viewport row.
 */
export function gardenTerrainFrame(projection, viewport, profile = null) {
  const resolved = profile ?? gardenPresentationProfile(viewport);
  const cameraY = Number(projection?.camera?.[1]);
  const delta = Number.isFinite(cameraY)
    ? GARDEN_HOME_CAMERA_Y - cameraY : 0;
  let groundBack = resolved.groundBack + roundHalfAway(
    delta * resolved.yScale * FAR_TERRAIN_DEPTH,
  );
  let groundFront = resolved.groundFront + roundHalfAway(
    delta * resolved.yScale * NEAR_TERRAIN_DEPTH,
  );
  groundBack = clamp(groundBack, 4, resolved.height - 4);
  groundFront = clamp(groundFront, groundBack + 2, resolved.height - 2);
  return Object.freeze({
    farGroundY: groundBack,
    groundBack,
    groundFront,
    groundSpan: groundFront - groundBack,
  });
}

/**
 * Compatibility query for consumers that need the near soil row.
 * A projection makes it frame-accurate; omitting one asks for the authored
 * neutral view and does not create a second paint owner.
 */
export function gardenGroundY(viewport, projection = { camera: [60, GARDEN_HOME_CAMERA_Y] }) {
  const profile = gardenPresentationProfile(viewport);
  return gardenTerrainFrame(projection, viewport, profile).groundFront;
}

/**
 * Project a canonical world point onto the character grid.
 *
 * point      canonical [x, y]; y is depth into the scene, not altitude
 * camera     canonical camera centre, same units
 * viewport   [columns, rows] of character cells currently available
 * depth      parallax multiplier for the layer being drawn (see DEPTH)
 * worldSize  canonical world extent, used to scale depth onto the plane
 *
 * Returns [column, row] where `row` is the SOIL LINE the point stands on. Art
 * is drawn upward from this row (see presentationRect, whose `bottom` is the
 * anchor), so a returned row is literally where a thing's feet go.
 *
 * The row is deliberately NOT clamped to the plane. A point whose row falls
 * outside [groundBack, groundFront] is behind or in front of the visible
 * Garden, and the caller culls it — clamping here would drag distant objects
 * into view and destroy vertical culling.
 */
export function worldToGardenScreen(
  point, camera, viewport, depth = DEPTH.world, worldSize = [120, 80],
) {
  const profile = gardenPresentationProfile(viewport, worldSize);
  return [
    profile.centerX + roundHalfAway((point[0] - camera[0]) * profile.xScale * depth),
    profile.centerY + roundHalfAway((point[1] - camera[1]) * profile.yScale * depth),
  ];
}

function artDimensions(lines) {
  return {
    width: Math.max(1, ...lines.map(line => [...String(line)].length)),
    height: Math.max(1, lines.length),
  };
}

function presentationRect(anchor, lines) {
  const size = artDimensions(lines);
  const left = anchor[0] - Math.floor(size.width / 2);
  return {
    left, right: left + size.width - 1,
    top: anchor[1] - size.height + 1, bottom: anchor[1],
  };
}

function translatedRect(rect, dx, dy) {
  return {
    left: rect.left + dx, right: rect.right + dx,
    top: rect.top + dy, bottom: rect.bottom + dy,
  };
}

function orderedIntegerRange(minimum, maximum) {
  const values = [];
  for (let value = Math.ceil(minimum); value <= Math.floor(maximum); value += 1)
    values.push(value);
  return values.sort((left, right) =>
    Math.abs(left) - Math.abs(right) || left - right);
}

function projectedHotspotRect(object, projection, viewport, depth) {
  const hotspot = object?.hotspot;
  const values = [hotspot?.x, hotspot?.y, hotspot?.width, hotspot?.height].map(Number);
  if (values.some(value => !Number.isFinite(value)) || values[2] <= 0 || values[3] <= 0) {
    throw new Error(`object ${object?.object_id ?? 'unknown'} lacks a projection-owned hotspot`);
  }
  const [x, y, width, height] = values;
  const first = worldToGardenScreen([x, y], projection.camera, viewport, depth);
  const last = worldToGardenScreen(
    [x + Math.max(0, width - 1), y + Math.max(0, height - 1)],
    projection.camera, viewport, depth,
  );
  return {
    left: Math.min(first[0], last[0]), right: Math.max(first[0], last[0]),
    top: Math.min(first[1], last[1]), bottom: Math.max(first[1], last[1]),
  };
}

function intersectionArea(left, right, margin = 0) {
  const width = Math.min(left.right + margin, right.right + margin) -
    Math.max(left.left - margin, right.left - margin) + 1;
  const height = Math.min(left.bottom + margin, right.bottom + margin) -
    Math.max(left.top - margin, right.top - margin) + 1;
  return Math.max(0, width) * Math.max(0, height);
}

function expandedRect(rect, minimumCells = [1, 1]) {
  const width = rect.right - rect.left + 1, height = rect.bottom - rect.top + 1;
  const missingWidth = Math.max(0, Number(minimumCells[0] ?? 1) - width);
  const missingHeight = Math.max(0, Number(minimumCells[1] ?? 1) - height);
  return {
    left: rect.left - Math.floor(missingWidth / 2),
    right: rect.right + Math.ceil(missingWidth / 2),
    top: rect.top - Math.floor(missingHeight / 2),
    bottom: rect.bottom + Math.ceil(missingHeight / 2),
  };
}

function rectContains(rect, point) {
  return point[0] >= rect.left && point[0] <= rect.right &&
    point[1] >= rect.top && point[1] <= rect.bottom;
}

/**
 * Convert a renderer hit rectangle into a canonical hotspot rectangle.
 *
 * Two rectangle conventions meet here and the conversion is deliberately
 * explicit rather than folded into a pixel helper.
 *
 * A layout `hitRect` is INCLUSIVE on all four edges, because it counts cells: a
 * one-cell object has `left === right`, and both edges name real cells that
 * belong to the object. A canonical hotspot is an ORIGIN AND AN EXTENT, which
 * is what `garden-geometry.mjs` converts to pixels. Hence the `+ 1`: an
 * inclusive span from column 4 to column 4 is one column wide, not zero.
 *
 * Getting this wrong is silent -- every object simply becomes one cell smaller
 * than it looks -- so it lives in one named function with one comment rather
 * than being re-derived at each call site.
 *
 * @param {{left: number, top: number, right: number, bottom: number}} rect -
 *   Inclusive rectangle in world cells.
 * @returns {{x: number, y: number, width: number, height: number}} A hotspot in
 *   world cells, ready for `geometry.hotspotToRect`.
 */
export function hitRectToHotspot(rect) {
  return {
    x: rect.left,
    y: rect.top,
    width: rect.right - rect.left + 1,
    height: rect.bottom - rect.top + 1,
  };
}

export function connectedMasks(objects) {
  const result = new Map();
  for (const object of objects) {
    if (object.kind !== 'fixture') continue;
    const state = object.semantic_state ?? {};
    if (!Object.hasOwn(state, 'connected_group')) {
      throw new Error(`fixture ${object.object_id} lacks a projection-owned connected group`);
    }
    const group = state.connected_group;
    const mask = state.connected_mask;
    if (!Number.isInteger(mask) || mask < 0 || mask > 15) {
      throw new Error(`fixture ${object.object_id} lacks a projection-owned connected mask`);
    }
    const renderCells = state.render_cells;
    if (!Array.isArray(renderCells) || renderCells.some(cell =>
      !Number.isInteger(cell?.connected_mask) || cell.connected_mask < 0 || cell.connected_mask > 15)) {
      throw new Error(`fixture ${object.object_id} lacks projection-owned connected cells`);
    }
    if (group === null) {
      if (mask !== 0) throw new Error(`fixture ${object.object_id} has a mask without a connected group`);
      continue;
    }
    if (typeof group !== 'string' || group.length === 0) {
      throw new Error(`fixture ${object.object_id} has an invalid connected group`);
    }
    result.set(object.object_id, mask);
  }
  return result;
}

export class Raster {
  /**
   * @param width     cells across
   * @param height    cells down
   * @param authority optional Set of accepted source ids. When present, a
   *   write whose source the set does not contain is recorded as an
   *   attempted-but-SUPPRESSED primitive and paints nothing: unreviewed ink
   *   composes on no host. When null, everything paints WITH its identity --
   *   the diagnostic mode Node adapters and authoring tools use.
   */
  constructor(width, height, { authority = null } = {}) {
    this.authority = authority;
    this.width = width; this.height = height;
    this.glyphs = Array.from({ length: height }, () => Array(width).fill(' '));
    this.colors = Array.from({ length: height }, () => Array(width).fill(null));
    this.animated = Array.from({ length: height }, () => Array(width).fill(false));
    // Atlas assets are painted twice for two different consumers. `glyphs`
    // remains the semantic/test raster; `measuredAssets` is the browser paint
    // plan whose horizontal positions come from PreText prefix widths. `owners`
    // prevents the lattice layer from painting the same atlas glyph a second
    // time. A later non-asset write clears the owner, preserving painter order.
    this.owners = Array.from({ length: height }, () => Array(width).fill(null));
    this.measuredAssets = [];
    // IDENTITY. `sources` keeps, per cell, the register id of whatever drew
    // the cell's CURRENT glyph -- the runtime form of SPEC 7.2.1's
    // visual_source_id. An anonymous write stores null rather than
    // inheriting the previous claim, so anonymous paint stays visible to the
    // gate instead of riding an earlier drawing's identity.
    this.sources = Array.from({ length: height }, () => Array(width).fill(null));
    // ATTEMPTS. Every write is also recorded in painter order, whether or
    // not a later write covers it -- SPEC 7.2.2's attempted_primitives.
    // `cellAttempt` maps each cell to the index of the attempt currently
    // visible there, which is how the composer later derives
    // visible_primitives without a second occlusion policy.
    this.attempted = [];
    this.cellAttempt = Array.from({ length: height }, () => Array(width).fill(null));
  }
  put(x, y, glyph, color = null, animated = false, owner = null, options = null) {
    if (x < 0 || x >= this.width || y < 0 || y >= this.height || !glyph) return;
    const source = options?.source ?? null;
    const objectId = options?.objectId ?? null;
    // Suppression is a property of the write, decided by the authority this
    // raster was constructed with. A blank glyph is never suppressed: it is
    // not ink, and suppressing it would let an unaccepted drawing ERASE
    // accepted ink underneath it, which is a paint decision by other means.
    const glyphValue = [...String(glyph)][0];
    const isInk = glyphValue !== ' ' && glyphValue !== '';
    const suppressed = Boolean(
      this.authority && isInk && (source === null || !this.authority.has(source)),
    );
    this.attempted.push({
      x, y, glyph: glyphValue, color, animated,
      source_id: source, object_id: objectId,
      painter_order: this.attempted.length + 1,
      suppressed,
    });
    if (suppressed) return;
    this.glyphs[y][x] = glyphValue; this.colors[y][x] = color;
    this.animated[y][x] = animated; this.owners[y][x] = owner;
    this.sources[y][x] = source;
    this.cellAttempt[y][x] = this.attempted.length - 1;
  }
  text(x, y, value, color = null, animated = false, owner = null, options = null) {
    [...String(value)].forEach((glyph, index) =>
      this.put(x + index, y, glyph, color, animated, owner, options));
  }
  /**
   * Draw a picture, optionally recolouring named parts of it.
   *
   * @param accents Optional `{ "row,column": color }` supplied by the atlas
   *   asset. It exists so a fixture can have a part in a different colour --
   *   the mailbox flag is red while its body and post stay neutral -- without
   *   the renderer inspecting glyphs or catalog ids to guess which cell is
   *   which. The atlas authored the drawing, so the atlas says which cells are
   *   the flag; this method only obeys. Coordinates are into the ART, not the
   *   screen, so they survive the drawing moving.
   */
  art(anchorX, anchorY, lines, color, {
    baseline = true, animated = false, accents = null, owner = null,
    source = null, objectId = null,
  } = {}) {
    const identity = { source, objectId };
    const width = Math.max(0, ...lines.map(line => [...line].length));
    const top = baseline ? anchorY - lines.length + 1 : anchorY;
    const left = anchorX - Math.floor(width / 2);
    lines.forEach((line, row) => {
      // A billboard's rectangle owns spacing and hit geometry; its EMPTY
      // cells are transparent.  The measured Contract-P path has always
      // omitted spaces from its final glyph list.  Writing blanks only on the
      // lattice path made the same card opaque in one renderer and transparent
      // in the other, and let a later pond erase a nearer plant through empty
      // water.  Per-cell emission keeps the two paths identical.
      [...line].forEach((glyph, column) => {
        if (glyph === ' ' || glyph === '') return;
        this.put(left + column, top + row,
          glyph, accents?.[`${row},${column}`] ?? color, animated, owner, identity);
      });
    });
  }

  /**
   * Record one atlas-owned picture for Contract-P painting.
   *
   * The semantic raster still receives the glyphs so terminal-style tests and
   * accessible summaries keep seeing the same frame. The browser layer does not
   * consume those cell positions: it measures each row string independently and
   * places it relative to the asset's own measured anchor.
   */
  measuredArt(objectId, anchorX, anchorY, lines, artAnchor, color, options = {}) {
    const owner = `asset:${objectId}`;
    const anchor = Array.isArray(artAnchor) && artAnchor.length === 2
      ? [Number(artAnchor[0]), Number(artAnchor[1])]
      : [Math.floor(Math.max(0, ...lines.map(line => [...line].length)) / 2), lines.length - 1];
    const top = anchorY - anchor[1], left = anchorX - anchor[0];
    const source = options.source ?? null;
    // The measured paint plan obeys the SAME authority as the lattice cells.
    // Before this gate, suppression applied per cell below while the plan was
    // recorded unconditionally -- so an unaccepted or anonymous atlas asset
    // had its lattice glyphs suppressed and then painted anyway on the
    // measured pixel overlay. The per-cell attempts still record the
    // suppression verdicts; what an unaccepted asset no longer gets is a
    // place in the plan the overlay is painted from.
    if (!this.authority || (source !== null && this.authority.has(source))) {
      this.measuredAssets.push({
        objectId: String(objectId), anchor: [anchorX, anchorY], artAnchor: anchor,
        lines: [...lines], color, accents: options.accents ?? null,
        source, owner,
      });
    }
    lines.forEach((line, row) => [...line].forEach((glyph, column) => {
      if (glyph === ' ' || glyph === '') return;
      this.put(left + column, top + row, glyph,
        options.accents?.[`${row},${column}`] ?? color,
        Boolean(options.animated), owner,
        { source: options.source ?? null, objectId: String(objectId) });
    }));
  }
  line(row) { return this.glyphs[row].join(''); }

  /** Paint lattice decoration; measured atlas cells are omitted when supported. */
  latticeHtml(row, pitch, skipMeasuredOwners = true) {
    let output = '';
    for (let column = 0; column < this.width; column += 1) {
      const glyph = this.glyphs[row][column];
      if (glyph === ' ' || glyph === '' ||
        (skipMeasuredOwners && this.owners[row][column] !== null)) continue;
      const color = this.colors[row][column];
      const left = column * pitch;
      output += `<span style="left:${left.toFixed(2)}px` +
        (color ? `;color:${color}` : '') + `">${escapeHtml(glyph)}</span>`;
    }
    return output;
  }

  html(row) {
    let output = '', color = null, run = '';
    const flush = () => {
      if (!run) return;
      output += color ? `<span style="color:${color}">${escapeHtml(run)}</span>` : escapeHtml(run);
      run = '';
    };
    for (let column = 0; column < this.width; column += 1) {
      const next = this.colors[row][column];
      if (next !== color) { flush(); color = next; }
      run += this.glyphs[row][column];
    }
    flush(); return output;
  }
}

/**
 * Turn one atlas row-string picture into an asset-local Contract-P paint plan.
 *
 * World placement remains affine: only `asset.anchor` reaches `worldToPixel`.
 * Everything inside the picture is measured from its own row prefixes, so a
 * glyph in this asset cannot shift another asset and no fixed column pitch is
 * reintroduced through the renderer.
 */
export function measuredAssetPlacement(geometry, asset) {
  if (!geometry || geometry.affineOnly) {
    throw new Error('renderer: measured atlas art requires a measurement-capable geometry');
  }
  const lines = Array.isArray(asset?.lines) ? asset.lines.map(String) : null;
  const artAnchor = Array.isArray(asset?.artAnchor) ? asset.artAnchor.map(Number) : null;
  const worldAnchor = Array.isArray(asset?.anchor) ? asset.anchor.map(Number) : null;
  if (!lines || !artAnchor || artAnchor.length !== 2 || !worldAnchor || worldAnchor.length !== 2) {
    throw new Error('renderer: measured atlas art needs lines, artAnchor and anchor');
  }
  const [anchorColumn, anchorRow] = artAnchor;
  if (!Number.isInteger(anchorColumn) || !Number.isInteger(anchorRow) ||
    anchorRow < 0 || anchorRow >= lines.length) {
    throw new Error('renderer: atlas drawing anchor lies outside its rows');
  }

  const measured = geometry.measureAsset(lines);
  const anchorMeasuredRow = measured.rows[anchorRow];
  if (anchorColumn < 0 || anchorColumn >= anchorMeasuredRow.graphemes.length) {
    throw new Error('renderer: atlas drawing anchor column lies outside its anchor row');
  }
  const screenAnchor = geometry.worldToPixel(worldAnchor[0], worldAnchor[1]);
  const left = screenAnchor.x - geometry.offsetOfGrapheme(anchorMeasuredRow, anchorColumn);
  const top = screenAnchor.y - anchorRow * geometry.lineHeight;
  const glyphs = [];

  measured.rows.forEach((row, rowIndex) => {
    row.graphemes.forEach((glyph, column) => {
      if (glyph === ' ' || glyph === '') return;
      glyphs.push({
        glyph, row: rowIndex, column,
        x: left + geometry.offsetOfGrapheme(row, column),
        y: top + rowIndex * geometry.lineHeight,
        color: asset.accents?.[`${rowIndex},${column}`] ?? asset.color ?? null,
      });
    });
  });

  return {
    objectId: String(asset.objectId), left, top,
    width: measured.width, height: measured.height, glyphs,
  };
}

export function presentationTime(projection) {
  const observed = Number(projection.observed_time);
  return Number.isFinite(observed) && observed >= 0
    ? observed : Math.max(0, Number(projection.effective_time) || 0);
}

export function timeOfDay(projection) {
  const authored = String(projection.scene?.story_time ?? projection.scene?.palette ?? '').toLowerCase();
  if (authored.includes('night')) return 'night';
  if (authored.includes('evening') || authored.includes('sunset') || authored.includes('dusk')) return 'evening';
  if (authored.includes('day') || authored.includes('morning')) return 'day';
  const hour = new Date(presentationTime(projection) * 1000).getUTCHours();
  return hour >= 21 || hour < 5 ? 'night' : hour >= 18 ? 'evening' : 'day';
}
export function seasonOf(projection) {
  const authored = String(projection.scene?.season ?? projection.scene?.palette ?? '').toLowerCase();
  for (const season of ['spring', 'summer', 'autumn', 'winter']) if (authored.includes(season)) return season;
  const month = new Date(presentationTime(projection) * 1000).getUTCMonth() + 1;
  // The deployed boundaries (frozen blob 59dc49a8, lines 1634-1637):
  // 3-5 spring, 6-8 summer, 9-11 autumn, everything else winter. The earlier
  // chain here tested `month <= 8` with no lower bound, so January and
  // February fell into SUMMER and winter never existed on the clock path --
  // the mis-transcription behind "winter-day paints the same bytes".
  if (month >= 3 && month <= 5) return 'spring';
  if (month >= 6 && month <= 8) return 'summer';
  if (month >= 9 && month <= 11) return 'autumn';
  return 'winter';
}
function lunarPhase(effectiveTime) {
  const days = ((Number(effectiveTime) * 1000 - Date.UTC(2000, 0, 6, 18, 14)) / 86400000);
  return Math.floor((((days % 29.53) + 29.53) % 29.53) / 29.53 * 8);
}

function starterPlantArt(object, frame, hovered, lod) {
  const species = String(object.semantic_state?.species_id ?? object.semantic_name ?? '');
  const entry = STARTER_PLANT_ART[species];
  if (!entry) return null;
  const source = lod === 'full' ? entry.full : entry.compact;
  const seed = stringHash(object.object_id);
  const cadence = hovered ? 2 : 8;
  const phase = Math.floor((Math.max(0, frame) + seed % 31) / cadence);
  const families = {
    '.': ['.', "'", '`', '.'],
    ':': [':', ';', ':', '·'],
    ';': [';', ':', ';', "'"],
    '~': ['~', '-', '~', '`'],
    '/': ['/', '|', '\\', '|'],
    '\\': ['\\', '|', '/', '|'],
  };
  const lines = source.map((line, row) => [...line].map((glyph, column) => {
    const family = families[glyph];
    if (!family) return glyph;
    const local = stringHash(`${seed}:${row}:${column}`);
    // The outline remains stable; only a sparse interior subset breathes.
    if (local % (hovered ? 3 : 9) !== 0) return glyph;
    return family[(phase + local) % family.length];
  }).join(''));
  const color = species === 'meadow_grass' ? 'brightGreen' :
    ['hydrangea', 'lavender', 'sunflower'].includes(species) ? 'flower' : 'green';
  return { lines, color, purposeDrawn: true };
}

function basePlantArt(object, frame) {
  const state = object.semantic_state ?? {};
  const species = String(state.species_id ?? object.semantic_name ?? 'plant');
  const visible = Math.max(1, Number(state.visible_organ_count ?? state.visible_organs?.length ?? 1));
  const stage = clamp(Math.floor(Math.log2(visible + 1)), 1, 4);
  const phase = (Math.max(0, frame) + stringHash(object.object_id) % 37) % 32;
  const sway = phase < 16 ? '/' : '\\', other = sway === '/' ? '\\' : '/';
  // ── Trees ───────────────────────────────────────────────────────────────
  // A tree is the one thing in this Garden that is supposed to occupy the air.
  // Drawn four or six lines tall it sits in the planting like a shrub, the
  // headroom above the ground plane goes unused, and the frame reads as a thin
  // band of objects under an empty sky. Height here is what gives the
  // composition a vertical middle, so canopy and trunk are both generous and
  // grow materially between an establishing tree and a mature one.
  if (species === 'oak') {
    const lines = stage >= 4
      ? ['    * *  *    ', '  *o*Y*o*Yo*  ', ' ***oYoo*Yo** ', '**oYo*oY*oYo**',
        ' ***oYoo*Yo** ', `   **${sway}/|${other}o**   `, '      |       ', '      |       ',
        '      |       ', '     _|_      ', '    __|__     ']
      : stage >= 3
        ? ['    * *    ', '  *o*Y*o*  ', ' ***oYoo** ', '**oYo*oY*o*', ' ***oYoo** ',
          `   ${sway}/|${other}   `, '     |     ', '     |     ', '    _|_    ']
        : ['   *   ', ' *oYo* ', `  ${sway}|${other}  `, '   |   ', '  _|_  '];
    return { lines, color: 'green' };
  }
  if (species === 'willow') {
    const lines = stage >= 4
      ? [' v vYv vYv v ', 'vVvYvVvVvYvVv', `${sway}vVv Y vVv${other}`, ' v v   v v v ',
        '  v  /|\\  v  ', '     /|\\     ', '      |      ', '      |      ',
        '      |      ', '     _|_     ', '    __|__    ']
      : stage >= 3
        ? [' v vYv v ', 'vVvYvVvVv', `${sway}v Y v${other}`, ' v  v  v ', '   /|\\   ',
          '    |    ', '    |    ', '   _|_   ']
        : ['  vYv  ', `${sway} | ${other}`, '   |   ', '   |   ', '  _|_  '];
    return { lines, color: 'green' };
  }
  if (species === 'pine') {
    const lines = stage >= 4
      ? ['      ^      ', '     /|\\     ', '    //|\\\\    ', '   ///|\\\\\\   ',
        '  ////|\\\\\\\\  ', ' /////|\\\\\\\\\\ ', '//////|\\\\\\\\\\\\', '      |      ',
        '      |      ', '     _|_     ']
      : stage >= 3
        ? ['    ^    ', '   /|\\   ', '  //|\\\\  ', ' ///|\\\\\\ ', '////|\\\\\\\\',
          '    |    ', '    |    ', '   _|_   ']
        : ['   ^   ', '  /|\\  ', ' //|\\\\ ', '   |   ', '  _|_  '];
    return { lines, color: 'deepGreen' };
  }
  // ── Everything that is not a tree ───────────────────────────────────────
  // These were three or four lines each, which is the width of the stem and
  // little else. A bed of them reads as scattered punctuation rather than as
  // planting, and it leaves the ground plane looking bare between the trees.
  // Each species now carries foliage, a stem of real length and a base, so a
  // Garden with no tree in it still reads as planted.
  if (species === 'hydrangea') {
    return { lines: stage >= 3
      ? ['  @@@@@  ', ' @o@@@o@ ', '@@o@@@o@@', ` ${sway}@|Y|@${other} `,
        '   /|\\   ', '    |    ', '   _|_   ']
      : ['  @o@  ', ` ${sway}|Y|${other} `, '   |   ', '  _|_  '], color: 'flower' };
  }
  if (species === 'wisteria') {
    return { lines: stage >= 3
      ? [' @ @ @ @ ', `@${sway}@ @${other}@`, ' @ @ @ @ ', '  @ | @  ',
        '   |Y|   ', '    |    ', '   _|_   ']
      : [' @ @ ', `@${sway} ${other}@`, ' |Y| ', '  |  ', ' _|_ '], color: 'flower' };
  }
  if (species === 'tulip') return { lines: stage >= 3
    ? [' u u u ', ` ${sway}|||${other} `, '  |||  ', ' /|||\\ ', '  |||  ', ' __|__ ']
    : ['  u  ', ` ${sway}|${other} `, '  |  ', ' /|\\ ', ' _|_ '], color: 'flower' };
  if (species === 'sunflower') return { lines: stage >= 3
    ? ['  O O O  ', ' \\Y/\\Y/ ', `  ${sway}|||${other}  `, '   |||   ',
      '  /|||\\  ', '   |||   ', '  _|_|_  ']
    : ['   O   ', '  \\Y/  ', `  ${sway}|${other}  `, '   |   ', '  _|_  '], color: 'flower' };
  if (species === 'lavender') return { lines: stage >= 3
    ? [' : : : ', ` ;${sway}|${other}; `, ' ;|||; ', ' ;|||; ', '  |||  ', ' __|__ ']
    : ['  : :  ', ' ;|||; ', '  |||  ', ' __|__ '], color: 'flower' };
  if (species === 'water_lily') return { lines: stage >= 3
    ? ['   *   *   ', ' ~~Y~~~Y~~ ', '~~~~~~~~~~~', ' ~~~~~~~~~ ']
    : ['  *  *  ', ' ~~Y~~~~ ', ' ~~~~~~ '], color: 'flower' };
  if (species === 'meadow_grass') {
    return { lines: stage >= 3
      ? [`${sway}|${other}'${sway}|${other}'${sway}`, `|${sway}|||${other}|`, '|||||||', '|||||||']
      : [`${sway}|${other}' ${sway}`, '|||||', '|||||'], color: 'brightGreen' };
  }
  if (species === 'ivy') return { lines: stage >= 3
    ? [' * Y * Y ', `${sway}Y * Y *${other}`, ' Y * Y * ', '  Y | Y  ', '    |    ', '   _|_   ']
    : [' * * ', `${sway}Y Y${other}`, '  Y  ', '  |  ', ' _|_ '], color: 'green' };
  if (species === 'rosemary') return { lines: stage >= 3
    ? [`;${sway};${other};${sway};`, ' ;;|;; ', ' ;;|;; ', '  ;|;  ', '   |   ', '  _|_  ']
    : [`;${sway};${other};`, ' ;|; ', '  |  ', ' _|_ '], color: 'green' };
  return { lines: [' ;;; ', `${sway};|;${other}`, '  |  '], color: 'green' };
}

const FOLIAGE_CYCLES = Object.freeze({
  '*': ['*', '·', '*', 'o'], o: ['o', '0', 'o', '@'], '@': ['@', 'o', '@', '0'],
  v: ['v', 'V', 'v', 'y'], V: ['V', 'v', 'Y', 'v'], Y: ['Y', 'y', 'Y', 'v'],
  ':': [':', ';', ':', '·'], ';': [';', ':', ';', "'"], u: ['u', 'v', 'u', 'U'],
  O: ['O', '0', 'O', 'o'], '^': ['^', '*', '^', "'"],
});

/**
 * Maturity tier a plant is currently showing.
 *
 * `visible_organ_count` is world state -- how much of this plant's authored
 * organ graph has actually grown -- so the tier changes only when the plant
 * grows, never between presentation frames. Taking log2 compresses a count that
 * can run to dozens into the handful of sizes anything is drawn at.
 */
function plantStage(object) {
  const state = object.semantic_state ?? {};
  const visible = Math.max(1, Number(state.visible_organ_count ?? state.visible_organs?.length ?? 1));
  return clamp(Math.floor(Math.log2(visible + 1)), 1, 4);
}

/**
 * Draw a plant from the legacy archive, if the archive draws this species.
 *
 * object   canonical plant object
 * frame    presentation frame counter
 * hovered  whether this plant is the focused object
 * lod      current level of detail
 *
 * Returns the same `{lines, color}` shape the other plant painters return, or
 * null when the archive has no drawing for this species -- in which case the
 * caller keeps its existing, still-unapproved placeholder.
 *
 * WHY THE STAGE IS CAPPED BY LOD
 * ------------------------------
 * The archive draws each species small, medium and large, and maturity picks
 * between them. A narrow viewport also needs a smaller picture, and it has two
 * ways to get one: ask the archive for its smaller drawing, or take the large
 * drawing and delete rows from the middle of it. The archive's own small
 * drawing is a picture somebody composed at that size; a trimmed large drawing
 * is a picture with its middle missing, and for a tree that middle is the
 * trunk. So the lod lowers the stage first and `presentationLod` only ever runs
 * as a backstop on what is already the right size.
 */
function legacyPlantArt(object, frame, hovered, lod) {
  const species = String(object.semantic_state?.species_id ?? object.semantic_name ?? '');
  // 'compact' is a phone-width Garden; 'medium' a small window. Both ask the
  // archive for a smaller drawing rather than for a reduced large one.
  // The archive's larger frames are hero/detail drawings.  In the shared
  // world view even the medium oak still outweighed the full deployed planting
  // band.  Use the archive's own approved small world sprite at every viewport;
  // growth/detail views may select larger approved frames elsewhere.
  const ceiling = 1;
  const presentation = legacyPlantPresentation(
    species, Math.min(plantStage(object), ceiling), frame,
    // Offsetting the loop by a hash of this object's own id is what keeps two
    // plants of one species from swaying in unison. See the module header.
    stringHash(object.object_id) % 29, hovered,
  );
  if (!presentation) return null;
  // Colour is a palette role, not part of the drawing, so it stays a renderer
  // decision. Trees read as foliage, the two flowering species as blooms.
  const color = species === 'pine' ? 'deepGreen'
    : species === 'sunflower' || species === 'water_lily' ? 'flower' : 'green';
  return { lines: [...presentation.lines], color,
    legacySource: presentation.source, identity: presentation.identity };
}

function plantArt(object, frame, hovered = false, lod = 'full') {
  const species = String(object.semantic_state?.species_id ?? 'plant');
  // Exact approved starter flowers outrank both the legacy stage painter and
  // every renderer fallback. Their species identity is seed-selected by the
  // canonical world; this lookup may present that identity but cannot choose
  // a different flower on its own.
  const approvedArt = approvedStarterFlowerPresentation(species);
  if (approvedArt) return { ...approvedArt, color: 'flower' };
  // The archive first: where it draws a species, its drawing is the approved
  // one and everything below is a placeholder awaiting review.
  const legacy = legacyPlantArt(object, frame, hovered, lod);
  if (legacy) return legacy;
  const starter = starterPlantArt(object, frame, hovered, lod);
  if (starter) return starter;
  const art = basePlantArt(object, frame);
  const seed = stringHash(object.object_id);
  const cadence = hovered ? 2 : 9;
  const lines = art.lines.map((line, row) => [...line].map((glyph, column) => {
    if (species === 'meadow_grass' && ['/', '|', '\\', "'"].includes(glyph)) {
      const family = ['\\', '|', '/', '|'];
      return family[Math.floor((Math.max(0, frame) + seed % 23 + row * 5 + column * 3) / cadence) % family.length];
    }
    const family = FOLIAGE_CYCLES[glyph];
    if (!family) return glyph;
    const local = stringHash(`${seed}:${row}:${column}`);
    if (!hovered && local % 5 !== 0) return glyph;
    return family[Math.floor((Math.max(0, frame) + local % 31) / cadence) % family.length];
  }).join(''));
  return { ...art, lines };
}

export function animalPoseFamily(intentValue, choreographyLocked = false) {
  if (choreographyLocked) return 'perform';
  const intent = String(intentValue ?? '').toLowerCase();
  if (/retreat|withdraw|startle|hide/.test(intent)) return 'retreat';
  if (/approach|follow|greet|return/.test(intent)) return 'approach';
  if (/groom|ruffle|knead/.test(intent)) return 'groom';
  if (/forage|sniff|track|walk|explore|patrol/.test(intent)) return 'forage';
  if (/play|hop|song|sing|bathe|paddle|flop/.test(intent)) return 'play';
  if (/rest|nap|perch|settled|sunbathe/.test(intent)) return 'rest';
  return 'greet';
}

/**
 * Every frame one animal can show in its current routine, and which one is up.
 *
 * object  canonical animal object
 * frame   presentation frame counter
 * lod     current level of detail
 *
 * Returns `{lines, poses}` -- the frame to draw now, and the complete set of
 * frames this routine can ever draw. Placement needs the whole set (see
 * `stableArtFootprint`) and drawing needs one of them; deriving both here keeps
 * them from disagreeing, which is how an animal ends up drawn outside the
 * rectangle that was reserved for it.
 *
 * The archive is consulted first. It draws cats and birds; for the rabbit and
 * the turtle it returns nothing and the renderer's own unapproved pose tables
 * are used, which is why neither species is in the default scene. It also
 * returns nothing for a routine it never depicted even in a species it does
 * draw -- a foraging cat is archived, a performing one is not -- and that too
 * falls through rather than being faked.
 */
function resolveAnimalPose(object, frame, lod) {
  const state = object.semantic_state ?? {};
  const species = String(state.species_id ?? 'bird');
  const family = animalPoseFamily(
    state.intent ?? state.current_intent, state.choreography_locked,
  );
  const seed = stringHash(object.object_id) % 29;
  const legacy = legacyAnimalPresentation(species, family, frame, seed);
  if (legacy) {
    // Every archived frame of this routine shares one bounding box, because
    // `normalizeFrames` padded them at load. The whole set is still returned so
    // the footprint calculation does not have to know that.
    const poses = [];
    for (let index = 0; index < legacy.loopLength; index += 1) {
      poses.push(legacyAnimalPresentation(species, family, index * 64, 0).lines);
    }
    return { lines: [...legacy.lines], poses, identity: legacy.identity };
  }
  const poses = species === 'cat' && lod === 'full'
    ? STARTER_CAT_FULL_POSES[family]
    : ANIMAL_POSES[species]?.[family] ?? ANIMAL_POSES.bird.greet;
  const phase = Math.floor((Math.max(0, frame) + seed) / 10) % poses.length;
  return { lines: [...poses[phase]], poses };
}

function animalArt(object, frame, lod = 'full') {
  const state = object.semantic_state ?? {};
  const intent = String(state.intent ?? state.current_intent ?? 'greet').toLowerCase();
  // The authored pose is already a complete silhouette. Appending the same
  // `######` body block underneath every pose made all four species read as
  // inventory icons and doubled their visual weight in the Garden.
  const pose = resolveAnimalPose(object, frame, lod);
  let lines = pose.lines;
  if (/feed/.test(intent)) lines = lines.map((line, index) => index === lines.length - 1 ? `${line} [_]` : line);
  if (state.choreography_locked && frame % 12 < 6) lines = lines.map(line => line.replace('o', 'O'));
  const tier = clamp(Number(state.bond_tier) || 0, 0, 3);
  const bondMark = ['', ' ·', ' *', ' ♥'][tier];
  if (bondMark) lines = lines.map((line, index) => index === 0 ? `${line}${bondMark}` : line);
  return { lines, identity: pose.identity ?? null };
}

/**
 * Pick a collectible's picture for the current density.
 *
 * Identity is resolved from the catalogue id first, then the object's label,
 * then its family, so a collectible this renderer does not recognise still gets
 * a drawn picture rather than a placeholder mark.
 *
 * lod  'full' returns the full picture; every other density returns the
 *      purpose-drawn compact picture, which is NOT the full one with lines
 *      removed — trimming a small picture destroys the thing that made it
 *      recognisable.
 */
function collectibleArt(object, lod = 'full') {
  const state = object.semantic_state ?? {};
  const catalog = String(state.catalog_id ?? '').toLowerCase();
  const label = String(object.semantic_name ?? '').toLowerCase().replaceAll(' ', '_');
  const entry = STARTER_COLLECTIBLE_ART[catalog]
    ?? STARTER_COLLECTIBLE_ART[Object.keys(STARTER_COLLECTIBLE_ART).find(key => label.includes(key))]
    ?? COLLECTIBLE_ART[catalog]
    ?? COLLECTIBLE_ART[Object.keys(COLLECTIBLE_ART).find(key => label.includes(key))]
    ?? COLLECTIBLE_ART[state.family]
    ?? COLLECTIBLE_ART.authored_keepsake;
  return lod === 'full' ? entry.full : entry.compact;
}

function fixtureArt(object, lod = 'full', frame = 0) {
  const catalog = String(object.semantic_state?.catalog_id ?? 'fixture');
  const visualAssetId = String(
    object.semantic_state?.visual_asset_id ?? `fixture.${catalog}`,
  );

  // CANONICAL ART FIRST.
  //
  // The versioned atlas is the single owner of any asset it carries. It is
  // consulted before the browser-local tables so that migrating an asset into
  // the atlas is the only step needed to change who owns it -- there is no
  // second switch to remember to flip.
  //
  // An asset the atlas does not yet own returns null here and falls through to
  // the legacy tables below. Those tables shrink to nothing as the remaining
  // fixtures are migrated one class at a time.
  const canonical = canonicalProportionalArt(visualAssetId, 'idle', frame);
  if (canonical) {
    // `compactRows` is present only when the asset carries an authored
    // narrow-viewport drawing. When it is absent the full drawing is reduced
    // the same way generated art is.
    if (lod !== 'full' && canonical.compactRows) return canonical.compactRows;
    return lod === 'full'
      ? canonical.rows
      : presentationLod(canonical.rows, object.kind, lod);
  }

  const purposeDrawn = STARTER_FIXTURE_ART[catalog];
  if (purposeDrawn) return purposeDrawn[lod === 'full' ? 'full' : 'compact'];
  return presentationLod(
    FIXTURE_DECOR[catalog] ?? [glyphForProjection(object)], object.kind, lod,
  );
}

/**
 * Reduce a picture for a smaller viewport.
 *
 * Only kinds whose art is generated rather than authored per density come
 * through here. Collectibles are excluded: they carry their own compact
 * picture, chosen in `collectibleArt`, because dropping interior lines from a
 * three-line drawing leaves something that depicts nothing.
 *
 * The plant and animal budgets are deliberately generous. A mature oak reduced
 * to three lines is no longer a tree, and a Garden of uniformly three-line
 * stubs is the flat heap this reduction was meant to avoid.
 */
function presentationLod(lines, kind, lod) {
  if (lod === 'full' || kind === 'collectible') return lines;
  const maximum = lod === 'compact'
    ? (kind === 'fixture' ? 3 : 6)
    : (kind === 'fixture' ? 4 : 8);
  if (lines.length <= maximum) return lines;
  const head = lines[0], tail = lines.slice(-(maximum - 1));
  return [head, ...tail];
}

/**
 * Semantic colour roles an authored visual part may claim.
 *
 * A ROLE, not a colour, is what the atlas declares. The mailbox flag asks for
 * `signal` -- "this part tells you something has arrived" -- while the exact
 * rose asset names bloom, stem and vessel parts. The palette
 * decides what `signal` looks like in the current theme and season. Had the
 * atlas named a hex value instead, changing the palette would mean editing
 * artwork, and a dark theme would have no way to keep the accent legible.
 *
 * The set is deliberately tiny. Every entry is a meaning the garden actually
 * needs; a role that exists "because a part should stand out" is decoration,
 * and decoration is what the restrained palette exists to keep out.
 */
const ACCENT_ROLES = Object.freeze({
  signal: 'flag', bloom: 'flower', stem: 'brightGreen', vessel: 'brown',
});

/**
 * Resolve an asset-authored part-role map into palette colours.
 *
 * @param accents `{ "row,column": role }` as authored, or null/undefined.
 * @returns `{ "row,column": color }` for `Raster.art`, or null when there is
 *   nothing to accent. An unknown role is dropped rather than guessed at, so a
 *   typo in an atlas asset loses the accent instead of inventing a colour.
 */
export function accentColors(accents, palette, season) {
  if (!accents) return null;
  const resolved = {};
  for (const [cell, role] of Object.entries(accents)) {
    const key = ACCENT_ROLES[role];
    if (key) resolved[cell] = paletteColor(palette, key, season);
  }
  return Object.keys(resolved).length ? resolved : null;
}

export function objectPresentationArt(object, frame, lod = 'full', emphasized = false) {
  const state = object.semantic_state ?? {};
  if (object.kind === 'plant') {
    const art = plantArt(object, frame, emphasized, lod);
    return { ...art, identity: art.identity ?? null, lines: art.purposeDrawn
      ? art.lines : presentationLod(art.lines, object.kind, lod),
    animated: art.animated ?? true };
  }
  if (object.kind === 'animal') {
    const animal = animalArt(object, frame, lod);
    return {
      lines: presentationLod(animal.lines, object.kind, lod),
      identity: animal.identity,
      color: 'creature', animated: true,
      poseFamily: animalPoseFamily(state.intent ?? state.current_intent, state.choreography_locked),
    };
  }
  if (object.kind === 'fixture') {
    const catalog = String(state.catalog_id ?? 'fixture');
    const visualAssetId = String(state.visual_asset_id ?? `fixture.${catalog}`);
    const canonical = canonicalProportionalArt(visualAssetId, 'idle', frame);
    const lines = fixtureArt(object, lod, frame);
    const maximumWidth = Math.max(0, ...lines.map(line => [...line].length));
    return { lines,
      assetId: canonical ? visualAssetId : null,
      measured: Boolean(canonical),
      // Full atlas art carries its authored anchor. A reduced derivative keeps
      // the same baseline/centre convention but is still measured as strings.
      assetAnchor: canonical && lod === 'full'
        ? canonical.anchor : [Math.floor(maximumWidth / 2), lines.length - 1],
      // Accents come from the atlas asset and only apply to the full drawing:
      // a reduced picture has different rows, so its cell coordinates would no
      // longer point at the part that was authored.
      accents: lod === 'full' ? canonical?.accents ?? null : null,
      color: catalog === 'pond' ? 'water' : state.presentation_state === 'on' ? 'gold' : 'stone' };
  }
  return { lines: presentationLod(collectibleArt(object, lod), object.kind, lod),
    color: state.family === 'animal_trace' ? 'creature' : 'gold' };
}

/**
 * How high above its soil line an object's feet are allowed to sit.
 *
 * Everything in this Garden lives on the ground except a bird in flight. That
 * is the whole rule, and it is stated here in one place so a future kind cannot
 * quietly acquire the ability to hover by being added to the packing loop.
 *
 * object   the canonical object being placed
 * Returns the maximum lift in character lines; 0 means feet on the soil.
 */
function maximumFlightLift(object) {
  if (object?.kind !== 'animal') return 0;
  const state = object.semantic_state ?? {};
  if (String(state.species_id ?? '') !== 'bird') return 0;
  // A bird that is resting, foraging, grooming or bathing is on the ground or
  // on a fixture, exactly like every other animal. Only active intents lift it.
  const intent = String(state.intent ?? state.current_intent ?? '').toLowerCase();
  if (/rest|sleep|forage|groom|bathe|nap|drink/.test(intent)) return 0;
  // Matches the flight height the pre-removal presentation used, which was
  // reviewed and accepted: high enough to read as flight, low enough to stay
  // visually attached to the Garden rather than drifting into empty sky.
  return 6;
}

/**
 * Dimensions used for PLACEMENT, which must not change between frames.
 *
 * Packing from the currently-animated picture is what made the whole scene
 * rearrange itself when a single plant swayed or an animal changed pose: a
 * one-cell difference in one object's art alters its rectangle, which alters
 * the collision solution, which moves unrelated objects. Placement therefore
 * uses a footprint that is the largest picture the object can ever present,
 * computed once from its pose set rather than from the current frame.
 *
 * object  canonical object
 * lod     current level of detail, since that genuinely does change size
 * Returns {width, height} in character cells.
 */
function stableArtFootprint(object, lod) {
  const measure = lines => ({
    width: Math.max(1, ...lines.map(line => [...String(line)].length)),
    height: Math.max(1, lines.length),
  });
  if (object.kind === 'animal') {
    // Every phase of the pose family this animal is currently in. Intent is
    // projection state, so it is stable across frames; only the phase cycles.
    // Resolved through the same function that draws it, so an archived pose and
    // a placeholder pose are measured on identical terms.
    const { poses } = resolveAnimalPose(object, 0, lod);
    const sizes = poses.map(pose => measure(presentationLod(pose, object.kind, lod)));
    const size = {
      width: Math.max(...sizes.map(size => size.width)),
      height: Math.max(...sizes.map(size => size.height)),
    };
    // Animal poses are not atlas assets with authored anchors, so they keep the
    // centred-on-feet default. Stated explicitly rather than left to a fallback
    // so the two conventions are visible side by side.
    return { ...size, anchor: centredArtAnchor(size) };
  }
  // Fixtures and collectibles are static, so one frame is representative.
  //
  // Plants used to be too, because their animation substituted single glyphs
  // and never changed the outline. The legacy sway does change it -- a leaning
  // stem is a different picture -- so this would now be reading one arbitrary
  // frame's width. It stays correct because `normalizeFrames` pads every frame
  // of an archived sequence to the sequence's own bounding box before the
  // renderer ever sees it: the ink moves inside a box that does not. Frame 0 is
  // used so the result is stable.
  const art = objectPresentationArt(object, 0, lod);
  const size = measure(art.lines);
  return { ...size, anchor: authoredArtAnchor(art, size) };
}

/**
 * Where inside its own drawing an object's anchor cell sits, by default.
 *
 * Horizontally centred, vertically on the last row -- "the feet". This is the
 * convention `GardenRaster.art` has always used for non-asset decoration, and
 * it stays the default for anything the atlas did not author an anchor for.
 *
 * @param {{width: number, height: number}} size the drawing's bounding box
 * @returns {[number, number]} column and row within the drawing
 */
function centredArtAnchor(size) {
  return [Math.floor(size.width / 2), size.height - 1];
}

/**
 * The anchor an atlas asset authored, or the centred default.
 *
 * WHY THIS EXISTS. Measured atlas pictures are painted by
 * `GardenRaster.measuredArt`, which places them at `anchorX - assetAnchor[0]`.
 * The placement rectangle was computed separately at `anchorX - width/2`. When
 * an asset's authored anchor is not the middle of its own box, those two
 * disagree, and the rectangle stops describing the picture it is supposed to
 * describe.
 *
 * That is not cosmetic. The rectangle is what collision packs, what the ground
 * painter treats as covered, what hit testing turns into a target, and what the
 * terminal reads -- so a one-column error means an object is clickable one
 * column off its own ink, and the ground line goes unpainted under a cell an
 * object is genuinely standing on. Stepping stones authored `[5,1]` inside a
 * 12-wide box against a centred `[6,1]`, and the ground row showed the result:
 * a bare `)` sitting on nothing at column 67.
 *
 * Goal section 5 states the rule this restores -- interaction geometry must
 * "follow exactly the same transform as the art" -- and section 2 forbids the
 * "mismatch between painted ink and interaction geometry" that the two
 * conventions produced.
 *
 * @param {{assetAnchor?: [number, number]}} art the resolved presentation art
 * @param {{width: number, height: number}} size its bounding box
 * @returns {[number, number]} the anchor to lay the drawing out from
 */
function authoredArtAnchor(art, size) {
  const authored = art?.assetAnchor;
  if (Array.isArray(authored) && authored.length === 2 &&
    Number.isFinite(Number(authored[0])) && Number.isFinite(Number(authored[1]))) {
    return [Number(authored[0]), Number(authored[1])];
  }
  return centredArtAnchor(size);
}

/**
 * Rectangle a footprint occupies when it is placed at `anchor`.
 *
 * `size.anchor` says where inside the drawing that cell falls, so the rectangle
 * is derived by the same subtraction the painter performs. Objects whose art
 * anchors on its last row still get `bottom === anchor[1]`, which is what
 * "its feet rest on the anchor" meant before the anchor became explicit.
 */
function footprintRect(anchor, size) {
  const origin = size.anchor ?? centredArtAnchor(size);
  const left = anchor[0] - origin[0], top = anchor[1] - origin[1];
  return {
    left, right: left + size.width - 1,
    top, bottom: top + size.height - 1,
  };
}

/**
 * Canonical neighbors whose pictures deliberately share one visual feature.
 *
 * This does not create a gameplay link: exact IDs, actions and hotspots remain
 * separate. It only permits the water lily and bridge to be painted into the
 * pond picture when their canonical positions already put them together.
 */
export function gardenObjectsShareVisualFeature(left, right) {
  const fixture = object => object?.kind === 'fixture'
    ? String(object.semantic_state?.catalog_id ?? '') : '';
  const plant = object => object?.kind === 'plant'
    ? String(object.semantic_state?.species_id ?? '') : '';
  const fixturePair = new Set([fixture(left), fixture(right)]);
  if (fixturePair.has('pond') && fixturePair.has('bridge')) return true;
  if (fixturePair.has('pond') && fixturePair.has('stepping_stones')) return true;
  return (fixture(left) === 'pond' && plant(right) === 'water_lily') ||
    (fixture(right) === 'pond' && plant(left) === 'water_lily');
}

export function layoutGardenObjects(projection, viewport, frame = 0, terrain = null) {
  const profile = gardenPresentationProfile(viewport);
  const visibleTerrain = terrain ?? gardenTerrainFrame(projection, viewport, profile);
  const kindOrder = { fixture: 0, plant: 1, collectible: 2, animal: 3 };
  const ordered = [...(projection.objects ?? [])].sort((left, right) =>
    Number(left.position?.[1] ?? 0) - Number(right.position?.[1] ?? 0) ||
    (kindOrder[left.kind] ?? 9) - (kindOrder[right.kind] ?? 9) ||
    Number(left.depth ?? 100) - Number(right.depth ?? 100) ||
    compareCodePoints(left.object_id, right.object_id));
  const prepared = [];
  for (const object of ordered) {
    const art = objectPresentationArt(object, frame, profile.lod);
    const depth = Number(object.depth ?? 100) / 100;
    // Feet land on the soil line for this object's world depth. A bird in
    // flight is lifted off that line by a bounded amount; nothing else is.
    const ground = worldToGardenScreen(object.position, projection.camera, viewport, depth);
    // Placement geometry comes from the frame-independent footprint so that a
    // sway, a pose change or a focus highlight cannot repack the scene.
    const footprint = stableArtFootprint(object, profile.lod);
    // Flight height is capped by the headroom that actually exists. On a short
    // viewport the full height would carry a bird off the top of the frame,
    // where it would be culled entirely and simply vanish.
    const lift = clamp(
      maximumFlightLift(object), 0, Math.max(0, ground[1] - footprint.height + 1),
    );
    const base = [ground[0], ground[1] - lift];
    const baseRect = footprintRect(base, footprint);
    // Horizontal culling is unchanged. Vertical culling now asks whether the
    // object's feet fall on the visible ground plane: a world depth in front of
    // or behind the plane is outside the camera's view, exactly as a position
    // off the left or right edge is.
    if (baseRect.right < 0 || baseRect.left >= profile.width ||
      ground[1] < visibleTerrain.groundBack || ground[1] > visibleTerrain.groundFront) continue;
    prepared.push({
      object, art, lod: profile.lod, baseAnchor: base, baseRect, footprint,
      groundRow: ground[1], lift,
      // Hit testing stays projection-owned: the rectangle is still derived
      // entirely from the object's own hotspot. It is only carried up by the
      // same presentation lift applied to the art, so that a bird in flight can
      // be clicked where it is actually drawn rather than at the empty patch of
      // soil it took off from. Objects on the ground have a zero lift and are
      // therefore completely unchanged.
      baseHitRect: translatedRect(
        projectedHotspotRect(object, projection, viewport, depth), 0, -lift,
      ),
    });
  }

  // A projection-owned connected group is one visual packing unit. Moving the
  // unit is disposable presentation; every member retains its exact canonical
  // relative anchor and connected-mask topology.
  const units = new Map();
  for (const entry of prepared) {
    const group = entry.object.kind === 'fixture'
      ? entry.object.semantic_state?.connected_group : null;
    const key = group === null || group === undefined
      ? `object:${entry.object.object_id}` : `connected:${group}`;
    if (!units.has(key)) units.set(key, []);
    units.get(key).push(entry);
  }

  const placed = [];
  for (const entries of units.values()) {
    const bounds = {
      left: Math.min(...entries.map(entry => entry.baseRect.left)),
      right: Math.max(...entries.map(entry => entry.baseRect.right)),
      top: Math.min(...entries.map(entry => entry.baseRect.top)),
      bottom: Math.max(...entries.map(entry => entry.baseRect.bottom)),
    };
    // A compositor may nudge a picture enough to resolve a glyph collision,
    // but it may not relocate an object across the viewport. Unbounded packing
    // created a new fake scene at paint time and destroyed the canonical
    // pond/bridge, trellis/plant and path relationships.
    // A phone is a camera slice, not a request to drag every object on screen.
    // Keep only enough local freedom to clear a neighboring silhouette. A unit
    // that still cannot fit is culled until canonical pan/focus reaches it.
    const maximumXShift = profile.lod === 'compact' ? 2 :
      profile.lod === 'medium' ? 4 : 8;
    const xOffsets = orderedIntegerRange(
      Math.max(-bounds.left, -maximumXShift),
      Math.min(profile.width - 1 - bounds.right, maximumXShift),
    );
    // Vertical freedom is limited to moving the unit between SOIL LINES. Every
    // member's feet must land on ground that is actually painted, so the
    // permitted range is derived from the members' ground rows rather than from
    // the whole object band. Without this the packer resolves a collision by
    // lifting a bench into the sky, which is precisely the defect being
    // repaired: an object band is somewhere art may extend into, never
    // somewhere feet may rest.
    const groundRowsUsed = entries.map(entry => entry.groundRow);
    const maximumYShift = profile.lod === 'compact' ? 1 :
      profile.lod === 'medium' ? 2 : 3;
    const yOffsets = orderedIntegerRange(
      Math.max(
        visibleTerrain.groundBack - Math.min(...groundRowsUsed), -bounds.top, -maximumYShift,
      ),
      Math.min(
        visibleTerrain.groundFront - Math.max(...groundRowsUsed), maximumYShift,
      ),
    );
    const candidates = [];
    for (const dy of yOffsets) for (const dx of xOffsets) candidates.push({
      // Sliding sideways preserves how far away a thing looks; moving it
      // between soil lines changes its apparent distance, so depth changes are
      // charged far more and are only taken when nothing else resolves.
      dx, dy, distance: Math.abs(dx) * 2 + Math.abs(dy) * 12,
    });
    candidates.sort((left, right) => left.distance - right.distance ||
      Math.abs(left.dy) - Math.abs(right.dy) || left.dy - right.dy || left.dx - right.dx);

    let best = null;
    for (const candidate of candidates) {
      const translated = entries.map(entry => ({
        ...entry,
        anchor: [entry.baseAnchor[0] + candidate.dx, entry.baseAnchor[1] + candidate.dy],
        rect: translatedRect(entry.baseRect, candidate.dx, candidate.dy),
        hitRect: translatedRect(entry.baseHitRect, candidate.dx, candidate.dy),
      }));
      // Functional neighbors may share a painted bed or water edge, but their
      // independently targetable pictures may never overlap. Grouping is added
      // later as background presentation, not by collapsing two canonical
      // objects into one raster footprint.
      const overlap = translated.reduce((total, entry) => total + placed.reduce(
        (subtotal, item) => subtotal + intersectionArea(entry.rect, item.rect), 0,
      ), 0);
      const padded = translated.reduce((total, entry) => total + placed.reduce(
        (subtotal, item) => subtotal + intersectionArea(
          entry.rect, item.rect,
          gardenObjectsShareVisualFeature(entry.object, item.object) ? 0 : 1,
        ), 0,
      ), 0);
      const score = overlap * 1000000 + padded * 1000 + candidate.distance;
      if (!best || score < best.score) best = { translated, overlap, score };
    }
    // A unit that cannot fit in this bounded canonical neighbourhood belongs
    // outside the current camera slice. It stays available through canonical
    // focus/pan rather than being swept into an unrelated empty slot.
    if (!best || best.overlap > 0) continue;
    placed.push(...best.translated);
  }
  return placed;
}

/**
 * Presentation cohorts derived from already-packed canonical depth.
 *
 * They do not change an anchor, object order in the projection, or a hotspot.
 * The cohorts only establish a painter's order so near planting can overlap the
 * feet of the middle distance while far silhouettes remain behind it.
 */
export function gardenDepthCohorts(layout, profile, terrain = null) {
  const visibleTerrain = terrain ?? profile;
  const cohorts = { far: [], middle: [], near: [] };
  const span = Math.max(1, visibleTerrain.groundFront - visibleTerrain.groundBack);
  for (const entry of layout) {
    const nearness = clamp((entry.groundRow - visibleTerrain.groundBack) / span, 0, 1);
    const name = nearness < 0.34 ? 'far' : nearness < 0.68 ? 'middle' : 'near';
    cohorts[name].push(entry);
  }
  for (const entries of Object.values(cohorts)) entries.sort((left, right) =>
    left.groundRow - right.groundRow ||
    Number(left.object.depth ?? 100) - Number(right.object.depth ?? 100) ||
    compareCodePoints(left.object.object_id, right.object.object_id));
  return cohorts;
}

export function paletteColor(palette, key, season) {
  if (season === 'autumn' && ['green', 'brightGreen'].includes(key)) return key === 'green' ? '#a66d25' : '#c18a2f';
  if (season === 'winter' && key === 'brightGreen') return palette.stone;
  return palette[key] ?? palette.text;
}

export function objectBurstPattern(burst, age = 0) {
  const kind = String(burst?.kind ?? 'ambient');
  const species = String(burst?.species ?? '');
  const catalog = String(burst?.catalog ?? '');
  const phase = Math.max(0, Number(age) || 0);
  if (kind === 'plant') {
    const pine = species === 'pine';
    const grass = species === 'meadow_grass';
    const glyphs = pine ? ["'", '`', '.', "'"] : grass ? ["'", '/', '\\', ','] : ['*', 'o', '·', '*'];
    return [[-2, -1], [-1, -2], [0, -2], [1, -2], [2, -1], [-1, 0], [1, 0], [0, 1]]
      .slice(0, phase < 4 ? 8 : 5)
      .map(([dx, dy], index) => [dx, dy + Math.floor(phase / 4), glyphs[index % glyphs.length],
        pine ? 'deepGreen' : grass ? 'brightGreen' : 'flower']);
  }
  if (kind === 'fixture') {
    if (catalog === 'pond' || catalog === 'birdbath' || catalog === 'well')
      return [[-2, 0, '~', 'water'], [-1, 0, '~', 'water'], [1, 0, '~', 'water'], [2, 0, '~', 'water']];
    if (catalog === 'lantern')
      return [[0, -2, '*', 'gold'], [-1, -1, '·', 'gold'], [1, -1, '·', 'gold']];
    return [[-1, -1, '+', 'stone'], [1, -1, '+', 'stone'], [0, -2, '·', 'gold']];
  }
  if (kind === 'collectible')
    return [[0, -2, '✦', 'gold'], [-1, -1, '·', 'gold'], [1, -1, '·', 'gold']];
  if (kind === 'animal')
    return [[-1, -2, '·', 'flower'], [0, -3, '*', 'flower'], [1, -2, '·', 'flower']];
  return [[0, -1, '·', 'gold']];
}

// ---------------------------------------------------------------------------
// Composition painters, extracted from the renderer class 2026-08-03.
// ---------------------------------------------------------------------------
//
// These were `CanonicalGardenRenderer` methods. They are module-level pure
// functions now -- every input is a parameter, none reads `this` -- so the
// GardenPresentation owner can call them without owning a renderer. This
// extraction changes NO behaviour: the class calls the same functions with
// the same values, and the ownership transfer that retires the class's
// orchestration is the following patch, not this one.

export function drawSky(raster, projection, sky, palette, profile, mode) {
  const observedTime = presentationTime(projection);
  // Project the catalogue into the region the sky actually owns rather than
  // over the whole frame. Stars projected into the Garden band are painted
  // and then immediately covered by ground, planting and objects, so they
  // were doing nothing except thinning the visible sky.
  const skyRows = Math.max(2, profile.bandTop);
  const projected = projectSkyPoints(sky, observedTime, [raster.width, skyRows]);
  const visible = mode === 'day' ? (sky.astronomical ? [] : projected.slice(0, 3)) :
    mode === 'evening' ? projected.filter((_, index) => index % 2 === 0) : projected;
  for (const [x, y, glyph] of visible) raster.put(x, y, glyph, palette.star, false, null,
    { source: 'recipe.scene.starfield' });
  if (mode === 'night') {
    const art = MOON_ART[lunarPhase(observedTime)];
    art.forEach((line, row) => raster.text(Math.max(1, Math.floor(raster.width * 0.78)), 1 + row, line, palette.moon,
      false, null, { source: 'recipe.scene.moon' }));
  }
}


/**
 * Paint the two authoritative contours of the receding ground plane.
 *
 * These uninterrupted far-transition and near-soil edges are the only
 * renderer-owned marks on the ground. Population comes exclusively from the
 * canonical projection.
 */
export function drawGround(raster, palette, season, terrain) {
  // `profile.horizon` is deliberately NOT read here. It is a neutral viewport
  // bound, not the current frame's camera-projected terrain.
  // Restore the Garden's previous continuous punctuation texture. The
  // structural reference supplied the far-band SHAPE; its `---^/\\` bytes were
  // never Garden art and must not be copied into the product.
  const farTexture = ',~.^,.,~^,.,~,.^,~.,';
  const nearSoil = '.,,.*,.`';
  // Both edges remain one terrain owner's responsibility. The far contour is
  // also the CSS colour transition and roots big trees/far fixtures. The near
  // contour roots small legacy planting and the pond room. Their distinct
  // texture and colour are intentional depth cues, not two unrelated bands.
  for (const row of [terrain.farGroundY, terrain.groundFront]) {
    for (let x = 0; x < raster.width; x += 1) {
      const isFarEdge = row === terrain.farGroundY;
      const texture = isFarEdge ? farTexture : nearSoil;
      const glyph = texture[(x + (isFarEdge ? 0 : 5)) % texture.length];
      raster.put(x, row, glyph,
        isFarEdge ? palette.dimGreen : palette.ground, false, null,
        { source: 'recipe.scene.ground_line' });
    }
  }
}

// The deployed Garden's planting is presentation-native: it is regenerated
// from the measured viewport and fills as many non-overlapping silhouettes as
// the frame can hold.  Replacing it with two canonical starter records made
// the current Garden sparse by construction.  These functions are the exact
// deployed generators from the frozen 59dc49a8 viewer, expressed as pure data
// so canonical gameplay objects remain the only interactive/persisted plants.
class LegacyPlantRng {
  constructor(seed) {
    const hash = value => {
      value ^= value >> 16; value = Math.imul(value, 0x45d9f3b) >>> 0;
      value ^= value >> 16; return value >>> 0;
    };
    this.a = hash(seed >>> 0); this.b = hash((seed + 1) >>> 0);
    this.c = hash((seed + 2) >>> 0); this.d = hash((seed + 3) >>> 0);
    for (let index = 0; index < 20; index += 1) this.random();
  }
  random() {
    const total = ((this.a + this.b | 0) + this.d) | 0;
    this.d = this.d + 1 | 0; this.a = this.b ^ (this.b >>> 9);
    this.b = this.c + (this.c << 3) | 0;
    this.c = (this.c << 21 | this.c >>> 11); this.c = this.c + total | 0;
    return (total >>> 0) / 4294967296;
  }
  randint(first, last) { return first + Math.floor(this.random() * (last - first + 1)); }
  choice(values) { return values[Math.floor(this.random() * values.length)]; }
  choices(values, weights) {
    let draw = this.random() * weights.reduce((total, value) => total + value, 0);
    for (let index = 0; index < values.length; index += 1) {
      draw -= weights[index]; if (draw <= 0) return values[index];
    }
    return values.at(-1);
  }
}

const LEGACY_PLANT_WEIGHTS = Object.freeze({
  spring: Object.freeze({ pine: 6, oak: 6, bush: 8, flower: 30, grass: 15, mushroom: 2, fern: 5 }),
  summer: Object.freeze({ pine: 8, oak: 8, bush: 8, flower: 18, grass: 12, mushroom: 3, fern: 7 }),
  autumn: Object.freeze({ pine: 10, oak: 10, bush: 6, flower: 4, grass: 8, mushroom: 5, fern: 6 }),
  winter: Object.freeze({ pine: 15, oak: 4, bush: 4, flower: 0, grass: 4, mushroom: 2, fern: 3 }),
});
const LEGACY_AUTUMN_COLORS = Object.freeze(['yellow', 'bright_yellow', 'orange', 'red', 'brown']);
const LEGACY_GRASS_FAMILIES = Object.freeze([["'", '`', ','], ['/', '|', '\\'], ['v', 'y', 'w'], ['"', ';', "'"]]);

function legacyPine(rng) {
  const height = rng.randint(8, 16), levels = height - 2;
  const rows = [[1, 0, '|', 'brown'], [2, 0, '|', 'brown']];
  for (let level = 0; level < levels; level += 1) {
    const dy = 3 + level;
    if (level === levels - 1) rows.push([dy, 0, '^', 'bright_green']);
    else {
      // `dy` increases upward from the baseline. Width must therefore shrink
      // as `level` rises; using `width = level` produced an upside-down pine
      // whose broadest boughs sat immediately under the apex.
      const width = Math.max(1, Math.ceil((levels - level) * 0.65));
      rows.push([dy, -width,
        '/'.repeat(width) + (level % 2 ? '*' : '^') + '\\'.repeat(width),
        level < levels / 2 ? 'bright_green' : 'green']);
    }
  }
  const maximum = Math.max(1, Math.ceil(levels * 0.65));
  return { type: 'pine', rows, width: maximum * 2 + 1 };
}
function legacyOak(rng) {
  const height = rng.randint(8, 14), trunk = Math.max(2, Math.floor(height / 3));
  const glyph = rng.choice(['@', 'o', '0', '&']), rows = [];
  for (let index = 1; index <= trunk; index += 1) rows.push([index, 0, '|', 'brown']);
  const crown = height - trunk, radius = Math.floor(crown / 2) + 1;
  for (let level = 0; level <= crown + 1; level += 1) {
    const dy = trunk + level + 1, t = level / (crown + 1) * 2 - 1;
    const width = Math.max(0, Math.round(radius * Math.sqrt(Math.max(0, 1 - t * t))));
    if (width) rows.push([dy, -width, glyph.repeat(width * 2 + 1),
      level > 0 && level <= crown ? 'bright_green' : 'green']);
  }
  return { type: 'oak', rows, width: radius * 2 + 3 };
}
function legacyBush(rng) {
  const width = rng.randint(2, 4), glyph = rng.choice(['~', 'u', 'w', 'v']);
  return { type: 'bush', rows: [
    [2, -(width + 1), `(${glyph.repeat(width * 2 + 1)})`, 'bright_green'],
    [1, -width, `{${glyph.repeat(width * 2 - 1)}}`, 'green'],
  ], width: width * 2 + 4 };
}
function legacyFlower(rng) {
  const species = rng.choice(['daisy', 'tulip', 'sunflower', 'wildflower', 'rose']);
  const stem = rng.randint(2, 5), rows = [];
  for (let index = 1; index <= stem; index += 1) rows.push([index, 0, '|', 'green']);
  if (stem >= 2) {
    const leafY = rng.randint(1, stem - 1), side = rng.choice(['left', 'right', 'both', 'none', 'none']);
    if (side === 'left' || side === 'both') rows.push([leafY, -1, '\\', 'green']);
    if (side === 'right' || side === 'both') rows.push([leafY, 1, '/', 'green']);
  }
  const bloom = stem + 1;
  if (species === 'daisy') {
    const color = rng.choice(['white', 'bright_white', 'cyan', 'bright_cyan']);
    rows.push([bloom + 1, -1, '\\*/', color], [bloom, -1, '-O-', 'bright_yellow']);
  } else if (species === 'tulip') {
    const color = rng.choice(['red', 'magenta', 'bright_magenta', 'bright_red']);
    rows.push([bloom + 1, -1, '(" )'.replace(' ', ''), color], [bloom, -1, '|"|', color]);
  } else if (species === 'sunflower') {
    rows.push([bloom + 1, -2, '\\{O}/', 'bright_yellow'], [bloom, -1, '{#}', 'yellow']);
  } else if (species === 'wildflower') {
    const color = rng.choice(['magenta', 'bright_magenta', 'cyan', 'bright_cyan', 'bright_white']);
    rows.push([bloom + 1, 0, '*', color], [bloom, -1, '>*<', color]);
  } else {
    const color = rng.choice(['red', 'bright_magenta', 'bright_red']);
    rows.push([bloom + 1, -1, '@@@', color], [bloom, -1, '(@)', color]);
  }
  return { type: 'flower', rows, width: species === 'sunflower' ? 5 : 3 };
}
function legacyGrass(rng) {
  const count = rng.randint(1, 3), offsets = count === 1 ? [0] : count === 2 ? [-1, 1] : [-1, 0, 1];
  const blades = offsets.map(dx => ({ dx, height: rng.randint(2, 5), seed: rng.randint(0, 1023),
    family: rng.randint(0, LEGACY_GRASS_FAMILIES.length - 1), flower: rng.random() < 0.09 }));
  return { type: 'grass', blades, rows: [], width: count === 1 ? 1 : 3 };
}
function legacyMushroom(rng) {
  const width = rng.randint(1, 2), color = rng.choice(['red', 'bright_red', 'yellow', 'bright_white', 'magenta']);
  return { type: 'mushroom', rows: [[2, -width, `(${'~'.repeat(width * 2)})`, color], [1, 0, '|', 'white']], width: width * 2 + 2 };
}
function legacyFern(rng) {
  const height = rng.randint(2, 4), rows = [[height + 1, 0, '*', 'bright_green']];
  for (let index = 1; index <= height; index += 1) {
    rows.push([index, 0, '|', 'green']);
    rows.push([index, -1, index % 2 ? '*' : ',', index % 2 ? 'bright_green' : 'green']);
    rows.push([index, 1, index % 2 ? '*' : ',', index % 2 ? 'bright_green' : 'green']);
  }
  return { type: 'fern', rows, width: 3 };
}
const LEGACY_PLANT_MAKERS = Object.freeze({
  pine: legacyPine, oak: legacyOak, bush: legacyBush, flower: legacyFlower,
  grass: legacyGrass, mushroom: legacyMushroom, fern: legacyFern,
});

// ---------------------------------------------------------------------------
// WORLD-SPACE BACKDROP (parallax ADR, 2026-08-04).
//
// The first port of the deployed planting generated positions from
// `raster.width` and painted at fixed screen columns -- a second coordinate
// owner beside the canonical camera. Arrow-key panning moved the canonical
// fixtures while the backdrop stood still, which is the split the operator
// rejected. The backdrop is now authored in WORLD COLUMNS over a fixed
// extended extent and projected through the same `worldToGardenScreen`
// transform as everything else, with its own depth: the camera moves every
// layer, background more slowly than the interactive world, foreground
// cover faster -- the deployed page never had a pannable camera, so this is
// the deployed LOOK carried into the canonical architecture rather than a
// copy of its screen-space generation.
//
// The extent is wide enough that no reachable camera can pan past the
// planted region at the shallowest depth on the widest supported frame:
// panning cannot expose uninitialized columns, and resize changes the crop,
// never the population.
// ---------------------------------------------------------------------------
const LEGACY_WORLD_COLUMNS = 120;
const LEGACY_WORLD_ROWS = 80;
const LEGACY_BACKDROP_MARGIN = 300;
// The declared starter camera is [60, 51] in the canonical 120 x 80 world.
// Presentation-native vegetation has stable terrain coordinates relative to
// that authored view; it is not repacked when the camera or viewport changes.
const LEGACY_HOME_CAMERA_Y = 51;
const LEGACY_TERRAIN_CENTER = 0.45;

/** Deepest and shallowest backdrop layers (ADR band 0.45-0.65). */
const LEGACY_TREE_DEPTH = [0.45, 0.55];
const LEGACY_SHRUB_DEPTH = [0.55, 0.65];
/** Ground cover leads the canonical world slightly: fast foreground. */
const LEGACY_COVER_DEPTH = 1.12;

/**
 * The population is a pure function of (seed, season) over the fixed world
 * extent, so it is memoised: the deployed page generated its layout once per
 * reset, and regenerating identical placements every composed frame would be
 * the same picture at thirty times the cost. Cache keys are exact inputs, so
 * composition stays observationally pure -- composing twice still returns
 * one picture.
 */
const legacyLayoutCache = new Map();

function legacyPlantCardRect(plant, anchorX, baseline, margin = 0) {
  if (plant.blades) {
    const left = Math.min(...plant.blades.map(blade => anchorX + blade.dx)) - 2;
    const right = Math.max(...plant.blades.map(blade => anchorX + blade.dx)) + 2;
    const top = baseline - Math.max(...plant.blades.map(blade => blade.height)) - 1;
    return { left: left - margin, right: right + margin,
      top: top - margin, bottom: baseline + margin };
  }
  const left = Math.min(...plant.rows.map(([, dx]) => anchorX + dx));
  const right = Math.max(...plant.rows.map(([, dx, text]) =>
    anchorX + dx + [...text].length - 1));
  const top = Math.min(...plant.rows.map(([dy]) => baseline - dy));
  const bottom = Math.max(...plant.rows.map(([dy]) => baseline - dy));
  return { left: left - margin, right: right + margin,
    top: top - margin, bottom: bottom + margin };
}

function legacyPlantLayout(seed, season) {
  const key = `${seed}:${season}`;
  const cached = legacyLayoutCache.get(key);
  if (cached) return cached;
  const rng = new LegacyPlantRng(seed);
  const weights = LEGACY_PLANT_WEIGHTS[season] ?? LEGACY_PLANT_WEIGHTS.summer;
  const names = Object.keys(weights), values = Object.values(weights);
  const first = -LEGACY_BACKDROP_MARGIN;
  const last = LEGACY_WORLD_COLUMNS + LEGACY_BACKDROP_MARGIN;
  const extent = last - first;
  // Membership is settled against one neutral projected field, never against
  // the current camera or viewport.  This gives the generator a real
  // two-dimensional card-spacing law without reviving the resize/pan defect
  // where plants appeared and vanished as the crop changed.
  const occupiedCards = [], regionCounts = new Map(), placed = [];
  for (let attempt = 0; attempt < extent * 3; attempt += 1) {
    const type = rng.choices(names, values), plant = LEGACY_PLANT_MAKERS[type](rng);
    if (season === 'autumn' && ['oak', 'bush'].includes(plant.type)) {
      plant.rows = plant.rows.map(([dy, dx, text, color]) => [dy, dx, text,
        color === 'green' || color === 'bright_green' ? rng.choice(LEGACY_AUTUMN_COLORS) : color]);
    }
    const isTree = plant.type === 'oak' || plant.type === 'pine';
    // A terrain coordinate is part of the generated population. Trees own the
    // far transition; smaller planting occupies several stable rows of the
    // receding plane. The previous implementation assigned no terrain
    // coordinate and consequently forced every flower onto groundFront.
    const plane = isTree ? 0 : 0.18 + rng.random() * 0.76;
    const band = isTree ? LEGACY_TREE_DEPTH : LEGACY_SHRUB_DEPTH;
    const baseDepth = band[0] + rng.random() * (band[1] - band[0]);
    const depth = isTree ? baseDepth : baseDepth + plane * 0.40;
    const half = Math.floor(plant.width / 2) + 2;
    const x = rng.randint(first + half + 1, last - half - 2);
    const worldY = LEGACY_HOME_CAMERA_Y +
      (plane - LEGACY_TERRAIN_CENTER) * LEGACY_WORLD_ROWS / depth;
    const [referenceX, referenceBaseline] = worldToGardenScreen(
      [x, worldY], [60, LEGACY_HOME_CAMERA_Y], [160, 66], depth,
    );
    const referenceRect = legacyPlantCardRect(plant, referenceX, referenceBaseline, 1);
    if (occupiedCards.some(rect => intersectionArea(referenceRect, rect) > 0)) continue;
    // A region may carry a small intentional cluster, but never an accretion
    // of unrelated cards.  The key is neutral-world projected, so membership
    // remains a pure function of seed and season under every pan and resize.
    const regionKey = `${Math.floor(referenceX / 24)}:${Math.floor(referenceBaseline / 9)}`;
    if ((regionCounts.get(regionKey) ?? 0) >= 3) continue;
    occupiedCards.push(referenceRect);
    regionCounts.set(regionKey, (regionCounts.get(regionKey) ?? 0) + 1);
    placed.push({ plant, x, depth, plane });
  }
  // Stable generation order only. Final paint order is owned by the shared
  // billboard queue, which interleaves these cards with canonical objects.
  placed.sort((left, right) => left.plane - right.plane || left.x - right.x);
  legacyLayoutCache.set(key, placed);
  return placed;
}

/**
 * How many rows above the walkable line a backdrop layer's baseline sits.
 *
 * The structural reference the operator supplied (Downloads/STRUCTURAL ASCII
 * ART EXAMPLES, 2026-07-31 screenshot) stands the background tree ABOVE the
 * one structural ground line with foreground texture continuing below it:
 * depth recedes upward. Shallow foreground (depth > 1) resolves below the
 * line, onto the soil rows.
 */
const LEGACY_INK_DAY = Object.freeze({
  dim_green: '#ddd8ce', deep_green: '#33511e', green: '#4a7030', bright_green: '#62923e',
  brown: '#7a5830', orange: '#b07020', bright_white: '#555555', white: '#777777',
  yellow: '#8a6418', bright_yellow: '#c09428', red: '#883830', bright_red: '#b85038',
  cyan: '#246858', bright_cyan: '#329878', magenta: '#702468', bright_magenta: '#a03888', dim: '#b0a898',
});
const LEGACY_INK_NIGHT = Object.freeze({
  ...LEGACY_INK_DAY, dim_green: '#13181e', deep_green: '#41703e', green: '#5a9858', bright_green: '#78b870',
  brown: '#a08868', orange: '#c89848', bright_white: '#cccccc', white: '#b0b0a8', yellow: '#c09838',
  bright_yellow: '#e0b848', red: '#d06860', bright_red: '#e87868', cyan: '#68a898',
  bright_cyan: '#80c8b0', magenta: '#b868a8', bright_magenta: '#d880c0', dim: '#606058',
});
const LEGACY_RUSTLE_A = Object.freeze({ '@': 'o', o: '0', 0: '@', '&': '@', '*': '.', '^': '*', '/': '\\', '\\': '/', '~': '`', u: 'v', v: 'u', w: '~', '(': '<', ')': '>' });
const LEGACY_RUSTLE_B = Object.freeze({ '@': '0', o: '@', 0: 'o', '&': 'o', '*': ',', '^': '`', '/': '\\', '\\': '/', '~': 'v', u: '~', v: 'w', w: 'u' });
const LEGACY_CANOPY_SHIMMER = new Set(['oak', 'bush', 'pine']);
function legacyRustle(glyph, intensity, seed) {
  const wave = Math.sin(seed) * intensity;
  return wave > 0.45 ? (LEGACY_RUSTLE_A[glyph] ?? glyph)
    : wave < -0.45 ? (LEGACY_RUSTLE_B[glyph] ?? glyph) : glyph;
}

export function drawGardenBillboards(
  raster, projection, palette, season, profile, terrain, frame, hoverCell,
  wind = 0, canonicalEntries = [], view = {},
) {
  // The ordinary picture contains only canonical world objects. Older code
  // populated this queue with renderer-owned plants and ground cover, so the
  // Garden visibly contained objects that persistence, hit testing, and
  // commands could not name. Canonical projection identity is now the only
  // route into this painter.
  const cards = canonicalEntries.map(entry => ({
    kind: 'canonical', baseline: entry.groundRow,
    depth: Number(entry.object.depth ?? 100) / 100,
    stableId: entry.object.object_id, entry,
  }));
  cards.sort((left, right) =>
    left.baseline - right.baseline || left.depth - right.depth ||
    compareCodePoints(left.stableId, right.stableId));
  for (const card of cards) {
    drawObject(raster, card.entry, projection, palette, season, view);
  }
}
export function drawAmbient(raster, projection, palette, season, horizon, profile) {
  const mode = timeOfDay(projection);
  // Small ambient life belongs among the planting, not scattered through the
  // whole airspace. The band runs from a little above the far edge of the
  // ground plane down to just above the near soil line, which is where the
  // flowers and grass are.
  const lifeBand = profile
    ? [Math.max(1, profile.groundBack - 4), Math.max(1, profile.groundFront - 1)]
    : null;
  // EMPTIED 2026-07-31, pending per-asset visual approval.
  //
  // Three ambient populations used to be drawn here: seven `⋈`/`⋊`
  // butterflies in daylight coloured `flower` and `gold`, `·`/`✦` fireflies
  // in the evening, and `·`/`.` winter drift. None of that art was ever
  // submitted for acceptance, and in the live capture the butterflies were
  // exactly what the operator had already rejected twice -- scattered
  // multicolour marks, sitting in the ground region rather than the sky.
  //
  // The band is computed above and left unused rather than deleted, and the
  // time-of-day and season branches are gone rather than commented out,
  // because a dead branch that still runs is how unapproved art returns by
  // accident. Restoring a population means drawing it, having that drawing
  // accepted under SPEC 7.10, and only then writing the code back.
  //
  // SPEC 7.8.4 does list ambience as required before the CATALOG is complete.
  // That is a catalog obligation, not a licence to ship unreviewed marks in
  // the default scene -- the same distinction 7.8.4 now records for fixtures.
  void lifeBand;
}


/**
 * The archived ambient-bird frames, exactly as deployed.
 *
 * `_AMBIENT_BIRD_FRAMES` / `_AMBIENT_BIRD_COMPACT_FRAMES` from the frozen
 * legacy viewer (blob 59dc49a820d07d1b6a1741e17aafe6d075f6c99d, lines
 * 566-567). The compact pair is what the deployed page shows below 60
 * columns; swapping frames by width is part of the accepted recipe, not a
 * candidate invention.
 */
export const AMBIENT_BIRD_FRAMES = Object.freeze(['\\v/', '_v_', '/v\\', '_v_']);
export const AMBIENT_BIRD_COMPACT_FRAMES = Object.freeze(['>-', '~>']);

/**
 * Sky life: the lifecycle's ambient-bird actors, painted from state alone.
 *
 * Reopened step 5: birds are no longer synthesized here from (worldId,
 * frame) -- they are ACTORS the presentation state advance spawns, steps and
 * retires under the deployed law (per-tick resampled 250+[0,350) threshold,
 * 28% flocks of 3-5, 0.42 cells a tick, winter gating SPAWNS only so a bird
 * mid-crossing at a season boundary finishes its crossing exactly as the
 * deployed page let it). This painter draws what the state says exists:
 * `Math.round` placement and the `floor(tick/frameStep)` wing cycle are the
 * deployed render lines (blob 59dc49a8, lines 1476-1498), and the muted
 * role is the deployed 'gray'.
 *
 * The clouds and one-cell distant-bird backdrop removed on 2026-08-01 stay
 * removed: nothing here paints them.
 *
 * @param raster    frame being painted
 * @param lifecycle `state.lifecycle` from the presentation advance; null
 *                  (no scene facts ever arrived) paints nothing
 * @param palette   active theme colours
 */
export function drawSkyLife(raster, lifecycle, palette) {
  if (!lifecycle) return;
  const ink = palette === NIGHT ? LEGACY_INK_NIGHT : LEGACY_INK_DAY;
  for (const actor of lifecycle.ambient ?? []) {
    if (actor.kind === 'firefly') {
      const cycle = actor.on + actor.off;
      if (lifecycle.tick % cycle >= actor.on) continue;
      raster.put(Math.round(actor.x), Math.round(actor.y), '*', ink.bright_yellow,
        true, null, { source: 'recipe.ambient.firefly' });
    }
  }
  for (const bird of lifecycle.birds) {
    const frames = bird.compact ? AMBIENT_BIRD_COMPACT_FRAMES : AMBIENT_BIRD_FRAMES;
    const wing = frames[Math.floor(Math.max(0, lifecycle.tick) / bird.frameStep) % frames.length];
    raster.text(Math.round(bird.x), Math.round(bird.y), wing, palette.dim, true, null,
      { source: 'recipe.ambient.bird_traversal' });
  }
}

/** Butterflies paint after canonical objects so their pond orbit stays visible. */
export function drawPondButterflies(raster, lifecycle, palette) {
  if (!lifecycle) return;
  const ink = palette === NIGHT ? LEGACY_INK_NIGHT : LEGACY_INK_DAY;
  const frames = ['><', '||', '><', '\\/'];
  for (const actor of lifecycle.ambient ?? []) {
    if (actor.kind !== 'butterfly') continue;
    const glyph = frames[Math.floor(Math.max(0, lifecycle.tick) / 6) % frames.length];
    raster.text(Math.round(actor.x), Math.round(actor.y), glyph,
      ink[actor.color] ?? ink.magenta, true, null,
      { source: 'recipe.ambient.butterfly' });
  }
}



/**
 * Weather: the lifecycle's particle actors and snow depth, painted from
 * state alone.
 *
 * Reopened step 5: the per-frame synthesis that stood here (positions
 * hashed from worldId and frame, invented splash/settle/cap densities) is
 * deleted. Every particle on screen is an actor the state advance spawned
 * under the deployed seasonal law and stepped under the deployed physics
 * (blob 59dc49a8, lines 947-1116): rain accelerates and breaks into
 * fragments on plants or splashes on the ground, snow sways by its own
 * phase and settles into a per-column depth map capped at 3, leaves tumble
 * through their three-glyph rotation and rest for 41 ticks. The paint here
 * is the deployed render pair: floor placement for particles, and the
 * accumulation piles rising from the ground line alternating glyphs on
 * (column + depth) % 3.
 *
 * The reactions report summarizes the state for tests and diagnostics; it
 * decides nothing.
 *
 * @param raster    frame being painted
 * @param lifecycle `state.lifecycle` from the presentation advance; null
 *                  paints nothing
 * @param palette   active theme colours
 * @returns counts: fragments, splashes, settledLeaves, snowColumns,
 *          snowDepthTotal
 */
export function drawWeather(raster, lifecycle, palette) {
  const reactions = {
    fragments: 0, splashes: 0, settledLeaves: 0,
    snowColumns: 0, snowDepthTotal: 0,
  };
  if (!lifecycle) return reactions;
  const colorOf = key =>
    key === 'rain' ? palette.water :
    key === 'bright_white' || key === 'white' ? palette.moon :
    key === 'autumn' ? palette.gold : palette.dim;
  const sourceOf = kind =>
    kind === 'rain' ? 'recipe.weather.rain' :
    kind === 'snow' ? 'recipe.weather.snow' :
    kind === 'frag' ? 'recipe.weather.rain_fragments' :
    kind === 'splash' ? 'recipe.weather.rain_splashes' :
    'recipe.weather.falling_leaves';
  for (const particle of lifecycle.particles) {
    raster.put(Math.floor(particle.x), Math.floor(particle.y), particle.glyph,
      colorOf(particle.color), true, null, { source: sourceOf(particle.kind) });
    if (particle.kind === 'frag') reactions.fragments += 1;
    else if (particle.kind === 'splash') reactions.splashes += 1;
    else if (particle.kind === 'leaf-rest') reactions.settledLeaves += 1;
  }
  // Accumulation piles: upward from the ground line, exactly the deployed
  // loop (blob lines 1105-1115).
  for (const [column, depth] of Object.entries(lifecycle.snowDepth)) {
    const c = Number(column);
    if (c < 0 || c >= raster.width || !depth) continue;
    reactions.snowColumns += 1;
    reactions.snowDepthTotal += depth;
    for (let d = 0; d < depth; d += 1) {
      const row = lifecycle.groundY - d;
      if (row < 0) continue;
      raster.put(c, row, (c + d) % 3 === 0 ? '*' : '.', palette.moon, true, null,
        { source: 'recipe.weather.snow_accumulation' });
    }
  }
  return reactions;
}


export function drawObject(raster, entry, projection, palette, season, view) {
  const { object } = entry, [x, y] = entry.anchor;
  const state = object.semantic_state ?? {};
  const hovered = view.hoverCell && rectContains(expandedRect(entry.hitRect, [3, 2]), view.hoverCell);
  // Pointer hover is the approved local response. Selection/focus must not
  // recolour an accepted picture or add anonymous ink: doing so made a click
  // visibly replace the mailbox flag and made the whole scene look unstable.
  const emphasized = Boolean(hovered);
  if (object.kind === 'plant') {
    const art = objectPresentationArt(
      object, view.visualFrame, entry.lod, emphasized,
    );
    // The plant's whole drawing -- foliage, organs and the canonical centre
    // glyph -- is one picture of one object, so every cell carries the same
    // identity: the grant-backed archive drawing when the archive draws this
    // species, and null (honest anonymity) for a placeholder awaiting review.
    const plantIdentity = { source: art.identity ?? null, objectId: object.object_id };
    raster.art(x, y, art.lines, paletteColor(palette, art.color, season),
      { animated: emphasized, accents: accentColors(art.accents, palette, season),
        source: plantIdentity.source, objectId: plantIdentity.objectId });
    // Exact operator-authored pictures are sealed compositions. The old path
    // painted procedural topology organs and a centre glyph over those bytes,
    // which is where the green `/@` beside the rose pot came from. A sealed
    // asset replaces that local painter; it is not a background for it.
    if (art.sealed) return;
    for (const organ of state.visible_organs ?? []) {
      const ox = clamp(Number(organ.offset?.[0] ?? 0), -3, 3);
      const oy = clamp(Number(organ.offset?.[1] ?? 0), 0, Math.max(0, art.lines.length - 1));
      raster.put(x + ox, y - oy,
        organGlyph(organ.kind, organ.glyph_family), paletteColor(palette, organ.kind === 'bloom' ? 'flower' : 'brightGreen', season),
        false, null, plantIdentity);
    }
    raster.put(x, y, glyphForProjection(object), paletteColor(palette, 'brightGreen', season),
      false, null, plantIdentity);
    return;
  }
  if (object.kind === 'animal') {
    const animalArt = objectPresentationArt(
      object, view.visualFrame, entry.lod, emphasized,
    );
    // Archived poses carry the grant identity; a placeholder pose carries
    // null, exactly like a placeholder plant.
    const animalIdentity = { source: animalArt.identity ?? null, objectId: object.object_id };
    raster.art(x, y, animalArt.lines, palette.creature,
      { animated: true, source: animalIdentity.source, objectId: animalIdentity.objectId });
    raster.put(x, y, glyphForProjection(object), palette.creature, true, null, animalIdentity);
    const memories = Number(state.recent_memories?.length ?? 0);
    // The memory dot is renderer-authored decoration: anonymous by intent.
    if (memories > 0) raster.put(x + 3, y - 2, memories > 2 ? '*' : '.', palette.flower, true);
    if (Number(state.bond_tier) > 0 && (projection.scene?.absence_summary ?? []).length) {
      raster.text(x - 1, y + 1, state.species_id === 'bird' ? 'v v' : state.species_id === 'turtle' ? '---' : '. .', palette.dim, true,
        null, { source: 'recipe.animal.absence_footprints', objectId: object.object_id });
    }
    return;
  }
  if (object.kind === 'fixture') {
    const catalog = String(state.catalog_id ?? 'fixture');
    const presentation = objectPresentationArt(
      object, view.visualFrame, entry.lod, emphasized,
    );
    const fixtureColor = emphasized ? 'gold' : presentation.color;
    // Accents SURVIVE focus. They used to be dropped while an object was
    // emphasized, on the reasoning that focus recolours the whole drawing and
    // a part keeping its own colour would look half-applied.
    //
    // That reasoning was backwards. An accent is not decoration: the `signal`
    // role means "this part is telling you something" -- the mailbox flag is
    // up because there is something in the mailbox. Suppressing it during
    // focus deletes that information at the exact moment the reader has
    // turned their attention to the object, which is the worst possible
    // moment to delete it. Focus is emphasis; it is not a repaint that
    // outranks meaning.
    const resolvedColor = paletteColor(palette, fixtureColor, season);
    const resolvedAccents = accentColors(presentation.accents, palette, season);
    const fixtureIdentity = { source: presentation.assetId ?? null, objectId: object.object_id };
    if (presentation.measured) {
      raster.measuredArt(
        object.object_id, x, y, presentation.lines, presentation.assetAnchor,
        resolvedColor, { animated: emphasized, accents: resolvedAccents,
          source: fixtureIdentity.source },
      );
    } else {
      // A fixture the atlas does not own is a placeholder: anonymous, like
      // every other drawing without an accepted identity to its name.
      raster.art(x, y, presentation.lines, resolvedColor, {
        animated: emphasized, accents: resolvedAccents,
        source: fixtureIdentity.source, objectId: fixtureIdentity.objectId,
      });
    }
    const renderCells = Array.isArray(state.render_cells) ? state.render_cells : [];
    for (const cell of renderCells) raster.put(x + Number(cell.dx ?? 0), y + Number(cell.dy ?? 0), glyphForProjection(object, {
      connectedMask: state.connected_group && state.presentation_state !== 'open' ? Number(cell.connected_mask ?? 0) : null,
    }), emphasized || state.presentation_state === 'on' ? palette.gold : palette.stone, emphasized,
    null, fixtureIdentity);
    return;
  }
  // Collectibles and unknown kinds: their tables are renderer-authored and
  // unreviewed, so the ink stays anonymous until atlas ownership arrives.
  raster.art(x, y, entry.art.lines,
    paletteColor(palette, emphasized ? 'flower' : entry.art.color, season),
    { animated: emphasized, objectId: object.object_id });
}
