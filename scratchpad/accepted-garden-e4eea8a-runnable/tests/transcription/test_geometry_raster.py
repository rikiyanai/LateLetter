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
ROOT_V2 = Path(__file__).parents[1] / "fixtures" / "transcription-v2"
HORSE_SHEET = Path(__file__).parents[2] / "tracked" / "LateLetterResearch" / "transcription-parity" / "horse-animation-sheet" / "source" / "source.normalized.png"
SITTING_CAT = Path(__file__).parents[2] / "tracked" / "LateLetterResearch" / "transcription-parity" / "sitting-cat" / "source" / "source.normalized.png"
BBBB_FLOWERS = Path(__file__).parents[2] / "tracked" / "LateLetterResearch" / "transcription-parity" / "bbbb-flowers" / "source" / "source.normalized.png"
A828_REFERENCE = Path(__file__).parents[2] / "tracked" / "LateLetterResearch" / "transcription-parity" / "a8283c5cdb63b130" / "source" / "source.normalized.png"


def test_accepted_anchor_sources_prove_their_lattice_mode() -> None:
    """The two operator-accepted anchors must prove a lattice, not merely cohere.

    Both sources carry an operator-reviewed acceptance receipt built on a
    monospace cell grid, so ``unresolved`` and ``shaped_runs`` are both wrong
    answers for them.  The earlier version of this test accepted either outcome
    as long as the flags agreed with the status, which let a mode regression
    pass unnoticed.  Nothing here reads ``accepted.txt`` or any transcript; the
    expectation comes from the sources' tracked lattice calibrations, which are
    operator-reviewed geometric measurements used only as test expectations.
    """

    for source in (BBBB_FLOWERS, A828_REFERENCE):
        _bundle, decision = route_raster_geometry(source)
        assert decision.status == "proved"
        assert decision.mode == "fixed_lattice"
        assert (
            decision.candidate_valid,
            decision.pitch_proven,
            decision.phase_proven,
            decision.ownership_proven,
        ) == (True, True, True, True)
        assert decision.provenance["selected_geometry"]["geometry_proven"] is True
        assignment = decision.provenance["mode_assignment"]
        assert assignment["lattice_authority_proven"] is True
        # A proved lattice never needs an absence reason, and never consults
        # the shaped branch to reach its answer.
        assert not assignment["lattice_absence_reasons"]
        assert assignment["shaped_admitted"] is False
        assert assignment["transcript_input"] is False


def test_geometry_authority_has_no_status_and_proof_contradiction() -> None:
    """The public decision is the only authority surface.

    A rejected decision may not expose any proof flag.  A proved decision must
    name a concrete mode, expose the selected branch's own property proofs, and
    carry no absence reason for the branch it selected.
    """

    for source in (BBBB_FLOWERS, A828_REFERENCE, SITTING_CAT):
        _bundle, decision = route_raster_geometry(source)
        assert decision.mode in {"fixed_lattice", "shaped_runs", "unresolved"}
        flags = (decision.candidate_valid, decision.pitch_proven, decision.phase_proven, decision.ownership_proven)
        assignment = decision.provenance["mode_assignment"]
        if decision.status == "proved":
            assert decision.mode != "unresolved"
            assert decision.provenance["selected_geometry"]["geometry_proven"] is True
            branch = decision.provenance["branch_proofs"][decision.mode]
            # The four public flags are exactly the selected branch's own
            # measurements -- never raised to true because a mode was chosen.
            assert flags == (
                branch["candidate_valid"],
                branch["pitch_proven"],
                branch["phase_proven"],
                branch["ownership_proven"],
            )
            assert branch["authority_proven"] is True
            assert branch["absence_reasons"] == ()
            if decision.mode == "shaped_runs":
                # Shaped admission requires the lattice absence to be proved,
                # with at least one name from the enumerated vocabulary.
                assert assignment["lattice_absence_proven"] is True
                assert assignment["lattice_absence_reasons"]
                assert set(assignment["lattice_absence_reasons"]) <= set(
                    assignment["absence_vocabulary"]
                )
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


