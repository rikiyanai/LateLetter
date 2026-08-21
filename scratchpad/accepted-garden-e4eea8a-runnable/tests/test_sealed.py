"""Tests for the real encryption layer (sealed.py)."""

from __future__ import annotations

import pytest

from lateletter.bundle import (
    Bundle,
    BundleValidationError,
    GardenGift,
    Trigger,
    create_dev_fixture,
)
from lateletter.sealed import (
    KDF_PARAMS_V0,
    bundle_persistence_binding,
    compute_bundle_hmac,
    derive_key,
    open_gift_sentiment,
    open_message,
    seal_bundle,
    seal_gift_sentiment,
    seal_message,
    verify_bundle_hmac,
)

PASS = "correct horse"


def _sealed_bundle() -> Bundle:
    msg = seal_message(
        PASS, message_id="m1", date="2027-06-15",
        label="Her 30th birthday", body="Dear Maya,\n\nLove, Dad",
    )
    gift = GardenGift(
        id="g1", type="item", catalog_id="coffee_mug",
        trigger=Trigger(type="date", value="2027-06-15"),
    )
    seal_gift_sentiment(PASS, gift, "Two sugars, always.")
    bundle = Bundle(
        author_name="Robert", passphrase_hint="first dog",
        garden_seed=42301, messages=[msg], garden_gifts=[gift],
    )
    seal_bundle(bundle, PASS)
    return bundle


def test_message_round_trip():
    bundle = _sealed_bundle()
    content = open_message(PASS, bundle.messages[0])
    assert content == {"label": "Her 30th birthday",
                       "body": "Dear Maya,\n\nLove, Dad"}


def test_message_records_kdf_params():
    bundle = _sealed_bundle()
    assert bundle.messages[0].kdf_params == KDF_PARAMS_V0


def test_wrong_passphrase_fails_decrypt():
    bundle = _sealed_bundle()
    with pytest.raises(Exception):
        open_message("wrong", bundle.messages[0])


def test_gift_sentiment_round_trip():
    bundle = _sealed_bundle()
    assert open_gift_sentiment(PASS, bundle.garden_gifts[0]) == \
        "Two sugars, always."


def test_bundle_hmac_verifies():
    bundle = _sealed_bundle()
    assert verify_bundle_hmac(bundle, PASS)
    assert not verify_bundle_hmac(bundle, "wrong")


def test_hmac_detects_tampering():
    bundle = _sealed_bundle()
    bundle.messages[0].date = "2020-01-01"  # attacker moves delivery date
    assert not verify_bundle_hmac(bundle, PASS)


def test_checksum_set_on_seal():
    bundle = _sealed_bundle()
    assert bundle.checksum == bundle.compute_checksum()


def test_hmac_stable_across_reserialization():
    bundle = _sealed_bundle()
    reparsed = Bundle.from_dict(bundle.to_dict())
    assert compute_bundle_hmac(reparsed, PASS) == bundle.hmac


def test_persistence_binding_is_stable_and_bound_to_sealed_identity():
    bundle = _sealed_bundle()
    reparsed = Bundle.from_dict(bundle.to_dict())
    binding = bundle_persistence_binding(bundle, PASS)
    assert len(binding) == 64
    assert binding == bundle_persistence_binding(reparsed, PASS)

    other = _sealed_bundle()
    other.bundle_id = bundle.bundle_id
    seal_bundle(other, PASS)
    assert bundle_persistence_binding(other, PASS) != binding


def test_persistence_binding_survives_legitimate_reseal_append():
    bundle = _sealed_bundle()
    binding = bundle_persistence_binding(bundle, PASS)
    bundle.messages.append(seal_message(
        PASS, message_id="m2", date="2028-01-01", label="Later", body="Still here.",
    ))
    seal_bundle(bundle, PASS)
    assert bundle_persistence_binding(bundle, PASS) == binding


def test_unicode_body_survives():
    msg = seal_message(
        PASS, message_id="m2", date="2027-01-01",
        label="день рождения", body="Café ☕ — 你好\n⚘",
    )
    assert open_message(PASS, msg)["body"] == "Café ☕ — 你好\n⚘"


@pytest.mark.parametrize("params", [
    {"name": "PBKDF2", "hash": "SHA-256", "iterations": True},
    {"name": "PBKDF2", "hash": "SHA-256", "iterations": "600000"},
    {"name": "PBKDF2", "hash": "SHA-256", "iterations": 599_999},
    {"name": "PBKDF2", "hash": "SHA-256", "iterations": 2_000_001},
    {"name": "pbkdf2", "hash": "SHA-256", "iterations": 600_000},
    {"name": "PBKDF2", "hash": "sha256", "iterations": 600_000},
    {
        "name": "PBKDF2", "hash": "SHA-256", "iterations": 600_000,
        "dklen": 1,
    },
])
def test_derive_key_rejects_noncanonical_or_unsafe_params(params):
    with pytest.raises(ValueError):
        derive_key(PASS, b"s" * 16, params)


def test_huge_kdf_is_rejected_before_pbkdf2(monkeypatch):
    called = False

    def forbidden_pbkdf2(*args, **kwargs):
        nonlocal called
        called = True
        raise AssertionError("PBKDF2 must not run for rejected work factors")

    monkeypatch.setattr("lateletter.sealed.hashlib.pbkdf2_hmac", forbidden_pbkdf2)
    with pytest.raises(ValueError, match="between"):
        derive_key(
            PASS,
            b"s" * 16,
            {"name": "PBKDF2", "hash": "SHA-256", "iterations": 10**12},
        )
    assert called is False


def test_open_message_rejects_invalid_base64_and_nonce_shape_before_decrypt():
    message = seal_message(
        PASS, message_id="m-shape", date="2027-01-01", label="Label", body="Body",
    )
    message.nonce = "not base64!"
    with pytest.raises(ValueError, match="base64"):
        open_message(PASS, message)

    message = seal_message(
        PASS, message_id="m-shape", date="2027-01-01", label="Label", body="Body",
    )
    message.salt = "c2hvcnQ="
    with pytest.raises(ValueError, match="16 bytes"):
        open_message(PASS, message)


def test_seal_bundle_refuses_plaintext_fixture_message_shape():
    fixture = create_dev_fixture(include_gifts=False)

    with pytest.raises(BundleValidationError, match="kdf_params"):
        seal_bundle(fixture, PASS)
    assert fixture.hmac == ""
