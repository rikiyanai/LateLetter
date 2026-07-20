from __future__ import annotations

import json
from pathlib import Path

import pytest

from lateletter.garden.evaluator import evaluate_condition, evaluate_program
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
