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
        # This legacy adapter is handed aggregate criterion scores, not per-
        # property raster measurements, so it has nothing finer than "a branch
        # won" to report.  The four flags below are therefore only a coherence
        # echo of that selection.  Production routing -- and the honest,
        # branch-derived flags -- live in route_raster_geometry above.
        candidate_valid=bool(selected),
        pitch_proven=bool(selected),
        phase_proven=bool(selected),
        ownership_proven=bool(selected),
    )


# ---------------------------------------------------------------------------
# Typed absence vocabulary
# ---------------------------------------------------------------------------
# Mode assignment is lattice-first: the fixed-lattice branch is evaluated before
# any shaped-run evidence is consulted, and a shaped decision is admitted only
# when the *absence* of lattice authority has itself been proved.  "Proved
# absent" means the router could name at least one specific measurement that
# came out negative.  The tuple below is the enumerated set of those names; it
# is not free text, and every entry corresponds to one branch of
# ``_lattice_proof`` below.
LATTICE_ABSENCE_REASONS: tuple[str, ...] = (
    # The geometry evidence bundle itself did not prove, so no lattice claim
    # could rest on it.
    "lattice_evidence_bundle_rejected",
    # The raster produced no fixed-lattice candidate at all (no usable
    # foreground, or no column-projection periodicity peak).
    "lattice_candidate_absent",
    # The periodic row sweep produced no candidate that survived its own
    # validity checks (terminal/initial slivers, unexplained clipped edges).
    "lattice_periodic_candidate_invalid",
    # No winning row period could be measured from the seam ranking.
    "lattice_pitch_unmeasured",
    # A winning period exists but does not separate from its rivals, and the
    # rivals do not describe the same row ownership.
    "lattice_pitch_margin_insufficient",
    # Same, for the phase (origin) of the winning period.
    "lattice_phase_margin_insufficient",
    # The winning candidate does not own every source pixel exactly once.
    "lattice_ownership_incomplete",
    # Measured baselines disagree with the measured line advance, so the rows
    # are not a regular lattice.
    "lattice_baselines_irregular",
    # Replaying the pinned foreground thresholds does not reproduce the same
    # winning period/phase, so the lattice is an artefact of one threshold.
    "lattice_foreground_unstable",
    # Fewer than two rows were measured; one band cannot exhibit a period.
    "lattice_rows_below_minimum",
    # Blank-gap grouping reports undersegmentation and the periodic baseline
    # proof did not rescue it.
    "lattice_row_bands_undersegmented",
    # The concrete lattice candidate's own measured criteria sit below the
    # pinned criterion threshold.
    "lattice_branch_criteria_below_threshold",
    # An independent measurement (vertical autocorrelation of the row-ink
    # profile) prefers a different period to the seam-ranked winner.
    "lattice_pitch_contested_by_vertical_autocorrelation",
)

# Emitted when the lattice branch neither proved nor produced any of the typed
# findings above.  It is deliberately NOT a member of
# ``LATTICE_ABSENCE_REASONS``: an untyped absence is a hole in the proof and
# never licenses a shaped admission.  The router fails shut instead.
UNTYPED_LATTICE_ABSENCE = "lattice_authority_absence_untyped"

# The same discipline for the shaped-run branch.
SHAPED_ABSENCE_REASONS: tuple[str, ...] = (
    "shaped_evidence_bundle_rejected",
    "shaped_row_bands_absent",
    "shaped_run_anchors_absent",
    "shaped_component_unowned",
)
UNTYPED_SHAPED_ABSENCE = "shaped_authority_absence_untyped"


