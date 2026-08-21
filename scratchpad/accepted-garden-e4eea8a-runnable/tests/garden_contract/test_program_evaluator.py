from __future__ import annotations

import json
from pathlib import Path
import shutil
import subprocess

import pytest

from lateletter.garden.evaluator import (
    EXCLUSIVE_LEDGER_LIMIT,
    OCCURRENCE_LEDGER_LIMIT,
    evaluate_condition,
    evaluate_program,
)
from lateletter.garden.program import ProgramValidationError, parse_program


FIXTURES = Path(__file__).parent / "fixtures"


def _fixture():
    return json.loads((FIXTURES / "program_evaluation.v1.json").read_text())


def test_program_fixture_parses_and_all_any_not_are_explainable():
    raw = _fixture()
    program = parse_program(raw["program"])
    result, trace = evaluate_condition(
        program.events[0].conditions, raw["context"]["facts"],
        seed=raw["context"]["seed"], event_id=program.events[0].id,
        occurrence_id="once",
    )
    assert result is True
    assert trace["kind"] == "all"
    assert [child["kind"] for child in trace["children"]] == ["leaf", "any", "not"]


def test_program_binds_letter_and_event_references_to_final_sets():
    raw = _fixture()["program"]
    raw["events"][0]["actions"].append({
        "type": "event.complete", "target": None,
        "params": {"event_id": "event.missing"},
    })
    with pytest.raises(ProgramValidationError) as exc_info:
        parse_program(raw, known_letter_ids={"letter.present"})
    message = str(exc_info.value)
    assert "unknown bundle letter 'letter.future'" in message
    assert "unknown program event 'event.missing'" in message


def test_entity_reveal_nested_state_cannot_bypass_ethics_validation():
    raw = _fixture()["program"]
    raw["events"][0]["actions"][1] = {
        "type": "entity.reveal", "target": "fixture.bench",
        "params": {"state": {
            "description": "Read this now or I will be disappointed",
        }},
    }
    with pytest.raises(ProgramValidationError, match="prohibited guilt"):
        parse_program(raw)


@pytest.mark.parametrize("position", [
    "somewhere-ish", [1.5, 2], [True, 2], ["1", 2],
    (1, 2), {"x": 1, "y": 2, "extra": 3}, {"x": 1, "y": False},
])
def test_program_parser_rejects_unknown_hints_and_noninteger_positions(position):
    raw = _fixture()["program"]
    raw["entities"][0]["placement"] = position
    with pytest.raises(ProgramValidationError, match="placement|position"):
        parse_program(raw)


@pytest.mark.parametrize("position", [
    "random", "authored", "path", "near_tallest_tree", "near_bench", "by_edge",
    [1, 2], {"x": 1, "y": 2},
])
def test_program_parser_accepts_canonical_positions(position):
    raw = _fixture()["program"]
    raw["entities"][0]["placement"] = position
    parse_program(raw)


def test_priority_exclusivity_and_idempotency_are_deterministic():
    raw = _fixture()
    program = parse_program(raw["program"])
    first = evaluate_program(program, raw["state"], raw["context"])
    expected = raw["expected"]

    assert first.state["variables"]["visits_rewarded"] == expected["visits_rewarded"]
    rows = {row["event_id"]: row for row in first.trace}
    assert rows[expected["applied_event"]]["status"] == "applied"
    assert rows[expected["blocked_event"]]["reason"] == "exclusive_group_claimed"

    second = evaluate_program(program, first.state, raw["context"])
    assert second.state == first.state
    assert second.effects == ()
    assert any(row.get("reason") == "already_applied" for row in second.trace)


