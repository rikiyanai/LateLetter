"""Canonical program-to-world materialization contract."""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import shutil
import subprocess

import pytest

from lateletter.garden.materializer import (
    apply_program,
    build_runtime_facts,
    eligible_occurrences,
)
from lateletter.garden.program import ProgramAction, parse_program
from lateletter.garden.world.fixtures import fixture_cells, layout_is_safe
from lateletter.garden.world.generation import generate_initial_world


ROOT = Path(__file__).parents[2]


def _program(*, schedule=None):
    return parse_program({
        "version": 1,
        "evaluator_version": 1,
        "world_state_version": 1,
        "atlas_version": "garden-atlas-1",
        "astronomy_catalog_version": "bright-stars-1",
        "author_timezone": "UTC",
        "variables": {"visits": 0},
        "entities": [
            {"id": "fixture.authored", "kind": "fixture", "catalog_id": "fixture.bench", "position": [11, 11]},
            {"id": "keepsake.authored", "kind": "item", "catalog_id": "old_key", "position": [14, 11]},
            {"id": "plant.authored", "kind": "plant", "catalog_id": "rose", "position": [17, 11]},
        ],
        "animals": [{
            "id": "animal.miso", "species": "animal.cat", "name": "Miso",
            "personality": {"boldness": 91, "curiosity": 73},
            "routine": "evening_patrol",
            "favorite_places": ["fixture.authored"],
            "prohibited_behaviors": ["scratch"],
        }],
        "events": [{
            "id": "welcome",
            "conditions": {"fact": "visit.total", "op": ">=", "value": 0},
            "schedule": schedule,
            "occurrence": "recurring" if schedule else "once",
            "priority": 0,
            "exclusive_group": None,
            "cooldown": None,
            "actions": [
                {"type": "animal.arrive", "target": "animal.miso", "params": {"position": [20, 12], "routine": "morning_rounds"}},
                {"type": "animal.behave", "target": "animal.miso", "params": {"behavior": "greet", "duration_ticks": 12}},
                {"type": "plant.plant", "target": "plant.authored", "params": {"species_id": "rose", "position": [17, 11]}},
                {"type": "plant.grow", "target": "plant.authored", "params": {"amount": 3}},
                {"type": "entity.reveal", "target": "fixture.authored", "params": {"position": [11, 11], "state": "ready"}},
                {"type": "entity.reveal", "target": "keepsake.authored", "params": {"position": [14, 11], "state": "A small key"}},
                {"type": "narrative.show", "target": None, "params": {"kind": "memory", "label": "Welcome", "text": "You are remembered."}},
                {"type": "scene.set", "target": None, "params": {
                    "weather": "clear", "palette": "gold", "sky_mode": "author_fixed",
                    "author_region": {"latitude_cell": 36, "longitude_cell": 140, "grid_degrees": 1},
                }},
                {"type": "variable.increment", "target": None, "params": {"name": "visits", "amount": 1}},
                {"type": "event.complete", "target": None, "params": {"event_id": "welcome"}},
            ],
        }],
    })


def _facts(world, program, now):
    return build_runtime_facts(
        world, program, now_utc=now, total_visits=1,
        absence_seconds=0, read_ids=set(),
    )


def _single_action_program(action, *, entities=(), schedule=None):
    return parse_program({
        "version": 1,
        "evaluator_version": 1,
        "world_state_version": 1,
        "atlas_version": "garden-atlas-1",
        "astronomy_catalog_version": "bright-stars-1",
        "author_timezone": "UTC",
        "variables": {},
        "entities": list(entities),
        "animals": [],
        "events": [{
            "id": "event.single",
            "conditions": {"fact": "visit.total", "op": ">=", "value": 0},
            "schedule": schedule,
            "occurrence": "recurring" if schedule else "once",
            "priority": 0,
            "exclusive_group": None,
            "cooldown": None,
            "actions": [action],
        }],
    })