def test_v2_monospace_ascii_fixture_routes_lattice_mode() -> None:
    """A two-row monospace render must route to the lattice branch.

    This fixture is rendered by ``build_corpus_v2.py`` from a monospace font at
    a pinned size, so a cell lattice is true by construction.  It used to route
    ``shaped_runs`` because its zero-seam period band (28..32 px) tied and the
    tie was read as an ambiguity.  All the tied periods carry the same measured
    row-ownership signature, so they describe one geometry and the tie decides
    nothing; the router now says so explicitly.
    """

    source = ROOT_V2 / "positive" / "positive-fixed-ascii" / "source.png"
    bundle, decision = route_raster_geometry(source)

    assert bundle.status == "proved"
    assert decision.status == "proved"
    assert decision.mode == "fixed_lattice"
    assert (
        decision.candidate_valid,
        decision.pitch_proven,
        decision.phase_proven,
        decision.ownership_proven,
    ) == (True, True, True, True)
    assert decision.provenance["mode_assignment"]["lattice_authority_proven"] is True
    authority = bundle.projection_evidence["periodic_authority"]
    # The tie is recorded, not hidden: the margin really is zero, and the proof
    # rests on the contesting periods sharing the winner's row ownership.
    assert authority["normalized_pitch_margin"] == 0.0
    assert authority["pitch_tie_equivalent"] is True
    assert authority["pitch_margin_sufficient"] is True
    assert authority["pitch_tie_contesting_pitches"]
    assert authority["pitch_tie_ownership_signature"]


def test_horse_animation_sheet_proves_its_calibrated_line_pitch() -> None:
    """The horse sheet recovers its true 21 px line pitch from autocorrelation.

    Its operator-reviewed calibration measures a 21.0 px line height and an
    11.55 px cell advance.  Those figures are used here only as test
    expectations; the router never opens a calibration file.

    Seam energy alone cannot see this lattice.  The sheet's box-drawing strokes
    run through every true row seam, so a 21 px period has no gutter to measure
    and the seam ranking prefers 30 px -- and then the harmonic gate rejects 21
    as a supposed stroke harmonic *of that wrong parent*.  The vertical
    autocorrelation of the row-ink profile answers the period question directly:
    it peaks at exactly 21 with a prominence of about six sampling standard
    errors, which restricts the seam ranking to 21's harmonic ladder and refutes
    the harmonic rejection whose parent (30) the same measurement rejected.

    The phase is a different question, and the source still cannot answer it:
    every phase of a 21 px period cuts strokes, the best two differ by 7.3% of
    their boundary ink (below the 10% authority margin), and the winning phase
    moves when the foreground threshold moves.  So this is an honest partial --
    pitch proven, phase not -- and it is pinned as such.
    """

    bundle, decision = route_raster_geometry(HORSE_SHEET)

    assert bundle.status == "proved"
    assert decision.status == "proved"
    # Phase authority is still absent, so no lattice may be claimed.
    assert decision.mode == "shaped_runs"
    assert (
        decision.candidate_valid,
        decision.pitch_proven,
        decision.phase_proven,
        decision.ownership_proven,
    ) == (True, True, False, True)

    lattice = decision.provenance["branch_proofs"]["fixed_lattice"]
    # The fused winner is the calibrated line height, not the seam winner.
    assert lattice["winning_pitch"] == 21
    assert lattice["seam_winning_pitch"] == 30
    assert lattice["pitch_authority_stream"] == "fused_autocorrelation_restricted"
    assert lattice["autocorrelation_decisive"] is True
    assert lattice["autocorrelation_leader_pitch"] == 21.0
    # Six sampling standard errors: far above the three-sigma significance gate.
    assert lattice["autocorrelation_leader_sigma"] > 5.0
    # With the streams fused there is nothing left to contest.
    assert lattice["autocorrelation_contesting_pitch"] is None
    assert lattice["pitch_streams_contested"] is False

    # The fractional horizontal stream corroborates the probe's 11.55 px
    # advance -- a value no integer-lag measurement could have produced.
    assert lattice["horizontal_measured_advance_px"] == 11.55
    assert lattice["horizontal_advance_corroborated"] is True
    assert lattice["horizontal_advance_contested"] is False

    authority = bundle.projection_evidence["periodic_authority"]
    # Pitch replay is stable across every retained foreground threshold; the
    # phase replay is not, and the two are now reported separately.
    assert authority["foreground_stability"]["pitch_stable"] is True
    assert authority["foreground_stability"]["stable_pitch"] == 21
    assert authority["foreground_stability"]["stable"] is False
    assert authority["pitch_margin_sufficient"] is True
    assert authority["phase_margin_sufficient"] is False
    assert 0.0 < authority["normalized_phase_margin"] < 0.10

    assignment = decision.provenance["mode_assignment"]
    assert assignment["lattice_authority_proven"] is False
    assert assignment["lattice_absence_proven"] is True
    assert set(assignment["lattice_absence_reasons"]) <= set(assignment["absence_vocabulary"])
    # The absence is now named by the property that is actually missing.
    assert "lattice_phase_margin_insufficient" in assignment["lattice_absence_reasons"]
    assert "lattice_pitch_margin_insufficient" not in assignment["lattice_absence_reasons"]
    assert (
        "lattice_pitch_contested_by_vertical_autocorrelation"
        not in assignment["lattice_absence_reasons"]
    )


