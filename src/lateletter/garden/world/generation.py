"""Viewport-independent initial world generation from stable domain streams."""

from __future__ import annotations

from dataclasses import replace

from .animals import ANIMAL_SPECIES, create_animal
from .collectibles import COLLECTIBLE_CATALOG, create_collectible
from .fixtures import (
    REQUIRED_FUNCTIONAL_FIXTURES,
    fixture_cells,
    layout_is_safe,
)
from .model import FixtureState, Vec2, WorldState, new_world, stable_id
from .plants import SPECIES_CATALOG, create_plant
from .rng import DeterministicRNG, derive_seed


MINIMUM_WORLD_WIDTH = 64
MINIMUM_WORLD_HEIGHT = 40


def _shuffle(values: tuple[str, ...], rng: DeterministicRNG) -> list[str]:
    result = list(values)
    for index in range(len(result) - 1, 0, -1):
        swap = rng.randbelow(index + 1)
        result[index], result[swap] = result[swap], result[index]
    return result


def _fixture_layout(state: WorldState) -> tuple[FixtureState, ...]:
    rng = DeterministicRNG(derive_seed(state.seed, "layout", "fixtures"))
    catalog_ids = _shuffle(REQUIRED_FUNCTIONAL_FIXTURES, rng)
    columns = 5
    spacing_x = max(8, (state.world_width - 8) // columns)
    rows = (len(catalog_ids) + columns - 1) // columns
    start_y = max(2, state.world_height - (rows * 5 + 3))
    fixtures: list[FixtureState] = []
    for index, catalog_id in enumerate(catalog_ids):
        column = index % columns
        row = index // columns
        position = Vec2(4 + column * spacing_x, start_y + row * 5)
        fixture_id = stable_id("fixture", state.world_id, catalog_id)
        fixtures.append(FixtureState(
            fixture_id=fixture_id,
            catalog_id=catalog_id,
            position=position,
            rotation=(rng.randbelow(4) * 90),
            authored=False,
        ))
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


def generate_initial_world(
    world_id: str,
    seed: int | str | bytes,
    *,
    world_width: int = 120,
    world_height: int = 80,
) -> WorldState:
    """Generate canonical world coordinates; viewport size is not an input."""
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

    plants = []
    for species_id in sorted(SPECIES_CATALOG):
        plant_id = stable_id("plant", state.world_id, species_id)
        position = _pick_free_position(state, ("plant", species_id), occupied, margin=3)
        plants.append(create_plant(state.seed, plant_id, species_id, position))
    state = replace(state, plants=tuple(plants))

    blocked = set(occupied).union(plant.position for plant in plants)
    animals = []
    for species_id in sorted(ANIMAL_SPECIES):
        animal_id = stable_id("animal", state.world_id, species_id)
        position = _pick_free_position(state, ("animal", species_id), blocked, margin=2)
        animals.append(create_animal(state.seed, animal_id, species_id, position))
    state = replace(state, animals=tuple(animals))

    collectibles = []
    for catalog_id in sorted(COLLECTIBLE_CATALOG):
        collectible_id = stable_id("collectible", state.world_id, catalog_id)
        position = _pick_free_position(state, ("collectible", catalog_id), blocked, margin=2)
        collectibles.append(create_collectible(collectible_id, catalog_id, position))
    state = replace(state, collectibles=tuple(collectibles))

    if not layout_is_safe(state):
        raise ValueError("generated Garden layout failed safety validation")
    return state


def required_catalog_coverage(state: WorldState) -> dict[str, frozenset[str]]:
    return {
        "plants": frozenset(plant.species_id for plant in state.plants),
        "fixtures": frozenset(fixture.catalog_id for fixture in state.fixtures),
        "animals": frozenset(animal.species_id for animal in state.animals),
        "collectibles": frozenset(item.family for item in state.collectibles),
    }
