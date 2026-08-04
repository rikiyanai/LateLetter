"""The single production owner for PNG transcription attempts.

This module deliberately stops at the first unavailable authority.  Diagnostic
recognizers may propose evidence elsewhere, but they cannot write a candidate
or promote an accepted transcript.  ``accept`` is the only function that can
copy candidate bytes to ``accepted.txt``.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Any, Mapping

from PIL import Image

from .attempts import AttemptError, create_attempt, read_record, verify_candidate_bundle, write_record
from .geometry import route_raster_geometry
from .hashing import resolve_under, sha256_bytes, sha256_file
from .model import (
    CandidateBundle,
    GateReport,
    GeometryDecision,
    NormalizationReceipt,
    OperatorReviewReceipt,
    SourceReceipt,
)
from .schema import canonical_bytes


def _write_json_once(path: Path, payload: Mapping[str, Any]) -> str:
    """Write one immutable diagnostic JSON artifact."""

    if path.exists():
        raise AttemptError(f"immutable artifact already exists: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    data = canonical_bytes(payload) + b"\n"
    path.write_bytes(data)
    return sha256_bytes(data)


def _record_path(attempt: Path, name: str) -> Path:
    return resolve_under(attempt, name)


def transcribe(
    source_png: str | Path,
    attempt_root: str | Path,
    attempt_id: str,
    *,
    geometry_configuration: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Run the canonical source-to-review pipeline until its first failed gate.

    The current release has a raster geometry owner but no open-repertoire
    decoder capable of satisfying the recognition gate.  Consequently proved
    geometry produces a deterministic blocked attempt, while unresolved
    geometry stops earlier.  Neither branch writes candidate TXT bytes.
    """

    source = Path(source_png).resolve()
    if not source.exists() or not source.is_file():
        raise AttemptError(f"source PNG does not exist: {source}")
    if source.suffix.lower() != ".png":
        raise AttemptError("transcribe requires a PNG source")
    root = Path(attempt_root).resolve()
    root.mkdir(parents=True, exist_ok=True)
    attempt = create_attempt(root, attempt_id)

    source_bytes = source.read_bytes()
    source_hash = sha256_bytes(source_bytes)
    with Image.open(source) as image:
        width, height = image.size
        if width <= 0 or height <= 0:
            raise AttemptError("source PNG has invalid dimensions")

    source_copy = attempt / "source.png"
    source_copy.write_bytes(source_bytes)
    source_receipt = SourceReceipt(
        source_path="source.png",
        source_sha256=source_hash,
        width=width,
        height=height,
        input_hashes={"source": source_hash},
        provenance={"authority": "pipeline.transcribe", "source_copy": True},
        status="verified",
    )
    source_receipt_hash = write_record(attempt / "source-receipt.json", source_receipt)

    normalized_copy = attempt / "normalized.png"
    normalized_copy.write_bytes(source_bytes)
    normalized_hash = sha256_file(normalized_copy)
    normalization = NormalizationReceipt(
        source_sha256=source_hash,
        normalized_sha256=normalized_hash,
        method="identity",
        guide_removal="none",
        operations=("identity_copy",),
        input_hashes={"source": source_hash},
        provenance={"authority": "pipeline.transcribe", "source_specific_guides": False},
        status="verified",
    )
    normalization_hash = write_record(attempt / "normalization.json", normalization)

    bundle, decision = route_raster_geometry(
        normalized_copy,
        expected_sha256=normalized_hash,
        configuration=geometry_configuration,
    )
    geometry_hash = write_record(attempt / "geometry.json", decision)
    evidence_hash = _write_json_once(
        attempt / "geometry-evidence.json",
        {**bundle.to_dict(), "artifact_sha256": bundle.output_hash},
    )
    _write_json_once(
        attempt / "components.json",
        {
            "source_sha256": normalized_hash,
            "geometry_evidence_hash": bundle.output_hash,
            "component_evidence": dict(bundle.component_evidence),
            "artifact_sha256": str(bundle.component_evidence.get("component_hash", "")),
        },
    )

    checks: dict[str, bool] = {
        "source_verified": source_receipt_hash == sha256_file(attempt / "source-receipt.json"),
        "normalization_verified": normalization_hash == sha256_file(attempt / "normalization.json"),
        "geometry_proved": decision.status == "proved" and decision.mode != "unresolved",
    }
    rejection_codes = list(decision.rejection_reasons)
    if checks["geometry_proved"]:
        # This is an intentional product gate, not a hidden fallback to the
        # old structural table.  The open-repertoire recognizer must be wired
        # before a candidate can be emitted.
        checks["open_repertoire_recognizer_available"] = False
        rejection_codes.append("recognizer_open_repertoire_unavailable")
    gate = GateReport(
        input_hashes={"source": normalized_hash, "geometry": decision.geometry_hash or bundle.output_hash},
        configuration={"pipeline": "transcribe-v1"},
        provenance={"geometry_decision_hash": geometry_hash, "geometry_evidence_hash": evidence_hash},
        status="rejected",
        passed=False,
        checks=checks,
        counts={"blocking_failures": sum(1 for value in checks.values() if not value)},
        rejection_reasons=tuple(dict.fromkeys(rejection_codes or ["geometry_unresolved"])),
    )
    gate_hash = write_record(attempt / "gate-report.json", gate)

    status = "rejected_geometry" if not checks["geometry_proved"] else "rejected_recognition"
    manifest = {
        "schema": "lateletter-transcribe-attempt-1",
        "attempt_id": attempt_id,
        "status": status,
        "candidate_written": False,
        "source": {"path": "source.png", "sha256": source_hash, "receipt_hash": source_receipt_hash},
        "normalized": {"path": "normalized.png", "sha256": normalized_hash, "receipt_hash": normalization_hash},
        "geometry": {"path": "geometry.json", "record_hash": geometry_hash, "evidence_hash": evidence_hash, "mode": decision.mode},
        "gate": {"path": "gate-report.json", "record_hash": gate_hash, "passed": False},
        "rejection_reasons": list(gate.rejection_reasons),
    }
    _write_json_once(attempt / "manifest.json", manifest)
    return {
        "attempt_dir": str(attempt),
        "status": status,
        "candidate_written": False,
        "gate_report": gate.to_dict(),
        "manifest": manifest,
    }


