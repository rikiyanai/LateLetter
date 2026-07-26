"""
Tests for .lateletter bundle format — schema, reader, writer, validation.

Uses tmp_path so tests never touch real files.
"""

import json
import os
import stat
from pathlib import Path

import pytest

from lateletter.bundle import (
    Bundle,
    BundleValidationError,
    GardenGift,
    Message,
    Notification,
    Trigger,
    canonical_json,
    create_dev_fixture,
    read_bundle,
    verify_checksum,
    write_bundle,
)


# ---------------------------------------------------------------------------
# canonical_json
# ---------------------------------------------------------------------------

class TestCanonicalJson:
    def test_sorted_keys(self):
        result = canonical_json({"b": 1, "a": 2})
        assert result == b'{"a":2,"b":1}'

    def test_compact_separators(self):
        result = canonical_json({"x": [1, 2, 3]})
        assert b" " not in result

    def test_recursive_sorting(self):
        result = canonical_json({"z": {"b": 1, "a": 2}})
        assert result == b'{"z":{"a":2,"b":1}}'

    def test_utf8_encoding(self):
        result = canonical_json({"name": "Mäya"})
        assert "Mäya".encode("utf-8") in result
        assert b"\\u" not in result  # ensure_ascii=False

    def test_deterministic(self):
        obj = {"c": 3, "a": 1, "b": {"z": 26, "y": 25}}
        assert canonical_json(obj) == canonical_json(obj)

    def test_none_value(self):
        result = canonical_json({"a": None})
        assert result == b'{"a":null}'


# ---------------------------------------------------------------------------
# Data classes — round-trip serialization
# ---------------------------------------------------------------------------

class TestTrigger:
    def test_roundtrip(self):
        t = Trigger(type="date", value="2027-06-15")
        assert Trigger.from_dict(t.to_dict()) == t

    def test_all_trigger_types(self):
        for typ, val in [
            ("date", "2027-06-15"),
            ("cumulative_visits", "10"),
            ("post_letter", "abc-123"),
        ]:
            t = Trigger(type=typ, value=val)
            d = t.to_dict()
            assert d["type"] == typ
            assert d["value"] == val


class TestGardenGift:
    def test_roundtrip(self):
        g = GardenGift(
            id="gift-1",
            type="item",
            catalog_id="plate_of_food",
            trigger=Trigger(type="date", value="2027-06-15"),
            placement_hint="near_tallest_tree",
            sentiment_ciphertext="cGxhaW50ZXh0",  # base64 placeholder
            salt="c2FsdA==",
            nonce="bm9uY2U=",
        )
        assert GardenGift.from_dict(g.to_dict()) == g

    def test_animal_fields(self):
        g = GardenGift(
            id="gift-2",
            type="animal",
            catalog_id="cat",
            trigger=Trigger(type="cumulative_visits", value="7"),
            animal_name="Whiskers",
            animal_collar_color="blue",
        )
        d = g.to_dict()
        assert d["animal_name"] == "Whiskers"
        assert d["animal_collar_color"] == "blue"
        assert GardenGift.from_dict(d).animal_name == "Whiskers"

    def test_defaults(self):
        g = GardenGift(
            id="g", type="plant", catalog_id="sapling",
            trigger=Trigger(type="date", value="2028-01-01"),
        )
        assert g.placement_hint == "random"
        assert g.animal_name is None


class TestMessage:
    def test_roundtrip(self):
        m = Message(
            id="msg-1", date="2027-06-15",
            ciphertext="Y2lwaGVy", salt="c2FsdA==", nonce="bm9uY2U=",
        )
        assert Message.from_dict(m.to_dict()) == m

    def test_kdf_params_none(self):
        m = Message(id="m", date="2027-01-01")
        assert m.to_dict()["kdf_params"] is None

    def test_kdf_params_custom(self):
        params = {"time_cost": 4, "memory_cost": 131072}
        m = Message(id="m", date="2027-01-01", kdf_params=params)
        assert Message.from_dict(m.to_dict()).kdf_params == params


class TestNotification:
    def test_roundtrip_with_email(self):
        n = Notification(email="maya@example.com", method="self-hosted")
        d = n.to_dict()
        assert d == {"email": "maya@example.com", "method": "self-hosted"}
        assert Notification.from_dict(d) == n

    def test_none_returns_none_dict(self):
        n = Notification()
        assert n.to_dict() is None

    def test_from_none(self):
        n = Notification.from_dict(None)
        assert n.email is None
        assert n.method is None


