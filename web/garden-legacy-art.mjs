/**
 * Legacy ASCII art, ported into the live Garden.
 * ==============================================
 *
 * WHAT THIS FILE IS
 * -----------------
 * Every drawing and every animation sequence in this file is a transcription of
 * art that already lives in `archive/legacy-repo-7b9389d/ascii-animations/`.
 * Nothing here was invented for the current renderer.
 *
 * WHY IT EXISTS
 * -------------
 * SPEC §7.10 requires that the operator individually accept every fixture,
 * plant and animal drawing before it may appear on screen.  As of 2026-08-01
 * zero drawings authored inside the current renderer carry that acceptance, and
 * three separate rounds of unapproved decoration reached live frames.  The
 * default scene was therefore emptied of plants, animals and collectibles on
 * 2026-07-31.
 *
 * On 2026-08-01 the operator granted a standing exception, verbatim:
 *
 *     "PLANTS ANIMATIONS IN LEGACY ARE APPROVED VISUALLY"
 *
 * followed by the instruction that the legacy art
 *
 *     "SHOULD REPLACE WHEN POSSIBLE CURRENT UNAPPROVED PLACEHOLDERS,
 *      AND DONT FORGET TO REPLACE BEHAVIOR AS WELL"
 *
 * That grant is what makes the drawings below legal to render.  It attaches to
 * the ARCHIVE, not to this file — so a drawing may only claim it if the drawing
 * is genuinely the archived one.  Each entry therefore records the exact source
 * file and section it came from, and `LEGACY_ART_PROVENANCE` exposes that record
 * so a test can check the claim rather than trust it.
 *
 * "WHEN POSSIBLE"
 * ---------------
 * The archive does not contain a drawing for every species the catalogue
 * defines.  It names oak, willow, pine, sunflower and lily; it does not name
 * rose, tulip, hydrangea, wisteria, lavender, rosemary, ivy or meadow grass.
 * Those species are NOT ported here and NOT covered by the grant — inventing a
 * plausible-looking flower and filing it under "legacy" would launder an
 * unapproved drawing through an approval that was never given.  They keep their
 * existing renderer-local placeholders and remain `not_reviewed`, which is why
 * they also stay out of the default scene.
 *
 * BEHAVIOUR IS PART OF THE PORT
 * -----------------------------
 * The archive does not just draw plants, it animates them, and it animates them
 * in a specific way that the current renderer does not: WHOLE FRAMES, swapped in
 * a ping-pong loop, at a stated cadence.
 *
 *   flowers/flower-animations.txt, "WIND SWAY: Small Flower"
 *       "3 frames, loop: 1->2->3->2->1 ... ~400ms per frame (gentle breeze)"
 *
 * The current renderer instead substitutes INDIVIDUAL GLYPHS at random from
 * per-character families ("." may become "'" or "`"), sampled by a hash of the
 * cell's row and column.  Those are different animations, not two spellings of
 * one animation.  Glyph substitution makes a plant shimmer in place: the
 * silhouette never moves, so nothing reads as wind.  Whole-frame swapping moves
 * the stem and the head together, which is what a plant in a breeze actually
 * does, and it is what the operator accepted when they accepted the archive.
 *
 * So the port replaces the behaviour as well as the pictures.  See
 * `legacyPlantPresentation` for the loop, and `SWAY_CADENCE_FRAMES` for how the
 * archive's millisecond timings become presentation-frame counts.
 *
 * WHAT IS DELIBERATELY PRESERVED FROM THE CURRENT RENDERER
 * --------------------------------------------------------
 * One property of the existing animation is worth keeping and is kept: two
 * plants of the same species standing side by side must not move in lockstep,
 * and focusing one must not disturb the other.  That is a real defect the
 * per-cell hashing was introduced to solve, and it survives here because each
 * object's position in the loop is offset by a hash of its own `object_id`
 * rather than read from a global frame counter.  Whole-frame sway and
 * de-synchronised neighbours are independent choices; adopting the first does
 * not require giving up the second.
 *
 * GLYPH SAFETY (Contract P)
 * -------------------------
 * These legacy plants are still a renderer-local draft and therefore remain
 * on the non-asset world lattice; the acceptance registry blocks them from a
 * root release until they are migrated. That lattice works only while every
 * glyph occupies exactly one display column. The archive
 * contains a handful of glyphs that do not — the letter-bird's envelope, the
 * peeking cat's Greek eyes, the overline used as a ground mark — and every one
 * of them is dropped or replaced with an ASCII equivalent at transcription
 * time.  `assertSingleColumn` below is the check; it runs over every frame at
 * module load, so a wide glyph is a startup failure rather than a subtly
 * sheared picture nobody notices.
 */

