from __future__ import annotations

from dataclasses import replace

from lateletter.garden.world import LIVE_RUNTIME_WIRED
from lateletter.garden.world.model import (
    FixtureState,
    PlantState,
    Vec2,
    WorldState,
    new_world,
    stable_id,
)


def test_package_is_explicitly_not_live():
    assert LIVE_RUNTIME_WIRED is False


def test_stable_ids_depend_only_on_explicit_inputs():
    assert stable_id("plant", "world", "rose", 7) == stable_id(
        "plant", "world", "rose", 7,
    )
    assert stable_id("plant", "world", "rose", 7).startswith("plant:")
    assert stable_id("plant", "world", "rose", 7) != stable_id(
        "plant", "world", "rose", 8,
    )


def test_canonical_serialization_sorts_entity_collections():
    base = new_world("world", 42)
    first = replace(
        base,
        plants=(
            PlantState("plant:z", "rose", Vec2(2, 2)),
            PlantState("plant:a", "oak", Vec2(1, 1)),
        ),
        fixtures=(
            FixtureState("fixture:z", "bench", Vec2(4, 4)),
            FixtureState("fixture:a", "lantern", Vec2(3, 3)),
        ),
        inventory=("collectible:z", "collectible:a"),
    )
    second = replace(
        base,
        plants=tuple(reversed(first.plants)),
        fixtures=tuple(reversed(first.fixtures)),
        inventory=tuple(reversed(first.inventory)),
    )
    assert first.canonical_bytes() == second.canonical_bytes()


def test_world_round_trip_is_byte_identical(world):
    restored = WorldState.from_dict(world.to_dict())
    assert restored == world
    assert restored.canonical_bytes() == world.canonical_bytes()


def test_world_coordinates_do_not_include_viewport_dimensions(world):
    data = world.to_dict()
    assert "viewport" not in data
    assert data["plants"][0]["position"] == [4, 5]
    assert data["world_width"] == 40
    assert data["world_height"] == 30