# ---------------------------------------------------------------------------
# Bundle
# ---------------------------------------------------------------------------

class TestBundle:
    def test_visible_payload_excludes_checksum_hmac(self):
        b = Bundle(author_name="Robert")
        vp = b.visible_payload()
        assert "checksum" not in vp
        assert "hmac" not in vp

    def test_visible_payload_includes_all_fields(self):
        b = Bundle(author_name="Robert")
        vp = b.visible_payload()
        for key in ("version", "bundle_id", "author_name", "passphrase_hint",
                     "bundle_auth_salt", "garden_seed", "messages",
                     "garden_gifts", "notification"):
            assert key in vp

    def test_compute_checksum_is_deterministic(self):
        b = Bundle(bundle_id="fixed", author_name="Robert", garden_seed=42)
        assert b.compute_checksum() == b.compute_checksum()

    def test_checksum_changes_on_mutation(self):
        b = Bundle(bundle_id="fixed", author_name="Robert")
        c1 = b.compute_checksum()
        b.author_name = "Sarah"
        c2 = b.compute_checksum()
        assert c1 != c2

    def test_to_dict_includes_checksum_hmac(self):
        b = Bundle()
        b.checksum = "abc"
        b.hmac = "def"
        d = b.to_dict()
        assert d["checksum"] == "abc"
        assert d["hmac"] == "def"


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------

class TestValidation:
    def test_valid_bundle_dict(self):
        b = create_dev_fixture()
        errors = []
        from lateletter.bundle import validate_bundle_dict
        errors = validate_bundle_dict(b.to_dict())
        assert errors == []

    def test_missing_version(self):
        from lateletter.bundle import validate_bundle_dict
        errors = validate_bundle_dict({"bundle_id": "x"})
        assert any("version" in e for e in errors)

    def test_wrong_version(self):
        from lateletter.bundle import validate_bundle_dict
        errors = validate_bundle_dict({"version": 99, "bundle_id": "x"})
        assert any("Unsupported" in e for e in errors)

    def test_missing_bundle_id(self):
        from lateletter.bundle import validate_bundle_dict
        errors = validate_bundle_dict({"version": 1})
        assert any("bundle_id" in e for e in errors)

    def test_bad_messages_type(self):
        from lateletter.bundle import validate_bundle_dict
        errors = validate_bundle_dict({
            "version": 1, "bundle_id": "x", "messages": "not a list",
        })
        assert any("messages" in e and "list" in e for e in errors)

    def test_message_missing_id(self):
        from lateletter.bundle import validate_bundle_dict
        errors = validate_bundle_dict({
            "version": 1, "bundle_id": "x",
            "messages": [{"date": "2027-01-01"}],
        })
        assert any("messages[0]" in e for e in errors)

    def test_gift_missing_trigger(self):
        from lateletter.bundle import validate_bundle_dict
        errors = validate_bundle_dict({
            "version": 1, "bundle_id": "x",
            "garden_gifts": [{"id": "g1", "type": "item"}],
        })
        assert any("garden_gifts[0]" in e for e in errors)

    def test_bad_garden_seed_type(self):
        from lateletter.bundle import validate_bundle_dict
        errors = validate_bundle_dict({
            "version": 1, "bundle_id": "x", "garden_seed": "not_int",
        })
        assert any("garden_seed" in e for e in errors)

    def test_from_dict_raises_on_invalid(self):
        with pytest.raises(BundleValidationError) as exc_info:
            Bundle.from_dict({"version": 99, "bundle_id": "x"})
        assert "Unsupported" in str(exc_info.value)


# ---------------------------------------------------------------------------
# Checksum verification
# ---------------------------------------------------------------------------

class TestChecksum:
    def test_verify_checksum_valid(self):
        b = create_dev_fixture()
        b.checksum = b.compute_checksum()
        assert verify_checksum(b)

    def test_verify_checksum_corrupt(self):
        b = create_dev_fixture()
        b.checksum = "0" * 64
        assert not verify_checksum(b)

    def test_verify_checksum_empty(self):
        b = create_dev_fixture()
        b.checksum = ""
        assert not verify_checksum(b)


# ---------------------------------------------------------------------------
# Writer / Reader round-trip
# ---------------------------------------------------------------------------