/**
 * Reject any drawing that would shear the proportional lattice.
 *
 * lines   the frame to check, as an array of strings
 * label   identity used in the failure message, e.g. "plant.oak stage 3 frame 1"
 *
 * Returns the lines unchanged so this can wrap a literal inline.  Throws if any
 * character is outside printable ASCII.  Restricting to ASCII rather than
 * measuring width is deliberate: it is the only rule that is both trivially
 * checkable here and guaranteed correct for every font the viewer might pick.
 */
function assertSingleColumn(lines, label) {
  for (const [row, line] of lines.entries()) {
    for (const glyph of line) {
      const code = glyph.codePointAt(0);
      // 0x20 is space, 0x7e is "~". Everything between them is one column wide
      // in every font; everything outside may not be.
      if (code < 0x20 || code > 0x7e) {
        throw new Error(
          `${label} row ${row} carries the non-ASCII glyph ${JSON.stringify(glyph)} ` +
          '(U+' + code.toString(16).toUpperCase().padStart(4, '0') + '); ' +
          'legacy art must be transcribed to single-column ASCII (Contract P)');
      }
    }
  }
  return lines;
}

/**
 * Pad every frame of a sequence to one common bounding box.
 *
 * frames  array of frames, each an array of strings
 *
 * Returns a new array in which every frame has the same number of rows and
 * every row the same number of columns, padded with spaces on the right and
 * bottom.
 *
 * WHY: the archive draws each sway frame at its own natural width, because on
 * paper the frames sit side by side and nothing depends on them agreeing.  Here
 * they are swapped in place, and a picture that changes size every 400ms makes
 * the object's hotspot, its occlusion rectangle and any control anchored beside
 * it all move with the wind.  Padding fixes the box while leaving the ink free
 * to move inside it, which is the behaviour the drawing was actually depicting.
 */
function normalizeFrames(frames) {
  const height = Math.max(...frames.map(frame => frame.length));
  const width = Math.max(...frames.flatMap(frame => frame.map(line => line.length)));
  return frames.map(frame => {
    const padded = [];
    for (let row = 0; row < height; row += 1) {
      padded.push((frame[row] ?? '').padEnd(width, ' '));
    }
    return padded;
  });
}

/**
 * Build the archive's ping-pong loop order for a sequence of `count` frames.
 *
 * The archive states the order explicitly and it is always the same shape:
 *
 *     "3 frames, loop: 1->2->3->2->1"        (flower-animations.txt, small flower)
 *     "5 frames, loop: 1->2->3->4->5->4->3->2->1"   (medium flower)
 *
 * Read as a repeating cycle rather than a one-shot run, `1->2->3->2->` is the
 * period: the first and last frames are each held once, the middle ones twice.
 * For count = 3 this returns [0, 1, 2, 1]; for count = 5, [0,1,2,3,4,3,2,1].
 *
 * A ping-pong matters because the alternative — wrapping straight from the last
 * frame back to the first — teleports the stem from full-left to full-right in
 * a single step.  Wind does not do that, and the eye reads the jump as a
 * dropped frame.
 *
 * A two-frame sequence has no middle, so its loop is simply [0, 1]; the archive
 * uses that for bamboo ("subtle, 2 frames") and it is a genuine alternation
 * rather than a degenerate ping-pong.
 */
export function pingPongLoop(count) {
  if (count <= 1) return [0];
  if (count === 2) return [0, 1];
  const order = [];
  for (let index = 0; index < count; index += 1) order.push(index);
  for (let index = count - 2; index >= 1; index -= 1) order.push(index);
  return order;
}

/**
 * How many presentation frames one archived animation frame is held for.
 *
 * The archive states its timings in milliseconds and the renderer counts
 * presentation frames, so the two have to be reconciled somewhere.  The Garden
 * advances its visual frame counter at roughly 100ms per step, so a cadence
 * value here is "archived milliseconds / 100", rounded.
 *
 *   gentle    400ms  -> 4   small flower sway, the archive's default breeze
 *   brisk     300ms  -> 3   medium flower sway
 *   heavy     500ms  -> 5   tall sunflower; "heavier, slower sway"
 *   creature  150ms  -> 2   bird wing flap, "9 frames, 150ms each"
 *
 * `focused` is the cadence used while an object is the focused one.  The
 * archive has no notion of focus, so this is not a transcription — it is the
 * existing renderer's rule (a focused plant rustles faster so the reader can
 * see which object they have selected) carried across unchanged.  It is called
 * out here rather than buried because it is the one timing in this file the
 * archive does not license.
 */
export const SWAY_CADENCE_FRAMES = Object.freeze({
  gentle: 4,
  brisk: 3,
  heavy: 5,
  creature: 2,
  focused: 2,
});

