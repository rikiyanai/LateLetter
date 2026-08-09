"""Production-builder safety and encrypted v2 Garden regressions."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import pytest

from lateletter.bundle import (
    BUNDLE_VERSION_WITH_GARDEN_PROGRAM,
    read_bundle,
    verify_checksum,
    write_bundle,
)
from lateletter.garden.program import parse_program
from lateletter.sealed import (
    open_garden_program,
    open_message,
    seal_bundle,
    seal_garden_program,
    verify_bundle_hmac,
)
from make_letter import (
    _REPOSITORY_ROOT,
    _fresh_passphrase,
    _validate_private_paths,
    build,
    verify,
)


FRESH_PASSPHRASE = "synthetic garden phrase 2026!"


def _full_source() -> dict:
    return {
        "author_name": "Synthetic Author",
        "passphrase_hint": "a synthetic offline-only hint",
        "garden_seed": 20260721,
        "messages": [{
            "date": "2027-07-21",
            "label": "Synthetic first letter",
            "body": "Dear Chloe,\n\nThis is synthetic regression copy.\n",
        }],
        "garden_program": {
            "version": 1,
            "evaluator_version": 1,
            "world_state_version": 1,
            "atlas_version": "garden-atlas-1",
            "astronomy_catalog_version": "bright-stars-1",
            "author_timezone": "UTC",
            "variables": {"welcomed": False},
            "entities": [
                {"id": "fixture.bench", "kind": "fixture", "catalog_id": "bench"},
                {"id": "plant.rose", "kind": "plant", "catalog_id": "rose"},
                {
                    "id": "gift.flower", "kind": "collectible",
                    "catalog_id": "pressed_flower",
                },
            ],
            "animals": [{
                "id": "animal.clover", "species": "rabbit", "name": "Clover",
                "personality": "patient and curious", "routine": "forage at dawn",
                "favorite_places": ["fixture.bench"],
                "prohibited_behaviors": ["startle the recipient"],
            }],
            "events": [
                {
                    "id": "welcome",
                    "conditions": {"fact": "visit.total", "op": ">=", "value": 1},
                    "schedule": None,
                    "occurrence": "once",
                    "priority": 10,
                    "exclusive_group": None,
                    "cooldown": None,
                    "actions": [
                        {
                            "type": "animal.arrive", "target": "animal.clover",
                            "params": {"position": "random", "routine": "forage at dawn"},
                        },
                        {
                            "type": "entity.reveal", "target": "fixture.bench",
                            "params": {"position": "random"},
                        },
                        {
                            "type": "scene.set", "target": None,
                            "params": {"weather": "clear", "palette": "warm"},
                        },
                        {
                            "type": "narrative.show", "target": None,
                            "params": {
                                "kind": "memory", "label": "A synthetic welcome",
                                "text": "Synthetic private Garden prose.",
                            },
                        },
                        {
                            "type": "variable.set", "target": None,
                            "params": {"name": "welcomed", "value": True},
                        },
                    ],
                },
                {
                    "id": "weekly-care",
                    "conditions": {"fact": "visit.total", "op": ">=", "value": 1},
                    "schedule": {
                        "start": "2027-07-21T09:00:00",
                        "timezone": "UTC",
                        "recurrence": {
                            "frequency": "weekly", "interval": 1, "count": 4,
                            "by_weekday": ["WE"], "dst_gap": "shift_forward",
                            "dst_fold": "first",
                        },
                        "exceptions": [],
                        "missed": "deliver_on_next_visit",
                    },
                    "occurrence": "recurring",
                    "priority": 0,
                    "exclusive_group": None,
                    "cooldown": {"visits": 1},
                    "actions": [{
                        "type": "plant.grow", "target": "plant.rose",
                        "params": {"amount": 1},
                    }],
                },
                {
                    "id": "present-letter",
                    "conditions": {"fact": "letter.due", "op": "exists"},
                    "schedule": None,
                    "occurrence": "once",
                    "priority": 5,
                    "exclusive_group": None,
                    "cooldown": None,
                    "actions": [{
                        "type": "letter.present", "target": None,
                        "params": {"letter_id": "FIRST_MESSAGE"},
                    }],
                },
            ],
        },
    }


def _write_source(path: Path, value: dict | None = None) -> None:
    path.write_text(json.dumps(value or _full_source()), encoding="utf-8")


def test_build_round_trips_full_encrypted_v2_program(tmp_path, capsys):
    source = tmp_path / "private-source.json"
    output = tmp_path / "chloe.lateletter"
    _write_source(source)

    build(source, output, passphrase=FRESH_PASSPHRASE)

    bundle = read_bundle(output)
    assert bundle.version == BUNDLE_VERSION_WITH_GARDEN_PROGRAM
    assert bundle.garden_gifts == []
    assert verify_checksum(bundle)
    assert verify_bundle_hmac(bundle, FRESH_PASSPHRASE)
    assert open_message(FRESH_PASSPHRASE, bundle.messages[0])["body"].startswith(
        "Dear Chloe,"
    )
    program = parse_program(open_garden_program(FRESH_PASSPHRASE, bundle.garden_program))
    assert program.animals[0]["name"] == "Clover"
    scheduled = next(event for event in program.events if event.id == "weekly-care")
    assert scheduled.schedule["recurrence"]["by_weekday"] == ["WE"]
    assert scheduled.cooldown == {"visits": 1}
    presented = next(event for event in program.events if event.id == "present-letter")
    assert presented.actions[0].params["letter_id"] == bundle.messages[0].id
    assert "garden program: yes" in capsys.readouterr().out


def test_builder_rejects_letter_reference_absent_from_final_bundle(tmp_path):
    source = tmp_path / "private-source.json"
    output = tmp_path / "chloe.lateletter"
    value = _full_source()
    value["garden_program"]["events"][2]["actions"][0]["params"][
        "letter_id"
    ] = "letter.missing"
    _write_source(source, value)

    with pytest.raises(SystemExit, match="unknown bundle letter 'letter.missing'"):
        build(source, output, passphrase=FRESH_PASSPHRASE)
    assert not output.exists()


def test_verify_binds_program_references_to_authenticated_final_bundle(tmp_path):
    source = tmp_path / "private-source.json"
    output = tmp_path / "chloe.lateletter"
    _write_source(source)
    build(source, output, passphrase=FRESH_PASSPHRASE)
    bundle = read_bundle(output)
    raw = open_garden_program(FRESH_PASSPHRASE, bundle.garden_program)
    raw["events"][2]["actions"][0]["params"]["letter_id"] = "letter.missing"
    raw["events"][0]["actions"].append({
        "type": "event.complete", "target": None,
        "params": {"event_id": "event.missing"},
    })
    bundle.garden_program = seal_garden_program(FRESH_PASSPHRASE, raw)
    seal_bundle(bundle, FRESH_PASSPHRASE)
    write_bundle(bundle, output)

    with patch("make_letter.getpass.getpass", return_value=FRESH_PASSPHRASE):
        with pytest.raises(SystemExit) as exc_info:
            verify(output)
    assert "unknown bundle letter" in str(exc_info.value)
    assert "unknown program event" in str(exc_info.value)


def test_builder_rejects_passphrase_in_plaintext_source(tmp_path):
    source = tmp_path / "unsafe-source.json"
    output = tmp_path / "never-written.lateletter"
    value = _full_source()
    value["passphrase"] = FRESH_PASSPHRASE
    _write_source(source, value)

    with pytest.raises(SystemExit, match="remove 'passphrase'"):
        build(source, output, passphrase=FRESH_PASSPHRASE)
    assert not output.exists()


def test_builder_rejects_tracked_source_before_reading_it(tmp_path):
    tracked_source = _REPOSITORY_ROOT / "letters" / "letter_source.example.json"
    output = tmp_path / "never-written.lateletter"

    with patch.object(Path, "read_text", side_effect=AssertionError("must not read")):
        with pytest.raises(SystemExit, match="Git-tracked plaintext"):
            build(tracked_source, output, passphrase=FRESH_PASSPHRASE)
    assert not output.exists()


def test_builder_rejects_unignored_repository_output(tmp_path):
    source = tmp_path / "private-source.json"
    _write_source(source)
    unsafe_output = _REPOSITORY_ROOT / "untracked-chloe-output.lateletter"
    assert not unsafe_output.exists()

    with pytest.raises(ValueError, match="not ignored by Git"):
        _validate_private_paths(source, unsafe_output)


def test_builder_requires_v2_program_and_rejects_legacy_gifts(tmp_path):
    source = tmp_path / "legacy-source.json"
    output = tmp_path / "never-written.lateletter"
    value = _full_source()
    value.pop("garden_program")
    value["garden_gifts"] = [{"type": "item"}]
    _write_source(source, value)

    with pytest.raises(SystemExit, match="legacy garden_gifts"):
        build(source, output, passphrase=FRESH_PASSPHRASE)
    assert not output.exists()


def test_fresh_passphrase_is_confirmed_and_accepted():
    answers = iter([FRESH_PASSPHRASE, FRESH_PASSPHRASE])
    assert _fresh_passphrase(lambda _prompt: next(answers)) == FRESH_PASSPHRASE

    mismatch = iter([FRESH_PASSPHRASE, "different phrase 2026!"])
    with pytest.raises(ValueError, match="do not match"):
        _fresh_passphrase(lambda _prompt: next(mismatch))


def test_fresh_passphrase_uses_the_service_four_character_floor():
    accepted = iter(["1234", "1234"])
    assert _fresh_passphrase(lambda _prompt: next(accepted)) == "1234"

    too_short = iter(["123", "123"])
    with pytest.raises(ValueError, match="at least 4 characters"):
        _fresh_passphrase(lambda _prompt: next(too_short))
