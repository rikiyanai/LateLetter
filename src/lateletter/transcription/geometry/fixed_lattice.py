"""Evidence contract for fixed-cell lattice geometry."""

from __future__ import annotations

from typing import Any, Mapping

from .evidence import GeometryProof, evaluate_criteria

FIXED_LATTICE_CRITERIA = (
    "row_periodicity",
    "horizontal_advance_stability",
    "phase_origin_confidence",
    "fullwidth_multiples",
    "boundary_intersections",
    "horizontal_joins_vs_cuts",
    "negative_origin_clipping",
    "cross_row_spill",
    "foreground_alternatives",
)


def assess_fixed_lattice(evidence: Mapping[str, Any] | None, *, threshold: float = 0.8) -> GeometryProof:
    return evaluate_criteria("fixed_lattice", evidence, FIXED_LATTICE_CRITERIA, threshold=threshold)
