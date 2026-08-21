"""Regression test for the author demo's canonical sealed artifact."""

import pytest

from demo_author import (
    PASSPHRASE,
    _REPOSITORY_ROOT,
    _validate_demo_output,
    run_demo,
)
from lateletter.bundle import (
    BUNDLE_VERSION_WITH_GARDEN_PROGRAM,
    read_bundle,
    verify_checksum,
)
from lateletter.garden.program import parse_program
from lateletter.sealed import open_garden_program, open_message, verify_bundle_hmac


def test_demo_author_writes_valid_sealed_bundle(tmp_path):
    path = tmp_path / "demo.lateletter"
    run_demo(path, quiet=True)

    bundle = read_bundle(path)
    assert verify_checksum(bundle)
    assert verify_bundle_hmac(bundle, PASSPHRASE)
    assert open_message(PASSPHRASE, bundle.messages[0])["body"].startswith(
        "Dear Maya,"
    )
    assert bundle.version == BUNDLE_VERSION_WITH_GARDEN_PROGRAM
    assert bundle.garden_gifts == []
    program = parse_program(open_garden_program(PASSPHRASE, bundle.garden_program))
    assert {event.id for event in program.events} == {"rabbit-arrives", "food-appears"}
    assert program.animals[0]["name"] == "Clover"
    assert program.animals[0]["personality"] == "cautious, patient, and curious"


def test_demo_refuses_to_overwrite_tracked_bundle():
    with pytest.raises(ValueError, match="tracked"):
        _validate_demo_output(_REPOSITORY_ROOT / "sealed_demo.lateletter")
