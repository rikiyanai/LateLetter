# Garden world fixtures

## `historical_world_13_22_4_8.json`

A persisted world in the condition the browser one was actually found in: the
**current shape**, **no content stamps**, and a roster today's generator cannot
produce — 13 plants, 22 fixtures, 4 animals, 8 collectibles, against a current
starter composition.

**What it is.** A document that loads through the real `WorldState.from_dict`,
so its shape is authentic rather than hand-approximated. It was built from the
widest world this generator can make (8 plants, 5 fixtures, 4 animals, 3
collectibles, using every anchor the tables define) and extended with further
valid entries under distinct ids until the census matched what the review
observed.

**What it is not.** It is not a byte copy of the world seen in that browser
session — that document was never captured, and claiming otherwise would put a
provenance on the fixture that it does not have. What is faithful is the
condition under test: current schema, absent stamps, a population from a
generator that no longer exists.

**Why it is not a schema-migration fixture.** Schema 1 is the only shape this
project has ever written. The historical world is not an *older* schema; it is a
current-shape document with nothing recorded about where its contents came from.
So it is handled by characterization, and the schema-migration path stays empty
and refusing until a real second shape exists to write a transform against.
