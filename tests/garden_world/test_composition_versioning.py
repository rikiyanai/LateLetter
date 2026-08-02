"""Composition versioning: can a world say where it came from, and prove it?

A localhost review once opened a persisted world of 13 plants, 22 fixtures, 4
animals and 8 collectibles and read it as the current starter, which generates 2
plants and 5 fixtures.  Nothing in the stored document was false; there was no
field capable of saying "an older generator made me".

These tests cover the fields that can now say it.  Three of them exist because a
first attempt at this file got the semantics wrong in ways worth keeping named:

  - it stamped an EMPTY world from ``new_world`` and then certified 0/0/0/0 as a
    fresh composition;
  - it described the composition version as an operator approval, so every
    generated world claimed a verdict nobody has ever given;
  - it "migrated" a document by changing its schema number and nothing else,
    which proves a number can be reassigned and proves nothing about migration.
"""

from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path

import pytest

from lateletter.garden.world.generation import (
    STARTER_PLANT_SPECIES,
    generate_initial_world,
)
from lateletter.garden.world.model import (
    COMPOSITION_VERSION,
    GENERATOR_VERSION,
    WORLD_SCHEMA_VERSION,
    WorldState,
    new_world,
)
from lateletter.garden.world.provenance import (
    LOAD_GENERATED,
    LOAD_SCHEMA_MIGRATED,
    LOAD_STORED,
    NotAFreshComposition,
    characterize_world,
    composition_acceptance,
    composition_fingerprint,
    load_migrated_world,
    migrate_world_document,
    require_fresh_composition,
    world_census,
)


def _generated() -> WorldState:
    """The REAL starter, through the real generator.

    Not ``new_world``.  ``new_world`` returns an empty world, and testing the
    starter through it is how 0/0/0/0 came to be certified as a composition.
    """
    return generate_initial_world("world-1", "seed-1")


# ---------------------------------------------------------------------------
# What the stamps mean, and what they do not.
# ---------------------------------------------------------------------------


def test_the_three_versions_are_independent_fields():
    """One number cannot carry three separate facts.

    Shape, generator and composition revision answer different questions and can
    disagree; held together, an obsolete starter reads as today's candidate.
    """
    world = _generated()
    assert world.schema_version == WORLD_SCHEMA_VERSION
    assert world.generator_version == GENERATOR_VERSION
    assert world.composition_version == COMPOSITION_VERSION
    stored = world.to_dict()
    assert {
        "schema_version",
        "generator_version",
        "composition_version",
        "composition_fingerprint",
    } <= set(stored)


def test_an_empty_world_is_not_a_composition():
    """``new_world`` returns nothing planted, so it stamps nothing.

    Stamping there declared an empty world to be a whole composition, and the
    characterization then agreed with it.  This is the assertion that keeps the
    stamp attached to a population rather than to a constructor call.
    """
    empty = new_world("world-1", "seed-1")
    assert world_census(empty) == {
        "plants": 0, "fixtures": 0, "animals": 0, "collectibles": 0,
    }
    assert empty.generator_version is None
    assert empty.composition_version is None
    assert empty.composition_fingerprint is None
    assert not characterize_world(empty).is_fresh


def test_the_stamp_describes_the_roster_the_generator_actually_produced():
    """The census and the fingerprint are measured, never assumed.

    The starter is two plants and five fixtures.  An earlier report of this work
    quoted 8/10/4/3 from the failure log's history instead of measuring, which
    is the same class of mistake as trusting a version number.
    """
    world = _generated()
    census = world_census(world)
    assert census["plants"] == len(STARTER_PLANT_SPECIES) == 2
    assert census == {"plants": 2, "fixtures": 5, "animals": 0, "collectibles": 0}
    assert world.composition_fingerprint == composition_fingerprint(world)
    # Species AND the authored anchor each was placed against. Names alone were
    # not enough: moving every anchor produces a visibly different garden out of
    # an identical species list, so a verdict bound to names would survive a
    # layout nobody had seen.
    assert "plants=oak@60,300,sunflower@940,320" in world.composition_fingerprint


def test_moving_an_authored_anchor_changes_the_fingerprint():
    """A composition is where things are, not only what they are.

    This is the assertion that stops an accepted verdict from surviving a
    re-laid-out garden with an unchanged species list.
    """
    from lateletter.garden.world import generation as generation_module

    world = _generated()
    before = composition_fingerprint(world)
    original = generation_module.STARTER_PLANT_ANCHORS["oak"]
    generation_module.STARTER_PLANT_ANCHORS["oak"] = (999, 999)
    try:
        assert composition_fingerprint(world) != before
    finally:
        generation_module.STARTER_PLANT_ANCHORS["oak"] = original


def test_a_version_stamp_is_never_an_operator_approval():
    """Acceptance is a verdict a person gives, held in its own register.

    The stamp is written by the code that generated the world.  Reading it as
    approval made every generated world claim a verdict that has never been
    granted for any composition, so the two are answered by different functions
    reading different sources.
    """
    world = _generated()
    assert characterize_world(world).is_fresh, "fresh is about lineage"
    assert composition_acceptance(world) == "not_reviewed", "and says nothing about approval"


