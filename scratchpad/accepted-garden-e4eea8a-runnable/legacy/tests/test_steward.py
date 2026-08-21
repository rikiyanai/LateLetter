"""Tests for steward and incapacitation handling (§5.6)."""

from lateletter.session_store import SessionStore
from lateletter.steward import (
    HandoffSummary,
    StewardInfo,
    compact_session,
    format_handoff_text,
)


def _session(**overrides):
    base = {
        "schema_version": 1,
        "author_name": "Robert",
        "recipient_name": "Maya",
        "steward_name": "Sarah Chen",
        "steward_contact": "sarah@example.com",
        "passphrase_hint": "What we called our first dog",
        "consent": {
            "release_unfinished": False,
            "default_release_date": None,
            "allow_steward_access": True,
        },
        "messages": [],
    }
    base.update(overrides)
    return base


class TestStewardInfo:
    def test_extracts_from_session(self):
        info = StewardInfo.from_session(_session())
        assert info.name == "Sarah Chen" and info.contact == "sarah@example.com"

    def test_none_when_no_steward(self):
        assert StewardInfo.from_session(_session(steward_name="")) is None

    def test_release_unfinished(self):
        info = StewardInfo.from_session(_session(consent={
            "release_unfinished": True, "default_release_date": "2027-06-15",
            "allow_steward_access": True,
        }))
        assert info.release_unfinished is True and info.release_date == "2027-06-15"


class TestHandoffSummary:
    def test_counts(self):
        s = HandoffSummary.from_session(_session(messages=[
            {"id": "m1", "status": "encrypted"},
            {"id": "m2", "status": "encrypted"},
            {"id": "m3", "status": "pending"},
            {"id": "m4", "status": "written"},
        ]))
        assert s.total_messages == 4
        assert s.completed_messages == 2
        assert s.pending_messages == 2

    def test_unfinished_notes_detection(self):
        s1 = HandoffSummary.from_session(_session(messages=[
            {"id": "m1", "status": "pending", "qa_answers": [{"q": "a"}]},
        ]))
        assert s1.has_unfinished_notes is True
        # Encrypted messages don't count as unfinished
        s2 = HandoffSummary.from_session(_session(messages=[
            {"id": "m1", "status": "encrypted", "qa_answers": [{"q": "a"}]},
        ]))
        assert s2.has_unfinished_notes is False


class TestFormatHandoffText:
    def test_contains_essential_info(self):
        text = format_handoff_text(HandoffSummary.from_session(_session()))
        assert "Robert" in text and "Maya" in text
        assert "Sarah Chen" in text
        assert "first dog" in text
        assert "NOT stored" in text
        assert "Only deliver completed" in text

    def test_release_unfinished_variant(self):
        text = format_handoff_text(HandoffSummary.from_session(_session(consent={
            "release_unfinished": True, "default_release_date": "2027-06-15",
            "allow_steward_access": True,
        })))
        assert "Release all" in text and "2027-06-15" in text


class TestCompactSession:
    def test_removes_encrypted_preserves_pending(self, tmp_path):
        store = SessionStore(base_dir=tmp_path)
        store.save_session(_session(messages=[
            {"id": "m1", "status": "encrypted", "qa_answers": [{"q": "a"}]},
            {"id": "m2", "status": "pending", "qa_answers_draft": [{"q": "b"}]},
        ]))
        removed = compact_session(store)
        assert removed == 1
        session = store.load_session()
        assert len(session["messages"]) == 1
        assert session["messages"][0]["id"] == "m2"
        # Intake fields preserved
        assert session["author_name"] == "Robert"
        assert session["steward_name"] == "Sarah Chen"

    def test_empty_messages(self, tmp_path):
        store = SessionStore(base_dir=tmp_path)
        store.save_session(_session())
        assert compact_session(store) == 0