def test_multi_year_recurring_and_exclusive_ledgers_are_bounded_with_totals():
    program = parse_program({
        "version": 1,
        "evaluator_version": 1,
        "world_state_version": 1,
        "atlas_version": "garden-atlas-1",
        "astronomy_catalog_version": "bright-stars-1",
        "author_timezone": "UTC",
        "variables": {"returns": 0},
        "entities": [],
        "animals": [],
        "events": [{
            "id": "event.recurring",
            "conditions": {"fact": "visit.total", "op": ">=", "value": 1},
            "schedule": None,
            "occurrence": "recurring",
            "priority": 1,
            "exclusive_group": "return",
            "cooldown": None,
            "actions": [{
                "type": "variable.increment", "target": None,
                "params": {"name": "returns", "amount": 1},
            }],
        }],
    })
    state: dict = {}
    for visit in range(1, 701):
        state = evaluate_program(
            program, state, {"facts": {"visit.total": visit}},
        ).state
    assert len(state["applied_occurrences"]) == OCCURRENCE_LEDGER_LIMIT
    assert len(state["exclusive_occurrences"]) == EXCLUSIVE_LEDGER_LIMIT
    assert state["applied_occurrence_total"] == 700
    assert state["exclusive_occurrence_total"] == 700
    assert state["variables"]["returns"] == 700
    assert state["applied_occurrences"][0].endswith(":visit:189")
    assert state["applied_occurrences"][-1].endswith(":visit:700")
    assert state["exclusive_occurrences"][0] == "return@visit:189"
    assert state["exclusive_occurrences"][-1] == "return@visit:700"


def test_seeded_probability_repeats_for_identical_occurrence():
    raw = _fixture()
    condition_raw = {"fact": "probability.seeded", "op": "<", "value": 0.5}
    raw["program"]["events"][0]["conditions"] = condition_raw
    raw["program"]["events"] = raw["program"]["events"][:1]
    program = parse_program(raw["program"])
    left = evaluate_condition(program.events[0].conditions, {}, seed=9,
                              event_id="event.spring-return", occurrence_id="o1")
    right = evaluate_condition(program.events[0].conditions, {}, seed=9,
                               event_id="event.spring-return", occurrence_id="o1")
    assert left == right
    assert 0.0 <= left[1]["observed"] < 1.0


@pytest.mark.parametrize("mutator", [
    lambda program: program.update({"unexpected": True}),
    lambda program: program["events"][0]["actions"][0]["params"].update({"script": "alert(1)"}),
    lambda program: program["events"][0]["actions"][0]["params"].update({"name": "https://bad.invalid"}),
    lambda program: program["events"][0]["actions"][0]["params"].update({"name": "bad\x1b[2J"}),
])
def test_program_rejects_unknown_executable_remote_and_control_input(mutator):
    raw = _fixture()["program"]
    mutator(raw)
    with pytest.raises(ProgramValidationError):
        parse_program(raw)


def test_scheduled_events_require_clock_owner_occurrence():
    raw = _fixture()
    raw["program"]["events"] = raw["program"]["events"][:1]
    raw["program"]["events"][0]["schedule"] = {
        "start": "2028-06-15T19:00:00", "timezone": "America/New_York",
        "recurrence": None, "exceptions": [], "missed": "deliver_on_next_visit",
    }
    program = parse_program(raw["program"])
    blocked = evaluate_program(program, raw["state"], raw["context"])
    assert blocked.trace[0]["reason"] == "schedule_not_eligible"
    context = {**raw["context"], "eligible_occurrences": {
        "event.spring-return": "event.spring-return@2028-06-15T23:00:00Z",
    }}
    applied = evaluate_program(program, raw["state"], context)
    assert applied.trace[0]["status"] == "applied"


