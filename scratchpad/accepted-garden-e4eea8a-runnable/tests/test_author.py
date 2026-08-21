"""End-to-end tests for the integrated offline author workflow."""

from pathlib import Path
from datetime import datetime, timezone
from unittest.mock import patch

import pytest

from lateletter.author import (
    AuthorFlowError, _NOTES_MARKER, _REPOSITORY_ROOT, _confirm_export_passphrase,
    garden_program_to_mapping,
    _install_timeline_program, _merge_programs, _run_garden_timeline_editor,
    _resolve_preview_local, _timeline_to_mapping, _validate_export_destination,
    _validate_private_author_path, run_author_workflow,
)
from lateletter.bundle import (
    BUNDLE_VERSION_WITH_GARDEN_PROGRAM, Bundle, read_bundle, verify_checksum,
    write_bundle,
)
from lateletter.garden.authoring import (
    ActionCard, BeatCard, Timeline, When, compile_timeline,
)
from lateletter.garden.program import ProgramValidationError, parse_program
from lateletter.intake import IntakeData
from lateletter.sealed import (
    open_garden_program, open_message, seal_bundle, seal_garden_program,
    seal_message, verify_bundle_hmac,
)
from lateletter.session_store import SessionStore


FRESH_PASSPHRASE = "synthetic private phrase 2026!"


def _intake() -> IntakeData:
    return IntakeData(
        author_name="Robert",
        recipient_name="Maya",
        recipient_relationship="daughter",
        passphrase_hint="first dog",
    )


def test_written_draft_is_sealed_and_exported(tmp_path: Path):
    store = SessionStore(base_dir=tmp_path / "author")
    store.save_session({"messages": [{
        "id": "m1",
        "label": "Her birthday",
        "date": "2026-07-21",
        "occasion": "birthday",
        "status": "written",
    }]})
    output_path = tmp_path / "maya.lateletter"
    answers = iter(["", "n", "n"])

    with patch(
        "lateletter.author.edit_draft",
        return_value=("Dear Maya,\n\nI love you.\n\nDad", True),
    ), patch(
        "lateletter.author._prompt_export_path",
        return_value=output_path,
    ):
        result = run_author_workflow(
            store,
            _intake(),
            FRESH_PASSPHRASE,
            accessible=True,
            input_fn=lambda _prompt: next(answers),
            password_fn=lambda _prompt: FRESH_PASSPHRASE,
            output_fn=lambda _line: None,
        )

    assert result == 0
    bundle = read_bundle(output_path)
    assert verify_checksum(bundle)
    assert verify_bundle_hmac(bundle, FRESH_PASSPHRASE)
    assert open_message(FRESH_PASSPHRASE, bundle.messages[0]) == {
        "label": "Her birthday",
        "body": "Dear Maya,\n\nI love you.\n\nDad",
    }
    assert store.get_message("m1")["status"] == "encrypted"
    assert store.load_session()["bundle_path"] == str(output_path)


def test_second_written_message_appends_to_existing_bundle(tmp_path: Path):
    store = SessionStore(base_dir=tmp_path / "author")
    output_path = tmp_path / "maya.lateletter"
    data = _intake()

    for message_id, label, body in (
        ("m1", "First", "First body"),
        ("m2", "Second", "Second body"),
    ):
        store.upsert_message(message_id, {
            "label": label,
            "date": "2026-07-21",
            "occasion": "general",
            "status": "written",
        })
        answers = iter(["", "n", *( ["APPEND"] if output_path.exists() else [] ), "n"])
        with patch(
            "lateletter.author.edit_draft",
            return_value=(body, True),
        ), patch(
            "lateletter.author._prompt_export_path",
            return_value=output_path,
        ):
            assert run_author_workflow(
                store,
                data,
                FRESH_PASSPHRASE,
                accessible=True,
                input_fn=lambda _prompt: next(answers),
                password_fn=lambda _prompt: FRESH_PASSPHRASE,
                output_fn=lambda _line: None,
            ) == 0

    bundle = read_bundle(output_path)
    assert verify_checksum(bundle)
    assert verify_bundle_hmac(bundle, FRESH_PASSPHRASE)
    assert [message.id for message in bundle.messages] == ["m1", "m2"]
    assert [
        open_message(FRESH_PASSPHRASE, message)["body"]
        for message in bundle.messages
    ] == ["First body", "Second body"]
    backups = list(tmp_path.glob("maya.append.backup*.lateletter"))
    assert len(backups) == 1
    assert [message.id for message in read_bundle(backups[0]).messages] == ["m1"]


