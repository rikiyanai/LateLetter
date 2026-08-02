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
    decision = route_geometry(
        bundle.source_sha256,
        bundle.fixed_evidence(),
        bundle.shaped_evidence(),
        configuration={
            "criterion_threshold": float((configuration or {}).get("criterion_threshold", 0.8)),
            "authority_margin": float((configuration or {}).get("authority_margin", 0.05)),
        },
        provenance={"evidence_bundle_hash": bundle.output_hash},
    )
    # A bundle that cannot prove a foreground/row/run model is never upgraded
    # by the router's score arithmetic.
    if bundle.status != "proved" or decision.mode == "unresolved":
        return bundle, replace(
            decision,
            mode="unresolved",
            confidence=0.0,
            geometry_hash=sha256_bytes(canonical_bytes({"mode": "unresolved", "evidence": bundle.output_hash})),
            evidence_hash=bundle.output_hash,
            input_hashes={"source": bundle.source_sha256, "geometry_evidence": bundle.output_hash},
            provenance={
                **dict(decision.provenance),
                "selected_geometry": None,
                "bundle_status": bundle.status,
                "bundle_rejection_reasons": list(bundle.rejection_reasons),
            },
            status="rejected",
            rejection_reasons=tuple(dict.fromkeys((*decision.rejection_reasons, *bundle.rejection_reasons))),
            output_hash="",
        )
    selected = bundle.geometry_mapping(decision.mode)
    selected_hash = sha256_bytes(canonical_bytes(selected))
    return bundle, replace(
        decision,
        evidence_hash=bundle.output_hash,
        geometry_hash=selected_hash,
        input_hashes={"source": bundle.source_sha256, "geometry_evidence": bundle.output_hash},
        provenance={
            **dict(decision.provenance),
            "selected_geometry": selected,
            "bundle_status": bundle.status,
        },
        output_hash="",
    )


# Explicit alias used by command-line/integration callers.
recover_geometry = route_raster_geometry