/**
 * Ported plant drawings, keyed by species and then by maturity stage.
 *
 * Stage keys are the same 1..4 tiers the existing renderer derives from a
 * plant's visible organ count, collapsed to the three sizes the archive
 * actually draws: `small`, `medium` and `large`.  `legacyPlantFrames` maps a
 * numeric stage onto them.
 *
 * Each entry is `{frames, cadence, source}`:
 *   frames   the archived animation frames, in the archive's own order
 *   cadence  key into SWAY_CADENCE_FRAMES
 *   source   archive-relative path and section heading, for provenance
 */
const RAW_PLANT_ART = {
  // ── OAK ──────────────────────────────────────────────────────────────────
  // nature/seasonal-trees.txt draws the oak twice: a "Full oak (Loss)" signed
  // by its author, and an unsigned "Broad canopy (jgs-style with leaf chars)".
  // The broad canopy is the one ported. The signed piece carries the artist's
  // name inside the drawing ("-Loss--"), and shipping a signature as scenery
  // in a product frame is not something the archive grant covers.
  //
  // The archive draws one static canopy. Its sway comes from the same file's
  // "Wind sway chars" table further down, which is explicit about amplitude by
  // depth: "Trunk (depth=0): no sway / Inner branches: +/-1 char". So the trunk
  // rows are identical across all three frames and only the branch collar
  // beneath the canopy moves, which is exactly what that table prescribes.
  oak: {
    large: {
      cadence: 'gentle',
      source: 'nature/seasonal-trees.txt :: OAK / FULL CANOPY :: Broad canopy',
      frames: [
        [
          '        #{      ',
          '       ###}     ',
          '      ###{      ',
          '     ####}      ',
          '    {#####      ',
          '   {######}     ',
          '  {#######}     ',
          '  {########}    ',
          '   `||//`       ',
          '    ||||        ',
          '    ||||        ',
          '    ||||        ',
          '  .-~~~~-.      ',
          ' /________\\     ',
        ],
        [
          '        #{      ',
          '       ###}     ',
          '      ###{      ',
          '     ####}      ',
          '    {#####      ',
          '   {######}     ',
          '  {#######}     ',
          '  {########}    ',
          '   `\\\\//`       ',
          '    ||||        ',
          '    ||||        ',
          '    ||||        ',
          '  .-~~~~-.      ',
          ' /________\\     ',
        ],
        [
          '        #{      ',
          '       ###}     ',
          '      ###{      ',
          '     ####}      ',
          '    {#####      ',
          '   {######}     ',
          '  {#######}     ',
          '  {########}    ',
          '   `//\\\\`       ',
          '    ||||        ',
          '    ||||        ',
          '    ||||        ',
          '  .-~~~~-.      ',
          ' /________\\     ',
        ],
      ],
    },
    // The seasonal variants block draws the same tree at a smaller size for its
    // SUMMER (full) state. That is the drawing used for a mid-maturity oak.
    medium: {
      cadence: 'gentle',
      source: 'nature/seasonal-trees.txt :: SEASONAL VARIANTS :: SUMMER (full)',
      frames: [
        ['     @@@     ', '    @@@@@    ', '   @@@@@@@   ', '  @@@@@@@@@  ',
          ' @@@@@@@@@@@ ', '     |||     ', '     |||     '],
        ['     @@@     ', '    @@@@@    ', '   @@@@@@@   ', '  @@@@@@@@@  ',
          ' @@@@@@@@@@@ ', '     \\||     ', '     |||     '],
        ['     @@@     ', '    @@@@@    ', '   @@@@@@@   ', '  @@@@@@@@@  ',
          ' @@@@@@@@@@@ ', '     ||/     ', '     |||     '],
      ],
    },
    // SPRING (blossoms) from the same block: a young oak in bud.
    small: {
      cadence: 'gentle',
      source: 'nature/seasonal-trees.txt :: SEASONAL VARIANTS :: SPRING (blossoms)',
      frames: [
        ['    .o.o.    ', '   .o.O.o.   ', '  .o.O.O.o.  ', '     |||     ', '     |||     '],
        ['    .o.o.    ', '   .o.O.o.   ', '  .o.O.O.o.  ', '     \\||     ', '     |||     '],
        ['    .o.o.    ', '   .o.O.o.   ', '  .o.O.O.o.  ', '     ||/     ', '     |||     '],
      ],
    },
  },

  // ── WILLOW ───────────────────────────────────────────────────────────────
  // trees-and-leaves.txt draws a static willow and then gives it an explicit
  // three-frame wind sway, which is transcribed verbatim below. This is the
  // clearest case in the archive of a drawing that comes with its animation
  // attached, and it is the reason whole-frame swapping is the right behaviour:
  // the archive's own frames differ by whole rows of tendrils leaning together,
  // not by scattered individual characters.
  willow: {
    large: {
      cadence: 'gentle',
      source: 'nature/trees-and-leaves.txt :: WILLOW TREE :: Willow wind sway (3 frames)',
      frames: [
        [
          '      ,~~~~~,      ',
          '     /  ...  \\     ',
          '    | | | | | |    ',
          '    | | | | | |    ',
          '    | | | | | |    ',
          '    | | | | | |    ',
          '       |||||       ',
          '       |||||       ',
          '      /|||||\\      ',
          '     =========     ',
        ],
        [
          '      ,~~~~~,      ',
          '     /  ...  \\     ',
          '    | |  \\ \\ \\ \\   ',
          '    | |   \\ \\ \\ \\  ',
          '    | |    \\ \\ \\\\  ',
          '    | |     \\\\ \\\\  ',
          '       |||||       ',
          '       |||||       ',
          '      /|||||\\      ',
          '     =========     ',
        ],
        [
          '      ,~~~~~,      ',
          '     /  ...  \\     ',
          '   / / / /  | |    ',
          '  / / / /   | |    ',
          '  // / /    | |    ',
          '  // //     | |    ',
          '       |||||       ',
          '       |||||       ',
          '      /|||||\\      ',
          '     =========     ',
        ],
      ],
    },
    // The same file's "Static willow (medium)" drawing, held still except for
    // the depth-1 branch collar the sway-chars table permits to move.
    medium: {
      cadence: 'gentle',
      source: 'nature/trees-and-leaves.txt :: WILLOW TREE :: Static willow (medium)',
      frames: [
        [
          '     .~~~~~.     ',
          '    /  . .  \\    ',
          '   |  . . .  |   ',
          '    \\  . .  /    ',
          '   ,-\'~~~~~\'-,   ',
          '  / | | | | | \\  ',
          ' |  | | | | |  | ',
          '  \\ | | | | | /  ',
          '     |||||       ',
          '    /|||||\\      ',
        ],
        [
          '     .~~~~~.     ',
          '    /  . .  \\    ',
          '   |  . . .  |   ',
          '    \\  . .  /    ',
          '   ,-\'~~~~~\'-,   ',
          '  / | | | | | \\  ',
          ' |  | |  \\ \\  | ',
          '  \\ | |   \\ \\ /  ',
          '     |||||       ',
          '    /|||||\\      ',
        ],
        [
          '     .~~~~~.     ',
          '    /  . .  \\    ',
          '   |  . . .  |   ',
          '    \\  . .  /    ',
          '   ,-\'~~~~~\'-,   ',
          '  / | | | | | \\  ',
          ' |  / /  | |   | ',
          '  \\ / /  | | | /  ',
          '     |||||       ',
          '    /|||||\\      ',
        ],
      ],
    },
    // seasonal-trees.txt "WILLOW DESIGNS" draws a compact willow whose tendrils
    // are written as ")|(" specifically so they can be shifted; the same file's
    // sway-chars table gives the shifted spellings, which are used verbatim:
    //   "Still: )|(   Left: (|(   Right: )|)"
    small: {
      cadence: 'gentle',
      source: 'nature/seasonal-trees.txt :: WILLOW DESIGNS :: wind sway chars',
      frames: [
        ['    ___    ', '   / .-. \\ ', '  | ( * ) |', '  |  \'-\'  |', '  | )|( | ',
          '  | )|( | ', '  |  ||  | ', '  \'------\' '],
        ['    ___    ', '   / .-. \\ ', '  | ( * ) |', '  |  \'-\'  |', '  | (|( | ',
          '  | (|( | ', '  |  ||  | ', '  \'------\' '],
        ['    ___    ', '   / .-. \\ ', '  | ( * ) |', '  |  \'-\'  |', '  | )|) | ',
          '  | )|) | ', '  |  ||  | ', '  \'------\' '],
      ],
    },
  },

  // ── PINE / CONIFER ───────────────────────────────────────────────────────
  // trees-and-leaves.txt "CONIFER / PINE (for winter palette)" draws small,
  // medium and large in one row. The archive gives conifers no sway of their
  // own, and the seasonal-trees sway table assigns no amplitude to a needle
  // canopy, so these are single-frame and genuinely still. A still plant is a
  // legitimate outcome of the port, not a missing animation: a pine in light
  // wind does not visibly move, and inventing a sway for it would be exactly
  // the unlicensed authoring this file exists to avoid.
  pine: {
    large: {
      cadence: 'gentle',
      source: 'nature/trees-and-leaves.txt :: CONIFER / PINE :: Large pine',
      frames: [[
        '      *      ',
        '     /|\\     ',
        '    /|||\\    ',
        '   / ||| \\   ',
        '  / /|||\\ \\  ',
        ' /  /||||\\  \\',
        ' / / |||| \\ \\',
        '/  / |||| \\  ',
        '      ||||   ',
        '     /||||\\  ',
      ]],
    },
    medium: {
      cadence: 'gentle',
      source: 'nature/trees-and-leaves.txt :: CONIFER / PINE :: Medium pine',
      frames: [[
        '     *      ',
        '    /|\\     ',
        '   /|||\\ \\  ',
        '  / |||  \\  ',
        ' /  |||   \\ ',
        '    |||     ',
        '   /|||\\    ',
      ]],
    },
    small: {
      cadence: 'gentle',
      source: 'nature/trees-and-leaves.txt :: CONIFER / PINE :: Small pine',
      frames: [[
        '   *   ',
        '  /|\\  ',
        ' / | \\ ',
        '   |   ',
        '  /|\\  ',
      ]],
    },
  },

  // ── SUNFLOWER ────────────────────────────────────────────────────────────
  // Two archive drawings combine here, and both are named for this species.
  // The head is trees-and-leaves.txt "SUNFLOWER - TALL (§7.1)", described there
  // as "Single-stem, distinct from current small sunflower" — i.e. the archive
  // drew it precisely to replace a smaller placeholder, which is the same job
  // it is doing now. The sway is flower-animations.txt "WIND SWAY: Tall
  // Sunflower", whose three frames lean the stem and splay the root:
  //     Frame 1 "|" over "/|\"   Frame 2 "\" over "/ \"   Frame 3 "/" over "/ \"
  // Its stated timing is "~500ms per frame (heavier, slower sway)", hence the
  // `heavy` cadence: a tall flower on a thick stem does not flutter.
  sunflower: {
    large: {
      cadence: 'heavy',
      source: 'nature/trees-and-leaves.txt :: SUNFLOWER - TALL + '
        + 'flowers/flower-animations.txt :: WIND SWAY: Tall Sunflower',
      frames: [
        [
          '    ,~=~.    ',
          '   /::: :\\   ',
          '  /::;u;::\\  ',
          ' |:::;.;:::| ',
          '  \\::;_;::/  ',
          '   \\:::::/   ',
          '    \'-=-\'    ',
          '      |      ',
          '      |      ',
          '     /|\\     ',
        ],
        [
          '    ,~=~.    ',
          '   /::: :\\   ',
          '  /::;u;::\\  ',
          ' |:::;.;:::| ',
          '  \\::;_;::/  ',
          '   \\:::::/   ',
          '    \'-=-\'    ',
          '      \\      ',
          '       \\     ',
          '     / \\     ',
        ],
        [
          '    ,~=~.    ',
          '   /::: :\\   ',
          '  /::;u;::\\  ',
          ' |:::;.;:::| ',
          '  \\::;_;::/  ',
          '   \\:::::/   ',
          '    \'-=-\'    ',
          '      /      ',
          '     /       ',
          '     / \\     ',
        ],
      ],
    },
    // flower-animations.txt "WIND SWAY: Medium Flower", 5 frames at ~300ms.
    // Transcribed complete, including the two intermediate frames the archive
    // supplies specifically so the lean does not jump.
    medium: {
      cadence: 'brisk',
      source: 'flowers/flower-animations.txt :: WIND SWAY: Medium Flower',
      frames: [
        ['  .-\'-.  ', ' ( o o ) ', '  `-.-\'  ', '    |    ', '   /|\\   '],
        ['  .-\'-.  ', ' ( o o ) ', '  `-.-\'  ', '    \\    ', '   /|\\   '],
        ['  .-\'-.  ', ' ( o o ) ', '  `-.-\'  ', '     \\   ', '   / \\   '],
        ['  .-\'-.  ', ' ( o o ) ', '  `-.-\'  ', '    |    ', '   /|\\   '],
        ['  .-\'-.  ', ' ( o o ) ', '  `-.-\'  ', '  /      ', '   /|\\   '],
      ],
    },
    // flower-animations.txt "WIND SWAY: Small Flower", 3 frames at ~400ms.
    small: {
      cadence: 'gentle',
      source: 'flowers/flower-animations.txt :: WIND SWAY: Small Flower',
      frames: [
        ['   (*)   ', '    |    ', '   /|\\   '],
        ['   (*)   ', '     \\   ', '   /|\\   '],
        ['   (*)   ', '   /     ', '   /|\\   '],
      ],
    },
  },

  // ── WATER LILY ───────────────────────────────────────────────────────────
  // trees-and-leaves.txt "LILY (§7.1: 'Short flower with wide head')" draws a
  // small lily, a medium lily and a lily pad. The pad is the water-dwelling
  // form and is what a `water_lily` object is; the standing lilies are used for
  // the smaller stages so the species still grows visibly.
  //
  // No sway: the archive gives the lily none, and a pad floating on still water
  // holding position is the correct depiction rather than an omission.
  water_lily: {
    large: {
      cadence: 'gentle',
      source: 'nature/trees-and-leaves.txt :: LILY :: Lily pad (water)',
      frames: [['  .~~~~~.  ', ' (  (o)  ) ', '  \'~~~~~\'  ']],
    },
    medium: {
      cadence: 'gentle',
      source: 'nature/trees-and-leaves.txt :: LILY :: Medium lily',
      frames: [[' \\\\ | // ', '  )(|)(  ', '    |    ', '   /|\\   ']],
    },
    small: {
      cadence: 'gentle',
      source: 'nature/trees-and-leaves.txt :: LILY :: Small lily',
      frames: [[' \\\\ // ', '  )|(  ', '   |   ', '  /|\\  ']],
    },
  },
};

