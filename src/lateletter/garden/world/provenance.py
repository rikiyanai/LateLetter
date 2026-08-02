"""Say where a Garden world came from, so a review knows what it is looking at.

WHY THIS MODULE EXISTS
----------------------
A localhost review of the browser Garden once opened a persisted world holding
13 plants, 22 fixtures, 4 animals and 8 collectibles, and it was read as the
current starter -- which generates 8 plants, 10 fixtures, 4 animals and 3
collectibles.  Nothing lied.  The stored document was shape-valid, it loaded
without complaint, and there was no field anywhere in it that could have said
"an older generator made me".  The reviewer had no way to tell a restored world
from a fresh one, so an obsolete starter was reviewed as today's candidate.

The fix is not a better reviewer.  It is a world that can answer the question.
``model.py`` now carries three independent stamps -- schema, generator,
composition -- and this module turns them into the one sentence a review needs:
is this composition FRESH, or is it something restored from before?

WHAT "FRESH" MEANS HERE
-----------------------
Fresh means every stamp matches what this code produces today: the shape is
current, the content was built by today's generator, and the population is the
composition the operator approved.  Anything else is not fresh, and the reasons
are enumerated rather than summarised, because "stale" is not actionable and
"built by generator 1, current is 2" is.

WHAT A MIGRATION MAY AND MAY NOT DO
-----------------------------------
A migration upgrades the SHAPE of a stored document so today's code can read
it.  It never rewrites the generator or composition stamps, because migrating a
document does not regenerate its content: a world built by an old generator is
an old world afterwards exactly as it was before.  This is the single rule that
stops a migration from laundering an obsolete starter into a fresh-looking one.
"""

from __future__ import annotations

from dataclasses import dataclass

from .model import (
    COMPOSITION_VERSION,
    GENERATOR_VERSION,
    WORLD_SCHEMA_VERSION,
    WorldState,
)


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
    :param composition_version: which approved composition the population came
        from, or None for the same reason
    :param migrated: whether a shape migration has been applied to this world
    :param census: how many of each kind of object the world actually holds --
        the observable fact that first exposed the problem, kept beside the
        claimed versions so the two can be compared by eye
    :param reasons: why this world is not fresh; empty exactly when it is
    """

    schema_version: int
    generator_version: int | None
    composition_version: int | None
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


def characterize_world(state: WorldState) -> WorldOrigin:
    """Decide, from the world alone, whether it is a fresh composition.

    Every reason is stated separately.  A world can be stale in more than one
    way at once -- an old generator AND an unapproved composition -- and
    collapsing that into a single "stale" would hide half of it.

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
        reasons.append("no composition_version: the population was never stamped as approved")
    elif state.composition_version != COMPOSITION_VERSION:
        reasons.append(
            f"composition {state.composition_version}, current is {COMPOSITION_VERSION}"
        )

    if state.migrated_from_schema is not None:
        reasons.append(f"shape migrated from schema {state.migrated_from_schema}")

    return WorldOrigin(
        schema_version=state.schema_version,
        generator_version=state.generator_version,
        composition_version=state.composition_version,
        migrated=state.migrated_from_schema is not None,
        census=world_census(state),
        reasons=tuple(reasons),
    )


def require_fresh_composition(state: WorldState) -> WorldOrigin:
    """Refuse to proceed unless this world is a fresh composition.

    Called by any surface whose result would be misread otherwise -- above all
    a visual review, where the whole point is to look at what today's code
    produces.  Refusing loudly is the difference between a review of the
    current Garden and a review of something restored from before it.

    :param state: the world about to be reviewed or captured
    :returns: the origin, when it is fresh
    :raises NotAFreshComposition: when it is not, carrying every reason
    """
    origin = characterize_world(state)
    if not origin.is_fresh:
        raise NotAFreshComposition(origin)
    return origin


def migrate_world_shape(state: WorldState) -> WorldState:
    """Bring a stored world's SHAPE up to date, and nothing else.

    What this deliberately does not do is touch ``generator_version`` or
    ``composition_version``.  A migration reads and rewrites a document; it does
    not rebuild the garden inside it.  Leaving the content stamps alone is what
    guarantees a migrated world can never afterwards pass as fresh -- and the
    migration records the schema it came from, so the fact of having been
    migrated survives too.

    :param state: a world loaded from storage
    :returns: the same world at the current schema, marked as migrated; the
        input unchanged when it was already current and unmigrated
    """
    if state.schema_version == WORLD_SCHEMA_VERSION and state.migrated_from_schema is None:
        return state
    from dataclasses import replace

    return replace(
        state,
        schema_version=WORLD_SCHEMA_VERSION,
        # Record the ORIGINAL schema, not the one we happen to be migrating
        # from on a second pass: a world migrated twice still came from where it
        # came from.
        migrated_from_schema=(
            state.migrated_from_schema
            if state.migrated_from_schema is not None
            else state.schema_version
        ),
    )
