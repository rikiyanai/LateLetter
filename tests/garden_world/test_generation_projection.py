from __future__ import annotations

import json
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
from lateletter.garden.world.model import OrganNode, Vec2, WorldState, canonical_json_bytes
from lateletter.garden.world.projection import PLANT_MATURITY_STAGES, project_scene


def test_initial_generation_is_deterministic_and_catalog_complete():
    first = generate_initial_world("world", 42, world_width=64, world_height=40)
    second = generate_initial_world("world", 42, world_width=64, world_height=40)
    assert first.canonical_bytes() == second.canonical_bytes()
    coverage = required_catalog_coverage(first)
    assert coverage["plants"] == frozenset(SPECIES_CATALOG)
    assert coverage["fixtures"] == frozenset(REQUIRED_FUNCTIONAL_FIXTURES)
    assert coverage["animals"] == frozenset(ANIMAL_SPECIES)
    assert coverage["collectibles"] == frozenset(COLLECTIBLE_FAMILIES)
    assert first.ui.camera.x == first.world_width // 2
    fixture_rows = [fixture.position.y for fixture in first.fixtures]
    assert min(fixture_rows) <= first.ui.camera.y <= max(fixture_rows)


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
                "node_id", "parent_id", "kind", "offset", "offset_milli",
                "maturity_progress", "maturity_stage_index", "maturity_stage",
                "glyph_family", "bloom_state",
            }
    fixtures = [item for item in serialized["objects"] if item["kind"] == "fixture"]
    assert all("connected_mask" in item["semantic_state"] for item in fixtures)
    for fixture in fixtures:
        cells = fixture["semantic_state"]["render_cells"]
        assert len(cells) == fixture["hotspot"]["width"] * fixture["hotspot"]["height"]
        assert all(set(cell) == {"dx", "dy", "connected_mask"} for cell in cells)
        assert fixture["semantic_state"]["semantic_description"]
    animals = [item for item in serialized["objects"] if item["kind"] == "animal"]
    assert {item["semantic_state"]["presentation_variant"].split(".")[0] for item in animals} == set(ANIMAL_SPECIES)
    assert all("bond tier" in item["semantic_state"]["semantic_description"] for item in animals)


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


def test_plant_projection_has_seven_monotonic_interpolated_restart_stages():
    world = generate_initial_world("maturity-world", 42, world_width=64, world_height=40)
    plant = world.plants[0]
    root = OrganNode(
        "organ:root", None, "root", 0, 0, Vec2(0, -1), 1, "root",
    )
    branch = OrganNode(
        "organ:branch", root.node_id, "branch", 0, 1_000,
        Vec2(1, -1), 7, "branch",
    )
    world = replace(
        world,
        plants=(replace(plant, topology=(root, branch)),),
        fixtures=(), animals=(), collectibles=(),
    )
    times = (0, 167, 334, 500, 667, 834, 1_000)
    records = []
    for effective_time in times:
        projection = project_scene(replace(world, effective_time=effective_time))
        projected_plant = next(item for item in projection.objects if item.kind == "plant")
        records.append(next(
            item for item in projected_plant.semantic_state["visible_organs"]
            if item["node_id"] == branch.node_id
        ))
    assert [item["maturity_stage_index"] for item in records] == list(range(7))
    assert [item["maturity_stage"] for item in records] == list(PLANT_MATURITY_STAGES)
    assert [item["maturity_progress"] for item in records] == list(times)
    assert [item["offset_milli"][0] for item in records] == [time * 7 for time in times]
    assert all(
        records[index]["offset_milli"][0] <= records[index + 1]["offset_milli"][0]
        for index in range(6)
    )
    assert len({item["node_id"] for item in records}) == 1

    persisted = canonical_json_bytes(replace(world, effective_time=667).to_dict())
    restarted = WorldState.from_dict(json.loads(persisted))
    assert project_scene(restarted).to_dict() == project_scene(
        replace(world, effective_time=667),
    ).to_dict()


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
