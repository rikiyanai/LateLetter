"""Exclusive geometry authority tests."""

from __future__ import annotations

import pytest

from lateletter.transcription.geometry import assess_fixed_lattice, assess_shaped_runs, route_geometry


H = "b" * 64


def fixed(score: float = 1.0) -> dict[str, float]:
    return {
        "row_periodicity": score,
        "horizontal_advance_stability": score,
        "phase_origin_confidence": score,
        "fullwidth_multiples": score,
        "boundary_intersections": score,
        "horizontal_joins_vs_cuts": score,
        "negative_origin_clipping": score,
        "cross_row_spill": score,
        "foreground_alternatives": score,
    }


def shaped(score: float = 1.0) -> dict[str, float]:
    return {
        "row_bands_baselines": score,
        "variable_advances": score,
        "connected_joined_runs": score,
        "direction_candidates": score,
        "vertical_text_candidates": score,
    }


def test_fixed_lattice_wins_only_with_pinned_margin() -> None:
    decision = route_geometry(H, fixed(), shaped(0.4))
    assert decision.mode == "fixed_lattice"
    assert decision.status == "proved"
    assert decision.geometry_hash
    assert decision.alternatives[0]["mode"] == "fixed_lattice"


def test_shaped_runs_wins_for_variable_directional_evidence() -> None:
    decision = route_geometry(H, fixed(0.3), shaped())
    assert decision.mode == "shaped_runs"
    assert decision.status == "proved"


def test_tie_and_missing_evidence_are_unresolved_not_dual_authority() -> None:
    tie = route_geometry(H, fixed(), shaped())
    assert tie.mode == "unresolved"
    assert "geometry_authority_tie" in tie.rejection_reasons
    missing = route_geometry(H, {}, {})
    assert missing.mode == "unresolved"
    assert "geometry_unresolved" in missing.rejection_reasons


def test_fixed_proof_retains_required_failure_reasons() -> None:
    proof = assess_fixed_lattice({"row_periodicity": True})
    assert proof.passed is False
    assert any(reason.endswith("horizontal_advance_stability") for reason in proof.rejection_reasons)
    assert assess_shaped_runs(shaped()).passed is True


def test_router_rejects_malformed_source_binding_and_invalid_thresholds() -> None:
    with pytest.raises(ValueError):
        route_geometry("not-a-hash", fixed(), shaped())
    with pytest.raises(ValueError):
        route_geometry(H, fixed(), shaped(), configuration={"authority_margin": -1})