def test_visit_and_time_cooldowns_are_persisted_and_enforced_together():
    raw = {
        "version": 1, "evaluator_version": 1, "world_state_version": 1,
        "atlas_version": "garden-atlas-1",
        "astronomy_catalog_version": "bright-stars-1",
        "author_timezone": "UTC", "variables": {}, "entities": [], "animals": [],
        "events": [{
            "id": "return.memory",
            "conditions": {"fact": "visit.total", "op": ">=", "value": 1},
            "schedule": None, "occurrence": "recurring", "priority": 0,
            "exclusive_group": None,
            "cooldown": {"duration_seconds": 3600, "visits": 2},
            "actions": [{"type": "narrative.show", "target": None,
                         "params": {"text": "Welcome back."}}],
        }],
    }
    program = parse_program(raw)
    first = evaluate_program(program, {}, {"facts": {
        "visit.total": 1, "time.utc": "2026-07-21T00:00:00Z",
    }})
    assert first.trace[0]["status"] == "applied"
    assert first.state["event_cooldowns"]["return.memory"] == {
        "time_utc_seconds": 1784592000, "visit_total": 1,
    }
    too_soon = evaluate_program(program, first.state, {"facts": {
        "visit.total": 2, "time.utc": "2026-07-21T02:00:00Z",
    }})
    assert too_soon.trace[0]["reason"] == "cooldown_active"
    ready = evaluate_program(program, too_soon.state, {"facts": {
        "visit.total": 3, "time.utc": "2026-07-21T02:00:00Z",
    }})
    assert ready.trace[0]["status"] == "applied"


@pytest.mark.parametrize("mutation", [
    lambda raw: raw["events"][0].update({"schedule": {
        "start": "2026-02-30T09:00:00", "timezone": "UTC",
        "recurrence": None, "exceptions": [], "missed": "skip",
    }}),
    lambda raw: raw["events"][0]["actions"][0].update({"params": {}}),
    lambda raw: raw.update({"animals": [{
        "id": "animal.unknown", "species": "dragon", "initial_state": {},
    }]}),
])
def test_runtime_unsafe_programs_fail_during_parse(mutation):
    raw = {
        "version": 1, "evaluator_version": 1, "world_state_version": 1,
        "atlas_version": "garden-atlas-1",
        "astronomy_catalog_version": "bright-stars-1",
        "author_timezone": "UTC", "variables": {}, "entities": [], "animals": [],
        "events": [{
            "id": "safe", "conditions": {"fact": "visit.total", "op": ">=", "value": 0},
            "schedule": None, "occurrence": "once", "priority": 0,
            "exclusive_group": None, "cooldown": None,
            "actions": [{"type": "narrative.show", "target": None,
                         "params": {"text": "Safe."}}],
        }],
    }
    mutation(raw)
    with pytest.raises(ProgramValidationError):
        parse_program(raw)


def _minimal_program(events, *, entities=None, animals=None):
    return {
        "version": 1, "evaluator_version": 1, "world_state_version": 1,
        "atlas_version": "garden-atlas-1",
        "astronomy_catalog_version": "bright-stars-1",
        "author_timezone": "UTC", "variables": {},
        "entities": entities or [], "animals": animals or [], "events": events,
    }


def _reference_validation_program(action):
    return _minimal_program([{
        "id": "validate", "priority": 0, "schedule": None,
        "occurrence": "once", "exclusive_group": None, "cooldown": None,
        "conditions": {"fact": "visit.total", "op": ">=", "value": 0},
        "actions": [action],
    }], entities=[
        {"id": "plant.one", "kind": "plant", "catalog_id": "rose"},
        {"id": "fixture.one", "kind": "fixture", "catalog_id": "bench"},
        {"id": "gift.one", "kind": "collectible", "catalog_id": "small_key"},
    ], animals=[
        {"id": "rabbit.one", "species": "rabbit", "initial_state": {}},
    ])


def test_program_parser_rejects_unavailable_timezone_and_unsafe_version_data():
    unavailable = _minimal_program([])
    unavailable["author_timezone"] = "Mars/Base"
    with pytest.raises(ProgramValidationError, match="available IANA timezone"):
        parse_program(unavailable)

    bad_version = _minimal_program([])
    bad_version["atlas_version"] = "garden atlas/../../escape"
    with pytest.raises(ProgramValidationError, match="invalid version identifier"):
        parse_program(bad_version)

    oversized = _minimal_program([])
    oversized["variables"] = {"memory": "x" * 16_385}
    with pytest.raises(ProgramValidationError, match="string exceeds 16384"):
        parse_program(oversized)

    too_deep = _minimal_program([])
    cursor = too_deep["variables"]
    for _ in range(21):
        cursor["memory"] = {}
        cursor = cursor["memory"]
    with pytest.raises(ProgramValidationError, match="nesting is too deep"):
        parse_program(too_deep)


