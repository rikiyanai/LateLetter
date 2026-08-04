"""Structural stroke graphs and profile stylizations for the Garden's fixtures.

WHAT CHANGED IN ROUND 2, AND WHY
--------------------------------
Round 1 drew each fixture twice, by hand, once per profile. The operator
rejected most of them, and `docs/FAILURE_LOG.md` records the rule that came out
of that: a fixture needs a canonical **structural stroke graph** and its
material/affordance facts BEFORE either profile chooses glyphs. The two
profiles may stylize that graph differently; they must not invent two different
objects.

That rule comes from the FL-4512 bibliography, in particular Bénard et al.'s
*Active Strokes*, which keeps persistent curve topology and correspondence
separate from the later stylization path. FL-4208 supplies the evaluation
axes -- density, directional axis, openness, stroke continuity, terminal shape,
interior voids, baseline anchoring, survival at gameplay scale, and neighbour
composability -- with the depicted object, not the glyph, remaining the owner.

So every fixture below declares `structure` first: the named parts that make it
that object, in the order they stack. Both profiles then realise those same
parts. A test asserts the two profiles agree on row count and that a structure
is declared, so a profile cannot quietly drift into drawing something else.

HISTORICAL REVIEW RECEIPTS, NOT CURRENT RELEASE VERDICTS
--------------------------------------------------------
Round 4 recorded all ten fixtures as reading in the old rendering contract.
Those words remain useful provenance, but Contract P changed the acceptance
surface and `docs/garden-asset-acceptance.json` withdrew the verdicts. The
drawings below are therefore review candidates, not accepted product assets.

What each round actually cost, because the shape of it is the useful part:

  * Round 1 -- nine of ten rejected. The cause was an idiom, not detail: every
    drawing was a sealed rectangle with strokes inside it, which is a schematic
    diagram convention the supplied references never use.
  * Round 2 -- rejected on the proportional profile in four places, reported as
    "offset" and "unreadable". The cause was mechanical, not aesthetic: rows
    authored by eye had different display widths, and one double-width glyph
    shifted the rest of its row. Addressed by DERIVING the proportional profile
    from the ascii columns rather than drawing it twice.
  * Round 3 -- seven accepted. The three rejections were the last of the boxed
    idiom (bridge), a proportional-only side-bearing defect (lantern), and a
    solid band of ripples that read as a texture fill (pond).
  * Round 4 -- all ten read on the historical review surface.

The through-line: every complaint that sounded like taste had a cause that could
be stated mechanically, and two of them were invisible in the ascii-safe profile
entirely. None of them would have been found by looking harder at the art.

THE STANDING CORRECTIONS
------------------------
Three rules were extracted from earlier rounds and still bind every drawing
here. BIGGER WAS WRONG: the failure log had recorded reference art at 30-90
columns and treated small size as a defect, but the operator's own reference for
the mailbox is about seven columns and calls the wider ones too wide. Density at
small size is the target, not scale. ISOMETRIC IS OUT, so every fixture stays in
flat elevation. And OUTLINED BOXES ARE OUT -- the round-1 rejects all drew a
sealed rectangle and put strokes inside it, which is an icon idiom the supplied
references never use; the bridge was the last fixture still doing it.
"""

from __future__ import annotations

from typing import Any


