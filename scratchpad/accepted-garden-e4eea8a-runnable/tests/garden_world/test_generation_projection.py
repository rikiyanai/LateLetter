from __future__ import annotations

import json
from dataclasses import replace

import pytest

from lateletter.garden.world.animals import ANIMAL_SPECIES
from lateletter.garden.world.collectibles import COLLECTIBLE_CATALOG, COLLECTIBLE_FAMILIES
from lateletter.garden.world.fixtures import (
    REQUIRED_FUNCTIONAL_FIXTURES,
    STARTER_FIXTURES,
    layout_is_safe,
)
from lateletter.garden.world.generation import (
    REVIEW_PENDING_ANIMAL_SPECIES,
    REVIEW_PENDING_COLLECTIBLES,
    REVIEW_PENDING_PLANT_SPECIES,
    STARTER_ANIMAL_SPECIES,
    STARTER_COLLECTIBLES,
    STARTER_PLANT_SPECIES,
    generate_initial_world,
    required_catalog_coverage,
)
from lateletter.garden.world.plants import SPECIES_CATALOG
from lateletter.garden.world.model import OrganNode, Vec2, WorldState, canonical_json_bytes
from lateletter.garden.world.projection import PLANT_MATURITY_STAGES, project_scene


def _canonical_starter_camera(world_width: int, world_height: int) -> Vec2:
    """Scale the canonical 500/650 composition anchor, not a viewport centre."""
    return Vec2(
        ((world_width - 1) * 500 + 500) // 1_000,
        ((world_height - 1) * 650 + 500) // 1_000,
    )


def test_initial_generation_is_deterministic_and_cozy_not_a_catalog_dump():
    first = generate_initial_world("world", 42, world_width=64, world_height=40)
    second = generate_initial_world("world", 42, world_width=64, world_height=40)
    assert first.canonical_bytes() == second.canonical_bytes()
    coverage = required_catalog_coverage(first)
    assert coverage["plants"] == frozenset(STARTER_PLANT_SPECIES)
    assert coverage["fixtures"] == frozenset(STARTER_FIXTURES)
    assert coverage["animals"] == frozenset(STARTER_ANIMAL_SPECIES)
    assert tuple(animal.species_id for animal in first.animals) == STARTER_ANIMAL_SPECIES
    assert set(STARTER_ANIMAL_SPECIES) < set(ANIMAL_SPECIES)
    assert {item.label for item in first.collectibles} == {
        COLLECTIBLE_CATALOG[catalog_id].label for catalog_id in STARTER_COLLECTIBLES
    }
    assert coverage["collectibles"] < frozenset(COLLECTIBLE_FAMILIES)
    assert len(first.fixtures) < len(REQUIRED_FUNCTIONAL_FIXTURES)
    assert set(STARTER_PLANT_SPECIES) < set(SPECIES_CATALOG)
    assert first.ui.camera == _canonical_starter_camera(
        first.world_width,
        first.world_height,
    )
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
        assert len(world.plants) == len(STARTER_PLANT_SPECIES)
        for plant in world.plants:
            visible_count = sum(node.birth_time <= 0 for node in plant.topology)
            assert 4 <= visible_count < len(plant.topology), (seed, plant.plant_id)
        assert len(world.fixtures) == len(STARTER_FIXTURES)
        assert tuple(animal.species_id for animal in world.animals) == STARTER_ANIMAL_SPECIES
        assert {item.label for item in world.collectibles} == {
            COLLECTIBLE_CATALOG[catalog_id].label for catalog_id in STARTER_COLLECTIBLES
        }


def test_generation_refuses_unsupported_and_duplicated_starter_rosters():
    """A bad roster must fail loudly, with the same words the browser uses.

    The exact message strings are asserted, not just the exception type. The
    browser generator carries the identical assertions in
    `tests/garden_adapters/test_garden_world.mjs`, so if either implementation
    changes what it refuses -- or merely how it says so -- one of the two
    suites goes red. That is the cheapest available parity check short of
    running both and diffing, and it is what stops the two generators drifting
    into accepting different rosters.
    """
    # Unknown ids are refused by name, and the message lists what IS allowed
    # so the caller does not have to go reading anchor tables.
    with pytest.raises(ValueError) as unknown:
        generate_initial_world("x", 1, plant_species=("nope",))
    assert str(unknown.value) == (
        "unsupported plant species requested: 'nope' (supported: "
        "hydrangea, lavender, meadow_grass, oak, rose, sunflower, "
        "water_lily, willow)"
    )

    # Duplicates matter because every object id is a pure function of the
    # species: asking twice used to yield two records sharing one id.
    with pytest.raises(ValueError) as duplicate:
        generate_initial_world("x", 1, plant_species=("oak", "oak"))
    assert str(duplicate.value) == "duplicate plant species requested: 'oak'"

    with pytest.raises(ValueError) as animal:
        generate_initial_world("x", 1, animal_species=("dragon",))
    assert str(animal.value) == (
        "unsupported animal species requested: 'dragon' "
        "(supported: bird, cat, rabbit, turtle)"
    )

    with pytest.raises(ValueError) as collectible:
        generate_initial_world("x", 1, collectibles=("nope",))
    assert str(collectible.value) == (
        "unsupported collectible requested: 'nope' "
        "(supported: fallen_acorn, lavender_sprig, oak_leaf)"
    )

    # The empty roster is NOT an error -- it is the current default, and means
    # "deliberately none" rather than "nothing was asked for".
    empty = generate_initial_world("x", 1, plant_species=(), animal_species=(), collectibles=())
    assert (empty.plants, empty.animals, empty.collectibles) == ((), (), ())