def test_author_paths_reject_tracked_and_unignored_repository_destinations():
    with pytest.raises(Exception, match="Git-tracked"):
        _validate_export_destination(_REPOSITORY_ROOT / "sealed_demo.lateletter")
    unsafe = _REPOSITORY_ROOT / "unsafe-author-output.lateletter"
    assert not unsafe.exists()
    with pytest.raises(Exception, match="not ignored by Git"):
        _validate_export_destination(unsafe)
    with pytest.raises(Exception, match="not ignored by Git"):
        _validate_private_author_path(
            _REPOSITORY_ROOT / "unsafe-author-storage", label="plaintext author storage",
        )


def test_fresh_export_passphrase_must_be_strong_and_confirmed():
    with pytest.raises(Exception, match="short|at least 12"):
        _confirm_export_passphrase(
            "biscuit", existing=False, password_fn=lambda _prompt: "biscuit",
        )
    with pytest.raises(Exception, match="did not match"):
        _confirm_export_passphrase(
            FRESH_PASSPHRASE, existing=False, password_fn=lambda _prompt: "wrong",
        )


def test_qa_notes_marker_blocks_accidental_sealing(tmp_path: Path):
    store = SessionStore(base_dir=tmp_path / "author")
    store.save_session({"messages": [{
        "id": "m1",
        "label": "Her birthday",
        "date": "2026-07-21",
        "occasion": "birthday",
        "status": "written",
    }]})

    with patch(
        "lateletter.author.edit_draft",
        return_value=(f"Draft\n{_NOTES_MARKER}\nprivate notes", True),
    ):
        result = run_author_workflow(
            store,
            _intake(),
            FRESH_PASSPHRASE,
            accessible=True,
            input_fn=lambda _prompt: "",
            output_fn=lambda _line: None,
        )

    assert result == 0
    assert not list(tmp_path.glob("*.lateletter"))
    assert store.get_message("m1")["status"] == "written"


def test_fresh_message_reaches_questions_then_drafting(tmp_path: Path):
    store = SessionStore(base_dir=tmp_path / "author")
    answers = iter(
        ["Birthday letter", "2026-07-21", "birthday"]
        + [part for index in range(10) for part in (f"Answer {index}", "")]
    )

    with patch(
        "lateletter.author.edit_draft",
        return_value=("A reviewed draft", False),
    ) as editor:
        result = run_author_workflow(
            store,
            _intake(),
            FRESH_PASSPHRASE,
            accessible=True,
            input_fn=lambda _prompt: next(answers),
            output_fn=lambda _line: None,
        )

    assert result == 0
    message = store.load_session()["messages"][0]
    assert message["qa_complete"] is True
    assert message["qa_exchange_count"] == 10
    assert message["status"] == "written"
    editor.assert_called_once()


def _timeline() -> Timeline:
    timeline = Timeline(author_timezone="UTC", variables={"welcomed": False})
    timeline.beats.append(BeatCard(
        id="welcome", title="Welcome", track="revisit",
        when=When.fact("visit.total", ">=", 1),
        actions=(ActionCard.set_variable("welcomed", True),),
    ))
    return timeline


def test_write_exports_valid_encrypted_garden_v2(tmp_path: Path):
    store = SessionStore(base_dir=tmp_path / "author")
    store.upsert_message("m1", {
        "label": "First", "date": "2026-07-21", "occasion": "general",
        "status": "written",
    })
    output_path = tmp_path / "maya.lateletter"
    answers = iter(["", "n"])
    with patch("lateletter.author.edit_draft", return_value=("Body", True)), patch(
        "lateletter.author._run_garden_timeline_editor", return_value=_timeline(),
    ), patch("lateletter.author._prompt_export_path", return_value=output_path):
        assert run_author_workflow(
            store, _intake(), FRESH_PASSPHRASE, accessible=True,
            input_fn=lambda _prompt: next(answers),
            password_fn=lambda _prompt: FRESH_PASSPHRASE,
            output_fn=lambda _line: None,
        ) == 0

    bundle = read_bundle(output_path)
    assert bundle.version == BUNDLE_VERSION_WITH_GARDEN_PROGRAM
    assert bundle.garden_gifts == []
    assert bundle.garden_program is not None
    assert parse_program(open_garden_program(FRESH_PASSPHRASE, bundle.garden_program)).events[0].id == "welcome"