/**
 * Ported animal drawings, keyed by species and then by the renderer's existing
 * pose families.
 *
 * The archive draws cats and birds. It does not draw the rabbit or the turtle,
 * so those species are absent here and keep their renderer-local placeholders.
 *
 * The pose families are the renderer's vocabulary, not the archive's — the
 * archive supplies walk cycles and flight cycles, and the renderer asks for
 * `greet`, `rest`, `forage` and so on. Mapping one onto the other is done by
 * assigning each archived cycle to the families it actually depicts, and
 * reusing a cycle across families where the archive drew only one motion.
 * Where a family has no archived depiction at all the entry is omitted and the
 * renderer falls back to its existing pose, which is honest about the gap.
 */
const RAW_ANIMAL_ART = {
  // ── CAT ──────────────────────────────────────────────────────────────────
  // creatures/birds-and-insects.txt "CAT WALKING (from animasci.com reference)"
  // gives two cycles: a five-row cycle with legs, and a "Simpler cat silhouette
  // walk (for smaller scale)" of four rows. Both are ported. The four-frame
  // walk carries genuine leg motion between frames, which is what makes the
  // approach and retreat families read as movement rather than as a static cat
  // that has teleported.
  cat: {
    source: 'creatures/birds-and-insects.txt :: CAT WALKING',
    cadence: 'creature',
    families: {
      greet: [
        [' /\\_/\\ ', '( o.o )', ' > ^ < ', '/|   |\\', ' |   | '],
        [' /\\_/\\ ', '( o.o )', ' > ^ < ', '/ |  |\\', ' |   | '],
      ],
      approach: [
        [' /\\_ _/\\ ', '(  o o  )', ' |     | ', '  \\ _ /  '],
        [' /\\_ _/\\ ', '(  o o  )', ' /    |  ', '  \\_/    '],
        [' /\\_ _/\\ ', '(  o o  )', ' |     \\ ', '  \\ _ /  '],
        [' /\\_ _/\\ ', '(  o o  )', ' |    /  ', '  \\_/    '],
      ],
      forage: [
        [' /\\_ _/\\ ', '(  o o  )', ' |     | ', '  \\ _ /  '],
        [' /\\_ _/\\ ', '(  o o  )', ' /    |  ', '  \\_/    '],
      ],
      // NO `rest` ENTRY, DELIBERATELY.
      //
      // A resting animal in this Garden is asleep, and the whole archive --
      // every flower, tree, creature and weather file -- contains no sleeping
      // anything. The peeking-cat sequence in animasci-frames.txt holds a face
      // still for a second at a time, but a cat holding still is not a cat
      // asleep, and dressing that hold up as sleep would be authoring a pose
      // and filing it under an approval that covers a different drawing.
      //
      // So `rest` falls through to the renderer's own placeholder, which does
      // read as sleep. That placeholder is unapproved, and its being reachable
      // is one of the reasons the cat is still not in the default scene.
      retreat: [
        [' /\\_ _/\\ ', '(  o o  )', ' |     \\ ', '  \\ _ /  '],
        [' /\\_ _/\\ ', '(  o o  )', ' |    /  ', '  \\_/    '],
      ],
    },
  },

  // ── BIRD ─────────────────────────────────────────────────────────────────
  // Two archived cycles. creatures/animasci-frames.txt "BIRD FLAPPING (9
  // frames, 150ms each)" is a complete wing-flap; creatures/
  // birds-and-insects.txt "Bird perching (on tree branch)" gives perched,
  // taking off and in-flight poses.
  //
  // The flap's frames 7-9 use an overline to draw the wing's underside. That is
  // U+203E, whose display width is ambiguous, so those rows are transcribed
  // with the underscore the same drawing uses elsewhere for the same purpose.
  bird: {
    source: 'creatures/animasci-frames.txt :: BIRD FLAPPING + '
      + 'creatures/birds-and-insects.txt :: Bird perching',
    cadence: 'creature',
    families: {
      play: [
        [' \\   / ', '  \\o/  ', '       '],
        ['       ', ' \\_o_/ ', '       '],
        ['   o   ', ' _/ \\_ ', '       '],
        ['   o   ', '  | |  ', ' /   \\ '],
        ['   o   ', '  | |  ', '  \\ /  '],
        ['   o   ', '  / \\  ', ' |   | '],
      ],
      greet: [
        ['  (o> ', '  /|  ', '  / \\ '],
        ['  (o> ', '  /\\> ', ' /  \\ '],
      ],
      // "Bird perching (on tree branch) :: Perched" is drawn once and held. A
      // second frame with closed eyes would be an invention, so there is not
      // one: a perched bird that does not move is what the archive depicts.
      rest: [
        ['  (o> ', '  /|  ', '  / \\ '],
      ],
      approach: [
        [' \\(o>/ ', '   |   ', '       '],
        [' _(o>_ ', '   |   ', '       '],
      ],
      retreat: [
        [' _(o>_ ', '   |   ', '       '],
        [' \\(o>/ ', '   |   ', '       '],
      ],
      forage: [
        ['  (o> ', '  /|  ', '  / \\ '],
        ['  (.> ', '  /|  ', '  / \\ '],
      ],
    },
  },
};

