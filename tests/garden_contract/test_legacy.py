from __future__ import annotations

import json
from pathlib import Path

import pytest

from lateletter.garden.evaluator import evaluate_program
from lateletter.garden.legacy import LegacyAuthenticationRequired, migrate_legacy_gifts


FIXTURES = Path(__file__).parent / "fixtures"


def _legacy():
    return json.loads((FIXTURES / "legacy_migration.v1.json").read_text())


def test_legacy_gifts_cannot_migrate_before_bundle_authentication():
    with pytest.raises(LegacyAuthenticationRequired):
        migrate_legacy_gifts(_legacy()["gifts"], authenticated=False)


def test_every_legacy_trigger_becomes_an_authenticated_one_shot_event():
    raw = _legacy()
    program = migrate_legacy_gifts(
        raw["gifts"], authenticated=True, decrypted_sentiments=raw["sentiments"],
        message_ids=["letter.first", "letter.last"],
    )
    assert len(program.events) == 3
    assert all(event.occurrence == "once" for event in program.events)
    assert {animal["name"] for animal in program.animals} == {"Clover"}
    assert all("Clover comes close" not in repr(event.conditions) for event in program.events)


def test_migrated_visit_letter_and_date_conditions_use_canonical_evaluator():
    raw = _legacy()
    program = migrate_legacy_gifts(
        raw["gifts"], authenticated=True, decrypted_sentiments=raw["sentiments"],
        message_ids=["letter.first", "letter.last"],
    )
    result = evaluate_program(program, {"applied_occurrences": []}, {
        "seed": 7,
        "facts": {
            "visit.total": 3,
            "letter.read": ["letter.first"],
            "time.local": "2027-01-01T00:00:00",
        },
    })
    applied = {row["event_id"] for row in result.trace if row["status"] == "applied"}
    assert applied == {"legacy.gift.rabbit", "legacy.gift.flower"}
    assert "legacy.gift.mug" not in applied


def test_post_completion_releases_future_legacy_gifts_once():
    raw = _legacy()
    program = migrate_legacy_gifts(
        raw["gifts"], authenticated=True, decrypted_sentiments=raw["sentiments"],
        message_ids=["letter.first", "letter.last"],
    )
    context = {"seed": 7, "facts": {
        "visit.total": 1,
        "letter.read": ["letter.first", "letter.last"],
        "time.local": "2027-01-01T00:00:00",
    }}
    first = evaluate_program(program, {"applied_occurrences": []}, context)
    assert all(row["status"] == "applied" for row in first.trace)
    second = evaluate_program(program, first.state, context)
    assert second.effects == ()
    assert all(row["reason"] == "already_applied" for row in second.trace)
