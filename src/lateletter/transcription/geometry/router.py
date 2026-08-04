"""Exclusive fixed-lattice versus shaped-run authority router."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from typing import Any, Mapping

from ..hashing import require_sha256, sha256_bytes
from ..model import GeometryDecision
from ..schema import canonical_bytes
from .evidence import GeometryProof
from .evidence import GeometryEvidenceBundle, build_geometry_evidence
from .fixed_lattice import assess_fixed_lattice
from .shaped_runs import assess_shaped_runs


def route_geometry(
    source_hash: str,
    fixed_evidence: Mapping[str, Any] | None,
    shaped_evidence: Mapping[str, Any] | None,
    *,
    configuration: Mapping[str, Any] | None = None,
    provenance: Mapping[str, Any] | None = None,
) -> GeometryDecision:
    """Return exactly one authority, or an explicit unresolved decision."""

    require_sha256(source_hash, field="source_hash")
    configuration = dict(configuration or {})
    threshold = float(configuration.get("criterion_threshold", 0.8))
    margin = float(configuration.get("authority_margin", 0.15))
    if not 0 < threshold <= 1 or margin < 0:
        raise ValueError("invalid geometry router thresholds")
    fixed = assess_fixed_lattice(fixed_evidence, threshold=threshold)
    shaped = assess_shaped_runs(shaped_evidence, threshold=threshold)
    evidence = {"fixed_lattice": fixed.to_dict(), "shaped_runs": shaped.to_dict()}
    evidence_hash = sha256_bytes(canonical_bytes(evidence))
    selected: GeometryProof | None = None
    rejection_codes: list[str] = []
    if fixed.passed and fixed.score - shaped.score >= margin:
        selected = fixed
    elif shaped.passed and shaped.score - fixed.score >= margin:
        selected = shaped
    else:
        rejection_codes.append("geometry_unresolved")
        if fixed.passed and shaped.passed:
            rejection_codes.append("geometry_authority_tie")
        if not fixed.passed:
            rejection_codes.extend(fixed.rejection_reasons)
        if not shaped.passed:
            rejection_codes.extend(shaped.rejection_reasons)
    if selected is None:
        mode = "unresolved"
        geometry_hash = sha256_bytes(canonical_bytes({"mode": mode, "evidence_hash": evidence_hash}))
    else:
        mode = selected.mode
        geometry_hash = sha256_bytes(
            canonical_bytes({"mode": mode, "score": selected.score, "evidence_hash": evidence_hash})
        )
    return GeometryDecision(
        mode=mode,
        confidence=selected.score if selected else max(fixed.score, shaped.score),
        alternatives=(fixed.to_dict(), shaped.to_dict()),
        evidence_hash=evidence_hash,
        geometry_hash=geometry_hash,
        input_hashes={"source": source_hash, "geometry_evidence": evidence_hash},
        configuration={"criterion_threshold": threshold, "authority_margin": margin, **configuration},
        provenance={"router": "exclusive", "proofs": evidence, **dict(provenance or {})},
        status="proved" if selected else "rejected",
        rejection_reasons=tuple(rejection_codes),
        candidate_valid=bool(selected),
        pitch_proven=bool(selected),
        phase_proven=bool(selected),
        ownership_proven=bool(selected),
    )


def route_raster_geometry(
    source_path: str | Path,
    *,
    expected_sha256: str | None = None,
    configuration: Mapping[str, Any] | None = None,
) -> tuple[GeometryEvidenceBundle, GeometryDecision]:
    """Recover and route geometry from a PNG without caller-supplied scores.

    The legacy :func:`route_geometry` remains available for proof-unit tests,
    but this is the production authority.  Both model proofs are calculated
    by ``build_geometry_evidence`` from source projections and masks.  The
    returned decision carries the selected concrete lattice/run contract in
    ``provenance['selected_geometry']`` and binds its hash to the evidence
    bundle.
    """

    bundle = build_geometry_evidence(
        source_path,
        expected_sha256=expected_sha256,
        configuration=configuration,
    )
    # Production raster routing is owned here.  ``route_geometry`` remains a
    # diagnostic proof adapter for legacy unit fixtures, but its score margin
    # cannot select a production model.
    threshold = float((configuration or {}).get("criterion_threshold", 0.8))
    fixed = assess_fixed_lattice(bundle.fixed_evidence(), threshold=threshold)
    shaped = assess_shaped_runs(bundle.shaped_evidence(), threshold=threshold)
    periodic = bundle.projection_evidence.get("periodic_authority", {})
    fixed_authority = bool(periodic.get("fixed_lattice_authority_proven"))
    shaped_authority = bool(
        bundle.status == "proved"
        and bundle.shaped_evidence().get("shaped_run_authority_proven")
        and not fixed_authority
    )
    selected_mode = "fixed_lattice" if fixed_authority else "shaped_runs" if shaped_authority else "unresolved"
    authority_proofs: dict[str, dict[str, Any]] = {}
    for proof, authority in ((fixed, fixed_authority), (shaped, shaped_authority)):
        item = proof.to_dict()
        item["branch_candidate_passed"] = bool(proof.passed)
        item["authority_proven"] = bool(authority)
        item["passed"] = bool(authority)
        authority_proofs[proof.mode] = item
    rejection_codes: list[str] = []
    if selected_mode == "unresolved":
        rejection_codes.append("geometry_unresolved")
        rejection_codes.extend(bundle.rejection_reasons)
        rejection_codes.extend(fixed.rejection_reasons)
        rejection_codes.extend(shaped.rejection_reasons)
    selected = bundle.geometry_mapping(selected_mode) if selected_mode != "unresolved" else None
    if selected is None:
        return bundle, GeometryDecision(
            mode="unresolved",
            confidence=0.0,
            alternatives=tuple(authority_proofs.values()),
            evidence_hash=bundle.output_hash,
            geometry_hash=sha256_bytes(canonical_bytes({"mode": "unresolved", "evidence": bundle.output_hash})),
            input_hashes={"source": bundle.source_sha256, "geometry_evidence": bundle.output_hash},
            configuration={"criterion_threshold": threshold, **dict(configuration or {})},
            provenance={
                "router": "raster_authority_owner",
                "proofs": authority_proofs,
                "selected_geometry": None,
                "bundle_status": bundle.status,
                "bundle_rejection_reasons": list(bundle.rejection_reasons),
            },
            status="rejected",
            rejection_reasons=tuple(dict.fromkeys(rejection_codes)),
            candidate_valid=False,
            pitch_proven=False,
            phase_proven=False,
            ownership_proven=False,
        )
    selected_hash = sha256_bytes(canonical_bytes(selected))
    return bundle, GeometryDecision(
        mode=selected_mode,
        confidence=float(fixed.score if selected_mode == "fixed_lattice" else shaped.score),
        alternatives=tuple(authority_proofs.values()),
        evidence_hash=bundle.output_hash,
        geometry_hash=selected_hash,
        input_hashes={"source": bundle.source_sha256, "geometry_evidence": bundle.output_hash},
        configuration={"criterion_threshold": threshold, **dict(configuration or {})},
        provenance={
            "router": "raster_authority_owner",
            "proofs": authority_proofs,
            "selected_geometry": selected,
            "bundle_status": bundle.status,
        },
        status="proved",
        rejection_reasons=(),
        candidate_valid=True,
        pitch_proven=True,
        phase_proven=True,
        ownership_proven=True,
    )


# Explicit alias used by command-line/integration callers.
recover_geometry = route_raster_geometry
