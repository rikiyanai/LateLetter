"""Version 2 encrypted Garden-program bundle contract."""

from __future__ import annotations

from copy import deepcopy

import pytest

from lateletter.bundle import (
    BUNDLE_VERSION_WITH_GARDEN_PROGRAM,
    Bundle,
    BundleValidationError,
    GardenGift,
    Trigger,
)
from lateletter.sealed import (
    KDF_PARAMS_V0,
    open_garden_program,
    seal_bundle,
    seal_garden_program,
    verify_bundle_hmac,
)


PASS = "garden program passphrase"


def _program() -> dict:
    return {
        "version": 1,
        "evaluator_version": 1,
        "world_state_version": 1,
        "atlas_version": "garden-atlas-1",
        "astronomy_catalog_version": "bright-stars-1",
        "author_timezone": "UTC",
        "variables": {},
        "entities": [],
        "animals": [],
        "events": [],
    }


def _bundle() -> Bundle:
    bundle = Bundle(
        version=BUNDLE_VERSION_WITH_GARDEN_PROGRAM,
        bundle_id="v2-test",
        garden_seed=20260721,
        garden_program=seal_garden_program(PASS, _program()),
    )
    seal_bundle(bundle, PASS)
    return bundle


def test_v1_visible_payload_remains_frozen():
    payload = Bundle(version=1, bundle_id="v1").visible_payload()

    assert set(payload) == {
        "version", "bundle_id", "author_name", "passphrase_hint",
        "bundle_auth_salt", "garden_seed", "messages", "garden_gifts",
        "notification",
    }
    assert "garden_program" not in payload
    assert "bundle_auth_kdf_params" not in payload


def test_v2_program_round_trip_and_hmac():
    bundle = _bundle()
    reparsed = Bundle.from_dict(bundle.to_dict())

    assert reparsed.bundle_auth_kdf_params == KDF_PARAMS_V0
    assert reparsed.garden_program is not None
    assert open_garden_program(PASS, reparsed.garden_program) == _program()
    assert verify_bundle_hmac(reparsed, PASS)
    assert not verify_bundle_hmac(reparsed, "wrong")


def test_program_ciphertext_is_authenticated():
    bundle = _bundle()
    assert bundle.garden_program is not None
    bundle.garden_program.ciphertext = (
        "A" + bundle.garden_program.ciphertext[1:]
    )

    assert not verify_bundle_hmac(bundle, PASS)
    with pytest.raises(Exception):
        open_garden_program(PASS, bundle.garden_program)


def test_v2_rejects_legacy_gift_owner():
    bundle = _bundle()
    data = deepcopy(bundle.to_dict())
    data["garden_gifts"] = [GardenGift(
        id="legacy",
        type="item",
        catalog_id="coffee_mug",
        trigger=Trigger(type="date", value="2026-07-21"),
    ).to_dict()]

    with pytest.raises(BundleValidationError, match="garden_gifts"):
        Bundle.from_dict(data)


def test_v1_rejects_garden_program_extension():
    data = Bundle(version=1, bundle_id="v1").to_dict()
    data["garden_program"] = _bundle().garden_program.to_dict()

    with pytest.raises(BundleValidationError, match="Version 1"):
        Bundle.from_dict(data)


def test_v2_requires_explicit_auth_kdf_and_program():
    data = Bundle(
        version=BUNDLE_VERSION_WITH_GARDEN_PROGRAM,
        bundle_id="broken",
    ).to_dict()

    with pytest.raises(BundleValidationError) as exc:
        Bundle.from_dict(data)

    text = str(exc.value)
    assert "bundle_auth_kdf_params" in text
    assert "garden_program" in text


def test_seal_v2_refuses_missing_program():
    bundle = Bundle(
        version=BUNDLE_VERSION_WITH_GARDEN_PROGRAM,
        bundle_id="missing-program",
    )

    with pytest.raises(ValueError, match="garden program"):
        seal_bundle(bundle, PASS)