class TestWriteRead:
    def test_roundtrip(self, tmp_path):
        path = tmp_path / "test.lateletter"
        original = create_dev_fixture()
        write_bundle(original, path)
        loaded = read_bundle(path)

        assert loaded.version == original.version
        assert loaded.bundle_id == original.bundle_id
        assert loaded.author_name == original.author_name
        assert loaded.passphrase_hint == original.passphrase_hint
        assert loaded.garden_seed == original.garden_seed
        assert len(loaded.messages) == len(original.messages)
        assert len(loaded.garden_gifts) == len(original.garden_gifts)

    def test_checksum_set_on_write(self, tmp_path):
        path = tmp_path / "test.lateletter"
        b = create_dev_fixture()
        assert b.checksum == ""
        write_bundle(b, path)
        assert b.checksum != ""
        loaded = read_bundle(path)
        assert verify_checksum(loaded)

    def test_file_permissions(self, tmp_path):
        path = tmp_path / "test.lateletter"
        write_bundle(create_dev_fixture(), path)
        mode = oct(stat.S_IMODE(path.stat().st_mode))
        assert mode == oct(0o600), f"Expected 0o600, got {mode}"

    def test_no_tmp_file_left(self, tmp_path):
        path = tmp_path / "test.lateletter"
        write_bundle(create_dev_fixture(), path)
        tmp_files = list(tmp_path.glob("*.tmp"))
        assert tmp_files == [], f"Leftover .tmp files: {tmp_files}"

    def test_file_is_valid_json(self, tmp_path):
        path = tmp_path / "test.lateletter"
        write_bundle(create_dev_fixture(), path)
        data = json.loads(path.read_text())
        assert data["version"] == 1
        assert isinstance(data["messages"], list)
        assert isinstance(data["garden_gifts"], list)

    def test_read_nonexistent_raises(self, tmp_path):
        with pytest.raises(FileNotFoundError):
            read_bundle(tmp_path / "nope.lateletter")

    def test_read_corrupt_json_raises(self, tmp_path):
        path = tmp_path / "bad.lateletter"
        path.write_text("{{not valid json")
        with pytest.raises(json.JSONDecodeError):
            read_bundle(path)

    def test_read_invalid_schema_raises(self, tmp_path):
        path = tmp_path / "bad.lateletter"
        path.write_text(json.dumps({"version": 99, "bundle_id": "x"}))
        with pytest.raises(BundleValidationError):
            read_bundle(path)

    def test_overwrite_existing(self, tmp_path):
        path = tmp_path / "test.lateletter"
        b1 = create_dev_fixture(author_name="Alice")
        write_bundle(b1, path)
        b2 = create_dev_fixture(author_name="Bob")
        write_bundle(b2, path)
        loaded = read_bundle(path)
        assert loaded.author_name == "Bob"


# ---------------------------------------------------------------------------
# Dev fixture
# ---------------------------------------------------------------------------

class TestDevFixture:
    def test_creates_valid_bundle(self):
        b = create_dev_fixture()
        assert b.version == 1
        assert b.author_name == "Robert"
        assert len(b.messages) == 3
        assert len(b.garden_gifts) == 4

    def test_gift_trigger_types_present(self):
        b = create_dev_fixture()
        types = {g.trigger.type for g in b.garden_gifts}
        assert "date" in types
        assert "cumulative_visits" in types
        assert "post_letter" in types

    def test_messages_have_base64_fields(self):
        import base64
        b = create_dev_fixture()
        for m in b.messages:
            # Should be valid base64
            base64.b64decode(m.ciphertext)
            base64.b64decode(m.salt)
            base64.b64decode(m.nonce)

    def test_no_gifts_option(self):
        b = create_dev_fixture(include_gifts=False)
        assert b.garden_gifts == []

    def test_no_notification(self):
        b = create_dev_fixture(notification_email=None)
        assert b.notification.email is None

    def test_custom_dates(self):
        dates = ["2030-01-01", "2030-07-04"]
        b = create_dev_fixture(message_dates=dates)
        assert len(b.messages) == 2
        assert b.messages[0].date == "2030-01-01"

    def test_post_letter_gift_references_real_message(self):
        b = create_dev_fixture()
        post_letter_gifts = [
            g for g in b.garden_gifts if g.trigger.type == "post_letter"
        ]
        msg_ids = {m.id for m in b.messages}
        for g in post_letter_gifts:
            assert g.trigger.value in msg_ids, (
                f"post_letter gift references {g.trigger.value} "
                f"but valid message IDs are {msg_ids}"
            )
