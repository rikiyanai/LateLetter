#!/usr/bin/env python3
"""Decode fixed-cell raster ASCII by joint row sequence, not isolated-cell OCR.

This decoder is deliberately a separate pipeline from ``ocr_monospace_cells.py``.  It treats
the cell lattice as a coordinate system, but learns glyph evidence from repeated source shapes
and scores each complete row with overlapping three-cell windows.  A cell can therefore be
explained as neighbour spill without being forced to own the ink at its boundary.

The decoder is deterministic and fail-closed:

* templates are screenshot-local but leave-one-out (a cell never validates itself);
* a candidate's score includes row-neighbour continuity and unexplained-ink cost;
* low-margin rows emit ``?`` rather than choosing a convenient glyph; and
* the output is a new immutable machine candidate, never an edit to an earlier attempt.

This is structural recognition evidence.  It does not use source pixels as a render candidate
and it does not establish font/raster parity.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import math
import os
import sys
import unicodedata
from dataclasses import dataclass, replace
from pathlib import Path

import numpy as np
from PIL import Image


ALPHABET = tuple("()[]/\\|_.:-=~^',`")
UNKNOWN = "?"
DECODER_VERSION = "row-joint-11-same-row-ownership-unicode-boundary"
BEAM_WIDTH = 96
MIN_MARGIN = 0.35


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


@dataclass(frozen=True)
class Cell:
    row: int
    column: int
    mask: np.ndarray
    window: np.ndarray
    topology: dict[str, object]
    seed: str | None
    component_ids: tuple[int, ...] = ()
    forced_blank: bool = False
    ownership_reason: str | None = None
    pixel_bounds: tuple[int, int, int, int] = (0, 0, 0, 0)
    component_part_ids: tuple[tuple[int, ...], ...] = ()
    baseline_local: float = 0.0


@dataclass(frozen=True)
class Template:
    glyph: str
    row: int
    column: int
    mask: np.ndarray
    normalized: np.ndarray
    window_normalized: np.ndarray
    top_ratio: float
    bottom_ratio: float
    left_edge: int
    right_edge: int


def connected_components(mask: np.ndarray) -> list[list[tuple[int, int]]]:
    ys, xs = np.where(mask)
    visited = np.zeros(mask.shape, dtype=bool)
    result: list[list[tuple[int, int]]] = []
    for start_y, start_x in zip(ys.tolist(), xs.tolist()):
        if visited[start_y, start_x]:
            continue
        stack = [(start_y, start_x)]
        visited[start_y, start_x] = True
        component: list[tuple[int, int]] = []
        while stack:
            cy, cx = stack.pop()
            component.append((cy, cx))
            for dy in (-1, 0, 1):
                for dx in (-1, 0, 1):
                    if not dx and not dy:
                        continue
                    ny, nx = cy + dy, cx + dx
                    if 0 <= ny < mask.shape[0] and 0 <= nx < mask.shape[1] and mask[ny, nx] and not visited[ny, nx]:
                        visited[ny, nx] = True
                        stack.append((ny, nx))
        result.append(component)
    return result


def topology(mask: np.ndarray) -> dict[str, object]:
    ys, xs = np.where(mask)
    if not len(xs):
        return {"bbox": None, "width": 0, "height": 0, "ink_pixels": 0, "components": 0, "edge_contacts": []}
    left, right, top, bottom = int(xs.min()), int(xs.max()), int(ys.min()), int(ys.max())
    edges = []
    if left == 0:
        edges.append("left")
    if right == mask.shape[1] - 1:
        edges.append("right")
    if top == 0:
        edges.append("top")
    if bottom == mask.shape[0] - 1:
        edges.append("bottom")
    return {
        "bbox": {"left": left, "top": top, "right": right, "bottom": bottom},
        "width": right - left + 1,
        "height": bottom - top + 1,
        "ink_pixels": int(len(xs)),
        "components": len(connected_components(mask)),
        "edge_contacts": edges,
    }


def normalized_shape(mask: np.ndarray, size: int = 24) -> np.ndarray:
    """Place the cropped shape in a fixed square without using source pixels as art."""
    ys, xs = np.where(mask)
    output = np.zeros((size, size), dtype=bool)
    if not len(xs):
        return output
    cropped = mask[ys.min() : ys.max() + 1, xs.min() : xs.max() + 1]
    scale = min((size - 4) / max(cropped.shape[0], 1), (size - 4) / max(cropped.shape[1], 1))
    height = max(1, round(cropped.shape[0] * scale))
    width = max(1, round(cropped.shape[1] * scale))
    image = Image.fromarray(np.where(cropped, 255, 0).astype(np.uint8), mode="L")
    resized = np.asarray(image.resize((width, height), Image.Resampling.NEAREST)) > 0
    y0 = (size - height) // 2
    x0 = (size - width) // 2
    output[y0 : y0 + height, x0 : x0 + width] = resized
    return output


def recognition_shape_key(mask: np.ndarray) -> str:
    """Return a position-independent key for an exact normalized source silhouette.

    Width/height/ink/component counts are useful diagnostics but are not an identity: a slash,
    bracket fragment, and diagonal spill can share all four.  Consensus is allowed to transfer a
    glyph label only between the same normalized binary shape, while retaining dimensions to
    prevent unrelated resize collisions.  Absolute row position is intentionally excluded.
    """
    info = topology(mask)
    normalized = normalized_shape(mask, size=32)
    digest = hashlib.sha256(normalized.tobytes()).hexdigest()
    return (
        f"{int(info.get('width', 0))}x{int(info.get('height', 0))}:"
        f"{int(info.get('components', 0))}:{digest}"
    )


def horizontal_band(mask: np.ndarray, baseline: float) -> tuple[str | None, str]:
    ys, xs = np.where(mask)
    if not len(xs):
        return " ", "blank"
    row_counts = mask.sum(axis=1)
    width = int(xs.max() - xs.min() + 1)
    height = int(ys.max() - ys.min() + 1)
    components = len(connected_components(mask))
    if components != 1 or height > 3 or width < 4:
        return None, "not_horizontal_seed"
    if int(row_counts.max()) < max(4, math.ceil(width * 0.8)):
        return None, "not_horizontal_seed"
    center = float(ys.mean() + 0.5)
    if center <= baseline - 2:
        return "-", "horizontal_upper_seed"
    if center >= baseline + 2:
        return "_", "horizontal_lower_seed"
    return None, "horizontal_middle_ambiguous"


def seed_geometry(mask: np.ndarray, baseline: float) -> tuple[str | None, str]:
    """Reuse the canonical structural classifier for anchors, never its prose-OCR fallback.

    The first prototype duplicated a partial classifier here.  That created two authorities:
    the established cell pipeline called a comma/apostrophe/caret correctly while the row
    decoder called the same bitmap ``=`` or ``~``.  A joint decoder may change an *unresolved*
    cell, but it must start from one deterministic geometry vocabulary.  Importing the module
    keeps the old owner out of the new path; only ``classify_shape`` is used, and confidence
    below the shared 0.85 gate remains unknown.
    """
    if not np.asarray(mask).any():
        return " ", "blank_seed"
    script_dir = Path(__file__).resolve().parent
    if str(script_dir) not in sys.path:
        sys.path.insert(0, str(script_dir))
    try:
        from ocr_monospace_cells import classify_shape
    except ImportError:
        module_path = script_dir / "ocr_monospace_cells.py"
        spec = importlib.util.spec_from_file_location("ocr_monospace_cells", module_path)
        if spec is None or spec.loader is None:
            return None, "canonical_classifier_unavailable"
        module = importlib.util.module_from_spec(spec)
        sys.modules.setdefault("ocr_monospace_cells", module)
        spec.loader.exec_module(module)
        classify_shape = module.classify_shape
    glyph, confidence, reason = classify_shape(mask, baseline)
    if glyph == " ":
        return " ", "blank_seed"
    # A compact upper diagonal may be an apostrophe, but it may also be a cut-off slash or
    # backslash.  Defer it to the row/window ownership pass instead of accepting shape alone.
    if glyph == "'":
        return None, f"canonical_{reason}_deferred_punctuation"
    if glyph is not None and float(confidence) >= 0.85:
        return str(glyph), f"canonical_{reason}"
    return None, f"canonical_{reason}"


def build_templates(cells: list[Cell]) -> dict[str, list[Template]]:
    templates: dict[str, list[Template]] = {}
    for cell in cells:
        if cell.seed in (None, " "):
            continue
        ys, xs = np.where(cell.mask)
        if not len(xs):
            continue
        templates.setdefault(str(cell.seed), []).append(
            Template(
                glyph=str(cell.seed),
                row=cell.row,
                column=cell.column,
                mask=cell.mask,
                normalized=normalized_shape(cell.mask),
                window_normalized=normalized_shape(cell.window, size=32),
                top_ratio=float(ys.min() / max(cell.mask.shape[0] - 1, 1)),
                bottom_ratio=float(ys.max() / max(cell.mask.shape[0] - 1, 1)),
                left_edge=int(xs.min() == 0),
                right_edge=int(xs.max() == cell.mask.shape[1] - 1),
            )
        )
    return templates


def template_similarity(cell: Cell, template: Template) -> float:
    target = normalized_shape(cell.mask)
    union = np.logical_or(target, template.normalized).sum()
    if not union:
        return 1.0
    intersection = np.logical_and(target, template.normalized).sum()
    shape_score = float(intersection / union)
    ys, xs = np.where(cell.mask)
    if not len(xs):
        return 0.0
    top_ratio = float(ys.min() / max(cell.mask.shape[0] - 1, 1))
    bottom_ratio = float(ys.max() / max(cell.mask.shape[0] - 1, 1))
    vertical_score = math.exp(-2.0 * (abs(top_ratio - template.top_ratio) + abs(bottom_ratio - template.bottom_ratio)))
    edge_score = 1.0 if (int(xs.min() == 0), int(xs.max() == cell.mask.shape[1] - 1)) == (template.left_edge, template.right_edge) else 0.0
    window_target = normalized_shape(cell.window, size=32)
    window_union = np.logical_or(window_target, template.window_normalized).sum()
    window_score = (
        float(np.logical_and(window_target, template.window_normalized).sum() / window_union)
        if window_union
        else 1.0
    )
    # The cell mask identifies the glyph; the overlapping window is deliberately weaker
    # evidence that resolves spill/ownership and repeated row context without allowing a
    # neighbouring horse leg to masquerade as the target character.
    exact_repeated_shape = shape_score >= 0.999 and template.glyph not in ("-", "_")
    exact_bonus = 0.40 if exact_repeated_shape else 0.0
    return min(
        1.0,
        0.55 * shape_score + 0.20 * vertical_score + 0.10 * edge_score + 0.15 * window_score + exact_bonus,
    )


def edge_continuity(left: Cell, right: Cell) -> float:
    if not left.mask.size or not right.mask.size:
        return 0.0
    left_edge = left.mask[:, -1]
    right_edge = right.mask[:, 0]
    overlap = int(np.logical_and(left_edge, right_edge).sum())
    return min(1.0, overlap / 3.0)


def candidate_domain(cell: Cell, templates: dict[str, list[Template]]) -> list[str]:
    # A high-signal structural seed is an anchor, not one vote among every glyph learned from
    # the screenshot.  The previous prototype let a template with a superficially similar
    # silhouette replace a proven ``|``/``~``/``=`` and produced nonsense such as ``\=\``.  Joint
    # decoding is for unresolved ownership and identity; it must not undo deterministic
    # geometry.  Blank is only a legal candidate for an empty cell (or an explicitly tiny edge
    # fragment, where ownership is still allowed to win by sequence context).
    # A proven spill is authoritative.  A geometric seed such as ``.`` can remain in the crop,
    # but it belongs to the neighbouring row and must serialize as blank.  Only an explicit
    # component-cleanup reassignment clears ``forced_blank`` before this function runs.
    if cell.forced_blank:
        return [" "]
    # A recovered seed is evidence that this cell owns a substantive glyph.  It wins only after
    # cleanup has explicitly cleared any stale spill state.
    if cell.seed not in (None, " "):
        return [str(cell.seed), UNKNOWN]
    if not cell.mask.any():
        return [" "]
    # Cleanup may retain ink without being able to name the retained component.  A compound or
    # edge-contact crop is not eligible for screenshot-local template guessing: it is exactly how
    # a diagonal continuation was previously promoted to an apostrophe.  Preserve the source
    # evidence as an explicit unknown instead of deleting it or inventing a glyph.
    if str(cell.ownership_reason or "").startswith("component_spill_removed:"):
        return [UNKNOWN]
    if str(cell.ownership_reason or "").startswith("punctuation_continuity_unproven"):
        return [UNKNOWN]
    if int(cell.topology.get("components", 0)) != 1 or cell.topology.get("edge_contacts"):
        return [UNKNOWN]
    labels = sorted(templates)
    if " " in labels:
        labels.remove(" ")
    # A sparse edge fragment may belong to a neighbour.  Do not erase a substantive cell just
    # because it touches a boundary.
    topology_info = cell.topology
    if int(topology_info.get("ink_pixels", 0)) <= 4 and topology_info.get("edge_contacts"):
        labels.insert(0, " ")
    labels.append(UNKNOWN)
    return labels


def unary_score(cell: Cell, glyph: str, templates: dict[str, list[Template]]) -> float:
    if glyph == " ":
        return 2.0 if not cell.mask.any() else -1.0
    if glyph == UNKNOWN:
        return -0.4 if cell.mask.any() else -3.0
    if not cell.mask.any():
        return -3.0
    if cell.seed == glyph:
        return 3.5
    options = [item for item in templates.get(glyph, []) if (item.row, item.column) != (cell.row, cell.column)]
    if not options:
        return -1.5
    similarity = max(template_similarity(cell, item) for item in options)
    if similarity >= 0.999 and glyph not in ("-", "_"):
        # An exact normalized shape learned from another cell is stronger than a weak row
        # transition.  Leave-one-out exclusion guarantees this is not self-validation.
        return 4.0
    return 4.0 * similarity - 1.0


def pair_score(left: Cell, right: Cell, left_glyph: str, right_glyph: str) -> float:
    continuity = edge_continuity(left, right)
    left_nonblank = left_glyph not in (" ", UNKNOWN)
    right_nonblank = right_glyph not in (" ", UNKNOWN)
    score = 0.0
    if continuity:
        score += 1.0 if left_nonblank and right_nonblank else -0.75
    if left.mask.any() and right.mask.any() and not continuity and left_nonblank and right_nonblank:
        score += 0.2
    if left_glyph == right_glyph and left_glyph not in (" ", UNKNOWN):
        score += 0.35
    shared_components = set(left.component_ids).intersection(right.component_ids)
    if shared_components:
        # A connected source component crossing a lattice edge cannot be simultaneously
        # explained as blank on one side and ink on the other.  Keeping both cells in the
        # sequence is preferable to silently deleting a boundary fragment.
        if (left_glyph == " ") != (right_glyph == " "):
            score -= 1.5
        elif left_glyph != UNKNOWN and right_glyph != UNKNOWN:
            score += 0.25
    return score


def decode_row(row_cells: list[Cell], templates: dict[str, list[Template]]) -> tuple[list[str], list[float], dict[str, object]]:
    states: list[tuple[float, list[str]]] = [(0.0, [])]
    candidate_counts = []
    for cell in row_cells:
        domain = candidate_domain(cell, templates)
        candidate_counts.append(len(domain))
        expanded: list[tuple[float, list[str]]] = []
        for score, sequence in states:
            previous = sequence[-1] if sequence else None
            for glyph in domain:
                total = score + unary_score(cell, glyph, templates)
                if previous is not None:
                    total += pair_score(row_cells[len(sequence) - 1], cell, previous, glyph)
                expanded.append((total, sequence + [glyph]))
        expanded.sort(key=lambda item: (-item[0], "".join(item[1])))
        states = expanded[:BEAM_WIDTH]
    if not states:
        return [UNKNOWN] * len(row_cells), [0.0] * len(row_cells), {"candidate_counts": candidate_counts}
    best_score, best_sequence = states[0]
    second_score = states[1][0] if len(states) > 1 else best_score - 1.0
    margin = best_score - second_score
    # A row-level margin is stronger evidence than an isolated cell confidence.  Recompute a
    # local margin by comparing each position against all alternatives while holding the chosen
    # prefix/suffix fixed; this avoids accepting one convenient glyph in an otherwise ambiguous
    # sequence.
    confidences: list[float] = []
    output = list(best_sequence)
    for index, cell in enumerate(row_cells):
        alternatives = candidate_domain(cell, templates)
        chosen = output[index]
        chosen_unary = unary_score(cell, chosen, templates)
        alternative_scores = [unary_score(cell, item, templates) for item in alternatives if item != chosen]
        local_margin = chosen_unary - max(alternative_scores, default=chosen_unary - 1.0)
        confidence = max(0.0, min(1.0, (local_margin + 1.0) / 3.0))
        confidences.append(confidence)
        # A low row margin only says that one *unresolved* sequence has alternatives.  It must
        # not erase deterministic geometry anchors elsewhere in that row; doing so was the
        # source of whole rows of ``?`` in attempts 032–036.  Forced spill blanks are likewise
        # already proven by neighbouring ownership.
        if cell.seed is None and not cell.forced_blank and (
            margin < MIN_MARGIN or local_margin < MIN_MARGIN or confidence < 0.85
        ):
            if cell.mask.any():
                output[index] = UNKNOWN
                confidences[index] = 0.0
    return output, confidences, {"score": best_score, "row_margin": margin, "candidate_counts": candidate_counts}


def apply_repeated_topology_consensus(
    cells: list[Cell], decoded: list[str], confidences: list[float], columns: int
) -> list[str]:
    """Resolve an unknown only from another independently resolved identical silhouette.

    This is a screenshot-wide consistency check, not an absolute-coordinate rule.  The source
    crop may shift vertically, so the exact normalized-shape key excludes absolute position while
    retaining structural dimensions and component topology.  Conflicting labels or no
    high-confidence exemplar leave the cell as ``?``.
    """
    def eligible(cell: Cell) -> bool:
        # A composite/edge-contact crop is precisely the evidence that may be a continuation of
        # ``/`` or ``\\``.  Never let a clean exemplar relabel that ambiguous crop by consensus.
        if int(cell.topology.get("components", 0)) != 1 or cell.topology.get("edge_contacts"):
            return False
        if str(cell.ownership_reason or "").startswith("component_spill_removed:"):
            return False
        if str(cell.ownership_reason or "").startswith("punctuation_continuity_unproven"):
            return False
        return not cell.component_ids or len(cell.component_ids) == 1

    groups: dict[str, set[str]] = {}
    for cell, glyph, confidence in zip(cells, decoded, confidences):
        if glyph in (" ", UNKNOWN) or confidence < 0.85 or cell.forced_blank or not eligible(cell):
            continue
        key = recognition_shape_key(cell.mask)
        groups.setdefault(key, set()).add(glyph)
    output = list(decoded)
    for index, (cell, glyph) in enumerate(zip(cells, decoded)):
        if glyph != UNKNOWN or not eligible(cell):
            continue
        key = recognition_shape_key(cell.mask)
        labels = groups.get(key, set())
        if len(labels) == 1:
            output[index] = next(iter(labels))
            confidences[index] = 0.86
    return output


def segment(source: Path, calibration: dict[str, object]) -> list[Cell]:
    with Image.open(source) as opened:
        pixels = np.asarray(opened.convert("RGB"))
    bg = np.asarray(calibration["canvas"]["background_rgb"])
    ink = np.max(np.abs(pixels.astype(int) - bg), axis=2) > int(calibration["normalization"]["ink_threshold_l1"])
    for column in calibration.get("guide_columns_px", []):
        if 0 <= int(column) < ink.shape[1]:
            ink[:, int(column)] = False
    grid = calibration["grid"]
    columns, rows = int(grid["columns"]), int(grid["rows"])
    origin, baseline, advance_x, advance_y = (float(grid[key]) for key in ("origin_x_px", "first_baseline_y_px", "cell_advance_x_px", "line_height_px"))
    top, bottom = int(grid["cell_crop_top_offset_px"]), int(grid["cell_crop_bottom_offset_px"])
    cells: list[Cell] = []
    for row in range(rows):
        y0, y1 = round(baseline + row * advance_y + top), round(baseline + row * advance_y + bottom)
        for column in range(columns):
            x0, x1 = round(origin + column * advance_x), round(origin + (column + 1) * advance_x)
            xa, xb, ya, yb = max(0, x0), min(ink.shape[1], x1), max(0, y0), min(ink.shape[0], y1)
            mask = ink[ya:yb, xa:xb] if xa < xb and ya < yb else np.zeros((1, 1), dtype=bool)
            wx0, wx1 = round(origin + (column - 1) * advance_x), round(origin + (column + 2) * advance_x)
            wxa, wxb = max(0, wx0), min(ink.shape[1], wx1)
            window = ink[ya:yb, wxa:wxb] if wxa < wxb and ya < yb else np.zeros((1, 1), dtype=bool)
            seed, seed_reason = seed_geometry(mask, baseline + row * advance_y - y0)
            forced_blank, ownership_reason = ownership_decision(
                ink,
                x0,
                x1,
                y0,
                y1,
                mask,
                seed,
                seed_reason,
            )
            cells.append(
                Cell(
                    row,
                    column,
                    mask.copy(),
                    window.copy(),
                    topology(mask),
                    seed,
                    forced_blank=forced_blank,
                    ownership_reason=ownership_reason,
                    pixel_bounds=(x0, y0, x1, y1),
                    baseline_local=baseline + row * advance_y - y0,
                )
            )
    cells = assign_global_component_ids(cells, ink)
    cells = resolve_cross_row_spill(cells, columns)
    cells = resolve_component_spill_seeds(cells, columns)
    cells = resolve_same_row_horizontal_spill(cells, columns)
    cells = resolve_repeated_baseline_punctuation(cells)
    return resolve_row_horizontal_bands(cells, columns)


def horizontal_band_candidate(mask: np.ndarray) -> float | None:
    """Return the vertical centre of a single strong horizontal stroke, if present."""
    ys, xs = np.where(mask)
    if not len(xs) or len(connected_components(mask)) != 1:
        return None
    width = int(xs.max() - xs.min() + 1)
    height = int(ys.max() - ys.min() + 1)
    # Scaled references may rasterize a horizontal band across four rows; keep it in the same
    # ownership/row-order family as the two- and three-row bands used by the horse fixture.
    if height > 4 or width < 4:
        return None
    if int(mask.sum(axis=1).max()) < max(4, math.ceil(width * 0.8)):
        return None
    return float(ys.mean() + 0.5)


def compact_baseline_punctuation(mask: np.ndarray, baseline: float) -> str | None:
    """Return punctuation only when compact diagonal geometry and baseline agree.

    Positive ``dx/dy`` is the backtick (`` ` ``); negative slope is the apostrophe.  Treating
    both orientations as ``'`` was the source of the horse-sheet false apostrophes.
    """
    ys, xs = np.where(mask)
    if not len(xs):
        return None
    left, right, top, bottom = xs.min(), xs.max(), ys.min(), ys.max()
    width, height = int(right - left + 1), int(bottom - top + 1)
    if not (4 <= height <= 7 and width <= 8 and len(xs) >= 4):
        return None
    slope = np.polyfit(ys, xs, 1)[0] if len(xs) > 1 else 0.0
    if abs(slope) < 0.15:
        return None
    center = float(ys.mean() + 0.5)
    if center <= baseline - 1.5:
        return "`" if slope > 0 else "'"
    if center >= baseline + 1.5:
        return ","
    return None


def punctuation_window_context_proven(cells: list[Cell], index: int, columns: int, glyph: str) -> bool:
    """Require row/window context before naming a compact diagonal punctuation mark.

    Component isolation is not enough: antialiasing can disconnect a diagonal continuation into
    a quote-shaped crop.  An upper quote is accepted only inside a complete delimiter window
    (diagonal anchors within two slots on both sides) and with no diagonal continuation in the
    adjacent row window.  Otherwise source ink remains evidence and becomes ``?``.
    """
    cell = cells[index]
    row, column = cell.row, cell.column
    by_key = {(item.row, item.column): item for item in cells}
    diagonal = {"/", "\\"}
    left = [by_key.get((row, column - distance)) for distance in (1, 2)]
    right = [by_key.get((row, column + distance)) for distance in (1, 2)]
    if glyph in ("'", "`"):
        left_anchor = any(item is not None and item.seed in diagonal for item in left)
        right_anchor = any(item is not None and item.seed in diagonal for item in right)
        if not (left_anchor and right_anchor):
            return False
        for adjacent_row in (row - 1, row + 1):
            for distance in (0, 1):
                for adjacent_column in (column - distance, column + distance):
                    item = by_key.get((adjacent_row, adjacent_column))
                    if item is not None and item.seed in diagonal:
                        return False
        return True
    # Lower punctuation is accepted only when it is not sitting on a diagonal continuation.
    for adjacent_row in (row - 1, row + 1):
        for distance in (0, 1):
            for adjacent_column in (column - distance, column + distance):
                item = by_key.get((adjacent_row, adjacent_column))
                if item is not None and item.seed in diagonal:
                    return False
    return True


def resolve_repeated_baseline_punctuation(cells: list[Cell]) -> list[Cell]:
    """Use baseline-relative punctuation only when the exact silhouette repeats consistently.

    An isolated diagonal fragment remains unresolved. Repetition supplies the missing identity
    evidence, while the measured baseline distinguishes an upper apostrophe from a lower comma;
    no absolute row/column or horse-specific rule is involved.
    """
    # A punctuation-shaped crop is not enough: a slash/parenthesis can leave a compact diagonal
    # fragment in the same crop.  Require a complete, unshared source component and no crop-edge
    # contact before allowing repetition to name it.  Otherwise the cell remains unresolved.
    component_cell_counts: dict[int, int] = {}
    for cell in cells:
        for component_id in set(cell.component_ids):
            component_cell_counts[component_id] = component_cell_counts.get(component_id, 0) + 1

    candidates: list[tuple[int, str]] = []
    for index, cell in enumerate(cells):
        if cell.seed is not None or cell.forced_blank:
            continue
        if int(cell.topology.get("components", 0)) != 1:
            continue
        if cell.topology.get("edge_contacts"):
            continue
        if len(cell.component_ids) != 1 or component_cell_counts.get(cell.component_ids[0], 0) != 1:
            continue
        glyph = compact_baseline_punctuation(cell.mask, cell.baseline_local)
        if glyph is None:
            continue
        candidates.append((index, glyph))
    output = list(cells)
    columns = max((cell.column for cell in cells), default=-1) + 1
    # Antialiasing and subpixel phase can move one or two source pixels while the glyph remains
    # the same.  Exact masks are ideal for ordinary template transfer, but too strict for this
    # compact punctuation family.  Permit a high normalized-shape overlap only between two
    # independently proven candidates with the same baseline-derived label.
    normalized = {index: normalized_shape(cells[index].mask) for index, _ in candidates}
    for index, glyph in candidates:
        if not punctuation_window_context_proven(cells, index, columns, glyph):
            output[index] = replace(
                output[index],
                seed=None,
                ownership_reason="punctuation_continuity_unproven",
            )
            continue
        has_exemplar = any(
            other_index != index
            and other_glyph == glyph
            and float(
                np.logical_and(normalized[index], normalized[other_index]).sum()
                / max(np.logical_or(normalized[index], normalized[other_index]).sum(), 1)
            )
            >= 0.80
            for other_index, other_glyph in candidates
        )
        if has_exemplar or glyph == "`":
            output[index] = replace(
                output[index],
                seed=glyph,
                ownership_reason=(
                    "punctuation_window_context"
                    if glyph == "`" and not has_exemplar
                    else "repeated_baseline_punctuation_consensus"
                ),
            )
    return output


def resolve_row_horizontal_bands(cells: list[Cell], columns: int) -> list[Cell]:
    """Resolve unseeded horizontal bands by their order within a complete row.

    A dash and underscore share the same horizontal topology.  Their useful invariant is the
    row-relative vertical order: the lowest strong band is `_`; a distinct band above it is `-`.
    This is derived per row from the evidence graph, not keyed to horse rows or absolute pixel
    coordinates.  A row with no second band remains unknown rather than receiving a threshold
    guess.
    """
    output = list(cells)
    for start in range(0, len(cells), columns):
        row_cells = cells[start : start + columns]
        bands: list[tuple[int, float, str | None]] = []
        for index, cell in enumerate(row_cells):
            center = horizontal_band_candidate(cell.mask)
            if center is not None and not cell.forced_blank:
                bands.append((index, center, cell.seed if cell.seed in ("-", "_") else None))
        if len(bands) < 2:
            continue
        lowest = max(center for _, center, _ in bands)
        for index, center, seed in bands:
            cell = row_cells[index]
            if cell.seed is not None:
                continue
            glyph = "_" if center >= lowest - 1.5 else "-"
            output[start + index] = replace(
                cell,
                seed=glyph,
                ownership_reason="row_horizontal_band_order",
            )
    return output


def resolve_component_spill_seeds(cells: list[Cell], columns: int) -> list[Cell]:
    """Remove only components proven to belong to the preceding row, then classify the rest.

    A crop can contain a previous-row terminal plus the actual current-row glyph.  Treating the
    entire crop as a composite loses the glyph; treating the dominant component as authoritative
    loses ownership evidence.  This keeps the original topology/ownership record, but supplies a
    recognition mask containing only components not proven to continue from the previous row.
    """
    output = list(cells)
    for index, cell in enumerate(cells):
        if int(cell.topology.get("components", 0)) < 2 or index < columns:
            continue
        previous_ids = set(cells[index - columns].component_ids)
        parts = connected_components(cell.mask)
        retained_parts: list[list[tuple[int, int]]] = []
        retained_part_ids: list[tuple[int, ...]] = []
        removed = False
        for part, part_ids in zip(parts, cell.component_part_ids):
            ys = [point[0] for point in part]
            top_spill = min(ys) <= 2 and bool(set(part_ids).intersection(previous_ids))
            if top_spill:
                removed = True
            else:
                retained_parts.append(part)
                retained_part_ids.append(tuple(sorted(set(part_ids))))
        if not removed or not retained_parts:
            continue
        reduced = np.zeros_like(cell.mask)
        for part in retained_parts:
            for y, x in part:
                reduced[y, x] = True
        seed, reason = seed_geometry(reduced, cell.baseline_local)
        output[index] = replace(
            cell,
            mask=reduced,
            topology=topology(reduced),
            component_ids=tuple(sorted({item for ids in retained_part_ids for item in ids})),
            component_part_ids=tuple(retained_part_ids),
            seed=seed,
            # Retained ink is never a blank.  The old code preserved forced_blank here, so a
            # recovered real glyph was later hidden by candidate_domain and omitted from TXT.
            forced_blank=False,
            ownership_reason="component_spill_removed:" + reason,
        )
    return output


def resolve_same_row_horizontal_spill(cells: list[Cell], columns: int) -> list[Cell]:
    """Remove a joined horizontal run from a neighbouring diagonal cell.

    At a scaled monospace pitch, a dash/underscore can overhang its left boundary by a few
    pixels.  The cell at the start of the run then contains two disconnected components: its
    own diagonal and the next cell's horizontal stroke.  Treating that compound crop as an
    unknown loses an otherwise obvious diagonal.  Ownership is proven only when the same global
    component continues into another cell of the same row that has a full horizontal-band seed;
    a short edge-only fragment is then blank spill, never a guessed punctuation mark.
    """
    component_locations: dict[int, list[Cell]] = {}
    for cell in cells:
        for component_id in cell.component_ids:
            component_locations.setdefault(component_id, []).append(cell)

    horizontal_ids: set[int] = set()
    for cell in cells:
        if cell.seed not in ("-", "_") or horizontal_band_candidate(cell.mask) is None:
            continue
        horizontal_ids.update(cell.component_ids)

    output = list(cells)
    for index, cell in enumerate(cells):
        parts = connected_components(cell.mask)
        if not parts or not horizontal_ids.intersection(cell.component_ids):
            continue
        removable: list[int] = []
        for part_index, part_ids in enumerate(cell.component_part_ids):
            if not horizontal_ids.intersection(part_ids):
                continue
            locations = component_locations.get(next(iter(horizontal_ids.intersection(part_ids))), [])
            same_row_full_band = any(
                other.row == cell.row
                and other.column != cell.column
                and other.seed in ("-", "_")
                and horizontal_band_candidate(other.mask) is not None
                for other in locations
            )
            ys = [point[0] for point in parts[part_index]]
            xs = [point[1] for point in parts[part_index]]
            part_width = max(xs) - min(xs) + 1 if xs else 0
            cell_width = cell.mask.shape[1]
            is_edge_fragment = part_width < max(4, math.ceil(cell_width * 0.8))
            if same_row_full_band and (len(parts) > 1 or is_edge_fragment):
                removable.append(part_index)
        if not removable:
            continue
        retained = [part for part_index, part in enumerate(parts) if part_index not in removable]
        reduced = np.zeros_like(cell.mask)
        retained_part_ids: list[tuple[int, ...]] = []
        for part, part_ids in zip(retained, (cell.component_part_ids[i] for i in range(len(parts)) if i not in removable)):
            for y, x in part:
                reduced[y, x] = True
            retained_part_ids.append(tuple(sorted(set(part_ids))))
        if not retained:
            output[index] = replace(
                cell,
                mask=reduced,
                topology=topology(reduced),
                seed=" ",
                component_ids=(),
                component_part_ids=(),
                forced_blank=True,
                ownership_reason="same_row_horizontal_spill_proven",
            )
            continue
        seed, reason = seed_geometry(reduced, cell.baseline_local)
        output[index] = replace(
            cell,
            mask=reduced,
            topology=topology(reduced),
            seed=seed,
            component_ids=tuple(sorted({item for ids in retained_part_ids for item in ids})),
            component_part_ids=tuple(retained_part_ids),
            forced_blank=False,
            ownership_reason="same_row_horizontal_spill_removed:" + reason,
        )
    return output


def resolve_cross_row_spill(cells: list[Cell], columns: int) -> list[Cell]:
    """Blank a multi-component crop only when its top and bottom owners prove adjacent rows.

    This is stricter than a pixel-count shortcut.  Each component must be connected to the
    preceding/following row in the complete-image component graph; a genuine two-part glyph with
    no such neighbours remains unresolved.  It addresses the exact row-boundary composites that
    defeated attempts 030/031 without introducing a screenshot-specific coordinate rule.
    """
    output = list(cells)
    for index, cell in enumerate(cells):
        if cell.forced_blank or int(cell.topology.get("components", 0)) < 2:
            continue
        parts = connected_components(cell.mask)
        if len(parts) < 2:
            continue
        top_ids: set[int] = set()
        bottom_ids: set[int] = set()
        for part, part_ids in zip(parts, cell.component_part_ids):
            ys = [point[0] for point in part]
            if min(ys) <= 2:
                top_ids.update(part_ids)
            if max(ys) >= cell.mask.shape[0] - 3:
                bottom_ids.update(part_ids)
        previous_ids = set(cells[index - columns].component_ids) if index >= columns else set()
        next_ids = set(cells[index + columns].component_ids) if index + columns < len(cells) else set()
        # Every component in the crop must be proven spill.  The old ``any top && any bottom``
        # test blanked a crop containing one genuine component plus two neighboring-row fragments.
        # That is the deletion bug: a cell can only become blank when no retained component is
        # left for this row to own.
        part_proofs: list[tuple[bool, bool]] = []
        for part, part_ids in zip(parts, cell.component_part_ids):
            ys = [point[0] for point in part]
            part_proofs.append(
                (
                    min(ys) <= 2 and bool(set(part_ids).intersection(previous_ids)),
                    max(ys) >= cell.mask.shape[0] - 3 and bool(set(part_ids).intersection(next_ids)),
                )
            )
        if (
            part_proofs
            and all(top or bottom for top, bottom in part_proofs)
            and any(top for top, _ in part_proofs)
            and any(bottom for _, bottom in part_proofs)
        ):
            output[index] = replace(
                cell,
                forced_blank=True,
                ownership_reason="bidirectional_component_row_spill_proven",
            )
    return output


def assign_global_component_ids(cells: list[Cell], ink: np.ndarray) -> list[Cell]:
    """Attach IDs from connected components in the complete source, including row crossings.

    A component is not re-cut at a row boundary.  This is the crucial distinction from the old
    cell OCR: a stroke that enters the top or bottom of a crop remains one ownership fact and can
    be explained by an adjacent row's sequence.  The source mask is used only as evidence; no
    component pixels are copied into a candidate render.
    """
    labels = np.full(ink.shape, -1, dtype=int)
    next_id = 0
    for start_y, start_x in zip(*np.where(ink)):
        if labels[start_y, start_x] >= 0:
            continue
        stack = [(int(start_y), int(start_x))]
        labels[start_y, start_x] = next_id
        while stack:
            cy, cx = stack.pop()
            for dy in (-1, 0, 1):
                for dx in (-1, 0, 1):
                    if not dx and not dy:
                        continue
                    ny, nx = cy + dy, cx + dx
                    if (
                        0 <= ny < ink.shape[0]
                        and 0 <= nx < ink.shape[1]
                        and ink[ny, nx]
                        and labels[ny, nx] < 0
                    ):
                        labels[ny, nx] = next_id
                        stack.append((ny, nx))
        next_id += 1
    output = []
    for cell in cells:
        x0, y0, x1, y1 = cell.pixel_bounds
        xa, xb = max(0, x0), min(ink.shape[1], x1)
        ya, yb = max(0, y0), min(ink.shape[0], y1)
        ids = tuple(sorted(int(item) for item in np.unique(labels[ya:yb, xa:xb]) if item >= 0))
        part_ids: list[tuple[int, ...]] = []
        for part in connected_components(cell.mask):
            global_ids = {
                # `cell.mask` is clipped to (xa, ya) at image edges.  Using the unclipped x0/y0
                # here silently looked up negative or shifted coordinates, dropping ownership
                # IDs from the first row/column and preventing spill proofs from firing.
                int(labels[ya + local_y, xa + local_x])
                for local_y, local_x in part
                if 0 <= ya + local_y < labels.shape[0]
                and 0 <= xa + local_x < labels.shape[1]
                and labels[ya + local_y, xa + local_x] >= 0
            }
            part_ids.append(tuple(sorted(global_ids)))
        output.append(replace(cell, component_ids=ids, component_part_ids=tuple(part_ids)))
    return output


def ownership_decision(
    ink: np.ndarray,
    x0: int,
    x1: int,
    y0: int,
    y1: int,
    cell_mask: np.ndarray,
    seed: str | None,
    seed_reason: str,
) -> tuple[bool, str | None]:
    """Apply only the canonical, source-neighbour ownership proofs before row decoding.

    A row decoder must see a dot/quote that belongs to the next row as *spill*, not as a new
    punctuation token.  These proofs use neighbouring source occupancy, not a per-image glyph
    rule.  If no proof exists the ink remains visible and the cell can become ``?``.
    """
    if not cell_mask.any():
        return False, None
    script_dir = Path(__file__).resolve().parent
    if str(script_dir) not in sys.path:
        sys.path.insert(0, str(script_dir))
    try:
        from ocr_monospace_cells import (
            bidirectional_row_spill_proven,
            edge_fragment,
            neighbouring_ownership_proven,
            row_continuation_proven,
        )
    except ImportError:
        return False, "canonical_ownership_unavailable"
    if bidirectional_row_spill_proven(ink, x0, x1, y0, y1, cell_mask):
        return True, "bidirectional_row_spill_proven"
    if row_continuation_proven(ink, x0, x1, y0, cell_mask) and (
        seed is None or any(
            marker in seed_reason
            for marker in ("geometry_period", "geometry_split_apostrophe", "geometry_ambiguous")
        )
    ):
        return True, "row_boundary_spill_proven"
    if edge_fragment(cell_mask) and neighbouring_ownership_proven(ink, x0, x1, y0, y1, cell_mask):
        return True, "boundary_sidebearing_fragment_proven"
    return False, None


def assign_row_component_ids(cells: list[Cell], columns: int) -> list[Cell]:
    """Attach connected-component ownership evidence without changing cell boundaries.

    Components are found on each complete row after segmentation.  A slash or curved stroke
    that crosses a lattice edge therefore receives one shared ID in both cells; a later row
    sequence can keep the component visible instead of classifying each crop independently.
    IDs are evidence only: they never become glyphs and never authorize source-pixel copying.
    """
    output = list(cells)
    for row_start in range(0, len(cells), columns):
        row_cells = cells[row_start : row_start + columns]
        if not row_cells:
            continue
        height = max(cell.mask.shape[0] for cell in row_cells)
        widths = [cell.mask.shape[1] for cell in row_cells]
        canvas = np.zeros((height, sum(widths)), dtype=bool)
        offsets: list[tuple[int, int]] = []
        x = 0
        for cell, width in zip(row_cells, widths):
            canvas[: cell.mask.shape[0], x : x + width] = cell.mask
            offsets.append((x, x + width))
            x += width
        labels = np.full(canvas.shape, -1, dtype=int)
        next_id = 0
        for start_y, start_x in zip(*np.where(canvas)):
            if labels[start_y, start_x] >= 0:
                continue
            stack = [(int(start_y), int(start_x))]
            labels[start_y, start_x] = next_id
            while stack:
                cy, cx = stack.pop()
                for dy in (-1, 0, 1):
                    for dx in (-1, 0, 1):
                        if not dx and not dy:
                            continue
                        ny, nx = cy + dy, cx + dx
                        if (
                            0 <= ny < canvas.shape[0]
                            and 0 <= nx < canvas.shape[1]
                            and canvas[ny, nx]
                            and labels[ny, nx] < 0
                        ):
                            labels[ny, nx] = next_id
                            stack.append((ny, nx))
            next_id += 1
        for local_index, (x0, x1) in enumerate(offsets):
            ids = tuple(sorted(int(item) for item in np.unique(labels[:, x0:x1]) if item >= 0))
            output[row_start + local_index] = replace(output[row_start + local_index], component_ids=ids)
    return output


def structural_conflict_count(cells: list[Cell]) -> int:
    """Count exact repeated silhouettes that receive inconsistent deterministic seeds.

    Width/height/ink counts alone alias `/` and `\\` (and many diagonal/horizontal composites),
    manufacturing conflicts on a valid alphabet.  The same exact normalized silhouette key used
    for leave-one-out consensus is the ownership unit here.
    """
    clusters: dict[str, set[str]] = {}
    for cell in cells:
        if cell.seed in (None, " ") or cell.forced_blank:
            continue
        key = recognition_shape_key(cell.mask)
        if cell.seed in ("-", "_"):
            # Dash and underscore intentionally share a silhouette; their identity is the
            # baseline-relative band, which the position-independent shape key omits.
            center = horizontal_band_candidate(cell.mask)
            band = "upper" if center is not None and center < cell.baseline_local else "lower"
            key += f":horizontal:{band}"
        clusters.setdefault(key, set()).add(str(cell.seed))
    return sum(1 for labels in clusters.values() if len(labels) > 1)


def forced_blank_conflict_count(cells: list[Cell], decoded: list[str] | None = None) -> int:
    """Count every forced-blank cell that would emit a nonblank glyph.

    The old gate inspected only ``component_spill_removed:`` metadata and missed
    ``row_boundary_spill_proven`` cells whose stale geometric seed serialized as ``.``.  The
    emitted sequence is the authority: any forced blank paired with a non-space glyph is a
    conflict, regardless of the ownership reason.
    """
    if decoded is None:
        decoded = [cell.seed if cell.seed is not None else " " for cell in cells]
    if len(decoded) != len(cells):
        raise ValueError("decoded sequence must contain one glyph per cell")
    return sum(1 for cell, glyph in zip(cells, decoded) if cell.forced_blank and glyph not in (" ", UNKNOWN))


def validate_transcript_binding(
    transcript: str,
    cell_records: list[dict[str, object]],
    columns: int,
    rows: int,
) -> str:
    """Validate that the TXT is exactly the row/cell evidence emitted beside it.

    A path-only manifest is not enough for an immutable attempt: a later edit can leave a
    plausible-looking TXT beside evidence that describes different glyphs.  Build the expected
    rows from the cell records, preserve trailing spaces, and hash the byte sequence that will be
    written.  This catches both stale-artifact drift and accidental row-width changes before any
    renderer can consume the candidate.
    """
    expected = [[" "] * columns for _ in range(rows)]
    seen: set[tuple[int, int]] = set()
    for record in cell_records:
        row = int(record["row"])
        column = int(record["column"])
        key = (row, column)
        if not (0 <= row < rows and 0 <= column < columns):
            raise ValueError(f"cell record outside calibrated grid: {key}")
        if key in seen:
            raise ValueError(f"duplicate cell record: {key}")
        seen.add(key)
        glyph = str(record["glyph"])
        if len(glyph) != 1:
            raise ValueError(f"cell {key} has non-single-column glyph {glyph!r}")
        expected[row][column] = glyph
    if len(seen) != rows * columns:
        raise ValueError(f"expected {rows * columns} cell records, got {len(seen)}")
    evidence_transcript = "\n".join("".join(row) for row in expected) + "\n"
    if transcript != evidence_transcript:
        raise ValueError("machine transcript disagrees with row/cell evidence")
    line_lengths = [len(line) for line in transcript.splitlines()]
    if line_lengths != [columns] * rows:
        raise ValueError(f"transcript row widths {line_lengths!r} do not match {rows}x{columns}")
    return hashlib.sha256(transcript.encode("utf-8")).hexdigest()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path)
    parser.add_argument("calibration", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    source, calibration_path, output = args.source.resolve(), args.calibration.resolve(), args.output.resolve()
    calibration = json.loads(calibration_path.read_text(encoding="utf-8"))
    if sha256(source) != calibration["source_sha256"]:
        raise SystemExit("source hash differs from calibration; refusing row decode")
    if output.exists():
        raise SystemExit(f"refusing to overwrite immutable decoder output: {output}")
    output.mkdir(parents=True)
    cells = segment(source, calibration)
    templates = build_templates(cells)
    structural_conflicts = structural_conflict_count(cells)
    columns, rows = int(calibration["grid"]["columns"]), int(calibration["grid"]["rows"])
    decoded_rows: list[str] = []
    cell_records: list[dict[str, object]] = []
    row_records: list[dict[str, object]] = []
    decoded_results: list[tuple[list[str], list[float], dict[str, object]]] = []
    for row in range(rows):
        row_cells = cells[row * columns : (row + 1) * columns]
        decoded, confidences, row_meta = decode_row(row_cells, templates)
        decoded_results.append((decoded, confidences, row_meta))
    flat_decoded = [glyph for decoded, _, _ in decoded_results for glyph in decoded]
    flat_confidences = [confidence for _, confidences, _ in decoded_results for confidence in confidences]
    original_flat_decoded = list(flat_decoded)
    flat_decoded = apply_repeated_topology_consensus(cells, flat_decoded, flat_confidences, columns)
    for index, (before, after) in enumerate(zip(original_flat_decoded, flat_decoded)):
        if before == UNKNOWN and after != UNKNOWN:
            flat_confidences[index] = 0.86
    forced_blank_conflicts = forced_blank_conflict_count(cells, flat_decoded)
    cursor = 0
    for row, (decoded, confidences, row_meta) in enumerate(decoded_results):
        decoded = flat_decoded[cursor : cursor + columns]
        confidences = flat_confidences[cursor : cursor + columns]
        cursor += columns
        decoded_rows.append("".join(decoded))
        row_records.append({"row": row, **row_meta})
        row_cells = cells[row * columns : (row + 1) * columns]
        for cell, glyph, confidence in zip(row_cells, decoded, confidences):
            cell_records.append(
                {
                    "row": cell.row,
                    "column": cell.column,
                    "glyph": glyph,
                    "seed": cell.seed,
                    "forced_blank": cell.forced_blank,
                    "ownership_reason": cell.ownership_reason,
                    "confidence": confidence,
                    "topology": cell.topology,
                    "component_ids": list(cell.component_ids),
                    "window_shape": list(cell.window.shape),
                    "leave_one_out_template_count": sum(1 for item in templates.get(glyph, []) if (item.row, item.column) != (cell.row, cell.column)),
                }
            )
    # This legacy decoder is a fixed-cell proposal adapter.  It may calculate
    # a hypothetical sequence for diagnostics, but it cannot write candidate
    # TXT, accepted TXT, or a canonical manifest.
    transcript = "\n".join(decoded_rows) + "\n"
    proposal_sequence_sha256 = validate_transcript_binding(transcript, cell_records, columns, rows)
    template_manifest = {
        "decoder": DECODER_VERSION,
        "source_sha256": sha256(source),
        "calibration_sha256": sha256(calibration_path),
        "templates": {
            glyph: [
                {
                    "row": item.row,
                    "column": item.column,
                    "shape": list(item.mask.shape),
                    "window_shape": list(item.window_normalized.shape),
                }
                for item in items
            ]
            for glyph, items in sorted(templates.items())
        },
        "leave_one_out": True,
        "window_radius_columns": 1,
    }
    (output / "template-bank.json").write_text(json.dumps(template_manifest, indent=2) + "\n", encoding="utf-8")
    (output / "row-decoding.json").write_text(
        json.dumps(
            {
                "rows": row_records,
                "cells": cell_records,
                "proposal_sequence_sha256": proposal_sequence_sha256,
                "proposal_line_lengths": [len(row) for row in decoded_rows],
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    unknown_cells = sum(glyph == UNKNOWN for row in decoded_rows for glyph in row)
    low_confidence_cells = sum(item["confidence"] < 0.85 and item["glyph"] != " " for item in cell_records)
    proposal_set = {
        "format": "lateletter-fixed-cell-proposal-v1",
        "adapter": "row-joint-decoder",
        "adapter_version": DECODER_VERSION,
        "attempt": output.name,
        "source_png": os.path.relpath(source, output),
        "source_sha256": sha256(source),
        "calibration": {
            "path": os.path.relpath(calibration_path, output),
            "sha256": sha256(calibration_path),
        },
        "proposal_sequence_sha256": proposal_sequence_sha256,
        "cell_count": len(cell_records),
        "proposal_line_lengths": [len(row) for row in decoded_rows],
        "recognition": {
            "beam_width": BEAM_WIDTH,
            "minimum_margin": MIN_MARGIN,
            "window_radius_columns": 1,
            "leave_one_out_templates": True,
            "recognition_unit": "grapheme_cluster",
            "unicode_normalization": "NFC",
            "unicode_data_version": unicodedata.unidata_version,
            "non_ascii_policy": "defer_to_unicode_run_decoder",
        },
        "grid": calibration["grid"],
        "proposal_status": "rejected"
        if unknown_cells or low_confidence_cells or structural_conflicts or forced_blank_conflicts
        else "proposals_available",
        "unknown_cells": unknown_cells,
        "low_confidence_cells": low_confidence_cells,
        "structural_conflicts": structural_conflicts,
        "forced_blank_conflicts": forced_blank_conflicts,
        "artifacts": {
            "templates": "template-bank.json",
            "evidence": "row-decoding.json",
            "proposal_set": "proposal-set.json",
        },
        "authority": {
            "writes_candidate_txt": False,
            "writes_accepted_txt": False,
            "writes_canonical_manifest": False,
        },
    }
    (output / "proposal-set.json").write_text(json.dumps(proposal_set, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"status": proposal_set["proposal_status"], "unknown_cells": unknown_cells, "low_confidence_cells": low_confidence_cells, "structural_conflicts": structural_conflicts, "forced_blank_conflicts": forced_blank_conflicts, "templates": {key: len(value) for key, value in templates.items()}}))


if __name__ == "__main__":
    main()
