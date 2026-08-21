"""Ownership-transfer regressions for legacy transcription adapters."""

from __future__ import annotations

import ast
from pathlib import Path
import os
import subprocess
import sys

import pytest
from PIL import Image

from lateletter.transcription import AttemptError, CandidateBundle, write_candidate_bundle, write_record
from lateletter.transcription.hashing import sha256_bytes


ROOT = Path(__file__).resolve().parents[2]


def _candidate_bundle() -> CandidateBundle:
    digest = sha256_bytes(b"fixture")
    return CandidateBundle(
        source_hash=digest,
        normalized_source_hash=digest,
        geometry_hash=digest,
        component_hash=digest,
        proposal_hash=digest,
        logical_txt_hash=digest,
        visual_layout_hash=digest,
        ownership_hash=digest,
        environment_lock_hash=digest,
        gate_report_hash=digest,
        candidate_txt_path="candidate.txt",
        visual_layout_path="layout.json",
        input_hashes={"source": digest},
    )


def test_exactly_one_canonical_candidate_bundle_writer() -> None:
    attempts = (ROOT / "src/lateletter/transcription/attempts.py").read_text(encoding="utf-8")
    tree = ast.parse(attempts)
    writers = [node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == "write_candidate_bundle"]
    assert len(writers) == 1
    for legacy in (
        "scripts/ocr_monospace_cells.py",
        "scripts/decode_monospace_rows.py",
        "scripts/unicode_run_decoder.py",
        "scripts/render_transcription_parity.py",
    ):
        source = (ROOT / legacy).read_text(encoding="utf-8")
        assert "write_candidate_bundle" not in source
    assert "manifest_path.write_text" not in (ROOT / "scripts/render_transcription_parity.py").read_text(encoding="utf-8")
    assert 'machine-cell-ocr.txt").write_text' not in (ROOT / "scripts/ocr_monospace_cells.py").read_text(encoding="utf-8")
    assert 'machine-row-joint.txt").write_text' not in (ROOT / "scripts/decode_monospace_rows.py").read_text(encoding="utf-8")


def test_legacy_adapters_cannot_promote_candidate(tmp_path: Path) -> None:
    bundle = _candidate_bundle()
    with pytest.raises(AttemptError):
        write_record(tmp_path / "bundle.json", bundle)
    assert write_candidate_bundle(tmp_path / "bundle.json", bundle)


def test_rejected_proposal_capture_emits_no_txt(tmp_path: Path) -> None:
    """Proposal evidence must never masquerade as a converted transcript."""

    source = tmp_path / "blank.png"
    Image.new("RGB", (48, 32), (255, 255, 255)).save(source)
    attempt = tmp_path / "attempt"
    env = {**os.environ, "PYTHONPATH": str(ROOT / "src")}
    result = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "capture_reference_attempt.py"), str(source), str(attempt)],
        cwd=ROOT,
        env=env,
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 2, result.stderr
    assert (attempt / "manifest.json").exists()
    assert (attempt / "geometry-overlay.png").exists()
    assert (attempt / "recognition-proposals.json").exists()
    assert (attempt / "joint-review.json").exists()
    assert not any((attempt / name).exists() for name in ("candidate.txt", "machine.txt", "accepted.txt"))
