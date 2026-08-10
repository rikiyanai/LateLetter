"""Tests for the canonical author service.

These cover the properties that matter when the thing being produced is a
letter someone will read once, years from now: that a sealed bundle can always
be opened again, that the bytes are identical to the ones the command-line
builder has always written, and that a passphrase cannot end up inside a draft.
"""

from __future__ import annotations

import ast
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from lateletter.author_service import (  # noqa: E402
    AuthorServiceError, append_bundle_bytes, build_bundle, export_bundle_bytes, find_passphrase_key,
    passphrase_problem, serialize_bundle, validate_draft, write_bundle_file,
)
from lateletter.bundle import Bundle, read_bundle, write_bundle  # noqa: E402
from lateletter.sealed import open_garden_program, open_message, verify_bundle_hmac  # noqa: E402

STRONG_PASSPHRASE = "correct-horse-battery-staple-2026"
REPOSITORY_ROOT = Path(__file__).resolve().parents[1]


def draft() -> dict:
    """A minimal draft holding everything an export requires."""
    return {
        "author_name": "Riki",
        "passphrase_hint": "the word we always say instead of goodbye",
        "garden_seed": 20260719,
        "messages": [
            {"date": "2026-07-20", "label": "Open me", "body": "Dear you,\nhello."},
            {"date": "2026-08-20", "label": "Later", "body": "Still here."},
        ],
        "garden_program": {
            "version": 1, "evaluator_version": 1, "world_state_version": 1,
            "atlas_version": "garden-atlas-1",
            "astronomy_catalog_version": "bright-stars-1",
            "author_timezone": "UTC",
            "variables": {}, "entities": [], "animals": [], "events": [],
        },
    }


# ── secret scanning ─────────────────────────────────────────────────────────

def test_secret_keys_are_found_at_any_depth():
    assert find_passphrase_key({"passphrase": "x"}) == "passphrase"
    # The reason this scan exists: a top-level-only check would miss this.
    buried = {"messages": [{"body": "hi", "meta": {"password": "x"}}]}
    assert find_passphrase_key(buried) == "messages[0].meta.password"
    assert find_passphrase_key(draft()) is None


def test_validate_refuses_a_draft_carrying_a_secret():
    hostile = draft()
    hostile["messages"][0]["secret"] = "hunter2"
    result = validate_draft(hostile)
    assert not result.ok
    assert any("messages[0].secret" in issue for issue in result.errors)


def test_preview_never_contains_message_bodies():
    result = validate_draft(draft())
    assert result.ok, result.errors
    rendered = json.dumps(result.preview)
    assert "Dear you" not in rendered
    assert result.preview["message_count"] == 2
    assert result.preview["messages"][0]["body_characters"] > 0


def test_guided_rabbit_story_previews_and_exports_the_same_three_events():
    value = draft()
    del value["garden_program"]
    value["recipient_name"] = "Mara"
    value["author_timezone"] = "UTC"
    value["garden_template"] = {
        "kind": "letter_rabbit_autumn", "letter_index": 0,
        "rabbit_name": "Clover",
    }
    result = validate_draft(value)
    assert result.ok, result.errors
    assert result.preview["garden_story_preview"]["trace"] == [
        "arc.rabbit-arrives", "arc.third-visit-rose", "arc.bonded-autumn-gift",
    ]
    payload, _summary = export_bundle_bytes(value, STRONG_PASSPHRASE)
    bundle = Bundle.from_dict(json.loads(payload))
    program = open_garden_program(STRONG_PASSPHRASE, bundle.garden_program)
    assert [event["id"] for event in program["events"]] == result.preview[
        "garden_story_preview"
    ]["trace"]


# ── passphrase policy ───────────────────────────────────────────────────────

@pytest.mark.parametrize("value", ["", "a", "abc", 12, None])
def test_passphrases_below_the_four_character_floor_are_refused(value):
    assert passphrase_problem(value) is not None


@pytest.mark.parametrize(
    "value", ["1234", "aaaa", "password", STRONG_PASSPHRASE],
)
def test_four_or_more_characters_are_accepted_even_when_strength_copy_warns(value):
    assert passphrase_problem(value) is None


def test_export_refuses_a_passphrase_below_four_characters():
    with pytest.raises(AuthorServiceError) as excinfo:
        export_bundle_bytes(draft(), "123")
    assert any("4 characters" in issue for issue in excinfo.value.issues)


def test_export_accepts_a_four_character_passphrase():
    payload, _summary = export_bundle_bytes(draft(), "1234")
    assert verify_bundle_hmac(Bundle.from_dict(json.loads(payload)), "1234")


def test_append_preserves_identity_auth_salt_old_ciphertext_and_program():
    original_payload, _ = export_bundle_bytes(draft(), STRONG_PASSPHRASE)
    original = Bundle.from_dict(json.loads(original_payload))
    old_messages = [message.to_dict() for message in original.messages]
    old_program = original.garden_program.to_dict()
    appended_payload, summary = append_bundle_bytes(
        original_payload,
        [{"date": "2027-01-01", "label": "A new year", "body": "Still with you."}],
        STRONG_PASSPHRASE,
    )
    appended = Bundle.from_dict(json.loads(appended_payload))
    assert appended.bundle_id == original.bundle_id
    assert appended.bundle_auth_salt == original.bundle_auth_salt
    assert [message.to_dict() for message in appended.messages[:2]] == old_messages
    assert appended.garden_program.to_dict() == old_program
    assert open_message(STRONG_PASSPHRASE, appended.messages[-1])["label"] == "A new year"
    assert summary["appended_message_count"] == 1
    assert summary["message_count"] == 3


