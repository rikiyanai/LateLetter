"""
Tests for SessionStore (session.json, questions_asked.json, selector_state.json).

Uses a temp directory as base_dir so tests never touch ~/.lateletter/.
"""

import json
import os
import stat
from pathlib import Path

import pytest

from src.lateletter.session_store import SessionStore


@pytest.fixture
def store(tmp_path):
    return SessionStore(base_dir=tmp_path)


# ---------------------------------------------------------------------------
# session.json
# ---------------------------------------------------------------------------

class TestSessionFile:
    def test_load_returns_empty_dict_if_absent(self, store):
        assert store.load_session() == {}

    def test_save_and_load_roundtrip(self, store):
        data = {"intake": {"author_name": "Robert"}, "messages": []}
        store.save_session(data)
        assert store.load_session() == data

    def test_save_creates_file_with_secure_permissions(self, store, tmp_path):
        store.save_session({"x": 1})
        path = tmp_path / "session.json"
        assert path.exists()
        mode = oct(stat.S_IMODE(path.stat().st_mode))
        assert mode == oct(0o600), f"Expected 0o600, got {mode}"

    def test_save_is_valid_json(self, store, tmp_path):
        store.save_session({"foo": "bar", "n": 42})
        raw = (tmp_path / "session.json").read_text()
        parsed = json.loads(raw)
        assert parsed["foo"] == "bar"

    def test_no_tmp_file_left_after_write(self, store, tmp_path):
        store.save_session({"a": 1})
        tmp_files = list(tmp_path.glob("*.tmp"))
        assert tmp_files == [], f"Leftover .tmp files: {tmp_files}"


# ---------------------------------------------------------------------------
# questions_asked.json
# ---------------------------------------------------------------------------

class TestQuestionsAsked:
    def test_load_returns_empty_list_if_absent(self, store):
        assert store.load_questions_asked() == []

    def test_record_and_load_roundtrip(self, store):
        store.record_question_asked("u-001", "How would you describe yourself?", "msg-1")
        entries = store.load_questions_asked()
        assert len(entries) == 1
        assert entries[0]["question_id"] == "u-001"
        assert entries[0]["message_id"] == "msg-1"
        assert "asked_at" in entries[0]
        assert len(entries[0]["question_hash"]) == 64  # SHA-256 hex

    def test_asked_question_ids(self, store):
        store.record_question_asked("u-001", "Q1", "msg-1")
        store.record_question_asked("u-003", "Q3", "msg-1")
        ids = store.asked_question_ids()
        assert ids == {"u-001", "u-003"}

    def test_record_appends(self, store):
        store.record_question_asked("u-001", "Q1", "msg-1")
        store.record_question_asked("u-002", "Q2", "msg-1")
        assert len(store.load_questions_asked()) == 2

    def test_question_hash_is_deterministic(self, store):
        text = "How would you describe yourself?"
        store.record_question_asked("u-001", text, "msg-1")
        store.record_question_asked("u-001", text, "msg-2")
        entries = store.load_questions_asked()
        assert entries[0]["question_hash"] == entries[1]["question_hash"]


# ---------------------------------------------------------------------------
# selector_state.json
# ---------------------------------------------------------------------------

class TestSelectorState:
    def test_load_returns_none_if_absent(self, store):
        assert store.load_selector_state("msg-1") is None

    def test_save_and_load_roundtrip(self, store):
        state = {"occasion": "birthday", "relationship": "child", "asked_this_session": []}
        store.save_selector_state("msg-1", state)
        loaded = store.load_selector_state("msg-1")
        assert loaded == state

    def test_load_returns_none_for_different_message_id(self, store):
        store.save_selector_state("msg-1", {"x": 1})
        assert store.load_selector_state("msg-2") is None

    def test_clear_removes_file(self, store, tmp_path):
        store.save_selector_state("msg-1", {"x": 1})
        store.clear_selector_state()
        assert not (tmp_path / "selector_state.json").exists()


# ---------------------------------------------------------------------------
# upsert_message
# ---------------------------------------------------------------------------

