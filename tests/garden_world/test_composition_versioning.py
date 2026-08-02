"""Composition versioning: can a world say where it came from?

A localhost review once opened a persisted world of 13 plants, 22 fixtures, 4
animals and 8 collectibles and read it as the current starter, which makes 8,
10, 4 and 3.  Nothing in the stored document was false; there was simply no
field capable of saying "an older generator made me".  These tests cover the
fields that can now say it, and -- more importantly -- the ways a stale world
could still end up claiming to be fresh.
"""

from __future__ import annotations

import json
from dataclasses import replace

import pytest

from lateletter.garden.world.model import (
    COMPOSITION_VERSION,
    GENERATOR_VERSION,
    WORLD_SCHEMA_VERSION,
    WorldState,
    new_world,
)
from lateletter.garden.world.provenance import (
    NotAFreshComposition,
    characterize_world,
    migrate_world_shape,
    require_fresh_composition,
    world_census,
)


def _fresh() -> WorldState:
    """A world made by today's code, which is the only source of the stamps."""
    return new_world("world-1", "seed-1")


def test_the_three_versions_are_independent_fields():
    """One number cannot carry three separate facts.

    Shape, generator and composition answer different questions and can
    disagree with each other; held together, an obsolete starter reads as
    today's candidate, which is the defect this whole module exists for.
    """
    world = _fresh()
    assert world.schema_version == WORLD_SCHEMA_VERSION
    assert world.generator_version == GENERATOR_VERSION
    assert world.composition_version == COMPOSITION_VERSION
    stored = world.to_dict()
    assert {"schema_version", "generator_version", "composition_version"} <= set(stored)


def test_a_freshly_generated_world_is_characterized_as_fresh():
    """The positive control: the check must be satisfiable by real code.

    A characterization that has only ever reported staleness proves nothing
    about whether anything can be fresh.
    """
    origin = characterize_world(_fresh())
    assert origin.is_fresh, origin.reasons
    assert origin.label == "fresh"
    assert require_fresh_composition(_fresh()) == origin


def test_a_world_stored_before_versioning_does_not_claim_todays_stamps():
    """Absent must stay absent.

    This is the whole defect in one assertion.  If ``from_dict`` defaulted the
    missing stamps to the current constants, every pre-versioning world would
    load claiming to be today's -- exactly how the 13/22/4/8 world was reviewed
    as the current starter.
    """
    document = _fresh().to_dict()
    del document["generator_version"]
    del document["composition_version"]

    restored = WorldState.from_dict(document)
    assert restored.generator_version is None
    assert restored.composition_version is None

    origin = characterize_world(restored)
    assert not origin.is_fresh
    assert any("predates version stamping" in reason for reason in origin.reasons)
    assert any("never stamped as approved" in reason for reason in origin.reasons)


def test_an_explicit_null_stamp_is_also_absent_not_zero():
    """``null`` in the document is "not recorded", never the integer zero.

    A stored ``null`` coerced to 0 would compare unequal to the current version
    and so would still be caught -- but it would be caught with the wrong
    sentence, reporting a generator that never existed instead of a world that
    cannot say.
    """
    document = _fresh().to_dict()
    document["generator_version"] = None
    restored = WorldState.from_dict(document)
    assert restored.generator_version is None


def test_an_older_generator_is_named_rather_than_summarised():
    """"Stale" is not actionable; "built by 1, current is 2" is."""
    world = replace(_fresh(), generator_version=GENERATOR_VERSION - 1)
    origin = characterize_world(world)
    assert not origin.is_fresh
    assert any(
        f"built by generator {GENERATOR_VERSION - 1}" in reason for reason in origin.reasons
    )


def test_every_way_of_being_stale_is_reported_separately():
    """A world can be stale in more than one way at once.

    Collapsing three defects into one sentence hides two of them, and the one
    that gets hidden is whichever the summary happened not to mention.
    """
    world = replace(
        _fresh(),
        generator_version=None,
        composition_version=COMPOSITION_VERSION - 1,
        migrated_from_schema=WORLD_SCHEMA_VERSION,
    )
    origin = characterize_world(world)
    assert len(origin.reasons) == 3, origin.reasons


