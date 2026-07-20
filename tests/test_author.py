"""End-to-end tests for the integrated offline author workflow."""

from pathlib import Path
from unittest.mock import patch

from lateletter.author import (
    _NOTES_MARKER, _install_timeline_program, _run_garden_timeline_editor,
    _timeline_to_mapping, run_author_workflow,
)
from lateletter.bundle import (
    BUNDLE_VERSION_WITH_GARDEN_PROGRAM, Bundle, read_bundle, verify_checksum,
    write_bundle,
)
from lateletter.garden.authoring import ActionCard, BeatCard, Timeline, When
from lateletter.garden.program import parse_program
from lateletter.intake import IntakeData
from lateletter.sealed import (
    open_garden_program, open_message, seal_bundle, verify_bundle_hmac,
)
from lateletter.session_store import SessionStore


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
            "biscuit",
            accessible=True,
            input_fn=lambda _prompt: next(answers),
            output_fn=lambda _line: None,
        )

    assert result == 0
    bundle = read_bundle(output_path)
    assert verify_checksum(bundle)
    assert verify_bundle_hmac(bundle, "biscuit")
    assert open_message("biscuit", bundle.messages[0]) == {
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
        answers = iter(["", "n", "n"])
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
                "biscuit",
                accessible=True,
                input_fn=lambda _prompt: next(answers),
                output_fn=lambda _line: None,
            ) == 0

    bundle = read_bundle(output_path)
    assert verify_checksum(bundle)
    assert verify_bundle_hmac(bundle, "biscuit")
    assert [message.id for message in bundle.messages] == ["m1", "m2"]
    assert [
        open_message("biscuit", message)["body"]
        for message in bundle.messages
    ] == ["First body", "Second body"]


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
            "biscuit",
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
            "biscuit",
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
            store, _intake(), "biscuit", accessible=True,
            input_fn=lambda _prompt: next(answers), output_fn=lambda _line: None,
        ) == 0

    bundle = read_bundle(output_path)
    assert bundle.version == BUNDLE_VERSION_WITH_GARDEN_PROGRAM
    assert bundle.garden_gifts == []
    assert bundle.garden_program is not None
    assert parse_program(open_garden_program("biscuit", bundle.garden_program)).events[0].id == "welcome"


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
            store, _intake(), "biscuit", accessible=True,
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