def test_acceptance_binds_to_the_roster_and_not_only_to_the_revision_number():
    """Re-rostering under the same revision inherits nothing.

    Approval attaches to what was actually looked at.  A verdict keyed on the
    revision number alone would be inherited by any later roster that reused the
    number, which is how an unreviewed population acquires an approval.
    """
    world = _generated()
    register = {
        "records": {
            f"{COMPOSITION_VERSION}:{world.composition_fingerprint}": {"verdict": "accepted"},
        }
    }
    assert composition_acceptance(world, register) == "accepted"

    rerostered = replace(
        world, composition_fingerprint="plants=rose|fixtures=|animals=|collectibles="
    )
    assert composition_acceptance(rerostered, register) == "not_reviewed"


def test_the_committed_acceptance_register_grants_nothing():
    """No starter composition has ever been submitted for review.

    A register that quietly held an accepted record would make this whole
    mechanism report an approval that did not happen, so the on-disk state is
    asserted rather than assumed.
    """
    assert composition_acceptance(_generated()) == "not_reviewed"


# ---------------------------------------------------------------------------
# The fingerprint: turning an assertion into evidence.
# ---------------------------------------------------------------------------


def test_a_current_stamp_over_a_changed_population_is_caught():
    """A version number alone is an unverified assertion.

    Without the fingerprint a world could carry every current stamp over an
    arbitrary roster and characterize as fresh.  This is the case that made the
    stamp evidence instead of a claim.
    """
    world = _generated()
    tampered = replace(world, plants=world.plants[:1])   # somebody removed a plant
    origin = characterize_world(tampered)
    assert not origin.is_fresh
    assert any("no longer match the stamped composition" in reason for reason in origin.reasons)
    # Both fingerprints are reported, so a reviewer sees WHICH species differ
    # rather than only that something did.
    assert origin.composition_fingerprint != origin.observed_fingerprint


def test_a_custom_roster_is_not_the_named_composition_and_cannot_be_reviewed():
    """A number every roster receives identifies nothing.

    An earlier version stamped ``COMPOSITION_VERSION`` on every successful
    generation, so a one-oak test roster read as the current composition and a
    fresh-composition review guard would have accepted it.  The revision names
    ONE candidate -- the declared starter -- and a custom roster belongs to no
    named candidate at all.
    """
    custom = generate_initial_world("world-1", "seed-1", plant_species=["oak"])
    assert custom.composition_version is None
    assert custom.composition_fingerprint != _generated().composition_fingerprint

    origin = characterize_world(custom)
    assert not origin.is_fresh, "a non-starter population was certified as fresh"
    assert any("names no composition revision" in reason for reason in origin.reasons)
    assert composition_acceptance(custom) == "not_reviewed"

    with pytest.raises(NotAFreshComposition):
        require_fresh_composition(custom, LOAD_GENERATED)


def test_the_fingerprint_ignores_positions_so_two_seeds_are_one_composition():
    """Positions are seed-derived; the composition is the roster."""
    assert (
        generate_initial_world("world-1", "seed-1").composition_fingerprint
        == generate_initial_world("world-2", "seed-2").composition_fingerprint
    )


# ---------------------------------------------------------------------------
# Absent stamps, which is the actual historical world.
# ---------------------------------------------------------------------------


def test_a_world_stored_before_versioning_does_not_claim_todays_stamps():
    """Absent must stay absent -- the whole defect in one assertion.

    If ``from_dict`` defaulted the missing stamps to the current constants,
    every pre-versioning world would load claiming to be today's.
    """
    document = _generated().to_dict()
    del document["generator_version"]
    del document["composition_version"]
    del document["composition_fingerprint"]

    restored = WorldState.from_dict(document)
    assert restored.generator_version is None
    assert restored.composition_version is None
    assert restored.composition_fingerprint is None

    origin = characterize_world(restored)
    assert not origin.is_fresh
    assert origin.label == "restored"
    assert any("predates version stamping" in reason for reason in origin.reasons)
    assert any("names no composition revision" in reason for reason in origin.reasons)
    assert any("roster was never recorded" in reason for reason in origin.reasons)


def test_the_authentic_historical_world_is_characterized_as_restored():
    """The 13/22/4/8 case, as it actually was.

    It was never an older SCHEMA -- schema 1 is the only shape this project has
    written.  It is a current-shape document with no content stamps and a roster
    that is not today's, which is why the schema-migration path is not where
    this world is handled.
    """
    fixture = Path(__file__).resolve().parent / "fixtures" / "historical_world_13_22_4_8.json"
    world = WorldState.from_dict(json.loads(fixture.read_text(encoding="utf-8")))
    assert world_census(world) == {
        "plants": 13, "fixtures": 22, "animals": 4, "collectibles": 8,
    }
    origin = characterize_world(world)
    assert not origin.is_fresh
    assert origin.migrated is False
    assert origin.label == "restored"
    assert composition_acceptance(world) == "not_reviewed"


def test_an_explicit_null_stamp_is_also_absent_not_zero():
    """"Cannot say what made me" and "made by generator 0" are different."""
    document = _generated().to_dict()
    document["generator_version"] = None
    assert WorldState.from_dict(document).generator_version is None