def test_program_effects_materialize_with_receipts_trace_and_runtime_state():
    world = generate_initial_world("materialize", 11)
    program = _program()
    now = datetime(2030, 6, 2, 12, tzinfo=timezone.utc)
    command_sequence = world.command_sequence
    processed = world.processed_commands

    result = apply_program(world, program, facts=_facts(world, program, now))
    updated = result.world

    animal = next(item for item in updated.animals if item.animal_id == "animal.miso")
    assert animal.personality.boldness == 91
    assert animal.display_name == "Miso"
    assert animal.current_intent == "greet"
    assert animal.authored_preferences == ("morning_rounds",)
    assert animal.favorite_fixture_ids == ("fixture.authored",)
    assert any(item.fixture_id == "fixture.authored" and item.authored for item in updated.fixtures)
    assert any(item.collectible_id == "keepsake.authored" and item.authored for item in updated.collectibles)
    assert next(item for item in updated.plants if item.plant_id == "plant.authored").growth_points == 3
    assert {entry.label for entry in updated.journal} >= {"Welcome", "The Garden changed"}
    assert updated.program_state["variables"]["visits"] == 1
    assert updated.program_state["completed_events"] == ["welcome"]
    assert updated.program_state["scene"] == {
        "palette": "gold", "sky_mode": "author_fixed", "weather": "clear",
        "author_region": {"latitude_cell": 36, "longitude_cell": 140, "grid_degrees": 1},
    }
    assert result.effect_receipts
    assert all(receipt.startswith("program-receipt:") for receipt in result.effect_receipts)
    assert len(updated.event_trace) - len(world.event_trace) == len(result.effect_receipts)
    assert updated.command_sequence == command_sequence
    assert updated.processed_commands == processed

    second = apply_program(updated, program, facts=_facts(updated, program, now))
    assert second.effect_receipts == ()
    assert second.world.canonical_bytes() == updated.canonical_bytes()


def test_schedule_occurrences_are_recurring_and_idempotent():
    schedule = {
        "start": "2030-06-02T11:59:30", "timezone": "UTC",
        "recurrence": {"frequency": "daily", "interval": 1, "count": 3,
                       "by_weekday": [], "intentional_unbounded": False,
                       "dst_gap": "shift_forward", "dst_fold": "first"},
        "exceptions": [], "missed": "deliver_on_next_visit",
    }
    program = _program(schedule=schedule)
    world = generate_initial_world("scheduled", 12)
    now = datetime(2030, 6, 2, 12, tzinfo=timezone.utc)
    eligible = eligible_occurrences(
        program, last_seen_utc=now - timedelta(minutes=1), now_utc=now,
    )
    first = apply_program(world, program, facts=_facts(world, program, now), eligible=eligible)
    assert first.effect_receipts

    same = apply_program(first.world, program, facts=_facts(first.world, program, now), eligible=eligible)
    assert same.effect_receipts == ()

    tomorrow = now + timedelta(days=1)
    tomorrow_eligible = eligible_occurrences(
        program, last_seen_utc=tomorrow - timedelta(minutes=1), now_utc=tomorrow,
    )
    recurring = apply_program(
        same.world, program, facts=_facts(same.world, program, tomorrow),
        eligible=tomorrow_eligible,
    )
    assert recurring.effect_receipts
    assert recurring.world.program_state["variables"]["visits"] == 2


def test_letter_present_persists_sorted_canonical_eligibility():
    program = _single_action_program({
        "type": "letter.present", "target": None,
        "params": {"letter_id": "letter.future"},
    })
    world = generate_initial_world("present-letter", 21)
    world = replace(world, program_state={"presented_letters": ["letter.z"]})
    now = datetime(2030, 1, 1, tzinfo=timezone.utc)
    result = apply_program(world, program, facts=_facts(world, program, now))
    assert result.world.program_state["presented_letters"] == [
        "letter.future", "letter.z",
    ]
    assert next(
        entry.object_id for entry in result.world.journal
        if entry.label == "A letter is ready"
    ) == "letter.future"
    facts = build_runtime_facts(
        result.world, program, now_utc=now, total_visits=1,
        absence_seconds=0, read_ids=set(), due_letter_ids=("letter.date",),
    )
    assert facts["letter.due"] == ["letter.date", "letter.future", "letter.z"]


def test_summarize_then_current_persists_only_applied_bounded_summary():
    schedule = {
        "start": "2030-01-01T12:00:00", "timezone": "UTC",
        "recurrence": {
            "frequency": "daily", "interval": 1, "count": 20,
            "by_weekday": [], "intentional_unbounded": False,
            "dst_gap": "shift_forward", "dst_fold": "first",
        },
        "exceptions": [], "missed": "summarize_then_current",
    }
    program = _single_action_program({
        "type": "narrative.show", "target": None,
        "params": {"text": "Welcome back."},
    }, schedule=schedule)
    world = generate_initial_world("missed-summary", 22)
    now = datetime(2030, 1, 5, 13, tzinfo=timezone.utc)
    eligible = eligible_occurrences(
        program, last_seen_utc=datetime(2029, 12, 31, tzinfo=timezone.utc),
        now_utc=now,
    )
    result = apply_program(
        world, program, facts=_facts(world, program, now), eligible=eligible,
    )
    assert result.world.program_state["missed_event_summaries"] == [{
        "event_id": "event.single",
        "occurrence_id": eligible["event.single"],
        "missed_count": 4,
        "catch_up_truncated": False,
    }]
    assert result.missed_event_summaries == tuple(
        result.world.program_state["missed_event_summaries"]
    )