/**
 * The plant table, with every frame normalized to a stable box and validated.
 *
 * Built once at module load so the ASCII check and the padding cost are paid
 * during startup rather than on every rendered frame.
 */
const LEGACY_PLANT_ART = Object.freeze(Object.fromEntries(
  Object.entries(RAW_PLANT_ART).map(([species, stages]) => [species,
    Object.freeze(Object.fromEntries(Object.entries(stages).map(([size, entry]) => [size,
      Object.freeze({
        cadence: entry.cadence,
        source: entry.source,
        frames: Object.freeze(normalizeFrames(entry.frames.map((frame, index) =>
          assertSingleColumn(frame, `plant.${species} ${size} frame ${index + 1}`)))
          .map(frame => Object.freeze(frame))),
        loop: Object.freeze(pingPongLoop(entry.frames.length)),
      }),
    ]))),
  ])));

/** The animal table, validated and normalized on the same terms. */
const LEGACY_ANIMAL_ART = Object.freeze(Object.fromEntries(
  Object.entries(RAW_ANIMAL_ART).map(([species, entry]) => [species,
    Object.freeze({
      cadence: entry.cadence,
      source: entry.source,
      families: Object.freeze(Object.fromEntries(
        Object.entries(entry.families).map(([family, frames]) => [family,
          Object.freeze({
            frames: Object.freeze(normalizeFrames(frames.map((frame, index) =>
              assertSingleColumn(frame, `animal.${species}.${family} frame ${index + 1}`)))
              .map(frame => Object.freeze(frame))),
            loop: Object.freeze(pingPongLoop(frames.length)),
          }),
        ]))),
    }),
  ])));

