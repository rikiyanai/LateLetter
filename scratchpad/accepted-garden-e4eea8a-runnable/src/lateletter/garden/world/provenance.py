"""Say where a Garden world came from, so a review knows what it is looking at.

WHY THIS MODULE EXISTS
----------------------
A localhost review of the browser Garden once opened a persisted world holding
13 plants, 22 fixtures, 4 animals and 8 collectibles, and it was read as the
current starter.  Nothing lied.  The
stored document was shape-valid, it loaded
without complaint, and there was no field anywhere in it that could have said
"an older generator made me".  The reviewer had no way to tell a restored world
from a fresh one, so an obsolete starter was reviewed as today's candidate.

The fix is not a better reviewer.  It is a world that can answer the question.
``model.py`` now carries three independent stamps -- schema, generator,
composition -- and this module turns them into the one sentence a review needs:
is this composition FRESH, or is it something restored from before?

WHAT "FRESH" MEANS HERE, AND WHAT IT DOES NOT
---------------------------------------------
Fresh is a statement about LINEAGE only: the shape is current, the content was
built by today's generator, and the population still matches the composition its
own stamp describes.  Anything else is not fresh, and the reasons are enumerated
rather than summarised, because "stale" is not actionable and "built by
generator 1, current is 2" is.

Fresh does NOT mean the operator approved anything.  Approval is a verdict a
person gives, held in ``docs/garden-composition-acceptance.json`` and read by
:func:`composition_acceptance`; no arrangement of numbers written by the
generator can stand in for one.  Fresh also does not mean "newly generated": a
world can have perfect stamps and still have come out of storage after a hundred
interactions, which is why load origin is carried separately.

WHAT A MIGRATION MAY AND MAY NOT DO
-----------------------------------
A migration upgrades the SHAPE of a stored document so today's code can read
it.  It never rewrites the generator or composition stamps, because migrating a
document does not regenerate its content: a world built by an old generator is
an old world afterwards exactly as it was before.  This is the single rule that
stops a migration from laundering an obsolete starter into a fresh-looking one.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any, Iterable, Mapping

from .model import (
    COMPOSITION_VERSION,
    GENERATOR_VERSION,
    WORLD_SCHEMA_VERSION,
    WorldState,
)


# The operator verdict register. Kept out of the world document entirely: a
# verdict is a fact about what a person decided, not a field a generator writes.
_ACCEPTANCE_REGISTER = (
    Path(__file__).resolve().parents[4] / "docs" / "garden-composition-acceptance.json"
)


# How a world arrived in this process, which is a different question from what
# its lineage is.
#
# A world can be built by today's generator from today's roster and STILL have
# been loaded out of storage after a hundred interactions -- watered plants,
# collected items, a moved camera. Its stamps are all current, so its lineage is
# fresh, and it is nonetheless not a newly generated world. A visual review that
# needs "what today's code produces, untouched" cannot get that from version
# stamps at all, because no stamp records an event that happens at load time.
LOAD_GENERATED = "generated"               # produced in this process, right now
LOAD_STORED = "loaded"                     # read from storage at the current schema
LOAD_SCHEMA_MIGRATED = "schema_migrated"   # read from storage and transformed

# The whole set, so a caller cannot pass a value nobody defined. A guard that
# silently accepts an unrecognised origin is a guard that can be switched off by
# a typo.
LOAD_ORIGINS = frozenset({LOAD_GENERATED, LOAD_STORED, LOAD_SCHEMA_MIGRATED})


class NotAFreshComposition(RuntimeError):
    """Raised when a surface that requires a fresh world was given another.

    Carrying the reasons on the exception rather than only in its message means
    a caller can report them without re-deriving them.
    """

    def __init__(self, origin: "WorldOrigin") -> None:
        self.origin = origin
        super().__init__(
            "this world is not a fresh composition: " + "; ".join(origin.reasons)
        )


@dataclass(frozen=True)
class WorldOrigin:
    """Everything a review needs to know about where a world came from.

    :param schema_version: the shape version the document was stored under
    :param generator_version: which generator built the content, or None when
        the world predates version stamping and genuinely cannot say
    :param composition_version: which candidate composition revision the
        population came from, or None for the same reason. It carries no
        approval; see :func:`composition_acceptance`
    :param composition_fingerprint: the roster recorded when the world was
        generated, or None when it was never recorded
    :param observed_fingerprint: the roster the world holds NOW, recomputed
        from its contents. Kept beside the stamped one so a reviewer can see
        which of them changed rather than only that they differ
    :param migrated: whether a shape migration has been applied to this world
    :param census: how many of each kind of object the world actually holds --
        the observable fact that first exposed the problem, kept beside the
        claimed versions so the two can be compared by eye
    :param reasons: why this world is not fresh; empty exactly when it is
    """

    schema_version: int
    generator_version: int | None
    composition_version: int | None
    composition_fingerprint: str | None
    observed_fingerprint: str
    migrated: bool
    census: dict[str, int]
    reasons: tuple[str, ...]

    @property
    def is_fresh(self) -> bool:
        """True only when nothing at all distinguishes this from a new world."""
        return not self.reasons

    @property
    def label(self) -> str:
        """One word for a review surface to print beside its capture."""
        return "fresh" if self.is_fresh else ("migrated" if self.migrated else "restored")

    def to_dict(self) -> dict[str, object]:
        """A serialisable form, for review manifests and test receipts."""
        return {
            "label": self.label,
            "is_fresh": self.is_fresh,
            "schema_version": self.schema_version,
            "generator_version": self.generator_version,
            "composition_version": self.composition_version,
            "composition_fingerprint": self.composition_fingerprint,
            "observed_fingerprint": self.observed_fingerprint,
            "migrated": self.migrated,
            "census": dict(self.census),
            "reasons": list(self.reasons),
        }


def world_census(state: WorldState) -> dict[str, int]:
    """Count what the world actually contains.

    This is the observable half of the answer.  The version stamps say what a
    world CLAIMS to be; the census says what it IS, and the 13/22/4/8 case was
    found by someone noticing the two did not agree.

    :param state: the world to count
    :returns: counts keyed by kind, in the order a reviewer reads them
    """
    return {
        "plants": len(state.plants),
        "fixtures": len(state.fixtures),
        "animals": len(state.animals),
        "collectibles": len(state.collectibles),
    }


def composition_fingerprint(state: WorldState) -> str:
    """Describe the AUTHORED composition a world holds, as one comparable string.

    A version number on its own is an unverified assertion: a world can carry
    the current number over an arbitrary population and nothing notices.  This
    is the evidence half.  It is computed at generation time and stored, and
    recomputed here whenever a world is characterized; when the two disagree,
    the world's contents are no longer the composition its stamp names.

    It covers the roster AND the authored placement inputs -- the anchor each
    identity was placed against.  Roster names alone were not enough: moving
    every anchor produces a visibly different garden out of an identical species
    list, so an operator verdict bound to names only would survive a layout it
    had never seen.  What it does NOT cover is the seed-derived position two
    identical compositions land on; different seeds are the same composition.

    The form is deliberately readable rather than hashed.  A reviewer looking at
    a rejected world benefits from seeing which entry differs; a digest would
    only tell them that something did.

    :param state: the world to describe
    :returns: a canonical string, stable across processes and languages
    """
    from .generation import (
        STARTER_ANIMAL_ANCHORS,
        STARTER_COLLECTIBLE_ANCHORS,
        STARTER_FIXTURE_ANCHORS,
        STARTER_PLANT_ANCHORS,
    )

    def _entries(identities: Iterable[str], anchors: Mapping[str, Any]) -> str:
        # Each identity is written with the anchor it was authored against, so a
        # change to the anchor table changes the fingerprint. An identity with no
        # anchor is written as `?`, which is itself a difference worth seeing.
        parts = []
        for identity in sorted(identities):
            anchor = anchors.get(identity)
            parts.append(
                f"{identity}@{anchor[0]},{anchor[1]}" if anchor else f"{identity}@?"
            )
        return ",".join(parts)

    return "|".join((
        "plants=" + _entries(
            (plant.species_id for plant in state.plants), STARTER_PLANT_ANCHORS,
        ),
        "fixtures=" + _entries(
            (fixture.catalog_id for fixture in state.fixtures), STARTER_FIXTURE_ANCHORS,
        ),
        "animals=" + _entries(
            (animal.species_id for animal in state.animals), STARTER_ANIMAL_ANCHORS,
        ),
        "collectibles=" + _entries(
            (item.family for item in state.collectibles), STARTER_COLLECTIBLE_ANCHORS,
        ),
    ))


def characterize_world(state: WorldState) -> WorldOrigin:
    """Decide, from the world alone, whether it is a fresh composition.

    Every reason is stated separately.  A world can be stale in more than one
    way at once -- an old generator AND a roster that no longer matches its own
    stamp -- and collapsing that into a single "stale" would hide half of it.

    Note what this does NOT decide: whether the operator has accepted the
    composition.  That is a verdict given by a person, held in
    ``docs/garden-composition-acceptance.json``, and read by
    :func:`composition_acceptance`.  A version number written by the code can
    never mean a person approved something.

    :param state: the world to characterize
    :returns: a :class:`WorldOrigin`, whose ``is_fresh`` is True only when
        there is nothing to report
    """
    reasons: list[str] = []

    if state.schema_version != WORLD_SCHEMA_VERSION:
        reasons.append(
            f"stored under schema {state.schema_version}, current is {WORLD_SCHEMA_VERSION}"
        )

    # An absent stamp is reported as absent rather than as a mismatch, because
    # "made by an unknown generator" and "made by generator 1 when 2 is current"
    # are different situations: the first cannot even be compared.
    if state.generator_version is None:
        reasons.append("no generator_version: this world predates version stamping")
    elif state.generator_version != GENERATOR_VERSION:
        reasons.append(
            f"built by generator {state.generator_version}, current is {GENERATOR_VERSION}"
        )

    if state.composition_version is None:
        reasons.append("no composition_version: this world names no composition revision")
    elif state.composition_version != COMPOSITION_VERSION:
        reasons.append(
            f"composition revision {state.composition_version}, current is {COMPOSITION_VERSION}"
        )

    # The stamp against the contents. An unstamped fingerprint is reported
    # separately from a mismatched one: "never described" and "described, and
    # the description is now wrong" are different states, and the second is the
    # one that means somebody changed the world after it was generated.
    observed = composition_fingerprint(state)
    if state.composition_fingerprint is None:
        reasons.append("no composition_fingerprint: the roster was never recorded")
    elif state.composition_fingerprint != observed:
        reasons.append(
            "contents no longer match the stamped composition: "
            f"stamped {state.composition_fingerprint!r}, holds {observed!r}"
        )

    if state.migrated_from_schema is not None:
        reasons.append(f"shape migrated from schema {state.migrated_from_schema}")

    return WorldOrigin(
        schema_version=state.schema_version,
        generator_version=state.generator_version,
        composition_version=state.composition_version,
        composition_fingerprint=state.composition_fingerprint,
        observed_fingerprint=observed,
        migrated=state.migrated_from_schema is not None,
        census=world_census(state),
        reasons=tuple(reasons),
    )


def require_fresh_composition(state: WorldState, load_origin: str) -> WorldOrigin:
    """Refuse to proceed unless this world is a freshly generated composition.

    Called by any surface whose result would be misread otherwise -- above all
    a visual review, where the whole point is to look at what today's code
    produces.  Refusing loudly is the difference between a review of the
    current Garden and a review of something restored from before it.

    TWO conditions, because they are two different facts.  The lineage must be
    fresh (every stamp current and the roster still matching), and the world
    must have been GENERATED in this process rather than loaded.  A world with
    perfect stamps that came out of storage after a hundred interactions has a
    fresh lineage and is not a fresh composition, and nothing in its stamps
    could ever say so -- no stamp records an event that happens at load time.

    :param state: the world about to be reviewed or captured
    :param load_origin: how this world arrived; one of ``generated``,
        ``loaded``, ``schema_migrated``. MANDATORY and validated. An earlier
        draft defaulted it to ``generated``, so a caller who simply forgot the
        argument certified a loaded world as newly generated -- the permissive
        answer was the one you got by not thinking about it, which is the worst
        possible default for a guard
    :returns: the origin, when it is fresh
    :raises ValueError: when ``load_origin`` is not one of the three
    :raises NotAFreshComposition: when the world is not a fresh composition
    """
    if load_origin not in LOAD_ORIGINS:
        raise ValueError(
            f"unknown load origin {load_origin!r}; expected one of "
            + ", ".join(sorted(LOAD_ORIGINS))
        )
    origin = characterize_world(state)
    reasons = list(origin.reasons)
    if load_origin != LOAD_GENERATED:
        reasons.append(
            f"this world was {load_origin}, not generated in this process"
        )
    if reasons:
        raise NotAFreshComposition(
            origin if reasons == list(origin.reasons)
            else replace(origin, reasons=tuple(reasons))
        )
    return origin


def composition_acceptance(state: WorldState, register: Mapping[str, Any] | None = None) -> str:
    """What the OPERATOR said about this world's composition.

    Read from ``docs/garden-composition-acceptance.json``, never inferred from
    a version stamp.  A stamp is written by the code that generated the world;
    a verdict is given by a person, and no arrangement of numbers can stand in
    for one.  An earlier draft did exactly that -- it described
    ``composition_version`` as "the population the operator reviewed and
    approved", which made every generated world claim an approval that has
    never been granted for any composition.

    The verdict binds to the revision AND the fingerprint together, so
    re-rostering under the same revision number inherits nothing: approval
    attaches to what was actually looked at.

    :param state: the world whose composition is in question
    :param register: an already-loaded register, for tests; read from disk when
        omitted
    :returns: one of ``accepted`` / ``rejected`` / ``not_reviewed``. An
        unstamped world is ``not_reviewed``, because there is nothing to look up
    """
    if state.composition_version is None or state.composition_fingerprint is None:
        return "not_reviewed"
    if register is None:
        register = json.loads(_ACCEPTANCE_REGISTER.read_text(encoding="utf-8"))
    key = f"{state.composition_version}:{state.composition_fingerprint}"
    record = register.get("records", {}).get(key)
    if not record:
        return "not_reviewed"
    return str(record.get("verdict", "not_reviewed"))


# Transforms that bring an older stored SHAPE up to the next one, keyed by the
# schema they read.
#
# It is EMPTY, and that is the honest state: schema 1 is the only shape this
# project has ever written, so there is no historical document for a transform
# to have been written against. An earlier draft "migrated" an old schema by
# assigning the current number to it, which proves that a number can be
# reassigned and nothing else -- a document written under a genuinely different
# shape would have had different fields, and renumbering it would have produced
# a world that claimed to be current while holding whatever the old shape held.
#
# So an unregistered old schema is REFUSED rather than renumbered. When a real
# schema 2 arrives, its transform is registered here with a fixture of an
# authentic schema 1 document to run it against.
SCHEMA_MIGRATIONS: dict[int, Any] = {}


def migrate_world_document(data: Mapping[str, Any]) -> dict[str, Any]:
    """Bring a stored DOCUMENT up to the current schema, and nothing else.

    This works on the raw document rather than on a :class:`WorldState`,
    because ``WorldState.from_dict`` refuses any schema but the current one --
    so by the time a world exists as an object, migration is already too late.
    A migration has to happen between reading the file and constructing the
    state, which is where this sits.

    What it deliberately does not do is touch ``generator_version`` or
    ``composition_version``.  A migration reads and rewrites a document; it does
    not rebuild the garden inside it.  Leaving the content stamps alone is the
    single rule that keeps a migration honest: if it stamped today's generator
    onto the world it upgraded, then upgrading an obsolete starter would make it
    indistinguishable from one built today -- the masquerade, reintroduced by
    the very code meant to prevent it.

    :param data: a document as read from storage
    :returns: a new document at the current schema, marked as migrated; a plain
        copy when it was already current and unmigrated
    :raises ValueError: when the document was written by a NEWER build (reading
        a future document by ignoring the fields we do not understand would
        silently discard whatever they meant), or when it was written under an
        older schema for which no transform is registered
    """
    document = dict(data)
    stored_schema = int(document.get("schema_version", 0))

    if stored_schema > WORLD_SCHEMA_VERSION:
        raise ValueError(
            f"world schema {stored_schema} was written by a newer build "
            f"than this one, which understands {WORLD_SCHEMA_VERSION}"
        )
    if stored_schema == WORLD_SCHEMA_VERSION:
        return document

    # Walk the registered transforms one schema at a time. Each step must be a
    # real transform written against a real old shape: renumbering a document
    # is not migrating it, and a document written under a different shape would
    # have held different fields, so simply calling it current would produce a
    # world claiming to be something it is not.
    original_schema = stored_schema
    while stored_schema < WORLD_SCHEMA_VERSION:
        transform = SCHEMA_MIGRATIONS.get(stored_schema)
        if transform is None:
            raise ValueError(
                f"no migration is registered from world schema {stored_schema}; "
                "refusing to renumber a document written under a shape this build "
                "has never seen"
            )
        document = transform(document)
        stored_schema += 1

    document["schema_version"] = WORLD_SCHEMA_VERSION
    # Record the ORIGINAL schema, not the one we happen to be migrating from on
    # a second pass: a world migrated twice still came from where it came from.
    if document.get("migrated_from_schema") is None:
        document["migrated_from_schema"] = original_schema
    return document


def load_migrated_world(data: Mapping[str, Any]) -> tuple[WorldState, str]:
    """Read a stored document, migrating its shape if it needs it.

    The pairing matters more than either half: a caller that migrates without
    loading has a dict nobody validated, and a caller that loads without
    migrating gets an exception on any older world.  This is the entry point
    storage should use.

    :param data: a document as read from storage
    :returns: the world, and the load origin -- ``loaded`` or
        ``schema_migrated``. Never ``generated``: nothing that came out of
        storage was generated here, and returning the origin rather than
        leaving the caller to guess is the point
    """
    migrated = migrate_world_document(data)
    origin = (
        LOAD_SCHEMA_MIGRATED
        if migrated.get("schema_version") != data.get("schema_version")
        else LOAD_STORED
    )
    return WorldState.from_dict(migrated), origin