@pytest.mark.parametrize(("action", "error"), [
    ({"type": "plant.plant", "target": "plant.one",
      "params": {"species_id": "dragon_rose"}}, "unknown runtime plant asset"),
    ({"type": "plant.grow", "target": "fixture.one",
      "params": {"amount": 1}}, "must reference a plant"),
    ({"type": "animal.arrive", "target": "plant.one",
      "params": {}}, "must reference an animal"),
    ({"type": "entity.reveal", "target": "rabbit.one",
      "params": {}}, "must reference a non-animal entity"),
    ({"type": "animal.set_destination", "target": "rabbit.one",
      "params": {"fixture_id": "plant.one"}}, "must reference a fixture"),
    ({"type": "animal.present_gift", "target": "rabbit.one",
      "params": {"gift_id": "rabbit.one"}}, "must reference a non-animal entity"),
    ({"type": "entity.transform", "target": "fixture.one",
      "params": {"asset_id": "plant.rose"}}, "unknown runtime fixture asset"),
    ({"type": "entity.transform", "target": "plant.one",
      "params": {"asset_id": "fixture.bench"}}, "unknown runtime plant asset"),
    ({"type": "entity.transform", "target": "gift.one",
      "params": {"asset_id": "animal.rabbit"}}, "asset kind does not match collectible"),
])
def test_program_parser_binds_action_targets_references_and_catalog_kinds(action, error):
    with pytest.raises(ProgramValidationError, match=error):
        parse_program(_reference_validation_program(action))


@pytest.mark.skipif(shutil.which("node") is None, reason="Node.js is unavailable")
def test_python_and_browser_parser_match_adversarial_schema_vectors():
    vectors = []
    unavailable = _minimal_program([])
    unavailable["author_timezone"] = "Mars/Base"
    vectors.append(unavailable)
    bad_version = _minimal_program([])
    bad_version["atlas_version"] = "garden atlas/../../escape"
    vectors.append(bad_version)
    oversized = _minimal_program([])
    oversized["variables"] = {"memory": "x" * 16_385}
    vectors.append(oversized)
    too_deep = _minimal_program([])
    cursor = too_deep["variables"]
    for _ in range(21):
        cursor["memory"] = {}
        cursor = cursor["memory"]
    vectors.append(too_deep)
    vectors.extend(_reference_validation_program(action) for action in [
        {"type": "plant.plant", "target": "plant.one",
         "params": {"species_id": "dragon_rose"}},
        {"type": "animal.set_destination", "target": "rabbit.one",
         "params": {"fixture_id": "plant.one"}},
        {"type": "entity.transform", "target": "fixture.one",
         "params": {"asset_id": "plant.rose"}},
        {"type": "entity.reveal", "target": "rabbit.one", "params": {}},
    ])
    script = """
import { parseGardenProgram } from './web/garden-program.mjs';
const vectors = JSON.parse(process.argv[1]);
const results = vectors.map(raw => {
  try { parseGardenProgram(raw); return 'accepted'; }
  catch (error) { return error.message; }
});
process.stdout.write(JSON.stringify(results));
"""
    completed = subprocess.run(
        [shutil.which("node") or "node", "--input-type=module", "-e", script,
         json.dumps(vectors)],
        cwd=Path(__file__).parents[2], check=True, capture_output=True, text=True,
    )
    browser_results = json.loads(completed.stdout)
    for raw, browser_result in zip(vectors, browser_results, strict=True):
        with pytest.raises(ProgramValidationError):
            parse_program(raw)
        assert browser_result.startswith("Invalid garden program:")