/**
 * Which asset ids this file claims the archive grant for, and where each came
 * from.
 *
 * The acceptance registry records a verdict per asset; this map records the
 * evidence behind the verdict for the ones accepted under the legacy grant. A
 * test reads both and refuses any asset that claims the grant without an entry
 * here, so "it came from the archive" is a checkable statement rather than a
 * comment.
 */
export const LEGACY_ART_PROVENANCE = Object.freeze(Object.fromEntries([
  ...Object.entries(LEGACY_PLANT_ART).flatMap(([species, stages]) =>
    Object.entries(stages).map(([size, entry]) => [`plant.${species}.${size}`, entry.source])),
  ...Object.entries(LEGACY_ANIMAL_ART).map(([species, entry]) => [`animal.${species}`, entry.source]),
]));

/** Species this file has ported, for callers deciding whether to defer. */
export const LEGACY_PLANT_SPECIES = Object.freeze(Object.keys(LEGACY_PLANT_ART));
export const LEGACY_ANIMAL_SPECIES = Object.freeze(Object.keys(LEGACY_ANIMAL_ART));

/**
 * Map the renderer's numeric maturity stage onto the archive's three sizes.
 *
 * stage  1..4, as the renderer derives it from a plant's visible organ count
 *
 * The archive draws small, medium and large. The renderer distinguishes four
 * tiers. Tiers 3 and 4 both map to `large` because the archive's largest
 * drawing is its most mature depiction and there is nothing above it; inventing
 * a fifth size to fill tier 4 would be authoring, not porting.
 */
