"""Tests for the intake data model and validation (§5.1)."""

import pytest

from lateletter.intake import (
    IntakeData,
    KeyDate,
    load_intake,
    passphrase_communication_warning,
    passphrase_strength_warning,
    save_intake,
    validate_intake,
    validate_passphrase,
)
from lateletter.session_store import SessionStore


def _valid_intake(**overrides) -> IntakeData:
    defaults = dict(
        author_name="Robert",
        relationship="Father",
        recipient_name="Maya",
        recipient_relationship="Daughter",
        key_dates=[KeyDate(label="Maya's birthday", date="June 15")],
        memory_tags=["dogs", "hiking"],
        steward_name="Sarah Chen",
        steward_contact="sarah@example.com",
        release_unfinished=False,
        release_date=None,
        passphrase_hint="What we called our first dog",
    )
    defaults.update(overrides)
    return IntakeData(**defaults)


class TestIntakeData:
    def test_roundtrip(self):
        data = _valid_intake()
        d = data.to_session_dict()
        restored = IntakeData.from_session_dict(d)
        assert restored.author_name == "Robert"
        assert restored.recipient_name == "Maya"
        assert restored.steward_name == "Sarah Chen"
        assert restored.passphrase_hint == "What we called our first dog"
        assert d["schema_version"] == 1
        assert len(restored.key_dates) == 1

    def test_passphrase_keys_never_in_session_dict(self):
        d = _valid_intake().to_session_dict()
        for key in ("passphrase", "passphrase_confirm", "key", "secret", "password"):
            assert key not in d

    def test_consent_block(self):
        d = _valid_intake(release_unfinished=True, release_date="2027-01-01").to_session_dict()
        assert d["consent"]["release_unfinished"] is True
        assert d["consent"]["default_release_date"] == "2027-01-01"
        # No steward → allow_steward_access False
        d2 = _valid_intake(steward_name="").to_session_dict()
        assert d2["consent"]["allow_steward_access"] is False

    def test_from_empty_dict(self):
        restored = IntakeData.from_session_dict({})
        assert restored.author_name == ""
        assert restored.key_dates == []


@pytest.mark.parametrize("field,value", [
    ("author_name", ""),
    ("relationship", ""),
    ("recipient_name", ""),
    ("recipient_relationship", ""),
    ("passphrase_hint", ""),
])
def test_required_field_produces_error(field, value):
    errors = validate_intake(_valid_intake(**{field: value}))
    assert any(e.field == field for e in errors)


def test_key_dates_required():
    errors = validate_intake(_valid_intake(key_dates=[]))
    assert any(e.field == "key_dates" for e in errors)


def test_optional_fields_pass():
    assert validate_intake(_valid_intake(memory_tags=[], steward_name="", steward_contact="")) == []


def test_release_unfinished_requires_date():
    errors = validate_intake(_valid_intake(release_unfinished=True, release_date=None))
    assert any(e.field == "release_date" for e in errors)
    assert validate_intake(_valid_intake(release_unfinished=True, release_date="2027-01-01")) == []


class TestValidatePassphrase:
    def test_match(self):
        assert validate_passphrase("secret phrase", "secret phrase") == []

    def test_mismatch(self):
        assert any(e.field == "passphrase_confirm" for e in validate_passphrase("a", "b"))

    def test_empty(self):
        errors = validate_passphrase("", "anything")
        assert len(errors) == 1
        assert errors[0].field == "passphrase"

    def test_service_four_character_floor(self):
        errors = validate_passphrase("123", "123")
        assert any(
            error.field == "passphrase"
            and "at least 4 characters" in error.message
            for error in errors
        )
        assert validate_passphrase("1234", "1234") == []


@pytest.mark.parametrize("phrase,expect_warn", [
    ("abc", True),           # short
    ("password", True),      # common
    ("aaaaaaaa", True),      # repetitive
    ("correct horse battery staple", False),
    ("", False),
])
def test_passphrase_strength_warning(phrase, expect_warn):
    assert (passphrase_strength_warning(phrase) is not None) == expect_warn


def test_passphrase_communication_warning():
    msg = passphrase_communication_warning("Maya")
    assert "Maya" in msg and "lost forever" in msg


class TestSessionIntegration:
    def test_save_load_roundtrip(self, tmp_path):
        store = SessionStore(base_dir=tmp_path)
        save_intake(_valid_intake(), store)
        loaded = load_intake(store)
        assert loaded is not None
        assert loaded.author_name == "Robert"

    def test_save_preserves_existing_messages(self, tmp_path):
        store = SessionStore(base_dir=tmp_path)
        store.save_session({"schema_version": 1, "messages": [{"id": "msg-1"}]})
        save_intake(_valid_intake(), store)
        session = store.load_session()
        assert session["messages"][0]["id"] == "msg-1"
        assert session["author_name"] == "Robert"

    def test_save_preserves_unknown_keys(self, tmp_path):
        store = SessionStore(base_dir=tmp_path)
        store.save_session({"schema_version": 1, "future_field": "keep me"})
        save_intake(_valid_intake(), store)
        assert store.load_session()["future_field"] == "keep me"

    def test_load_empty_returns_none(self, tmp_path):
        assert load_intake(SessionStore(base_dir=tmp_path)) is None