def _aligned_proportional(rows: tuple[str, ...], name: str) -> tuple[str, ...]:
    """Verify a proportional drawing cannot render misaligned, and pad it square.

    WHY THIS CHECK EXISTS
    ---------------------
    Round 2 was rejected on the proportional profile for exactly one reason,
    repeated across four fixtures: "offset", "bad/unreadable", "ascii safe
    better". The cause was not taste. Two mechanical faults produced all of it.

    First, RAGGED WIDTH. The rows of a drawing were authored by eye and ended
    up different display widths -- bench `[8,9,8,8]`, pond `[8,13,8]`. The one
    fixture accepted in round 1, trellis, is the only one whose rows were all
    equal. A drawing whose rows disagree on width cannot line up vertically, so
    every stroke that should have been continuous is broken.

    Second, DOUBLE-WIDTH GLYPHS. `\u301c` occupies two columns, not one, so a
    single one of them shifts the entire remainder of its row sideways. The
    Shift_JIS repertoire is full of these, and they are legitimate in art that
    accounts for them -- but they must be counted, never assumed narrow.

    Both are now rejected at authoring time rather than discovered at review.
    `wcswidth` measures the display width the way a terminal does, which is the
    right ruler here: the proportional profile is stylization of a shared
    structure, and a structure whose rows do not align is not that structure.

    :param rows: The proportional drawing, one string per row.
    :param name: Catalog id, for error messages.
    :returns: The rows padded to a common display width.
    :raises ValueError: On a double-width glyph, which cannot be padded around.
    """
    from wcwidth import wcswidth

    for row in rows:
        for char in row:
            if char != " " and wcswidth(char) != 1:
                raise ValueError(
                    f"{name}: {char!r} (U+{ord(char):04X}) occupies "
                    f"{wcswidth(char)} display columns, not 1. A wide glyph "
                    "shifts the rest of its row sideways and breaks every "
                    "vertical stroke below it."
                )

    # Every row is padded to the widest, so the drawing is square by
    # construction and a stroke in one row sits above the stroke below it.
    width = max(wcswidth(row) for row in rows)
    return tuple(row + " " * (width - wcswidth(row)) for row in rows)


# Column-preserving stylization: ascii character -> replacement of the SAME
# display width.
#
# EMPTIED UNDER CONTRACT P, 2026-07-31. This table used to map each ascii mark
# to a box-drawing character (`|` to U+2502, `_` to U+2581, and so on). That is
# now incompatible with the runtime font contract, and the reason is worth
# stating because it is not obvious.
#
# Contract P bundles ONE exact face and forbids any fallback, because a
# substituted glyph's advance bears no relation to the declared face's and a
# measured layout would misplace every glyph after it. The bundled face
# (Literata, pinned and subset) contains none of those twelve box-drawing
# characters -- and neither does any other proportional face examined: Source
# Serif 4 had none, EB Garamond had two of twelve. Emitting them would
# guarantee the per-glyph fallback the contract exists to prevent.
#
# What replaced them is not a downgrade. Under Contract P the drawing no longer
# depends on characters that happen to be one column wide, because placement is
# measured per glyph rather than inherited from a monospace cell. The ascii
# marks are drawn by a real text face at a real weight, which is what the
# operator confirmed as legible on 2026-07-31.
#
# Restoring an entry here requires the bundled font to contain it; the cmap test
# in tests/test_garden_font_contract.py enforces exactly that.
PROPORTIONAL_INK: dict[str, str] = {}


def _stylize(ascii_rows: tuple[str, ...], overrides: dict[str, str]) -> tuple[str, ...]:
    """Derive the proportional drawing from the ascii one, column for column.

    Every substituted glyph is one display column wide, so the result occupies
    the identical grid. A character with no substitution is carried through
    unchanged rather than dropped, so an unmapped glyph degrades to plain ASCII
    instead of silently vanishing from the picture.

    :param ascii_rows: The ascii-safe drawing, already rectangular.
    :param overrides: Per-fixture ink choices layered over the shared table,
      for cases where a character means something different in that object.
    :returns: The proportional rows, same count and same width.
    """
    ink = {**PROPORTIONAL_INK, **overrides}
    return tuple("".join(ink.get(char, char) for char in row) for row in ascii_rows)


def _rectangular(rows: tuple[str, ...], name: str) -> tuple[str, ...]:
    """Right-pad rows to a common width, and verify nothing unsafe crept in.

    The ascii-safe profile stores a rectangular cell matrix, so every row must be
    the same length. Padding with trailing spaces is invisible and safe; it is
    applied here rather than by hand so a drawing can be edited without
    re-counting every row.
    """
    width = max(len(row) for row in rows)
    padded = tuple(row.ljust(width) for row in rows)
    for row in padded:
        for char in row:
            if not 32 <= ord(char) <= 126:
                raise ValueError(f"{name}: {char!r} is not printable ASCII")
    return padded


