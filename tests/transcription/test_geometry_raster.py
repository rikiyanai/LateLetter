"""Literal-PNG geometry ownership tests.

These tests intentionally pass only a source PNG to the geometry owner.  The
corpus transcript and visual-layout sidecar are never opened, so a successful
run proves that recognizer inputs came from measured raster evidence.
"""

from __future__ import annotations

from pathlib import Path
import json
import pytest
import numpy as np

from lateletter.transcription.geometry import (
    build_recognition_inputs,
    build_recognition_hypothesis_inputs,
    route_raster_geometry,
)


ROOT = Path(__file__).parents[1] / "fixtures" / "transcription"
SITTING_CAT = Path(__file__).parents[2] / "tracked" / "LateLetterResearch" / "transcription-parity" / "sitting-cat" / "source" / "source.normalized.png"
BBBB_FLOWERS = Path(__file__).parents[2] / "tracked" / "LateLetterResearch" / "transcription-parity" / "bbbb-flowers" / "source" / "source.normalized.png"
A828_REFERENCE = Path(__file__).parents[2] / "tracked" / "LateLetterResearch" / "transcription-parity" / "a8283c5cdb63b130" / "source" / "source.normalized.png"


def test_geometry_authority_has_no_status_and_proof_contradiction() -> None:
    """The public decision is the only authority surface.

    A rejected decision cannot expose proof flags, and a proved decision must
    expose all four required proofs.  The two existing reviewed fixed sources
    are regression anchors for this contract.
    """

    for source in (BBBB_FLOWERS, A828_REFERENCE):
        _bundle, decision = route_raster_geometry(source)
        assert decision.mode in {"fixed_lattice", "shaped_runs", "unresolved"}
        flags = (decision.candidate_valid, decision.pitch_proven, decision.phase_proven, decision.ownership_proven)
        if decision.status == "proved":
            assert decision.mode != "unresolved"
            assert flags == (True, True, True, True)
            assert decision.provenance["selected_geometry"]["geometry_proven"] is True
        else:
            assert decision.mode == "unresolved"
            assert flags == (False, False, False, False)
            assert decision.provenance.get("selected_geometry") is None


def test_fixed_ascii_png_produces_concrete_lattice_and_complete_row_strips() -> None:
    source = ROOT / "positive" / "positive-fixed-ascii" / "source.png"
    bundle, decision = route_raster_geometry(source)

    assert bundle.status == "proved"
    assert decision.mode == "fixed_lattice"
    assert (decision.candidate_valid, decision.pitch_proven, decision.phase_proven, decision.ownership_proven) == (True, True, True, True)
    selected = decision.provenance["selected_geometry"]
    assert selected["geometry_proven"] is True
    assert selected["cells"]
    assert selected["source_sha256"] == bundle.source_sha256
    assert selected["selected_foreground_mask_sha256"] == bundle.projection_evidence["selected_mask_sha256"]
    assert bundle.component_evidence["bbox_row_candidates_authoritative"] is False

    inputs = build_recognition_inputs(source, bundle, mode=decision.mode)
    assert inputs["mode"] == "fixed_lattice"
    assert len(inputs["runs"]) == len(selected["row_bands"])
    # Fixed strips are content-cropped to the measured lattice extent.  The
    # source receipt remains full-canvas; logical decoding must not invent
    # trailing blank columns from that canvas.
    for item in inputs["runs"]:
        x0, y0, x1, y1 = item["source_bounds"]
        assert 0 <= x0 < x1 <= 180
        assert 0 <= y0 < y1 <= 100
        assert x1 - x0 == len(item["binary_run_mask"][0])
        assert any("1" in row for row in item["binary_run_mask"])
    assert all(item["run_strip_png_sha256"] for item in inputs["runs"])
    assert all(item["binary_run_mask_sha256"] for item in inputs["runs"])
    assert all(item["anchor_evidence"]["authority"] == "source_mask_anchor_evidence" for item in inputs["runs"])
    assert all(item["anchor_evidence"]["evidence_hash"] for item in inputs["runs"])
    assert all(item["anchor_evidence"]["mask_sha256"] == item["binary_run_mask_sha256"] for item in inputs["runs"])
    assert all(item["anchor_evidence"]["painted_runs"] for item in inputs["runs"])
    assert inputs["provenance"]["source_only"] is True
    assert inputs["provenance"]["transcript_input"] is False

    # The same source and pinned configuration must produce byte-identical
    # strips and hashes across runs.
    assert inputs == build_recognition_inputs(source, bundle, mode=decision.mode)
    assert build_recognition_inputs(source, bundle.to_dict(), mode=decision.mode)["input_hash"] == inputs["input_hash"]