# ── validation ──────────────────────────────────────────────────────────────

def test_a_draft_without_a_garden_program_cannot_export():
    partial = draft()
    del partial["garden_program"]
    result = validate_draft(partial)
    assert not result.ok
    assert any("garden_program" in issue for issue in result.errors)


def test_every_problem_is_reported_at_once():
    broken = {"author_name": 5, "messages": []}
    result = validate_draft(broken)
    assert len(result.errors) >= 2


def test_legacy_garden_gifts_are_refused():
    legacy = draft()
    legacy["garden_gifts"] = [{"type": "flower"}]
    result = validate_draft(legacy)
    assert any("garden_gifts" in issue for issue in result.errors)


# ── sealing ─────────────────────────────────────────────────────────────────

def test_exported_bytes_open_again():
    payload, summary = export_bundle_bytes(draft(), STRONG_PASSPHRASE)
    assert summary["message_count"] == 2
    data = json.loads(payload.decode("utf-8"))
    assert data["version"] == 2
    # The passphrase must appear nowhere in the produced file.
    assert STRONG_PASSPHRASE not in payload.decode("utf-8")


def test_in_memory_bytes_match_what_the_builder_writes(tmp_path):
    """The HTML UI's download and the command line's file must be one format."""
    bundle = build_bundle(draft(), STRONG_PASSPHRASE)
    in_memory = serialize_bundle(bundle)
    out = tmp_path / "written.lateletter"
    write_bundle(bundle, out)
    assert out.read_bytes() == in_memory


def test_a_written_bundle_verifies_and_decrypts(tmp_path):
    out = tmp_path / "letter.lateletter"
    summary = write_bundle_file(draft(), STRONG_PASSPHRASE, out)
    assert summary["message_count"] == 2
    reread = read_bundle(out)
    assert verify_bundle_hmac(reread, STRONG_PASSPHRASE)
    bodies = [open_message(STRONG_PASSPHRASE, m)["body"] for m in reread.messages]
    assert "Dear you,\nhello." in bodies


def test_the_wrong_passphrase_does_not_verify(tmp_path):
    out = tmp_path / "letter.lateletter"
    write_bundle_file(draft(), STRONG_PASSPHRASE, out)
    assert not verify_bundle_hmac(read_bundle(out), "a-different-passphrase-2026")


def test_message_placeholders_are_substituted():
    """FIRST_MESSAGE must become a real identifier the viewer can match."""
    timed = draft()
    timed["garden_program"]["events"] = [{
        "id": "deliver",
        "conditions": {"fact": "visit.total", "op": ">=", "value": 1},
        "schedule": None, "occurrence": "once", "priority": 0,
        "exclusive_group": None, "cooldown": None,
        "actions": [{"type": "letter.present", "target": None,
                     "params": {"letter_id": "FIRST_MESSAGE"}}],
    }]
    payload, summary = export_bundle_bytes(timed, STRONG_PASSPHRASE)
    assert summary["garden_event_count"] == 1
    assert b"FIRST_MESSAGE" not in payload


def test_an_out_of_range_placeholder_is_refused():
    broken = draft()
    broken["garden_program"]["events"] = [{
        "id": "deliver",
        "conditions": {"fact": "visit.total", "op": ">=", "value": 1},
        "schedule": None, "occurrence": "once", "priority": 0,
        "exclusive_group": None, "cooldown": None,
        "actions": [{"type": "letter.present", "target": None,
                     "params": {"letter_id": "MESSAGE_9"}}],
    }]
    result = validate_draft(broken)
    assert any("out of range" in issue for issue in result.errors)


def test_author_service_is_the_only_product_bundle_writer_and_questions_survive():
    """Delete-first ownership: no second product module may seal or write."""
    product_root = REPOSITORY_ROOT / "src" / "lateletter"
    owner = product_root / "author_service.py"
    calls: dict[str, set[str]] = {}

    for path in product_root.rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        called = {
            node.func.id
            for node in ast.walk(tree)
            if isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id in {"seal_bundle", "write_bundle"}
        }
        if called:
            calls[path.relative_to(REPOSITORY_ROOT).as_posix()] = called

    assert calls == {
        owner.relative_to(REPOSITORY_ROOT).as_posix(): {
            "seal_bundle", "write_bundle",
        },
    }
    assert not (product_root / "author.py").exists()

    preserved = [
        product_root / "data" / "question_bank_seed.v0.json",
        product_root / "data" / "question_bank_domain_pools.v0.json",
        product_root / "question_selector.py",
        product_root / "qa_loop.py",
        product_root / "session_resumer.py",
        product_root / "draft_editor.py",
    ]
    assert all(path.is_file() for path in preserved)