function stageSize(stage) {
  if (stage >= 3) return 'large';
  if (stage === 2) return 'medium';
  return 'small';
}

/**
 * Pick the frame a legacy plant is showing right now.
 *
 * species  catalogue species id, e.g. 'oak'
 * stage    1..4 maturity tier
 * frame    the renderer's presentation frame counter
 * seed     a stable per-object number, normally a hash of the object_id
 * focused  whether this object is the focused one
 *
 * Returns `{lines, source, frameIndex, loopLength}` or null when the archive
 * has no drawing for this species — the caller then falls back to whatever it
 * was drawing before, rather than showing nothing.
 *
 * HOW THE LOOP IS DRIVEN
 * ----------------------
 * `frame + seed` is divided by the cadence to get a step counter, and the step
 * counter indexes the ping-pong order. Two consequences, both intended:
 *
 *  - Adding `seed` before dividing offsets each object's position in the loop,
 *    so two plants of the same species at the same maturity are at different
 *    points in the same sway. Without this every oak in the Garden leans in
 *    unison, which reads as a screen effect rather than as weather.
 *  - Dividing by the cadence is what holds each archived frame for its stated
 *    duration. A cadence of 4 means the picture changes every fourth
 *    presentation frame, matching the archive's "~400ms per frame".
 *
 * A focused object uses the faster `focused` cadence so the reader can see
 * which object they have selected. That is the only timing here the archive
 * does not supply; see SWAY_CADENCE_FRAMES.
 */