def test_recognition_input_builder_never_selects_geometry_without_explicit_mode() -> None:
    """Recognition inputs cannot invoke a second geometry authority."""

    source = ROOT / "positive" / "positive-fixed-ascii" / "source.png"
    bundle, decision = route_raster_geometry(source)
    assert decision.status == "proved"
    with pytest.raises(ValueError, match="explicit proved geometry mode"):
        build_recognition_inputs(source, bundle)
    with pytest.raises(ValueError, match="explicit proved geometry mode"):
        build_recognition_inputs(source, bundle.to_dict())


def test_fixed_run_anchor_evidence_preserves_local_and_global_frames() -> None:
    source = ROOT / "positive" / "positive-fixed-ascii" / "source.png"
    bundle, decision = route_raster_geometry(source)
    inputs = build_recognition_inputs(source, bundle, mode=decision.mode)
    source_offset = int(inputs["runs"][0]["source_bounds"][0])
    for run in inputs["runs"]:
        evidence = run["anchor_evidence"]
        assert evidence["frame"] == "run_local_with_global_bounds"
        assert evidence["global_origin_px"] - source_offset == evidence["origin_px"]
        for painted in evidence["painted_runs"]:
            gx0, _gy0, gx1, _gy1 = painted["source_bounds"]
            lx0, _ly0, lx1, _ly1 = painted["local_bounds"]
            assert gx0 - source_offset == run["source_bounds"][0] + lx0 - source_offset
            assert gx1 - source_offset == run["source_bounds"][0] + lx1 - source_offset


def test_emoji_png_produces_geometry_owned_shaped_run_strips() -> None:
    source = ROOT / "positive" / "positive-emoji-zwj" / "source.png"
    bundle, decision = route_raster_geometry(source)

    assert bundle.status == "proved"
    assert decision.mode == "shaped_runs"
    selected = decision.provenance["selected_geometry"]
    assert selected["run_anchors"]
    assert selected["orientation"] == "horizontal"
    assert tuple(selected["direction_candidates"]) == ("ltr",)

    inputs = build_recognition_inputs(source, bundle, mode=decision.mode)
    assert inputs["mode"] == "shaped_runs"
    assert len(inputs["runs"]) == len(selected["run_anchors"])
    assert all(item["source_bounds"][2] > item["source_bounds"][0] for item in inputs["runs"])
    assert all(item["source_bounds"][3] > item["source_bounds"][1] for item in inputs["runs"])
    assert inputs["geometry_hash"] == bundle.output_hash


def test_geometry_rejects_blank_raster_before_recognition_inputs(tmp_path: Path) -> None:
    from PIL import Image

    source = tmp_path / "blank.png"
    Image.new("RGB", (32, 24), (255, 255, 255)).save(source)
    bundle, decision = route_raster_geometry(source)

    assert bundle.status == "rejected"
    assert "foreground_unresolved" in bundle.rejection_reasons
    assert decision.mode == "unresolved"