# ---------------------------------------------------------------------------
# Historical operator receipts, as given
# ---------------------------------------------------------------------------
#
# SPEC 7.10 requires per-asset sign-off, and until now the log recorded that
# round 1's verdicts had been lost. They were not lost twice: the round-2
# worksheet exported them, so they are recorded here verbatim rather than
# summarised. `accepted` means the operator marked it as reading. It does NOT
# mean the drawing is final -- two accepted fixtures came with refinements,
# which have been applied and need confirming.
HISTORICAL_REVIEW_RECEIPTS: dict[str, dict[str, str]] = {
    # ROUND 4 CLOSES THE STARTER SET. All ten fixtures are now marked as
    # reading, across four rounds. Nothing below is drawn again.
    #
    # Seven were marked in round 4: the four redrawn that round, plus mailbox,
    # stepping_stones and arbor re-confirmed. The remaining three -- bench,
    # trellis, birdbath -- were left unmarked in round 4 and therefore KEEP
    # their round-3 verdicts. An unmarked item is not a new acceptance, so
    # re-stamping them with round 4 would invent a sign-off that was not given,
    # in exactly the direction that flatters the work.
    "trellis": {
        "verdict": "accepted", "round": "3",
        "quote": "READS",
    },
    "bench": {
        "verdict": "accepted", "round": "3",
        "quote": "READS",
    },
    "birdbath": {
        "verdict": "accepted", "round": "3",
        "quote": "READS",
    },
    "mailbox": {
        "verdict": "accepted", "round": "4",
        "quote": "READS",
    },
    "stepping_stones": {
        "verdict": "accepted", "round": "4",
        "quote": "READS",
    },
    "arbor": {
        "verdict": "accepted", "round": "4",
        "quote": "READS",
    },
    # The four redrawn in round 4, all accepted on the first showing.
    "lantern": {
        "verdict": "accepted", "round": "4",
        "quote": "READS",
    },
    "bridge": {
        "verdict": "accepted", "round": "4",
        "quote": "READS",
    },
    "pond": {
        "verdict": "accepted", "round": "4",
        "quote": "READS",
    },
    # Marked READS and [keep]. The note attached to it is NOT a change request
    # -- it names what works ("the ' ' is good touch, and space between the two
    # sprouts") and raises a future requirement, that the growth will have to
    # change as the plant grows. That is a states problem, not a drawing
    # problem, and it is recorded in `PENDING_REQUIREMENTS` rather than acted on
    # here. Redrawing on the strength of a compliment would be the same mistake
    # as ignoring a rejection, pointed the other way.
    "planter": {
        "verdict": "accepted", "round": "4",
        "quote": (
            "reads as just sprouted seedlings, which is fine, but it may need "
            "to change as it grows, the ' ' is good touch, and space between "
            "the two sprouts"
        ),
    },
}


# ---------------------------------------------------------------------------
# Requirements raised during review that are deliberately NOT drawings
# ---------------------------------------------------------------------------
#
# A review note can name a change to the art, or it can name a gap in the
# model. These are the second kind. Acting on them by redrawing would produce a
# picture that still cannot do the thing asked for, so they are recorded here
# and left for the lane that owns the model.
PENDING_REQUIREMENTS: dict[str, str] = {
    "planter": (
        "Round 4: the growth 'may need to change as it grows'. All ten drawn "
        "fixtures declare exactly one state, `idle`, in both profiles, so there "
        "is nowhere for a second drawing to live. The schema is not the "
        "obstacle -- four undrawn placeholders already declare two states each "
        "(fence_gate, shed_edge, watering_can, compost), so the capability "
        "exists and only the assets with art gave it up. This needs a growth "
        "quantity on the planter's world state, a mapping from it to a few "
        "named states, a state list on the asset, and then a drawing per state "
        "in BOTH profiles, which the existing cross-profile parity rule "
        "already requires."
    ),
}


# ---------------------------------------------------------------------------
# The starter composition's ten fixtures
# ---------------------------------------------------------------------------
#
# `structure` is the canonical stroke graph: the named parts that make the
# object that object, top to bottom. `material` and `affordance` are the facts
# a glyph choice has to serve. Both profiles realise the same parts.

