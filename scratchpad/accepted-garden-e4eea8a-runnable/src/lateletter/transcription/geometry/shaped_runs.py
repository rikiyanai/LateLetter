"""Evidence contract for variable-width/shaped visual runs."""

from __future__ import annotations

from typing import Any, Mapping

from .evidence import GeometryProof, evaluate_criteria

SHAPED_RUN_CRITERIA = (
    "row_bands_baselines",
    "variable_advances",
    "connected_joined_runs",
    "direction_candidates",
    "vertical_text_candidates",
)


def assess_shaped_runs(evidence: Mapping[str, Any] | None, *, threshold: float = 0.8) -> GeometryProof:
    return evaluate_criteria("shaped_runs", evidence, SHAPED_RUN_CRITERIA, threshold=threshold)