def test_vertically_connected_cat_art_admits_shaped_run_geometry_without_fixed_lattice_proof() -> None:
    """Blank-gap diagnostics may not veto an independent periodic baseline proof.

    The cat has vertical strokes spanning several logical drawing rows.  Blank-
    gap grouping still collapses those rows into diagnostic bands, but the
    source-period evidence recovers a stable nine-row family.  Missing fixed-
    lattice phase/ownership proof must not veto a shaped-run authority path
    when every source pixel is owned by concrete row/run anchors.
    """

    bundle, decision = route_raster_geometry(SITTING_CAT)

    assert bundle.status == "proved"
    assert decision.mode == "shaped_runs"
    assert (decision.candidate_valid, decision.pitch_proven, decision.phase_proven, decision.ownership_proven) == (True, True, True, True)
    assert decision.provenance["selected_geometry"]["geometry_proven"] is True
    assert decision.provenance["selected_geometry"]["shaped_run_authority_proven"] is True
    assert "row_baselines_undersegmented" not in bundle.rejection_reasons
    quality = bundle.projection_evidence["row_band_quality"]
    assert quality["undersegmented"] is True
    assert quality["blank_gap_undersegmented"] is True
    assert quality["periodic_baselines_proven"] is True
    assert quality["largest_height"] >= 3 * quality["reference_height"]
    assert quality["periodic_candidate_pitch"] == 23
    assert quality["periodic_candidate_rows"] == 9
    assert len(bundle.row_band_candidates) == 9
    assert bundle.projection_evidence["selected_baseline_rows"][0]["source"] == "periodic_baseline_candidate"
    mixed = bundle.projection_evidence["mixed_width_display"]
    assert mixed["mode"] == "mixed_width_display"
    assert 9.0 <= mixed["base_advance_px"] <= 16.0
    assert mixed["wide_span_units"] == 2
    assert mixed["width_classes"]["ambiguous"] == "profile_required"
    assert len(mixed["origin_candidates_px"]) == 5
    assert mixed["origin_candidates_px"][0] < mixed["origin_px"]
    periodic = bundle.projection_evidence["periodic_row_candidates"]
    assert periodic
    # The independent pitch sweep sees materially more rows than the old
    # four-band grouping; it remains evidence, not an automatic promotion.
    assert max(item["row_count"] for item in periodic) >= 9

    phase8 = next(item for item in periodic if item["pitch"] == 23 and item["phase"] == 8)
    phase9 = next(item for item in periodic if item["pitch"] == 23 and item["phase"] == 9)
    assert phase8["valid"] is True
    assert phase9["valid"] is True
    assert phase8["baselines"] == [30, 53, 76, 99, 122, 145, 168, 191, 213]
    assert phase9["baselines"] == [31, 54, 77, 100, 123, 146, 169, 192, 213]
    assert phase8["baseline_delta_residuals"][-1] == -1
    assert phase9["baseline_delta_residuals"][-1] == -2
    assert phase8["nominal_baselines"][-1] == 214
    assert phase8["terminal_baseline_clamped"] is True
    assert phase8["ownership"]["owned_pixel_count"] == phase8["ownership"]["substantive_pixel_count"]
    assert phase8["ownership"]["unowned_pixel_count"] == 0
    assert phase8["ownership"]["cross_row_continuations"]

    terminal_sliver = next(item for item in periodic if item["pitch"] == 22 and item["phase"] == 12)
    assert terminal_sliver["valid"] is False
    assert terminal_sliver["terminal_sliver_rejected"] is True
    assert terminal_sliver["baseline_delta_residuals"][-1] == -18
    assert "terminal_sliver_rejected" in terminal_sliver["rejection_reasons"]
    assert terminal_sliver["partial_edge_rows"] == []
    authority = bundle.projection_evidence["periodic_authority"]
    assert authority["baseline_proven"] is True
    assert authority["pitch_proven"] is True
    assert authority["phase_proven"] is False
    assert authority["ownership_proven"] is False
    fixed_surface = next(item for item in decision.alternatives if item["mode"] == "fixed_lattice")
    # The measured mixed-width/row evidence no longer fabricates a fixed
    # branch for this connected cat; its periodic table remains diagnostic
    # evidence while shaped-run anchors own recognition input.
    assert fixed_surface["branch_candidate_passed"] is False
    assert fixed_surface["passed"] is False
    shaped_surface = next(item for item in decision.alternatives if item["mode"] == "shaped_runs")
    assert shaped_surface["authority_proven"] is True
    assert shaped_surface["passed"] is True
    # Threshold replay must preserve the winning pitch, phase topology, and
    # ownership geometry.  Raw pixel hashes may still differ under
    # antialiasing; phase/ownership authority remains rejected below.
    assert authority["foreground_stability"]["stable"] is True
    assert {tuple(item["background_rgb"]) for item in authority["foreground_stability"]["retained_thresholds"]} == {(255, 255, 255)}
    assert {item["winning_pitch"] for item in authority["foreground_stability"]["retained_thresholds"]} == {23}
    phase23 = authority["phase_authority_by_pitch"]["23"]
    assert phase23["phase_group_count"] >= 2
    assert phase23["phase_margin"] < 0.10

    with pytest.raises(ValueError, match="recognition inputs require"):
        build_recognition_inputs(SITTING_CAT, bundle, mode="fixed_lattice")

    threshold_bundle, threshold_decision = route_raster_geometry(
        SITTING_CAT,
        configuration={"foreground_thresholds": (25,)},
    )
    # A single foreground recipe changes the fixed-period diagnostics, but the
    # authority split remains the same: fixed-lattice recognition is not
    # admitted unless its concrete mode is selected, while shaped-run source
    # anchors remain admissible.
    assert threshold_decision.mode == "shaped_runs"
    assert threshold_bundle.status == "proved"
    assert threshold_decision.provenance["selected_geometry"]["shaped_run_authority_proven"] is True
    assert threshold_bundle.projection_evidence["periodic_authority"]["foreground_stability"]["stable"] is True
    assert threshold_bundle.projection_evidence["periodic_authority"]["pitch_proven"] is True
    assert threshold_bundle.projection_evidence["periodic_authority"]["phase_proven"] is True
    assert threshold_bundle.projection_evidence["periodic_authority"]["ownership_proven"] is True

    hypotheses = build_recognition_hypothesis_inputs(SITTING_CAT, bundle, max_hypotheses=4)
    assert len(hypotheses) == 4
    assert all(item["provenance"]["hypothesis_only"] is True for item in hypotheses)
    assert all(item["provenance"]["authoritative"] is False for item in hypotheses)
    assert len({item["provenance"]["hypothesis"]["origin_px"] for item in hypotheses}) == 4
    assert {(item["provenance"]["hypothesis"]["pitch"], item["provenance"]["hypothesis"]["phase"]) for item in hypotheses} == {(23, 8)}


