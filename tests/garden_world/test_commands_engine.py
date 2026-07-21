from __future__ import annotations

from dataclasses import replace

from lateletter.garden.world.commands import CommandKind, command
from lateletter.garden.world.engine import advance_live_world, dispatch
from lateletter.garden.world.clock import reconcile_offline
from lateletter.garden.world.fixtures import fixture_active_affordances, fixture_presentation_state
from lateletter.garden.world.model import (
    EVENT_TRACE_LIMIT, PROCESSED_COMMAND_LIMIT, UNDO_STACK_LIMIT,
)
from lateletter.garden.world.plants import create_plant, visible_organs


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


def test_live_dwell_is_partition_deterministic_and_pause_is_authoritative(world):
    observed = replace(world, last_observed_wall_time=1_000)
    one_call = advance_live_world(observed, 600)
    partitioned = observed
    for _ in range(120):
        partitioned = advance_live_world(partitioned, 5)
    assert one_call.canonical_bytes() == partitioned.canonical_bytes()
    assert one_call.effective_time == observed.effective_time + 600
    assert one_call.last_observed_wall_time == 1_600
    reopened, report = reconcile_offline(one_call, 1_600)
    assert reopened.canonical_bytes() == one_call.canonical_bytes()
    assert report.elapsed_seconds == 0
    assert any(entry.kind == "live_tick" for entry in one_call.event_trace)
    assert len([entry for entry in advance_live_world(observed, 3_600).event_trace
                if entry.kind == "live_tick"]) == 120
    paused = replace(observed, ui=replace(observed.ui, motion_paused=True))
    paused_advanced = advance_live_world(paused, 600)
    assert paused_advanced.effective_time == paused.effective_time
    assert paused_advanced.last_observed_wall_time == 1_600
    resumed = replace(
        paused_advanced, ui=replace(paused_advanced.ui, motion_paused=False),
    )
    reopened_paused, paused_report = reconcile_offline(resumed, 1_600)
    assert reopened_paused.effective_time == paused.effective_time
    assert reopened_paused.last_observed_wall_time == 1_600
    assert paused_report.elapsed_seconds == 0


def test_command_idempotency_trace_and_undo_windows_are_bounded(world):
    state = world
    recent = None
    for sequence in range(1, 701):
        x = 7 if sequence % 2 else 8
        recent = command(
            state.world_id, sequence, "move_fixture", target_id="fixture:bench",
            args={"x": x, "y": 5},
        )
        state, result = dispatch(state, recent)
        assert result.accepted, result.reason
    assert len(state.processed_commands) == PROCESSED_COMMAND_LIMIT
    assert len(state.event_trace) == EVENT_TRACE_LIMIT
    assert len(state.undo_stack) == UNDO_STACK_LIMIT
    restored = type(state).from_dict(state.to_dict())
    assert restored.canonical_bytes() == state.canonical_bytes()
    assert recent is not None
    duplicate, result = dispatch(restored, recent)
    assert result.accepted and not result.changed
    assert duplicate.canonical_bytes() == restored.canonical_bytes()


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


def test_place_plant_creates_full_stable_topology_and_undo_removes_it(world):
    state, result, _ = apply(
        world,
        "place",
        args={"object_kind": "plant", "catalog_id": "willow", "x": 20, "y": 20},
    )
    plant_id = str(result.details["plant_id"])
    plant = next(item for item in state.plants if item.plant_id == plant_id)
    assert len(plant.topology) > 1
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
    assert "overlaps a plant" in result.reason
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


def test_tending_advances_persistent_topology_and_fixture_tend_is_meaningful(world):
    plant = create_plant(world.seed, "plant:rose", "rose", world.plants[0].position)
    state = replace(world, plants=(plant,))
    before_topology = state.plants[0].topology
    before_visible = len(visible_organs(state.plants[0], state.effective_time))
    state, _, _ = apply(
        state, "tend", target="plant:rose", args={"care_action": "water"},
    )
    assert state.plants[0].topology != before_topology
    assert len(visible_organs(state.plants[0], state.effective_time)) > before_visible

    tending_fixture = replace(
        state.fixtures[0], fixture_id="fixture:trellis", catalog_id="trellis",
    )
    state = replace(state, fixtures=(tending_fixture,))
    state, _, _ = apply(
        state, "tend", target="fixture:trellis", args={"care_action": "train"},
    )
    assert state.fixtures[0].interaction_count == 1
    assert state.fixtures[0].last_interaction == "train"


def test_every_plant_care_action_is_persistent_and_transplant_is_undoable(world):
    plant = create_plant(world.seed, "plant:rose", "rose", world.plants[0].position)
    state = replace(world, plants=(plant,))
    original = plant
    for care in ("observe", "water", "prune", "train", "rest"):
        state, _, _ = apply(state, "tend", target="plant:rose", args={"care_action": care})
    shaped = state.plants[0]
    assert shaped.topology != original.topology
    assert shaped.dormant
    state, _, _ = apply(state, "tend", target="plant:rose", args={
        "care_action": "transplant", "x": 22, "y": 22,
    })
    assert state.plants[0].position.x == 22
    state, _, _ = apply(state, "undo")
    assert state.plants[0].position == original.position


def test_fixture_catalog_verbs_change_fixture_state(world):
    state = world
    state, result, _ = apply(
        state, "primary_interact", target="fixture:bench", args={"fixture_action": "sit"},
    )
    fixture = state.fixtures[0]
    assert fixture.last_interaction == "sit"
    assert fixture.authored_state["sit_count"] == 1
    assert "sit" in result.summary.lower()


def test_fixture_state_machine_controls_visible_state_and_animal_affordances(world):
    birdbath = replace(world.fixtures[0], fixture_id="fixture:birdbath", catalog_id="birdbath")
    state = replace(world, fixtures=(birdbath,))
    assert fixture_presentation_state(birdbath) == "empty"
    assert "bathe" not in fixture_active_affordances(birdbath)
    state, _, _ = apply(
        state, "primary_interact", target="fixture:birdbath",
        args={"fixture_action": "refill"},
    )
    filled = state.fixtures[0]
    assert fixture_presentation_state(filled) == "full"
    assert {"drink", "bathe"}.issubset(fixture_active_affordances(filled))