def test_a_shape_migration_never_launders_an_old_world_into_a_fresh_one():
    """Migrating a document does not regenerate the garden inside it.

    This is the single rule that keeps a migration honest.  If a migration
    stamped the current generator onto the world it upgraded, then upgrading an
    obsolete starter would make it indistinguishable from one built today --
    the masquerade, reintroduced by the very code meant to prevent it.
    """
    document = _fresh().to_dict()
    del document["generator_version"]
    del document["composition_version"]
    stored = WorldState.from_dict(document)

    migrated = migrate_world_shape(stored)

    assert migrated.schema_version == WORLD_SCHEMA_VERSION
    assert migrated.generator_version is None, "the migration invented a content stamp"
    assert migrated.composition_version is None, "the migration invented a content stamp"

    origin = characterize_world(migrated)
    assert not origin.is_fresh
    assert origin.label == "migrated"
    assert origin.migrated is True


def test_migrating_twice_still_records_where_the_world_originally_came_from():
    """A world migrated twice still came from where it came from."""
    stored = replace(_fresh(), schema_version=WORLD_SCHEMA_VERSION, migrated_from_schema=0)
    once = migrate_world_shape(stored)
    twice = migrate_world_shape(once)
    assert twice.migrated_from_schema == 0


def test_a_current_unmigrated_world_is_left_exactly_alone():
    """A migration that rewrites a world it did not need to touch is a change
    nobody asked for, and would mark a fresh world as migrated."""
    world = _fresh()
    assert migrate_world_shape(world) is world


def test_a_review_surface_refuses_a_world_that_is_not_fresh():
    """The enforceable half: a fresh-composition review must refuse the rest.

    Refusing loudly is the difference between reviewing today's Garden and
    reviewing something restored from before it -- which is the mistake that
    was actually made, by a person, looking at a screen.
    """
    document = _fresh().to_dict()
    del document["generator_version"]
    stale = WorldState.from_dict(document)

    with pytest.raises(NotAFreshComposition) as caught:
        require_fresh_composition(stale)

    # The reasons ride on the exception so a caller can report them without
    # re-deriving them.
    assert caught.value.origin.reasons
    assert "predates version stamping" in str(caught.value)


def test_the_census_is_reported_beside_the_claimed_versions():
    """The stamps say what a world CLAIMS; the census says what it IS.

    The 13/22/4/8 case was found by a person noticing the two disagreed, so
    both belong in the same report rather than one being derivable on request.
    """
    world = _fresh()
    assert world_census(world) == {
        "plants": 0,
        "fixtures": 0,
        "animals": 0,
        "collectibles": 0,
    }
    origin = characterize_world(world)
    assert origin.census == world_census(world)
    assert set(origin.to_dict()) >= {"label", "is_fresh", "census", "reasons"}


def test_the_stamps_survive_a_round_trip_through_storage():
    """A field that does not survive serialisation is not a stored fact."""
    world = replace(_fresh(), migrated_from_schema=0)
    restored = WorldState.from_dict(json.loads(json.dumps(world.to_dict())))
    assert restored.generator_version == GENERATOR_VERSION
    assert restored.composition_version == COMPOSITION_VERSION
    assert restored.migrated_from_schema == 0


def test_the_browser_and_python_constants_are_the_same_numbers():
    """Two generators stamping different versions would make the label lie.

    The browser and terminal worlds are byte-identical by contract
    (tests/garden_adapters/test_world_browser_conformance.py); that only holds
    if both stamp the same numbers, so the constants are compared directly.
    """
    from pathlib import Path
    import re

    source = (Path(__file__).resolve().parents[2] / "web" / "garden-world.mjs").read_text(
        encoding="utf-8"
    )
    for name, value in (
        ("GENERATOR_VERSION", GENERATOR_VERSION),
        ("COMPOSITION_VERSION", COMPOSITION_VERSION),
        ("WORLD_SCHEMA_VERSION", WORLD_SCHEMA_VERSION),
    ):
        match = re.search(rf"export const {name} = (\d+);", source)
        assert match, f"{name} is not exported by the browser world"
        assert int(match.group(1)) == value, f"{name} differs between the two generators"