def _autocorrelation_contest(projection: Mapping[str, Any]) -> int | None:
    """Return a row period that out-measures the seam-ranked winner, if any.

    ``periodic_row_candidates`` already carries, for every measured period, the
    vertical autocorrelation of the source row-ink profile at that lag.  That is
    an *independent* periodicity measurement: unlike seam energy it does not
    reward a long period simply for having fewer boundaries to cut.  When some
    other period scores strictly higher on it, the seam-ranked winner is
    contested, and the router records that by name.

    This function reads source-derived numbers only -- no transcript, no
    calibration file, no fixture metadata.  It is consulted solely to *explain*
    an already-absent lattice authority, so it can never promote a mode.

    :param projection: the bundle's ``projection_evidence`` mapping.
    :returns: the contesting period in pixels, or ``None`` when the winner is
        also the autocorrelation leader (or nothing could be measured).
    """

    periodic = dict(projection.get("periodic_authority", {}))
    winner = periodic.get("winning_pitch")
    if winner is None:
        return None
    # One score per period: every phase of a period shares the same lag, so the
    # maximum over phases is that period's measurement.
    best_by_pitch: dict[int, float] = {}
    for item in projection.get("periodic_row_candidates", ()):  # source measurements
        if not bool(item.get("candidate_valid")):
            continue
        pitch = int(item.get("pitch", 0))
        score = float(item.get("vertical_autocorrelation", 0.0))
        if score > best_by_pitch.get(pitch, -1.0):
            best_by_pitch[pitch] = score
    if not best_by_pitch:
        return None
    # Ties go to the shorter period: a lattice period is the fundamental, and a
    # multiple of it necessarily reproduces the same correlation.
    leader_pitch, leader_score = max(best_by_pitch.items(), key=lambda entry: (entry[1], -entry[0]))
    if int(leader_pitch) == int(winner):
        return None
    if leader_score <= best_by_pitch.get(int(winner), 0.0):
        return None
    return int(leader_pitch)


def _lattice_proof(bundle: GeometryEvidenceBundle, *, criterion_threshold: float) -> dict[str, Any]:
    """Prove fixed-lattice authority, or prove its absence with typed reasons.

    :param bundle: the raster evidence recovered from the source PNG.
    :param criterion_threshold: the pinned per-criterion score the concrete
        lattice candidate must reach; supplied by the caller's configuration so
        the threshold is never chosen here.
    :returns: a mapping with ``authority_proven``, the four honest per-property
        proofs (``candidate_valid``, ``pitch_proven``, ``phase_proven``,
        ``ownership_proven``) taken from this branch's own evidence, and
        ``absence_reasons`` -- empty when authority is proved, otherwise one or
        more names drawn from :data:`LATTICE_ABSENCE_REASONS`.
    """

    projection = bundle.projection_evidence
    periodic = dict(projection.get("periodic_authority", {}))
    detail = dict(periodic.get("fixed_lattice_authority", {}))
    row_band_quality = dict(projection.get("row_band_quality", {}))
    stability = dict(periodic.get("foreground_stability", {}))
    candidates = bundle.fixed_lattice_candidates
    leading_candidate = dict(candidates[0]) if candidates else {}

    authority_proven = bool(periodic.get("fixed_lattice_authority_proven"))
    # The four properties are read straight from the evidence owner.  They are
    # never overwritten to agree with the chosen mode.
    candidate_valid = bool(periodic.get("candidate_valid")) and bool(candidates)
    pitch_proven = bool(periodic.get("pitch_proven"))
    phase_proven = bool(periodic.get("phase_proven"))
    ownership_proven = bool(periodic.get("ownership_proven"))

    reasons: list[str] = []
    contesting_pitch: int | None = None
    if not authority_proven:
        margin = float(periodic.get("authority_margin", 0.10))
        if bundle.status != "proved":
            reasons.append("lattice_evidence_bundle_rejected")
        if not candidates:
            reasons.append("lattice_candidate_absent")
        if not periodic.get("candidate_valid"):
            reasons.append("lattice_periodic_candidate_invalid")
        if periodic.get("winning_pitch") in (None, 0):
            reasons.append("lattice_pitch_unmeasured")
        # ``*_margin_sufficient`` already accounts for near-ties whose rivals
        # describe identical row ownership; fall back to the raw comparison for
        # evidence produced before those keys existed.
        pitch_margin_ok = bool(
            periodic.get(
                "pitch_margin_sufficient",
                float(periodic.get("normalized_pitch_margin", 0.0)) >= margin,
            )
        )
        phase_margin_ok = bool(
            periodic.get(
                "phase_margin_sufficient",
                float(periodic.get("normalized_phase_margin", 0.0)) >= margin,
            )
        )
        if not pitch_margin_ok:
            reasons.append("lattice_pitch_margin_insufficient")
        if not phase_margin_ok:
            reasons.append("lattice_phase_margin_insufficient")
        if not detail.get("ownership_complete", False):
            reasons.append("lattice_ownership_incomplete")
        if not detail.get("baseline_regular", False):
            reasons.append("lattice_baselines_irregular")
        if not stability.get("stable", False):
            reasons.append("lattice_foreground_unstable")
        if int(leading_candidate.get("rows", 0)) < 2:
            reasons.append("lattice_rows_below_minimum")
        if row_band_quality.get("undersegmented") and not periodic.get("baseline_proven"):
            reasons.append("lattice_row_bands_undersegmented")
        measured = dict(detail.get("criterion_values", {}))
        if measured and any(float(value) < criterion_threshold for value in measured.values()):
            reasons.append("lattice_branch_criteria_below_threshold")
        contesting_pitch = _autocorrelation_contest(projection)
        if contesting_pitch is not None:
            reasons.append("lattice_pitch_contested_by_vertical_autocorrelation")
        if not reasons:
            # Nothing measurable explained the absence.  Say so rather than
            # letting an unexplained lattice failure hand the source to the
            # shaped branch.
            reasons.append(UNTYPED_LATTICE_ABSENCE)

    return {
        "mode": "fixed_lattice",
        "authority_proven": authority_proven,
        "candidate_valid": candidate_valid,
        "pitch_proven": pitch_proven,
        "phase_proven": phase_proven,
        "ownership_proven": ownership_proven,
        "absence_reasons": tuple(dict.fromkeys(reasons)),
        "winning_pitch": periodic.get("winning_pitch"),
        "normalized_pitch_margin": float(periodic.get("normalized_pitch_margin", 0.0)),
        "normalized_phase_margin": float(periodic.get("normalized_phase_margin", 0.0)),
        "pitch_tie_equivalent": bool(periodic.get("pitch_tie_equivalent")),
        "phase_tie_equivalent": bool(periodic.get("phase_tie_equivalent")),
        "autocorrelation_contesting_pitch": contesting_pitch,
        "evidence": "source_raster_periodic_authority",
    }