def test_exclusivity_is_idempotent_per_occurrence_but_reopens_next_visit():
    def event(event_id, priority, condition):
        return {
            "id": event_id, "conditions": condition, "schedule": None,
            "occurrence": "recurring", "priority": priority,
            "exclusive_group": "return-choice", "cooldown": None,
            "actions": [{"type": "event.complete", "target": None,
                         "params": {"event_id": event_id}}],
        }
    program = parse_program(_minimal_program([
        event("first-visit", 10, {"fact": "visit.total", "op": "==", "value": 1}),
        event("later-visit", 0, {"fact": "visit.total", "op": ">=", "value": 1}),
    ]))
    first = evaluate_program(program, {}, {"facts": {"visit.total": 1}})
    assert [row["event_id"] for row in first.trace if row["status"] == "applied"] == ["first-visit"]
    repeated = evaluate_program(program, first.state, {"facts": {"visit.total": 1}})
    assert not [row for row in repeated.trace if row["status"] == "applied"]
    later = evaluate_program(program, repeated.state, {"facts": {"visit.total": 2}})
    assert [row["event_id"] for row in later.trace if row["status"] == "applied"] == ["later-visit"]
    assert later.state["exclusive_occurrences"] == [
        "return-choice@visit:1", "return-choice@visit:2",
    ]


def test_evaluator_runs_dependent_events_to_a_bounded_fixed_point():
    program = parse_program(_minimal_program([
        {
            "id": "dependent", "priority": 20, "schedule": None,
            "occurrence": "once", "exclusive_group": None, "cooldown": None,
            "conditions": {"fact": "event.completed", "op": "contains", "ref": "producer"},
            "actions": [{"type": "variable.set", "target": None,
                         "params": {"name": "finished", "value": True}}],
        },
        {
            "id": "producer", "priority": 10, "schedule": None,
            "occurrence": "once", "exclusive_group": None, "cooldown": None,
            "conditions": {"fact": "visit.total", "op": ">=", "value": 1},
            "actions": [{"type": "event.complete", "target": None,
                         "params": {"event_id": "producer"}}],
        },
    ]))
    result = evaluate_program(program, {}, {"facts": {"visit.total": 1}})
    assert result.state["variables"]["finished"] is True
    attempts = [row for row in result.trace if row["event_id"] == "dependent"]
    assert [(row["evaluation_pass"], row["status"]) for row in attempts] == [
        (1, "blocked"), (2, "applied"),
    ]


def test_delivery_completes_semantically_and_reveals_gift_in_same_transaction():
    program = parse_program(_minimal_program([
        {
            "id": "deliver", "priority": 0, "schedule": None,
            "occurrence": "once", "exclusive_group": None, "cooldown": None,
            "conditions": {"fact": "visit.total", "op": ">=", "value": 1},
            "actions": [{"type": "animal.present_gift", "target": "rabbit",
                         "params": {"gift_id": "gift"}}],
        },
    ], entities=[{"id": "gift", "kind": "collectible", "catalog_id": "collectible.seed_packet"}],
       animals=[{"id": "rabbit", "species": "rabbit", "initial_state": {"present": True}}]))
    result = evaluate_program(program, {}, {"facts": {"visit.total": 1}})
    assert result.state["entities"]["gift"] == {
        "id": "gift", "revealed": True, "delivered": True, "delivered_by": "rabbit",
    }
    assert result.state["entities"]["rabbit"]["directive"]["status"] == "completed"


@pytest.mark.skipif(shutil.which("node") is None, reason="Node.js is unavailable")
def test_python_and_browser_evaluator_match_fixed_point_and_exclusivity():
    raw = _minimal_program([
        {
            "id": "dependent", "priority": 20, "schedule": None,
            "occurrence": "recurring", "exclusive_group": None, "cooldown": None,
            "conditions": {"fact": "event.completed", "op": "contains", "ref": "producer"},
            "actions": [{"type": "variable.set", "target": None,
                         "params": {"name": "finished", "value": True}}],
        },
        {
            "id": "producer", "priority": 10, "schedule": None,
            "occurrence": "recurring", "exclusive_group": "choice", "cooldown": None,
            "conditions": {"fact": "visit.total", "op": ">=", "value": 2},
            "actions": [{"type": "event.complete", "target": None,
                         "params": {"event_id": "producer"}}],
        },
    ])
    context = {"seed": 4, "facts": {"visit.total": 2, "time.utc": "2030-01-01T00:00:00Z"}}
    python_result = evaluate_program(parse_program(raw), {}, context)
    script = """
import { evaluateGardenProgram } from './web/garden-program.mjs';
const [program, context] = JSON.parse(process.argv[1]);
const result = await evaluateGardenProgram(program, {}, context);
process.stdout.write(JSON.stringify(result));
"""
    completed = subprocess.run(
        [shutil.which("node") or "node", "--input-type=module", "-e", script,
         json.dumps([raw, context])],
        cwd=Path(__file__).parents[2], check=True, capture_output=True, text=True,
    )
    browser = json.loads(completed.stdout)
    assert browser == {
        "state": python_result.state,
        "effects": list(python_result.effects),
        "trace": list(python_result.trace),
    }