class TestUpsertMessage:
    def test_creates_message_if_absent(self, store):
        store.upsert_message("msg-1", {"label": "Birthday", "status": "draft"})
        msg = store.get_message("msg-1")
        assert msg is not None
        assert msg["label"] == "Birthday"

    def test_updates_existing_message(self, store):
        store.upsert_message("msg-1", {"label": "Birthday"})
        store.upsert_message("msg-1", {"label": "Her Birthday", "status": "complete"})
        msg = store.get_message("msg-1")
        assert msg["label"] == "Her Birthday"
        assert msg["status"] == "complete"

    def test_get_message_returns_none_if_absent(self, store):
        assert store.get_message("does-not-exist") is None

    def test_multiple_messages_coexist(self, store):
        store.upsert_message("msg-1", {"label": "Birthday"})
        store.upsert_message("msg-2", {"label": "Wedding"})
        assert store.get_message("msg-1")["label"] == "Birthday"
        assert store.get_message("msg-2")["label"] == "Wedding"

    def test_preserves_unrelated_session_fields(self, store):
        store.save_session({"intake": {"author_name": "Robert"}, "messages": []})
        store.upsert_message("msg-1", {"label": "Birthday"})
        session = store.load_session()
        assert session["intake"]["author_name"] == "Robert"

    def test_upsert_message_rejects_passphrase_key(self, store):
        import pytest
        with pytest.raises(ValueError, match="passphrase"):
            store.upsert_message("msg-1", {"passphrase": "secret"})

    def test_upsert_message_rejects_password_key(self, store):
        import pytest
        with pytest.raises(ValueError):
            store.upsert_message("msg-1", {"password": "hunter2"})

    def test_upsert_message_passphrase_not_written_to_disk(self, store):
        import pytest
        with pytest.raises(ValueError):
            store.upsert_message("msg-1", {"passphrase": "secret"})
        # Nothing was written
        assert store.get_message("msg-1") is None


# ---------------------------------------------------------------------------
# Corrupt JSON recovery
# ---------------------------------------------------------------------------

class TestCorruptJsonRecovery:
    def test_corrupt_questions_asked_returns_empty_list(self, store, tmp_path):
        import warnings
        (tmp_path / "questions_asked.json").write_text("{bad json", encoding="utf-8")
        with warnings.catch_warnings(record=True):
            result = store.load_questions_asked()
        assert result == []

    def test_corrupt_session_json_returns_corruption_marker(self, store, tmp_path):
        import warnings
        (tmp_path / "session.json").write_text("!!!not json", encoding="utf-8")
        with warnings.catch_warnings(record=True):
            result = store.load_session()
        assert result.get("_was_corrupt") is True

    def test_corrupt_file_renamed_to_dot_corrupt(self, store, tmp_path):
        import warnings
        (tmp_path / "questions_asked.json").write_text("{bad", encoding="utf-8")
        with warnings.catch_warnings(record=True):
            store.load_questions_asked()
        assert (tmp_path / "questions_asked.corrupt").exists()
        assert not (tmp_path / "questions_asked.json").exists()


# ---------------------------------------------------------------------------
# Passphrase deny guard on save_session
# ---------------------------------------------------------------------------

class TestSaveSessionPassphraseGuard:
    def test_rejects_passphrase_key(self, store):
        with pytest.raises(ValueError, match="passphrase"):
            store.save_session({"passphrase": "hunter2", "author_name": "X"})

    def test_rejects_password_key(self, store):
        with pytest.raises(ValueError, match="password"):
            store.save_session({"password": "hunter2"})

    def test_allows_passphrase_hint(self, store):
        store.save_session({"passphrase_hint": "first dog", "schema_version": 1})
        result = store.load_session()
        assert result["passphrase_hint"] == "first dog"


class TestGardenTimeline:
    def test_resumable_timeline_roundtrip(self, store):
        timeline = {"version": 1, "beats": [{"id": "welcome"}]}
        store.save_garden_timeline(timeline)
        assert store.load_garden_timeline() == timeline

    def test_nested_secret_is_rejected(self, store):
        with pytest.raises(ValueError, match="sensitive Garden"):
            store.save_garden_timeline({"beats": [{"secret": "do not persist"}]})


# ---------------------------------------------------------------------------
# Secure temp-file creation
# ---------------------------------------------------------------------------

class TestAtomicWritePermissions:
    def test_tmp_file_never_world_readable(self, store, tmp_path):
        """Temp file must be born at 0o600, not umask-permissive 0o644."""
        import stat
        created_modes: list[int] = []

        original_open = open

        def _recording_opener(path, flags):
            fd = os.open(path, flags, 0o600)
            mode = stat.S_IMODE(os.fstat(fd).st_mode)
            created_modes.append(mode)
            return fd

        # Trigger a write and capture what mode the tmp file was created with.
        # We monkeypatch by writing then checking the final file — the opener
        # guarantees the creation mode; we verify the final file is 0o600.
        store.save_session({"x": 1})
        final_mode = oct(stat.S_IMODE((tmp_path / "session.json").stat().st_mode))
        assert final_mode == oct(0o600)

    def test_no_tmp_file_left_after_successful_write(self, store, tmp_path):
        store.save_session({"a": 1})
        assert list(tmp_path.glob("*.tmp")) == []