def test_point_and_click_model_declares_primary_actions_and_opportunities():
    """SPEC 7.8.3.1/7.8.3.2, asserted behaviourally rather than visually.

    The composition this runs on is under review and not approved, so nothing
    here asserts a glyph, a colour or a position -- only what the world OFFERS
    and what performing it does. The browser carries the same assertions in
    `tests/garden_adapters/test_garden_world.mjs`.
    """
    from lateletter.garden.world.commands import command
    from lateletter.garden.world.engine import dispatch

    world = generate_initial_world("interaction:contract", "slice")
    scene = project_scene(world)
    bench = next(item for item in scene.objects if item.semantic_name == "Garden bench")
    lantern = next(item for item in scene.objects if item.semantic_name == "Lantern")

    # The world declares the act and its wording, so a renderer reading this
    # has nothing left to infer.
    assert bench.primary_action == {
        "command": "primary_interact",
        "args": {"fixture_action": "sit"},
        "label": "Sit on the garden bench",
    }
    # The lantern's primary is the SAFE act. Lighting is state-dependent and
    # must not be what a plain click does.
    assert lantern.primary_action["args"]["fixture_action"] == "observe"
    assert bench.opportunities == ()

    # Exactly one side of the lit/unlit state is ever on offer.
    assert len(lantern.opportunities) == 1
    assert lantern.opportunities[0]["label"] == "Light the lantern"
    assert lantern.opportunities[0]["command"] == "primary_interact"
    assert lantern.opportunities[0]["args"]["fixture_action"] == "light"

    # Performing it goes through the ordinary dispatcher: the opportunity owns
    # no state and adds no command of its own.
    lit, result = dispatch(world, command(
        world.world_id, world.command_sequence + 1,
        lantern.opportunities[0]["command"],
        target_id=lantern.object_id,
        args=lantern.opportunities[0]["args"],
    ))
    assert result.accepted
    lit_lantern = next(
        item for item in project_scene(lit).objects
        if item.object_id == lantern.object_id
    )
    assert lit_lantern.semantic_state["authored_state"]["lit"] is True
    # The offer flips rather than vanishing: still exactly one, now the
    # opposite act, under a DIFFERENT id so a renderer can tell it is new.
    assert len(lit_lantern.opportunities) == 1
    assert lit_lantern.opportunities[0]["label"] == "Put out the lantern"
    assert (
        lit_lantern.opportunities[0]["opportunity_id"]
        != lantern.opportunities[0]["opportunity_id"]
    )

    # Every projected object carries both fields, so a renderer never has to
    # test whether a key exists before reading it.
    for item in scene.to_dict()["objects"]:
        assert "primary_action" in item
        assert isinstance(item["opportunities"], list)


def test_scene_projection_is_renderer_neutral_and_stably_ordered():
    world = generate_initial_world(
        "world", 42, world_width=64, world_height=40,
        plant_species=REVIEW_PENDING_PLANT_SPECIES,
        animal_species=REVIEW_PENDING_ANIMAL_SPECIES,
        collectibles=REVIEW_PENDING_COLLECTIBLES,
    )
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
    assert serialized["observed_time"] is None
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
    # Compared against what this world was ASKED for, not against the default
    # starter list. The default is empty while the animal art awaits per-asset
    # approval, and this test needs a populated world to have animals to check
    # at all -- so it requests `REVIEW_PENDING_ANIMAL_SPECIES` explicitly above.
    assert {
        item["semantic_state"]["presentation_variant"].split(".")[0]
        for item in animals
    } == set(REVIEW_PENDING_ANIMAL_SPECIES)
    assert all("bond tier" in item["semantic_state"]["semantic_description"] for item in animals)


def test_scene_projection_separates_observed_civil_time_from_elapsed_time():
    world = replace(
        generate_initial_world("clock-world", 42),
        effective_time=37,
        last_observed_wall_time=1_783_510_400,
    )
    projection = project_scene(world)
    assert projection.effective_time == 37
    assert projection.observed_time == 1_783_510_400
    assert projection.to_dict()["observed_time"] == 1_783_510_400


def test_projection_age_changes_semantics_without_changing_object_identity():
    world = generate_initial_world(
        "world", 42, world_width=64, world_height=40,
        plant_species=REVIEW_PENDING_PLANT_SPECIES,
        animal_species=REVIEW_PENDING_ANIMAL_SPECIES,
        collectibles=REVIEW_PENDING_COLLECTIBLES,
    )
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
    world = generate_initial_world(
        "maturity-world", 42, world_width=64, world_height=40,
        plant_species=REVIEW_PENDING_PLANT_SPECIES,
        animal_species=REVIEW_PENDING_ANIMAL_SPECIES,
        collectibles=REVIEW_PENDING_COLLECTIBLES,
    )
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
    world = generate_initial_world(
        "world", 42, world_width=64, world_height=40,
        plant_species=REVIEW_PENDING_PLANT_SPECIES,
        animal_species=REVIEW_PENDING_ANIMAL_SPECIES,
        collectibles=REVIEW_PENDING_COLLECTIBLES,
    )
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