@pytest.mark.skipif(shutil.which("node") is None, reason="Node.js is unavailable")
def test_python_and_browser_parser_reject_same_reference_position_and_ethics_vectors():
    raw = _fixture()["program"]
    raw["entities"][0]["placement"] = "somewhere-ish"
    raw["events"][0]["actions"][1]["params"] = {
        "state": {"journal": ["Act now or I'll be disappointed"]},
    }
    script = """
import { parseGardenProgram } from './web/garden-program.mjs';
const raw = JSON.parse(process.argv[1]);
try { parseGardenProgram(raw, { knownLetterIds: ['letter.present'] }); }
catch (error) { process.stdout.write(error.message); }
"""
    completed = subprocess.run(
        [shutil.which("node") or "node", "--input-type=module", "-e", script,
         json.dumps(raw)],
        cwd=Path(__file__).parents[2], check=True, capture_output=True, text=True,
    )
    with pytest.raises(ProgramValidationError) as python_error:
        parse_program(raw, known_letter_ids={"letter.present"})
    assert "unsupported placement hint" in str(python_error.value)
    assert "prohibited guilt" in str(python_error.value)
    assert "unsupported placement hint" in completed.stdout
    assert "prohibited guilt" in completed.stdout

    binding_raw = _fixture()["program"]
    completed = subprocess.run(
        [shutil.which("node") or "node", "--input-type=module", "-e", script,
         json.dumps(binding_raw)],
        cwd=Path(__file__).parents[2], check=True, capture_output=True, text=True,
    )
    with pytest.raises(ProgramValidationError, match="unknown bundle letter"):
        parse_program(binding_raw, known_letter_ids={"letter.present"})
    assert "unknown bundle letter" in completed.stdout


def test_program_parser_rejects_precise_or_malformed_author_sky_region():
    raw = _minimal_program([{
        "id": "sky", "priority": 0, "schedule": None, "occurrence": "once",
        "exclusive_group": None, "cooldown": None,
        "conditions": {"fact": "visit.total", "op": ">=", "value": 0},
        "actions": [{"type": "scene.set", "target": None, "params": {
            "sky_mode": "author_fixed",
            "author_region": {"latitude_cell": 35.68, "longitude_cell": 139.76,
                              "grid_degrees": 0.01},
        }}],
    }])
    with pytest.raises(ProgramValidationError, match="coarse one-degree region"):
        parse_program(raw)

    raw["events"][0]["actions"][0]["params"]["author_region"] = {
        "latitude_cell": 36, "longitude_cell": 140, "grid_degrees": True,
    }
    with pytest.raises(ProgramValidationError, match="coarse one-degree region"):
        parse_program(raw)


@pytest.mark.parametrize("text", [
    "If you really love me, come back every day.",
    "This is your last chance before it disappears.",
    "I'll be disappointed if you do not visit.",
])
def test_program_parser_rejects_manipulative_authored_copy(text):
    raw = _minimal_program([{
        "id": "unsafe", "priority": 0, "schedule": None, "occurrence": "once",
        "exclusive_group": None, "cooldown": None,
        "conditions": {"fact": "visit.total", "op": ">=", "value": 0},
        "actions": [{"type": "narrative.show", "target": None,
                     "params": {"text": text}}],
    }])
    with pytest.raises(ProgramValidationError, match="dark-pattern"):
        parse_program(raw)