FIXTURE_ART: dict[str, dict[str, Any]] = {
    # ROUND 2. Round 1 stacked two solid `|_____|` rows, which gave the object a
    # continuous upholstered mass -- the reason it read as a sofa. The fix is
    # openness, not detail: the backrest is now separated uprights with gaps
    # showing through, the seat is a single plank that overhangs its supports,
    # and the legs are inset so daylight appears under both ends.
    "bench": {
        "structure": (
            ("backrest", "separated vertical slats with visible gaps between them"),
            ("seat", "one horizontal plank, overhanging the legs at both ends"),
            ("legs", "two supports inset from the plank ends, open beneath"),
        ),
        "material": "timber",
        "affordance": "sit",
        "ascii": (
            " |_|_|_| ",
            "_|_____|_",
            " |     | ",
            " '     ' ",
        ),
        "anchor_column": 4,
        "note": "Round 2: open slatted back and inset legs, so it is a bench rather than a sofa.",
    },

    # ROUND 2. Rebuilt at the operator's own reference size -- about seven
    # columns -- after "too wide/big". The flag is the identifying part and is
    # the only thing above the body; the body is a single closed run of strokes
    # rather than an outlined box, which is what keeps it small.
    "mailbox": {
        "structure": (
            ("flag", "raised signal arm, the identifying part, clear of the body"),
            ("body", "horizontal drum with a rounded door end"),
            ("post", "single narrow support"),
            ("foot", "short ground flare"),
        ),
        "material": "painted metal on a timber post",
        "affordance": "receive",
        "ascii": (
            "   7   ",
            " (__(_)",
            "   ||  ",
            "  _||_ ",
        ),
        "accents": {"0,3": "signal"},
        "anchor_column": 3,
        "note": "Round 2: rebuilt at the operator's ~7-column reference; flag is the only mass above the drum.",
    },

    # ROUND 2. `(__)` read as an open container because the bracket pair encloses
    # a void with an open top. Replacing the void with a flat `=` surface makes
    # the stone read as something stood on rather than something poured into.
    "stepping_stones": {
        "structure": (
            ("stones", "low flat-topped slabs, staggered across the route"),
        ),
        "material": "river stone",
        "affordance": "path",
        "ascii": (
            " (=)  (=)   ",
            "    (=)  (=)",
        ),
        "anchor_column": 5,
        "note": "Round 2: flat top surface instead of an open bowl, so it is stood on, not filled.",
    },

    # ROUND 3. Rejected twice. Rounds 1 and 2 both drew the bridge as a boxed
    # frame -- a rectangle with strokes inside it -- and both times the operator
    # could not tell what it was. This round abandons that idiom and follows the
    # operator's own round-2 sketch literally: `/=|=|=|=\` over `' '`. Two facts
    # come out of that sketch. The deck and its railing are ONE row, with the
    # balusters interleaved between the planks, not stacked as two separate
    # bands. And the ends RISE -- the diagonals are approach ramps, which is
    # what states "you cross this" rather than "you look at this".
    "bridge": {
        "structure": (
            ("ramps", "diagonal approaches rising from each bank onto the deck"),
            ("deck", "planks and railing balusters interleaved along one run"),
            ("piers", "two supports, the span open between them"),
            ("feet", "ground contact under each pier"),
        ),
        "material": "timber planking",
        "affordance": "cross",
        "ascii": (
            " /=|=|=|=\\ ",
            "_|       |_",
            " '       ' ",
        ),
        "anchor_column": 5,
        "note": "Round 3: drawn from the operator's own sketch -- rising approaches, interleaved deck and railing, open span.",
    },

    # ROUND 3. "BASE IS BETTER KEEP THAT PLANTS LOOK BAD" -- so the container is
    # untouched below the rim and only the growth is redrawn. The round-2 plants
    # were `\|/`, which is the standard sparkle/starburst mark: it has no
    # vertical run, so it read as debris scattered on the rim rather than as
    # something rooted in the box. The growth now has HEIGHT -- a stem row of its
    # own before the tip -- which is the single property that separates a
    # planted thing from a dropped one. Leaves point outward, because an inward
    # pair closes into a bracket and re-reads as another container.
    "planter": {
        "structure": (
            ("tips", "forked stem ends, sparse and clear of each other"),
            ("stems", "upright runs with one side leaf each, rooted in the box"),
            ("rim", "upper course, slightly proud of the body"),
            ("body", "offset brick courses"),
        ),
        "material": "brick",
        "affordance": "plant",
        "ascii": (
            "   Y   Y   ",
            "  ,|   |,  ",
            " [_______] ",
            "  \\_|_|_/  ",
        ),
        "anchor_column": 5,
        "note": "Round 3: base kept as accepted; growth redrawn with a stem run so it reads as planted, not scattered.",
    },

    # ROUND 2. Straight-sided uprights and a ruled top made this read as a
    # doorway. Curved shoulders and paired uprights, with the arch carried by
    # rounded strokes rather than corners, is the "better glyphs, curves" note.
    "arbor": {
        "structure": (
            ("crown", "climbing growth over the arch, uneven along its length"),
            ("arch", "curved shoulders meeting overhead"),
            ("uprights", "paired posts, open between them"),
        ),
        "material": "timber frame under climbing growth",
        "affordance": "walk_under",
        "ascii": (
            "  ,~^~^~,  ",
            " ((     )) ",
            " ||     || ",
            " ||     || ",
        ),
        "anchor_column": 5,
        "note": "Round 2: curved shoulders and paired uprights so it reads as walk-through, not a doorway.",
    },

    # ROUND 2. The operator preferred the ascii-safe version and asked for
    # better glyphs. The bowl keeps its converging dish lines; the stem is now
    # visibly narrower than both bowl and foot, which is what makes a birdbath
    # a birdbath rather than a goblet.
    "birdbath": {
        "structure": (
            ("bowl", "shallow dish, wider than it is deep"),
            ("stem", "narrow column, clearly thinner than bowl and foot"),
            ("foot", "spread base wider than the stem"),
        ),
        "material": "weathered stone",
        "affordance": "water",
        "ascii": (
            " \\~~~~~/ ",
            "  '-|-'  ",
            "   _|_   ",
            "  /___\\  ",
        ),
        "anchor_column": 4,
        "note": "Round 2: stem narrowed against both bowl and foot so the dish reads as a bath, not a cup.",
    },

    # ROUND 3. "ONE HORIZONTAL... SPACE IT OUT VERTICALLY AND HORIZONTALLY,
    # ALTERNATE ~". Round 2 filled the interior with a single solid run,
    # `(~~~~-~~~~)`, and a continuous band of identical marks is a texture fill,
    # not a surface: it has no depth cue, which is why it read as a cloud.
    # Ripples are OFFSET -- no two rows put a train in the same columns. The
    # first accepted version used only two isolated marks per row; live review
    # showed that its frames differed mechanically but the motion disappeared
    # at full-scene scale. Short trains preserve open water while making their
    # two-cell lateral translation perceptible.
    #
    # The form is also flatter now: fifteen columns across four rows. A pond is
    # seen at a shallow angle, so its silhouette is wide and low, and rounds 1
    # and 2 were both nearly square.
    "pond": {
        "structure": (
            ("waterline", "uneven upper boundary, no two spans alike"),
            ("surface", "sparse ripples, offset row to row, never in one band"),
            ("far_edge", "lower boundary broken by mixed-weight punctuation"),
        ),
        "material": "still water",
        "affordance": "water",
        "ascii": (
            "  _,-~-.,_,-~-.,_,-~-.  ",
            "(   ~~      ~~~      ~~)",
            "(  ~~~      ~~      ~~ )",
            "  `-.,_,-~-.,_,-~-.,_-' ",
        ),
        # The operator-directed wider silhouette stays fixed across the four
        # motion frames. Only the interior ripple trains translate
        # left/centre/right, then ping-pong, so the pond reads as water without
        # redrawing its banks or filling it with texture.
        "frames": (
            (
                "  _,-~-.,_,-~-.,_,-~-.  ",
                "( ~~      ~~~      ~~  )",
                "(    ~~~      ~~      ~)",
                "  `-.,_,-~-.,_,-~-.,_-' ",
            ),
            (
                "  _,-~-.,_,-~-.,_,-~-.  ",
                "(   ~~      ~~~      ~~)",
                "(  ~~~      ~~      ~~ )",
                "  `-.,_,-~-.,_,-~-.,_-' ",
            ),
            (
                "  _,-~-.,_,-~-.,_,-~-.  ",
                "(     ~~      ~~~    ~ )",
                "(~~~      ~~      ~~   )",
                "  `-.,_,-~-.,_,-~-.,_-' ",
            ),
            (
                "  _,-~-.,_,-~-.,_,-~-.  ",
                "(   ~~      ~~~      ~~)",
                "(  ~~~      ~~      ~~ )",
                "  `-.,_,-~-.,_,-~-.,_-' ",
            ),
        ),
        "frame_ticks": 10,
        # The shared table reads `'` as a ground foot, because in the bench and
        # the bridge that is what it is. Here it is the right-hand hook of the
        # far edge, mirroring the `` ` `` at the left, and turning one half of a
        # mirrored pair into an upward stroke breaks the contour. Same reason as
        # the lantern's override: a character's meaning belongs to the object.
        "ink": {"'": "'"},
        "anchor_column": 11,
        "note": "Round 3 silhouette widened on 2026-08-04 so the path can meet its bank; the 2026-08-05 live review kept that accepted bank and strengthened only the interior ripple train so its side-to-side oscillation reads at full-scene scale.",
    },

    # ROUND 3. "TALLER, AND ||| NOT | | | BASE CAN HAVE /___\\ STYLE BASE".
    #
    # The `||| NOT | | |` note is not about the ascii drawing -- that already
    # said `|||`. It is about what the PROPORTIONAL profile did with it. A
    # proportional font gives every glyph side bearings, so three light verticals
    # set side by side render as three separated hairlines with daylight between
    # them: `| | |`. The `ink` override below swaps that one character for the
    # HEAVY vertical, which fills far more of its advance width, so the three
    # strokes close up into a single column of mass. This is the first case
    # where a fixture needs its own ink: the same character means "one thin lath"
    # in the trellis and "part of a solid post" here.
    #
    # Taller by two rows, and the foot is now the requested spread base rather
    # than a flat rule, so the post visibly stands on something.
    "lantern": {
        "structure": (
            ("light", "single small mass at the top, brighter than anything below"),
            ("post", "solid column, the tallest run of the silhouette"),
            ("foot", "spread base the post stands on, wider than the post"),
        ),
        "material": "iron post with a glass head",
        "affordance": "light",
        "ascii": (
            "   _   ",
            "  (*)  ",
            "  |||  ",
            "  |||  ",
            "  |||  ",
            "  |||  ",
            " /___\\ ",
        ),
        # Override removed under Contract P, 2026-07-31. This mapped `|` to
        # U+2503 HEAVY VERTICAL so the lantern post read as one mass rather than
        # three hairlines. The bundled face does not contain that character, and
        # emitting it would force the per-glyph fallback the font contract
        # forbids. The equivalent effect is now available through the contract's
        # own weight axis rather than by borrowing a heavier character from
        # whatever font the browser happened to substitute.
        "ink": {},
        "anchor_column": 3,
        "note": "Round 3: two rows taller, spread base, and a heavy-vertical override so the proportional post is solid rather than gapped.",
    },

    # ACCEPTED IN ROUND 1 -- the only fixture the operator marked as reading.
    # Left exactly as drawn. Its structure is recorded here so it conforms to
    # the same contract as the rest, but not one stroke of the art is touched:
    # re-drawing something already accepted would put it back under review for
    # no reason.
    "trellis": {
        "structure": (
            ("lattice", "opposed diagonals crossing, open between them"),
            ("uprights", "two ground posts carrying the panel"),
        ),
        "material": "thin timber lath",
        "affordance": "climb",
        "ascii": (
            " \\/\\/\\/\\/ ",
            " /\\/\\/\\/\\ ",
            " \\/\\/\\/\\/ ",
            " /\\/\\/\\/\\ ",
            " |      | ",
        ),
        "anchor_column": 4,
        "note": "Accepted in round 1 and left untouched: opposed diagonals, not a box grid.",
    },
}


