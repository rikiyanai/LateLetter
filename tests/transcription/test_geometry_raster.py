"""Literal-PNG geometry ownership tests.

These tests intentionally pass only a source PNG to the geometry owner.  The
corpus transcript and visual-layout sidecar are never opened, so a successful
run proves that recognizer inputs came from measured raster evidence.
"""

from __future__ import annotations

from pathlib import Path
import json

from lateletter.transcription.geometry import (
    build_recognition_inputs,
    route_raster_geometry,
)


ROOT = Path(__file__).parents[1] / "fixtures" / "transcription"
SITTING_CAT = Path(__file__).parents[2] / "tracked" / "LateLetterResearch" / "transcription-parity" / "sitting-cat" / "source" / "source.normalized.png"


def test_fixed_ascii_png_produces_concrete_lattice_and_complete_row_strips() -> None:
    source = ROOT / "positive" / "positive-fixed-ascii" / "source.png"
    bundle, decision = route_raster_geometry(source)

    assert bundle.status == "proved"
    assert decision.mode == "fixed_lattice"
    selected = decision.provenance["selected_geometry"]
    assert selected["geometry_proven"] is True
    assert selected["cells"]
    assert selected["source_sha256"] == bundle.source_sha256
    assert selected["selected_foreground_mask_sha256"] == bundle.projection_evidence["selected_mask_sha256"]

    inputs = build_recognition_inputs(source, bundle, mode=decision.mode)
    assert inputs["mode"] == "fixed_lattice"
    assert len(inputs["runs"]) == len(selected["row_bands"])
    assert all(item["source_bounds"][0] == 0 for item in inputs["runs"])
    assert all(item["source_bounds"][2] == 180 for item in inputs["runs"])
    assert all(item["run_strip_png_sha256"] for item in inputs["runs"])
    assert all(item["binary_run_mask_sha256"] for item in inputs["runs"])
    assert inputs["provenance"]["source_only"] is True
    assert inputs["provenance"]["transcript_input"] is False

    # The same source and pinned configuration must produce byte-identical
    # strips and hashes across runs.
    assert inputs == build_recognition_inputs(source, bundle, mode=decision.mode)
    assert build_recognition_inputs(source, bundle.to_dict(), mode=decision.mode)["input_hash"] == inputs["input_hash"]


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


def test_vertically_connected_cat_art_rejects_blank_gap_row_undersegmentation() -> None:
    """A giant connected band may not masquerade as a proved lattice.

    The cat has vertical strokes spanning several logical drawing rows.  The
    old blank-gap grouping collapsed those rows into four bands and let OCR
    run anyway.  Until periodic baselines are recovered, geometry must fail
    closed before recognition inputs are built.
    """

    bundle, decision = route_raster_geometry(SITTING_CAT)

    assert bundle.status == "rejected"
    assert decision.mode == "unresolved"
    assert "row_baselines_undersegmented" in bundle.rejection_reasons
    quality = bundle.projection_evidence["row_band_quality"]
    assert quality["periodic_baselines_proven"] is False
    assert quality["largest_height"] >= 3 * quality["reference_height"]
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

    terminal_sliver = next(item for item in periodic if item["pitch"] == 22 and item["phase"] == 12)
    assert terminal_sliver["valid"] is False
    assert terminal_sliver["terminal_sliver_rejected"] is True
    assert terminal_sliver["baseline_delta_residuals"][-1] == -18
    assert "terminal_sliver_rejected" in terminal_sliver["rejection_reasons"]
    assert terminal_sliver["partial_edge_rows"] == []


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
