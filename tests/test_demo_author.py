"""Regression test for the author demo's canonical sealed artifact."""

from demo_author import PASSPHRASE, run_demo
from lateletter.bundle import BUNDLE_VERSION_WITH_GARDEN_PROGRAM, read_bundle, verify_checksum
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
