"""Regression test for the author demo's canonical sealed artifact."""

from demo_author import PASSPHRASE, run_demo
from lateletter.bundle import read_bundle, verify_checksum
from lateletter.sealed import open_message, verify_bundle_hmac


def test_demo_author_writes_valid_sealed_bundle(tmp_path):
    path = tmp_path / "demo.lateletter"
    run_demo(path, quiet=True)

    bundle = read_bundle(path)
    assert verify_checksum(bundle)
    assert verify_bundle_hmac(bundle, PASSPHRASE)
    assert open_message(PASSPHRASE, bundle.messages[0])["body"].startswith(
        "Dear Maya,"
    )
