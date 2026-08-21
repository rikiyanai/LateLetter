"""Public-interface tests for the canonical transcription evidence IR."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from lateletter.transcription import (
    AttemptError,
    CandidateBundle,
    GraphemeCandidate,
    SourceReceipt,
    create_attempt,
    read_record,
    verify_candidate_bundle,
    write_candidate_bundle,
    write_record,
)
from lateletter.transcription.hashing import sha256_bytes
from lateletter.transcription.schema import SchemaError, canonical_bytes


H = "a" * 64


def source() -> SourceReceipt:
    return SourceReceipt(
        source_path="source/source.png",
        source_sha256=H,
        width=12,
        height=8,
        input_hashes={"source": H},
        configuration={"threshold": 0.5, "nested": {"mode": "fixed"}},
    )


def test_public_record_serialization_is_stable_and_deeply_immutable() -> None:
    record = source()
    first = canonical_bytes(record.to_dict())
    second = canonical_bytes(SourceReceipt.from_dict(json.loads(first)))
    assert first == second
    assert record.output_hash == SourceReceipt.from_dict(json.loads(first)).output_hash
    with pytest.raises(TypeError):
        record.configuration["new"] = "value"  # type: ignore[index]


def test_unknown_fields_missing_hashes_and_traversal_are_rejected() -> None:
    payload = source().to_dict()
    payload["unknown"] = True
    with pytest.raises(SchemaError, match="unknown"):
        SourceReceipt.from_dict(payload)
    payload = source().to_dict()
    payload["source_path"] = "../outside.png"
    with pytest.raises((SchemaError, ValueError), match="unsafe|traversal"):
        SourceReceipt.from_dict(payload)
    payload = source().to_dict()
    payload["input_hashes"] = {"source": "not-a-hash"}
    with pytest.raises((SchemaError, ValueError), match="SHA-256"):
        SourceReceipt.from_dict(payload)
    payload = source().to_dict()
    payload["schema_version"] = "future-ir-99"
    with pytest.raises(SchemaError, match="unsupported schema_version"):
        SourceReceipt.from_dict(payload)
    payload = source().to_dict()
    payload["source_path"] = r"folder\\..\\outside.png"
    with pytest.raises((SchemaError, ValueError), match="unsafe|traversal"):
        SourceReceipt.from_dict(payload)


def test_nested_candidates_are_decoded_as_immutable_records() -> None:
    candidate = GraphemeCandidate(
        text="木",
        normalized_text="木",
        codepoints=("U+6728",),
        display_width=2,
        confidence=0.9,
        input_hashes={"component": H},
    )
    from lateletter.transcription import RecognitionProposal

    proposal = RecognitionProposal(
        proposal_id="p1",
        adapter="offline-test",
        adapter_version="1",
        candidates=(candidate,),
        input_hashes={"components": H},
    )
    decoded = RecognitionProposal.from_dict(proposal.to_dict())
    assert decoded.candidates[0].text == "木"
    with pytest.raises(TypeError):
        decoded.model_hashes["x"] = H  # type: ignore[index]


def test_immutable_record_write_and_hash_bound_artifact_validation(tmp_path: Path) -> None:
    attempt = create_attempt(tmp_path, "001-ir")
    path = attempt / "source.json"
    written_hash = write_record(path, source())
    assert written_hash == sha256_bytes(path.read_bytes())
    with pytest.raises(AttemptError):
        write_record(path, source())
    assert read_record(path, SourceReceipt).output_hash == source().output_hash

    artifact = attempt / "source.png"
    artifact.write_bytes(b"source")
    artifact_hash = sha256_bytes(b"source")
    bundle = CandidateBundle(
        source_hash=artifact_hash,
        normalized_source_hash=artifact_hash,
        geometry_hash=artifact_hash,
        component_hash=artifact_hash,
        proposal_hash=artifact_hash,
        logical_txt_hash=artifact_hash,
        visual_layout_hash=artifact_hash,
        ownership_hash=artifact_hash,
        environment_lock_hash=artifact_hash,
        gate_report_hash=artifact_hash,
        candidate_txt_path="candidate.txt",
        visual_layout_path="layout.json",
        input_hashes={"source": artifact_hash},
    )
    verify_candidate_bundle(
        bundle,
        attempt,
        {
            "source_hash": "source.png",
            "normalized_source_hash": "source.png",
            "geometry_hash": "source.png",
            "component_hash": "source.png",
            "proposal_hash": "source.png",
            "logical_txt_hash": "source.png",
            "visual_layout_hash": "source.png",
            "ownership_hash": "source.png",
            "environment_lock_hash": "source.png",
            "gate_report_hash": "source.png",
        },
    )
    artifact.write_bytes(b"mutated")
    with pytest.raises(AttemptError, match="stale"):
        verify_candidate_bundle(
            bundle,
            attempt,
            {key: "source.png" for key in bundle.bound_hashes},
        )


def test_candidate_bundle_has_one_public_writer(tmp_path: Path) -> None:
    """Generic diagnostics cannot silently become the canonical candidate writer."""
    artifact_hash = sha256_bytes(b"source")
    bundle = CandidateBundle(
        source_hash=artifact_hash,
        normalized_source_hash=artifact_hash,
        geometry_hash=artifact_hash,
        component_hash=artifact_hash,
        proposal_hash=artifact_hash,
        logical_txt_hash=artifact_hash,
        visual_layout_hash=artifact_hash,
        ownership_hash=artifact_hash,
        environment_lock_hash=artifact_hash,
        gate_report_hash=artifact_hash,
        candidate_txt_path="candidate.txt",
        visual_layout_path="layout.json",
        input_hashes={"source": artifact_hash},
    )
    with pytest.raises(AttemptError, match="write_candidate_bundle"):
        write_record(tmp_path / "bundle.json", bundle)
    path = tmp_path / "bundle.json"
    assert write_candidate_bundle(path, bundle) == sha256_bytes(path.read_bytes())