def test_hypothesis_budget_reaches_competing_vertical_families() -> None:
    """A joint proposal budget cannot be consumed by one origin basin."""

    bundle, _ = route_raster_geometry(SITTING_CAT)
    hypotheses = build_recognition_hypothesis_inputs(SITTING_CAT, bundle, max_hypotheses=16)
    vertical_families = {
        (
            item["provenance"]["hypothesis"]["pitch"],
            item["provenance"]["hypothesis"]["phase"],
        )
        for item in hypotheses
    }
    bases = [item["provenance"]["hypothesis"]["base_advance_px"] for item in hypotheses]
    assert len(hypotheses) == 16
    assert len(vertical_families) > 1
    # Every retained vertical family reaches both measured display-base
    # alternatives before extra origin evidence consumes the bounded budget.
    for family in sorted(vertical_families):
        indices = [
            index
            for index, item in enumerate(hypotheses)
            if (
                item["provenance"]["hypothesis"]["pitch"],
                item["provenance"]["hypothesis"]["phase"],
            ) == family
        ]
        assert {bases[index] for index in indices} >= {6.825, 13.65}


def test_hypothesis_edge_ownership_conserves_every_source_pixel() -> None:
    """Proposal-only edge reassignment may move ownership, never lose or duplicate ink."""

    from lateletter.transcription.geometry.evidence import RecognitionInputBuilder

    mask = np.zeros((46, 48), dtype=bool)
    # A horizontal edge stroke and a vertical continuation deliberately cross
    # the nominal seam, matching the connected-stroke failure class without
    # supplying any character or transcript hint.
    mask[21:25, 8:39] = True
    mask[22:44, 25:28] = True
    anchors = [
        {"row_index": 0, "y0": 0, "y1": 23},
        {"row_index": 1, "y0": 23, "y1": 46},
    ]
    owner, owned = RecognitionInputBuilder._reassign_cross_row_edge_pixels(
        mask,
        anchors,
        base_advance=13.65,
    )

    assert np.all(owner[mask] >= 0)
    assert sum(int(item.sum()) for item in owned) == int(mask.sum())
    stacked = np.stack(owned, axis=0)
    assert int(stacked.sum(axis=0).max()) == 1
    assert int(stacked.sum()) == int(mask.sum())