def test_autocorrelation_stream_is_silent_on_shaped_and_proportional_sources() -> None:
    """The promotion path must not fabricate a lattice on non-lattice sources.

    Promoting autocorrelation to pitch authority is exactly how a false lattice
    could be manufactured, so every fixture below is checked twice: the routed
    mode must not become ``fixed_lattice``, *and* the autocorrelation stream
    must not be decisive in the first place.  The second check is the stronger
    one -- it pins the gate rather than the outcome, so a future loosening is
    caught even if some other guard happens to save the mode.

    The sources are proportional Latin, emoji-ZWJ clusters, CJK, mixed script,
    width mixtures and a degraded render, across both fixture corpora.  None of
    them is a monospace cell grid, and their row-ink correlation curves are
    either monotone (no interior peak at all) or carry only ripple below three
    sampling standard errors.
    """

    shaped_fixtures = [
        (ROOT, "positive-emoji-zwj"),
        (ROOT, "positive-kana"),
        (ROOT, "positive-kanji"),
        (ROOT, "positive-mixed-script"),
        (ROOT, "positive-width-mixture"),
        (ROOT, "positive-combining"),
        (ROOT, "positive-degraded-fixed"),
        (ROOT_V2, "positive-emoji-zwj"),
        (ROOT_V2, "positive-kana"),
        (ROOT_V2, "positive-kanji"),
        (ROOT_V2, "positive-mixed-script"),
        (ROOT_V2, "positive-width-mixture"),
        (ROOT_V2, "positive-combining"),
        (ROOT_V2, "positive-degraded-fixed"),
        (ROOT_V2, "positive-proportional-latin"),
        (ROOT, "positive-proportional-latin"),
    ]
    for root, name in shaped_fixtures:
        source = root / "positive" / name / "source.png"
        bundle, decision = route_raster_geometry(source)
        authority = bundle.projection_evidence["periodic_authority"]
        evidence = authority["autocorrelation_pitch_evidence"]
        assert evidence["decisive"] is False, f"{name} fabricated a periodicity"
        assert authority["autocorrelation_selected"] is False, name
        assert authority["pitch_authority_stream"] == "seam_energy", name
        assert not authority["autocorrelation_reinstated_pitches"], name

    # The genuinely shaped fixtures among them must also still route shaped.
    for root, name in shaped_fixtures:
        if "proportional" in name:
            # Both proportional-latin fixtures already routed ``fixed_lattice``
            # before this change, on seam evidence alone; the assertions above
            # pin that the autocorrelation stream took no part in that, and the
            # mode is deliberately left exactly as it was found.
            continue
        source = root / "positive" / name / "source.png"
        _bundle, decision = route_raster_geometry(source)
        assert decision.mode == "shaped_runs", f"{name} flipped to {decision.mode}"


