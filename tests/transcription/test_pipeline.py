"""Production transcription ownership and fail-closed orchestration tests."""

from __future__ import annotations

from pathlib import Path

import pytest
from PIL import Image

from lateletter.cli import main
from lateletter.transcription import (
    AttemptError,
    CandidateBundle,
    OperatorReviewReceipt,
    accept,
    transcribe,
    write_candidate_bundle,
    write_record,
)
from lateletter.transcription.hashing import sha256_file
from lateletter.transcription.model import GateReport


ROOT = Path(__file__).parents[2]
FIXTURE = ROOT / "tests" / "fixtures" / "transcription" / "positive" / "positive-fixed-ascii" / "source.png"


def test_transcribe_stops_at_geometry_and_writes_no_txt(tmp_path: Path) -> None:
    source = tmp_path / "blank.png"
    Image.new("RGB", (32, 24), (255, 255, 255)).save(source)
    result = transcribe(source, tmp_path / "attempts", "001-blank-geometry")

    attempt = Path(result["attempt_dir"])
    assert result["status"] == "rejected_geometry"
    assert result["candidate_written"] is False
    assert result["manifest"]["gate"]["passed"] is False
    assert not any((attempt / name).exists() for name in ("candidate.txt", "machine.txt", "accepted.txt"))


def test_transcribe_proved_geometry_stops_before_unavailable_recognizer(tmp_path: Path) -> None:
    result = transcribe(FIXTURE, tmp_path / "attempts", "001-recognition-gate")
    attempt = Path(result["attempt_dir"])

    assert result["status"] == "rejected_recognition"
    assert "recognizer_open_repertoire_unavailable" in result["gate_report"]["rejection_reasons"]
    assert not (attempt / "candidate-bundle.json").exists()
    assert not (attempt / "candidate.txt").exists()


def test_transcribe_attempts_are_immutable(tmp_path: Path) -> None:
    transcribe(FIXTURE, tmp_path / "attempts", "001-immutable")
    with pytest.raises(AttemptError, match="attempt directory already exists"):
        transcribe(FIXTURE, tmp_path / "attempts", "001-immutable")


def test_accept_cannot_promote_without_machine_candidate(tmp_path: Path) -> None:
    result = transcribe(FIXTURE, tmp_path / "attempts", "001-no-candidate")
    with pytest.raises(AttemptError, match="no candidate bundle"):
        accept(result["attempt_dir"], tmp_path / "operator-review.json")


def test_accept_promotes_only_byte_identical_candidate_after_receipt(tmp_path: Path) -> None:
    attempt = tmp_path / "attempt"
    attempt.mkdir()
    candidate = attempt / "candidate.txt"
    candidate.write_text("/\\_|\n", encoding="utf-8")
    artifact_names = {
        "source_hash": "source.png",
        "normalized_source_hash": "normalized.png",
        "geometry_hash": "geometry.json",
        "component_hash": "components.json",
        "proposal_hash": "proposals.json",
        "visual_layout_hash": "layout.json",
        "ownership_hash": "ownership.json",
        "environment_lock_hash": "environment-lock.json",
        "gate_report_hash": "gate-report.json",
    }
    for name in artifact_names.values():
        (attempt / name).write_bytes(name.encode("utf-8"))
    hashes = {name: sha256_file(attempt / path) for name, path in artifact_names.items()}
    hashes["logical_txt_hash"] = sha256_file(candidate)
    bundle = CandidateBundle(
        **hashes,
        candidate_txt_path="candidate.txt",
        visual_layout_path="layout.json",
        input_hashes={"source": hashes["source_hash"]},
        status="candidate",
    )
    write_candidate_bundle(attempt / "candidate-bundle.json", bundle)
    review = OperatorReviewReceipt(
        candidate_bundle_hash=bundle.output_hash,
        operator_verdict="approved",
        layout_parity="accepted",
        human_visual_parity="accepted",
        raster_parity="not_run",
        reviewed_artifact_hashes={"candidate": hashes["logical_txt_hash"]},
        input_hashes={"candidate_bundle": bundle.output_hash},
        status="approved",
    )
    review_path = attempt / "operator-review.json"
    write_record(review_path, review)

    result = accept(attempt, review_path)
    assert result["status"] == "accepted"
    assert (attempt / "accepted.txt").read_bytes() == candidate.read_bytes()
    with pytest.raises(AttemptError, match="accepted.txt already exists"):
        accept(attempt, review_path)


def test_gate_report_rejects_passed_with_failed_evidence() -> None:
    digest = "a" * 64
    with pytest.raises(ValueError, match="passed gate cannot contain failed checks"):
        GateReport(
            input_hashes={"source": digest},
            passed=True,
            checks={"geometry_proved": False},
            status="proved",
        )


def test_cli_transcribe_uses_canonical_pipeline(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    code = main(
        [
            "transcribe",
            str(FIXTURE),
            "--attempt-root",
            str(tmp_path / "attempts"),
            "--attempt-id",
            "001-cli-gate",
        ]
    )
    assert code == 0
    assert '"candidate_written": false' in capsys.readouterr().out
