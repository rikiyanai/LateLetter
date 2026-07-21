from __future__ import annotations

from dataclasses import replace

from lateletter.garden.world.animals import ANIMAL_SPECIES
from lateletter.garden.world.collectibles import COLLECTIBLE_FAMILIES
from lateletter.garden.world.fixtures import (
    REQUIRED_FUNCTIONAL_FIXTURES,
    layout_is_safe,
)
from lateletter.garden.world.generation import (
    generate_initial_world,
    required_catalog_coverage,
)
from lateletter.garden.world.plants import SPECIES_CATALOG
from lateletter.garden.world.projection import project_scene


def test_initial_generation_is_deterministic_and_catalog_complete():
    first = generate_initial_world("world", 42, world_width=64, world_height=40)
    second = generate_initial_world("world", 42, world_width=64, world_height=40)
    assert first.canonical_bytes() == second.canonical_bytes()
    coverage = required_catalog_coverage(first)
    assert coverage["plants"] == frozenset(SPECIES_CATALOG)
    assert coverage["fixtures"] == frozenset(REQUIRED_FUNCTIONAL_FIXTURES)
    assert coverage["animals"] == frozenset(ANIMAL_SPECIES)
    assert coverage["collectibles"] == frozenset(COLLECTIBLE_FAMILIES)


def test_one_thousand_initial_layouts_are_safe_and_viewport_independent():
    for seed in range(1_000):
        world = generate_initial_world(
            f"world:{seed}",
            seed,
            world_width=64,
            world_height=40,
        )
        assert layout_is_safe(world), seed
        assert len(world.plants) == len(SPECIES_CATALOG)
        assert len(world.fixtures) == len(REQUIRED_FUNCTIONAL_FIXTURES)
        assert len(world.animals) == 4
        assert {item.family for item in world.collectibles} == set(COLLECTIBLE_FAMILIES)


def test_scene_projection_is_renderer_neutral_and_stably_ordered():
    world = generate_initial_world("world", 42, world_width=64, world_height=40)
    projection = project_scene(world)
    reordered = replace(
        world,
        plants=tuple(reversed(world.plants)),
        fixtures=tuple(reversed(world.fixtures)),
        animals=tuple(reversed(world.animals)),
        collectibles=tuple(reversed(world.collectibles)),
    )
    assert projection.to_dict() == project_scene(reordered).to_dict()
    assert projection.camera == world.ui.camera
    assert len(projection.objects) == (
        len(world.plants) + len(world.fixtures) + len(world.animals) + len(world.collectibles)
    )
    serialized = projection.to_dict()
    forbidden = {"glyph", "css", "dom", "terminal_cell", "viewport"}
    for item in serialized["objects"]:
        assert forbidden.isdisjoint(item)
        assert item["actions"]
        assert item["hotspot"]["width"] >= 1
        assert item["hotspot"]["height"] >= 1
    plants = [item for item in serialized["objects"] if item["kind"] == "plant"]
    assert plants
    for plant in plants:
        for organ in plant["semantic_state"]["visible_organs"]:
            assert set(organ) == {
                "node_id", "parent_id", "kind", "offset", "glyph_family", "bloom_state",
            }
    fixtures = [item for item in serialized["objects"] if item["kind"] == "fixture"]
    assert all("connected_mask" in item["semantic_state"] for item in fixtures)


def test_projection_age_changes_semantics_without_changing_object_identity():
    world = generate_initial_world("world", 42, world_width=64, world_height=40)
    early = project_scene(world)
    late = project_scene(replace(world, effective_time=10_000_000))
    early_plants = {item.object_id: item for item in early.objects if item.kind == "plant"}
    late_plants = {item.object_id: item for item in late.objects if item.kind == "plant"}
    assert early_plants.keys() == late_plants.keys()
    assert any(
        early_plants[key].semantic_state["topology_hash"]
        != late_plants[key].semantic_state["topology_hash"]
        for key in early_plants
    )


def test_projection_surfaces_bounded_absence_inventory_and_lasting_memorial():
    world = generate_initial_world("world", 42, world_width=64, world_height=40)
    world = replace(world, program_state={
        "absence_summary": ["One", "Two", "Three"],
        "absence_elapsed_seconds": 99,
        "story_complete": True,
        "memorial": {"active": True, "completed_at": 88, "examined_gifts": [], "lasting": True},
    })
    scene = project_scene(world).scene
    assert scene["absence_summary"] == ["One", "Two", "Three"]
    assert scene["absence_elapsed_seconds"] == 99
    assert scene["memorial"]["active"] is True
