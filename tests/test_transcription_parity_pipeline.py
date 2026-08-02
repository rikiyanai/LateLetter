"""Regression checks for the immutable raster-to-text parity workflow."""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import numpy as np
import pytest
from PIL import Image


ROOT = Path(__file__).resolve().parents[1]
ATTEMPTS = ROOT / "tracked/LateLetterResearch/transcription-parity/horse-animation-sheet/attempts"


def load_script(name: str):
    path = ROOT / "scripts" / name
    spec = importlib.util.spec_from_file_location(path.stem, path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_attempt_008_is_complete_but_fail_closed() -> None:
    manifest = json.loads(
        (ATTEMPTS / "008-high-contrast-structural-gate/manifest.json").read_text(encoding="utf-8")
    )
    assert manifest["grid"]["columns"] == 40
    assert manifest["grid"]["rows"] == 22
    assert manifest["unknown_cells"] > 0
    assert manifest["low_confidence_cells"] > 0
    assert manifest["structural_conflicts"] > 0
    assert manifest["recognition_gate"]["passed"] is False
    assert not (ATTEMPTS / "008-high-contrast-structural-gate/accepted.txt").exists()


def test_attempt_014_only_passes_the_machine_gate() -> None:
    manifest = json.loads(
        (ATTEMPTS / "014-classify-before-spill/manifest.json").read_text(encoding="utf-8")
    )
    assert manifest["status"] == "machine_candidate_only"
    assert manifest["unknown_cells"] == 0
    assert manifest["low_confidence_cells"] == 0
    assert manifest["structural_conflicts"] == 0
    assert manifest["recognition_gate"]["passed"] is True
    assert not (ATTEMPTS / "014-classify-before-spill/accepted.txt").exists()
    root_manifest = json.loads(
        (ROOT / "tracked/LateLetterResearch/transcription-parity/horse-animation-sheet/manifest.json").read_text(
            encoding="utf-8"
        )
    )
    assert root_manifest["current_attempt"].startswith("attempts/064")
    assert root_manifest["status"] == "rejected"
    assert root_manifest["review"]["verdict"] == "rejected_machine_candidate"
    assert root_manifest["excluded_attempts"]["029-genuine-bicubic-render"].startswith(
        "rejected_renderer_parameter_churn"
    )


def test_horse_attempt_031_rejects_middle_band_and_keeps_unknowns() -> None:
    attempt_dir = ATTEMPTS / "031-middle-band-fail-closed"
    manifest = json.loads((attempt_dir / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["status"] == "rejected"
    assert manifest["unknown_cells"] == 10
    assert manifest["low_confidence_cells"] == 10
    assert manifest["structural_conflicts"] == 0
    lines = (attempt_dir / "machine-cell-ocr.txt").read_text(encoding="utf-8").splitlines()
    assert lines[7][6:8] == "??"
    assert lines[8][9:11] == "??"
    assert lines[17][5] == "?"
    review = json.loads(
        (ROOT / "tracked/LateLetterResearch/transcription-parity/horse-animation-sheet/reviews/031-unknown-neighborhoods/review.json").read_text(
            encoding="utf-8"
        )
    )
    assert review["panel_shape"] == "3x3"
    assert len(review["unknown_centers"]) == 10
    assert (ROOT / "tracked/LateLetterResearch/transcription-parity/horse-animation-sheet/reviews/031-unknown-neighborhoods/unknown-neighborhoods.png").exists()
    assert not (attempt_dir / "rerender.png").exists()


def test_horse_attempt_037_is_row_joint_evidence_and_still_rejected() -> None:
    attempt_dir = ATTEMPTS / "037-row-joint-local-margin"
    manifest = json.loads((attempt_dir / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["status"] == "rejected"
    assert manifest["decoder"]["version"] == "row-joint-2-component-context"
    assert manifest["unknown_cells"] == 8
    assert manifest["low_confidence_cells"] == 10
    assert manifest["acceptance"]["operator_review"] == "pending"
    assert not (attempt_dir / "accepted.txt").exists()
    assert not (attempt_dir / "rerender.png").exists()
    evidence = json.loads((attempt_dir / "row-decoding.json").read_text(encoding="utf-8"))
    assert len(evidence["cells"]) == 37 * 22
    assert all("component_ids" in cell for cell in evidence["cells"])
    assert all(len(cell["window_shape"]) == 2 for cell in evidence["cells"])


def test_horse_attempt_038_records_the_complete_machine_gate() -> None:
    attempt_dir = ATTEMPTS / "038-row-joint-gate-complete"
    manifest = json.loads((attempt_dir / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["status"] == "rejected"
    assert manifest["unknown_cells"] == 8
    assert manifest["low_confidence_cells"] == 10
    assert manifest["structural_conflicts"] == 0
    assert manifest["acceptance"]["zero_unknown_required"] is True
    assert not (attempt_dir / "accepted.txt").exists()
    assert not (attempt_dir / "rerender.png").exists()


def test_horse_attempt_039_uses_complete_image_component_ownership() -> None:
    attempt_dir = ATTEMPTS / "039-global-component-ownership"
    manifest = json.loads((attempt_dir / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["status"] == "rejected"
    assert manifest["decoder"]["version"] == "row-joint-3-global-components"
    assert manifest["unknown_cells"] == 8
    assert manifest["low_confidence_cells"] == 10
    assert manifest["structural_conflicts"] == 0
    assert not (attempt_dir / "accepted.txt").exists()
    assert not (attempt_dir / "rerender.png").exists()


def test_horse_attempt_046_passes_machine_gate_but_is_not_accepted() -> None:
    attempt_dir = ATTEMPTS / "046-recognition-topology-consensus"
    manifest = json.loads((attempt_dir / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["status"] == "machine_candidate_only"
    assert manifest["unknown_cells"] == 0
    assert manifest["low_confidence_cells"] == 0
    assert manifest["structural_conflicts"] == 0
    assert not (attempt_dir / "accepted.txt").exists()
    assert not (attempt_dir / "rerender.png").exists()


def test_horse_attempt_048_rejects_nonzero_genuine_render_diff() -> None:
    attempt_dir = ATTEMPTS / "048-genuine-render-hash-corrected"
    manifest = json.loads((attempt_dir / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["status"] == "rejected_nonzero_diff"
    assert manifest["parity"]["diff_pixel_count"] == 4423
    assert manifest["parity"]["source_pixels_used_in_candidate"] is False
    assert not (attempt_dir / "accepted.txt").exists()


def test_horse_attempt_049_is_best_but_still_nonzero_genuine_render() -> None:
    attempt_dir = ATTEMPTS / "049-genuine-dejavu-supersampled"
    manifest = json.loads((attempt_dir / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["status"] == "rejected_nonzero_diff"
    assert manifest["parity"]["diff_pixel_count"] == 1597
    assert manifest["parity"]["source_pixels_used_in_candidate"] is False
    assert not (attempt_dir / "accepted.txt").exists()


def test_row_band_order_distinguishes_dash_from_lower_underscore_without_absolute_threshold() -> None:
    decoder = load_row_decoder()
    middle = np.zeros((21, 11), dtype=bool)
    middle[11:13, 1:11] = True
    lower = np.zeros((21, 11), dtype=bool)
    lower[19:21, 1:11] = True
    cells = [
        decoder.Cell(0, 0, middle, np.zeros((21, 33), dtype=bool), decoder.topology(middle), None),
        decoder.Cell(0, 1, lower, np.zeros((21, 33), dtype=bool), decoder.topology(lower), "_"),
    ]
    resolved = decoder.resolve_row_horizontal_bands(cells, 2)
    assert resolved[0].seed == "-"
    assert resolved[0].ownership_reason == "row_horizontal_band_order"
    assert resolved[1].seed == "_"


def test_repeated_topology_consensus_requires_another_high_confidence_exemplar() -> None:
    decoder = load_row_decoder()
    mask = np.zeros((21, 11), dtype=bool)
    mask[2:6, 5:9] = True
    cells = [
        decoder.Cell(0, 0, mask, np.zeros((21, 33), dtype=bool), decoder.topology(mask), "'"),
        decoder.Cell(0, 1, mask.copy(), np.zeros((21, 33), dtype=bool), decoder.topology(mask), None),
    ]
    decoded = decoder.apply_repeated_topology_consensus(cells, ["'", "?"], [0.9, 0.0], 2)
    assert decoded == ["'", "'"]


def test_repeated_consensus_cannot_relabel_unproven_punctuation() -> None:
    decoder = load_row_decoder()
    mask = np.zeros((21, 11), dtype=bool)
    mask[8:12, 5:9] = True
    cell = decoder.Cell(
        0,
        1,
        mask,
        np.zeros((21, 33), dtype=bool),
        decoder.topology(mask),
        None,
        component_ids=(71,),
        ownership_reason="punctuation_continuity_unproven",
        baseline_local=12,
    )
    assert decoder.apply_repeated_topology_consensus([cell], ["?"], [0.0], 3) == ["?"]


def test_attempt_015_is_calibration_only_and_compares_pitch_candidates() -> None:
    attempt = ATTEMPTS / "015-subpixel-calibration"
    calibration = json.loads((attempt / "calibration.json").read_text(encoding="utf-8"))
    assert calibration["status"] == "calibration_candidate"
    assert calibration["grid"]["columns"] == 37
    assert calibration["grid"]["cell_advance_x_px"] == 11.55
    assert calibration["grid_legality"]["x"]["boundary_ink_total"] == 2
    candidates = {item["label"]: item for item in calibration["measurement"]["x_candidate_comparison"]}
    assert candidates["integer-11"]["boundary_ink_total"] == 202
    assert candidates["integer-12"]["boundary_ink_total"] == 116
    assert candidates["subpixel-selected"]["boundary_ink_total"] == 2
    assert calibration["review"]["calibration_overlay"] == "pending_operator_review"
    assert (attempt / "calibration-candidates.png").exists()
    assert not (attempt / "machine-cell-ocr.txt").exists()
    assert not (attempt / "accepted.txt").exists()


def test_horse_source_stencil_zero_is_rejected_proxy() -> None:
    attempt = json.loads(
        (
            ATTEMPTS / "028-source-stencil-zero-diff/manifest.json"
        ).read_text(encoding="utf-8")
    )
    assert attempt["parity"]["diff_pixel_count"] == 0
    assert attempt["parity"]["passed"] is False
    assert attempt["parity"]["comparison_valid"] is False
    assert attempt["parity"]["source_pixels_used_in_candidate"] is True
    assert attempt["renderer_configuration"]["font_recovered"] is False
    assert attempt["status"] == "rejected_source_copy_proxy"
    assert attempt.get("accepted", False) is False
    assert not (
        ROOT
        / "tracked/LateLetterResearch/transcription-parity/horse-animation-sheet/accepted.txt"
    ).exists()


def test_horse_genuine_attempt_records_nonzero_per_cell_residuals() -> None:
    attempt = json.loads(
        (ATTEMPTS / "029-genuine-bicubic-render/manifest.json").read_text(encoding="utf-8")
    )
    assert attempt["status"] == "rejected_nonzero_diff"
    assert attempt["parity"]["diff_pixel_count"] == 1486
    assert attempt["parity"]["source_pixels_used_in_candidate"] is False
    assert attempt["parity"]["per_cell_residual_count"] == 143
    assert attempt["parity"]["resample_filter"] == "bicubic"


def test_horse_attempt_030_is_immutable_contact_sheet_evidence_and_rejected() -> None:
    attempt_dir = ATTEMPTS / "030-recognizer-ownership-gate"
    manifest = json.loads((attempt_dir / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["status"] == "rejected"
    assert manifest["unknown_cells"] == 5
    assert manifest["low_confidence_cells"] == 5
    assert manifest["structural_conflicts"] == 0
    assert manifest["recognition_gate"]["passed"] is False
    lines = (attempt_dir / "machine-cell-ocr.txt").read_text(encoding="utf-8").splitlines()
    assert len(lines) == 22
    assert {len(line) for line in lines} == {37}
    receipt = json.loads((attempt_dir / "cell-contact-sheet.json").read_text(encoding="utf-8"))
    assert receipt["review_only"] is True
    assert receipt["cells_shown"] == 814
    assert receipt["nonblank_cells_shown"] == 104
    assert (attempt_dir / "cell-contact-sheet.png").exists()
    assert (attempt_dir / "nonblank-contact-sheet.png").exists()
    assert not (attempt_dir / "rerender.png").exists()
    assert not (ROOT / "tracked/LateLetterResearch/transcription-parity/horse-animation-sheet/accepted.txt").exists()


def test_candidate_rows_preserve_literal_trailing_cells() -> None:
    for attempt in ("007-row-covering-cleanup", "008-high-contrast-structural-gate"):
        lines = (
            (ATTEMPTS / attempt / "machine-cell-ocr.txt")
            .read_text(encoding="utf-8")
            .splitlines()
        )
        assert len(lines) == 22
        assert {len(line) for line in lines} == {40}


def test_normalization_does_not_claim_missing_guides() -> None:
    calibration = json.loads(
        (ATTEMPTS / "008-high-contrast-structural-gate/calibration.json").read_text(encoding="utf-8")
    )
    assert calibration["guide_columns_px"] == []
    assert calibration["normalization"]["guide_removal"] == "none"
    assert calibration["normalization"]["foreground_rgb"] == [34, 37, 41]


def test_review_artifacts_are_exact_size_and_visibly_contrasted() -> None:
    attempt = ATTEMPTS / "008-high-contrast-structural-gate"
    for name in ("rerender.png", "overlay.png", "diff.png"):
        with Image.open(attempt / name) as image:
            assert image.size == (424, 468)
    with Image.open(attempt / "rerender.png") as image:
        assert image.getpixel((40, 15))[:3] != (255, 255, 255)
    with Image.open(attempt / "diff.png") as image:
        colours = set(image.convert("RGB").getdata())
        assert (205, 36, 42) in colours or (0, 118, 190) in colours


def test_structural_fixtures_do_not_collapse_dash_underscore_or_fragments() -> None:
    ocr = load_script("ocr_monospace_cells.py")
    dash = np.zeros((21, 11), dtype=bool)
    dash[4:6, 1:10] = True
    underscore = np.zeros((21, 11), dtype=bool)
    underscore[16:18, 1:10] = True
    assert ocr.classify_shape(dash, 12)[0] == "-"
    assert ocr.classify_shape(underscore, 12)[0] == "_"
    assert ocr.topology(dash)["signature"] != ocr.topology(underscore)["signature"]

    # The queued references may be scaled so a dash band occupies four raster rows and touches
    # both cell edges.  It is still a dash/underscore when its baseline relation is clear.
    four_row_dash = np.zeros((33, 18), dtype=bool)
    four_row_dash[24:28, :] = True
    four_row_underscore = np.zeros((33, 18), dtype=bool)
    four_row_underscore[29:33, :] = True
    assert ocr.classify_shape(four_row_dash, 30.5)[0] == "-"
    assert ocr.classify_shape(four_row_underscore, 30.5)[0] == "_"

    diagonal_fragment = np.zeros((21, 11), dtype=bool)
    diagonal_fragment[8:12, 5:9] = np.array(
        [[1, 1, 1, 0], [0, 1, 1, 1], [0, 1, 1, 1], [0, 0, 1, 1]], dtype=bool
    )
    assert ocr.classify_shape(diagonal_fragment, 12)[0] is None

    # These are the literal source-cell masks from horse r07/r08.  The middle band at
    # rows 11–12 is not the lower underscore band at rows 19–20; it must fail closed until
    # its ownership/identity is proven.  The eight cells previously all became `_`.
    middle_masks = []
    r07c06 = np.zeros((21, 11), dtype=bool)
    r07c06[11:13, 1:11] = True
    middle_masks.append(r07c06)
    r07c07 = np.zeros((21, 12), dtype=bool)
    r07c07[11, 0] = True
    r07c07[11, 2:12] = True
    r07c07[12, 0:12] = True
    middle_masks.append(r07c07)
    r08c09 = np.zeros((21, 12), dtype=bool)
    r08c09[11:13, 2:12] = True
    middle_masks.append(r08c09)
    r08c10 = np.zeros((21, 12), dtype=bool)
    r08c10[11:13, 1:12] = True
    middle_masks.append(r08c10)
    assert all(ocr.classify_shape(mask, 12)[0] is None for mask in middle_masks)
    assert all(ocr.classify_shape(mask, 12)[2] == "geometry_middle_horizontal_ambiguous" for mask in middle_masks)

    bottom_masks = []
    r07c08 = np.zeros((21, 11), dtype=bool)
    r07c08[19:21, 1:11] = True
    bottom_masks.append(r07c08)
    r07c09 = np.zeros((21, 12), dtype=bool)
    r07c09[19:21, 2:12] = True
    bottom_masks.append(r07c09)
    r08c11 = np.zeros((21, 11), dtype=bool)
    r08c11[19:21, 1:11] = True
    bottom_masks.append(r08c11)
    r08c12 = np.zeros((21, 12), dtype=bool)
    r08c12[19:21, 1:12] = True
    bottom_masks.append(r08c12)
    assert all(ocr.classify_shape(mask, 12)[0] == "_" for mask in bottom_masks)

    # r17c05 is a detached diagonal fragment plus a lower horizontal band.  Dominant-component
    # cleanup must not turn that composite into a confident underscore.
    composite = np.zeros((21, 11), dtype=bool)
    composite[0:3, 5:8] = np.array([[1, 1, 1], [0, 1, 1], [0, 1, 1]], dtype=bool)
    composite[15:17, 0:11] = True
    assert ocr.classify_shape(composite, 12)[0] is None

    # Literal source-cell mask from horse r17c04: a horizontal spill component plus a diagonal
    # continuation.  Its curvature accidentally matched the parenthesis heuristic in attempt
    # 061; compound/edge-contact masks must never become a confident parenthesis.
    r17c04 = np.array(
        [
            [0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0],
            [0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0],
            [0, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1],
            [0, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1],
            [0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0],
            [0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0],
            [0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0],
            [0, 0, 1, 1, 0, 0, 0, 0, 0, 0, 0],
            [0, 0, 1, 1, 1, 0, 0, 0, 0, 0, 0],
            [0, 0, 0, 1, 1, 0, 0, 0, 0, 0, 0],
            [0, 0, 0, 1, 1, 1, 0, 0, 0, 0, 0],
            [0, 0, 0, 1, 1, 1, 0, 0, 0, 0, 0],
            [0, 0, 0, 0, 1, 1, 0, 0, 0, 0, 0],
            [0, 0, 0, 0, 1, 1, 1, 0, 0, 0, 0],
            [0, 0, 0, 0, 0, 1, 1, 0, 0, 0, 0],
            [0, 0, 0, 0, 0, 1, 1, 1, 0, 0, 0],
            [0, 0, 0, 0, 0, 1, 1, 1, 0, 0, 0],
            [0, 0, 0, 0, 0, 0, 1, 1, 0, 0, 0],
            [0, 0, 0, 0, 0, 0, 1, 1, 1, 0, 0],
            [0, 0, 0, 0, 0, 0, 0, 1, 1, 0, 0],
            [0, 0, 0, 0, 0, 0, 0, 1, 1, 1, 0],
        ],
        dtype=bool,
    )
    glyph, confidence, reason = ocr.classify_shape(r17c04, 12)
    assert glyph is None
    # Once ownership isolates the actual diagonal component, the same literal source evidence
    # is a slash-family stroke; the compound crop itself must never name the parenthesis.
    diagonal_only = r17c04.copy()
    diagonal_only[:7] = False
    glyph, confidence, reason = ocr.classify_shape(diagonal_only, 12)
    assert glyph == "\\"
    assert confidence < 0.9
    assert reason == "geometry_diagonal"

    fragment = np.zeros((21, 11), dtype=bool)
    fragment[10:12, 0:2] = True
    source_without_owner = np.zeros((21, 22), dtype=bool)
    source_with_owner = np.zeros((21, 22), dtype=bool)
    source_with_owner[10:12, 10] = True
    assert ocr.edge_fragment(fragment)
    assert not ocr.neighbouring_ownership_proven(source_without_owner, 11, 22, 0, 21, fragment)
    assert ocr.neighbouring_ownership_proven(source_with_owner, 11, 22, 0, 21, fragment)

    unrelated = np.zeros((21, 22), dtype=bool)
    unrelated[5, 10] = True
    assert not ocr.neighbouring_ownership_proven(unrelated, 11, 22, 0, 21, fragment)

    continuation = np.zeros((21, 11), dtype=bool)
    continuation[:6, 6:8] = True
    previous_row = np.zeros((42, 11), dtype=bool)
    previous_row[20, 6:8] = True
    assert ocr.row_continuation_proven(previous_row, 0, 11, 21, continuation)


def test_punctuation_and_terminal_fixtures_remain_explicit() -> None:
    ocr = load_script("ocr_monospace_cells.py")
    colon = np.zeros((21, 11), dtype=bool)
    colon[5:7, 4:6] = True
    colon[14:16, 4:6] = True
    assert ocr.classify_shape(colon, 12)[0] == ":"

    apostrophe = np.zeros((21, 11), dtype=bool)
    apostrophe[1, 5] = True
    apostrophe[2, 6] = True
    apostrophe[3, 6] = True
    apostrophe[4, 7] = True
    comma = np.zeros((21, 11), dtype=bool)
    comma[16, 7] = True
    comma[17, 6] = True
    comma[18, 6] = True
    comma[19, 5] = True
    assert ocr.classify_shape(apostrophe, 12)[0] == "'"
    assert ocr.classify_shape(comma, 12)[0] == ","

    # Fractional row phase can put an upper quote below the crop's first third.  Baseline-relative
    # geometry must still identify it, while the same silhouette below the baseline is a comma.
    shifted_upper = np.zeros((21, 11), dtype=bool)
    shifted_upper[8:12, 4:9] = np.array(
        [[1, 1, 1, 0, 0], [0, 1, 1, 1, 0], [0, 1, 1, 1, 0], [0, 0, 1, 1, 0]], dtype=bool
    )
    shifted_lower = np.zeros((21, 11), dtype=bool)
    shifted_lower[14:18, 2:7] = np.array(
        [[1, 1, 1, 0, 0], [0, 1, 1, 1, 0], [0, 1, 1, 1, 0], [0, 0, 1, 1, 0]], dtype=bool
    )
    decoder = load_row_decoder()
    assert ocr.classify_shape(shifted_upper, 12)[0] is None
    assert decoder.compact_baseline_punctuation(shifted_upper, 12) == "`"
    assert decoder.compact_baseline_punctuation(shifted_lower, 12) == ","


def test_contrast_gate_rejects_near_white_foreground() -> None:
    renderer = load_script("render_transcription_parity.py")
    assert renderer.contrast_ratio((34, 37, 41, 255), (255, 255, 255, 255)) >= 4.5
    assert renderer.contrast_ratio((241, 241, 235, 255), (255, 255, 255, 255)) < 4.5


def test_comparison_font_residual_does_not_automatically_reject_txt() -> None:
    renderer = load_script("render_transcription_parity.py")
    manifest = {"status": "machine_candidate_pending_operator_review", "review": {"verdict": "pending"}}
    renderer.mark_comparison_pending(manifest)
    assert manifest["status"] == "comparison_rendered_pending_operator_review"
    assert manifest["review"]["verdict"] == "pending_operator_structural_review"


def load_row_decoder():
    """Load the row decoder through a registered module (required by Python 3.14 dataclasses)."""
    path = ROOT / "scripts" / "decode_monospace_rows.py"
    spec = importlib.util.spec_from_file_location("lateletter_row_decoder", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_row_joint_decoder_keeps_geometry_anchors_and_fails_middle_band_closed() -> None:
    decoder = load_row_decoder()
    middle = np.zeros((21, 11), dtype=bool)
    middle[11:13, 1:11] = True
    assert decoder.seed_geometry(middle, 12)[0] is None

    vertical = np.zeros((21, 11), dtype=bool)
    vertical[1:19, 5:7] = True
    cell = decoder.Cell(0, 0, vertical, np.zeros((21, 33), dtype=bool), decoder.topology(vertical), "|")
    assert decoder.candidate_domain(cell, {"|": []}) == ["|", "?"]


def test_forced_blank_owns_a_stale_geometric_seed() -> None:
    decoder = load_row_decoder()
    mask = np.zeros((21, 11), dtype=bool)
    mask[0:3, 5:8] = True
    cell = decoder.Cell(
        1,
        0,
        mask,
        np.zeros((21, 33), dtype=bool),
        decoder.topology(mask),
        ".",
        forced_blank=True,
        ownership_reason="row_boundary_spill_proven",
    )
    assert decoder.candidate_domain(cell, {".": []}) == [" "]
    assert decoder.forced_blank_conflict_count([cell], ["."]) == 1
    assert decoder.forced_blank_conflict_count([cell], [" "]) == 0


def test_component_cleanup_cannot_hide_a_recovered_glyph_as_forced_blank() -> None:
    decoder = load_row_decoder()
    previous_mask = np.zeros((21, 11), dtype=bool)
    previous = decoder.Cell(
        0,
        0,
        previous_mask,
        np.zeros((21, 33), dtype=bool),
        decoder.topology(previous_mask),
        None,
        component_ids=(41,),
    )
    composite = np.zeros((21, 11), dtype=bool)
    composite[0:2, 2] = True  # terminal owned by the preceding row
    composite[6:19, 5:7] = True  # substantive current-row vertical glyph
    current = decoder.Cell(
        1,
        0,
        composite,
        np.zeros((21, 33), dtype=bool),
        decoder.topology(composite),
        None,
        component_ids=(41, 42),
        forced_blank=True,
        ownership_reason="bidirectional_component_row_spill_proven",
        component_part_ids=((41,), (42,)),
        baseline_local=12,
    )
    resolved = decoder.resolve_component_spill_seeds([previous, current], 1)[1]
    assert resolved.forced_blank is False
    assert resolved.seed == "|"
    assert resolved.topology["components"] == 1
    assert resolved.component_ids == (42,)
    assert decoder.candidate_domain(resolved, {"|": []}) == ["|", "?"]

    ambiguous = decoder.Cell(
        1,
        1,
        composite,
        np.zeros((21, 33), dtype=bool),
        decoder.topology(composite),
        None,
        ownership_reason="component_spill_removed:canonical_geometry_ambiguous",
    )
    assert decoder.candidate_domain(ambiguous, {"'": []}) == ["?"]


def test_cross_row_spill_requires_every_component_to_be_proven_neighbor_ink() -> None:
    decoder = load_row_decoder()
    blank = np.zeros((21, 11), dtype=bool)
    previous = decoder.Cell(
        0, 0, blank, np.zeros((21, 33), dtype=bool), decoder.topology(blank), None, component_ids=(51,)
    )
    composite = np.zeros((21, 11), dtype=bool)
    composite[0:2, 2] = True
    composite[10:12, 5] = True  # genuine current-row component
    composite[19:21, 8] = True
    current = decoder.Cell(
        1,
        0,
        composite,
        np.zeros((21, 33), dtype=bool),
        decoder.topology(composite),
        None,
        component_ids=(51, 52, 53),
        component_part_ids=((51,), (52,), (53,)),
    )
    following = decoder.Cell(
        2, 0, blank, np.zeros((21, 33), dtype=bool), decoder.topology(blank), None, component_ids=(53,)
    )
    resolved = decoder.resolve_cross_row_spill([previous, current, following], 1)[1]
    assert resolved.forced_blank is False


def test_repeated_punctuation_requires_an_independent_unshared_component() -> None:
    decoder = load_row_decoder()
    diagonal = np.zeros((21, 11), dtype=bool)
    diagonal[8:12, 4:9] = np.array(
        [[1, 1, 1, 0, 0], [0, 1, 1, 1, 0], [0, 1, 1, 1, 0], [0, 0, 1, 1, 0]], dtype=bool
    )
    slash = decoder.Cell(0, 0, diagonal.copy(), np.zeros((21, 33), dtype=bool), decoder.topology(diagonal), "/", component_ids=(60,), baseline_local=12)
    backtick = decoder.Cell(0, 1, diagonal.copy(), np.zeros((21, 33), dtype=bool), decoder.topology(diagonal), None, component_ids=(61,), baseline_local=12)
    backslash = decoder.Cell(0, 2, diagonal.copy(), np.zeros((21, 33), dtype=bool), decoder.topology(diagonal), "\\", component_ids=(62,), baseline_local=12)
    clean = [slash, backtick, backslash]
    resolved = decoder.resolve_repeated_baseline_punctuation(clean)
    assert resolved[1].seed == "`"
    assert resolved[1].ownership_reason == "punctuation_window_context"

    contaminated_mask = diagonal.copy()
    contaminated_mask[0, 1] = True
    contaminated = decoder.Cell(
        0,
        2,
        contaminated_mask,
        np.zeros((21, 33), dtype=bool),
        decoder.topology(contaminated_mask),
        None,
        component_ids=(63, 64),
        baseline_local=12,
    )
    assert decoder.resolve_repeated_baseline_punctuation([contaminated])[0].seed is None


def test_horse_source_spill_cleanup_recomputes_component_state_before_punctuation() -> None:
    decoder = load_row_decoder()
    calibration = json.loads(
        (ATTEMPTS / "015-subpixel-calibration/calibration.json").read_text(encoding="utf-8")
    )
    source = ROOT / "tracked/LateLetterResearch/transcription-parity/horse-animation-sheet/source/source.normalized.png"
    cells = decoder.segment(source, calibration)
    by_key = {(cell.row, cell.column): cell for cell in cells}
    # The lower cells begin as row-boundary composites.  A disconnected diagonal fragment is not
    # an apostrophe: without a delimiter window the decoder preserves it as an unknown.
    for key in ((19, 7), (19, 13)):
        cell = by_key[key]
        assert cell.topology["components"] == 1
        assert not cell.topology["edge_contacts"]
        assert len(cell.component_ids) == 1
        assert cell.ownership_reason == "punctuation_continuity_unproven"
        assert cell.seed is None
        assert cell.forced_blank is False


def test_row_joint_decoder_templates_are_leave_one_out_and_deterministic() -> None:
    decoder = load_row_decoder()
    masks = []
    for column in range(3):
        mask = np.zeros((21, 11), dtype=bool)
        mask[4:6, 1:10] = True
        masks.append(mask)
    cells = [
        decoder.Cell(
            0,
            column,
            mask,
            np.zeros((21, 33), dtype=bool),
            decoder.topology(mask),
            "-",
        )
        for column, mask in enumerate(masks)
    ]
    templates = decoder.build_templates(cells)
    assert len(templates["-"]) == 3
    assert sum((item.row, item.column) != (0, 1) for item in templates["-"]) == 2
    first, first_confidence, first_meta = decoder.decode_row(cells, templates)
    second, second_confidence, second_meta = decoder.decode_row(cells, templates)
    assert first == second == ["-", "-", "-"]
    assert first_confidence == second_confidence
    assert first_meta == second_meta
    calibration = json.loads(
        (ATTEMPTS / "031-middle-band-fail-closed/calibration.json").read_text(encoding="utf-8")
    )
    source = ROOT / "tracked/LateLetterResearch/transcription-parity/horse-animation-sheet/source/source.normalized.png"
    segmented = decoder.segment(source, calibration)
    assert segmented
    assert all(cell.window.shape[1] >= cell.mask.shape[1] * 2 for cell in segmented)


def test_row_joint_transcript_binding_preserves_grid_and_detects_stale_txt() -> None:
    decoder = load_row_decoder()
    records = [
        {"row": 0, "column": 0, "glyph": " "},
        {"row": 0, "column": 1, "glyph": "/"},
        {"row": 1, "column": 0, "glyph": "_"},
        {"row": 1, "column": 1, "glyph": " "},
    ]
    transcript = " /\n_ \n"
    digest = decoder.validate_transcript_binding(transcript, records, 2, 2)
    assert len(digest) == 64
    with pytest.raises(ValueError, match="disagrees"):
        decoder.validate_transcript_binding("S /\n_ \n", records, 2, 2)


def test_repeated_consensus_does_not_alias_equal_coarse_topologies() -> None:
    decoder = load_row_decoder()
    diagonal = np.zeros((9, 9), dtype=bool)
    reverse = np.zeros((9, 9), dtype=bool)
    for index in range(5):
        diagonal[index + 2, index + 2] = True
        reverse[index + 2, 6 - index] = True
    assert decoder.topology(diagonal)["width"] == decoder.topology(reverse)["width"]
    assert decoder.topology(diagonal)["height"] == decoder.topology(reverse)["height"]
    assert decoder.topology(diagonal)["ink_pixels"] == decoder.topology(reverse)["ink_pixels"]
    assert decoder.recognition_shape_key(diagonal) != decoder.recognition_shape_key(reverse)


def test_horse_046_is_rejected_when_txt_disagrees_with_its_evidence() -> None:
    attempt = ATTEMPTS / "046-recognition-topology-consensus"
    manifest = json.loads((attempt / "manifest.json").read_text(encoding="utf-8"))
    evidence = json.loads((attempt / "row-decoding.json").read_text(encoding="utf-8"))
    rows = evidence["cells"]
    by_row: dict[int, list[str]] = {}
    for cell in rows:
        by_row.setdefault(int(cell["row"]), []).append(str(cell["glyph"]))
    evidence_txt = "\n".join("".join(by_row[row]) for row in sorted(by_row)) + "\n"
    candidate_txt = (attempt / "machine-row-joint.txt").read_text(encoding="utf-8")
    assert candidate_txt != evidence_txt
    assert "transcript_sha256" not in manifest


def test_horse_052_binds_transcript_hash_and_grid_before_render() -> None:
    attempt = ATTEMPTS / "052-row-joint-bound-output"
    manifest = json.loads((attempt / "manifest.json").read_text(encoding="utf-8"))
    evidence = json.loads((attempt / "row-decoding.json").read_text(encoding="utf-8"))
    transcript = (attempt / "machine-row-joint.txt").read_text(encoding="utf-8")
    import hashlib

    digest = hashlib.sha256(transcript.encode("utf-8")).hexdigest()
    assert manifest["transcript_sha256"] == digest
    assert evidence["transcript_sha256"] == digest
    assert manifest["cell_count"] == 814
    assert manifest["transcript_line_lengths"] == [37] * 22
    assert manifest["unknown_cells"] == 0
    assert manifest["low_confidence_cells"] == 0
    assert manifest["structural_conflicts"] == 0
    assert not (attempt / "accepted.txt").exists()


def test_horse_054_exact_shape_gate_rejects_aliases_before_render() -> None:
    attempt = ATTEMPTS / "054-row-joint-exact-shape-consensus"
    manifest = json.loads((attempt / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["status"] == "rejected"
    assert manifest["unknown_cells"] == 2
    assert manifest["low_confidence_cells"] == 2
    assert manifest["structural_conflicts"] == 0
    assert not (attempt / "rerender.png").exists()
    root_manifest = json.loads(
        (ROOT / "tracked/LateLetterResearch/transcription-parity/horse-animation-sheet/manifest.json").read_text(
            encoding="utf-8"
        )
    )
    assert root_manifest["latest_machine_candidate"]["attempt"].startswith("attempts/064")


def test_horse_055_passes_machine_gate_without_creating_acceptance() -> None:
    attempt = ATTEMPTS / "055-row-joint-repeated-baseline-punctuation"
    manifest = json.loads((attempt / "manifest.json").read_text(encoding="utf-8"))
    evidence = json.loads((attempt / "row-decoding.json").read_text(encoding="utf-8"))
    transcript = (attempt / "machine-row-joint.txt").read_text(encoding="utf-8")
    import hashlib

    digest = hashlib.sha256(transcript.encode("utf-8")).hexdigest()
    assert manifest["status"] == "machine_candidate_only"
    assert manifest["transcript_sha256"] == digest == evidence["transcript_sha256"]
    assert (manifest["unknown_cells"], manifest["low_confidence_cells"], manifest["structural_conflicts"]) == (0, 0, 0)
    assert not (attempt / "accepted.txt").exists()


def test_horse_060_is_current_machine_candidate_and_raster_is_not_the_gate() -> None:
    attempt = ATTEMPTS / "060-component-state-boundary-fix"
    manifest = json.loads((attempt / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["status"] == "machine_candidate_only"
    assert (manifest["unknown_cells"], manifest["low_confidence_cells"], manifest["structural_conflicts"], manifest["forced_blank_conflicts"]) == (0, 0, 0, 0)
    assert manifest["cell_count"] == 814
    assert manifest["transcript_line_lengths"] == [37] * 22
    assert not (attempt / "accepted.txt").exists()
    root_manifest = json.loads(
        (ROOT / "tracked/LateLetterResearch/transcription-parity/horse-animation-sheet/manifest.json").read_text(
            encoding="utf-8"
        )
    )
    assert root_manifest["review"]["zero_diff_required"] is False
    assert root_manifest["review"]["raster_parity"] == "not_run_machine_gate_rejected"


def test_horse_061_enters_renderer_without_turning_font_diff_into_rejection() -> None:
    attempt = ATTEMPTS / "061-executable-structural-comparison"
    manifest = json.loads((attempt / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["status"] == "comparison_rendered_pending_operator_review"
    assert manifest["parity"]["diff_pixel_count"] == 4240
    assert manifest["parity"]["pixel_exact"] is False
    assert manifest["parity"]["zero_diff_required"] is False
    assert manifest["parity"]["source_pixels_used_in_candidate"] is False
    assert manifest["review"]["verdict"] == "pending_operator_structural_review"
    assert all((attempt / name).exists() for name in ("rerender.png", "overlay.png", "diff.png"))
    assert not (attempt / "accepted.txt").exists()
    root_manifest = json.loads(
        (ROOT / "tracked/LateLetterResearch/transcription-parity/horse-animation-sheet/manifest.json").read_text(
            encoding="utf-8"
        )
    )
    assert root_manifest["current_attempt"].startswith("attempts/064")
    assert root_manifest["review"]["comparison_diff_pixel_count"] is None


def test_horse_063_is_rejected_on_unknown_compound_and_punctuation_cells() -> None:
    attempt = ATTEMPTS / "063-ownership-context-parenthesis-guard"
    manifest = json.loads((attempt / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["status"] == "rejected"
    assert (manifest["unknown_cells"], manifest["low_confidence_cells"], manifest["structural_conflicts"], manifest["forced_blank_conflicts"]) == (17, 17, 0, 0)
    evidence = json.loads((attempt / "row-decoding.json").read_text(encoding="utf-8"))
    cells = {(item["row"], item["column"]): item for item in evidence["cells"]}
    assert cells[(17, 4)]["glyph"] == "?"
    assert cells[(17, 4)]["seed"] is None
    assert cells[(18, 9)]["glyph"] == "?"
    assert cells[(18, 16)]["glyph"] == "?"
    assert cells[(19, 7)]["glyph"] == "?"
    assert cells[(19, 13)]["glyph"] == "?"
    assert not (attempt / "accepted.txt").exists()


def test_horse_064_retries_063_without_mutation_and_hash_binds_transcript() -> None:
    attempt = ATTEMPTS / "064-immutable-ownership-context-retry"
    manifest = json.loads((attempt / "manifest.json").read_text(encoding="utf-8"))
    transcript = (attempt / "machine-row-joint.txt").read_bytes()
    import hashlib

    assert manifest["status"] == "rejected"
    assert hashlib.sha256(transcript).hexdigest() == "8d6b27d77024d10a220f4841610b215065abeb6e7b173c25b1963aef18c0c2e2"
    assert transcript.startswith(b"   ,~~_")
    assert (manifest["unknown_cells"], manifest["low_confidence_cells"]) == (17, 17)
    assert not (attempt / "accepted.txt").exists()
