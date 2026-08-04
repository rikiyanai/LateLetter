"""Viewport-independent initial world generation from stable domain streams."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import replace

from .animals import create_animal
from .collectibles import COLLECTIBLE_CATALOG, create_collectible
from .fixtures import (
    FIXTURE_CATALOG,
    STARTER_FIXTURES,
    fixture_cells,
    layout_is_safe,
)
from .model import (
    COMPOSITION_VERSION,
    GENERATOR_VERSION,
    FixtureState,
    Vec2,
    WorldState,
    new_world,
    stable_id,
)
from .plants import SPECIES_CATALOG, create_plant
from .rng import DeterministicRNG, derive_seed


MINIMUM_WORLD_WIDTH = 64
MINIMUM_WORLD_HEIGHT = 40

# EMPTIED 2026-07-31, pending per-asset visual approval.
#
# The starter world used to place five plants, one cat and one collectible by
# default. The operator reviewed and accepted the ten fixtures; none of this
# content was ever submitted, and on seeing it in the scene they rejected it.
#
# This is not a capability removal. Every species remains defined and placeable
# and the catalogues are untouched -- an author can still place any of them.
# What changes is that the DEFAULT scene no longer ships art nobody approved.
# Each entry returns here once its drawing has been through per-asset
# acceptance under SPEC 7.10.
#
# These tuples must stay in step with `STARTER_*` in `web/garden-world.mjs`;
# the two implementations are held to identical starter output by the world
# conformance tests.
# PARTIALLY REFILLED 2026-08-01, from the legacy art port.
#
# The operator granted the legacy archive a standing visual approval on
# 2026-08-01 ("PLANTS ANIMATIONS IN LEGACY ARE APPROVED VISUALLY") and ordered
# the archived drawings to replace the unapproved placeholders. `oak` and
# `sunflower` are now drawn entirely from the archive -- picture and wind sway
# both -- so they are approved art and may stand in the default scene again.
#
# The other three species the default scene carried before the removal
# (`hydrangea`, `meadow_grass`, `lavender`) are NOT back, because the archive
# does not draw them: it names oak, willow, pine, sunflower and lily and nothing
# else. They would still be renderer-authored placeholders, which is the exact
# thing the removal was for.
#
# The cat is not back either, and the reason is narrower. Its walk, its face and
# its retreat are all archived, but a resting animal in this Garden is asleep
# and the archive contains no sleeping anything -- so a cat that settles would
# fall through to a renderer-authored pose. One unapproved pose is enough to
# keep it out; see `web/garden-legacy-art.mjs`, the deliberate absence of a
# `rest` entry.
#
# Collectibles remain empty. Nothing in the archive draws them.
STARTER_PLANT_SPECIES: tuple[str, ...] = ("rose",)
STARTER_ANIMAL_SPECIES: tuple[str, ...] = ()
STARTER_COLLECTIBLES: tuple[str, ...] = ()

# Exactly what the default scene carried until 2026-07-31, kept as a named set
# rather than deleted outright.
#
# Two reasons it earns a name. It records what was removed, so restoring an
# entry after its art is approved is a one-line move rather than an
# archaeological dig through history. And it gives the tests that exercise
# plant growth, animal behaviour and collectible pickup a way to ask for a
# populated world explicitly -- those features did not go away, only their
# unapproved presence in the DEFAULT scene did.
#
# Passing this to `generate_initial_world` reproduces the pre-removal world
# exactly. It must never become the default again without per-asset approval.
REVIEW_PENDING_PLANT_SPECIES: tuple[str, ...] = (
    "oak", "hydrangea", "meadow_grass", "lavender", "sunflower",
)
REVIEW_PENDING_ANIMAL_SPECIES: tuple[str, ...] = ("cat",)
REVIEW_PENDING_COLLECTIBLES: tuple[str, ...] = ("fallen_acorn",)

# Canonical starter composition, expressed in thousandths of the world extent.
# These are semantic relationships, not viewport coordinates: the pond, bridge
# and water lily form one water garden; the trellis and rose form another. A
# renderer may crop the world, but it must not invent relationships by repacking
# records.
#
# THE STARTER TERRAIN ROOMS (operator decision, 2026-08-04)
# ---------------------------------------------------
# These anchors author relationships, not even spacing. The bench is directly
# behind the pond; stepping stones approach from one side; the lantern occupies
# the far transition band near that room. This belongs here because a renderer
# that drags props together would create a second, viewport-dependent owner.
STARTER_FIXTURE_ANCHORS = {
    "pond": (400, 900),
    "bridge": (180, 450),
    "birdbath": (80, 720),
    "trellis": (720, 450),
    "arbor": (830, 700),
    # ── the authored water/sitting room ──
    "stepping_stones": (300, 900),
    "bench": (400, 300),
    "lantern": (480, 200),
    "mailbox": (700, 700),
    "planter": (850, 820),
}

# Authored visual identities the seeded fixture-room planner may select.  The
# base ids are the already accepted drawings; every other id is a separate
# not-reviewed atlas asset so a new silhouette cannot inherit the base asset's
# verdict.  Selection is canonical and persisted in ``FixtureState``'s
# ``authored_state``; projection transports it and the renderer only resolves
# the named asset.
POND_VISUAL_ASSETS: tuple[str, ...] = (
    "fixture.pond",
    "fixture.pond_compact",
    "fixture.pond_round",
)
STEPPING_STONE_VISUAL_ASSETS: tuple[str, ...] = (
    "fixture.stepping_stones",
    "fixture.stepping_stones_three",
    "fixture.stepping_stones_five",
)
PLANTER_VISUAL_ASSETS: tuple[str, ...] = (
    "fixture.planter",
    "fixture.planter_one",
    "fixture.planter_three",
)
BENCH_X_OFFSETS: tuple[int, ...] = (-35, 0, 35)
BENCH_Y_ANCHORS: tuple[int, ...] = (260, 300, 340)
# THE DEFAULT ROSE SITS OUTSIDE THE FIXTURE ROW
# ------------------------------------------------------------------------
# `oak` and `sunflower` were anchored at 330 and 590 thousandths, which was a
# sound composition while the world had depth: the oak stood behind the bench
# and the sunflower behind the lantern, and the two rows did not compete.
#
# The walkable plane is now a single line. Depth no longer separates anything,
# so an anchor is only its horizontal position, and 330 and 590 fall directly
# between the authoritative fixture anchors at 250/375/500/625/750. Measured at
# 1600x1000 the packer reacted by pushing the fixtures apart -- the bench moved
# 7 columns, the lantern 7, the stepping stones 4 -- and at 390x844 the two
# displaced fixtures fell out of the initial crop entirely, leaving oak, mailbox
# and sunflower where the operator's own verification requires bench, mailbox
# and lantern.
#
# The operator-authored rose accepted on 2026-08-03 is the canonical starter
# plant: it is the exact approved six-line asset, not the old local placeholder.
# Its earlier interior anchors put the wide drawing inside a fixture room and
# forced the compositor to move canonical fixtures. At 10 it owns the extreme
# left edge without rewriting the pond/stones relationship. Oak and sunflower
# remain available to authored programs; the deployed presentation-native
# planting layer supplies the dense seasonal planting around all six objects.
#
# The remaining six entries are not in the default scene and keep their original
# relationship anchors for authored programs.
STARTER_PLANT_ANCHORS = {
    "water_lily": (220, 420),
    "oak": (150, 300),
    "hydrangea": (360, 570),
    "willow": (900, 180),
    "rose": (70, 820),
    "meadow_grass": (470, 590),
    "lavender": (570, 760),
    "sunflower": (850, 320),
}
STARTER_ANIMAL_ANCHORS = {
    "bird": (100, 680),
    "cat": (350, 780),
    "rabbit": (740, 520),
    "turtle": (220, 500),
}
STARTER_COLLECTIBLE_ANCHORS = {
    "oak_leaf": (330, 290),
    "lavender_sprig": (620, 650),
    "fallen_acorn": (200, 790),
}


def _scaled_anchor(
    state: WorldState,
    anchor: tuple[int, int],
    *,
    margin: int,
    footprint: Vec2 = Vec2(1, 1),
) -> Vec2:
    """Scale one canonical composition anchor without viewport input."""
    max_x = max(margin, state.world_width - footprint.x - margin)
    max_y = max(margin, state.world_height - footprint.y - margin)
    span_x = max(0, max_x - margin)
    span_y = max(0, max_y - margin)
    return Vec2(
        margin + (span_x * anchor[0] + 500) // 1_000,
        margin + (span_y * anchor[1] + 500) // 1_000,
    )


def _pick_near_position(
    state: WorldState,
    desired: Vec2,
    occupied: set[Vec2],
    *,
    margin: int,
) -> Vec2:
    """Take the nearest safe cell, preserving the authored visual grouping."""
    maximum_radius = max(state.world_width, state.world_height)
    for radius in range(maximum_radius + 1):
        for dy in range(-radius, radius + 1):
            dx_abs = radius - abs(dy)
            for dx in ([0] if dx_abs == 0 else [-dx_abs, dx_abs]):
                candidate = Vec2(desired.x + dx, desired.y + dy)
                if not (
                    margin <= candidate.x < state.world_width - margin
                    and margin <= candidate.y < state.world_height - margin
                ):
                    continue
                if candidate not in occupied:
                    occupied.add(candidate)
                    return candidate
    raise ValueError(f"could not place a starter object near {desired!r}")


def _fixture_room_plan(
    state: WorldState,
) -> tuple[dict[str, tuple[int, int]], dict[str, dict[str, object]]]:
    """Choose one canonical water/sitting-room composition from the seed.

    Each axis has its own derived stream.  Adding a pond silhouette therefore
    cannot flip the stepping-stone side or move the bench, which is the seeded
    generation contract in SPEC 7.3.  Values are thousandth anchors or atlas
    identities; no viewport or renderer input exists here.
    """
    pond_asset = DeterministicRNG(derive_seed(
        state.seed, "fixture-room", "pond", "visual-asset",
    )).choice(POND_VISUAL_ASSETS)
    stone_asset = DeterministicRNG(derive_seed(
        state.seed, "fixture-room", "stepping-stones", "visual-asset",
    )).choice(STEPPING_STONE_VISUAL_ASSETS)
    planter_asset = DeterministicRNG(derive_seed(
        state.seed, "fixture-room", "planter", "visual-asset",
    )).choice(PLANTER_VISUAL_ASSETS)
    stone_side = DeterministicRNG(derive_seed(
        state.seed, "fixture-room", "stepping-stones", "side",
    )).choice(("left", "right"))
    bench_x_offset = DeterministicRNG(derive_seed(
        state.seed, "fixture-room", "bench", "x-offset",
    )).choice(BENCH_X_OFFSETS)
    bench_y = DeterministicRNG(derive_seed(
        state.seed, "fixture-room", "bench", "y-anchor",
    )).choice(BENCH_Y_ANCHORS)

    anchors = dict(STARTER_FIXTURE_ANCHORS)
    pond_x, pond_y = anchors["pond"]
    anchors["stepping_stones"] = (
        pond_x - 100 if stone_side == "left" else pond_x + 100,
        pond_y,
    )
    anchors["bench"] = (pond_x + bench_x_offset, bench_y)
    visual_assets = {
        catalog_id: {
            "visual_asset_id": f"fixture.{catalog_id}",
            "fixture_room_role": "independent",
        }
        for catalog_id in STARTER_FIXTURES
    }
    visual_assets["pond"] = {
        "visual_asset_id": pond_asset,
        "fixture_room_role": "water",
    }
    visual_assets["stepping_stones"] = {
        "visual_asset_id": stone_asset,
        "fixture_room_role": "approach",
        "side": stone_side,
    }
    visual_assets["bench"] = {
        "visual_asset_id": "fixture.bench",
        "fixture_room_role": "seat-facing-water",
        "x_offset": bench_x_offset,
        "y_anchor": bench_y,
    }
    visual_assets["planter"] = {
        "visual_asset_id": planter_asset,
        "fixture_room_role": "container",
    }
    return anchors, visual_assets


def _fixture_layout(state: WorldState) -> tuple[FixtureState, ...]:
    rng = DeterministicRNG(derive_seed(state.seed, "layout", "fixtures"))
    anchors, authored_states = _fixture_room_plan(state)
    fixtures: list[FixtureState] = []
    occupied: set[Vec2] = set()
    for catalog_id in STARTER_FIXTURES:
        definition = FIXTURE_CATALOG[catalog_id]
        position = _scaled_anchor(
            state,
            anchors[catalog_id],
            margin=2,
            footprint=definition.footprint,
        )
        fixture_id = stable_id("fixture", state.world_id, catalog_id)
        fixture = FixtureState(
            fixture_id=fixture_id,
            catalog_id=catalog_id,
            position=position,
            rotation=(rng.randbelow(4) * 90),
            authored=False,
            authored_state=authored_states[catalog_id],
        )
        cells = fixture_cells(fixture)
        if occupied.intersection(cells):
            raise ValueError(f"starter fixture anchors overlap: {catalog_id}")
        occupied.update(cells)
        fixtures.append(fixture)
    return tuple(fixtures)


def _pick_free_position(
    state: WorldState,
    domain: tuple[object, ...],
    occupied: set[Vec2],
    *,
    margin: int = 2,
) -> Vec2:
    rng = DeterministicRNG(derive_seed(state.seed, "layout", *domain))
    for _ in range(512):
        candidate = Vec2(
            rng.randint(margin, state.world_width - margin - 1),
            rng.randint(margin, state.world_height - margin - 1),
        )
        if candidate not in occupied:
            occupied.add(candidate)
            return candidate
    raise ValueError(f"could not place {domain!r} safely")


def _validated_roster(
    kind: str,
    requested: tuple[str, ...],
    anchors: dict[str, tuple[int, int]],
) -> tuple[str, ...]:
    """Reject a starter roster this generator cannot honour, before it is used.

    Three things go wrong quietly without this check, so each is turned into a
    loud error naming the offending id:

    * An UNKNOWN id used to surface as a bare `KeyError` from the anchor lookup
      further down -- a stack trace with no statement of what was wrong.
    * An UNSUPPORTED id -- one that exists in its catalogue but has no canonical
      anchor here -- failed the same opaque way. Placement is not a free choice:
      every starter sits at an authored position expressing a relationship
      between objects, so a species with no anchor genuinely cannot be placed
      by this generator, and saying so is more honest than inventing a spot.
    * A DUPLICATE id was accepted outright, and that is the dangerous one. Every
      object id here is `stable_id(kind, world_id, species_id)`, which is a pure
      function of the species -- so asking for a species twice produced two
      records SHARING one id. Anything keyed by object id afterwards (focus,
      dispatch, persistence) would then address an ambiguous target.

    :param kind: Noun used in the error message, e.g. `"plant species"`.
    :param requested: The roster as asked for, already normalised to a tuple.
    :param anchors: Anchor table for this kind; its keys are the supported ids.
    :returns: `requested` unchanged, so callers can use this inline.
    :raises ValueError: On any unknown, unsupported or duplicated id.

    Kept textually in step with `validatedRoster` in `web/garden-world.mjs`:
    both implementations must refuse the same rosters for the same reasons.
    """
    seen: set[str] = set()
    for identifier in requested:
        if identifier in seen:
            raise ValueError(f"duplicate {kind} requested: {identifier!r}")
        seen.add(identifier)
        if identifier not in anchors:
            raise ValueError(
                f"unsupported {kind} requested: {identifier!r} "
                f"(supported: {', '.join(sorted(anchors))})",
            )
    return requested


def generate_initial_world(
    world_id: str,
    seed: int | str | bytes,
    *,
    world_width: int = 120,
    world_height: int = 80,
    plant_species: Sequence[str] | None = None,
    animal_species: Sequence[str] | None = None,
    collectibles: Sequence[str] | None = None,
) -> WorldState:
    """Generate canonical world coordinates; viewport size is not an input.

    :param plant_species: Species to plant, defaulting to `STARTER_PLANT_SPECIES`.
    :param animal_species: Species to place, defaulting to `STARTER_ANIMAL_SPECIES`.
    :param collectibles: Catalog ids to place, defaulting to `STARTER_COLLECTIBLES`.

    The three species arguments exist because the default starter lists were
    emptied on 2026-07-31: their art had never been through per-asset visual
    approval, and the operator rejected it on sight. The CAPABILITY had to
    survive that removal, though -- plant growth, animal behaviour and
    collectible pickup are all still real features with real tests, and those
    tests need a world that actually contains such things.

    So the default answers "what does a recipient see", which is currently only
    approved fixtures, while a caller that needs populated content asks for it
    explicitly. Anything relying on the implicit old default now fails loudly
    rather than quietly rendering unapproved art.

    Keep these parameters in step with `generateInitialWorld` in
    `web/garden-world.mjs`; the two implementations are held to identical
    output by the world conformance tests.
    """
    if world_width < MINIMUM_WORLD_WIDTH or world_height < MINIMUM_WORLD_HEIGHT:
        raise ValueError(
            f"canonical world must be at least {MINIMUM_WORLD_WIDTH}x{MINIMUM_WORLD_HEIGHT}",
        )
    state = new_world(
        world_id,
        seed,
        world_width=world_width,
        world_height=world_height,
    )
    fixtures = _fixture_layout(state)
    state = replace(state, fixtures=fixtures)
    occupied: set[Vec2] = set()
    for fixture in fixtures:
        occupied.update(fixture_cells(fixture))

    # `None` means "use the default scene"; an explicit empty sequence means
    # "deliberately none", and the two must stay distinguishable.
    # Validated before anything is placed, so a bad roster fails with a clear
    # message instead of a partial world or a duplicated object id.
    requested_plants = _validated_roster("plant species", (
        STARTER_PLANT_SPECIES if plant_species is None else tuple(plant_species)
    ), STARTER_PLANT_ANCHORS)
    requested_animals = _validated_roster("animal species", (
        STARTER_ANIMAL_SPECIES if animal_species is None else tuple(animal_species)
    ), STARTER_ANIMAL_ANCHORS)
    requested_collectibles = _validated_roster("collectible", (
        STARTER_COLLECTIBLES if collectibles is None else tuple(collectibles)
    ), STARTER_COLLECTIBLE_ANCHORS)

    plants = []
    plant_age_rng = DeterministicRNG(derive_seed(state.seed, "layout", "plant-ages"))
    for species_id in requested_plants:
        plant_id = stable_id("plant", state.world_id, species_id)
        desired = _scaled_anchor(
            state, STARTER_PLANT_ANCHORS[species_id], margin=3,
        )
        position = _pick_near_position(state, desired, occupied, margin=3)
        # Choose age from this plant's own deterministic topology instead of a
        # wall-time range. That guarantees every starter is established (at
        # least four visible organs) while retaining unborn persistent growth.
        preview = create_plant(state.seed, plant_id, species_id, position)
        birth_times = sorted({node.birth_time for node in preview.topology})
        minimum_visible = max(4, (len(preview.topology) * 55 + 99) // 100)
        maximum_visible = max(minimum_visible, (len(preview.topology) * 85) // 100)
        eligible_ages = [
            age for age in birth_times
            if minimum_visible <= sum(node.birth_time <= age for node in preview.topology)
            <= maximum_visible
        ]
        if not eligible_ages:
            raise ValueError(f"starter topology has no partial established age: {plant_id}")
        planted_at = -plant_age_rng.choice(eligible_ages)
        plants.append(create_plant(
            state.seed, plant_id, species_id, position, planted_at=planted_at,
        ))
    state = replace(state, plants=tuple(plants))

    blocked = set(occupied).union(plant.position for plant in plants)
    animals = []
    for species_id in requested_animals:
        animal_id = stable_id("animal", state.world_id, species_id)
        desired = _scaled_anchor(
            state, STARTER_ANIMAL_ANCHORS[species_id], margin=2,
        )
        position = _pick_near_position(state, desired, blocked, margin=2)
        animals.append(create_animal(state.seed, animal_id, species_id, position))
    state = replace(state, animals=tuple(animals))

    placed_collectibles = []
    for catalog_id in requested_collectibles:
        collectible_id = stable_id("collectible", state.world_id, catalog_id)
        desired = _scaled_anchor(
            state, STARTER_COLLECTIBLE_ANCHORS[catalog_id], margin=2,
        )
        position = _pick_near_position(state, desired, blocked, margin=2)
        placed_collectibles.append(create_collectible(collectible_id, catalog_id, position))
    state = replace(state, collectibles=tuple(placed_collectibles))

    if not layout_is_safe(state):
        raise ValueError("generated Garden layout failed safety validation")
    # Frame the central path room. Wide viewports see both flanking garden
    # rooms; narrow viewports intentionally crop rather than shrinking every
    # canonical object into a single unreadable heap.
    # Horizontally the camera is exactly centred, which is what "canonically
    # centred" means and what the projection contract asserts: with an anchor of
    # 500 the scaling above reduces to world_width // 2 at every world size.
    # The previous 490 was a tenth of a percent short of centre and produced 31
    # in a 64-wide world where 32 is required — visually indistinguishable, but
    # it made the camera depend on world width in a way nothing else did.
    # Vertically the anchor stays at 650 so the frame still sits down in the
    # planted rooms rather than on the horizon.
    camera = _scaled_anchor(state, (500, 650), margin=0)
    state = replace(state, ui=replace(state.ui, camera=camera))

    # Stamp the composition ONLY here, at the end, after every placement has
    # succeeded and the layout has been validated.
    #
    # `new_world` deliberately leaves these unset: it returns an empty world,
    # and stamping there declared 0/0/0/0 to be a whole composition. Every
    # `return` above this point is a raised exception, so a partially generated
    # world can never carry a stamp either -- the stamp means "this population
    # was produced, entire, by this generator", and there is no other place in
    # the code where that is true.
    #
    # The fingerprint is what makes the version number evidence rather than an
    # assertion: it describes the roster that was actually produced, so a custom
    # roster, or a world an author program has since changed, no longer matches
    # its own stamp. See `composition_fingerprint` in provenance.py.
    from .provenance import composition_fingerprint

    # `COMPOSITION_VERSION` names ONE candidate composition -- the declared
    # starter. A world generated from a custom roster is a different
    # composition, so it does not get that number; it gets None, meaning "this
    # population belongs to no named candidate".
    #
    # Without this, every successful generation stamped the same revision, so a
    # one-oak test roster read as the current composition and would have been
    # accepted by a fresh-composition review guard. A number that every roster
    # receives identifies nothing.
    is_declared_starter = (
        tuple(requested_plants) == tuple(STARTER_PLANT_SPECIES)
        and tuple(requested_animals) == tuple(STARTER_ANIMAL_SPECIES)
        and tuple(requested_collectibles) == tuple(STARTER_COLLECTIBLES)
    )

    return replace(
        state,
        generator_version=GENERATOR_VERSION,
        composition_version=COMPOSITION_VERSION if is_declared_starter else None,
        # The fingerprint is recorded either way: a custom world should still be
        # able to say its contents have not changed since it was generated.
        composition_fingerprint=composition_fingerprint(state),
    )


def required_catalog_coverage(state: WorldState) -> dict[str, frozenset[str]]:
    return {
        "plants": frozenset(plant.species_id for plant in state.plants),
        "fixtures": frozenset(fixture.catalog_id for fixture in state.fixtures),
        "animals": frozenset(animal.species_id for animal in state.animals),
        "collectibles": frozenset(item.family for item in state.collectibles),
    }
