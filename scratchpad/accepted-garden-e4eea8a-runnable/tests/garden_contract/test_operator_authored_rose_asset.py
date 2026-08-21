"""Durable intake contract for the operator-authored rose-bush art."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path


ROOT = Path(__file__).parents[2]
REGISTER = ROOT / "docs" / "garden-asset-acceptance.json"
PACKAGE = (
    ROOT
    / "tracked"
    / "LateLetterResearch"
    / "transcription-parity"
    / "eb861dc84400fc36"
)
EXPECTED_SHA256 = "04bce501c712fc071523711a3ea1b67a8af302434a66f0e638c2bdc144b0baac"
OPERATOR_STATEMENT = (
    "eb861dc84400fc36.provisional-not-pipeline.txt is approved rose bush art "
    "asset i just authored. log and track and take in and index"
)


def test_operator_authored_rose_is_hash_bound_and_not_mislabeled_as_pipeline_work():
    accepted = PACKAGE / "accepted.txt"
    receipt = json.loads((PACKAGE / "acceptance-receipt.json").read_text(encoding="utf-8"))
    manifest = json.loads((PACKAGE / "manifest.json").read_text(encoding="utf-8"))

    payload = accepted.read_bytes()
    assert len(payload) == 139
    assert payload.count(b"\n") == 6
    assert all(not row.endswith(b" ") for row in payload.splitlines())
    assert hashlib.sha256(payload).hexdigest() == EXPECTED_SHA256

    assert receipt["asset_id"] == "plant.rose"
    assert receipt["authorship"] == "operator_authored"
    assert receipt["operator_statement"] == OPERATOR_STATEMENT
    assert receipt["accepted"]["sha256"] == EXPECTED_SHA256
    assert receipt["operator_correction"] == "trailing spaces.NOO DONT INCLUDE TRAILING SPACES"
    assert receipt["accepted"]["bytes"] == 139
    assert receipt["accepted"]["trailing_spaces_included"] is False
    assert receipt["accepted"]["right_trimmed_from_provisional_source"] is True
    assert receipt["pipeline"]["status"] == "not_run_not_applicable_to_authored_asset"
    assert receipt["pipeline"]["candidate"] is None
    assert receipt["pipeline"]["attempt"] is None
    assert receipt["runtime_integration"]["status"] == "not_integrated"
    assert receipt["runtime_integration"]["current_renderer_placeholder_inherits_approval"] is False

    assert manifest["status"] == "operator_authored_approved_art_asset"
    assert manifest["transcript_sha256"] == EXPECTED_SHA256
    assert manifest["recognition_pipeline"] == "not_run"
    assert manifest["runtime_integration"] == "pending_delete_first_owner_transfer"


def test_acceptance_register_records_exact_grant_without_releasing_old_rose_placeholder():
    register = json.loads(REGISTER.read_text(encoding="utf-8"))
    grant = next(
        item for item in register["operator_grants"]
        if item.get("statement") == OPERATOR_STATEMENT
    )

    assert grant["asset_id"] == "plant.rose"
    assert grant["source"] == (
        "tracked/LateLetterResearch/transcription-parity/"
        "eb861dc84400fc36/accepted.txt"
    )
    assert grant["source_sha256"] == EXPECTED_SHA256
    assert "not a transcription-pipeline verdict" in grant["effect"]
    assert "does not approve or release the different renderer-local rose placeholder" in grant["effect"]

    authority = json.loads((ROOT / "web" / "garden-accepted-paint.v1.json").read_text(encoding="utf-8"))
    assert not any("rose" in identity for identity in authority["accepted_legacy_art"])
