from __future__ import annotations

from dataclasses import replace

from lateletter.garden.world.commands import CommandKind, command
from lateletter.garden.world.engine import dispatch


def apply(state, kind, *, target=None, args=None):
    value = command(
        state.world_id,
        state.command_sequence + 1,
        kind,
        target_id=target,
        args=args,
    )
    updated, result = dispatch(state, value)
    assert result.accepted, result.reason
    return updated, result, value


def test_command_vocabulary_is_exact_and_complete():
    assert {item.value for item in CommandKind} == {
        "move_focus",
        "pan",
        "inspect",
        "primary_interact",
        "open_actions",
        "tend",
        "feed",
        "play",
        "collect",
        "place",
        "move_fixture",
        "undo",
        "open_journal",
        "pause_motion",
        "back",
    }


def test_all_fifteen_commands_have_real_state_behavior(world):
    state, _, _ = apply(world, "move_focus", args={"target_id": "animal:rabbit"})
    assert state.ui.focus_id == "animal:rabbit"

    state, _, _ = apply(state, "pan", args={"dx": 3, "dy": 2})
    assert state.ui.camera.to_list() == [3, 2]

    state, _, _ = apply(state, "inspect", target="plant:rose")
    assert any(entry.object_id == "plant:rose" for entry in state.journal)

    state, _, _ = apply(state, "primary_interact", target="animal:rabbit")
    assert state.animals[0].interaction_count("observe") == 1

    state, result, _ = apply(state, "open_actions", target="animal:rabbit")
    assert state.ui.actions_open_for == "animal:rabbit"
    assert result.available_actions == ("inspect", "feed", "play")

    state, _, _ = apply(state, "tend", target="plant:rose", args={"care_action": "water"})
    assert state.plants[0].growth_points == 2
    assert state.plants[0].tended_count == 1

    state, _, _ = apply(state, "feed", target="animal:rabbit")
    state, _, _ = apply(state, "play", target="animal:rabbit")
    assert state.animals[0].interaction_count("feed") == 1
    assert state.animals[0].interaction_count("play") == 1
    assert state.animals[0].bond_tier == 1

    state, _, _ = apply(state, "collect", target="collectible:feather")
    assert state.inventory == ("collectible:feather",)
    assert next(item for item in state.journal if item.object_id == "collectible:feather").status == "collected"

    state, place_result, _ = apply(
        state,
        "place",
        args={"object_kind": "fixture", "catalog_id": "lantern", "x": 20, "y": 10},
    )
    placed_id = str(place_result.details["fixture_id"])
    assert any(item.fixture_id == placed_id for item in state.fixtures)

    state, _, _ = apply(
        state,
        "move_fixture",
        target=placed_id,
        args={"x": 21, "y": 10, "rotation": 90},
    )
    assert next(item for item in state.fixtures if item.fixture_id == placed_id).position.x == 21

    state, _, _ = apply(state, "undo")
    restored = next(item for item in state.fixtures if item.fixture_id == placed_id)
    assert restored.position.x == 20
    assert restored.rotation == 0

    state, result, _ = apply(state, "open_journal")
    assert state.ui.journal_open
    assert result.details["entries"]

    state, _, _ = apply(state, "pause_motion", args={"paused": True})
    assert state.ui.motion_paused

    state, _, _ = apply(state, "back")
    assert not state.ui.journal_open
    assert len(state.event_trace) == 15


def test_primary_interact_collects_a_collectible(world):
    state, _, _ = apply(world, "primary_interact", target="collectible:feather")
    assert "collectible:feather" in state.inventory


def test_place_plant_creates_stable_root_topology_and_undo_removes_it(world):
    state, result, _ = apply(
        world,
        "place",
        args={"object_kind": "plant", "catalog_id": "willow", "x": 20, "y": 20},
    )
    plant_id = str(result.details["plant_id"])
    plant = next(item for item in state.plants if item.plant_id == plant_id)
    assert len(plant.topology) == 1
    assert plant.topology[0].parent_id is None
    state, _, _ = apply(state, "undo")
    assert all(item.plant_id != plant_id for item in state.plants)


def test_repeated_feeding_has_diminishing_value_and_cannot_full_bond(world):
    state = world
    for _ in range(12):
        state, _, _ = apply(state, "feed", target="animal:rabbit")
    animal = state.animals[0]
    assert animal.bond_points == 6
    assert animal.bond_tier == 0
    assert animal.interaction_count("feed") == 12


def test_duplicate_command_is_idempotent(world):
    value = command(world.world_id, 1, "inspect", target_id="plant:rose")
    state, first = dispatch(world, value)
    duplicate, second = dispatch(state, value)
    assert first.accepted and first.changed
    assert second.accepted and not second.changed
    assert duplicate == state


def test_invalid_commands_do_not_consume_sequence(world):
    value = command(
        world.world_id,
        1,
        "place",
        args={"catalog_id": "bench", "x": 4, "y": 5},
    )
    state, result = dispatch(world, value)
    assert not result.accepted
    assert "occupied" in result.reason
    assert state.command_sequence == 0


def test_pan_is_clamped_to_canonical_world_bounds(world):
    state, _, _ = apply(world, "pan", args={"dx": 999, "dy": -999})
    assert state.ui.camera.to_list() == [39, 0]


def test_back_unwinds_actions_then_focus(world):
    state, _, _ = apply(world, "move_focus", args={"target_id": "plant:rose"})
    state, _, _ = apply(state, "open_actions", target="plant:rose")
    state, _, _ = apply(state, "back")
    assert state.ui.actions_open_for is None
    assert state.ui.focus_id == "plant:rose"
    state, _, _ = apply(state, "back")
    assert state.ui.focus_id is None