def test_unsafe_explicit_authored_position_fails_atomically():
    world = generate_initial_world("unsafe-authored", 23)
    occupied = world.plants[0].position.to_list()
    program = _single_action_program({
        "type": "entity.reveal", "target": "keepsake.authored",
        "params": {"position": occupied, "state": "A key"},
    }, entities=({
        "id": "keepsake.authored", "kind": "collectible",
        "catalog_id": "collectible.seed_packet",
    },))
    before = world.canonical_bytes()
    now = datetime(2030, 1, 1, tzinfo=timezone.utc)
    with pytest.raises(ValueError, match="overlaps another Garden object"):
        apply_program(world, program, facts=_facts(world, program, now))
    assert world.canonical_bytes() == before


def test_random_auto_placement_sentinel_stays_safe_for_legacy_migration():
    world = generate_initial_world("legacy-random-position", 24)
    program = _single_action_program({
        "type": "entity.reveal", "target": "legacy.keepsake",
        "params": {"position": "random", "state": "A safe memory"},
    }, entities=({
        "id": "legacy.keepsake", "kind": "collectible",
        "catalog_id": "collectible.seed_packet",
    },))
    now = datetime(2030, 1, 1, tzinfo=timezone.utc)
    result = apply_program(world, program, facts=_facts(world, program, now))
    item = next(
        value for value in result.world.collectibles
        if value.collectible_id == "legacy.keepsake"
    )
    assert item.position not in {
        plant.position for plant in world.plants
    }


def test_unknown_position_sentinel_is_rejected_instead_of_randomized():
    with pytest.raises(ValueError, match="unsupported placement hint"):
        _single_action_program({
            "type": "entity.reveal", "target": "keepsake.bad",
            "params": {"position": "somewhere-ish", "state": "A memory"},
        }, entities=({
            "id": "keepsake.bad", "kind": "collectible",
            "catalog_id": "collectible.seed_packet",
        },))


def test_animal_fixture_destination_uses_safe_reachable_adjacent_cell():
    program = _program()
    event = program.events[0]
    program = replace(program, events=(replace(
        event,
        actions=event.actions + (ProgramAction(
            "animal.set_destination", "animal.miso",
            {"fixture_id": "fixture.authored"},
        ),),
    ),))
    world = generate_initial_world("animal-destination", 26)
    now = datetime(2030, 1, 1, tzinfo=timezone.utc)
    result = apply_program(world, program, facts=_facts(world, program, now))
    animal = next(
        value for value in result.world.animals
        if value.animal_id == "animal.miso"
    )
    fixture = next(
        value for value in result.world.fixtures
        if value.fixture_id == "fixture.authored"
    )
    assert animal.position not in fixture_cells(fixture)
    assert layout_is_safe(result.world)


def test_prune_removes_requested_node_and_all_descendants():
    world = generate_initial_world("prune", 13)
    plant = world.plants[0]
    selected = next(node for node in plant.topology if node.parent_id is not None)
    descendants = {selected.node_id}
    changed = True
    while changed:
        before = len(descendants)
        descendants.update(node.node_id for node in plant.topology if node.parent_id in descendants)
        changed = len(descendants) != before
    raw = {
        "version": 1, "evaluator_version": 1, "world_state_version": 1,
        "atlas_version": "garden-atlas-1", "astronomy_catalog_version": "bright-stars-1",
        "author_timezone": "UTC", "variables": {},
        "entities": [{"id": plant.plant_id, "kind": "plant", "catalog_id": plant.species_id}],
        "animals": [],
        "events": [{
            "id": "prune", "conditions": {"fact": "visit.total", "op": ">=", "value": 0}, "schedule": None,
            "occurrence": "once", "priority": 0, "exclusive_group": None,
            "cooldown": None,
            "actions": [{"type": "plant.prune", "target": plant.plant_id,
                         "params": {"node_ids": [selected.node_id]}}],
        }],
    }
    program = parse_program(raw)
    now = datetime(2030, 6, 2, 12, tzinfo=timezone.utc)
    updated = apply_program(world, program, facts=_facts(world, program, now)).world
    remaining = {node.node_id for node in next(
        item for item in updated.plants if item.plant_id == plant.plant_id
    ).topology}
    assert descendants.isdisjoint(remaining)