def test_sitting_cat_records_an_undecisive_autocorrelation_peak() -> None:
    """A peak that is real but not significant may not carry the pitch.

    The cat's tracked calibration measures an 18.0 px line height, and the
    autocorrelation curve does lead at lag 18 -- but its prominence is under
    three sampling standard errors on this 236-row raster, so the stream is not
    decisive and the seam ranking keeps its own answer of 23.  That is the
    correct, conservative outcome for this slice: the gate is a statistical
    significance test, not a race to match a calibration, and the source is
    pinned here so the gap is visible rather than silently absorbed.
    """

    bundle, decision = route_raster_geometry(SITTING_CAT)

    assert decision.status == "proved"
    assert decision.mode == "shaped_runs"
    authority = bundle.projection_evidence["periodic_authority"]
    evidence = authority["autocorrelation_pitch_evidence"]
    assert evidence["leader_lag"] == 18.0
    assert evidence["separation_met"] is True
    assert evidence["significance_met"] is False
    assert evidence["leader_prominence_sigma"] < evidence["significance_sigma"]
    assert evidence["decisive"] is False
    assert authority["pitch_authority_stream"] == "seam_energy"
    assert authority["winning_pitch"] == 23


def test_shaped_admission_requires_a_typed_lattice_absence(monkeypatch) -> None:
    """An unexplained lattice failure must fail shut, never fall back to shaped.

    The router is handed a lattice proof whose authority is absent but whose
    absence carries no typed reason.  That is a hole in the proof, so the only
    admissible answer is ``unresolved`` even though the shaped branch of this
    source proves perfectly well on its own.
    """

    from lateletter.transcription.geometry import router as router_module

    source = ROOT / "positive" / "positive-emoji-zwj" / "source.png"
    _bundle, baseline = route_raster_geometry(source)
    assert baseline.mode == "shaped_runs"

    real_proof = router_module._lattice_proof

    def untyped_proof(bundle, *, criterion_threshold):
        proof = dict(real_proof(bundle, criterion_threshold=criterion_threshold))
        proof["authority_proven"] = False
        proof["absence_reasons"] = (router_module.UNTYPED_LATTICE_ABSENCE,)
        return proof

    monkeypatch.setattr(router_module, "_lattice_proof", untyped_proof)
    _bundle, decision = route_raster_geometry(source)
    assert decision.mode == "unresolved"
    assert decision.status == "rejected"
    assert router_module.UNTYPED_LATTICE_ABSENCE in decision.rejection_reasons
    assert (
        decision.candidate_valid,
        decision.pitch_proven,
        decision.phase_proven,
        decision.ownership_proven,
    ) == (False, False, False, False)


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
    # Honest per-property flags.  The cat proves a stable row period and
    # exactly-once run ownership, but its phase groups do not separate, so the
    # phase proof stays false even though the shaped decision itself is proved.
    assert (decision.candidate_valid, decision.pitch_proven, decision.phase_proven, decision.ownership_proven) == (True, True, False, True)
    assignment = decision.provenance["mode_assignment"]
    assert assignment["lattice_authority_proven"] is False
    assert assignment["lattice_absence_proven"] is True
    assert "lattice_phase_margin_insufficient" in assignment["lattice_absence_reasons"]
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


# ---------------------------------------------------------------------------
# Unit-level pins on the autocorrelation periodicity stream
# ---------------------------------------------------------------------------
# The tests above measure real sources.  The ones below pin the gate itself, so
# a future loosening is caught even on a source nobody thought to add.


def test_monotone_correlation_curve_carries_no_periodicity_evidence() -> None:
    """A decaying curve has no interior peak, so no lag may be a period.

    This is the shape a shaped or proportional source produces: neighbouring
    lags of a smooth ink profile correlate, so the curve slides downwards from
    the shortest searched lag with nothing standing out.  Reading its *maximum*
    as a pitch -- which is what a raw-magnitude comparison does -- would name the
    shortest searched lag as the period of almost every source in the corpus.
    """

    from lateletter.transcription.geometry.evidence import (
        _autocorrelation_periodicity_evidence,
        _curve_peak_prominences,
    )

    curve = {float(lag): 0.9 - 0.02 * lag for lag in range(8, 33)}
    assert _curve_peak_prominences(curve) == []
    evidence = _autocorrelation_periodicity_evidence(
        curve, authority_margin=0.10, sample_count=400
    )
    assert evidence["decisive"] is False
    assert evidence["leader_lag"] is None
    assert evidence["peaks"] == []


