"""Tests for the real encryption layer (sealed.py)."""

from __future__ import annotations

import pytest

from lateletter.bundle import Bundle, GardenGift, Trigger
from lateletter.sealed import (
    KDF_PARAMS_V0,
    compute_bundle_hmac,
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


def test_unicode_body_survives():
    msg = seal_message(
        PASS, message_id="m2", date="2027-01-01",
        label="день рождения", body="Café ☕ — 你好\n⚘",
    )
    assert open_message(PASS, msg)["body"] == "Café ☕ — 你好\n⚘"
