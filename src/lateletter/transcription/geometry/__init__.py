"""Exclusive geometry proof, raster recovery, and routing."""

from .evidence import (
    GeometryEvidenceBundle,
    GeometryProof,
    RecognitionInputBuilder,
    build_geometry_evidence,
    build_recognition_hypothesis_inputs,
    build_recognition_inputs,
    evaluate_criteria,
)
from .fixed_lattice import assess_fixed_lattice
from .router import recover_geometry, route_geometry, route_raster_geometry
from .shaped_runs import assess_shaped_runs

__all__ = [
    "GeometryProof",
    "GeometryEvidenceBundle",
    "RecognitionInputBuilder",
    "build_geometry_evidence",
    "build_recognition_hypothesis_inputs",
    "build_recognition_inputs",
    "evaluate_criteria",
    "assess_fixed_lattice",
    "assess_shaped_runs",
    "route_geometry",
    "route_raster_geometry",
    "recover_geometry",
]