def _shaped_run_proof(bundle: GeometryEvidenceBundle) -> dict[str, Any]:
    """Prove shaped-run authority, or prove its absence with typed reasons.

    A shaped-run decision asserts measured row bands, measured run anchors, and
    exactly-once ownership of every foreground pixel.  It deliberately asserts
    *no* cell period and *no* cell phase.  ``pitch_proven`` and ``phase_proven``
    therefore report what the source's periodic row evidence actually measured
    for this raster -- which a shaped decision does not depend on -- rather than
    being raised to true because a mode was chosen.

    :param bundle: the raster evidence recovered from the source PNG.
    :returns: the same shape as :func:`_lattice_proof`, with absence reasons
        drawn from :data:`SHAPED_ABSENCE_REASONS`.
    """

    projection = bundle.projection_evidence
    periodic = dict(projection.get("periodic_authority", {}))
    candidate = dict(bundle.shaped_evidence())
    components = dict(bundle.component_evidence)
    unowned = list(components.get("unassigned_component_ids", ()))

    candidate_valid = bool(candidate.get("row_bands")) and bool(candidate.get("run_anchors"))
    ownership_proven = bool(components.get("component_ownership_complete")) and not unowned
    authority_proven = bool(
        bundle.status == "proved"
        and candidate.get("shaped_run_authority_proven")
        and candidate_valid
        and ownership_proven
    )

    reasons: list[str] = []
    if not authority_proven:
        if bundle.status != "proved":
            reasons.append("shaped_evidence_bundle_rejected")
        if not candidate.get("row_bands"):
            reasons.append("shaped_row_bands_absent")
        if not candidate.get("run_anchors"):
            reasons.append("shaped_run_anchors_absent")
        if not ownership_proven:
            reasons.append("shaped_component_unowned")
        if not reasons:
            reasons.append(UNTYPED_SHAPED_ABSENCE)

    return {
        "mode": "shaped_runs",
        "authority_proven": authority_proven,
        "candidate_valid": candidate_valid,
        "pitch_proven": bool(periodic.get("pitch_proven")),
        "phase_proven": bool(periodic.get("phase_proven")),
        "ownership_proven": ownership_proven,
        "absence_reasons": tuple(dict.fromkeys(reasons)),
        "unassigned_component_ids": unowned,
        "evidence": "source_raster_run_anchor_ownership",
    }


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

    Mode assignment is lattice-first and proof-carrying:

    1.  Fixed-lattice authority is evaluated first.  When it is proved, the
        decision is ``fixed_lattice`` and no shaped evidence can override it.
    2.  Otherwise the router requires the *absence* of lattice authority to be
        proved as well.  :func:`_lattice_proof` derives at least one reason
        from :data:`LATTICE_ABSENCE_REASONS`, each naming one measurement that
        came out negative.  Only then may a shaped-run authority be admitted.
    3.  If lattice authority is neither proved nor proved-absent, the router
        fails shut with ``unresolved``.  A shaped decision is never a fallback
        for an unexplained lattice failure.

    The four public proof flags mirror the *selected branch's* own evidence.
    They are no longer raised to true merely because a mode was chosen: a
    shaped-run source whose row period cannot be proved reports
    ``pitch_proven`` false while still being a fully proved shaped decision.
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
    lattice_branch = assess_fixed_lattice(bundle.fixed_evidence(), threshold=threshold)
    shaped_branch = assess_shaped_runs(bundle.shaped_evidence(), threshold=threshold)

    # Step 1 -- the lattice branch is proved (or proved absent) before any
    # shaped evidence is allowed to influence the outcome.
    lattice_proof = _lattice_proof(bundle, criterion_threshold=threshold)
    # Step 2 -- the shaped branch is measured, but its admission is gated below.
    shaped_proof = _shaped_run_proof(bundle)

    lattice_authority = bool(lattice_proof["authority_proven"])
    # "Proved absent" means every negative finding was named.  An untyped
    # absence is a hole in the proof, not a licence to route shaped.
    lattice_absence_proven = bool(
        not lattice_authority
        and lattice_proof["absence_reasons"]
        and UNTYPED_LATTICE_ABSENCE not in lattice_proof["absence_reasons"]
    )
    shaped_authority = bool(
        not lattice_authority and lattice_absence_proven and shaped_proof["authority_proven"]
    )
    selected_mode = "fixed_lattice" if lattice_authority else "shaped_runs" if shaped_authority else "unresolved"
    branch_proofs = {"fixed_lattice": lattice_proof, "shaped_runs": shaped_proof}
    selected_proof = branch_proofs.get(selected_mode)
    # The record every consumer can audit: which branch was tried first, what
    # it proved, and -- when it did not prove -- exactly why the shaped branch
    # was allowed to answer instead.
    mode_assignment = {
        "order": ["fixed_lattice", "shaped_runs"],
        "lattice_authority_proven": lattice_authority,
        "lattice_absence_proven": lattice_absence_proven,
        "lattice_absence_reasons": list(lattice_proof["absence_reasons"]),
        "shaped_authority_proven": bool(shaped_proof["authority_proven"]),
        "shaped_admitted": shaped_authority,
        "shaped_absence_reasons": list(shaped_proof["absence_reasons"]),
        "selected_mode": selected_mode,
        "absence_vocabulary": list(LATTICE_ABSENCE_REASONS),
        "transcript_input": False,
    }
    authority_proofs: dict[str, dict[str, Any]] = {}
    for proof, authority, branch in (
        (lattice_branch, lattice_authority, lattice_proof),
        (shaped_branch, shaped_authority, shaped_proof),
    ):
        item = proof.to_dict()
        item["branch_candidate_passed"] = bool(proof.passed)
        item["authority_proven"] = bool(authority)
        item["passed"] = bool(authority)
        # Every alternative now carries its own branch's property proofs and
        # the typed reasons for whatever that branch could not prove.
        item["property_proofs"] = {
            key: bool(branch[key])
            for key in ("candidate_valid", "pitch_proven", "phase_proven", "ownership_proven")
        }
        item["absence_reasons"] = list(branch["absence_reasons"])
        authority_proofs[proof.mode] = item
    rejection_codes: list[str] = []
    if selected_mode == "unresolved":
        rejection_codes.append("geometry_unresolved")
        if not lattice_authority and not lattice_absence_proven:
            rejection_codes.append(UNTYPED_LATTICE_ABSENCE)
        rejection_codes.extend(lattice_proof["absence_reasons"])
        rejection_codes.extend(shaped_proof["absence_reasons"])
        rejection_codes.extend(bundle.rejection_reasons)
        rejection_codes.extend(lattice_branch.rejection_reasons)
        rejection_codes.extend(shaped_branch.rejection_reasons)
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
                "mode_assignment": mode_assignment,
                "branch_proofs": branch_proofs,
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
        confidence=float(
            lattice_branch.score if selected_mode == "fixed_lattice" else shaped_branch.score
        ),
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
            "mode_assignment": mode_assignment,
            "branch_proofs": branch_proofs,
        },
        status="proved",
        rejection_reasons=(),
        # Honest per-property flags: each one mirrors the selected branch's own
        # measurement.  A proved shaped-run decision may legitimately report a
        # false pitch or phase proof, because shaped-run geometry never claims
        # a cell period or origin in the first place.
        candidate_valid=bool(selected_proof["candidate_valid"]),
        pitch_proven=bool(selected_proof["pitch_proven"]),
        phase_proven=bool(selected_proof["phase_proven"]),
        ownership_proven=bool(selected_proof["ownership_proven"]),
    )


# Explicit alias used by command-line/integration callers.
recover_geometry = route_raster_geometry