def test_write_blocks_invalid_garden_before_export(tmp_path: Path):
    store = SessionStore(base_dir=tmp_path / "author")
    store.upsert_message("m1", {
        "label": "First", "date": "2026-07-21", "occasion": "general",
        "status": "written",
    })
    invalid = Timeline(author_timezone="UTC")
    invalid.beats.append(BeatCard(
        id="missing", title="Missing", track="gifts",
        when=When.fact("visit.total", ">=", 1),
        actions=(ActionCard.reveal("does-not-exist"),),
    ))
    output_path = tmp_path / "blocked.lateletter"
    with patch("lateletter.author.edit_draft", return_value=("Body", True)), patch(
        "lateletter.author._run_garden_timeline_editor", return_value=invalid,
    ), patch("lateletter.author._prompt_export_path", return_value=output_path):
        result = run_author_workflow(
            store, _intake(), FRESH_PASSPHRASE, accessible=True,
            input_fn=lambda _prompt: "", output_fn=lambda _line: None,
        )
    assert result == 1
    assert not output_path.exists()


def test_saved_timeline_resumes_without_raw_json(tmp_path: Path):
    store = SessionStore(base_dir=tmp_path / "author")
    store.save_garden_timeline(_timeline_to_mapping(_timeline()))
    answers = iter(["", "done"])
    resumed = _run_garden_timeline_editor(
        store, _intake(), ["m1"], input_fn=lambda _prompt: next(answers),
        output_fn=lambda _line: None,
    )
    assert resumed is not None
    assert [beat.id for beat in resumed.beats] == ["welcome"]


def test_existing_v1_requires_explicit_upgrade_and_is_preserved(tmp_path: Path):
    path = tmp_path / "legacy.lateletter"
    original = Bundle(bundle_id="legacy")
    seal_bundle(original, "biscuit")
    write_bundle(original, path)
    loaded = read_bundle(path)

    changed = _install_timeline_program(
        loaded, path=path, existed=True,
        timeline_program=parse_program({
            "version": 1, "evaluator_version": 1, "world_state_version": 1,
            "atlas_version": "garden-atlas-1",
            "astronomy_catalog_version": "bright-stars-1",
            "author_timezone": "UTC", "variables": {}, "entities": [],
            "animals": [], "events": [],
        }),
        passphrase="biscuit", input_fn=lambda _prompt: "KEEP V1",
        output_fn=lambda _line: None,
    )

    assert changed is False
    assert loaded.version == 1
    assert loaded.garden_program is None
    assert read_bundle(path).version == 1
    assert not list(tmp_path.glob("*.backup*.lateletter"))


def test_no_json_editor_builds_chloe_acceptance_arc(tmp_path: Path):
    store = SessionStore(base_dir=tmp_path / "author")
    answers = iter(["y", "UTC", "arc", "1", "Clover", "36,140", "done"])
    timeline = _run_garden_timeline_editor(
        store, _intake(), ["letter.chloe"],
        input_fn=lambda _prompt: next(answers), output_fn=lambda _line: None,
    )
    assert timeline is not None
    assert [beat.id for beat in timeline.beats] == [
        "arc.rabbit-arrives", "arc.third-visit-rose", "arc.bonded-autumn-gift",
    ]
    assert timeline.animals[0]["name"] == "Clover"
    sky_action = next(
        action for action in timeline.beats[0].actions if action.type == "scene.set"
    )
    assert sky_action.params == {
        "sky_mode": "author_fixed",
        "author_region": {
            "latitude_cell": 36, "longitude_cell": 140, "grid_degrees": 1,
        },
    }
    compile_timeline(
        timeline, known_letter_ids={"letter.chloe"},
        known_asset_ids={"collectible.seed_packet"},
    )
    saved = store.load_garden_timeline()
    assert saved is not None
    assert [beat["id"] for beat in saved["beats"]] == [
        "arc.rabbit-arrives", "arc.third-visit-rose", "arc.bonded-autumn-gift",
    ]