def accept(
    attempt_dir: str | Path,
    operator_review_receipt: str | Path,
) -> dict[str, Any]:
    """Promote one machine candidate after an approved hash-bound review."""

    attempt = Path(attempt_dir).resolve()
    bundle_path = attempt / "candidate-bundle.json"
    if not bundle_path.exists():
        raise AttemptError("attempt has no candidate bundle")
    bundle = read_record(bundle_path, CandidateBundle)
    review_path = Path(operator_review_receipt).resolve()
    review = read_record(review_path, OperatorReviewReceipt)
    if review.operator_verdict != "approved":
        raise AttemptError("operator review is not approved")
    if review.candidate_bundle_hash != bundle.output_hash:
        raise AttemptError("operator review candidate bundle hash mismatch")
    candidate_path = resolve_under(attempt, bundle.candidate_txt_path)
    if sha256_file(candidate_path) != bundle.logical_txt_hash:
        raise AttemptError("candidate TXT hash mismatch")
    artifact_paths = {
        "source_hash": "source.png",
        "normalized_source_hash": "normalized.png",
        "geometry_hash": "geometry.json",
        "component_hash": "components.json",
        "proposal_hash": "proposals.json",
        "logical_txt_hash": bundle.candidate_txt_path,
        "visual_layout_hash": bundle.visual_layout_path,
        "ownership_hash": "ownership.json",
        "environment_lock_hash": "environment-lock.json",
        "gate_report_hash": "gate-report.json",
    }
    verify_candidate_bundle(bundle, attempt, artifact_paths)
    accepted = attempt / "accepted.txt"
    if accepted.exists():
        raise AttemptError("accepted.txt already exists")
    accepted.write_bytes(candidate_path.read_bytes())
    receipt = {
        "schema": "lateletter-acceptance-receipt-1",
        "candidate_bundle_hash": bundle.output_hash,
        "operator_review_hash": review.output_hash,
        "candidate_sha256": sha256_file(candidate_path),
        "accepted_sha256": sha256_file(accepted),
        "status": "accepted",
    }
    receipt_hash = _write_json_once(attempt / "acceptance-receipt.json", receipt)
    return {"status": "accepted", "accepted_path": str(accepted), "receipt_hash": receipt_hash}