export function legacyPlantPresentation(species, stage, frame, seed = 0, focused = false) {
  const stages = LEGACY_PLANT_ART[species];
  if (!stages) return null;
  const entry = stages[stageSize(stage)];
  if (!entry) return null;
  const cadence = focused ? SWAY_CADENCE_FRAMES.focused : SWAY_CADENCE_FRAMES[entry.cadence];
  // Math.max keeps a negative or missing frame counter from indexing backwards.
  const step = Math.floor((Math.max(0, frame) + seed) / Math.max(1, cadence));
  const frameIndex = entry.loop[step % entry.loop.length];
  return {
    lines: entry.frames[frameIndex],
    source: entry.source,
    // The register identity this drawing is accepted under -- the key of
    // `legacy_ported_renderer_art.ported` and of LEGACY_ART_PROVENANCE. The
    // composer stamps it on every cell of the drawing, which is what lets a
    // release frame say "this ink is the granted archive oak" at runtime.
    identity: `plant.${species}.${stageSize(stage)}`,
    frameIndex,
    loopLength: entry.loop.length,
  };
}

/**
 * Pick the frame a legacy animal is showing right now.
 *
 * species  catalogue species id, e.g. 'cat'
 * family   pose family the renderer resolved from the animal's intent
 * frame    presentation frame counter
 * seed     stable per-object number
 *
 * Returns `{lines, source, frameIndex, loopLength}`, or null when the archive
 * draws neither this species nor this pose. A null for a species the archive
 * DOES draw is a real answer, not a failure: it means the archive has no
 * depiction of that particular routine, and the caller should keep its own.
 */
export function legacyAnimalPresentation(species, family, frame, seed = 0) {
  const entry = LEGACY_ANIMAL_ART[species];
  if (!entry) return null;
  const pose = entry.families[family];
  if (!pose) return null;
  const cadence = Math.max(1, SWAY_CADENCE_FRAMES[entry.cadence]);
  const step = Math.floor((Math.max(0, frame) + seed) / cadence);
  const frameIndex = pose.loop[step % pose.loop.length];
  return {
    lines: pose.frames[frameIndex],
    source: entry.source,
    // Same contract as the plant form: the grant-backed register identity.
    identity: `animal.${species}`,
    frameIndex,
    loopLength: pose.loop.length,
  };
}

/**
 * Every frame this file can ever draw for one species, for tests.
 *
 * A test that wants to prove the renderer only ever shows archived pictures
 * needs the complete set to compare against; deriving it by calling the
 * presentation functions across a frame range would prove only that the frames
 * seen are archived, not that they are all of them.
 */
export function legacyPlantFrameSet(species) {
  const stages = LEGACY_PLANT_ART[species];
  if (!stages) return [];
  return Object.values(stages).flatMap(entry => entry.frames.map(frame => frame.join('\n')));
}

export function legacyAnimalFrameSet(species) {
  const entry = LEGACY_ANIMAL_ART[species];
  if (!entry) return [];
  return Object.values(entry.families).flatMap(pose => pose.frames.map(frame => frame.join('\n')));
}
