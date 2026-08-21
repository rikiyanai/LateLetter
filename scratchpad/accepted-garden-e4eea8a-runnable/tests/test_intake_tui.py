"""Tests for intake_tui field building, parsing, and input handling."""

from lateletter.intake import IntakeData, KeyDate
from lateletter.intake_tui import (
    FormField,
    _build_fields,
    _field_row,
    _fields_to_intake,
    _handle_text_input,
    _parse_key_dates,
)


class TestParseKeyDates:
    def test_basic_parsing(self):
        assert _parse_key_dates("") == []
        r = _parse_key_dates("Birthday: June 15; Wedding: Sep 2028")
        assert len(r) == 2
        assert r[0].label == "Birthday" and r[0].date == "June 15"

    def test_no_colon_stores_as_label(self):
        r = _parse_key_dates("someday")
        assert r[0].label == "someday" and r[0].date == ""

    def test_multiple_colons_preserved(self):
        r = _parse_key_dates("Meeting: 10:30am")
        assert r[0].date == "10:30am"

    def test_trailing_semicolons_ignored(self):
        assert len(_parse_key_dates("Birthday: June 15; ; ")) == 1


class TestFieldsRoundtrip:
    def test_build_and_extract(self):
        original = IntakeData(
            author_name="Robert", relationship="Father",
            recipient_name="Maya", recipient_relationship="Daughter",
            key_dates=[KeyDate("Birthday", "June 15")],
            memory_tags=["dogs", "hiking"],
            steward_name="Sarah", steward_contact="sarah@x.com",
            passphrase_hint="first dog",
        )
        fields = _build_fields(original)
        restored = _fields_to_intake(fields)
        assert restored.author_name == "Robert"
        assert restored.memory_tags == ["dogs", "hiking"]
        assert restored.key_dates[0].label == "Birthday"

    def test_prepopulation(self):
        fields = _build_fields(IntakeData(author_name="Robert", recipient_name="Maya",
                                          key_dates=[KeyDate("Birthday", "June 15")]))
        by_name = {f.name: f for f in fields}
        assert by_name["author_name"].value == "Robert"
        assert by_name["passphrase"].masked is True
        assert by_name["release_choice"].is_radio is True

    def test_release_unfinished_from_radio(self):
        fields = _build_fields(None)
        by_name = {f.name: f for f in fields}
        by_name["release_choice"].radio_selected = 1
        by_name["release_date"].value = "2027-01-01"
        result = _fields_to_intake(fields)
        assert result.release_unfinished is True


class TestHandleTextInput:
    def test_passphrase_routing(self):
        """Passphrase chars go into the return var, not just fld.value."""
        fld = FormField("passphrase", "Passphrase", masked=True)
        pp, _ = _handle_text_input(ord("a"), fld, "", "")
        assert pp == "a" and fld.value == "a"
        # Confirm field is independent
        fld2 = FormField("passphrase_confirm", "Confirm", masked=True)
        _, ppc = _handle_text_input(ord("b"), fld2, "secret", "")
        assert ppc == "b"

    def test_regular_field_does_not_touch_passphrase(self):
        fld = FormField("author_name", "Name", value="Rob")
        pp, ppc = _handle_text_input(ord("x"), fld, "secret", "secret")
        assert fld.value == "Robx" and pp == "secret"

    def test_backspace(self):
        fld = FormField("passphrase", "Passphrase", value="abc", masked=True)
        pp, _ = _handle_text_input(127, fld, "abc", "")
        assert pp == "ab" and fld.value == "ab"

    def test_error_cleared_on_input(self):
        fld = FormField("author_name", "Name", error="required")
        _handle_text_input(ord("x"), fld, "", "")
        assert fld.error == ""


class TestFieldRow:
    def test_radio_adds_extra_rows(self):
        fields = _build_fields(None)
        radio_idx = next(i for i, f in enumerate(fields) if f.name == "release_choice")
        row_at = _field_row(fields, radio_idx)
        row_after = _field_row(fields, radio_idx + 1)
        assert row_after == row_at + 3  # label + 2 options