# ---------------------------------------------------------------------------
# Seeded fixture-room review candidates
# ---------------------------------------------------------------------------
#
# These are separate atlas identities, not extra states smuggled underneath an
# accepted asset id.  The current acceptance registry reviewed only the base
# fixture ``idle`` drawings.  Reusing that id for new silhouettes would make a
# new pond or planter inherit a verdict it was never shown under.  Separate ids
# keep the review boundary executable: the generator may persist the selected
# identity, the renderer may resolve it, and production paint authority still
# refuses it until its own registry row is accepted.
#
# The variants deliberately preserve each base fixture's structural grammar.
# They vary only the axes the operator assigned to the seed on 2026-08-05:
# pond diameter/loop silhouette, stone count/size, and planter blossom count.
# Stone SIDE and bench POSITION are canonical room-layout choices and therefore
# live in the world generator, not in these drawings.
FIXTURE_VARIANT_BASES: dict[str, str] = {
    "pond_compact": "pond",
    "pond_round": "pond",
    "stepping_stones_three": "stepping_stones",
    "stepping_stones_five": "stepping_stones",
    "planter_one": "planter",
    "planter_three": "planter",
}

FIXTURE_ART.update({
    "pond_compact": {
        "structure": FIXTURE_ART["pond"]["structure"],
        "material": "still water",
        "affordance": "water",
        "ascii": (
            "  _,-~-.,_,-~-.,_-.",
            "( ~~    ~~~    ~~  )",
            "(   ~~~    ~~     ~)",
            "  `-.,_,-~-.,_,-'",
        ),
        "frames": (
            (
                "  _,-~-.,_,-~-.,_-.",
                "(~~    ~~~    ~~   )",
                "(    ~~    ~~~    ~)",
                "  `-.,_,-~-.,_,-'",
            ),
            (
                "  _,-~-.,_,-~-.,_-.",
                "(  ~~    ~~~    ~~ )",
                "( ~~    ~~~    ~   )",
                "  `-.,_,-~-.,_,-'",
            ),
            (
                "  _,-~-.,_,-~-.,_-.",
                "(    ~~    ~~~   ~)",
                "(~~~    ~~    ~~   )",
                "  `-.,_,-~-.,_,-'",
            ),
            (
                "  _,-~-.,_,-~-.,_-.",
                "(  ~~    ~~~    ~~ )",
                "( ~~    ~~~    ~   )",
                "  `-.,_,-~-.,_,-'",
            ),
        ),
        "frame_ticks": 10,
        "anchor_column": 9,
        "note": "Seeded compact pond candidate: the accepted shallow-water grammar in a shorter loop.",
    },
    "pond_round": {
        "structure": FIXTURE_ART["pond"]["structure"],
        "material": "still water",
        "affordance": "water",
        "ascii": (
            "    _,-~-.,_,-~-.    ",
            "  ,'             `.  ",
            "(   ~~    ~~~    ~~  )",
            "( ~~    ~~~    ~~    )",
            "  `-.,_       _,-'   ",
            "      `-~-~-~-'       ",
        ),
        "frames": (
            (
                "    _,-~-.,_,-~-.    ",
                "  ,'             `.  ",
                "( ~~    ~~~    ~~    )",
                "(    ~~    ~~~    ~~ )",
                "  `-.,_       _,-'   ",
                "      `-~-~-~-'       ",
            ),
            (
                "    _,-~-.,_,-~-.    ",
                "  ,'             `.  ",
                "(   ~~    ~~~    ~~  )",
                "(  ~~    ~~~    ~~   )",
                "  `-.,_       _,-'   ",
                "      `-~-~-~-'       ",
            ),
            (
                "    _,-~-.,_,-~-.    ",
                "  ,'             `.  ",
                "(     ~~    ~~~    ~ )",
                "(~~~    ~~    ~~~    )",
                "  `-.,_       _,-'   ",
                "      `-~-~-~-'       ",
            ),
            (
                "    _,-~-.,_,-~-.    ",
                "  ,'             `.  ",
                "(   ~~    ~~~    ~~  )",
                "(  ~~    ~~~    ~~   )",
                "  `-.,_       _,-'   ",
                "      `-~-~-~-'       ",
            ),
        ),
        "frame_ticks": 10,
        "anchor_column": 10,
        "note": "Seeded round pond candidate: greater front-to-back diameter while retaining open water and moving ripple trains.",
    },
    "stepping_stones_three": {
        "structure": FIXTURE_ART["stepping_stones"]["structure"],
        "material": "river stone",
        "affordance": "path",
        "ascii": (
            " (=)      ",
            "   (=) (=)",
        ),
        "anchor_column": 4,
        "note": "Seeded three-stone path candidate with a short staggered approach.",
    },
    "stepping_stones_five": {
        "structure": FIXTURE_ART["stepping_stones"]["structure"],
        "material": "river stone",
        "affordance": "path",
        "ascii": (
            " (=)       (=)  ",
            "    (=)         ",
            "       (=)  (=) ",
        ),
        "anchor_column": 7,
        "note": "Seeded five-stone path candidate with a longer staggered approach.",
    },
    "planter_one": {
        "structure": FIXTURE_ART["planter"]["structure"],
        "material": "brick",
        "affordance": "plant",
        "ascii": (
            "     Y     ",
            "    ,|     ",
            " [_______] ",
            "  \\_|_|_/  ",
        ),
        "anchor_column": 5,
        "note": "Seeded one-blossom planter candidate; the accepted vessel is unchanged.",
    },
    "planter_three": {
        "structure": FIXTURE_ART["planter"]["structure"],
        "material": "brick",
        "affordance": "plant",
        "ascii": (
            "  Y   Y   Y  ",
            " ,|   |   |, ",
            " [_________] ",
            "  \\__|_|__/  ",
        ),
        "anchor_column": 6,
        "note": "Seeded three-blossom planter candidate with separated stems and a widened authored vessel.",
    },
})