def test_existing_v2_program_is_semantically_merged_without_data_loss(tmp_path: Path):
    existing = _timeline()
    added = Timeline(author_timezone="UTC", variables={"welcomed": False, "later": 0})
    added.beats.extend(existing.beats)
    added.beats.append(BeatCard(
        id="later", title="Later", track="revisit",
        when=When.fact("visit.total", ">=", 2),
        actions=(ActionCard.set_variable("later", 1),),
    ))
    existing_program = compile_timeline(existing)
    added_program = compile_timeline(added)
    bundle = Bundle(
        bundle_id="v2-append",
        version=BUNDLE_VERSION_WITH_GARDEN_PROGRAM,
        garden_program=seal_garden_program(
            FRESH_PASSPHRASE, garden_program_to_mapping(existing_program),
        ),
    )

    assert _install_timeline_program(
        bundle, path=tmp_path / "existing.lateletter", existed=True,
        timeline_program=added_program, passphrase=FRESH_PASSPHRASE,
        input_fn=lambda _prompt: "", output_fn=lambda _line: None,
    )
    merged = parse_program(open_garden_program(
        FRESH_PASSPHRASE, bundle.garden_program,
    ))
    assert [event.id for event in merged.events] == ["welcome", "later"]
    assert merged.variables == {"welcomed": False, "later": 0}


def test_existing_v2_program_rejects_changed_id_collision():
    existing = _timeline()
    conflicting = Timeline(author_timezone="UTC", variables={"welcomed": False})
    conflicting.beats.append(BeatCard(
        id="welcome", title="Changed", track="revisit",
        when=When.fact("visit.total", ">=", 1),
        actions=(ActionCard.set_variable("welcomed", False),),
    ))
    with pytest.raises(AuthorFlowError, match="event ID 'welcome'"):
        _merge_programs(
            compile_timeline(existing), compile_timeline(conflicting),
        )


def test_existing_v2_merge_rejects_collision_and_dangling_letter_atomically(
    tmp_path: Path,
):
    existing_program = compile_timeline(_timeline())
    bundle = Bundle(
        bundle_id="v2-collision",
        version=BUNDLE_VERSION_WITH_GARDEN_PROGRAM,
        messages=[seal_message(
            FRESH_PASSPHRASE, message_id="letter.present",
            date="2030-01-01", label="Present", body="Body",
        )],
        garden_program=seal_garden_program(
            FRESH_PASSPHRASE, garden_program_to_mapping(existing_program),
        ),
    )
    original_envelope = bundle.garden_program
    dangling = parse_program({
        "version": 1, "evaluator_version": 1, "world_state_version": 1,
        "atlas_version": "garden-atlas-1",
        "astronomy_catalog_version": "bright-stars-1",
        "author_timezone": "UTC", "variables": {}, "entities": [],
        "animals": [], "events": [{
            "id": "dangling", "conditions": {
                "fact": "visit.total", "op": ">=", "value": 1,
            }, "schedule": None, "occurrence": "once", "priority": 0,
            "exclusive_group": None, "cooldown": None,
            "actions": [{
                "type": "letter.present", "target": None,
                "params": {"letter_id": "letter.missing"},
            }],
        }],
    })
    with pytest.raises(ProgramValidationError, match="unknown bundle letter"):
        _install_timeline_program(
            bundle, path=tmp_path / "existing.lateletter", existed=True,
            timeline_program=dangling, passphrase=FRESH_PASSPHRASE,
            input_fn=lambda _prompt: "", output_fn=lambda _line: None,
        )
    assert bundle.garden_program == original_envelope


def test_author_preview_resolves_dst_gap_and_fold_in_author_timezone():
    gap = _resolve_preview_local(
        datetime(2026, 3, 8, 2, 30), "America/New_York",
    )
    fold = _resolve_preview_local(
        datetime(2026, 11, 1, 1, 30), "America/New_York",
    )
    assert gap.replace(tzinfo=None) == datetime(2026, 3, 8, 3, 0)
    assert gap.astimezone(timezone.utc) == datetime(
        2026, 3, 8, 7, 0, tzinfo=timezone.utc,
    )
    assert fold.astimezone(timezone.utc) == datetime(
        2026, 11, 1, 5, 30, tzinfo=timezone.utc,
    )