def test_true_initial_definition_state_materializes_once():
    program = parse_program({
        "version": 1, "evaluator_version": 1, "world_state_version": 1,
        "atlas_version": "garden-atlas-1", "astronomy_catalog_version": "bright-stars-1",
        "author_timezone": "UTC", "variables": {"tone": "gentle"},
        "entities": [
            {"id": "initial.rose", "kind": "plant", "catalog_id": "plant.rose",
             "position": [8, 8], "initial_state": {"planted": True}},
            {"id": "initial.bench", "kind": "fixture", "catalog_id": "fixture.bench",
             "position": [12, 8], "initial_state": {"revealed": True}},
        ],
        "animals": [{
            "id": "initial.rabbit", "species": "animal.rabbit", "routine": "dawn forage",
            "initial_state": {"present": True},
        }],
        "events": [],
    })
    world = generate_initial_world("initial-state", 14)
    first = apply_program(world, program, facts={})
    assert {"initial.rose", "initial.bench", "initial.rabbit"} <= set(first.world.object_ids())
    assert first.world.program_state["variables"]["tone"] == "gentle"
    second = apply_program(first.world, program, facts={})
    assert second.effect_receipts == ()
    assert second.world.canonical_bytes() == first.world.canonical_bytes()


def test_runtime_fact_contract_accepts_real_duration_examined_and_canonical_overrides():
    world = generate_initial_world("fact-hooks", 15)
    program = _program()
    now = datetime(2030, 6, 2, 12, tzinfo=timezone.utc)
    facts = build_runtime_facts(
        world, program, now_utc=now, total_visits=4,
        absence_seconds=8 * 86_400, read_ids={"letter.one"},
        due_letter_ids=("letter.two",), session_duration_seconds=127,
        examined_ids={"keepsake.authored"},
        interaction_facts={"animal.memory": ["author-greeting"]},
    )
    assert facts["session.duration_seconds"] == 127
    assert facts["gift.examined"] == ["keepsake.authored"]
    assert facts["animal.memory"] == ["author-greeting"]
    with pytest.raises(ValueError, match="unsupported fact"):
        build_runtime_facts(
            world, program, now_utc=now, total_visits=1,
            absence_seconds=0, read_ids=set(),
            interaction_facts={"renderer.secret": True},
        )


@pytest.mark.skipif(shutil.which("node") is None, reason="Node.js is unavailable")
def test_animal_delivery_materializes_revealed_collectible_and_completes_choreography():
    raw = {
        "version": 1, "evaluator_version": 1, "world_state_version": 1,
        "atlas_version": "garden-atlas-1", "astronomy_catalog_version": "bright-stars-1",
        "author_timezone": "UTC", "variables": {},
        "entities": [{
            "id": "gift", "kind": "collectible", "catalog_id": "collectible.seed_packet",
            "position": [18, 10], "properties": {"label": "For Chloe"},
        }],
        "animals": [{
            "id": "rabbit", "species": "rabbit", "name": "Clover",
            "initial_state": {"present": True},
        }],
        "events": [{
            "id": "delivery", "conditions": {"fact": "visit.total", "op": ">=", "value": 1},
            "schedule": None, "occurrence": "once", "priority": 0,
            "exclusive_group": None, "cooldown": None,
            "actions": [{"type": "animal.present_gift", "target": "rabbit",
                         "params": {"gift_id": "gift"}}],
        }],
    }
    program = parse_program(raw)
    world = generate_initial_world("delivery", 16)
    now = datetime(2030, 9, 2, 12, tzinfo=timezone.utc)
    applied = apply_program(
        world, program, facts=build_runtime_facts(
            world, program, now_utc=now, total_visits=1,
            absence_seconds=0, read_ids=set(),
        ),
    )
    updated = applied.world
    gift = next(item for item in updated.collectibles if item.collectible_id == "gift")
    rabbit = next(item for item in updated.animals if item.animal_id == "rabbit")
    assert gift.label == "For Chloe"
    assert rabbit.display_name == "Clover"
    assert rabbit.current_intent == "animal.present_gift"
    assert rabbit.choreography_lock is None
    assert any(entry.label == "Gift delivered" for entry in updated.journal)
    payload = {
        "world": world.to_dict(),
        "program": raw,
        "evaluation": {
            "state": applied.evaluation.state,
            "trace": list(applied.evaluation.trace),
            "effects": list(applied.evaluation.effects),
        },
    }
    browser = subprocess.run(
        [shutil.which("node") or "node",
         "tests/garden_acceptance/garden_acceptance_runner.mjs", "--materialize"],
        cwd=ROOT, input=json.dumps(payload), check=True,
        capture_output=True, text=True,
    )
    assert json.loads(browser.stdout)["world"] == json.loads(updated.canonical_bytes())