def fixture_profiles(catalog_id: str) -> dict[str, Any] | None:
    """Return the structure and both stylizations for one fixture.

    :param catalog_id: The catalog id, e.g. `bench`.
    :returns: A dict carrying `structure`, `material`, `affordance`, `ascii`,
      `proportional`, `anchor_column` and `note`, or None when this fixture has
      no artwork yet.
    :raises ValueError: If the two profiles disagree on row count, which would
      mean they had stopped realising the same structure.
    """
    entry = FIXTURE_ART.get(catalog_id)
    if entry is None:
        return None

    ascii_rows = _rectangular(tuple(entry["ascii"]), catalog_id)
    # Derived, never hand-drawn: see `_stylize`. The alignment guard still runs
    # over the result, so a bad override is caught rather than shipped.
    proportional_rows = _aligned_proportional(
        _stylize(ascii_rows, entry.get("ink", {})), catalog_id,
    )

    # The shared structure is what both profiles are required to realise, so a
    # disagreement in row count means one of them has drifted into drawing a
    # different object. Caught here rather than in the atlas compiler, because
    # here the message can name the artistic cause.
    if len(proportional_rows) != len(ascii_rows):
        raise ValueError(
            f"{catalog_id}: profiles disagree on row count "
            f"({len(ascii_rows)} ascii, {len(proportional_rows)} proportional). "
            "Both profiles stylize one structure; they may not depict different objects."
        )
    if not entry.get("structure"):
        raise ValueError(f"{catalog_id}: no structural stroke graph declared")

    ascii_frames = tuple(
        _rectangular(tuple(frame), f"{catalog_id} frame {index}")
        for index, frame in enumerate(entry.get("frames", (ascii_rows,)))
    )
    proportional_frames = tuple(
        _aligned_proportional(
            _stylize(frame, entry.get("ink", {})), f"{catalog_id} frame {index}",
        )
        for index, frame in enumerate(ascii_frames)
    )

    return {
        **entry,
        "ascii": ascii_rows,
        "proportional": proportional_rows,
        "ascii_frames": ascii_frames,
        "proportional_frames": proportional_frames,
        # Historical words survive as provenance only. Current verdicts live
        # exclusively in docs/garden-asset-acceptance.json.
        "historical_review": HISTORICAL_REVIEW_RECEIPTS.get(
            catalog_id, {"verdict": "not_reviewed", "round": "-", "quote": ""},
        ),
        # None for most fixtures. See `PENDING_REQUIREMENTS`: a review note that
        # names a gap in the model rather than in the drawing.
        "pending_requirement": PENDING_REQUIREMENTS.get(catalog_id),
    }
