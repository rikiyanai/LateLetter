"""Tests for the router-emitted calibration artifact and the row-joint seam.

What is under test here
-----------------------
Two things that must hold together for a router proof to become a decode:

1.  ``geometry.calibration_emitter.emit_calibration`` may only write a
    calibration for a source whose lattice the router proved outright, must
    refuse everything else with a NAMED reason, must never overwrite, and must
    produce the same bytes every time it runs on the same source.
2.  ``row_joint.resolve_calibration`` must prefer the hand-reviewed legacy
    attempt calibration when one is bound to the source, must fall through to
    the router-emitted artifact otherwise, and must refuse any calibration an
    operator explicitly rejected.

Every source used below is either an in-repository synthetic fixture or a
tracked parity source PNG.  No test in this file reads a transcript.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from lateletter.transcription import row_joint
from lateletter.transcription.geometry import calibration_emitter

# Repository root, three levels up from tests/transcription/<file>.
ROOT = Path(__file__).resolve().parents[2]

# A synthetic monospace render whose lattice the router proves on all four
# properties.  Small, so emitting it inside a test costs about a second.
PROVED_LATTICE_SOURCE = (
    ROOT / "tests" / "fixtures" / "transcription" / "positive" / "positive-fixed-ascii" / "source.png"
)

# A synthetic proportional/CJK render the router routes to shaped runs: its row
# period is measured but neither pitch nor phase authority is proved.
SHAPED_RUN_SOURCE = (
    ROOT / "tests" / "fixtures" / "transcription" / "positive" / "positive-kana" / "source.png"
)

# A live screenshot the router cannot settle on at all (it returns ``rejected``).
UNRESOLVED_SOURCE = (
    ROOT
    / "tracked"
    / "LateLetterResearch"
    / "transcription-parity"
    / "ldb-flower-field"
    / "source"
    / "source.normalized.png"
)

# A live screenshot the router DOES prove, and which the legacy attempt history
# also binds — the one place the two stores contest a source hash, so the one
# place seam precedence can actually be observed.
LEGACY_BOUND_PROVED_SOURCE = (
    ROOT
    / "tracked"
    / "LateLetterResearch"
    / "transcription-parity"
    / "bbbb-flowers"
    / "source"
    / "source.normalized.png"
)

# The legacy attempt calibration an operator explicitly turned down.
REJECTED_LEGACY_CALIBRATION = (
    ROOT
    / "tracked"
    / "LateLetterResearch"
    / "transcription-parity"
    / "ldb-flower-field"
    / "attempts"
    / "001-calibrate"
    / "calibration.json"
)


@pytest.fixture(autouse=True)
def _clear_seam_caches():
    """Drop the seam's cached indexes around every test.

    Both indexes are ``lru_cache``d because calibrations are immutable in
    production.  Tests deliberately point the router index at temporary
    directories, so the cache has to be emptied before AND after each test or
    one test's temporary index would leak into the next.
    """

    row_joint._calibration_index.cache_clear()
    row_joint._router_calibration_index.cache_clear()
    yield
    row_joint._calibration_index.cache_clear()
    row_joint._router_calibration_index.cache_clear()


# ---------------------------------------------------------------------------
# Refusals
# ---------------------------------------------------------------------------


def test_emitter_refuses_shaped_run_source_with_named_reasons(tmp_path: Path) -> None:
    """A shaped-run source has no cell grid, so no calibration may be written."""

    receipt = calibration_emitter.emit_calibration(SHAPED_RUN_SOURCE, tmp_path)
    assert receipt["status"] == "refused"
    reasons = set(receipt["refusal_reasons"])
    # The mode itself is disqualifying, and the two properties a shaped-run
    # decision never asserts are named individually.
    assert "emitter_mode_not_fixed_lattice" in reasons
    assert "emitter_pitch_unproven" in reasons or "emitter_phase_unproven" in reasons
    # Every reason must come from the module's own enumerated vocabulary; a
    # free-text refusal would be indistinguishable from a crash.
    assert reasons <= set(calibration_emitter.REFUSAL_REASONS)
    # Nothing at all may be written on a refusal.
    assert list(tmp_path.iterdir()) == []


def test_emitter_refuses_unresolved_geometry_with_named_reasons(tmp_path: Path) -> None:
    """When the router settles on no model, the emitter says so and writes nothing."""

    receipt = calibration_emitter.emit_calibration(UNRESOLVED_SOURCE, tmp_path)
    assert receipt["status"] == "refused"
    reasons = set(receipt["refusal_reasons"])
    assert "emitter_geometry_not_proved" in reasons
    assert reasons <= set(calibration_emitter.REFUSAL_REASONS)
    assert list(tmp_path.iterdir()) == []


# ---------------------------------------------------------------------------
# Emission, schema, and the decoder contract
# ---------------------------------------------------------------------------


def test_emitted_artifact_decodes_under_the_source_hash_binding(tmp_path: Path) -> None:
    """The emitted file satisfies the legacy decoder's calibration schema.

    This is the whole point of the emitter: what it writes must be directly
    consumable by ``decode_rows_with_calibration``, which enforces the
    source-hash binding before it segments a single pixel.
    """

    receipt = calibration_emitter.emit_calibration(PROVED_LATTICE_SOURCE, tmp_path)
    assert receipt["status"] == "emitted", receipt.get("refusal_reasons")

    artifact_path = tmp_path / receipt["artifact_path"]
    calibration = json.loads(artifact_path.read_text(encoding="utf-8"))

    # Every field ``segment()`` reads must be present and usable.
    assert len(calibration["canvas"]["background_rgb"]) == 3
    assert isinstance(calibration["normalization"]["ink_threshold_l1"], int)
    assert calibration["guide_columns_px"] == []
    grid = calibration["grid"]
    for key in (
        "columns",
        "rows",
        "origin_x_px",
        "first_baseline_y_px",
        "cell_advance_x_px",
        "line_height_px",
        "cell_crop_top_offset_px",
        "cell_crop_bottom_offset_px",
    ):
        assert key in grid, key
    assert grid["columns"] >= 1 and grid["rows"] >= 1
    assert grid["cell_advance_x_px"] > 0 and grid["line_height_px"] > 0
    # A cell box may not be taller than the line advance, or two rows would
    # segment the same pixels.
    assert grid["cell_crop_bottom_offset_px"] - grid["cell_crop_top_offset_px"] <= round(
        grid["line_height_px"]
    )

    # The artifact is bound to the exact bytes it was measured from, and the
    # decoder refuses anything else.
    decoded = row_joint.decode_rows_with_calibration(PROVED_LATTICE_SOURCE, calibration)
    assert decoded["row_count"] == grid["rows"]
    assert decoded["columns"] == grid["columns"]
    assert decoded["cell_count"] == grid["rows"] * grid["columns"]
    assert decoded["source_sha256"] == calibration["source_sha256"]

    # A calibration bound to different bytes must raise rather than decode.
    mismatched = dict(calibration)
    mismatched["source_sha256"] = "0" * 64
    with pytest.raises(ValueError):
        row_joint.decode_rows_with_calibration(PROVED_LATTICE_SOURCE, mismatched)


def test_emitted_receipt_carries_every_required_proof_family(tmp_path: Path) -> None:
    """The receipt must state the margins, not merely that a margin existed."""

    receipt = calibration_emitter.emit_calibration(PROVED_LATTICE_SOURCE, tmp_path)
    assert receipt["status"] == "emitted"
    assert receipt["pitch_margins"]["winning_pitch"]
    assert receipt["pitch_margins"]["normalized_pitch_margin"] is not None
    assert receipt["phase_margins"]["normalized_phase_margin"] is not None
    assert receipt["ownership_completeness"]["ownership_complete"] is True
    assert receipt["ownership_completeness"]["unowned_pixel_count"] == 0
    assert receipt["baseline_regularity"]["regular"] is True
    assert receipt["baseline_regularity"]["baseline_delta_residual_max"] >= 0
    # Boundary-ink legality is measured, not asserted: the counts must be there.
    legality = receipt["boundary_ink_legality"]
    assert legality["ink_pixels_total"] > 0
    assert legality["ink_pixels_inside_cells"] + legality["ink_pixels_outside_cells"] == (
        legality["ink_pixels_total"]
    )
    # Identity and provenance, so a replay can prove it ran the same code.
    assert receipt["implementation_sha256"]
    assert receipt["evidence_sha256"] and receipt["geometry_sha256"]
    assert receipt["transcript_input"] is False


def test_index_records_the_artifact_hash_at_creation(tmp_path: Path) -> None:
    """An emitted artifact is only visible through the index it was written to."""

    from lateletter.transcription.hashing import sha256_file

    receipt = calibration_emitter.emit_calibration(PROVED_LATTICE_SOURCE, tmp_path)
    index = json.loads((tmp_path / "index.json").read_text(encoding="utf-8"))
    entry = index["calibrations"][receipt["source_sha256"]]
    assert entry["artifact_sha256"] == receipt["artifact_sha256"]
    # The recorded hash must be the hash of the bytes actually on disk.
    assert sha256_file(tmp_path / receipt["artifact_path"]) == entry["artifact_sha256"]


# ---------------------------------------------------------------------------
# Determinism and write-once
# ---------------------------------------------------------------------------


def test_two_emissions_produce_identical_bytes_and_the_second_write_is_refused(
    tmp_path: Path,
) -> None:
    """Same source bytes, same artifact hash — and no silent overwrite.

    Emitting into two independent roots must produce byte-identical artifacts,
    which is the determinism claim.  Emitting twice into the SAME root must
    refuse the second write, which is the immutability claim; the refusal
    carries the existing file's hash so a replay can compare it.
    """

    first_root, second_root = tmp_path / "one", tmp_path / "two"
    first = calibration_emitter.emit_calibration(PROVED_LATTICE_SOURCE, first_root)
    second = calibration_emitter.emit_calibration(PROVED_LATTICE_SOURCE, second_root)
    assert first["status"] == second["status"] == "emitted"
    assert first["artifact_sha256"] == second["artifact_sha256"]
    assert (first_root / first["artifact_path"]).read_bytes() == (
        second_root / second["artifact_path"]
    ).read_bytes()

    # A second emission into an already-populated root is refused, not merged.
    repeat = calibration_emitter.emit_calibration(PROVED_LATTICE_SOURCE, first_root)
    assert repeat["status"] == "refused"
    assert repeat["refusal_reasons"] == ["emitter_artifact_already_present"]
    assert repeat["existing_artifact_sha256"] == first["artifact_sha256"]


# ---------------------------------------------------------------------------
# The row-joint seam
# ---------------------------------------------------------------------------


def test_seam_prefers_the_legacy_binding_over_a_router_emission(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Legacy attempt calibrations remain the interim authority they bind.

    bbbb-flowers is the one source that both stores can describe: the router
    proves its lattice, and the attempt history already binds it.  The legacy
    artifact must win, because the repository's accepted decode evidence for
    that source was produced under exactly that geometry.
    """

    emitted = calibration_emitter.emit_calibration(LEGACY_BOUND_PROVED_SOURCE, tmp_path)
    assert emitted["status"] == "emitted", emitted.get("refusal_reasons")

    monkeypatch.setattr(row_joint, "_ROUTER_CALIBRATION_ROOT", tmp_path)
    monkeypatch.setattr(row_joint, "_ROUTER_CALIBRATION_INDEX", tmp_path / "index.json")
    row_joint._router_calibration_index.cache_clear()

    # Both stores now bind the source hash.
    assert any(item[0] == emitted["source_sha256"] for item in row_joint._router_calibration_index())
    found = row_joint.resolve_calibration(emitted["source_sha256"])
    assert found is not None
    _payload, path = found
    assert "/attempts/" in path, "legacy attempt calibration must keep precedence"
    assert str(tmp_path) not in path


