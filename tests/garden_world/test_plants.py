from __future__ import annotations

from dataclasses import replace

from lateletter.garden.world.model import Vec2
from lateletter.garden.world.plants import (
    SPECIES_CATALOG,
    age_visibility_hash,
    create_plant,
    validate_topology,
    visible_organs,
)


def test_catalog_has_at_least_twelve_distinct_persistent_species():
    assert len(SPECIES_CATALOG) >= 12
    assert {definition.category for definition in SPECIES_CATALOG.values()} >= {
        "tree", "shrub", "vine", "grass", "herb", "flower", "aquatic",
    }


def test_one_hundred_seeds_produce_valid_stable_rooted_topologies():
    for seed in range(100):
        for species_id, definition in SPECIES_CATALOG.items():
            plant_id = f"plant:{species_id}:{seed}"
            first = create_plant(seed, plant_id, species_id, Vec2(10, 10))
            second = create_plant(seed, plant_id, species_id, Vec2(99, 77))
            assert not validate_topology(first)
            assert definition.minimum_organs <= len(first.topology) <= definition.maximum_organs
            assert first.topology == second.topology
            assert first.topology[0].parent_id is None
            assert len({node.node_id for node in first.topology}) == len(first.topology)


def test_age_visibility_changes_without_regenerating_topology():
    plant = create_plant("seed", "plant:rose", "rose", Vec2(5, 5))
    topology = plant.topology
    at_birth = min(node.birth_time for node in topology)
    after_maturity = max(node.maturity_time for node in topology) + 1
    early = visible_organs(plant, at_birth)
    late = visible_organs(plant, after_maturity)
    assert len(early) < len(late)
    assert age_visibility_hash(plant, at_birth) != age_visibility_hash(plant, after_maturity)
    assert plant.topology is topology


def test_age_visibility_hash_is_canonical_across_topology_storage_order():
    plant = create_plant("seed", "plant:rose", "rose", Vec2(5, 5))
    effective_time = max(node.maturity_time for node in plant.topology) + 1
    reordered = replace(plant, topology=tuple(reversed(plant.topology)))
    assert age_visibility_hash(plant, effective_time) == age_visibility_hash(
        reordered, effective_time,
    )


def test_topology_streams_are_domain_separated_by_plant_identity():
    first = create_plant(42, "plant:a", "oak", Vec2(1, 1))
    second = create_plant(42, "plant:b", "oak", Vec2(1, 1))
    assert first.topology != second.topology
