"""Production transcription ownership and fail-closed orchestration tests."""

from __future__ import annotations

import json
import unicodedata
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
from lateletter.transcription.pipeline import _best_effort_candidate_from_report, _missing_glyph_box_evidence


ROOT = Path(__file__).parents[2]
V2_ROOT = ROOT / "tests" / "fixtures" / "transcription-v2"
FIXTURE = V2_ROOT / "positive" / "positive-fixed-ascii" / "source.png"
FALLBACK_IDS = ("fallback-kana", "fallback-kanji", "fallback-width-mixture", "fallback-emoji-zwj", "fallback-mixed-script")
POSITIVE_IDS = (
    "positive-fixed-ascii",
    "positive-proportional-latin",
    "positive-kana",
    "positive-kanji",
    "positive-arabic",
    "positive-combining",
    "positive-width-mixture",
    "positive-emoji-zwj",
    "positive-mixed-script",
    "positive-degraded-fixed",
)


def test_ensemble_timeout_does_not_block_row_joint_candidate(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """When the diagnostic ensemble exceeds its production ceiling but
    bounded deterministic row-joint evidence exists, the row-joint text
    still authors the candidate; the timeout is recorded as missing
    diagnostics, not a candidate-authority failure."""

    from lateletter.transcription import pipeline as pipeline_module
    from lateletter.transcription import row_joint as row_joint_module

    def _boom(callback):
        raise pipeline_module._RecognizerBudgetExceeded("simulated ensemble ceiling")

    monkeypatch.setattr(pipeline_module, "_run_with_recognizer_budget", _boom)
    monkeypatch.setattr(
        row_joint_module,
        "decode_for_source",
        lambda source: {
            "decoder_version": "test-decoder",
            "text": "/\\_|\n(=)",
            "unknown_cells": 0,
            "cell_count": 8,
            "row_count": 2,
            "columns": 4,
            "template_glyphs": ["/", "\\", "_", "|", "(", "=", ")"],
        },
    )
    result = transcribe(FIXTURE, tmp_path / "attempts", "001-ensemble-timeout")
    assert result["status"] == "machine_candidate_pending_operator_review"
    assert result["candidate_written"] is True
    attempt = Path(result["attempt_dir"])
    assert (attempt / "candidate.txt").read_text(encoding="utf-8").rstrip("\n") == "/\\_|\n(=)"
    error_record = json.loads((attempt / "recognizer-error.json").read_text(encoding="utf-8"))
    assert error_record["status"] == "ensemble_diagnostics_unavailable"


def test_ensemble_timeout_without_row_joint_still_refuses(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from lateletter.transcription import pipeline as pipeline_module
    from lateletter.transcription import row_joint as row_joint_module

    def _boom(callback):
        raise pipeline_module._RecognizerBudgetExceeded("simulated ensemble ceiling")

    monkeypatch.setattr(pipeline_module, "_run_with_recognizer_budget", _boom)
    monkeypatch.setattr(row_joint_module, "decode_for_source", lambda source: None)
    result = transcribe(FIXTURE, tmp_path / "attempts", "001-timeout-no-row-joint")
    assert result["candidate_written"] is False
    assert result["status"] != "machine_candidate_pending_operator_review"


def test_ensemble_timeout_with_unknown_bearing_row_joint_refuses(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from lateletter.transcription import pipeline as pipeline_module
    from lateletter.transcription import row_joint as row_joint_module

    def _boom(callback):
        raise pipeline_module._RecognizerBudgetExceeded("simulated ensemble ceiling")

    monkeypatch.setattr(pipeline_module, "_run_with_recognizer_budget", _boom)
    monkeypatch.setattr(
        row_joint_module,
        "decode_for_source",
        lambda source: {
            "decoder_version": "test-decoder",
            "text": "/\\?|\n(=)",
            "unknown_cells": 1,
            "cell_count": 8,
            "row_count": 2,
            "columns": 4,
            "template_glyphs": ["/", "\\", "|", "(", "=", ")"],
        },
    )
    result = transcribe(FIXTURE, tmp_path / "attempts", "001-timeout-unknown-cells")
    assert result["candidate_written"] is False


def test_transcribe_stops_at_geometry_and_writes_no_txt(tmp_path: Path) -> None:
    source = tmp_path / "blank.png"
    Image.new("RGB", (32, 24), (255, 255, 255)).save(source)
    result = transcribe(source, tmp_path / "attempts", "001-blank-geometry")

    attempt = Path(result["attempt_dir"])
    assert result["status"] == "rejected_geometry"
    assert result["candidate_written"] is False
    assert result["manifest"]["gate"]["passed"] is False
    assert not any((attempt / name).exists() for name in ("candidate.txt", "machine.txt", "accepted.txt"))


def test_transcribe_writes_candidate_after_phase6_authority_passes(tmp_path: Path) -> None:
    result = transcribe(FIXTURE, tmp_path / "attempts", "001-recognition-gate")
    attempt = Path(result["attempt_dir"])

    assert result["status"] == "machine_candidate_pending_operator_review"
    assert result["candidate_written"] is True
    assert result["gate_report"]["passed"] is True
    assert (attempt / "candidate-bundle.json").exists()
    assert (attempt / "candidate.txt").read_text(encoding="utf-8").rstrip("\n") == "/\\_|\n(=)"


def test_transcribe_attempts_are_immutable(tmp_path: Path) -> None:
    source = tmp_path / "blank.png"
    Image.new("RGB", (32, 24), (255, 255, 255)).save(source)
    transcribe(source, tmp_path / "attempts", "001-immutable")
    with pytest.raises(AttemptError, match="attempt directory already exists"):
        transcribe(source, tmp_path / "attempts", "001-immutable")


def test_accept_cannot_promote_without_machine_candidate(tmp_path: Path) -> None:
    source = tmp_path / "blank.png"
    Image.new("RGB", (32, 24), (255, 255, 255)).save(source)
    result = transcribe(source, tmp_path / "attempts", "001-no-candidate")
    with pytest.raises(AttemptError, match="no candidate bundle"):
        accept(result["attempt_dir"], tmp_path / "operator-review.json")


def test_source_collision_gate_rejects_fallbacks_and_preserves_positives() -> None:
    fallback_counts = {
        fixture_id: len(_missing_glyph_box_evidence(V2_ROOT / "fail_closed" / fixture_id / "source.png"))
        for fixture_id in FALLBACK_IDS
    }
    positive_counts = {
        fixture_id: len(_missing_glyph_box_evidence(V2_ROOT / "positive" / fixture_id / "source.png"))
        for fixture_id in POSITIVE_IDS
    }

    assert all(count > 0 for count in fallback_counts.values())
    assert positive_counts == {fixture_id: 0 for fixture_id in POSITIVE_IDS}


def test_phase6_selector_preserves_all_d2_positive_family_candidates() -> None:
    report = json.loads((V2_ROOT / "recognizer-benchmark-v11-d2-rank1-positive.json").read_text(encoding="utf-8"))
    selected: dict[str, str] = {}
    for result in report["results"]:
        fixture_id = result["fixture"]
        one_result_report = {**report, "results": [result]}
        selector = _best_effort_candidate_from_report(one_result_report, source_png=V2_ROOT / "positive" / fixture_id / "source.png")
        assert selector is not None, fixture_id
        assert float(selector["selector_margin"]) > 0.0, fixture_id
        selected[fixture_id] = unicodedata.normalize("NFC", str(selector["text"]))

    expected = {
        fixture_id: unicodedata.normalize("NFC", (V2_ROOT / "positive" / fixture_id / "transcript.txt").read_text(encoding="utf-8").rstrip("\n"))
        for fixture_id in POSITIVE_IDS
    }
    assert selected == expected


@pytest.mark.parametrize("fixture_id", FALLBACK_IDS)
def test_transcribe_rejects_source_collision_fallback_without_candidate(tmp_path: Path, fixture_id: str) -> None:
    result = transcribe(V2_ROOT / "fail_closed" / fixture_id / "source.png", tmp_path / "attempts", f"001-{fixture_id}")
    attempt = Path(result["attempt_dir"])

    assert result["status"] == "rejected_candidate_authority"
    assert result["candidate_written"] is False
    assert "source_missing_glyph_box_collision" in result["gate_report"]["rejection_reasons"]
    assert not (attempt / "candidate-bundle.json").exists()
    assert not (attempt / "candidate.txt").exists()


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
            str(V2_ROOT / "fail_closed" / "fallback-kana" / "source.png"),
            "--attempt-root",
            str(tmp_path / "attempts"),
            "--attempt-id",
            "001-cli-gate",
        ]
    )
    assert code == 0
    assert '"candidate_written": false' in capsys.readouterr().out