def test_autocorrelation_significance_scales_with_the_sampling_error() -> None:
    """The same peak is evidence on a tall raster and noise on a short one.

    Bartlett's approximation puts the standard error of a sample
    autocorrelation at ``1 / sqrt(N)``.  A prominence of 0.15 is five standard
    errors on a 1000-row profile and well under three on a 100-row profile, and
    the gate must follow that -- it is a significance test, not a fixed cutoff.
    """

    from lateletter.transcription.geometry.evidence import _autocorrelation_periodicity_evidence

    curve = {float(lag): 0.30 - 0.004 * lag for lag in range(8, 33)}
    curve[21.0] = curve[21.0] + 0.15  # one clean peak, prominence 0.15

    # The peak stands 0.15 above the trend line, and its nearer col is the
    # neighbouring lag one trend-step (0.004) below it, so the prominence the
    # measurement reports is 0.146.
    tall = _autocorrelation_periodicity_evidence(curve, authority_margin=0.10, sample_count=1000)
    assert tall["leader_lag"] == 21.0
    assert tall["leader_prominence"] == pytest.approx(0.146, abs=1e-9)
    assert tall["leader_prominence_sigma"] == pytest.approx(0.146 * 1000 ** 0.5, rel=1e-9)
    assert tall["significance_met"] is True
    assert tall["decisive"] is True

    short = _autocorrelation_periodicity_evidence(curve, authority_margin=0.10, sample_count=100)
    assert short["leader_lag"] == 21.0
    assert short["significance_met"] is False
    assert short["decisive"] is False


def test_autocorrelation_leader_outside_the_admissible_set_never_decides() -> None:
    """A period with no valid candidate cannot be selected, however clean.

    ``admissible`` is the set of periods the seam sweep produced a valid
    candidate for.  A correlation peak at a period that was rejected (a terminal
    sliver, an unexplained clipped edge) is reported but must fail shut, because
    there is no geometry behind it to route to.
    """

    from lateletter.transcription.geometry.evidence import _autocorrelation_periodicity_evidence

    curve = {float(lag): 0.30 - 0.004 * lag for lag in range(8, 33)}
    curve[21.0] = curve[21.0] + 0.30

    admitted = _autocorrelation_periodicity_evidence(
        curve, authority_margin=0.10, sample_count=1000, admissible={21.0}
    )
    assert admitted["decisive"] is True

    excluded = _autocorrelation_periodicity_evidence(
        curve, authority_margin=0.10, sample_count=1000, admissible={19.0, 30.0}
    )
    assert excluded["leader_lag"] == 21.0
    assert excluded["significance_met"] is True
    assert excluded["leader_admissible"] is False
    assert excluded["decisive"] is False


def test_harmonic_ladder_folds_multiples_and_divisors_of_the_leader() -> None:
    """A period's own harmonics are not rivals to it.

    A source with period 15 also correlates at 30.  Counting 30 as a competitor
    would destroy the separation margin of a perfectly clean measurement, so the
    ladder folds multiples and divisors into the leader before the margin test.
    """

    from lateletter.transcription.geometry.evidence import _harmonic_ladder

    lags = [float(value) for value in range(8, 33)]
    assert _harmonic_ladder(15.0, lags) == [15.0, 30.0]
    assert _harmonic_ladder(21.0, lags) == [21.0]
    # Fractional lags need slack; a quarter pixel is enough to fold 11.5 into 23.
    assert 23.0 in _harmonic_ladder(11.5, [11.5, 17.0, 23.0], tolerance=0.25)


def test_fractional_autocorrelation_recovers_a_non_integer_period() -> None:
    """The horizontal stream must see advances no integer lag can express.

    The horse sheet's operator-reviewed cell advance is 11.55 px.  A synthetic
    profile with exactly that period must peak at 11.55 and not at 11 or 12,
    which is the whole reason the horizontal sweep is fractional.
    """

    from lateletter.transcription.geometry.evidence import (
        _curve_peak_prominences,
        _fractional_autocorrelation,
    )

    period = 11.55
    columns = np.arange(600, dtype=float)
    # A narrow bar once per period: the column-ink profile of a cell grid.
    profile = np.exp(-((columns % period) - 0.0) ** 2 / 0.8) + np.exp(
        -((columns % period) - period) ** 2 / 0.8
    )
    curve = _fractional_autocorrelation(profile, 9.0, 16.0, 0.05)
    assert curve
    peaks = _curve_peak_prominences(curve)
    assert peaks
    assert peaks[0]["lag"] == pytest.approx(period, abs=0.05)
