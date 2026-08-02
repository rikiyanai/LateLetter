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
        candidate = self.fixed_lattice_candidates[0] if self.fixed_lattice_candidates else {}
        return candidate

    def shaped_evidence(self) -> Mapping[str, Any]:
        candidate = self.shaped_run_candidates[0] if self.shaped_run_candidates else {}
        return candidate

    def geometry_mapping(self, mode: str) -> dict[str, Any]:
        """Return the concrete geometry contract consumed by adapters."""

        if mode == "fixed_lattice":
            candidate = dict(self.fixed_evidence())
            candidate.update(
                {
                    "mode": mode,
                    "source_sha256": self.source_sha256,
                    "canvas": dict(self.canvas),
                    "geometry_evidence_hash": self.output_hash,
                    "selected_foreground_mask_sha256": self.projection_evidence.get("selected_mask_sha256"),
                    "selected_foreground": dict(self.selected_foreground or {}),
                    "geometry_proven": self.status == "proved",
                    "row_band_quality": dict(self.projection_evidence.get("row_band_quality", {})),
                    "periodic_row_candidates": list(self.projection_evidence.get("periodic_row_candidates", [])),
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
                    baseline_rows.append(min(end - 1, y1 - 1))
                start += pitch
            baseline_deltas = [int(next_value - value) for value, next_value in zip(baseline_rows, baseline_rows[1:])]
            baseline_delta_residuals = [int(delta - pitch) for delta in baseline_deltas]
            tolerance = max(1.0, pitch * 0.15)
            partial_edge_rows: list[str] = []
            if row_bounds and row_bounds[0][0] == 0 and phase != row_bounds[0][0]:
                partial_edge_rows.append("initial")
            if row_bounds and row_bounds[-1][1] == height and (row_bounds[-1][0] + pitch) > height:
                partial_edge_rows.append("terminal")
            clipping_proven = {
                "initial": top_clipped,
                "terminal": bottom_clipped,
            }
            partial_without_clipping = [edge for edge in partial_edge_rows if not clipping_proven[edge]]
            terminal_sliver_rejected = bool(
                baseline_delta_residuals
                and abs(float(baseline_delta_residuals[-1])) > tolerance
            )
            initial_sliver_rejected = bool(
                baseline_delta_residuals
                and abs(float(baseline_delta_residuals[0])) > tolerance
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
            independent_score = float(
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
                    "row_count": len(row_bounds),
                    "row_bounds": row_bounds,
                    "baselines": baseline_rows,
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
                    "valid": valid,
                    "rejection_reasons": rejection_reasons,
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
        "min_vertical_pitch": 8,
        "max_vertical_pitch": 32,
        "foreground_margin": 0.03,
        "geometry_margin": 0.12,
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
        "periodic_baselines_proven": not undersegmented,
        "rejection_reason": "row_baselines_undersegmented" if undersegmented else None,
    }
    if undersegmented:
        rejection.append("row_baselines_undersegmented")
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
            if sparse_multiline:
                # The sparse signal is an additional raster measurement; it
                # raises proof criteria only for the fixed-looking candidate,
                # never by accepting a caller's declared geometry mode.
                stability = max(0.84, periodicity)
                fullwidth = max(0.84, min(1.0, periodicity + 0.1))
            else:
                stability = min(0.74, periodicity)
                fullwidth = min(0.74, periodicity)
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
                        "row_periodicity": max(0.85, row_regular) if sparse_multiline else min(0.74, row_regular),
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

    run_anchors = _run_anchors(projection, row_bands, merge_gap=int(configuration["run_merge_gap"])) if selected_mask is not None else []
    shaped_score = 0.0
    if row_bands and run_anchors and selected_mask is not None:
        best_fixed = float(lattice_candidates[0]["score"]) if lattice_candidates else 0.0
        # Shaped geometry is supported by measured rows/runs.  Variable-advance
        # evidence is explicitly reduced when a strong lattice explains the
        # same raster, so neither authority can win by recognizer preference.
        variable = 0.35 if sparse_multiline else max(0.86, min(1.0, 1.0 - best_fixed * 0.7))
        connected = min(1.0, len(run_anchors) / max(1, len(row_bands)))
        shaped_score = float(np.mean([1.0, variable, connected, 1.0, 1.0]))
    shaped_candidate = {
        "mode": "shaped_runs",
        "criteria": {
            "row_bands_baselines": 1.0 if row_bands else 0.0,
            "variable_advances": 0.35 if sparse_multiline else max(0.86, min(1.0, 1.0 - (float(lattice_candidates[0]["score"]) if lattice_candidates else 0.0) * 0.7)),
            "connected_joined_runs": min(1.0, len(run_anchors) / max(1, len(row_bands))) if row_bands else 0.0,
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
        component_evidence = extract_components(selected_mask, source_hash=source_hash, row_bands=row_bands, run_anchors=run_anchors)
        unassigned = [
            component.component_id
            for component in component_evidence["components"]
            if not component.candidate_run_ids
        ]
        component_evidence = {
            **component_evidence,
            "unassigned_component_ids": unassigned,
            "component_ownership_complete": not unassigned,
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
        }
    selected_hash = selected_meta["mask_sha256"] if selected_meta else ""
    projection_evidence = {
        "row_projection": row_projection.tolist(),
        "column_projection": column_projection.tolist(),
        "row_groups": [list(group) for group in row_bands_raw],
        "x_groups": [list(group) for group in x_groups],
        "autocorrelation": autocorrelation[:16],
        "selected_mask_sha256": selected_hash,
        "foreground_margin": float(configuration["foreground_margin"]),
        "measurement": "source_raster_projection",
        "row_band_quality": row_band_quality,
        "periodic_row_candidates": periodic_row_candidates,
    }
    if selected_mask is None:
        rejection.extend(["geometry_unresolved", "component_evidence_missing"])
    elif not row_bands or not run_anchors:
        rejection.append("geometry_unresolved")
    elif component_evidence.get("unassigned_component_ids"):
        rejection.append("component_unowned")
    status = "proved" if selected_mask is not None and row_bands and run_anchors and not rejection else "rejected"
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

    def __init__(self, source_path: str | Path, geometry: GeometryEvidenceBundle | Mapping[str, Any], *, mode: str | None = None):
        self.source_path = Path(source_path)
        self.geometry = geometry
        self.mode = mode

    def _mapping(self) -> Mapping[str, Any]:
        if isinstance(self.geometry, GeometryEvidenceBundle):
            if self.mode in {"fixed_lattice", "shaped_runs"}:
                selected_mode = self.mode
            else:
                # Select only from the measured bundle proofs.  This fallback
                # is deliberately conservative and never consults a corpus
                # mode or transcript.
                from .fixed_lattice import assess_fixed_lattice
                from .shaped_runs import assess_shaped_runs

                fixed = assess_fixed_lattice(self.geometry.fixed_evidence())
                shaped = assess_shaped_runs(self.geometry.shaped_evidence())
                selected_mode = "fixed_lattice" if fixed.passed and fixed.score - shaped.score >= 0.05 else "shaped_runs"
            return self.geometry.geometry_mapping(selected_mode)
        mapping = self.geometry
        # Accept a serialized evidence bundle as a convenience, while still
        # selecting only from its measured candidates.  This path is useful
        # for a process boundary where the ndarray is intentionally absent;
        # the pinned foreground recipe below reconstructs it from the source.
        if "mode" not in mapping and (mapping.get("fixed_lattice_candidates") or mapping.get("shaped_run_candidates")):
            from .fixed_lattice import assess_fixed_lattice
            from .shaped_runs import assess_shaped_runs

            fixed_items = mapping.get("fixed_lattice_candidates") or []
            shaped_items = mapping.get("shaped_run_candidates") or []
            fixed_item = dict(fixed_items[0]) if fixed_items else {}
            shaped_item = dict(shaped_items[0]) if shaped_items else {}
            fixed = assess_fixed_lattice(fixed_item)
            shaped = assess_shaped_runs(shaped_item)
            selected_mode = self.mode or ("fixed_lattice" if fixed.passed and fixed.score - shaped.score >= 0.05 else "shaped_runs")
            selected = fixed_item if selected_mode == "fixed_lattice" else shaped_item
            return {
                **selected,
                "mode": selected_mode,
                "source_sha256": mapping.get("source_sha256", ""),
                "geometry_evidence_hash": mapping.get("output_hash", ""),
                "selected_foreground": dict(mapping.get("selected_foreground") or {}),
                "selected_foreground_mask_sha256": mapping.get("projection_evidence", {}).get("selected_mask_sha256", ""),
                "geometry_proven": mapping.get("status") == "proved",
            }
        return mapping

    def build(self) -> dict[str, Any]:
        source_pixels, source_hash = load_rgb(self.source_path)
        geometry = self._mapping()
        expected = geometry.get("source_sha256") or geometry.get("input_hashes", {}).get("source")
        if expected and source_hash != expected:
            raise ValueError("recognition input source hash mismatch")
        mode = str(geometry.get("mode", "unresolved"))
        if mode not in {"fixed_lattice", "shaped_runs"} or not geometry.get("geometry_proven", False):
            raise ValueError("recognition inputs require one proved geometry authority")
        if mode == "fixed_lattice":
            quality = geometry.get("row_band_quality") or {}
            if quality.get("periodic_baselines_proven") is False:
                raise ValueError("recognition inputs require periodic baseline coverage")
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
            anchors = [
                {
                    "run_id": f"row-r{int(row.get('row_index', index)):03d}",
                    "row_index": int(row.get("row_index", index)),
                    "x0": 0,
                    "x1": source_pixels.shape[1],
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
        components = extract_components(mask, source_hash=source_hash, row_bands=geometry.get("row_bands", []), run_anchors=anchors)
        unassigned = [
            component.component_id
            for component in components["components"]
            if not component.candidate_run_ids
        ]
        if unassigned:
            raise ValueError(f"component_unowned:{','.join(unassigned)}")
        runs: list[dict[str, Any]] = []
        for anchor in anchors:
            x0, x1 = max(0, int(anchor["x0"])), min(source_pixels.shape[1], int(anchor["x1"]))
            y0, y1 = max(0, int(anchor["y0"])), min(source_pixels.shape[0], int(anchor["y1"]))
            if x1 <= x0 or y1 <= y0:
                continue
            strip = source_pixels[y0:y1, x0:x1]
            binary = mask[y0:y1, x0:x1]
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
        payload = {
            "source_sha256": source_hash,
            "geometry_hash": geometry.get("geometry_evidence_hash") or geometry.get("geometry_hash", ""),
            "foreground_mask_sha256": _mask_hash(mask),
            "mode": mode,
            "components_hash": components["component_hash"],
            "runs": runs,
            "provenance": {
                "source_only": True,
                "transcript_input": False,
                "visual_layout_input": False,
                "emoji_sequence_input": False,
            },
        }
        payload["input_hash"] = sha256_bytes(canonical_bytes(payload))
        return payload


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
