"""Raster-derived geometry evidence and shared proof scoring.

The first version of this module accepted scores supplied by callers.  That is
useful for unit-testing the authority router, but it is not a geometry owner:
there is no way for a real screenshot to produce a run strip from those
scores.  The raster entry point below deliberately accepts only a PNG (and a
pinned preprocessing configuration) and computes all evidence from its
pixels.  Transcripts, visual-layout sidecars, and recognizer hints never enter
this module.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import base64
import math
from pathlib import Path
from types import MappingProxyType
from typing import Any, Mapping

import numpy as np
from PIL import Image

from ..components import extract_components
from ..hashing import require_sha256, sha256_bytes, sha256_file
from ..preprocess import build_foreground_alternatives, load_rgb
from ..schema import canonical_bytes


@dataclass(frozen=True)
class GeometryProof:
    mode: str
    criteria: Mapping[str, float]
    score: float
    passed: bool
    rejection_reasons: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "mode": self.mode,
            "criteria": dict(self.criteria),
            "score": self.score,
            "passed": self.passed,
            "rejection_reasons": list(self.rejection_reasons),
        }


@dataclass(frozen=True)
class GeometryEvidenceBundle:
    """Complete geometry evidence recovered from one source raster.

    ``selected_mask`` is intentionally kept out of JSON serialization.  The
    selection recipe and its hash are serialized instead, so a consumer can
    reconstruct it from the source bytes and verify the hash before using it.
    The ndarray is read-only to avoid an in-memory mutation bypassing the
    artifact hash.
    """

    source_sha256: str
    canvas: Mapping[str, int]
    foreground_alternatives: tuple[Mapping[str, Any], ...]
    projection_evidence: Mapping[str, Any]
    row_band_candidates: tuple[Mapping[str, Any], ...]
    baseline_candidates: tuple[Mapping[str, Any], ...]
    fixed_lattice_candidates: tuple[Mapping[str, Any], ...]
    shaped_run_candidates: tuple[Mapping[str, Any], ...]
    component_evidence: Mapping[str, Any]
    selected_foreground: Mapping[str, Any] | None
    selected_mask: np.ndarray | None = field(default=None, repr=False, compare=False)
    configuration: Mapping[str, Any] = field(default_factory=dict)
    status: str = "candidate"
    rejection_reasons: tuple[str, ...] = ()
    output_hash: str = ""

    def __post_init__(self) -> None:
        require_sha256(self.source_sha256, field="source_sha256")
        if self.selected_mask is not None:
            if self.selected_mask.ndim != 2 or self.selected_mask.dtype != np.bool_:
                raise ValueError("selected_mask must be a two-dimensional boolean array")
            mask = np.asarray(self.selected_mask, dtype=bool)
            mask.setflags(write=False)
            object.__setattr__(self, "selected_mask", mask)
        payload = self.to_dict(include_output_hash=False)
        digest = sha256_bytes(canonical_bytes(payload))
        if self.output_hash and self.output_hash != digest:
            raise ValueError("geometry evidence output hash mismatch")
        object.__setattr__(self, "output_hash", digest)

    @property
    def geometry_input_hashes(self) -> dict[str, str]:
        return {
            "source": self.source_sha256,
            "foreground": str(self.projection_evidence.get("selected_mask_sha256", "")),
            "evidence": self.output_hash,
        }

    def to_dict(self, *, include_output_hash: bool = True) -> dict[str, Any]:
        component_payload = dict(self.component_evidence)
        if isinstance(component_payload.get("components"), (list, tuple)):
            component_payload["components"] = [
                item.to_dict() if hasattr(item, "to_dict") else dict(item) if isinstance(item, Mapping) else item
                for item in component_payload["components"]
            ]
        payload: dict[str, Any] = {
            "source_sha256": self.source_sha256,
            "canvas": dict(self.canvas),
            "foreground_alternatives": [dict(item) for item in self.foreground_alternatives],
            "projection_evidence": dict(self.projection_evidence),
            "row_band_candidates": [dict(item) for item in self.row_band_candidates],
            "baseline_candidates": [dict(item) for item in self.baseline_candidates],
            "fixed_lattice_candidates": [dict(item) for item in self.fixed_lattice_candidates],
            "shaped_run_candidates": [dict(item) for item in self.shaped_run_candidates],
            "component_evidence": component_payload,
            "selected_foreground": dict(self.selected_foreground) if self.selected_foreground else None,
            "configuration": dict(self.configuration),
            "status": self.status,
            "rejection_reasons": list(self.rejection_reasons),
        }
        if include_output_hash:
            payload["output_hash"] = self.output_hash
        return payload

    def fixed_evidence(self) -> Mapping[str, Any]:
        candidate = dict(self.fixed_lattice_candidates[0]) if self.fixed_lattice_candidates else {}
        if candidate:
            # Keep branch plausibility and final authority distinct even when
            # this evidence is consumed directly by the legacy proof adapter.
            branch = evaluate_criteria(
                "fixed_lattice",
                candidate,
                (
                    "row_periodicity",
                    "horizontal_advance_stability",
                    "phase_origin_confidence",
                    "fullwidth_multiples",
                    "boundary_intersections",
                    "horizontal_joins_vs_cuts",
                    "negative_origin_clipping",
                    "cross_row_spill",
                    "foreground_alternatives",
                ),
            )
            authority = self.projection_evidence.get("periodic_authority", {})
            authority_proven = bool(
                self.status == "proved"
                and all(bool(authority.get(key)) for key in ("candidate_valid", "pitch_proven", "phase_proven", "ownership_proven"))
            )
            candidate["branch_candidate_passed"] = bool(branch.passed)
            candidate["authority_proven"] = authority_proven
            candidate["passed"] = authority_proven
        return candidate

    def shaped_evidence(self) -> Mapping[str, Any]:
        candidate = self.shaped_run_candidates[0] if self.shaped_run_candidates else {}
        return candidate

    def geometry_mapping(self, mode: str) -> dict[str, Any]:
        """Return the concrete geometry contract consumed by adapters."""

        if mode == "fixed_lattice":
            candidate = dict(self.fixed_evidence())
            authority = dict(self.projection_evidence.get("periodic_authority", {}))
            candidate.update(
                {
                    "mode": mode,
                    "source_sha256": self.source_sha256,
                    "canvas": dict(self.canvas),
                    "geometry_evidence_hash": self.output_hash,
                    "selected_foreground_mask_sha256": self.projection_evidence.get("selected_mask_sha256"),
                    "selected_foreground": dict(self.selected_foreground or {}),
                    "geometry_proven": self.status == "proved" and all(
                        bool(authority.get(key)) for key in ("candidate_valid", "pitch_proven", "phase_proven", "ownership_proven")
                    ),
                    "row_band_quality": dict(self.projection_evidence.get("row_band_quality", {})),
                    "periodic_row_candidates": list(self.projection_evidence.get("periodic_row_candidates", [])),
                    "periodic_authority": authority,
                    "mixed_width_display": dict(self.projection_evidence.get("mixed_width_display", {})),
                }
            )
            return candidate
        if mode == "shaped_runs":
            candidate = dict(self.shaped_evidence())
            candidate.update(
                {
                    "mode": mode,
                    "source_sha256": self.source_sha256,
                    "canvas": dict(self.canvas),
                    "geometry_evidence_hash": self.output_hash,
                    "selected_foreground_mask_sha256": self.projection_evidence.get("selected_mask_sha256"),
                    "selected_foreground": dict(self.selected_foreground or {}),
                    "geometry_proven": self.status == "proved",
                    "periodic_authority": dict(self.projection_evidence.get("periodic_authority", {})),
                }
            )
            return candidate
        return {
            "mode": "unresolved",
            "source_sha256": self.source_sha256,
            "geometry_evidence_hash": self.output_hash,
            "geometry_proven": False,
        }


def _groups(values: np.ndarray, *, merge_gap: int = 0) -> list[tuple[int, int]]:
    """Return half-open groups of true values, optionally merging small gaps."""

    indices = np.flatnonzero(values)
    if len(indices) == 0:
        return []
    groups: list[tuple[int, int]] = []
    start = previous = int(indices[0])
    for value in indices[1:]:
        value = int(value)
        if value - previous > merge_gap + 1:
            groups.append((start, previous + 1))
            start = value
        previous = value
    groups.append((start, previous + 1))
    return groups


def _pack_mask(mask: np.ndarray) -> bytes:
    return np.packbits(mask.astype(bool), axis=None).tobytes()


def _mask_hash(mask: np.ndarray) -> str:
    return sha256_bytes(_pack_mask(mask))


def _autocorrelation(profile: np.ndarray, min_lag: int, max_lag: int) -> list[dict[str, float]]:
    values = np.asarray(profile, dtype=float)
    if values.size < 3:
        return []
    values = values - values.mean()
    denominator = float(np.dot(values, values))
    if denominator <= 1e-12:
        return []
    result: list[dict[str, float]] = []
    upper = min(max_lag, values.size - 1)
    for lag in range(max(1, min_lag), upper + 1):
        score = float(np.dot(values[:-lag], values[lag:]) / denominator)
        result.append({"lag": lag, "score": score})
    return sorted(result, key=lambda item: (-item["score"], item["lag"]))


def _phase_and_boundaries(mask: np.ndarray, advance: float, *, origin_hint: float) -> dict[str, Any]:
    """Find the phase with the least ink at lattice boundaries."""

    width = mask.shape[1]
    integer_advance = max(1, int(round(advance)))
    candidates: list[dict[str, Any]] = []
    # Search one full period around the observed left edge.  The search is in
    # source pixels, not a font metric or a transcript column count.
    start = int(math.floor(origin_hint)) - integer_advance
    for origin in range(start, start + integer_advance * 2 + 1):
        boundaries = list(range(origin, width + integer_advance, integer_advance))
        boundary_pixels = 0
        considered = 0
        for x in boundaries:
            for dx in (-1, 0, 1):
                column = x + dx
                if 0 <= column < width:
                    boundary_pixels += int(mask[:, column].sum())
                    considered += mask.shape[0]
        gutter_score = 1.0 - (boundary_pixels / considered if considered else 1.0)
        candidates.append({"origin_x": origin, "advance_x": float(integer_advance), "gutter_score": max(0.0, gutter_score)})
    candidates.sort(key=lambda item: (-item["gutter_score"], abs(item["origin_x"] - origin_hint), item["origin_x"]))
    return {"selected": candidates[0], "candidates": candidates[: min(8, len(candidates))]}


def _periodic_row_candidates(
    mask: np.ndarray,
    *,
    min_pitch: int,
    max_pitch: int,
    horizontal_advance_hint: float | None = None,
    reference_ink_extent: tuple[int, int] | None = None,
) -> list[dict[str, Any]]:
    """Measure row-pitch/phase alternatives independently of blank gaps.

    Connected vertical strokes make projection groups unsuitable as row
    ownership.  This sweep treats the full ink extent as a periodic lattice
    and records the gutter evidence for every plausible pitch and phase.  It
    is evidence only; callers still need component and ownership proofs before
    promoting one candidate.
    """

    profile = mask.any(axis=1)
    occupied = np.flatnonzero(profile)
    if occupied.size == 0:
        return []
    y0, y1 = int(occupied[0]), int(occupied[-1]) + 1
    height, width = mask.shape
    candidates: list[dict[str, Any]] = []
    vertical_autocorrelation = {
        int(item["lag"]): float(item["score"])
        for item in _autocorrelation(mask.sum(axis=1).astype(float), min_pitch, max_pitch)
    }
    top_clipped = bool(mask[0].any())
    bottom_clipped = bool(mask[-1].any())
    reference_y0, reference_y1 = reference_ink_extent or (y0, y1)
    for pitch in range(max(2, int(min_pitch)), min(int(max_pitch), height) + 1):
        for phase in range(pitch):
            boundaries = list(range(phase, y1 + pitch, pitch))
            boundary_ink = 0
            considered = 0
            for boundary in boundaries:
                for dy in (-1, 0, 1):
                    row = boundary + dy
                    if 0 <= row < height:
                        boundary_ink += int(mask[row].sum())
                        considered += width
            gutter_score = 1.0 - (boundary_ink / considered if considered else 1.0)
            row_bounds: list[list[int]] = []
            baseline_rows: list[int] = []
            nominal_baseline_rows: list[int] = []
            start = phase + ((y0 - phase) // pitch) * pitch
            while start + pitch <= 0:
                start += pitch
            while start < y1:
                end = start + pitch
                if end > y0 and start < y1:
                    clipped_start = max(0, start)
                    clipped_end = min(height, end)
                    row_bounds.append([clipped_start, clipped_end])
                    # A baseline is the nominal row baseline, clipped only by
                    # the observed ink extent.  Do not append y1 as a new
                    # baseline: that creates terminal sliver rows.
                    nominal_baseline_rows.append(end - 1)
                    baseline_rows.append(min(end - 1, y1 - 1))
                start += pitch
            baseline_deltas = [int(next_value - value) for value, next_value in zip(baseline_rows, baseline_rows[1:])]
            baseline_delta_residuals = [int(delta - pitch) for delta in baseline_deltas]
            ownership = _row_ownership_evidence(mask, row_bounds)
            ownership["ownership_geometry_signature"] = sha256_bytes(
                canonical_bytes(
                    {
                        "pitch": int(pitch),
                        "phase": int(phase),
                        "row_bounds": row_bounds,
                    }
                )
            )
            # A seam must be measured on unique raster rows.  The former
            # gutter score counted overlapping three-pixel windows and then
            # mixed that value with autocorrelation; short pitches therefore
            # received credit for repeatedly cutting continuous strokes.  Keep
            # the raw window score as diagnostics, but expose a normalized
            # seam/interior measurement for authority.
            seam_rows = {
                int(boundary + dy)
                for boundary in boundaries
                for dy in (-1, 0, 1)
                if 0 <= boundary + dy < height
            }
            interior_rows = set(range(max(0, y0), min(height, y1))) - seam_rows
            seam_pixels = int(mask[sorted(seam_rows)].sum()) if seam_rows else 0
            interior_pixels = int(mask[sorted(interior_rows)].sum()) if interior_rows else 0
            seam_capacity = max(1, len(seam_rows) * width)
            interior_capacity = max(1, len(interior_rows) * width)
            seam_density = float(seam_pixels / seam_capacity)
            interior_density = float(interior_pixels / interior_capacity)
            normalized_seam_energy = float(seam_pixels / max(1, int(mask.sum())))
            seam_to_interior_contrast = float(
                max(0.0, min(1.0, 1.0 - seam_density / max(interior_density, 1e-9)))
            )
            tolerance = max(1.0, pitch * 0.15)
            partial_edge_rows: list[str] = []
            if row_bounds and row_bounds[0][0] == 0 and phase != row_bounds[0][0]:
                partial_edge_rows.append("initial")
            if row_bounds and row_bounds[-1][1] == height and (row_bounds[-1][0] + pitch) > height:
                partial_edge_rows.append("terminal")
            # Threshold replay may erase antialiased edge pixels.  Use the
            # selected-mask envelope as clipping evidence so that erosion of a
            # real terminal row is not promoted to a new pitch hypothesis.
            reference_initial = int(reference_y0) < int(y0)
            reference_terminal = int(reference_y1) > int(y1)
            clipping_proven = {
                "initial": top_clipped or reference_initial,
                "terminal": bottom_clipped or reference_terminal,
                "reference_ink_extent": [int(reference_y0), int(reference_y1)],
            }
            partial_without_clipping = [edge for edge in partial_edge_rows if not clipping_proven[edge]]
            terminal_sliver_rejected = bool(
                baseline_delta_residuals
                and abs(float(baseline_delta_residuals[-1])) > tolerance
                and not reference_terminal
            )
            initial_sliver_rejected = bool(
                baseline_delta_residuals
                and abs(float(baseline_delta_residuals[0])) > tolerance
                and not reference_initial
            )
            profile_vectors: list[np.ndarray] = []
            for bound_start, bound_end in row_bounds:
                vector = mask[bound_start:bound_end].any(axis=0).astype(float)
                norm = float(np.linalg.norm(vector))
                if norm:
                    profile_vectors.append(vector / norm)
            similarities = [
                float(np.dot(left, right))
                for left, right in zip(profile_vectors, profile_vectors[1:])
            ]
            row_profile_similarity = float(np.mean(similarities)) if similarities else 0.0
            autocorrelation_score = max(
                0.0,
                min(1.0, (vertical_autocorrelation.get(pitch, -1.0) + 1.0) / 2.0),
            )
            full_span_coverage = 1.0 if row_bounds and row_bounds[0][0] <= y0 and row_bounds[-1][1] >= y1 else 0.0
            advance_proximity = (
                max(0.0, 1.0 - abs(float(pitch) - float(horizontal_advance_hint)) / max(1.0, float(horizontal_advance_hint)))
                if horizontal_advance_hint
                else 0.0
            )
            rejection_reasons: list[str] = []
            if terminal_sliver_rejected:
                rejection_reasons.append("terminal_sliver_rejected")
            if initial_sliver_rejected:
                rejection_reasons.append("initial_sliver_rejected")
            if partial_without_clipping:
                rejection_reasons.append("partial_edge_without_clipping_evidence")
            valid = not rejection_reasons
            # Authority score uses only source-period evidence.  Row-profile
            # similarity and horizontal advance remain diagnostic fields; they
            # are intentionally excluded because different text rows need not
            # resemble one another and horizontal glyph advance cannot prove a
            # vertical pitch.
            independent_score = float(
                0.65 * (1.0 - min(1.0, normalized_seam_energy))
                + 0.35 * seam_to_interior_contrast
            )
            diagnostic_score = float(
                0.30 * row_profile_similarity
                + 0.20 * float(gutter_score)
                + 0.15 * autocorrelation_score
                + 0.15 * full_span_coverage
                + 0.20 * advance_proximity
            )
            candidates.append(
                {
                    "pitch": pitch,
                    "phase": phase,
                    "gutter_score": max(0.0, min(1.0, float(gutter_score))),
                    "boundary_ink_pixels": int(boundary_ink),
                    "seam_pixels": seam_pixels,
                    "seam_density": seam_density,
                    "interior_density": interior_density,
                    "normalized_seam_energy": normalized_seam_energy,
                    "seam_to_interior_contrast": seam_to_interior_contrast,
                    "row_count": len(row_bounds),
                    "row_bounds": row_bounds,
                    "baselines": baseline_rows,
                    "nominal_baselines": nominal_baseline_rows,
                    "terminal_baseline_clamped": bool(nominal_baseline_rows and nominal_baseline_rows[-1] != baseline_rows[-1]),
                    "baseline_deltas": baseline_deltas,
                    "baseline_delta_residuals": baseline_delta_residuals,
                    "partial_edge_rows": partial_edge_rows,
                    "clipping_evidence": clipping_proven,
                    "terminal_sliver_rejected": terminal_sliver_rejected,
                    "initial_sliver_rejected": initial_sliver_rejected,
                    "row_profile_similarity": row_profile_similarity,
                    "vertical_autocorrelation": autocorrelation_score,
                    "full_span_coverage": full_span_coverage,
                    "horizontal_advance_reference": horizontal_advance_hint,
                    "advance_proximity": advance_proximity,
                    "independent_score": independent_score,
                    "diagnostic_score": diagnostic_score,
                    "valid": valid,
                    "candidate_valid": valid,
                    "rejection_reasons": rejection_reasons,
                    "ownership": ownership,
                    "ink_extent": [y0, y1],
                    "evidence": "periodic_row_projection",
                }
            )
    candidates.sort(
        key=lambda item: (
            not bool(item["valid"]),
            -float(item["independent_score"]),
            -float(item["gutter_score"]),
            -int(item["row_count"]),
            int(item["pitch"]),
            int(item["phase"]),
        )
    )
    # Retain the complete measured candidate set.  Downstream review surfaces
    # may show the leading candidates, but dropping phases here would hide a
    # one-pixel tie (or a rejected terminal-sliver alternative) from the
    # evidence record.
    return candidates


def _row_ownership_evidence(mask: np.ndarray, row_bounds: list[list[int]]) -> dict[str, Any]:
    """Assign foreground pixels to row intervals without bbox duplication.

    Components may continue across a seam, but a pixel belongs to exactly one
    interval.  The seam contact is retained as explicit continuation evidence;
    it is never converted into a glyph or forced blank.
    """

    height, width = mask.shape
    owners = np.full(height, -1, dtype=np.int32)
    overlap_rows: list[int] = []
    for row_index, (start, end) in enumerate(row_bounds):
        start = max(0, int(start))
        end = min(height, int(end))
        if end <= start:
            continue
        occupied = owners[start:end] >= 0
        overlap_rows.extend((np.flatnonzero(occupied) + start).tolist())
        owners[start:end] = np.where(occupied, -2, row_index)
    unowned = np.argwhere(mask & (owners[:, None] < 0))
    seam_contacts: list[dict[str, int]] = []
    for row_index in range(len(row_bounds) - 1):
        seam = int(row_bounds[row_index][1])
        if 0 < seam < height:
            touching = mask[seam - 1] & mask[seam]
            count = int(touching.sum())
            if count:
                seam_contacts.append({"row_index": row_index, "y": seam, "ink_pixels": count})
    row_pixel_counts = [int(mask[max(0, int(start)):min(height, int(end))].sum()) for start, end in row_bounds]
    signature_payload = {
        "row_pixel_counts": row_pixel_counts,
        "seam_contacts": seam_contacts,
        "unowned_pixels": int(len(unowned)),
        "overlap_rows": sorted(set(int(item) for item in overlap_rows)),
    }
    return {
        "owned_pixel_count": int(mask.sum()) - int(len(unowned)),
        "substantive_pixel_count": int(mask.sum()),
        "unowned_pixel_count": int(len(unowned)),
        "overlap_rows": sorted(set(int(item) for item in overlap_rows)),
        "cross_row_continuations": seam_contacts,
        "ownership_signature": sha256_bytes(canonical_bytes(signature_payload)),
        "ownership_proven": not unowned.size and not overlap_rows,
        "method": "pixel_interval_with_explicit_seam_continuation",
    }


def _periodic_authority_snapshot(
    candidates: list[Mapping[str, Any]],
    *,
    harmonic_margin: float = 0.20,
) -> dict[str, Any]:
    """Rank raster hypotheses without claiming final geometry authority.

    The ordering is deliberately source-only and lexicographic: seam energy is
    primary, seam/interior contrast breaks ties, and autocorrelation is retained
    only as a diagnostic.  A short period is marked as a stroke harmonic when a
    materially cleaner, longer period explains the same ink span.
    """

    valid = [item for item in candidates if bool(item.get("candidate_valid"))]
    families: dict[int, list[Mapping[str, Any]]] = {}
    for item in valid:
        families.setdefault(int(item["pitch"]), []).append(item)

    family_scores: list[dict[str, Any]] = []
    for pitch, family in families.items():
        best = min(
            family,
            key=lambda item: (
                float(item.get("normalized_seam_energy", 1.0)),
                -float(item.get("seam_to_interior_contrast", 0.0)),
                int(item.get("boundary_ink_pixels", 0)),
                int(item.get("phase", 0)),
            ),
        )
        seam_energy = float(best.get("normalized_seam_energy", 1.0))
        family_scores.append(
            {
                "pitch": pitch,
                "score": float(1.0 - min(1.0, seam_energy)),
                "seam_cost": seam_energy,
                "normalized_seam_energy": seam_energy,
                "seam_to_interior_contrast": float(best.get("seam_to_interior_contrast", 0.0)),
                "boundary_ink_pixels": int(best.get("boundary_ink_pixels", 0)),
                "phase_count": len(family),
                "best_phase": int(best.get("phase", 0)),
                "best_candidate_valid": bool(best.get("candidate_valid")),
                "best": best,
                "harmonic_rejected": False,
                "harmonic_parent_pitch": None,
            }
        )

    # Explicitly reject stroke-frequency harmonics.  This is a diagnostic and
    # ranking exclusion only; all original candidates remain in the evidence.
    for item in family_scores:
        pitch = int(item["pitch"])
        for larger in family_scores:
            larger_pitch = int(larger["pitch"])
            if larger_pitch <= pitch or larger_pitch < pitch + 4:
                continue
            improvement = (float(item["seam_cost"]) - float(larger["seam_cost"])) / max(float(item["seam_cost"]), 1e-9)
            if improvement >= harmonic_margin and larger_pitch / max(1.0, pitch) <= 4.0:
                item["harmonic_rejected"] = True
                item["harmonic_parent_pitch"] = larger_pitch
                break

    eligible = [item for item in family_scores if not item["harmonic_rejected"]]
    ranked = sorted(
        eligible or family_scores,
        key=lambda item: (
            float(item["seam_cost"]),
            -float(item["seam_to_interior_contrast"]),
            int(item["pitch"]),
        ),
    )
    top = ranked[0] if ranked else None
    runner_up = ranked[1] if len(ranked) > 1 else None
    pitch_margin = (
        (float(runner_up["seam_cost"]) - float(top["seam_cost"])) / max(float(runner_up["seam_cost"]), 1e-9)
        if top and runner_up else 1.0 if top else 0.0
    )
    winning_pitch = int(top["pitch"]) if top else None
    winning_family = families.get(winning_pitch, []) if winning_pitch is not None else []

    phase_authority_by_pitch: dict[str, dict[str, Any]] = {}
    for pitch, family in sorted(families.items()):
        groups: dict[str, list[Mapping[str, Any]]] = {}
        for item in family:
            signature = str(
                item.get("ownership", {}).get("ownership_geometry_signature")
                or item.get("ownership", {}).get("ownership_signature", "")
            )
            groups.setdefault(signature, []).append(item)
        group_rows: list[dict[str, Any]] = []
        for signature, group in groups.items():
            best_group = min(
                group,
                key=lambda item: (int(item.get("boundary_ink_pixels", 0)), int(item.get("phase", 0))),
            )
            group_rows.append(
                {
                    "ownership_signature": signature,
                    "ownership_geometry_signature": signature,
                    "phases": sorted(int(item.get("phase", 0)) for item in group),
                    "boundary_ink_pixels": int(best_group.get("boundary_ink_pixels", 0)),
                    "normalized_seam_energy": float(best_group.get("normalized_seam_energy", 1.0)),
                }
            )
        group_rows.sort(key=lambda item: (item["boundary_ink_pixels"], item["ownership_signature"]))
        phase_margin = (
            (group_rows[1]["boundary_ink_pixels"] - group_rows[0]["boundary_ink_pixels"])
            / max(group_rows[1]["boundary_ink_pixels"], 1)
            if len(group_rows) > 1 else 1.0 if group_rows else 0.0
        )
        phase_authority_by_pitch[str(pitch)] = {
            "phase_groups": group_rows,
            "phase_group_count": len(group_rows),
            "phase_margin": float(phase_margin),
            "winning_phase_group": group_rows[0]["ownership_signature"] if group_rows else None,
        }
    phase_summary = phase_authority_by_pitch.get(str(winning_pitch), {"phase_groups": [], "phase_group_count": 0, "phase_margin": 0.0, "winning_phase_group": None})
    selected = min(
        winning_family,
        key=lambda item: (
            int(item.get("boundary_ink_pixels", 0)),
            -float(item.get("seam_to_interior_contrast", 0.0)),
            int(item.get("phase", 0)),
        ),
        default=None,
    )
    return {
        "valid": bool(valid),
        "winning_pitch": winning_pitch,
        "winning_phase_group": phase_summary.get("winning_phase_group"),
        "pitch_margin": float(pitch_margin),
        "normalized_pitch_margin": float(pitch_margin),
        "phase_margin": float(phase_summary.get("phase_margin", 0.0)),
        "normalized_phase_margin": float(phase_summary.get("phase_margin", 0.0)),
        "family_scores": [
            {key: value for key, value in item.items() if key != "best"}
            for item in sorted(family_scores, key=lambda item: int(item["pitch"]))
        ],
        "ranked_family_scores": [
            {key: value for key, value in item.items() if key != "best"}
            for item in ranked
        ],
        "phase_authority_by_pitch": phase_authority_by_pitch,
        "winning_candidate": dict(selected) if selected else {},
        "winning_candidate_ownership": dict(selected.get("ownership", {})) if selected else {},
        "ownership_signature": str(selected.get("ownership", {}).get("ownership_signature", "")) if selected else None,
        "ownership_geometry_signature": str(
            selected.get("ownership", {}).get("ownership_geometry_signature", "")
        ) if selected else None,
        "harmonic_rejections": [
            {"pitch": int(item["pitch"]), "parent_pitch": item["harmonic_parent_pitch"]}
            for item in family_scores if item["harmonic_rejected"]
        ],
    }


def _assess_periodic_authority(
    candidates: list[Mapping[str, Any]],
    *,
    row_band_quality: Mapping[str, Any],
    row_band_count: int,
    foreground_stability: Mapping[str, Any] | None = None,
    harmonic_margin: float = 0.20,
    authority_margin: float = 0.10,
) -> dict[str, Any]:
    """Separate candidate validity from pitch, phase, and ownership proof.

    Competing families and phase groups are retained as evidence.  They do not
    invalidate proof by their mere existence; proof requires a pinned source
    margin and replay-stable winning authority.
    """

    snapshot = _periodic_authority_snapshot(candidates, harmonic_margin=harmonic_margin)
    valid = [item for item in candidates if bool(item.get("candidate_valid"))]
    winning = snapshot.get("winning_candidate") or {}
    stability = bool((foreground_stability or {}).get("stable", False))
    same_pitch = (
        not foreground_stability
        or foreground_stability.get("winning_pitch") in {None, snapshot.get("winning_pitch")}
    )
    # Blank-gap grouping is deliberately not part of this proof.  Connected
    # structural art routinely joins several logical rows into one diagnostic
    # band, while the periodic candidate still supplies complete source-span
    # baseline evidence.  Keep the blank-gap result as a warning, but require
    # the winning periodic candidate itself to be complete and replay-stable.
    baseline_proven = bool(
        winning
        and bool(winning.get("candidate_valid"))
        and int(winning.get("row_count", 0)) >= 2
        and float(winning.get("full_span_coverage", 0.0)) >= 1.0
        and not bool(winning.get("terminal_sliver_rejected"))
        and not bool(winning.get("initial_sliver_rejected"))
        and bool(winning.get("ownership", {}).get("ownership_proven"))
        and stability
        and same_pitch
    )
    pitch_proven = bool(
        baseline_proven
        and float(snapshot.get("normalized_pitch_margin", 0.0)) >= authority_margin
        and not any(int(item.get("pitch")) == int(snapshot["winning_pitch"]) for item in snapshot.get("harmonic_rejections", []))
    )
    phase_summary = (snapshot.get("phase_authority_by_pitch") or {}).get(str(snapshot.get("winning_pitch")), {})
    phase_proven = bool(
        pitch_proven
        and phase_summary.get("winning_phase_group")
        and float(phase_summary.get("phase_margin", 0.0)) >= authority_margin
        and stability
        and (foreground_stability or {}).get("winning_phase_group") in {None, phase_summary.get("winning_phase_group")}
    )
    ownership_proven = bool(
        winning
        and winning.get("ownership", {}).get("ownership_proven")
        and pitch_proven
        and phase_proven
    )
    reasons: list[str] = []
    if not snapshot.get("winning_pitch"):
        reasons.append("periodic_pitch_missing")
    if snapshot.get("harmonic_rejections"):
        reasons.append("stroke_harmonics_rejected")
    if not pitch_proven:
        reasons.append("pitch_authority_margin_insufficient")
    if not phase_proven:
        reasons.append("phase_authority_margin_insufficient")
    if not ownership_proven:
        reasons.append("ownership_authority_unresolved")
    family_scores = snapshot.get("family_scores", [])
    harmonic_scores = {
        str(item.get("pitch")): item.get("score")
        for item in family_scores
    }
    return {
        "candidate_valid": bool(valid),
        "pitch_proven": pitch_proven,
        "baseline_proven": baseline_proven,
        "periodic_baselines_proven": baseline_proven,
        "phase_proven": phase_proven,
        "ownership_proven": ownership_proven,
        # Kept as a diagnostic compatibility field only.  A short blank-gap
        # result is never sufficient to prove a lattice.
        "compact_authority": False,
        "winning_pitch": snapshot.get("winning_pitch"),
        "pitch_margin": float(snapshot.get("pitch_margin", 0.0)),
        "normalized_pitch_margin": float(snapshot.get("normalized_pitch_margin", 0.0)),
        "phase_margin": float(phase_summary.get("phase_margin", 0.0)),
        "normalized_phase_margin": float(phase_summary.get("phase_margin", 0.0)),
        "family_scores": family_scores,
        "ranked_family_scores": snapshot.get("ranked_family_scores", []),
        "harmonic_family_scores": harmonic_scores,
        "harmonic_rejections": snapshot.get("harmonic_rejections", []),
        "phase_groups": phase_summary.get("phase_groups", []),
        "phase_group_count": int(phase_summary.get("phase_group_count", 0)),
        "winning_phase_group": phase_summary.get("winning_phase_group"),
        "phase_authority_by_pitch": snapshot.get("phase_authority_by_pitch", {}),
        "winning_candidate_ownership": dict(winning.get("ownership", {})) if winning else {},
        "ownership_signature": snapshot.get("ownership_signature"),
        "ownership_method": "pixel_interval_with_explicit_seam_continuation",
        "authority_reasons": reasons,
        "foreground_stability": dict(foreground_stability or {}),
    }


def _assess_fixed_lattice_authority(
    candidate: Mapping[str, Any] | None,
    periodic_authority: Mapping[str, Any],
    *,
    row_band_quality: Mapping[str, Any],
    foreground_stability: Mapping[str, Any],
    criterion_threshold: float = 0.8,
) -> dict[str, Any]:
    """Prove a fixed lattice from one concrete raster candidate.

    Branch plausibility remains diagnostic.  This owner accepts either a
    complete periodic proof or a regular, source-measured lattice candidate
    whose baselines, seams, and exactly-once ownership agree.  Blank-gap band
    count alone is never sufficient; it is only used to reject an explicitly
    undersegmented candidate.
    """

    item = dict(candidate or {})
    criteria = dict(item.get("criteria") or {})
    baselines = [float(entry.get("baseline", 0.0)) for entry in item.get("baselines", ())]
    deltas = [next_value - value for value, next_value in zip(baselines, baselines[1:])]
    regular = False
    if deltas:
        expected_pitch = float(item.get("line_height", np.median(deltas)))
        # Edge rows can be clipped by a pixel or two.  Compare against the
        # measured lattice advance rather than requiring every baseline delta
        # to equal the rounded raster distance exactly.
        regular = max(abs(delta - expected_pitch) for delta in deltas) <= 2.0
    ownership = dict(periodic_authority.get("winning_candidate_ownership") or {})
    ownership_complete = bool(
        ownership.get("ownership_proven")
        and int(ownership.get("unowned_pixel_count", 0)) == 0
        and not ownership.get("overlap_rows")
    )
    branch_measures = (
        float(criteria.get("row_periodicity", 0.0)),
        float(criteria.get("phase_origin_confidence", 0.0)),
        float(criteria.get("boundary_intersections", 0.0)),
        float(criteria.get("cross_row_spill", 0.0)),
    )
    measured_lattice = bool(
        item.get("geometry_proof") == "raster_measured"
        and int(item.get("rows", 0)) >= 2
        and regular
        and not bool(row_band_quality.get("undersegmented"))
        and all(value >= criterion_threshold for value in branch_measures)
        and ownership_complete
        and bool(foreground_stability.get("stable"))
    )
    periodic_complete = bool(
        periodic_authority.get("candidate_valid")
        and periodic_authority.get("pitch_proven")
        and periodic_authority.get("phase_proven")
        and periodic_authority.get("ownership_proven")
        and (
            not bool(row_band_quality.get("undersegmented"))
            or not bool(ownership.get("cross_row_continuations"))
        )
    )
    proven = bool(periodic_complete or measured_lattice)
    return {
        "proven": proven,
        "periodic_complete": periodic_complete,
        "measured_lattice": measured_lattice,
        "baseline_regular": regular,
        "ownership_complete": ownership_complete,
        "criterion_values": {
            "row_periodicity": branch_measures[0],
            "phase_origin_confidence": branch_measures[1],
            "boundary_intersections": branch_measures[2],
            "cross_row_spill": branch_measures[3],
        },
    }


def _run_anchors(mask: np.ndarray, row_bands: list[Mapping[str, Any]], *, merge_gap: int) -> list[dict[str, Any]]:
    anchors: list[dict[str, Any]] = []
    for row in row_bands:
        row_index = int(row["row_index"])
        y0, y1 = int(row["y0"]), int(row["y1"])
        profile = mask[y0:y1].any(axis=0)
        groups = _groups(profile, merge_gap=merge_gap)
        for run_index, (x0, x1) in enumerate(groups):
            if x1 <= x0:
                continue
            anchors.append(
                {
                    "run_id": f"r{row_index:03d}-{run_index:03d}",
                    "row_index": row_index,
                    "x0": x0,
                    "x1": x1,
                    "start_x": x0,
                    "end_x": x1,
                    "y0": y0,
                    "y1": y1,
                    "baseline": float(row["baseline"]),
                    "direction": "ltr",
                    "advance": float(x1 - x0),
                    "ink_pixels": int(mask[y0:y1, x0:x1].sum()),
                }
            )
    return anchors


def _foreground_score(mask: np.ndarray, *, height: int, width: int) -> float:
    ink_ratio = float(mask.mean()) if mask.size else 0.0
    if ink_ratio <= 0.0001 or ink_ratio >= 0.65:
        return 0.0
    row_groups = _groups(mask.any(axis=1), merge_gap=3)
    if not row_groups:
        return 0.0
    density = 1.0 - min(1.0, abs(ink_ratio - 0.05) / 0.25)
    band_shape = min(1.0, len(row_groups) / max(1.0, height / 2.0))
    # A light-background raster can contain broad, saturated glyphs (notably
    # colour emoji) whose occupied ratio is much higher than monochrome ASCII.
    # The border is still expected to be background.  Measuring that border
    # evidence prevents the all-pixels mask produced by the wrong black
    # background from tying the real foreground selection.
    border = np.concatenate(
        (
            mask[0, :],
            mask[-1, :],
            mask[:, 0],
            mask[:, -1],
        )
    ) if mask.size else np.asarray([], dtype=bool)
    border_score = 1.0 - min(1.0, float(border.mean()) * 4.0) if border.size else 0.0
    return max(0.0, min(1.0, 0.50 * density + 0.25 * band_shape + 0.25 * border_score))


def _horizontal_join_mask(mask: np.ndarray, *, minimum_run: int = 8, maximum_vertical_run: int = 4) -> np.ndarray:
    """Mark short vertical pixels embedded in long horizontal joins.

    Mixed-width display cells may share a horizontal stroke at a glyph boundary;
    those pixels are diagnostic rather than proof that a base-unit seam is
    wrong.  The mask is source-derived and never labels a character.
    """

    horizontal = np.zeros_like(mask, dtype=bool)
    for row in range(mask.shape[0]):
        xs = np.flatnonzero(mask[row])
        if not len(xs):
            continue
        starts = np.r_[0, np.flatnonzero(np.diff(xs) > 1) + 1]
        ends = np.r_[starts[1:] - 1, len(xs) - 1]
        for start, end in zip(starts, ends):
            if int(xs[end] - xs[start] + 1) >= minimum_run:
                horizontal[row, xs[start] : xs[end] + 1] = True
    vertical_short = np.zeros_like(mask, dtype=bool)
    for column in range(mask.shape[1]):
        ys = np.flatnonzero(mask[:, column])
        if not len(ys):
            continue
        starts = np.r_[0, np.flatnonzero(np.diff(ys) > 1) + 1]
        ends = np.r_[starts[1:] - 1, len(ys) - 1]
        for start, end in zip(starts, ends):
            if int(ys[end] - ys[start] + 1) <= maximum_vertical_run:
                vertical_short[ys[start] : ys[end] + 1, column] = True
    return mask & horizontal & vertical_short


def _measure_mixed_width_display(mask: np.ndarray, *, minimum: float = 9.0, maximum: float = 16.0) -> dict[str, Any]:
    """Recover a narrow display unit without forcing a uniform cell lattice.

    The result is an anchor measurement: wide CJK graphemes may span two base
    units, ambiguous-width characters retain alternatives, and no character
    identity is inferred here.
    """

    nonhorizontal = mask & ~_horizontal_join_mask(mask)
    best: tuple[tuple[float, ...], dict[str, Any]] | None = None
    for period_index in range(int(round(minimum * 20)), int(round(maximum * 20)) + 1):
        period = period_index / 20.0
        for phase_index in range(int(round(period * 20))):
            phase = phase_index / 20.0
            # Keep the phase in the canonical [0, period) interval.  The
            # boundary columns are unchanged, but a negative equivalent
            # origin shifts logical column numbering and can split one
            # full-width horizontal glyph into two artificial tokens.
            origin = phase % period
            positions: list[int] = []
            cursor = origin
            while cursor < mask.shape[1] + period:
                rounded = round(cursor)
                if 0 <= rounded < mask.shape[1] and (not positions or rounded != positions[-1]):
                    positions.append(rounded)
                cursor += period
            values = [int(mask[:, column].sum()) for column in positions]
            nonhorizontal_values = [int(nonhorizontal[:, column].sum()) for column in positions]
            total = int(sum(values))
            nonhorizontal_total = int(sum(nonhorizontal_values))
            key = (
                float(nonhorizontal_total),
                float(max(nonhorizontal_values) if nonhorizontal_values else 0),
                float(sum(value > 0 for value in nonhorizontal_values)),
                float(total),
                float(max(values) if values else 0),
                float(sum(value > 0 for value in values)),
                period,
            )
            candidate = {
                "mode": "mixed_width_display",
                "base_advance_px": period,
                "phase_px_mod_period": phase,
                "origin_px": origin,
                # Phase identifies boundary placement modulo one narrow unit;
                # it does not identify the logical column zero.  Preserve a
                # bounded set of equivalent origins so joint geometry/text
                # scoring can recover leading indentation without consulting
                # a transcript or fixture metadata.
                "origin_candidates_px": [
                    float(phase + shift * period)
                    for shift in (-1, 0, -2, 1, -3)
                ],
                "boundary_columns_px": positions,
                "boundary_ink_total": total,
                "boundary_ink_nonhorizontal_total": nonhorizontal_total,
                "boundary_ink_nonhorizontal_max": max(nonhorizontal_values) if nonhorizontal_values else 0,
                "boundary_columns_with_nonhorizontal_ink": sum(value > 0 for value in nonhorizontal_values),
                "wide_span_units": 2,
                "width_classes": {"narrow": 1, "wide": 2, "ambiguous": "profile_required"},
                "authority": "anchor_evidence_only",
            }
            if best is None or key < best[0]:
                best = (key, candidate)
    if best:
        measured = dict(best[1])
        selected_advance = float(measured.get("base_advance_px", 0.0))
        # Retain the strongest harmonic family as proposal evidence.  A
        # half-period is common when a wide East-Asian glyph spans two narrow
        # units; it must be compared downstream rather than silently rejected
        # by the first seam-cost winner.
        harmonic_advances = [selected_advance]
        half = selected_advance / 2.0
        if half >= max(1.0, float(minimum) / 2.0):
            harmonic_advances.append(half)
        measured["base_advance_candidates_px"] = [
            float(value) for value in dict.fromkeys(round(value, 4) for value in harmonic_advances)
        ]
        origin = float(measured.get("origin_px", 0.0))
        origin_candidates = tuple(float(value) for value in measured.get("origin_candidates_px", (origin,)))
        measured["base_origin_candidates_px"] = {
            str(round(advance, 4)): [
                float(value)
                for value in dict.fromkeys(
                    round(origin + shift * advance, 4)
                    for shift in (-1, 0, 1, -2, 2)
                )
            ]
            for advance in measured["base_advance_candidates_px"]
        }
        # Preserve the seam-derived alternatives for the selected base.  The
        # mapping is the proposal contract; callers must not infer a base from
        # the candidate list's order alone.
        measured["base_origin_candidates_px"][str(round(selected_advance, 4))] = list(origin_candidates)
        return measured
    return {
        "mode": "mixed_width_display",
        "authority": "unresolved",
        "width_classes": {"narrow": 1, "wide": 2, "ambiguous": "profile_required"},
    }


def _candidate_mask_from_pixels(pixels: np.ndarray, *, configuration: Mapping[str, Any]) -> tuple[dict[str, Any], ...]:
    backgrounds = configuration.get("backgrounds", ((255, 255, 255), (0, 0, 0)))
    thresholds = configuration.get("foreground_thresholds", (12, 25, 50))
    alternatives = build_foreground_alternatives(pixels, backgrounds=backgrounds, thresholds=thresholds)
    scored: list[dict[str, Any]] = []
    for item in alternatives:
        mask = item["mask"]
        scored.append(
            {
                **{key: value for key, value in item.items() if key != "mask"},
                "raster_score": _foreground_score(mask, height=mask.shape[0], width=mask.shape[1]),
            }
        )
    return tuple(scored)


def build_geometry_evidence(
    source_path: str | Path,
    *,
    expected_sha256: str | None = None,
    configuration: Mapping[str, Any] | None = None,
) -> GeometryEvidenceBundle:
    """Recover geometry candidates from source pixels only.

    This function does not inspect any corpus metadata.  A source with no
    defensible foreground or with tied foreground candidates is rejected before
    either recognizer or component extraction can run.
    """

    configuration = {
        "foreground_thresholds": (12, 25, 50),
        "backgrounds": ((255, 255, 255), (0, 0, 0)),
        "max_row_gap": 3,
        "run_merge_gap": 4,
        "min_horizontal_advance": 5,
        "max_horizontal_advance": 32,
        "mixed_width_min_advance": 9.0,
        "mixed_width_max_advance": 16.0,
        "min_vertical_pitch": 8,
        "max_vertical_pitch": 32,
        "foreground_margin": 0.03,
        "geometry_margin": 0.12,
        "periodic_authority_margin": 0.10,
        "harmonic_rejection_margin": 0.20,
        # A single blank-gap group cannot stand in for many periodic text
        # rows.  This is deliberately a fail-closed gate: sources with
        # vertically connected art need a baseline model, not a larger band.
        "row_band_max_height_ratio": 3.0,
        "row_band_max_height_pixels": 48,
        **dict(configuration or {}),
    }
    pixels, source_hash = load_rgb(source_path, expected_sha256=expected_sha256)
    height, width = pixels.shape[:2]
    alternatives = _candidate_mask_from_pixels(pixels, configuration=configuration)
    ranked = sorted(alternatives, key=lambda item: (-float(item["raster_score"]), item["mask_sha256"]))
    rejection: list[str] = []
    selected_meta: dict[str, Any] | None = None
    selected_mask: np.ndarray | None = None
    if not ranked or ranked[0]["raster_score"] <= 0:
        rejection.append("foreground_unresolved")
    else:
        # Equal masks at multiple thresholds are one evidence candidate, not a
        # false ambiguity.  Distinct masks must clear a pinned score margin.
        # Thresholds are a pinned sensitivity sweep over the same inferred
        # background; they are not independent foreground hypotheses.  Only
        # competing backgrounds can make foreground selection ambiguous.
        best_by_background: dict[tuple[int, int, int], dict[str, Any]] = {}
        for item in ranked:
            key = tuple(int(value) for value in item["background_rgb"])
            best_by_background.setdefault(key, item)
        background_candidates = sorted(best_by_background.values(), key=lambda item: (-float(item["raster_score"]), item["mask_sha256"]))
        if len(background_candidates) > 1 and float(background_candidates[0]["raster_score"]) - float(background_candidates[1]["raster_score"]) < float(configuration["foreground_margin"]):
            rejection.append("foreground_ambiguous")
        else:
            selected_meta = dict(ranked[0])
            # Rebuild the mask from its pinned recipe rather than retaining a
            # caller-provided array.
            distance = np.max(np.abs(pixels.astype(np.int16) - np.asarray(selected_meta["background_rgb"], dtype=np.int16)), axis=2)
            selected_mask = distance > int(selected_meta["threshold"])
            selected_mask.setflags(write=False)
            if _mask_hash(selected_mask) != selected_meta["mask_sha256"]:
                raise ValueError("selected foreground mask hash mismatch")

    projection = selected_mask if selected_mask is not None else np.zeros((height, width), dtype=bool)
    mixed_width_display = _measure_mixed_width_display(
        projection,
        minimum=float(configuration["mixed_width_min_advance"]),
        maximum=float(configuration["mixed_width_max_advance"]),
    ) if selected_mask is not None else {"mode": "mixed_width_display", "authority": "unresolved"}
    row_projection = projection.sum(axis=1).astype(int)
    column_projection = projection.sum(axis=0).astype(int)
    row_bands_raw = _groups(row_projection > 0, merge_gap=int(configuration["max_row_gap"]))
    row_bands = [
        {
            "row_index": index,
            "y0": y0,
            "y1": y1,
            "baseline": float(y1 - 1),
            "ink_pixels": int(projection[y0:y1].sum()),
            "confidence": 1.0 if y1 > y0 else 0.0,
        }
        for index, (y0, y1) in enumerate(row_bands_raw)
    ]
    band_heights = [int(item["y1"] - item["y0"]) for item in row_bands]
    reference_height = float(np.median(band_heights)) if band_heights else 0.0
    largest_height = max(band_heights, default=0)
    largest_index = int(np.argmax(band_heights)) if band_heights else None
    undersegmented = bool(
        len(row_bands) >= 3
        and largest_height >= int(configuration["row_band_max_height_pixels"])
        and reference_height > 0
        and largest_height / reference_height >= float(configuration["row_band_max_height_ratio"])
    )
    row_band_quality = {
        "method": "blank_gap_groups_with_outlier_gate",
        "band_heights": band_heights,
        "reference_height": reference_height,
        "largest_height": largest_height,
        "largest_band_index": largest_index,
        "undersegmented": undersegmented,
        # This is filled by the independent periodic authority below.  The
        # blank-gap detector cannot prove or disprove a connected-art lattice.
        "periodic_baselines_proven": False,
        "rejection_reason": "row_baselines_undersegmented" if undersegmented else None,
    }
    baselines = [
        {"row_index": item["row_index"], "baseline": item["baseline"], "confidence": item["confidence"]}
        for item in row_bands
    ]
    min_lag = int(configuration["min_horizontal_advance"])
    max_lag = min(int(configuration["max_horizontal_advance"]), max(1, width - 1))
    autocorrelation = _autocorrelation(column_projection, min_lag, max_lag)
    x_groups = _groups(column_projection > 0, merge_gap=0)
    x_origin_hint = float(x_groups[0][0] if x_groups else 0)
    lattice_candidates: list[dict[str, Any]] = []
    ink_ratio = float(projection.mean()) if projection.size else 0.0
    occupied_x = (max((group[1] for group in x_groups), default=0) - min((group[0] for group in x_groups), default=0))
    # Sparse multiline art is the characteristic raster evidence for fixed
    # cell drawings (and is deliberately measured, not read from a fixture
    # mode).  Dense or single-band text remains a shaped-run candidate unless
    # its lattice proof independently dominates.
    sparse_multiline = bool(
        len(row_bands) >= 2
        and ink_ratio < 0.06
        and occupied_x > 0
        and occupied_x <= width * 0.65
    )
    if selected_mask is not None and autocorrelation:
        for correlation in autocorrelation[:8]:
            advance = float(correlation["lag"])
            phase = _phase_and_boundaries(selected_mask, advance, origin_hint=x_origin_hint)
            selected_phase = phase["selected"]
            gutter_score = float(selected_phase["gutter_score"])
            periodicity = max(0.0, min(1.0, (float(correlation["score"]) + 1.0) / 2.0))
            fixed_score = max(0.0, min(1.0, 0.48 * periodicity + 0.52 * gutter_score))
            row_regular = 1.0
            if len(row_bands) > 2:
                starts = np.asarray([item["y0"] for item in row_bands], dtype=float)
                gaps = np.diff(starts)
                row_regular = max(0.0, 1.0 - float(np.std(gaps)) / max(1.0, float(np.mean(gaps))))
            # These are measured scores, not sparse-art heuristics.  A
            # periodic autocorrelation peak is useful only in combination with
            # the candidate's gutter placement; continuous strokes can produce
            # a strong peak at the wrong harmonic.  The mixed-width probe is a
            # separate horizontal measurement, so a candidate advance that
            # disagrees with it loses fullwidth evidence instead of being
            # promoted by the same sparse-multiline flag.
            stability = max(0.0, min(1.0, 0.50 * periodicity + 0.50 * gutter_score))
            mixed_base = float(mixed_width_display.get("base_advance_px", 0.0))
            if mixed_base > 0.0:
                fullwidth = max(
                    0.0,
                    min(1.0, 1.0 - abs(advance - mixed_base) / max(advance, mixed_base)),
                )
            else:
                fullwidth = 0.0
            origin = int(selected_phase["origin_x"])
            columns = max(1, int(math.ceil((width - origin) / advance)))
            cells = [
                {
                    "row": int(row["row_index"]),
                    "column": column,
                    "x0": origin + int(round(column * advance)),
                    "x1": origin + int(round((column + 1) * advance)),
                    "y0": int(row["y0"]),
                    "y1": int(row["y1"]),
                }
                for row in row_bands
                for column in range(columns)
            ]
            lattice_candidates.append(
                {
                    "mode": "fixed_lattice",
                    "criteria": {
                        # One isolated row has no periodic evidence.  It may
                        # still be a shaped run, but it cannot prove a fixed
                        # lattice from a self-comparison of one band.
                        "row_periodicity": max(0.0, min(1.0, row_regular if len(row_bands) >= 2 else 0.0)),
                        "horizontal_advance_stability": stability,
                        "phase_origin_confidence": gutter_score,
                        "fullwidth_multiples": fullwidth,
                        "boundary_intersections": gutter_score,
                        "horizontal_joins_vs_cuts": gutter_score,
                        "negative_origin_clipping": 1.0 if origin >= 0 else 0.85,
                        "cross_row_spill": 1.0,
                        "foreground_alternatives": 1.0,
                    },
                    "score": fixed_score,
                    "origin_x": origin,
                    "origin_y": float(row_bands[0]["y0"] if row_bands else 0),
                    "advance_x": advance,
                    "line_height": float(np.median(np.diff([item["y0"] for item in row_bands])) if len(row_bands) > 1 else max(1, (row_bands[0]["y1"] - row_bands[0]["y0"]) if row_bands else 1)),
                    "phase": [origin % max(1, int(round(advance))), 0],
                    "rows": len(row_bands),
                    "columns": columns,
                    "row_bands": row_bands,
                    "baselines": baselines,
                    "row_bounds": [[int(row["y0"]), int(row["y1"])] for row in row_bands],
                    "cells": cells,
                    "boundary_intersections": int(round((1.0 - gutter_score) * width * max(1, len(row_bands)))),
                    "autocorrelation": correlation,
                    "geometry_proof": "raster_measured",
                }
            )
    lattice_candidates.sort(key=lambda item: (-float(item["score"]), item["advance_x"], item["origin_x"]))
    if lattice_candidates:
        lattice_candidates = lattice_candidates[:8]

    periodic_row_candidates = _periodic_row_candidates(
        projection,
        min_pitch=int(configuration["min_vertical_pitch"]),
        max_pitch=int(configuration["max_vertical_pitch"]),
        horizontal_advance_hint=(float(lattice_candidates[0]["advance_x"]) if lattice_candidates else None),
    )
    # Blank-gap groups remain diagnostic evidence only.  For connected art,
    # derive a candidate line lattice from the source-period seam ranking so
    # downstream overlays and proposal strips cover the actual visual rows.
    periodic_snapshot = _periodic_authority_snapshot(
        periodic_row_candidates,
        harmonic_margin=float(configuration["harmonic_rejection_margin"]),
    )
    baseline_candidate = periodic_snapshot.get("winning_candidate") or {}
    baseline_row_bands = [
        {
            "row_index": index,
            "y0": int(bounds[0]),
            "y1": int(bounds[1]),
            "baseline": float(int(bounds[1]) - 1),
            "ink_pixels": int(projection[int(bounds[0]):int(bounds[1])].sum()),
            "confidence": 0.0,
            "source": "periodic_baseline_candidate",
        }
        for index, bounds in enumerate(baseline_candidate.get("row_bounds", ()))
    ]
    if undersegmented and len(baseline_row_bands) > len(row_bands):
        row_band_quality = {
            **row_band_quality,
            "blank_gap_row_bands": [dict(item) for item in row_bands],
            "method": "periodic_baseline_candidate_with_blank_gap_diagnostic",
            "periodic_candidate_pitch": baseline_candidate.get("pitch"),
            "periodic_candidate_phase": baseline_candidate.get("phase"),
            "periodic_candidate_rows": len(baseline_row_bands),
            "periodic_baselines_proven": False,
        }
        row_bands = baseline_row_bands
        baselines = [
            {"row_index": item["row_index"], "baseline": item["baseline"], "confidence": item["confidence"]}
            for item in row_bands
        ]
    threshold_pitch_families: list[dict[str, Any]] = []
    seen_recipes: set[tuple[tuple[int, int, int], int]] = set()
    selected_background = tuple(int(value) for value in selected_meta["background_rgb"]) if selected_meta else None
    selected_occupied_rows = np.flatnonzero(selected_mask.any(axis=1)) if selected_mask is not None else np.asarray([], dtype=int)
    selected_ink_extent = (
        (int(selected_occupied_rows[0]), int(selected_occupied_rows[-1]) + 1)
        if len(selected_occupied_rows)
        else None
    )
    # Threshold replay is a sensitivity check for the selected foreground
    # family, not a vote between complementary black/white interpretations.
    # Complementary backgrounds are retained in foreground_alternatives but
    # cannot manufacture stability here.
    for alternative in ranked:
        recipe = (tuple(int(value) for value in alternative["background_rgb"]), int(alternative["threshold"]))
        if selected_background is None or recipe[0] != selected_background:
            continue
        # A complementary/all-pixels mask is not a retained foreground
        # threshold.  Feeding it into the replay creates a spurious winning
        # pitch and makes a real source appear unstable.  The selected
        # foreground family is replayed only for masks that remain a valid
        # foreground candidate under the same raster score gate.
        if float(alternative.get("raster_score", 0.0)) <= 0.0:
            continue
        if recipe in seen_recipes:
            continue
        seen_recipes.add(recipe)
        distance = np.max(np.abs(pixels.astype(np.int16) - np.asarray(recipe[0], dtype=np.int16)), axis=2)
        alternative_mask = distance > recipe[1]
        alternative_candidates = _periodic_row_candidates(
            alternative_mask,
            min_pitch=int(configuration["min_vertical_pitch"]),
            max_pitch=int(configuration["max_vertical_pitch"]),
            horizontal_advance_hint=None,
            reference_ink_extent=selected_ink_extent,
        )
        snapshot = _periodic_authority_snapshot(
            alternative_candidates,
            harmonic_margin=float(configuration["harmonic_rejection_margin"]),
        )
        threshold_pitch_families.append(
            {
                "background_rgb": list(recipe[0]),
                "threshold": recipe[1],
                "valid_pitches": sorted({int(item["pitch"]) for item in alternative_candidates if item.get("candidate_valid")}),
                "winning_pitch": snapshot.get("winning_pitch"),
                "winning_phase": (snapshot.get("winning_candidate") or {}).get("phase"),
                "winning_phase_group": snapshot.get("winning_phase_group"),
                "normalized_pitch_margin": snapshot.get("normalized_pitch_margin", 0.0),
                "normalized_phase_margin": snapshot.get("normalized_phase_margin", 0.0),
                "ownership_signature": snapshot.get("ownership_signature"),
                "ownership_geometry_signature": snapshot.get("ownership_geometry_signature"),
                "cross_row_indices": sorted({
                    int(item.get("row_index"))
                    for item in (snapshot.get("winning_candidate") or {}).get("ownership", {}).get("cross_row_continuations", [])
                    if item.get("row_index") is not None
                }),
                "harmonic_rejections": snapshot.get("harmonic_rejections", []),
            }
        )
    authority_snapshots = [
        (
            item.get("winning_pitch"),
            item.get("winning_phase"),
            tuple(item.get("cross_row_indices", ())),
        )
        for item in threshold_pitch_families
    ]
    snapshot_stable = False
    if authority_snapshots:
        reference_pitch, reference_phase, reference_cross_rows = authority_snapshots[0]
        phase_tolerance = 1
        snapshot_stable = all(
            item[0] == reference_pitch
            and item[1] is not None
            and reference_phase is not None
            and abs(int(item[1]) - int(reference_phase)) <= phase_tolerance
            and len(set(item[2]).symmetric_difference(reference_cross_rows)) <= 1
            for item in authority_snapshots
        )
    family_sets = {tuple(item["valid_pitches"]) for item in threshold_pitch_families}
    foreground_stability = {
        "method": "retained_foreground_threshold_periodic_replay",
        "stable": snapshot_stable,
        "retained_thresholds": threshold_pitch_families,
        "family_count": len(family_sets),
        "selected_background_rgb": list(selected_background) if selected_background is not None else None,
        "winning_pitch": authority_snapshots[0][0] if snapshot_stable else None,
        "winning_phase_group": threshold_pitch_families[0].get("winning_phase_group") if snapshot_stable else None,
        "normalized_pitch_margin": threshold_pitch_families[0].get("normalized_pitch_margin") if snapshot_stable else None,
        "normalized_phase_margin": threshold_pitch_families[0].get("normalized_phase_margin") if snapshot_stable else None,
        "ownership_signature": threshold_pitch_families[0].get("ownership_signature") if snapshot_stable else None,
        "ownership_geometry_signature": threshold_pitch_families[0].get("ownership_geometry_signature") if snapshot_stable else None,
    }

    periodic_authority = _assess_periodic_authority(
        periodic_row_candidates,
        row_band_quality=row_band_quality,
        row_band_count=len(row_bands),
        foreground_stability=foreground_stability,
        harmonic_margin=float(configuration["harmonic_rejection_margin"]),
        authority_margin=float(configuration["periodic_authority_margin"]),
    )
    fixed_authority = _assess_fixed_lattice_authority(
        lattice_candidates[0] if lattice_candidates else None,
        periodic_authority,
        row_band_quality=row_band_quality,
        foreground_stability=foreground_stability,
        criterion_threshold=float(configuration["criterion_threshold"])
        if "criterion_threshold" in configuration
        else 0.8,
    )
    if fixed_authority["proven"]:
        # The concrete fixed-lattice owner is authoritative even when the
        # legacy branch score is below threshold (for example, one connected
        # multiline ASCII drawing).  Preserve the raw periodic diagnostics,
        # but expose one coherent proof surface to every consumer.
        periodic_authority = {
            **periodic_authority,
            "pitch_proven": True,
            "phase_proven": True,
            "ownership_proven": True,
            "baseline_proven": True,
            "periodic_baselines_proven": True,
            "fixed_lattice_authority_proven": True,
            "fixed_lattice_authority": fixed_authority,
        }
    else:
        periodic_authority = {
            **periodic_authority,
            "fixed_lattice_authority_proven": False,
            "fixed_lattice_authority": fixed_authority,
        }
    run_anchors = _run_anchors(projection, row_bands, merge_gap=int(configuration["run_merge_gap"])) if selected_mask is not None else []
    shaped_score = 0.0
    anchor_advances = [float(anchor.get("advance", 0.0)) for anchor in run_anchors if float(anchor.get("advance", 0.0)) > 0.0]
    if len(anchor_advances) >= 2:
        advance_mean = float(np.mean(anchor_advances))
        advance_cv = float(np.std(anchor_advances) / max(1e-9, advance_mean))
    else:
        advance_cv = 0.0
    # A single row with multiple independently measured spans is the common
    # shaped-run case (including a joined emoji cluster).  For multiline
    # material, variance is only evidence when it is measured across enough
    # anchors; sparse multiline status itself never changes this value.
    if len(row_bands) == 1 and len(anchor_advances) >= 2:
        variable_advance_score = max(0.0, min(1.0, 0.80 + advance_cv))
    else:
        variable_advance_score = max(0.0, min(1.0, 0.35 + 0.50 * advance_cv))
    if row_bands and run_anchors and selected_mask is not None:
        cross_row_continuations = any(
            bool(item.get("ownership", {}).get("cross_row_continuations"))
            for item in periodic_row_candidates
            if bool(item.get("candidate_valid"))
        )
        periodic_ready = all(
            bool(periodic_authority.get(key))
            for key in ("candidate_valid", "phase_proven", "ownership_proven")
        ) and not (undersegmented and cross_row_continuations)
        # A periodic row detector may supply useful shaped-run candidates, but
        # an undersegmented connected drawing cannot pass shaped authority
        # until the same source evidence proves phase and one-owner-per-pixel
        # relationships.  This is an ownership gate, not a sparse-art score.
        connected = (
            min(1.0, len(run_anchors) / max(1, len(row_bands)))
            if (not undersegmented or periodic_ready)
            else 0.35
        )
        shaped_score = float(np.mean([1.0, variable_advance_score, connected, 1.0, 1.0]))
    shaped_candidate = {
        "mode": "shaped_runs",
        "criteria": {
            "row_bands_baselines": 1.0 if row_bands else 0.0,
            "variable_advances": variable_advance_score,
            "connected_joined_runs": connected if row_bands and run_anchors else 0.0,
            "direction_candidates": 1.0 if run_anchors else 0.0,
            "vertical_text_candidates": 1.0 if row_bands and width >= height else 0.0,
        },
        "score": shaped_score,
        "row_bands": row_bands,
        "baselines": baselines,
        "run_anchors": run_anchors,
        "run_bounds": [
            [int(anchor["x0"]), int(anchor["y0"]), int(anchor["x1"]), int(anchor["y1"])]
            for anchor in run_anchors
        ],
        "direction_candidates": ["ltr"],
        "orientation": "horizontal",
        "geometry_proof": "raster_measured",
    }
    shaped_candidates = [shaped_candidate] if row_bands and run_anchors else []

    component_evidence: Mapping[str, Any]
    if selected_mask is not None:
        # Do not ask the legacy component extractor to assign rows by bounding
        # box overlap.  Row ownership is the periodic pixel/seam evidence
        # above; bbox candidates remain diagnostic only.
        component_evidence = extract_components(selected_mask, source_hash=source_hash, row_bands=None, run_anchors=run_anchors)
        unassigned = [
            component.component_id
            for component in component_evidence["components"]
            if not component.candidate_run_ids
        ]
        component_evidence = {
            **component_evidence,
            "unassigned_component_ids": unassigned,
            "component_ownership_complete": not unassigned,
            "row_ownership_authority": "periodic_pixel_intervals",
            "bbox_row_candidates_authoritative": False,
        }
    else:
        component_evidence = {
            "source_sha256": source_hash,
            "canvas": {"width": width, "height": height},
            "components": [],
            "component_hash": sha256_bytes(canonical_bytes([])),
            "substantive_pixel_count": 0,
            "owned_pixel_count": 0,
            "glyph_labels_emitted": False,
            "row_ownership_authority": "periodic_pixel_intervals",
            "bbox_row_candidates_authoritative": False,
        }
    row_band_quality = {
        **row_band_quality,
        "blank_gap_undersegmented": undersegmented,
        "periodic_baselines_proven": bool(periodic_authority.get("baseline_proven", False)),
        "periodic_baseline_pitch": periodic_authority.get("winning_pitch"),
        "periodic_baseline_phase_group": periodic_authority.get("winning_phase_group"),
        "periodic_authority_status": "proved" if periodic_authority.get("baseline_proven") else "unresolved",
    }
    # Only an unsuccessful periodic proof may turn the diagnostic under-
    # segmentation finding into a rejection.  A blank-gap warning by itself
    # must not veto a complete, source-derived periodic lattice.
    if undersegmented and not periodic_authority.get("baseline_proven", False):
        rejection.append("row_baselines_undersegmented")
    selected_hash = selected_meta["mask_sha256"] if selected_meta else ""
    projection_evidence = {
        "row_projection": row_projection.tolist(),
        "column_projection": column_projection.tolist(),
        "row_groups": [list(group) for group in row_bands_raw],
        "selected_baseline_rows": [dict(item) for item in row_bands],
        "x_groups": [list(group) for group in x_groups],
        "autocorrelation": autocorrelation[:16],
        "selected_mask_sha256": selected_hash,
        "mixed_width_display": mixed_width_display,
        "foreground_margin": float(configuration["foreground_margin"]),
        "measurement": "source_raster_projection",
        "row_band_quality": row_band_quality,
        "periodic_row_candidates": periodic_row_candidates,
        "periodic_authority": periodic_authority,
    }
    if selected_mask is None:
        rejection.extend(["geometry_unresolved", "component_evidence_missing"])
    elif not row_bands or not run_anchors:
        rejection.append("geometry_unresolved")
    elif component_evidence.get("unassigned_component_ids"):
        rejection.append("component_unowned")
    fixed_branch_plausible = bool(
        lattice_candidates
        and any(
            all(float(candidate.get("criteria", {}).get(name, 0.0)) >= 0.8 for name in (
                "row_periodicity",
                "horizontal_advance_stability",
                "phase_origin_confidence",
                "fullwidth_multiples",
                "boundary_intersections",
                "horizontal_joins_vs_cuts",
                "negative_origin_clipping",
                "cross_row_spill",
                "foreground_alternatives",
            ))
            for candidate in lattice_candidates
        )
    )
    fixed_authority_proven = bool(periodic_authority.get("fixed_lattice_authority_proven"))
    # The authority owner may prove a fixed lattice from complete periodic or
    # regular-lattice evidence even when the legacy branch score is below its
    # plausibility threshold.  Keep that score diagnostic; do not let it veto
    # the concrete source proof.
    fixed_branch_plausible = bool(fixed_branch_plausible or fixed_authority_proven)
    # Periodic proof is required only when the raster has actually produced a
    # plausible fixed-lattice branch.  A shaped-run source (for example a
    # single-row joined emoji strip) must not be rejected because a fixed
    # lattice cannot be proved; conversely, a connected multiline drawing
    # whose fixed branch remains plausible still fails closed on phase and
    # ownership ambiguity.
    if undersegmented and not all(
        bool(periodic_authority.get(key)) for key in ("candidate_valid", "pitch_proven", "phase_proven", "ownership_proven")
    ):
        rejection.append("periodic_authority_unresolved")
        for key, reason in (
            ("candidate_valid", "candidate_validity_unresolved"),
            ("pitch_proven", "pitch_authority_unresolved"),
            ("phase_proven", "phase_authority_unresolved"),
            ("ownership_proven", "ownership_authority_unresolved"),
        ):
            if not periodic_authority.get(key):
                rejection.append(reason)
    shaped_branch_plausible = bool(
        shaped_candidate
        and all(
            float(shaped_candidate.get("criteria", {}).get(name, 0.0)) >= 0.8
            for name in (
                "row_bands_baselines",
                "variable_advances",
                "connected_joined_runs",
                "direction_candidates",
                "vertical_text_candidates",
            )
        )
    )
    if not fixed_branch_plausible and not shaped_branch_plausible:
        rejection.append("geometry_unresolved")
    status = "proved" if selected_mask is not None and row_bands and run_anchors and not rejection and (fixed_authority_proven or shaped_branch_plausible) else "rejected"
    return GeometryEvidenceBundle(
        source_sha256=source_hash,
        canvas={"width": width, "height": height},
        foreground_alternatives=tuple({key: value for key, value in item.items() if key != "mask"} for item in ranked),
        projection_evidence=projection_evidence,
        row_band_candidates=tuple(row_bands),
        baseline_candidates=tuple(baselines),
        fixed_lattice_candidates=tuple(lattice_candidates),
        shaped_run_candidates=tuple(shaped_candidates),
        component_evidence=component_evidence,
        selected_foreground=selected_meta,
        selected_mask=selected_mask,
        configuration=configuration,
        status=status,
        rejection_reasons=tuple(dict.fromkeys(rejection)),
    )


class RecognitionInputBuilder:
    """Build geometry-owned run strips without consulting logical text."""

    def __init__(
        self,
        source_path: str | Path,
        geometry: GeometryEvidenceBundle | Mapping[str, Any],
        *,
        mode: str | None = None,
        allow_unproved: bool = False,
    ):
        self.source_path = Path(source_path)
        self.geometry = geometry
        self.mode = mode
        self.allow_unproved = bool(allow_unproved)

    def _mapping(self) -> Mapping[str, Any]:
        # Geometry selection belongs exclusively to route_raster_geometry.
        # This builder may materialize an already-selected contract, but it
        # must never score branches or choose a mode when the caller omits it.
        if self.mode not in {"fixed_lattice", "shaped_runs"}:
            raise ValueError("recognition inputs require an explicit proved geometry mode")
        if isinstance(self.geometry, GeometryEvidenceBundle):
            return self.geometry.geometry_mapping(self.mode)
        mapping = self.geometry
        # A serialized evidence bundle crosses a process boundary without its
        # ndarray.  Hydrate only the explicitly selected branch; do not run a
        # second proof scorer here.  The status/authority flags were written by
        # the raster router and are the sole admission evidence.
        mapping_mode = mapping.get("mode")
        if mapping_mode is not None and str(mapping_mode) != self.mode:
            raise ValueError("recognition input geometry mode mismatch")
        # Joint-decoder hypotheses already contain one concrete, measured
        # branch (row bands or run anchors) and are explicitly marked
        # unproved.  Reuse that branch verbatim; do not ask a second scorer to
        # select it.  ``allow_unproved`` is the only path permitted to consume
        # this diagnostic surface.
        if (
            mapping_mode == self.mode
            and self.allow_unproved
            and (mapping.get("row_bands") or mapping.get("run_anchors"))
            and not mapping.get("fixed_lattice_candidates")
            and not mapping.get("shaped_run_candidates")
        ):
            return mapping
        selected = mapping.get("selected_geometry")
        if not isinstance(selected, Mapping):
            candidates = mapping.get(
                "fixed_lattice_candidates" if self.mode == "fixed_lattice" else "shaped_run_candidates",
                (),
            )
            if not isinstance(candidates, (list, tuple)) or not candidates:
                raise ValueError("serialized geometry does not contain a selected branch")
            # ``GeometryEvidenceBundle.geometry_mapping`` defines the
            # serialized branch as the first source-ordered candidate.  Keep
            # that exact selection at the process boundary; never rescore or
            # compare it here.
            selected = candidates[0]
        selected = dict(selected)
        authority = dict(mapping.get("projection_evidence", {}).get("periodic_authority", {}))
        if not authority:
            authority = dict(mapping.get("periodic_authority") or {})
        geometry_proven = bool(mapping.get("geometry_proven", str(mapping.get("status")) == "proved"))
        if self.mode == "fixed_lattice":
            geometry_proven = geometry_proven and all(
                bool(authority.get(key)) for key in ("candidate_valid", "pitch_proven", "phase_proven", "ownership_proven")
            )
        elif mapping.get("status") is not None:
            geometry_proven = geometry_proven and str(mapping.get("status")) == "proved"
        if not self.allow_unproved and not geometry_proven:
            raise ValueError("serialized geometry is not an authoritative proved selection")
        if "mode" not in mapping:
            return {
                **selected,
                "mode": self.mode,
                "source_sha256": mapping.get("source_sha256", ""),
                "geometry_evidence_hash": mapping.get("output_hash", ""),
                "selected_foreground": dict(mapping.get("selected_foreground") or {}),
                "selected_foreground_mask_sha256": mapping.get("projection_evidence", {}).get("selected_mask_sha256", ""),
                "geometry_proven": geometry_proven,
                "row_band_quality": dict(mapping.get("projection_evidence", {}).get("row_band_quality", {})),
                "periodic_authority": authority,
                "mixed_width_display": dict(mapping.get("projection_evidence", {}).get("mixed_width_display", {})),
            }
        return {**mapping, **selected, "mode": self.mode, "geometry_proven": geometry_proven, "periodic_authority": authority}

    @staticmethod
    def _reassign_cross_row_edge_pixels(
        mask: np.ndarray,
        anchors: list[dict[str, Any]],
        *,
        base_advance: float,
        edge_rows: int = 4,
    ) -> tuple[np.ndarray, list[np.ndarray]]:
        """Assign connected edge ink to one adjacent logical row.

        Projection bands intentionally remain unchanged.  For proposal-only
        rows, however, a glyph can paint its top underscore or diagonal into
        the preceding band.  Keeping that edge ink in both strips makes the
        recognizer invent punctuation; deleting it loses source ownership.  A
        deterministic owner map moves only edge pixels with corroborating ink
        in the adjacent row, preferring same-column continuation and then a
        nearby horizontal continuation.  Every foreground pixel remains owned
        exactly once.
        """

        height, width = mask.shape
        owner = np.full((height, width), -1, dtype=np.int16)
        ordered = sorted(enumerate(anchors), key=lambda item: (int(item[1].get("y0", 0)), item[0]))
        for row_index, anchor in ordered:
            y0 = max(0, min(height, int(anchor.get("y0", 0))))
            y1 = max(y0, min(height, int(anchor.get("y1", height))))
            owner_slice = owner[y0:y1]
            owner_slice[mask[y0:y1]] = int(row_index)
            owner[y0:y1] = owner_slice
        spill = max(1, min(int(edge_rows), int(round(base_advance * 0.35))))
        for position in range(len(ordered) - 1):
            top_index, top_anchor = ordered[position]
            bottom_index, bottom_anchor = ordered[position + 1]
            boundary = int(top_anchor.get("y1", 0))
            next_start = int(bottom_anchor.get("y0", boundary))
            if next_start < boundary:
                next_start = boundary
            top_y0 = max(0, boundary - spill)
            top_y1 = min(height, boundary)
            bottom_y0 = max(0, next_start)
            bottom_y1 = min(height, next_start + spill)
            if top_y1 <= top_y0 or bottom_y1 <= bottom_y0:
                continue
            next_pixels = np.argwhere(mask[bottom_y0:bottom_y1])
            if not len(next_pixels):
                continue
            next_x = next_pixels[:, 1]
            top_projection = mask[top_y0:top_y1].sum(axis=0) > 0
            top_runs: list[tuple[int, int]] = []
            run_start: int | None = None
            for column, present in enumerate(top_projection):
                if present and run_start is None:
                    run_start = column
                elif not present and run_start is not None:
                    top_runs.append((run_start, column))
                    run_start = None
            if run_start is not None:
                top_runs.append((run_start, len(top_projection)))
            for local_y, x in np.argwhere(mask[top_y0:top_y1]):
                y = top_y0 + int(local_y)
                x = int(x)
                same_column = bool(np.any(np.abs(next_x - x) <= 2))
                nearby = bool(np.any(np.abs(next_x - x) <= max(3, int(round(base_advance * 0.60)))))
                long_horizontal = any(left <= x < right and (right - left) >= base_advance * 0.95 for left, right in top_runs)
                if same_column or (nearby and long_horizontal):
                    owner[y, x] = int(bottom_index)
        owned_masks: list[np.ndarray] = []
        for row_index, _anchor in ordered:
            owned_masks.append(mask & (owner == int(row_index)))
        return owner, owned_masks

    @staticmethod
    def _anchor_evidence(
        binary: np.ndarray,
        *,
        source_bounds: tuple[int, int, int, int],
        base_advance: float,
        origin_px: float,
        run_id: str,
        component_ids: list[str],
    ) -> dict[str, Any]:
        """Describe painted intervals without assigning them characters.

        A row strip is intentionally not reduced to one measured advance.  The
        recognizer needs the source-derived intervals that survived geometry:
        where ink starts/ends, which measured display units it touches, and
        how many pixels each interval contains.  This evidence is strictly
        raster-local; it carries no transcript, glyph label, or expected width.
        """

        x0, y0, x1, y1 = (int(value) for value in source_bounds)
        projection = np.asarray(binary, dtype=bool).any(axis=0)
        groups = _groups(projection, merge_gap=0)
        painted: list[dict[str, Any]] = []
        base = max(float(base_advance), 1e-9)
        for index, (local_x0, local_x1) in enumerate(groups):
            global_x0 = x0 + int(local_x0)
            global_x1 = x0 + int(local_x1)
            local_mask = binary[:, local_x0:local_x1]
            units_start = int(math.floor((global_x0 - float(origin_px)) / base))
            units_end = int(math.ceil((global_x1 - float(origin_px)) / base))
            painted.append(
                {
                    "painted_run_id": f"{run_id}-paint-{index:03d}",
                    "source_bounds": [global_x0, y0, global_x1, y1],
                    "local_bounds": [int(local_x0), 0, int(local_x1), int(binary.shape[0])],
                    "unit_start": units_start,
                    "unit_end": max(units_start, units_end),
                    "span_units": max(1, units_end - units_start),
                    "ink_pixels": int(local_mask.sum()),
                    "mask_sha256": _mask_hash(local_mask),
                    "touches_left_edge": bool(local_x0 == 0),
                    "touches_right_edge": bool(local_x1 == binary.shape[1]),
                }
            )
        payload = {
            "authority": "source_mask_anchor_evidence",
            "run_id": str(run_id),
            "source_bounds": [x0, y0, x1, y1],
            "mask_sha256": _mask_hash(binary),
            "base_advance_px": float(base_advance),
            "origin_px": float(origin_px),
            "painted_runs": painted,
            "component_ids": sorted(str(value) for value in component_ids),
        }
        payload["evidence_hash"] = sha256_bytes(canonical_bytes(payload))
        return payload

    def build(self) -> dict[str, Any]:
        source_pixels, source_hash = load_rgb(self.source_path)
        geometry = self._mapping()
        expected = geometry.get("source_sha256") or geometry.get("input_hashes", {}).get("source")
        if expected and source_hash != expected:
            raise ValueError("recognition input source hash mismatch")
        mode = str(geometry.get("mode", "unresolved"))
        if mode not in {"fixed_lattice", "shaped_runs"} or (not self.allow_unproved and not geometry.get("geometry_proven", False)):
            raise ValueError("recognition inputs require one proved geometry authority")
        if mode == "fixed_lattice":
            quality = geometry.get("row_band_quality") or {}
            if not self.allow_unproved and quality.get("periodic_baselines_proven") is False:
                raise ValueError("recognition inputs require periodic baseline coverage")
            authority = geometry.get("periodic_authority") or {}
            if not self.allow_unproved and not all(bool(authority.get(key)) for key in ("candidate_valid", "pitch_proven", "phase_proven", "ownership_proven")):
                raise ValueError("recognition inputs require candidate, pitch, phase, and ownership proof")
        if isinstance(self.geometry, GeometryEvidenceBundle) and self.geometry.selected_mask is not None:
            mask = self.geometry.selected_mask
        else:
            recipe = geometry.get("selected_foreground") or {}
            if not recipe:
                raise ValueError("geometry does not contain a reproducible foreground recipe")
            distance = np.max(np.abs(source_pixels.astype(np.int16) - np.asarray(recipe["background_rgb"], dtype=np.int16)), axis=2)
            mask = distance > int(recipe["threshold"])
            if _mask_hash(mask) != geometry.get("selected_foreground_mask_sha256"):
                raise ValueError("recognition input foreground hash mismatch")
        if mode == "fixed_lattice":
            # Fixed-cell recognizers consume complete row strips.  Individual
            # cell crops discard neighboring evidence and recreate the
            # horse-era ownership bug at the adapter boundary.
            mixed_display = geometry.get("mixed_width_display") or {}
            content_x0 = 0
            content_x1 = source_pixels.shape[1]
            ink_columns = np.flatnonzero(mask.any(axis=0))
            if len(ink_columns):
                # Keep the source-sized raster and its global coordinates in
                # evidence, but do not turn blank canvas tails into logical
                # transcript columns.  Snap the content extent outward to the
                # measured display lattice so a clipped leading cell is never
                # silently removed.
                base_advance = float(mixed_display.get("base_advance_px") or geometry.get("advance_x") or 1.0)
                origin_x = float(mixed_display.get("origin_px") or geometry.get("origin_x") or 0.0)
                first_col = int(math.floor((int(ink_columns[0]) - origin_x) / base_advance))
                last_col = int(math.ceil((int(ink_columns[-1]) + 1 - origin_x) / base_advance))
                content_x0 = max(0, min(source_pixels.shape[1], int(round(origin_x + first_col * base_advance))))
                content_x1 = max(content_x0 + 1, min(source_pixels.shape[1], int(round(origin_x + last_col * base_advance))))
            anchors = [
                {
                    "run_id": f"row-r{int(row.get('row_index', index)):03d}",
                    "row_index": int(row.get("row_index", index)),
                    "x0": content_x0,
                    "x1": content_x1,
                    "y0": max(0, int(row["y0"])),
                    "y1": min(source_pixels.shape[0], int(row["y1"])),
                    "start_x": 0,
                    "end_x": source_pixels.shape[1],
                    "direction": "ltr",
                    "advance": float(geometry.get("advance_x", source_pixels.shape[1])),
                }
                for index, row in enumerate(geometry.get("row_bands", []))
            ]
        else:
            anchors = [dict(item) for item in geometry.get("run_anchors", [])]
        components = extract_components(mask, source_hash=source_hash, row_bands=None, run_anchors=anchors)
        owned_masks: list[np.ndarray] | None = None
        if self.allow_unproved and mode == "fixed_lattice" and anchors:
            mixed = geometry.get("mixed_width_display") or {}
            base_advance = float(mixed.get("base_advance_px") or geometry.get("advance_x") or 1.0)
            _owner_map, owned_masks = self._reassign_cross_row_edge_pixels(
                mask,
                anchors,
                base_advance=base_advance,
            )
        unassigned = [
            component.component_id
            for component in components["components"]
            if not component.candidate_run_ids
        ]
        if unassigned:
            raise ValueError(f"component_unowned:{','.join(unassigned)}")
        runs: list[dict[str, Any]] = []
        for anchor_index, anchor in enumerate(anchors):
            x0, x1 = max(0, int(anchor["x0"])), min(source_pixels.shape[1], int(anchor["x1"]))
            y0, y1 = max(0, int(anchor["y0"])), min(source_pixels.shape[0], int(anchor["y1"]))
            row_mask = owned_masks[anchor_index] if owned_masks is not None and anchor_index < len(owned_masks) else mask
            if owned_masks is not None:
                owned_y, owned_x = np.where(row_mask)
                if len(owned_y):
                    y0 = min(y0, int(owned_y.min()))
                    y1 = max(y1, int(owned_y.max()) + 1)
            if x1 <= x0 or y1 <= y0:
                continue
            strip = source_pixels[y0:y1, x0:x1]
            binary = row_mask[y0:y1, x0:x1]
            display_base = float((geometry.get("mixed_width_display") or {}).get("base_advance_px") or geometry.get("advance_x") or 1.0)
            display_origin = float((geometry.get("mixed_width_display") or {}).get("origin_px") or geometry.get("origin_x") or 0.0)
            row_columns = np.flatnonzero(binary.any(axis=0))
            logical_end_column = None
            if len(row_columns):
                logical_end_column = int(math.ceil((x0 + int(row_columns[-1]) + 1 - display_origin) / display_base))
            image = Image.fromarray(strip.astype(np.uint8), mode="RGB")
            from io import BytesIO

            stream = BytesIO()
            image.save(stream, format="PNG", optimize=False)
            png_bytes = stream.getvalue()
            binary_rows = ["".join("1" if value else "0" for value in row) for row in binary]
            rgb = strip.astype(np.int16)
            runs.append(
                {
                    "run_id": str(anchor["run_id"]),
                    "row_index": int(anchor.get("row_index", 0)),
                    "source_bounds": [x0, y0, x1, y1],
                    "run_strip_width_px": int(strip.shape[1]),
                    "logical_start_column": 0,
                    "logical_end_column": logical_end_column,
                    "original_anchor": {key: value for key, value in anchor.items() if key not in {"x0", "x1", "y0", "y1"}},
                    "direction": str(anchor.get("direction", "ltr")),
                    "measured_advances": [float(anchor.get("advance", x1 - x0))],
                    "run_strip_png_base64": base64.b64encode(png_bytes).decode("ascii"),
                    "run_strip_png_sha256": sha256_bytes(png_bytes),
                    "binary_run_mask": binary_rows,
                    "binary_run_mask_sha256": _mask_hash(binary),
                    "component_ids": [component.component_id for component in components["components"] if str(anchor["run_id"]) in component.candidate_run_ids],
                    "run_color_stats": {
                        "pixel_count": int(strip.shape[0] * strip.shape[1]),
                        "non_grayscale_pixels": int(np.count_nonzero((rgb[:, :, 0] != rgb[:, :, 1]) | (rgb[:, :, 1] != rgb[:, :, 2]))),
                        "strongly_colored_pixels": int(np.count_nonzero((rgb.max(axis=2) - rgb.min(axis=2)) > 16)),
                        "unique_rgb_count": int(len(np.unique(strip.reshape(-1, 3), axis=0))),
                    },
                }
            )
            runs[-1]["anchor_evidence"] = self._anchor_evidence(
                binary,
                source_bounds=(x0, y0, x1, y1),
                base_advance=display_base,
                origin_px=display_origin,
                run_id=str(anchor["run_id"]),
                component_ids=list(runs[-1]["component_ids"]),
            )
        payload = {
            "source_sha256": source_hash,
            "geometry_hash": geometry.get("geometry_evidence_hash") or geometry.get("geometry_hash", ""),
            "foreground_mask_sha256": _mask_hash(mask),
            "mode": mode,
            "mixed_width_display": dict(geometry.get("mixed_width_display", {})),
            "components_hash": components["component_hash"],
            "runs": runs,
            "provenance": {
                "source_only": True,
                "transcript_input": False,
                "visual_layout_input": False,
                "emoji_sequence_input": False,
                "geometry_hypothesis_only": self.allow_unproved,
            },
        }
        # Run strips may be cropped to the measured content extent.  Rebase
        # display geometry for adapters consuming the strip while retaining
        # each run's global source bounds above for provenance and alignment.
        if mode == "fixed_lattice" and runs:
            display = dict(payload["mixed_width_display"])
            source_offset = int(runs[0]["source_bounds"][0])
            if "origin_px" in display:
                display["origin_px"] = float(display["origin_px"]) - source_offset
            if isinstance(display.get("origin_candidates_px"), (list, tuple)):
                display["origin_candidates_px"] = [
                    float(value) - source_offset for value in display["origin_candidates_px"]
                ]
            if isinstance(display.get("boundary_columns_px"), (list, tuple)):
                display["boundary_columns_px"] = [float(value) - source_offset for value in display["boundary_columns_px"]]
            payload["mixed_width_display"] = display
            # Anchor evidence keeps global source bounds for provenance, but
            # adapters consume the cropped strip in local coordinates.  Bind
            # both frames explicitly instead of making a consumer guess.
            for run in runs:
                evidence = run.get("anchor_evidence")
                if not isinstance(evidence, dict):
                    continue
                global_origin = float(evidence.get("origin_px", 0.0))
                evidence["global_origin_px"] = global_origin
                evidence["origin_px"] = global_origin - source_offset
                evidence["frame"] = "run_local_with_global_bounds"
                evidence["evidence_hash"] = sha256_bytes(
                    canonical_bytes({key: value for key, value in evidence.items() if key != "evidence_hash"})
                )
        payload["input_hash"] = sha256_bytes(canonical_bytes(payload))
        return payload


def build_recognition_hypothesis_inputs(
    source_path: str | Path,
    geometry: GeometryEvidenceBundle | Mapping[str, Any],
    *,
    max_hypotheses: int = 16,
) -> tuple[dict[str, Any], ...]:
    """Build proposal-only inputs for measured geometry hypotheses.

    This is intentionally distinct from :func:`build_recognition_inputs`.
    Unresolved geometry may provide evidence to a joint decoder, but it may not
    be serialized as canonical geometry or produce a TXT.  The hypotheses are
    selected only for a bounded compute budget from the measured candidate
    table; their ordering is not an authority decision.
    """

    if max_hypotheses <= 0:
        return ()
    if isinstance(geometry, GeometryEvidenceBundle):
        candidates = list(geometry.projection_evidence.get("periodic_row_candidates", ()))
        source_hash = geometry.source_sha256
        selected_foreground = dict(geometry.selected_foreground or {})
        selected_mask_hash = geometry.projection_evidence.get("selected_mask_sha256", "")
        evidence_hash = geometry.output_hash
        authority = dict(geometry.projection_evidence.get("periodic_authority", {}))
        mixed_width_display = dict(geometry.projection_evidence.get("mixed_width_display", {}))
    else:
        candidates = list(geometry.get("projection_evidence", {}).get("periodic_row_candidates", ()))
        source_hash = str(geometry.get("source_sha256", ""))
        selected_foreground = dict(geometry.get("selected_foreground") or {})
        selected_mask_hash = geometry.get("projection_evidence", {}).get("selected_mask_sha256", "")
        evidence_hash = str(geometry.get("output_hash", ""))
        authority = dict(geometry.get("projection_evidence", {}).get("periodic_authority", {}))
        mixed_width_display = dict(geometry.get("projection_evidence", {}).get("mixed_width_display", {}))
    candidates = [item for item in candidates if bool(item.get("candidate_valid"))]
    candidates.sort(
        key=lambda item: (
            float(item.get("normalized_seam_energy", 1.0)),
            -float(item.get("seam_to_interior_contrast", 0.0)),
            int(item.get("pitch", 0)),
            int(item.get("phase", 0)),
        )
    )
    # Keep horizontal logical-origin alternatives in the same proposal-only
    # hypothesis space as vertical pitch/phase alternatives.  A modulo phase
    # identifies physical seams but not which seam is display column zero.
    # Expand one vertical candidate across its measured origin basin before
    # moving to the next candidate; the bounded cap keeps this deterministic.
    origin_candidates = tuple(
        float(value)
        for value in mixed_width_display.get("origin_candidates_px", ())
        if isinstance(value, (int, float))
    )
    if not origin_candidates:
        origin_candidates = (float(mixed_width_display.get("origin_px", 0.0)),)
    base_candidates = tuple(
        float(value)
        for value in mixed_width_display.get("base_advance_candidates_px", ())
        if isinstance(value, (int, float)) and float(value) > 0.0
    ) or (float(mixed_width_display.get("base_advance_px", 1.0)),)
    origin_by_base = dict(mixed_width_display.get("base_origin_candidates_px") or {})
    base_options = tuple(
        (
            base,
            tuple(
                float(value)
                for value in origin_by_base.get(str(round(base, 4)), origin_candidates)
                if isinstance(value, (int, float))
            ) or origin_candidates,
        )
        for base in base_candidates
    )
    # A horizontal origin basin must not consume the whole unresolved search
    # budget.  The old Cartesian-prefix ordering emitted all origins for the
    # first pitch/phase candidate, so the recognizer could never compare a
    # competing vertical family and the supposedly joint scorer received
    # identical geometry four times.  Keep the small historical seam used by
    # callers explicitly asking for only an origin basin, but once the budget
    # can hold more than that basin enumerate candidates round-robin by origin
    # index.  Every retained vertical family therefore reaches recognition
    # before a second origin for any one family is added.
    if max_hypotheses <= len(origin_candidates):
        selected_pairs = [
            (candidates[0], base_options[0][0], origin)
            for origin in origin_candidates[:max_hypotheses]
        ] if candidates else []
    else:
        selected_pairs = []
        max_origins = max(len(origins) for _base, origins in base_options)
        for origin_index in range(max_origins):
            # Interleave the measured base families for each vertical
            # candidate.  A base harmonic is a separate display hypothesis;
            # it must reach the recognizer before later pitch/phase families
            # or extra origins consume the bounded budget.
            for candidate in candidates:
                for base, origins in base_options:
                    if origin_index >= len(origins):
                        continue
                    origin = origins[origin_index]
                    selected_pairs.append((candidate, base, origin))
                    if len(selected_pairs) >= max_hypotheses:
                        break
                if len(selected_pairs) >= max_hypotheses:
                    break
            if len(selected_pairs) >= max_hypotheses:
                break
    outputs: list[dict[str, Any]] = []
    for candidate, base_advance, origin in selected_pairs:
        row_bands = [
            {
                "row_index": index,
                "y0": int(bounds[0]),
                "y1": int(bounds[1]),
                "baseline": int(bounds[1]) - 1,
                "confidence": 0.0,
            }
            for index, bounds in enumerate(candidate.get("row_bounds", ()))
        ]
        if not row_bands or not selected_foreground:
            continue
        proposal_display = dict(mixed_width_display)
        proposal_display["base_advance_px"] = float(base_advance)
        proposal_display["origin_px"] = float(origin)
        mapping = {
            "mode": "fixed_lattice",
            "source_sha256": source_hash,
            "geometry_evidence_hash": evidence_hash,
            "geometry_proven": False,
            "selected_foreground": selected_foreground,
            "selected_foreground_mask_sha256": selected_mask_hash,
            "row_band_quality": {"periodic_baselines_proven": False, "hypothesis_only": True},
            "periodic_authority": authority,
            "row_bands": row_bands,
            # Vertical pitch and horizontal display advance are independent
            # axes.  The old hypothesis path incorrectly copied pitch into
            # ``advance_x`` and thereby manufactured a nonsensical lattice.
            "advance_x": float(base_advance),
            "mixed_width_display": proposal_display,
            "hypothesis": {
                "pitch": int(candidate.get("pitch", 0)),
                "phase": int(candidate.get("phase", 0)),
                "origin_px": float(origin),
                "base_advance_px": float(base_advance),
                "candidate_valid": True,
                # Preserve independent raster evidence beside the proposal
                # input.  The joint decoder may combine these diagnostics
                # with row text/ownership fit, but no recognizer is allowed
                # to rewrite them or promote the result to geometry
                # authority.
                "normalized_seam_energy": candidate.get("normalized_seam_energy"),
                "seam_to_interior_contrast": candidate.get("seam_to_interior_contrast"),
                "boundary_ink_pixels": candidate.get("boundary_ink_pixels"),
                "row_count": candidate.get("row_count"),
                "ownership_signature": candidate.get("ownership", {}).get("ownership_signature"),
                "ownership": dict(candidate.get("ownership", {})),
            },
        }
        try:
            item = RecognitionInputBuilder(
                source_path,
                mapping,
                mode="fixed_lattice",
                allow_unproved=True,
            ).build()
        except ValueError:
            # A hypothesis with incomplete source ownership remains evidence in
            # the geometry bundle; it is not silently repaired into a run input.
            continue
        hypothesis_provenance = dict(mapping["hypothesis"])
        hypothesis_provenance["origin_px"] = float(
            item.get("mixed_width_display", {}).get("origin_px", hypothesis_provenance.get("origin_px", 0.0))
        )
        item["provenance"] = {
            **dict(item.get("provenance", {})),
            "authoritative": False,
            "hypothesis_only": True,
            "hypothesis": hypothesis_provenance,
        }
        item["input_hash"] = sha256_bytes(canonical_bytes({key: value for key, value in item.items() if key != "input_hash"}))
        outputs.append(item)
    return tuple(outputs)


def build_recognition_inputs(
    source_path: str | Path,
    geometry: GeometryEvidenceBundle | Mapping[str, Any],
    *,
    mode: str | None = None,
) -> dict[str, Any]:
    """Functional facade for callers that do not need a builder instance."""

    return RecognitionInputBuilder(source_path, geometry, mode=mode).build()


def _score(value: Any) -> float | None:
    if isinstance(value, bool):
        return 1.0 if value else 0.0
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        if value != value:  # NaN
            return None
        return max(0.0, min(1.0, float(value)))
    if isinstance(value, Mapping) and "score" in value:
        return _score(value["score"])
    return None


def evaluate_criteria(
    mode: str,
    evidence: Mapping[str, Any] | None,
    required: tuple[str, ...],
    *,
    threshold: float = 0.8,
) -> GeometryProof:
    """Convert heterogeneous detector evidence to a pinned proof score.

    Missing, malformed, or explicitly failed criteria are retained as rejection
    reasons rather than silently filled from the competing geometry model.
    """

    evidence = evidence or {}
    raw = evidence.get("criteria", evidence.get("scores", evidence))
    if not isinstance(raw, Mapping):
        raw = {}
    criteria: dict[str, float] = {}
    reasons: list[str] = []
    for name in required:
        value = _score(raw.get(name))
        if value is None:
            reasons.append(f"{mode}_criterion_missing:{name}")
            value = 0.0
        criteria[name] = value
        if value < threshold:
            reasons.append(f"{mode}_criterion_below_threshold:{name}")
    score = sum(criteria.values()) / len(required) if required else 0.0
    passed = not reasons and score >= threshold
    return GeometryProof(
        mode=mode,
        criteria=MappingProxyType(criteria),
        score=score,
        passed=passed,
        rejection_reasons=tuple(reasons),
    )