def test_benchmark_v4_records_raster_geometry_instead_of_mask_missing() -> None:
    report_path = ROOT / "recognizer-benchmark-v4-geometry.json"
    report = json.loads(report_path.read_text(encoding="utf-8"))
    release = [item for item in report["results"] if item["expected_outcome"] == "positive"]
    assert release
    assert all(item["geometry_status"] == "proved" for item in release)
    assert all(item["recognition_input_hash"] for item in release)
    assert all(
        "geometry_run_mask_missing" not in reason
        for item in report["results"]
        for adapter in item["adapters"]
        for reason in adapter["unsupported_status"]
    )
    assert report["status"] == "blocked_release_coverage"


def test_sitting_cat_evaluation_truth_unavailable_after_rejected_hand_tuning() -> None:
    evaluation = ROOT.parent.parent / ".." / "tracked" / "LateLetterResearch" / "transcription-parity" / "sitting-cat" / "evaluation"
    manifest = json.loads((evaluation / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["source_sha256"] == "e9b08e31960ffd6fe6e5e52e84107fd22ad80b645b6f1de2e21f4e9a20444275"
    assert manifest["transcript_path"] is None
    assert manifest["transcript_sha256"] is None
    assert manifest["row_count"] == 9
    assert manifest["purpose"] == "evaluation_only"
    assert manifest["runtime_input"] is False
    assert manifest["operator_review"] == "rejected_candidates_001_through_005"
    assert manifest["status"] == "evaluation_truth_unavailable"


def test_benchmark_v5_executes_every_geometry_owned_run_with_tesseract_profiles() -> None:
    report_path = ROOT.parent / "transcription-v2" / "recognizer-benchmark-v5.json"
    report = json.loads(report_path.read_text(encoding="utf-8"))
    release = [item for item in report["results"] if item["expected_outcome"] == "positive"]
    assert len(release) == 10
    assert all(item["geometry_status"] == "proved" for item in release)
    assert all(item["recognition_input_hash"] for item in release)
    assert report["nondeterministic_adapters"] == []
    for item in release:
        counts = {adapter["run_count"] for adapter in item["adapters"]}
        assert len(counts) == 1
        run_count = counts.pop()
        assert run_count > 0
        assert all(adapter["deterministic"] for adapter in item["adapters"])
        assert all(adapter["run_input_hashes"] for adapter in item["adapters"])
        assert all(
            "adapter_exception" not in reason
            for adapter in item["adapters"]
            for reason in adapter["unsupported_status"]
        )
        tesseract = {adapter["adapter"] for adapter in item["adapters"] if adapter["adapter"].startswith("psm")}
        assert tesseract == {"psm7-eng", "psm13-eng", "psm7-jpn-cjk", "psm7-ara"}

    fixed = next(item for item in release if item["fixture"] == "positive-fixed-ascii")
    assert {adapter["run_count"] for adapter in fixed["adapters"]} == {2}
    assert report["status"] == "blocked_release_coverage"