def test_an_older_generator_is_named_rather_than_summarised():
    """"Stale" is not actionable; "built by 0, current is 1" is."""
    world = replace(_generated(), generator_version=GENERATOR_VERSION - 1)
    origin = characterize_world(world)
    assert not origin.is_fresh
    assert any(
        f"built by generator {GENERATOR_VERSION - 1}" in reason for reason in origin.reasons
    )


def test_every_way_of_being_stale_is_reported_separately():
    """Collapsing several defects into one sentence hides all but one."""
    world = replace(
        _generated(),
        generator_version=None,
        composition_version=COMPOSITION_VERSION - 1,
        composition_fingerprint="plants=|fixtures=|animals=|collectibles=",
        migrated_from_schema=0,
    )
    origin = characterize_world(world)
    assert len(origin.reasons) == 4, origin.reasons


# ---------------------------------------------------------------------------
# Migration: a real transform, or a refusal.
# ---------------------------------------------------------------------------


def test_an_unregistered_older_schema_is_refused_not_renumbered():
    """Renumbering a document is not migrating it.

    A document written under a genuinely different shape held different fields;
    assigning it the current number produces a world claiming to be current
    while holding whatever the old shape held.  There is no registered
    transform, because there has never been another shape -- so this refuses.
    """
    document = _generated().to_dict()
    document["schema_version"] = WORLD_SCHEMA_VERSION - 1
    with pytest.raises(ValueError, match="no migration is registered"):
        migrate_world_document(document)


def test_a_document_from_a_newer_build_is_refused_rather_than_downgraded():
    """Ignoring fields we do not understand silently discards what they meant."""
    document = _generated().to_dict()
    document["schema_version"] = WORLD_SCHEMA_VERSION + 1
    with pytest.raises(ValueError, match="newer build"):
        migrate_world_document(document)


def test_a_current_document_is_left_exactly_alone():
    """A migration that rewrites what it need not touch would mark a fresh
    world as migrated."""
    document = _generated().to_dict()
    assert migrate_world_document(document) == document
    state, origin = load_migrated_world(document)
    assert origin == LOAD_STORED
    assert characterize_world(state).is_fresh


# ---------------------------------------------------------------------------
# Load origin: lineage and arrival are different facts.
# ---------------------------------------------------------------------------


def test_load_origin_is_reported_because_no_stamp_can_record_it():
    """Being loaded is an event, not a lineage.

    A world with every stamp current can still have come out of storage after a
    hundred interactions.  Nothing inside the document can say so.
    """
    document = _generated().to_dict()
    state, origin = load_migrated_world(document)
    assert origin == LOAD_STORED
    assert characterize_world(state).is_fresh, "its LINEAGE is fresh"


def test_a_review_refuses_a_world_that_was_loaded_even_when_its_lineage_is_fresh():
    """The condition is fresh lineage AND generated in this process.

    This is the case a version-stamp check can never catch, and the one a visual
    review most needs: a perfectly current world that is nonetheless not what
    the code just produced.
    """
    world = _generated()
    assert require_fresh_composition(world, LOAD_GENERATED).is_fresh

    with pytest.raises(NotAFreshComposition) as caught:
        require_fresh_composition(world, LOAD_STORED)
    assert "not generated in this process" in str(caught.value)

    with pytest.raises(NotAFreshComposition):
        require_fresh_composition(world, LOAD_SCHEMA_MIGRATED)


def test_a_review_refuses_a_stale_world_and_carries_every_reason():
    """The reasons ride on the exception so a caller reports them without
    re-deriving them."""
    document = _generated().to_dict()
    del document["generator_version"]
    stale = WorldState.from_dict(document)

    with pytest.raises(NotAFreshComposition) as caught:
        require_fresh_composition(stale, LOAD_GENERATED)
    assert caught.value.origin.reasons
    assert "predates version stamping" in str(caught.value)


def test_the_load_origin_argument_is_mandatory_and_validated():
    """The permissive answer must never be the one you get by forgetting.

    An earlier version defaulted this to ``generated``, so a caller who simply
    omitted it certified a loaded world as newly generated -- and a test
    enshrined that bypass rather than catching it.
    """
    world = _generated()
    with pytest.raises(TypeError):
        require_fresh_composition(world)          # type: ignore[call-arg]
    with pytest.raises(ValueError, match="unknown load origin"):
        require_fresh_composition(world, "probably_generated")


# ---------------------------------------------------------------------------
# Storage and cross-language agreement.
# ---------------------------------------------------------------------------


def test_the_stamps_survive_a_round_trip_through_storage():
    """A field that does not survive serialisation is not a stored fact."""
    world = _generated()
    restored = WorldState.from_dict(json.loads(json.dumps(world.to_dict())))
    assert restored.generator_version == GENERATOR_VERSION
    assert restored.composition_version == COMPOSITION_VERSION
    assert restored.composition_fingerprint == world.composition_fingerprint


def test_the_browser_and_python_constants_are_the_same_numbers():
    """Two generators stamping different versions would make the label lie."""
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