def test_seam_serves_a_router_emission_when_no_legacy_binding_exists(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A source nobody ever calibrated by hand is served by the router's proof."""

    emitted = calibration_emitter.emit_calibration(PROVED_LATTICE_SOURCE, tmp_path)
    assert emitted["status"] == "emitted"
    # This synthetic fixture has never appeared in the attempt history.
    assert not any(
        item[0] == emitted["source_sha256"] for item in row_joint._calibration_index()
    )

    monkeypatch.setattr(row_joint, "_ROUTER_CALIBRATION_ROOT", tmp_path)
    monkeypatch.setattr(row_joint, "_ROUTER_CALIBRATION_INDEX", tmp_path / "index.json")
    row_joint._router_calibration_index.cache_clear()

    found = row_joint.resolve_calibration(emitted["source_sha256"])
    assert found is not None
    payload, path = found
    assert payload["source_sha256"] == emitted["source_sha256"]
    assert payload["status"] == calibration_emitter.EMITTED_STATUS
    assert str(tmp_path) in path


def test_explicitly_rejected_calibration_is_refused_at_the_seam() -> None:
    """A calibration an operator turned down may never carry a decode.

    ldb-flower-field's only tracked calibration is marked
    ``calibration_rejected``.  Before this seam change the seam still returned
    it and still decoded under it; it must now return nothing at all, because a
    decode under known-wrong geometry is worse than no decode.
    """

    rejected = json.loads(REJECTED_LEGACY_CALIBRATION.read_text(encoding="utf-8"))
    assert rejected["status"] == "calibration_rejected"
    assert row_joint.calibration_is_explicitly_rejected(rejected) is True

    source_hash = rejected["source_sha256"]
    assert row_joint.resolve_calibration(source_hash) is None
    # And the rejected path must not appear in the legacy index at all.
    assert all(
        str(REJECTED_LEGACY_CALIBRATION) != path for _digest, path in row_joint._calibration_index()
    )


def test_absent_status_stays_admissible_at_the_seam() -> None:
    """Silence is not rejection: only the explicit value blocks a calibration."""

    assert row_joint.calibration_is_explicitly_rejected({}) is False
    assert row_joint.calibration_is_explicitly_rejected({"status": "calibration_candidate"}) is False
    assert row_joint.calibration_is_explicitly_rejected({"status": "machine_candidate_only"}) is False
    assert (
        row_joint.calibration_is_explicitly_rejected(
            {"status": calibration_emitter.EMITTED_STATUS}
        )
        is False
    )
    assert row_joint.calibration_is_explicitly_rejected({"status": "calibration_rejected"}) is True


def test_router_index_ignores_an_artifact_whose_bytes_changed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """An artifact edited after indexing is no longer the artifact emitted."""

    emitted = calibration_emitter.emit_calibration(PROVED_LATTICE_SOURCE, tmp_path)
    artifact = tmp_path / emitted["artifact_path"]
    tampered = json.loads(artifact.read_text(encoding="utf-8"))
    tampered["grid"]["rows"] = int(tampered["grid"]["rows"]) + 1
    artifact.write_text(json.dumps(tampered, sort_keys=True, indent=2) + "\n", encoding="utf-8")

    monkeypatch.setattr(row_joint, "_ROUTER_CALIBRATION_ROOT", tmp_path)
    monkeypatch.setattr(row_joint, "_ROUTER_CALIBRATION_INDEX", tmp_path / "index.json")
    row_joint._router_calibration_index.cache_clear()

    assert row_joint._router_calibration_index() == ()
    assert row_joint.resolve_calibration(emitted["source_sha256"]) is None
