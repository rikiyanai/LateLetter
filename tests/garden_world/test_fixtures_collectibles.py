from __future__ import annotations

from dataclasses import replace

from lateletter.garden.world.collectibles import (
    COLLECTIBLE_CATALOG,
    COLLECTIBLE_FAMILIES,
)
from lateletter.garden.world.commands import command
from lateletter.garden.world.engine import dispatch
from lateletter.garden.world.fixtures import (
    CONNECTED_GROUPS,
    CONNECTED_TILE_MASKS,
    FIXTURE_CATALOG,
    REQUIRED_FUNCTIONAL_FIXTURES,
    connected_tile_key,
    connected_tile_mask,
    layout_is_safe,
    validate_fixture_placement,
)
from lateletter.garden.world.model import FixtureState, Vec2


def test_required_fixture_catalog_has_actions_and_systemic_affordances():
    assert set(REQUIRED_FUNCTIONAL_FIXTURES) == {
        "bench", "fence_gate", "sundial", "trellis", "birdbath", "lantern",
        "pond", "mailbox", "stepping_stones", "bridge", "planter",
        "table_chairs", "well", "arbor", "wind_chime", "shed_edge",
        "tool_rack", "watering_can", "compost", "basket", "sign",
        "memorial_stone",
    }
    for fixture in FIXTURE_CATALOG.values():
        assert fixture.direct_actions
        assert fixture.affordances


def test_all_five_connected_groups_define_all_sixteen_masks():
    assert set(CONNECTED_TILE_MASKS) == set(CONNECTED_GROUPS)
    for group in CONNECTED_GROUPS:
        assert CONNECTED_TILE_MASKS[group] == tuple(range(16))
        assert len({connected_tile_key(group, mask) for mask in range(16)}) == 16
    assert connected_tile_mask(north=True, east=True, south=True, west=True) == 15
    assert connected_tile_mask(north=False, east=True, south=False, west=True) == 10


def test_fixture_placement_rejects_overlap_and_out_of_bounds(world):
    assert validate_fixture_placement(world, "bench", Vec2(39, 29))
    assert validate_fixture_placement(world, "lantern", Vec2(8, 5))
    assert not validate_fixture_placement(world, "lantern", Vec2(20, 20))


def test_layout_safety_rejects_unreachable_animal(world):
    fences = tuple(
        FixtureState(f"fence:{x}", "fence", Vec2(x, 6))
        for x in range(world.world_width)
    )
    trapped_animal = replace(world.animals[0], position=Vec2(10, 8))
    state = replace(
        world,
        plants=(),
        fixtures=fences,
        animals=(trapped_animal,),
        collectibles=(),
    )
    assert not layout_is_safe(state)


def test_collectible_catalog_has_four_families_and_accessible_copy():
    assert {item.family for item in COLLECTIBLE_CATALOG.values()} == set(COLLECTIBLE_FAMILIES)
    for item in COLLECTIBLE_CATALOG.values():
        assert item.label
        assert item.description
        assert item.provenance in {
            "procedural", "recipient-grown", "animal-given", "author-authored",
        }


def test_inspect_and_collect_automatically_create_journal_paths(world):
    inspect = command(world.world_id, 1, "inspect", target_id="collectible:feather")
    state, result = dispatch(world, inspect)
    assert result.accepted
    assert next(item for item in state.journal if item.object_id == "collectible:feather").status == "observed"
    collect = command(state.world_id, 2, "collect", target_id="collectible:feather")
    state, result = dispatch(state, collect)
    assert result.accepted
    assert next(item for item in state.journal if item.object_id == "collectible:feather").status == "collected"
    assert "collectible:feather" in state.inventory
